#!/usr/bin/env python3
"""Build the structured index from a source directory.

Usage:
    python3 -m indexer.build --source path/to/repo
    python3 -m indexer.build --source path/to/repo --db indexer/index.db --ext md

Writes (or updates) a SQLite database with the schema in indexer/schema.sql.
Idempotent: re-running on the same source replaces each document's rows
(documents.id is content-derived; ON DELETE CASCADE handles the rest).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

# Allow running both `python3 -m indexer.build` and `python3 indexer/build.py`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from indexer.adapters import MarkdownAdapter  # noqa: E402
from indexer.adapters.base import Adapter, Document  # noqa: E402
from indexer.db import open_db  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
SCHEMA_VERSION = "2"
DEFAULT_DB = Path(__file__).resolve().parent / "index.db"


def init_schema(db: sqlite3.Connection) -> None:
    db.executescript(SCHEMA_PATH.read_text())
    db.commit()


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def write_document(db: sqlite3.Connection, doc: Document) -> None:
    db.execute("DELETE FROM documents WHERE id = ?", (doc.id,))  # cascades
    db.execute(
        "INSERT INTO documents(id, source_path, source_sha, title, metadata, indexed_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (doc.id, doc.source_path, doc.source_sha, doc.title,
         json.dumps(doc.metadata, ensure_ascii=False), int(time.time())),
    )
    for i, body in enumerate(doc.chunks):
        db.execute(
            "INSERT INTO chunks(id, doc_id, chunk_index, body) VALUES (?, ?, ?, ?)",
            (f"{doc.id}:{i:04d}", doc.id, i, body),
        )
    for s, e in doc.passage_refs:
        db.execute(
            "INSERT OR IGNORE INTO passage_refs(doc_id, start_bbcccvvv, end_bbcccvvv) "
            "VALUES (?, ?, ?)",
            (doc.id, s, e),
        )
    for tag in set(doc.tags):
        db.execute(
            "INSERT OR IGNORE INTO tags(doc_id, tag) VALUES (?, ?)",
            (doc.id, tag),
        )


def select_adapter(ext: str) -> Adapter:
    if ext.lower() in {"md", "markdown", "mdx"}:
        return MarkdownAdapter()
    raise ValueError(f"no adapter registered for *.{ext}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, type=Path, help="root directory to index")
    parser.add_argument("--db", default=DEFAULT_DB, type=Path, help="SQLite output path")
    parser.add_argument("--ext", default="md", help="file extension to index (default: md)")
    parser.add_argument("--reset", action="store_true", help="delete existing db before building")
    args = parser.parse_args()

    from indexer.env import load_env  # local: avoid circular at module load
    load_env()

    if not args.source.exists() or not args.source.is_dir():
        print(f"source dir not found: {args.source}", file=sys.stderr)
        return 2

    if args.reset and args.db.exists():
        args.db.unlink()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    db = open_db(args.db)
    # schema.sql is `CREATE … IF NOT EXISTS` throughout, so running it
    # unconditionally lets additive schema bumps land on existing indexes
    # without requiring --reset (which would wipe content).
    init_schema(db)
    db.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        ("schema_version", SCHEMA_VERSION),
    )

    adapter = select_adapter(args.ext)
    files = sorted(args.source.rglob(f"*.{args.ext}"))
    print(f"indexing {len(files)} *.{args.ext} files from {args.source}", file=sys.stderr)

    skipped = 0
    for path in files:
        try:
            doc = adapter.parse(path, args.source)
        except Exception as e:
            print(f"  skip {path.relative_to(args.source)}: {e}", file=sys.stderr)
            skipped += 1
            continue
        if doc is None or not doc.chunks:
            skipped += 1
            continue
        doc.source_sha = file_sha(path)
        write_document(db, doc)

    db.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        ("source_root", str(args.source.resolve())),
    )
    db.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        ("indexed_at", str(int(time.time()))),
    )
    db.commit()

    # Clean up orphan vectors: chunks_vec rows whose chunks row no longer
    # exists (e.g., after re-staging removed source files). Without this,
    # vector_search can return chunk_ids that resolve to no card and quietly
    # shrink effective top_k.
    try:
        orphan_rows = db.execute(
            "SELECT chunk_id FROM chunks_vec "
            "WHERE chunk_id NOT IN (SELECT id FROM chunks)"
        ).fetchall()
        if orphan_rows:
            db.executemany("DELETE FROM chunks_vec WHERE chunk_id = ?", orphan_rows)
            db.commit()
    except sqlite3.OperationalError:
        # chunks_vec doesn't exist yet (first build before any embed run) — fine.
        pass

    # Backfill documents_fts if it's empty but documents has rows. Triggers
    # populate it on every INSERT, so this only matters when documents_fts
    # was added to a pre-existing index without re-staging.
    try:
        fts_count = db.execute("SELECT COUNT(*) FROM documents_fts").fetchone()[0]
        docs_count = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        if fts_count == 0 and docs_count > 0:
            db.execute("INSERT INTO documents_fts(documents_fts) VALUES('rebuild')")
            db.commit()
    except sqlite3.OperationalError:
        pass

    # Route v3 expansion-content chunks into per-kind FTS5 tables, and
    # purge them from chunks_fts. See schema.sql comment +
    # docs/expansion-plan.md for the design context. Each per-kind FTS
    # isolates BM25 stats so the larger expansion corpus doesn't re-rank
    # v2 retrieval results.
    #
    # Add a new entry here + a CREATE VIRTUAL TABLE in schema.sql whenever
    # a new v3 ingest module lands.
    V3_KIND_TO_FTS: dict[str, str] = {
        "kind:lexicon":          "chunks_fts_lexicon",
        "kind:morphology":       "chunks_fts_morphology",
        "kind:bible":            "chunks_fts_bible",
        "kind:section-heading":  "chunks_fts_section_heading",
        "kind:video-transcript": "chunks_fts_video_transcript",
        # Pending stage-2 sources — uncomment once their chunks land:
        # "kind:dictionary":       "chunks_fts_dictionary",
        # "kind:ane-context":      "chunks_fts_ane_context",
        # "kind:passage-cluster":  "chunks_fts_passage_cluster",
    }

    # Per-kind FTS: wipe + bulk-INSERT-FROM-SELECT. A single SQL statement per
    # FTS table is much faster (and avoids the per-row 'delete' command,
    # which has caused intermittent FTS5 corruption when run on >10k rows
    # against external-content tables).
    for kind_tag, fts_table in V3_KIND_TO_FTS.items():
        try:
            db.execute(f"INSERT INTO {fts_table}({fts_table}) VALUES('delete-all')")
        except sqlite3.OperationalError as e:
            print(f"  build: skipping {fts_table} ({e}); add it to schema.sql", file=sys.stderr)
            continue
        db.execute(
            f"INSERT INTO {fts_table}(rowid, body) "
            f"SELECT chunks.rowid, chunks.body FROM chunks "
            f"JOIN tags ON tags.doc_id = chunks.doc_id WHERE tags.tag = ?",
            (kind_tag,),
        )

    # Aquifer breadth → chunks_fts_aquifer, isolated by RESOURCE (it overlaps
    # Door43 kinds). Keeps the large multilingual study corpus out of the main
    # chunks_fts BM25 stats. Retrieved via aquifer_search.
    try:
        db.execute("INSERT INTO chunks_fts_aquifer(chunks_fts_aquifer) VALUES('delete-all')")
        db.execute(
            "INSERT INTO chunks_fts_aquifer(rowid, body) "
            "SELECT chunks.rowid, chunks.body FROM chunks "
            "JOIN tags ON tags.doc_id = chunks.doc_id WHERE tags.tag = 'resource:aquifer'"
        )
    except sqlite3.OperationalError as e:
        print(f"  build: skipping chunks_fts_aquifer ({e}); add it to schema.sql", file=sys.stderr)

    # chunks_fts: wipe + repopulate with v2-only content (excluding the v3
    # per-kind tables AND the resource-isolated Aquifer corpus).
    v3_kinds = list(V3_KIND_TO_FTS.keys())
    placeholders = ",".join("?" * len(v3_kinds))
    db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('delete-all')")
    db.execute(
        "INSERT INTO chunks_fts(rowid, body) "
        "SELECT chunks.rowid, chunks.body FROM chunks "
        "WHERE chunks.doc_id NOT IN ("
        f" SELECT DISTINCT doc_id FROM tags WHERE tag IN ({placeholders}) "
        " OR tag = 'resource:aquifer'"
        ")",
        v3_kinds,
    )
    db.commit()

    counts = {
        "documents": db.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        "chunks":    db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
        "passages":  db.execute("SELECT COUNT(*) FROM passage_refs").fetchone()[0],
        "tags":      db.execute("SELECT COUNT(*) FROM tags").fetchone()[0],
        "skipped":   skipped,
    }
    print(json.dumps(counts, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
