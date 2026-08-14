#!/usr/bin/env python3
"""Direction yardstick for the Hebrew hierarchy DAG (Phase C step 1, internal-docs/
phase-c-instrument-calibration-plan.md) -- tests whether hierarchy_dag.tsv's claimed
broader->narrower DIRECTION is actually correct, not just whether the two lexemes are related.

Nothing in this project has tested direction before this script. All three yardsticks
(intrinsic/etymology/ctx) test relatedness only; the SDBH cross-check explicitly cannot test
direction either (SDBH is topic tags, not a hierarchy). The single prior exception,
build_hierarchy_dag.verify_held_out, only covers the 148 distributional edges -- this covers all 638,
including the 475 apposition-only edges whose direction was never measured, only "eyeballed" (see
build_hierarchy_dag.py's own docstring).

CRITICAL DESIGN CONSTRAINT: a naive containment ratio (|X∩Y|/|Y| vs |X∩Y|/|X|) is DEGENERATE --
it reduces algebraically to "which profile is bigger", silently re-implementing the same profile-size
proxy build_hierarchy_dag.py's enforce_acyclic() already uses to construct these very edges. Testing
direction with that measure would just confirm its own premise. Uses weighted asymmetry measures from
the distributional-inclusion literature instead:

  WeedsPrec(narrower, broader) = (narrower's weighted context mass that also appears in broader's
    profile) / (narrower's total weighted context mass). High when narrower's usage is a genuine
    subset of broader's -- and unlike a set-size ratio, it depends on WHERE narrower's occurrences
    fall, not just how many distinct contexts either side has.
  invCL (Lenci & Benotto 2012) = sqrt(CL(narrower,broader) * (1 - CL(broader,narrower))), where
    CL(u,v) = weighted-overlap(u,v) / total_weight(u). Rewards ASYMMETRIC inclusion specifically --
    high when narrower's contexts are mostly inside broader's AND broader has genuine extra contexts
    of its own (not just a bigger profile in general).

Profiles are built via intrinsic_yardstick.build_profiles() -- the same hub-filtered, MIN_OCC-filtered
definition used throughout Phase A -- on TEST-book text only, never used to infer the DAG edges in the
first place. Genuinely held out, not circular.

TWO CONTROLS, both required before trusting any headline number:
  reversed  -- every edge flipped and re-scored. A real signal must flip (CONFIRMED rate should drop,
    CONTRADICTED rate should rise). If reversed edges confirm at a similar rate to the originals, the
    measure is picking up relatedness, not direction, and nothing below is trustworthy.
  random    -- frequency-matched random pairs (intrinsic_yardstick.FrequencyMatcher). Should land near
    chance, mostly UNDETERMINED given sparse held-out profiles.

Honesty note: for apposition edges this is a genuinely INDEPENDENT check (grammar-inferred direction,
never touched distribution). For distributional edges it is a held-out CONSISTENCY check on the same
signal family that produced them -- weaker, and reported separately for exactly this reason.

MARGIN/MIN_MASS/INVCL_MIN below are picked, not swept -- same status as build_hierarchy_dag.py's own
four constants. A sweep is plausible future work, not done here (see the plan doc).

  python -m macula.direction_yardstick --report
  python -m macula.direction_yardstick            # writes the multi-seed aggregate used by
                                                    # tier_hierarchy_dag.py (Phase C step 3)
"""
from __future__ import annotations

import argparse
import collections
import math
import sys
from pathlib import Path

from macula.intrinsic_yardstick import SEED, TRAIN_FRAC, FrequencyMatcher, book_split, build_profiles

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DAG = ROOT / "resources" / "bhsa_hierarchy" / "hierarchy_dag.tsv"
OUT = ROOT / "resources" / "bhsa_hierarchy" / "direction_verdicts.tsv"

MARGIN = 0.10     # forward WeedsPrec must beat reverse by at least this much
MIN_MASS = 3      # each side needs >= this much TEST-split weighted context mass to be checkable
INVCL_MIN = 0.15  # invCL floor required for a CONFIRMED verdict


def load_dag_edges(path: Path = DAG) -> list[tuple[str, str, str]]:
    """[(broader, narrower, source)] -- source in {apposition, distributional, both}. `path` defaults
    to hierarchy_dag.tsv but accepts any same-shaped file, e.g. dropped_edges.tsv, so this same
    held-out check can be pointed at edges that never made it into the DAG."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith("broader_strong"):
            continue
        b, n, sources = line.split("\t")
        tags = sources.split("|")
        has_appo = any(t.startswith("apposition") for t in tags)
        has_dist = any(t.startswith("distributional") for t in tags)
        source = "both" if has_appo and has_dist else ("apposition" if has_appo else "distributional")
        rows.append((b, n, source))
    return rows


def weeds_prec(narrower: collections.Counter, broader: collections.Counter) -> float:
    total = sum(narrower.values())
    if not total:
        return 0.0
    common = set(narrower) & set(broader)
    return sum(narrower[f] for f in common) / total


def _cl(u: collections.Counter, v: collections.Counter) -> float:
    total = sum(u.values())
    if not total:
        return 0.0
    common = set(u) & set(v)
    return sum(min(u[f], v[f]) for f in common) / total


def inv_cl(narrower: collections.Counter, broader: collections.Counter) -> float:
    cl_fwd = _cl(narrower, broader)
    cl_rev = _cl(broader, narrower)
    val = cl_fwd * (1 - cl_rev)
    return math.sqrt(val) if val > 0 else 0.0


def verdict(profiles: dict, broader: str, narrower: str) -> tuple[str, float, float, float]:
    """(verdict, weeds_fwd, weeds_rev, invcl) -- verdict in {CONFIRMED, CONTRADICTED, UNDETERMINED}."""
    pb, pn = profiles.get(broader), profiles.get(narrower)
    if not pb or not pn or sum(pb.values()) < MIN_MASS or sum(pn.values()) < MIN_MASS:
        return "UNDETERMINED", 0.0, 0.0, 0.0
    fwd = weeds_prec(pn, pb)   # narrower's mass covered by broader -- should be HIGH if claim is true
    rev = weeds_prec(pb, pn)   # broader's mass covered by narrower -- should be LOWER if claim is true
    icl = inv_cl(pn, pb)
    if fwd - rev >= MARGIN and icl >= INVCL_MIN:
        return "CONFIRMED", fwd, rev, icl
    if rev - fwd >= MARGIN:
        return "CONTRADICTED", fwd, rev, icl
    return "UNDETERMINED", fwd, rev, icl


def run(seed: int = SEED, dag_path: Path = DAG) -> dict[str, list[tuple]]:
    _, test_books = book_split(seed=seed, train_frac=TRAIN_FRAC)
    profiles = build_profiles(test_books)
    print(f"[direction] test books={len(test_books)}  test-split profiled lexemes={len(profiles)}",
          file=sys.stderr)

    edges = load_dag_edges(dag_path)
    matcher = FrequencyMatcher({lx: sum(p.values()) for lx, p in profiles.items()})

    results: dict[str, list[tuple]] = {"real": [], "reversed": [], "random": []}
    for b, n, source in edges:
        v, fwd, rev, icl = verdict(profiles, b, n)
        results["real"].append((b, n, source, v, fwd, rev, icl))
    for b, n, source in edges:
        v, fwd, rev, icl = verdict(profiles, n, b)   # flipped: does the OPPOSITE direction confirm?
        results["reversed"].append((n, b, source, v, fwd, rev, icl))

    real_pairs = [(b, n) for b, n, _ in edges]
    random_pairs = matcher.matched_pairs(real_pairs, seed=seed)
    for b, n in random_pairs:
        v, fwd, rev, icl = verdict(profiles, b, n)
        results["random"].append((b, n, "random", v, fwd, rev, icl))
    return results


def summarize_group(name: str, rows: list[tuple]) -> dict:
    tally = collections.Counter(r[3] for r in rows)
    total = len(rows)
    print(f"[direction] {name}: n={total}  "
          f"CONFIRMED={tally['CONFIRMED']} ({100*tally['CONFIRMED']/max(total,1):.1f}%)  "
          f"CONTRADICTED={tally['CONTRADICTED']} ({100*tally['CONTRADICTED']/max(total,1):.1f}%)  "
          f"UNDETERMINED={tally['UNDETERMINED']} ({100*tally['UNDETERMINED']/max(total,1):.1f}%)",
          file=sys.stderr)
    return dict(tally)


def report(results: dict[str, list[tuple]]) -> None:
    print("\n=== controls (check these FIRST -- a broken measure invalidates everything below) ===",
          file=sys.stderr)
    real = summarize_group("real edges (all)", results["real"])
    reversed_ = summarize_group("reversed edges (should look WORSE than real)", results["reversed"])
    summarize_group("random pairs (should land near chance)", results["random"])

    real_n = len(results["real"])
    if real_n and reversed_.get("CONFIRMED", 0) / real_n >= real.get("CONFIRMED", 0) / max(real_n, 1) * 0.8:
        print("[direction] WARNING: reversed-edge CONFIRMED rate is not clearly lower than real -- "
              "the measure may be detecting relatedness, not direction. Treat below numbers with "
              "real suspicion.", file=sys.stderr)

    print("\n=== real edges by source ===", file=sys.stderr)
    for source in ("apposition", "distributional", "both"):
        rows = [r for r in results["real"] if r[2] == source]
        if rows:
            summarize_group(source, rows)


# This project's established multi-seed robustness-check set (used throughout Phase A/B; a single
# TEST-book split is a go/no-go only -- see e.g. the 5-seed structural-pair-restriction check). Baking
# a `tier` into hierarchy_dag.tsv from a single split's verdict would inherit that split's sparsity
# noise permanently, so the persisted file is the multi-seed majority, not any one seed's run().
SEEDS = (13, 17, 23, 29, 31)


def run_multi_seed(seeds: tuple[int, ...] = SEEDS, dag_path: Path = DAG) -> dict[tuple[str, str], dict]:
    """(broader,narrower) -> {source, verdict, n_confirmed, n_contradicted, n_undetermined, n_seeds}.
    `verdict` is the plurality across seeds; a tie is resolved to UNDETERMINED (conservative -- don't
    tier an edge as CONFIRMED or CONTRADICTED on a coin-flip split of the evidence)."""
    per_edge: dict[tuple[str, str], dict] = {}
    source_of: dict[tuple[str, str], str] = {}
    for seed in seeds:
        for b, n, source, v, _fwd, _rev, _icl in run(seed=seed, dag_path=dag_path)["real"]:
            key = (b, n)
            source_of[key] = source
            tally = per_edge.setdefault(key, collections.Counter())
            tally[v] += 1

    out = {}
    for key, tally in per_edge.items():
        counts = {v: tally.get(v, 0) for v in ("CONFIRMED", "CONTRADICTED", "UNDETERMINED")}
        top = max(counts.values())
        winners = [v for v, c in counts.items() if c == top]
        majority = winners[0] if len(winners) == 1 else "UNDETERMINED"
        out[key] = {"source": source_of[key], "verdict": majority, "n_seeds": len(seeds), **counts}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", action="store_true", help="print single-seed control diagnostics")
    ap.add_argument("--seed", type=int, default=SEED, help="seed used only for --report")
    ap.add_argument("--candidates", type=Path, default=DAG,
                    help="same-shaped (broader/narrower/sources) TSV to check, e.g. dropped_edges.tsv")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    if args.report:
        report(run(seed=args.seed, dag_path=args.candidates))

    aggregate = run_multi_seed(dag_path=args.candidates)
    verdict_tally = collections.Counter(v["verdict"] for v in aggregate.values())
    print(f"\n[direction] multi-seed ({len(SEEDS)} seeds) majority verdicts over {len(aggregate)} edges: "
          f"CONFIRMED={verdict_tally['CONFIRMED']}  CONTRADICTED={verdict_tally['CONTRADICTED']}  "
          f"UNDETERMINED={verdict_tally['UNDETERMINED']}", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write("# Direction verdicts for hierarchy_dag.tsv edges -- held-out weighted asymmetry\n"
                  "# (WeedsPrec + invCL), majority verdict across 5 TEST-book splits (seeds "
                  f"{','.join(map(str, SEEDS))}), never used to infer these edges. See\n"
                  "# direction_yardstick.py and internal-docs/phase-c-instrument-calibration-plan.md.\n")
        fh.write("broader_strong\tnarrower_strong\tsource\tverdict\tn_confirmed\tn_contradicted\t"
                  "n_undetermined\tn_seeds\n")
        for (b, n), v in sorted(aggregate.items()):
            fh.write(f"{b}\t{n}\t{v['source']}\t{v['verdict']}\t{v['CONFIRMED']}\t{v['CONTRADICTED']}\t"
                      f"{v['UNDETERMINED']}\t{v['n_seeds']}\n")
    print(f"[direction] -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
