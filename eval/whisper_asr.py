#!/usr/bin/env python3
"""ASR every {input,output,clean_input,clean_output}.wav that doesn't already
have a corresponding transcript JSON.

Uses OpenAI's Whisper API. With --word-timestamps, returns word-level timing
that matches FDB's NeMo Parakeet output format (so it can be fed to the
paper's evaluate.py --task behavior verbatim).

Default produces the simpler {offset_s, text} format used by our adapter.

Usage:
    pip install httpx
    export OPENAI_API_KEY=sk-...
    python3 whisper_asr.py /path/to/Full-Duplex-Bench-Data \\
        [--word-timestamps] [--subset v1.5/user_interruption ...]
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

API_KEY = os.environ["OPENAI_API_KEY"]
CONCURRENCY = 5

# (wav_filename, transcript_filename)
AUDIO_PAIRS = [
    ("output.wav",         "agent_transcript.json"),
    ("clean_output.wav",   "clean_agent_transcript.json"),
    ("input.wav",          "input.json"),        # only if missing — FDB ships these
    ("clean_input.wav",    "clean_input.json"),  # same
]


async def transcribe(client, wav, word_timestamps: bool):
    with open(wav, "rb") as f:
        files = {"file": (wav.name, f, "audio/wav")}
        if word_timestamps:
            data = {
                "model": "whisper-1",
                "response_format": "verbose_json",
                "timestamp_granularities[]": "word",
            }
        else:
            data = {"model": "gpt-4o-mini-transcribe", "response_format": "text"}
        r = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            files=files, data=data, timeout=120.0,
        )
    r.raise_for_status()
    return r.text.strip(), r.json() if word_timestamps else None


def to_word_chunks(verbose_json: dict) -> dict:
    """Convert Whisper verbose_json word data to FDB's chunks format."""
    words = verbose_json.get("words", [])
    return {
        "text": verbose_json.get("text", "").strip(),
        "chunks": [
            {"text": w["word"], "timestamp": [w["start"], w["end"]]}
            for w in words
        ],
    }


async def process(sem, client, folder: Path, wav_name: str, tx_name: str, word_timestamps: bool):
    wav = folder / wav_name
    tx = folder / tx_name
    if tx.exists() or not wav.exists():
        return None
    async with sem:
        try:
            text, vj = await transcribe(client, wav, word_timestamps)
            if word_timestamps and vj is not None:
                tx.write_text(json.dumps(to_word_chunks(vj), indent=2))
            else:
                tx.write_text(json.dumps([{"offset_s": 0.0, "text": text}], indent=2))
            return f"OK   {folder.parent.name}/{folder.name}/{wav_name}"
        except Exception as e:
            return f"ERR  {folder.parent.name}/{folder.name}/{wav_name}: {type(e).__name__}: {e}"


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("dataset_root", help="Path to Full-Duplex-Bench-Data")
    p.add_argument("--subset", action="append", default=None,
                   help="Repeatable. e.g. v1.5/user_interruption. Default: all v1.5 subsets.")
    p.add_argument("--word-timestamps", action="store_true",
                   help="Use whisper-1 with word-level timestamps (slower, paper-format)")
    args = p.parse_args()

    base = Path(args.dataset_root)
    subsets = args.subset or [
        "v1.5/user_interruption",
        "v1.5/user_backchannel",
        "v1.5/talking_to_other",
        "v1.5/background_speech",
    ]

    todo = []
    for sub in subsets:
        root = base / sub
        if not root.is_dir():
            print(f"  warning: {sub} not found, skipping")
            continue
        for folder in sorted(root.iterdir()):
            if not (folder.is_dir() and folder.name.isdigit()):
                continue
            for wav_name, tx_name in AUDIO_PAIRS:
                if (folder / wav_name).exists() and not (folder / tx_name).exists():
                    todo.append((folder, wav_name, tx_name))

    print(f"To ASR: {len(todo)} files (word-level={args.word_timestamps})")

    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient() as client:
        tasks = [process(sem, client, f, w, t, args.word_timestamps) for f, w, t in todo]
        done = 0
        for coro in asyncio.as_completed(tasks):
            msg = await coro
            done += 1
            if msg is None:
                continue
            if done % 50 == 0 or msg.startswith("ERR"):
                print(f"[{done}/{len(todo)}] {msg}")
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
