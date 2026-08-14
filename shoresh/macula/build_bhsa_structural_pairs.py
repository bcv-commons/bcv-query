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

Precision note (2026-08 finding): the naive extraction — pairing ALL content words under a coordinated
subphrase against ALL content words under its `mother` — is noisy (mother can span more than the
specific coordination partner when either side has multiple content words, producing spurious cross-
products). Restricting to sides that resolve to EXACTLY ONE content word raises quality substantially
(coordination: 49.5% -> 63.7% SDBH-domain agreement; apposition: 42.8% -> 48.3%) at a real but bounded
recall cost. Precision was chosen deliberately — this project's current need is confidence, not
coverage (see domain-replacement-roadmap.md).

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
MIN_COUNT = 2   # NOT CURRENTLY APPLIED (found 2026-08-14): no code in this file or in
                # build_semantic_neighbors.py's _load_structural_pairs() filters by count — that
                # function's own docstring confirms "no corroboration-count threshold" is used, the
                # single-content-word-side restriction below does the precision work alone. This
                # constant's SDBH-era justification (coordination 63.7%->73.9%) describes a filter
                # that was never wired in. Left here as a known discrepancy, not re-derived.


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


def extract() -> tuple[collections.Counter, collections.Counter]:
    """(coordination_pairs, apposition_pairs): Counter[frozenset({H_a, H_b})] -> occurrence count.
    Only pairs where BOTH sides resolve to exactly one content word are kept (see module docstring)."""
    api = _load_api()
    F, E, L = api.F, api.E, api.L

    hbo = sqlite3.connect(f"file:{HBO}?mode=ro", uri=True)
    node2strong = dict(hbo.execute("SELECT node, strong FROM occurrence WHERE strong IS NOT NULL"))

    coord: collections.Counter = collections.Counter()
    for n in F.otype.s("subphrase"):
        if F.rela.v(n) != "par":
            continue
        m = E.mother.f(n)
        if not m:
            continue
        a_words = _content_words(n, F, L, node2strong)
        b_words = _content_words(m[0], F, L, node2strong)
        if len(a_words) == 1 and len(b_words) == 1 and a_words[0] != b_words[0]:
            coord[frozenset((a_words[0], b_words[0]))] += 1

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
        a_words = _content_words(n, F, L, node2strong)
        if len(a_words) == 1 and len(b_words) == 1 and a_words[0] != b_words[0]:
            appo[frozenset((a_words[0], b_words[0]))] += 1

    print(f"[bhsa-structural] coordination: {len(coord)} distinct pairs, {sum(coord.values())} occurrences",
          file=sys.stderr)
    print(f"[bhsa-structural] apposition: {len(appo)} distinct pairs, {sum(appo.values())} occurrences",
          file=sys.stderr)
    return coord, appo


def build() -> list[tuple[str, str, str, int]]:
    """[(strong_a, strong_b, relation, count)] — relation in {coordination, apposition}."""
    coord, appo = extract()
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
    args = ap.parse_args()

    rows = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write("# Biblical Hebrew syntactic-structure word pairs, via Context-Fabric (ETCBC/BHSA).\n"
                  "# coordination (subphrase rela=par): \"X and Y\" constructions. apposition (phrase_atom\n"
                  "# rela=Appo): \"the man, the prophet\" restatement pairs. Independent of BDB/UBS MARBLE/\n"
                  "# Hebrew WordNet — syntactic structure, not lexical/etymological derivation. Restricted to\n"
                  "# single-content-word sides (precision > recall — see build_bhsa_structural_pairs.py).\n"
                  "# count: independent occurrences across the OT (corroboration strength).\n")
        fh.write("strong_a\tstrong_b\trelation\tcount\n")
        for a, b, relation, cnt in sorted(rows, key=lambda r: (r[2], -r[3], r[0])):
            fh.write(f"{a}\t{b}\t{relation}\t{cnt}\n")
    print(f"[bhsa-structural] -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
