"""Slot-sharing pairs from MACULA Hebrew's verb frames: words that do the same things, or have the same
things done to them.

MACULA Hebrew annotates verb-argument frames (macula-spine.db `frames`: verb, role A0/A1/A2/AA, argument head;
CC BY 4.0): בָּרָא A0 אֱלֹהִים, A1 שָׁמַיִם. A noun is described by the (verb, role) slots it fills, a verb by the
(role, argument) pairs it takes. Profiles are PPMI-weighted; two words pair when they are mutual nearest
neighbours (top K) with cosine >= MIN_COS and each has at least MIN_SLOTS frame instances. A distributional
signal of a different kind from the BEREL word windows: grammatical role rather than nearby words.

  python -m macula.build_verb_frames        # -> resources/verb_frames/candidate_pairs.tsv
"""
from __future__ import annotations

import collections
import math
import sqlite3
import sys
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MACULA = HERE / "macula-spine.db"
SPINE = HERE / "lexeme-spine-macula.db"
OUT = ROOT / "resources" / "verb_frames" / "candidate_pairs.tsv"
K = 5
MIN_COS = 0.25
MIN_SLOTS = 8


def profiles():
    pos = {r["lexeme"]: r["pos"] for r in pq.read_table(ROOT / "resources" / "prior_pack" / "prior_pack.parquet",
                                                         columns=["lexeme", "pos"]).to_pylist()}
    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    lex_of = {k: lx for k, lx in sp.execute("SELECT key, lexeme FROM spine_words WHERE lexeme LIKE 'hbo:%'")}
    m = sqlite3.connect(f"file:{MACULA}?mode=ro", uri=True)
    noun_prof: dict = collections.defaultdict(collections.Counter)
    verb_prof: dict = collections.defaultdict(collections.Counter)
    for vk, role, ak in m.execute("SELECT verb_key, role, arg_key FROM frames WHERE CAST(substr(verb_key,1,2) AS INT) < 40"):
        v, a = lex_of.get(vk), lex_of.get(ak)
        if not v or not a or pos.get(v) != "verb" or pos.get(a) not in ("noun", "adj"):
            continue
        noun_prof[a][(v, role)] += 1
        verb_prof[v][(role, a)] += 1
    return noun_prof, verb_prof


def ppmi(prof: dict) -> dict:
    total = sum(sum(c.values()) for c in prof.values())
    feat = collections.Counter()
    for c in prof.values():
        feat.update(c)
    out = {}
    for w, c in prof.items():
        nw = sum(c.values())
        vec = {}
        for f, n in c.items():
            v = math.log((n * total) / (nw * feat[f]))
            if v > 0:
                vec[f] = v
        norm = math.sqrt(sum(x * x for x in vec.values())) or 1.0
        out[w] = {f: x / norm for f, x in vec.items()}
    return out


def neighbours(vecs: dict, prof: dict) -> list[tuple]:
    words = [w for w in vecs if sum(prof[w].values()) >= MIN_SLOTS]
    by_feat = collections.defaultdict(list)
    for w in words:
        for f, x in vecs[w].items():
            by_feat[f].append((w, x))
    top = {}
    for w in words:
        score = collections.Counter()
        for f, x in vecs[w].items():
            for o, y in by_feat[f]:
                if o != w:
                    score[o] += x * y
        top[w] = [(o, s) for o, s in score.most_common(K) if s >= MIN_COS]
    pairs = []
    for w, ns in top.items():
        for o, s in ns:
            if w < o and any(x == w for x, _ in top.get(o, [])):
                pairs.append((w, o, round(s, 3)))
    return pairs


def main() -> int:
    noun_prof, verb_prof = profiles()
    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    strong = {lx: f"H{int(s):04d}" for lx, s in sp.execute(
        "SELECT lexeme, strong FROM spine_words WHERE lexeme LIKE 'hbo:%' AND strong IS NOT NULL GROUP BY lexeme")}
    rows = []
    for kind, prof in (("noun", noun_prof), ("verb", verb_prof)):
        pairs = neighbours(ppmi(prof), prof)
        rows += [(strong.get(a, ""), strong.get(b, ""), a, b, kind, s) for a, b, s in pairs]
        print(f"[verb-frames] {kind}s with >= {MIN_SLOTS} frame instances: "
              f"{sum(1 for w in prof if sum(prof[w].values()) >= MIN_SLOTS)}; mutual-kNN pairs: {len(pairs)}",
              file=sys.stderr)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        fh.write("# CANDIDATE Hebrew pairs from MACULA Hebrew verb frames (CC BY 4.0): nouns filling the same verb "
                 "slots, verbs taking\n# the same arguments (PPMI cosine, mutual top-5). Derived data CC0. Built by "
                 "shoresh/macula/build_verb_frames.py.\n")
        fh.write("strong_a\tstrong_b\tlexeme_a\tlexeme_b\tkind\tcosine\n")
        for r in sorted(rows, key=lambda r: -r[5]):
            if r[0] and r[1] and r[0] != r[1]:
                fh.write("\t".join(map(str, r)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
