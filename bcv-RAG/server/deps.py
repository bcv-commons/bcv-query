"""FastAPI dependency: shared SQLite connection with sqlite-vec loaded.

A single process-lifetime connection is shared across all requests so that
SQLite's page cache (which can hold gigabytes of hot index pages) survives
between requests. On a 4 GB index, per-request connections produce cold-cache
SQL that takes 5-10× longer than warm-cache SQL for range and FTS queries.

Thread-safety: uvicorn runs a single worker process with one event-loop
thread. Sync dependencies are resolved on threadpool workers, but SQLite
`check_same_thread=False` + WAL mode (readers don't block each other) means
sharing the connection is safe as long as we never issue concurrent writes,
which we don't during serving.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterator

from indexer.db import open_db

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "indexer" / "index.db"

_shared_db: sqlite3.Connection | None = None


def db_path() -> Path:
    """Resolve the index database path. Set INDEX_DB_PATH to override."""
    explicit = os.environ.get("INDEX_DB_PATH")
    if explicit:
        return Path(explicit)
    return DEFAULT_DB


def get_shared_db() -> sqlite3.Connection:
    """Return (or lazily create) the process-lifetime shared DB connection."""
    global _shared_db
    if _shared_db is None:
        _shared_db = open_db(db_path())
        # Large page cache so hot index pages survive between requests.
        # 10 000 pages × 4 096 B ≈ 40 MB; SQLite default is only 2 MB.
        _shared_db.execute("PRAGMA cache_size = -65536")  # 64 MB in KiB units
    return _shared_db


def get_db() -> Iterator[sqlite3.Connection]:
    """Yield the shared connection (kept alive for the process lifetime)."""
    yield get_shared_db()
