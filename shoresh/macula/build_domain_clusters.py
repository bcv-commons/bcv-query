#!/usr/bin/env python3
"""Domain clusters — Louvain community detection over the semantic-neighbors graph (prototype/step 1).

`semantic_neighbors/` gives PAIRWISE "X is near Y" edges — a CC0, independently-re-derived stand-in for
Louw-Nida/SDBH, never touching the MARBLE taxonomy as an input (see internal-docs/semantic-neighbors-pack.md).
This script takes the next step: turn that neighbor graph into discrete DOMAIN-like GROUPS (buckets a
lexeme belongs to), the shape Louw-Nida actually has, via graph community detection — no new external
data, no touching MARBLE, same CC0 provenance chain.

Input: resources/semantic_neighbors/by_lexeme.tsv, filtered to confidence=high, relation=similar (the
tier that scored 100% same-domain agreement against the NC yardstick in build_semantic_neighbors.py).
That's the cleanest signal to cluster on — the noisier `prior`/`recall` tiers are left for a later pass.

Method: networkx's built-in Louvain implementation (`louvain_communities`) on the high-tier graph,
weighted by score. No new dependency — networkx already ships this.

Validation (internal only, never published — same rule as build_semantic_neighbors.py's --validate):
mirrors that script's yardstick methodology exactly, but applied to CLUSTER COHABITATION instead of
graph EDGES — for every same-cluster lexeme pair, does it share >=1 real NC domain code? This measures
whether the clustering step preserves the neighbor graph's already-validated quality, or degrades it.

  python -m macula.build_domain_clusters --validate
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from itertools import combinations
from pathlib import Path

from networkx import Graph
from networkx.algorithms.community import louvain_communities

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NEIGHBORS = ROOT / "resources" / "semantic_neighbors" / "by_lexeme.tsv"
DOMAINS = ROOT / "resources" / "semantic_domains" / "hbo.tsv"
OUT = ROOT / "resources" / "semantic_neighbors" / "domain_clusters.tsv"

SEED = 13   # fixed, for reproducible cluster ids across rebuilds


def _hs(lx: str) -> str:
    m = re.search(r"(\d+)", lx or "")
    return f"{'G' if lx.startswith('grc') else 'H'}{int(m.group(1)):04d}" if m else ""


#  step 1 finding: the high-only graph (956 edges / 1296 lexemes) is too SPARSE for Louvain to find
#  real community structure — resolution-tuning plateaus at 71.4% (vs the edges' own 100%) because
#  there's little to tighten; most "clusters" are just one edge's two endpoints. Fix: densify with the
#  `prior` tier (95% edge-quality per build_semantic_neighbors.py's own validation) at a DISCOUNTED
#  weight, so Louvain has enough signal to find real neighborhoods without prior-tier noise dominating
#  high-tier confidence in the merge decision.
PRIOR_WEIGHT_DISCOUNT = 0.5   # prior-tier edges count at half weight vs. their raw score
# CANONICAL DEFAULTS (2026-08, re-swept on the BEREL+sense-split+xling-free canonical pack, correctly
# labeled this time — an earlier "step-1" sweep silently included prior-tier edges by accident, see
# domain-replacement-roadmap.md's methodology-bug note): include_prior=True (LLM-only, xling excluded
# — validated separately that xling as clustering fuel hurts quality) + resolution=5.0 gives median
# cluster size 23 (genuinely domain-sized, not 2-3-member fragments) at 45.1% same-domain agreement —
# a reasonable middle point on the high-only-vs-high+prior tradeoff (high-only alone: 60.5% quality but
# useless median-3 clusters).
# Re-swept 2026-08 after bdb_root signal added to the canonical neighbor pack (graph grew from 3,408
# to 5,648 nodes) — resolution is not portable across graph-density changes (seen repeatedly this
# project). Operating point at that point: resolution=30.0 gave median cluster size 10 at 47.8% same-
# domain agreement (up from the pre-BDB 45.1% at median 23) — better quality AND much larger coverage
# together.
# Re-swept again 2026-08 after parallelism + hwn signals added (graph grew to 5,715 nodes, 22,451
# edges). New operating point: resolution=35.0 gives median cluster size 11 at 47.1% same-domain
# agreement, 4,695 distinct Strong's covered (up from 4,628 pre-hwn) — hwn's own edges score well
# (89.7%) but its edge volume is small next to bdb_root's, so the cluster-level move is modest: real,
# not noise, but don't expect another BDB-sized jump from it.
RESOLUTION = 35.0


def load_graph(include_prior: bool = True, neighbors_path: Path = NEIGHBORS) -> Graph:
    g = Graph()
    with neighbors_path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("strong\t"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) < 9:
                continue
            _, lexeme, _, _, neighbor_lexeme, _, relation, confidence, score = p
            if relation != "similar":
                continue
            if confidence == "high":
                w = float(score)
            elif confidence == "prior" and include_prior:
                w = float(score) * PRIOR_WEIGHT_DISCOUNT
            else:
                continue
            if g.has_edge(lexeme, neighbor_lexeme):
                g[lexeme][neighbor_lexeme]["weight"] = max(g[lexeme][neighbor_lexeme]["weight"], w)
            else:
                g.add_edge(lexeme, neighbor_lexeme, weight=w)
    return g


def cluster(g: Graph, resolution: float = RESOLUTION) -> dict[str, int]:
    communities = louvain_communities(g, weight="weight", resolution=resolution, seed=SEED)
    assign = {}
    for cid, members in enumerate(communities):
        for lx in members:
            assign[lx] = cid
    return assign


def _load_domains() -> dict[str, set[str]]:
    dom: dict[str, set[str]] = collections.defaultdict(set)
    if not DOMAINS.exists():
        return dom
    for line in DOMAINS.read_text(encoding="utf-8").splitlines()[1:]:
        p = line.split("\t")
        if len(p) >= 3:
            dom[p[0]].add(p[2])
    return dom


def validate(assign: dict[str, int]) -> None:
    """Internal yardstick ONLY (never published): do same-cluster lexemes share a real NC domain?"""
    dom = _load_domains()
    if not dom:
        print("[validate] no domains table", file=sys.stderr)
        return
    by_cluster: dict[int, list[str]] = collections.defaultdict(list)
    for lx, cid in assign.items():
        by_cluster[cid].append(lx)
    same = tot = 0
    for members in by_cluster.values():
        if len(members) < 2:
            continue
        for a, b in combinations(members, 2):
            ds, db_ = dom.get(_hs(a), set()), dom.get(_hs(b), set())
            if ds and db_:
                tot += 1
                same += bool(ds & db_)
    if tot:
        print(f"[validate] same-cluster pairs sharing >=1 NC domain: {same}/{tot} = {100*same/tot:.1f}%  "
              f"(yardstick; cf. the neighbor graph's own high-conf edge rate)", file=sys.stderr)
    else:
        print("[validate] no same-cluster pairs had domain coverage on both sides", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--neighbors", type=Path, default=NEIGHBORS,
                    help="by_lexeme.tsv to cluster (default: resources/semantic_neighbors/by_lexeme.tsv). "
                         "Point at an alternative pack (e.g. semantic_neighbors_berel/) to experiment.")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--resolution", type=float, default=RESOLUTION)
    ap.add_argument("--no-prior", action="store_true",
                     help="high-tier edges only (real quality ~60%%, but median cluster size ~3 — not "
                          "domain-shaped). Default includes LLM-only prior-tier edges too (median ~23).")
    args = ap.parse_args()

    g = load_graph(neighbors_path=args.neighbors, include_prior=not args.no_prior)
    print(f"[domain-clusters] graph: {g.number_of_nodes()} lexemes, {g.number_of_edges()} edges "
          f"({'high-only' if args.no_prior else 'high+LLM-prior'}, resolution={args.resolution})",
          file=sys.stderr)
    assign = cluster(g, resolution=args.resolution)
    sizes = collections.Counter(assign.values())
    print(f"[domain-clusters] {len(sizes)} clusters; size distribution: "
          f"min={min(sizes.values())} median={sorted(sizes.values())[len(sizes)//2]} max={max(sizes.values())}",
          file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write("# Louvain communities over the semantic_neighbors graph (BEREL+sense-split, xling-free "
                  "clustering input). Canonical config: high+LLM-prior tiers, resolution=5.0 (median "
                  "cluster size 23, ~45% same-domain agreement vs SDBH yardstick). NOT LLM-labeled yet — "
                  "cluster_id is arbitrary, not a domain name. CC0 lineage. See build_domain_clusters.py.\n")
        fh.write("lexeme\tstrong\tcluster_id\tcluster_size\n")
        for lx, cid in sorted(assign.items(), key=lambda kv: (kv[1], kv[0])):
            fh.write(f"{lx}\t{_hs(lx)}\t{cid}\t{sizes[cid]}\n")
    print(f"[domain-clusters] -> {args.out}", file=sys.stderr)

    if args.validate:
        validate(assign)
    return 0


if __name__ == "__main__":
    sys.exit(main())
