"""V3b gate items: concepts labelled without definitions for the B2 lexemes (the 20 Hebrew lexemes with no UBS sense).

    python -m macula.build_concept_gate_items [--arm seed|strict] [--out DIR]

Agreed with research 2026-11-17 (design note internal-docs/clause-structure-work/v3b/design-note-2026-11-17.md, five changes):
  - every Tanakh occurrence of the 20 lexemes (closed chapters GEN 22, 37, 44 left out);
  - examples: hebrew-word-concepts-model v0.6 b2 occurrences with jev_confidence >= 0.9, taken from other books than the
    occurrence's own (book folds, so parallel passages and the same verse never serve as their own example);
    arm `strict`: only examples whose Septuagint word (corpus edge `lxx`) is the concept's main Greek word in `concept_greek`;
  - step 3: the 7 nearest examples (vector store, cosine); at >= 6 of 7 agreeing the vector label stands (labeller `vector`);
  - step 4: the rest go to Jev, each concept shown by 3 example verses (Hebrew ref + its Septuagint ref), plus "none of these".
No definitions, glosses or English are written into the items.

DIR gets vector_labels.json (key -> concept, agreement), items.json (for Jev: key, ref, septuagint_ref, lexeme, concepts with example
refs), and summary.json.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REL = ROOT / "internal-docs" / "hebrew-word-concepts-model-release" / "v0.6-release" / "data"
CLOSED = {"01022", "01037", "01044"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--arm", choices=("seed", "strict"), default="seed")
    ap.add_argument("--store", type=Path, default=HERE / "data" / "vector-store")
    ap.add_argument("--corpus", type=Path, default=HERE / "data" / "bridge-corpus" / "dev-builds" / "b15")
    ap.add_argument("--k", type=int, default=7)
    ap.add_argument("--keep", type=int, default=6)
    ap.add_argument("--out", type=Path, default=ROOT / "internal-docs" / "clause-structure-work" / "v3b" / "gate")
    a = ap.parse_args()
    import pyarrow.parquet as pq
    from macula import build_bridge_corpus as B
    api = B.load(a.corpus)
    F, E, L = api.F, api.E, api.L
    toks = pq.read_table(REL / "tokens.parquet").to_pylist()
    b2 = [r for r in toks if r["stage"] == "b2"]
    lexemes = sorted({r["concept"].rsplit(".", 1)[0] for r in b2})
    strong_of = {lx: lx[1:] for lx in lexemes}
    main_greek = {}
    best = {}
    for r in pq.read_table(REL / "concept_greek.parquet").to_pylist():
        if r["concept"].rsplit(".", 1)[0] in lexemes and r["greek_strong"] and r["count"] > best.get(r["concept"], 0):
            best[r["concept"]] = r["count"]
            main_greek[r["concept"]] = str(r["greek_strong"]).lstrip("0")
    nodes = pq.read_table(a.store / "tanakh.parquet", columns=["node"]).column("node").to_pylist()
    X = np.load(a.store / "tanakh.npy", mmap_mode="r")
    row = {n: i for i, n in enumerate(nodes)}
    tan = next(t for t in F.otype.s("text") if F.name.v(t) == "tanakh")
    want = {s.lstrip("0") for s in strong_of.values()}
    occ = []
    for w in L.d(tan, otype="word"):
        s = F.strong.v(w)
        if not s or str(s).lstrip("0").rstrip("abcdefgh") not in want:
            continue
        key = F.mid.v(w)
        if key[:5] in CLOSED:
            continue
        v = L.u(w, otype="verse")[0]
        lx = [g for g, _ in (E.lxx.f(w) or ())]
        sref, gs = "", ""
        if lx:
            g = int(lx[0])
            gv = L.u(g, otype="verse")
            sref = f"{F.book.v(gv[0])} {F.chapter.v(gv[0])}:{F.verse.v(gv[0])}" if gv else ""
            gs = str(F.strong.v(g) or "").lstrip("0")
        occ.append({"key": key, "node": w, "lexeme": "H" + str(s).lstrip("0").rstrip("abcdefgh"),
                    "ref": f"{F.book.v(v)} {F.chapter.v(v)}:{F.verse.v(v)}", "septuagint_ref": sref, "greek": gs})
    lab = {r["key"]: r for r in b2}
    ex = [o for o in occ if o["key"] in lab and (lab[o["key"]]["jev_confidence"] or 0) >= 0.9]
    if a.arm == "strict":
        ex = [o for o in ex if main_greek.get(lab[o["key"]]["concept"]) == o["greek"]]
    for o in ex:
        o["concept"] = lab[o["key"]]["concept"]

    def vec(os_):
        V = np.asarray(X[[row[o["node"]] for o in os_]], dtype=np.float32)
        return V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)

    vector_labels, items = {}, []
    summary = collections.Counter()
    by_lex = collections.defaultdict(list)
    for o in ex:
        by_lex[o["lexeme"]].append(o)
    for lx in lexemes:
        es = by_lex.get(lx, [])
        os_ = [o for o in occ if o["lexeme"] == lx]
        summary["occurrences"] += len(os_)
        if not es:
            summary["lexemes with no examples"] += 1
            continue
        EV = vec(es)
        concepts = sorted({e["concept"] for e in es})
        shown = {}
        for c in concepts:
            ce = [e for e in es if e["concept"] == c]
            idx = np.linspace(0, len(ce) - 1, min(3, len(ce))).astype(int)
            shown[c] = [{"ref": ce[i]["ref"], "septuagint_ref": ce[i]["septuagint_ref"]} for i in idx]
        OV = vec(os_)
        S = OV @ EV.T
        book = np.array([e["key"][:2] for e in es])
        for i, o in enumerate(os_):
            s = np.where(book != o["key"][:2], S[i], -9)
            nn = np.argsort(-s)[: a.k]
            votes = collections.Counter(es[j]["concept"] for j in nn if s[j] > -9)
            if not votes:
                continue
            c, n = votes.most_common(1)[0]
            if n >= a.keep and len(concepts) > 1:
                vector_labels[o["key"]] = {"concept": c, "agree": n}
                summary["vector"] += 1
            elif len(concepts) == 1 and n >= a.keep:
                vector_labels[o["key"]] = {"concept": c, "agree": n}
                summary["vector (one concept)"] += 1
            else:
                items.append({"key": o["key"], "ref": o["ref"], "septuagint_ref": o["septuagint_ref"], "lexeme": lx,
                              "concepts": [{"code": c2, "examples": shown[c2]} for c2 in concepts]})
                summary["to jev"] += 1
    a.out.mkdir(parents=True, exist_ok=True)
    suf = "" if a.arm == "seed" else "-strict"
    (a.out / f"vector_labels{suf}.json").write_text(json.dumps(vector_labels, indent=1))
    (a.out / f"items{suf}.json").write_text(json.dumps(items, ensure_ascii=False, indent=1))
    agree_v06 = sum(1 for k, v in vector_labels.items() if k in lab and lab[k]["concept"] == v["concept"])
    in_v06 = sum(1 for k in vector_labels if k in lab)
    res = {"arm": a.arm, "lexemes": len(lexemes), "examples": len(ex), **summary,
           "vector labels that v0.6 also labelled": in_v06, "of them the same concept": agree_v06}
    (a.out / f"summary{suf}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
