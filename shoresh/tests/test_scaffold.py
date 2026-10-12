"""/scaffold: one chapter of original-language tokens keyed by MACULA token key (the key lexeme-aligner publishes)."""
import pytest

import trees_macula

pytestmark = pytest.mark.skipif(not trees_macula.available(), reason="MACULA trees not built")


def test_gen_1_tokens_keys_and_structure():
    r = trees_macula.scaffold("GEN", 1)
    t = r["tokens"]
    assert len(t) == 690 and t[0]["key"] == "010010010011" and t[1]["key"] == "010010010012"
    assert t[1]["lemma"].startswith("ר") and t[1]["strong"] == "7225"
    assert not t[0]["content"] and t[1]["content"]                     # the prefix is a function token, the noun is content
    assert t[1]["lexeme"] == "hbo:7225" and t[1]["clause"] in r["clauses"] and t[1]["phrase"] in r["phrases"]
    assert r["phrases"][t[1]["phrase"]]["type"]


def test_greek_lexeme_is_the_aligner_lexeme():
    t = trees_macula.scaffold("JHN", 1)["tokens"]
    assert t[1]["lexeme"] == "grc:746" and len(t[1]["key"]) == 11


def test_unknown_chapter_is_an_error():
    assert "error" in trees_macula.scaffold("GEN", 99)


def test_language_depth_and_trailer():
    r = trees_macula.scaffold("DAN", 2)
    t = r["tokens"]
    assert t[0]["language"] == "hbo" and t[-1]["language"] == "arc"                            # Daniel 2:4b onward is Aramaic
    v9 = "".join(x["text"] + x["trailer"] for x in t if x["verse"] == 9)
    assert "֙לְ" not in v9                                                                      # no glued words at ketiv/qere
    c = r["clauses"]
    assert all(x["depth"] == (0 if x["parent"] is None else c[x["parent"]]["depth"] + 1) for x in c.values())
    assert trees_macula.scaffold("JHN", 1)["tokens"][0]["language"] == "grc"
