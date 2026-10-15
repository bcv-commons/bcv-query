"""Licence register: where each route's data comes from and under which licence (served at /licenses).

The facts live in licenses.json next to this file (sources with licence and attribution, routes -> source ids, the code's
licence); this module only reads and matches them. tests/test_licenses.py fails when a route has no entry, so a new
endpoint cannot ship without saying what it serves."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

REGISTER = Path(__file__).resolve().parent / "licenses.json"


@lru_cache(maxsize=1)
def _load() -> dict:
    return json.loads(REGISTER.read_text(encoding="utf-8"))


def code_license_info() -> dict:
    """FastAPI/OpenAPI `license_info` for the service code."""
    c = _load()["code_license"]
    return {"name": c["name"], **({"url": c["url"]} if c.get("url") else {})}


def register() -> dict:
    """The whole register."""
    r = _load()
    return {"about": r["about"], "code_license": r["code_license"], "sources": r["sources"], "routes": r["routes"]}


def _matches(template: str, path: str) -> bool:
    pattern = "^" + re.sub(r"\\\{[^/]+?\\\}", "[^/]+", re.escape(template)) + "$"
    return re.match(pattern, path) is not None


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
