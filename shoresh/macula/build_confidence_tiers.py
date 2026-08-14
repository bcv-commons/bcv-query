#!/usr/bin/env python3
"""Cross-signal-agreement confidence tiers — the publication gate for semantic_neighbors.

Historically measured against SDBH `core`-domain agreement (see domain-replacement-roadmap.md for
that record: individual signals topped out 35-90% agreement; requiring >=2 independent signal
FAMILIES to agree did far better than any single signal, 73.4% at >=2 vs 82.9% at >=3). SDBH is
retired as the validation yardstick as of 2026-08-14 (internal-docs/text-anchored-semantics-plan.md)
— `--validate` now scores against the text-anchored intrinsic yardstick (held-out slot-filler
prediction, see intrinsic_yardstick.py) instead. The FAMILY_GATE constant in build_published_pairs.py
still carries its SDBH-era value pending re-derivation under the new yardstick.

"Family", not raw source tag: emb/lxx/gloss are all byproducts of the SAME embedding kNN pass and
would trivially co-occur — counting them as 3 independent votes would be circular. Grouped into
families that are methodologically independent of each other:
  distributional  — emb, lxx, gloss, xling (all derived from the embedding pass or its immediate corroborators)
  etymological    — bdb_root
  structural       — parallelism, structural (BHSA coordination/apposition)
  lexical-external — hwn (Hebrew WordNet)
  llm              — llm (scholarly-prior)
  corroborated     — corroborated (xling ∩ wiktionary_roots — already its own agreement signal)

  python -m macula.build_confidence_tiers
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NEIGHBORS = ROOT / "resources" / "semantic_neighbors" / "neighbors.parquet"
OUT_DIR = ROOT / "resources" / "semantic_neighbors"

FAMILY = {
    "emb": "distributional", "lxx": "distributional", "gloss": "distributional", "xling": "distributional",
    "bdb_root": "etymological",
    "parallelism": "structural", "structural": "structural",
    "hwn": "lexical-external",
    "llm": "llm",
    "corroborated": "corroborated",
}


def _hs(lx: str) -> str:
    m = re.search(r"(\d+)", lx or "")
    return f"H{int(m.group(1)):04d}" if m else ""


def build() -> list[tuple[str, str, int, str]]:
    """[(strong_a, strong_b, n_families, families_csv)] — one row per distinct Strong's pair, keyed by
    how many INDEPENDENT signal families ever asserted it (across all confidence tiers, not just
    high/prior — a pair earns cross-signal credit even if individual mentions were only "recall")."""
    import pyarrow.parquet as pq

    t = pq.read_table(NEIGHBORS).to_pydict()
    pair_families: dict[frozenset, set[str]] = collections.defaultdict(set)
    pair_antonym: set[frozenset] = set()
    for lx, nb, src, rel in zip(t["lexeme"], t["neighbor_lexeme"], t["sources"], t["relation"]):
        a, b = _hs(lx), _hs(nb)
        if not a or not b or a == b:
            continue
        key = frozenset((a, b))
        if rel == "antonym":
            pair_antonym.add(key)
            continue
        for tag in src.split("|"):
            fam = FAMILY.get(tag)
            if fam:
                pair_families[key].add(fam)

    rows = []
    for pair, fams in pair_families.items():
        if pair in pair_antonym:
            continue
        a, b = sorted(pair)
        rows.append((a, b, len(fams), "|".join(sorted(fams))))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT_DIR / "confidence_tiers.tsv")
    ap.add_argument("--validate", action="store_true",
                     help="score vs the text-anchored intrinsic yardstick (see intrinsic_yardstick.py)")
    args = ap.parse_args()

    rows = build()
    tally = collections.Counter(r[2] for r in rows)
    print(f"[confidence-tiers] {len(rows)} distinct pairs; "
          f"{sum(1 for r in rows if r[2] >= 2)} with >=2 families, "
          f"{sum(1 for r in rows if r[2] >= 3)} with >=3 families", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write("# Cross-signal-agreement confidence tiers — the publication gate. n_families = how many\n"
                  "# INDEPENDENT signal families (see build_confidence_tiers.py) assert this pair. Validated\n"
                  "# 2026-08 vs SDBH core: >=1 family 35.7%, >=2 73.4%, >=3 82.9% same-domain agreement.\n"
                  "# Publication recommendation: n_families >= 2 as the headline dataset.\n")
        fh.write("strong_a\tstrong_b\tn_families\tfamilies\n")
        for a, b, n, fams in sorted(rows, key=lambda r: (-r[2], r[0], r[1])):
            fh.write(f"{a}\t{b}\t{n}\t{fams}\n")
    print(f"[confidence-tiers] -> {args.out}", file=sys.stderr)

    if args.validate:
        from macula.intrinsic_yardstick import Yardstick, validate_pairs

        ys = Yardstick()
        for n in (1, 2, 3):
            pairs = [(a, b) for a, b, nf, _ in rows if nf >= n]
            validate_pairs(ys, f">= {n} families", pairs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
