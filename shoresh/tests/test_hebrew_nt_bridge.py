"""The Hebrew NT bridge files (resources/hebrew_nt_bridge) and the rules of their builder; the tagger's reading without vowel points."""
import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "shoresh"))
from macula import build_hebrew_nt_bridge as b  # noqa: E402
from macula import clause_tagger as ct  # noqa: E402

OUT = ROOT / "resources" / "hebrew_nt_bridge"


def rows(name):
    lines = (OUT / name).read_text().splitlines()
    assert lines[0] + "\n" == b.HEADER
    return [l.split("\t") for l in lines[1:]]


def test_tier_files():
    files = sorted(OUT.glob("heb_*.tsv"))
    assert files, "no tier file"
    for f in files:
        rs = rows(f.name)
        total = collections.Counter()
        seen = set()
        for h, g, tier, count, kept, score, quoted in rs:
            assert re.fullmatch(r"H\d{4}", h) and re.fullmatch(r"G\d{4}", g), (h, g)
            assert tier == f.stem and int(count) >= b.MIN and 0 < float(score) <= 1
            assert kept == "" or 0 <= int(kept) <= int(count)
            assert 0 <= int(quoted) <= int(count)
            assert (h, g) not in seen
            seen.add((h, g))
            total[g] += float(score)
        assert max(total.values()) <= 1.0001
        assert [(r[1], -int(r[3])) for r in rs] == sorted((r[1], -int(r[3])) for r in rs)       # by Greek lexeme, then count
        top = {}
        for h, g, *_ in rs:
            top.setdefault(g, h)
        assert top["G3004"] == "H0559" and top["G2316"] == "H0430"                             # λέγω -> אמר, θεός -> אלהים


def test_codes():
    assert b.hcode("1886a") == "H1886" and b.hcode("0559") == "H0559" and b.hcode(None) is None and b.hcode("") is None
    assert b.gcode("26") == "G0026" and b.gcode(3004) == "G3004" and b.gcode("1417+3461") is None


def test_content_units():
    gw = {"a": {"class": "noun", "n": "5"}, "b": {"class": "prep", "n": "1722"}, "c": {"class": "noun", "n": "5"},
          "d": {"class": "verb", "n": "7"}, "e": {"class": "adv", "n": "9"}}
    ids = list(gw)
    assert b.content_units(ids, gw, ["5", "5", "7"]) == [["a"], ["c"], ["d"]]                    # adverbs and prepositions are not counted
    assert b.content_units(ids, gw, ["0005", "7"]) == [["a", "c"], ["d"]]                        # two words of one lexeme given as one
    assert b.content_units(ids, gw, ["5", "8"]) is None


def test_resolve():
    tok = {2: [{"i": 2, "part": 0, "class": "cj"}, {"i": 2, "part": 1, "class": "art"}, {"i": 2, "part": 2, "class": "noun"}],
           3: [{"i": 3, "part": 0, "class": "ptcl"}]}
    assert [r["part"] for r in b.resolve([2], tok, "noun")] == [2]                               # a content word takes the content part
    assert [r["part"] for r in b.resolve([2], tok, "conj")] == [0]                               # a function word its own family
    assert [r["part"] for r in b.resolve(["2.1"], tok, "noun")] == [1]                           # a named part is taken as named
    assert [r["i"] for r in b.resolve([3], tok, "noun")] == [3]                                  # a token of one part is that part
    assert b.resolve([9], tok, "noun") is None and b.resolve(["2.7"], tok, "noun") is None


def test_depoint():
    v = {"ref": "x", "words": [{"text": ct.pointed("בַּמָּשִׁיחַ"), "parts": [{"len": 3, "lemma": "בְּ"}, {"len": 0, "lemma": "הַ"}, {"len": 9, "lemma": "מָשִׁיחַ"}]}]}
    assert sum(p["len"] for p in v["words"][0]["parts"]) == len(v["words"][0]["text"])
    d = ct.depoint(v)["words"][0]
    assert d["text"] == "במשיח" and [p["len"] for p in d["parts"]] == [1, 0, 4]
    assert [p["lemma"] for p in d["parts"]] == ["בְּ", "הַ", "מָשִׁיחַ"]                            # the lemma labels keep their points
    assert v["words"][0]["parts"][0]["len"] == 3                                                 # the pointed verse is left as it was


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)


def test_quotes():
    """a Hebrew NT verse that follows a Tanakh verse is found from the lexemes alone; a phrase any text shares is not"""
    verses = {("DEU", 8, 3): ["H3808", "H3899", "H0905", "H2421", "H0120", "H3605", "H4161", "H6310", "H3068"],
              ("GEN", 1, 1): ["H7225", "H1254", "H0430", "H8064", "H0776"]}
    for i in range(60):                                                     # verses that make H0559 H3068 a common pair of lexemes
        verses[("ISA", 1, i + 1)] = ["H0559", "H3068", f"H{9000 + i}"]
    t = b.Tanakh(verses)
    got = t.follows(["H0559", "H3068", "H3808", "H3899", "H0905", "H2421", "H0120", "H5315"])
    assert [(x[3], x[1], x[2]) for x in got] == [(("DEU", 8, 3), 5, 5)] and got[0][4] == [2, 3, 4, 5, 6] and got[0][0] >= b.QUOTE_MARK
    assert t.follows(["H0559", "H3068", "H5315"]) == []                    # two common lexemes in a row weigh too little
    part = lambda i, strong, cls="noun": {"i": i, "part": 0, "class": cls, "strong": strong}
    ana = {("MAT", 4, 4): {0: [part(0, "559", "verb")], 1: [part(1, "3808", "adv")], 2: [part(2, "3899")], 3: [part(3, "905")],
                           4: [part(4, "2421", "verb")], 5: [part(5, "120")], 6: [part(6, None)]}}
    listed, marked = b.quotes(ana, t, ["MAT"])
    assert [x[:2] for x in listed] == [("MAT 4:4", "DEU 8:3")]
    assert marked == {("MAT", 4, 4, i, 0): "DEU 8:3" for i in range(1, 6)}
    row = lambda h, g, tanakh: {"link": "kept", "greek_strong": g, "hebrew_strong": h, "tanakh": tanakh}
    assert b.tier([row("H3899", "G0740", "DEU 8:3"), row("H3899", "G0740", None), row("H3899", "G0740", None)], "x") == \
        [("H3899", "G0740", "x", 3, 3, 1.0, 1)]
    for f in sorted((OUT / "quotes").glob("heb_*.tsv")):
        lines = f.read_text().splitlines()
        assert lines[0] + "\n" == b.QUOTE_HEADER and len(lines) > 100
        rs = [l.split("\t") for l in lines[1:]]
        assert all(float(r[2]) >= b.QUOTE_LIST and int(r[3]) >= int(r[4]) >= 2 for r in rs)
        assert ("MAT 4:4", "DEU 8:3") in {(r[0], r[1]) for r in rs if float(r[2]) >= b.QUOTE_MARK}
