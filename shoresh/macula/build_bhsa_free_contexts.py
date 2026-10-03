#!/usr/bin/env python3
"""BHSA-free occurrence contexts + embeddings, for testing whether the CC0 semantic-neighbors pack can be
built without any BHSA input (BHSA is non-commercial; the pack is published CC0).

The production pack embeds BHSA clauses (resources/occurrences/hbo.db, built from Context Fabric).
Here each Hebrew content token in lexeme-spine.db (MACULA, CC BY 4.0, WLC text) gets a word-centred
window of up to WINDOW words on each side, bounded by its verse. No clause segmentation is needed, so
no BHSA syntax enters. Windows are embedded with BEREL 3.0 (Apache 2.0), mean-pooled, the same encoder
the production pack uses.

Output (gitignored), shoresh/macula/data/bhsa_free/:
  occurrence.db        occurrence(key, lexeme, strong, gloss, context)
  context_emb_berel.npz  contexts + vectors, the shape build_semantic_neighbors expects

  cd shoresh && .venv/bin/python3 -m macula.build_bhsa_free_contexts
"""
from __future__ import annotations

import argparse
import collections
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPINE = HERE / "lexeme-spine.db"
OUT = HERE / "data" / "bhsa_free"
WINDOW = 6
MODEL = "dicta-il/BEREL_3.0"

_ACCENTS = re.compile(r"[֑-ֽ֯⁠]")


def build_occurrences(out_db: Path) -> list[str]:
    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    verses: dict[tuple, list] = collections.defaultdict(list)
    for book, ch, vs, idx, key, surface, lexeme, strong, gloss, is_content in sp.execute(
            "SELECT book, chapter, verse, idx, key, surface, lexeme, strong, gloss, is_content "
            "FROM spine_words WHERE lexeme LIKE 'hbo:%' ORDER BY book, chapter, verse, idx"):
        verses[(book, ch, vs)].append((key, _ACCENTS.sub("", surface or ""), lexeme, strong, gloss, is_content))

    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()
    db = sqlite3.connect(out_db)
    db.execute("CREATE TABLE occurrence (key TEXT PRIMARY KEY, lexeme TEXT, strong INTEGER, gloss TEXT, context TEXT)")
    rows, contexts = [], set()
    for words in verses.values():
        for i, (key, _surface, lexeme, strong, gloss, is_content) in enumerate(words):
            if not is_content:
                continue
            lo, hi = max(0, i - WINDOW), min(len(words), i + WINDOW + 1)
            ctx = " ".join(w[1] for w in words[lo:hi] if w[1])
            rows.append((key, lexeme, strong, gloss, ctx))
            contexts.add(ctx)
    db.executemany("INSERT INTO occurrence VALUES (?,?,?,?,?)", rows)
    db.commit()
    print(f"[bhsa-free] {len(rows)} content occurrences, {len(contexts)} distinct windows -> {out_db}",
          file=sys.stderr)
    return sorted(contexts)


def embed(contexts: list[str], out_npz: Path, batch: int) -> None:
    sys.path.insert(0, str(ROOT / "bcv-RAG" / "scripts"))
    from embed_context import PooledEncoder
    enc = PooledEncoder(MODEL)
    vecs = enc.encode(contexts, batch_size=batch, max_length=64)
    np.savez(out_npz, contexts=np.array(contexts, dtype=object), vectors=vecs)
    print(f"[bhsa-free] {vecs.shape} -> {out_npz}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch", type=int, default=256)
    args = ap.parse_args()
    contexts = build_occurrences(OUT / "occurrence.db")
    embed(contexts, OUT / "context_emb_berel.npz", args.batch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
