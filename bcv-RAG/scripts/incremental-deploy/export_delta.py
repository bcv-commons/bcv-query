#!/usr/bin/env python3
"""Export an incremental DATA delta from the local (GPU-embedded) index.

The hybrid incremental-deploy path: instead of rsyncing the whole 6.6 GB
index.db, we ship only what changed since the server's copy — the new/changed
ROWS plus the NEW VECTORS — as a small SQLite `delta.db`. The server imports it
(import_delta.py) and rebuilds FTS (rebuild_fts.py); it never re-builds rows, so
chunk_ids cannot diverge from the vectors (the rows come straight from the
machine that embedded them).

A delta has three independently-scoped parts:

  * ROWS    — full documents/chunks/tags/passage_refs for docs matching
              --rows-where. Use for NEW or CHANGED docs (their rows aren't on
              the server, or differ).
  * VECTORS — chunks_vec blobs for: every chunk of the --rows-where docs, PLUS
              any chunk_id listed in --extra-vec-ids-file. The extra-ids file is
              how you ship vectors for docs whose ROWS are already on the server
              (e.g. a previously-deployed-but-unembedded backlog) without
              re-shipping their rows.
  * DELETES — doc_ids to remove on the server (--deletes-file). Staging-based
              builds only ADD; deletions (e.g. the retired pilot docs) must be
              expressed explicitly.

Example (the English-aquifer round + the 227k unembedded backlog):

    python export_delta.py \
      --db indexer/index.db \
      --rows-where "id IN (SELECT doc_id FROM tags WHERE tag='resource:aquifer')
                    AND id IN (SELECT doc_id FROM tags WHERE tag='lang:en')" \
      --extra-vec-ids-file /tmp/backlog_chunk_ids.txt \
      --deletes-file /tmp/pilot_doc_ids.txt \
      --out /tmp/delta.db

`--rows-where` is a raw SQL predicate over `documents` — keep it under your own
control (this is an internal op tool, not a public surface).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# Run from anywhere: locate the bcv-RAG package so `indexer.db` (sqlite-vec
# loader) is importable. This file lives at bcv-RAG/scripts/incremental-deploy/,
# so parents[2] is the bcv-RAG root.
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from indexer.db import open_db  # noqa: E402

DELTA_SCHEMA = """
CREATE TABLE documents (
  id TEXT PRIMARY KEY, source_path TEXT, source_sha TEXT,
  title TEXT, metadata TEXT, indexed_at INTEGER);
CREATE TABLE chunks (
  id TEXT PRIMARY KEY, doc_id TEXT, chunk_index INTEGER, body TEXT);
CREATE TABLE tags (doc_id TEXT, tag TEXT);
CREATE TABLE passage_refs (doc_id TEXT, start_bbcccvvv INTEGER, end_bbcccvvv INTEGER);
CREATE TABLE vec_delta (chunk_id TEXT PRIMARY KEY, embedding BLOB);
CREATE TABLE deletes (doc_id TEXT PRIMARY KEY);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _read_ids(path: str | None) -> list[str]:
    if not path:
        return []
    return [ln.strip() for ln in Path(path).read_text().splitlines() if ln.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(REPO / "indexer" / "index.db"), type=str)
    ap.add_argument("--rows-where", default=None,
                    help="SQL predicate over `documents` selecting docs whose ROWS to ship")
    ap.add_argument("--extra-vec-ids-file", default=None,
                    help="newline-delimited chunk_ids to ship vectors for (rows already on server)")
    ap.add_argument("--deletes-file", default=None,
                    help="newline-delimited doc_ids to delete on the server")
    ap.add_argument("--out", required=True, help="output delta.db path")
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists():
        print(f"refusing to overwrite existing {out}", file=sys.stderr)
        return 2

    src = open_db(Path(args.db))          # sqlite-vec loaded → chunks_vec readable
    d = sqlite3.connect(out)
    d.executescript(DELTA_SCHEMA)
    d.commit()
    d.close()
    src.execute("ATTACH ? AS d", (str(out),))

    # ---- ROWS ----
    n_docs = 0
    if args.rows_where:
        where = args.rows_where
        src.execute(f"INSERT INTO d.documents    SELECT * FROM documents     WHERE {where}")
        src.execute(f"INSERT INTO d.chunks       SELECT * FROM chunks        WHERE doc_id IN (SELECT id FROM d.documents)")
        src.execute(f"INSERT INTO d.tags         SELECT * FROM tags          WHERE doc_id IN (SELECT id FROM d.documents)")
        src.execute(f"INSERT INTO d.passage_refs SELECT * FROM passage_refs  WHERE doc_id IN (SELECT id FROM d.documents)")
        n_docs = src.execute("SELECT COUNT(*) FROM d.documents").fetchone()[0]

    # ---- VECTORS: chunks of the shipped rows, plus the extra-ids set ----
    # Vectors for the rows we just shipped:
    src.execute(
        "INSERT OR IGNORE INTO d.vec_delta(chunk_id, embedding) "
        "SELECT cv.chunk_id, cv.embedding FROM chunks_vec cv "
        "WHERE cv.chunk_id IN (SELECT id FROM d.chunks)"
    )
    # Vectors for already-on-server rows (e.g. the backlog):
    extra = _read_ids(args.extra_vec_ids_file)
    for i in range(0, len(extra), 900):       # stay under the 999-variable limit
        batch = extra[i:i + 900]
        ph = ",".join("?" * len(batch))
        src.execute(
            f"INSERT OR IGNORE INTO d.vec_delta(chunk_id, embedding) "
            f"SELECT cv.chunk_id, cv.embedding FROM chunks_vec cv WHERE cv.chunk_id IN ({ph})",
            batch,
        )
    n_vec = src.execute("SELECT COUNT(*) FROM d.vec_delta").fetchone()[0]

    # ---- DELETES ----
    deletes = _read_ids(args.deletes_file)
    src.executemany("INSERT OR IGNORE INTO d.deletes(doc_id) VALUES (?)",
                    [(x,) for x in deletes])

    # ---- meta: expected counts so import_delta can self-check ----
    model = src.execute("SELECT value FROM meta WHERE key='embedding_model'").fetchone()
    for k, v in [("expected_docs", n_docs), ("expected_vectors", n_vec),
                 ("expected_deletes", len(deletes)),
                 ("embedding_model", model[0] if model else "")]:
        src.execute("INSERT OR REPLACE INTO d.meta(key, value) VALUES (?, ?)", (k, str(v)))

    src.commit()
    src.execute("DETACH d")
    src.close()

    print(f"wrote {out}")
    print(f"  documents (rows): {n_docs}")
    print(f"  vectors:          {n_vec}")
    print(f"  deletes:          {len(deletes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
