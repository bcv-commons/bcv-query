"""Database connection helper with sqlite-vec extension loading.

Every callsite that opens `index.db` should go through `open_db()` so that
the sqlite-vec extension is loaded uniformly. If sqlite-vec is unavailable
(missing pip package, system SQLite without extension support), v1 code
paths still work — only vector retrieval is degraded.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def open_db(path: Path | str, *, load_vec: bool = True) -> sqlite3.Connection:
    """Open `path` with FK + WAL + (optionally) sqlite-vec loaded.

    `check_same_thread=False` lets the connection move between threads
    sequentially — needed because FastAPI's sync-dep + async-endpoint
    pattern resolves `Depends(get_db)` in a threadpool worker but then
    uses the connection on the event-loop thread. We never share a single
    connection across CONCURRENT threads, so disabling SQLite's check is
    safe (per-request connections are scoped to a single request).
    """
    db = sqlite3.connect(str(path), check_same_thread=False)
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    if load_vec:
        try:
            import sqlite_vec  # type: ignore
            db.enable_load_extension(True)
            sqlite_vec.load(db)
            db.enable_load_extension(False)
        except (ImportError, AttributeError, sqlite3.OperationalError) as e:
            # Vector layer disabled — v1 retrievers still work.
            print(
                f"  warning: sqlite-vec unavailable ({type(e).__name__}: {e}); "
                f"vector retrieval disabled",
                file=sys.stderr,
            )
    return db


def has_vec(db: sqlite3.Connection) -> bool:
    """Whether sqlite-vec is loaded and usable on this connection."""
    try:
        db.execute("SELECT vec_version()").fetchone()
        return True
    except sqlite3.OperationalError:
        return False
