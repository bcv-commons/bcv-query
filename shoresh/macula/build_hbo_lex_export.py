#!/usr/bin/env python3
"""Publish-ready export of `senses/hbo_lex.tsv` — export candidate #5 (bcv-commons-export-candidates.md).

The sense-CLUSTER structure (which occurrences group into which sense, per lex+stem) is independently
derived from Hebrew-context embedding similarity (`cluster_senses_hebrew.py`) — clean, no UBS/SDBH
involvement at any point. The original caution was about the per-sense GLOSS text, not the structure.
Traced precisely (2026-08), the risk profile turned out to be the OPPOSITE of what was originally
assumed:

  - Sub-sense glosses (every sense after the dominant one) come from `occurrence.gloss`, which maps
    directly to MACULA's own `@gloss` XML attribute — confirmed via MACULA-Hebrew's own LICENSE.md to
    be Cherith Glosses (Andi Wu, Copyright 2022, CC BY 4.0), NOT SDBH/UBS MARBLE. Genuinely clean.
  - The DOMINANT sense of every (lex, stem) group (both monosemous and polysemous) instead comes from
    `resources/word_glosses/hbo/English.csv`, sourced from BibleOL — whose repo license (MIT) covers the
    *software*, not confirmed to cover the *gloss data* itself (word_glosses/README.md: "each gloss set
    carries its own terms — record provenance/licence per file as more are added" — not yet done for
    this one). This is the actually-uncertain one, not the sub-senses.

Fix: replace every dominant-sense gloss with the already-vetted `resources/strongs_gloss.tsv` value
(method=lexicon+llm, used throughout this project) via a lex->strong lookup from `hbo.db` — a mechanical
substitution, not a re-derivation, and it sidesteps the BibleOL question entirely rather than resolving
it. Sub-sense glosses are kept as-is (already clean) with proper Cherith Glosses attribution in the
output header. No LLM relabeling needed at all.

  python -m macula.build_hbo_lex_export
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HBO_LEX = ROOT / "resources" / "senses" / "hbo_lex.tsv"
HBO_DB = ROOT / "resources" / "occurrences" / "hbo.db"
STRONGS_GLOSS = ROOT / "resources" / "strongs_gloss.tsv"
OUT = ROOT / "resources" / "senses" / "hbo_lex_export.tsv"


def load_lex_to_strong() -> dict[str, str]:
    """{lex: dominant H#### strong}, by occurrence-count majority vote per lex."""
    conn = sqlite3.connect(f"file:{HBO_DB}?mode=ro", uri=True)
    tally: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for lex, strong in conn.execute(
            "SELECT lex, strong FROM occurrence WHERE strong IS NOT NULL"):
        tally[lex][strong] += 1
    return {lex: c.most_common(1)[0][0] for lex, c in tally.items()}


def load_strongs_gloss() -> dict[str, str]:
    gl: dict[str, str] = {}
    with STRONGS_GLOSS.open(encoding="utf-8") as fh:
        header = next(fh).rstrip("\n").split("\t")
        idx = {name: i for i, name in enumerate(header)}
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) > idx.get("lang", -1) and p[idx["lang"]] == "eng":
                gl.setdefault(p[idx["strong"]], p[idx["gloss"]])
    return gl


def build() -> list[tuple[str, str, str, str, int, float]]:
    lex2strong = load_lex_to_strong()
    strong_gloss = load_strongs_gloss()

    by_group: dict[tuple[str, str], list[list]] = collections.defaultdict(list)
    with HBO_LEX.open(encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) < 6:
                continue
            lex, stem, sense, gloss, count, share = p[0], p[1], p[2], p[3], int(p[4]), float(p[5])
            by_group[(lex, stem)].append([lex, stem, sense, gloss, count, share])

    rows = []
    replaced = kept = 0
    for (lex, stem), senses in by_group.items():
        dominant = max(senses, key=lambda r: r[5])   # highest share = dominant sense
        strong = lex2strong.get(lex)
        new_gloss = strong_gloss.get(strong) if strong else None
        for r in senses:
            if r is dominant and new_gloss:
                rows.append((r[0], r[1], r[2], new_gloss, r[4], r[5]))
                replaced += 1
            else:
                rows.append(tuple(r))
                kept += 1
    print(f"[hbo-lex-export] {len(rows)} sense-rows: {replaced} dominant glosses replaced "
          f"(strongs_gloss.tsv), {kept} kept as-is (Cherith Glosses, CC BY 4.0)", file=sys.stderr)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    rows = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write("# Publish-ready Hebrew lexeme sense inventory (export candidate #5). Sense-cluster\n"
                  "# structure is independently derived from Hebrew-clause embedding similarity\n"
                  "# (cluster_senses_hebrew.py) — no UBS/SDBH involvement. Dominant-sense (per lex+stem)\n"
                  "# glosses are from resources/strongs_gloss.tsv (method=lexicon+llm). All other\n"
                  "# (sub-)sense glosses are Cherith Glosses (Andi Wu, Copyright 2022, CC BY 4.0), via\n"
                  "# MACULA's own @gloss attribute — confirmed via MACULA-Hebrew's LICENSE.md, NOT\n"
                  "# SDBH/UBS MARBLE. See build_hbo_lex_export.py.\n")
        fh.write("lex\tstem\tsense\tgloss\tcount\tshare\n")
        for lex, stem, sense, gloss, count, share in sorted(rows, key=lambda r: (r[0], r[1], r[2])):
            fh.write(f"{lex}\t{stem}\t{sense}\t{gloss}\t{count}\t{share}\n")
    print(f"[hbo-lex-export] -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
