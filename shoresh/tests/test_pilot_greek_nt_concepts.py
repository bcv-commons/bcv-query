"""The pilot's reading of answers and its calls (macula/pilot_greek_nt_concepts.py); no model is called."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "shoresh"))
from macula import pilot_greek_nt_concepts as m  # noqa: E402

ITEMS = [{"id": "n1", "set": "quoted", "hebrew": ["H0559"], "inventory": ["H559.2", "H559.1", "H559.3"]},
         {"id": "n2", "set": "quoted", "hebrew": ["H0559"], "inventory": ["H559.2", "H559.1", "H559.3"]},
         {"id": "n3", "set": "dominated", "hebrew": ["H0559"], "inventory": ["H559.2", "H559.1", "H559.3"]},
         {"id": "n4", "set": "quoted", "hebrew": ["H5612"], "inventory": ["H5612.1"]}]


def test_parse():
    text = 'Here: [{"id": "n1", "choice": 2, "sure": true}, {"id": "n2", "choice": 9}, {"id": "n9", "choice": 1}, {"id": "n2", "choice": 3, "sure": false}]'
    assert m.parse(text, ITEMS[:2]) == {"n1": {"concept": "H559.1", "sure": True}, "n2": {"concept": "H559.3", "sure": False}}   # out of range, unknown id: dropped
    assert m.parse("no list", ITEMS[:2]) == {} and m.parse("[{]", ITEMS[:2]) == {}


def test_batches():
    bs = m.batches(ITEMS)
    assert [[it["id"] for it in bt] for bt in bs] == [["n1", "n2"], ["n3"]]          # one inventory and one set per call, quoted first, one concept: no call


def test_load_jev():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "jev.jsonl"
        f.write_text("".join(json.dumps(r) + "\n" for r in ({"id": "n1", "choice": "c2", "confidence": 0.93}, {"id": "n2", "choice": "c3", "confidence": 0.5},
                                                           {"id": "n3", "choice": "c7", "confidence": 0.9}, {"id": "n9", "choice": "c1", "confidence": 0.9})))
        assert m.load_jev(f, ITEMS) == {"n1": {"concept": "H559.1", "sure": True, "confidence": 0.93}, "n2": {"concept": "H559.3", "sure": False, "confidence": 0.5}}
        f.write_text(json.dumps({"id": "n5", "choice": "c2", "confidence": 0.9}) + "\n")                    # the choice after the inventory: no concept
        assert m.load_jev(f, [{"id": "n5", "inventory": ["H1.1"], "none": True}]) == {"n5": {"concept": "", "sure": True, "confidence": 0.9}}
