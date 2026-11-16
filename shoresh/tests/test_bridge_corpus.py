"""The converter to one Context-Fabric dataset (macula/build_bridge_corpus.py): values, numbering, edges with values after a cached load."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "shoresh"))
from macula import build_bridge_corpus as m  # noqa: E402


def test_value():
    assert m.value(None) is None and m.value("") is None and m.value([]) is None
    assert m.value(False) == 0 and m.value(True) == 1 and m.value(0) == 0                   # false and 0 are values
    assert m.value(["fc.jus", "fc.imp"]) == "fc.jus fc.imp" and m.value(0.42) == 42


def small() -> m.Corpus:
    c = m.Corpus()
    for i, k in enumerate(("010010010011", "010010010012", "010010010021", "40001001001")):
        c.slot[k] = i + 1
        c.F["mid"][i + 1], c.F["text"][i + 1], c.F["trailer"][i + 1] = k, "x", " "
        c.origin.update({"mid": "words", "text": "words", "trailer": "words", "book": "words", "chapter": "words", "verse": "words", "sec": "words"})
    for typ, sl, key in (("verse", [1, 2, 3], ("GEN", 1, 1)), ("verse", [4], ("MAT", 1, 1)), ("clause", [1, 2, 3], "010010010011"), ("clause", [4], "40001001001"),
                         ("phrase", [3], None), ("chapter", [1, 2, 3], None), ("chapter", [4], None), ("book", [1, 2, 3], None), ("book", [4], None)):
        h = c.node(typ, sl, key)
        if typ in ("verse", "chapter", "book"):
            c.F["book"][h] = "GEN" if 1 in sl else "MAT"
            if typ == "book":
                c.F["sec"][h] = c.F["book"][h]
            if typ != "book":
                c.F["chapter"][h] = 1
            if typ == "verse":
                c.F["verse"][h] = 1
    c.put(c.at["clause"]["010010010011"], {"kind": "VC", "speech": 0, "case_": "", "interrog": False}, "cc_", "clause-columns")
    c.edge("arg", 2, ("phrase", 0), "o", "argument-roles")
    c.edge("parent", c.at["clause"]["40001001001"], c.at["clause"]["010010010011"], None, "hebrew-clause-layout")
    return c


def test_put_and_node():
    c = small()
    h = c.at["clause"]["010010010011"]
    assert c.F["cc_kind"][h] == "VC" and c.F["cc_speech"][h] == 0 and c.F["cc_interrog"][h] == 0 and "cc_case" not in c.F
    assert c.node("phrase", []) is None and c.words(["010010010012", "nokey"]) == [2]
    assert not c.edge("arg", None, h, "s", "argument-roles")


def test_save_and_load():
    """types are numbered one after the other, and an edge's value can be searched after a load from Context Fabric's cache"""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "tf"
        rep = m.save(small(), out)
        assert rep["nodes"]["word"] == 4 and rep["nodes"]["clause"] == 2 and not rep["features that lost a value (two rows on one unit)"]
        for _ in range(2):                                              # the second load reads the cache
            api = m.load(out)
            assert [len(list(api.F.otype.s(t))) for t in ("word", "phrase", "clause", "verse", "book")] == [4, 1, 2, 2, 2]
            assert len(list(api.S.search("v:word\np:phrase\nv -arg=o> p\n"))) == 1 and len(list(api.S.search("v:word\np:phrase\nv -arg=s> p\n"))) == 0
            assert len(list(api.S.search("c:clause cc_kind=VC\nd:clause\nd -parent> c\n"))) == 1
            assert api.T.nodeFromSection(("MAT", 1, 1)) is not None


def test_pins():
    p = m.pins()
    assert len(p["words"]["sha256"]) == 64 and all(len(x["revision"]) == 8 and x["tag"] and x["licence"] for x in p["layers"].values())
    assert m.version(p) == m.version(p) and m.version(p) != m.version({**p, "x": 1})
