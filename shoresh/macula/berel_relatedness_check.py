#!/usr/bin/env python3
"""BEREL relatedness check for hierarchy_dag.tsv (Phase C step 4, internal-docs/
phase-c-instrument-calibration-plan.md) -- an independent check on the "medium" tier (491 edges
direction_yardstick.py could not confirm OR contradict, usually held-out-corpus sparsity rather than
real ambiguity, see tier_hierarchy_dag.py).

Genuinely DIFFERENT question from direction_yardstick.py, and answerable with a DIFFERENT instrument:
not "which side is broader" (BEREL cosine similarity is symmetric, it has no notion of direction) but
"are these two lexemes even semantically related at all, or is this apposition/distributional pair
noise" (e.g. the dropped-edge pool's "father, land" apposition -- co-occurring in a clause, not a real
semantic relation). A medium-tier edge with LOW BEREL similarity is a candidate for being exactly that
kind of noise, independent of whatever direction it was assigned.

Reuses build_semantic_neighbors.lexeme_vectors() (already handles proper-noun/non-content filtering
and the BEREL-vs-bge-m3 embedding-file swap) and its own mean-centering recipe (removes the "generic
biblical clause" anisotropy direction that otherwise inflates every cosine toward ~0.94) rather than
re-deriving either. Aggregates lexeme-level centroids up to STRONG'S level (hierarchy_dag.tsv is
Strong's-keyed; MACULA lexeme is the finer-grained homograph key) by simple mean + renormalize.

CIRCULARITY NOTE (same honesty standard as intrinsic_yardstick.py's own caveat): BEREL's input
segmentation uses BHSA clause boundaries, so this isn't a fully independent corpus -- but it's a much
shallower dependency than direction_yardstick.py's own reuse of BHSA slot-filler grammar, and BEREL's
embeddings encode contextual/distributional meaning, not the apposition/construct RELATIONS the DAG's
direction claims are built from. Different facet, weaker overlap -- noted, not hidden.

  python -m macula.berel_relatedness_check --report
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
import sys
from pathlib import Path

import numpy as np

from macula.build_semantic_neighbors import lexeme_vectors

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BEREL = ROOT / "resources" / "occurrences" / "context_emb__dicta_il_BEREL_3_0.npz"
HBO = ROOT / "resources" / "occurrences" / "hbo.db"
DAG = ROOT / "resources" / "bhsa_hierarchy" / "hierarchy_dag.tsv"
OUT = DAG
SUSPECT_OUT = ROOT / "resources" / "bhsa_hierarchy" / "hierarchy_dag_suspect.tsv"

SEED = 13   # for the frequency-matched random baseline only -- no held-out split needed here (BEREL
            # was never used to infer these edges in the first place, unlike the yardstick's own signal)


def strong_centroids() -> dict[str, np.ndarray]:
    lexemes, M, meta = lexeme_vectors(BEREL)
    M = M - M.mean(axis=0, keepdims=True)             # same anisotropy fix as build_semantic_neighbors.build()
    M /= (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
    acc: dict[str, np.ndarray] = collections.defaultdict(lambda: np.zeros(M.shape[1], np.float32))
    cnt = collections.Counter()
    for i, lx in enumerate(lexemes):
        hstrong, _ = meta[lx]
        if not hstrong:
            continue
        acc[hstrong] += M[i]
        cnt[hstrong] += 1
    out = {}
    for s, v in acc.items():
        c = v / cnt[s]
        n = np.linalg.norm(c)
        if n > 0:
            out[s] = c / n
    return out


def cos(a: str, b: str, centroids: dict[str, np.ndarray]):
    va, vb = centroids.get(a), centroids.get(b)
    if va is None or vb is None:
        return None
    return float(np.dot(va, vb))


def load_dag() -> list[tuple[str, str, str, str]]:
    rows = []
    for line in DAG.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith("broader_strong"):
            continue
        p = line.split("\t")
        rows.append((p[0], p[1], p[2], p[3]))   # broader, narrower, sources, tier
    return rows


def strong_frequencies() -> dict[str, int]:
    db = sqlite3.connect(f"file:{HBO}?mode=ro", uri=True)
    return dict(db.execute("SELECT strong, COUNT(*) FROM occurrence WHERE strong LIKE 'H%' "
                            "GROUP BY strong"))


def random_pairs(strongs: list[str], freq: dict[str, int], n: int, seed: int = SEED) -> list[tuple[str, str]]:
    """Frequency-matched (not frequency-weighted) -- mirrors intrinsic_yardstick's FrequencyMatcher
    principle so common hub words (kol/H3605) don't dominate the baseline. Simple local
    implementation rather than importing FrequencyMatcher, which is keyed to slot-profile occurrence
    counts, not this script's strong_frequencies()."""
    import random as _random
    rng = _random.Random(seed)
    weighted = [s for s in strongs for _ in range(min(freq.get(s, 1), 50))]   # cap so hub words don't
                                                                                # dominate the sample pool
    out = []
    seen = set()
    tries = 0
    while len(out) < n and tries < n * 50:
        tries += 1
        a, b = rng.choice(weighted), rng.choice(weighted)
        if a == b or (a, b) in seen or (b, a) in seen:
            continue
        seen.add((a, b))
        out.append((a, b))
    return out


def summarize(name: str, sims: list[float]) -> None:
    if not sims:
        print(f"[berel] {name}: n=0 (no scorable pairs)", file=sys.stderr)
        return
    arr = np.array(sims)
    print(f"[berel] {name}: n={len(arr)}  mean={arr.mean():.4f}  median={np.median(arr):.4f}  "
          f"p25={np.percentile(arr, 25):.4f}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--suspect-percentile", type=float, default=25,
                    help="medium-tier edges scoring below this percentile of the RANDOM baseline's "
                         "distribution are flagged as suspect (default: 25th percentile)")
    args = ap.parse_args()

    centroids = strong_centroids()
    print(f"[berel] {len(centroids)} Strong's-level centroids", file=sys.stderr)

    dag_rows = load_dag()
    by_tier: dict[str, list[tuple[str, str, str, float]]] = collections.defaultdict(list)
    missing = 0
    for b, n, sources, tier in dag_rows:
        c = cos(b, n, centroids)
        if c is None:
            missing += 1
            continue
        by_tier[tier].append((b, n, sources, c))

    freq = strong_frequencies()
    all_strongs = sorted(centroids)
    rand = random_pairs(all_strongs, freq, n=max(200, len(dag_rows) // 2))
    rand_sims = [c for a, b in rand if (c := cos(a, b, centroids)) is not None]

    if args.report:
        print(f"[berel] {missing}/{len(dag_rows)} DAG edges skipped (no BEREL centroid for one side, "
              f"< MIN_OCC clauses or proper noun/non-content filtered)", file=sys.stderr)
        summarize("random pairs (frequency-matched baseline)", rand_sims)
        for tier in ("high", "medium"):
            summarize(f"DAG edges, tier={tier}", [c for *_, c in by_tier[tier]])

    suspect_floor = float(np.percentile(rand_sims, args.suspect_percentile)) if rand_sims else -1.0
    suspects = [(b, n, sources, c) for b, n, sources, c in by_tier.get("medium", []) if c < suspect_floor]
    print(f"[berel] {len(suspects)}/{len(by_tier.get('medium', []))} medium-tier edges score below "
          f"the random baseline's {args.suspect_percentile:.0f}th percentile ({suspect_floor:.4f}) -- "
          f"flagged as suspect, not removed", file=sys.stderr)

    cos_of = {(b, n): c for b, n, _, c in [row for rows in by_tier.values() for row in rows]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        fh.write("# Directed Hebrew hierarchy (broader -> narrower), assembled from apposition\n"
                  "# direction (BHSA grammar) + distributional inclusion (held-out verified, see\n"
                  "# build_hierarchy_dag.py). Text-anchored, no SDBH/MARBLE.\n"
                  "# `tier`: high = CONFIRMED by direction_yardstick.py's 5-seed held-out majority\n"
                  "# vote; medium = UNDETERMINED there (usually held-out sparsity). `berel_cos`:\n"
                  "# cosine similarity of mean-centered BEREL Strong's centroids (relatedness, not\n"
                  "# direction -- symmetric) -- see berel_relatedness_check.py; blank if either side\n"
                  "# lacked a scorable centroid.\n")
        fh.write("broader_strong\tnarrower_strong\tsources\ttier\tberel_cos\n")
        for b, n, sources, tier in sorted(dag_rows):
            c = cos_of.get((b, n))
            fh.write(f"{b}\t{n}\t{sources}\t{tier}\t{'' if c is None else f'{c:.4f}'}\n")
    print(f"[berel] -> {OUT}", file=sys.stderr)

    SUSPECT_OUT.parent.mkdir(parents=True, exist_ok=True)
    with SUSPECT_OUT.open("w", encoding="utf-8") as fh:
        fh.write("# medium-tier hierarchy_dag.tsv edges whose BEREL relatedness (see\n"
                  "# berel_relatedness_check.py) sits below the frequency-matched random baseline's\n"
                  f"# {args.suspect_percentile:.0f}th percentile ({suspect_floor:.4f}) -- candidates for being\n"
                  "# noise apposition/distributional pairs rather than real semantic relations.\n"
                  "# Flagged, not removed from hierarchy_dag.tsv.\n")
        fh.write("broader_strong\tnarrower_strong\tsources\tberel_cos\n")
        for b, n, sources, c in sorted(suspects):
            fh.write(f"{b}\t{n}\t{sources}\t{c:.4f}\n")
    print(f"[berel] -> {SUSPECT_OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
