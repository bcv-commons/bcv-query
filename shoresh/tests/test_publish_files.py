"""publish_files: a new spine build is staged as a GitHub release whose notes name its sha256."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish_files as pf  # noqa: E402


def test_new_build_is_staged_with_findable_notes(tmp_path, monkeypatch):
    spine = tmp_path / "toy-spine.db"
    db = sqlite3.connect(spine)
    db.execute("CREATE TABLE spine_words(key TEXT, lemma TEXT)")
    db.execute("CREATE TABLE spine_meta(key TEXT PRIMARY KEY, value TEXT)")
    db.execute("INSERT INTO spine_meta VALUES ('license', 'CC0')")
    db.commit(); db.close()
    monkeypatch.setattr(pf, "RELEASES", tmp_path / "releases")
    e = pf.entry(spine)
    tag, z, notes = pf.stage_release(spine, e, "first build", set())
    from compression import zstd
    assert tag == f"toy-spine-{e['modified'][:10]}"
    assert zstd.decompress(z.read_bytes()) == spine.read_bytes()
    assert pf.NOTES_DB_SHA.findall(notes.read_text(encoding="utf-8")) == [e["sha256"]]
