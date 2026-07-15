#!/usr/bin/env python3
"""
AssemblyAI Voice Agent API adapter for Full-Duplex-Bench v1.0 / v1.5.

For each sample folder under <dataset_dir> with an `input.wav`, stream the
audio through `wss://agents.assemblyai.com/v1/ws` at real-time pace and
write the agent's response audio as `output.wav`, time-aligned to the input
(leading silence pads until the first agent audio chunk arrives; output is
truncated to match input duration — the FDB convention).

Captures any `transcript.agent` / `reply.text` events into
`agent_transcript.json` alongside the wav file.

Usage:
    pip install websockets soundfile numpy
    export ASSEMBLYAI_API_KEY=...
    python3 run_inference.py /path/to/dataset/v1.5/user_interruption \\
        --concurrency 5
"""
import argparse
import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import websockets

URL = "wss://agents.us.assemblyai.com/v1/ws"
TARGET_SR = 24_000
SYSTEM_PROMPT = (
    "You are a helpful voice assistant. Keep your responses brief and "
    "conversational — usually one or two sentences. Speak naturally."
)
PER_SAMPLE_TIMEOUT = 90.0
TURN_DETECTION = None  # set from --turn-detection; merged into session.input


def load_pcm16(path):
    audio, sr = sf.read(path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != TARGET_SR:
        new_len = int(len(audio) * TARGET_SR / sr)
        idx = np.linspace(0, len(audio) - 1, new_len)
        audio = np.interp(idx, np.arange(len(audio)), audio).astype(np.float32)
    pcm16 = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
    return pcm16, TARGET_SR


def b64_pcm16(samples):
    return base64.b64encode(samples.tobytes()).decode("ascii")


async def run_one(api_key, input_wav, output_wav, transcript_path):
    pcm16, sr = load_pcm16(input_wav)
    chunk_samples = sr * 100 // 1000
    chunk_period = 0.1
    silence_b64 = b64_pcm16(np.zeros(chunk_samples, dtype=np.int16))
    headers = {"Authorization": f"Bearer {api_key}"}

    agent_chunks = []
    agent_text = []
    start_t = None
    reply_done = asyncio.Event()
    session_ready = asyncio.Event()
    first_greeting_done = asyncio.Event()
    session_ended = asyncio.Event()

    async with websockets.connect(URL, extra_headers=headers, open_timeout=15) as ws:
        input_cfg = {"type": "audio"}
        if TURN_DETECTION:
            input_cfg["turn_detection"] = TURN_DETECTION
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "system_prompt": SYSTEM_PROMPT,
                "input": input_cfg,
                "output": {"type": "audio", "voice": "alba"},
            },
        }))

        async def receiver():
            nonlocal start_t
            async for raw in ws:
                event = json.loads(raw)
                if event.get("type") is None and event.get("code"):
                    raise RuntimeError(f"{event['code']}: {event.get('message', '')}")
                t = event.get("type")
                if t == "session.ready":
                    session_ready.set()
                elif t == "reply.audio":
                    if start_t is None:
                        continue
                    offset = time.monotonic() - start_t
                    pcm = np.frombuffer(base64.b64decode(event["data"]), dtype=np.int16)
                    agent_chunks.append((offset, pcm))
                elif t in ("reply.text", "transcript.agent"):
                    if start_t is None:
                        continue
                    text = event.get("text") or event.get("delta") or ""
                    if text:
                        agent_text.append((round(time.monotonic() - start_t, 3), text))
                elif t == "reply.done":
                    if start_t is None:
                        first_greeting_done.set()
                    else:
                        reply_done.set()
                elif t == "session.ended":
                    session_ended.set()

        recv_task = asyncio.create_task(receiver())
        try:
            await asyncio.wait_for(session_ready.wait(), timeout=15)
            try:
                await asyncio.wait_for(first_greeting_done.wait(), timeout=3)
            except asyncio.TimeoutError:
                pass

            start_t = time.monotonic()
            for i in range(0, len(pcm16), chunk_samples):
                chunk = pcm16[i:i + chunk_samples]
                if len(chunk) < chunk_samples:
                    chunk = np.concatenate([chunk, np.zeros(chunk_samples - len(chunk), dtype=np.int16)])
                await ws.send(json.dumps({"type": "input.audio", "audio": b64_pcm16(chunk)}))
                await asyncio.sleep(chunk_period)
            for _ in range(15):
                await ws.send(json.dumps({"type": "input.audio", "audio": silence_b64}))
                await asyncio.sleep(chunk_period)
            try:
                await asyncio.wait_for(reply_done.wait(), timeout=10)
            except asyncio.TimeoutError:
                pass
            # End the session explicitly: closing the socket without
            # session.end leaves it resumable (and billable) for 30s,
            # which counts against the per-key concurrent-session limit.
            try:
                await ws.send(json.dumps({"type": "session.end"}))
                await asyncio.wait_for(session_ended.wait(), timeout=3)
            except Exception:
                pass
        finally:
            recv_task.cancel()
            try:
                await recv_task
            except (asyncio.CancelledError, Exception):
                pass

    output = np.zeros(len(pcm16), dtype=np.int16)
    if agent_chunks:
        first_offset_s, _ = agent_chunks[0]
        write_pos = max(0, int(first_offset_s * sr))
        for _, samples in agent_chunks:
            if write_pos >= len(output):
                break
            end = min(write_pos + len(samples), len(output))
            output[write_pos:end] = samples[:end - write_pos]
            write_pos = end
    sf.write(output_wav, output, sr, subtype="PCM_16")
    if agent_text:
        transcript_path.write_text(json.dumps(
            [{"offset_s": o, "text": t} for o, t in agent_text], indent=2))


async def main_async(args):
    api_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not api_key:
        sys.exit("ASSEMBLYAI_API_KEY is not set")
    dataset_dir = Path(args.dataset)
    if not dataset_dir.is_dir():
        sys.exit(f"Not a directory: {dataset_dir}")

    input_name = args.input_name
    output_name = args.output_name
    transcript_name = args.transcript_name

    folders = sorted(
        (d for d in dataset_dir.iterdir() if d.is_dir() and d.name.isdigit()),
        key=lambda d: int(d.name),
    )
    if not folders:
        sys.exit(f"No numeric sample folders in {dataset_dir}")

    sem = asyncio.Semaphore(args.concurrency)
    counts = {"ok": 0, "skip": 0, "err": 0}
    total = len(folders)
    t0 = time.monotonic()

    async def process(folder):
        in_wav = folder / input_name
        out_wav = folder / output_name
        tx = folder / transcript_name
        if not in_wav.exists():
            counts["skip"] += 1
            return f"SKIP {folder.name}: no {input_name}"
        if out_wav.exists() and not args.overwrite:
            counts["skip"] += 1
            return f"SKIP {folder.name}: {output_name} already exists"
        # timeout must cover real-time streaming of the whole input
        # (some CANDOR samples exceed the 90s floor, e.g. 94s)
        try:
            info = sf.info(str(in_wav))
            sample_timeout = max(PER_SAMPLE_TIMEOUT, info.frames / info.samplerate + 30)
        except Exception:
            sample_timeout = PER_SAMPLE_TIMEOUT
        async with sem:
            try:
                await asyncio.wait_for(
                    run_one(api_key, in_wav, out_wav, tx),
                    timeout=sample_timeout,
                )
                counts["ok"] += 1
                return f"OK   {folder.name}"
            except Exception as e:
                counts["err"] += 1
                (folder / "error.log").write_text(f"{type(e).__name__}: {e}\n")
                return f"ERR  {folder.name}: {type(e).__name__}: {e}"

    tasks = [asyncio.create_task(process(f)) for f in folders]
    done = 0
    for coro in asyncio.as_completed(tasks):
        msg = await coro
        done += 1
        print(f"[{done}/{total}] {msg}", flush=True)

    elapsed = time.monotonic() - t0
    print(f"\nFinished {total} samples in {elapsed:.1f}s "
          f"(ok={counts['ok']}, skip={counts['skip']}, err={counts['err']})")
    return 0 if counts["err"] == 0 else 1


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dataset", help="Path to a subset folder (e.g. v1.5/user_interruption)")
    p.add_argument("--concurrency", type=int, default=5)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--input-name", default="input.wav",
                   help="Input WAV filename (default: input.wav). Use clean_input.wav for FDB v1.5 paper-faithful second pass.")
    p.add_argument("--output-name", default="output.wav",
                   help="Output WAV filename (default: output.wav). Use clean_output.wav for the second pass.")
    p.add_argument("--transcript-name", default="agent_transcript.json",
                   help="Transcript JSON filename (default: agent_transcript.json). Use clean_agent_transcript.json for the second pass.")
    p.add_argument("--turn-detection", default=None,
                   help='JSON for session.input.turn_detection, e.g. \'{"min_silence": 2000}\'')
    args = p.parse_args()
    if args.turn_detection:
        global TURN_DETECTION
        TURN_DETECTION = json.loads(args.turn_detection)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
