#!/usr/bin/env python3
"""Phase 2+3 (Hebrew-anchored) — embed each distinct Hebrew clause (the per-occurrence
CONTEXT) with a local model. THE LONG BATCH; run it on the Mac GPU. No Cloudflare/API quota.

Default output (resources/occurrences/context_emb.npz, bge-m3) feeds cluster_senses_hebrew.py,
which decides sense identity from HEBREW usage — bge-m3 is multilingual, so it embeds the Hebrew
directly. That file is PRODUCTION input to a deployed feature — this script never overwrites it
except with the exact default model, so experiments (e.g. --pooled BEREL) can't clobber it by
accident; anything else auto-suffixes the output filename by model id.

  shoresh/.venv/bin/python bcv-RAG/scripts/embed_context.py [--model BAAI/bge-m3] [--batch 64]

  # BEREL (or any other masked-LM, non-sentence-transformers model) — mean-pooled, same technique
  # already proven in shoresh/embed_eval/spike.py's PooledEncoder (5.5x separation over bge-m3-style
  # multilingual baselines on Hebrew word-sense discrimination). Writes to a model-suffixed file,
  # e.g. resources/occurrences/context_emb__dicta-il_BEREL_3.0.npz — never touches the default.
  shoresh/.venv/bin/python bcv-RAG/scripts/embed_context.py --model dicta-il/BEREL_3.0 --pooled

Resumable-friendly: re-running just recomputes (the cluster step is the cheap, tunable part).
~78k clauses; minutes on MPS, longer on CPU. Pair with build_lex_occurrences.py (context col).
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
OCC = ROOT / "resources/occurrences/hbo.db"
OUT_DIR = ROOT / "resources/occurrences"
DEFAULT_MODEL = "BAAI/bge-m3"


class PooledEncoder:
    """Masked-LM encoder + mean pooling (for BEREL and other non-sentence-transformers encoders) —
    same technique as shoresh/embed_eval/spike.py's PooledEncoder, duplicated here rather than
    imported since that module lives under shoresh/ (a different package root than bcv-RAG/scripts/)."""

    def __init__(self, model_id: str):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.torch = torch
        # spike.py's original (53-verse eval) never needed a device — CPU was fine at that scale.
        # At ~78k clauses that's the difference between minutes and hours, so place on MPS if available.
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.tok = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModel.from_pretrained(model_id).to(self.device)
        self.model.eval()
        print(f"PooledEncoder: {model_id} on {self.device}", file=sys.stderr)

    def encode(self, texts: list[str], batch_size: int = 32, **_kw) -> np.ndarray:
        torch = self.torch
        out = []
        with torch.no_grad():
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                enc = self.tok(batch, padding=True, truncation=True, max_length=128,
                               return_tensors="pt").to(self.device)
                hidden = self.model(**enc).last_hidden_state
                mask = enc["attention_mask"].unsqueeze(-1).float()
                pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
                pooled = torch.nn.functional.normalize(pooled, dim=1)
                out.extend(pooled.cpu().tolist())
                if i % (batch_size * 20) == 0:
                    print(f"  {i}/{len(texts)}", file=sys.stderr)
        return np.array(out, dtype="float32")


def _default_out_path(model_id: str) -> Path:
    if model_id == DEFAULT_MODEL:
        return OUT_DIR / "context_emb.npz"
    slug = re.sub(r"[^A-Za-z0-9]+", "_", model_id)
    return OUT_DIR / f"context_emb__{slug}.npz"


def main() -> None:
    argv = sys.argv[1:]
    model_id = argv[argv.index("--model") + 1] if "--model" in argv else DEFAULT_MODEL
    batch = int(argv[argv.index("--batch") + 1]) if "--batch" in argv else 64
    pooled = "--pooled" in argv
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else _default_out_path(model_id)

    if not OCC.exists():
        sys.exit(f"no sidecar: {OCC} (run build_lex_occurrences.py first)")
    con = sqlite3.connect(OCC)
    contexts = [r[0] for r in con.execute(
        "SELECT DISTINCT context FROM occurrence WHERE context IS NOT NULL AND context != ''")]
    con.close()
    if not contexts:
        sys.exit("no contexts — regenerate the sidecar with the `context` column first")

    kind = "pooled masked-LM" if pooled else "sentence-transformers"
    print(f"embedding {len(contexts)} distinct Hebrew clauses with {model_id} ({kind}, local) …",
          file=sys.stderr)
    if pooled:
        model = PooledEncoder(model_id)
        vecs = model.encode(contexts, batch_size=batch)
    else:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_id)
        vecs = model.encode(contexts, normalize_embeddings=True, batch_size=batch,
                            show_progress_bar=True).astype("float32")
    np.savez(out, contexts=np.array(contexts, dtype=object), vectors=vecs)
    print(f"wrote {out.relative_to(ROOT)}: {vecs.shape}"
          + ("" if out.name == "context_emb.npz" else " (experiment — not the production file)"),
          file=sys.stderr)


if __name__ == "__main__":
    main()
