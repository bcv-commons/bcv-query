"""Prove a usearch HNSW ANN index over the existing float vectors (work copy).

Builds an HNSW index from chunks_vec (streamed in batches → low peak RAM, f16
storage), saves it, then measures query latency + recall@20 vs the exact float
KNN. No re-embedding. Run in the bcv-rag container:

    docker exec bcv-rag python /tmp/hnsw.py /data/index.db.work
"""
import sys, time, sqlite3, pickle
import numpy as np
import sqlite_vec
from usearch.index import Index

DB = sys.argv[1] if len(sys.argv) > 1 else "/data/index.db.work"
NDIM, K, BATCH = 1024, 20, 20000

db = sqlite3.connect(DB)
db.enable_load_extension(True)
sqlite_vec.load(db)

idx = Index(ndim=NDIM, metric="cos", dtype="f16")
keys_map = []                       # int key -> chunk_id
t = time.time()
cur = db.execute("SELECT chunk_id, embedding FROM chunks_vec")
k = 0
while True:
    rows = cur.fetchmany(BATCH)
    if not rows:
        break
    bk = np.arange(k, k + len(rows), dtype=np.uint64)
    bv = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), NDIM)
    idx.add(bk, bv, log=False)
    keys_map.extend(r[0] for r in rows)
    k += len(rows)
print(f"[build] {k} vectors -> usearch HNSW in {time.time()-t:.1f}s  (size ~{idx.memory_usage//(1024*1024)} MB)")

idx.save("/data/vec.usearch")
with open("/data/vec_keys.pkl", "wb") as f:
    pickle.dump(keys_map, f)
print("[build] saved /data/vec.usearch + /data/vec_keys.pkl")

# ---- recall + latency vs exact float KNN ----
probes = db.execute("SELECT chunk_id, embedding FROM chunks_vec "
                    "ORDER BY chunk_id LIMIT 5 OFFSET 50000").fetchall()
t_ann = t_float = 0.0
recalls = []
for cid, qblob in probes:
    qv = np.frombuffer(qblob, dtype=np.float32)
    t = time.time(); m = idx.search(qv, K); t_ann += time.time() - t
    ann_ids = [keys_map[int(key)] for key in m.keys]
    t = time.time()
    truth = [r[0] for r in db.execute(
        "SELECT chunk_id FROM chunks_vec WHERE embedding MATCH ? AND k=? ORDER BY distance",
        (qblob, K)).fetchall()]
    t_float += time.time() - t
    recalls.append(len(set(truth) & set(ann_ids)) / K)

n = len(probes)
print(f"\n[query] usearch ANN : {t_ann/n*1000:.2f} ms avg   recall@{K} {sum(recalls)/n*100:.0f}%  (per-q {[round(r,2) for r in recalls]})")
print(f"[query] float exact : {t_float/n:.2f} s avg   ({(t_float/max(t_ann,1e-9)):.0f}x slower than ANN)")
