"""Lexeme/sense read path on MACULA keys (lexeme_macula.py) and the LEXEME_BASE switch in data.py (NC exit step 2a).
Runs on the real lexeme-spine-macula.db + verse-senses.db and skips without them."""
import sys
from pathlib import Path

import pytest

SHORESH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHORESH))
import lexeme_macula as L  # noqa: E402

pytestmark = pytest.mark.skipif(not L.available(), reason="MACULA lexeme databases not present")


def test_lexeme_ids_and_homographs():
    assert L.is_lexeme_id("hbo:6942") and L.is_lexeme_id("hbo:0871a") and not L.is_lexeme_id("QDC[") and not L.is_lexeme_id("H6942")
    assert L.lexemes_of(6942) == ["hbo:6942"]
    assert {"hbo:0871a", "hbo:0871b"} <= set(L.lexemes_of(871))                     # one Strong's number, several lexemes


def test_sense_groups_have_the_hbo_db_shape():
    g = L.sense_concordance("H6942")["senses"][0]
    assert set(g) == {"lex", "stem", "sense", "label", "count", "refs"} and g["lex"] == "hbo:6942" and isinstance(g["sense"], str)
    counts = [x["count"] for x in L.sense_concordance("H6942")["senses"]]
    assert counts == sorted(counts, reverse=True)
    assert sum(counts) == L.lexeme_profile("hbo:6942")["total"]                     # unsensed occurrences are counted, as in hbo.db


def test_lexeme_profile_takes_macula_ids_and_codes_not_bhsa_ids():
    assert L.lexeme_profile("hbo:6942")["lex"] == "hbo:6942"
    fan = L.lexeme_profile("H871")
    assert "lexemes" in fan and len(fan["lexemes"]) >= 2                              # an H-code fans out over the homographs
    assert "error" in L.lexeme_profile("QDC[") and "no longer supported" in L.lexeme_profile("QDC[")["error"]
    assert "error" in L.lexeme_profile("G26")


def test_stem_views_are_recomputed_from_the_occurrences():
    ls = L.lex_senses("H6942")[0]
    assert ls["lex"] == "hbo:6942" and {"piel", "qal", "niphal"} <= set(ls["stems"])
    for stem, senses in ls["stems"].items():
        assert abs(sum(s["share"] for s in senses) - 1) < 0.01, stem                  # shares are within the stem
    assert L.stem_senses("H6942")[0]["senses"]["qal"]


def test_concordance_rows_are_in_hebrew_numbering_with_token_keys_and_senses():
    rows = L.occurrences("H7225", 3)
    assert rows[0]["ref"] == "GEN 1:1" and len(rows[0]["key"]) == 12 and rows[0]["sense"] == "beginning"


def test_the_switch_in_data_py(monkeypatch):
    import data
    monkeypatch.setenv("LEXEME_BASE", "bhsa")
    assert not data._on_macula()
    monkeypatch.setenv("LEXEME_BASE", "macula")
    assert data._on_macula()
    assert data.sense_concordance("H6942")["senses"][0]["lex"] == "hbo:6942"
    ws = data.word_study("H6942")
    assert ws["lex_senses"][0]["lex"] == "hbo:6942" and ws["stems"][0]["senses"]["qal"]
    assert data.lexicon_meanings_for_strongs("H6942", "x")[0]["grammar"]
    assert data.concordance("H7225", 2)["occurrences"][0]["key"]
