"""MCP morphology_concordance and the Torah shared-lexemes helper on MACULA lexeme tags (NC exit step 2)."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.mcp import tools  # noqa: E402


@pytest.fixture()
def db(monkeypatch):
    con = sqlite3.connect(":memory:")
    con.executescript("""
      CREATE TABLE chunks (id TEXT, doc_id TEXT);
      CREATE TABLE tags (doc_id TEXT NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (doc_id, tag));
      CREATE TABLE passage_refs (doc_id TEXT, start_bbcccvvv INTEGER, end_bbcccvvv INTEGER);
    """)
    rows = {  # doc, ref, tags
        "d1": (1001001, ["lexeme:hbo:6942", "lexemestem:hbo:6942.piel", "lexemesense:hbo:6942.1", "lexemestemsense:hbo:6942.piel.1", "lexeme:hbo:0871a"]),
        "d2": (1001002, ["lexeme:hbo:6942", "lexemestem:hbo:6942.hiphil", "lexemesense:hbo:6942.4", "lexemestemsense:hbo:6942.hiphil.4", "lexeme:hbo:0871b"]),
        "d3": (2001001, ["lexeme:hbo:0871a", "lexeme:hbo:7225"]),
    }
    for d, (ref, tags) in rows.items():
        con.execute("INSERT INTO chunks VALUES (?,?)", (d + "c", d)); con.execute("INSERT INTO passage_refs VALUES (?,?,?)", (d, ref, ref))
        con.executemany("INSERT INTO tags VALUES (?,?)", [(d, t) for t in tags])
    monkeypatch.setattr(tools.citations_mod, "resolve_many", lambda db, ids: ids)
    monkeypatch.setattr(tools, "chunk_preview_from_card", lambda c, lang="en": {"id": c})
    import server.original_words as ow
    monkeypatch.setattr(ow, "shoresh_get", lambda path, params=None, timeout=4.0: {"senses": [
        {"lex": "hbo:6942", "stem": "piel", "sense": "1", "label": "sanctuary", "count": 50, "refs": []},
        {"lex": "hbo:6942", "stem": "hiphil", "sense": "4", "label": "dedicated", "count": 18, "refs": []}]} if path == "/lexeme/hbo:6942" else None)
    return con


def call(db, **args):
    return tools._morphology_concordance(args, db)


def test_lexeme_stem_and_sense_narrow_the_verses(db):
    assert call(db, lexeme="hbo:6942")["total"] == 2
    r = call(db, lexeme="hbo:6942", stem="hiphil")
    assert r["total"] == 1 and [v["id"] for v in r["verses"]] == ["d2c"] and r["tags"] == ["lexemestem:hbo:6942.hiphil"]
    r = call(db, lexeme="hbo:6942", stem="piel", sense="1")
    assert r["total"] == 1 and r["sense_gloss"] == "sanctuary"
    assert call(db, lexeme="hbo:6942", sense="4")["tags"] == ["lexemesense:hbo:6942.4"]


def test_the_senses_of_one_lexeme_come_from_shoresh_and_can_be_filtered_by_stem(db):
    assert [(s["stem"], s["gloss"]) for s in call(db, lexeme="hbo:6942")["senses"]] == [("piel", "sanctuary"), ("hiphil", "dedicated")]
    assert [s["gloss"] for s in call(db, lexeme="hbo:6942", stem="piel")["senses"]] == ["sanctuary"]


def test_a_strong_code_searches_every_homograph_lexeme_in_the_index(db):
    r = call(db, lexeme="H871")
    assert r["lexemes"] == ["hbo:0871a", "hbo:0871b"] and r["total"] == 3 and r["senses"] == []


def test_bhsa_ids_and_an_untagged_index_are_clear_errors(db):
    with pytest.raises(ValueError, match="BHSA lex-ids are no longer supported"):
        call(db, lexeme="QDC[")
    db.execute("DELETE FROM tags WHERE tag LIKE 'lexeme%'")
    with pytest.raises(ValueError, match="no lexeme tags"):
        call(db, lexeme="hbo:6942")


def test_torah_shared_strongs_come_from_the_lexeme_tags(db):
    assert tools._torah_shared_lexemes(1001001, 1001001, 2001001, 2001001, db) == ["H0871"]
    assert tools._torah_shared_lexemes(1001001, 1001002, 2001001, 2001001, db) == ["H0871"]
