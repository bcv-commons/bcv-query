"""The SQLite connection pool (server/deps.py): connections are borrowed exclusively, so concurrent requests can
never see each other's rows. Regression for 2026-10-06, when one shared connection returned `bad parameter or
other API misuse`, rows of another request and 500s under 30 parallel searches."""
import concurrent.futures as cf
import importlib
import sqlite3
import threading

import pytest


@pytest.fixture()
def deps(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t(k INTEGER PRIMARY KEY, v TEXT)")
    con.executemany("INSERT INTO t VALUES (?, ?)", [(i, f"value-{i}") for i in range(2000)])
    con.commit(); con.close()
    monkeypatch.setenv("INDEX_DB_PATH", str(db))
    monkeypatch.setenv("BTMCP_DB_POOL", "3")
    monkeypatch.setenv("BTMCP_DB_WAIT_S", "0.3")
    import server.deps as d
    return importlib.reload(d)


def test_concurrent_borrowers_always_get_their_own_rows(deps):
    def work(i):
        with deps.db_connection() as db:
            out = []
            for k in range(i % 50, i % 50 + 40):
                out.append(db.execute("SELECT v FROM t WHERE k = ?", (k,)).fetchone()[0])
            return i, out
    with cf.ThreadPoolExecutor(24) as ex:
        for i, out in ex.map(work, range(200)):
            assert out == [f"value-{k}" for k in range(i % 50, i % 50 + 40)]


def test_a_connection_is_never_lent_twice(deps):
    live, peak, lock = set(), [0], threading.Lock()
    def work(_):
        with deps.db_connection() as db:
            with lock:
                assert id(db) not in live, "the same connection was handed to two borrowers"
                live.add(id(db)); peak[0] = max(peak[0], len(live))
            db.execute("SELECT count(*) FROM t").fetchone()
            with lock:
                live.discard(id(db))
    with cf.ThreadPoolExecutor(16) as ex:
        list(ex.map(work, range(100)))
    assert peak[0] <= 3


def test_waiting_too_long_gives_503_not_a_hang(deps):
    from fastapi import HTTPException
    held = [deps.db_connection() for _ in range(3)]
    for h in held:
        h.__enter__()
    try:
        with pytest.raises(HTTPException) as e:
            with deps.db_connection():
                pass
        assert e.value.status_code == 503
    finally:
        for h in held:
            h.__exit__(None, None, None)
    with deps.db_connection() as db:                      # and it recovers once connections are returned
        assert db.execute("SELECT 1").fetchone()[0] == 1
