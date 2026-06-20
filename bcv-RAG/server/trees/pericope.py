"""Pericope view: passage range → all overlapping chunks (no children, leaf-only)."""
from __future__ import annotations

import sqlite3

from indexer import citations as citations_mod
from indexer.references import human
from server.resolver import chunk_preview_from_card


def root(db: sqlite3.Connection, *, lang: str = "en") -> dict:
    return {
        "tree": "pericope", "lang": lang,
        "node": {"id": "root", "label": "Pericope view"},
        "children": [],
        "note": "Pericope is a leaf-only view; navigate to /pericope/<start>-<end> directly.",
    }


def descend(db: sqlite3.Connection, path: list[str], *, lang: str = "en") -> dict:
    if not path:
        return root(db, lang=lang)
    spec = path[0]
    try:
        s_str, e_str = spec.split("-", 1)
        start, end = int(s_str), int(e_str)
    except ValueError:
        raise ValueError(f"pericope path must be <start>-<end> (BBCCCVVV-BBCCCVVV); got {spec!r}")
    rows = db.execute(
        """
        SELECT DISTINCT chunks.id
        FROM chunks
        JOIN passage_refs ON passage_refs.doc_id = chunks.doc_id
        WHERE passage_refs.start_bbcccvvv <= ?
          AND passage_refs.end_bbcccvvv   >= ?
        """,
        (end, start),
    ).fetchall()
    cards = citations_mod.resolve_many(db, [r[0] for r in rows])
    try:
        label = human(start, end)
    except Exception:
        label = f"{start}-{end}"
    return {
        "tree": "pericope", "lang": lang,
        "node": {"id": spec, "label": label, "start": start, "end": end},
        "chunks": [chunk_preview_from_card(c, lang=lang) for c in cards],
    }
