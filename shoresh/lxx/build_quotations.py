#!/usr/bin/env python3
"""OT-in-NT quotations (roadmap X1) — detect which OT verse an NT passage quotes, via the LXX.

The NT quotes the Greek OT (LXX), so an NT verse and the OT verse it quotes share the same Greek
words. We match **content Greek Strong's**, weighted by rarity (IDF over LXX verses): sharing rare
words (ἄρτος, μάννα) is a strong quotation signal; sharing common ones (θεός, λέγω) is not. The LXX
verse's `(book, chapter, verse)` IS the canonical OT reference, so a match yields the OT link directly.

  python -m lxx.build_quotations              # -> resources/ot_nt_quotations/quotations.tsv
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

LXX = HERE / "lxx.db"
MACULA = ROOT / "shoresh" / "macula" / "macula-spine.db"
OUT_DIR = ROOT / "resources" / "ot_nt_quotations"

_NT_CONTENT = {"noun", "verb", "adj", "adv"}
MIN_SHARED = 3        # shared content Strong's required
MIN_SCORE = 0.30      # IDF-cosine floor (∈[0,1]); tuned on known quotations
STRONG_SCORE = 0.45   # confidence=high above this
TOPK = 3              # OT candidates kept per NT verse


def _ref(book, ch, v):
    return f"{book} {ch}:{v}"


def _psalm_lxx_to_mt(ch):
    """LXX Psalm chapter -> (Masoretic/English chapter, safe?).

    The LXX Psalter is numbered one behind the Hebrew across two clean blocks (from the
    9|10 merge and the 114|115 merge). Chapter-level shift only; verse numbers are stable
    inside these blocks. The merge/split boundary Psalms (9, 113, 114, 115, 146, 147) need a
    verse-level map (roadmap V1) — we leave those in LXX numbering and flag them unsafe.
    """
    if 10 <= ch <= 112 or 116 <= ch <= 145:   # clean −1 blocks
        return ch + 1, True
    if 1 <= ch <= 8 or 148 <= ch <= 150:       # identity blocks
        return ch, True
    return ch, False                           # 9, 113, 114, 115, 146, 147 — merge/split


def _to_mt(book, ch, v):
    """Normalize an LXX OT ref to Masoretic/English numbering. Returns (book, ch, v, vrs)."""
    if book == "PSA":
        mt_ch, safe = _psalm_lxx_to_mt(ch)
        return book, mt_ch, v, ("mt" if safe else "lxx?")
    return book, ch, v, "mt"


def build():
    lx = sqlite3.connect(f"file:{LXX}?mode=ro", uri=True)
    lxx_verse: dict = collections.defaultdict(set)          # (book,ch,v) -> {strong}
    for book, ch, v, strong in lx.execute(
            "SELECT book, chapter, verse, strong FROM lxx_words "
            "WHERE is_content=1 AND strong IS NOT NULL AND strong != ''"):
        lxx_verse[(book, ch, v)].update(int(x) for x in re.findall(r"\d+", str(strong)))
    N = len(lxx_verse)
    df: collections.Counter = collections.Counter()
    inv: dict = collections.defaultdict(list)
    for ref, ss in lxx_verse.items():
        for s in ss:
            df[s] += 1
            inv[s].append(ref)
    idf = {s: math.log(N / df[s]) for s in df}
    # IDF-cosine magnitude per LXX verse (length normalizer — kills giant-verse false positives)
    lxx_norm = {ref: math.sqrt(sum(idf[s] ** 2 for s in ss)) or 1.0 for ref, ss in lxx_verse.items()}
    print(f"[quotations] LXX: {N} verses, {len(df)} content strongs", file=sys.stderr)

    m = sqlite3.connect(f"file:{MACULA}?mode=ro", uri=True)
    nt_verse: dict = collections.defaultdict(set)
    for book, ch, v, strong, cls in m.execute(
            "SELECT book, chapter, verse, strong, class FROM macula_words "
            "WHERE lang='grc' AND strong IS NOT NULL AND strong != ''"):
        if cls in _NT_CONTENT:
            nt_verse[(book, ch, v)].update(int(x) for x in re.findall(r"\d+", str(strong)))

    rows = []
    for ntref, ss in nt_verse.items():
        dot: collections.Counter = collections.Counter()      # Σ idf² over shared strongs
        shared: dict = collections.defaultdict(list)
        nt_norm = math.sqrt(sum(idf[s] ** 2 for s in ss if s in idf)) or 1.0
        for s in ss:
            w = idf.get(s, 0.0)
            if w <= 0:
                continue
            for lref in inv.get(s, ()):
                dot[lref] += w * w
                shared[lref].append(s)
        cand = {lref: d / (nt_norm * lxx_norm[lref]) for lref, d in dot.items()}   # IDF-cosine
        for lref, score in sorted(cand.items(), key=lambda kv: -kv[1])[:TOPK * 3]:
            sh = shared[lref]
            if len(sh) >= MIN_SHARED and score >= MIN_SCORE:
                rows.append((ntref, lref, len(sh), round(score, 3), sh))
        # keep only the top TOPK for this NT verse
    # rank per NT verse, keep TOPK
    by_nt: dict = collections.defaultdict(list)
    for r in rows:
        by_nt[r[0]].append(r)
    final = []
    for ntref, rs in by_nt.items():
        for r in sorted(rs, key=lambda x: -x[3])[:TOPK]:
            final.append(r)
    final.sort(key=lambda r: (BOOK_NUMBERS.get(r[0][0], 99), r[0][1], r[0][2], -r[3]))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "quotations.tsv").open("w", encoding="utf-8") as fh:
        fh.write("# OT-in-NT quotations via LXX Strong's overlap (IDF-weighted); shoresh lxx.build_quotations\n")
        fh.write("# ot_ref is Masoretic/English numbering; vrs=lxx? marks a boundary Psalm left in LXX numbering (needs V1 verse-map)\n")
        fh.write("nt_ref\tot_ref\tconfidence\tvrs\tn_shared\tscore\tshared_strongs\n")
        for nt, ot, n, sc, sh in final:
            b, ch, v, vrs = _to_mt(*ot)
            conf = "high" if sc >= STRONG_SCORE else "med"
            fh.write(f"{_ref(*nt)}\t{_ref(b, ch, v)}\t{conf}\t{vrs}\t{n}\t{sc}\t"
                     f"G{','.join(f'{s:04d}' for s in sorted(sh))}\n")
    print(f"[quotations] {len(final)} NT→OT links over {len(by_nt)} NT verses "
          f"-> {OUT_DIR/'quotations.tsv'}", file=sys.stderr)
    return final


if __name__ == "__main__":
    build()
