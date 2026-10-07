"""Psalm title spans (macula/psalm_title_spans.tsv + psalm_title_spans.py). Run from the repo root:
  bcv-RAG/.venv/bin/python -m pytest shoresh/tests/test_psalm_title_spans.py -q
"""
import sqlite3
import sys
from pathlib import Path

import pytest

SHORESH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHORESH))
from macula import psalm_title_spans as pts  # noqa: E402

UNTITLED = [1, 2, 10, 33, 43, 71, 91, 93, 94, 95, 96, 97, 99, 104, 105, 106, 107, 111, 112, 113, 114, 115, 116, 117, 118,
            119, 135, 136, 137, 146, 147, 148, 149, 150]


def test_table_is_complete_and_well_formed():
    spans = pts.load_spans()
    assert len(spans) == 116
    assert [s["chapter"] for s in spans] == sorted({s["chapter"] for s in spans})            # unique, ordered
    assert [c for c in range(1, 151) if c not in {s["chapter"] for s in spans}] == UNTITLED
    ev = {}
    for s in spans:
        ev[s["evidence"]] = ev.get(s["evidence"], 0) + 1
        assert s["first_key"] <= s["last_key"] and len(s["first_key"]) == len(s["last_key"]) == 12
        assert s["first_key"].startswith("19") and int(s["first_key"][2:5]) == s["chapter"] == int(s["last_key"][2:5])
        assert s["words"] >= 1 and s["hebrew"]
    assert ev == {"tvtms": 63, "macula-clauses": 52, "manual": 1}


def test_titles_that_run_into_verse_two_are_covered():
    by = {s["chapter"]: s for s in pts.load_spans()}
    for ch in (51, 52, 54, 60):                                  # the Hebrew title is verses 1+2
        assert by[ch]["verses"] == "1+2" and by[ch]["last_key"][5:8] == "002"
    assert by[3]["last_key"][5:8] == "001" and by[3]["words"] == 6          # all of PSA 3:1 is the title


def test_clause_titles_extend_past_the_first_clause():
    by = {s["chapter"]: s for s in pts.load_spans()}
    assert by[11]["words"] == 2 and by[87]["words"] == 4 and by[122]["words"] == 3     # lamnatzeach|le-David, ...|shir, shir ha-maalot le-David
    assert by[23]["words"] == 2 and by[132]["words"] == 2                             # body clauses are not absorbed


def test_flagged_keys_is_inclusive_and_chapter_local():
    spans = [{"first_key": "190030010011", "last_key": "190030010062"}]
    keys = ["190030010011", "190030010062", "190030010071", "190030020011", "190230010011"]
    assert pts.flagged_keys(keys, spans) == {"190030010011", "190030010062"}


@pytest.fixture()
def tiny_db(tmp_path):
    p = tmp_path / "s.db"
    db = sqlite3.connect(p)
    db.execute("CREATE TABLE spine_words(book TEXT, chapter INT, verse INT, key TEXT, is_superscription INT DEFAULT 0)")
    db.execute("CREATE TABLE spine_meta(key TEXT PRIMARY KEY, value TEXT)")
    for k in ("190030010011", "190030010062", "190030010071", "190030020011"):
        db.execute("INSERT INTO spine_words VALUES ('PSA', 3, 1, ?, 0)", (k,))
    db.execute("INSERT INTO spine_words VALUES ('GEN', 1, 1, '010010010011', 1)")     # a stray flag outside the Psalms is cleared
    db.commit(); db.close()
    return p


def test_apply_marks_exactly_the_span_and_is_idempotent(tiny_db):
    spans = [{"chapter": 3, "first_key": "190030010011", "last_key": "190030010062"}]
    assert pts.apply(tiny_db, spans) == (1, 2) and pts.apply(tiny_db, spans) == (2, 2)
    assert pts.check(tiny_db, spans) == []
    db = sqlite3.connect(tiny_db)
    assert db.execute("SELECT count(*) FROM spine_words WHERE is_superscription=1 AND book='GEN'").fetchone()[0] == 0
    note = db.execute("SELECT value FROM spine_meta WHERE key='superscription_source'").fetchone()[0]
    assert "no BHSA" in note and "Hebrew-only" in note


@pytest.mark.skipif(not (SHORESH / "macula" / "lexeme-spine-macula.db").exists(), reason="spine not built locally")
def test_the_local_published_spine_matches_the_table():
    assert pts.check(SHORESH / "macula" / "lexeme-spine-macula.db") == []
