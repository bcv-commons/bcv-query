"""vrsmap.py: conversion between numbering schemes, built only on bibles' published .vrs shapes, maps, multi-verse relations and edition index.
  bcv-RAG/.venv/bin/python -m pytest shoresh/tests/test_vrsmap.py -q
Unit tests use small synthetic files in the published formats; the integration tests use the real cached files (shoresh/data/vrs) and skip without them."""
import json
import sys
from pathlib import Path

import pytest

SHORESH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHORESH))
REAL = SHORESH / "data" / "vrs"
HAVE_REAL = (REAL / "org-to-eng.json").exists() and (REAL / "index.json").exists()


def _vrs(rows: dict) -> str:
    return "# Versification\n" + "\n".join(f"{b} " + " ".join(f"{c}:{n}" for c, n in chs) for b, chs in rows.items()) + "\n"


@pytest.fixture()
def vm(tmp_path, monkeypatch):
    """Synthetic scheme 'org' (Psalm 3 with title as verse 1, Psalm 51 two-verse title, Joel 3 = English 2:28-32, Numbers 25:19 joined to 26:1) and 'rso'
    (Psalm 114 = first half of English 116, verse 9 has no row: the gap rule)."""
    eng = {"PSA": [(3, 8), (51, 19), (114, 8), (115, 18), (116, 19)], "JOL": [(2, 32), (3, 21)], "NUM": [(25, 18), (26, 65)]}
    org = {"PSA": [(3, 9), (51, 21)], "JOL": [(2, 27), (3, 5)], "NUM": [(25, 19), (26, 65)]}
    rso = {"PSA": [(3, 9), (113, 26), (114, 9), (115, 18)]}
    (tmp_path / "eng.vrs").write_text(_vrs(eng)); (tmp_path / "org.vrs").write_text(_vrs(org)); (tmp_path / "rso.vrs").write_text(_vrs(rso))
    rows = [("PSA 3:1", "PSA 3:title"), *[(f"PSA 3:{i}", f"PSA 3:{i-1}") for i in range(2, 10)],
            ("PSA 51:1", "PSA 51:title"), ("PSA 51:2", "PSA 51:title"), *[(f"PSA 51:{i}", f"PSA 51:{i-2}") for i in range(3, 22)],
            *[(f"JOL 3:{i}", f"JOL 2:{27+i}") for i in range(1, 6)]]
    (tmp_path / "org-to-eng.json").write_text(json.dumps({"tvtms_rev": "abc", "map": [{"s": s, "t": t, "a": "x"} for s, t in rows]}))
    (tmp_path / "org-to-eng.multiverse.json").write_text(json.dumps({"map": [{"s": "NUM 25:19-26:1", "t": "NUM 26:1"}]}))
    rows = [("PSA 3:1", "PSA 3:title"), *[(f"PSA 3:{i}", f"PSA 3:{i-1}") for i in range(2, 10)]] + [(f"PSA 114:{i}", f"PSA 116:{i}") for i in range(1, 9)] + [(f"PSA 115:{i}", f"PSA 116:{i+9}") for i in range(1, 11)]
    (tmp_path / "rso-to-eng.json").write_text(json.dumps({"tvtms_rev": "abc", "map": [{"s": s, "t": t, "a": "x"} for s, t in rows]}))
    (tmp_path / "index.json").write_text(json.dumps({"schemes": ["eng", "org", "rso"], "vrs_base": "http://127.0.0.1:9/_vrs/", "map_base": "http://127.0.0.1:9/_vrs/map/",
                                                       "l": {"deu/A": "eng", "deu/B": "eng", "fra/A": "org", "fra/B": "eng", "rus/A": "rso", "xxx/Z": "undetermined"}}))
    monkeypatch.setenv("VERSIFICATION_MAP_DIR", str(tmp_path))
    import vrsmap
    for f in (vrsmap.table, vrsmap.shape, vrsmap._index_cached):
        f.cache_clear()
    vrsmap._failed.clear()
    return vrsmap


def test_english_reference_to_hebrew_and_back(vm):
    assert vm.convert(("PSA", 3, 1), "eng", "org") == [("PSA", 3, 2)]
    assert vm.convert(("PSA", 3, 2), "org", "eng") == [("PSA", 3, 1)]
    assert vm.convert(("JOL", 2, 28), "eng", "org") == [("JOL", 3, 1)]


def test_a_title_is_english_verse_zero_and_may_be_two_hebrew_verses(vm):
    assert vm.convert(("PSA", 3, 0), "eng", "org") == [("PSA", 3, 1)]
    assert vm.convert(("PSA", 51, 0), "eng", "org") == [("PSA", 51, 1), ("PSA", 51, 2)]
    assert vm.convert(("PSA", 51, 2), "org", "eng") == [("PSA", 51, 0)]


def test_multiverse_relations_are_expanded_with_the_published_shapes(vm):
    assert vm.convert(("NUM", 25, 19), "org", "eng") == [("NUM", 26, 1)]
    assert vm.convert(("NUM", 26, 1), "eng", "org") == [("NUM", 25, 19), ("NUM", 26, 1)]


def test_the_gap_rule_fills_a_verse_that_keeps_its_number_but_changes_chapter(vm):
    # rso 114:1-8 -> eng 116:1-8 and rso 115:1 -> eng 116:10: rso 114:9 has no row and is eng 116:9 (doc/vrs-maps.md)
    assert vm.convert(("PSA", 114, 9), "rso", "eng") == [("PSA", 116, 9)]


def test_schemes_convert_through_english_and_unlisted_verses_keep_their_reference(vm):
    assert vm.convert(("PSA", 3, 1), "rso", "org") == [("PSA", 3, 1)]
    assert vm.convert(("PSA", 3, 2), "rso", "org") == [("PSA", 3, 2)]
    assert vm.convert(("GEN", 1, 1), "eng", "org") == [("GEN", 1, 1)]
    assert vm.convert(("PSA", 3, 1), "org", "org") == [("PSA", 3, 1)]


def test_a_scheme_bibles_does_not_publish_is_unknown(vm):
    for bad in ("luther", "../etc/passwd", ""):
        with pytest.raises(vm.UnknownScheme):
            vm.convert(("PSA", 3, 1), bad, "org")
    assert vm.available("eng") and not vm.available("luther")


def test_language_to_scheme_comes_from_bibles_edition_index(vm):
    assert vm.scheme_for_language("deu")["scheme"] == "eng" and vm.scheme_for_language("deu")["agreement"] == 1.0
    assert vm.scheme_for_language("rus")["scheme"] == "rso"
    fr = vm.scheme_for_language("fra")
    assert fr["editions"] == 2 and fr["agreement"] == 0.5                  # editions of one language disagree: reported, not hidden
    assert vm.scheme_for_language("xxx") is None                            # undetermined editions do not count
    assert vm.scheme_for_language("zzz") is None and vm.scheme_for_language(None) is None


@pytest.mark.skipif(not HAVE_REAL, reason="bibles' files not cached locally (shoresh/data/vrs)")
class TestRealFiles:
    @pytest.fixture(autouse=True)
    def real(self, monkeypatch):
        monkeypatch.setenv("VERSIFICATION_MAP_DIR", str(REAL))
        import vrsmap
        for f in (vrsmap.table, vrsmap.shape, vrsmap._index_cached):
            f.cache_clear()
        self.vm = vrsmap

    def test_every_published_scheme_loads_and_maps_into_the_english_shape(self):
        for s in self.vm.schemes():
            if s == "eng":
                continue
            c = self.vm.check(s)
            assert c["verses"] > 20000, s
            assert len(c["outside_english"]) < 1000, s

    def test_documented_cases(self):
        v = self.vm.convert
        assert v(("PSA", 114, 9), "rso", "eng") == [("PSA", 116, 9)]                      # vrs-maps.md gap-rule example
        assert v(("PSA", 12, 6), "rso", "eng") == [("PSA", 13, 5), ("PSA", 13, 6)]        # rso multiverse relation
        assert v(("PSA", 3, 1), "eng", "org") == [("PSA", 3, 2)]
        assert v(("PSA", 51, 0), "eng", "org") == [("PSA", 51, 1), ("PSA", 51, 2)]
        assert v(("PSA", 22, 1), "vul", "org") == [("PSA", 23, 1)]

    def test_language_registry_from_the_edition_index(self):
        assert self.vm.scheme_for_language("rus")["scheme"] == "rso"
        assert self.vm.scheme_for_language("deu")["scheme"] == "eng"
        assert self.vm.scheme_for_language("en")["scheme"] == "eng"


MACULA = SHORESH / "macula" / "macula-spine.db"


@pytest.mark.skipif(not (HAVE_REAL and MACULA.exists()), reason="needs bibles' cached files and macula-spine.db")
class TestVerseInTheReadersNumbering:
    @pytest.fixture(autouse=True)
    def base(self, monkeypatch):
        monkeypatch.setenv("VERSIFICATION_MAP_DIR", str(REAL))
        import data, vrsmap
        for f in (vrsmap.table, vrsmap.shape, vrsmap._index_cached):
            f.cache_clear()
        self.data = data

    def test_the_same_verse_is_served_whatever_the_scheme(self):
        he = self.data.verse("PSA", 3, 2, versification="org")["spine"]["words"]
        en = self.data.verse("PSA", 3, 1, versification="eng")["spine"]["words"]
        ru = self.data.verse("PSA", 3, 2, versification="rso")["spine"]["words"]
        assert [w["key"] for w in he] == [w["key"] for w in en] == [w["key"] for w in ru]

    def test_a_two_verse_title_comes_back_whole_and_the_greek_side_follows_its_own_numbering(self):
        r = self.data.verse("PSA", 51, 0, versification="eng")
        assert r["versification"]["hebrew"] == ["PSA 51:1", "PSA 51:2"] and r["versification"]["lxx"] == ["PSA 50:1", "PSA 50:2"]
        assert {w["verse"] for w in r["spine"]["words"]} == {1, 2}
        assert [w["idx"] for w in r["spine"]["words"]] == list(range(len(r["spine"]["words"])))

    def test_an_unknown_scheme_is_an_error_not_a_guess(self):
        import vrsmap
        with pytest.raises(vrsmap.UnknownScheme):
            self.data.verse("GEN", 1, 1, versification="luther")


def test_revalidation_downloads_only_what_changed(tmp_path, monkeypatch):
    """A cached file older than a day is revalidated with If-None-Match: 304 keeps it (age restarted), a new ETag replaces it and flags the tables for rebuild."""
    import os, time, urllib.error, urllib.request, vrsmap
    monkeypatch.setenv("VERSIFICATION_MAP_DIR", str(tmp_path))
    (tmp_path / "a.json").write_text("old"); (tmp_path / "a.json.etag").write_text('"v1"')
    (tmp_path / "b.json").write_text("old"); (tmp_path / "b.json.etag").write_text('"v1"')
    old = time.time() - 3 * 86400
    for n in ("a.json", "b.json"):
        os.utime(tmp_path / n, (old, old))
    seen = []

    class Resp:
        headers = {"ETag": '"v2"'}
        def read(self): return b"new"

    def fake_urlopen(req, timeout=0):
        seen.append((req.full_url, req.headers.get("If-none-match")))
        if req.full_url.endswith("a.json"):
            raise urllib.error.HTTPError(req.full_url, 304, "Not Modified", {}, None)
        return Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    vrsmap._failed.clear(); vrsmap._changed.clear()
    assert vrsmap._bytes("a.json", "http://x/a.json", max_age=86400) == b"old"
    assert not vrsmap._changed.is_set() and time.time() - (tmp_path / "a.json").stat().st_mtime < 60      # unchanged: kept, age restarted
    assert vrsmap._bytes("b.json", "http://x/b.json", max_age=86400) == b"new"
    assert vrsmap._changed.is_set() and (tmp_path / "b.json.etag").read_text() == '"v2"'
    assert seen == [("http://x/a.json", '"v1"'), ("http://x/b.json", '"v1"')]
    assert vrsmap._bytes("a.json", "http://x/a.json", max_age=86400) == b"old" and len(seen) == 2            # fresh again: no request at all


def test_an_unlisted_verse_is_left_unmapped_when_another_verse_lands_on_it(tmp_path, monkeypatch):
    """Sirach-like case: the row 1:21 -> 1:17 exists, verse 1:17 has no row; identity would put two verses on English 1:17."""
    (tmp_path / "eng.vrs").write_text(_vrs({"SIR": [(1, 17)]}))
    (tmp_path / "vul.vrs").write_text(_vrs({"SIR": [(1, 21)]}))
    (tmp_path / "vul-to-eng.json").write_text(json.dumps({"tvtms_rev": "abc", "map": [{"s": "SIR 1:21", "t": "SIR 1:17", "a": "x"}]}))
    (tmp_path / "index.json").write_text(json.dumps({"schemes": ["eng", "vul"], "vrs_base": "http://127.0.0.1:9/_vrs/", "map_base": "http://127.0.0.1:9/_vrs/map/",
                                                      "l": {}, "maps": ["vul-to-eng.json"]}))
    monkeypatch.setenv("VERSIFICATION_MAP_DIR", str(tmp_path))
    import vrsmap
    for f in (vrsmap.table, vrsmap.shape, vrsmap._index_cached, vrsmap._nt_rows):
        f.cache_clear()
    assert vrsmap.to_eng(("SIR", 1, 21), "vul") == [("SIR", 1, 17)]
    assert vrsmap.to_eng(("SIR", 1, 17), "vul") == []
    assert vrsmap.check("vul")["collisions"] == {}


def test_nt_variants_replace_the_scheme_map_for_new_testament_verses(vm, tmp_path):
    (tmp_path / "nt-variants.json").write_text(json.dumps({"variants": {
        "1TI6-22": {"kind": "renumbering", "map": [{"s": "1TI 6:22", "t": ["1TI 6:21"]}]},
        "REV12-17": {"kind": "renumbering", "map": [{"s": "REV 13:1", "t": ["REV 12:18", "REV 13:1"]}]}}}))
    idx = json.loads((tmp_path / "index.json").read_text())
    idx.update({"nt_variants": "nt-variants.json", "nt": {"arb/X": {"variants": ["1TI6-22", "REV12-17"]}, "arb/Y": {"variants": []}}})
    (tmp_path / "index.json").write_text(json.dumps(idx))
    for f in (vm._index_cached, vm._nt_rows):
        f.cache_clear()
    assert vm.to_eng(("1TI", 6, 22), "eng", "arb/X") == [("1TI", 6, 21)]
    assert vm.to_eng(("REV", 13, 1), "eng", "arb/X") == [("REV", 12, 18), ("REV", 13, 1)]
    assert vm.from_eng(("REV", 12, 18), "eng", "arb/X") == [("REV", 13, 1)]
    assert vm.to_eng(("1TI", 6, 22), "eng", "arb/Y") == [("1TI", 6, 22)]          # an nt entry without variants: identity
    assert vm.to_eng(("1TI", 6, 22), "eng") == [("1TI", 6, 22)]                   # no edition: unchanged
    assert vm.to_eng(("1TI", 6, 22), "eng", "arb/none") == [("1TI", 6, 22)]       # an edition without an nt entry: unchanged
    assert vm.to_eng(("PSA", 3, 2), "org", "arb/X") == [("PSA", 3, 1)]            # Old Testament still uses the scheme's map


def test_check_separates_block_relations_from_conflicts(vm):
    """NUM 25:19 and NUM 26:1 (org) are one multiverse relation = English NUM 26:1: intended, not a conflict."""
    r = vm.check("org")
    assert ("NUM", 26, 1) in r["block_relations"] and ("NUM", 26, 1) not in r["collisions"]
    assert r["collisions"] == {}
