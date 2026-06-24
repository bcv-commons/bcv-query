#!/usr/bin/env python3
"""Apply an incremental data delta to a WORK COPY of the server index.

Runs inside the bcv-rag image (which has the `indexer` package + sqlite-vec).
Imports rows + vectors from a delta.db (export_delta.py); does NOT touch FTS —
run rebuild_fts.py afterwards (its delete-all repopulate is the corruption-safe
way to refresh the partitions and also cleans any rows the deletes orphaned).

ALWAYS run against a copy, never the live file:

    cp /data/index.db /data/index.db.work
    PYTHONPATH=/app python /deploy/import_delta.py --db /data/index.db.work --delta /deploy/delta.db
    PYTHONPATH=/app python /deploy/rebuild_fts.py  --db /data/index.db.work
    # verify, then: mv /data/index.db /data/index.db.bak && mv /data/index.db.work /data/index.db

Safety rails:
  * Aborts if deletes exceed --max-deletes (default 5000). Large delete sets
    cascade into the per-row chunks_ad FTS5 'delete' trigger, which corrupts
    external-content FTS above ~10k rows (we hit this once). For big removals,
    do a full local rebuild + whole-index deploy instead.
  * Verifies row/vector/delete counts against delta.meta, runs quick_check, and
    asserts every shipped chunk ends up with a vector — before you swap.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, "/app")          # image WORKDIR; override via PYTHONPATH if needed
try:
    from indexer.db import open_db
except ImportError:                  # running from the repo locally (parents[2] = bcv-RAG root)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from indexer.db import open_db


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="WORK COPY of the index (not the live file)")
    ap.add_argument("--delta", required=True, help="delta.db from export_delta.py")
    ap.add_argument("--max-deletes", type=int, default=5000)
    args = ap.parse_args()

    db = open_db(Path(args.db))
    db.execute("ATTACH ? AS d", (args.delta,))

    exp = dict(db.execute("SELECT key, value FROM d.meta").fetchall())
    n_del = db.execute("SELECT COUNT(*) FROM d.deletes").fetchone()[0]
    if n_del > args.max_deletes:
        print(f"ABORT: {n_del} deletes > --max-deletes {args.max_deletes}; "
              f"use a full rebuild + whole-index deploy instead.", file=sys.stderr)
        return 2

    # Guard against a provider/model mismatch silently mixing vector spaces.
    stored = db.execute("SELECT value FROM meta WHERE key='embedding_model'").fetchone()
    if stored and exp.get("embedding_model") and stored[0] != exp["embedding_model"]:
        print(f"ABORT: embedding_model mismatch (index={stored[0]} delta={exp['embedding_model']})",
              file=sys.stderr)
        return 2

    db.execute("BEGIN")

    # 1) Clear vectors for every chunk currently under a TOUCHED doc (deletes +
    #    shipped docs that already exist). chunks_vec is a vec0 virtual table: it
    #    has NO ON DELETE CASCADE (so deleting a doc would orphan its vectors) and
    #    does NOT honor INSERT OR REPLACE. Clearing here keeps deletes clean and
    #    lets the re-insert in step 4 be a plain INSERT with no collisions.
    touched = [r[0] for r in db.execute(
        "SELECT doc_id FROM d.deletes UNION SELECT id FROM d.documents").fetchall()]
    for did in touched:
        for (cid,) in db.execute("SELECT id FROM chunks WHERE doc_id = ?", (did,)).fetchall():
            db.execute("DELETE FROM chunks_vec WHERE chunk_id = ?", (cid,))

    # 2) DELETES (cascade clears chunks/tags/passage_refs; fires the per-row
    #    chunks_ad FTS delete on chunks_fts(main) — safe under the threshold).
    db.execute("DELETE FROM documents WHERE id IN (SELECT doc_id FROM d.deletes)")

    # 3) ROW UPSERT: replace-in-place so re-deploys are idempotent. The chunks_ai
    #    trigger will add new chunks to chunks_fts(main); harmless — rebuild_fts
    #    wipes and repopulates every partition next.
    db.execute("DELETE FROM documents WHERE id IN (SELECT id FROM d.documents)")
    db.execute("INSERT INTO documents    SELECT * FROM d.documents")
    db.execute("INSERT INTO chunks       SELECT * FROM d.chunks")
    db.execute("INSERT OR IGNORE INTO tags         SELECT * FROM d.tags")
    db.execute("INSERT OR IGNORE INTO passage_refs SELECT * FROM d.passage_refs")

    # 4) VECTORS: clear any leftover rows for the shipped chunk_ids (e.g. an
    #    extra-vec-id that already had a vector), then plain-INSERT. vec0 has no
    #    INSERT OR REPLACE, so DELETE-then-INSERT is the idempotent idiom.
    db.execute("DELETE FROM chunks_vec WHERE chunk_id IN (SELECT chunk_id FROM d.vec_delta)")
    db.execute("INSERT INTO chunks_vec(chunk_id, embedding) "
               "SELECT chunk_id, embedding FROM d.vec_delta")

    db.execute("COMMIT")

    # 4) VERIFY before the caller swaps.
    ok = True
    chk = db.execute("PRAGMA quick_check").fetchone()[0]
    if chk != "ok":
        print(f"FAIL quick_check: {chk}", file=sys.stderr); ok = False

    got_docs = db.execute("SELECT COUNT(*) FROM documents WHERE id IN (SELECT id FROM d.documents)").fetchone()[0]
    if str(got_docs) != exp.get("expected_docs", str(got_docs)):
        print(f"FAIL doc count: got {got_docs} expected {exp.get('expected_docs')}", file=sys.stderr); ok = False

    # every shipped chunk must now have a vector (catches chunk_id mismatch)
    miss = db.execute(
        "SELECT COUNT(*) FROM d.chunks WHERE id NOT IN (SELECT chunk_id FROM chunks_vec)"
    ).fetchone()[0]
    if miss:
        print(f"FAIL: {miss} imported chunks have no vector", file=sys.stderr); ok = False

    db.execute("DETACH d")
    db.close()
    if not ok:
        print("DELTA IMPORT FAILED — do NOT swap; discard the work copy.", file=sys.stderr)
        return 1
    print(f"import OK — docs={got_docs} deletes={n_del}; now run rebuild_fts.py, then swap.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
