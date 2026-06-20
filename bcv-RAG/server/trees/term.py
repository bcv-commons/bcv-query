"""Term tree: merged Door43 TW (term:/category:) + Aquifer ACAI (acai:type:id)."""
from __future__ import annotations

import sqlite3

from indexer import citations as citations_mod
from server.resolver import chunk_preview_from_card


def root(db: sqlite3.Connection, *, lang: str = "en") -> dict:
    children: list[dict] = []
    # Door43 TW categories (kt / names / other)
    rows = db.execute(
        """
        SELECT REPLACE(tag, 'category:', '') AS type, COUNT(DISTINCT doc_id) AS n
        FROM tags
        WHERE tag LIKE 'category:%'
        GROUP BY tag
        ORDER BY type
        """
    ).fetchall()
    for type_, n in rows:
        children.append({
            "id": type_, "label": f"Door43: {type_}", "child_count": n,
            "url": f"/{lang}/term/{type_}",
            "namespace": "door43",
        })
    # Aquifer ACAI types (person / keyterm / etc.)
    rows = db.execute(
        """
        SELECT
            CASE
                WHEN INSTR(SUBSTR(tag, 6), ':') > 0
                THEN SUBSTR(tag, 6, INSTR(SUBSTR(tag, 6), ':') - 1)
                ELSE SUBSTR(tag, 6)
            END AS type,
            COUNT(DISTINCT doc_id) AS n
        FROM tags
        WHERE tag LIKE 'acai:%'
        GROUP BY type
        ORDER BY type
        """
    ).fetchall()
    for type_, n in rows:
        children.append({
            "id": f"acai-{type_}", "label": f"ACAI: {type_}", "child_count": n,
            "url": f"/{lang}/term/acai-{type_}",
            "namespace": "acai",
        })
    return {
        "tree": "term", "lang": lang,
        "node": {"id": "root", "label": "Terms / Entities"},
        "children": children,
    }


def descend(db: sqlite3.Connection, path: list[str], *, lang: str = "en") -> dict:
    if not path:
        return root(db, lang=lang)
    head = path[0]
    if head.startswith("acai-"):
        return _acai_type(db, head[len("acai-"):], path[1:], lang=lang)
    return _door43_type(db, head, path[1:], lang=lang)


def _door43_type(db: sqlite3.Connection, type_: str, sub: list[str], *, lang: str) -> dict:
    if not sub:
        rows = db.execute(
            """
            SELECT REPLACE(t2.tag, 'term:', '') AS term, chunks.id
            FROM chunks
            JOIN documents ON documents.id = chunks.doc_id
            JOIN tags AS t1 ON t1.doc_id = documents.id AND t1.tag = ?
            JOIN tags AS t2 ON t2.doc_id = documents.id AND t2.tag LIKE 'term:%'
            ORDER BY term
            """,
            (f"category:{type_}",),
        ).fetchall()
        cards = citations_mod.resolve_many(db, [r[1] for r in rows])
        return {
            "tree": "term", "lang": lang,
            "node": {"id": type_, "label": f"Door43: {type_}", "namespace": "door43"},
            "chunks": [chunk_preview_from_card(c, lang=lang) for c in cards],
        }
    # Drill into a specific term
    term_id = sub[0]
    rows = db.execute(
        """
        SELECT chunks.id
        FROM chunks
        JOIN documents ON documents.id = chunks.doc_id
        JOIN tags AS t1 ON t1.doc_id = documents.id AND t1.tag = ?
        JOIN tags AS t2 ON t2.doc_id = documents.id AND t2.tag = ?
        """,
        (f"category:{type_}", f"term:{term_id}"),
    ).fetchall()
    # Merge Aquifer ACAI hits for the same name (best-effort)
    rows2 = db.execute(
        """
        SELECT chunks.id
        FROM chunks
        JOIN documents ON documents.id = chunks.doc_id
        JOIN tags ON tags.doc_id = documents.id
        WHERE LOWER(tags.tag) LIKE ?
        LIMIT 50
        """,
        (f"acai:%:{term_id.lower()}",),
    ).fetchall()
    chunk_ids = list({r[0] for r in rows} | {r[0] for r in rows2})
    cards = citations_mod.resolve_many(db, chunk_ids)
    return {
        "tree": "term", "lang": lang,
        "node": {"id": f"{type_}/{term_id}", "label": term_id, "namespace": "door43+acai"},
        "chunks": [chunk_preview_from_card(c, lang=lang) for c in cards],
    }


def _acai_type(db: sqlite3.Connection, acai_type: str, sub: list[str], *, lang: str) -> dict:
    if not sub:
        rows = db.execute(
            """
            SELECT
                SUBSTR(tag, ?) AS entity,
                COUNT(DISTINCT doc_id) AS n
            FROM tags
            WHERE tag LIKE ?
            GROUP BY entity
            ORDER BY entity
            """,
            (len(f"acai:{acai_type}:") + 1, f"acai:{acai_type}:%"),
        ).fetchall()
        return {
            "tree": "term", "lang": lang,
            "node": {"id": f"acai-{acai_type}", "label": f"ACAI: {acai_type}", "namespace": "acai"},
            "children": [
                {"id": entity, "label": entity, "child_count": n,
                 "url": f"/{lang}/term/acai-{acai_type}/{entity}"}
                for entity, n in rows
            ],
        }
    entity = sub[0]
    rows = db.execute(
        """
        SELECT DISTINCT chunks.id
        FROM chunks
        JOIN documents ON documents.id = chunks.doc_id
        JOIN tags ON tags.doc_id = documents.id AND tags.tag = ?
        LIMIT 100
        """,
        (f"acai:{acai_type}:{entity}",),
    ).fetchall()
    cards = citations_mod.resolve_many(db, [r[0] for r in rows])
    return {
        "tree": "term", "lang": lang,
        "node": {"id": f"acai-{acai_type}/{entity}", "label": entity, "namespace": "acai"},
        "chunks": [chunk_preview_from_card(c, lang=lang) for c in cards],
    }
