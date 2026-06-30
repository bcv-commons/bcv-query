#!/usr/bin/env python3
"""Add Danish to the canonical Strong's-keyed multilingual store (strongs_gloss.tsv).

Wires the Danish glosses into the Strong's-anchored RAG layer (concept_expand reads
strongs_gloss.tsv per language). Sources, both already Strong's-aligned:
  Hebrew → resources/word_glosses/strong_keyed/dan.tsv  (from the lex→Strong's bridge)
  Greek  → example/BibleOL/lexicons/greek_da.csv         (natively Strong's-keyed)

Idempotent: drops any existing lang=dan rows, then appends the merged set as
`strong<TAB>gloss<TAB><TAB>dan`. Run after refreshing either source.

  python scripts/build_danish_strongs_gloss.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
STORE = ROOT / "resources" / "strongs_gloss.tsv"
HEB = ROOT / "resources" / "word_glosses" / "strong_keyed" / "dan.tsv"
GRC = ROOT / "example" / "BibleOL" / "lexicons" / "greek_da.csv"
LANG = "dan"


def _danish_by_strong() -> dict[str, str]:
    out: dict[str, str] = {}
    # Hebrew: already strong-keyed (H####)
    if HEB.exists():
        with HEB.open(encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                strong, gloss = line.rstrip("\n").split("\t")
                if gloss.strip():
                    out[strong] = gloss.strip()
    # Greek: Strong's number (int) + unreliable flag + gloss → G####
    if GRC.exists():
        with GRC.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            next(reader, None)
            for r in reader:
                if len(r) < 5 or r[3].strip().lower() == "yes" or not r[4].strip():
                    continue
                try:
                    out[f"G{int(r[2]):04d}"] = r[4].strip()
                except ValueError:
                    continue
    return out


def main() -> None:
    if not STORE.exists():
        sys.exit(f"need {STORE}")
    danish = _danish_by_strong()

    kept = [ln for ln in STORE.read_text(encoding="utf-8").splitlines()
            if not ln.endswith(f"\t{LANG}")]            # drop old dan rows (idempotent)
    with STORE.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(kept) + "\n")
        for strong in sorted(danish):
            fh.write(f"{strong}\t{danish[strong]}\t\t{LANG}\n")

    heb = sum(1 for s in danish if s.startswith("H"))
    grc = sum(1 for s in danish if s.startswith("G"))
    print(f"strongs_gloss.tsv += {len(danish)} dan rows (H={heb}, G={grc})", file=sys.stderr)


if __name__ == "__main__":
    main()
