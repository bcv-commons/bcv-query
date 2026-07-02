"""MCP server — official SDK transports (Streamable HTTP + stdio).

Wraps the shared tool registry in `server.mcp.tools` (unchanged) in the SDK's low-level
`Server`, so a client discovers/calls the same tools. This replaced a hand-rolled JSON-RPC
endpoint; the SDK now owns protocol compliance (Streamable HTTP with sessions, resumability)
so remote MCP clients work plug-and-play.

- HTTP:  the ASGI app `handle_streamable_http`, mounted at `/mcp` by server.app.
- stdio: `python -m server.mcp.stdio` (calls `_server.run`).

Auth + rate limiting are enforced by the app-level gate middleware (server.gate): the whole
`/mcp` surface requires a valid API key. `stateless=True` — each request is independent (a
pure tools server; no session state to persist).
"""
from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from server.deps import get_shared_db
from server.mcp.tools import call_tool as _call_tool
from server.mcp.tools import list_tools as _list_tools

_server: Server = Server("bcv-query")


@_server.list_tools()
async def _handle_list_tools() -> list[types.Tool]:
    return [types.Tool(name=t["name"], description=t["description"], inputSchema=t["inputSchema"])
            for t in _list_tools()]


@_server.call_tool()
async def _handle_call_tool(name: str, arguments: dict) -> dict:
    db = get_shared_db()
    # tools are sync and hit SQLite — run off the event loop so the transport stays responsive.
    result = await anyio.to_thread.run_sync(lambda: _call_tool(name, arguments or {}, db))
    # a dict → the SDK returns it as structuredContent AND serialized JSON in content.
    return result if isinstance(result, dict) else {"result": result}


# Streamable HTTP transport (mounted at /mcp by server.app; its .run() lifespan is entered there).
session_manager = StreamableHTTPSessionManager(app=_server, stateless=True, json_response=False)


async def handle_streamable_http(scope, receive, send) -> None:
    await session_manager.handle_request(scope, receive, send)


@contextlib.asynccontextmanager
async def session_lifespan() -> AsyncIterator[None]:
    """Run the Streamable HTTP session manager's background task group for the app's lifetime."""
    async with session_manager.run():
        yield
