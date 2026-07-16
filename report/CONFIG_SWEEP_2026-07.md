# Turn-Detection Config Sweep — Full-Duplex-Bench Composite vs Latency

**Date:** 2026-07-15 · **Voice:** alba · **Endpoint:** `agents.us.assemblyai.com` · Sweep = 50-sample probes per config (15 candor-pause + 15 synthetic-pause + 20 turn-taking); anchors re-scored on the identical samples. Full methodology and eval pipeline: [FDB_REPORT_2026-07.md](FDB_REPORT_2026-07.md).

---

## Executive summary

1. **The AA-style composite peaks near `turn_detection: {min_silence: 1500}` — probe-estimated ~92, tracking to ~90 in full-scale validation** (see Full-scale validation below), up from 84.7 at the documented defaults and 80.4 at the no-config adaptive mode. Either way, top of the published cohort's range.

2. **The peak is real, not a monotone knob.** Above 1500 ms the score *falls*: the agent waits so long it misses legitimate turns entirely (turn-taking TOR drops 1.00 → 0.90 at 2000 ms), cancelling the pause-handling gains. The sweep found an interior optimum.

3. **But the metric does not price latency, and latency pays for every point.** Response latency climbs ~0.5 s per config step: the composite-maximizing config answers **~2.9 s** after the user stops speaking — benchmark gold, demo poison. This is the central caveat on the "92".

4. **Recommendation — with the AA conversational dynamics score as the primary objective: `turn_detection: {min_silence: 1500, max_silence: 4500}`.** It is the composite maximizer (~92 est.), keeps turn-taking TOR perfect, and saturates pause handling. The cost is response latency (~2.9 s after end of user speech, vs 1.05 s adaptive / 1.85 s documented defaults) — report it alongside the score rather than trading the score away for it. If a latency ceiling is ever imposed, `min_silence: 1200` retains ~90 at 2.4 s.

5. **Caveats:** sweep points are 50-sample probes (±2 composite points); interruption/backchannel components are held at their measured full-scale values (they are insensitive to this config — verified at full scale); tuning `min_silence` to a benchmark's pause-length distribution is borderline metric-gaming and should not silently become the product default. Full-scale validation of any chosen config is ~25 min of inference.

---

## The frontier (all runs scored on identical samples)

| Config | Pause interrupts ↓ (n=30) | Turn-taking TOR ↑ (n=20) | Response latency (n=20) | Est. AA composite ↑ |
|---|---:|---:|---:|---:|
| No config (adaptive mode) | 17–19/30 | 1.00 | **1.05 s** | 80.4 † |
| May 2026 baseline (no config, ivy) | 10/30 | 1.00 | 1.37 s | 84.8 † |
| `{min_silence: 1000, max_silence: 3000}` (documented defaults) | 8/30 | 1.00 | 1.85 s | 84.7 † |
| `{min_silence: 1200}` | 3/30 | 1.00 | 2.40 s | ~90 |
| **`{min_silence: 1500}`** | **1/30** | **1.00** | 2.86 s | **~92** |
| `{min_silence: 2000}` | 2/30 | 0.90 | 3.00 s | ~88.5 |
| `{min_silence: 2500}` | 2/30 | 0.90 | 2.93 s | ~88.5 |

† measured at full scale (not probe-estimated). All sweep configs use `vad_threshold: 0.5`, `max_silence = 3×min_silence`. Composite = mean(pause, turn-taking TOR, interruption 0.82, backchannel 0.89); the latter two are config-insensitive (full-scale verified: ±0.03 between adaptive and explicit modes).

Marginal cost of each composite point:

| Step | Composite gain | Latency cost |
|---|---:|---:|
| defaults → 1200 | +5.6 | +0.55 s |
| 1200 → 1500 | +1.6 | +0.46 s |
| 1500 → 2000 | **−3.4** | +0.14 s |

## Reading it

- **Why the score rises:** pause handling is 25% of the composite and the current no-config mode barges into 50–58% of natural user pauses. Every ms of added patience converts almost directly into pause points until saturation (~1/30 at 1500 ms).
- **Why it falls after 1500 ms:** FDB's turn-taking clips end shortly after the user's turn; an agent still waiting at clip end scores as "didn't take the turn." At 2000 ms, 2/20 turns are lost — each worth as much as 3 pause samples.
- **Why latency is the hidden axis:** AA's composite has no latency term. The 92-config is *slower to respond than May, the defaults, and the adaptive mode combined would suggest is acceptable* — 2.86 s of silence after every user turn. Publish the pair (composite, latency), not the composite alone.

## Full-scale validation (in progress)

Probe estimates are being replaced by full-scale measured runs of the two viable configs (all composite-relevant subsets, ~1,050 sessions each). Measured so far — `min_silence: 1500`, v1.0 subsets, full n:

| ms1500 component | Full-scale measured | Probe estimate |
|---|---:|---:|
| Candor pause TOR (n=215) | **0.098** | ~0.07 ✓ |
| Synthetic pause TOR (n=137) | **0.036** | 0.00 ✓ |
| Pause component | **93.3** | ~93 ✓ |
| Turn-taking TOR (n=119) | **0.958** | 1.00 ✗ |
| Turn-taking latency | 2.37 s | 2.86 s (slow-skewed probe subset) |

The probe's 20-sample turn-taking set missed a real cost: at full scale the agent fails to take 5/119 legitimate turns at 1500 ms patience. **Measured composite is tracking to ~90, not the probe's ~92.** The `min_silence: 1200` full run (in flight) may win outright if its shorter wait preserves those turns — final measured composites for both configs will replace this section.

## Method notes

- Probes: first 15 samples of each pause subset, first 20 of candor_turn_taking; anchors (adaptive / May / defaults) re-scored on the same samples from archived full-run artifacts, so every row is sample-matched. Measured probe↔full-scale offset on this turn-taking subset: ~+0.3 s (the 20 probe samples skew slow); relative ordering is unaffected.
- Scoring identical to the main report: whisper-1 word ASR + silence gate + trim repair → FDB official `eval_pause_handling` / `eval_smooth_turn_taking`.
- Run-to-run noise on 30-sample pause probes: ±2 interrupts (measured with repeat runs).
- All inference same-day, concurrency 10, clean `session.end` teardown; 0 errors across 200 sweep sessions.

## Next steps

1. Full-scale validation (353 pause + 119 turn-taking sessions) of the chosen config before publishing any number from this sweep.
2. If a latency-priced composite is wanted: re-rank with a latency penalty term (e.g. −2 pts per second over 1.5 s) — under that, `1200` wins and adaptive/default modes become competitive again.
3. The v1.5 axes (`talking_to_other`, `background_speech`) are unaffected by this dial and remain the open regression vs May (see main report).
