#!/usr/bin/env python3
"""Download DictaLM-3.0-1.7B-Instruct via huggingface_hub's Python API directly (not the CLI, whose
module path has proven fragile across huggingface_hub versions). Called by fetch_dictalm.sh, which
wraps this with a stall watchdog + retry loop — snapshot_download() itself has internal resume support
(safe to just re-run on failure), but was observed to occasionally hang indefinitely rather than raise,
so the external watchdog (kills + retries the whole process) is the actual reliability mechanism.
"""
import os
import sys

# FIXED 2026-08: HF_XET_HIGH_PERFORMANCE made things worse, not better — every retry hung at the exact
# same 16MB mark (right where the small config/tokenizer files end and the first large safetensors
# shard would start transferring via Xet), which is the signature of Xet's connection pattern getting
# stuck on this network (proxy/firewall), not genuine slowness — the byte count never moved even
# slightly, across many retries. Disabling Xet entirely and falling back to the plain, universally-
# compatible HTTP downloader instead.
os.environ["HF_HUB_DISABLE_XET"] = "1"

from huggingface_hub import snapshot_download  # noqa: E402

MODEL = "dicta-il/DictaLM-3.0-1.7B-Instruct"
LOCAL_DIR = "/tmp/dictalm-1.7b-mlx.hf-src"

if __name__ == "__main__":
    path = snapshot_download(repo_id=MODEL, local_dir=LOCAL_DIR)
    print(f"[fetch-dictalm] snapshot at {path}", file=sys.stderr)
