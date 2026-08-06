#!/bin/bash
# LLM-verify Sefer HaShorashim's candidate pairs via Haiku (verify_pairs_llm.py). Safe to re-run at any
# time — the underlying script skips pairs already present in the output file (dedup by strong_a|
# strong_b) and flushes after every batch, so a Ctrl-C, crash, or deliberate pause never loses progress
# and never re-spends on already-verified pairs; just run this again to continue exactly where it left
# off. See verify_pairs_llm.py's own docstring for the incremental-write history (2026-08 fix).
#
#   bash macula/run_sefer_hashorashim_verify.sh

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$HERE/../.venv/bin/python3"

"$PY" -m macula.verify_pairs_llm \
  --candidates "$HERE/../../resources/sefer_hashorashim/candidate_pairs.tsv" \
  --out "$HERE/../../resources/sefer_hashorashim/llm_pair_verification.tsv"
