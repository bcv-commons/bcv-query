"""MACULA lowfat trees (NC exit step 3): the builder and the reader, on a tiny synthetic lowfat file (Hebrew-like keys), plus the real database when present."""
import sqlite3
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

LOWFAT = """<?xml version="1.0" encoding="UTF-8"?>
<chapter lang="he" id="GEN 1">
 <sentence id="GEN 1:1">
  <p><milestone unit="verse" id="GEN 1:1">GEN 1:1</milestone> x</p>
  <wg>
   <wg class="cl" rule="C-V-S-O">
    <w class="conj" xml:id="o010010010011" ref="GEN 1:1!1" after="" lemma="וְ" strongnumberx="1">וְ</w>
    <w role="v" class="verb" xml:id="o010010010021" ref="GEN 1:1!2" after=" " lemma="בָּרָא" strongnumberx="1254a">בָּרָא</w>
    <wg role="s" class="np" rule="NPofNP">
     <w class="noun" xml:id="o010010010031" ref="GEN 1:1!3" after=" " lemma="אֱלֹהִים" strongnumberx="430">אֱלֹהִים</w>
     <wg class="cl" rule="RelCl" role="adv">
      <w class="rel" xml:id="o010010010041" ref="GEN 1:1!4" after=" " lemma="אֲשֶׁר" strongnumberx="834">אֲשֶׁר</w>
      <w role="v" class="verb" xml:id="o010010010051" ref="GEN 1:1!5" after=" " lemma="עָשָׂה" strongnumberx="6213a">עָשָׂה</w>
     </wg>
    </wg>
    <wg role="o" class="np"><w class="noun" xml:id="o010010010061" ref="GEN 1:1!6" after="" lemma="שָׁמַיִם" strongnumberx="8064">שָׁמַיִם</w></wg>
   </wg>
  </wg>
 </sentence>
</chapter>
"""

KEYS = [("010010010011", "hbo:0001", 1), ("010010010021", "hbo:1254a", 1254), ("010010010031", "hbo:0430", 430), ("010010010041", "hbo:0834", 834),
        ("010010010051", "hbo:6213a", 6213), ("010010010061", "hbo:8064", 8064)]


@pytest.fixture()
def trees(tmp_path, monkeypatch):
    from macula import build_trees
    xml = tmp_path / "01-Gen-001-lowfat.xml"
    xml.write_text(LOWFAT, encoding="utf-8")
    sp = tmp_path / "lexeme-spine-macula.db"
    c = sqlite3.connect(sp)
    c.execute("CREATE TABLE spine_words(book TEXT, chapter INT, verse INT, idx INT, key TEXT, surface TEXT, lexeme TEXT, strong INT, lemma TEXT, is_content INT, "
              "morph TEXT, gloss TEXT, role TEXT, stem TEXT, person TEXT, number TEXT, gender TEXT, case_ TEXT, tense TEXT, voice TEXT, mood TEXT, degree TEXT, state TEXT)")
    for i, (k, lx, st) in enumerate(KEYS):
        c.execute("INSERT INTO spine_words VALUES ('GEN',1,1,?,?,?,?,?,?,1,'',?,'',?,'','','','','','','','','')", (i, k, "s", lx, st, "l", f"g{i}", "qal" if lx.startswith("hbo:1254") else ""))
    c.commit(); c.close()
    db = tmp_path / "trees-macula.db"
    con = sqlite3.connect(db)
    con.executescript(build_trees.SCHEMA)
    b = build_trees.Builder(con, "hbo")
    b.chapter(xml)
    con.commit()
    build_trees.finish(con, sp)
    con.commit(); con.close()
    monkeypatch.setenv("TREES_DB", str(db))
    monkeypatch.setenv("LEXEME_SPINE_DB", str(sp))
    monkeypatch.setenv("VERSE_SENSES_DB", str(sp))
    import trees_macula
    return trees_macula


def test_builder_assigns_clause_and_phrase(trees):
    con = trees._con()
    rows = {r["key"]: r for r in con.execute("SELECT * FROM words")}
    outer, inner = rows["010010010021"]["cl"], rows["010010010051"]["cl"]
    assert outer != inner                                          # the relative clause is a clause of its own
    assert rows["010010010031"]["cl"] == outer and rows["010010010031"]["ph"] is not None   # the subject np is a phrase of the outer clause
    assert rows["010010010021"]["ph"] is None and rows["010010010021"]["role"] == "v"        # a role-bearing word directly under the clause is its own phrase
    assert rows["010010010011"]["role"] is None                    # the conjunction is not part of any phrase
    con.close()


def test_syntax_shape_and_own_words(trees):
    r = trees.syntax("GEN", 1, 1)
    d = r["data"]
    assert r["corpus"] == "hebrew" and r["corpus_book"] == "Genesis" and d["book"] == "Genesis"
    assert len(d["clauses"]) == 2
    outer = d["clauses"][0]
    assert set(outer) >= {"type", "rela", "kind", "text", "phrases"} and outer["rule"] == "C-V-S-O"
    fns = [p["function"] for p in outer["phrases"]]
    assert fns == [None, "Verb", "Subject", "Object"]              # conjunction, verb, subject, object, in reading order
    assert [w["text"] for w in outer["phrases"][2]["words"]] == ["אֱלֹהִים"]    # the nested clause's words are not the subject's own
    assert outer["phrases"][1]["words"][0]["lex"] == "hbo:1254a" and outer["phrases"][1]["words"][0]["stem"] == "qal"
    assert d["clauses"][1]["phrases"][1]["function"] == "Verb"


def test_tree_groups_clauses_under_the_sentence(trees):
    d = trees.tree("GEN", 1, 1)["data"]
    assert len(d["sentences"]) == 1 and len(d["sentences"][0]["clauses"]) == 2 and d["sentences"][0]["text"].startswith("וְבָּרָא")


def test_passage_and_context(trees):
    p = trees.passage("GEN", 1, 1)["data"]["verses"][0]
    assert [w["lexeme"] for w in p["words"]][:2] == ["hbo:0001", "hbo:1254a"]
    assert set(p["words"][0]) >= {"monad", "text", "trailer", "lexeme", "gloss", "part_of_speech", "verbal_stem", "suffix"}
    c = trees.context("GEN", 1, 1, 2)["data"]                      # אֱלֹהִים
    assert {"word", "wg", "phrase", "clause", "sentence"} <= set(c)
    assert c["phrase"]["features"]["function"] == "Subject" and c["clause"]["features"]["otype"] == "clause"
    assert "error" in trees.context("GEN", 1, 1, 99)
    assert "error" in trees.syntax("GEN", 1, 2)


def test_syntax_search_function_and_aliases(trees):
    r = trees.syntax_search(strong="H0430", function="Subj")["data"]
    assert r["count"] == 1 and r["clauses"][0]["function"] == "Subject" and r["clauses"][0]["phrase"] == "אֱלֹהִים"
    assert trees.syntax_search(strong="H0430", function="Object")["data"]["count"] == 0
    assert trees.syntax_search(strong="H1254", function="Pred")["data"]["count"] == 1      # BHSA's Pred finds the verb
    assert trees.syntax_search(lex="hbo:8064", function="Objc")["data"]["count"] == 1
    assert trees.syntax_search(strong="H0430", book="EXO") == {"error": "no corpus mapping for book 'EXO'"}


def test_words_feed_filters_and_shape(trees):
    import words_macula
    words_macula._ranks.cache_clear()
    r = words_macula.list_words_filtered(corpus="hebrew", language="Hebrew", pos=["verb"], limit=10)
    assert r["total_pool"] == 2 and r["count"] == 2
    w = r["words"][0]
    assert set(w) >= {"node", "lex", "lexUtf8", "language", "pos", "stem", "tense", "rank", "sfx", "gloss", "strong", "ref", "clauseWords", "targetIndex"}
    assert w["lex"] == "hbo:1254a" and w["pos"] == "verb" and w["stem"] == "qal" and w["strong"] == "H1254" and w["ref"] == "Genesis 1:1" and w["language"] == "Hebrew"
    assert w["clauseWords"] == ["וְ", "בָּרָא ", "שָׁמַיִם"] or w["clauseWords"][w["targetIndex"]] == "בָּרָא "
    assert words_macula.list_words_filtered(corpus="hebrew", pos=["verb"], stem=["qal"])["total_pool"] == 1          # only the first verb carries a stem in the fixture
    assert words_macula.list_words_filtered(corpus="hebrew", pos=["subs"])["total_pool"] == 2                       # the noun and the object noun
    assert words_macula.list_words_filtered(corpus="hebrew", pos=["conj"])["total_pool"] == 1                       # וְ (cj) ... the relative אֲשֶׁר has class rel -> conj as well
    assert words_macula.list_words_filtered(corpus="hebrew", order="frequency", limit=3)["count"] == 3
    assert words_macula.list_words_filtered(corpus="hebrew", lex_filter={"hbo:0430"})["total_pool"] == 1
    assert words_macula.list_words_filtered(corpus="hebrew", language="Aramaic")["total_pool"] == 0


def test_bhsa_style_codes_map_both_ways():
    import words_macula as wm
    assert wm.bhsa_pos("noun", "proper") == "nmpr" and wm.bhsa_pos("noun", "common") == "subs" and wm.bhsa_pos("om", None) == "prep" and wm.bhsa_pos("adv", "negative") == "nega"
    assert wm.STEM_CODE["niphal"] == "nif" and wm.STEM_NAME["hif"] == "hiphil" and wm.HBO_TENSE["wayyiqtol"] == "wayq"


def test_corpus_switch_defaults_to_the_engine(monkeypatch):
    import corpus
    monkeypatch.delenv("STRUCTURE_BASE", raising=False)
    assert corpus.structure_base() == "bhsa" and corpus._on_macula() is False


REAL = HERE / "macula" / "trees-macula.db"


@pytest.mark.skipif(not REAL.exists() or not (HERE / "macula" / "lexeme-spine-macula.db").exists(), reason="trees not built locally")
def test_real_trees_cover_the_text(monkeypatch):
    monkeypatch.delenv("TREES_DB", raising=False)
    monkeypatch.delenv("LEXEME_SPINE_DB", raising=False)
    import trees_macula
    d = trees_macula.syntax("PSA", 3, 1)["data"]
    assert d["clauses"] and any(p["function"] == "Verb" for c in d["clauses"] for p in c["phrases"])


@pytest.mark.skipif(not REAL.exists() or not (HERE / "macula" / "lexeme-spine-macula.db").exists(), reason="trees not built locally")
def test_search_marks_nested_words_and_head_only_drops_them(monkeypatch):
    monkeypatch.delenv("TREES_DB", raising=False)
    monkeypatch.delenv("LEXEME_SPINE_DB", raising=False)
    import trees_macula
    allr = trees_macula.syntax_search(strong="G2316", function="Subject", limit=1000)["data"]["clauses"]
    only = trees_macula.syntax_search(strong="G2316", function="Subject", limit=1000, head_only=True)["data"]["clauses"]
    assert all("head" in c for c in allr)
    assert 0 < len(only) < len(allr) and all(c["head"] for c in only)


def test_stem_labels_are_characteristic_and_voiced():
    from macula import build_stem_senses as b
    raw = {1: {"gather": "gathered", "assembl": "assembled", "been": "been"}}
    stems = {"qal": ({"k1": 1}, {1: "gathered"}, {1: {"gather": 5, "been": 9}}, raw),
             "niphal": ({"k2": 1}, {1: "gathered"}, {1: {"gather": 5, "assembl": 4}}, raw)}
    assert b.relabel(stems, "freq") == {"qal": {1: "gathered"}, "niphal": {1: "gathered"}}
    v = b.relabel(stems, "voice")
    assert v["qal"][1] == "gathered"                                   # an auxiliary is never a label
    assert v["niphal"][1] == "be assembled"                            # characteristic against the other stem; passive stem gets "be"
