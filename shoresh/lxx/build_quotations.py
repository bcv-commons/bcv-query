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


# LXX Psalm chapters whose mapping to KJV involves a merge/split (9|10, 114|115, 116, 147|148) — a
# verse in one of these that the single-verse V1 scheme doesn't list is genuinely uncertain (needs the
# range map), so we flag it. Everywhere else, "not in the scheme" = identity with the KJV standard.
_LXX_PSALM_MERGE = {9, 113, 114, 115, 146, 147}

_LXX_KJV: dict | None = None


def _to_standard(book, ch, v):
    """Normalize an LXX OT ref to the KJV standard via the V1 `lxx` versification scheme
    (`resources/versification/schemes/lxx.tsv`, from STEPBible TVTMS). Returns (book, ch, v, vrs)."""
    global _LXX_KJV
    if _LXX_KJV is None:
        _LXX_KJV = {}
        p = ROOT / "resources" / "versification" / "schemes" / "lxx.tsv"
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines():
                if ln.startswith("#") or ln.startswith("source_ref"):
                    continue
                f = ln.split("\t")
                if len(f) >= 2:
                    _LXX_KJV[f[0]] = f[1]
    std = _LXX_KJV.get(f"{book} {ch}:{v}")
    if std:
        b, rest = std.split(" ", 1)
        c, vv = rest.split(":")
        return b, c, vv, "kjv"
    vrs = "lxx?" if (book == "PSA" and ch in _LXX_PSALM_MERGE) else "kjv"
    return book, str(ch), str(v), vrs


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
        fh.write("# ot_ref is KJV-standard (normalized from LXX via the V1 lxx versification scheme); "
                 "vrs=lxx? marks a residual merge-Psalm verse not in the single-verse scheme\n")
        fh.write("nt_ref\tot_ref\tconfidence\tvrs\tn_shared\tscore\tshared_strongs\n")
        for nt, ot, n, sc, sh in final:
            b, ch, v, vrs = _to_standard(*ot)
            conf = "high" if sc >= STRONG_SCORE else "med"
            fh.write(f"{_ref(*nt)}\t{_ref(b, ch, v)}\t{conf}\t{vrs}\t{n}\t{sc}\t"
                     f"G{','.join(f'{s:04d}' for s in sorted(sh))}\n")
    print(f"[quotations] {len(final)} NT→OT links over {len(by_nt)} NT verses "
          f"-> {OUT_DIR/'quotations.tsv'}", file=sys.stderr)
    return final


if __name__ == "__main__":
    build()
