#!/usr/bin/env python3
"""Add a confidence `tier` to hierarchy_dag.tsv from direction_yardstick.py's multi-seed verdicts
(Phase C step 3, internal-docs/phase-c-instrument-calibration-plan.md) -- the step the plan explicitly
deferred until direction had been measured. Same "high" vs weaker-but-kept pattern already used for
domain_clusters.tsv's `anchor` column (build_domain_clusters.py), not a new convention.

  high        -- CONFIRMED by majority vote across 5 held-out TEST-book splits: an independent,
                 text-anchored check corroborates the claimed direction.
  medium      -- UNDETERMINED: usually just corpus sparsity on the held-out side (Biblical Hebrew is
                 small), not counter-evidence. Grammar (apposition) or distributional inclusion is
                 still the basis for these edges -- kept, not downgraded to "wrong".
  (dropped)   -- CONTRADICTED by majority vote: held-out data actively disagrees with the claimed
                 direction. Written to hierarchy_dag_flagged.tsv instead of the main file -- a small
                 pool (see the script's own printed count), candidate for the deferred Haiku
                 adjudication pass if ever revisited, not silently discarded.

  python -m macula.direction_yardstick    # regenerate direction_verdicts.tsv first if edges changed
  python -m macula.tier_hierarchy_dag
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DAG = ROOT / "resources" / "bhsa_hierarchy" / "hierarchy_dag.tsv"
VERDICTS = ROOT / "resources" / "bhsa_hierarchy" / "direction_verdicts.tsv"
OUT = DAG
FLAGGED_OUT = ROOT / "resources" / "bhsa_hierarchy" / "hierarchy_dag_flagged.tsv"

TIER_OF_VERDICT = {"CONFIRMED": "high", "UNDETERMINED": "medium", "CONTRADICTED": None}


def load_dag() -> list[tuple[str, str, str]]:
    rows = []
    for line in DAG.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith("broader_strong"):
            continue
        b, n, sources = line.split("\t")
        rows.append((b, n, sources))
    return rows


def load_verdicts() -> dict[tuple[str, str], str]:
    if not VERDICTS.exists():
        sys.exit(f"{VERDICTS} not found -- run direction_yardstick.py first")
    out = {}
    for line in VERDICTS.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith("broader_strong"):
            continue
        p = line.split("\t")
        out[(p[0], p[1])] = p[3]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--flagged-out", type=Path, default=FLAGGED_OUT)
    args = ap.parse_args()

    dag_rows = load_dag()
    verdicts = load_verdicts()

    missing = [key for key in ((b, n) for b, n, _ in dag_rows) if key not in verdicts]
    if missing:
        sys.exit(f"{len(missing)} DAG edges have no direction verdict -- DAG and verdicts file are "
                  f"out of sync, re-run direction_yardstick.py against the current hierarchy_dag.tsv "
                  f"before tiering (e.g. {missing[0]})")

    kept, flagged = [], []
    for b, n, sources in dag_rows:
        v = verdicts[(b, n)]
        tier = TIER_OF_VERDICT[v]
        if tier is None:
            flagged.append((b, n, sources, v))
        else:
            kept.append((b, n, sources, tier))

    print(f"[tier-dag] {len(kept)} edges kept (tier: "
          f"{sum(1 for *_, t in kept if t == 'high')} high, "
          f"{sum(1 for *_, t in kept if t == 'medium')} medium), "
          f"{len(flagged)} CONTRADICTED edges moved to {args.flagged_out.name}", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write("# Directed Hebrew hierarchy (broader -> narrower), assembled from apposition\n"
                  "# direction (BHSA grammar) + distributional inclusion (held-out verified, see\n"
                  "# build_hierarchy_dag.py). Text-anchored, no SDBH/MARBLE.\n"
                  "# `tier`: high = CONFIRMED by direction_yardstick.py's 5-seed held-out majority\n"
                  "# vote (independent check); medium = UNDETERMINED there (usually held-out\n"
                  "# sparsity, not counter-evidence) -- see tier_hierarchy_dag.py. Edges the vote\n"
                  "# CONTRADICTED are excluded here, see hierarchy_dag_flagged.tsv.\n")
        fh.write("broader_strong\tnarrower_strong\tsources\ttier\n")
        for b, n, sources, tier in sorted(kept):
            fh.write(f"{b}\t{n}\t{sources}\t{tier}\n")

    args.flagged_out.parent.mkdir(parents=True, exist_ok=True)
    with args.flagged_out.open("w", encoding="utf-8") as fh:
        fh.write("# Edges dropped from hierarchy_dag.tsv: direction_yardstick.py's 5-seed held-out\n"
                  "# majority vote CONTRADICTED the claimed broader->narrower direction. Small pool,\n"
                  "# kept (not deleted) as the candidate set for the deferred Haiku adjudication pass\n"
                  "# noted in internal-docs/phase-c-instrument-calibration-plan.md -- distinct from\n"
                  "# the larger pool build_hierarchy_dag.py's enforce_acyclic() drops before assembly.\n")
        fh.write("broader_strong\tnarrower_strong\tsources\tverdict\n")
        for b, n, sources, v in sorted(flagged):
            fh.write(f"{b}\t{n}\t{sources}\t{v}\n")

    print(f"[tier-dag] -> {args.out}", file=sys.stderr)
    print(f"[tier-dag] -> {args.flagged_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
