#!/usr/bin/env python3
"""GPT-4o classifier with NO scenario priming — only the bare paper definitions.

This is the de-biased version of fdb_classify.py. Compare the resulting
aggregate to the 82.7 from the primed version to see how much scenario hints
inflated the score.
"""
import asyncio, json, os, sys
from pathlib import Path
import httpx

API_KEY = os.environ["OPENAI_API_KEY"]
MODEL = "gpt-4o-2024-08-06"
CONCURRENCY = 4
MAX_RETRIES = 4

# Verbatim from FDB paper §2.3.1
SYSTEM = """You are an evaluator labelling how a spoken-dialogue model behaves when its speech overlaps with user speech.

Given the user's overlap content and the model's response that followed the overlap, classify the response into EXACTLY ONE of these four categories. Definitions (verbatim from the Full-Duplex-Bench v1.5 paper §2.3.1):

RESPOND — The model meaningfully addresses the overlap's content (answers, clarifies, or reacts to what the overlap said).
RESUME — The model ignores the overlap and continues or completes the pre-overlap task / answer that was already in progress.
UNCERTAIN — The model signals uncertainty or difficulty hearing / missing info ("I didn't catch that…", "Could you repeat?") without giving a clear, content-specific answer.
UNKNOWN — The model output is semantically off-target or low-information: does not clearly resume, respond, or express uncertainty (unrelated filler, templated noise, or no speech at all after the overlap).

Output STRICTLY a single line of JSON with one key:
{"behaviour": "RESPOND" or "RESUME" or "UNCERTAIN" or "UNKNOWN"}

No reasoning, no preamble, no trailing text."""

OVERLAP_TEXT_FIELDS = {
    "user_interruption": "current_turn_text",
    "user_backchannel":  "backchannel_text",
    "talking_to_other":  "current_turn_text",
    "background_speech": "background_text",
}


def load_response_text(folder: Path) -> str:
    # Prefer Whisper ASR of output.wav: it covers exactly the audible response
    # window. Native transcript.agent events can miss the post-overlap reply
    # (it arrives after the capture window), which misclassifies RESPOND
    # samples as RESUME/UNKNOWN.
    oj = folder / "output.json"
    if oj.exists():
        try:
            data = json.loads(oj.read_text())
            text = (data.get("text") or "").strip()
            if text:
                return text
        except Exception:
            pass
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


async def classify_one(client, scenario, folder):
    md = json.loads((folder / "metadata.json").read_text())
    field = OVERLAP_TEXT_FIELDS[scenario]
    overlap_text = md.get(field, md.get("current_turn_text", ""))
    context = md.get("context_text", "")
    response = load_response_text(folder)

    user_msg = f"""User's original utterance (before overlap): "{context}"
Overlap content (during model's response): "{overlap_text}"
Model speech that followed the overlap: "{response or '<no speech captured>'}"

Classify into RESPOND, RESUME, UNCERTAIN, or UNKNOWN."""

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
    (folder / "behaviour_neutral.json").write_text(json.dumps({"behaviour": cat, "response_text": response[:500]}, indent=2))
    return cat


async def with_retry(client, scenario, folder):
    backoff = 1.0
    for attempt in range(MAX_RETRIES):
        try:
            return await classify_one(client, scenario, folder), None
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                return None, str(e)
            await asyncio.sleep(backoff)
            backoff *= 2


async def main():
    base = Path("/Users/danielince/Downloads/llm-gateway-streaming/fdb-dataset/Full-Duplex-Bench-Data")
    sem = asyncio.Semaphore(CONCURRENCY)
    DESIRED = {"user_interruption": "RESPOND", "user_backchannel": "RESUME",
               "talking_to_other": "RESUME", "background_speech": "RESUME"}

    async with httpx.AsyncClient() as client:
        async def work(scenario, folder):
            async with sem:
                return scenario, folder.name, *(await with_retry(client, scenario, folder))

        all_tasks = []
        for scenario in DESIRED:
            for d in sorted((base / "v1.5" / scenario).iterdir()):
                if d.is_dir() and d.name.isdigit() and not (d / "behaviour_neutral.json").exists():
                    all_tasks.append(work(scenario, d))
        print(f"To classify: {len(all_tasks)}")
        done = 0
        errors = 0
        for coro in asyncio.as_completed(all_tasks):
            scenario, name, cat, err = await coro
            done += 1
            if err:
                errors += 1
            if done % 50 == 0:
                print(f"  [{done}/{len(all_tasks)}]  errors: {errors}")

    # Aggregate
    score_sum = 0.0
    print("\nNeutral-prompt results:")
    for scenario, desired in DESIRED.items():
        cats = {"RESPOND": 0, "RESUME": 0, "UNCERTAIN": 0, "UNKNOWN": 0}
        n = 0
        for d in sorted((base / "v1.5" / scenario).iterdir()):
            bj = d / "behaviour_neutral.json"
            if not bj.exists():
                continue
            n += 1
            cat = json.loads(bj.read_text())["behaviour"]
            cats[cat] = cats.get(cat, 0) + 1
        rate = cats.get(desired, 0) / n if n else 0
        score_sum += rate
        print(f"  {scenario:25s} {desired:10s} {rate:.3f}  ({cats.get(desired,0)}/{n})  | counts: {cats}")
    avg = score_sum / 4
    print(f"\nNeutral FDB v1.5 Average × 100 = {avg * 100:.1f}")


if __name__ == "__main__":
    asyncio.run(main())
