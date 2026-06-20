#!/usr/bin/env python3
"""Query the structured index — three retrieval paths + stats.

Usage:
    python3 -m indexer.query stats
    python3 -m indexer.query fts "justification by faith"
    python3 -m indexer.query passage 45003024 45003025      # Romans 3:24-25
    python3 -m indexer.query tag "keyterm:Justification"
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent / "index.db"


def fts_search(db: sqlite3.Connection, query: str, limit: int = 10) -> list[dict]:
    rows = db.execute(
        """
        SELECT documents.id, documents.title, documents.source_path,
               snippet(chunks_fts, 0, '<<', '>>', '…', 16) AS snippet,
               rank
        FROM chunks_fts
        JOIN chunks    ON chunks_fts.rowid = chunks.rowid
        JOIN documents ON chunks.doc_id    = documents.id
        WHERE chunks_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()
    return [
        {"id": r[0], "title": r[1], "path": r[2], "snippet": r[3], "rank": r[4]}
        for r in rows
    ]


def passage_search(db: sqlite3.Connection, start: int, end: int, limit: int = 50) -> list[dict]:
    """Return docs whose [start, end] passage range overlaps [start, end]."""
    rows = db.execute(
        """
        SELECT DISTINCT documents.id, documents.title, documents.source_path,
                        passage_refs.start_bbcccvvv, passage_refs.end_bbcccvvv
        FROM passage_refs
        JOIN documents ON passage_refs.doc_id = documents.id
        WHERE passage_refs.start_bbcccvvv <= ?
          AND passage_refs.end_bbcccvvv   >= ?
        ORDER BY passage_refs.start_bbcccvvv
        LIMIT ?
        """,
        (end, start, limit),
    ).fetchall()
    return [
        {"id": r[0], "title": r[1], "path": r[2], "passage": [r[3], r[4]]}
        for r in rows
    ]


def tag_search(db: sqlite3.Connection, tag: str, limit: int = 50) -> list[dict]:
    rows = db.execute(
        """
        SELECT documents.id, documents.title, documents.source_path
        FROM tags
        JOIN documents ON tags.doc_id = documents.id
        WHERE tags.tag = ?
        LIMIT ?
        """,
        (tag, limit),
    ).fetchall()
    return [{"id": r[0], "title": r[1], "path": r[2]} for r in rows]


def stats(db: sqlite3.Connection) -> dict:
    out = {
        "documents": db.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        "chunks":    db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
        "passages":  db.execute("SELECT COUNT(*) FROM passage_refs").fetchone()[0],
        "tags":      db.execute("SELECT COUNT(*) FROM tags").fetchone()[0],
        "meta":      dict(db.execute("SELECT key, value FROM meta").fetchall()),
    }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=DEFAULT_DB, type=Path)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fts = sub.add_parser("fts", help="full-text (FTS5) search over chunk bodies")
    p_fts.add_argument("query")
    p_fts.add_argument("--limit", type=int, default=10)

    p_pas = sub.add_parser("passage", help="range overlap on encoded BBCCCVVV refs")
    p_pas.add_argument("start", type=int, help="encoded start, e.g. 45003024 = Rom 3:24")
    p_pas.add_argument("end", type=int)
    p_pas.add_argument("--limit", type=int, default=50)

    p_tag = sub.add_parser("tag", help="exact tag lookup")
    p_tag.add_argument("tag")
    p_tag.add_argument("--limit", type=int, default=50)

    sub.add_parser("stats", help="row counts + meta")

    args = parser.parse_args()

    from indexer.env import load_env
    load_env()

    if not args.db.exists():
        print(f"db not found: {args.db}\nrun: python3 -m indexer.build --source <dir>", file=sys.stderr)
        return 2

    from indexer.db import open_db  # local to avoid circular import at module load
    db = open_db(args.db)

    if args.cmd == "fts":
        out = fts_search(db, args.query, args.limit)
    elif args.cmd == "passage":
        out = passage_search(db, args.start, args.end, args.limit)
    elif args.cmd == "tag":
        out = tag_search(db, args.tag, args.limit)
    else:  # stats
        out = stats(db)

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
