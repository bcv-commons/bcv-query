"""MCP stdio transport.

Reads line-delimited JSON-RPC from stdin, writes responses to stdout.
Used by Claude desktop and other local-process MCP integrations.

Usage:
  python -m server.mcp.stdio
"""
from __future__ import annotations

import json
import sys

from indexer.db import open_db
from indexer.env import load_env
from server.deps import db_path
from server.mcp.server import _handle_one


def main() -> int:
    load_env()
    db = open_db(db_path())
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                _emit({"jsonrpc": "2.0", "id": None,
                       "error": {"code": -32700, "message": "Parse error: invalid JSON"}})
                continue
            response = _handle_one(msg, db)
            # Notifications are acknowledged silently; response is empty dict.
            if response:
                _emit(response)
    finally:
        db.close()
    return 0


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
