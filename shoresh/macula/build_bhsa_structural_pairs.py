#!/usr/bin/env python3
"""BHSA syntactic-structure word pairs — coordination + apposition, via Context-Fabric (candidate #6's
tree structure, previously "parked... never extracted anywhere in this codebase", re-purposed here for
semantic-pairs rather than its original clause-dependency-export framing).

Two relations, both from BHSA's own phrase/subphrase nesting (`rela` feature), independent of BDB
(etymology), UBS MARBLE, and Hebrew WordNet — a genuinely different LINEAGE (syntactic structure, not
lexical/etymological derivation):

  coordination (subphrase rela=par): "X and Y" constructions — e.g. Genesis 1's own
    heaven/earth, day/night, light/darkness. Real synonym-or-near-synonym evidence BY CONSTRUCTION,
    same logic as T'OMIM's parallelism but from prose coordination, not poetic half-verses.
  apposition (phrase_atom rela=Appo): "the man, the prophet" restatement/specification pairs.

Precision note, SUPERSEDED 2026-08-15 (Phase B, text-anchored-semantics-plan.md): this script used to
restrict to sides resolving to EXACTLY ONE content word, justified by an SDBH-domain-agreement jump
(coordination 49.5% -> 63.7%, apposition 42.8% -> 48.3%) that made the naive all-cross-product
extraction look much noisier than it turns out to be. Re-measured against the text-anchored intrinsic
yardstick (held-out slot-filler prediction, SDBH retired as validator) across 5 book-level train/test
splits: naive extraction's lift over a frequency-matched baseline is nearly IDENTICAL to the restricted
version for apposition (1.76x vs 1.76x -- no cost at all) and only modestly lower for coordination
(1.82x vs 1.99x, ~9% relative) -- while yielding 3.3x/4.7x more pairs (6,411/1,280 vs 1,939/275). The
restriction is now REMOVED: naive extraction is the default, at 3.5x the total coverage the previous
years-long default carried. The single-content-word-only path is kept as a legacy option (--restricted)
for anyone who wants the higher-precision/lower-recall variant.

  python -m macula.build_bhsa_structural_pairs
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HBO = ROOT / "resources" / "occurrences" / "hbo.db"
OUT_DIR = ROOT / "resources" / "bhsa_structural"
BHSA_PATH = Path.home() / "text-fabric-data" / "github" / "ETCBC" / "bhsa" / "tf" / "2021"

CONTENT_SP = {"subs", "verb", "adjv"}


def _load_api():
    import cfabric

    CF = cfabric.Fabric(locations=str(BHSA_PATH), silent="deep")
    return CF.loadAll(silent="deep")


def _content_word(node, F, node2strong) -> str | None:
    sp = F.sp.v(node)
    s = node2strong.get(node)
    if s and sp in CONTENT_SP:
        return s if s.startswith("H") else f"H{int(s):04d}"
    return None


def _content_words(node, F, L, node2strong) -> list[str]:
    out = []
    for w in L.d(node, otype="word"):
        hs = _content_word(w, F, node2strong)
        if hs:
            out.append(hs)
    return out


def extract(restricted: bool = False) -> tuple[collections.Counter, collections.Counter]:
    """(coordination_pairs, apposition_pairs): Counter[frozenset({H_a, H_b})] -> occurrence count.

    restricted=False (default, since 2026-08-15): all-cross-product pairing between the two sides --
    see module docstring for the text-anchored measurement justifying this. restricted=True: legacy
    single-content-word-side-only variant (higher precision, ~3.5x less coverage)."""
    api = _load_api()
    F, E, L = api.F, api.E, api.L

    hbo = sqlite3.connect(f"file:{HBO}?mode=ro", uri=True)
    node2strong = dict(hbo.execute("SELECT node, strong FROM occurrence WHERE strong IS NOT NULL"))

    def pair_up(a_words, b_words, counter):
        if restricted:
            if len(a_words) == 1 and len(b_words) == 1 and a_words[0] != b_words[0]:
                counter[frozenset((a_words[0], b_words[0]))] += 1
        else:
            for a in a_words:
                for b in b_words:
                    if a != b:
                        counter[frozenset((a, b))] += 1

    coord: collections.Counter = collections.Counter()
    for n in F.otype.s("subphrase"):
        if F.rela.v(n) != "par":
            continue
        m = E.mother.f(n)
        if not m:
            continue
        pair_up(_content_words(n, F, L, node2strong), _content_words(m[0], F, L, node2strong), coord)

    appo: collections.Counter = collections.Counter()
    for n in F.otype.s("phrase_atom"):
        if F.rela.v(n) != "Appo":
            continue
        m = E.mother.f(n)
        if not m:
            continue
        mo = m[0]
        if F.otype.v(mo) == "word":
            hs = _content_word(mo, F, node2strong)
            b_words = [hs] if hs else []
        else:
            b_words = _content_words(mo, F, L, node2strong)
        pair_up(_content_words(n, F, L, node2strong), b_words, appo)

    print(f"[bhsa-structural] coordination: {len(coord)} distinct pairs, {sum(coord.values())} occurrences",
          file=sys.stderr)
    print(f"[bhsa-structural] apposition: {len(appo)} distinct pairs, {sum(appo.values())} occurrences",
          file=sys.stderr)
    return coord, appo


def build(restricted: bool = False) -> list[tuple[str, str, str, int]]:
    """[(strong_a, strong_b, relation, count)] — relation in {coordination, apposition}."""
    coord, appo = extract(restricted=restricted)
    rows = []
    for pair, cnt in coord.items():
        a, b = sorted(pair)
        rows.append((a, b, "coordination", cnt))
    for pair, cnt in appo.items():
        a, b = sorted(pair)
        rows.append((a, b, "apposition", cnt))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT_DIR / "structural_pairs.tsv")
    ap.add_argument("--restricted", action="store_true",
                     help="legacy single-content-word-side-only extraction (~3.5x less coverage, "
                          "the pre-2026-08-15 default) instead of the current all-cross-product default")
    args = ap.parse_args()

    rows = build(restricted=args.restricted)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write("# Biblical Hebrew syntactic-structure word pairs, via Context-Fabric (ETCBC/BHSA).\n"
                  "# coordination (subphrase rela=par): \"X and Y\" constructions. apposition (phrase_atom\n"
                  "# rela=Appo): \"the man, the prophet\" restatement pairs. Independent of BDB/UBS MARBLE/\n"
                  "# Hebrew WordNet — syntactic structure, not lexical/etymological derivation.\n"
                  f"# Extraction: {'RESTRICTED (legacy, --restricted)' if args.restricted else 'all-cross-product (default since 2026-08-15)'}"
                  " — see build_bhsa_structural_pairs.py and internal-docs/text-anchored-semantics-plan.md.\n"
                  "# count: independent occurrences across the OT (corroboration strength).\n")
        fh.write("strong_a\tstrong_b\trelation\tcount\n")
        for a, b, relation, cnt in sorted(rows, key=lambda r: (r[2], -r[3], r[0])):
            fh.write(f"{a}\t{b}\t{relation}\t{cnt}\n")
    print(f"[bhsa-structural] -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
