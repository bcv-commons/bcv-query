#!/usr/bin/env python3
"""Text-anchored intrinsic yardstick -- replaces SDBH `core`-domain agreement as the internal
validation measure for the semantic-neighbors pipeline (internal-docs/text-anchored-semantics-plan.md).

Ground truth shifts from AGREEMENT (does this match a human-made taxonomy) to PREDICTION (does this
structure explain unseen Hebrew). Concretely:

  1. Split the 39 OT books into TRAIN/TEST (fixed SEED, book-level -- not verse-level, to avoid
     leaking a clause's neighbours into its own test fold).
  2. Build a slot-filler PROFILE per lexeme from TRAIN books only, via build_slot_profiles.extract():
     profile[lex] = Counter[(verb, slot)] -> count, i.e. which verb-argument slots this lexeme has
     been seen filling.
  3. predict_score(A, B) = cosine similarity between TRAIN profiles -- computed with zero access to
     TEST data, exactly mirroring how the real embedding/BDB/etc. signals are each computed once and
     then applied.
  4. held_out_positive(A, B) = does the TEST split independently show A and B filling the SAME
     (verb, slot) at least once? This is the genuinely unseen event being predicted.
  5. Report predict_score and held_out_positive rate for existing confidence tiers (n_families>=2,
     n_families==1) against a FREQUENCY-MATCHED random baseline -- random lexeme pairs sampled
     proportional to their train-split occurrence count, so common words don't win merely by being
     common.

Minimum occurrence gate (MIN_OCC=2 per split) matches the spirit of build_semantic_neighbors.py's
MIN_OCC=3 for embeddings -- a structural noise-reduction choice, not one tuned against SDBH.

Caveat (must travel with any published number derived from this): the `structural` signal
(build_bhsa_structural_pairs.py) and BEREL embeddings are THEMSELVES derived from BHSA, so scoring
them against a BHSA-derived yardstick is partially circular. Mitigated but not eliminated by using a
different facet of BHSA (selectional preference, not coordination/apposition) and a book-level split.

  python -m macula.intrinsic_yardstick --report
"""
from __future__ import annotations

import argparse
import collections
import math
import random
import sys
from pathlib import Path

from macula.build_slot_profiles import extract as extract_slot_triples

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HBO = ROOT / "resources" / "occurrences" / "hbo.db"
CONFIDENCE_TIERS = ROOT / "resources" / "semantic_neighbors" / "confidence_tiers.tsv"

SEED = 13
TRAIN_FRAC = 0.7
MIN_OCC = 2   # a lexeme needs >= this many occurrences in a split to get a profile there
HUB_PERCENTILE = 90   # (verb,slot) keys filled by more than this percentile of lexemes are excluded
                       # -- these are light verbs (be/give/take/come) with near-universal selectional
                       # restrictions (e.g. H1961/PreC "to be" is filled by 29% of all lexemes in the
                       # train split); without this, frequency-weighted random pairs of common nouns
                       # (kol/all, ben/son, melekh/king) beat curated candidate pairs on both score and
                       # held-out co-occurrence purely by hub contamination. Linguistic, not SDBH-tuned.


def book_split(seed: int = SEED, train_frac: float = TRAIN_FRAC) -> tuple[set[str], set[str]]:
    import sqlite3

    db = sqlite3.connect(f"file:{HBO}?mode=ro", uri=True)
    books = sorted(r[0] for r in db.execute("SELECT DISTINCT book FROM occurrence"))
    rng = random.Random(seed)
    rng.shuffle(books)
    n_train = round(len(books) * train_frac)
    return set(books[:n_train]), set(books[n_train:])


def _hub_keys(profiles: dict[str, collections.Counter], percentile: int) -> set[tuple[str, str]]:
    df: collections.Counter = collections.Counter()
    for prof in profiles.values():
        for key in prof:
            df[key] += 1
    if not df:
        return set()
    n = len(profiles)
    cutoff = sorted(df.values())[int(len(df) * percentile / 100)]
    return {key for key, count in df.items() if count > cutoff and count / n > 0.05}


def build_profiles(books: set[str]) -> dict[str, collections.Counter]:
    """lex -> Counter[(verb, slot)] -> count, restricted to lexemes with >= MIN_OCC total occurrences
    as a FILLER in this book set, with hub (light-verb) slots removed -- see HUB_PERCENTILE. Includes
    the verb's own profile too (a verb can itself be a filler of another clause's slot, e.g.
    infinitive complements) -- extract() already covers this since it only restricts filler `sp` to
    CONTENT_SP, which includes verb."""
    triples = extract_slot_triples(books=books)
    profiles: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for (verb, slot, filler), cnt in triples.items():
        profiles[filler][(verb, slot)] += cnt
    profiles = {lex: prof for lex, prof in profiles.items() if sum(prof.values()) >= MIN_OCC}
    hubs = _hub_keys(profiles, HUB_PERCENTILE)
    return {lex: collections.Counter({k: v for k, v in prof.items() if k not in hubs})
            for lex, prof in profiles.items()}


def cosine(a: collections.Counter, b: collections.Counter) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[k] * b[k] for k in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def held_out_positive(profiles_test: dict[str, collections.Counter], a: str, b: str) -> bool:
    pa, pb = profiles_test.get(a), profiles_test.get(b)
    if not pa or not pb:
        return False
    return bool(set(pa) & set(pb))


class FrequencyMatcher:
    """Frequency-rank bucket matching, for building a frequency-MATCHED (not frequency-weighted)
    random baseline: replace each side of a real pair with a random lexeme from the SAME frequency
    rank bucket. Frequency-weighted global sampling skews overwhelmingly toward a handful of extreme
    outliers (e.g. H3605/kol "all", train total 1282 vs a median lexeme's 3), which made an earlier
    version of this baseline systematically far more frequent -- and hence far more likely to share
    context purely by profile-size combinatorics -- than real candidate pairs (see
    internal-docs/text-anchored-semantics-plan.md, "Phase A results"). Shared by intrinsic_yardstick's
    Yardstick (slot-profile weight) and etymology_yardstick's EtymologyYardstick (verse-membership
    weight) -- same matching need, different underlying profile shape."""

    N_BUCKETS = 20

    def __init__(self, weight_of: dict[str, float]):
        ranked = sorted(weight_of, key=lambda lx: -weight_of[lx])
        self._bucket_of: dict[str, int] = {}
        self._lexemes_in_bucket: dict[int, list[str]] = collections.defaultdict(list)
        for i, lx in enumerate(ranked):
            b = min(i * self.N_BUCKETS // max(len(ranked), 1), self.N_BUCKETS - 1)
            self._bucket_of[lx] = b
            self._lexemes_in_bucket[b].append(lx)

    def substitute(self, lex: str, rng: random.Random) -> str | None:
        bucket = self._bucket_of.get(lex)
        if bucket is None:
            return None
        candidates = self._lexemes_in_bucket[bucket]
        return rng.choice(candidates) if candidates else None

    def matched_pairs(self, real_pairs: list[tuple[str, str]], seed: int = SEED) -> list[tuple[str, str]]:
        """One frequency-matched substitute pair per real pair."""
        rng = random.Random(seed + 1)
        exclude = {frozenset(p) for p in real_pairs}
        out: list[tuple[str, str]] = []
        for a, b in real_pairs:
            for _ in range(20):
                a2 = self.substitute(a, rng)
                b2 = self.substitute(b, rng)
                if a2 and b2 and a2 != b2 and frozenset((a2, b2)) not in exclude:
                    out.append((a2, b2))
                    break
        return out


class Yardstick:
    """Loads once (train + test profiles); use .score(a, b) and .held_out(a, b) per pair, plus
    .random_baseline(n) for a frequency-matched null-hypothesis sample."""

    def __init__(self, seed: int = SEED, train_frac: float = TRAIN_FRAC):
        train_books, test_books = book_split(seed, train_frac)
        self.profiles_train = build_profiles(train_books)
        self.profiles_test = build_profiles(test_books)
        print(f"[yardstick] train books={len(train_books)} test books={len(test_books)} "
              f"train lexemes={len(self.profiles_train)} test lexemes={len(self.profiles_test)}",
              file=sys.stderr)
        self._matcher = FrequencyMatcher(
            {lx: sum(prof.values()) for lx, prof in self.profiles_train.items()})

    def score(self, a: str, b: str) -> float:
        return cosine(self.profiles_train.get(a, collections.Counter()),
                      self.profiles_train.get(b, collections.Counter()))

    def held_out(self, a: str, b: str) -> bool:
        return held_out_positive(self.profiles_test, a, b)

    def random_baseline(self, real_pairs: list[tuple[str, str]], seed: int = SEED) -> list[tuple[str, str]]:
        return self._matcher.matched_pairs(real_pairs, seed)


def load_confidence_tiers() -> list[tuple[str, str, int]]:
    rows = []
    if not CONFIDENCE_TIERS.exists():
        return rows
    for line in CONFIDENCE_TIERS.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith("strong_a"):
            continue
        p = line.split("\t")
        if len(p) >= 3:
            rows.append((p[0], p[1], int(p[2])))
    return rows


def summarize(ys: Yardstick, name: str, pairs: list[tuple[str, str]]) -> dict:
    """Print + return {mean_train_sim, test_cooccur_rate, n, scored} for a pair set -- the shared
    reporting shape every --validate branch should use in place of its old SDBH dom-agreement rate()."""
    if not pairs:
        print(f"[yardstick] {name}: 0 pairs", file=sys.stderr)
        return {"n": 0, "mean_train_sim": 0.0, "test_cooccur_rate": 0.0, "scored": 0}
    scores = [ys.score(a, b) for a, b in pairs]
    positives = [ys.held_out(a, b) for a, b in pairs]
    scored = sum(1 for s in scores if s > 0)
    mean_score = sum(scores) / len(scores)
    pos_rate = sum(positives) / len(positives)
    print(f"[yardstick] {name}: n={len(pairs)}  mean_train_sim={mean_score:.4f}  "
          f"(scored>0: {scored}/{len(pairs)})  test_cooccur_rate={100*pos_rate:.2f}%",
          file=sys.stderr)
    return {"n": len(pairs), "mean_train_sim": mean_score, "test_cooccur_rate": pos_rate, "scored": scored}


def validate_pairs(ys: Yardstick, name: str, pairs: list[tuple[str, str]]) -> None:
    """Standard two-line validate() body: the pair set, then its frequency-matched random baseline."""
    summarize(ys, name, pairs)
    summarize(ys, f"{name} -- frequency-matched random baseline", ys.random_baseline(pairs))


def report(ys: Yardstick) -> None:
    tiers = load_confidence_tiers()
    cross_signal = [(a, b) for a, b, n in tiers if n >= 2]
    single_signal = [(a, b) for a, b, n in tiers if n == 1]
    baseline = ys.random_baseline(cross_signal)
    summarize(ys, "cross-signal (n_families>=2)", cross_signal)
    summarize(ys, "single-signal (n_families==1)", single_signal)
    summarize(ys, "frequency-matched random baseline", baseline)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", action="store_true", help="print the tier-separation GO/NO-GO check")
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()

    ys = Yardstick(seed=args.seed)
    if args.report:
        report(ys)
    return 0


if __name__ == "__main__":
    sys.exit(main())
