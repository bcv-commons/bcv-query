"""Methodology tree: TA section → module → chunks."""
from __future__ import annotations

import sqlite3

from indexer import citations as citations_mod
from server.resolver import chunk_preview_from_card


def root(db: sqlite3.Connection, *, lang: str = "en") -> dict:
    rows = db.execute(
        """
        SELECT REPLACE(tag, 'section:', '') AS section, COUNT(DISTINCT doc_id) AS n
        FROM tags WHERE tag LIKE 'section:%' GROUP BY tag ORDER BY section
        """
    ).fetchall()
    return {
        "tree": "methodology", "lang": lang,
        "node": {"id": "root", "label": "Translation Methodology"},
        "children": [
            {"id": sec, "label": sec, "child_count": n, "url": f"/{lang}/methodology/{sec}"}
            for sec, n in rows
        ],
    }


def descend(db: sqlite3.Connection, path: list[str], *, lang: str = "en") -> dict:
    if not path:
        return root(db, lang=lang)
    section = path[0]
    if len(path) == 1:
        rows = db.execute(
            """
            SELECT REPLACE(t2.tag, 'module:', '') AS module, chunks.id
            FROM chunks
            JOIN documents ON documents.id = chunks.doc_id
            JOIN tags AS t1 ON t1.doc_id = documents.id AND t1.tag = ?
            JOIN tags AS t2 ON t2.doc_id = documents.id AND t2.tag LIKE 'module:%'
            ORDER BY module
            """,
            (f"section:{section}",),
        ).fetchall()
        cards = citations_mod.resolve_many(db, [r[1] for r in rows])
        return {
            "tree": "methodology", "lang": lang,
            "node": {"id": section, "label": section},
            "chunks": [chunk_preview_from_card(c, lang=lang) for c in cards],
        }
    module = path[1]
    rows = db.execute(
        """
        SELECT chunks.id
        FROM chunks
        JOIN documents ON documents.id = chunks.doc_id
        JOIN tags AS t1 ON t1.doc_id = documents.id AND t1.tag = ?
        JOIN tags AS t2 ON t2.doc_id = documents.id AND t2.tag = ?
        """,
        (f"section:{section}", f"module:{module}"),
    ).fetchall()
    cards = citations_mod.resolve_many(db, [r[0] for r in rows])
    return {
        "tree": "methodology", "lang": lang,
        "node": {"id": f"{section}/{module}", "label": module},
        "chunks": [chunk_preview_from_card(c, lang=lang) for c in cards],
    }
