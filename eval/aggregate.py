#!/usr/bin/env python3
"""Aggregate per-folder behaviour.json files into the final FDB v1.5 score."""
import json, sys
from pathlib import Path

DESIRED = {
    "user_interruption":  "RESPOND",
    "user_backchannel":   "RESUME",
    "talking_to_other":   "RESUME",
    "background_speech":  "RESUME",
}

base = Path(sys.argv[1])
results = {}
score_sum = 0.0
for sub in ["user_interruption", "user_backchannel", "talking_to_other", "background_speech"]:
    root = base / "v1.5" / sub
    cats = {"RESPOND": 0, "RESUME": 0, "UNCERTAIN": 0, "UNKNOWN": 0}
    n = 0
    for d in sorted(root.iterdir()):
        if not (d.is_dir() and d.name.isdigit()):
            continue
        bj = d / "behaviour.json"
        if not bj.exists():
            continue
        n += 1
        cat = json.loads(bj.read_text()).get("behaviour", "UNKNOWN")
        cats[cat] = cats.get(cat, 0) + 1
    desired = DESIRED[sub]
    rate = cats.get(desired, 0) / n if n else 0
    score_sum += rate
    results[sub] = {"n": n, "counts": cats, "desired": desired, "rate": rate}
    print(f"\n=== {sub}  (n={n}) ===")
    print(f"  desired: {desired}")
    for k, v in cats.items():
        mark = " ←" if k == desired else ""
        print(f"  {k:10s}: {v:4d} ({v/n:.1%}){mark}")
    print(f"  desired rate: {rate:.3f}")

avg = score_sum / len(DESIRED)
print(f"\n{'=' * 50}")
print(f"FDB V1.5 Average × 100 = {avg * 100:.1f}")
print(f"{'=' * 50}")
Path("/tmp/fdb_final_results.json").write_text(json.dumps({
    "per_subset": results, "aggregate": avg * 100,
}, indent=2))
