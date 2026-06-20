"""Source tree: provider → resource → sub → document."""
from __future__ import annotations

import sqlite3

from indexer import citations as citations_mod
from indexer.references import BOOK_NAMES
from server.resolver import chunk_preview_from_card

DOOR43_RESOURCES = ["ult", "ust", "tn", "tq", "tw", "ta"]


def root(db: sqlite3.Connection, *, lang: str = "en") -> dict:
    door43_count = db.execute(
        """
        SELECT COUNT(DISTINCT documents.id)
        FROM documents
        WHERE documents.id NOT IN (SELECT doc_id FROM tags WHERE tag = 'resource:aquifer')
        """
    ).fetchone()[0]
    aquifer_count = db.execute(
        "SELECT COUNT(DISTINCT doc_id) FROM tags WHERE tag = 'resource:aquifer'"
    ).fetchone()[0]
    return {
        "tree": "source",
        "lang": lang,
        "node": {"id": "root", "label": "Sources"},
        "children": [
            {"id": "door43", "label": "Door43 / unfoldingWord",
             "child_count": door43_count, "url": f"/{lang}/source/door43"},
            {"id": "aquifer", "label": "Aquifer",
             "child_count": aquifer_count, "url": f"/{lang}/source/aquifer"},
        ],
    }


def descend(db: sqlite3.Connection, path: list[str], *, lang: str = "en") -> dict:
    if not path:
        return root(db, lang=lang)
    if path[0] == "door43":
        return _door43(db, path[1:], lang=lang)
    if path[0] == "aquifer":
        return _aquifer(db, path[1:], lang=lang)
    raise ValueError(f"unknown source provider: {path[0]}")


# ---------- Door43 ----------

def _door43(db: sqlite3.Connection, sub: list[str], *, lang: str) -> dict:
    if not sub:
        children = []
        for res in DOOR43_RESOURCES:
            n = db.execute(
                "SELECT COUNT(DISTINCT doc_id) FROM tags WHERE tag = ?",
                (f"resource:{res}",),
            ).fetchone()[0]
            if n > 0:
                children.append({
                    "id": res, "label": res.upper(), "child_count": n,
                    "url": f"/{lang}/source/door43/{res}",
                })
        return {
            "tree": "source", "lang": lang,
            "node": {"id": "door43", "label": "Door43"},
            "children": children,
        }
    res = sub[0]
    if res not in DOOR43_RESOURCES:
        raise ValueError(f"unknown Door43 resource: {res}")
    rest = sub[1:]
    if res in ("ult", "ust", "tn", "tq"):
        return _door43_per_book(db, res, rest, lang=lang)
    if res == "tw":
        return _door43_tw(db, rest, lang=lang)
    if res == "ta":
        return _door43_ta(db, rest, lang=lang)
    raise ValueError(f"unsupported Door43 resource: {res}")


def _door43_per_book(db: sqlite3.Connection, res: str, sub: list[str], *, lang: str) -> dict:
    if not sub:
        rows = db.execute(
            """
            SELECT DISTINCT REPLACE(t2.tag, 'book:', '') AS book,
                   COUNT(DISTINCT documents.id) AS n
            FROM documents
            JOIN tags AS t1 ON t1.doc_id = documents.id AND t1.tag = ?
            JOIN tags AS t2 ON t2.doc_id = documents.id AND t2.tag LIKE 'book:%'
            GROUP BY book
            ORDER BY book
            """,
            (f"resource:{res}",),
        ).fetchall()
        return {
            "tree": "source", "lang": lang,
            "node": {"id": res, "label": res.upper()},
            "children": [
                {"id": book, "label": BOOK_NAMES.get(book, book), "child_count": n,
                 "url": f"/{lang}/source/door43/{res}/{book}"}
                for book, n in rows
            ],
        }
    book = sub[0].upper()
    rows = db.execute(
        """
        SELECT chunks.id
        FROM chunks
        JOIN documents ON documents.id = chunks.doc_id
        JOIN tags AS t1 ON t1.doc_id = documents.id AND t1.tag = ?
        JOIN tags AS t2 ON t2.doc_id = documents.id AND t2.tag = ?
        ORDER BY documents.source_path
        """,
        (f"resource:{res}", f"book:{book}"),
    ).fetchall()
    cards = citations_mod.resolve_many(db, [r[0] for r in rows])
    return {
        "tree": "source", "lang": lang,
        "node": {"id": f"{res}/{book}",
                 "label": f"{res.upper()} — {BOOK_NAMES.get(book, book)}"},
        "chunks": [chunk_preview_from_card(c, lang=lang) for c in cards],
    }


def _door43_tw(db: sqlite3.Connection, sub: list[str], *, lang: str) -> dict:
    if not sub:
        rows = db.execute(
            """
            SELECT REPLACE(t2.tag, 'category:', '') AS cat, COUNT(DISTINCT documents.id) AS n
            FROM documents
            JOIN tags AS t1 ON t1.doc_id = documents.id AND t1.tag = 'resource:tw'
            JOIN tags AS t2 ON t2.doc_id = documents.id AND t2.tag LIKE 'category:%'
            GROUP BY cat
            ORDER BY cat
            """
        ).fetchall()
        return {
            "tree": "source", "lang": lang,
            "node": {"id": "tw", "label": "Translation Words"},
            "children": [
                {"id": cat, "label": cat, "child_count": n,
                 "url": f"/{lang}/source/door43/tw/{cat}"}
                for cat, n in rows
            ],
        }
    cat = sub[0]
    if len(sub) == 1:
        rows = db.execute(
            """
            SELECT REPLACE(t3.tag, 'term:', '') AS term, chunks.id
            FROM chunks
            JOIN documents ON documents.id = chunks.doc_id
            JOIN tags AS t1 ON t1.doc_id = documents.id AND t1.tag = 'resource:tw'
            JOIN tags AS t2 ON t2.doc_id = documents.id AND t2.tag = ?
            JOIN tags AS t3 ON t3.doc_id = documents.id AND t3.tag LIKE 'term:%'
            ORDER BY term
            """,
            (f"category:{cat}",),
        ).fetchall()
        chunk_ids = [r[1] for r in rows]
        cards = citations_mod.resolve_many(db, chunk_ids)
        return {
            "tree": "source", "lang": lang,
            "node": {"id": f"tw/{cat}", "label": f"TW — {cat}"},
            "chunks": [chunk_preview_from_card(c, lang=lang) for c in cards],
        }
    raise ValueError(f"door43 tw path too deep: {sub}")


def _door43_ta(db: sqlite3.Connection, sub: list[str], *, lang: str) -> dict:
    if not sub:
        rows = db.execute(
            """
            SELECT REPLACE(t2.tag, 'section:', '') AS sec, COUNT(DISTINCT documents.id) AS n
            FROM documents
            JOIN tags AS t1 ON t1.doc_id = documents.id AND t1.tag = 'resource:ta'
            JOIN tags AS t2 ON t2.doc_id = documents.id AND t2.tag LIKE 'section:%'
            GROUP BY sec
            ORDER BY sec
            """
        ).fetchall()
        return {
            "tree": "source", "lang": lang,
            "node": {"id": "ta", "label": "Translation Academy"},
            "children": [
                {"id": sec, "label": sec, "child_count": n,
                 "url": f"/{lang}/source/door43/ta/{sec}"}
                for sec, n in rows
            ],
        }
    sec = sub[0]
    rows = db.execute(
        """
        SELECT chunks.id
        FROM chunks
        JOIN documents ON documents.id = chunks.doc_id
        JOIN tags AS t1 ON t1.doc_id = documents.id AND t1.tag = 'resource:ta'
        JOIN tags AS t2 ON t2.doc_id = documents.id AND t2.tag = ?
        ORDER BY documents.title
        """,
        (f"section:{sec}",),
    ).fetchall()
    cards = citations_mod.resolve_many(db, [r[0] for r in rows])
    return {
        "tree": "source", "lang": lang,
        "node": {"id": f"ta/{sec}", "label": f"TA — {sec}"},
        "chunks": [chunk_preview_from_card(c, lang=lang) for c in cards],
    }


# ---------- Aquifer ----------

def _aquifer(db: sqlite3.Connection, sub: list[str], *, lang: str) -> dict:
    if not sub:
        rows = db.execute(
            """
            SELECT REPLACE(tag, 'aquifer:', '') AS repo, COUNT(DISTINCT doc_id) AS n
            FROM tags
            WHERE tag LIKE 'aquifer:%'
            GROUP BY tag
            ORDER BY repo
            """
        ).fetchall()
        return {
            "tree": "source", "lang": lang,
            "node": {"id": "aquifer", "label": "Aquifer"},
            "children": [
                {"id": repo, "label": repo, "child_count": n,
                 "url": f"/{lang}/source/aquifer/{repo}"}
                for repo, n in rows
            ],
        }
    repo = sub[0]
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
        "tree": "source", "lang": lang,
        "node": {"id": repo, "label": repo},
        "chunks": [chunk_preview_from_card(c, lang=lang) for c in cards],
    }
