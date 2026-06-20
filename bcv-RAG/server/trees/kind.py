"""Kind tree: content shape (kind:*) → list of chunks."""
from __future__ import annotations

import sqlite3

from indexer import citations as citations_mod
from server.resolver import chunk_preview_from_card


def root(db: sqlite3.Connection, *, lang: str = "en") -> dict:
    rows = db.execute(
        """
        SELECT REPLACE(tag, 'kind:', '') AS kind, COUNT(DISTINCT doc_id) AS n
        FROM tags WHERE tag LIKE 'kind:%' GROUP BY tag ORDER BY kind
        """
    ).fetchall()
    return {
        "tree": "kind", "lang": lang,
        "node": {"id": "root", "label": "Kinds"},
        "children": [
            {"id": kind, "label": kind, "child_count": n, "url": f"/{lang}/kind/{kind}"}
            for kind, n in rows
        ],
    }


def descend(db: sqlite3.Connection, path: list[str], *, lang: str = "en") -> dict:
    if not path:
        return root(db, lang=lang)
    kind = path[0]
    rows = db.execute(
        """
        SELECT chunks.id
        FROM chunks
        JOIN documents ON documents.id = chunks.doc_id
        JOIN tags ON tags.doc_id = documents.id AND tags.tag = ?
        ORDER BY documents.source_path
        LIMIT 300
        """,
        (f"kind:{kind}",),
    ).fetchall()
    cards = citations_mod.resolve_many(db, [r[0] for r in rows])
    return {
        "tree": "kind", "lang": lang,
        "node": {"id": kind, "label": kind},
        "chunks": [chunk_preview_from_card(c, lang=lang) for c in cards],
    }
