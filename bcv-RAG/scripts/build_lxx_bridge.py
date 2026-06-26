"""Precompute the Hebrew→Greek LXX bridge into a local table.

Strategy 2 (query/lxx_expand.py) used to hit shoresh `/bridge/{H}` per Hebrew tag
at query time; we materialize the bridge once here into resources/lxx_bridge.tsv
and let expand_lxx read it locally (zero network on the hot path).

SOURCE (2026-06-26): the per-occurrence **`greekstrong`** column of MACULA Hebrew
(`Clear-Bible/macula-hebrew`, WLC TSV). This is a *curated* Hebrew→Greek alignment
and is dramatically cleaner than the positional `/bridge` computation it replaces
(e.g. H2617 chesed → G1656 eleos ×142, no G2962/Lord or G4160/do noise). CC BY 4.0
(Biblica) + UBS MARBLE attribution. No shoresh dependency anymore.

Output TSV columns: hebrew_strong<TAB>greek_strong<TAB>count
(zero-padded codes, e.g. H0430 / G1656; top GREEK_PER_HEBREW greek per hebrew,
each with count >= MIN_GREEK_COUNT; sorted by hebrew then count desc).

Usage:
    # download the 84 MB Git-LFS TSV and build:
    python -m scripts.build_lxx_bridge --out resources/lxx_bridge.tsv
    # or reuse a cached copy:
    python -m scripts.build_lxx_bridge --tsv /tmp/macula-hebrew.tsv
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import re
import sys
from pathlib import Path

import httpx

# Git-LFS content is served from the media endpoint (raw gives a pointer).
MACULA_HEBREW_TSV = ("https://media.githubusercontent.com/media/"
                     "Clear-Bible/macula-hebrew/main/WLC/tsv/macula-hebrew.tsv")
GREEK_PER_HEBREW = 4
MIN_GREEK_COUNT = 3


def _hnorm(s: str) -> str | None:
    m = re.match(r"(\d+)", s.strip())          # drop homonym suffix (0871a -> 0871)
    return f"H{int(m.group(1)):04d}" if m else None


def _gnorm(s: str) -> str | None:
    s = s.strip()
    m = re.match(r"(\d+)", s)
    return f"G{int(m.group(1)):04d}" if (s and m) else None


def _rows(tsv: str | None) -> io.StringIO | io.TextIOBase:
    if tsv:
        return open(tsv, encoding="utf-8")
    print(f"downloading {MACULA_HEBREW_TSV} …", file=sys.stderr)
    r = httpx.get(MACULA_HEBREW_TSV, timeout=300.0, follow_redirects=True)
    r.raise_for_status()
    return io.StringIO(r.text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="resources/lxx_bridge.tsv")
    ap.add_argument("--tsv", default="", help="cached macula-hebrew TSV (else download)")
    args = ap.parse_args()

    gk: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    n_rows = n_pairs = 0
    fh = _rows(args.tsv or None)
    try:
        for row in csv.DictReader(fh, delimiter="\t"):
            n_rows += 1
            h = _hnorm(row.get("strongnumberx") or "")
            g = _gnorm(row.get("greekstrong") or "")
            if h and g:
                gk[h][g] += 1
                n_pairs += 1
    finally:
        fh.close()

    out = Path(args.out)
    n_codes = n_written = 0
    with out.open("w", encoding="utf-8") as f:
        f.write("hebrew_strong\tgreek_strong\tcount\n")
        for h in sorted(gk):
            kept = [(g, c) for g, c in gk[h].most_common() if c >= MIN_GREEK_COUNT][:GREEK_PER_HEBREW]
            if not kept:
                continue
            n_codes += 1
            for g, c in kept:
                f.write(f"{h}\t{g}\t{c}\n")
                n_written += 1
    print(f"scanned {n_rows} word rows, {n_pairs} H→G occurrences")
    print(f"wrote {out}: {n_codes} hebrew codes, {n_written} bridge pairs")


if __name__ == "__main__":
    main()
