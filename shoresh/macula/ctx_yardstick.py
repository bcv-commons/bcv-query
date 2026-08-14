#!/usr/bin/env python3
"""Text-anchored yardstick for the `ctx`-axis genre_context signal (build_genre_context_pairs.py) --
a third companion to intrinsic_yardstick.py (distributional/structural) and etymology_yardstick.py
(etymological/lexical-external). Neither of those is axis-appropriate here either: genre_context
targets SDBH's `ctx` (register/setting: Divine, Law, Warfare, Sanctuary...) axis, not `core`
(concept/synonymy) -- a genuinely different kind of category, same distinction the project already
separated once when it found mixing NC domain_type axes inflated agreement (see
build_domain_clusters.py's _load_domains(), now removed).

Method mirrors build_genre_context_pairs.py's own EXACTLY -- occurrence share per book, L2-normalized,
cosine similarity -- just computed INDEPENDENTLY on train-books-only and test-books-only occurrence
data (book-level split reused from intrinsic_yardstick.book_split()), so this is a genuine held-out
generalization check: does a pair that clears the production MIN_COS=0.90 bar on training books ALSO
clear the same bar on entirely unseen books, or did it just fit the training half?

  python -m macula.ctx_yardstick --report
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
import sys
from pathlib import Path

import numpy as np

from macula.intrinsic_yardstick import SEED, TRAIN_FRAC, FrequencyMatcher, book_split, summarize

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HBO = ROOT / "resources" / "occurrences" / "hbo.db"
CONTEXT_PAIRS = ROOT / "resources" / "genre_context" / "context_pairs.tsv"

MIN_OCC = 3      # lower than the production MIN_OCC=5 (whole-OT) -- each split has fewer books
MIN_COS = 0.90   # same bar build_genre_context_pairs.py itself uses -- reused deliberately, see docstring


def build_book_profiles(books: set[str]) -> tuple[dict[str, np.ndarray], dict[str, int]]:
    """(strong -> L2-normalized occurrence-share vector, strong -> raw total occurrence count) over
    THIS split's own books only -- mirrors build_genre_context_pairs.py's build() exactly, restricted
    to one split's books. Raw counts are kept separately (not derivable from the normalized vector)
    for frequency-matched baseline weighting -- see CtxYardstick.__init__."""
    db = sqlite3.connect(f"file:{HBO}?mode=ro", uri=True)
    placeholders = ",".join("?" * len(books))
    strong_book: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for strong, book in db.execute(
        f"SELECT strong, book FROM occurrence WHERE strong IS NOT NULL AND strong != '' "
        f"AND book IN ({placeholders})",
        tuple(books),
    ):
        strong_book[strong][book] += 1

    book_list = sorted(books)
    strongs = [s for s, c in strong_book.items() if sum(c.values()) >= MIN_OCC]
    if not strongs:
        return {}, {}
    M = np.array([[strong_book[s].get(b, 0) for b in book_list] for s in strongs], dtype=float)
    counts = {s: int(M[i].sum()) for i, s in enumerate(strongs)}
    M /= (M.sum(axis=1, keepdims=True) + 1e-9)
    M /= (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
    return {s: M[i] for i, s in enumerate(strongs)}, counts


class CtxYardstick:
    """Same shape as Yardstick/EtymologyYardstick (.score/.held_out/.random_baseline)."""

    def __init__(self, seed: int = SEED, train_frac: float = TRAIN_FRAC):
        train_books, test_books = book_split(seed, train_frac)
        self.profiles_train, counts_train = build_book_profiles(train_books)
        self.profiles_test, _ = build_book_profiles(test_books)
        print(f"[ctx-yardstick] train books={len(train_books)} test books={len(test_books)} "
              f"train lexemes={len(self.profiles_train)} test lexemes={len(self.profiles_test)}",
              file=sys.stderr)
        # weighted by raw TRAIN occurrence count, same rationale as the other two yardsticks: a
        # sparse, low-occurrence profile is noisier regardless of the vector being L2-normalized, so
        # the baseline substitute needs comparable frequency, not just a comparable vector norm.
        self._matcher = FrequencyMatcher(counts_train)

    def score(self, a: str, b: str) -> float:
        va, vb = self.profiles_train.get(a), self.profiles_train.get(b)
        if va is None or vb is None:
            return 0.0
        return float(np.dot(va, vb))

    def held_out(self, a: str, b: str) -> bool:
        """Does this pair ALSO clear the production MIN_COS bar on entirely unseen (test-split) books?"""
        va, vb = self.profiles_test.get(a), self.profiles_test.get(b)
        if va is None or vb is None:
            return False
        return float(np.dot(va, vb)) >= MIN_COS

    def random_baseline(self, real_pairs: list[tuple[str, str]], seed: int = SEED) -> list[tuple[str, str]]:
        return self._matcher.matched_pairs(real_pairs, seed)


def load_context_pairs() -> list[tuple[str, str]]:
    if not CONTEXT_PAIRS.exists():
        return []
    pairs = []
    for line in CONTEXT_PAIRS.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith("strong_a"):
            continue
        p = line.split("\t")
        if len(p) >= 2:
            pairs.append((p[0], p[1]))
    return pairs


def report(ys: CtxYardstick) -> None:
    pairs = load_context_pairs()
    summarize(ys, "genre_context", pairs)
    summarize(ys, "genre_context -- frequency-matched random baseline", ys.random_baseline(pairs))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()

    ys = CtxYardstick(seed=args.seed)
    if args.report:
        report(ys)
    return 0


if __name__ == "__main__":
    sys.exit(main())
