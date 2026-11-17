"""A concept for unsure Greek NT words from the world's translations: occurrences of one Greek lexeme that most translations render
alike are taken to carry the same concept. Measured, not released.

Result (2026-11-17, 196 languages, one edition each, English from the BSB; rend.pkl at the pins below): it fails the bar research
set (well above 0.8 on the quoted unsure words it labels). Quoted unsure words: rend 0.408 (262 words; margin >= 0.1: 0.495, 97),
Jev 0.551, Opus 0.706; where rend and Opus agree 0.752 (101). Held-out confident anchors, competing concepts: 0.886 (0.960 with
margin >= 0.1), so the method works on easy words and not on the unsure ones. Not pursued; more languages would not close the gap.

    python -m macula.nt_concepts_by_rend --jev FILE [--opus]  -> macula/data/greek-nt-concepts/rend/{predictions.parquet,report.json}

Inputs: build_nt_rend's rend.pkl (rendering ids per Greek word and edition); label_greek_nt_concepts' items.jsonl (each word's concept
list); Jev's answers; with --opus, Opus's answers (labelling/opus_answers.jsonl).

Anchors: the words of a Greek lexeme (Strong's number) that Jev labelled with confidence >= 0.8 and a concept. For a word u, the
similarity to an anchor a is the share of languages that render both alike: per edition that renders both, 1 if the two rendering ids
are equal, weighted 1 / (editions of its language) so that each language counts once; English is read from the BSB alone. A concept's score is the mean similarity of
its K most similar anchors (fewer if it has fewer); the word gets the concept with the highest score among the concepts on its own
list; `margin` = best minus second best (the second is 0 where only one concept has anchors).

Checks, all printed in report.json:
  held-out anchors  each anchor predicted from the other anchors: agreement with Jev's confident label (Jev is right about 93% there)
  quoted words      the words whose Tanakh word's concept is known (the pilot's check): rend against Jev and Opus
  agreement         on the unsure words: rend against Opus, and where both agree
"""
from __future__ import annotations

import argparse
import collections
import json
import pickle
from pathlib import Path

import numpy as np

from macula import build_greek_nt_concepts as g
from macula import label_greek_nt_concepts as lab
from macula import pilot_greek_nt_concepts as p
from macula.build_nt_rend import OUT as REND

OUT = g.OUT / "rend"
K = 5
ONLY = {"eng": "eng_BSB"}                                               # a language read from one edition only
MIN_EDITIONS = 20                                                       # editions that render both words, below this no similarity


def matrix(ids: list[str], feats: dict, n_ed: int) -> np.ndarray:
    m = np.zeros((len(ids), n_ed), dtype=np.int32)                      # 0 = not rendered there
    for i, w in enumerate(ids):
        for e, r in feats.get(w, ()):
            if not m[i, e]:
                m[i, e] = r + 1
    return m


def similarity(a: np.ndarray, b: np.ndarray, w: np.ndarray, chunk: int = 16) -> np.ndarray:
    """rows of a against rows of b: weighted share of shared editions with the same rendering"""
    num = np.zeros((len(a), len(b)), dtype=np.float32)
    den = np.zeros((len(a), len(b)), dtype=np.float32)
    cnt = np.zeros((len(a), len(b)), dtype=np.int32)
    for s in range(0, a.shape[1], chunk):
        x, y, ww = a[:, s:s + chunk], b[:, s:s + chunk], w[s:s + chunk]
        both = (x[:, None, :] > 0) & (y[None, :, :] > 0)
        same = both & (x[:, None, :] == y[None, :, :])
        den += (both * ww).sum(-1)
        num += (same * ww).sum(-1)
        cnt += both.sum(-1)
    out = np.where(cnt >= MIN_EDITIONS, num / np.maximum(den, 1e-9), np.nan)
    return out


def predict(sim_row: np.ndarray, anchor_concepts: list[str], allowed: set[str]) -> tuple[str, float, float]:
    by = collections.defaultdict(list)
    for s, c in zip(sim_row, anchor_concepts):
        if c in allowed and not np.isnan(s):
            by[c].append(s)
    if not by:
        return "", 0.0, 0.0
    score = sorted(((float(np.mean(sorted(v, reverse=True)[:K])), c) for c, v in by.items()), reverse=True)
    best, second = score[0], score[1][0] if len(score) > 1 else 0.0
    return best[1], best[0], best[0] - second


def run(jev_file: Path, with_opus: bool) -> dict:
    import pyarrow as pa
    import pyarrow.parquet as pq
    d = pickle.load((REND / "rend.pkl").open("rb"))
    eds, feats = d["editions"], d["features"]
    use = [ONLY.get(i, e) == e for i, e in eds]                          # English: the BSB alone (the user's choice)
    per_lang = collections.Counter(i for (i, _), u in zip(eds, use) if u)
    w = np.array([1.0 / per_lang[i] if u else 0.0 for (i, _), u in zip(eds, use)], dtype=np.float32)
    items = [json.loads(x) for x in (lab.OUT / "items.jsonl").read_text(encoding="utf-8").splitlines()]
    jev = p.load_jev(jev_file, items)
    opus = p.load_answers(lab.OUT / "opus_answers.jsonl")[0] if with_opus else {}
    con = g.Concepts(g.CONCEPTS)
    gold = {it["id"]: con.label[it["tanakh"]] for it in items if it.get("tanakh") and it["tanakh"] in con.label}
    by_lex = collections.defaultdict(list)
    for it in items:
        if it["id"] in jev and len(it["inventory"]) > 1:
            by_lex[it["greek_strong"]].append(it)
    rows, held = [], collections.Counter()
    for lex, its in by_lex.items():
        anchors = [it for it in its if jev[it["id"]]["sure"] and jev[it["id"]]["concept"]]
        unsure = [it for it in its if not jev[it["id"]]["sure"]]
        if not anchors:
            for it in unsure:
                rows.append({"greek_id": it["id"], "set": it["set"], "rend_concept": "", "score": 0.0, "margin": 0.0, "anchors": 0})
            continue
        A = matrix([it["id"] for it in anchors], feats, len(eds))
        ac = [jev[it["id"]]["concept"] for it in anchors]
        if unsure:
            S = similarity(matrix([it["id"] for it in unsure], feats, len(eds)), A, w)
            for it, row in zip(unsure, S):
                c, sc, mg = predict(row, ac, set(it["inventory"]))
                rows.append({"greek_id": it["id"], "set": it["set"], "rend_concept": c, "score": sc, "margin": mg, "anchors": len(anchors)})
        if len(anchors) > 1:                                            # held-out anchors (at most 200 per lexeme)
            pick = anchors[:200]
            S = similarity(A[:len(pick)], A, w)
            for i, (it, row) in enumerate(zip(pick, S)):
                row = row.copy()
                row[i] = np.nan
                c, sc, mg = predict(row, ac, set(it["inventory"]))
                key = "competing" if len({x for x in ac if x in it["inventory"]}) > 1 else "one concept among anchors"
                held[f"{key}: tried"] += 1
                held[f"{key}: predicted"] += bool(c)
                held[f"{key}: same as jev"] += c == ac[i]
                if key == "competing" and c and mg >= 0.1:
                    held["competing, margin >= 0.1: predicted"] += 1
                    held["competing, margin >= 0.1: same as jev"] += c == ac[i]
    by = {r["greek_id"]: r for r in rows}
    rep = {"editions": len(eds), "languages": len(per_lang), "unsure words": len(rows),
           "with a prediction": sum(bool(r["rend_concept"]) for r in rows), "held-out anchors": dict(held)}
    q = [(by[i], gold[i]) for i in by if i in gold]
    def acc(pairs, f):
        pairs = [(r, gd) for r, gd in pairs if f(r) is not None]
        return {"words": len(pairs), "right": p.share(sum(f(r) == gd for r, gd in pairs), len(pairs))}
    rep["quoted unsure words"] = {"rend (where it predicts)": acc(q, lambda r: r["rend_concept"] or None),
                                  "rend, margin >= 0.1": acc([x for x in q if x[0]["margin"] >= 0.1], lambda r: r["rend_concept"] or None),
                                  "jev": acc(q, lambda r: jev[r["greek_id"]]["concept"])}
    if opus:
        rep["quoted unsure words"]["opus"] = acc(q, lambda r: opus[r["greek_id"]]["concept"] if r["greek_id"] in opus else None)
        both = [x for x in q if x[0]["rend_concept"] and x[0]["greek_id"] in opus and opus[x[0]["greek_id"]]["concept"] == x[0]["rend_concept"]]
        rep["quoted unsure words"]["rend and opus agree"] = acc(both, lambda r: r["rend_concept"])
        apart = [x for x in q if x[0]["rend_concept"] and x[0]["greek_id"] in opus and opus[x[0]["greek_id"]]["concept"] != x[0]["rend_concept"]]
        rep["quoted unsure words"]["rend and opus differ: rend"] = acc(apart, lambda r: r["rend_concept"])
        rep["quoted unsure words"]["rend and opus differ: opus"] = acc(apart, lambda r: opus[r["greek_id"]]["concept"])
        pr = [r for r in rows if r["rend_concept"] and r["greek_id"] in opus]
        rep["all unsure words: rend agrees with opus"] = {"words": len(pr), "share": p.share(sum(opus[r["greek_id"]]["concept"] == r["rend_concept"] for r in pr), len(pr))}
    OUT.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), OUT / "predictions.parquet")
    (OUT / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return rep


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--jev", type=Path, required=True)
    ap.add_argument("--opus", action="store_true")
    a = ap.parse_args()
    print(json.dumps(run(a.jev, a.opus), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
