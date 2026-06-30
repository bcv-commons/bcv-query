#!/usr/bin/env python3
"""Convert Strong's-keyed glosses → the lex-keyed /words trainer format.

The inverse of the Strong's-anchored world feeding the trainer. Any Strong's-keyed
gloss source (an LLM batch slice, resources/word_glosses/strong_keyed/<lang3>.tsv, …)
maps to BHSA/Nestle1904 lexemes via the lex→Strong's bridge (word_freq/<src>_strong.tsv,
read in reverse) and is written as a `/words` gloss CSV.

  python scripts/build_lex_glosses_from_strong.py <src> <Language> <strong_gloss_file>
    <src>               hbo | grc
    <strong_gloss_file>  TSV/CSV with columns: strong, gloss   (header optional)

MERGE = gap-fill. An existing word_glosses/<src>/<Language>.csv is preserved exactly —
curated per-stem entries (Hebrew) are NEVER overwritten; only lexemes that have no gloss
yet are filled (single `default`). Strong's has no verbal-stem dimension, so this can
only ever add a stem-agnostic gloss — which is why it's gap-fill, not replace.
"""
from __future__ import annotations

import collections
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _read_strong_glosses(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        sample = fh.readline()
        delim = "\t" if "\t" in sample else ","
        fh.seek(0)
        reader = csv.reader(fh, delimiter=delim)
        for row in reader:
            if len(row) < 2:
                continue
            strong, gloss = row[0].strip(), row[1].strip()
            if strong.lower() == "strong" or not strong or not gloss:
                continue   # header or empty
            out[strong] = gloss
    return out


def build(src: str, lang: str, strong_file: str) -> None:
    bridge_path = ROOT / "resources" / "word_freq" / f"{src}_strong.tsv"
    out_path = ROOT / "resources" / "word_glosses" / src / f"{lang}.csv"
    sg = _read_strong_glosses(Path(strong_file))
    if not bridge_path.exists():
        sys.exit(f"need {bridge_path}")

    strong_to_lex: dict[str, list[str]] = collections.defaultdict(list)
    with bridge_path.open(encoding="utf-8") as fh:
        next(fh, None)
        for line in fh:
            lex, strong = line.rstrip("\n").split("\t")
            strong_to_lex[strong].append(lex)

    # Existing CSV — preserve header + every row; track which lexemes already have a gloss.
    header = ["lex", "default"]
    rows: dict[str, dict] = {}
    glossed: set[str] = set()
    if out_path.exists():
        with out_path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            cols = [c.strip() for c in next(reader)]
            header = [c for c in cols if c]                       # drop unnamed index col
            lex_i = cols.index("lex")
            gloss_cols = [c for i, c in enumerate(cols) if c and i != lex_i]
            for r in reader:
                if len(r) <= lex_i or not r[lex_i].strip():
                    continue
                lx = r[lex_i].strip()
                rows[lx] = {cols[i]: (r[i].strip() if i < len(r) else "") for i in range(len(cols)) if cols[i]}
                if any(rows[lx].get(c) for c in gloss_cols):
                    glossed.add(lx)

    added = 0
    for strong, gloss in sg.items():
        for lex in strong_to_lex.get(strong, []):
            if lex in glossed:
                continue                                          # never overwrite curated
            row = rows.setdefault(lex, {c: "" for c in header})
            row["lex"] = lex
            row["default"] = gloss
            glossed.add(lex)
            added += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for lex in sorted(rows):
            w.writerow([rows[lex].get(c, "") for c in header])

    print(f"{lang}/{src}: {len(sg)} strong glosses, gap-filled {added} lexemes → "
          f"{len(glossed)} glossed total → {out_path.relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit("usage: build_lex_glosses_from_strong.py <hbo|grc> <Language> <strong_gloss_file>")
    build(sys.argv[1], sys.argv[2], sys.argv[3])
