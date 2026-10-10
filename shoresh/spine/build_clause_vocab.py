#!/usr/bin/env python3
"""Rebuild psalm_superscription_clauses.tsv from MACULA (CC BY 4.0): the Strong's numbers of the content words in the title of each of the 52 Psalms whose title is part of
Hebrew verse 1 (e.g. Psalm 23: "A psalm of David"). The title extent is macula/psalm_title_spans.tsv (TVTMS + MACULA lowfat clauses, Hebrew only); the numbers come from
lexeme-spine-macula.db. Replaces the earlier table that was extracted from the BHSA clause segmentation (non-commercial), which cut some titles short (it left David out of
8 titles and mizmor out of 7). spine/superscriptions.py reads it as a set of Strong's numbers per chapter.

  cd shoresh && python -m spine.build_clause_vocab
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHORESH = HERE.parent
OUT = HERE / "psalm_superscription_clauses.tsv"


def main() -> int:
    chapters = [int(r["chapter"]) for r in csv.DictReader(OUT.open(encoding="utf-8"), delimiter="\t")]          # the 52 merged-title psalms
    spans = {}
    with (SHORESH / "macula" / "psalm_title_spans.tsv").open(encoding="utf-8") as fh:
        rows = [ln.rstrip("\n").split("\t") for ln in fh if not ln.startswith("#")]
    hdr = rows[0]
    for r in rows[1:]:
        d = dict(zip(hdr, r))
        spans[int(d["chapter"])] = (d["first_key"], d["last_key"])
    con = sqlite3.connect(f"file:{SHORESH / 'macula' / 'lexeme-spine-macula.db'}?mode=ro", uri=True)
    lines = ["chapter\tstrong_sequence"]
    for ch in chapters:
        k1, k2 = spans[ch]
        strongs = sorted({int(s) for (s,) in con.execute(
            "SELECT strong FROM spine_words WHERE key>=? AND key<=? AND strong IS NOT NULL AND is_content=1 AND lexeme LIKE 'hbo:%'", (k1, k2))})
        lines.append(f"{ch}\t" + ",".join(f"H{s:04d}" for s in strongs))
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(chapters)} psalms -> {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
