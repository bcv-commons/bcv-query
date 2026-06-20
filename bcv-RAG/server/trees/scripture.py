"""Scripture tree: testament → book → chapter → verse → chunks."""
from __future__ import annotations

import sqlite3

from indexer.references import BOOK_NAMES, BOOK_NUMBERS, NUMBER_TO_CODE, encode
from server.resolver import chunk_preview_from_card
from indexer import citations as citations_mod

OT = "ot"
NT = "nt"


def root(db: sqlite3.Connection, *, lang: str = "en") -> dict:
    return {
        "tree": "scripture",
        "lang": lang,
        "node": {"id": "root", "label": "Scripture"},
        "children": [
            {"id": OT, "label": "Old Testament", "child_count": _book_count(db, OT),
             "url": f"/{lang}/scripture/{OT}"},
            {"id": NT, "label": "New Testament", "child_count": _book_count(db, NT),
             "url": f"/{lang}/scripture/{NT}"},
        ],
    }


def descend(db: sqlite3.Connection, path: list[str], *, lang: str = "en") -> dict:
    if not path:
        return root(db, lang=lang)
    if len(path) == 1:
        return _testament_view(db, path[0], lang=lang)
    if len(path) == 2:
        return _book_view(db, path[0], path[1], lang=lang)
    if len(path) == 3:
        return _chapter_view(db, path[0], path[1], int(path[2]), lang=lang)
    if len(path) == 4:
        return _verse_leaf(db, path[0], path[1], int(path[2]), int(path[3]), lang=lang)
    raise ValueError(f"scripture path too deep: {path}")


# ---------- helpers ----------

def _book_count(db: sqlite3.Connection, testament: str) -> int:
    return _book_count_raw(db, testament)


def _book_count_raw(db: sqlite3.Connection, testament: str) -> int:
    lo, hi = (1, 39) if testament == OT else (40, 66)
    row = db.execute(
        """
        SELECT COUNT(DISTINCT start_bbcccvvv / 1000000)
        FROM passage_refs
        WHERE start_bbcccvvv >= ? AND start_bbcccvvv < ?
        """,
        (lo * 1_000_000, (hi + 1) * 1_000_000),
    ).fetchone()
    return row[0] if row else 0


def _testament_view(db: sqlite3.Connection, testament: str, *, lang: str) -> dict:
    if testament not in (OT, NT):
        raise ValueError(f"unknown testament: {testament}")
    lo, hi = (1, 39) if testament == OT else (40, 66)
    rows = db.execute(
        """
        SELECT DISTINCT start_bbcccvvv / 1000000 AS book_num
        FROM passage_refs
        WHERE start_bbcccvvv >= ? AND start_bbcccvvv < ?
        ORDER BY book_num
        """,
        (lo * 1_000_000, (hi + 1) * 1_000_000),
    ).fetchall()
    children = []
    for (book_num,) in rows:
        code = NUMBER_TO_CODE.get(book_num)
        if not code:
            continue
        children.append({
            "id": code,
            "label": BOOK_NAMES.get(code, code),
            "url": f"/{lang}/scripture/{testament}/{code}",
        })
    return {
        "tree": "scripture",
        "lang": lang,
        "node": {"id": testament, "label": "Old Testament" if testament == OT else "New Testament"},
        "children": children,
    }


def _book_view(db: sqlite3.Connection, testament: str, book_code: str, *, lang: str) -> dict:
    book_num = BOOK_NUMBERS.get(book_code.upper())
    if not book_num:
        raise ValueError(f"unknown book: {book_code}")
    rows = db.execute(
        """
        SELECT DISTINCT (start_bbcccvvv / 1000) % 1000 AS chapter
        FROM passage_refs
        WHERE start_bbcccvvv >= ? AND start_bbcccvvv < ?
        ORDER BY chapter
        """,
        (book_num * 1_000_000, (book_num + 1) * 1_000_000),
    ).fetchall()
    children = []
    for (chap,) in rows:
        if chap == 0:  # whole-book inheritance from TW articles
            continue
        children.append({
            "id": str(chap),
            "label": f"Chapter {chap}",
            "url": f"/{lang}/scripture/{testament}/{book_code.upper()}/{chap}",
        })
    return {
        "tree": "scripture",
        "lang": lang,
        "node": {
            "id": book_code.upper(),
            "label": BOOK_NAMES.get(book_code.upper(), book_code.upper()),
            "testament": testament,
        },
        "children": children,
    }


def _chapter_view(db: sqlite3.Connection, testament: str, book_code: str, chapter: int, *, lang: str) -> dict:
    book_num = BOOK_NUMBERS.get(book_code.upper())
    if not book_num:
        raise ValueError(f"unknown book: {book_code}")
    chapter_base = book_num * 1_000_000 + chapter * 1_000
    rows = db.execute(
        """
        SELECT DISTINCT start_bbcccvvv % 1000 AS verse
        FROM passage_refs
        WHERE start_bbcccvvv >= ? AND start_bbcccvvv < ?
        ORDER BY verse
        """,
        (chapter_base, chapter_base + 1_000),
    ).fetchall()
    children = []
    for (verse,) in rows:
        if verse == 0:
            continue
        children.append({
            "id": str(verse),
            "label": f"{BOOK_NAMES.get(book_code.upper(), book_code)} {chapter}:{verse}",
            "url": f"/{lang}/scripture/{testament}/{book_code.upper()}/{chapter}/{verse}",
        })
    return {
        "tree": "scripture",
        "lang": lang,
        "node": {
            "id": f"{book_code.upper()}/{chapter}",
            "label": f"{BOOK_NAMES.get(book_code.upper(), book_code)} {chapter}",
            "book": book_code.upper(),
            "chapter": chapter,
        },
        "children": children,
    }


def _verse_leaf(db: sqlite3.Connection, testament: str, book_code: str, chapter: int, verse: int, *, lang: str) -> dict:
    bb = encode(book_code.upper(), chapter, verse)
    rows = db.execute(
        """
        SELECT DISTINCT chunks.id
        FROM chunks
        JOIN passage_refs ON passage_refs.doc_id = chunks.doc_id
        WHERE passage_refs.start_bbcccvvv <= ?
          AND passage_refs.end_bbcccvvv   >= ?
        """,
        (bb, bb),
    ).fetchall()
    chunk_ids = [r[0] for r in rows]
    cards = citations_mod.resolve_many(db, chunk_ids)
    chunks = [chunk_preview_from_card(c, lang=lang) for c in cards]
    return {
        "tree": "scripture",
        "lang": lang,
        "node": {
            "passage": f"{BOOK_NAMES.get(book_code.upper(), book_code)} {chapter}:{verse}",
            "bbcccvvv": bb,
            "book": book_code.upper(),
            "chapter": chapter,
            "verse": verse,
        },
        "chunks": chunks,
    }
