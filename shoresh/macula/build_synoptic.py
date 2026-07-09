#!/usr/bin/env python3
"""Synoptic Gospel parallels (roadmap X2) — which Gospel verses tell the same passage.

Same technique as the OT-in-NT quotation detector (X1), applied *within* the four Gospels: a verse in
one Gospel and its parallel in another share the same **content Greek Strong's**. Score = IDF-cosine of
the two verses' content-Strong's bags (rare shared words like ἀγρός/μαργαρίτης drive it; common ones
barely count; the cosine's length-normalization stops long verses from colliding). Cross-Gospel pairs
only (a parallel is between Gospels), symmetric-deduped.

  python -m macula.build_synoptic          # -> resources/synoptic_parallels/parallels.tsv
"""
from __future__ import annotations

import collections
import math
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from references import BOOK_NUMBERS  # noqa: E402

MACULA = HERE / "macula-spine.db"
OUT_DIR = ROOT / "resources" / "synoptic_parallels"

GOSPELS = ("MAT", "MRK", "LUK", "JHN")
_CONTENT = {"noun", "verb", "adj", "adv"}
MIN_SHARED = 3        # shared content Strong's required
MIN_SCORE = 0.30      # IDF-cosine floor (∈[0,1]); tuned on known parallels
STRONG_SCORE = 0.45   # confidence=high above this
TOPK = 4              # parallel candidates kept per verse (a pericope spans ≤3 other Gospels)


def _ref(book, ch, v):
    return f"{book} {ch}:{v}"


def build():
    m = sqlite3.connect(f"file:{MACULA}?mode=ro", uri=True)
    verse: dict = collections.defaultdict(set)          # (book,ch,v) -> {content strong}
    qmarks = ",".join("?" * len(GOSPELS))
    for book, ch, v, strong, cls in m.execute(
            f"SELECT book, chapter, verse, strong, class FROM macula_words "
            f"WHERE lang='grc' AND book IN ({qmarks}) AND strong IS NOT NULL AND strong != ''",
            GOSPELS):
        if cls in _CONTENT:
            verse[(book, ch, v)].update(int(x) for x in re.findall(r"\d+", str(strong)))

    N = len(verse)
    df: collections.Counter = collections.Counter()
    inv: dict = collections.defaultdict(list)
    for ref, ss in verse.items():
        for s in ss:
            df[s] += 1
            inv[s].append(ref)
    idf = {s: math.log(N / df[s]) for s in df}
    norm = {ref: math.sqrt(sum(idf[s] ** 2 for s in ss)) or 1.0 for ref, ss in verse.items()}
    print(f"[synoptic] {N} Gospel verses, {len(df)} content strongs", file=sys.stderr)

    # For each verse, IDF-cosine against candidate verses in OTHER Gospels sharing content strongs.
    pairs: dict = {}                                    # frozenset({refA,refB}) -> (n_shared, score, shared)
    for ref, ss in verse.items():
        dot: collections.Counter = collections.Counter()
        shared: dict = collections.defaultdict(list)
        for s in ss:
            w = idf.get(s, 0.0)
            if w <= 0:
                continue
            for other in inv.get(s, ()):
                if other[0] == ref[0]:                  # same Gospel — not a parallel
                    continue
                dot[other] += w * w
                shared[other].append(s)
        scored = sorted(((o, d / (norm[ref] * norm[o])) for o, d in dot.items()),
                        key=lambda kv: -kv[1])[:TOPK * 2]
        for other, score in scored:
            sh = shared[other]
            if len(sh) < MIN_SHARED or score < MIN_SCORE:
                continue
            key = frozenset((ref, other))
            if key not in pairs or score > pairs[key][1]:
                pairs[key] = (len(sh), round(score, 3), sh)

    rows = []
    for key, (n, score, sh) in pairs.items():
        a, b = sorted(key, key=lambda r: (BOOK_NUMBERS.get(r[0], 99), r[1], r[2]))
        rows.append((a, b, n, score, sh))
    rows.sort(key=lambda r: (BOOK_NUMBERS.get(r[0][0], 99), r[0][1], r[0][2], -r[3]))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "parallels.tsv").open("w", encoding="utf-8") as fh:
        fh.write("# Synoptic Gospel parallels via shared content Greek Strong's (IDF-cosine); "
                 "shoresh macula.build_synoptic. Cross-Gospel, symmetric-deduped.\n")
        fh.write("ref_a\tref_b\tconfidence\tn_shared\tscore\tshared_strongs\n")
        for a, b, n, score, sh in rows:
            conf = "high" if score >= STRONG_SCORE else "med"
            fh.write(f"{_ref(*a)}\t{_ref(*b)}\t{conf}\t{n}\t{score}\t"
                     f"G{','.join(f'{s:04d}' for s in sorted(sh))}\n")
    hi = sum(1 for r in rows if r[3] >= STRONG_SCORE)
    print(f"[synoptic] {len(rows)} parallel pairs ({hi} high-conf) -> {OUT_DIR/'parallels.tsv'}",
          file=sys.stderr)
    return rows


if __name__ == "__main__":
    build()
