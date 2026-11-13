"""Every release script refuses TBTA and private inputs (development-phase plan, section 7).
  bcv-RAG/.venv/bin/python -m pytest shoresh/tests/test_release_guard.py -q"""
import sys
import argparse
import re
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from macula import release_guard as G  # noqa: E402

MACULA = Path(__file__).resolve().parents[1] / "macula"


def test_every_release_script_calls_the_guard():
    scripts = sorted(p for p in MACULA.glob("release_*.py") if p.name != "release_guard.py")
    assert scripts
    for p in scripts:
        s = p.read_text(encoding="utf-8")
        assert re.search(r"release_guard\.check\(\w+\)", s), f"{p.name} does not call release_guard.check"


@pytest.mark.parametrize("path", [
    "~/dev/make-tanakh-grammar/private/tbta/download/csv/x.csv",
    "~/dev/make-tanakh-research/private/rules/bridge/clause_feats_tbta_ot.json",
    "~/dev/make-tanakh-research/private/training/ind_ayt/x.json",
    "/somewhere/else/TaBiThA-export/a.sqlite",
])
def test_refused(path):
    assert G.forbidden(path)
    with pytest.raises(SystemExit):
        G.check(argparse.Namespace(table=Path(path), out="x"))


@pytest.mark.parametrize("path", [
    "~/dev/make-tanakh-research/internal-docs/handover/bcv-query-2026-11-12/hebrew_phrase_types_model.tsv",
    "../internal-docs/word-parts-release/v0.1-a",
    "macula/data/clause-layout",
])
def test_allowed(path):
    assert G.forbidden(path) is None
    G.check({"src": path, "tag": "v0.1", "allow_dirty": False})
