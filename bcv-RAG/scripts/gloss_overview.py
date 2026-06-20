#!/usr/bin/env python3
"""Generate the all-languages-at-a-glance gloss overview + a coverage summary.

A GENERATED view (not a source of truth) over the gloss layer:
  - authoritative UBS glosses   (strongs_gloss.tsv, all langs)
  - LLM gap-fills               (glosses_llm/<lang>.tsv, source=llm)

Outputs:
  glosses_overview.tsv  — wide: strong, lemma, en, es, fr, …  (one column per
                          language; LLM-filled cells marked with a trailing '*').
                          Glance-able for a handful of languages; pass --langs to
                          focus a subset once there are many.
  stderr summary        — per-language coverage (UBS / LLM / union / % of the
                          English universe) + gaps. This is the *scalable* glance
                          when languages reach the hundreds.

Regenerate after adding a language or running build_llm_glosses.py.
Usage: python3 scripts/gloss_overview.py [--langs es,fr,pt]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
GLOSS = HERE.parent / "resources" / "strongs_gloss.tsv"
LEMMA = HERE / "strong_lemma.tsv"
LLM_DIR = HERE.parent / "resources" / "llm_strongs_glosses"
OUT = HERE / "glosses_overview.tsv"


def main() -> None:
    want = None
    for a in sys.argv[1:]:
        if a.startswith("--langs"):
            want = set((a.split("=", 1)[1] if "=" in a else sys.argv[sys.argv.index(a) + 1]).split(","))

    # authoritative UBS glosses per language; en is the universe
    ubs: dict[str, dict[str, str]] = {}
    en_codes: list[str] = []
    with GLOSS.open(encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 4 and p[1]:
                ubs.setdefault(p[3], {})[p[0]] = p[1]
    en_codes = sorted(ubs.get("eng", {}), key=lambda c: (c[0], int(re.sub(r"\D", "", c[1:5] or "0"))))

    # LLM gap-fills per language
    llm: dict[str, dict[str, str]] = {}
    if LLM_DIR.exists():
        for f in sorted(LLM_DIR.glob("*.tsv")):
            lang = f.stem
            d: dict[str, str] = {}
            with f.open(encoding="utf-8") as fh:
                header = None
                for line in fh:
                    if line.startswith("#"):
                        continue
                    parts = line.rstrip("\n").split("\t")
                    if header is None:
                        header = parts
                        si = header.index("strong"); gi = header.index("gloss")
                        continue
                    if len(parts) > max(si, gi):
                        d[parts[si]] = parts[gi]
            llm[lang] = d

    lemma: dict[str, str] = {}
    if LEMMA.exists():
        with LEMMA.open(encoding="utf-8") as fh:
            next(fh)
            for line in fh:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 3:
                    lemma[p[0]] = p[2]

    langs = sorted(set(ubs) | set(llm))
    if want:
        langs = [l for l in langs if l in want]
    langs = (["eng"] if "eng" in langs else []) + [l for l in langs if l != "eng"]

    # wide overview
    with OUT.open("w", encoding="utf-8") as fh:
        fh.write("strong\tlemma\t" + "\t".join(langs) + "\n")
        for c in en_codes:
            cells = []
            for l in langs:
                g = ubs.get(l, {}).get(c, "")
                if not g and c in llm.get(l, {}):
                    g = llm[l][c] + " *"        # LLM-filled
                cells.append(g)
            fh.write(f"{c}\t{lemma.get(c,'')}\t" + "\t".join(cells) + "\n")

    # coverage summary (the scalable glance)
    total = len(en_codes)
    print(f"\nGloss coverage over {total} English-universe codes "
          f"('*' = LLM gap-fill; → {OUT.name})\n", file=sys.stderr)
    print(f"  {'lang':8} {'UBS':>7} {'LLM':>7} {'union':>7} {'cover%':>7}  gaps", file=sys.stderr)
    for l in langs:
        u = set(ubs.get(l, {}))
        m = set(llm.get(l, {}))
        union = (u | m) & set(en_codes)
        cov = 100 * len(union) / total if total else 0
        print(f"  {l:8} {len(u & set(en_codes)):>7} {len(m):>7} {len(union):>7} "
              f"{cov:>6.1f}%  {total - len(union)}", file=sys.stderr)


if __name__ == "__main__":
    main()
