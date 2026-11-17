"""Candidates from contextual vectors for lexemes the bridge leaves without a partner (Hebrew and Greek only).

    python -m macula.build_vector_candidates --lexemes LIST.json [--top 8] [--existing CANDIDATES.json] [--map lexeme|occurrence]
    python -m macula.build_vector_candidates --auto --names-hbo MACULA_HEBREW.tsv --names-grc MACULA_GREEK.tsv [--min-count 5]
           [--model-pairs PAIRS.tsv ...] [--existing CANDIDATES.json] [--out FILE]

The user (2026-11-17): the pairs found through English glosses are dropped; alternatives come through the original languages (first
run: 92 Tanakh lexemes, hebrew-greek-lexeme-bridge-model v0.2). Vector track V3a (same day): every content lexeme still without a
partner, on both sides.

Vectors: the vector store (macula/build_vector_store.py: BEREL 3.0 for the unpointed Tanakh and both Hebrew NTs, GreBerta for the
Greek NT and the Septuagint; lexeme = mean over its occurrences). Map (--map):
  lexeme      orthogonal Procrustes on the lexeme pairs of the macula Septuagint tier (run 1);
  occurrence  orthogonal Procrustes on word pairs: a Tanakh word and the Septuagint word MACULA links it to (corpus edge `lxx`),
              contextual vectors on both sides (V2 variant C: held-out top 10 0.840, unseeded Hebrew NT pairs 0.595 / 0.555).
A lexeme's candidates are the nearest lexemes on the other side (content words, at least --min-count occurrences, no proper names).
Earlier Hebrew/Greek candidates for the same lexeme (macula.build_bridge_candidates) come first when --existing is given.

--lexemes: {"ot": [Hebrew Strong's], "nt": [Greek Strong's]}. --auto: every noun, verb and adjective lexeme (not a proper name in
MACULA's `type`) with at least --min-count occurrences that has no pair in the Septuagint tiers (macula, glaux) nor in the
--model-pairs files; side `ot` = a Hebrew lexeme given Greek candidates, side `nt` = a Greek NT lexeme given Hebrew candidates.
Writes OUT (default macula/data/bridge-candidates/vector-candidates.json) in build_bridge_candidates' format, evidence
{"vector": {"rank", "cos"}}. No English. The choice (Jev, on the verses, no glosses) is research's; budget given 2026-11-17.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
from pathlib import Path

import numpy as np

from macula import build_bridge_corpus as B

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "bridge-candidates"
CORPUS = HERE / "data" / "bridge-corpus" / "dev-builds" / "b15"
STORE = HERE / "data" / "vector-store"
CONTENT = {"noun", "verb", "adj"}
HEB_TEXTS = ("tanakh", "salkinson", "delitzsch")
GRC_TEXTS = ("greek_nt", "septuagint")


def norm(X):
    return X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)


def procrustes(A, Bm):
    u, _, vt = np.linalg.svd(A.T @ Bm)
    return u @ vt


def names(hbo: str | None, grc: str | None) -> set:
    out = set()
    for path, side, col_strong in ((hbo, "h", "strongnumberx"), (grc, "g", "strong")):
        if not path:
            continue
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                if (r.get("type") or "") == "proper" and r.get(col_strong):
                    out.add(side + r[col_strong].lstrip("0").rstrip("abcdefghABCDEFGH"))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lexemes")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--names-hbo")
    ap.add_argument("--names-grc")
    ap.add_argument("--model-pairs", action="append", default=[])
    ap.add_argument("--min-count", type=int, default=5)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--existing")
    ap.add_argument("--map", choices=("lexeme", "occurrence"), default="occurrence")
    ap.add_argument("--store", type=Path, default=STORE)
    ap.add_argument("--out", type=Path, default=OUT / "vector-candidates.json")
    a = ap.parse_args()
    import pyarrow.parquet as pq
    api = B.load(CORPUS)
    F, E = api.F, api.E

    def lex(w):
        s = F.strong.v(w)
        if not s:
            return None
        return ("h" if F.lang.v(w) in ("hbo", "arc") else "g") + str(s).lstrip("0").rstrip("abcdefgh")

    lemma, pos = {}, collections.defaultdict(collections.Counter)
    for w in F.otype.s("word"):
        k = lex(w)
        if k:
            pos[k][F.pos.v(w)] += 1
            if k not in lemma and F.lemma.v(w):
                lemma[k] = F.lemma.v(w)
    meta = json.loads((a.store / "lexemes.json").read_text())
    LX = np.load(a.store / "lexemes.npy")
    cnt = dict(zip(meta["keys"], meta["counts"]))
    proper = names(a.names_hbo, a.names_grc)
    usable = [k for k in meta["keys"] if cnt[k] >= a.min_count and pos[k] and pos[k].most_common(1)[0][0] in CONTENT
              and k not in proper]
    hk = [k for k in usable if k[0] == "h"]
    gk = [k for k in usable if k[0] == "g"]
    row = {k: i for i, k in enumerate(meta["keys"])}
    Hm = LX[[row[k] for k in hk]]
    Gm = LX[[row[k] for k in gk]]
    hmu, gmu = Hm.mean(0), Gm.mean(0)
    H, G = norm(Hm - hmu), norm(Gm - gmu)
    hix, gix = {k: i for i, k in enumerate(hk)}, {k: i for i, k in enumerate(gk)}

    if a.map == "lexeme":
        seed = []
        for h in F.otype.s("lexeme"):
            for g, _ in E.tier_macula.f(h):
                ws = [w for w in E.oslots.s(g) if F.strong.v(w)][:1]
                hs = [w for w in E.oslots.s(h) if F.strong.v(w)][:1]
                if ws and hs and lex(hs[0]) in hix and lex(ws[0]) in gix:
                    seed.append((lex(hs[0]), lex(ws[0])))
        W = procrustes(G[[gix[b] for _, b in seed]], H[[hix[x] for x, _ in seed]])
    else:
        rows = {}
        for t in ("tanakh", "septuagint"):
            nodes = pq.read_table(a.store / f"{t}.parquet", columns=["node"]).column("node").to_pylist()
            rows[t] = ({n: i for i, n in enumerate(nodes)}, np.load(a.store / f"{t}.npy", mmap_mode="r"))
        hr, HX = rows["tanakh"]
        gr, GX = rows["septuagint"]
        occ = []
        for w, i in hr.items():
            if lex(w) not in hix:
                continue
            for g, _label in E.lxx.f(w) or ():
                g = int(g)
                if lex(g) in gix and g in gr:
                    occ.append((i, gr[g]))
        rng = np.random.default_rng(13)
        rng.shuffle(occ)
        occ = occ[:400000]
        A_ = norm(np.asarray(GX[[g for _, g in occ]], dtype=np.float32) - gmu)
        B_ = norm(np.asarray(HX[[h for h, _ in occ]], dtype=np.float32) - hmu)
        W = procrustes(A_, B_)
        print(f"map: occurrence Procrustes on {len(occ):,} word pairs", flush=True)
    GW = norm(G @ W)

    if a.auto:
        paired = set()
        for tier in ("tier_macula", "tier_glaux"):
            for h in F.otype.s("lexeme"):
                for g, _ in getattr(E, tier).f(h):
                    ws = [w for w in E.oslots.s(g) if F.strong.v(w)][:1]
                    hs = [w for w in E.oslots.s(h) if F.strong.v(w)][:1]
                    if ws and hs:
                        paired.add(lex(hs[0]))
                        paired.add(lex(ws[0]))
        for f in a.model_pairs:
            for r in csv.DictReader(open(f, encoding="utf-8"), delimiter="\t"):
                paired.add("h" + r["hebrew_strong"].lstrip("H").lstrip("0"))
                paired.add("g" + r["greek_strong"].lstrip("G").lstrip("0"))
        nt_words = set()
        for t in F.otype.s("text"):
            if F.name.v(t) == "greek_nt":
                nt_words = {lex(w) for w in api.L.d(t, otype="word")}
        want = {"ot": sorted(int(k[1:]) for k in hk if k not in paired),
                "nt": sorted(int(k[1:]) for k in gk if k not in paired and k in nt_words)}
    else:
        want = json.load(open(a.lexemes))
    existing = {}
    if a.existing:
        for side, es in json.load(open(a.existing)).items():
            for r in es:
                existing[(side, int(r["strong"]))] = r["candidates"]

    out, missing = {"ot": [], "nt": []}, []
    for side in ("ot", "nt"):
        for s in want.get(side, []):
            k = ("h" if side == "ot" else "g") + str(s)
            cands = [dict(c) for c in existing.get((side, int(s)), [])]
            seen = {int(c["strong"]) for c in cands}
            if side == "ot" and k in hix:
                sims, vocab = GW @ H[hix[k]], gk
            elif side == "nt" and k in gix:
                sims, vocab = H @ GW[gix[k]], hk
            else:
                sims = None
            if sims is not None:
                for rank, j in enumerate(np.argsort(-sims)[: a.top], 1):
                    c = int(vocab[j][1:])
                    ev = {"rank": rank, "cos": round(float(sims[j]), 3)}
                    if c in seen:
                        next(x for x in cands if int(x["strong"]) == c).setdefault("evidence", {})["vector"] = ev
                    else:
                        cands.append({"strong": c, "lemma": lemma.get(vocab[j], ""), "tokens": cnt[vocab[j]], "evidence": {"vector": ev}})
                        seen.add(c)
            if not cands:
                missing.append(f"{side}:{s}")
                continue
            out[side].append({"strong": int(s), "lemma": lemma.get(k, ""), "tokens": cnt.get(k, 0), "candidates": cands})
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{a.out}: ot {len(out['ot'])} lexemes, nt {len(out['nt'])}; "
          f"{sum(len(r['candidates']) for v in out.values() for r in v)} candidates; {len(missing)} with none")


if __name__ == "__main__":
    main()
