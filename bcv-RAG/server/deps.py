"""FastAPI dependency: a small pool of SQLite connections (sqlite-vec loaded), one request per connection.

FastAPI runs the synchronous routes concurrently on a thread pool. A sqlite3 connection must never be used by two
threads at the same time: its statement cache and cursors interleave, which showed up (2026-10-06, 30 parallel
searches) as `sqlite3.InterfaceError: bad parameter or other API misuse`, `unknown book number: 0`, `'NoneType'
object has no attribute 'split'` and, worse, a request receiving ANOTHER request's rows. Earlier versions shared ONE
process-lifetime connection on the theory that WAL makes this safe "as long as nobody writes"; it does not (the
problem is the shared connection object, not the database file).

So each request borrows a connection exclusively and returns it afterwards. A few long-lived connections (not one per
request) keep SQLite's page cache warm: on a multi-GB index, cold per-request connections made range/FTS queries
5-10x slower. Pool size BTMCP_DB_POOL (default 8) and per-connection cache BTMCP_DB_CACHE_MB (default 16) bound the
memory (8 x 16 MB); a request that waits more than BTMCP_DB_WAIT_S (default 30) gets 503 instead of hanging.
"""
from __future__ import annotations

import os
import queue
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from indexer.db import open_db

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "indexer" / "index.db"

POOL_SIZE = max(1, int(os.environ.get("BTMCP_DB_POOL", "8")))
CACHE_MB = max(2, int(os.environ.get("BTMCP_DB_CACHE_MB", "16")))
WAIT_S = float(os.environ.get("BTMCP_DB_WAIT_S", "30"))

_pool: "queue.LifoQueue[sqlite3.Connection] | None" = None
_pool_lock = threading.Lock()


def db_path() -> Path:
    """Resolve the index database path. Set INDEX_DB_PATH to override."""
    explicit = os.environ.get("INDEX_DB_PATH")
    if explicit:
        return Path(explicit)
    return DEFAULT_DB


def _new_connection() -> sqlite3.Connection:
    conn = open_db(db_path())
    conn.execute(f"PRAGMA cache_size = -{CACHE_MB * 1024}")   # KiB units; SQLite's default is only 2 MB
    return conn


def _get_pool() -> "queue.LifoQueue[sqlite3.Connection]":
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                q: "queue.LifoQueue[sqlite3.Connection]" = queue.LifoQueue(POOL_SIZE)
                for _ in range(POOL_SIZE):
                    q.put(_new_connection())
                _pool = q
    return _pool


@contextmanager
def db_connection() -> Iterator[sqlite3.Connection]:
    """Borrow a connection for the duration of the block; nobody else uses it meanwhile."""
    pool = _get_pool()
    try:
        conn = pool.get(timeout=WAIT_S)
    except queue.Empty:
        from fastapi import HTTPException
        raise HTTPException(503, "database busy, retry shortly", headers={"Retry-After": "2"})
    try:
        yield conn
    finally:
        pool.put(conn)


_startup: sqlite3.Connection | None = None


def get_shared_db() -> sqlite3.Connection:
    """A dedicated connection for startup-time, single-threaded use (building lookup maps, warming caches).

    Not part of the pool and NOT thread-safe: never use it from request handlers or concurrent threads; use
    `db_connection()` / `Depends(get_db)` there."""
    global _startup
    if _startup is None:
        _startup = _new_connection()
    return _startup


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: an exclusively borrowed connection, returned after the request."""
    with db_connection() as conn:
        yield conn
