#!/usr/bin/env python3
"""ElevenLabs Agents adapter for Full-Duplex-Bench v1.0 / v1.5.

Mirrors run_inference.py (AssemblyAI): for each numeric sample folder with an
input wav, stream the audio through an ElevenLabs Agents WebSocket session at
real-time pace and write the agent's response audio as output.wav, time-aligned
to the input (FDB convention: zero-padded, truncated to input duration).

Playback simulation matches the AssemblyAI adapter: agent audio chunks are laid
out contiguously from the arrival offset of each burst (monotonic cursor). On an
`interruption` event, the cursor is pulled back to the current wall-clock
offset — modelling a client that stops playback when told to.

Usage:
    export ELEVENLABS_API_KEY=...
    python3 run_inference_elevenlabs.py <subset_dir> --agent-id <id> --concurrency 3
"""
import argparse
import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf
import websockets

TARGET_SR = 16_000
PER_SAMPLE_TIMEOUT = 90.0


def load_pcm16(path):
    audio, sr = sf.read(path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != TARGET_SR:
        new_len = int(len(audio) * TARGET_SR / sr)
        idx = np.linspace(0, len(audio) - 1, new_len)
        audio = np.interp(idx, np.arange(len(audio)), audio).astype(np.float32)
    return np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)


async def get_signed_url(api_key, agent_id):
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
            params={"agent_id": agent_id},
            headers={"xi-api-key": api_key},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["signed_url"]


async def run_one(api_key, agent_id, input_wav, output_wav, transcript_path):
    pcm16 = load_pcm16(input_wav)
    chunk = TARGET_SR // 10  # 100 ms
    silence_b64 = base64.b64encode(np.zeros(chunk, dtype=np.int16).tobytes()).decode()

    url = await get_signed_url(api_key, agent_id)
    agent_chunks = []   # (arrival_offset_s, np.int16 samples)
    agent_text = []
    interrupts = []     # wall-clock offsets of interruption events
    start_t = None

    async with websockets.connect(url, open_timeout=15, max_size=2**24) as ws:
        await ws.send(json.dumps({
            "type": "conversation_initiation_client_data",
        }))

        async def receiver():
            async for raw in ws:
                ev = json.loads(raw)
                t = ev.get("type")
                if t == "ping":
                    await ws.send(json.dumps({
                        "type": "pong",
                        "event_id": ev.get("ping_event", ev).get("event_id")
                        if isinstance(ev.get("ping_event"), dict) else ev.get("event_id"),
                    }))
                elif t == "audio":
                    if start_t is None:
                        continue
                    data = ev.get("audio_event", ev).get("audio_base_64") or ev.get("audio_base_64")
                    if not data:
                        continue
                    pcm = np.frombuffer(base64.b64decode(data), dtype=np.int16)
                    agent_chunks.append((time.monotonic() - start_t, pcm))
                elif t == "agent_response":
                    if start_t is None:
                        continue
                    text = (ev.get("agent_response_event", ev).get("agent_response")
                            or ev.get("agent_response") or "")
                    if isinstance(text, str) and text.strip():
                        agent_text.append((round(time.monotonic() - start_t, 3), text.strip()))
                elif t == "interruption":
                    if start_t is not None:
                        interrupts.append(time.monotonic() - start_t)

        recv_task = asyncio.create_task(receiver())
        try:
            start_t = time.monotonic()
            for i in range(0, len(pcm16), chunk):
                c = pcm16[i:i + chunk]
                if len(c) < chunk:
                    c = np.concatenate([c, np.zeros(chunk - len(c), dtype=np.int16)])
                await ws.send(json.dumps(
                    {"user_audio_chunk": base64.b64encode(c.tobytes()).decode()}))
                await asyncio.sleep(0.1)
            for _ in range(15):
                await ws.send(json.dumps({"user_audio_chunk": silence_b64}))
                await asyncio.sleep(0.1)
            await asyncio.sleep(2.0)  # tail grace for in-flight reply text
        finally:
            recv_task.cancel()
            try:
                await recv_task
            except (asyncio.CancelledError, Exception):
                pass

    # Lay out agent audio time-aligned to input (playback simulation).
    output = np.zeros(len(pcm16), dtype=np.int16)
    events = sorted(
        [("audio", off, pcm) for off, pcm in agent_chunks]
        + [("interrupt", off, None) for off in interrupts],
        key=lambda e: e[1],
    )
    write_pos = 0
    for kind, off, pcm in events:
        pos = int(off * TARGET_SR)
        if kind == "interrupt":
            write_pos = min(write_pos, pos)  # stop playback at interrupt time
            continue
        write_pos = max(write_pos, pos)
        if write_pos >= len(output):
            continue
        end = min(write_pos + len(pcm), len(output))
        output[write_pos:end] = pcm[:end - write_pos]
        write_pos = end
    sf.write(output_wav, output, TARGET_SR, subtype="PCM_16")
    if agent_text:
        transcript_path.write_text(json.dumps(
            [{"offset_s": o, "text": t} for o, t in agent_text], indent=2))


async def main_async(args):
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        sys.exit("ELEVENLABS_API_KEY is not set")
    dataset_dir = Path(args.dataset)
    folders = sorted(
        (d for d in dataset_dir.iterdir() if d.is_dir() and d.name.isdigit()),
        key=lambda d: int(d.name),
    )
    if not folders:
        sys.exit(f"No numeric sample folders in {dataset_dir}")

    sem = asyncio.Semaphore(args.concurrency)
    counts = {"ok": 0, "skip": 0, "err": 0}
    t0 = time.monotonic()

    async def process(folder):
        in_wav = folder / args.input_name
        out_wav = folder / args.output_name
        tx = folder / args.transcript_name
        if not in_wav.exists():
            counts["skip"] += 1
            return f"SKIP {folder.name}: no {args.input_name}"
        if out_wav.exists() and not args.overwrite:
            counts["skip"] += 1
            return f"SKIP {folder.name}: exists"
        try:
            info = sf.info(str(in_wav))
            sample_timeout = max(PER_SAMPLE_TIMEOUT, info.frames / info.samplerate + 30)
        except Exception:
            sample_timeout = PER_SAMPLE_TIMEOUT
        async with sem:
            try:
                await asyncio.wait_for(
                    run_one(api_key, args.agent_id, in_wav, out_wav, tx),
                    timeout=sample_timeout)
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
        print(f"[{done}/{len(folders)}] {msg}", flush=True)
    print(f"\nFinished {len(folders)} in {time.monotonic()-t0:.1f}s "
          f"(ok={counts['ok']}, skip={counts['skip']}, err={counts['err']})")
    return 0 if counts["err"] == 0 else 1


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dataset")
    p.add_argument("--agent-id", required=True)
    p.add_argument("--concurrency", type=int, default=3)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--input-name", default="input.wav")
    p.add_argument("--output-name", default="output.wav")
    p.add_argument("--transcript-name", default="agent_transcript.json")
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
