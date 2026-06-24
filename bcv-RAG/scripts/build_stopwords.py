#!/usr/bin/env python3
"""Build resources/stopwords/<lang>.tsv — data-derived function-word stopwords.

Roadmap R2. A surface is a stopword when its PRIMARY alignments (share ≥ floor)
go only to *function* Strong's numbers — articles, conjunctions, particles,
prepositions (is_function=1 in strongs_freq.tsv). Derived per language from the
same word-alignment data as concept_surfaces, so it's multilingual and reviewable
— retiring the hand-authored, "needs native review" lists in analyzer_lang/.

Mirrors filter_biblical_words' runtime "all matches are function" gate, but
precomputed into a flat, shippable, inspectable list.

Output: resources/stopwords/<lang>.tsv
  columns: surface, codes, max_share
  - surface:   lowercased in-language token
  - codes:     the function Strong's it aligns to (comma-joined)
  - max_share: highest surface→Strong's share among them (confidence)

    python3 scripts/build_stopwords.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resource_paths import resource_path  # noqa: E402

ALIGNED_DIR = resource_path("aligned_lex")
FREQ = resource_path("strongs_freq.tsv")
OUT_DIR = resource_path("stopwords")

# A surface counts as a stopword if EVERY one of its renderings at/above this
# share is a function code (mirrors concept_expand's _ALIGNED_PRIMARY_SHARE)...
_PRIMARY_SHARE = 0.10
# ...AND it actually occurs often enough to be a real function word. Without this,
# a rare content word with ONE spurious function-code alignment (share 1.0 from a
# single occurrence — "administrator", "144") would be mis-flagged. Genuine
# function words (the, a, and, de, la) appear hundreds-to-thousands of times.
_MIN_COUNT = 10


def _function_codes() -> set[str]:
    out: set[str] = set()
    if not FREQ.exists():
        return out
    with FREQ.open(encoding="utf-8") as fh:
        next(fh, None)  # header
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 3 and p[2] == "1":
                out.add(p[0])
    return out


def build_lang(path: Path, funcs: set[str]) -> int:
    # surface -> list of (code, share, count) for its primary renderings
    primary: dict[str, list[tuple[str, float, int]]] = defaultdict(list)
    with path.open(encoding="utf-8") as fh:
        si = ci = cti = shi = None
        for line in fh:
            if line.startswith("#"):
                continue
            p = line.rstrip("\n").split("\t")
            if si is None:  # header
                try:
                    si, ci, cti, shi = (p.index("surface"), p.index("strong"),
                                        p.index("count"), p.index("share"))
                except ValueError:
                    return 0
                continue
            if len(p) <= max(si, ci, cti, shi):
                continue
            try:
                share, count = float(p[shi]), int(p[cti])
            except ValueError:
                continue
            if share >= _PRIMARY_SHARE:
                primary[p[si].lower()].append((p[ci], share, count))

    rows = []
    for surface, codes in primary.items():
        # all primary renderings are function AND the surface is frequent enough
        if codes and all(c in funcs for c, _, _ in codes) \
                and sum(ct for _, _, ct in codes) >= _MIN_COUNT:
            uniq = sorted({c for c, _, _ in codes})
            rows.append((surface, ",".join(uniq), max(s for _, s, _ in codes)))
    rows.sort()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / path.name
    with out.open("w", encoding="utf-8") as fh:
        fh.write(f"# source=derived from resources/aligned_lex/{path.name} + strongs_freq.tsv "
                 f"(roadmap R2: function-word stopwords); license=inherits aligned_lex\n")
        fh.write("surface\tcodes\tmax_share\n")
        for surface, codes, share in rows:
            fh.write(f"{surface}\t{codes}\t{share:.3f}\n")
    return len(rows)


def main() -> int:
    funcs = _function_codes()
    if not funcs:
        print(f"no function codes from {FREQ}", file=sys.stderr)
        return 2
    files = sorted(ALIGNED_DIR.glob("*.tsv"))
    total = 0
    for path in files:
        n = build_lang(path, funcs)
        total += n
        print(f"  {path.stem}: {n} stopwords")
    print(f"  → {len(files)} languages, {total} stopwords total ({len(funcs)} function codes) → {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
