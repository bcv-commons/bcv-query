"""Access gate + coarse rate limiting, as one app-level middleware.

Transport-agnostic on purpose — it runs over every path (REST + /mcp, whatever serves
/mcp), so it survives the MCP transport swap.

Policy (chosen balance): on REST, only **synthesis** (the LLM call — real $) is worth
gating; everything else is open (anonymous but rate-limited). "Gated" = requires a key:
  - **LLM synthesis** — `/api/ask`, `/api/ask/branched`,
  - the whole **MCP** surface (`/mcp`) — registration for the tool surface,
  - **write** methods (PUT/PATCH/DELETE) — future-proofing; none today.
Everything else is open — semantic search included: embedding is Cloudflare BGE-M3 ($0),
so it's not worth gating (revisit if you switch to a paid embedding provider). Open:
`/api/search` (incl. `?semantic=true`), `/api/search/branched`, `/api/study`, concordance,
cross-refs, topics, entities, trees, chunk, health, and all of shoresh.

- **Auth:** `verify()` is the single check on gated paths — swap it for a per-client keys
  table later without touching call sites (mechanism A → B/C).
- **Rate limit:** fixed 60s window per **identity** (API key if present, else client IP),
  applied to ALL non-liveness paths; gated paths get a tighter cap. In-memory / per-process
  (single-instance assumption; use a shared store to scale horizontally).
"""
from __future__ import annotations

import os
import time

from fastapi import Request
from fastapi.responses import JSONResponse

from server.auth import verify, _present_password
from server.ratelimit import _client_ip

_NO_LIMIT = {"/", "/api/health", "/favicon.ico"}   # liveness/discovery: no auth, no rate limit


def _needs_key(request: Request) -> bool:
    """Gated set: LLM synthesis (/api/ask*) + the MCP surface + writes. Semantic search is
    open ($0 Cloudflare embedding)."""
    p = request.url.path
    if p.startswith("/mcp") or p.startswith("/api/ask"):
        return True
    return request.method in ("PUT", "PATCH", "DELETE")


_WINDOW = 60.0
LIMIT_DEFAULT = int(os.environ.get("BTMCP_RL_PER_MIN", "120"))    # open $0 reads
LIMIT_PAID = int(os.environ.get("BTMCP_RL_PAID_PER_MIN", "20"))   # gated (LLM/semantic/MCP)

_state: dict = {"window": -1, "hits": {}}


def _identity(request: Request) -> str:
    key = _present_password(request.headers.get("authorization"),
                           request.headers.get("x-api-key"))
    return f"k:{key[:16]}" if key else f"ip:{_client_ip(request)}"


def _rate_ok(ident: str, gated: bool) -> bool:
    """Fixed-window counter; the whole window resets each minute (bounded memory)."""
    w = int(time.monotonic() // _WINDOW)
    if w != _state["window"]:
        _state["window"], _state["hits"] = w, {}
    hits = _state["hits"]
    bucket = f"{ident}|{'paid' if gated else 'std'}"
    hits[bucket] = hits.get(bucket, 0) + 1
    return hits[bucket] <= (LIMIT_PAID if gated else LIMIT_DEFAULT)


async def gate(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path in _NO_LIMIT:
        return await call_next(request)
    gated = _needs_key(request)
    if gated and not verify(request.headers.get("authorization"),
                            request.headers.get("x-api-key")):
        return JSONResponse(status_code=401,
                            content={"detail": "API key required for this endpoint "
                                               "(Authorization: Bearer <key> or X-API-Key)"})
    if not _rate_ok(_identity(request), gated):
        return JSONResponse(status_code=429, content={"detail": "rate limit exceeded"},
                            headers={"Retry-After": str(int(_WINDOW))})
    return await call_next(request)
