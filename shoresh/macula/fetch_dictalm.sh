#!/bin/bash
# Fetch + convert DictaLM-3.0-1.7B-Instruct to MLX format, for local Hebrew-verification testing.
#
# Repeated stalls were observed downloading via `mlx_lm.convert`'s implicit download (dead at ~310MB,
# then again at exactly 16MB on EVERY retry via a first snapshot_download attempt) — the byte count
# never moving even slightly across many retries is the signature of huggingface_hub's newer Xet
# transfer backend (`hf_xet`, Rust-based) getting stuck on this network (proxy/firewall), not genuine
# slowness. FIXED: HF_HUB_DISABLE_XET=1 (set in _fetch_dictalm.py) falls back to the plain, universally-
# compatible HTTP downloader instead. (HF_HUB_ENABLE_HF_TRANSFER, tried earlier, is a deprecated no-op —
# not the same thing as Xet, despite the similar-sounding name.)
#
# This script: (1) downloads the snapshot directly via huggingface_hub with visible progress + a stall
# watchdog that kills and retries the whole download if the target directory hasn't grown in
# STALL_SECS, then (2) runs the MLX convert/quantize step separately, once the download is confirmed
# complete — so a failure in step 2 never means re-downloading.
#
#   bash macula/fetch_dictalm.sh

set -uo pipefail

MODEL="dicta-il/DictaLM-3.0-1.7B-Instruct"
MLX_OUT="/tmp/dictalm-1.7b-mlx"
STALL_SECS=45
MAX_RETRIES=8
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$HERE/../.venv/bin/python3"
CACHE_DIR="$MLX_OUT.hf-src"

cache_size_mb() {
    du -sm "$CACHE_DIR" 2>/dev/null | cut -f1 || echo 0
}

echo "[fetch-dictalm] downloading $MODEL (stall watchdog: ${STALL_SECS}s, retries: $MAX_RETRIES)"

attempt=0
while [ "$attempt" -lt "$MAX_RETRIES" ]; do
    attempt=$((attempt + 1))
    echo "[fetch-dictalm] attempt $attempt/$MAX_RETRIES — starting from $(cache_size_mb)MB"

    "$PY" "$HERE/_fetch_dictalm.py" > /tmp/dictalm_dl.log 2>&1 &
    dl_pid=$!

    last_size=$(cache_size_mb)
    stalled_for=0
    while kill -0 "$dl_pid" 2>/dev/null; do
        sleep 5
        cur_size=$(cache_size_mb)
        if [ "$cur_size" != "$last_size" ]; then
            echo "[fetch-dictalm] progress: ${cur_size}MB"
            last_size=$cur_size
            stalled_for=0
        else
            stalled_for=$((stalled_for + 5))
            if [ "$stalled_for" -ge "$STALL_SECS" ]; then
                echo "[fetch-dictalm] stalled at ${cur_size}MB for ${stalled_for}s — killing and retrying"
                kill "$dl_pid" 2>/dev/null
                sleep 2
                break
            fi
        fi
    done

    wait "$dl_pid" 2>/dev/null
    exit_code=$?
    if [ "$exit_code" -eq 0 ]; then
        echo "[fetch-dictalm] download complete ($(cache_size_mb)MB) after $attempt attempt(s)"
        break
    fi
    echo "[fetch-dictalm] attempt $attempt failed/stalled (exit $exit_code) — retrying"
done

if [ "$attempt" -ge "$MAX_RETRIES" ]; then
    echo "[fetch-dictalm] gave up after $MAX_RETRIES attempts — see /tmp/dictalm_dl.log"
    exit 1
fi

echo "[fetch-dictalm] converting to MLX + quantizing -> $MLX_OUT"
"$PY" -m mlx_lm convert --hf-path "$MLX_OUT.hf-src" -q --mlx-path "$MLX_OUT"
echo "[fetch-dictalm] done -> $MLX_OUT"
