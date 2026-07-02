"""Access gate + coarse rate limiting, as a pure-ASGI middleware.

Pure ASGI (not BaseHTTPMiddleware) on purpose: it only inspects the request and either
short-circuits (401/429) or passes through **untouched** — so it never buffers a response
and is safe in front of the streaming `/mcp` (Streamable HTTP / SSE) mount.

Policy: gate only **synthesis** (LLM) + the **MCP** surface + **writes**; leave the $0 read
endpoints open (anonymous, but rate-limited). "Gated" = requires a valid API key:
  - LLM synthesis — `/api/ask`, `/api/ask/branched`,
  - the whole MCP surface (`/mcp`) — registration for the tool surface,
  - write methods (PUT/PATCH/DELETE).
Everything else is open — semantic search included (embedding is Cloudflare BGE-M3, $0).

- Auth: `verify()` is the single check on gated paths — swap for a per-client keys table
  later without touching call sites (mechanism A → B/C).
- Rate limit: fixed 60s window per identity (API key if present, else client IP), applied to
  all non-liveness paths; gated paths get a tighter cap. In-memory / per-process.
"""
from __future__ import annotations

import json
import os
import time

from server.auth import _present_password, verify

_NO_LIMIT = {"/", "/api/health", "/favicon.ico"}   # liveness/discovery: no auth, no rate limit


def _needs_key(method: str, path: str) -> bool:
    """Gated set: LLM synthesis (/api/ask*) + the MCP surface + writes."""
    if path.startswith("/mcp") or path.startswith("/api/ask"):
        return True
    return method in ("PUT", "PATCH", "DELETE")


_WINDOW = 60.0
LIMIT_DEFAULT = int(os.environ.get("BTMCP_RL_PER_MIN", "120"))    # open $0 reads
LIMIT_PAID = int(os.environ.get("BTMCP_RL_PAID_PER_MIN", "20"))   # gated (LLM/MCP)
_state: dict = {"window": -1, "hits": {}}


def _client_ip(headers: dict, scope) -> str:
    xff = headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    client = scope.get("client")
    return client[0] if client else "unknown"


def _rate_ok(ident: str, gated: bool) -> bool:
    w = int(time.monotonic() // _WINDOW)
    if w != _state["window"]:
        _state["window"], _state["hits"] = w, {}
    hits = _state["hits"]
    bucket = f"{ident}|{'paid' if gated else 'std'}"
    hits[bucket] = hits.get(bucket, 0) + 1
    return hits[bucket] <= (LIMIT_PAID if gated else LIMIT_DEFAULT)


class Gate:
    """Pure-ASGI middleware — wraps the whole app (including the /mcp mount)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        method, path = scope["method"], scope["path"]
        if method == "OPTIONS" or path in _NO_LIMIT:
            return await self.app(scope, receive, send)

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        gated = _needs_key(method, path)
        if gated and not verify(headers.get("authorization"), headers.get("x-api-key")):
            return await _reject(send, 401, "API key required for this endpoint "
                                             "(Authorization: Bearer <key> or X-API-Key)")
        key = _present_password(headers.get("authorization"), headers.get("x-api-key"))
        ident = f"k:{key[:16]}" if key else f"ip:{_client_ip(headers, scope)}"
        if not _rate_ok(ident, gated):
            return await _reject(send, 429, "rate limit exceeded", retry_after=int(_WINDOW))
        return await self.app(scope, receive, send)


async def _reject(send, status: int, detail: str, retry_after: int | None = None) -> None:
    headers = [(b"content-type", b"application/json")]
    if retry_after is not None:
        headers.append((b"retry-after", str(retry_after).encode()))
    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
