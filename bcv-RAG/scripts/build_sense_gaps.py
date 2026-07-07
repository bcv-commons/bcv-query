#!/usr/bin/env python3
"""Extract the multilingual-senses TRANSLATION GAP → resources/senses/senses_i18n/_gaps.tsv.

The DOMINANT sense of each (lex, stem) already localizes for free — shoresh `_lex_senses`
relabels it with the per-stem gloss (word_glosses/, 12 languages). What stays English is the
NON-dominant (polysemous sub-) senses. This lists exactly those, so translating them is a
matter of filling a per-language file, not re-deriving anything.

Output `_gaps.tsv` (the canonical worklist): lex · stem · sense · en_gloss · share
To localize a language, copy the gaps into `senses_i18n/<iso639-3>.tsv` (same key columns +
a translated `gloss`); shoresh reads it via `_sense_i18n`. Single-sense (lex,stem) are NOT
listed — they're already covered by the dominant-sense reuse.

  python -m scripts.build_sense_gaps
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "resources" / "senses" / "hbo_lex.tsv"
OUT = ROOT / "resources" / "senses" / "senses_i18n"


def build() -> None:
    by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    with SRC.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            by_key[(r["lex"], r["stem"])].append(r)

    gaps = []
    for (lex, stem), senses in by_key.items():
        if len(senses) < 2:
            continue                                   # single sense → dominant reuse covers it
        ordered = sorted(senses, key=lambda s: -float(s["share"]))
        for s in ordered[1:]:                          # skip the dominant (index 0)
            gaps.append((lex, stem, s["sense"], s["gloss"], s["share"]))
    gaps.sort()

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "_gaps.tsv").open("w", encoding="utf-8", newline="") as fh:
        fh.write("# non-dominant (polysemous) senses needing translation per language; the "
                 "dominant sense of each (lex,stem) localizes for free via the per-stem gloss\n")
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["lex", "stem", "sense", "en_gloss", "share"])
        w.writerows(gaps)

    print(f"senses_i18n/_gaps.tsv: {len(gaps)} non-dominant senses "
          f"across {len({(g[0], g[1]) for g in gaps})} polysemous (lex,stem)", file=sys.stderr)


if __name__ == "__main__":
    build()
    raise SystemExit(0)
