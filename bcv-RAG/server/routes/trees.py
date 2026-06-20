"""GET /api/tree/<tree_name>[/...] — dispatch to tree builders.

GET /api/trees returns all tree roots with their first level of children
pre-expanded, so clients can render the full top-level navigation in one
round trip.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request

from server.deps import get_db
from server.ratelimit import LIMIT_READ, limiter
from server.trees import BUILDERS
from lang import canon

router = APIRouter()


_SKIP_TREES = {"bible", "pericope"}
_DEPTH1_ONLY = {"term", "topic"}


@router.get("/trees")
@limiter.limit(LIMIT_READ)
def trees_overview(request: Request, lang: str = "en", db: sqlite3.Connection = Depends(get_db)) -> dict:
    """All tree roots with first-level children pre-expanded (depth=2).

    Skips: ``bible`` (standard book structure, clients build locally).
    Depth-1 only: ``term``, ``topic`` (too many second-level entries).
    """
    lang = canon(lang)
    trees: dict[str, dict] = {}
    for name, builder in BUILDERS.items():
        if name in _SKIP_TREES:
            continue
        try:
            root_data = builder.root(db, lang=lang)
        except Exception:
            continue
        if name not in _DEPTH1_ONLY:
            for child in root_data.get("children", []):
                child_id = child.get("id")
                if child_id is None:
                    continue
                try:
                    child_data = builder.descend(db, [str(child_id)], lang=lang)
                    child["children"] = child_data.get("children", [])
                except Exception:
                    pass
        trees[name] = root_data
    return {"lang": lang, "trees": trees}


@router.get("/tree/{tree_name}")
@limiter.limit(LIMIT_READ)
def tree_root(request: Request, tree_name: str, lang: str = "en", db: sqlite3.Connection = Depends(get_db)) -> dict:
    builder = BUILDERS.get(tree_name)
    if builder is None:
        raise HTTPException(status_code=404, detail=f"unknown tree: {tree_name}")
    lang = canon(lang)
    try:
        return builder.root(db, lang=lang)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/tree/{tree_name}/{path:path}")
@limiter.limit(LIMIT_READ)
def tree_descend(
    request: Request,
    tree_name: str,
    path: str,
    lang: str = "en",
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    builder = BUILDERS.get(tree_name)
    if builder is None:
        raise HTTPException(status_code=404, detail=f"unknown tree: {tree_name}")
    parts = [p for p in path.split("/") if p]
    lang = canon(lang)
    try:
        return builder.descend(db, parts, lang=lang)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
