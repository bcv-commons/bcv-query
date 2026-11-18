"""Vector track V3e + V3g: "clauses like this" from contextual vectors, ids and scores only (no text).

    python -m macula.build_clauses_similar [--top 10] [--out macula/data/clauses-similar]

Clause vector: the mean of the clause's content-word occurrence vectors (noun, verb, adjective, adverb; all words when it has
none) from the vector store (BEREL 3.0 for Hebrew, GreBerta for Greek, 4 layers), each text centred on its own mean, then
normalised. Greek is mapped into the Hebrew space by the V3a map: orthogonal Procrustes on Tanakh-Septuagint occurrence pairs
(corpus edge `lxx`, MACULA's alignment). No New Testament pair enters the map.

OUT gets (ids are clause keys of hebrew-clause-layout / greek-nt-clause-layout, i.e. clause-columns keys):
  hebrew.parquet        clause_key, rank, other, score     Tanakh clause -> nearest Tanakh clauses outside its own verse
  greek-nt.parquet      the same for the Greek NT
  tanakh-nt.parquet     clause_key, rank, nt_clause, score Tanakh clause -> nearest Greek NT clauses (V3g)
  checks.json           yardsticks:
     cross   Salkinson's Hebrew NT verse -> the Greek NT verse among all 7,9xx (mapped space): recall@1/@10; the direction V3g
             uses, unseeded (no NT pair trains the map)
     within  synoptic lift: the share of Chronicles clauses whose best neighbour outside Chronicles is in Samuel-Kings, against
             those books' share of the clauses; the same for Matthew -> Mark/Luke
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
STORE = HERE / "data" / "vector-store"
CORPUS = HERE / "data" / "bridge-corpus" / "dev-builds" / "b15"
CONTENT = {"noun", "verb", "adj", "adv"}


def norm(X):
    return X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)


def procrustes(A, Bm):
    u, _, vt = np.linalg.svd(A.T @ Bm)
    return u @ vt


def knn(Q, K, top, exclude=None, chunk=4096):
    """top cosine neighbours of each row of Q among rows of K (both normalised), on the GPU when there is one;
    exclude(i_block) -> boolean mask (rows x K) of pairs to skip"""
    import torch
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    Kt = torch.from_numpy(K.astype(np.float16 if dev == "cuda" else np.float32)).to(dev)
    out_i, out_s = [], []
    for s in range(0, len(Q), chunk):
        q = torch.from_numpy(Q[s:s + chunk].astype(np.float16 if dev == "cuda" else np.float32)).to(dev)
        sim = (q @ Kt.T).float()
        if exclude is not None:
            sim[torch.from_numpy(exclude(s, min(s + chunk, len(Q)))).to(dev)] = -2
        v, i = sim.topk(top, dim=1)
        out_i.append(i.cpu().numpy()), out_s.append(v.cpu().numpy())
    return np.concatenate(out_i), np.concatenate(out_s)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--store", type=Path, default=STORE)
    ap.add_argument("--out", type=Path, default=HERE / "data" / "clauses-similar")
    a = ap.parse_args()
    import pyarrow as pa
    import pyarrow.parquet as pq
    from macula import build_bridge_corpus as B
    api = B.load(CORPUS)
    F, E = api.F, api.E

    store, mean = {}, {}
    for t in ("tanakh", "greek_nt", "septuagint", "salkinson"):
        meta = pq.read_table(a.store / f"{t}.parquet", columns=["node", "pos", "book", "chapter", "verse"]).to_pylist()
        X = np.load(a.store / f"{t}.npy", mmap_mode="r")
        ix = {r["node"]: i for i, r in enumerate(meta)}
        content = np.array([r["pos"] in CONTENT for r in meta])
        mean[t] = np.asarray(X[np.flatnonzero(content)[::7]], dtype=np.float32).mean(0)
        store[t] = (meta, X, ix, content)
        print(t, len(meta), flush=True)

    # the V3a map: Septuagint -> Hebrew, occurrence Procrustes
    hm, HX, hix, hc = store["tanakh"]
    gm, GX, gix, gc = store["septuagint"]
    occ = []
    for w, i in hix.items():
        if not hc[i]:
            continue
        for g, _ in E.lxx.f(w) or ():
            j = gix.get(int(g))
            if j is not None and gc[j]:
                occ.append((i, j))
    rng = np.random.default_rng(13)
    rng.shuffle(occ)
    occ = occ[:400000]
    A_ = norm(np.asarray(GX[[j for _, j in occ]], dtype=np.float32) - mean["septuagint"])
    B_ = norm(np.asarray(HX[[i for i, _ in occ]], dtype=np.float32) - mean["tanakh"])
    W = procrustes(A_, B_).astype(np.float32)
    print(f"map: {len(occ):,} occurrence pairs", flush=True)

    def pool(t, groups, greek):
        meta, X, ix, content = store[t]
        V = np.zeros((len(groups), X.shape[1]), dtype=np.float32)
        for n, nodes in enumerate(groups):
            rows = [ix[x] for x in nodes if x in ix]
            sel = [r for r in rows if content[r]] or rows
            if sel:
                V[n] = (np.asarray(X[sel], dtype=np.float32) - mean[t]).mean(0)
        V = norm(V)
        return norm(V @ W) if greek else V

    # clauses from the layouts (Hebrew: clause_key; Greek: first), words -> corpus nodes
    node_of = {}
    for t in F.otype.s("text"):
        if F.name.v(t) in ("tanakh", "greek_nt"):
            for w in api.L.d(t, otype="word"):
                m = F.mid.v(w)
                if m:
                    node_of[str(m).lstrip("n")] = w
    clauses = {}
    for lang, layout, kf in (("hebrew", "clause-layout", "clause_key"), ("greek-nt", "nt-clause-layout", "first")):
        rows = collections.OrderedDict()
        for f in sorted((HERE / "data" / layout / "clauses").glob("*/*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    k = r.get(kf)
                    if k:
                        e = rows.setdefault(str(k), [r.get("book") or f.parent.name, int(r.get("chapter") or 0), int(r["verse"]), []])
                        e[3] += [node_of[x] for x in (str(y).lstrip("n") for y in r["words"]) if x in node_of]
        keys = list(rows)
        V = pool("tanakh" if lang == "hebrew" else "greek_nt", [rows[k][3] for k in keys], lang != "hebrew")
        clauses[lang] = (keys, [tuple(rows[k][:3]) for k in keys], V)
        print(lang, len(keys), "clauses", flush=True)

    a.out.mkdir(parents=True, exist_ok=True)
    checks = {}
    tables = {}
    for lang in ("hebrew", "greek-nt"):
        keys, vref, V = clauses[lang]
        vid = np.array([hash(v) for v in vref])
        I, S = knn(V, V, a.top, exclude=lambda s, e: vid[s:e, None] == vid[None, :])
        tables[lang] = (I, S)
        pq.write_table(pa.table({"clause_key": [keys[i] for i in range(len(keys)) for _ in range(a.top)],
                                 "rank": [r + 1 for _ in range(len(keys)) for r in range(a.top)],
                                 "other": [keys[j] for j in I.ravel()],
                                 "score": np.round(S.ravel(), 4).astype(np.float32)}), a.out / f"{lang}.parquet", compression="zstd")
    hk, hv, HV = clauses["hebrew"]
    gk, gv, GV = clauses["greek-nt"]
    I, S = knn(HV, GV, a.top)
    pq.write_table(pa.table({"clause_key": [hk[i] for i in range(len(hk)) for _ in range(a.top)],
                             "rank": [r + 1 for _ in range(len(hk)) for r in range(a.top)],
                             "nt_clause": [gk[j] for j in I.ravel()],
                             "score": np.round(S.ravel(), 4).astype(np.float32)}), a.out / "tanakh-nt.parquet", compression="zstd")

    # cross check: Salkinson verse -> Greek NT verse
    def verses(t, greek):
        meta = store[t][0]
        g = collections.OrderedDict()
        for r in meta:
            g.setdefault((r["book"], r["chapter"], r["verse"]), []).append(r["node"])
        ks = list(g)
        return ks, pool(t, [g[k] for k in ks], greek)
    sk, SV = verses("salkinson", False)
    nk, NV = verses("greek_nt", True)
    pos = {k: i for i, k in enumerate(nk)}
    both = [i for i, k in enumerate(sk) if k in pos]
    I2, _ = knn(SV[both], NV, 10)
    gold = np.array([pos[sk[i]] for i in both])
    checks["cross: Salkinson verse -> Greek NT verse"] = {
        "verses": len(both), "candidates": len(nk), "recall@1": round(float((I2[:, 0] == gold).mean()), 3),
        "recall@10": round(float((I2 == gold[:, None]).any(1).mean()), 3)}

    # within: synoptic lift
    def lift(lang, src, targets):
        keys, vref, V = clauses[lang]
        I, _ = tables[lang]
        books = np.array([v[0] for v in vref])
        m = np.isin(books, list(src))
        out = ~np.isin(books, list(src))
        hit = n = 0
        for i in np.flatnonzero(m):
            j = next((j for j in I[i] if out[j]), None)
            if j is not None:
                n += 1
                hit += books[j] in targets
        base = float(np.isin(books[out], list(targets)).mean())
        return {"clauses": n, "best outside in parallel books": round(hit / max(1, n), 3), "their share of clauses": round(base, 3),
                "lift": round(hit / max(1, n) / base, 2)}
    checks["within: Chronicles -> Samuel-Kings"] = lift("hebrew", {"1CH", "2CH"}, {"1SA", "2SA", "1KI", "2KI"})
    checks["within: Matthew -> Mark, Luke"] = lift("greek-nt", {"MAT"}, {"MRK", "LUK"})
    checks["tanakh-nt score"] = {"median top-1": round(float(np.median(S[:, 0])), 3), "median top-10": round(float(np.median(S[:, -1])), 3)}
    checks["counts"] = {"hebrew clauses": len(hk), "greek-nt clauses": len(gk), "top": a.top, "map pairs": len(occ)}
    (a.out / "checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=1))
    print(json.dumps(checks, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
