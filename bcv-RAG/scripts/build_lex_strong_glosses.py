#!/usr/bin/env python3
"""Bridge lexeme-keyed target-language glosses → Strong's-keyed glosses.

The trainer's gloss sets (resources/word_glosses/<src>/<Lang>.csv) are keyed by the
BHSA `lex`; the RAG/study layer is keyed by Strong's. The lex→Strong's bridge
(resources/word_freq/<src>_strong.tsv) connects them — so one gloss set can serve BOTH
worlds. This emits a Strong's-keyed copy of a language's glosses.

  python scripts/build_lex_strong_glosses.py hbo Danish dan

Output: resources/word_glosses/strong_keyed/<lang3>.tsv  (columns: strong, gloss)
  Representative gloss per lexeme = `default`, else the first non-empty column (the
  stem-agnostic citation form — Strong's has no stem context). When several lexemes map
  to one Strong's, the longest gloss wins.

To serve these in the RAG/study layer, append them to strongs_gloss.tsv as
`strong<TAB>gloss<TAB><translit><TAB><lang3>` rows (or load as a supplement).
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LANG3 = {"Danish": "dan", "English": "eng"}   # extend as languages are added


def _representative(row: dict, gloss_cols: list[str]) -> str:
    """default, else the first non-empty column (citation form, stem-agnostic)."""
    if row.get("default"):
        return row["default"]
    for c in gloss_cols:
        if row.get(c):
            return row[c]
    return ""


def build(src: str, lang: str, lang3: str | None = None) -> None:
    lang3 = lang3 or LANG3.get(lang, lang[:3].lower())
    csv_path = ROOT / "resources" / "word_glosses" / src / f"{lang}.csv"
    bridge_path = ROOT / "resources" / "word_freq" / f"{src}_strong.tsv"
    if not csv_path.exists() or not bridge_path.exists():
        sys.exit(f"need {csv_path} and {bridge_path}")

    lex_to_strong: dict[str, str] = {}
    with bridge_path.open(encoding="utf-8") as fh:
        next(fh, None)
        for line in fh:
            lex, strong = line.rstrip("\n").split("\t")
            lex_to_strong[lex] = strong

    by_strong: dict[str, str] = {}
    glossed = bridged = 0
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = [c.strip() for c in next(reader)]
        lex_i = header.index("lex")
        gloss_cols = [c for i, c in enumerate(header) if c and i != lex_i and c != "default"]
        for r in reader:
            if len(r) <= lex_i or not r[lex_i].strip():
                continue
            row = {header[i]: (r[i].strip() if i < len(r) else "") for i in range(len(header))}
            gloss = _representative(row, gloss_cols)
            if not gloss:
                continue
            glossed += 1
            strong = lex_to_strong.get(r[lex_i].strip())
            if not strong:
                continue
            bridged += 1
            # longest gloss wins when several lexemes share a Strong's
            if strong not in by_strong or len(gloss) > len(by_strong[strong]):
                by_strong[strong] = gloss

    out_dir = ROOT / "resources" / "word_glosses" / "strong_keyed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{lang3}.tsv"
    with out.open("w", encoding="utf-8") as fh:
        fh.write("strong\tgloss\n")
        for strong in sorted(by_strong):
            fh.write(f"{strong}\t{by_strong[strong]}\n")

    print(f"{lang} ({lang3}): {glossed} glossed lexemes, {bridged} bridged → "
          f"{len(by_strong)} Strong's codes → {out.relative_to(ROOT)}", file=sys.stderr)


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 2:
        sys.exit("usage: build_lex_strong_glosses.py <src> <Language> [lang3]")
    build(args[0], args[1], args[2] if len(args) > 2 else None)
