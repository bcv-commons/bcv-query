#!/usr/bin/env python3
"""Convert BibleOL Hebrew+Aramaic lexicons → the lex-keyed /words gloss format.

BibleOL ships per-language `heb_<xx>.csv` (+ `aram_<xx>.csv`), keyed by BHSA `lex` with
human-readable stem column names. This renames the columns to BHSA verbal-stem (`vs`)
codes — the values /words returns as `stem` — and MERGES the Aramaic stems into the same
file (Hebrew and Aramaic share the BHSA lex namespace; a word resolves via its own stem).

  python scripts/convert_bibleol_hebrew_glosses.py <Language> <suffix>
    e.g.  convert_bibleol_hebrew_glosses.py German de

Output: resources/word_glosses/hbo/<Language>.csv  (lex, default, <hebrew stems>, <aramaic stems>)
Source lives in the git-ignored example/; the committed output is the served artifact.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LEX = ROOT / "example" / "BibleOL" / "lexicons"

# BibleOL column name → BHSA vs code (the value /words returns as `stem`). `None`=non-verb.
HEB_MAP = {"None": "default", "Qal": "qal", "Nifal": "nif", "Piel": "piel", "Pual": "pual",
           "Hitpael": "hit", "Hifil": "hif", "Hofal": "hof", "Hishtafal": "hsht",
           "Passive Qal": "pasq", "Etpaal": "etpa", "Nitpael": "nit", "Hotpaal": "hotp",
           "Tifal": "tif", "Hitpoal": "htpa", "Poal": "poal", "Poel": "poel"}
ARAM_MAP = {"None": "default", "Peal": "peal", "Peil": "peil", "Pael": "pael",
            "Hafel": "haf", "Afel": "afel", "Shafel": "shaf", "Hofal": "hof",
            "Hitpeel": "htpe", "Hitpaal": "htpa", "Hishtafal": "hsht",
            "Etpeel": "etpe", "Etpaal": "etpa"}
# Output column order: default + Hebrew stems + Aramaic-only stems.
COLS = ["default", "qal", "nif", "piel", "pual", "hit", "hif", "hof", "hsht", "pasq",
        "etpa", "nit", "hotp", "tif", "htpa", "poal", "poel",
        "peal", "peil", "pael", "haf", "afel", "shaf", "htpe", "etpe"]


def _merge(path: Path, colmap: dict, rows: dict[str, dict], default_wins: bool) -> int:
    """Fold one lexicon into rows[lex][code]=gloss. default_wins: don't overwrite an
    existing `default` (Hebrew read first, so its sense wins on a shared lex string)."""
    if not path.exists():
        return 0
    n = 0
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = [h.strip() for h in next(reader)]
        idx = {h: i for i, h in enumerate(header)}
        if "lex" not in idx:
            return 0
        for r in reader:
            lex = r[idx["lex"]].strip() if idx["lex"] < len(r) else ""
            if not lex:
                continue
            row = rows.setdefault(lex, {})
            wrote = False
            for col, code in colmap.items():
                i = idx.get(col)
                val = r[i].strip() if (i is not None and i < len(r)) else ""
                if not val:
                    continue
                if code == "default" and default_wins and row.get("default"):
                    continue
                row[code] = val
                wrote = True
            n += wrote
    return n


def build(language: str, suffix: str) -> None:
    rows: dict[str, dict] = {}
    nh = _merge(LEX / f"heb_{suffix}.csv", HEB_MAP, rows, default_wins=False)
    na = _merge(LEX / f"aram_{suffix}.csv", ARAM_MAP, rows, default_wins=True)
    out = ROOT / "resources" / "word_glosses" / "hbo" / f"{language}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    glossed = 0
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["lex"] + COLS)
        for lex in sorted(rows):
            vals = [rows[lex].get(c, "") for c in COLS]
            if any(vals):
                glossed += 1
            w.writerow([lex] + vals)
    print(f"{language} (hbo): heb {nh} + aram {na} lexicon rows → {glossed} glossed lexemes "
          f"→ {out.relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: convert_bibleol_hebrew_glosses.py <Language> <suffix>")
    build(sys.argv[1], sys.argv[2])
