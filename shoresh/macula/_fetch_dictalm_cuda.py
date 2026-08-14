#!/usr/bin/env python3
"""Smoke-test DictaLM-3.0-1.7B-Instruct via plain transformers + CUDA (Linux/GPU box).

Supersedes fetch_dictalm.sh/_fetch_dictalm.py for this machine — those target MLX (Apple Silicon
only). Loads from a local directory populated by dictalm_curl_download.sh (~/models/), NOT via
transformers' own HF-hub download — that path (and huggingface_hub's snapshot_download, even with
HF_HUB_DISABLE_XET=1) starts a fresh randomly-named .incomplete temp file on every process restart
and can't resume across one, which on this machine's frequent involuntary reboots meant repeated
multi-GB downloads that never finished. Plain `curl -L -C -` against a fixed local filename resumes
correctly across restarts; this script just loads the result.

  .venv/bin/python macula/_fetch_dictalm_cuda.py [--model-dir ~/models/dictalm-3.0-1.7b-instruct]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

DEFAULT_MODEL_DIR = Path("~/models/dictalm-3.0-1.7b-instruct").expanduser()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if not torch.cuda.is_available():
        sys.exit("CUDA not available")

    weights = args.model_dir / "model.safetensors"
    if not weights.exists():
        sys.exit(f"{weights} not found — run dictalm_curl_download.sh first (or pass --model-dir)")

    print(f"[dictalm] loading {args.model_dir} ...", file=sys.stderr)
    t0 = time.time()
    tok = AutoTokenizer.from_pretrained(args.model_dir)
    model = AutoModelForCausalLM.from_pretrained(args.model_dir, torch_dtype=torch.bfloat16)
    model.to("cuda")
    model.eval()
    print(f"[dictalm] loaded in {time.time()-t0:.1f}s, "
          f"GPU mem allocated: {torch.cuda.memory_allocated()/1e9:.2f} GB", file=sys.stderr)

    prompts = [
        ("sanity", "שלום! מי אתה?"),
        ("pair-verify-1",
         "You are a Biblical Hebrew lexicographer. Judge whether these two Strong's-numbered words "
         "are genuinely synonyms in Biblical Hebrew usage. Be strict.\n"
         "Pair: H0157 (love, 'ahev') vs H2617 (kindness, 'chesed')\n"
         "Answer exactly: yes, no, or unsure. One word only."),
        ("pair-verify-2",
         "You are a Biblical Hebrew lexicographer. Judge whether these two Strong's-numbered words "
         "are genuinely synonyms in Biblical Hebrew usage. Be strict.\n"
         "Pair: H8085 (hear, 'shama') vs H7200 (see, 'ra'ah')\n"
         "Answer exactly: yes, no, or unsure. One word only."),
    ]

    for label, prompt in prompts:
        chat = [{"role": "user", "content": prompt}]
        text = tok.apply_chat_template(chat, add_generation_prompt=True, tokenize=False)
        enc = tok(text, return_tensors="pt").to("cuda")
        t0 = time.time()
        with torch.no_grad():
            out = model.generate(**enc, max_new_tokens=60, do_sample=False)
        dt = time.time() - t0
        reply = tok.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)
        print(f"\n--- {label} ({dt:.1f}s) ---")
        print(f"prompt: {prompt!r}")
        print(f"reply:  {reply!r}")

    print(f"\n[dictalm] peak GPU mem during generation: "
          f"{torch.cuda.max_memory_allocated()/1e9:.2f} GB", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
