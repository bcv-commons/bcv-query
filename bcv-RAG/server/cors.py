"""CORS allowlist configuration."""
from __future__ import annotations

import os


def allowed_origins() -> list[str]:
    """Read CORS_ALLOWED_ORIGINS env var (comma-separated) with sane local defaults."""
    raw = (os.environ.get("CORS_ALLOWED_ORIGINS") or "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8080",
    ]
