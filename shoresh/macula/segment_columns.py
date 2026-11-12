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
  force            codes of what the clause does by its grammar, in every segment (in speech or not): fc.imp imperative, fc.jus
                   jussive, fc.coh cohortative, fc.proh prohibition, fc.hort exhortation (Greek), fc.q question, fc.voc vocative (Greek);
                   see build_passage_facts.Builder.force_codes
  you              the number of the segment's second-person forms inside speech: ad.sg, ad.pl, ad.both
  para_end         Hebrew: sc.pe / sc.sa where a Leningrad Codex paragraph (petuchah / setumah) ends with this segment's last word
  printed          Greek: fm.ed.lines / fm.ed.qlines / fm.ed.block where Nestle 1904 prints the segment set apart (poetic lines, lines
                   quoted from the Scriptures, a hymn block)
  printed_line     Greek: true where a printed line of Nestle 1904 starts at the segment's first word
  connective, connective_of
                   Greek: where a dependent clause stands before its parent and opens with the sentence's connective (καί, ἀλλά ...
                   first; δέ, γάρ, οὖν, μέν, τέ among the first four words) and MACULA's tree hangs that connective above the
                   clause: its word key(s), and the clause it belongs to (the highest layout clause whose tree node covers it).
                   Proposed and first listed by make-tanakh-research (2026-11-12); read from the MACULA Greek tree.
  shape            both: the roles of the clause's constituents in one vocabulary for both layouts (S O V P A N I + ~), from the
                   rule string or the tree (macula.greek_relation.shapes)
  relation, relation_basis
                   Greek: how the clause relates to what it hangs on, in the Hebrew layout's vocabulary, by rule; basis names the rule
                   (macula.greek_relation.relations; rules by make-tanakh-research)
"""
from __future__ import annotations

import collections
import functools
import sqlite3

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


FIRST = {"καί", "ἀλλά", "ἤ", "οὐδέ", "μηδέ", "οὔτε", "μήτε", "πλήν", "διό", "ἄρα"}
POST = {"δέ", "γάρ", "οὖν", "μέν", "τέ"}


@functools.lru_cache(maxsize=1)
def _greek_tree():
    db = sqlite3.connect(f"file:{pf.TREES}?mode=ro", uri=True)
    words = {k: (cl, lemma) for k, cl, lemma in db.execute("SELECT key, cl, lemma FROM words WHERE corpus='grc' AND inserted=0")}
    nodes = dict(db.execute("SELECT id, parent FROM nodes WHERE corpus='grc'"))
    return words, nodes


def connectives(rows: list[dict]) -> tuple[dict[int, tuple[list[str], str]], collections.Counter]:
    """row index -> (connective keys, owner clause) for the Greek rows; and counts (`own`: the connective is the clause's own)."""
    W, N = _greek_tree()
    first, words = {}, collections.defaultdict(list)
    for i, r in enumerate(rows):
        if r.get("clause"):
            first.setdefault(r["clause"], i)
            words[r["clause"]] += [str(k).lstrip("n") for k in r["words"]]

    @functools.lru_cache(maxsize=None)
    def node(c):
        n = collections.Counter(W[k][0] for k in words[c] if k in W)
        return n.most_common(1)[0][0] if n else None

    def above(x, y):                                       # x is a proper ancestor of y
        y, n = N.get(y), 0
        while y is not None and n < 60:
            if x == y:
                return True
            y, n = N.get(y), n + 1
        return False

    def covers(wn, c):
        return node(c) is not None and (wn == node(c) or above(wn, node(c)))

    out, stat = {}, collections.Counter()
    for i, r in enumerate(rows):
        c, p = r.get("clause"), r.get("parent")
        if not c or not p or p not in first or first[c] != i or first[p] <= i:
            continue
        ks = [str(k).lstrip("n") for k in r["words"]]
        hit = next(((j, k) for j, k in enumerate(ks[:4]) if k in W and ((j == 0 and W[k][1] in FIRST) or W[k][1] in POST)), None)
        if not hit:
            continue
        stat["opening"] += 1
        k, wn, cn = hit[1], W[hit[1]][0], node(c)
        if wn is None or cn is None or not above(wn, cn):
            stat["own" if wn == cn else "undecided"] += 1
            continue
        q = p
        while q in first and covers(wn, q) and rows[first[q]].get("parent") in first:
            q = rows[first[q]]["parent"]
        out[i] = ([k], q if covers(wn, q) else p)
        stat["tree"] += 1
    return out, stat


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
    from macula import greek_relation
    shape = greek_relation.shapes("hbo" if hebrew else "grc", rows)
    rel = {} if hebrew else greek_relation.relations(rows)
    conn = {} if hebrew else connectives(rows)[0]
    out = []
    for i, r in enumerate(rows):
        c = {}
        if hebrew:
            c.update(spk.get((r["chapter"], r["seg"])) or {k: ([] if k in ("speaker_ref", "speaker_name_ref", "speaker_members") else
                                                               0 if k == "quote_level" else None) for k in HEB_SPEAKER})
        c["shape"] = shape.get(r.get("clause_key") if hebrew else r.get("clause")) or None
        if not hebrew:
            x = rel.get(r.get("clause"), (None, None, None))
            c.update(relation=x[0], relation_basis=x[1])
        n = you.get(i, set())
        c.update(force=force.get(i, []), you="ad.both" if len(n) == 2 else "ad.sg" if n == {"singular"} else "ad.pl" if n else None)
        if hebrew:
            c["para_end"] = para.get(i)
        else:
            con = conn.get(i)
            c.update(printed=printed.get(i), printed_line=i in line, connective=con[0] if con else [], connective_of=con[1] if con else None)
        out.append(c)
    return out
