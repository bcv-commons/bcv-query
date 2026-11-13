"""Clause columns as source facts: make-tanakh-research's per-clause discourse and argument columns (its lab/bridge/clause_layers.py,
published as bcv-commons/clause-columns), rebuilt here from our own free sources, keyed by our layouts' clause keys, both testaments.

    python -m macula.build_clause_columns [--out DIR] [--check DIR_OF_clause-columns_SNAPSHOT]

Writes <out>/hebrew.parquet, <out>/greek-nt.parquet, <out>/build.json (default out: macula/data/clause-columns, git-ignored) and, with
--check, the contract check against research's published table: <out>/checks.md, <out>/contract.tsv, <out>/examples.tsv.

Inputs (all local; no BHSA, no TBTA, no English as evidence):
  - our clause layouts: data/clause-layout/clauses (Hebrew, clause_key), data/nt-clause-layout/clauses (Greek, `first`);
  - the Hebrew speaker layer (data/speaker-layer: segments/<BOOK>.tsv, quotations.tsv; CC BY 4.0);
  - MACULA Hebrew words (lowfat-hbo.db: class, type, morph, strong, Septuagint form `greek`), the spine's phrase_role and the Greek
    morphology / own role (lexeme-spine-macula.db), MACULA verb frames and references (macula-spine.db: frames, refs), MACULA Greek
    trees (trees-macula.db); MACULA Hebrew's own `frame` attribute (.lowfat-src/WLC/lowfat XML: it keeps a label with no word, "A0:;",
    which macula-spine.db's frames table drops); all CC BY 4.0;
  - GLAUx Septuagint parses (lxx/data/lxx-glaux.db, CC BY-SA 4.0): only lxx_tense / lxx_mood read it, so those two columns are CC BY-SA.

Columns (research's names and value names; the definition is research's unless "ours" says otherwise):
  clause_key     Hebrew: the layout's clause_key (one row per key; a clause split into several segments takes the union of its words,
                 in text order: ours; research reads such a clause from one segment, see clause_columns_contract);
                 Greek: the segment's first word (the layout's `first`)
  ref            BOOK c:v.seg of the clause's first segment
  verb, conj, voice, neg   the main verb (first finite verb, else participle / infinitive), its form (Hebrew qatal | wayyiqtol | ...;
                 Greek <tense>_<mood>), voice, and the clause's negator class (research's clause_features.py rules)
  speech         Hebrew: the speaker layer's quotation level (0 narration); Greek: 1 inside a quotation (the layout's `quotation`)
  speaker        Hebrew: the layer's speaker (MACULA lemma[s] of the naming words); Greek: the layout's speaker_id
  speaker_id     (ours, Hebrew) the layer's character id of the quotation's speaker, the id the Greek layout also uses
  frame          (Hebrew) the speaker of a text that is speech from its first line, from the layer
  genre          the book's genre, research's fixed table (one code per book)
  line           main | background | setting | speech | non-narrative: speech when the clause is in a quotation (or a framed text),
                 setting when verbless, non-narrative outside the narrative books, else Hebrew main = wayyiqtol, Greek main = aorist or
                 present indicative at layout depth 0; background otherwise
  actor, undergoer   overt | implicit | none. Hebrew: the verb's frame A0 / A1 inside the clause (overt), named elsewhere (implicit);
                 actor also implicit when the verb has a subject referent. Greek (ours): research reads the word's role only (actor
                 overt when a word has role s, implicit for a finite verb; undergoer overt for o / o2, never implicit); here the role is
                 the nearest role above the word within its clause in MACULA's tree (as research's own subj_form / front use), and the
                 Greek frames add what the Hebrew definition has: an A0 / A1 word inside the clause is overt, outside it implicit; Greek
                 undergoer `clause` when every A1 of the verb lies under an object node that is a clause (packet 25: TBTA carries
                 such a patient as an embedded proposition, not a patient NP); undergoer `complement` (both testaments) when a word in the clause
                 has role o / o2 but the frame lists no A1 inside the clause (complements, double and cognate objects; against TBTA's
                 patient NP its precision is 0.339, near `none`'s 0.288, packet 25 section 5)
  undergoer_basis (both) what made the undergoer present: clause | passive_subject | np_a1 | single_word_o | a1_other |
                 role_o_without_a1 | role_o_et (Hebrew: an object in the tree with no A1 in the frame, and the object marker et
                 in the clause, so overt; packet 25 section 7); empty for implicit and none. Hebrew `complement` is then an object
                 with no frame A1 and no et: complements, indefinite objects, and objects the tentative Hebrew frames miss
  args           the frame's argument labels in order (A0+A1+...); Greek too (ours: research has Hebrew only)
  subj           the subject's referent word id(s): MACULA subjref of the verb, else the A0's participantref (Greek: referent), else the
                 A0 word; Greek too (ours)
  subj_switch    same | switch | first | none, by referent word against the previous clause with a subject in the chapter
  lxx_form, lxx_tense, lxx_mood   (Hebrew) the Septuagint form MACULA gives for the verb and its tense and mood. Ours: the parse of that
                 very form in the same GLAUx verse when it is there (lxx_basis "verse"), else research's rule, the commonest GLAUx parse of
                 the form (then of the Greek NT form) anywhere ("form"); "" when unknown
  neg_scope, subj_form, part, part_switch, front, focus, m_trans, subj_role, recip   research's extra columns, same rules
                 (clause_layers.py extra_ot / extra_nt), from the same MACULA data read from our stores
Not rebuilt: research's copies of layout columns (kind, rule, relation, discourse, via, role, junction, parent, depth: read the layout),
force / person / number / gender / stem (the layout's force column and the spine's morphology hold them), juncture / nexus (wave 2,
clause relation), akt / akt_p / juss_p (model answers, not source facts), heb_form (research's private Delitzsch alignment).
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime
import hashlib
import json
import re
import sqlite3
import subprocess
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
HEB_LAYOUT = HERE / "data" / "clause-layout" / "clauses"
GRC_LAYOUT = HERE / "data" / "nt-clause-layout" / "clauses"
LAYER = HERE / "data" / "speaker-layer"
LOWFAT, LSPINE, MSPINE, TREES = (HERE / "lowfat-hbo.db", HERE / "lexeme-spine-macula.db", HERE / "macula-spine.db",
                                 HERE / "trees-macula.db")
LXX = HERE.parent / "lxx" / "data" / "lxx-glaux.db"
HBO_LOWFAT = HERE / ".lowfat-src" / "WLC" / "lowfat"           # Clear-Bible/macula-hebrew WLC/lowfat (CC BY 4.0)
OUT = HERE / "data" / "clause-columns"
RESEARCH_REV = "8a132e44"
NEVER = {("GEN", 22), ("GEN", 37), ("GEN", 44)}          # research's closed chapters: its table has no layer columns there

BOOK_GENRE = {}
for _g, _bs in (("narrative", "GEN JOS JDG RUT 1SA 2SA 1KI 2KI 1CH 2CH EZR NEH EST JON MAT MRK LUK JHN ACT"),
                ("law", "EXO LEV NUM DEU"), ("poetry", "PSA SNG LAM"), ("wisdom", "JOB PRO ECC"),
                ("prophecy", "ISA JER EZK HOS JOL AMO OBA MIC NAM HAB ZEP HAG ZEC MAL"), ("apocalyptic", "DAN REV"),
                ("epistle", "ROM 1CO 2CO GAL EPH PHP COL 1TH 2TH 1TI 2TI TIT PHM HEB JAS 1PE 2PE 1JN 2JN 3JN JUD")):
    BOOK_GENRE.update({b: _g for b in _bs.split()})

# ---- research's clause_features.py tables (verb, conj, voice, neg)
H_CONJ = {"p": "qatal", "w": "wayyiqtol", "i": "yiqtol", "q": "weqatal", "v": "imperative", "j": "jussive", "h": "cohortative",
          "r": "ptc", "s": "ptc_pass", "c": "inf_c", "a": "inf_a"}
H_STEM = {"q": "qal", "N": "niphal", "p": "piel", "P": "pual", "h": "hiphil", "H": "hophal", "t": "hitpael", "o": "polel", "O": "polal",
          "r": "hitpolel", "m": "poel", "M": "poal", "k": "palel", "K": "pulal", "Q": "qal_pass", "l": "pilpel", "L": "polpal",
          "f": "hitpalpel", "D": "nithpael", "j": "pealal", "i": "pilel", "u": "hothpaal", "c": "tiphil", "v": "hishtaphel",
          "w": "hitpoel", "y": "hitpalal", "z": "hitpoel"}
A_STEM = {"q": "peal", "Q": "peil", "u": "hithpeel", "p": "pael", "P": "ithpaal", "M": "hithpaal", "a": "aphel", "h": "haphel",
          "s": "saphel", "e": "shaphel", "H": "hophal", "i": "ithpeel", "t": "hishtaphel", "v": "ishtaphel", "w": "hithaphel",
          "o": "polel", "z": "ithpoel", "r": "hithpolel", "f": "hithpalpel", "b": "hephal", "c": "tiphel", "m": "poel", "l": "palpel",
          "L": "ithpalpel", "O": "ithpolel", "G": "ittaphal"}
H_PASS = {"niphal", "pual", "hophal", "qal_pass", "polal", "poal", "pulal", "polpal", "peil", "ithpaal", "hithpaal", "ithpeel", "ithpoel",
          "ittaphal"}
H_MID = {"hitpael", "hitpolel", "hitpalpel", "nithpael", "hitpoel", "hitpalal", "hothpaal", "hishtaphel", "hithpeel", "ishtaphel",
         "hithaphel", "hithpolel", "hithpalpel", "ithpalpel"}
H_NEG = {"3808": "lo", "0408": "al", "0409": "al", "0369": "en", "1077": "bal", "3809": "la", "1115": "bilti"}
G_NEG = {3756: "ou", 3761: "ou", 3765: "ou", 3780: "ou", 3361: "me", 3366: "me", 3371: "me", 3762: "ou", 3763: "ou", 3764: "ou",
         3768: "ou", 3777: "ou", 3367: "me", 3368: "me", 3369: "me", 3380: "me", 3383: "me"}
G_EXCEPT = {1487, 1437, 4133}
G_LEST = {3379, 3381}
FINITE_G = {"indicative", "imperative", "subjunctive", "optative"}
FINITE_H = {"qatal", "wayyiqtol", "yiqtol", "weqatal", "imperative", "jussive", "cohortative"}

# ---- research's clause_layers.py tables
G_TENSE = {"P": "present", "I": "imperfect", "F": "future", "A": "aorist", "X": "perfect", "Y": "pluperfect"}
G_MOOD = {"I": "indicative", "S": "subjunctive", "O": "optative", "D": "imperative", "M": "imperative", "N": "infinitive",
          "P": "participle"}
H_NEGS = set(H_NEG)
G_NEGS = set(G_NEG)
SKIP_H = {"cj", "rel", "ptcl", "ij", "art"}
SKIP_G = {"conj", "ptcl", "intj", "det"}
FRONT = {"s", "o", "o2", "io", "pp", "adv", "p"}


def plain(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c)).replace("ς", "σ").strip(".,;·:!?'’\"")


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _tsv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader((l for l in f if not l.startswith("#")), delimiter="\t"))


def _layout(root: Path) -> dict[str, list[dict]]:
    """book -> rows in layout order"""
    out = {}
    for d in sorted(root.iterdir()):
        rows = []
        for f in sorted(d.glob("*.jsonl")):
            rows += [json.loads(l) for l in open(f, encoding="utf-8")]
        out[d.name] = rows
    return out


# ------------------------------------------------------------------------------------------------------------------- shared stores
class Stores:
    def __init__(self) -> None:
        m = _ro(MSPINE)
        self.frames = collections.defaultdict(list)            # verb key -> [(label, arg key)] in MACULA's order
        for v, lab, a in m.execute("select verb_key, role, arg_key from frames order by rowid"):
            self.frames[v].append((lab, a))
        self.refs = collections.defaultdict(lambda: collections.defaultdict(list))   # key -> kind -> [targets]
        for s, t, k in m.execute("select src_key, tgt_key, kind from refs order by rowid"):
            self.refs[s][k].append(t)
        self.wlang, mstrong = {}, {}
        for k, wl, st in m.execute("select key, wlang, strong from macula_words where lang='hbo'"):
            self.wlang[k], mstrong[k] = wl, st
        sp = _ro(LSPINE)
        prole = dict(sp.execute("select key, phrase_role from spine_words where length(key)=12"))
        # Hebrew word -> [class, type, strong, lemma, phrase_role, subjref, participantref, morph, greek, lang]. The strong number is
        # MACULA's TSV value (macula-spine.db; lowfat-hbo.db leaves 1,706 words of multi-word names without one); the Septuagint form
        # loses the CSV quotes lowfat-hbo.db keeps on 101 bracketed forms ("{δ}" -> {δ}).
        self.H = {}
        for k, cls, typ, strong, lemma, morph, greek in _ro(LOWFAT).execute(
                "select key, class, type, strong, lemma, morph, greek from lowfat_words where is_inserted=0"):
            r = self.refs.get(k, {})
            g = greek or ""
            if len(g) > 1 and g[0] == g[-1] == '"':
                g = g[1:-1]
            self.H[k] = [cls or "", typ or "", mstrong.get(k) or strong or "", lemma or "", prole.get(k) or "",
                         " ".join(r.get("subjref", [])), " ".join(r.get("participantref", [])), morph or "", g, self.wlang.get(k, "H")]
        # Greek word -> [class, strong, lemma, role (tree), plain surface, tense, voice, mood, person, number, gender, own role]
        self.G = {}
        for k, strong, role, tense, voice, mood, person, number, gender in sp.execute(
                "select key, strong, role, tense, voice, mood, person, number, gender from spine_words where length(key)=11"):
            self.G[k] = ["", strong or 0, "", role or "", "", tense or "", voice or "", mood or "", person or "", number or "",
                         gender or "", role or ""]
        for k, cls, lemma, text in m.execute("select key, class, lemma, text from macula_words where lang='grc'"):
            if k in self.G:
                self.G[k][0], self.G[k][2], self.G[k][4] = cls or "", lemma or "", plain(text or "")
        t = _ro(TREES)
        node = {i: (par, cls, role) for i, par, cls, role in t.execute("select id, parent, cls, role from nodes where corpus='grc'")}
        self.g_obj_node = self._object_nodes(t, "grc")       # Greek word -> class of the nearest object node above it (cl, np ...)
        self.g_clause_obj = {k for k, c in self.g_obj_node.items() if c == "cl"}
        h_obj = self._object_nodes(t, "hbo")
        self.h_clause_obj = {k for k, c in h_obj.items() if c == "cl"}
        self.h_obj_node = h_obj                                # Hebrew word -> class of the nearest object node above it
        self.h_obj_word = set(h_obj) | {k for k, r in t.execute("select key, role from words where corpus='hbo'") if r in ("o", "o2")}
        for k, role, par in t.execute("select key, role, parent from words where corpus='grc'"):
            if k not in self.G:
                continue
            r = role if role in FRONT else ""
            while not r and par in node:                       # the nearest role above the word, within its clause (research's rule)
                par, cls, nr = node[par]
                if nr in FRONT:
                    r = nr
                elif cls == "cl":
                    break
                if nr in ("v", "vc"):
                    break
            if r:
                self.G[k][3] = r
        self.hframes = self._hebrew_frames()
        self.lxx_form, self.lxx_verse = self._lxx()

    @staticmethod
    def _object_nodes(t, corpus: str) -> dict[str, str]:
        """word key -> the class of the nearest word group above it whose role is o / o2 (an object), for words inside an object"""
        node = {i: (par, cls, role) for i, par, cls, role in t.execute("select id, parent, cls, role from nodes where corpus=?", (corpus,))}
        out = {}
        for k, par in t.execute("select key, parent from words where corpus=?", (corpus,)):
            p = par
            while p in node:
                pp, pc, pr = node[p]
                if pr in ("o", "o2"):
                    out[k] = pc or ""
                    break
                p = pp
        return out

    @staticmethod
    def _hebrew_frames() -> dict[str, list[tuple[str, list[str]]]]:
        """Hebrew verb key -> [(label, [arg keys])] from MACULA's own `frame` attribute (lowfat XML). macula-spine.db's frames table
        keeps one row per argument word and so drops a label MACULA gives with no word ("A0:;", an argument it marks unexpressed);
        research's table keeps such labels, and they count in args, m_trans and subj_role."""
        el, fid, ffr = re.compile(r"<w\b[^>]*>"), re.compile(r'xml:id="o?(\d{12})"'), re.compile(r'\bframe="([^"]*)"')
        out = {}
        for f in sorted(HBO_LOWFAT.glob("*.xml")):
            for m in el.finditer(f.read_text(encoding="utf-8")):
                x = m.group(0)
                fr, i = ffr.search(x), fid.search(x)
                if not (fr and i):
                    continue
                args = []
                for part in fr.group(1).replace(" ", "").split(";"):
                    if ":" in part:
                        lab, w = part.split(":", 1)
                        args.append((lab, [re.sub(r"\D", "", w)] if w else []))
                    elif part and args:
                        args[-1][1].append(re.sub(r"\D", "", part))
                out[i.group(1)] = args
        return out

    def _lxx(self):
        """plain form -> commonest (tense, mood) in GLAUx, then in the Greek NT (research's rule); and (book, c, v, plain) -> parse"""
        c, verse = collections.defaultdict(collections.Counter), {}
        for book, ch, vs, surf, morph in _ro(LXX).execute(
                "select book, chapter, verse, surface, morph from lxx_words where morph like 'V.%' order by book, chapter, verse, idx"):
            mm = morph.split(".", 1)[1]
            if len(mm) >= 3:
                p = (G_TENSE.get(mm[0], ""), G_MOOD.get(mm[2], ""))
                c[plain(surf)][p] += 1
                verse.setdefault((book, ch, vs, plain(surf)), p)
        nt = collections.defaultdict(collections.Counter)
        for g in self.G.values():
            if g[7]:
                nt[g[4]][(g[5], g[7])] += 1
        out = {k: v.most_common(1)[0][0] for k, v in nt.items()}
        out.update({k: v.most_common(1)[0][0] for k, v in c.items()})
        return out, verse


def _resolve(w, step, lemma_of, n=3):
    for _ in range(n):
        nx = step(w)
        if not nx or nx == w:
            break
        w = nx
    return lemma_of(w)


def _order_cols(words, cls_role, verb, is_neg, presentational):
    """front, focus, neg_scope (research's order_cols)"""
    skip = SKIP_H | SKIP_G
    neg_scope = "none"
    for i, w in enumerate(words):
        if is_neg(w):
            nxt = next((x for x in words[i + 1:] if cls_role(x)[0] not in skip), None)
            neg_scope = "verb" if nxt is not None and (nxt == verb or cls_role(nxt)[0] == "verb") else "constituent"
            break
    front, front_cls = "", ""
    if not verb:
        front = "verbless"
    else:
        for w in words:
            if w == verb:
                break
            c, r = cls_role(w)
            if c in skip or is_neg(w) or c == "verb":
                continue
            if r in FRONT:
                front, front_cls = r, c
                break
    if presentational:
        focus = "sentence"
    elif front in ("o", "o2", "io", "pp", "adv") and front_cls != "pron":
        focus = "narrow"
    elif front == "s":
        focus = "topic"
    else:
        focus = "predicate"
    return front, focus, neg_scope


def _switch(prev, cur):
    return "none" if not cur else ("first" if prev is None else ("same" if prev == cur else "switch"))


# ------------------------------------------------------------------------------------------------------------------------- Hebrew
def _hebrew_verb(morph: str, lang: str):
    m = morph[1:] if lang == "A" and morph.startswith("A") else morph
    if not m.startswith("V") or len(m) < 3:
        return None
    return {"conj": H_CONJ.get(m[2], m[2]), "stem": (A_STEM if lang == "A" else H_STEM).get(m[1], m[1])}


def hebrew(S: Stores, replica: bool = False) -> list[dict]:
    """One row per clause_key. replica=True reproduces research's reading, for the contract check only: a clause the layout splits
    into several segments takes its verb (and neg) from the last segment and its word order from the first (research's
    clause_features.py keeps the last row of a key, clause_layers.py the first), the layer's last segment row of the key, and the
    Septuagint parse by form only."""
    seg, spk_id = {}, {}
    for q in _tsv(LAYER / "quotations.tsv"):
        spk_id[q["id"]] = q["speaker_id"] or ""
    for f in sorted((LAYER / "segments").glob("*.tsv")):
        for r in _tsv(f):
            val = (int(r["level"] or 0), r["speaker"] or "", r["frame"] or "", spk_id.get(r["quotation"], ""))
            if replica:
                seg[r["clause_key"]] = val
            else:
                seg.setdefault(r["clause_key"], val)
    H = S.H
    info = lambda w: H.get(w, ["", "", "", "", "", "", "", "", "", "H"])
    out = []
    for book, rows in _layout(HEB_LAYOUT).items():
        clauses = collections.OrderedDict()
        for r in rows:
            clauses.setdefault(r["clause_key"], []).append(r)
        last_subj, last_part = {}, {}
        for k, segs in clauses.items():
            r0 = segs[0]
            ws = sorted({w for r in segs for w in r["words"]})
            inside = set(ws)
            vws = ws
            if replica:
                ws, vws = list(segs[0]["words"]), list(segs[-1]["words"])
            cand, neg = [], None
            for w in vws:
                x = info(w)
                if x[2] in H_NEG and not neg:
                    neg = H_NEG[x[2]]
                d = _hebrew_verb(x[7], x[9])
                if d:
                    cand.append((0 if d["conj"] in FINITE_H else 1, w, d))
            v, vd = (sorted(cand, key=lambda c: c[0])[0][1:] if cand else (None, None))
            conj = vd["conj"] if vd else None
            stem = vd["stem"] if vd else None
            voice = (("passive" if stem in H_PASS else "middle" if stem in H_MID else "active") if stem else None)
            lv, spk, frm, sid = seg.get(k, (0, "", "", ""))
            args = S.hframes.get(v, []) if v else []           # [(label, [words])], MACULA's order; a label may have no word
            labs = [a for a, _ in args]
            a0 = next((w for a, w in args if a == "A0" and w), [])
            sref = info(v)[5] if v else ""
            genre = BOOK_GENRE.get(book, "")
            if lv or frm:
                line = "speech"
            elif not v:
                line = "setting"
            elif genre != "narrative":
                line = "non-narrative"
            else:
                line = "main" if conj == "wayyiqtol" else "background"
            subj = sref or (info(a0[0])[6] if a0 else "") or (a0[0] if a0 else "")
            ch = r0["chapter"]
            sw = _switch(last_subj.get(ch), subj)
            if subj:
                last_subj[ch] = subj
            gk = info(v)[8] if v else ""
            t, m, basis = "", "", ""
            if gk:
                p = None if replica else S.lxx_verse.get((book, int(v[2:5]), int(v[5:8]), plain(gk)))   # same verse in GLAUx
                if p:
                    (t, m), basis = p, "verse"
                elif plain(gk) in S.lxx_form:
                    (t, m), basis = S.lxx_form[plain(gk)], "form"
            a1in = any(a == "A1" and any(x in inside for x in w) for a, w in args)
            a1out = any(a == "A1" and w for a, w in args)
            a1w = [x for a, w in args if a == "A1" for x in w]
            a1_in = [x for x in a1w if x in inside]
            # undergoer and its basis, the same vocabulary as the Greek (packet 25 sections 4-6)
            if a1w and all(x in S.h_clause_obj for x in a1w):
                und, ub = "clause", "clause"
            elif a1_in:
                und = "overt"
                ub = ("passive_subject" if voice == "passive" and any(info(x)[4] == "s" for x in a1_in) else
                      "np_a1" if any(S.h_obj_node.get(x) for x in a1_in) else
                      "single_word_o" if any(x in S.h_obj_word for x in a1_in) else "a1_other")
            elif any(x in S.h_obj_word for x in inside):              # an object in the tree with no A1 in the frame: with the
                und, ub = (("overt", "role_o_et") if any(info(x)[2].lstrip("0").rstrip("abcdef") == "853" for x in inside)
                           else ("complement", "role_o_without_a1"))     # object marker et it acts as a direct object (packet 25 s.7)
            else:
                und, ub = ("implicit" if a1out else "none"), ""
            row = dict(clause_key=k, ref=f"{book} {r0['chapter']}:{r0['verse']}.{r0['seg']}", verb=v, conj=conj, voice=voice, neg=neg,
                       speech=lv, speaker=spk, speaker_id=sid, frame=frm, genre=genre, line=line,
                       actor="overt" if any(w in inside for w in a0) else ("implicit" if a0 or sref else "none"),
                       undergoer=und, undergoer_basis=ub, args="+".join(labs),
                       subj=subj, subj_switch=sw, lxx_form=gk, lxx_tense=t, lxx_mood=m, lxx_basis=basis)
            row.update(_extra_hebrew(ws, v, conj, voice, args, info, last_part, ch))
            out.append(row)
    return out


def _extra_hebrew(ws, v, conj, voice, args, info, last_part, ch):
    subj_w = [w for w in ws if info(w)[4] == "s" and info(w)[0] in ("noun", "pron", "adj", "num")]
    finite = conj in FINITE_H
    sf = ("noun" if any(info(w)[0] != "pron" for w in subj_w) else "pronoun") if subj_w else ("zero" if finite else "none")

    def step(w):
        x = info(w)
        ref = (x[5] or x[6]).split()
        return ref[0] if ref else None
    lemma_of = lambda w: info(w)[2] or info(w)[3]
    if subj_w:
        part = _resolve(next((w for w in subj_w if info(w)[0] != "pron"), subj_w[0]), step, lemma_of)
    elif v and info(v)[5]:
        part = _resolve(info(v)[5].split()[0], step, lemma_of)
    else:
        part = ""
    psw = _switch(last_part.get(ch), part)
    if part:
        last_part[ch] = part
    first = next((w for w in ws if info(w)[0] != "cj"), None)
    pres = bool(first and info(first)[2] in ("2009", "2005")) or (not v and any(info(w)[2] in ("3426", "0369") for w in ws)) \
        or bool(v and first == v and info(v)[2] == "1961" and conj == "wayyiqtol" and info(v)[4] == "v" and len(ws) <= 3)
    front, focus, ns = _order_cols(ws, lambda w: (info(w)[0], info(w)[4]), v, lambda w: info(w)[2] in H_NEGS, pres)
    labs = {a for a, _ in args}
    a0 = {x for a, w in args if a == "A0" for x in w}
    a1 = {x for a, w in args if a == "A1" for x in w}
    if subj_w:
        sr = "actor" if set(subj_w) & a0 else "undergoer" if set(subj_w) & a1 else "other"
    elif v and finite:
        sr = "undergoer" if voice == "passive" else ("actor" if "A0" in labs else "other")
    else:
        sr = "none"
    return dict(neg_scope=ns, subj_form=sf, part=part, part_switch=psw, front=front, focus=focus,
                m_trans=("A0" in labs) + ("A1" in labs), subj_role=sr, recip=int("A2" in labs))


# -------------------------------------------------------------------------------------------------------------------------- Greek
def greek(S: Stores) -> list[dict]:
    G = S.G
    info = lambda w: G.get(w, ["", 0, "", "", "", "", "", "", "", "", "", ""])
    out = []
    for book, rows in _layout(GRC_LAYOUT).items():
        last_subj, last_part = {}, {}
        for r in rows:
            k, ws = r["first"], list(r["words"])
            neg, cand, prev = None, [], None
            for i, w in enumerate(ws):
                x = info(w)
                strong = x[1]
                nxt = info(ws[i + 1])[1] if i + 1 < len(ws) else None
                if strong == 3361 and nxt == 4218:                 # me pote: "lest"
                    prev = strong
                    continue
                if strong in G_NEG and not neg and not (strong == 3361 and prev in G_EXCEPT):
                    neg = G_NEG[strong]
                prev = strong
                if x[7]:
                    cand.append((0 if x[7] in FINITE_G else 1, 0 if x[11] == "v" else 1, w))
            v = sorted(cand, key=lambda c: (c[0], c[1]))[0][2] if cand else None
            tense, voice, mood = (info(v)[5], info(v)[6], info(v)[7]) if v else ("", "", "")
            conj = f"{tense}_{mood}" if mood else None
            finite = mood in FINITE_G
            sp = 1 if r["quotation"] else 0
            genre = BOOK_GENRE.get(book, "")
            if sp:
                line = "speech"
            elif not v:
                line = "setting"
            elif genre != "narrative":
                line = "non-narrative"
            else:
                line = "main" if (r["depth"] or 0) == 0 and conj in ("aorist_indicative", "present_indicative") else "background"
            inside = set(ws)
            roles = {info(w)[3] for w in ws}
            args = S.frames.get(v, []) if v else []
            labs = [a for a, _ in args]
            a0 = [w for a, w in args if a == "A0"]
            a1 = [w for a, w in args if a == "A1"]
            sref = (S.refs.get(v, {}).get("subjref") or [""])[0] if v else ""
            actor = "overt" if ("s" in roles or any(w in inside for w in a0)) else ("implicit" if finite or a0 or sref else "none")
            undergoer = "overt" if (roles & {"o", "o2"} or any(w in inside for w in a1)) else ("implicit" if a1 else "none")
            if a1 and all(w in S.g_clause_obj for w in a1):    # the verb's patient is a clause (TBTA: an embedded proposition)
                undergoer = "clause"
            # undergoer_basis (packet 25 sections 4-5): what made the undergoer present; a documented column
            a1_in = [w for w in a1 if w in inside]
            if undergoer == "clause":
                ubasis = "clause"
            elif undergoer != "overt":
                ubasis = ""
            elif a1_in and voice == "passive" and any(info(w)[3] == "s" for w in a1_in):
                ubasis = "passive_subject"
            elif any(S.g_obj_node.get(w) for w in a1_in):
                ubasis = "np_a1"
            elif a1_in:
                ubasis = "single_word_o" if any(info(w)[11] == "o" for w in a1_in) else "a1_other"
            else:
                ubasis = "role_o_without_a1"
                undergoer = "complement"                         # an object-role word the frame does not list as A1 (packet 25 s.5)
            subj = sref or (" ".join(S.refs.get(a0[0], {}).get("referent", [])) if a0 else "") or (a0[0] if a0 else "")
            ch = r["chapter"] if "chapter" in r else int(k[2:5])
            sw = _switch(last_subj.get(ch), subj)
            if subj:
                last_subj[ch] = subj
            row = dict(clause_key=k, ref=f"{book} {int(k[2:5])}:{r['verse']}.{r['seg']}", verb=v, conj=conj, voice=voice or None,
                       neg=neg, speech=sp, speaker=r["speaker_id"] or "", genre=genre, line=line, actor=actor, undergoer=undergoer, undergoer_basis=ubasis,
                       args="+".join(labs), subj=subj, subj_switch=sw)
            row.update(_extra_greek(ws, v, voice, neg, finite, info, S, last_part, ch))
            out.append(row)
    return out


def _extra_greek(ws, v, voice, neg, finite, info, S, last_part, ch):
    subj_w = [w for w in ws if info(w)[3] == "s"]
    sf = ("pronoun" if all(info(w)[0] == "pron" for w in subj_w) else "noun") if subj_w else ("zero" if finite else "none")

    def step(w):
        r = S.refs.get(w, {})
        return (r.get("referent") or r.get("subjref") or [None])[0]
    lemma_of = lambda w: info(w)[2]
    sref = (S.refs.get(v, {}).get("subjref") or [None])[0] if v else None
    if subj_w:
        part = _resolve(subj_w[0], step, lemma_of)
    elif sref:
        part = _resolve(sref, step, lemma_of)
    else:
        part = ""
    psw = _switch(last_part.get(ch), part)
    if part:
        last_part[ch] = part
    pres = any(info(w)[4] in ("ιδου", "ιδε") for w in ws)
    front, focus, ns = _order_cols(ws, lambda w: (info(w)[0], info(w)[3]), v, lambda w: info(w)[1] in G_NEGS and bool(neg), pres)
    fr = S.frames.get(v or "", [])
    labs = {a for a, _ in fr}
    a0 = {w for a, w in fr if a == "A0"}
    a1 = {w for a, w in fr if a == "A1"}
    if not fr:
        labs = ({"A0"} if subj_w or finite else set()) | ({"A1"} if any(info(w)[3] in ("o", "o2") for w in ws) else set())
    if subj_w:
        sr = "actor" if set(subj_w) & a0 else "undergoer" if set(subj_w) & a1 else \
            ("undergoer" if voice == "passive" else "actor" if not fr else "other")
    elif v and finite:
        sr = "undergoer" if voice == "passive" else ("actor" if "A0" in labs else "other")
    else:
        sr = "none"
    return dict(neg_scope=ns, subj_form=sf, part=part, part_switch=psw, front=front, focus=focus,
                m_trans=("A0" in labs) + ("A1" in labs), subj_role=sr, recip=int("A2" in labs))


# ------------------------------------------------------------------------------------------------------------------------- output
def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _tree_sha(root: Path, pattern: str) -> str:
    h = hashlib.sha256()
    for f in sorted(root.glob(pattern)):
        h.update(f.name.encode())
        h.update(_sha(f).encode())
    return h.hexdigest()


def _write(rows: list[dict], path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    pq.write_table(pa.Table.from_pylist(rows), path)


def _meta(db: Path, table: str = "meta") -> dict:
    try:
        return dict(_ro(db).execute(f"select key, value from {table}"))
    except sqlite3.Error:
        return {}


def build(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    S = Stores()
    heb, grc = hebrew(S), greek(S)
    _write(heb, out / "hebrew.parquet")
    _write(grc, out / "greek-nt.parquet")
    code = HERE / "build_clause_columns.py"
    commit = subprocess.run(["git", "log", "-1", "--format=%h", "--", "macula/build_clause_columns.py"], cwd=HERE.parent, text=True,
                            capture_output=True).stdout.strip() or None
    counts = {}
    for name, rows in (("hebrew", heb), ("greek-nt", grc)):
        cols = list(rows[0])
        counts[name] = {"rows": len(rows), "filled": {c: sum(1 for r in rows if r[c] not in (None, "")) for c in cols},
                        "values": {c: dict(collections.Counter(r[c] for r in rows).most_common(12)) for c in
                                   ("line", "actor", "undergoer", "subj_switch", "lxx_tense", "lxx_mood", "lxx_basis", "subj_form",
                                    "part_switch", "front", "focus", "subj_role", "m_trans") if c in cols}}
    hl, gl = json.loads((HERE / "data" / "clause-layout" / "build.json").read_text()), \
        json.loads((HERE / "data" / "nt-clause-layout" / "build.json").read_text())
    build = {
        "built": datetime.date.today().isoformat(),
        "code": {"file": "macula/build_clause_columns.py", "sha256": _sha(code), "last_commit": commit,
                 "contract_check": {"file": "macula/clause_columns_contract.py", "sha256": _sha(HERE / "clause_columns_contract.py")}},
        "sources": {
            "hebrew-clause-layout": {"path": "macula/data/clause-layout", "built": hl.get("built"),
                                     "clauses_sha256": _tree_sha(HEB_LAYOUT, "*/*.jsonl"), "release": "same clause keys as v0.37 (checked)",
                                     "licence": "CC BY-SA 4.0 (the release; its keys key this table)"},
            "greek-nt-clause-layout": {"path": "macula/data/nt-clause-layout", "built": gl.get("built"),
                                       "clauses_sha256": _tree_sha(GRC_LAYOUT, "*/*.jsonl"), "licence": "CC BY 4.0"},
            "hebrew-speaker-layer": {"path": "macula/data/speaker-layer", "quotations_sha256": _sha(LAYER / "quotations.tsv"),
                                     "segments_sha256": _tree_sha(LAYER / "segments", "*.tsv"), "release": "v0.15 (HF 2e93b66, identical)",
                                     "licence": "CC BY 4.0"},
            "lowfat-hbo.db": {"sha256": _sha(LOWFAT), "meta": _meta(LOWFAT), "licence": "CC BY 4.0 (MACULA Hebrew)"},
            "lexeme-spine-macula.db": {"sha256": _sha(LSPINE), "content": _meta(LSPINE, "spine_meta").get("spine_content_sha256"),
                                       "licence": "CC BY 4.0"},
            "macula-spine.db": {"sha256": _sha(MSPINE), "licence": "CC BY 4.0 (MACULA frames and refs)"},
            "trees-macula.db": {"sha256": _sha(TREES), "meta": _meta(TREES), "licence": "CC BY 4.0"},
            "macula-hebrew lowfat XML (frame attribute)": {"path": "macula/.lowfat-src/WLC/lowfat", "git": subprocess.run(
                ["git", "-C", str(HERE / ".lowfat-src"), "log", "-1", "--format=%H"], text=True, capture_output=True).stdout.strip()
                or None, "licence": "CC BY 4.0"},
            "lxx-glaux.db": {"sha256": _sha(LXX), "release": "spine-releases lxx-glaux-2026-10-10", "licence": "CC BY-SA 4.0 (GLAUx)",
                             "used_by": ["lxx_tense", "lxx_mood"]},
        },
        "licence": "CC BY-SA 4.0 as a whole (the Hebrew layout's keys; lxx_tense / lxx_mood from GLAUx parses); the column values "
                   "themselves come from CC BY 4.0 sources (MACULA, the speaker layer, the Greek layout) except lxx_tense / lxx_mood",
        "compared_with": {"repo": "bcv-commons/clause-columns", "revision": RESEARCH_REV, "files": ["checks.md", "contract.tsv",
                                                                                                   "examples.tsv"]},
        "not_read": ["BHSA", "TBTA", "English text"],
        "counts": counts,
    }
    (out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return build


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--check", help="research's clause-columns snapshot (folder with data/hebrew.parquet, data/greek-nt.parquet)")
    ap.add_argument("--check-only", action="store_true", help="skip the build, check the tables already in --out")
    a = ap.parse_args()
    out = Path(a.out)
    if not a.check_only:
        b = build(out)
        for n, c in b["counts"].items():
            print(n, c["rows"], json.dumps(c["values"], ensure_ascii=False))
    if a.check:
        from macula import clause_columns_contract
        clause_columns_contract.run(out, Path(a.check))


if __name__ == "__main__":
    main()
