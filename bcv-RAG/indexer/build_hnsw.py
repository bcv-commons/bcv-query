"""Build the usearch HNSW vector index from index.db's chunks_vec.

Run after embedding — the float vectors already exist, so this is CPU-only (no
re-embed, no GPU). Produces `vec.usearch` + `vec_keys.pkl` next to the index;
both ship alongside index.db to the server, where bcv-rag mmap-loads them for
~2ms vector search (vs sqlite-vec brute-force ~6-16s).

    python -m indexer.build_hnsw --db index.db --out data/vec.usearch

usearch HNSW: cosine metric, f16 storage (~96% recall@20, ~2.6GB for 1.2M×1024).
Streamed in batches → low peak RAM.
"""
from __future__ import annotations

import argparse
import pickle
import sqlite3
import sys
import time

import numpy as np
import sqlite_vec
from usearch.index import Index


def build(db_path: str, out_path: str, ndim: int = 1024, batch: int = 20000) -> None:
    db = sqlite3.connect(db_path)
    db.enable_load_extension(True)
    sqlite_vec.load(db)

    idx = Index(ndim=ndim, metric="cos", dtype="f16")
    keys: list[str] = []
    t = time.time()
    cur = db.execute("SELECT chunk_id, embedding FROM chunks_vec")
    k = 0
    while True:
        rows = cur.fetchmany(batch)
        if not rows:
            break
        bk = np.arange(k, k + len(rows), dtype=np.uint64)
        bv = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), ndim)
        idx.add(bk, bv, log=False)
        keys.extend(r[0] for r in rows)
        k += len(rows)
        print(f"  {k} vectors…", file=sys.stderr, end="\r")

    idx.save(out_path)
    keys_path = out_path.rsplit(".", 1)[0] + "_keys.pkl"
    with open(keys_path, "wb") as f:
        pickle.dump(keys, f)
    print(f"\nbuilt {k} vectors → {out_path} (+ {keys_path}) in {time.time()-t:.0f}s "
          f"(~{idx.memory_usage//(1024*1024)} MB)", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the usearch HNSW vector index")
    ap.add_argument("--db", default="index.db")
    ap.add_argument("--out", default="vec.usearch")
    ap.add_argument("--ndim", type=int, default=1024)
    a = ap.parse_args()
    build(a.db, a.out, a.ndim)


if __name__ == "__main__":
    main()
