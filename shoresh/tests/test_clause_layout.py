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
    if not (cache / b.UHB_TAG / "27-DAN.usfm").exists():
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
    assert d.RULES_VERSION >= "0.2"
    assert d.is_subordinator({"lemma": "\u05db\u05bc\u05b4\u05d9", "wlang": "H"})                  # כִּי in MACULA's order (dagesh first)
    assert not d.is_subordinator({"lemma": "הֵן", "wlang": "H"}) and d.is_subordinator({"lemma": "הֵן", "wlang": "A"})
