"""Probe binary quantization on a WORK COPY of the index (no swap, no re-embed).

Builds a bit[1024] coarse table from the existing float chunks_vec, then measures
(1) build time, (2) query latency float-vs-binary+rerank, (3) recall@20 of
binary+rerank against the exact float KNN as ground truth. Uses existing index
vectors as probe queries — no embedding API needed.

Run inside the bcv-rag container against the work copy:
    docker exec bcv-rag python /app/scripts/vec_quantize_probe.py /data/index.db.work
"""
import sys, time, struct, sqlite3
import sqlite_vec

DB = sys.argv[1] if len(sys.argv) > 1 else "/data/index.db.work"
K = 20            # final top-K
OVERFETCH = 32    # coarse candidates = K * OVERFETCH
N_QUERIES = 5     # exact float KNN ground truth is ~16s each — keep small

db = sqlite3.connect(DB)
db.enable_load_extension(True)
sqlite_vec.load(db)

def unblob(b):
    import array
    a = array.array("f"); a.frombytes(b); return list(a)

# ---- 1. build the binary coarse table (skip if already built) ----
exists = db.execute("SELECT name FROM sqlite_master WHERE name='chunks_vec_bin'").fetchone()
if not exists:
    db.execute("CREATE VIRTUAL TABLE chunks_vec_bin USING vec0("
               "chunk_id TEXT PRIMARY KEY, embedding bit[1024])")
    t = time.time()
    db.execute("INSERT INTO chunks_vec_bin(chunk_id, embedding) "
               "SELECT chunk_id, vec_quantize_binary(embedding) FROM chunks_vec")
    db.commit()
    print(f"[build] binary table populated in {time.time()-t:.1f}s")
nrows = db.execute("SELECT count(*) FROM chunks_vec_bin").fetchone()[0]
print(f"[build] rows: {nrows} (reused existing table)" if exists else f"[build] rows: {nrows}")

# ---- 2. sample probe queries (existing vectors) ----
probes = db.execute("SELECT chunk_id, embedding FROM chunks_vec "
                    f"ORDER BY chunk_id LIMIT {N_QUERIES} OFFSET 50000").fetchall()

import numpy as np

# ---- build int8 table too (single-stage, no rerank) ----
if not db.execute("SELECT name FROM sqlite_master WHERE name='chunks_vec_i8'").fetchone():
    db.execute("CREATE VIRTUAL TABLE chunks_vec_i8 USING vec0("
               "chunk_id TEXT PRIMARY KEY, embedding int8[1024] distance_metric=cosine)")
    t = time.time()
    db.execute("INSERT INTO chunks_vec_i8(chunk_id, embedding) "
               "SELECT chunk_id, vec_quantize_int8(embedding, 'unit') FROM chunks_vec")
    db.commit()
    print(f"[build] int8 table populated in {time.time()-t:.1f}s")

t_float=t_bcoarse=t_rerank=t_i8=0.0
rec_bin=[]; rec_i8=[]
for cid, qblob in probes:
    qv = np.frombuffer(qblob, dtype=np.float32)

    t=time.time()
    truth=[r[0] for r in db.execute(
        "SELECT chunk_id FROM chunks_vec WHERE embedding MATCH ? AND k=? ORDER BY distance",(qblob,K)).fetchall()]
    t_float += time.time()-t

    # binary COARSE only (timed alone)
    t=time.time()
    cand=[r[0] for r in db.execute(
        "SELECT chunk_id FROM chunks_vec_bin WHERE embedding MATCH vec_quantize_binary(vec_f32(?)) AND k=? ORDER BY distance",
        (qblob,K*OVERFETCH)).fetchall()]
    t_bcoarse += time.time()-t

    # rerank with numpy (timed alone)
    t=time.time()
    ph=",".join("?"*len(cand))
    rows=db.execute(f"SELECT chunk_id, embedding FROM chunks_vec WHERE chunk_id IN ({ph})",cand).fetchall()
    M=np.frombuffer(b"".join(e for _,e in rows),dtype=np.float32).reshape(len(rows),-1)
    sims=M@qv
    order=np.argsort(-sims)[:K]
    approx=[rows[i][0] for i in order]
    t_rerank += time.time()-t
    rec_bin.append(len(set(truth)&set(approx))/K)

    # int8 single-stage (no rerank)
    t=time.time()
    i8=[r[0] for r in db.execute(
        "SELECT chunk_id FROM chunks_vec_i8 WHERE embedding MATCH vec_quantize_int8(vec_f32(?),'unit') AND k=? ORDER BY distance",
        (qblob,K)).fetchall()]
    t_i8 += time.time()-t
    rec_i8.append(len(set(truth)&set(i8))/K)

n=len(probes)
print(f"\n[latency avg over {n} queries]")
print(f"  float exact KNN     : {t_float/n:.2f}s   (baseline, recall 100%)")
print(f"  binary coarse only  : {t_bcoarse/n:.2f}s")
print(f"  binary rerank (np)  : {t_rerank/n:.2f}s")
print(f"  binary TOTAL+rerank : {(t_bcoarse+t_rerank)/n:.2f}s   recall {sum(rec_bin)/n*100:.0f}%")
print(f"  int8 single-stage   : {t_i8/n:.2f}s   recall {sum(rec_i8)/n*100:.0f}%")
