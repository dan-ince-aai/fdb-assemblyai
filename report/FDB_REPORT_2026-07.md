# AssemblyAI Voice Agent — Full-Duplex-Bench v1.0 + v1.5 (July 2026 re-run)

**Run date:** 2026-07-15
**Endpoint:** `wss://agents.us.assemblyai.com/v1/ws` (May run used `agents.assemblyai.com`)
**Voice:** alba (May: ivy) · **Audio:** 24 kHz PCM16 mono · **Concurrency:** 10 sockets globally, with explicit `session.end` teardown
**System prompt:** identical generic assistant prompt, no benchmark tuning
**Coverage:** 1,723/1,723 sessions (498 v1.5 + 498 v1.5 clean pass + 727 v1.0), zero unrecovered errors
**Baseline:** the 2026-05-18 ivy run, re-evaluated from archived artifacts (`fdb-dataset/backup-2026-05-18-ivy-run/`) with the *identical* July eval pipeline — including the whisper-on-alba transcript repair described below, applied to both runs — so every May number here is pipeline-matched. (May numbers therefore differ slightly from the May report.)

---

## TL;DR

**AA-style composite ("weighted average of pause handling, turn-taking, interruption handling, and backchannel handling from FDB v1 and v1.5"): 80.4 July vs 84.8 May (equal weights).** The entire remaining gap is pause handling. Interruption handling is identical, backchannel actually improved, turn-taking latency improved 28%.

| AA composite | July (alba, us host) | May (ivy) |
|---|---:|---:|
| Equal weights | **80.4** | 84.8 |
| Weighted by sample count | **69.5** | 78.8 |

| Component | Definition | July | May | Δ |
|---|---|---:|---:|---:|
| Pause handling | % pauses correctly not interrupted, v1.0 (candor+synthetic avg) | **45.7** | 69.6 | **−23.9** |
| Turn-taking | % turns correctly taken, v1.0 candor | **100** | 100 | 0 |
| Interruption handling | % RESPOND on user interruptions, v1.5 paper-faithful | **84.0** | 84.0 | 0 |
| Backchannel handling | % RESUME through backchannels, v1.5 paper-faithful | **91.8** | 85.7 | **+6.1** |

AA does not publish weights or pipeline; absolute comparison to their leaderboard (GPT-Realtime ~94–96) is not meaningful. The May↔July deltas, computed with one pipeline on both runs, are the signal.

---

## v1.0 results (FDB official ASR-based eval, silence-gated)

Pipeline: whisper-1 word-level ASR of `output.wav` → FDB `eval_pause_handling.py` / `eval_smooth_turn_taking.py` verbatim. All-zero output wavs are transcript-gated to empty (Whisper hallucinates on silence; 364/943 transcripts across both runs). Identical treatment for both runs.

| Subset | n | Metric | July | May |
|---|---:|---|---:|---:|
| candor_pause_handling | 216 | TOR (lower better) | **0.583** | 0.426 |
| synthetic_pause_handling | 137 | TOR (lower better) | **0.504** | 0.182 |
| candor_turn_taking | 119 | TOR (higher better) | **1.000** | 1.000 |
| candor_turn_taking | 119 | response latency (s) | **1.04** | 1.45 |

Independent VAD cross-check (Silero, FDB `get_timing.py`, no ASR): candor pause TOR 0.583 vs May 0.407; synthetic 0.511 vs 0.146; turn-taking 1.000 vs 0.983. **The pause-handling regression is confirmed by two independent pipelines** — it is not an ASR artifact.

July includes candor_turn_taking sample 62 (94 s input) for the first time in any run — it exceeded the adapter's fixed 90 s timeout in every previous attempt including May's (adapter now scales the timeout with input duration). Its 51.6 s response latency is an outlier worth an ear.

## v1.5 results (three classifier pipelines, corrected transcripts)

| Subset (desired) | Paper July | Paper May | Primed July | Primed May | Neutral July | Neutral May |
|---|---:|---:|---:|---:|---:|---:|
| user_interruption (RESPOND) | **0.84** | 0.84 | 0.83 | 0.81 | 0.86 | 0.81 |
| user_backchannel (RESUME) | **0.92** | 0.86 | 0.94 | 0.96 | 0.92 | 0.97 |
| talking_to_other (RESUME) | **0.27** | 0.38 | 0.46 | 0.55 | 0.39 | 0.51 |
| background_speech (RESUME) | **0.79** | 0.94 | 0.85 | 0.99 | 0.85 | 0.99 |
| **Average ×100** | **70.5** | 75.4 | **77.0** | 82.7 | **75.3** | 81.9 |

## Reading the deltas

- **Pause handling (large, real regression):** agent takes the floor during natural user pauses in 50–58% of samples vs 15–43% in May.
- **Talking-to-other / background-speech (regression):** the floor-holding-through-third-party-speech axes dropped on all three pipelines (TO 0.27–0.46 vs 0.38–0.55; BG 0.79–0.85 vs 0.94–0.99). 16 July samples (12 BG, 4 TO) have all-zero output — the agent never spoke at all.
- **Turn-taking latency (improvement):** 1.45 s → 1.04 s at 100% TOR both runs.
- **Interruption (flat mechanically, softer qualitatively):** RESPOND rate identical (0.84), but "echo the question back" clarifying replies ("Are you asking about financial goals…?" in reply to *"what financial goals should I set?"*) rose from 4% (8/200) to **11% (22/200)**. FDB counts content-specific clarification as RESPOND, so this quality drop is invisible in the score.
- **Backchannel (improvement):** 0.92 vs 0.86 paper-faithful once transcripts were repaired.

One coherent story fits: **the endpoint's turn detector became more eager** — faster to conclude the user is done (latency win) and quicker to treat pauses and third-party speech as turn-yields (floor-holding losses). Confounds not fully excluded: voice (alba vs ivy) and regional host (`us.` vs global), though neither should drive speak/don't-speak decisions.

---

## Measurement bug found and fixed: whisper-1 collapses on alba

whisper-1's word-timestamp mode collapsed **59 July transcripts (vs 10 May)** — files with 7–10 s of clearly intelligible speech transcribed as just "Thanks for watching." (its signature silence-hallucination, triggered by ~3–4 s of leading silence; alba trips it ~6× more than ivy). 48 of the 59 were in user_backchannel, which initially made backchannel look like it regressed 0.86→0.67 when it had actually **improved**. Human listening + native `transcript.agent` + normal pitch stats confirmed the audio was fine.

**Fix (applied to both runs before all numbers above):** trim leading sub-threshold audio before sending to whisper-1, shift word timestamps back by the trim offset, invalidate and re-run classification for affected samples. Detection heuristic: >2.5 s of voiced audio but <5 transcribed words.

## Other methodology fixes made during this run

1. **`session.end` teardown** (adapter): closing the socket without it leaves each session resumable *and billable* for 30 s, and the zombies count against the per-key concurrency limit — the real cause of the old "5 sockets max" rule. Concurrency 10 is now error-free (20 still isn't). Side benefit: native transcript capture rose from 200/498 to 473/498.
2. **Duration-scaled per-sample timeout** (adapter): `max(90 s, input + 30 s)`.
3. **`run_all.sh` arg forwarding**: the v1.5 clean-pass `--input/--output-name` flags were silently dropped; the clean pass never ran via the script before.
4. **Classifier response-text source**: native `transcript.agent` misses post-overlap replies that arrive after the capture window (0/88 RESPOND on affected user_interruption samples). Classifiers now read Whisper ASR of `output.wav`.
5. **Silence gating before v1.0 TOR eval** (Whisper hallucinates on all-zero wavs; 364/943 affected).
6. **`content_tag.json` purging**: FDB's behavior eval silently reuses cached per-sample results; stale caches from a previous run must be removed before re-evaluating.
7. **Retry/backoff + skip-existing in classifiers** (fresh OpenAI keys rate-limit hard).

## Reproducing

```bash
export ASSEMBLYAI_API_KEY=... OPENAI_API_KEY=...
export FDB_DATASET=/path/to/Full-Duplex-Bench-Data
export FDB_CONCURRENCY=10
bash scripts/run_all.sh                                  # inference, all subsets + clean pass

# timing (Silero VAD)
for sub in v1.0/* v1.5/*; do python3 fdb-eval/v1_v1.5/evaluation/get_timing.py --root_dir "$FDB_DATASET/$sub"; done

# word-level ASR (then: silence-gate all-zero wavs; trim-fix any >2.5s-voiced/<5-word transcripts)
python3 eval/whisper_asr.py "$FDB_DATASET" --word-timestamps

# FDB official evals
python3 fdb-eval/v1_v1.5/evaluation/evaluate.py --task pause_handling     --root_dir "$FDB_DATASET/v1.0/candor_pause_handling"
python3 fdb-eval/v1_v1.5/evaluation/evaluate.py --task pause_handling     --root_dir "$FDB_DATASET/v1.0/synthetic_pause_handling"
python3 fdb-eval/v1_v1.5/evaluation/evaluate.py --task smooth_turn_taking --root_dir "$FDB_DATASET/v1.0/candor_turn_taking"
python3 fdb-eval/v1_v1.5/evaluation/evaluate.py --task behavior           --root_dir "$FDB_DATASET/v1.5/<subset>"   # ×4

# classifier pipelines + aggregate
python3 eval/classify_simplified.py "$FDB_DATASET"
python3 eval/classify_neutral.py "$FDB_DATASET"
python3 eval/aggregate.py "$FDB_DATASET"
```
