"""Guard for the NC exit: BHSA/ETCBC/OpenHebrewBible-tied files must be registered in resources/LICENSES.md; open outputs must stay clean.
Run from the repo root:  bcv-RAG/.venv/bin/python -m pytest shoresh/tests/test_nc_register.py -q
"""
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SHORESH = REPO / "shoresh"
sys.path.insert(0, str(SHORESH))
PAT = re.compile(r"BHSA|ETCBC|OpenHebrewBible|Open Hebrew Bible|hbo\.db", re.I)
TEXT = (".tsv", ".csv", ".md", ".json", ".txt")


def _tracked_resources() -> list[str]:
    return subprocess.run(["git", "ls-files", "resources"], cwd=REPO, capture_output=True, text=True, check=True).stdout.split()


def _register() -> list[str]:
    entries = []
    for line in (REPO / "resources" / "LICENSES.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"- `([^`]+)`", line)
        if m:
            entries.append("resources/" + m.group(1))
    return entries


def _registered(path: str, entries: list[str]) -> bool:
    return any(path == e or (e.endswith("/") and path.startswith(e)) for e in entries)


def test_every_tracked_file_that_mentions_bhsa_is_registered():
    entries = _register()
    unregistered = []
    for f in _tracked_resources():
        if not f.endswith(TEXT) or not (REPO / f).exists() or f == "resources/LICENSES.md":   # the register itself talks about BHSA
            continue
        with open(REPO / f, encoding="utf-8", errors="replace") as fh:
            head = [next(fh, "") for _ in range(30)]
        if any(PAT.search(line) for line in head) and not _registered(f, entries):
            unregistered.append(f)
    assert not unregistered, ("these tracked files mention BHSA/ETCBC/OHB in their header but are not listed in resources/LICENSES.md "
                              f"(classify them there, or remove the NC data): {unregistered}")


def test_register_has_no_dead_entries():
    tracked = set(_tracked_resources())
    dead = [e for e in _register() if not any(t == e or (e.endswith("/") and t.startswith(e)) for t in tracked)
            and not e.endswith(".local.tsv") and e.split("/")[1] not in ("bhsa_hierarchy", "bhsa_structural", "syntax_profiles")]
    assert not dead, f"LICENSES.md lists paths that are not tracked: {dead}"


def test_legacy_nc_folders_are_not_tracked_any_more():
    for prefix in ("resources/bhsa_hierarchy/", "resources/bhsa_structural/", "resources/syntax_profiles/"):
        assert not [f for f in _tracked_resources() if f.startswith(prefix)], f"{prefix} must stay untracked (BHSA-derived)"
    assert "parallelism_pairs.local.tsv" not in " ".join(_tracked_resources())
    tiers = {l.split("\t")[2] for l in (REPO / "resources/parallelism/parallelism_pairs.tsv").read_text(encoding="utf-8").splitlines()
             if l and not l.startswith("#") and not l.startswith("strong_a")}
    assert tiers == {"tomim_confirmed"}, f"the tracked parallelism file may only hold the T'OMIM-confirmed tier, found {tiers}"


def test_open_licensed_manifests_do_not_list_bhsa_inputs():
    open_lic = re.compile(r"cc0|cc-by", re.I)
    for f in _tracked_resources():
        if not f.endswith("manifest.json") or not (REPO / f).exists():
            continue
        m = json.loads((REPO / f).read_text(encoding="utf-8"))
        if not open_lic.search(str(m.get("license", ""))):
            continue
        inputs = json.dumps([m.get(k) for k in ("signals", "inputs", "sources") if k in m])
        assert not PAT.search(inputs), f"{f} declares an open licence but lists a BHSA/OHB input: {inputs[:200]}"


def test_publisher_refuses_the_bhsa_bearing_spines():
    import publish_files
    assert {"lexeme-spine.db", "lexeme-spine-bhsa-baseline.db"} <= set(publish_files.REFUSE)
    assert all(Path(p).name not in publish_files.REFUSE for p in publish_files.DEFAULT)


@pytest.mark.skipif(not (SHORESH / "macula" / "lexeme-spine-macula.db").exists(), reason="spine not built locally")
def test_published_spine_has_no_bhsa_columns_or_provenance():
    db = sqlite3.connect(f"file:{SHORESH / 'macula' / 'lexeme-spine-macula.db'}?mode=ro", uri=True)
    cols = {r[1] for r in db.execute("PRAGMA table_info(spine_words)")}
    assert not cols & {"phrase_id", "function", "rela", "sense", "sense_conf", "sense_source"}, "BHSA-derived columns in the published spine"
    meta = dict(db.execute("SELECT key, value FROM spine_meta"))
    assert "no BHSA-derived columns" in meta["variant"] and "no BHSA" in meta["superscription_source"]
    assert meta["license"].startswith("CC BY")
