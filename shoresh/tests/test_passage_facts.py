"""Passage facts: the decoding table, the source table's licence rules, TBTA off by default, and the CC BY export's filter."""
import csv
import json
import shutil
from pathlib import Path

import pytest

from macula import build_passage_facts as pf

HAVE_DATA = pf.SPINE.exists() and pf.TREES.exists() and (pf.LAYER / "quotations.tsv").exists() and pf.GRC_LAYOUT.exists()


def test_codes_unique_and_closed_maps_covered():
    rows = pf._tsv(pf.CODES)
    codes = [r["code"] for r in rows]
    assert len(codes) == len(set(codes))
    assert all(r["english"] for r in rows)
    for table in (pf.QUOTE_TYPE, pf.FOUND, pf.NAMED_BY, pf.HEB_FORCE):
        assert set(table.values()) <= set(codes), set(table.values()) - set(codes)
    for group in pf.OPEN:
        assert group in codes or group in ("sdbh", "louw_nida")     # TBTA's and delivery's groups are kinds; the domain groups are of `domain`
    assert "domain" in codes and "note" in codes


def test_tbta_disabled_and_enabled_sources_open():
    src = pf.sources()
    assert src["tbta"]["enabled"] == "0"
    assert not pf.enabled("tbta")
    for s, r in src.items():
        if r["enabled"] == "1":
            assert r["licence"] in pf.OPEN_LICENCES and r["attribution"]


def test_enabling_without_licence_stops(tmp_path, monkeypatch):
    p = tmp_path / "sources.tsv"
    text = pf.SOURCES.read_text(encoding="utf-8").splitlines()
    text = ["\t".join(r.split("\t")[:4] + ["1"] + r.split("\t")[5:]) if r.startswith("tbta\t") else r for r in text]
    p.write_text("\n".join(text) + "\n", encoding="utf-8")
    monkeypatch.setattr(pf, "SOURCES", p)
    with pytest.raises(AssertionError, match="tbta is enabled"):
        pf.sources()


@pytest.mark.skipif(not HAVE_DATA, reason="MACULA databases or layouts not built")
def test_cc_by_export_drops_share_alike(tmp_path):
    """The default export keeps the share-alike facts (unfoldingWord, MAM, UBS) and says CC BY-SA; the CC BY export drops them."""
    src = pf.sources()
    sa = {s for s, r in src.items() if r["share_alike"] == "1" and r["enabled"] == "1"}
    assert {"ult", "tn", "mam", "ubs"} <= sa
    for lic in ("by-sa", "by"):
        out = tmp_path / lic
        assert pf.main(["--books", "EXO", "LUK", "--out", str(out), "--licence", lic]) == 0
        build = json.loads((out / "build.json").read_text(encoding="utf-8"))
        known = {r["code"] for r in csv.DictReader((l for l in (out / "codes.tsv").open(encoding="utf-8") if not l.startswith("#")),
                                                   delimiter="\t")}
        for book in ("EXO", "LUK"):
            facts = [json.loads(l) for l in (out / f"{book}.jsonl").read_text(encoding="utf-8").splitlines()]
            shared = [f for f in facts if set(f["src"]) & sa]
            if lic == "by-sa":
                assert shared and all(f["lic"] == "CC BY-SA 4.0" for f in shared) and build["licence"] == "CC BY-SA 4.0"
            else:
                assert not shared and build["licence"] == "CC BY 4.0" and build["dropped_share_alike"][book] > 0
                assert all(f["lic"] != "CC BY-SA 4.0" for f in facts)
            for f in facts:
                assert f["kind"] == "frame" or f["value"] in known
                assert "tbta" not in f["src"]


@pytest.mark.skipif(not HAVE_DATA, reason="MACULA databases or layouts not built")
def test_places(tmp_path):
    out = tmp_path / "o"
    pf.main(["--books", "LUK", "--out", str(out)])
    facts = [json.loads(l) for l in (out / "LUK.jsonl").read_text(encoding="utf-8").splitlines()]
    magnificat = [f for f in facts if f["kind"] == "form" and f["value"] == "fm.ed.lines" and f["ref"] == "LUK 1:46-55"]
    assert magnificat and len(magnificat[0]["lines"]) == 16
    gabriel = next(f for f in facts if f["kind"] == "quote" and f["quote"] == "n42001013007")
    assert gabriel["speaker_name"] == "Γαβριήλ" and gabriel["level"] == 1
    assert any(f["kind"] == "voice" and f["value"] == "vc.narrator" and f["first"] == "42001001001" for f in facts)
    ult = [f for f in facts if f["value"] == "fm.tr.poetry" and "ult" in f["src"] and f["ref"] == "LUK 1:46-55"]
    assert ult and len(ult[0]["lines"]) >= 10
    assert sum(f["kind"] == "note" and f["value"] == "tn.figs-rquestion" for f in facts) > 50
    pf.main(["--books", "EXO", "--out", str(out)])
    exo = [json.loads(l) for l in (out / "EXO.jsonl").read_text(encoding="utf-8").splitlines()]
    song = [f for f in exo if f["value"] == "fm.ms.song"]
    assert len(song) == 1 and song[0]["ref"] == "EXO 15:1-19" and len(song[0]["lines"]) == 43
    assert song[0]["first"] == "020150010121"                  # אָשִׁירָה: the lead-in (Then Moses sang ...) is not a line


@pytest.mark.skipif(not HAVE_DATA, reason="MACULA databases or layouts not built")
def test_layout_columns_and_lines():
    """The CC BY columns the layout releases add, and the share-alike line cut."""
    from macula import build_clause_lines as cl
    from macula import segment_columns as sc
    psa = cl.layout_rows("hbo", "PSA")
    cols = sc.columns("PSA", psa)
    i = next(n for n, r in enumerate(psa) if r["chapter"] == 3)
    assert cols[i]["frame_speaker"] == "דָּוִד" and cols[i]["quotation"] is None
    assert all(c["force"] == [] or set(c["force"]) <= {"fc.imp", "fc.jus", "fc.coh", "fc.proh", "fc.q"} for c in cols)
    assert any("fc.imp" in c["force"] and c["quotation"] is None for c in cols)              # a psalm's plea: force outside speech
    assert any("fc.proh" in c["force"] for c in cols)                                           # אַל + jussive
    assert not any(v for c in cols for k, v in c.items() if k in ("printed", "printed_line"))   # Greek only
    luk = cl.layout_rows("grc", "LUK")
    lc = sc.columns("LUK", luk)
    assert sum(c["printed_line"] for c, r in zip(lc, luk) if r["chapter"] == 1 and 46 <= r["verse"] <= 55) >= 10
    for book, ch, v, code, word in (("MAT", 1, 20, "fc.proh", "φοβηθῇς"), ("JHN", 14, 31, "fc.hort", "ἄγωμεν")):
        rows = cl.layout_rows("grc", book)
        cs = sc.columns(book, rows)
        assert any(code in c["force"] and word in r["text"] for r, c in zip(rows, cs) if r["chapter"] == ch and r["verse"] == v)
    mat = cl.layout_rows("grc", "MAT")
    con, stat = sc.connectives(mat)
    i = next(n for n, r in enumerate(mat) if r["chapter"] == 2 and r["verse"] == 8 and con.get(n))
    owner = next(r for r in mat if r["clause"] == con[i][1])
    assert "εἶπεν" in owner["text"] and con[i][0] == [mat[i]["words"][0].lstrip("n")]     # καὶ πέμψας ... / εἶπεν
    assert stat["tree"] > 200 and stat["own"] > 0
    spans = [r for r in pf._tsv(pf.SPEAKER_SPANS) if r["word_start"]]
    rows, stat = cl.book_lines("hbo", "EXO", spans, {})
    assert stat["line starts from mam"] == 43                    # the Song of the Sea
    assert sum(len(r["words"]) for r in rows) == sum(len(r["words"]) for r in cl.layout_rows("hbo", "EXO"))   # a cut loses no word


@pytest.mark.skipif(not HAVE_DATA, reason="MACULA databases or layouts not built")
def test_shape_relation_and_question_extent(tmp_path):
    """One shape vocabulary for both layouts; the Greek relation by rule; a question does not run back into its inquit."""
    from macula import build_clause_lines as cl
    from macula import greek_relation as gr
    assert gr.from_rule("V-S-PP") == "V-S-A" and gr.from_rule("V2CL") == "V" and gr.from_rule("ADV-IO-V") == "A-V"
    mat = cl.layout_rows("grc", "MAT")
    rel = gr.relations(mat)
    assert sum(v[0] is None for v in rel.values()) / len(rel) < 0.02
    first = next(r for r in mat if r["chapter"] == 5 and r["verse"] == 3)          # Μακάριοι οἱ πτωχοί: the sermon's first clause
    assert rel[first["clause"]][0] == "speech"
    pf.main(["--books", "MAT", "--out", str(tmp_path)])
    facts = [json.loads(l) for l in (tmp_path / "MAT.jsonl").read_text(encoding="utf-8").splitlines()]
    q = {k for f in facts if f["kind"] == "force" and f["value"] == "fc.q" for k in f["at"]}
    assert "40020021006" in q and "40020021001" not in q          # MAT 20:21 ὁ δὲ εἶπεν αὐτῇ Τί θέλεις; — the frame is no question
