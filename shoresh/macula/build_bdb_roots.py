#!/usr/bin/env python3
"""BDB etymological root-groups — candidate #8, bcv-commons-export-candidates.md.

Brown-Driver-Briggs (1906) is public domain; the OpenScriptures digitization
(github.com/openscriptures/HebrewLexicon, CC-BY-4.0 for the XML structure) links every lexicon entry
to a Strong's number AND groups entries by etymological root via the `etym` field in
`LexicalIndex.xml`. Words sharing a root are semantically related far more often than chance — VALIDATED
2026-08 against SDBH (the same yardstick used throughout this project): same-root pairs share an SDBH
domain 50.6% of the time (2,731/5,397 checkable pairs), actually better than our own from-scratch
Louvain clustering (45.1%), at ~10x the scale (2,643 root-groups vs. 131 clusters, 8,673 distinct
Strong's covered vs. our 2,397). A completely free, comprehensive, independent signal.

Pinned fetch (not "latest") — same discipline as every other external dependency in this pipeline.

  python -m macula.build_bdb_roots
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT_DIR = ROOT / "resources" / "bdb_roots"
DATA_DIR = HERE / "data"

REPO = "openscriptures/HebrewLexicon"
COMMIT = "21c9add13bc727d3a951361778e97e3ff7afd1ce"   # pinned 2019-09-02, project is stable/dormant
URL = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/LexicalIndex.xml"
CACHE = DATA_DIR / "LexicalIndex.xml"

NS = {"ns": "http://openscriptures.github.com/morphhb/namespace"}
TAG = "{http://openscriptures.github.com/morphhb/namespace}entry"


def fetch() -> Path:
    if CACHE.exists():
        return CACHE
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[bdb-roots] fetching (pinned {COMMIT[:8]}) -> {CACHE}", file=sys.stderr)
    urllib.request.urlretrieve(URL, CACHE)
    return CACHE


def _strong(xref) -> str | None:
    s = xref.get("strong") if xref is not None else None
    if not s:
        return None
    m = re.match(r"(\d+)", s)
    return f"H{int(m.group(1)):04d}" if m else None


def build() -> list[tuple[str, str, str, str, str]]:
    """[(root_id, strong, xlit, gloss, pos)] — one row per Strong's in a root-group of size >= 2.
    root_id = the anchoring entry's own id (arbitrary but stable identifier for the group)."""
    path = fetch()
    tree = ET.parse(path)
    xmlroot = tree.getroot()

    entries = {}   # eid -> (strong, xlit, gloss, pos)
    for entry in xmlroot.iter(TAG):
        eid = entry.get("id")
        xref = entry.find("ns:xref", NS)
        strong = _strong(xref)
        w = entry.find("ns:w", NS)
        xlit = w.get("xlit", "") if w is not None else ""
        pos_el = entry.find("ns:pos", NS)
        pos = pos_el.text.strip() if pos_el is not None and pos_el.text else ""
        def_el = entry.find("ns:def", NS)
        gloss = def_el.text.strip() if def_el is not None and def_el.text else ""
        entries[eid] = (strong, xlit, gloss, pos)

    rows = []
    n_groups = 0
    for entry in xmlroot.iter(TAG):
        eid = entry.get("id")
        etym = entry.find("ns:etym", NS)
        if etym is None or etym.get("type") != "main":
            continue
        members = [m.strip() for m in (etym.text or "").split(",") if m.strip()]
        group_ids = [eid] + members
        group_rows = [(eid, *entries[i]) for i in group_ids if i in entries and entries[i][0]]
        if len({r[1] for r in group_rows}) < 2:   # need >=2 distinct Strong's to be a real group
            continue
        n_groups += 1
        rows.extend(group_rows)

    print(f"[bdb-roots] {n_groups} root-groups, {len(rows)} (root, strong) rows, "
          f"{len({r[1] for r in rows})} distinct Strong's", file=sys.stderr)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT_DIR / "root_groups.tsv")
    args = ap.parse_args()

    rows = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write(f"# BDB (public domain, 1906) etymological root-groups, via OpenScriptures/HebrewLexicon "
                 f"(CC-BY-4.0, pinned {COMMIT[:8]}). Words sharing root_id are etymologically related — "
                 f"validated at 50.6% SDBH-domain agreement (2026-08), see build_bdb_roots.py and "
                 f"domain-replacement-roadmap.md. NOT Louw-Nida/SDBH derived — independent free source.\n")
        fh.write("root_id\tstrong\txlit\tgloss\tpos\n")
        for row in rows:
            fh.write("\t".join(row) + "\n")
    print(f"[bdb-roots] -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
