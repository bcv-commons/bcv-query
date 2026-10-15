"""Licence register (resources/licenses/sources.json + shoresh/licenses.json, served at /licenses): every route of the app says which sources it serves, every source
has a licence, and every response points to the register with a `Link: <...>; rel="license"` header.
  bcv-RAG/.venv/bin/python -m pytest shoresh/tests/test_licenses.py -q"""
import sys
from pathlib import Path

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

SHORESH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHORESH))
import app as shoresh_app  # noqa: E402
import licenses  # noqa: E402

REG = licenses._load()
ROUTES = [r.path for r in shoresh_app.app.routes if isinstance(r, APIRoute)]


def test_every_route_is_in_the_register():
    missing = sorted(set(ROUTES) - set(REG["routes"]))
    assert not missing, f"routes without a licence entry in licenses.json: {missing}"
    stale = sorted(set(REG["routes"]) - set(ROUTES))
    assert not stale, f"licenses.json lists routes the app no longer has: {stale}"


def test_every_source_is_defined_and_licensed():
    for route, entry in REG["routes"].items():
        for s in entry["sources"]:
            assert s in REG["sources"], f"{route}: unknown source {s}"
    for sid, src in REG["sources"].items():
        assert src.get("license"), f"{sid}: no licence"
        assert src.get("url") or src.get("attribution"), f"{sid}: neither url nor attribution"


def test_link_header_and_lookup():
    client = TestClient(shoresh_app.app)          # no `with`: the search store is not loaded
    r = client.get("/health")
    assert 'rel="license"' in r.headers["link"] and "/licenses?path=/health" in r.headers["link"]
    r = client.get("/licenses", params={"path": "/speakers/at/GEN/1/3"})
    assert r.status_code == 200
    body = r.json()
    assert body["route"] == "/speakers/at/{book}/{chapter}/{verse}"
    assert any(s["license"] == "CC-BY-4.0" for s in body["sources"].values())
    assert client.get("/licenses", params={"path": "/no/such/route"}).status_code == 404
