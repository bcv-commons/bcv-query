"""Licence register for bcv-rag: where each route's data comes from and under which licence (served at /api/licenses).

The sources (licence, attribution, URL) and the code's licence are shared with shoresh in resources/licenses/sources.json;
this service's routes -> source ids are in licenses.json next to this file. tests/test_licenses.py fails when a route has no
entry, so a new endpoint cannot ship without saying what it serves. `LicenseLink` adds `Link: <...>; rel="license"` to every
response; it is pure ASGI so the streaming /mcp mount is not buffered."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from resource_paths import resource_path

ROUTES = Path(__file__).resolve().parent / "licenses.json"


@lru_cache(maxsize=1)
def _load() -> dict:
    sources = json.loads((resource_path("licenses") / "sources.json").read_text(encoding="utf-8"))
    return {**sources, **json.loads(ROUTES.read_text(encoding="utf-8"))}


def register() -> dict:
    """The register: the sources this service draws on, the routes, the code's licence."""
    r = _load()
    used = {s for e in r["routes"].values() for s in e["sources"]}
    return {"about": r["about"], "code_license": r["code_license"],
            "sources": {k: v for k, v in r["sources"].items() if k in used}, "routes": r["routes"]}


def _matches(template: str, path: str) -> bool:
    """`/api/tree/{tree_name}/{path:path}` style template against a URL path (a `:path` parameter spans slashes)."""
    pattern = re.sub(r"\\\{[^/]+?:path\\\}", ".+", re.escape(template))
    pattern = re.sub(r"\\\{[^/]+?\\\}", "[^/]+", pattern)
    return re.match(f"^{pattern}$", path) is not None


def for_path(path: str) -> dict | None:
    """The entry of one route: a route template as listed, or a concrete URL path (literal routes before templated ones;
    anything under /mcp is the MCP mount). None when no route matches."""
    r = _load()
    path = path.split("?", 1)[0]
    if path.startswith("/mcp"):
        path = "/mcp"
    route = path if path in r["routes"] else next(
        (t for t in sorted(r["routes"], key=lambda t: (t.count("{"), -len(t))) if _matches(t, path)), None)
    if route is None:
        return None
    entry = r["routes"][route]
    return {"route": route, **entry, "sources": {s: r["sources"][s] for s in entry["sources"]},
            "code_license": r["code_license"], "about": r["about"]}


class LicenseLink:
    """Pure-ASGI middleware: every HTTP response gets `Link: <base/api/licenses?path=<route>>; rel="license"` (RFC 8288)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_link(message):
            if message["type"] == "http.response.start":
                # The route template from the register (FastAPI keeps included routers nested, so scope["route"] lacks the /api prefix).
                entry = for_path(scope["path"])
                path = entry["route"] if entry else None
                if path:
                    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
                    proto = headers.get("x-forwarded-proto") or scope.get("scheme", "http")
                    host = headers.get("x-forwarded-host") or headers.get("host", "")
                    link = f'<{proto}://{host}/api/licenses?path={quote(path, safe="/")}>; rel="license"'
                    message = {**message, "headers": [*message.get("headers", []), (b"link", link.encode("latin-1"))]}
            await send(message)

        return await self.app(scope, receive, send_with_link)
