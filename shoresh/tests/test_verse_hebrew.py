"""verse_hebrew.py (word + parts shape of /verse) and the MACULA-based Hebrew path of data.verse.
  bcv-RAG/.venv/bin/python -m pytest shoresh/tests/test_verse_hebrew.py -q
"""
import os
import sqlite3
import sys
from pathlib import Path

import pytest

SHORESH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHORESH))
import verse_hebrew as vh  # noqa: E402


def tok(key, text, cls, strong="", lemma="", gloss="", **kw):
    return {"key": key, "text": text, "class": cls, "strong": strong, "lemma": lemma, "gloss": gloss, "role": kw.pop("role", ""), **kw}


def code(raw):
    import re
    d = re.sub(r"\D", "", raw or "")
    return f"H{int(d)}" if d else None


# Genesis 1:1 word 1 (be + reshit), word 2 (bara), and a word with a pronominal suffix and a prefix (Ps 3:1 be-borcho = be + borach + o)
GEN = [tok("010010010011", "בְּ", "prep", "0871a", "בְּ", "in"),
       tok("010010010012", "רֵאשִׁ֖ית", "noun", "7225", "רֵאשִׁית", "beginning", gender="feminine", number="singular", state="absolute"),
       tok("010010010021", "בָּרָ֣א", "verb", "1254", "בָּרָא", "he.created", stem="qal", person="third", number="singular", gender="masculine", tense="perfect"),
       tok("010010010061", "וְ", "cj", "2050b", "וְ", "and"), tok("010010010062", "אֵ֥ת", "ptcl", "0853", "אֵת", "(et)")]
PSA = [tok("190030010031", "בְּ֝", "prep", "0871a", "בְּ", "when"), tok("190030010032", "בָרְח", "verb", "1272", "בָּרַח", "flee"),
       tok("190030010033", "וֹ", "pron", "2050c", "הוּא", "he", person="third", number="singular", gender="masculine")]


def test_words_are_grouped_by_the_word_number_in_the_key():
    words = vh.build_words(GEN, code)
    assert [w["word"] for w in words] == [1, 2, 6] and [w["idx"] for w in words] == [0, 1, 2]
    assert [len(w["parts"]) for w in words] == [2, 1, 2]
    assert words[0]["key"] == "01001001001" and words[0]["surface"] == "בְּרֵאשִׁ֖ית"


def test_the_head_skips_prefixes_and_a_trailing_pronoun():
    words = vh.build_words(GEN, code)
    assert words[0]["strong"] == "H7225" and words[0]["head"] == "010010010012" and words[0]["lemma"] == "רֵאשִׁית"
    assert words[2]["strong"] == "H853" and words[2]["head"] == "010010010062"           # ve + et: the particle is the head
    suffixed = vh.build_words(PSA, code)[0]
    assert suffixed["strong"] == "H1272" and suffixed["head"] == "190030010032"          # be + borach + o: the verb, not the suffix
    assert [p["key"][-1] for p in suffixed["parts"]] == ["1", "2", "3"]


def test_a_lone_prefix_or_pronoun_is_its_own_head():
    assert vh.head_index([tok("1", "הַ", "art", "1886a")]) == 0
    assert vh.head_index([tok("1", "הוּא", "pron", "1931")]) == 0
    assert vh.head_index([tok("1", "לְ", "prep"), tok("2", "הַ", "art"), tok("3", "מֶּלֶךְ", "noun")]) == 2


def test_a_preposition_with_a_suffix_is_the_head_not_the_suffix():
    # 1 Chr 11:42 ve + al + ay ("and upon me"): MACULA gives the suffix its own Strong's number (2050c); the head must be al
    HU = "הוּא"
    assert vh.head_index([tok("1", "וְ", "cj", "2050b"), tok("2", "עָ", "prep", "5921"), tok("3", "לַי", "pron", "2050c", HU)]) == 1
    assert vh.head_index([tok("1", "לְ", "prep", "3807a"), tok("2", "וֹ", "pron", "2050c", HU)]) == 0           # lo = l + o
    assert vh.head_index([tok("1", "בְּ", "prep"), tok("2", "בָרְח", "verb"), tok("3", "וֹ", "pron", "2050c", HU)]) == 1
    assert vh.head_index([tok("1", "מֵ", "prep"), tok("2", "חֶלְבֵ", "noun"), tok("3", "הֶן", "pron", "2004", HU)]) == 1   # a suffix with a plain number


def test_an_independent_pronoun_is_a_head_even_after_a_prefix_or_with_a_preposition():
    HU = "הוּא"
    assert vh.head_index([tok("1", "וְ", "cj", "2050b"), tok("2", "הוּא", "pron", "1931", HU)]) == 1          # ve + hu "and he"
    assert vh.head_index([tok("1", "הַ", "art", "1886a"), tok("2", "הוּא", "pron", "1931a", HU)]) == 1       # ha + hu "that"
    assert vh.head_index([tok("1", "לָ", "prep", "3807a"), tok("2", "מָּה", "pron", "4100", "מָה")]) == 1        # la + mah "why"
    assert vh.head_index([tok("1", "וְ", "cj", "2050b"), tok("2", "אַתָּה", "pron", "0859", "אַתָּה")]) == 1


def test_morphology_is_structured_and_empty_fields_are_dropped():
    w = vh.build_words(GEN, code)
    assert w[0]["morph"] == {"class": "noun", "number": "singular", "gender": "feminine", "state": "absolute"}
    assert w[1]["morph"] == {"class": "verb", "stem": "qal", "person": "third", "number": "singular", "gender": "masculine", "tense": "perfect"}
    assert "morph" in w[0]["parts"][0] and w[0]["parts"][0]["morph"] == {"class": "prep"}


def test_aramaic_words_are_marked_only_when_the_source_says_so():
    dan = [dict(tok("270020040011", "וַֽ", "cj", "2050b"), wlang="H"), dict(tok("270020040012", "יְדַבְּר֧וּ", "verb", "1696"), wlang="H"),
           dict(tok("270020040021", "מַלְכָּא", "noun", "4430"), wlang="A")]
    w = vh.build_words(dan, code)
    assert "lang" not in w[0] and w[1]["lang"] == "arc"
    assert "lang" not in vh.build_words(GEN, code)[0]                                      # old databases without `wlang` still work


def test_tokens_out_of_order_still_give_text_order():
    shuffled = [GEN[3], GEN[1], GEN[0], GEN[4], GEN[2]]
    assert [w["word"] for w in vh.build_words(shuffled, code)] == [1, 2, 6]


MACULA = SHORESH / "macula" / "macula-spine.db"


@pytest.mark.skipif(not MACULA.exists(), reason="macula-spine.db not built locally")
class TestAgainstTheRealSpine:
    @pytest.fixture(autouse=True)
    def base(self, monkeypatch):
        import data
        self.data = data

    def test_genesis_1_1_has_seven_words_and_declares_hebrew_numbering(self):
        sp = self.data.verse("GEN", 1, 1)["spine"]
        assert sp["base"] == "macula" and sp["versification"] == "org" and len(sp["words"]) == 7
        assert [len(w["parts"]) for w in sp["words"]] == [2, 1, 1, 1, 2, 2, 2]
        assert sp["words"][0]["strong"] == "H7225" and sp["words"][0]["gloss"] and sp["words"][1]["strong"] == "H1254"

    def test_hebrew_numbering_the_psalm_title_is_verse_1_and_verse_0_does_not_exist(self):
        r = self.data.verse("PSA", 3, 1)["spine"]
        assert len(r["words"]) == 6 and r["words"][0]["lemma"].startswith("מִזְמוֹר")
        assert self.data.verse("PSA", 3, 0)["spine"] is None

    def test_the_nt_side_is_not_affected(self):
        sp = self.data.verse("JHN", 1, 1)["spine"]
        assert sp["language"] == "grc" and "base" not in sp


@pytest.mark.skipif(not MACULA.exists(), reason="macula-spine.db not built locally")
def test_concurrent_verse_requests_get_their_own_answers(monkeypatch):
    import concurrent.futures as cf
    import data
    refs = [("GEN", 1, v) for v in range(1, 20)] + [("PSA", 23, v) for v in range(1, 7)]
    serial = {r: [w["surface"] for w in data.verse(*r)["spine"]["words"]] for r in refs}
    with cf.ThreadPoolExecutor(16) as ex:
        out = list(ex.map(lambda r: (r, [w["surface"] for w in data.verse(*r)["spine"]["words"]]), refs * 40))
    assert all(got == serial[r] for r, got in out)


def test_directional_and_aramaic_emphatic_endings_are_not_heads():
    # Dan 2:4 malka "the king": MACULA tags the Aramaic emphatic -a as an article piece with pseudo Strong's 0001b; 1 Chr 4:41-style directional -ah is 1886
    assert vh.head_index([tok("1", "מַלְכָּ", "noun", "4430", "מֶלֶךְ"), tok("2", "א", "art", "0001b", "א")]) == 0
    assert vh.head_index([tok("1", "יָמּ", "noun", "3220"), tok("2", "ָה", "art", "1886")]) == 0
    # but a real article stays a prefix, also after a preposition
    assert vh.head_index([tok("1", "הַ", "art", "1886a"), tok("2", "מֶּלֶךְ", "noun")]) == 1
    assert vh.head_index([tok("1", "בַּ", "prep", "0871a"), tok("2", "הַ", "art", "1886a")]) == 1                 # ba + ha (rare, article last): prefix


def test_a_trailing_class_x_piece_is_an_ending():
    # Gen 20:1-style directional he: Gerar + ah (class x, pseudo Strong's 1886c); hava + h (cohortative/paragogic, 1886j); nagda + h
    assert vh.head_index([tok("1", "גְרָ֖רָ", "noun", "1642"), tok("2", "ה", "x", "1886c")]) == 0
    assert vh.head_index([tok("1", "הָ֚בָ", "verb", "3051"), tok("2", "ה", "x", "1886j")]) == 0
    assert vh.head_index([tok("1", "מִ", "prep"), tok("2", "לְ", "prep"), tok("3", "מַ֔עְלָ", "adv"), tok("4", "ה", "x", "1886c")]) == 2
