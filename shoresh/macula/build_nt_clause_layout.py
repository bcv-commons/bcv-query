"""Build the Greek New Testament clause layout (phase 1): the Nestle 1904 text one clause segment per line, chapter by chapter, from
MACULA Greek (CC BY 4.0) in trees-macula.db. No BHSA input, no rules yet.

A clause segment is a maximal run of words, inside one verse, that belongs to one clause.
- MACULA Greek wraps many clauses in a clause node that holds only the word introducing them: a conjunction (Conj-CL: καί, δέ),
  a subordinator (sub-CL: ὅτι, ἵνα), the article of an articular infinitive (DetCL), a particle (PtclCL), or nothing but the
  coordinated clauses (CLaCL). Such a wrapper (own words only conj, ptcl, det or the adverbs οὐ, μή, καί, and a clause below it) is not a level: its words go
  with the clause they introduce (the next word's clause, or the previous word's for a postpositive δέ, γάρ, οὖν), and the clause
  takes the wrapper's rules as `via` and its role as `role`. AdvpCL (an adverb such as ὁμοίως over a clause) and that-VP
  (ὅτι, which MACULA tags as an adverb there) are wrappers too.
- A coordination node (CLaCL, Conj3CL, aCLaCL, EitherOr4CL, ...) is not a level either: its clauses are siblings. MACULA puts a short
  member straight into the node (ἀλλὰ ὁ ἀνήρ, καὶ διώξωσιν), so the node's own words are a segment of their own at the members'
  depth; a coordinating conjunction goes with the member it opens.
- A clause of a vocative alone (Κύριε, / Ἀδελφοί,) keeps its line but is not a level either: the speech under it stays at its level.
- A clause interrupted by an embedded clause gives two segments; a clause that crosses a verse boundary gives one per verse
  (a MACULA Greek sentence can run over several verses).
Rule (an expression, not a place): a bare articular participle, the article and the participle alone (οἱ πενθοῦντες, τῷ Ἠγαπημένῳ,
with μή at most), is a noun phrase in the line, not a line: MACULA makes every participle a clause, so it would otherwise stand alone
(μακάριοι / οἱ πενθοῦντες). It joins the segment before it in the verse (or the one after, at the start of a verse), and the clause
it interrupted is joined up again; the record lists it in `inline`. A participle with words of its own keeps its line.
Rule: a preposition, a conjunction that is not postpositive, the adverb καί "also, even" or a negation (οὐ, μή) that ends a segment, where the next segment in the verse is a clause below it,
goes with that clause, which it governs or introduces (εἰς || τὸ φαγεῖν, καὶ || οἱ κατοικοῦντες). MACULA puts it in the higher clause.
Such a word (and the question particles οὐχί, μήτι) never ends a line inside a verse: it goes with the next line whatever the tree
says (ἵνα || ἀγαπῶμεν ἀλλήλους; Κύριε, οὐχὶ || σπέρμα: found by the Hebrew cross-check).
Rule: no line of function words alone (conjunctions, prepositions, articles, particles, οὐ, μή, καί) where the tree leaves one
(ἀλλὰ || τῇ κακίᾳ νηπιάζετε): such a segment goes with the next segment of the verse, which it introduces, or, when it opens with a
postpositive (δέ, γάρ, μέν, οὖν, τε: ἐγὼ || μὲν || γάρ), with the one before; a question (τί γάρ;) stays a line; the line takes that segment's clause. ἰδού and
ἴδε ("look", which MACULA makes a clause of its own, lemma ὁράω) count as such words here: καὶ ἰδοὺ goes with what it points to.
So does a relative pronoun, and an interrogative one that does not end its question, which MACULA puts in a clause below the one
it opens (ὧν || ἤρξατο ὁ Ἰησοῦς ποιεῖν, ὃν || δεῖ οὐρανὸν δέξασθαι, Τί || θέλει τοῦτο εἶναι).
Rule: a line breaks where a quotation starts or ends inside it (ὁ δὲ ἔφη || Ἄνδρες ἀδελφοὶ … ἀκούσατε, Acts 7:2); both parts keep
the clause, and the record of the second says `split_at_quotation`.
Rule: a line steps in one level at a time. Where the tree has a level with no line of its own (λέγοντες, then the speech two levels
in), the deeper lines move out to one level in from the line above, and lines of the same depth that follow stay with them; the
order of the levels is kept. `text_depth` is after this step; `depth` is the tree's.
Rule: a participle clause inside a noun phrase goes on the line of its noun when that line holds nothing but the noun phrase
(φωνὴ || βοῶντος ἐν τῇ ἐρήμῳ): a noun alone is not a line. A longer line keeps the participle on a line of its own (τοῖς ἁγίοις ||
τοῖς οὖσιν ἐν Ἐφέσῳ).
Phase 2, speech levels (rule speech_levels, as in the Hebrew layout): every quotation of Clear's speaker data
(resources/speaker_quotations, MACULA Nestle 1904 word ids, CC BY 4.0) is a level. MACULA's tree already puts a speech one level in
under its λέγων inside one sentence, but a speech that goes on in further sentences (Matt 5:3 after 5:2 "λέγων") starts each of them
at the margin. `text_depth`: a quotation's lines stand at least one level in from the line that introduces it (the line before its
first line), never further out while it lasts, and keep the tree's levels relative to the speech's lowest line in each sentence;
a quotation inside a quotation is one further in; one that directly follows another of the same depth (no introducing line) stands
where that one stands, one with no line before it at level 1 (or one in from the quotation around it). Lines outside every
quotation keep their tree depth. `quotation` is the innermost quotation (its first word id), `speaker` its speaker. Two
quotations of one speaker are one when what stands between them is short (at most 12 words) and has no finite verb (the speaker
data leaves Luke 1:74 out of Zechariah's song, and Mark 7:21's list of vices out of Jesus' words); the words between belong to it.
`depth` is the number of clause ancestors in the sentence, wrappers not counted. `parent` is the parent clause's id; a clause is named
by the key of its first word. Verse numbers are Nestle 1904's.

  python -m macula.build_nt_clause_layout [--books MAT,ROM] [--out macula/data/nt-clause-layout]

Writes clauses/<BOOK>/<BOOK>_<CCC>.jsonl, layout/<BOOK>/<BOOK>_<CCC>.txt and build.json.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

SHORESH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SHORESH))

import trees_macula  # noqa: E402

FORMAT_VERSION = 1
WRAPPER_CLASSES = {"conj", "ptcl", "det"}
WRAPPER_ADVERBS = {"οὐ", "μή", "καί"}                    # οὐ γάρ ... ἀλλά, καὶ γὰρ οὐκ: the negation or "also" of a coordination
ADVERB_WRAPPERS = {"AdvpCL", "that-VP"}               # ὁμοίως over a clause; ὅτι (tagged adv) over its clause
COORDINATION = re.compile(r"^(?:\d?a?CL.*CL|Conj\d+(?:CL|P)|EitherOr\d+CL|ClCl\d?|CLand.*)$")


class Tree:
    """The clause nodes of MACULA Greek, with the wrappers made transparent."""

    def __init__(self, con: sqlite3.Connection):
        self.node = {r["id"]: r for r in con.execute("SELECT id, parent, cls, rule, role, junction FROM nodes WHERE corpus='grc'")}
        own = collections.defaultdict(list)
        for cl, cls, lemma in con.execute("SELECT cl, class, lemma FROM words WHERE corpus='grc' AND cl IS NOT NULL"):
            own[cl].append((cls, lemma))
        has_clause_below = set()
        for nid, r in self.node.items():
            if r["cls"] == "cl":
                p = r["parent"]
                while p is not None:
                    has_clause_below.add(p)
                    p = self.node[p]["parent"]
        case = dict(con.execute("SELECT w.cl, MIN(CASE WHEN s.case_='vocative' OR w.class IN ('det','conj','ptcl','intj') OR w.lemma IN ('οὐ','μή','καί') "
                                "THEN 1 ELSE 0 END) * MAX(CASE WHEN s.case_='vocative' THEN 1 ELSE 0 END) FROM words w "
                                "LEFT JOIN sp.spine_words s ON s.key=w.key WHERE w.corpus='grc' AND w.cl IS NOT NULL GROUP BY w.cl").fetchall())
        self.vocative = {nid for nid, v in case.items() if v and nid in has_clause_below}
        self.coord = {nid for nid, r in self.node.items() if r["cls"] == "cl" and nid in has_clause_below
                      and COORDINATION.match(r["rule"] or "")} | self.vocative
        self.wrapper = {nid for nid, r in self.node.items() if r["cls"] == "cl" and nid in has_clause_below and nid not in self.coord
                        and all(c in WRAPPER_CLASSES or (c == "adv" and (r["rule"] in ADVERB_WRAPPERS or lm in WRAPPER_ADVERBS))
                                for c, lm in own[nid])}
        self.parent: dict[int, int | None] = {}
        self.via: dict[int, list[str]] = {}
        self.role: dict[int, str | None] = {}
        for nid, r in self.node.items():
            if r["cls"] != "cl" or nid in self.wrapper:
                continue
            via, role, p = [], r["role"], r["parent"]
            while p is not None and not (self.node[p]["cls"] == "cl" and p not in self.wrapper and p not in self.coord):
                if p in self.wrapper or p in self.coord:
                    via.append(self.node[p]["rule"] or "-")
                    role = role or self.node[p]["role"]
                p = self.node[p]["parent"]
            self.parent[nid], self.via[nid], self.role[nid] = p, via[::-1], role

    def real(self, cl: int | None) -> int | None:
        """The nearest clause that is not a wrapper, from a word's clause."""
        while cl is not None and (self.node[cl]["cls"] != "cl" or cl in self.wrapper):
            cl = self.node[cl]["parent"]
        return cl

    def under(self, cl: int | None, anc: int) -> bool:
        while cl is not None:
            if cl == anc:
                return True
            cl = self.node[cl]["parent"]
        return False

    def depth(self, cl: int) -> int:
        n = 0
        while self.parent.get(cl) is not None:
            cl = self.parent[cl]
            n += 1
        return n


def word_clauses(rows: list[sqlite3.Row], tree: Tree) -> list[int | None]:
    """The clause each word goes with: its own, or for a wrapper's word (and a coordinating conjunction) the clause it introduces.
    Right to left, so that a run of such words (εἰ μή, ὁμοίως δέ) moves together; a word with nothing of its node after it goes with
    the word before (a postpositive δέ, γάρ, οὖν after the clause's first word)."""
    def movable(r: sqlite3.Row) -> bool:
        return r["cl"] in tree.wrapper or (r["cl"] in tree.coord and r["class"] == "conj")
    res = [r["cl"] for r in rows]
    post = [r["lemma"] in POSTPOSITIVE and r["class"] == "conj" for r in rows]
    for i in range(len(rows) - 2, -1, -1):
        r = rows[i]
        j = i + 1
        while j + 1 < len(rows) and post[j] and rows[j + 1]["sent"] == r["sent"]:
            j += 1                                   # look past a postpositive: ὁμοίως δὲ || καὶ ὁ ἀνήρ
        if movable(r) and not post[i] and rows[j]["sent"] == r["sent"] and res[j] != r["cl"] and tree.under(res[j], r["cl"]):
            res[i] = res[j]
    for i in range(len(rows)):
        r = rows[i]
        if not movable(r) or res[i] != r["cl"]:
            continue
        prev_in = i > 0 and rows[i - 1]["sent"] == r["sent"] and res[i - 1] != r["cl"] and tree.under(res[i - 1], r["cl"])
        nxt_in = (i + 1 < len(rows) and rows[i + 1]["sent"] == r["sent"] and res[i + 1] != r["cl"]
                  and tree.under(res[i + 1], r["cl"]))
        nxt_any = i + 1 < len(rows) and rows[i + 1]["sent"] == r["sent"] and tree.under(res[i + 1], r["cl"])
        if prev_in and (post[i] or not nxt_any):
            res[i] = res[i - 1]                  # a postpositive stays after the clause's first word (Προσέχετε δὲ)
        elif nxt_in:
            res[i] = res[i + 1]
    return [tree.real(c) for c in res]


def chapter_segments(rows: list[sqlite3.Row], tree: Tree) -> list[dict]:
    cids = word_clauses(rows, tree)
    segs: list[dict] = []
    for r, cid in zip(rows, cids):
        if segs and segs[-1]["verse"] == r["verse"] and segs[-1]["_cl"] == cid:
            segs[-1]["_rows"].append(r)
        else:
            segs.append({"verse": r["verse"], "_cl": cid, "_rows": [r], "_inline": []})
    for n, s in enumerate(segs, 1):
        s["seg"] = n
    return segs


NEGATIONS = {"μή", "οὐ"}
HAS_CHILD: set[int] = set()                                # clauses with a clause below them (filled in main)


def bare_participle(seg: dict, whole: dict[int, int], mood: dict[str, str]) -> bool:
    """Article and participle alone, the whole clause, and no clause below it (οἱ λέγοντες ὅτι ... keeps its line)."""
    rows = seg["_rows"]
    verbs = [r for r in rows if r["class"] == "verb"]
    return (seg["_cl"] is not None and len(rows) == whole.get(seg["_cl"]) and seg["_cl"] not in HAS_CHILD and rows[0]["class"] == "det" and len(verbs) == 1
            and mood.get(verbs[0]["key"]) == "participle"
            and all(r["class"] in ("det", "verb") or r["lemma"] in NEGATIONS for r in rows))


def inline_participles(segs: list[dict], whole: dict[int, int], mood: dict[str, str]) -> list[dict]:
    out: list[dict] = []
    i = 0
    while i < len(segs):
        s = segs[i]
        if bare_participle(s, whole, mood) and out and out[-1]["verse"] == s["verse"]:
            host = out[-1]
            host["_rows"] += s["_rows"]
            host["_inline"].append((s["_cl"], s["_rows"][0]["key"]))
            nxt = segs[i + 1] if i + 1 < len(segs) else None
            if nxt and nxt["verse"] == host["verse"] and nxt["_cl"] == host["_cl"]:
                host["_rows"] += nxt["_rows"]
                host["_inline"] += nxt["_inline"]
                i += 1
        elif (bare_participle(s, whole, mood) and i + 1 < len(segs) and segs[i + 1]["verse"] == s["verse"]
              and (not out or out[-1]["verse"] != s["verse"])):
            nxt = segs[i + 1]
            out.append({**nxt, "_rows": s["_rows"] + nxt["_rows"], "_inline": [(s["_cl"], s["_rows"][0]["key"])] + nxt["_inline"]})
            i += 1
        else:
            out.append(s)
        i += 1
    for n, s in enumerate(out, 1):
        s["seg"] = n
    return out


def noun_line_participles(segs: list[dict], tree: Tree, mood: dict[str, str]) -> list[dict]:
    """Rule: a participle clause in a noun phrase joins a line that is only that noun phrase."""
    def np_of(cid: int) -> int | None:
        p = tree.node[cid]["parent"]
        while p is not None and (tree.node[p]["cls"] != "cl" or p in tree.wrapper):
            if tree.node[p]["cls"] == "np":
                return p
            p = tree.node[p]["parent"]
        return None
    out: list[dict] = []
    i = 0
    while i < len(segs):
        s_ = segs[i]
        cid = s_["_cl"]
        verbs = [r for r in s_["_rows"] if r["class"] == "verb" and r["cl"] == cid]
        np_ = np_of(cid) if cid is not None and len(verbs) == 1 and mood.get(verbs[0]["key"]) == "participle" else None
        host = out[-1] if out else None
        if (np_ is not None and host and host["verse"] == s_["verse"] and host["_cl"] is not None and tree.under(cid, host["_cl"])
                and all(tree.under(r["parent"], np_) for r in host["_rows"] if not _function_word(r))):
            host["_rows"] += s_["_rows"]
            host["_inline"].append((cid, s_["_rows"][0]["key"]))
            nxt = segs[i + 1] if i + 1 < len(segs) else None
            if nxt and nxt["verse"] == host["verse"] and nxt["_cl"] == host["_cl"]:
                host["_rows"] += nxt["_rows"]
                host["_inline"] += nxt["_inline"]
                i += 1
        else:
            out.append(s_)
        i += 1
    return out


QUESTION_PARTICLES = {"οὐχί", "μήτι"}


def carried(r: sqlite3.Row) -> bool:
    return (r["class"] == "prep" or (r["class"] == "adv" and (r["lemma"] in WRAPPER_ADVERBS or r["lemma"] in ("ὅτι", "οὐχί")))
            or (r["class"] == "ptcl" and r["lemma"] in QUESTION_PARTICLES)
            or (r["class"] == "conj" and r["lemma"] not in POSTPOSITIVE))


def carry_forward(segs: list[dict], tree: Tree) -> list[dict]:
    for a, b in zip(segs, segs[1:]):
        while (a["_rows"] and a["verse"] == b["verse"] and b["_cl"] is not None and a["_cl"] is not None and b["_cl"] != a["_cl"]
               and tree.under(b["_cl"], a["_cl"])
               and carried(a["_rows"][-1])):
            b["_rows"].insert(0, a["_rows"].pop())
    # and wherever the next line is: such a word never ends a line inside a verse (ἵνα || ἀγαπῶμεν, Κύριε, οὐχὶ || σπέρμα)
    for a, b in zip(segs, segs[1:]):
        while len(a["_rows"]) > 1 and a["verse"] == b["verse"] and carried(a["_rows"][-1]):
            b["_rows"].insert(0, a["_rows"].pop())
    out = no_function_lines([s_ for s_ in segs if s_["_rows"]])
    for n, s_ in enumerate(out, 1):
        s_["seg"] = n
    return out


POSTPOSITIVE = {"δέ", "γάρ", "μέν", "οὖν", "τε"}


LOOK = {"ἰδού", "ἴδε"}


def _plain(w: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", w.lower()) if not unicodedata.combining(c))


def _function_word(r: sqlite3.Row) -> bool:
    if r["class"] == "pron" and (r["wtype"] == "relative" or (r["wtype"] == "interrogative" and ";" not in (r["after"] or ""))):
        return True
    if r["lemma"] == "ὁράω" and _plain(r["surface"]) in {_plain(x) for x in LOOK}:
        return True
    return r["class"] in ("conj", "prep", "det", "ptcl") or (r["class"] == "adv" and r["lemma"] in WRAPPER_ADVERBS)


def _question(s_: dict) -> bool:
    return ";" in (s_["_rows"][-1]["after"] or "")                    # τί γάρ; / Τί οὖν; is a line of its own


def no_function_lines(segs: list[dict]) -> list[dict]:
    segs = list(segs)
    i = len(segs) - 1
    while i >= 0:
        s_ = segs[i]
        if all(_function_word(r) for r in s_["_rows"]) and not _question(s_):
            prev_ok = i > 0 and segs[i - 1]["verse"] == s_["verse"]
            next_ok = i + 1 < len(segs) and segs[i + 1]["verse"] == s_["verse"]
            if prev_ok and (s_["_rows"][0]["lemma"] in POSTPOSITIVE or not next_ok):
                segs[i - 1] = {**segs[i - 1], "_rows": segs[i - 1]["_rows"] + s_["_rows"], "_inline": segs[i - 1]["_inline"] + s_["_inline"]}
                del segs[i]
            elif next_ok:
                segs[i + 1] = {**segs[i + 1], "_rows": s_["_rows"] + segs[i + 1]["_rows"], "_inline": s_["_inline"] + segs[i + 1]["_inline"]}
                del segs[i]
        i -= 1
    # a postpositive merged backwards can leave the line before it of function words only: one more pass
    if any(all(_function_word(r) for r in s_["_rows"]) and not _question(s_) and j + 1 < len(segs) and segs[j + 1]["verse"] == s_["verse"]
           and s_["_rows"][0]["lemma"] not in POSTPOSITIVE for j, s_ in enumerate(segs)):
        return no_function_lines(segs)
    return segs


SPEAKERS = SHORESH.parent / "resources" / "speaker_quotations" / "speaker_quotations.tsv"


def load_quotations() -> dict[str, list[dict]]:
    """NT quotations per book code number (the first two digits of a word id), outermost first where they share a start."""
    import csv
    with open(SPEAKERS, encoding="utf-8") as fh:
        rows = list(csv.DictReader((line for line in fh if not line.startswith("#")), delimiter="\t"))
    out: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        if r["word_start"].startswith("n"):
            q = {"id": r["word_start"][1:], "start": r["word_start"][1:], "end": r["word_end"][1:], "speaker": r["speaker"]}
            out[q["start"][:2]].append(q)
    for qs in out.values():
        qs.sort(key=lambda q: (q["start"], -int(q["end"])))
    return out


SAYING = {"λέγω", "εἶπον", "φημί", "ἀποκρίνομαι", "λαλέω", "κράζω", "γράφω", "ἐρωτάω", "βοάω", "φωνέω"}


FINITE = {"indicative", "subjunctive", "optative", "imperative"}


def close_gaps(quotes: dict[str, list[dict]], keys: list[str], lemma: dict[str, str], mood: dict[str, str]) -> int:
    import bisect
    joined = 0
    for book, qs in quotes.items():
        i = 0
        while i + 1 < len(qs):
            a, b = qs[i], qs[i + 1]
            gap = keys[bisect.bisect_right(keys, a["end"]):bisect.bisect_left(keys, b["start"])]
            if (a["speaker"] == b["speaker"] and b["start"] > a["end"] and len(gap) <= 12
                    and not any(lemma[k] in SAYING or mood.get(k) in FINITE for k in gap)):
                a["end"] = max(a["end"], b["end"])
                del qs[i + 1]
                joined += 1
            else:
                i += 1
    return joined


def chain_of(key: str, quotes: dict[str, list[dict]]) -> tuple:
    """The quotations a word stands in, outermost first."""
    return tuple(q["id"] for q in quotes.get(key[:2], []) if q["start"] <= key <= q["end"])


def speech_levels(segs: list[dict], quotes: dict[str, list[dict]], tree_depth: list[int]) -> list[int]:
    """Rule speech_levels over one book's segments, in text order. Returns text_depth per segment."""
    chains = []
    for s_ in segs:
        votes = collections.Counter(chain_of(r["key"], quotes) for r in s_["_rows"])
        chains.append(votes.most_common(1)[0][0])
    td = list(tree_depth)
    base: dict[str, int] = {}
    low: dict[tuple, int] = {}                      # (quotation, sentence) -> lowest tree depth of its lines there
    for s_, ch, d in zip(segs, chains, tree_depth):
        if ch:
            k = (ch[-1], s_["_rows"][0]["sent"])
            low[k] = min(low.get(k, d), d)
    for i, (s_, ch) in enumerate(zip(segs, chains)):
        if not ch:
            continue
        for depth_in, q in enumerate(ch):
            if q in base:
                continue
            prev = i - 1
            outer = ch[:depth_in]
            if prev >= 0 and chains[prev][:depth_in + 1] == outer + (q,):
                continue
            if prev < 0:
                base[q] = (base[outer[-1]] + 1) if outer else 1
            elif len(chains[prev]) > depth_in and chains[prev][:depth_in] == outer and chains[prev][depth_in] != q:
                base[q] = base.get(chains[prev][depth_in], td[prev])           # another speaker's words carried on, no inquit
            else:
                base[q] = td[prev] + 1
                if outer:
                    base[q] = max(base[q], base[outer[-1]] + 1)
        q = ch[-1]
        td[i] = base[q] + tree_depth[i] - low[(q, s_["_rows"][0]["sent"])]
    return td, chains


def split_at_quotations(segs: list[dict], quotes: dict[str, list[dict]], tree: Tree) -> list[dict]:
    """Rule: a line breaks where a quotation of the speaker data starts or ends inside it (MACULA has ὁ δὲ ἔφη Ἄνδρες ἀδελφοὶ …
    ἀκούσατε as one clause), unless a part would be function words alone. A break inside a phrase moves back to the phrase's
    start (the speaker data starts Stephen's words at ἀδελφοί, inside Ἄνδρες ἀδελφοί)."""
    def phrase_top(r: sqlite3.Row) -> int | None:
        top, p_ = None, r["parent"]
        while p_ is not None and tree.node[p_]["cls"] != "cl":
            top, p_ = p_, tree.node[p_]["parent"]
        return top
    out = []
    for s_ in segs:
        parts = [[s_["_rows"][0]]]
        for a, b in zip(s_["_rows"], s_["_rows"][1:]):
            if chain_of(a["key"], quotes) != chain_of(b["key"], quotes):
                top = phrase_top(b)
                moved = []
                while top is not None and len(parts[-1]) > 1 and tree.under(parts[-1][-1]["parent"], top):
                    moved.insert(0, parts[-1].pop())
                parts.append(moved)
            parts[-1].append(b)
        merged = [parts[0]]
        for part in parts[1:]:
            if all(_function_word(r) for r in part) or all(_function_word(r) for r in merged[-1]):
                merged[-1] += part
            else:
                merged.append(part)
        for k, part in enumerate(merged):
            out.append({**s_, "_rows": part, "_inline": s_["_inline"] if k == 0 else [], "_split": k > 0})
    for n, s_ in enumerate(out, 1):
        s_["seg"] = n
    return out


def one_step(levels: list[int]) -> list[int]:
    """Rule: a line steps in one level at a time, keeping the order of the levels."""
    stack: list[tuple[int, int]] = []                     # (level before, level shown)
    out = []
    for d in levels:
        while stack and stack[-1][0] > d:
            stack.pop()
        if not stack:
            shown = d
        elif stack[-1][0] == d:
            shown = stack[-1][1]
        else:
            shown = stack[-1][1] + 1
        if not stack or stack[-1][0] != d:
            stack.append((d, shown))
        out.append(shown)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--books", help="comma-separated USFM codes (default: all NT books)")
    ap.add_argument("--out", default=str(SHORESH / "macula" / "data" / "nt-clause-layout"))
    a = ap.parse_args()
    out = Path(a.out)
    tp = trees_macula.trees_path()
    con = trees_macula._con()                              # trees-macula.db with the lexeme spine (for the participles' mood)
    tree = Tree(con)
    HAS_CHILD.update(p_ for p_ in tree.parent.values() if p_ is not None)
    mood = dict(con.execute("SELECT w.key, s.mood FROM words w JOIN sp.spine_words s ON s.key=w.key WHERE w.corpus='grc' "
                            "AND w.class='verb'").fetchall())
    books = a.books.upper().split(",") if a.books else [r[0] for r in con.execute(
        "SELECT book FROM words WHERE corpus='grc' GROUP BY book ORDER BY MIN(seq)")]
    quotes = load_quotations()
    lemma = dict(con.execute("SELECT key, lemma FROM words WHERE corpus='grc'").fetchall())
    joined = close_gaps(quotes, sorted(lemma), lemma, mood)
    chapters: list[tuple[str, int, list[dict]]] = []
    for book in books:
        for (ch,) in con.execute("SELECT DISTINCT chapter FROM words WHERE corpus='grc' AND book=? ORDER BY chapter", (book,)).fetchall():
            rows = con.execute("SELECT * FROM words w WHERE corpus='grc' AND book=? AND chapter=? ORDER BY " + trees_macula.TEXT_ORDER,
                               (book, ch)).fetchall()
            segs = chapter_segments(rows, tree)
            whole = collections.Counter(s_["_cl"] for s_ in segs for _ in s_["_rows"])
            segs = carry_forward(noun_line_participles(inline_participles(segs, whole, mood), tree, mood), tree)
            chapters.append((book, ch, split_at_quotations(segs, quotes, tree)))
    key_of: dict[int, str] = {}                            # stable clause ids: the key of the clause's first word
    for _, _, segs in chapters:
        for s in segs:
            if s["_cl"] is not None:
                key_of.setdefault(s["_cl"], s["_rows"][0]["key"])
    speaker_of = {q["id"]: q["speaker"] for qs in quotes.values() for q in qs}
    by_book: dict[str, list[dict]] = collections.defaultdict(list)
    for book, ch, segs in chapters:
        by_book[book] += segs
    for book, segs in by_book.items():
        tds, chains = speech_levels(segs, quotes, [tree.depth(s_["_cl"]) if s_["_cl"] is not None else 0 for s_ in segs])
        tds = one_step(tds)
        for s_, t, c in zip(segs, tds, chains):
            s_["_td"], s_["_q"] = t, (c[-1] if c else None)
    stats = collections.Counter()
    depths = collections.Counter()
    for book, ch, segs in chapters:
        recs, lines = [], []
        for s in segs:
            cid, rows = s["_cl"], s["_rows"]
            own = [r for r in rows if r["cl"] == cid]
            depth = tree.depth(cid) if cid is not None else 0
            text = " ".join(r["surface"] + (r["after"] or "").strip() for r in rows)
            rec = {"verse": s["verse"], "seg": s["seg"], "clause": key_of.get(cid), "parent": key_of.get(tree.parent.get(cid)),
                   "depth": depth, "text_depth": s["_td"], "quotation": s["_q"], "speaker": speaker_of.get(s["_q"]), "kind": trees_macula._clause_kind(own or rows) if cid is not None else None,
                   "rule": tree.node[cid]["rule"] if cid is not None else None, "role": tree.role.get(cid),
                   "via": tree.via.get(cid, []), "junction": tree.node[cid]["junction"] if cid is not None else None,
                   "sentence": rows[0]["sent"], "first": rows[0]["key"], "last": rows[-1]["key"],
                   "inline": [k for _, k in s["_inline"]], "split_at_quotation": s.get("_split", False), "words": [r["key"] for r in rows], "text": text}
            recs.append(rec)
            lines.append(f"{ch}:{s['verse']}\t{'    ' * s['_td']}{text}")
            stats["segments"] += 1
            stats["words"] += len(rows)
            stats["no_clause"] += cid is None
            stats["split_at_quotation"] += s.get("_split", False)
            stats["inline_participles"] += len(s["_inline"])
            depths[s["_td"]] += 1
            stats["in_quotation"] += s["_q"] is not None
        d = out / "clauses" / book
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{book}_{ch:03d}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
        d = out / "layout" / book
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{book}_{ch:03d}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    meta = dict(con.execute("SELECT * FROM meta").fetchall())
    build = {"format_version": FORMAT_VERSION, "built": datetime.date.today().isoformat(), "source": meta.get("source_grc"),
             "trees_db_built": meta.get("built"), "trees_db_sha256": hashlib.sha256(Path(tp).read_bytes()).hexdigest(),
             "books": len(books), "chapters": len(chapters), "clauses": len(key_of), "wrappers": len(tree.wrapper),
             "coordinations": len(tree.coord), **stats,
             "text_depth": dict(sorted(depths.items())), "quotations": sum(len(q) for q in quotes.values()),
             "quotations_joined_over_a_gap": joined}
    (out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in build.items() if k != "trees_db_sha256"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
