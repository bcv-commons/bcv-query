"""macula.spine_stamp: the spine content version (changes with any row) and the two Strong's-0 Greek lemmas."""
import shutil
import sqlite3

import pytest

import lexeme_macula
from macula import spine_stamp

SPINE = lexeme_macula.spine_path()
pytestmark = pytest.mark.skipif(SPINE is None, reason="lexeme spine not built")


def test_gap_strong():
    assert spine_stamp.gap_strong("grc", "0", "Ἀρνί") == 6095
    assert spine_stamp.gap_strong("grc", "746", "ἀρχή") is None
    assert spine_stamp.gap_strong("hbo", "0", "Ἀρνί") is None


def test_content_hash_changes_with_a_derived_column(tmp_path):
    p = tmp_path / "spine.db"
    shutil.copyfile(SPINE, p)
    first = spine_stamp.stamp(p)["spine_content_sha256"]
    assert spine_stamp.stamp(p)["spine_content_sha256"] == first                    # stable
    with sqlite3.connect(p) as db:
        db.execute("UPDATE spine_words SET is_superscription=1-is_superscription WHERE key=(SELECT MIN(key) FROM spine_words WHERE book='PSA')")
        meta = dict(db.execute("SELECT key, value FROM spine_meta"))
    assert spine_stamp.stamp(p)["spine_content_sha256"] != first
    assert dict(sqlite3.connect(p).execute("SELECT key, value FROM spine_meta"))["macula_spine_sha256"] == meta["macula_spine_sha256"]


def test_served_spine_has_no_strong_zero_content_words():
    db = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    assert db.execute("SELECT COUNT(*) FROM spine_words WHERE lexeme IN ('grc:0', 'hbo:0') AND is_content=1").fetchone()[0] == 0
