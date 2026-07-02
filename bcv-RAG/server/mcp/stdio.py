"""MCP stdio transport (official SDK).

The standard transport for local desktop clients (Claude Desktop, Cursor, …). Serves the
same tool registry as the Streamable HTTP surface.

Usage:
  python -m server.mcp.stdio
"""
from __future__ import annotations

import anyio
from mcp.server.stdio import stdio_server

from indexer.env import load_env
from server.mcp.server import _server


async def _run() -> None:
    load_env()
    async with stdio_server() as (read_stream, write_stream):
        await _server.run(read_stream, write_stream, _server.create_initialization_options())


def main() -> None:
    anyio.run(_run)


if __name__ == "__main__":
    main()
