"""Split broad settings in two: the topic model run again on one setting's own passages and words.

The setting axis (build_setting_axis.py, k=40) has a few large settings (each 5-8% of content tokens: covenant
and land, family narrative, household narrative, battle). This takes a finished build, and for each named
setting fits a two-topic NMF on the passages and words assigned to it (same weighting as the main build,
document frequencies counted within the setting), then reassigns those occurrences between the halves the
same way (argmax W[passage] * P(word|half)^alpha; words outside the sub-vocabulary by passage). The first
half keeps the setting id, the second gets the next free id. Everything else is copied unchanged, so the
result can be scored head-to-head with setting_scorecard.

  python -m macula.split_settings --src k40a05 --split s06 s28 s38 s39 --out k40a05x
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import sys
from pathlib import Path

import numpy as np

from macula.build_setting_axis import MIN_UNITS, content_lexemes, nmf, passages

HERE = Path(__file__).resolve().parent
SETTINGS = HERE / "data" / "settings"


def split(src: str, which: list[str], out: str, alpha: float = 0.5, seeds=(13, 17, 23)) -> None:
    lex = content_lexemes()
    _units, where = passages()
    topics = json.loads((SETTINGS / src / "topics.json").read_text(encoding="utf-8"))
    rows = []
    with (SETTINGS / src / "occurrences.tsv").open(encoding="utf-8") as fh:
        header = next(fh)
        for line in fh:
            rows.append(line.rstrip("\n").split("\t"))
    next_id = max(int(t["topic"][1:]) for t in topics) + 1
    for s in which:
        mine = [i for i, r in enumerate(rows) if r[5] == s]
        tf = collections.defaultdict(collections.Counter)
        for i in mine:
            b, c, v, _idx, w = rows[i][:5]
            if rows[i][7] == "word":          # the main model's vocabulary only (no say/be/go-type words)
                tf[where[(b, int(c), int(v))]][w] += 1
        units = sorted(tf)
        row_of = {u: j for j, u in enumerate(units)}
        df = collections.Counter(w for u in tf for w in tf[u])
        vocab = sorted(w for w, d in df.items() if d >= MIN_UNITS)
        col = {w: j for j, w in enumerate(vocab)}
        X = np.zeros((len(units), len(vocab)), dtype=np.float32)
        for u, cnt in tf.items():
            for w, n in cnt.items():
                if w in col:
                    X[row_of[u], col[w]] = (1 + math.log(n)) * math.log(len(units) / df[w])
        W, H, err = min((nmf(X, 2, sd) for sd in seeds), key=lambda r: r[2])
        P = H / (H.sum(axis=1, keepdims=True) + 1e-12)
        new = f"s{next_id:02d}"
        next_id += 1
        ids = [s, new]
        n = collections.Counter()
        for i in mine:
            b, c, v, _idx, w = rows[i][:5]
            u = where[(b, int(c), int(v))]
            if u not in row_of:                  # a passage with only passage-assigned words: keep the first half
                rows[i][5] = s
                n[s] += 1
                continue
            wu = W[row_of[u]]
            sc = wu * P[:, col[w]] ** alpha if (w in col and rows[i][7] == "word") else wu
            h = int(sc.argmax()) if sc.sum() > 0 else 0
            rows[i][5] = ids[h]
            n[ids[h]] += 1
        for h, tid in enumerate(ids):
            top = np.argsort(-P[h])[:12]
            entry = {"topic": tid, "words": [{"lexeme": vocab[j], "strong": lex[vocab[j]]["strong"],
                                              "lemma": lex[vocab[j]]["lemma"], "p": round(float(P[h, j]), 5)}
                                             for j in top]}
            if tid == s:
                topics[[t["topic"] for t in topics].index(s)] = entry
            else:
                topics.append(entry)
            print(f"[split] {s} -> {tid}: {n[tid]} tokens, "
                  f"{', '.join(w['lemma'] for w in entry['words'][:4])}", file=sys.stderr)
    dst = SETTINGS / out
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "topics.json").write_text(json.dumps(topics, ensure_ascii=False, indent=1), encoding="utf-8")
    with (dst / "occurrences.tsv").open("w", encoding="utf-8") as fh:
        fh.write(header)
        for r in rows:
            fh.write("\t".join(r) + "\n")
    (dst / "meta.json").write_text(json.dumps({"src": src, "split": which, "alpha": alpha,
                                                "settings": len(topics)}, indent=1), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", default="k40a05")
    ap.add_argument("--split", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    split(a.src, a.split, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
