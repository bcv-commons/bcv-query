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


def allowed_origin_regex() -> str | None:
    """Optional CORS_ALLOWED_ORIGIN_REGEX env var, for origins that vary per-deploy (e.g. Netlify
    preview URLs: https://<random>--<site>.netlify.app, a different string every build).
    starlette.CORSMiddleware's `allow_origins` is EXACT STRING MATCH ONLY — a literal
    "https://*.netlify.app" entry in allow_origins never matches a real browser Origin header.
    `allow_origin_regex` is the actual mechanism for wildcard-subdomain origins; unset by default
    (no regex matching) so this stays opt-in per deployment."""
    raw = (os.environ.get("CORS_ALLOWED_ORIGIN_REGEX") or "").strip()
    return raw or None
