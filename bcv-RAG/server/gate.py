"""Registration gate (mechanism A) + coarse rate limiting, as one app-level middleware.

Transport-agnostic on purpose — it runs over every path (REST + /mcp, whatever serves
/mcp), so it survives the MCP transport swap.

- **Auth / registration:** every request needs a valid API key (`Authorization: Bearer …`
  or `X-API-Key: …`), except a small allowlist (health, docs, root, CORS preflight).
  `verify()` is the single check — swap it for a per-client keys table later without
  touching call sites (mechanism A → B/C).
- **Rate limit:** fixed 60s window per **identity** (the API key if present, else client
  IP), tiered — paid paths (LLM/semantic) get a tighter cap. In-memory / per-process
  (single-instance assumption; use a shared store to scale horizontally). Layers under
  the finer slowapi limit on /api/ask.
"""
from __future__ import annotations

import os
import time

from fastapi import Request
from fastapi.responses import JSONResponse

from server.auth import verify, _present_password
from server.ratelimit import _client_ip

_ALLOW = {"/", "/api/health", "/favicon.ico"}


def _allowed(path: str) -> bool:
    return path in _ALLOW or path.startswith(("/docs", "/redoc", "/openapi"))


_WINDOW = 60.0
LIMIT_DEFAULT = int(os.environ.get("BTMCP_RL_PER_MIN", "120"))    # keyless-ish / $0 traffic
LIMIT_PAID = int(os.environ.get("BTMCP_RL_PAID_PER_MIN", "20"))   # LLM / semantic embedding
_PAID_PREFIXES = ("/api/ask", "/api/study")

_state: dict = {"window": -1, "hits": {}}


def _identity(request: Request) -> str:
    key = _present_password(request.headers.get("authorization"),
                           request.headers.get("x-api-key"))
    return f"k:{key[:16]}" if key else f"ip:{_client_ip(request)}"


def _is_paid(request: Request) -> bool:
    p = request.url.path
    if p.startswith(_PAID_PREFIXES):
        return True
    return p == "/api/search" and str(request.query_params.get("semantic", "")).lower() in ("1", "true", "yes")


def _rate_ok(ident: str, paid: bool) -> bool:
    """Fixed-window counter; the whole window resets each minute (bounded memory)."""
    w = int(time.monotonic() // _WINDOW)
    if w != _state["window"]:
        _state["window"], _state["hits"] = w, {}
    hits = _state["hits"]
    bucket = f"{ident}|{'paid' if paid else 'std'}"
    hits[bucket] = hits.get(bucket, 0) + 1
    return hits[bucket] <= (LIMIT_PAID if paid else LIMIT_DEFAULT)


async def gate(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or _allowed(path):
        return await call_next(request)
    if not verify(request.headers.get("authorization"), request.headers.get("x-api-key")):
        return JSONResponse(status_code=401,
                            content={"detail": "registration required: valid API key needed "
                                               "(Authorization: Bearer <key> or X-API-Key)"})
    paid = _is_paid(request)
    if not _rate_ok(_identity(request), paid):
        return JSONResponse(status_code=429, content={"detail": "rate limit exceeded"},
                            headers={"Retry-After": str(int(_WINDOW))})
    return await call_next(request)
