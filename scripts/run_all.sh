#!/bin/bash
# Run the full Full-Duplex-Bench v1.0 + v1.5 inference suite against the
# AssemblyAI Voice Agent API. Sequential, max 5 concurrent WebSocket sessions
# globally.
#
# Usage:
#   export ASSEMBLYAI_API_KEY=...
#   export FDB_DATASET=/path/to/Full-Duplex-Bench-Data  # contains v1.0/ and v1.5/
#   bash scripts/run_all.sh
set -u
ADAPTER="$(cd "$(dirname "$0")/.." && pwd)/adapter/run_inference.py"

if [ -z "${FDB_DATASET:-}" ]; then
  echo "FDB_DATASET is not set (path to the Full-Duplex-Bench-Data directory)"
  exit 1
fi

run_subset() {
  local label="$1"
  local path="$2"
  shift 2
  echo "=================================================="
  echo "[$(date +%H:%M:%S)] starting $label"
  echo "=================================================="
  python3 "$ADAPTER" "$path" --concurrency "${FDB_CONCURRENCY:-5}" "$@" \
    || echo "(subset $label exited non-zero — continuing)"
  echo "[$(date +%H:%M:%S)] finished $label"
}

# v1.5 — first pass (input.wav -> output.wav)
for sub in user_interruption user_backchannel talking_to_other background_speech; do
  run_subset "v1.5/$sub" "$FDB_DATASET/v1.5/$sub"
done

# v1.5 — second pass (clean_input.wav -> clean_output.wav) for paper-faithful behavior eval
for sub in user_interruption user_backchannel talking_to_other background_speech; do
  run_subset "v1.5/$sub (clean)" "$FDB_DATASET/v1.5/$sub" \
    --input-name clean_input.wav \
    --output-name clean_output.wav \
    --transcript-name clean_agent_transcript.json
done

# v1.0
for sub in candor_pause_handling candor_turn_taking icc_backchannel \
           synthetic_pause_handling synthetic_user_interruption; do
  run_subset "v1.0/$sub" "$FDB_DATASET/v1.0/$sub"
done

echo "ALL DONE at $(date +%H:%M:%S)"
