"""Per-IP rate limiting via slowapi.

Why
---
The auth gate prevents *unauthorized* AI calls but doesn't bound how often
an authorized client can spend our LLM budget. Rate limiting caps that
per remote IP — cheap insurance against bugs, runaway clients, and basic
abuse.

Storage is in-process. Single-instance Railway is the assumed shape;
horizontal scaling would need a shared backend (Redis) — see slowapi
docs for `storage_uri=`.

Configuration
-------------
Limits are read from env vars at process start, with sensible defaults:

  BTMCP_RATE_LIMIT_ASK     default "10/minute"   POST /api/ask, MCP ask
  BTMCP_RATE_LIMIT_SEARCH  default "60/minute"   GET /api/search
  BTMCP_RATE_LIMIT_READ    default "120/minute"  /api/health, /api/chunk, /api/tree
  BTMCP_RATE_LIMIT_MCP     default "60/minute"   POST /mcp endpoint as a whole

slowapi accepts the standard "<count>/<period>" format
(period: second, minute, hour, day).
"""
from __future__ import annotations

import os

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from indexer.env import load_env

# Ensure .env values are visible to the limit-string lookups below before
# slowapi captures them. Idempotent.
load_env()


def _client_ip(request: Request) -> str:
    """Real client IP, honoring `X-Forwarded-For` from PaaS proxies (Railway)."""
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return get_remote_address(request)


limiter = Limiter(key_func=_client_ip)

LIMIT_ASK = os.environ.get("BTMCP_RATE_LIMIT_ASK", "10/minute")
LIMIT_SEARCH = os.environ.get("BTMCP_RATE_LIMIT_SEARCH", "60/minute")
LIMIT_READ = os.environ.get("BTMCP_RATE_LIMIT_READ", "120/minute")
LIMIT_MCP = os.environ.get("BTMCP_RATE_LIMIT_MCP", "60/minute")
