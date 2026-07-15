# AssemblyAI Voice Agent — Full-Duplex-Bench v1.0 + v1.5 (July 2026 re-run)

**Run date:** 2026-07-15
**Endpoint:** `wss://agents.us.assemblyai.com/v1/ws` (May run used `agents.assemblyai.com`)
**Voice:** alba (May: ivy) · **Audio:** 24 kHz PCM16 mono · **Concurrency:** 10 sockets globally, with explicit `session.end` teardown
**System prompt:** identical generic assistant prompt, no benchmark tuning
**Coverage:** 1,723/1,723 sessions (498 v1.5 + 498 v1.5 clean pass + 727 v1.0), zero unrecovered errors
**Baseline:** the 2026-05-18 ivy run, re-evaluated from archived artifacts (`fdb-dataset/backup-2026-05-18-ivy-run/`) with the *identical* July eval pipeline, so every May number below is pipeline-matched.

---

## TL;DR

**The Artificial-Analysis-style composite ("weighted average of pause handling, turn-taking, interruption handling, and backchannel handling from FDB v1 and v1.5") dropped from 84.1 (May) to 73.4 (July), equal weights.** Turn-taking latency improved and interruption handling held, but pause handling regressed hard (agent barges into natural user pauses 2–3× more often) and backchannel/floor-holding regressed moderately. The pattern is consistent with a server-side turn-detection shift toward eagerness between May and July.

| AA composite | July (alba, us host) | May (ivy) |
|---|---:|---:|
| Equal weights | **73.4** | 84.1 |
| Weighted by sample count | **65.5** | 78.3 |

Component scores (all ×100, higher is better):

| Component | Definition | July | May | Δ |
|---|---|---:|---:|---:|
| Pause handling | % pauses correctly not interrupted, v1.0 (candor+synthetic avg) | **45.7** | 69.6 | **−23.9** |
| Turn-taking | % turns correctly taken, v1.0 candor | **100** | 100 | 0 |
| Interruption handling | % RESPOND on user interruptions, v1.5 paper-faithful | **81.0** | 83.0 | −2.0 |
| Backchannel handling | % RESUME through backchannels, v1.5 paper-faithful | **67.0** | 83.7 | **−16.7** |

AA does not publish its weights or pipeline; the absolute numbers are not comparable to their leaderboard (GPT-Realtime ~94–96). The May↔July deltas, computed with one pipeline on both runs, are the reliable signal.

---

## v1.0 results (FDB official ASR-based eval, silence-gated)

Pipeline: whisper-1 word-level ASR of `output.wav` → FDB `eval_pause_handling.py` / `eval_smooth_turn_taking.py` verbatim. All-zero output wavs are transcript-gated to empty (Whisper hallucinates on silence; 364/943 transcripts across both runs were silence-gated). Identical treatment for both runs.

| Subset | n | Metric | July | May |
|---|---:|---|---:|---:|
| candor_pause_handling | 216 | TOR (lower better) | **0.583** | 0.426 |
| synthetic_pause_handling | 137 | TOR (lower better) | **0.504** | 0.182 |
| candor_turn_taking | 119 | TOR (higher better) | **1.000** | 1.000 |
| candor_turn_taking | 119 | response latency (s) | **1.04** | 1.45 |

Independent VAD cross-check (Silero, FDB `get_timing.py`, no ASR): candor pause TOR 0.583 vs May 0.407; synthetic 0.511 vs 0.146; turn-taking 1.000 vs 0.983. **The pause-handling regression is confirmed by two independent pipelines** — it is not an ASR artifact.

Note: July includes candor_turn_taking sample 62 (94 s input) for the first time — it exceeded the adapter's fixed 90 s timeout in every previous run, including May's. The adapter now scales its timeout with input duration.

## v1.5 results (three classifier pipelines)

All response texts are Whisper ASR of the audible output window (see Methodology fixes below). May numbers recomputed from archived artifacts where possible.

| Subset (desired) | Paper-faithful July | Paper-faithful May | Primed GPT-4o July | Primed May | Neutral GPT-4o July | Neutral May |
|---|---:|---:|---:|---:|---:|---:|
| user_interruption (RESPOND) | **0.81** | 0.83 | 0.805 | 0.810 | TBD | 0.814 |
| user_backchannel (RESUME) | **0.67** | 0.837 | 0.724 | 0.959 | TBD | 0.969 |
| talking_to_other (RESUME) | **0.27** | 0.38 | 0.460 | 0.550 | TBD | 0.515 |
| background_speech (RESUME) | **TBD** | 0.94 | 0.850 | 0.990 | TBD | 0.990 |
| **Average ×100** | **TBD** | 74.7 | **71.0** | 82.7 | TBD | 82.2 |

Caveat on the May primed/neutral columns: May's classifier consumed mixed transcript sources (200 native / 298 Whisper). July uses Whisper-of-output for all samples (strictly better; see fixes).

## What changed vs May — reading the deltas

- **Pause handling (large regression):** the agent takes the floor during natural user pauses in 50–58% of samples vs 18–43% in May. Biggest driver of the composite drop.
- **Backchannel (moderate regression):** RESUME dropped ~14–24 pts across all three pipelines; elevated UNKNOWN (23% paper-faithful) — the agent stops/yields on "mm-hmm" more than it used to.
- **Talking-to-other (regression):** 0.27–0.46 vs 0.38–0.55; already the weakest axis in May, weaker now. (Excluded from the AA composite.)
- **Turn-taking latency (improvement):** 1.45 s → 1.04 s at 100% TOR both runs.
- **Interruption handling (flat):** 0.81 vs 0.83 paper-faithful, well within noise.

One coherent story fits all five: **the endpoint's turn detector became more eager** — faster to conclude the user is done (better turn-taking latency) and quicker to treat pauses/backchannels/off-axis speech as turn-yields (worse floor-holding). Confounds that cannot be fully excluded: different voice (alba vs ivy) and regional host (`us.` vs global), though neither should drive speak/don't-speak decisions.

---

## Methodology fixes made during this run (affect anyone re-running)

1. **`session.end` teardown** (adapter): closing the socket without `session.end` leaves each session resumable *and billable* for 30 s, and those zombies count against the per-key concurrency limit. This was the real cause of the old "5 sockets max" rule. With clean teardown, concurrency 10 is error-free; 20 still produces ~7% timeouts. Side benefit: native `transcript.agent` capture rose from 200/498 to 473/498.
2. **Duration-scaled per-sample timeout** (adapter): `max(90 s, input + 30 s)`; fixes the perennial candor_turn_taking/62 failure.
3. **`run_all.sh` arg forwarding**: the clean-pass `--input-name/--output-name` flags were silently dropped, so the v1.5 clean pass never ran via the script (May's clean pass was evidently run by hand).
4. **Classifier response-text source**: native `transcript.agent` misses the post-overlap reply whenever it arrives after the capture window; on user_interruption this misclassified every such sample (0/88 RESPOND). Classifiers now read Whisper ASR of `output.wav`.
5. **Silence gating before v1.0 TOR eval**: Whisper hallucinates on all-zero wavs; without gating, pause-handling TOR is wildly inflated (364/943 transcripts affected).
6. **`content_tag.json` purging**: FDB's behavior eval caches per-sample results and silently reuses them; stale caches from a previous run must be moved out before re-evaluating.
7. **Retry/backoff in `classify_simplified.py`** (429s on fresh OpenAI keys) and skip-existing so re-runs are incremental.

## Reproducing

```bash
export ASSEMBLYAI_API_KEY=... OPENAI_API_KEY=...
export FDB_DATASET=/path/to/Full-Duplex-Bench-Data
export FDB_CONCURRENCY=10
bash scripts/run_all.sh                                  # inference, all subsets + clean pass

# timing (Silero VAD)
for sub in v1.0/* v1.5/*; do python3 fdb-eval/v1_v1.5/evaluation/get_timing.py --root_dir "$FDB_DATASET/$sub"; done

# word-level ASR + silence gate, then FDB official evals
python3 eval/whisper_asr.py "$FDB_DATASET" --word-timestamps
# (gate all-zero output.wav -> {"text":"","chunks":[]} before the next step)
python3 fdb-eval/v1_v1.5/evaluation/evaluate.py --task pause_handling     --root_dir "$FDB_DATASET/v1.0/candor_pause_handling"
python3 fdb-eval/v1_v1.5/evaluation/evaluate.py --task pause_handling     --root_dir "$FDB_DATASET/v1.0/synthetic_pause_handling"
python3 fdb-eval/v1_v1.5/evaluation/evaluate.py --task smooth_turn_taking --root_dir "$FDB_DATASET/v1.0/candor_turn_taking"
python3 fdb-eval/v1_v1.5/evaluation/evaluate.py --task behavior           --root_dir "$FDB_DATASET/v1.5/<subset>"   # ×4

# classifier pipelines + aggregate
python3 eval/classify_simplified.py "$FDB_DATASET"
python3 eval/classify_neutral.py "$FDB_DATASET"
python3 eval/aggregate.py "$FDB_DATASET"
```
