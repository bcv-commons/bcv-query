#!/usr/bin/env python3
"""Assemble a directed hierarchy (broader -> narrower) from two independent, text-anchored sources
(Phase B step 7, internal-docs/text-anchored-semantics-plan.md) -- the first hierarchy this project
has built; everything before this was flat pairwise "similar" edges.

Source 1 -- APPOSITION DIRECTION (build_hierarchy_relations.py's apposition_directed.tsv): the head
of an apposition is the broader term, the appositive narrows/restates it (e.g. "Pharaoh (head), the
king (appositive)" -> Pharaoh -> king is backwards for this purpose; direction taken is head=broader
category, appositive=specific instance, matching the majority pattern in the sample data eyeballed
2026-08-15: "lord, the king" / "Pharaoh, the king" / "children, priest"). Hub heads filtered (top
2% by out-degree, e.g. H3605 "every/all" -- appears as construct/apposition head far too often to
carry hierarchy information, same contamination pattern as intrinsic_yardstick.py's hub verb-slots).

Source 2 -- DISTRIBUTIONAL INCLUSION (the classic hypernymy-detection heuristic, Weeds/Weir-style):
if X's slot-filler profile (build_slot_profiles.py) is a near-superset of Y's -- X appears in every
context Y does, plus more -- X is the broader term. Computed only over an already-corroborated
candidate pool (confidence_tiers.tsv's n_families>=2 "cross_signal" pairs) to keep this tractable;
NOT run over the full O(n^2) lexeme space.

Verification: distributional-inclusion edges are checked for genuine held-out generalization --
direction inferred from TRAIN-book profiles must still show as containment (not just correlation) on
INDEPENDENTLY-computed TEST-book profiles, mirroring intrinsic_yardstick.py's own methodology. This
is the harder bar; apposition-direction edges are checked for cycles only (BHSA grammar itself is the
evidence there, not a statistical inference to re-validate).

Rerunning this script regenerates the plain 3-column (broader/narrower/sources) file -- if
direction_yardstick.py + tier_hierarchy_dag.py have already added the `tier` column and pruned
CONTRADICTED edges (Phase C step 3), re-run that pair afterward too, in that order.

  python -m macula.build_hierarchy_dag
  python -m macula.direction_yardstick   # then, to restore tiering:
  python -m macula.tier_hierarchy_dag
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
import sys
from pathlib import Path

from macula.build_slot_profiles import extract as extract_slot_triples
from macula.intrinsic_yardstick import book_split

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
APPOSITION = ROOT / "resources" / "bhsa_hierarchy" / "apposition_directed.tsv"
CONFIDENCE_TIERS = ROOT / "resources" / "semantic_neighbors" / "confidence_tiers.tsv"
HBO = ROOT / "resources" / "occurrences" / "hbo.db"
OUT = ROOT / "resources" / "bhsa_hierarchy" / "hierarchy_dag.tsv"
DROPPED_OUT = ROOT / "resources" / "bhsa_hierarchy" / "dropped_edges.tsv"

HUB_PERCENTILE = 98          # apposition heads above this out-degree percentile are dropped
MIN_PROFILE_SIZE = 3         # a lexeme needs >= this many (verb,slot) contexts to be considered
CONTAINMENT_MIN = 0.8        # fraction of the narrower side's contexts the broader side must also cover
MIN_BROADER_RATIO = 1.3      # broader side's profile must be at least this much bigger


def load_apposition_edges() -> list[tuple[str, str, int]]:
    if not APPOSITION.exists():
        return []
    rows = []
    for line in APPOSITION.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith("head_strong"):
            continue
        h, a, cnt = line.split("\t")
        rows.append((h, a, int(cnt)))
    out_degree = collections.Counter(h for h, _, _ in rows)
    if not out_degree:
        return []
    cutoff = sorted(out_degree.values())[int(len(out_degree) * HUB_PERCENTILE / 100)]
    hubs = {h for h, d in out_degree.items() if d > cutoff}
    kept = [(h, a, cnt) for h, a, cnt in rows if h not in hubs]
    print(f"[hierarchy-dag] apposition: {len(rows)} raw edges, {len(hubs)} hub heads dropped "
          f"(e.g. out-degree > {cutoff}), {len(kept)} kept", file=sys.stderr)
    return kept


def load_cross_signal_pairs() -> list[tuple[str, str]]:
    if not CONFIDENCE_TIERS.exists():
        return []
    pairs = []
    for line in CONFIDENCE_TIERS.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith("strong_a"):
            continue
        p = line.split("\t")
        if len(p) >= 3 and int(p[2]) >= 2:
            pairs.append((p[0], p[1]))
    return pairs


def build_profiles(books) -> dict[str, set]:
    triples = extract_slot_triples(books=books)
    profiles: dict[str, set] = collections.defaultdict(set)
    for (verb, slot, filler), _cnt in triples.items():
        profiles[filler].add((verb, slot))
    return dict(profiles)


def containment(broader: set, narrower: set) -> float:
    if not narrower:
        return 0.0
    return len(broader & narrower) / len(narrower)


def infer_distributional_edges(pairs, profiles) -> list[tuple[str, str, float]]:
    """[(broader, narrower, containment_score)] for cross_signal pairs where one side's profile
    clearly contains the other's."""
    out = []
    for a, b in pairs:
        pa, pb = profiles.get(a), profiles.get(b)
        if not pa or not pb or len(pa) < MIN_PROFILE_SIZE or len(pb) < MIN_PROFILE_SIZE:
            continue
        if len(pa) >= len(pb) * MIN_BROADER_RATIO:
            c = containment(pa, pb)
            if c >= CONTAINMENT_MIN:
                out.append((a, b, c))
        elif len(pb) >= len(pa) * MIN_BROADER_RATIO:
            c = containment(pb, pa)
            if c >= CONTAINMENT_MIN:
                out.append((b, a, c))
    return out


def verify_held_out(edges: list[tuple[str, str, float]], seed: int = 13) -> None:
    """For distributional-inclusion edges only: does the SAME containment direction hold when broader
    and narrower profiles are computed independently on held-out TEST books, never used to infer the
    edge in the first place?"""
    train_books, test_books = book_split(seed=seed)
    test_profiles = build_profiles(test_books)
    confirmed = checkable = 0
    for broader, narrower, _score in edges:
        pb, pn = test_profiles.get(broader), test_profiles.get(narrower)
        if not pb or not pn or len(pn) < 2:
            continue
        checkable += 1
        if containment(pb, pn) >= 0.5:   # a looser bar on the (much sparser) held-out side
            confirmed += 1
    if checkable:
        print(f"[hierarchy-dag] held-out check: {confirmed}/{checkable} distributional edges "
              f"({100*confirmed/checkable:.1f}%) still show containment on independently-computed "
              f"TEST-book profiles", file=sys.stderr)
    else:
        print("[hierarchy-dag] held-out check: no distributional edges had enough test-side data "
              "to check", file=sys.stderr)


def generality_scores(nodes: set[str], profiles: dict[str, set]) -> dict[str, int]:
    """node -> generality score (bigger = broader): slot-profile size when available (the same
    footprint distributional inclusion already uses), else raw corpus occurrence count as a fallback
    for nodes that never fill a Subj/Objc/Cmpl/PreC slot (rare words, some proper nouns in apposition
    pairs)."""
    scores = {n: len(profiles[n]) for n in nodes if n in profiles}
    missing = nodes - scores.keys()
    if missing:
        db = sqlite3.connect(f"file:{HBO}?mode=ro", uri=True)
        placeholders = ",".join("?" * len(missing))
        for strong, cnt in db.execute(
            f"SELECT strong, COUNT(*) FROM occurrence WHERE strong IN ({placeholders}) GROUP BY strong",
            tuple(missing),
        ):
            scores[strong] = -1000 + cnt   # kept on a separate, lower scale so profile-based scores
                                            # (real distributional footprint) always outrank a raw
                                            # frequency fallback when both are available for a pair
    return scores


def enforce_acyclic(all_edges: dict[tuple[str, str], list[str]],
                     scores: dict[str, int]) -> tuple[dict[tuple[str, str], list[str]],
                                                        dict[tuple[str, str], list[str]]]:
    """(kept, dropped). Keep only edges consistent with generality(broader) > generality(narrower). A
    strict global ordering can't cycle by construction (ties, or missing scores on either side, are
    dropped rather than guessed at). `dropped` -- the direction each edge was originally proposed with
    (apposition/distributional), not re-derived -- is the candidate pool for optional LLM adjudication
    later (see adjudicate_direction_llm.py); persisted by main() so that pool doesn't have to be
    reconstructed by re-running this filter by hand."""
    kept, dropped = {}, {}
    for (b, n), sources in all_edges.items():
        sb, sn = scores.get(b), scores.get(n)
        if sb is not None and sn is not None and sb > sn:
            kept[(b, n)] = sources
        else:
            dropped[(b, n)] = sources
    print(f"[hierarchy-dag] acyclic filter: {len(dropped)} edges dropped (reversed/tied/unscored), "
          f"{len(kept)} kept", file=sys.stderr)
    return kept, dropped


def find_cycles(edges: list[tuple[str, str]]) -> list[list[str]]:
    graph = collections.defaultdict(list)
    for a, b in edges:
        graph[a].append(b)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = collections.defaultdict(int)
    cycles = []

    def dfs(node, path):
        color[node] = GRAY
        path.append(node)
        for nxt in graph.get(node, []):
            if color[nxt] == GRAY:
                i = path.index(nxt)
                cycles.append(path[i:] + [nxt])
            elif color[nxt] == WHITE:
                dfs(nxt, path)
        path.pop()
        color[node] = BLACK

    for n in list(graph):
        if color[n] == WHITE:
            dfs(n, [])
    return cycles


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    appo_edges = load_apposition_edges()
    cross_signal_pairs = load_cross_signal_pairs()
    print(f"[hierarchy-dag] cross_signal candidate pool: {len(cross_signal_pairs)} pairs", file=sys.stderr)

    full_profiles = build_profiles(books=None)
    print(f"[hierarchy-dag] whole-OT slot profiles: {len(full_profiles)} lexemes", file=sys.stderr)

    dist_edges = infer_distributional_edges(cross_signal_pairs, full_profiles)
    print(f"[hierarchy-dag] distributional inclusion: {len(dist_edges)} edges "
          f"(containment >= {CONTAINMENT_MIN}, broader/narrower ratio >= {MIN_BROADER_RATIO})",
          file=sys.stderr)

    verify_held_out(dist_edges, seed=13)

    all_edges: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for h, a, cnt in appo_edges:
        all_edges[(h, a)].append(f"apposition:{cnt}")
    for b, n, score in dist_edges:
        all_edges[(b, n)].append(f"distributional:{score:.2f}")

    cycles = find_cycles(list(all_edges.keys()))
    print(f"[hierarchy-dag] {len(all_edges)} raw directed edges, {len(cycles)} cycles found "
          f"before filtering", file=sys.stderr)

    all_nodes = {n for pair in all_edges for n in pair}
    scores = generality_scores(all_nodes, full_profiles)
    all_edges, dropped_edges = enforce_acyclic(all_edges, scores)

    residual_cycles = find_cycles(list(all_edges.keys()))
    print(f"[hierarchy-dag] residual cycles after filtering: {len(residual_cycles)} "
          f"(should be 0 -- generality is a strict total order)", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write("# Directed Hebrew hierarchy (broader -> narrower), assembled from apposition\n"
                  "# direction (BHSA grammar) + distributional inclusion (held-out verified, see\n"
                  "# build_hierarchy_dag.py). First hierarchy this project has built -- everything\n"
                  "# before this was flat pairwise 'similar' edges. Text-anchored, no SDBH/MARBLE.\n")
        fh.write("broader_strong\tnarrower_strong\tsources\n")
        for (b, n), sources in sorted(all_edges.items()):
            fh.write(f"{b}\t{n}\t{'|'.join(sources)}\n")
    print(f"[hierarchy-dag] -> {args.out}", file=sys.stderr)

    DROPPED_OUT.parent.mkdir(parents=True, exist_ok=True)
    with DROPPED_OUT.open("w", encoding="utf-8") as fh:
        fh.write("# Edges enforce_acyclic() dropped (reversed/tied/unscored under the generality-\n"
                  "# ordering filter) -- direction shown is as originally proposed by apposition/\n"
                  "# distributional, NOT re-derived. Candidate pool for optional LLM adjudication,\n"
                  "# see adjudicate_direction_llm.py. Distinct from hierarchy_dag_flagged.tsv (edges\n"
                  "# that DID survive assembly but direction_yardstick.py's held-out check\n"
                  "# CONTRADICTED).\n")
        fh.write("broader_strong\tnarrower_strong\tsources\n")
        for (b, n), sources in sorted(dropped_edges.items()):
            fh.write(f"{b}\t{n}\t{'|'.join(sources)}\n")
    print(f"[hierarchy-dag] -> {DROPPED_OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
