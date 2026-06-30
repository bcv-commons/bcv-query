#!/usr/bin/env python3
"""Phase 1 (Step 2) — add lex/stem tags to morphology chunks from the occurrence sidecar.

For each verse-level morphology chunk in index.db, look up its distinct lexemes and verbal
stems from resources/occurrences/hbo.db (built by build_lex_occurrences.py) and add tags:
  lex:<lexid>          e.g. lex:QDC[      → homograph-precise (separates what Strong's merges)
  stem:<binyan>        e.g. stem:hif      → any verb in that stem
  lexstem:<lex>.<stem> e.g. lexstem:QDC[.hif → THIS lexeme in THIS binyan (the precise win)

Pure INSERTs into the tags table — no re-chunk, no re-embed. Idempotent (PK doc_id,tag) and
reversible (--revert deletes them). The `sense:` layer (Phase 3) will add tags the same way.

  python bcv-RAG/scripts/tag_lex_occurrences.py [path/to/index.db] [--revert]
"""
from __future__ import annotations

import collections
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OCC = ROOT / "resources/occurrences/hbo.db"
DEFAULT_IDX = ROOT / "bcv-RAG/indexer/index.db"


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    revert = "--revert" in sys.argv
    idx_path = Path(args[0]) if args else DEFAULT_IDX
    if not idx_path.exists():
        sys.exit(f"no index: {idx_path}")
    idx = sqlite3.connect(idx_path)

    if revert:
        n = idx.execute("DELETE FROM tags WHERE tag LIKE 'lex:%' OR tag LIKE 'stem:%' "
                        "OR tag LIKE 'lexstem:%'").rowcount
        idx.commit()
        print(f"reverted {n} lex/stem/lexstem tags from {idx_path.name}")
        return

    if not OCC.exists():
        sys.exit(f"no sidecar: {OCC} (run build_lex_occurrences.py first)")

    # 1. ref → distinct lex / stem / (lex,stem) from the sidecar
    occ = sqlite3.connect(OCC)
    ref_lex = collections.defaultdict(set)
    ref_stem = collections.defaultdict(set)
    ref_ls = collections.defaultdict(set)
    for ref, lex, stem in occ.execute("SELECT ref, lex, stem FROM occurrence WHERE lex!=''"):
        ref_lex[ref].add(lex)
        if stem:
            ref_stem[ref].add(stem)
            ref_ls[ref].add(f"{lex}.{stem}")
    occ.close()

    # 2. single-verse morphology chunks → their verse ref
    chunks = idx.execute(
        "SELECT p.doc_id, p.start_bbcccvvv FROM passage_refs p "
        "JOIN tags t ON t.doc_id=p.doc_id AND t.tag='kind:morphology' "
        "WHERE p.start_bbcccvvv=p.end_bbcccvvv").fetchall()

    inserts = []
    tagged = 0
    for doc_id, ref in chunks:
        before = len(inserts)
        for lx in ref_lex.get(ref, ()):
            inserts.append((doc_id, f"lex:{lx}"))
        for st in ref_stem.get(ref, ()):
            inserts.append((doc_id, f"stem:{st}"))
        for ls in ref_ls.get(ref, ()):
            inserts.append((doc_id, f"lexstem:{ls}"))
        if len(inserts) > before:
            tagged += 1

    idx.executemany("INSERT OR IGNORE INTO tags(doc_id, tag) VALUES (?,?)", inserts)
    idx.commit()
    nlex = idx.execute("SELECT count(*) FROM tags WHERE tag LIKE 'lex:%'").fetchone()[0]
    nstem = idx.execute("SELECT count(*) FROM tags WHERE tag LIKE 'stem:%'").fetchone()[0]
    nls = idx.execute("SELECT count(*) FROM tags WHERE tag LIKE 'lexstem:%'").fetchone()[0]
    idx.close()
    print(f"{idx_path.name}: {len(chunks)} morphology chunks, {tagged} matched a verse "
          f"→ tags now: {nlex} lex, {nstem} stem, {nls} lexstem")


if __name__ == "__main__":
    main()
