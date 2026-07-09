#!/usr/bin/env python3
"""Versification scheme registry (roadmap V1) — map any tradition's verse refs to the KJV standard.

**KJV is the chosen standard.** Every Bible version carries a `versification` scheme; anything not
KJV-numbered normalizes to KJV via its scheme's diffs. This builds those diff tables from STEPBible's
**TVTMS** (CC-BY) "Expanded Version", whose columns are `SourceType | SourceRef | StandardRef(=KJV) |
Action | …`. We extract, per scheme, the rows where `SourceRef != StandardRef` (identity elsewhere):

  • **hebrew** (Masoretic / WLC — our BHSA spine)  — TVTMS SourceType contains "Hebrew"
  • **lxx**    (Septuagint / Rahlfs — our lxx.db)  — TVTMS SourceType contains "Greek"

Output: `resources/versification/schemes/<scheme>.tsv` (`source_ref  standard_ref  action`) +
`schemes.tsv` registry. Refs are `BOOK ch:v` (USFM codes); a Psalm superscription maps to the KJV
verse token `title`. Ranges / LXX sub-verses (`;` `-` `!`) are out of scope for v1 (flagged, skipped).

  python -m versification.build              # downloads pinned TVTMS, writes resources/versification/
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT_DIR = ROOT / "resources" / "versification"
CACHE = HERE / "data" / "tvtms.txt"

# Pinned STEPBible TVTMS (CC-BY). raw githubusercontent needs the URL-encoded filename.
TVTMS_URL = ("https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master/Versification/"
             "TVTMS%20-%20Translators%20Versification%20Traditions%20with%20Methodology%20for%20"
             "Standardisation%20for%20Eng%2BHeb%2BLat%2BGrk%2BOthers%20-%20STEPBible.org%20CC%20BY.txt")

# TVTMS SourceType keyword -> our scheme name (a scheme = every SourceType containing the keyword).
SCHEMES = {"hebrew": "Hebrew", "lxx": "Greek"}
_REF = re.compile(r"^([1-4A-Za-z]{2,4})\.(\d+):(\d+|Title)$")   # Gen.6:1 / Psa.3:Title


def fetch(src: Path | None) -> Path:
    if src:
        return src
    if not CACHE.exists():
        import httpx
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        print("downloading TVTMS …", file=sys.stderr)
        r = httpx.get(TVTMS_URL, timeout=120, follow_redirects=True)
        r.raise_for_status()
        CACHE.write_bytes(r.content)
    return CACHE


def _norm(ref: str):
    """'Gen.6:1' / 'Psa.3:Title' -> ('GEN 6:1', verse-token) or None if not a clean single verse."""
    m = _REF.match(ref.strip())
    if not m:
        return None
    book, ch, v = m.group(1).upper(), m.group(2), m.group(3)
    v = "title" if v.lower() == "title" else v
    return f"{book} {ch}:{v}"


def build(src: Path | None = None):
    source = fetch(src)
    lines = source.read_text(encoding="utf-8-sig").splitlines()

    rows = {name: [] for name in SCHEMES}
    seen = {name: set() for name in SCHEMES}
    for ln in lines:
        c = ln.split("\t")
        if len(c) < 4 or not c[0].strip():
            continue
        stype, sref, stdref, action = c[0].strip(), c[1].strip(), c[2].strip(), c[3].strip()
        if "." not in sref or ":" not in sref:
            continue
        # v1: clean single-verse remaps only — skip ranges/subverses (';' '-' '!')
        if any(ch in sref or ch in stdref for ch in (";", "-", "!")):
            continue
        s, d = _norm(sref), _norm(stdref)
        if not s or not d or s == d:
            continue
        for name, kw in SCHEMES.items():
            if kw in stype and (s, d) not in seen[name]:
                seen[name].add((s, d))
                rows[name].append((s, d, action))

    (OUT_DIR / "schemes").mkdir(parents=True, exist_ok=True)
    reg = []
    for name, rr in rows.items():
        rr.sort(key=lambda r: r[0])
        with (OUT_DIR / "schemes" / f"{name}.tsv").open("w", encoding="utf-8") as fh:
            fh.write(f"# {name} versification -> KJV standard; single-verse diffs only "
                     f"(identity elsewhere). Source: STEPBible TVTMS (CC-BY). shoresh versification.build\n")
            fh.write("source_ref\tstandard_ref\taction\n")
            for s, d, a in rr:
                fh.write(f"{s}\t{d}\t{a}\n")
        reg.append((name, SCHEMES[name], len(rr)))
        print(f"[versification] {name}: {len(rr)} diff rows", file=sys.stderr)

    with (OUT_DIR / "schemes.tsv").open("w", encoding="utf-8") as fh:
        fh.write("# versification scheme registry; standard = KJV. shoresh versification.build\n")
        fh.write("scheme\ttvtms_sourcetype\tn_diffs\tstandard\n")
        fh.write("kjv\t(standard)\t0\tkjv\n")
        for name, kw, n in reg:
            fh.write(f"{name}\t{kw}\t{n}\tkjv\n")
    print(f"[versification] -> {OUT_DIR}", file=sys.stderr)
    return rows


if __name__ == "__main__":
    build()
