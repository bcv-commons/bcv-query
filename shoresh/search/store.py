"""Vector store for clause search — a normalized float32 matrix + SQLite
metadata on the /data volume. Brute-force cosine (a matrix-vector product)
is plenty for ~90k clauses (<~50ms) and avoids a sqlite-vec extension.

Layout per language under DATA_DIR:
    clauses_<lang>.npy      (N, D) float32, L2-normalized, row i ↔ clause id i
    clauses_<lang>.sqlite   clauses(id, book, chapter, verse, text)
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DATA_DIR = Path(os.environ.get("SHORESH_DATA", "/data"))


def paths(lang: str) -> tuple[Path, Path]:
    return DATA_DIR / f"clauses_{lang}.npy", DATA_DIR / f"clauses_{lang}.sqlite"


def exists(lang: str) -> bool:
    vec, meta = paths(lang)
    return vec.exists() and meta.exists()


class ClauseStore:
    """Loaded once at startup; holds the matrix in RAM for fast search."""

    def __init__(self, lang: str):
        import numpy as np
        vec_path, meta_path = paths(lang)
        self.lang = lang
        self.matrix = np.load(vec_path, mmap_mode=None).astype("float32")
        self.meta = sqlite3.connect(f"file:{meta_path}?mode=ro", uri=True,
                                    check_same_thread=False)
        self.meta.row_factory = sqlite3.Row
        self.count = self.matrix.shape[0]

    def search(self, qvec: list[float], k: int = 10) -> list[dict]:
        import numpy as np
        q = np.asarray(qvec, dtype="float32")
        q /= (np.linalg.norm(q) or 1.0)
        scores = self.matrix @ q                      # cosine (rows are normalized)
        k = min(k, scores.shape[0])
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        rows = []
        for i in top:
            r = self.meta.execute(
                "SELECT book, chapter, verse, text FROM clauses WHERE id=?",
                (int(i),)).fetchone()
            if r:
                rows.append({
                    "ref": f"{r['book']} {r['chapter']}:{r['verse']}",
                    "text": r["text"],
                    "score": round(float(scores[i]), 4),
                })
        return rows
