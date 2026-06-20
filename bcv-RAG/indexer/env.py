"""Project-wide `.env` loader.

Every CLI entry point calls `load_env()` near the top of its `main()`, so
`os.environ.get(...)` calls downstream see whatever the user has set in
their `.env`. Existing process env vars always win over `.env` (so
`OPENAI_API_KEY=… python -m query.ask …` still works as expected).

Search order (first match wins):
  1. $BTMCP_ENV_FILE  (explicit override)
  2. <cwd>/.env       (project-relative — typical case)
  3. <repo root>/.env (where this repo's .env lives if cwd is elsewhere)
"""
from __future__ import annotations

import os
from pathlib import Path

_LOADED_FROM: Path | None = None
_REPO_ROOT = Path(__file__).resolve().parent.parent


def load_env() -> Path | None:
    """Load the first `.env` file found. Idempotent. Returns the loaded path or None."""
    global _LOADED_FROM
    if _LOADED_FROM is not None:
        return _LOADED_FROM

    candidates: list[Path] = []
    explicit = os.environ.get("BTMCP_ENV_FILE")
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path.cwd() / ".env")
    candidates.append(_REPO_ROOT / ".env")

    for path in candidates:
        try:
            if path.is_file():
                _apply(path)
                _LOADED_FROM = path
                return path
        except OSError:
            continue
    return None


def _apply(path: Path) -> None:
    """Apply `.env` assignments to os.environ (without overriding existing vars)."""
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(path, override=False)
        return
    except ImportError:
        pass
    # Stdlib fallback so the project still works without python-dotenv installed.
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        # `setdefault` preserves any value already in the live environment.
        os.environ.setdefault(key, value)
