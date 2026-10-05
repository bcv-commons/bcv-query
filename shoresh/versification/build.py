#!/usr/bin/env python3
"""Versification scheme registry (roadmap V1) — map any tradition's verse refs to the KJV standard.

**KJV is the chosen standard.** Every Bible version carries a `versification` scheme; anything not
KJV-numbered normalizes to KJV via its scheme's diffs. This builds those diff tables from STEPBible's
**TVTMS** (CC-BY) "Expanded Version", whose columns are `SourceType | SourceRef | StandardRef(=KJV) |
Action | …`. We extract, per scheme, the rows where `SourceRef != StandardRef` (identity elsewhere):

  • **hebrew** (Masoretic / WLC — our BHSA spine)  — TVTMS SourceType has the part "Hebrew"
  • **lxx**    (Septuagint / Rahlfs — our lxx.db)  — TVTMS SourceType has the part "Greek"

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

# TVTMS SourceType keyword -> our scheme name. A SourceType names one or more traditions joined by "+"
# ("Latin+Greek", "Eng-KJV+Hebrew"); a scheme takes the rows whose SourceType has the keyword as one of
# those parts. Matched as a whole part, not a substring: "Greek2", "GreekUndivided", "GreekIntegrated",
# "Greek3", "Greek2-NETS" are other Greek traditions, and substring matching let their rows overwrite the
# standard ones (lxx Ps 9:21 mapped to both 9:20 and 10:1; 116 LXX verses had two targets).
SCHEMES = {"hebrew": "Hebrew", "lxx": "Greek"}
# Exact-part matching is used for "hebrew" only. The lxx scheme keeps the old substring match ("Greek" also
# takes Greek2, GreekUndivided...) until it gets per-book reconciliation: for Rahlfs neither tradition is
# right throughout. Exact "Greek" fixes Ps 9:21 and Hos 6:6 but loses LXX Jeremiah's reordering (only in
# Greek2) and Malachi (Rahlfs 3:22-24 follows Greek2), while Greek2 wrongly shifts Haggai and Zechariah 3.
# The right tradition per book is the one whose source shape matches data/vrs/lxx.vrs (see
# internal-docs/vrs-reconciliation/). Until then: unchanged behaviour (a source verse can have two targets).
EXACT = {"hebrew"}


def _has_tradition(stype: str, kw: str) -> bool:
    return kw in (part.strip() for part in stype.split("+"))
_REF = re.compile(r"^([1-4A-Za-z]{2,4})\.(\d+):(\d+|Title)$")   # Gen.6:1 / Psa.3:Title

# The generic single-verse extraction is reliable only for the protestant OT books whose versification
# has ONE consistent layout. Excluded here (need dedicated per-book reconciliation against the canonical
# `.vrs` — see internal-docs/vrs-reconciliation/):
#   • the deuterocanon — Greek Esther (`Esg`/`ESG`), Daniel-Greek (`DAG`), 2 Esdras (`2ES`), Odes (`ODA`)
#   • the two protestant books with EMBEDDED Greek additions — **Esther** (Addition A–F) and **Daniel**
#     (Song of the Three `S3Y`, Susanna `SUS`, Bel `BEL`). TVTMS carries multiple incompatible layouts
#     for these (Greek / GreekUndivided / GreekIntegrated / Greek2) + additions as sub-verses; the
#     `SourceType contains "Greek"` filter would conflate them into garbage (this produced the broken
#     `ESG`/`DAN→S3Y` rows). NT rows that leak via compound Greek SourceTypes are also out of scope.
_OT_BOOKS = {"GEN", "EXO", "LEV", "NUM", "DEU", "JOS", "JDG", "RUT", "1SA", "2SA", "1KI", "2KI",
             "1CH", "2CH", "EZR", "NEH", "JOB", "PSA", "PRO", "ECC", "SNG", "ISA", "JER",
             "LAM", "EZK", "HOS", "JOL", "AMO", "OBA", "JON", "MIC", "NAM", "HAB", "ZEP",
             "HAG", "ZEC", "MAL"}   # EST + DAN excluded (embedded Greek additions — dedicated handling)
# ... but only from the Greek scheme: the Hebrew text of Esther and Daniel has no additions, and Daniel's
# Hebrew/Aramaic renumbering (Dan 3:31 -> KJV 4:1, 6:1 -> 5:31) is ordinary. Excluding them from the
# Hebrew scheme too (2026-07-14) dropped 66 valid Daniel rows.
_BOOKS = {"hebrew": _OT_BOOKS | {"EST", "DAN"}, "lxx": _OT_BOOKS}


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


def _kjv_shape() -> dict:
    """book -> {chapter: verses} of the KJV standard (data/vrs/eng.vrs)."""
    out: dict = {}
    for ln in (Path(__file__).resolve().parent / "data" / "vrs" / "eng.vrs").read_text(encoding="utf-8").splitlines():
        p = ln.split()
        if p and not ln.startswith("#") and len(p) > 1 and ":" in p[1]:
            out[p[0]] = {int(t.split(":")[0]): int(t.split(":")[1]) for t in p[1:]}
    return out


def _in_kjv(shape: dict, ref: str) -> bool:
    b, cv = ref.split(" ", 1)
    c, v = cv.split(":")
    return v == "title" or (b in shape and int(c) in shape[b] and 1 <= int(v) <= shape[b][int(c)])


def build(src: Path | None = None):
    source = fetch(src)
    lines = source.read_text(encoding="utf-8-sig").splitlines()
    kjv = _kjv_shape()

    rows = {name: [] for name in SCHEMES}
    seen = {name: set() for name in SCHEMES}
    for ln in lines:
        c = ln.split("\t")
        if len(c) < 4 or not c[0].strip():
            continue
        stype, sref, stdref, action = c[0].strip(), c[1].strip(), c[2].strip(), c[3].strip()
        if "." not in sref or ":" not in sref:
            continue
        # protestant OT only — deuterocanon (ESG/DAG/2ES/ODA) needs dedicated per-book handling
        book = sref.split(".", 1)[0].upper()
        if book not in _OT_BOOKS | {"EST", "DAN"}:
            continue
        # v1: clean single-verse remaps only — skip ranges/subverses (';' '-' '!')
        if any(ch in sref or ch in stdref for ch in (";", "-", "!")):
            continue
        s, d = _norm(sref), _norm(stdref)
        if not s or not d or s == d:
            continue
        if not _in_kjv(kjv, d):           # the standard side must be a KJV verse (TVTMS 1Ki.5:18 -> 1Ki.5:32)
            continue
        for name, kw in SCHEMES.items():
            if book not in _BOOKS[name]:
                continue
            match = _has_tradition(stype, kw) if name in EXACT else kw in stype
            if match and (s, d) not in seen[name]:
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
