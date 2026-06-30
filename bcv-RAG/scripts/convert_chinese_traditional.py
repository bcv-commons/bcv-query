#!/usr/bin/env python3
"""Fill Chinese-Traditional per-stem glosses from Chinese-Simplified (Hans→Hant, OpenCC),
WITHOUT overwriting existing content, and REPORT every difference it finds.

We already have Chinese-Traditional at the `default` level (from the cmn-Hant gloss source);
it just lacks per-stem cells. This converts Chinese-Simplified's per-stem cells s2t and adds
them. For any cell that ALREADY exists in Chinese-Traditional, it never overwrites — instead
it compares and reports the difference, categorised so the reason is visible:

  - script-variant : the existing Traditional, converted back to Simplified (t2s), equals the
                     Simplified original → same word, only a script/region variant. Benign.
  - source-differs : it does NOT → the cmn-Hans and cmn-Hant sources chose different words.
                     This is a real disagreement to investigate; it is ALWAYS reported.

Differences are never silently dropped. The full diff is written to a TSV and source-differs
rows are printed.

  python scripts/convert_chinese_traditional.py            # DRY: report diffs, write nothing
  python scripts/convert_chinese_traditional.py --apply    # also add the new per-stem cells

Requires `opencc` (s2t + t2s). Install into your build venv; the script errors clearly if absent.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
WG = ROOT / "resources/word_glosses/hbo"
SRC = WG / "Chinese-Simplified.csv"
DST = WG / "Chinese-Traditional.csv"
DIFF = ROOT / "out/perstem/Chinese-Traditional_diffs.tsv"


def _converters(config):
    """Forward Simplified→Traditional via `config` (default s2tw = Taiwan standard, which
    matches the existing cmn-Hant source best); reverse via t2s for round-trip checks."""
    try:
        import opencc
    except ImportError:
        sys.exit("ERROR: needs `opencc` (Hans↔Hant). Install it into the build venv, e.g.\n"
                 "  bcv-RAG/.venv/bin/python -m pip install opencc")
    return opencc.OpenCC(config).convert, opencc.OpenCC("t2s").convert


def _read(path):
    """{lex: {col: val}}, [cols] — empty if file missing."""
    rows, cols = {}, ["lex", "default"]
    if not path.exists():
        return rows, cols
    with path.open(encoding="utf-8-sig", newline="") as fh:
        r = csv.reader(fh)
        cols = [c.strip() for c in next(r)]
        li = cols.index("lex")
        for row in r:
            if li < len(row) and row[li].strip():
                rows[row[li].strip()] = {cols[i]: (row[i] if i < len(row) else "")
                                         for i in range(len(cols))}
    return rows, cols


def main():
    apply = "--apply" in sys.argv
    config = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--config=")), "s2tw")
    s2t, t2s = _converters(config)
    print(f"  OpenCC config: {config}", file=sys.stderr)
    srows, scols = _read(SRC)
    drows, dcols = _read(DST)
    if not srows:
        sys.exit(f"no source: {SRC}")

    cols = list(dict.fromkeys(dcols + scols))           # union, dst order first
    stem_cols = [c for c in cols if c not in ("", "lex")]
    added = same = script_var = source_diff = 0
    diffs = []                                          # (lex, col, simp, conv, existing, t2s_existing, reason)

    for lex, scells in srows.items():
        for col in stem_cols:
            simp = (scells.get(col) or "").strip()
            if not simp:
                continue
            conv = s2t(simp)                            # Simplified → Traditional
            cur = (drows.get(lex, {}).get(col) or "").strip()
            if not cur:                                 # gap → add the converted value
                if apply:
                    drows.setdefault(lex, {"lex": lex})[col] = conv
                added += 1
            elif cur == conv:
                same += 1
            else:                                       # conflict — NEVER overwrite; report
                back = t2s(cur)
                reason = "script-variant" if back == simp else "source-differs"
                if reason == "script-variant":
                    script_var += 1
                else:
                    source_diff += 1
                diffs.append((lex, col, simp, conv, cur, back, reason))

    # always write the full diff report
    DIFF.parent.mkdir(parents=True, exist_ok=True)
    with DIFF.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["lex", "column", "simplified", "converted_s2t",
                    "existing_traditional", "existing_back_t2s", "reason"])
        w.writerows(diffs)

    print(f"Chinese-Traditional ← Chinese-Simplified (OpenCC s2t):", file=sys.stderr)
    print(f"  per-stem cells to add (empty in Traditional): {added}", file=sys.stderr)
    print(f"  cells identical after conversion:             {same}", file=sys.stderr)
    print(f"  DIFFERENCES (existing kept, reported):        {len(diffs)} "
          f"= {script_var} script-variant + {source_diff} source-differs", file=sys.stderr)
    print(f"  full diff: {DIFF.relative_to(ROOT)}", file=sys.stderr)
    if source_diff:
        print(f"\n  source-differs (cmn-Hans vs cmn-Hant disagree — investigate):", file=sys.stderr)
        for lex, col, simp, conv, cur, back, reason in diffs:
            if reason == "source-differs":
                print(f"    {lex} [{col}]  simp={simp}→{conv}  trad={cur}(→{back})", file=sys.stderr)

    if apply:
        with DST.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            for lex in sorted(drows):
                w.writerow([drows[lex].get(c, "") for c in cols])
        print(f"\n  APPLIED: added {added} cells → {DST.relative_to(ROOT)} "
              f"(existing content untouched).", file=sys.stderr)
    else:
        print(f"\n  DRY RUN — nothing written to {DST.name}. Re-run with --apply to add the "
              f"{added} new cells (differences stay as-is, already reported).", file=sys.stderr)


if __name__ == "__main__":
    main()
