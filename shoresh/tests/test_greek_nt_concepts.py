"""The rules that carry Hebrew concepts to Greek NT words (macula/build_greek_nt_concepts.py)."""
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "shoresh"))
from macula import build_greek_nt_concepts as m  # noqa: E402


def concepts():
    c = m.Concepts.__new__(m.Concepts)
    c.lexeme = {"H559.1": "H0559", "H559.2": "H0559", "H1697.1": "H1697", "H1697.2": "H1697"}
    c.prior = collections.defaultdict(collections.Counter, {"H0559": collections.Counter({"H559.1": 90, "H559.2": 10}),
                                                            "H1697": collections.Counter({"H1697.1": 60, "H1697.2": 40})})
    c.greek = collections.defaultdict(collections.Counter, {"G3004": collections.Counter({"H559.1": 70, "H559.2": 5, "H1697.2": 1}),
                                                            "G4487": collections.Counter({"H1697.2": 1})})
    return c


def test_project():
    c = concepts()
    assert c.project("G3004", {"H0559"}) == ("both", [("H559.1", 70), ("H559.2", 5)])            # the lexeme's concepts the Greek word renders
    assert c.project("G3004", {"H0559", "H1697"})[1][0] == ("H559.1", 70)                         # two editions, two lexemes: one ranking
    assert c.project("G9999", {"H1697"}) == ("hebrew", [("H1697.1", 60), ("H1697.2", 40)])       # no Septuagint evidence: the lexeme's own order
    assert c.project("G3004", {"H0430"}) == ("septuagint", [("H559.1", 70), ("H559.2", 5), ("H1697.2", 1)])   # a lexeme without concepts
    assert c.project("G9999", set()) == ("", [])
    assert c.project("G4487", {"H1697"}, ("H1697.2", "G4487")) == ("hebrew", [("H1697.1", 60), ("H1697.2", 40)])   # the one occurrence left out
    assert c.project("G4487", {"H1697"}, ("H1697.2", "G3004")) == ("both", [("H1697.2", 1)])     # another Greek word's occurrence: nothing to leave out


def test_ranked():
    assert m.ranked({"b": 2, "a": 2, "c": 5}) == [("c", 5), ("a", 2), ("b", 2)]


if __name__ == "__main__":
    test_project(); test_ranked(); print("ok")
