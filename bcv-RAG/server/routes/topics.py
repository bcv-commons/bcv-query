"""GET /api/topic/<id> — Nave's-style topic detail (verse list).

Powered by the `topics` + `topic_passages` tables populated by
`ingest.naves_topical`. Returns the topic name, source attribution,
and every passage (BBCCCVVV pair, decoded human form, scripture-tree URL)
that Nave's groups under this topic.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from indexer.references import BOOK_NAMES, NUMBER_TO_CODE, decode, human
from server.deps import get_db
from server.ratelimit import LIMIT_READ, limiter

router = APIRouter()


def _scripture_url_for(bb: int, lang: str) -> str | None:
    """BBCCCVVV → /<lang>/scripture/<testament>/<USFM>/<chap>/<verse>. None on
    decode failure (out-of-range integer)."""
    try:
        code, chap, verse = decode(bb)
    except ValueError:
        return None
    book_num = bb // 1_000_000
    testament = "ot" if book_num <= 39 else "nt"
    return f"/{lang}/scripture/{testament}/{code}/{chap}/{verse}"


def _humanize(start_bb: int, end_bb: int) -> str:
    try:
        return human(start_bb, end_bb)
    except Exception:
        return f"BBCCCVVV {start_bb}–{end_bb}"


@router.get("/topic/{topic_id}")
@limiter.limit(LIMIT_READ)
def get_topic(
    request: Request,
    topic_id: str,
    lang: str = "en",
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    row = db.execute(
        "SELECT id, name, source, metadata FROM topics WHERE id = ?",
        (topic_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"topic not found: {topic_id}")

    passages_rows = db.execute(
        "SELECT start_bbcccvvv, end_bbcccvvv FROM topic_passages "
        "WHERE topic_id = ? ORDER BY start_bbcccvvv",
        (topic_id,),
    ).fetchall()

    passages: list[dict[str, Any]] = []
    for s, e in passages_rows:
        url = _scripture_url_for(s, lang)
        passages.append({
            "start_bbcccvvv": s,
            "end_bbcccvvv": e,
            "human": _humanize(s, e),
            "url": url,
        })

    return {
        "id": row[0],
        "name": row[1],
        "source": row[2],
        "passage_count": len(passages),
        "passages": passages,
    }


@router.get("/topics")
@limiter.limit(LIMIT_READ)
def list_topics(
    request: Request,
    source: str | None = None,
    starts_with: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Alphabetical listing for the Topic tree's root + letter pages.

    Query params:
      source: filter by attribution ('naves' currently the only one)
      starts_with: filter to topics whose name starts with this prefix (case-insensitive)
      limit / offset: pagination (default limit=100)
    """
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=400, detail="limit must be 1..500")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")

    sql = "SELECT id, name, source FROM topics"
    where: list[str] = []
    params: list = []
    if source:
        where.append("source = ?")
        params.append(source)
    if starts_with:
        where.append("LOWER(name) LIKE ?")
        params.append(starts_with.lower() + "%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY name LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = db.execute(sql, params).fetchall()
    total_sql = "SELECT COUNT(*) FROM topics"
    if where:
        total_sql += " WHERE " + " AND ".join(where)
    total = db.execute(total_sql, params[:-2]).fetchone()[0]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "topics": [
            {"id": r[0], "name": r[1], "source": r[2]}
            for r in rows
        ],
    }
