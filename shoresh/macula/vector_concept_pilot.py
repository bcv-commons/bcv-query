"""Vector track V3b pilot: can occurrence vectors label concepts without any definition?

    python -m macula.vector_concept_pilot [--out FILE.json]

For every Hebrew lexeme with two or more concepts in hebrew-word-concepts-model v0.6, its labelled Tanakh occurrences are split in
5 folds (by book by default, so parallel passages in other books and the same verse never sit on both sides; GEN 22, 37, 44
left out); each held-out occurrence gets the concept of its nearest labelled occurrences (k-nearest neighbours, cosine, on the vector
store's contextual vectors). Compared with the v0.6 label, with the majority concept as the baseline, and with v0.6's own two-run
agreement on the same occurrences (jev_run1 vs jev_run2). Reported overall and at confidence cut-offs (share of the k neighbours that
agree). No English is read: the concepts are codes, the vectors come from the Hebrew text.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TOKENS = ROOT / "internal-docs" / "hebrew-word-concepts-model-release" / "v0.6-release" / "data" / "tokens.parquet"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--store", type=Path, default=HERE / "data" / "vector-store")
    ap.add_argument("--tokens", type=Path, default=TOKENS)
    ap.add_argument("--corpus", type=Path, default=HERE / "data" / "bridge-corpus" / "dev-builds" / "b15")
    ap.add_argument("--k", type=int, default=7)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--fold", choices=("occurrence", "book"), default="book")
    ap.add_argument("--closed", default="01022,01037,01044", help="book+chapter keys left out (GEN 22, 37, 44)")
    a = ap.parse_args()
    import pyarrow.parquet as pq
    from macula import build_bridge_corpus as B
    api = B.load(a.corpus)
    F = api.F
    nodes = pq.read_table(a.store / "tanakh.parquet", columns=["node"]).column("node").to_pylist()
    X = np.load(a.store / "tanakh.npy", mmap_mode="r")
    row = {F.mid.v(n): i for i, n in enumerate(nodes)}
    T = pq.read_table(a.tokens).to_pylist()
    closed = set(a.closed.split(",")) if a.closed else set()
    by = collections.defaultdict(list)
    for r in T:
        if r["lang"] == "hbo" and r["concept"] and r["key"] in row and r["key"][:5] not in closed:
            lexeme = r["concept"].rsplit(".", 1)[0]
            by[lexeme].append(r)
    rng = np.random.default_rng(5)
    tot = collections.Counter()
    cuts = (0.0, 0.6, 0.8, 1.0)
    cut = {c: collections.Counter() for c in cuts}
    per_stage = collections.defaultdict(collections.Counter)
    for lexeme, rs in by.items():
        labs = [r["concept"] for r in rs]
        if len(set(labs)) < 2 or len(rs) < 10:
            continue
        V = np.asarray(X[[row[r["key"]] for r in rs]], dtype=np.float32)
        V -= V.mean(0)
        V /= np.linalg.norm(V, axis=1, keepdims=True) + 1e-9
        if a.fold == "book":
            books = sorted({r["key"][:2] for r in rs})
            bf = {b: i % 5 for i, b in enumerate(rng.permutation(books))}
            fold = np.array([bf[r["key"][:2]] for r in rs])
        else:
            fold = rng.integers(0, 5, len(rs))
        lab = np.array(labs)
        for f in range(5):
            te, tr = np.where(fold == f)[0], np.where(fold != f)[0]
            if not len(te) or not len(tr):
                continue
            maj = collections.Counter(lab[tr]).most_common(1)[0][0]
            S = V[te] @ V[tr].T
            k = min(a.k, len(tr))
            nn = np.argsort(-S, axis=1)[:, :k]
            for i, t in enumerate(te):
                votes = collections.Counter(lab[tr][nn[i]])
                pred, n = votes.most_common(1)[0]
                conf = n / k
                ok = pred == lab[t]
                r = rs[t]
                tot["n"] += 1
                tot["knn right"] += ok
                tot["majority right"] += maj == lab[t]
                if r["jev_run1"] and r["jev_run2"]:
                    tot["with two runs"] += 1
                    tot["v0.6 runs agree"] += r["jev_run1"] == r["jev_run2"]
                    tot["knn right (two-run items)"] += ok
                two = bool(r["jev_run1"] and r["jev_run2"])
                for c in cuts:
                    if conf >= c:
                        cut[c]["n"] += 1
                        cut[c]["right"] += ok
                        cut[c]["two"] += two
                        cut[c]["two agree"] += two and r["jev_run1"] == r["jev_run2"]
                        cut[c]["knn right on two"] += two and ok
                per_stage[r["stage"]]["n"] += 1
                per_stage[r["stage"]]["right"] += ok
    res = {"fold": a.fold, "closed chapters left out": sorted(closed), "lexemes": sum(1 for rs in by.values() if len({r["concept"] for r in rs}) >= 2 and len(rs) >= 10),
           "occurrences": tot["n"], "knn agreement with v0.6": round(tot["knn right"] / tot["n"], 3),
           "majority baseline": round(tot["majority right"] / tot["n"], 3),
           "v0.6 two-run agreement (same model twice)": round(tot["v0.6 runs agree"] / max(1, tot["with two runs"]), 3),
           "knn on those two-run items": round(tot["knn right (two-run items)"] / max(1, tot["with two runs"]), 3),
           "by confidence (share of neighbours agreeing)": {f">= {c}": {"share of occurrences": round(cut[c]["n"] / tot["n"], 3),
                                                                        "agreement": round(cut[c]["right"] / max(1, cut[c]["n"]), 3),
                                                                        "v0.6 two-run agreement here": round(cut[c]["two agree"] / max(1, cut[c]["two"]), 3),
                                                                        "knn on the two-run items here": round(cut[c]["knn right on two"] / max(1, cut[c]["two"]), 3)}
                                                            for c in cuts},
           "by stage": {s: round(v["right"] / v["n"], 3) for s, v in per_stage.items()}}
    print(json.dumps(res, indent=1, ensure_ascii=False))
    if a.out:
        a.out.write_text(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
