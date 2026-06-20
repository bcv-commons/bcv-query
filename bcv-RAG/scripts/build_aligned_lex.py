#!/usr/bin/env python3
"""A2 (Tier-2): emit a target-language surface→Strong's lexicon from a
manually word-aligned Bible (Clear-Bible/Alignments), with corpus frequency.

This is the high-confidence complement to the Tier-1 LLM glosses: instead of
asking a model for one word per code, it reads how a real, human-aligned
translation actually renders each original-language word across the whole
corpus. Surface forms are grounded in usage (e.g. es 'amor'→G0026 agapē,
'amó'→G0025 agapaō), and counts let the runtime drop spurious 1-off alignments.

Provenance: source=aligned (manual word alignment). Generic over language +
version — reusable for every target in the Alignments repo (arb, fra, por, …).

Output: aligned_lex/<lang>.tsv  (surface, strong, count, share)
  share = this code's fraction of all alignments for the surface form, so the
  runtime can keep the dominant sense(s) and ignore the noise tail.
  Aggregated across ALL aligned versions found for the language.

This module is the single-language core; scripts/build_aligned_all.py fetches
the release assets and drives it over every available language.

Requires a local clone/extract of github.com/Clear-Bible/Alignments. Point
--data-dir at its `data/` directory.
Usage: python3 scripts/build_aligned_lex.py spa --data-dir /path/to/Alignments/data
       python3 scripts/build_aligned_lex.py spa --data-dir … --version RV09
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from ingest.clear_aligned import read_aligned  # noqa: E402

OUT_DIR = HERE.parent / "resources" / "aligned_lex"

_WORD = re.compile(r"\w", re.UNICODE)


def discover_versions(data_dir: str | Path, lang_iso: str) -> list[str]:
    """Aligned versions present for a language (dir names under alignments/)."""
    p = Path(data_dir) / lang_iso / "alignments"
    if not p.exists():
        return []
    return sorted(d.name for d in p.iterdir() if d.is_dir())


def emit_lexicon(data_dir: str | Path, lang_iso: str, versions: list[str],
                 out_path: str | Path, min_count: int = 1) -> dict:
    """Aggregate surface→Strong's across versions → write one TSV. Returns stats."""
    pairs: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    verses = 0
    for version in versions:
        for v in read_aligned(data_dir, lang_iso, version):
            verses += 1
            for t in v["tokens"]:
                s = (t["surface"] or "").strip().lower()
                if t["strong"] and _WORD.search(s):       # skip punctuation-only
                    pairs[s][t["strong"]] += 1

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    codes: set[str] = set()
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write(f"# source=aligned; {lang_iso}/{'+'.join(versions)} via "
                 f"Clear-Bible/Alignments manual word alignment\n")
        fh.write("surface\tstrong\tcount\tshare\n")
        for surf in sorted(pairs):
            total = sum(pairs[surf].values())
            for strong, cnt in sorted(pairs[surf].items(), key=lambda x: -x[1]):
                if cnt < min_count:
                    continue
                fh.write(f"{surf}\t{strong}\t{cnt}\t{cnt/total:.3f}\n")
                rows += 1
                codes.add(strong)
    return {"verses": verses, "surfaces": len(pairs), "rows": rows,
            "codes": len(codes), "versions": versions, "out": str(out_path)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("lang", help="ISO-639-3 language dir name (e.g. spa, fra)")
    ap.add_argument("--data-dir", required=True,
                    help="path to the Alignments repo's data/ directory")
    ap.add_argument("--version", action="append",
                    help="restrict to version(s); default = all aligned versions")
    ap.add_argument("--min-count", type=int, default=1)
    ap.add_argument("--out", help="override output path")
    args = ap.parse_args()

    versions = args.version or discover_versions(args.data_dir, args.lang)
    if not versions:
        print(f"no aligned versions for {args.lang} under {args.data_dir}",
              file=sys.stderr)
        sys.exit(1)
    out = args.out or OUT_DIR / f"{args.lang}.tsv"
    st = emit_lexicon(args.data_dir, args.lang, versions, out, args.min_count)
    print(f"{args.lang}/{'+'.join(versions)}: {st['verses']} verses → "
          f"{st['surfaces']} surfaces, {st['rows']} rows, {st['codes']} codes "
          f"→ {st['out']}", file=sys.stderr)


if __name__ == "__main__":
    main()
