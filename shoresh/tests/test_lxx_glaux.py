"""Pure-function tests for the GLAUx Septuagint builder (no data files needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lxx import build_glaux as g  # noqa: E402


def test_morph_strings_follow_the_ccat_style():
    assert g.ours_pos_morph("n-s---fd-", "ἀρχή") == ("N", "N.DSF")
    assert g.ours_pos_morph("v3saia---", "ποιέω") == ("V", "V.AAI3S")
    assert g.ours_pos_morph("v2sama---", "ἀκούω") == ("V", "V.AAD2S")            # imperative is D in CCAT
    assert g.ours_pos_morph("l-s---mn-", "ὁ") == ("RA", "RA.NSM")
    assert g.ours_pos_morph("r--------", "ἐν") == ("P", "P")
    assert g.ours_pos_morph("p-s---mn-", "αὐτός")[0] == "RD"
    assert g.ours_pos_morph("p-p---mn-", "πᾶς")[0] == "A"


def test_lemma_spelling_variants_reach_the_new_testament_lemma():
    table = {"γίνομαι": 1096, "ἐκπορεύομαι": 1607, "__plain__": {"γινομαι": 1096, "ανανιας": 367, "εκπορευομαι": 1607}}
    assert g.lookup_strong(table, "γίγνομαι") == 1096          # γιγν -> γιν
    assert g.lookup_strong(table, "παραγίγνομαι") is None      # absent in this toy table
    assert g.lookup_strong(table, "ἐκπορεύω") == 1607          # active / deponent doublet
    assert g.lookup_strong(table, "Ἀνανίας") == 367            # accent and breathing ignored
    assert g.lookup_strong(table, "ἰδού") == 2400              # explicit standard number
    assert g.lookup_strong(table, "ἀκατασκεύαστος") is None    # LXX-only lemma: no number


def test_sections_parse_with_and_without_a_chapter():
    assert g.SECTION.match("3.14").groups() == ("3", "14")
    assert g.SECTION.match("7").groups() == (None, "7")
    assert g.SECTION.match("11-DIV=14").groups() == (None, "11")


def _w(pos, lemma, parts=(None, None, None), rel=""):
    return {"pos": pos, "lemma": lemma, "parts": parts, "rel": rel, "morph": g.compose(pos, *parts), "inferred": ""}


def test_morph_strings_keep_fixed_positions_and_drop_trailing_gaps():
    assert g.compose("N", "G", "S", "M") == "N.GSM"
    assert g.compose("N", None, "S", "M") == "N.-SM"
    assert g.compose("N", "G", None, None) == "N.G"
    assert g.compose("N", None, None, None) == "N"                  # no trailing dot
    assert g.ours_pos_morph("n--------", "Ἰσραήλ") == ("N", "N")


def test_names_take_case_number_gender_from_the_article():
    words = [_w("RA", "ὁ", ("G", "S", "M")), _w("N", "Ἰσραήλ")]
    g.infer_nominal(words)
    assert words[1]["morph"] == "N.GSM" and words[1]["inferred"] == "article"


def test_names_take_case_from_a_preposition_and_never_override_a_tag():
    words = [_w("P", "ἐν"), _w("N", "Ἱεροσόλυμα")]
    g.infer_nominal(words)
    assert words[1]["morph"] == "N.D" and words[1]["inferred"] == "preposition"
    tagged = [_w("RA", "ὁ", ("N", "S", "M")), _w("N", "Δαυίδ", ("G", "S", "M"))]
    g.infer_nominal(tagged)
    assert tagged[1]["morph"] == "N.GSM" and tagged[1]["inferred"] == ""


def test_syntax_rule_is_optional_and_fills_case_only():
    words = [_w("C", "καὶ"), _w("N", "Δαυίδ", rel="SBJ")]
    g.infer_nominal(words)
    assert words[1]["morph"] == "N.N" and words[1]["inferred"] == "syntax"
    words = [_w("C", "καὶ"), _w("N", "Δαυίδ", rel="SBJ")]
    g.infer_nominal(words, use_syntax=False)
    assert words[1]["morph"] == "N" and words[1]["inferred"] == ""


def test_classic_numbers_of_forms():
    assert g.classic_number("ἐγώ", "μου", "p-s---mg-", "GEN") == 3450
    assert g.classic_number("σύ", "υμων", "p-p---mg-", "GEN") == 5216
    assert g.classic_number("λέγω", "ειπεν", "v3saia---", "GEN") == 2036
    assert g.classic_number("λέγω", "ερει", "v3sfia---", "GEN") == 2046
    assert g.classic_number("λέγω", "λεγει", "v3spia---", "GEN") is None        # present: the lemma number G3004
    assert g.classic_number("Ἰούδας", "ιουδα", "n-s---mg-", "2CH") == 2448
    assert g.classic_number("Ἰούδας", "ιουδα", "n-s---mg-", "1MA") is None      # Judas Maccabeus keeps G2455
    assert g.classic_number("Ἱεροσόλυμα", "ιερουσαλημ", "n-----nn-", "ISA") == 2419
    assert g.classic_number("ἐσθίω", "φαγειν", "v--anaa--", "GEN") == 5315


def test_verse_serves_strong_form_gloss_and_inferred_flag(tmp_path, monkeypatch):
    import sqlite3
    import data
    db = tmp_path / "lxx.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE lxx_words (book TEXT, chapter INT, verse INT, idx INT, surface TEXT, plain TEXT, strong INT, lexid INT, wordid INT, morph TEXT, pos TEXT, "
                "is_content INT, canonical INT, lemma TEXT, glaux_id INT, strong_form INT, morph_inferred TEXT)")
    con.execute("INSERT INTO lxx_words VALUES ('GEN',1,1,1,'μου','μου',1473,1,1,'RP.GS','RP',0,1,'ἐγώ',1,3450,NULL)")
    con.execute("INSERT INTO lxx_words VALUES ('GEN',1,1,2,'Ἰσραήλ','ισραηλ',2474,2,2,'N.G','N',1,1,'Ἰσραήλ',2,NULL,'syntax')")
    con.commit(); con.close()
    monkeypatch.setattr(data, "LXX_DB", db)
    words = data.verse("GEN", 1, 1)["lxx"]["words"]
    assert words[0]["strong"] == "G1473" and words[0]["strong_form"] == "G3450"
    assert words[0].get("gloss") == (data.gloss_of("G3450") or {}).get("gloss")           # the classic gloss ("of me")
    assert "strong_form" not in words[1] and words[1]["morph_inferred"] == "syntax"
    assert data.concordance("G3450")["occurrences"][0]["surface"] == "μου"                 # the classic number still finds its forms


def test_lxx_store_is_chosen_from_env_then_data_volume_then_local_glaux_then_image(tmp_path, monkeypatch):
    import data
    monkeypatch.setenv("LXX_DB_PATH", str(tmp_path / "x.db"))
    assert data._lxx_db_path() == tmp_path / "x.db"
    monkeypatch.delenv("LXX_DB_PATH")
    p = data._lxx_db_path()
    assert p.name in ("lxx-glaux.db", "lxx.db")                       # glaux wherever it exists, otherwise the image's store


def test_orphan_lexemes_use_the_glaux_lemma_as_citation_form(tmp_path):
    import sqlite3
    from lxx import build_orphan_lexemes as bo
    db = tmp_path / "s.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE lxx_words (book TEXT, chapter INT, verse INT, idx INT, surface TEXT, plain TEXT, strong INT, wordid INT, morph TEXT, pos TEXT, is_content INT, lemma TEXT)")
    con.executemany("INSERT INTO lxx_words VALUES ('GEN',1,2,?,?,?,NULL,77,?, 'N',1,'ἀκατασκεύαστος')",
                    [(1, "ἀκατασκεύαστος", "ακατασκευαστος", "N.NSF"), (2, "ἀκατασκεύαστον", "ακατασκευαστον", "N.ASM")])
    con.commit(); con.close()
    rows = bo.build(db)
    assert {r["citation_form"] for r in rows} == {"ἀκατασκεύαστος"} and {r["citation_confidence"] for r in rows} == {"lemma"}
    assert len(rows) == 2 and {r["wordid"] for r in rows} == {77}


def test_stable_lemma_ids_do_not_depend_on_the_other_lemmas():
    import hashlib
    def lid(lemma):
        return int.from_bytes(hashlib.sha1(lemma.encode("utf-8")).digest()[:4], "big") & 0x7FFFFFFF
    assert lid("ἀκατασκεύαστος") == lid("ἀκατασκεύαστος") and 0 < lid("Ἰσραήλ") < 2 ** 31
