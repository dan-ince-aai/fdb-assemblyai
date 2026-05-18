#!/usr/bin/env python3
"""GPT-4o behavior classifier for FDB v1.5.

This is a simplified version of the FDB paper's GPT-4o classifier (which
requires output_clean — the model's reply to clean_input — that we don't
have without a second inference pass). Instead we feed:

  - scenario name + expected behavior
  - the context turn text (metadata.context_text)
  - the overlap content text (metadata.{current_turn_text|backchannel_text|...})
  - the agent's actual response text (concatenated agent_transcript.json)

GPT-4o classifies into RESPOND/RESUME/UNCERTAIN/UNKNOWN per the FDB §2.3.1
definitions verbatim.

Run:
  export OPENAI_API_KEY=sk-...
  python3 fdb_classify.py /path/to/Full-Duplex-Bench-Data
"""
import asyncio, json, os, sys
from pathlib import Path
import httpx

API_KEY = os.environ["OPENAI_API_KEY"]
MODEL = "gpt-4o-2024-08-06"
CONCURRENCY = 8

SCENARIO_DESCRIPTIONS = {
    "user_interruption": ("User Interruption", "RESPOND",
        "User barges in with a new request/topic mid-utterance. The model should yield and address the new content."),
    "user_backchannel": ("User Backchannel", "RESUME",
        "Listener emits a short affirmation (e.g., 'uh-huh', 'yeah', 'mm-hmm') to signal engagement. The model should NOT take the turn — it should continue its prior utterance."),
    "talking_to_other": ("User Talking to Others", "RESUME",
        "User says something to another person (off-axis, processed to sound far-field). The model is NOT the addressee — it should continue its prior utterance."),
    "background_speech": ("Background Speech", "RESUME",
        "Far-field third-party speech on an unrelated topic, with low-pass filtering and echo. The model should ignore it and continue its prior utterance."),
}

OVERLAP_TEXT_FIELDS = {
    "user_interruption": "current_turn_text",
    "user_backchannel":  "backchannel_text",
    "talking_to_other":  "current_turn_text",
    "background_speech": "background_text",
}

SYSTEM = """You are an expert evaluator scoring full-duplex spoken-dialogue agents.

Given:
  - the scenario (one of: User Interruption, User Backchannel, User Talking to Others, Background Speech)
  - the user's prior context (what the user originally asked)
  - the overlap content (the user/other speech that overlapped the model's response)
  - the model's actual response text (transcribed)

Classify the model's post-overlap behavior into exactly ONE of:

RESPOND — the model meaningfully addresses the content of the overlap (answers, clarifies, or reacts to what the overlap said).
RESUME — the model ignores the overlap and continues or completes the pre-overlap task/answer.
UNCERTAIN — the model signals uncertainty or difficulty hearing ("I didn't catch that…", "Could you repeat?") without giving a content-specific answer.
UNKNOWN — the model output is semantically off-target, low-information, generic filler, or the model produces no speech after the overlap.

Output STRICTLY a single line of JSON with one key:
{"behaviour": "RESPOND" or "RESUME" or "UNCERTAIN" or "UNKNOWN"}

No other text."""


def load_response_text(folder: Path) -> str:
    f = folder / "agent_transcript.json"
    if not f.exists():
        return ""
    try:
        data = json.loads(f.read_text())
        if isinstance(data, list):
            return " ".join(item.get("text", "") for item in data).strip()
        return ""
    except Exception:
        return ""


async def classify_one(client: httpx.AsyncClient, scenario: str, folder: Path) -> tuple[str, str]:
    md = json.loads((folder / "metadata.json").read_text())
    name, desired, blurb = SCENARIO_DESCRIPTIONS[scenario]
    overlap_field = OVERLAP_TEXT_FIELDS[scenario]
    overlap_text = md.get(overlap_field, md.get("current_turn_text", ""))
    context = md.get("context_text", "")
    response = load_response_text(folder)

    user_msg = f"""Scenario: {name}
Scenario notes: {blurb}

User context turn: "{context}"
Overlap content: "{overlap_text}"
Model response after overlap: "{response or '<no transcript captured>'}"

Classify the response."""

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0,
        "seed": 0,
        "response_format": {"type": "json_object"},
    }
    r = await client.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json=payload, timeout=60.0,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    cat = parsed.get("behaviour", "UNKNOWN").upper()
    if cat not in {"RESPOND", "RESUME", "UNCERTAIN", "UNKNOWN"}:
        cat = "UNKNOWN"
    (folder / "behaviour.json").write_text(json.dumps({"behaviour": cat, "response_text": response[:500]}, indent=2))
    return cat, ""


async def run_subset(client: httpx.AsyncClient, sem: asyncio.Semaphore, base: Path, scenario: str):
    root = base / "v1.5" / scenario
    folders = sorted([d for d in root.iterdir() if d.is_dir() and d.name.isdigit()])
    cats = {"RESPOND": 0, "RESUME": 0, "UNCERTAIN": 0, "UNKNOWN": 0}
    errors = []

    async def work(d):
        async with sem:
            try:
                cat, _ = await classify_one(client, scenario, d)
                cats[cat] = cats.get(cat, 0) + 1
                return d.name, cat
            except Exception as e:
                errors.append((d.name, str(e)))
                return d.name, "ERROR"

    tasks = [work(d) for d in folders]
    done = 0
    for coro in asyncio.as_completed(tasks):
        await coro
        done += 1
        if done % 25 == 0:
            print(f"  [{scenario}] {done}/{len(folders)} done")

    n = sum(cats.values())
    print(f"\n=== {scenario}  ({n} samples) ===")
    desired = SCENARIO_DESCRIPTIONS[scenario][1]
    for k, v in cats.items():
        mark = " ←" if k == desired else ""
        print(f"  {k:10s}: {v:4d} ({v/n:.1%}){mark}" if n else f"  {k}: 0")
    if errors:
        print(f"  errors: {len(errors)} samples")
    return cats, errors


async def main():
    base = Path(sys.argv[1])
    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient() as client:
        results = {}
        for scenario in ["user_interruption", "user_backchannel", "talking_to_other", "background_speech"]:
            cats, errs = await run_subset(client, sem, base, scenario)
            results[scenario] = cats

    # Aggregate
    total_score = 0.0
    print("\n" + "=" * 50)
    print("FDB V1.5 FINAL — desired-behavior rates")
    print("=" * 50)
    for scenario, cats in results.items():
        n = sum(cats.values())
        desired = SCENARIO_DESCRIPTIONS[scenario][1]
        rate = cats.get(desired, 0) / n if n else 0
        total_score += rate
        print(f"  {scenario:25s} {desired:10s} {rate:.3f}  ({cats.get(desired,0)}/{n})")
    avg = total_score / len(results)
    print(f"\n  FDB v1.5 Average × 100 = {avg * 100:.1f}")

    (Path("/tmp") / "fdb_classify_results.json").write_text(json.dumps({
        "results": {k: v for k, v in results.items()},
        "aggregate": avg * 100,
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
