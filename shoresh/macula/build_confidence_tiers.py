#!/usr/bin/env python3
"""Cross-signal-agreement confidence tiers — the publication gate for semantic_neighbors.

Every individual signal in this pipeline (embedding, BDB roots, parallelism, Hebrew WordNet,
structural, corroborated, ...) tops out somewhere between 35% and 90% SDBH `core`-agreement on its
own. Measured 2026-08: requiring INDEPENDENT signal FAMILIES to agree on the same pair does far better
than any single signal — >=2 families: 73.4% (3,247 pairs); >=3: 82.9% (817 pairs) — a bigger jump than
any individual signal addition this whole project. This is the actual publication-quality lever, not
more signal-hunting (see domain-replacement-roadmap.md).

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
    ap.add_argument("--validate", action="store_true", help="score vs SDBH core domain (internal yardstick)")
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
        dom = collections.defaultdict(set)
        domains_path = ROOT / "resources" / "semantic_domains" / "hbo.tsv"
        if domains_path.exists():
            for line in domains_path.read_text(encoding="utf-8").splitlines()[1:]:
                p = line.split("\t")
                if len(p) >= 3 and p[1] == "core":
                    dom[p[0]].add(p[2])
            for n in (1, 2, 3):
                same = tot = 0
                for a, b, nf, _ in rows:
                    if nf < n:
                        continue
                    ds, db_ = dom.get(a, set()), dom.get(b, set())
                    if ds and db_:
                        tot += 1
                        same += bool(ds & db_)
                print(f"[validate] >= {n} families: {same}/{tot} = {100*same/max(tot,1):.1f}%", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
