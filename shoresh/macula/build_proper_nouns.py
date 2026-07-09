#!/usr/bin/env python3
"""Proper-noun lexicon (roadmap N1) — localized name renderings per biblical name Strong's.

A name Strong's (person/place) → how that name is written across languages, from two signals:
  • **gloss**    — the curated, localized name + transliteration (`strongs_gloss.tsv`, per language)
  • **aligned**  — names actually attested in real translations (`aligned_lex/<iso>.tsv`, empirical)

Proper nouns are identified by STEPBible's `Np` morph (`proper_strongs()`), so this is **OT/Hebrew for
now** — MACULA Greek carries no proper-noun flag, so NT Greek names need TIPNR (CC-BY) or STEP TAGNT
(roadmap N1 = the full version; see internal-docs). The lexicon lets the analyzer recognize a name in a
query (any language) → map to its Strong's → retrieve + drive the name-bridge.

  python -m macula.build_proper_nouns          # -> resources/proper_nouns/proper_nouns.tsv
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
from macula.build_semantic_neighbors import proper_strongs  # noqa: E402

GLOSS = ROOT / "resources" / "strongs_gloss.tsv"
ALIGNED_DIR = ROOT / "resources" / "aligned_lex"
OUT_DIR = ROOT / "resources" / "proper_nouns"

MIN_COUNT = 2       # an aligned surface needs this many attestations (drop one-off alignment noise)
MIN_SHARE = 0.10    # …and this share of the Strong's alignments
TOPK = 8            # aligned surfaces kept per (strong, lang)


def _load_glosses(proper):
    """{strong: {lang: [names]}} + {strong: translit} from strongs_gloss.tsv, restricted to names."""
    by: dict = collections.defaultdict(lambda: collections.defaultdict(list))
    translit: dict = {}
    if not GLOSS.exists():
        return by, translit
    with GLOSS.open(encoding="utf-8") as fh:
        next(fh, None)
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 4 and p[0] in proper:
                strong, gloss, tr, lang = p[0], p[1].strip(), p[2].strip(), p[3].strip()
                if gloss:
                    by[strong][lang].append(gloss)
                if tr and strong not in translit:
                    translit[strong] = tr
    return by, translit


def _load_aligned(proper):
    """{strong: {lang: [(surface, share, count)]}} from aligned_lex/<iso>.tsv, names only, thresholded."""
    by: dict = collections.defaultdict(lambda: collections.defaultdict(list))
    for path in sorted(ALIGNED_DIR.glob("*.tsv")):
        lang = path.stem
        cand: dict = collections.defaultdict(list)
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("#") or line.startswith("surface"):
                    continue
                p = line.rstrip("\n").split("\t")
                if len(p) < 4:
                    continue
                surface, strong = p[0].strip(), p[1].strip()
                if strong not in proper or not surface:
                    continue
                try:
                    count, share = int(p[2]), float(p[3])
                except ValueError:
                    continue
                if count >= MIN_COUNT and share >= MIN_SHARE:
                    cand[strong].append((surface, share, count))
        for strong, rows in cand.items():
            by[strong][lang] = sorted(rows, key=lambda r: -r[1])[:TOPK]
    return by


def build():
    proper = proper_strongs()
    gloss_by, translit = _load_glosses(proper)
    aligned_by = _load_aligned(proper)
    print(f"[proper-nouns] {len(proper)} name Strong's · "
          f"{len(gloss_by)} with a gloss · {len(aligned_by)} with aligned surfaces", file=sys.stderr)

    rows = []
    for strong in sorted(proper):
        tr = translit.get(strong, "")
        seen: set = set()                                  # (lang, surface) dedup across sources
        for lang, names in gloss_by.get(strong, {}).items():
            for name in names:
                if (lang, name) not in seen:
                    seen.add((lang, name))
                    rows.append((strong, tr, lang, name, "gloss", 1.0))
        for lang, surfs in aligned_by.get(strong, {}).items():
            for surface, share, _c in surfs:
                if (lang, surface) not in seen:
                    seen.add((lang, surface))
                    rows.append((strong, tr, lang, surface, "aligned", round(share, 3)))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "proper_nouns.tsv").open("w", encoding="utf-8") as fh:
        fh.write("# Proper-noun lexicon (roadmap N1): biblical name Strong's -> localized renderings; "
                 "shoresh macula.build_proper_nouns. OT/Hebrew (STEPBible Np); NT Greek needs TIPNR.\n")
        fh.write("strong\ttranslit\tlang\tsurface\tsource\tweight\n")
        for strong, tr, lang, surface, src, w in rows:
            fh.write(f"{strong}\t{tr}\t{lang}\t{surface}\t{src}\t{w}\n")

    langs = sorted({r[2] for r in rows})
    covered = len({r[0] for r in rows})
    print(f"[proper-nouns] {len(rows)} renderings · {covered} names · {len(langs)} langs "
          f"({', '.join(langs)}) -> {OUT_DIR/'proper_nouns.tsv'}", file=sys.stderr)
    return rows


if __name__ == "__main__":
    build()
