"""GET /api/licenses — where the data of each route comes from, and its licence (server/licenses.py)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from server import licenses
from server.ratelimit import LIMIT_READ, limiter

router = APIRouter()


@router.get("/licenses")
@limiter.limit(LIMIT_READ)
def get_licenses(request: Request, path: str | None = None) -> dict:
    """Every source with its licence and required attribution, and for each route the sources it draws on. `path` (a route
    as listed, e.g. /api/search, or a concrete URL path like /api/chunk/abc) narrows it to that route."""
    if path is None:
        return licenses.register()
    out = licenses.for_path(path)
    if out is None:
        raise HTTPException(404, f"no route matches '{path}'")
    return out
