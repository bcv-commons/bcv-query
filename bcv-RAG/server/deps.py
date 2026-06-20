"""FastAPI dependency: per-request SQLite connection with sqlite-vec loaded."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterator

from indexer.db import open_db

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "indexer" / "index.db"


def db_path() -> Path:
    """Resolve the index database path. Set INDEX_DB_PATH to override."""
    explicit = os.environ.get("INDEX_DB_PATH")
    if explicit:
        return Path(explicit)
    return DEFAULT_DB


def get_db() -> Iterator[sqlite3.Connection]:
    """Open a fresh SQLite connection per request (avoids thread-safety issues)."""
    db = open_db(db_path())
    try:
        yield db
    finally:
        db.close()
