"""The text faults table (text_faults/text_faults.tsv; see its README): faults found in our texts and the fix applied."""
from __future__ import annotations

import csv
from pathlib import Path

TABLE = Path(__file__).resolve().parent / "text_faults" / "text_faults.tsv"


def load(edition: str | None = None) -> dict[str, dict]:
    """{word_id: row} of the open faults (of one edition)"""
    with open(TABLE, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))
    return {r["word_id"]: r for r in rows if r["status"] == "open" and (edition is None or r["edition"] == edition)}
