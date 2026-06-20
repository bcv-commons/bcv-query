#!/usr/bin/env python3
"""Build strong_lemma.tsv — the canonical (prefixed Strong's, lang) → lemma map.

Phase 1a of the Strong's-anchored core. Resolves each Strong's code to its
primary original-language lemma (+ variants), **testament-split** so H/G don't
collide (spine_words.strong is a bare int over both testaments). Occurrences
stay in spine_words/lxx.db — this is the dictionary-level map, not the per-token
store.

Anchoring standard: this gives the L1 (lemma) for each L2 (prefixed Strong's).
The ~271 per-testament multi-lemma codes (mostly vocalization/accent variants of
the same word — יְהֹוָה/יְהֹוִה, ὁ/ὅς) keep the most-frequent lemma as primary and
the rest as `lemma_variants`. LXX-only Greek codes have no lemma (lxx_words has
no lemma column) → empty lemma, Strong's-only.

Columns: strong, lang, lemma, lemma_variants, count
  strong = padded prefixed (H####/G####), matching strongs_freq/keyness/gloss.
  lang   = hbo (OT) / grc (NT+LXX).
  count  = total tokens (matches strongs_freq.tsv).

BUILD-TIME ONLY (reads local spine.db/lxx.db). Run from bcv-RAG/.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SPINE_DB = ROOT / "shoresh" / "spine" / "spine.db"
LXX_DB = ROOT / "shoresh" / "lxx" / "lxx.db"
OUTPUT = Path(__file__).resolve().parent.parent / "strong_lemma.tsv"

sys.path.insert(0, str(ROOT / "shoresh"))
from spine.common import NT_BOOKS  # noqa: E402  (single source of the OT/NT split)


def _norm(prefix: str, strong: int) -> str:
    return f"{prefix}{int(strong):04d}"


def main() -> None:
    if not SPINE_DB.exists():
        print(f"ERROR: {SPINE_DB} not found", file=sys.stderr)
        sys.exit(1)

    # code -> {"lang": str, "lemmas": {lemma: count}, "total": int}
    agg: dict[str, dict] = {}

    def slot(code: str, lang: str) -> dict:
        s = agg.get(code)
        if s is None:
            s = {"lang": lang, "lemmas": {}, "total": 0}
            agg[code] = s
        return s

    nt = sorted(NT_BOOKS)
    nt_ph = ",".join("?" * len(nt))

    scon = sqlite3.connect(SPINE_DB)
    # OT (Hebrew → H) and NT (Greek → G), counting tokens per (strong, lemma).
    for prefix, lang, where, params in (
        ("H", "hbo", f"book NOT IN ({nt_ph})", nt),
        ("G", "grc", f"book IN ({nt_ph})", nt),
    ):
        rows = scon.execute(
            f"SELECT strong, lemma, COUNT(*) c FROM spine_words "
            f"WHERE strong IS NOT NULL AND {where} GROUP BY strong, lemma",
            params,
        ).fetchall()
        for strong, lemma, c in rows:
            s = slot(_norm(prefix, strong), lang)
            s["total"] += c
            if lemma:
                s["lemmas"][lemma] = s["lemmas"].get(lemma, 0) + c
    scon.close()

    # LXX (Greek OT) → merge token counts into G; no lemma available.
    if LXX_DB.exists():
        lcon = sqlite3.connect(LXX_DB)
        for strong, c in lcon.execute(
            "SELECT strong, COUNT(*) c FROM lxx_words "
            "WHERE strong IS NOT NULL GROUP BY strong"
        ).fetchall():
            slot(_norm("G", strong), "grc")["total"] += c
        lcon.close()
    else:
        print(f"WARN: {LXX_DB} not found — Greek counts are NT-only", file=sys.stderr)

    rows_out = []
    no_lemma = 0
    for code, s in agg.items():
        lemmas = sorted(s["lemmas"].items(), key=lambda kv: (-kv[1], kv[0]))
        primary = lemmas[0][0] if lemmas else ""
        variants = ",".join(l for l, _ in lemmas[1:])
        if not primary:
            no_lemma += 1
        rows_out.append((code, s["lang"], primary, variants, s["total"]))
    rows_out.sort(key=lambda r: (r[0][0], int(r[0][1:5]), r[0]))

    with OUTPUT.open("w", encoding="utf-8") as fh:
        fh.write("strong\tlang\tlemma\tlemma_variants\tcount\n")
        for code, lang, lemma, variants, count in rows_out:
            fh.write(f"{code}\t{lang}\t{lemma}\t{variants}\t{count}\n")

    n_var = sum(1 for r in rows_out if r[3])
    print(f"Wrote {len(rows_out)} codes to {OUTPUT} "
          f"({n_var} with lemma_variants, {no_lemma} no-lemma/LXX-only)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
