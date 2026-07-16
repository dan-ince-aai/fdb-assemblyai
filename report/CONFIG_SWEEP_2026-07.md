# Turn-Detection Config Sweep + Competitor Comparison — FDB Composite vs Latency

**Dates:** 2026-07-15/16 · **Voice:** alba · **Endpoint:** `agents.us.assemblyai.com` · All headline numbers below are **full-scale measured runs** (probe-based exploration documented at the bottom). Pipeline identical across every row: whisper-1 word ASR + silence gate + trim repair → FDB official evals → paper-faithful GPT-4o behavior classification. Main methodology report: [FDB_REPORT_2026-07.md](FDB_REPORT_2026-07.md).

---

## Executive summary

1. **Measured composite, AA-faithful definition: `turn_detection: {min_silence: 1200, max_silence: 3600}` scores 92.0** — the best of any configuration tested, up from 80.4 at the no-config default and 84.7 at the documented defaults. `min_silence: 1500` measures 91.0: beyond ~1200 ms the agent starts missing legitimate turns and responding to interruptions too slowly, so patience stops paying.

2. **ElevenLabs Agents (stock defaults, same benchmark, same pipeline): 86.8.** Stock-vs-stock, ElevenLabs beats our no-config default (86.8 vs 80.7). Tuned-vs-stock, we win (92.0 vs 86.8). Their profile is the mirror image of our default: near-perfect pause discipline (97.1) bought with an 11% legitimate-turn miss rate (turn-taking 89.1) and weak backchannel floor-holding (76).

3. **The AA composite formula was reverse-engineered from their page data**: equal-weight mean of four components with exact FDB denominators — and their "pause handling" uses **synthetic_pause_handling only** (n=137; the 216 candor samples are not scored). All composites below use that definition.

4. **Latency prices every point.** Turn-commit latency: 1.04 s (no-config) → 1.57 s (defaults) → 2.28 s (ms1200) → 2.37 s (ms1500); ElevenLabs stock sits at 1.67 s. The AA metric does not score latency; report the pair.

5. **Recommendation (composite-first, per benchmark owner):** `min_silence: 1200` — measured 92.0, #7-equivalent on the AA ladder, and the best latency of the tuned configs.

## Measured scorecard (full-n, single pipeline)

| Run | Pause (synth, n=137) | Turn-taking (n=119) | Interruption (n=200) | Backchannel (n=98) | **Composite** | TT latency |
|---|---:|---:|---:|---:|---:|---:|
| AAI — no config (adaptive default) | 49.6 | 100 | 81 | 92 | **80.7** | **1.04 s** |
| AAI — explicit documented defaults (1000/3000) | 73.0 | 97.5 | 82 | 89 | **85.4** | 1.57 s |
| **AAI — `min_silence: 1200`** | **96.4** | **96.6** | 79 | **96** | **92.0** | 2.28 s |
| AAI — `min_silence: 1500` | 96.4 | 95.8 | 76 | 96 | **91.0** | 2.37 s |
| ElevenLabs Agents — stock | 97.1 | 89.1 | **85** | 76 | **86.8** | 1.67 s |
| AAI — May 2026 baseline (ivy, no config) | 81.8 | 100 | 84 | 86 | **88.0** | 1.45 s |

Config-sensitivity note: interruption and backchannel move with the dial too — more patience trades interruption RESPOND (0.82 → 0.76 across the sweep) for backchannel RESUME (0.89 → 0.96). The dial moves all four components, with an interior optimum.

**ElevenLabs run config of record:** stock agent defaults — LLM `gemini-2.5-flash`, TTS `eleven_flash_v2`, turn mode `turn` / eagerness `normal`, PCM16 @16 kHz both directions, same generic system prompt as our runs, no first message. 1,068 sessions via `adapter/run_inference_elevenlabs.py` (playback-simulation alignment incl. interruption truncation, mirroring the AssemblyAI adapter). Their backchannel UNKNOWN rate is 20% — a portion is the agent going fully silent after a backchannel.

## AA Conversational Dynamics ladder (their published data + our measured runs)

AA per-model component data extracted from their page (2026-07-16); their composite = equal-weight mean, verified against their own aggregates. Cross-pipeline placement is directional — their inference client and classifier are not public.

| # | Model | Composite |
|---:|---|---:|
| 1 | Fun-Realtime-Audiochat | 97.8 |
| 2 | GPT-Realtime-2 (Minimal) | 96.1 |
| 3 | GPT-Realtime-1.5 / GPT Realtime Mini | 95.7 |
| 5 | GPT-Realtime-2 (High) | 95.3 |
| 6 | GPT Realtime (Aug '25) | 93.9 |
| — | **AssemblyAI, min_silence 1200 (measured)** | **92.0** |
| 7 | NVIDIA PersonaPlex | 91.0 |
| 8 | GPT-4o Realtime (Dec '24) | 89.8 |
| — | **AssemblyAI, May baseline (measured)** | **88.0** |
| — | **ElevenLabs Agents stock (measured)** | **86.8** |
| 9 | Deepslate Opal | 85.7 |
| — | **AssemblyAI, documented defaults (measured)** | **85.4** |
| — | **AssemblyAI, no-config default (measured)** | **80.7** |
| 10 | Grok Voice Think Fast / Nemotron Voicechat | 77.8 |
| 12 | Gemini 3.1 Flash (High) | 74.3 |
| … | (Qwen3 Omni 72.7, Gemini 3.1 Min 72.3, Grok Fast 71.6, FLM-Audio 62.0, Moshi 61.0, Freeze-Omni 58.7, Gemini 2.5 NA 44.0/30.3) | |

Per-component vs the leaders: with the tuned config our pause (96.4) and turn-taking (96.6) are at GPT-Realtime levels; the remaining gap to the top-6 is **interruption handling** (our 0.79–0.82 vs their 0.95–0.98 on AA's pipeline — partially a classifier-leniency artifact, but the ordering is consistent).

## Probe sweep (exploration that located the optimum)

50-sample probes per config, sample-matched anchors; ±2/30 run-to-run noise measured via repeat runs:

| Config | Pause interrupts (30) | TT TOR (20) | Est. → Measured composite |
|---|---:|---:|---|
| No config | 17–19/30 | 1.00 | 80.4→**80.7** |
| Documented defaults | 8/30 | 1.00 | 84.7→**85.4** |
| min_silence 1200 | 3/30 | 1.00 | ~90→**92.0** |
| min_silence 1500 | 1/30 | 1.00 | ~92→**91.0** |
| min_silence 2000 | 2/30 | 0.90 | ~88.5 (not validated — dominated) |
| min_silence 2500 | 2/30 | 0.90 | ~88.5 (not validated — dominated) |

Probe→measured deltas came from the probe's blind spots (20-sample turn-taking TOR; UI/UB config-sensitivity), which is why headline numbers are full-scale only.

## Method notes

- AA-faithful composite = mean(synthetic-pause correct-hold, candor turn-taking TOR, v1.5 interruption RESPOND, v1.5 backchannel RESUME), all paper-faithful classification for the v1.5 axes.
- All AssemblyAI runs: 24 kHz PCM16, `session.end` teardown, concurrency 10. ElevenLabs run: PCM16 @16 kHz, concurrency 3, signed-URL sessions, per-second billing (~375 min total).
- Archives: `backup-2026-05-18-ivy-run/` (May), `backup-2026-07-15-alba-noconfig/` (July default), main tree (July explicit defaults), `elevenlabs-run/` (ElevenLabs), scratch `validate-ms1200/1500/` trees (tuned configs).
- Measurement repairs applied equally to every run: whisper-on-alba trim fix, silence gating, transcript-source fix, content_tag purging — see the main report's "Measurement integrity" section.
