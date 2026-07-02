"""Password gate for endpoints that consume an AI-provider API key.

Why
---
Hosted deployments expose the server's `OPENAI_API_KEY` and `GROQ_API_KEY`
indirectly through any endpoint that calls them. To keep cost and abuse
under our control, every code path that triggers an LLM (synthesis) or
embedding (semantic vector search) call requires a shared secret.

Configuration
-------------
Set ``BTMCP_API_PASSWORD`` to any non-empty string in production.

If unset/empty, gated endpoints behave as if open — convenient for local
dev. Production deployments MUST set it.

Wire format
-----------
Clients pass the password via either header:
  Authorization: Bearer <password>
  X-API-Key: <password>

Stdio MCP transport is local-only (subprocess) and skips this check.
"""
from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import Header, HTTPException


def _expected_password() -> str:
    return (os.environ.get("BTMCP_API_PASSWORD") or "").strip()


def password_required() -> bool:
    """True iff `BTMCP_API_PASSWORD` is set (production); False = dev/open."""
    return bool(_expected_password())


def _present_password(authorization: Optional[str], x_api_key: Optional[str]) -> Optional[str]:
    if x_api_key:
        return x_api_key.strip() or None
    if authorization:
        token = authorization.strip()
        if token.lower().startswith("bearer "):
            return token[7:].strip() or None
        return token or None
    return None


def verify(authorization: Optional[str], x_api_key: Optional[str]) -> bool:
    """Return True if request is authorized, OR if auth is disabled."""
    expected = _expected_password()
    if not expected:
        return True
    presented = _present_password(authorization, x_api_key)
    if not presented:
        return False
    return hmac.compare_digest(presented, expected)


def require_password(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> None:
    """FastAPI dependency: 401 if BTMCP_API_PASSWORD is set and the request
    is missing or presents the wrong password."""
    if not verify(authorization, x_api_key):
        raise HTTPException(
            status_code=401,
            detail="missing or invalid API password (BTMCP_API_PASSWORD)",
        )


_AI_TOOLS = {"semantic_search"}   # tools that make a provider (embedding/LLM) call → need the key


def mcp_tool_call_uses_ai(name: Optional[str], arguments: dict) -> bool:
    """Whether an MCP `tools/call` invocation will hit an AI provider key. Keyed on the
    TOOL (not an argument flag) so the auth boundary is a clear per-tool contract:
    `semantic_search` needs the key; every other tool is $0 and open."""
    return name in _AI_TOOLS
