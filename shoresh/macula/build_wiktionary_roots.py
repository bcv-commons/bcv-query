#!/usr/bin/env python3
"""Wiktionary Hebrew root-category word pairs — a second, independent root-grouping source alongside
BDB (candidate #8). CC BY-SA (Wiktionary text license), community-maintained, bigger than BDB's own
root coverage (2,020 root categories vs. BDB's 1,432 root-groups) but WEAKER per-pair signal on its own
(validated 2026-08: 35.0% SDBH-domain agreement, vs. BDB's 50.6%) — modern-Hebrew-centric root grouping
absorbs post-biblical semantic drift BDB's 1906 biblical-only lexicon doesn't carry.

NOT wired into build_semantic_neighbors.py as a standalone signal for that reason — see
domain-replacement-roadmap.md's "corroborated" tier: this dataset's real value measured so far is as a
SECOND vote alongside xling (agreement jumps to 87.7%), not as an independent source on its own.

Source: kaikki.org's wiktextract JSONL extract of English Wiktionary's Hebrew-language entries (one
JSON object per word, each carrying a `categories` list including "Hebrew terms belonging to the root
X" when applicable). CAVEAT, unlike every other external fetch in this pipeline: kaikki.org's per-
language postprocessed download has no stable per-snapshot URL to pin to (the current file is marked
"deprecated, will be removed" upstream, see https://github.com/tatuylonen/wiktextract/issues/1178) — it
is fetched once and cached; if kaikki.org's URL goes away, re-fetching will fail, but the DERIVED
resources/wiktionary_roots/root_pairs.tsv output stays committed and usable regardless (same "commit
the derived output, not the fragile source" posture as everywhere else in this pipeline).

  python -m macula.build_wiktionary_roots
"""
from __future__ import annotations

import argparse
import collections
import itertools
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine.common import to_modern_form  # noqa: E402
from macula.build_hwn_benchmark import load_bare_to_strongs  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA_DIR = HERE / "data"
OUT_DIR = ROOT / "resources" / "wiktionary_roots"

KAIKKI_URL = "https://kaikki.org/dictionary/Hebrew/kaikki.org-dictionary-Hebrew.jsonl"
KAIKKI_CACHE = DATA_DIR / "kaikki_hebrew.jsonl"
ROOT_CAT_RE = re.compile(r"Hebrew terms belonging to the root (.+)")


def fetch_kaikki() -> Path:
    if KAIKKI_CACHE.exists():
        return KAIKKI_CACHE
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[wiktionary-roots] fetching -> {KAIKKI_CACHE} (see module docstring re: pin caveat)",
          file=sys.stderr)
    urllib.request.urlretrieve(KAIKKI_URL, KAIKKI_CACHE)
    return KAIKKI_CACHE


def load_by_root(path: Path | None = None) -> dict[str, set[str]]:
    """root -> {Hebrew lemma, ...}, from every word entry's `categories` (top-level + per-sense)."""
    path = path or fetch_kaikki()
    by_root: dict[str, set[str]] = collections.defaultdict(set)
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            d = json.loads(line)
            word = d.get("word")
            if not word:
                continue
            cats = list(d.get("categories", []))
            for sense in d.get("senses", []):
                cats += sense.get("categories", [])
            for c in cats:
                name = c if isinstance(c, str) else c.get("name", "")
                m = ROOT_CAT_RE.match(name)
                if m:
                    by_root[m.group(1)].add(word)
    return by_root


def build() -> list[tuple[str, str, str]]:
    """[(strong_a, strong_b, root)] — Strong's pairs sharing a Wiktionary root category, bare-
    consonant-matched to biblical Hebrew (same technique/ambiguity cap as build_hwn_benchmark.py)."""
    by_root = load_by_root()
    bare2strongs = load_bare_to_strongs()
    print(f"[wiktionary-roots] {len(by_root)} root categories, {len(bare2strongs)} biblical bare-forms",
          file=sys.stderr)

    rows, matched_roots = [], 0
    for root, lemmas in by_root.items():
        strongs: set[str] = set()
        for lem in lemmas:
            strongs |= bare2strongs.get(to_modern_form(lem, "hbo"), set())
        if len(strongs) >= 2:
            matched_roots += 1
            for a, b in itertools.combinations(sorted(strongs), 2):
                rows.append((a, b, root))
    print(f"[wiktionary-roots] {matched_roots}/{len(by_root)} roots matched -> {len(rows)} Strong's pairs",
          file=sys.stderr)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT_DIR / "root_pairs.tsv")
    args = ap.parse_args()

    rows = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write("# Hebrew Strong's pairs sharing a Wiktionary root category (CC BY-SA, kaikki.org "
                  "wiktextract extract\n# of English Wiktionary's Hebrew entries). Validated 2026-08 at "
                  "35.0% SDBH-domain agreement on its\n# own — weaker than BDB (50.6%); real value is as "
                  "a second vote alongside xling (agreement jumps\n# to 87.7% on the intersection) — see "
                  "domain-replacement-roadmap.md. See build_wiktionary_roots.py.\n")
        fh.write("strong_a\tstrong_b\troot\n")
        for a, b, root in sorted(rows):
            fh.write(f"{a}\t{b}\t{root}\n")
    print(f"[wiktionary-roots] -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
