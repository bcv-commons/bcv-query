#!/usr/bin/env python3
"""Add a BibleOL gloss language to the Strong's-keyed store (strongs_gloss.tsv) for the
RAG/study layer — the generalized version of build_danish_strongs_gloss.py.

  python scripts/build_bibleol_strongs_gloss.py                    # all BibleOL languages
  python scripts/build_bibleol_strongs_gloss.py German de deu      # just one

Hebrew/Aramaic: bridge the lex-keyed trainer glosses (word_glosses/hbo/<Language>.csv)
to Strong's via word_freq/hbo_strong.tsv (representative gloss = default else first real
column; placeholders skipped). Greek: read the natively-Strong's-keyed greek_<suffix>.csv
(if present). Merge as lang=<lang3>; idempotent (drops existing <lang3> rows first).
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
STORE = ROOT / "resources" / "strongs_gloss.tsv"
_PLACEHOLDER = re.compile(r"^[A-ZÆØÅ]{2,}$")   # ART / ZH / UKENDT — non-answerable labels


def _real(v: str | None) -> str:
    v = (v or "").strip()
    return "" if (not v or v == "-" or _PLACEHOLDER.match(v)) else v


def _hebrew(language: str) -> dict[str, str]:
    bridge: dict[str, str] = {}
    with (ROOT / "resources/word_freq/hbo_strong.tsv").open(encoding="utf-8") as fh:
        next(fh, None)
        for line in fh:
            lex, strong = line.rstrip("\n").split("\t")
            bridge[lex] = strong
    csvp = ROOT / "resources/word_glosses/hbo" / f"{language}.csv"
    out: dict[str, str] = {}
    if not csvp.exists():
        return out
    with csvp.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        cols = [c.strip() for c in next(reader)]
        lex_i = cols.index("lex")
        di = cols.index("default") if "default" in cols else -1
        gloss_idx = [i for i, c in enumerate(cols) if c and i != lex_i]
        for r in reader:
            lex = r[lex_i].strip() if lex_i < len(r) else ""
            strong = bridge.get(lex)
            if not strong:
                continue
            g = _real(r[di]) if 0 <= di < len(r) else ""
            if not g:
                for i in gloss_idx:
                    g = _real(r[i] if i < len(r) else "")
                    if g:
                        break
            if g and (strong not in out or len(g) > len(out[strong])):
                out[strong] = g
    return out


def _greek(suffix: str) -> dict[str, str]:
    gp = ROOT / "example/BibleOL/lexicons" / f"greek_{suffix}.csv"
    out: dict[str, str] = {}
    if not gp.exists():
        return out
    with gp.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        next(reader, None)
        for r in reader:
            if len(r) < 5 or r[3].strip().lower() == "yes":
                continue
            g = _real(r[4])
            if not g:
                continue
            try:
                out[f"G{int(r[2]):04d}"] = g
            except ValueError:
                pass
    return out


# BibleOL gloss languages → (Language file stem, greek_<suffix>, ISO-639-3 lang code).
LANGS = [("Danish", "da", "dan"), ("German", "de", "deu"), ("Dutch", "nl", "nld"),
         ("Swahili", "sw", "swa"), ("Amharic", "am", "amh")]


def one(language: str, suffix: str, lang3: str) -> None:
    glosses = {**_hebrew(language), **_greek(suffix)}
    kept = [ln for ln in STORE.read_text(encoding="utf-8").splitlines()
            if not ln.endswith(f"\t{lang3}")]
    with STORE.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(kept) + "\n")
        for strong in sorted(glosses):
            fh.write(f"{strong}\t{glosses[strong]}\t\t{lang3}\n")
    h = sum(1 for s in glosses if s.startswith("H"))
    g = sum(1 for s in glosses if s.startswith("G"))
    print(f"strongs_gloss.tsv += {len(glosses)} {lang3} rows (H={h}, G={g})", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) >= 4:
        one(sys.argv[1], sys.argv[2], sys.argv[3])
    else:
        for lang, suf, code in LANGS:
            one(lang, suf, code)
