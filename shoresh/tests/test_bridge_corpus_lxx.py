"""Placing MACULA's Septuagint forms on Septuagint words, and carrying Hebrew lines over (macula/bridge_corpus_lxx.py)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "shoresh"))
from macula import bridge_corpus_lxx as m  # noqa: E402


def test_plain_and_numbers():
    assert m.plain("θεὸς,") == "θεοσ" and m.plain(None) == ""
    assert m.numbers("1722|1698") == ["1722", "1698"] and m.numbers("G0040") == ["40"] and m.numbers(None) == []


def test_place():
    greek = [("και", ["2532"]), ("ειπεν", ["3004"]), ("ο", ["3588"]), ("θεοσ", ["2316"]), ("και", ["2532"]), ("εγενετο", ["1096"]), ("λεγων", ["3004"])]
    hebrew = [("h1", "και", ["2532"]), ("h2", "ειπεν", ["3004"]), ("h3", "θεοσ", ["2316"]), ("h4", "και", ["2532"]),
              ("h5", "εγενηθη", ["1096"]), ("h6", "", []), ("h7", "ειπε", ["3004"])]
    got = m.place(hebrew, greek)
    assert got["h2"] == (1, "sure") and got["h3"] == (3, "sure")
    assert got["h1"] == (0, "order") and got["h4"] == (4, "order")              # two καί, two claims: in order
    assert got["h5"] == (5, "number")                                           # the form is not there, its number is
    assert got["h7"] == (6, "number")                                           # two words of 3004: the one nearest the neighbours
    assert "h6" not in got
    one = m.place([("a", "και", []), ("b", "θεοσ", [])], greek)                 # one claim, two καί: by the neighbours
    assert one["a"] == (0, "neighbours") or one["a"] == (4, "neighbours")


def test_carry():
    lines = [{1, 2}, {3, 4}, {5}]
    links = {1: 10, 2: 12, 3: 11, 4: 13, 5: 14}                                 # line 0's stretch 10-12 holds 11 of line 1
    assert m.carry(lines, links) == [None, None, (14, 14, 2)]
    assert m.carry([{1, 2}, {3}], {1: 10, 2: 12, 3: 13}) == [(10, 12, 0), (13, 13, 1)]   # 11 is unlinked: taken inside
    assert m.carry([{7}], {}) == [None]


def test_strong_key():
    from macula.bridge_corpus_units import strong_key
    assert strong_key("H0871a") == "0871a" and strong_key("0871a") == "0871a" and strong_key(871) == "0871"
    assert strong_key("G3962") == "3962" and strong_key("G0040") == "0040" and strong_key(None) is None and strong_key("") is None
