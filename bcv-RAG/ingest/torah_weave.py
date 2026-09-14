"""Moshe Kline's "Woven Torah" literary-unit structure — ingest.

Writes 86 literary units (Genesis-Deuteronomy) and their ~600 verse-range cells into
torah_units / torah_unit_cells (indexer/schema.sql). Structural pairing between cells (same
row_number+subdivision, different column_letter) is computed at query time by the MCP tool
(server/mcp/tools.py:torah_unit_lookup), not stored here — see that table's schema comment.

  python -m ingest.torah_weave              # read the staged JSON, write to index.db
  python -m ingest.torah_weave --reset       # delete existing torah_units rows first

Deviation from the standard ingest pattern
-------------------------------------------
Same reasoning as ingest/theographic.py: this is structural/graph data (a unit containing cells,
each a verse range), not chunk-shaped text, so it's written straight into dedicated tables rather
than through the markdown/MarkdownAdapter chunking path.

Source and licensing
---------------------
Moshe Kline, "Before Chapter and Verse: Reading the Woven Torah" (self-published, 2022; the dataset's
own `description` field additionally claims a 2025 Journal of Biblical Literature publication — that
claim is unverified here and NOT asserted by this ingest, only the dataset's own `citation` field is
used as source-of-record). CC BY 4.0, https://chaver.com. No live fetch step: the source is a single
small JSON file, staged once at ingest/_staging/torah_weave/torah-units.json (committed nowhere —
gitignored like every other staged source; re-copy it there from wherever you obtained it before
running this script).

IMPORTANT — what this is and is not: this project cites Kline's structure as published content, the
same way it consumes SDBH's domain tags as content (see server/mcp/tools.py's `semantic_domain`
equivalent on the shoresh side). It does NOT use this data to derive or validate anything else this
project builds — see internal-docs/text-anchored-semantics-plan.md for why that distinction is
load-bearing (SDBH's retirement as a *validation yardstick* was about avoiding exactly that
circularity, not about licensing).

Output
------
  torah_units      (unit_id, serial_number, book, unit_number, title, start_bbcccvvv, end_bbcccvvv,
                    format, irregular, unit_type, source)
  torah_unit_cells (unit_id, cell_label, row_number, column_letter, subdivision,
                    start_bbcccvvv, end_bbcccvvv)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from indexer.build import init_schema
from indexer.db import open_db
from indexer.env import load_env
from indexer.references import encode

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "indexer" / "index.db"
DEFAULT_STAGING = REPO_ROOT / "ingest" / "_staging" / "torah_weave" / "torah-units.json"

# Kline's dataset only ever covers the five Torah books, spelled out in full English — a 5-entry
# local map is simpler and more honest about scope than reusing the general-purpose, many-language
# indexer.references.BOOK_ALIASES machinery for a fixed, tiny, known set.
_BOOK_TO_USFM = {
    "Genesis": "GEN", "Exodus": "EXO", "Leviticus": "LEV", "Numbers": "NUM", "Deuteronomy": "DEU",
}

_CELL_LABEL_RE = re.compile(r"^(\d+)([A-Z]?)([a-z]?)$")
# Three shapes seen in the source: single verse '2:1'; same-chapter range '28:1-43' (no repeated
# chapter); cross-chapter range '1:6-2:3' (full 'chapter:verse' on both sides).
_RANGE_RE = re.compile(r"^(\d+):(\d+)(?:-(?:(\d+):)?(\d+))?$")


def _parse_range(book_usfm: str, verse_range: str) -> tuple[int, int]:
    """'1:6-1:8' / '28:1-43' / '2:1' (relative to book_usfm) -> (start_bbcccvvv, end_bbcccvvv)."""
    m = _RANGE_RE.match(verse_range)
    if not m:
        raise ValueError(f"unparsed verse range: {verse_range!r}")
    c1, v1, c2, v2 = m.groups()
    start = encode(book_usfm, int(c1), int(v1))
    if v2 is None:
        end = start
    else:
        end = encode(book_usfm, int(c2) if c2 else int(c1), int(v2))
    return start, end


def parse_units(data: dict) -> tuple[list[tuple], list[tuple]]:
    """Return (unit_rows, cell_rows) ready for executemany."""
    unit_rows: list[tuple] = []
    cell_rows: list[tuple] = []

    for unit in data["units"]:
        serial = unit["serial_number"]
        unit_id = f"torahunit:{serial}"
        book_usfm = _BOOK_TO_USFM[unit["book"]]
        start, end = _parse_range(book_usfm, unit["verse_range"])
        unit_rows.append((
            unit_id, serial, book_usfm, unit["unit_number"], unit["title"],
            start, end, unit["format"], int(unit["irregular"]), unit.get("type"),
        ))

        for label, cell_range in unit["cells_detail"].items():
            m = _CELL_LABEL_RE.match(label)
            if not m:
                print(f"  ! unparsed cell label {label!r} in unit {serial} — skipped", file=sys.stderr)
                continue
            row_s, col, sub = m.groups()
            c_start, c_end = _parse_range(book_usfm, cell_range)
            cell_rows.append((
                unit_id, label, int(row_s), col or None, sub or None, c_start, c_end,
            ))

    return unit_rows, cell_rows


def _write(db, unit_rows: list[tuple], cell_rows: list[tuple]) -> dict:
    db.executemany(
        "INSERT OR REPLACE INTO torah_units "
        "(unit_id, serial_number, book, unit_number, title, start_bbcccvvv, end_bbcccvvv, "
        " format, irregular, unit_type) VALUES (?,?,?,?,?,?,?,?,?,?)",
        unit_rows,
    )
    db.executemany(
        "INSERT OR REPLACE INTO torah_unit_cells "
        "(unit_id, cell_label, row_number, column_letter, subdivision, start_bbcccvvv, end_bbcccvvv) "
        "VALUES (?,?,?,?,?,?,?)",
        cell_rows,
    )
    db.commit()
    return {"units": len(unit_rows), "cells": len(cell_rows)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--reset", action="store_true", help="delete existing torah_units rows before ingest")
    args = ap.parse_args()

    load_env()

    if not args.staging.is_file():
        print(f"missing staged file: {args.staging} (see this script's docstring)", file=sys.stderr)
        return 2

    data = json.loads(args.staging.read_text(encoding="utf-8"))
    unit_rows, cell_rows = parse_units(data)
    print(f"  parsed: {len(unit_rows)} units, {len(cell_rows)} cells", flush=True)

    db = open_db(args.db)
    init_schema(db)  # CREATE … IF NOT EXISTS throughout — cheap to re-run

    if args.reset:
        db.execute("DELETE FROM torah_units")  # torah_unit_cells cascades via FK ON DELETE CASCADE
        db.commit()

    started = time.time()
    counts = _write(db, unit_rows, cell_rows)
    elapsed = time.time() - started

    db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
               ("torah_weave_indexed_at", str(int(time.time()))))
    db.commit()
    db.close()

    print(json.dumps({"elapsed_seconds": round(elapsed, 2), **counts}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
