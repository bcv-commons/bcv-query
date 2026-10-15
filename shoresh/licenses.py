"""Licence register: where each route's data comes from and under which licence (served at /licenses).

The facts are data: the sources with licence and attribution, and the code's licence, in resources/licenses/sources.json
(shared with bcv-rag); this service's routes -> source ids in licenses.json next to this file. This module only reads and
matches them. tests/test_licenses.py fails when a route has no entry, so a new
endpoint cannot ship without saying what it serves."""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUTES = HERE / "licenses.json"


def _sources_path() -> Path:
    env = os.environ.get("BCV_RESOURCES_DIR")
    return (Path(env) if env else HERE.parent / "resources") / "licenses" / "sources.json"


@lru_cache(maxsize=1)
def _load() -> dict:
    return {**json.loads(_sources_path().read_text(encoding="utf-8")), **json.loads(ROUTES.read_text(encoding="utf-8"))}


def code_license_info() -> dict:
    """FastAPI/OpenAPI `license_info` for the service code."""
    c = _load()["code_license"]
    return {"name": c["name"], **({"url": c["url"]} if c.get("url") else {})}


def register() -> dict:
    """The whole register."""
    r = _load()
    used = {s for e in r["routes"].values() for s in e["sources"]}
    return {"about": r["about"], "code_license": r["code_license"],
            "sources": {k: v for k, v in r["sources"].items() if k in used}, "routes": r["routes"]}


def _matches(template: str, path: str) -> bool:
    """`/lexeme/{lex:path}` style template against a URL path (a `:path` parameter spans slashes)."""
    pattern = re.sub(r"\\\{[^/]+?:path\\\}", ".+", re.escape(template))
    pattern = re.sub(r"\\\{[^/]+?\\\}", "[^/]+", pattern)
    return re.match(f"^{pattern}$", path) is not None


def for_path(path: str, templates: list[str]) -> dict | None:
    """The register entry of one route: `path` is a route template as listed, or a concrete URL path matched against the
    app's route templates (literal routes before templated ones). None when no route matches."""
    r = _load()
    path = path.split("?", 1)[0]
    route = path if path in r["routes"] else next(
        (t for t in sorted(templates, key=lambda t: t.count("{")) if t in r["routes"] and _matches(t, path)), None)
    if route is None:
        return None
    entry = r["routes"][route]
    return {"route": route, **entry, "sources": {s: r["sources"][s] for s in entry["sources"]},
            "code_license": r["code_license"], "about": r["about"]}
