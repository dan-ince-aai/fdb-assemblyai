# Full-Duplex-Bench: AssemblyAI Voice Agent — July 2026 Report

**Runs compared:** May 2026 baseline (voice `ivy`, `agents.assemblyai.com`) · July 2026 default-config (voice `alba`, `agents.us.assemblyai.com`) · July 2026 explicit turn-detection config (same, plus `turn_detection: {vad_threshold: 0.5, min_silence: 1000, max_silence: 3000}`).
All three runs scored with one identical eval pipeline, from raw artifacts. 3,200+ inference sessions total, zero unrecovered errors.

---

## Executive summary

1. **On the leaderboard metric (Artificial-Analysis-style composite: pause handling + turn-taking + interruption + backchannel), the default-config agent scores 80.4, down from 84.8 in May.** One config line — explicitly setting turn detection to its own documented defaults — restores **84.7** today.

2. **Root cause of the drop: turn-detection endpointing behavior changed between May and July for sessions that send no `turn_detection` config.** Omitted-config sessions now use a more eager, adaptive endpointing mode; sending *any* explicit `turn_detection` object (even one restating the documented defaults) pins the classic fixed-window behavior. We verified this with five controlled arms on identical samples: the *presence* of the config object, not the values, produces the big shift.

3. **The eager default is a deliberate trade, and the benchmark sees its worst side.** Default-config turn-taking latency improved 1.45 s → 1.04 s (best-in-class territory), but the agent now barges into natural user pauses ~2.4× more often (pause-handling score 45.7 vs 69.6). FDB's prerecorded clips can never push back on interruptions the way live users do, so the benchmark measures the eager mode's cold start — but real callers experience that same cold start at the top of every call.

4. **Interruption and backchannel handling did not regress** (0.82/0.89 vs May's 0.84/0.86, paper-faithful) — and are unaffected by the endpointing mode. A residual v1.5 regression in `talking_to_other` (0.27–0.32 vs 0.38) and `background_speech` (0.78–0.79 vs 0.94) persists under *both* endpointing modes, so it has a different cause (model/filtering/voice drift since May) and needs separate investigation. Neither subset counts toward the AA composite.

5. **Two measurement bugs would have corrupted these conclusions if uncaught** — whisper-1 collapses transcripts on the alba voice ~6× more than ivy (initially faked a backchannel regression: 0.67 raw → 0.92 repaired), and Whisper hallucinates text on silent audio (364+ transcripts gated). All numbers here are post-repair, applied equally to all runs.

**Recommendations:** (a) decide deliberately which endpointing mode default-config customers should get — today's eager default trades ~4 composite points for ~0.4 s of latency; (b) treat "any config ⇒ fully manual mode" as an API-semantics issue — restating documented defaults should not change behavior; (c) investigate the `talking_to_other`/`background_speech` drift separately; (d) publish benchmark claims from the explicit-config run (84.7) or fix the default cold-start.

---

## Scorecard (three runs, one pipeline)

| Metric | July default | **July explicit TD** | May baseline |
|---|---:|---:|---:|
| **AA-style composite (equal weights)** | 80.4 | **84.7** | 84.8 |
| Pause handling (1−TOR, candor/synthetic avg) | 45.7 | **70.3** | 69.6 |
| Turn-taking TOR | 1.000 | 0.975 | 1.000 |
| Turn-taking latency | **1.04 s** | 1.57 s | 1.45 s |
| Interruption RESPOND (v1.5 paper) | 0.81 | 0.82 | 0.84 |
| Backchannel RESUME (v1.5 paper) | **0.92** | 0.89 | 0.86 |
| talking_to_other RESUME (v1.5 paper)* | 0.27 | 0.32 | 0.38 |
| background_speech RESUME (v1.5 paper)* | 0.79 | 0.78 | 0.94 |
| FDB v1.5 average — paper-faithful | 70.5 | 70.3 | 75.4 |
| FDB v1.5 average — primed GPT-4o | 77.0 | 77.0 | 82.7 |
| FDB v1.5 average — neutral GPT-4o | 75.3 | 76.5 | 81.9 |

\* not part of the AA composite. AA's own weights/pipeline are unpublished; absolute comparison to their leaderboard is not meaningful — run-vs-run deltas on this pipeline are.

## The turn-detection experiments

Controlled probe, same 30 pause-handling samples per arm (15 candor + 15 synthetic), counting pause interruptions:

| Arm | Interrupted |
|---|---:|
| No `turn_detection` sent (benchmark run) | 17/30 |
| No `turn_detection` sent (repeat, same day) | 19/30 |
| `{vad_threshold: 0.7}` — two runs | 6/30, 8/30 |
| `{vad_threshold: 0.5, min_silence: 1000, max_silence: 3000}` — **the documented defaults, stated explicitly** | **8/30** |
| `{min_silence: 2000}` | 2/30 |
| May baseline, no config | 10/30 |

The explicit-documented-defaults arm is the control that isolates the mechanism: identical values to the implicit default, ~2.3× fewer interruptions. Run-to-run noise is ±2/30 (26/30 identical verdicts between repeat runs), so these separations are far outside noise. The full-scale explicit run (1,468 sessions) confirmed the probe: pause TOR 0.324/0.270 (candor/synthetic) vs 0.583/0.504 default.

Supporting evidence for eager-mode side effects in the default run: "sorry, you were saying?"-style recovery phrases appear 7× in July default transcripts vs 1× in May, concentrated in pause-handling samples; "echo the question back" clarifying replies to interruptions rose 4% → 11%.

## Measurement integrity (read before re-running)

1. **whisper-1 collapses on alba.** Word-timestamp mode transcribed 59 July files (vs 10 May) of intelligible speech as "Thanks for watching." — triggered by 3–4 s of leading silence, hit ~6× more often with alba than ivy. Detection: >2.5 s voiced audio, <5 transcribed words. Fix: trim leading silence, re-transcribe, shift timestamps back. Unrepaired, this fakes a 25-point backchannel regression.
2. **Whisper hallucinates on silence.** Pause-handling outputs are often all-zero (correct behavior = silence); transcripts must be gated to empty before TOR scoring (364/943 v1.0 transcripts affected).
3. **Native `transcript.agent` misses post-overlap replies** that arrive after the capture window — classify from ASR of `output.wav`, never from native transcripts (0/88 false-RESUME otherwise).
4. **FDB's behavior eval caches `content_tag.json` per sample** and silently reuses it — purge before re-evaluating a new run.
5. Adapter/harness fixes this cycle: explicit `session.end` teardown (closing the socket without it leaves a 30 s billable zombie session that counts against per-key concurrency — root cause of the old 5-socket ceiling; 10 is now clean), duration-scaled per-sample timeout (fixes the never-completing 94 s sample), `run_all.sh` clean-pass arg forwarding, classifier 429 retry/backoff, `--turn-detection` flag on the adapter.

## Run inventory

| Run | Sessions | Where |
|---|---:|---|
| May 2026 baseline (ivy, no config) | 1,723 | `fdb-dataset/backup-2026-05-18-ivy-run/` |
| July 2026 default (alba, no config) | 1,723 | `fdb-dataset/backup-2026-07-15-alba-noconfig/` |
| July 2026 explicit TD (alba) | 1,468 (7 TD-sensitive subsets + clean pass) | `fdb-dataset/Full-Duplex-Bench-Data/` (in place) |

## Reproducing

```bash
export ASSEMBLYAI_API_KEY=... OPENAI_API_KEY=...
export FDB_DATASET=/path/to/Full-Duplex-Bench-Data
export FDB_CONCURRENCY=10
bash scripts/run_all.sh                       # default-config run
# explicit turn-detection run:
python3 adapter/run_inference.py "$FDB_DATASET/v1.0/candor_pause_handling" --concurrency 10 \
  --turn-detection '{"vad_threshold": 0.5, "min_silence": 1000, "max_silence": 3000}'
# ... then per subset: get_timing.py, whisper_asr.py --word-timestamps (+ silence gate + trim fix),
# evaluate.py --task pause_handling|smooth_turn_taking|behavior, classify_*.py, aggregate.py
```
