#!/usr/bin/env python3
"""Publish a pruned, tree-shaped view of hierarchy_dag.tsv (Phase C step 5, internal-docs/
phase-c-instrument-calibration-plan.md) -- the internal DAG stays as-is (full multi-parent graph,
tier + berel_cos columns); this derives a separate, smaller, cleaner artifact for actual consumption,
mirroring semantic_neighbors/'s own internal-parquet vs. published-TSV split.

WHY: a structural analysis of the raw DAG (519 nodes, 636 edges) found it doesn't look like a usable
hierarchy -- max depth 9, 28.9% of nodes with multiple parents, 17 hub words (H1004 "place", H4428
"king", H5971 "people", H3605 "all"...) responsible for 35% of all edges, gluing otherwise-unrelated
local pairs into one 386-node hairball. A one-time STRUCTURAL comparison against how SDBH/Louw-Nida
publishes its own domain hierarchy (shape only -- no SDBH data used as an input here, retirement
decision unchanged, see internal-docs/text-anchored-semantics-plan.md) gave a concrete target: SDBH is
exactly 2 levels deep, ~93 top-level domains, strict tree (single parent by construction), branching
~8.9 among domains that subdivide. Ours doesn't need to match those numbers exactly (empirically-mined
lexeme relations vs. a designed classification scheme are different things), but "shallow, tree-shaped,
moderate branching" is the right shape to aim for, and the swept fixes below get there.

TWO FIXES, both needed, in this order:
  1. Drop hub-anchored edges -- HUB_CUTOFF=6 (swept 3/4/5/6/8/10; 6 keeps 43% of edges, caps the
     largest surviving component at 21 nodes, only 6 of ~132 components reach depth>=3).
  2. Force single-parent-per-node -- for any node with multiple surviving parent candidates, keep only
     the best one (tier high > medium, `berel_cos` as tie-break). This is the fix that actually caps
     depth (9 -> 4 in the sweep, at EVERY hub cutoff tested) -- the runaway-depth chains turned out to
     be a multi-parent artifact (a node borrowing a different "best" parent at each step to thread an
     artificially long path), not something hub removal alone fixes.

WHAT THIS DOES NOT FIX, and why the published schema is edge-only: even after both fixes, depth>=3
paths were spot-checked and are still not reliably coherent as semantic chains (e.g. "head -> great ->
River -> Nile" -- each adjacent link has SOME local association, but the full path doesn't read as one
consistent broader->narrower descent; this is a known property of edges assembled one pair at a time
with no global path-coherence check). So `published_hierarchy.tsv` exposes direct parent->child edges
only -- the part that's actually reliable -- not multi-hop traversal. A consumer CAN chain edges
themselves, but this project isn't asserting that's meaningful.

  python -m macula.publish_hierarchy_dag
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

import networkx as nx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DAG = ROOT / "resources" / "bhsa_hierarchy" / "hierarchy_dag.tsv"
GLOSS_TSV = ROOT / "resources" / "strongs_gloss.tsv"
OUT = ROOT / "resources" / "bhsa_hierarchy" / "published_hierarchy.tsv"
MANIFEST = ROOT / "resources" / "bhsa_hierarchy" / "published_manifest.json"

HUB_CUTOFF = 6   # edges touching a node with full-DAG out-degree >= this are dropped -- see docstring
TIER_RANK = {"high": 1, "medium": 0}


def load_dag() -> list[tuple[str, str, str, float]]:
    rows = []
    for line in DAG.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith("broader_strong"):
            continue
        p = line.rstrip("\n").split("\t")
        b, n, tier = p[0], p[1], p[3]
        cos = float(p[4]) if len(p) > 4 and p[4] else -1.0
        rows.append((b, n, tier, cos))
    return rows


def load_glosses() -> dict[str, str]:
    gl: dict[str, str] = {}
    if not GLOSS_TSV.exists():
        return gl
    with GLOSS_TSV.open(encoding="utf-8") as fh:
        header = next(fh).rstrip("\n").split("\t")
        idx = {name: i for i, name in enumerate(header)}
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) > idx.get("lang", -1) and p[idx["lang"]] == "eng":
                gl.setdefault(p[idx["strong"]], p[idx["gloss"]])
    return gl


def build_published(rows: list[tuple[str, str, str, float]], hub_cutoff: int = HUB_CUTOFF):
    full_out_deg = collections.Counter(b for b, *_ in rows)
    hubs = {n for n, d in full_out_deg.items() if d >= hub_cutoff}

    kept = [(b, n, tier, cos) for b, n, tier, cos in rows if b not in hubs and n not in hubs]

    best: dict[str, tuple[tuple[int, float], str, str, float]] = {}
    for b, n, tier, cos in kept:
        key = (TIER_RANK[tier], cos)
        if n not in best or key > best[n][0]:
            best[n] = (key, b, tier, cos)

    edges = [(b, n, tier, cos) for n, (_, b, tier, cos) in best.items()]
    return edges, hubs


def graph_stats(edges: list[tuple[str, str, str, float]]) -> dict:
    G = nx.DiGraph()
    G.add_edges_from((b, n) for b, n, *_ in edges)
    wcc = list(nx.weakly_connected_components(G))
    depths = []
    for c in wcc:
        try:
            depths.append(nx.dag_longest_path_length(G.subgraph(c)))
        except Exception:
            depths.append(0)
    sizes = sorted((len(c) for c in wcc), reverse=True)
    return {
        "nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "components": len(wcc),
        "max_component_size": sizes[0] if sizes else 0, "max_depth": max(depths) if depths else 0,
        "components_depth_ge3": sum(1 for d in depths if d >= 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hub-cutoff", type=int, default=HUB_CUTOFF)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    args = ap.parse_args()

    rows = load_dag()
    edges, hubs = build_published(rows, args.hub_cutoff)
    stats = graph_stats(edges)
    glosses = load_glosses()

    print(f"[publish-dag] {len(rows)} internal edges -> {len(hubs)} hubs (out-degree >= "
          f"{args.hub_cutoff}) removed -> {len(edges)} edges after single-parent collapse",
          file=sys.stderr)
    print(f"[publish-dag] {stats['nodes']} nodes, {stats['components']} components, "
          f"max component={stats['max_component_size']}, max depth={stats['max_depth']}, "
          f"{stats['components_depth_ge3']} components reach depth>=3", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write("# Published Hebrew hierarchy -- pruned + tree-shaped view of hierarchy_dag.tsv\n"
                  "# (internal, unpruned, kept separately). EDGE-ONLY: direct parent->child pairs,\n"
                  "# not multi-hop paths -- chaining rows yourself is not asserted to be semantically\n"
                  "# coherent, see publish_hierarchy_dag.py. `tier`/`berel_cos` as in the internal DAG.\n"
                  "# Text-anchored, no SDBH/MARBLE as an input (structural comparison only).\n")
        fh.write("broader_strong\tbroader_gloss\tnarrower_strong\tnarrower_gloss\ttier\tberel_cos\n")
        for b, n, tier, cos in sorted(edges):
            fh.write(f"{b}\t{glosses.get(b, '')}\t{n}\t{glosses.get(n, '')}\t{tier}\t"
                      f"{'' if cos < 0 else f'{cos:.4f}'}\n")
    print(f"[publish-dag] -> {args.out}", file=sys.stderr)

    content_sha256 = hashlib.sha256(args.out.read_bytes()).hexdigest()
    manifest = {
        "dataset": "bhsa_hierarchy/published_hierarchy",
        "derived_from": "hierarchy_dag.tsv (internal, kept separately, not pruned)",
        "method": "hub-edge removal (out-degree >= hub_cutoff dropped) + single-best-parent collapse "
                  "(tier, then berel_cos, as tie-break)",
        "hub_cutoff": args.hub_cutoff,
        "shape_target": "structural comparison to SDBH/Louw-Nida's published domain hierarchy "
                        "(2 levels, ~93 top-level domains, strict tree, branching ~8.9) -- SDBH data "
                        "not used as an input, retirement decision unchanged",
        "scope_note": "edge-only (direct parent->child); multi-hop paths not asserted coherent",
        **stats,
        "content_sha256": content_sha256,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[publish-dag] -> {args.manifest}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
