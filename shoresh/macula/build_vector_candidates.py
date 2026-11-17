"""Candidates from contextual vectors for Hebrew lexemes the bridge leaves without a Greek partner (Hebrew and Greek only).

    python -m macula.build_vector_candidates --vectors DIR --lexemes LIST.json [--top 8] [--existing CANDIDATES.json]

The user (2026-11-17): the 212 pairs whose candidates were found through English glosses are dropped ("drop them now"); find
alternatives through the original languages. DIR holds lexeme vectors from the area C gate (h_/g_vectors.npy and h_/g_keys.json:
BEREL 3.0 on the unpointed Tanakh and both Hebrew NTs, GreBerta on the Greek NT and the Septuagint). Greek vectors are mapped onto
the Hebrew space by orthogonal Procrustes on the macula Septuagint tier; a Hebrew lexeme's candidates are its nearest Greek lexemes
(at least 5 occurrences each). Candidates already proposed for the same lexeme by macula.build_bridge_candidates (Hebrew NT pairs,
weak Septuagint co-occurrence) are put first when --existing is given.

--lexemes: {"ot": [Hebrew Strong's numbers]}. Writes macula/data/bridge-candidates/vector-candidates.json in the format of
build_bridge_candidates ({"ot": [{strong, lemma, tokens, candidates: [{strong, lemma, tokens, evidence}]}]}), evidence
{"vector": {"rank", "cos"}} and/or the existing evidence. No English. A judge (Jev, on the verses, no glosses) chooses one or none;
that run is research's and needs the user's go for its cost (given 2026-11-17).
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import numpy as np

from macula import build_bridge_corpus as B

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "bridge-candidates"
CORPUS = HERE / "data" / "bridge-corpus" / "dev-builds" / "b15"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--vectors", required=True)
    ap.add_argument("--lexemes", required=True)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--existing")
    a = ap.parse_args()
    D = Path(a.vectors)
    api = B.load(CORPUS)
    F, E = api.F, api.E

    def lex(w):
        s = F.strong.v(w)
        if not s:
            return None
        return ("h" if F.lang.v(w) in ("hbo", "arc") else "g") + str(s).lstrip("0").rstrip("abcdefgh")

    lemma = {}
    for w in F.otype.s("word"):
        k = lex(w)
        if k and k not in lemma and F.lemma.v(w):
            lemma[k] = F.lemma.v(w)

    def load(side):
        meta = json.loads((D / f"{side}_keys.json").read_text())
        X = np.load(D / f"{side}_vectors.npy")
        X = X - X.mean(0)
        X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
        return meta["keys"], {k: i for i, k in enumerate(meta["keys"])}, X, dict(zip(meta["keys"], meta["counts"]))

    hv, hix, H, hn = load("h")
    gv, gix, G, gn = load("g")
    seed = []
    for h in F.otype.s("lexeme"):
        for g, _ in E.tier_macula.f(h):
            ws = [w for w in E.oslots.s(g) if F.strong.v(w)][:1]
            hs = [w for w in E.oslots.s(h) if F.strong.v(w)][:1]
            if ws and hs and lex(hs[0]) in hix and lex(ws[0]) in gix:
                seed.append((lex(hs[0]), lex(ws[0])))
    u, _, vt = np.linalg.svd(G[[gix[b] for _, b in seed]].T @ H[[hix[a] for a, _ in seed]])
    GW = G @ (u @ vt)

    existing = {}
    if a.existing:
        for r in json.load(open(a.existing)).get("ot", []):
            existing[int(r["strong"])] = r["candidates"]
    want = [int(x) for x in json.load(open(a.lexemes))["ot"]]
    out, missing = [], []
    for s in want:
        k = f"h{s}"
        cands = [dict(c) for c in existing.get(s, [])]
        seen = {int(c["strong"]) for c in cands}
        if k in hix:
            sims = GW @ H[hix[k]]
            for rank, j in enumerate(np.argsort(-sims)[: a.top], 1):
                g = int(gv[j][1:])
                ev = {"rank": rank, "cos": round(float(sims[j]), 3)}
                if g in seen:
                    next(c for c in cands if int(c["strong"]) == g)["evidence"]["vector"] = ev
                else:
                    cands.append({"strong": g, "lemma": lemma.get(gv[j], ""), "tokens": gn[gv[j]], "evidence": {"vector": ev}})
                    seen.add(g)
        if not cands:
            missing.append(s)
            continue
        out.append({"strong": s, "lemma": lemma.get(k, ""), "tokens": hn.get(k, 0), "candidates": cands})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "vector-candidates.json").write_text(json.dumps({"ot": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(out)} lexemes with candidates ({sum(len(r['candidates']) for r in out)} in all); "
          f"{len(missing)} with none (too rare for the vectors and no earlier candidate): {missing}")


if __name__ == "__main__":
    main()
