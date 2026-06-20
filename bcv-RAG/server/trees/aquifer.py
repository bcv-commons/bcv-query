"""Aquifer collection view: per-repo browse."""
from __future__ import annotations

import sqlite3

from indexer import citations as citations_mod
from server.resolver import chunk_preview_from_card


def root(db: sqlite3.Connection, *, lang: str = "en") -> dict:
    rows = db.execute(
        """
        SELECT REPLACE(tag, 'aquifer:', '') AS repo, COUNT(DISTINCT doc_id) AS n
        FROM tags WHERE tag LIKE 'aquifer:%' GROUP BY tag ORDER BY repo
        """
    ).fetchall()
    return {
        "tree": "aquifer", "lang": lang,
        "node": {"id": "root", "label": "Aquifer Collections"},
        "children": [
            {"id": repo, "label": repo, "child_count": n, "url": f"/{lang}/aquifer/{repo}"}
            for repo, n in rows
        ],
    }


def descend(db: sqlite3.Connection, path: list[str], *, lang: str = "en") -> dict:
    if not path:
        return root(db, lang=lang)
    repo = path[0]
    rows = db.execute(
        """
        SELECT chunks.id
        FROM chunks
        JOIN documents ON documents.id = chunks.doc_id
        JOIN tags ON tags.doc_id = documents.id AND tags.tag = ?
        ORDER BY documents.source_path
        LIMIT 200
        """,
        (f"aquifer:{repo}",),
    ).fetchall()
    cards = citations_mod.resolve_many(db, [r[0] for r in rows])
    return {
        "tree": "aquifer", "lang": lang,
        "node": {"id": repo, "label": repo},
        "chunks": [chunk_preview_from_card(c, lang=lang) for c in cards],
    }
