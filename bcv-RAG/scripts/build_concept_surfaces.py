#!/usr/bin/env python3
"""Build resources/concept_surfaces/<lang>.tsv — Strong's → surface family.

Roadmap R1 ("Concept → surface family"). Inverts resources/aligned_lex/<lang>.tsv
(surface → Strong's, from word alignment) into Strong's → {all in-language surface
renderings of that concept}, ranked by alignment frequency.

At query time a consumer can expand a query word to EVERY in-language rendering of
its concept before full-text search — fixing recall on prose (study notes,
other-language Bibles) where exact match misses inflections/synonyms.

Output: resources/concept_surfaces/<lang>.tsv
  header:  # source / derived_from / license
  columns: strong, surface, count, share
  - strong:  H####/G#### (as in aligned_lex)
  - surface: an in-language rendering aligned to that Strong's
  - count:   alignment occurrences of this (strong, surface) pair
  - share:   surface→Strong's alignment confidence, carried through from
             aligned_lex = count / (this SURFACE's total alignments). High share
             means the surface genuinely renders this concept; a tiny share is
             alignment-span noise (e.g. a function word like "of"/"de" bleeding
             into a content word's span). FILTER ON THIS to keep a clean family —
             concept_expand uses a ~0.10 floor for the same reason.
  Rows sorted by strong asc, then count desc, then surface — so a concept's
  primary rendering comes first. All pairs kept (no build-time floor) so the
  table stays reusable; the consumer picks a share threshold.

Re-derivable; one file per language found under resources/aligned_lex/.
    python3 scripts/build_concept_surfaces.py
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resource_paths import resource_path  # noqa: E402

ALIGNED_DIR = resource_path("aligned_lex")
OUT_DIR = resource_path("concept_surfaces")


def _read_aligned(path: Path):
    """Yield (surface, strong, count, share) from an aligned_lex TSV, skipping the
    leading `# source=` comment line(s) and the column header."""
    with path.open(encoding="utf-8") as fh:
        header_seen = False
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            if not header_seen:
                header_seen = True          # the `surface\tstrong\tcount\tshare` header
                continue
            if len(parts) < 4:
                continue
            surface, strong, count, share = parts[0], parts[1], parts[2], parts[3]
            if not surface or not strong:
                continue
            try:
                yield surface, strong, int(count), float(share)
            except ValueError:
                continue


def build_lang(path: Path) -> tuple[int, int]:
    # strong -> list of (surface, count, share). aligned_lex has one row per
    # (surface, strong), so this is a re-key + re-sort, share carried through.
    by_strong: dict[str, list[tuple[str, int, float]]] = {}
    for surface, strong, count, share in _read_aligned(path):
        by_strong.setdefault(strong, []).append((surface, count, share))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / path.name
    n_rows = 0
    with out.open("w", encoding="utf-8") as fh:
        fh.write(f"# source=derived from resources/aligned_lex/{path.name} "
                 f"(roadmap R1: Strong's -> surface family)\n")
        fh.write("# derived_from=aligned_lex; license=inherits aligned_lex "
                 "(Clear-Bible/Alignments); share=surface→Strong's confidence (filter noise)\n")
        fh.write("strong\tsurface\tcount\tshare\n")
        for strong in sorted(by_strong):
            for surface, count, share in sorted(by_strong[strong], key=lambda t: (-t[1], t[0])):
                fh.write(f"{strong}\t{surface}\t{count}\t{share:.3f}\n")
                n_rows += 1
    return len(by_strong), n_rows


def main() -> int:
    files = sorted(ALIGNED_DIR.glob("*.tsv"))
    if not files:
        print(f"no aligned_lex files under {ALIGNED_DIR}", file=sys.stderr)
        return 2
    total_pairs = 0
    for path in files:
        n_strong, n_rows = build_lang(path)
        total_pairs += n_rows
        print(f"  {path.stem}: {n_strong} Strong's, {n_rows} surface rows")
    print(f"  → {len(files)} languages, {total_pairs} rows total → {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
