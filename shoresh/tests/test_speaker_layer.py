"""The built Hebrew speaker layer (macula/data/speaker-layer, from `python -m macula.build_speaker_layer`) is one consistent
structure: every segment names a quotation that exists at the segment's level, every quotation lies inside its parent at one level
below it, and every review row applies."""
import csv
from pathlib import Path

import pytest

LAYER = Path(__file__).resolve().parents[1] / "macula" / "data" / "speaker-layer"
pytestmark = pytest.mark.skipif(not (LAYER / "quotations.tsv").exists(), reason="speaker layer not built")


def _rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader((line for line in fh if not line.startswith("#")), delimiter="\t"))


@pytest.fixture(scope="module")
def quotes() -> dict:
    return {q["id"]: q for q in _rows(LAYER / "quotations.tsv")}


def test_segments_name_a_quotation_at_their_level(quotes):
    bad = []
    for f in sorted((LAYER / "segments").glob("*.tsv")):
        for r in _rows(f):
            q, lv = r["quotation"], int(r["level"])
            if (not q and lv) or (q and (q not in quotes or int(quotes[q]["level"]) != lv)):
                bad.append(f"{f.stem} {r['chapter']}:{r['verse']} {q} {lv}")
    assert not bad, bad[:10]


def test_quotation_levels_follow_their_parents(quotes):
    bad = []
    for q in quotes.values():
        p = quotes.get(q["parent"]) if q["parent"] else None
        if q["parent"] and p is None:
            bad.append(f"{q['id']}: parent {q['parent']} missing")
        elif int(q["level"]) != (int(p["level"]) + 1 if p else 1):
            bad.append(f"{q['id']}: level {q['level']} under {q['parent'] or '-'}")
        elif p and (p["last"] < q["first"] or q["last"] < p["first"]):
            bad.append(f"{q['id']}: outside {p['id']}")
    assert not bad, bad[:10]


def test_every_review_row_applies():
    path = LAYER / "_work" / "review_unapplied.tsv"
    if not path.exists() or "left out" in (LAYER / "report.md").read_text(encoding="utf-8").split("review rows applied")[-1][:80]:
        pytest.skip("built without the review rows")
    assert not _rows(path), [r["first"] + " " + r["field"] for r in _rows(path)]
