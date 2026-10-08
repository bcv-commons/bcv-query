"""No sqlite connection may be shared by concurrent requests: FastAPI runs sync routes on a thread pool and a sqlite3 connection used by
two threads at once raised `bad parameter or other API misuse` and returned other requests' rows (2026-10-07: 5,880 concurrent coref+frame
calls gave 1,342 exceptions and 1,278 wrong answers; 6,000 interlinear get_word calls gave 50 and 1,921). Regression tests for the fixes.
  bcv-RAG/.venv/bin/python -m pytest shoresh/tests/test_shared_connections.py -q
"""
import concurrent.futures as cf
import random
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

SHORESH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHORESH))


def hammer(fn, jobs, threads=24):
    """Run fn over jobs concurrently; return (exceptions, wrong) against the serial answers."""
    serial = {j: fn(j) for j in set(jobs)}
    exceptions = wrong = 0

    def work(j):
        try:
            return j, fn(j)
        except Exception:  # noqa: BLE001
            return j, Exception
    jobs = list(jobs); random.Random(11).shuffle(jobs)
    with cf.ThreadPoolExecutor(threads) as ex:
        for j, r in ex.map(work, jobs):
            if r is Exception:
                exceptions += 1
            elif r != serial[j]:
                wrong += 1
    return exceptions, wrong


@pytest.mark.skipif(not (SHORESH / "macula" / "macula-spine.db").exists(), reason="macula-spine.db not built locally")
def test_macula_coref_and_frame_under_concurrency():
    from macula import data as m
    refs = [("GEN", c, v, w) for c in range(1, 4) for v in range(1, 12) for w in range(1, 7)]
    assert hammer(lambda r: (m.coref(*r), m.frame(*r)), refs * 10) == (0, 0)


def test_interlinear_word_lookups_under_concurrency():
    from interlinear import serve
    if not serve.is_ready():
        pytest.skip("interlinear database not built locally")
    ids = [w.get("word_id") or w.get("id") for w in serve.get_chapter(1, 1)][:50]
    assert hammer(lambda i: serve.get_word(i), ids * 60) == (0, 0)


def test_clause_store_metadata_under_concurrency():
    import numpy as np
    from search import store
    d = Path(tempfile.mkdtemp()); n, dim = 300, 16
    rng = np.random.default_rng(2); m = rng.normal(size=(n, dim)).astype("float32"); m /= np.linalg.norm(m, axis=1, keepdims=True)
    np.save(d / "v.npy", m)
    con = sqlite3.connect(d / "m.sqlite"); con.execute("CREATE TABLE clauses(id INTEGER PRIMARY KEY, book TEXT, chapter INT, verse INT, text TEXT)")
    con.executemany("INSERT INTO clauses VALUES (?,?,?,?,?)", [(i, "GEN", i // 30 + 1, i % 30 + 1, f"clause {i}") for i in range(n)]); con.commit(); con.close()
    store.paths = lambda lang: (d / "v.npy", d / "m.sqlite")
    st = store.ClauseStore("hbo")
    qs = [tuple(rng.normal(size=dim).astype("float32").tolist()) for _ in range(30)]
    assert hammer(lambda q: st.search(list(q), 5), qs * 80) == (0, 0)
