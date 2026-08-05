#!/usr/bin/env python3
"""Genre/context-profile word pairs — a free, zero-licensing-risk approximation of SDBH's `ctx`
(contextual/situational) domain axis (resources/semantic_domains/README.md), which is a DIFFERENT kind
of category from the `core` concept axis every other signal in this pipeline targets: register/setting
tags (Divine, Human, Law, Sacrifices and Offerings, Warfare, Sanctuary, Priesthood, ...), not synonymy.

Method: for every Hebrew content Strong's, compute its occurrence distribution across the 39 canonical
OT books (WLC/hbo.db), L2-normalize, and pair words whose book-distribution profiles are highly similar
(cosine > MIN_COS, top-K nearest). Two words concentrated in the same books tend to share a setting —
e.g. words concentrated in Leviticus skew toward Sacrifices/Priesthood/Sanctuary — a genuinely different
signal from anything embedding/lexical/structural in this pipeline, derived entirely from public-domain
WLC occurrence counts (zero external dependency, zero licensing risk).

Validated 2026-08 against SDBH's own `ctx` axis (internal yardstick only, same as everywhere else):
45.6% same-domain agreement (9,323 pairs) vs. a 13.81% random-chance baseline for that axis — a real
~3.3x lift, though clearly weaker than every `core`-axis signal in this pipeline (BDB 50.6%, structural
61.7%+, HWN 89.7%). Expected: this is a cruder proxy (which books a word appears in) for a fundamentally
coarser category (setting, not concept) — not a quality regression, a different, harder target.

NOT wired into build_semantic_neighbors.py — that pipeline's signals all target the `core` axis
(same-domain/synonymy clustering); mixing a `ctx`-shaped signal in would repeat this project's own
"core"-vs-"blended axis" methodology mistake (see domain-replacement-roadmap.md's methodology-fix note)
in the opposite direction. This is a standalone artifact for a future, separate "contextual setting"
feature, not clustering fuel for the current one.

  python -m macula.build_genre_context_pairs
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HBO = ROOT / "resources" / "occurrences" / "hbo.db"
OUT_DIR = ROOT / "resources" / "genre_context"

MIN_OCC = 5     # a Strong's needs >= this many total occurrences for a stable book-distribution profile
MIN_COS = 0.90  # validated 2026-08: 0.90 gives 45.6% ctx-agreement at a real volume (9,323 pairs);
                # 0.88 -> 44.2%/11,423 pairs, 0.92 -> 47.9%/7,312 pairs — a smooth precision/recall knob
TOPK = 10


def build() -> list[tuple[str, str, float]]:
    """[(strong_a, strong_b, cosine)] — pairs with highly similar per-book occurrence profiles."""
    conn = sqlite3.connect(f"file:{HBO}?mode=ro", uri=True)
    strong_book: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    books: set[str] = set()
    for strong, book in conn.execute("SELECT strong, book FROM occurrence WHERE strong IS NOT NULL"):
        strong_book[strong][book] += 1
        books.add(book)
    book_list = sorted(books)

    strongs = [s for s, c in strong_book.items() if sum(c.values()) >= MIN_OCC]
    M = np.array([[strong_book[s].get(b, 0) for b in book_list] for s in strongs], dtype=float)
    M /= (M.sum(axis=1, keepdims=True) + 1e-9)          # occurrence share per book
    M /= (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)  # L2-normalize for cosine via dot product
    print(f"[genre-context] {len(strongs)} Strong's with >= {MIN_OCC} occurrences across "
          f"{len(book_list)} books", file=sys.stderr)

    pairs: dict[frozenset, float] = {}
    for i, s in enumerate(strongs):
        sims = M @ M[i]
        sims[i] = -1
        top = np.argpartition(-sims, TOPK)[:TOPK]
        for j in top:
            if sims[j] > MIN_COS:
                key = frozenset((s, strongs[j]))
                pairs[key] = max(pairs.get(key, 0.0), float(sims[j]))
    print(f"[genre-context] {len(pairs)} pairs (cos > {MIN_COS})", file=sys.stderr)
    return [(*sorted(pair), round(cos, 4)) for pair, cos in pairs.items()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT_DIR / "context_pairs.tsv")
    args = ap.parse_args()

    rows = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write("# Hebrew Strong's pairs with highly similar per-book occurrence profiles — a free\n"
                  "# approximation of SDBH's `ctx` (contextual/situational) domain axis, NOT the `core`\n"
                  "# (concept/synonymy) axis every other signal in this pipeline targets. Derived entirely\n"
                  "# from public-domain WLC occurrence counts. Validated 2026-08 at 45.6% SDBH ctx-agreement\n"
                  "# vs. 13.81% random baseline. NOT wired into build_semantic_neighbors.py — see\n"
                  "# build_genre_context_pairs.py's docstring for why.\n")
        fh.write("strong_a\tstrong_b\tcosine\n")
        for a, b, cos in sorted(rows, key=lambda r: (r[0], -r[2])):
            fh.write(f"{a}\t{b}\t{cos}\n")
    print(f"[genre-context] -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
