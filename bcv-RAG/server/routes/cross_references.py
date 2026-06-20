"""GET /api/cross-references/<bbcccvvv> — TSK + BSB-parallel cross-refs.

Returns the curated set of related verses for a single source verse.
Backed by the `cross_references` table populated by `ingest.bsb`
(currently TSK + BSB parallel-passage attributions).
"""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from indexer.references import decode, human
from server.deps import get_db
from server.ratelimit import LIMIT_READ, limiter

router = APIRouter()


def _scripture_url_for(bb: int, lang: str) -> str | None:
    try:
        code, chap, verse = decode(bb)
    except ValueError:
        return None
    book_num = bb // 1_000_000
    testament = "ot" if book_num <= 39 else "nt"
    return f"/{lang}/scripture/{testament}/{code}/{chap}/{verse}"


@router.get("/cross-references/{bbcccvvv}")
@limiter.limit(LIMIT_READ)
def get_cross_references(
    request: Request,
    bbcccvvv: int,
    lang: str = "en",
    source: str | None = Query(None, description="'tsk' | 'bsb-parallel' | None for all"),
    limit: int = 100,
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=400, detail="limit must be 1..500")
    try:
        decode(bbcccvvv)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"bad bbcccvvv: {bbcccvvv}")

    sql = (
        "SELECT target_start_bbcccvvv, target_end_bbcccvvv, source_attribution, rank "
        "FROM cross_references WHERE source_bbcccvvv = ?"
    )
    params: list = [bbcccvvv]
    if source:
        sql += " AND source_attribution = ?"
        params.append(source)
    # 'rank' may be NULL for sources without explicit ordering; sort NULLs last.
    sql += " ORDER BY (rank IS NULL), rank ASC, target_start_bbcccvvv ASC LIMIT ?"
    params.append(limit)

    rows = db.execute(sql, params).fetchall()

    refs: list[dict[str, Any]] = []
    for s, e, attr, rank in rows:
        try:
            h = human(s, e)
        except Exception:
            h = f"BBCCCVVV {s}-{e}"
        refs.append({
            "target_start_bbcccvvv": s,
            "target_end_bbcccvvv": e,
            "human": h,
            "url": _scripture_url_for(s, lang),
            "source": attr,
            "rank": rank,
        })

    try:
        source_human = human(bbcccvvv, bbcccvvv)
    except Exception:
        source_human = f"BBCCCVVV {bbcccvvv}"

    return {
        "source_passage": {
            "bbcccvvv": bbcccvvv,
            "human": source_human,
            "url": _scripture_url_for(bbcccvvv, lang),
        },
        "filters": {"source": source},
        "count": len(refs),
        "cross_references": refs,
    }
