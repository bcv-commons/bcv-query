#!/usr/bin/env python3
"""Text-anchored yardstick for ETYMOLOGICAL / lexical-external signals (bdb_root, hwn,
wiktionary_roots, sefer_hashorashim) -- a companion to intrinsic_yardstick.py, not a replacement.

Why a second yardstick: intrinsic_yardstick.py's held-out slot-filler prediction validates
DISTRIBUTIONAL/STRUCTURAL signals well (structural 3.9x its baseline, parallelism 3.3x) but is
axis-mismatched for etymological signals -- bdb_root and hwn both scored BELOW that yardstick's
baseline (see internal-docs/text-anchored-semantics-plan.md, "Axis mismatch"). Root-sharing pairs
often cross POS (a verb and a noun of the same root -- measured 32.0% of bdb_root pairs do this) and
are therefore structurally incapable of ever filling the same syntactic argument slot, even when
genuinely related. Repeating SDBH's own core/ctx axis-blending mistake with the replacement yardstick
would defeat the point of replacing it.

Ground truth here instead: SAME-VERSE held-out co-occurrence -- grounded in the documented Biblical
Hebrew literary phenomenon of root-play / paronomasia (deliberate juxtaposition of same-root words,
e.g. root A-Y-Sh in Genesis 2:23's ishah/ish). Mirrors intrinsic_yardstick.py's shape exactly: book-
level train/test split, a train-derived "predictor" (shared TRAIN-split verses), a genuinely unseen
TEST-split event (do the two lexemes co-occur in a held-out verse?), and the shared FrequencyMatcher
for a frequency-matched (not frequency-weighted) random baseline.

Preliminary result (2026-08-14): bdb_root 5.08% vs. a 4.15% frequency-matched baseline (1.22x) --
positive, though a weaker lift than structural/parallelism showed on their OWN matched yardstick. Not
yet wired into any --validate branch; this module exists to let that comparison be made deliberately,
not to replace the syntactic-slot yardstick for signals it already validates well.

  python -m macula.etymology_yardstick --report
"""
from __future__ import annotations

import argparse
import collections
import itertools
import sqlite3
import sys
from pathlib import Path

from macula.intrinsic_yardstick import SEED, TRAIN_FRAC, FrequencyMatcher, book_split, summarize

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HBO = ROOT / "resources" / "occurrences" / "hbo.db"
BDB_ROOTS = ROOT / "resources" / "bdb_roots" / "root_groups.tsv"


def build_verse_membership(books: set[str]) -> dict[str, set[int]]:
    """strong -> {verse ref, ...} it appears in, restricted to this book set. Verse (not clause)
    granularity: root-play/paronomasia is a verse- or passage-level literary device, coarser than the
    clause-level unit intrinsic_yardstick.py uses for syntactic slots."""
    db = sqlite3.connect(f"file:{HBO}?mode=ro", uri=True)
    placeholders = ",".join("?" * len(books))
    rows = db.execute(
        f"SELECT ref, strong FROM occurrence WHERE strong IS NOT NULL AND strong != '' "
        f"AND book IN ({placeholders})",
        tuple(books),
    )
    membership: dict[str, set[int]] = collections.defaultdict(set)
    for ref, strong in rows:
        membership[strong].add(ref)
    return membership


def load_bdb_root_pairs() -> list[tuple[str, str]]:
    by_root: dict[str, list[str]] = collections.defaultdict(list)
    if not BDB_ROOTS.exists():
        return []
    for line in BDB_ROOTS.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith("root_id"):
            continue
        p = line.split("\t")
        if len(p) >= 2:
            by_root[p[0]].append(p[1])
    return [(a, b) for members in by_root.values() if len(members) >= 2
            for a, b in itertools.combinations(sorted(set(members)), 2)]


class EtymologyYardstick:
    """Same shape as intrinsic_yardstick.Yardstick (.score, .held_out, .random_baseline) so it can be
    passed to the same summarize()/validate_pairs() reporting functions."""

    def __init__(self, seed: int = SEED, train_frac: float = TRAIN_FRAC):
        train_books, test_books = book_split(seed, train_frac)
        self.verses_train = build_verse_membership(train_books)
        self.verses_test = build_verse_membership(test_books)
        print(f"[etymology-yardstick] train books={len(train_books)} test books={len(test_books)} "
              f"train lexemes={len(self.verses_train)} test lexemes={len(self.verses_test)}",
              file=sys.stderr)
        # verse-count is the frequency proxy here (cheaper than a second frequency query, and
        # monotonic with true occurrence count for this purpose)
        self._matcher = FrequencyMatcher({lx: len(v) for lx, v in self.verses_train.items()})

    def score(self, a: str, b: str) -> float:
        """# of TRAIN-split verses A and B share -- the train-derived predictor."""
        return len(self.verses_train.get(a, set()) & self.verses_train.get(b, set()))

    def held_out(self, a: str, b: str) -> bool:
        """Do A and B co-occur in a held-out TEST-split verse -- the genuinely unseen event."""
        return bool(self.verses_test.get(a, set()) & self.verses_test.get(b, set()))

    def random_baseline(self, real_pairs: list[tuple[str, str]], seed: int = SEED) -> list[tuple[str, str]]:
        return self._matcher.matched_pairs(real_pairs, seed)


def report(ys: EtymologyYardstick) -> None:
    bdb_pairs = load_bdb_root_pairs()
    summarize(ys, "bdb_root", bdb_pairs)
    summarize(ys, "bdb_root -- frequency-matched random baseline", ys.random_baseline(bdb_pairs))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()

    ys = EtymologyYardstick(seed=args.seed)
    if args.report:
        report(ys)
    return 0


if __name__ == "__main__":
    sys.exit(main())
