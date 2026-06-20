#!/usr/bin/env python3
"""Build forms.tsv — original-language surface forms per Strong's/lemma (Phase 3a / Strategy 5).

The original-language twin of Tier-2's Product B: for each Strong's code, every
distinct inflected SURFACE form attested in spine_words, with a count and a
sample reference. Two uses:
  - reverse (surface → lemma → Strong's): a Hebrew/Greek query form like "חסדי"
    resolves to lemma חֶסֶד → H2617.
  - the lemma anchor that later Tier-2 (per-language) aligns its forms against.

Anchored on lemma (carried) with prefixed Strong's as alias; testament-split
(OT→H, NT→G) so H/G don't collide. LXX excluded (lxx_words has no lemma).

Columns: strong, lemma, surface, count, ref
  one row per distinct (strong, surface); ref = a sample "BOOK ch:vs".

BUILD-TIME ONLY (reads local spine.db). Run from bcv-RAG/.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SPINE_DB = ROOT / "shoresh" / "spine" / "spine.db"
OUTPUT = Path(__file__).resolve().parent.parent / "forms.tsv"

sys.path.insert(0, str(ROOT / "shoresh"))
from spine.common import NT_BOOKS  # noqa: E402


def _norm(prefix: str, strong: int) -> str:
    return f"{prefix}{int(strong):04d}"


def main() -> None:
    if not SPINE_DB.exists():
        print(f"ERROR: {SPINE_DB} not found", file=sys.stderr)
        sys.exit(1)

    # (strong_code, surface) -> {"count", "lemmas": {lemma: n}, "ref"}
    agg: dict[tuple[str, str], dict] = {}
    con = sqlite3.connect(SPINE_DB)
    rows = con.execute(
        "SELECT book, chapter, verse, surface, strong, lemma FROM spine_words "
        "WHERE strong IS NOT NULL AND surface IS NOT NULL "
        "ORDER BY book, chapter, verse, idx"
    ).fetchall()
    con.close()

    for book, ch, vs, surface, strong, lemma in rows:
        prefix = "G" if book in NT_BOOKS else "H"
        code = _norm(prefix, strong)
        key = (code, surface)
        slot = agg.get(key)
        if slot is None:
            slot = {"count": 0, "lemmas": {}, "ref": f"{book} {ch}:{vs}"}
            agg[key] = slot
        slot["count"] += 1
        if lemma:
            slot["lemmas"][lemma] = slot["lemmas"].get(lemma, 0) + 1

    out = []
    for (code, surface), slot in agg.items():
        lemma = max(slot["lemmas"].items(), key=lambda kv: kv[1])[0] if slot["lemmas"] else ""
        out.append((code, lemma, surface, slot["count"], slot["ref"]))
    out.sort(key=lambda r: (r[0][0], int(r[0][1:5]), -r[3], r[2]))

    with OUTPUT.open("w", encoding="utf-8") as fh:
        fh.write("strong\tlemma\tsurface\tcount\tref\n")
        for code, lemma, surface, count, ref in out:
            fh.write(f"{code}\t{lemma}\t{surface}\t{count}\t{ref}\n")

    codes = len({c for c, _ in agg})
    print(f"Wrote {len(out)} distinct (strong,surface) forms for {codes} codes "
          f"to {OUTPUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
