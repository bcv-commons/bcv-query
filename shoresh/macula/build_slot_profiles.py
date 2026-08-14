#!/usr/bin/env python3
"""Verb argument-slot filler profiles — the raw material for the text-anchored yardstick
(internal-docs/text-anchored-semantics-plan.md). Recovers BHSA clause structure from the two SQLite
DBs already on disk (resources/occurrences/hbo.db + hbo_syntax.db), needing no corpus mount:

  join hbo.db <-> hbo_syntax.db on `node`, group by (ref, context) to recover clauses, then for each
  clause's Pred verb, pair it with every content-word filler in a Subj/Objc/Cmpl/PreC slot.

Verified 2026-08-14: 88,138 clause groups recovered this way (vs. 88,131 known from
shoresh/data/clauses_hbo.sqlite — 7 collisions from identical clause text within one verse,
negligible), 44,027 with a Pred + >=1 argument. Sample verb->Objc profiles are exactly right:
BNH[ -> BJT/ (build->house) 110x, >KL[ -> LXM/ (eat->bread) 64x, CLX[ -> ML>K/ (send->messenger) 57x.

Content-word restriction (subs/verb/adjv) matches build_bhsa_structural_pairs.py's CONTENT_SP — a
structural choice, not an SDBH-tuned one. Clauses with >1 Pred verb (31 total, e.g. compound "and he
said... and he said") pair every verb with every filler in that clause; this is a known, small,
accepted source of noise rather than an attempt at full argument-structure disambiguation.

  python -m macula.build_slot_profiles
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HBO = ROOT / "resources" / "occurrences" / "hbo.db"
HBO_SYNTAX = ROOT / "resources" / "occurrences" / "hbo_syntax.db"
OUT_DIR = ROOT / "resources" / "syntax_profiles"

CONTENT_SP = {"subs", "verb", "adjv"}
SLOTS = {"Subj", "Objc", "Cmpl", "PreC"}


def extract(books: set[str] | None = None) -> collections.Counter:
    """Counter[(verb_strong, slot, filler_strong)] -> occurrence count.

    books: restrict to this set of BHSA book codes (e.g. {"GEN","EXO"}); None = whole OT. Used by
    intrinsic_yardstick.py to build train/test splits without duplicating the clause-recovery join."""
    db = sqlite3.connect(f"file:{HBO}?mode=ro", uri=True)
    db.execute(f"ATTACH 'file:{HBO_SYNTAX}?mode=ro' AS s")

    book_filter = ""
    params: tuple = ()
    if books is not None:
        placeholders = ",".join("?" * len(books))
        book_filter = f" AND o.book IN ({placeholders})"
        params = tuple(books)

    rows = db.execute(
        f"""
        SELECT o.ref, o.context, o.node, o.strong, o.sp, sy.function
        FROM occurrence o JOIN s.syntax sy ON sy.node = o.node
        WHERE o.strong IS NOT NULL AND o.strong != ''
          AND (sy.function = 'Pred' OR sy.function IN ('Subj','Objc','Cmpl','PreC')){book_filter}
        ORDER BY o.ref, o.context
        """,
        params,
    )

    profiles: collections.Counter = collections.Counter()
    clause_key = None
    verbs: list[str] = []
    fillers: list[tuple[str, str]] = []

    def flush():
        for v in verbs:
            for slot, f in fillers:
                if f != v:
                    profiles[(v, slot, f)] += 1

    for ref, context, node, strong, sp, function in rows:
        key = (ref, context)
        if key != clause_key:
            flush()
            clause_key = key
            verbs, fillers = [], []
        if function == "Pred" and sp == "verb":
            verbs.append(strong)
        elif function in SLOTS and sp in CONTENT_SP:
            fillers.append((function, strong))
    flush()

    print(f"[slot-profiles] {len(profiles)} distinct (verb, slot, filler) triples, "
          f"{sum(profiles.values())} occurrences", file=sys.stderr)
    return profiles


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT_DIR / "slot_fillers.tsv")
    args = ap.parse_args()

    profiles = extract()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write("# Verb argument-slot filler profiles, recovered from BHSA syntax (via Context-Fabric\n"
                  "# annotation, cached in resources/occurrences/hbo.db + hbo_syntax.db -- no corpus mount\n"
                  "# needed). slot in {Subj, Objc, Cmpl, PreC}. count: occurrences across the OT.\n"
                  "# Raw material for the text-anchored yardstick -- see\n"
                  "# internal-docs/text-anchored-semantics-plan.md. Not SDBH-derived.\n")
        fh.write("verb_strong\tslot\tfiller_strong\tcount\n")
        for (v, slot, f), cnt in sorted(profiles.items(), key=lambda r: (-r[1], r[0])):
            fh.write(f"{v}\t{slot}\t{f}\t{cnt}\n")
    print(f"[slot-profiles] -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
