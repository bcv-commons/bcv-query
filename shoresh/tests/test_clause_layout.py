"""macula.build_clause_layout: clause segments (whole words per MACULA clause, per verse) with depth, for the hebrew-clause-layout dataset."""
import sqlite3

import pytest

import trees_macula

pytestmark = pytest.mark.skipif(not trees_macula.available(), reason="MACULA trees not built")


def _segments(book, ch):
    from macula import build_clause_layout as b
    con = sqlite3.connect(f"file:{trees_macula.trees_path()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    nodes = {r["id"]: r for r in con.execute("SELECT id, rule FROM nodes WHERE corpus='hbo' AND cls='cl'")}
    rows = con.execute("SELECT * FROM words w WHERE corpus='hbo' AND book=? AND chapter=? AND inserted=0 ORDER BY " + trees_macula.TEXT_ORDER, (book, ch)).fetchall()
    return b.chapter_segments(rows, nodes, b._clause_parents(con))


def test_ruth_1_segments_and_depth():
    s = _segments("RUT", 1)
    assert len(s) == 117
    assert s[0]["first"] == "080010010011" and s[0]["depth"] == 0 and s[1]["depth"] == 1        # וַיְהִי בִּימֵי / שְׁפֹט הַשֹּׁפְטִים
    assert s[4]["words"][0] == "080010010131"                                                  # the ל of לָגוּר goes with its word, not the higher clause
    v8 = [x for x in s if x["verse"] == 8]
    assert [x["depth"] for x in v8][:3] == [0, 0, 0]                                           # a coordination group adds no level
    v6 = [x["text"] for x in s if x["verse"] == 6]
    assert not any(t.rstrip("־ ").endswith("כִּֽי") or t.strip() in ("כִּי", "כִּֽי־") for t in v6)      # no lone subordinator: it opens its clause


def test_daniel_2_aramaic_and_no_glued_words():
    s = _segments("DAN", 2)
    assert s[0]["language"] == "hbo" and s[-1]["language"] == "arc"
    v9 = " ".join(x["text"] for x in s if x["verse"] == 9)
    assert "֙לְ" not in v9                                                                     # MACULA's empty trailer at a ketiv/qere word gets a space


def test_ketiv_qere_from_uhb_cache():
    """Uses the downloaded UHB (macula/data/uhb); skipped when it is not there."""
    from pathlib import Path
    import collections
    from macula import build_clause_layout as b
    cache = Path(b.SHORESH) / "macula" / "data" / "uhb"
    if not (cache / b.uhb_source()["tag"] / "27-DAN.usfm").exists():
        pytest.skip("UHB not downloaded")
    con = sqlite3.connect(f"file:{trees_macula.trees_path()}?mode=ro", uri=True)
    kq = b.ketiv_qere(con, "DAN", cache, collections.Counter())
    assert kq["270020090131"]["ketiv"] == "הזמנתון" and b._cons(kq["270020090131"]["qere"]) == "הזדמנתון"
    rut = b.ketiv_qere(con, "RUT", cache, collections.Counter())
    assert rut["080030120061"] == {"key": "080030120061", "ketiv": "אם", "qere": None}           # ketiv without qere
    assert rut["080030050061"]["ketiv"] is None                                                   # qere without ketiv (אֵלַי)


def test_discourse_rules_subordinators():
    """Lemma sets compare in NFC (MACULA's pointing order differs from typed literals); Hebrew הֵן is "behold", Aramaic הֵן is "if"."""
    from macula import discourse_rules as d
    assert tuple(int(x) for x in d.RULES_VERSION.split(".")) >= (0, 2)
    assert d.is_subordinator({"lemma": "\u05db\u05bc\u05b4\u05d9", "wlang": "H"})                  # כִּי in MACULA's order (dagesh first)
    assert not d.is_subordinator({"lemma": "הֵן", "wlang": "H"}) and d.is_subordinator({"lemma": "הֵן", "wlang": "A"})


def test_relation_model_invariants():
    """v0.4: one tree. Every link has a relation from the published list, text_depth never exceeds tree_depth, no cycles."""
    import collections
    from macula import build_clause_layout as b, discourse_rules as d
    con = sqlite3.connect(f"file:{trees_macula.trees_path()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    nodes = {r["id"]: r for r in con.execute("SELECT id, rule, role FROM nodes WHERE corpus='hbo' AND cls='cl'")}
    parents = b._clause_parents(con)
    segs = _segments("RUT", 1)
    keys = {}
    for s in segs:
        keys.setdefault(s["clause"], s["first"])
    toks = collections.defaultdict(list)
    for s in segs:
        toks[s["clause"]] += s["_toks"]
    cl = [{"key": keys[c], "verse": ("RUT", 1, toks[c][0]["verse"]), "parent_key": keys.get(parents.get(c)), "attach": None,
           "f": d.features(toks[c], {}, nodes[c]["rule"], nodes[c]["role"]), "reset": False, "chapter_start": False, "poetry": False}
          for c in keys if c is not None]
    out = d.derive(cl)
    assert all((v["parent"] is None) == (v["relation"] is None) or v["rule"].endswith("fwd") for v in out.values())
    assert all(v["relation"] in d.RELATIONS for v in out.values() if v["relation"])
    assert all(v["depth"] <= v["tree_depth"] for v in out.values())
    assert sum(v["parent"] is None for v in out.values()) <= 2


def test_rule_scopes():
    """Every rule's scope limits it to its books ("poetic" = the group in [books.poetic], "not poetry", a list, "none")."""
    from macula import discourse_rules as d
    assert d.active("quotation_lines", "DEU") and not d.active("narrator_frames", "DEU")        # Deut 2:9: Moses retelling
    assert d.active("narrator_frames", "EZK") and d.active("circumstantial", "GEN") and not d.active("circumstantial", "PSA")
    old = d.SCOPE["quotation_lines"]
    try:
        d.SCOPE["quotation_lines"] = "poetic"
        assert not d.active("quotation_lines", "DEU") and d.active("quotation_lines", "MAL")
        d.SCOPE["quotation_lines"] = "none"
        assert not d.active("quotation_lines", "MAL")
    finally:
        d.SCOPE["quotation_lines"] = old


def test_rules_config_matches_code():
    """clause_layout.toml documents every rule, feature and relation the code uses, and the code has no Hebrew words, Strong's
    numbers or book names of its own."""
    import inspect
    import re
    from macula import build_clause_layout as b, discourse_rules as d
    src = inspect.getsource(d).replace(d.__doc__, "")                                          # the code, without the module docstring
    used = set(re.findall(r'\bon\("(\w+)"\)', src)) | set(re.findall(r'active\("(\w+)"', src + inspect.getsource(b)))
    switchable = {name for name, r in d.RULES.items() if r.get("switchable", True)}
    assert used == switchable, (used - switchable, switchable - used)
    assert all(r.get("doc") for r in d.RULES.values())
    keys = set(d.features([], {}).keys())
    assert keys == set(d.CFG["features"]), (keys - set(d.CFG["features"]), set(d.CFG["features"]) - keys)
    assert not re.search("[\u0590-\u05FF]", src)                                              # no Hebrew in discourse_rules.py
    assert not re.search(r'"\d{3,4}"', src)                                                     # no Strong's numbers
    assert not re.search(r'"(GEN|EXO|LEV|NUM|DEU|PSA|JOB|PRO|ISA|JER|EZK|MAL)"', src + inspect.getsource(b))
    assert set(d.RELATIONS) == set(d.CFG["relations"]) and "parallel" in d.TREE_FLAT and "speech" not in d.FLAT


def test_configure_another_file(tmp_path):
    """configure(path) loads another settings file; a turned-off rule is off; the default comes back."""
    from macula import discourse_rules as d
    text = d.CONFIG_PATH.read_text(encoding="utf-8").replace(
        '[rules.circumstantial]\nscope = "not poetry"', '[rules.circumstantial]\nscope = "none"')
    alt = tmp_path / "alt.toml"
    alt.write_text(text, encoding="utf-8")
    try:
        d.configure(alt)
        assert not d.active("circumstantial", "GEN") and d.CONFIG_SHA256 != ""
        bad = tmp_path / "bad.toml"
        bad.write_text(text.replace('[rules.main_clause_chain]\nscope = "all"', '[rules.main_clause_chain]\nscope = "none"'), encoding="utf-8")
        with pytest.raises(ValueError):
            d.configure(bad)                                                                     # a rule of the model cannot be turned off
    finally:
        d.configure()
    assert d.active("circumstantial", "GEN")


def test_sources_pinned_and_checked(tmp_path, monkeypatch):
    """The build checks its inputs against [sources.*] and writes nothing when one differs (here: a changed spine pin)."""
    import copy
    from pathlib import Path
    import lexeme_macula
    from macula import build_clause_layout as b, discourse_rules as d, sources
    src = d.CFG["sources"]
    spine = Path(lexeme_macula.spine_path())
    common = dict(trees_db=Path(trees_macula.trees_path()), spine_db=spine, uhb_dir=tmp_path, uhb_files=[], vrs_files={}, tvtms_rev=None)
    bad = copy.deepcopy(src)
    bad["lexeme_spine"]["spine_content_sha256"] = "0" * 64
    _, problems = sources.check(bad, **common)
    assert any(p.startswith("lexeme_spine:") and "spine_content_sha256 = " in p for p in problems)
    assert any(p.startswith("versification:") for p in problems)                                  # no map files given: reported, not skipped
    text = d.CONFIG_PATH.read_text(encoding="utf-8").replace(src["lexeme_spine"]["spine_content_sha256"], "0" * 64)
    alt = tmp_path / "alt.toml"
    alt.write_text(text, encoding="utf-8")
    out = tmp_path / "out"
    monkeypatch.setattr("sys.argv", ["x", "--books", "RUT", "--out", str(out), "--config", str(alt)])
    try:
        with pytest.raises(SystemExit, match="lexeme_spine"):
            b.main()
    finally:
        d.configure()
    assert not out.exists()
