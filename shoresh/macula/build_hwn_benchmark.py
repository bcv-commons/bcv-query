#!/usr/bin/env python3
"""Hebrew WordNet independent benchmark — Gap 4 of domain-replacement-roadmap.md.

Every quality number produced so far for the semantic_neighbors/domain_clusters work has been
measured against the very NC domains (SDBH/UBS MARBLE) it's trying to replace — the roadmap doc
itself flags this as circular, not proof. Hebrew WordNet (Ordan & Wintner, U. Haifa, 2007) is a
genuinely independent resource: not derived from UBS MARBLE at all (a different lineage —
MultiWordNet methodology, aligned to Princeton/Italian/Spanish WordNets), permissively licensed
("permission to use, copy, modify and distribute... for any purpose and without fee or royalty").

Caveat, real and unresolved: Hebrew WordNet is MODERN Hebrew, not biblical — vocabulary/register
overlap with BHSA is partial by construction, not a defect of this script.

Method: parse Hebrew WordNet's synsets, strip niqqud (spine.common.to_modern_form — the same
consonant-skeleton normalization already used elsewhere for biblical<->modern Hebrew matching) from
both HWN lemmas and lexeme-spine.db's biblical lemmas, join on the bare-consonant form. Homograph
collisions are real (multiple Strong's can share the same bare skeleton) — capped at
MAX_STRONGS_PER_FORM to keep the worst collisions out without discarding almost everything (an
unambiguous-only cut was tried: 41 synsets / 51 pairs, too small to be useful).

NOTE the encoding bug this script works around: hebrew_synsets.xml's `<?xml ... encoding="ISO-8859-1"?>`
declaration is WRONG — the bytes are actually UTF-8. Decode manually and parse from a str; don't let
ElementTree trust the (lying) declaration.

  python -m macula.build_hwn_benchmark [--hwn-xml path/to/hebrew_synsets.xml]
"""
from __future__ import annotations

import argparse
import collections
import itertools
import sqlite3
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine.common import to_modern_form  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPINE = HERE / "lexeme-spine.db"
OUT = ROOT / "resources" / "semantic_neighbors" / "hwn_benchmark.tsv"
DATA_DIR = HERE / "data"

# Ordan & Wintner, U. Haifa (2007) — permissively licensed ("permission to use, copy, modify and
# distribute... for any purpose and without fee or royalty"). Mirror, not the (defunct) original site.
# Pinned to a specific commit — never fetched from a mutable "latest" branch.
HWN_REPO = "NLPH/HebrewWordnetShuly"
HWN_COMMIT = "55a814bad768206ca2679f10337fe63a7f8540f9"
HWN_PATH_IN_REPO = "HWN/data/hebrew_xml_cgirardi1180700635/hebrew_synsets.xml"
HWN_URL = f"https://raw.githubusercontent.com/{HWN_REPO}/{HWN_COMMIT}/{HWN_PATH_IN_REPO}"
HWN_CACHE = DATA_DIR / "hebrew_synsets.xml"


def fetch_hwn() -> Path:
    if HWN_CACHE.exists():
        return HWN_CACHE
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[hwn] fetching (pinned {HWN_COMMIT[:8]}) -> {HWN_CACHE}", file=sys.stderr)
    urllib.request.urlretrieve(HWN_URL, HWN_CACHE)
    return HWN_CACHE


MAX_STRONGS_PER_FORM = 3   # cap ambiguous bare-consonant collisions; unambiguous-only is too sparse (41/51)


def load_hwn_synsets(xml_path: Path | None = None) -> list[tuple[str, str, list[str]]]:
    """[(synset_id, pos, [hebrew lemma, ...])] for synsets with >=2 lemmas. Manual UTF-8 decode —
    the file's own XML declaration falsely claims ISO-8859-1; trusting it produces mojibake."""
    xml_path = xml_path or fetch_hwn()
    text = xml_path.read_bytes().decode("utf-8")
    root = ET.fromstring(text)
    out = []
    for syn in root.iter("synset"):
        lemmas = []
        for lem in syn.iter("lemma"):
            t = (lem.text or "").strip()
            if t and t != "GAP!":
                lemmas.append(t.lstrip("!"))
        if len(lemmas) >= 2:
            out.append((syn.get("id"), syn.get("pos"), lemmas))
    return out


def load_bare_to_strongs(max_per_form: int = MAX_STRONGS_PER_FORM) -> dict[str, set[str]]:
    """Bare-consonant biblical Hebrew lemma -> {H####, ...}, from lexeme-spine.db. Content lexemes
    only (matches what the neighbor pack / domain clusters exclude — proper nouns aren't domains)."""
    c = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    bare2strongs: dict[str, set[str]] = collections.defaultdict(set)
    for strong, lemma in c.execute(
            "SELECT DISTINCT strong, lemma FROM spine_words WHERE is_content=1 AND strong IS NOT NULL "
            "AND lexeme LIKE 'hbo:%' AND lemma IS NOT NULL"):
        bare = to_modern_form(lemma, "hbo")
        if bare:
            bare2strongs[bare].add(f"H{int(strong):04d}")
    return {k: v for k, v in bare2strongs.items() if len(v) <= max_per_form}


def build(xml_path: Path) -> list[tuple[str, str, str]]:
    """[(strong_a, strong_b, synset_id)] — ground-truth synonym pairs, independent of UBS MARBLE."""
    synsets = load_hwn_synsets(xml_path)
    bare2strongs = load_bare_to_strongs()
    print(f"[hwn-benchmark] {len(synsets)} HWN synsets (>=2 lemmas); "
          f"{len(bare2strongs)} biblical bare-forms (<= {MAX_STRONGS_PER_FORM}-way ambiguity)",
          file=sys.stderr)

    pairs, matched_synsets = [], 0
    for sid, _pos, lemmas in synsets:
        strongs: set[str] = set()
        for lem in lemmas:
            strongs |= bare2strongs.get(to_modern_form(lem, "hbo"), set())
        if len(strongs) >= 2:
            matched_synsets += 1
            for a, b in itertools.combinations(sorted(strongs), 2):
                pairs.append((a, b, sid))
    print(f"[hwn-benchmark] {matched_synsets} synsets matched -> {len(pairs)} ground-truth pairs",
          file=sys.stderr)
    return pairs


def score_against(neighbors_path: Path, pairs: list[tuple[str, str, str]]) -> None:
    """How well does an existing by_lexeme.tsv's high-tier graph recover these independent pairs?
    Strong's-level: a pair 'recovers' if ANY lexeme of strong_a is a high-tier neighbor of ANY
    lexeme of strong_b (or vice versa) in the given pack."""
    high_strong_pairs = set()
    if neighbors_path.exists():
        with neighbors_path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("#") or line.startswith("strong\t"):
                    continue
                p = line.rstrip("\n").split("\t")
                if len(p) >= 8 and p[6] == "similar" and p[7] == "high":
                    high_strong_pairs.add(frozenset((p[0], p[3])))
    hit = sum(1 for a, b, _ in pairs if frozenset((a, b)) in high_strong_pairs)
    print(f"[hwn-benchmark] {neighbors_path.parent.name}: {hit}/{len(pairs)} independent HWN pairs "
          f"recovered by the high tier = {100*hit/max(len(pairs),1):.1f}%", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hwn-xml", type=Path, default=None,
                     help="default: pinned fetch (see HWN_URL/HWN_COMMIT)")
    ap.add_argument("--score", type=Path, action="append", default=[],
                    help="by_lexeme.tsv to score against the benchmark (repeatable)")
    args = ap.parse_args()

    pairs = build(args.hwn_xml)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        fh.write("# Independent synonym-pair benchmark from Hebrew WordNet (Ordan & Wintner, U. Haifa, "
                 "2007) — NOT derived from UBS MARBLE. Modern Hebrew; biblical overlap only. "
                 "See build_hwn_benchmark.py.\n")
        fh.write("strong_a\tstrong_b\thwn_synset_id\n")
        for a, b, sid in sorted(pairs):
            fh.write(f"{a}\t{b}\t{sid}\n")
    print(f"[hwn-benchmark] -> {OUT}", file=sys.stderr)

    for path in args.score:
        score_against(path, pairs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
