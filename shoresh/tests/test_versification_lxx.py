"""The lxx versification scheme: the rows written by hand for Daniel and Nehemiah (2026-11-22), checked against Brenton.
  python -m pytest shoresh/tests/test_versification_lxx.py -q   (or run the file: python shoresh/tests/test_versification_lxx.py)"""
import collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LXX = ROOT / "resources" / "versification" / "schemes" / "lxx.tsv"
ENG = ROOT / "shoresh" / "versification" / "data" / "vrs" / "eng.vrs"


def rows():
    out = []
    for ln in LXX.read_text(encoding="utf-8").splitlines():
        if ln.startswith("#") or ln.startswith("source_ref"):
            continue
        out.append(ln.split("\t"))
    return out


def kjv_shape():
    shape = {}
    for ln in ENG.read_text(encoding="utf-8").splitlines():
        p = ln.split()
        if p and not ln.startswith("#") and len(p) > 1 and ":" in p[1]:
            shape[p[0]] = {int(t.split(":")[0]): int(t.split(":")[1]) for t in p[1:]}
    return shape


def test_daniel_and_nehemiah_rows():
    m = {s: d for s, d, _ in rows()}
    assert m["DAN 3:91"] == "DAN 3:24" and m["DAN 3:97"] == "DAN 3:30"
    assert m["DAN 6:1"] == "DAN 5:31" and m["DAN 6:2"] == "DAN 6:1" and m["DAN 6:29"] == "DAN 6:28"
    assert m["NEH 10:1"] == "NEH 9:38" and m["NEH 10:40"] == "NEH 10:39"
    assert "DAN 3:24" not in m and "DAN 4:4" not in m and "DAN 5:30" not in m   # the Song has no row; ch. 4-5 as KJV
    assert not any(s.startswith("EST ") for s in m)                              # Esther left out on purpose


def test_daniel_nehemiah_one_to_one_onto_kjv():
    shape = kjv_shape()
    for book in ("DAN", "NEH"):
        rr = [(s, d) for s, d, _ in rows() if s.startswith(book + " ")]
        assert len({s for s, _ in rr}) == len(rr)                                 # one target per source verse
        targets = collections.Counter(d for _, d in rr)
        assert max(targets.values()) == 1                                         # read in reverse, unambiguous
        for _, d in rr:
            c, v = map(int, d.split(" ")[1].split(":"))
            assert 1 <= v <= shape[book][c]                                       # a real KJV verse


if __name__ == "__main__":
    test_daniel_and_nehemiah_rows()
    test_daniel_nehemiah_one_to_one_onto_kjv()
    print("ok")
