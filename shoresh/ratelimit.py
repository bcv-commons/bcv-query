"""Per-IP rate limiting for the public shoresh surface (via slowapi).

shoresh is reachable from the open internet at `shoresh.up.qombi.com` (Caddy →
uvicorn) and now serves a browser-facing, unauthenticated endpoint (`/words`).
Several routes scan the corpus or run a model, so an unbounded public client is
a cheap DoS vector. A blanket per-IP default limit caps that across every route;
expensive routes can override with a tighter explicit limit.

Storage is in-process — fine for the single-instance shape. Horizontal scaling
would need a shared backend (Redis); see slowapi's `storage_uri=`.

Limits are env-overridable at process start:

  SHORESH_RATE_LIMIT   default "120/minute"   blanket default for every route

slowapi accepts "<count>/<period>" (period: second, minute, hour, day).
"""
from __future__ import annotations

import os

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _client_ip(request: Request) -> str:
    """Real client IP, honoring `X-Forwarded-For` from the Caddy proxy in front."""
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return get_remote_address(request)


DEFAULT_LIMIT = os.environ.get("SHORESH_RATE_LIMIT", "120/minute")

limiter = Limiter(key_func=_client_ip, default_limits=[DEFAULT_LIMIT])
