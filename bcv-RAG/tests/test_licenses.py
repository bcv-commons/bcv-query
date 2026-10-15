"""Licence register for bcv-rag (resources/licenses/sources.json + server/licenses.json, served at /api/licenses): every route
says which sources it serves, every source has a licence, and every response points to the register with a
`Link: <...>; rel="license"` header.
  .venv/bin/python -m pytest tests/test_licenses.py -q"""
from fastapi.testclient import TestClient
from starlette.routing import Mount

from server import licenses
from server.app import app

REG = licenses._load()
# Every documented route (OpenAPI writes {path:path} as {path}) plus the mounts (/mcp).
ROUTES = list(app.openapi()["paths"]) + [r.path for r in app.routes if isinstance(r, Mount)]


def test_every_route_is_in_the_register():
    listed = {t.replace(":path}", "}"): t for t in REG["routes"]}
    missing = sorted(set(ROUTES) - set(listed))
    assert not missing, f"routes without a licence entry in server/licenses.json: {missing}"
    stale = sorted(set(listed) - set(ROUTES))
    assert not stale, f"server/licenses.json lists routes the app no longer has: {stale}"


def test_every_source_is_defined_and_licensed():
    for route, entry in REG["routes"].items():
        for s in entry["sources"]:
            assert s in REG["sources"], f"{route}: unknown source {s}"
    for sid, src in REG["sources"].items():
        assert src.get("license"), f"{sid}: no licence"
        assert src.get("url") or src.get("attribution"), f"{sid}: neither url nor attribution"


def test_link_header_and_lookup():
    client = TestClient(app)          # no `with`: the index is not opened
    r = client.get("/api/licenses", params={"path": "/api/tree/source/a/b"})
    assert 'rel="license"' in r.headers["link"] and "/api/licenses?path=/api/licenses" in r.headers["link"]
    assert r.json()["route"] == "/api/tree/{tree_name}/{path:path}"
    assert licenses.for_path("/mcp/")["route"] == "/mcp"
    body = client.get("/api/licenses").json()
    assert body["sources"]["aquifer"]["license"].startswith("CC-BY-SA-4.0")
    assert client.get("/api/licenses", params={"path": "/no/such"}).status_code == 404
