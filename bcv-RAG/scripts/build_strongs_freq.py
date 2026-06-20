#!/usr/bin/env python3
"""Build strongs_freq.tsv: per-Strong's occurrence count + function/content
class, from the original-language biblical text.

Sources (read-only, local):
  ../../shoresh/spine/spine.db  spine_words  (OSHB Hebrew OT + Nestle1904 Greek NT)
  ../../shoresh/lxx/lxx.db      lxx_words    (LXX Greek OT, incl. deuterocanon)

IMPORTANT: spine_words.strong is a bare INTEGER with no H/G prefix, and the
same int means a different word in Hebrew vs Greek (strong=3588 is H3588 כִּי
in the OT but G3588 ὁ in the NT). We split spine by book/testament to assign
the correct prefix. Greek totals merge spine NT + LXX.

The drop signal is `is_function`, derived from the corpus's per-word
`is_content` flag — NOT raw frequency. Frequency alone can't separate a
frequent CONTENT word (G2962 κύριος "Lord", 9009×, is_content=1, KEEP) from a
particle (H0834 אֲשֶׁר "that", 5503×, is_content=0, DROP). A Strong's number is
classed function when the majority of its occurrences are is_content=0.

Output: strongs_freq.tsv with columns: strong, count, is_function
  H#### from OT books; G#### from NT books + LXX.

Used by query/concept_expand.py to drop function particles that pass the gloss
filter but carry no retrieval signal. Generated once locally and committed —
same ship-as-TSV pattern as strongs_gloss.tsv.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SPINE_DB = ROOT / "shoresh" / "spine" / "spine.db"
LXX_DB = ROOT / "shoresh" / "lxx" / "lxx.db"
OUTPUT = Path(__file__).resolve().parent.parent / "strongs_freq.tsv"

# Canonical OT/NT book split — imported from shoresh's single source of truth
# (spine/common.py) rather than duplicated here. Used to assign H vs G to the
# bare-int strong. Build-time only; shoresh is on the local path at build time.
sys.path.insert(0, str(ROOT / "shoresh"))
from spine.common import NT_BOOKS  # noqa: E402


def _norm(prefix: str, strong: int) -> str:
    """430 → H0430 (4-digit padded, matching strongs_gloss.tsv format)."""
    return f"{prefix}{int(strong):04d}"


def main() -> None:
    # code -> [total_count, content_count]
    agg: dict[str, list[int]] = {}

    def add(code: str, total: int, content: int) -> None:
        slot = agg.setdefault(code, [0, 0])
        slot[0] += total
        slot[1] += content

    if not SPINE_DB.exists():
        print(f"ERROR: {SPINE_DB} not found", file=sys.stderr)
        sys.exit(1)

    placeholders = ",".join("?" * len(NT_BOOKS))
    nt = sorted(NT_BOOKS)

    scon = sqlite3.connect(SPINE_DB)
    # Hebrew OT: books NOT in the NT set
    ot_rows = scon.execute(
        f"SELECT strong, COUNT(*) total, SUM(is_content) content FROM spine_words "
        f"WHERE strong IS NOT NULL AND book NOT IN ({placeholders}) "
        f"GROUP BY strong",
        nt,
    ).fetchall()
    for strong, total, content in ot_rows:
        add(_norm("H", strong), total, content or 0)

    # Greek NT: books IN the NT set
    nt_rows = scon.execute(
        f"SELECT strong, COUNT(*) total, SUM(is_content) content FROM spine_words "
        f"WHERE strong IS NOT NULL AND book IN ({placeholders}) "
        f"GROUP BY strong",
        nt,
    ).fetchall()
    for strong, total, content in nt_rows:
        add(_norm("G", strong), total, content or 0)
    scon.close()
    print(f"spine: {len(ot_rows)} Hebrew, {len(nt_rows)} Greek (NT)", file=sys.stderr)

    # Greek LXX (OT): merge into the same G#### space
    if LXX_DB.exists():
        lcon = sqlite3.connect(LXX_DB)
        lxx_rows = lcon.execute(
            "SELECT strong, COUNT(*) total, SUM(is_content) content FROM lxx_words "
            "WHERE strong IS NOT NULL GROUP BY strong"
        ).fetchall()
        for strong, total, content in lxx_rows:
            add(_norm("G", strong), total, content or 0)
        lcon.close()
        print(f"lxx: {len(lxx_rows)} Greek (LXX) merged into G", file=sys.stderr)
    else:
        print(f"WARN: {LXX_DB} not found — Greek counts are NT-only", file=sys.stderr)

    # is_function = majority of occurrences are NOT content
    rows = []
    for code, (total, content) in agg.items():
        is_function = 1 if content < total / 2 else 0
        rows.append((code, total, is_function))
    rows.sort(key=lambda r: (-r[1], r[0]))

    with OUTPUT.open("w", encoding="utf-8") as fh:
        fh.write("strong\tcount\tis_function\n")
        for code, total, is_function in rows:
            fh.write(f"{code}\t{total}\t{is_function}\n")

    n_func = sum(1 for _, _, f in rows if f)
    print(f"\nWrote {len(rows)} entries to {OUTPUT} "
          f"({n_func} function, {len(rows) - n_func} content)", file=sys.stderr)
    print("Top 10 by frequency:", file=sys.stderr)
    for code, total, is_function in rows[:10]:
        kind = "function" if is_function else "content"
        print(f"  {code}\t{total}\t{kind}", file=sys.stderr)


if __name__ == "__main__":
    main()
