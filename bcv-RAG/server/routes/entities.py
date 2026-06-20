"""GET /api/entity/<id> — Theographic-style entity detail.

Returns the entity row's metadata (Theographic + TIPNR + OpenBible
overlays merged via stage-2 ingest), the relations graph (one-hop
edges in both directions), and the verse list.

Also exposes GET /api/entities for Entity-tree pagination.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

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


@router.get("/entity/{entity_id:path}")
@limiter.limit(LIMIT_READ)
def get_entity(
    request: Request,
    entity_id: str,
    lang: str = "en",
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """`entity_id` carries an embedded colon (`person:david_994`); the
    `:path` route hint above lets FastAPI keep the colon segment intact."""
    row = db.execute(
        "SELECT id, type, name, metadata FROM entities WHERE id = ?",
        (entity_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"entity not found: {entity_id}")

    try:
        metadata = json.loads(row[3]) if row[3] else {}
    except json.JSONDecodeError:
        metadata = {}

    # Outgoing relations (this entity is the source).
    out_rows = db.execute(
        """
        SELECT er.target_id, er.relation, e.name, e.type
        FROM entity_relations er
        LEFT JOIN entities e ON e.id = er.target_id
        WHERE er.source_id = ?
        ORDER BY er.relation, e.name
        """,
        (entity_id,),
    ).fetchall()

    # Incoming (this entity is the target). Useful UX: "father-of [child]" can
    # also be viewed from the child as "is-child-of [father]".
    in_rows = db.execute(
        """
        SELECT er.source_id, er.relation, e.name, e.type
        FROM entity_relations er
        LEFT JOIN entities e ON e.id = er.source_id
        WHERE er.target_id = ?
        ORDER BY er.relation, e.name
        """,
        (entity_id,),
    ).fetchall()

    relations: list[dict[str, Any]] = []
    for tgt, rel, name, typ in out_rows:
        relations.append({
            "direction": "outgoing",
            "relation": rel,
            "target_id": tgt,
            "target_name": name,
            "target_type": typ,
        })
    for src, rel, name, typ in in_rows:
        relations.append({
            "direction": "incoming",
            "relation": rel,
            "source_id": src,
            "source_name": name,
            "source_type": typ,
        })

    # Verse list (deduped passages this entity is mentioned in).
    passages_rows = db.execute(
        "SELECT start_bbcccvvv, end_bbcccvvv FROM entity_passages "
        "WHERE entity_id = ? ORDER BY start_bbcccvvv",
        (entity_id,),
    ).fetchall()
    passages = []
    for s, e in passages_rows:
        try:
            h = human(s, e)
        except Exception:
            h = f"BBCCCVVV {s}-{e}"
        passages.append({
            "start_bbcccvvv": s,
            "end_bbcccvvv": e,
            "human": h,
            "url": _scripture_url_for(s, lang),
        })

    return {
        "id": row[0],
        "type": row[1],
        "name": row[2],
        "metadata": metadata,
        "relation_count": len(relations),
        "relations": relations,
        "passage_count": len(passages),
        "passages": passages,
    }


@router.get("/entities")
@limiter.limit(LIMIT_READ)
def list_entities(
    request: Request,
    type: str | None = None,
    starts_with: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Pagination listing for Entity-tree pages.

    Query params:
      type: filter by entity type (person | place | event | deity)
      starts_with: case-insensitive name prefix
      limit / offset: pagination (default limit=100, max 500)
    """
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=400, detail="limit must be 1..500")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")

    sql = "SELECT id, type, name FROM entities"
    where: list[str] = []
    params: list = []
    if type:
        where.append("type = ?")
        params.append(type)
    if starts_with:
        where.append("LOWER(name) LIKE ?")
        params.append(starts_with.lower() + "%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY name, id LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = db.execute(sql, params).fetchall()

    total_sql = "SELECT COUNT(*) FROM entities"
    if where:
        total_sql += " WHERE " + " AND ".join(where)
    total = db.execute(total_sql, params[:-2]).fetchone()[0]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "entities": [
            {"id": r[0], "type": r[1], "name": r[2]}
            for r in rows
        ],
    }
