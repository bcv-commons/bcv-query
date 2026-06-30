#!/usr/bin/env python3
"""Phase 2+3 (Hebrew-anchored) — embed each distinct Hebrew clause (the per-occurrence
CONTEXT) with local bge-m3. THE LONG BATCH; run it on the Mac GPU. No Cloudflare/API quota.

Output (resources/occurrences/context_emb.npz) feeds cluster_senses_hebrew.py, which decides
sense identity from HEBREW usage — bge-m3 is multilingual, so it embeds the Hebrew directly.

  shoresh/.venv/bin/python bcv-RAG/scripts/embed_context.py [--model BAAI/bge-m3] [--batch 64]

Resumable-friendly: re-running just recomputes (the cluster step is the cheap, tunable part).
~78k clauses; minutes on MPS, longer on CPU. Pair with build_lex_occurrences.py (context col).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
OCC = ROOT / "resources/occurrences/hbo.db"
OUT = ROOT / "resources/occurrences/context_emb.npz"


def main() -> None:
    argv = sys.argv[1:]
    model_id = argv[argv.index("--model") + 1] if "--model" in argv else "BAAI/bge-m3"
    batch = int(argv[argv.index("--batch") + 1]) if "--batch" in argv else 64

    if not OCC.exists():
        sys.exit(f"no sidecar: {OCC} (run build_lex_occurrences.py first)")
    con = sqlite3.connect(OCC)
    contexts = [r[0] for r in con.execute(
        "SELECT DISTINCT context FROM occurrence WHERE context IS NOT NULL AND context != ''")]
    con.close()
    if not contexts:
        sys.exit("no contexts — regenerate the sidecar with the `context` column first")

    print(f"embedding {len(contexts)} distinct Hebrew clauses with {model_id} (local) …",
          file=sys.stderr)
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(model_id)
    vecs = model.encode(contexts, normalize_embeddings=True, batch_size=batch,
                        show_progress_bar=True).astype("float32")
    np.savez(OUT, contexts=np.array(contexts, dtype=object), vectors=vecs)
    print(f"wrote {OUT.relative_to(ROOT)}: {vecs.shape} — now run cluster_senses_hebrew.py",
          file=sys.stderr)


if __name__ == "__main__":
    main()
