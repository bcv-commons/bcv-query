"""Columns the clause layout releases add to each segment, from CC BY 4.0 (and public-domain) sources only.

    from macula import segment_columns as sc
    cols = sc.columns("EXO", rows)    # rows: the layout's segments of the book ({"chapter", "seg", "words", ...}); -> one dict per row

Hebrew, from the Hebrew Bible Speaker Layer (data/speaker-layer, CC BY 4.0), as the Greek NT layout already has them:
  quotation        the innermost quotation the segment stands in (the layer's id), or null in narrative
  quote_level      1 a speech in the narrative or text, 2 a speech inside it, ...; 0 in narrative
  speaker, speaker_ref, speaker_basis, speaker_id, speaker_name, speaker_name_ref, speaker_members
                   who speaks, as in the layer (Hebrew words of the text; keys; ids). No English label (`alt_eng` is not carried)
  frame_speaker    for narrative-level text that is one speaker's from its start (a psalm's psalmist, a prophet): that speaker
Both, from the passage facts of non-share-alike sources (macula.build_passage_facts; codes as in its codes.tsv):
  force            codes of what the clause does by its grammar, inside speech: fc.imp imperative, fc.jus jussive, fc.coh cohortative,
                   fc.q question (Hebrew interrogative word; Greek question mark), fc.voc vocative (Greek)
  you              the number of the segment's second-person forms inside speech: ad.sg, ad.pl, ad.both
  para_end         Hebrew: sc.pe / sc.sa where a Leningrad Codex paragraph (petuchah / setumah) ends with this segment's last word
  printed          Greek: fm.ed.lines / fm.ed.qlines / fm.ed.block where Nestle 1904 prints the segment set apart (poetic lines, lines
                   quoted from the Scriptures, a hymn block)
  printed_line     Greek: true where a printed line of Nestle 1904 starts at the segment's first word
"""
from __future__ import annotations

import collections

from macula import build_passage_facts as pf

HEB_SPEAKER = ["quotation", "quote_level", "speaker", "speaker_ref", "speaker_basis", "speaker_id", "speaker_name", "speaker_name_ref",
               "speaker_members", "frame_speaker"]
FACT_COLUMNS = ["force", "you", "para_end", "printed", "printed_line"]


def _hebrew_speakers(book: str) -> dict[tuple[int, int], dict]:
    seg = {(int(r["chapter"]), int(r["seg"])): r for r in pf._tsv(pf.LAYER / "segments" / f"{book}.tsv")}
    quotes = {r["id"]: r for r in pf._tsv(pf.LAYER / "quotations.tsv")}
    out = {}
    for k, r in seg.items():
        q = quotes.get(r["quotation"]) if r["quotation"] else None
        split = lambda s: s.split() if s else []
        out[k] = {"quotation": r["quotation"] or None, "quote_level": int(r["level"] or 0),
                  "speaker": (q["speaker"] or None) if q else None, "speaker_ref": split(q["speaker_ref"]) if q else [],
                  "speaker_basis": (q["speaker_basis"] or None) if q else None, "speaker_id": (q["speaker_id"] or None) if q else None,
                  "speaker_name": (q["speaker_name"] or None) if q else None,
                  "speaker_name_ref": split(q["speaker_name_ref"]) if q else [],
                  "speaker_members": split(q["speaker_members"]) if q else [], "frame_speaker": r["frame"] or None}
    return out


def columns(book: str, rows: list[dict], spans: list[dict] | None = None) -> list[dict]:
    """The added columns for each of the book's layout rows (same order)."""
    if spans is None:
        spans = [r for r in pf._tsv(pf.SPEAKER_SPANS) if r["word_start"]]
    src = pf.sources()
    b = pf.Builder(book, pf.Codes())
    facts = [f for f in b.build(spans) if all(src[s]["share_alike"] == "0" for s in f["src"])]
    hebrew = b.bk.hebrew
    row_of = {}
    for i, r in enumerate(rows):
        for k in r["words"]:
            row_of.setdefault(k, i)
    first_of = {r["words"][0]: i for i, r in enumerate(rows) if r["words"]}
    last_of = {r["words"][-1]: i for i, r in enumerate(rows) if r["words"]}
    force: dict[int, list] = collections.defaultdict(list)
    you: dict[int, set] = collections.defaultdict(set)
    para, printed, line = {}, {}, set()
    for f in facts:
        if f["kind"] == "force":
            i = row_of.get(f["at"][0])
            if i is not None and f["value"] not in force[i]:
                force[i].append(f["value"])
        elif f["kind"] == "addressee" and f["value"] != "ad.named":
            for k in f.get("at", []):
                i = row_of.get(k)
                if i is not None:
                    you[i].add(b.bk.w[k][3])
        elif f["kind"] == "section" and f["src"] == ["oshb"]:
            i = last_of.get(f["after"])
            if i is None:                                   # the mark ends a verse whose last word is not a segment's last word
                i = row_of.get(f["after"])
            if i is not None:
                para[i] = f["value"]
        elif f["kind"] == "form" and f["src"] == ["nestle1904"]:
            lo, hi = b.bk.pos[f["first"]], b.bk.pos[f["last"]]
            for i, r in enumerate(rows):
                if r["words"] and lo <= b.bk.pos.get(r["words"][0], -1) <= hi:
                    printed[i] = f["value"]
            for a, _ in f.get("lines") or []:
                if a in first_of:
                    line.add(first_of[a])
    spk = _hebrew_speakers(book) if hebrew else {}
    out = []
    for i, r in enumerate(rows):
        c = {}
        if hebrew:
            c.update(spk.get((r["chapter"], r["seg"])) or {k: ([] if k in ("speaker_ref", "speaker_name_ref", "speaker_members") else
                                                               0 if k == "quote_level" else None) for k in HEB_SPEAKER})
        n = you.get(i, set())
        c.update(force=force.get(i, []), you="ad.both" if len(n) == 2 else "ad.sg" if n == {"singular"} else "ad.pl" if n else None)
        if hebrew:
            c["para_end"] = para.get(i)
        else:
            c.update(printed=printed.get(i), printed_line=i in line)
        out.append(c)
    return out
