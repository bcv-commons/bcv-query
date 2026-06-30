#!/usr/bin/env python3
"""Ingest BibleOL's Greek Danish lexicon → a lemma-keyed grc gloss file for /words.

BibleOL's `greek_da.csv` is keyed by Strong's number (with a single Danish gloss per
lemma, no verbal-stem split). /words for Greek keys glosses by `lex` (the Nestle1904
lemma). Direct lemma matching is poor (~13%, accent/form drift), but Strong's bridges
cleanly (~99%) — so map each Strong's → its Nestle1904 lemma(s) via word_freq/grc_strong.tsv
and emit a `lex,default` file.

  python scripts/ingest_bibleol_greek_glosses.py [path/to/greek_da.csv]

Source CSV columns: Occurrences, Lexeme, "Strong's number", "Strong's unreliable?", Gloss.
Rows flagged Strong's-unreliable are skipped (the Strong's join would be untrustworthy).
Output: resources/word_glosses/grc/Danish.csv  (lex, default)

NOTE: the source lives in the git-ignored example/ (local only); the committed OUTPUT is
the served artifact. Re-run locally if BibleOL updates. Confirm the lexicon licence
(BibleOL techdoc ch.7) before redistributing.
"""
from __future__ import annotations

import collections
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "example/BibleOL/lexicons/greek_da.csv"
BRIDGE = ROOT / "resources/word_freq/grc_strong.tsv"   # Nestle1904 lemma → Strong's
OUT = ROOT / "resources/word_glosses/grc/Danish.csv"


def main() -> None:
    if not SRC.exists() or not BRIDGE.exists():
        sys.exit(f"need {SRC} and {BRIDGE}")

    strong_to_lemmas: dict[str, list[str]] = collections.defaultdict(list)
    with BRIDGE.open(encoding="utf-8") as fh:
        next(fh, None)
        for line in fh:
            lemma, strong = line.rstrip("\n").split("\t")
            strong_to_lemmas[strong].append(lemma)

    lemma_gloss: dict[str, str] = {}
    seen = bridged = skipped = 0
    with SRC.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # header
        for r in reader:
            if len(r) < 5:
                continue
            _occ, _lexeme, strong_num, unreliable, gloss = r[0], r[1], r[2], r[3], r[4]
            gloss = gloss.strip()
            if not gloss:
                continue
            seen += 1
            if unreliable.strip().lower() == "yes":
                skipped += 1
                continue
            try:
                strong = f"G{int(strong_num):04d}"
            except ValueError:
                continue
            lemmas = strong_to_lemmas.get(strong)
            if not lemmas:
                continue
            bridged += 1
            for lem in lemmas:           # a Strong's may have several lemma forms
                lemma_gloss[lem] = gloss

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["lex", "default"])
        for lem in sorted(lemma_gloss):
            w.writerow([lem, lemma_gloss[lem]])

    print(f"greek_da: {seen} glossed, {skipped} skipped (unreliable Strong's), {bridged} "
          f"bridged → {len(lemma_gloss)} lemmas → {OUT.relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    main()
