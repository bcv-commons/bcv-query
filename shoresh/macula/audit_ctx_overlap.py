#!/usr/bin/env python3
"""QA audit: does any PUBLISHED (core-axis, synonymy) pair overlap with a genre_context (ctx-axis,
register/setting) pair? Not proof of a false positive by itself -- two words can genuinely be both
synonyms AND share a setting -- but genre_context's own yardstick validated at 14.4x lift
(internal-docs/text-anchored-semantics-plan.md), so an overlap is worth a manual look: it's exactly
the failure mode this project already learned to avoid once with SDBH's own core/ctx axis blend
(two words sharing a `ctx` register tag isn't a synonymy signal).

Zero new pipeline code / no risk to anything live -- reads two already-built TSVs, reports overlaps.

  python -m macula.audit_ctx_overlap
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CONTEXT_PAIRS = ROOT / "resources" / "genre_context" / "context_pairs.tsv"
PUBLISHED_PAIRS = ROOT / "resources" / "semantic_neighbors" / "published_pairs.tsv"


def load_ctx_pairs() -> dict[frozenset, float]:
    out = {}
    for line in CONTEXT_PAIRS.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith("strong_a"):
            continue
        p = line.split("\t")
        if len(p) >= 3:
            out[frozenset((p[0], p[1]))] = float(p[2])
    return out


def load_published_pairs() -> dict[frozenset, tuple[str, int]]:
    out = {}
    for line in PUBLISHED_PAIRS.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith("strong_a"):
            continue
        p = line.split("\t")
        if len(p) >= 4:
            out[frozenset((p[0], p[1]))] = (p[2], int(p[3]))
    return out


def main() -> int:
    ctx = load_ctx_pairs()
    published = load_published_pairs()
    overlap = set(ctx) & set(published)

    print(f"[audit] {len(published)} published pairs, {len(ctx)} genre_context pairs, "
          f"{len(overlap)} overlap ({100*len(overlap)/max(len(published),1):.2f}% of published)",
          file=sys.stderr)

    if overlap:
        print("\nstrong_a\tstrong_b\tctx_cosine\tgate\tn_families", file=sys.stderr)
        for pair in sorted(overlap, key=lambda p: -ctx[p]):
            a, b = sorted(pair)
            gate, n_fam = published[pair]
            print(f"{a}\t{b}\t{ctx[pair]:.3f}\t{gate}\t{n_fam}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
