#!/usr/bin/env python3
"""One-time cleanup: remove STALE old Door43 docs left after rebuilding the
Door43 source with a different --source root than the original index.

The original index was built with `indexer.build --source ingest/_staging`
(→ source_path 'door43/tw/kt/love.md'). The --all-books rebuild used
`--source ingest/_staging/door43` (→ source_path 'tw/kt/love.md'). Different
path → different content-derived doc id → the new docs were ADDED alongside the
old ones instead of replacing them. The new docs are correct (they carry the
strongs: tags + full book coverage); the old 'door43/%' docs are stale dupes.

This deletes the stale 'door43/%' docs (cascades to chunks/tags/passages and,
via triggers, FTS) and cleans the orphaned chunks_vec rows. Run AFTER the embed
step finishes (never concurrently — it writes the same DB).

  python -m scripts.prune_stale_door43            # dry run (counts only)
  python -m scripts.prune_stale_door43 --apply    # actually delete
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from indexer.db import open_db  # noqa: E402  (FK ON + sqlite-vec loaded)

DB = Path(__file__).resolve().parent.parent / "indexer" / "index.db"
STALE = "door43/%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="delete (default: dry run)")
    args = ap.parse_args()
    db = open_db(DB)

    n_docs = db.execute("SELECT COUNT(*) FROM documents WHERE source_path LIKE ?", (STALE,)).fetchone()[0]
    chunk_ids = [r[0] for r in db.execute(
        "SELECT id FROM chunks WHERE doc_id IN (SELECT id FROM documents WHERE source_path LIKE ?)",
        (STALE,))]
    print(f"stale docs (source_path '{STALE}'): {n_docs}")
    print(f"their chunks (→ chunks_vec to prune): {len(chunk_ids)}")
    # sanity: confirm we keep the good Love doc
    love = db.execute("SELECT source_path FROM documents d JOIN tags t "
                      "ON t.doc_id=d.id AND t.tag='strongs:G0026' "
                      "WHERE d.title='TW — Love (kt)'").fetchall()
    print(f"TW Love docs that carry strongs:G0026 (must survive): {[r[0] for r in love]}")

    if not args.apply:
        print("\nDRY RUN — re-run with --apply to delete.")
        return 0

    db.execute("DELETE FROM documents WHERE source_path LIKE ?", (STALE,))  # cascades + FTS triggers
    db.executemany("DELETE FROM chunks_vec WHERE chunk_id = ?", [(c,) for c in chunk_ids])
    db.commit()
    left = db.execute("SELECT COUNT(*) FROM documents WHERE source_path LIKE ?", (STALE,)).fetchone()[0]
    dup = db.execute("SELECT COUNT(*) FROM documents WHERE title='TW — Love (kt)'").fetchone()[0]
    print(f"\ndeleted. remaining 'door43/%' docs: {left} (expect 0)")
    print(f"'TW — Love (kt)' docs now: {dup} (expect 1, the strongs-tagged one)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
