"""GET /api/concordance/<word> — exhaustive English-word → verse-list.

Backed by the `english_concordance` table built from BSB chunks via
`ingest.english_concordance`. Returns every BSB verse that contains the
given English word (case-insensitive, no stemming — this is the
exhaustive listing companion to FTS5's BM25-ranked search).
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from indexer.references import decode, human
from server.deps import get_db
from server.ratelimit import LIMIT_READ, limiter

router = APIRouter()

_WORD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9'\-]*$")


def _scripture_url_for(bb: int, lang: str) -> str | None:
    try:
        code, chap, verse = decode(bb)
    except ValueError:
        return None
    book_num = bb // 1_000_000
    testament = "ot" if book_num <= 39 else "nt"
    return f"/{lang}/scripture/{testament}/{code}/{chap}/{verse}"


def _bible_url_for(bb: int, lang: str) -> str | None:
    """The Bible tree (BSB) — preferred destination for concordance hits."""
    try:
        code, chap, verse = decode(bb)
    except ValueError:
        return None
    book_num = bb // 1_000_000
    testament = "ot" if book_num <= 39 else "nt"
    return f"/{lang}/bible/{testament}/{code}/{chap}/{verse}"


@router.get("/concordance/{word}")
@limiter.limit(LIMIT_READ)
def get_concordance(
    request: Request,
    word: str,
    lang: str = "en",
    limit: int = 500,
    offset: int = 0,
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    if not _WORD_RE.match(word):
        raise HTTPException(status_code=400, detail="word must match [A-Za-z][A-Za-z0-9'-]*")
    if not 1 <= limit <= 2000:
        raise HTTPException(status_code=400, detail="limit must be 1..2000")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")

    norm = word.lower()
    total = db.execute(
        "SELECT COUNT(*) FROM english_concordance WHERE word_normalized = ?", (norm,)
    ).fetchone()[0]
    if total == 0:
        raise HTTPException(status_code=404, detail=f"word not in concordance: {word!r}")

    rows = db.execute(
        "SELECT bbcccvvv FROM english_concordance "
        "WHERE word_normalized = ? ORDER BY bbcccvvv LIMIT ? OFFSET ?",
        (norm, limit, offset),
    ).fetchall()

    verses: list[dict[str, Any]] = []
    for (bb,) in rows:
        try:
            h = human(bb, bb)
        except Exception:
            h = f"BBCCCVVV {bb}"
        verses.append({
            "bbcccvvv": bb,
            "human": h,
            "url": _bible_url_for(bb, lang),
            "scripture_url": _scripture_url_for(bb, lang),
        })

    return {
        "word": word,
        "word_normalized": norm,
        "verse_count": total,
        "limit": limit,
        "offset": offset,
        "verses": verses,
    }
