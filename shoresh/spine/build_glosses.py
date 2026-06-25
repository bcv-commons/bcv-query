#!/usr/bin/env python3
"""Build the Strong's -> concise English gloss table for the Lexical prefix line.

Source: STEPBible Translators Brief lexicons (TBESH Hebrew, TBESG Greek),
CC BY — they carry a clean, primary-sense gloss per Strong's (unlike the
1890 Strong's defs, which lead with etymology/qualifiers). Output:
spine/spine_glosses.tsv  (strong, gloss, translit) — spine-scoped English
glosses of the original languages; distinct from bcv-RAG's multilingual
resources/strongs_gloss.tsv.

Usage:  python -m spine.build_glosses
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
OUT = HERE / "spine_glosses.tsv"
BASE = "https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master/Lexicons/"
SRC = {
    "H": BASE + "TBESH%20-%20Translators%20Brief%20lexicon%20of%20Extended%20Strongs%20for%20Hebrew%20-%20STEPBible.org%20CC%20BY.txt",
    "G": BASE + "TBESG%20-%20Translators%20Brief%20lexicon%20of%20Extended%20Strongs%20for%20Greek%20-%20STEPBible.org%20CC%20BY.txt",
}
_LEAD = re.compile(r"^(to be|to|a|an|the)\s+", re.I)


def clean_gloss(g: str) -> str:
    """'to go: went' -> 'go'; 'spirit/breath: spirit' -> 'spirit'; 'God' -> 'God'."""
    g = g.split(":", 1)[0]                 # headword sense, drop the specific rendering
    g = g.split("/", 1)[0]                 # first of alternatives
    g = re.sub(r"^\([^)]*\)\s*", "", g)    # leading (qualifier)
    g = _LEAD.sub("", g).strip().strip("-").strip()
    return g


def main() -> None:
    rows = []
    for prefix in ("H", "G"):
        t = httpx.get(SRC[prefix], timeout=180, follow_redirects=True).text
        seen = set()
        for line in t.splitlines():
            if not re.match(r"^[HG]\d", line):     # data lines only (skip preamble)
                continue
            c = line.split("\t")
            if len(c) < 7:
                continue
            m = re.match(r"([HG])0*(\d+)", c[0])
            if not m:
                continue
            strong = f"{m.group(1)}{int(m.group(2))}"   # H430, G2316 (unpadded)
            if strong in seen:                          # keep the first (primary) sense
                continue
            gloss = clean_gloss(c[6])
            if gloss:
                seen.add(strong)
                rows.append((strong, gloss, c[4] if len(c) > 4 else ""))
        print(f"  {prefix}: {sum(1 for r in rows if r[0][0]==prefix)} glosses", file=sys.stderr)

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("strong\tgloss\ttranslit\n")
        for strong, gloss, xlit in rows:
            f.write(f"{strong}\t{gloss}\t{xlit}\n")
    print(f"{len(rows)} glosses -> {OUT}")


if __name__ == "__main__":
    main()
