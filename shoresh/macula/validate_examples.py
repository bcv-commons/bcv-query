"""Validator of the source examples: the exit conditions of SPEC 1.0, section 10, stage by stage.

    shoresh/.venv/bin/python -I shoresh/macula/validate_examples.py --upto 02|...|10|14|...|19 [--build b1|c1] [--compare b2] [--write-md] [--only NN]

Prints every condition with its count and PASS/FAIL, then INFO lines (reported figures). Ends with code 1 when a
condition fails. It reads the sources itself with its own parser (it imports nothing from the builder), so a fault
of the builder's reading shows here.
"""
import argparse
import collections as C
import csv
import glob
import json
import multiprocessing as mp
import os
import re
import sys
import tomllib
import unicodedata as U
import xml.etree.ElementTree as ET

import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
XID = "{http://www.w3.org/XML/1998/namespace}id"
HEB_LOWFAT = os.path.join(HERE, ".lowfat-src/WLC/lowfat")
GRC_LOWFAT = os.path.join(HERE, ".lowfat-src-grc")
HEB_NODES = os.path.join(HERE, "data/macula-nodes/hebrew/WLC/nodes")
UBS = os.path.join(HERE, "data/word-senses-ubs/words.tsv")

WORD_COLS = ["t", "id", "book", "chapter", "verse", "w", "text", "after", "sentence",
             "clause", "head", "head_basis", "rel", "rel_shared"]
PIECE_COLS = ["t", "n", "pid", "text", "kind", "lexeme", "class", "marks", "fused", "head_t", "head_n",
              "head_basis", "rel", "who", "who_basis", "sense", "domain", "shared"]
# the stage that fills each column of a later stage; a column stays null until its stage has run
FILLED_BY = {"words": {"head": "03", "head_basis": "03", "rel": "03", "rel_shared": "03", "clause": "04"},
             "pieces": {"head_t": "03", "head_n": "03", "head_basis": "03", "rel": "03", "who": "06",
                        "who_basis": "06", "shared": "09"}}
UPTO = "02"
V11 = False   # set by stage 15: the stage 02-04 checks read the rules of SPEC 1.1 (build c1)
PIECE_COLS_11 = PIECE_COLS + ["concept", "concept_by"]
# SPEC 1.1, section 14: the columns that stages after 15 fill (null until then)
# the stage that fills each such column; a column is checked null while that stage is beyond --upto
FILLED_11 = {"words": {"rel_shared": "20"},
             "pieces": {"who": "16", "who_basis": "16", "shared": "20", "concept": "17", "concept_by": "17"},
             "clauses": {"marks": "16", "shared": "20", "quote": "16", "speaker": "16", "addressee": "16",
                         "speech_basis": "16", "line": "16", "quote_model": "17", "speaker_model": "17",
                         "addressee_model": "17", "subject_model": "17"},
             "constituents": {"sem_role": "16", "sem_role_basis": "16"}}


class _Later11(dict):
    def __getitem__(self, tab):
        return [c for c, st in FILLED_11[tab].items() if st > UPTO]


LATER_11 = _Later11()
LEX_COLS = ["lexeme", "lemma", "strong", "class", "count", "forms", "books", "senses", "domains", "first"]
MARK_CATS = {"hbo": {"type", "stem", "person", "gender", "number", "state"},
             "arc": {"type", "stem", "person", "gender", "number", "state"},
             "grc": {"type", "tense", "voice", "mood", "person", "case", "gender", "number", "degree"}}


S10_STAGE_LINES = []  # (stage, line) of this run, for VALIDATION.md


# SPEC 1.8 (j builds, stage 52): checks of older stages that cannot hold on j1, each with its reason. A failed check
# whose name holds one of these texts is printed HELD (not PASS, not FAIL) and counted apart; report 52 lists them.
# INPUT: an input i1 read is gone from the disk (data/arg-roles/roles.tsv 4c494ac9, the lexeme-aligner's old heb_scg
#   sidecars, clause-columns bc2e8159 as the live file); the table equals i1 (stage 52, outside the mends).
# MEND: the older rule or the older build (d1, g1) is what a 1.8 mend changes; stage 52 recomputes the mend.
# SPEC: the file lies outside section 13's reach, so it is i1's, but its recount reads mended tables (report 52).
HELD18_ON = False
HELD18 = (
    ("terms.tsv: every text term and every sem_role source is rule T", "INPUT roles.tsv"),
    ("constituents: sem_role, sem_role_basis equal D12 recomputed", "INPUT roles.tsv"),
    ("categories.toml constituents.sem_role", "INPUT roles.tsv"),
    ("strict view: constituents.parquet equals stage 16", "INPUT roles.tsv"),
    ("grc categories.toml links.how, links.basis, link_account.state", "INPUT heb_scg sidecars (counts of the republished pair)"),
    ("strict view: source_errors.tsv equals stage 16", "SPEC source_errors.tsv (SE5 reads the mended links)"),
    ("facts: rendered_by equals the recount from the linked rows", "SPEC facts.parquet (M4 links)"),
    ("map.tsv: every count equals the recount", "SPEC map.tsv (M1 form/kind counts)"),
    ("analysis and analysis_basis equal hebrew-nt-analysis v0.2 recomputed (D14)", "MEND M3 (stage 52: m3)"),
    ("added.parquet: every row recomputed by D18, in order", "MEND M1, M2 (stage 52: m1m2)"),
    ("added (1.5): every row recomputed by D18's three steps", "MEND M1, M2 (stage 52: m1m2)"),
    ("unchanged: links.parquet equals d1", "MEND M4 (stage 52: m4)"),
    ("unchanged: link_account.parquet equals d1", "MEND M4 (stage 52: m4)"),
    ("words.parquet: equals d1", "MEND M3 (stage 52: m3)"),
    ("tables and files byte-equal to g1", "MEND M1, M4 (stage 52: against i1)"),
    ("every file but parts.parquet byte-equal to g1", "MEND M3 words.parquet (stage 52: m3)"),
    ("parts unchanged: s, p, text, class, lemma, strong equal", "MEND M3 (stage 52: m3)"),
    ("parts (1.5): lexeme, key_rule, basis differ from", "MEND M3 (stage 52: m3)"),
    ("files byte-equal to g1 (all but", "MEND M3, M4 (stage 52: against i1, m3, m4)"),
    ("lexicon/groups.parquet unchanged: the rows of the members that stay", "MEND M3 (stage 52: m3, lexicon)"),
    ("added (1.6): every row's kind, form, person, number, gender, who", "MEND M1, M2 (stage 52: m1m2)"),
    ("added (1.6): form ending exactly on the subject rows", "MEND M1 (stage 52: m1m2)"),
    ("source_errors (1.6): the SE5 rows are exactly the added rows", "SPEC source_errors.tsv (SE5 reads the mended added rows)"),
    ("lexemes (1.6): states move only member", "MEND M3 (stage 52: m3, lexicon)"),
    ("parts.parquet: one row per part of every joined word", "MEND M3 (stage 52: m3)"),
    ("lexicon/lexemes.tsv", "MEND M3 (stage 52: m3, lexicon)"),
    ("pairs.parquet: every row recomputed by D24", "MEND M3 (stage 52: m3, lexicon)"),
    ("groups.parquet: every group recomputed by D25", "MEND M3 (stage 52: m3, lexicon)"),
    ("strict view: groups.parquet without its model rows", "MEND M3 (stage 52: m3, lexicon)"),
    ("strict view: lexemes.tsv strict columns", "MEND M3 (stage 52: m3, lexicon)"),
)
HELD18_LINES = []
# SPEC 1.9 (k builds, stage 55; N7): the held checks by full name, compared whole (held19.tsv beside this file: name, reason)
HELD19_ON = False
HELD19 = {}


def load_held19():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "validate_examples_held19.tsv")
    out = {}
    with open(p, encoding="utf-8") as fh:
        for ln in fh.read().split("\n")[1:]:
            if ln.strip():
                name, why = ln.split("\t")
                out[name] = why
    return out


class Report:
    def __init__(self):
        self.fails = 0
        self.held = 0
        self.passes = 0
        self.skips = 0
        self.stage = ""

    def _out(self, line):
        print(line)
        S10_STAGE_LINES.append((self.stage, line))

    def check(self, name, ok, count="", restates=False):
        """`restates`: the check restates a decision of the builder (SPEC 10), marked `(restates)`."""
        name = name + ("  (restates)" if restates else "")
        if HELD19_ON:
            why = HELD19.get(name) if (not ok and self.stage < "55") else None
        else:
            why = next((w for t, w in HELD18 if t in name), None) if (HELD18_ON and not ok and self.stage < "52") else None
        if why:
            line = f"HELD  {name}  [{count}]  ({why})"
            self._out(line[:600])
            HELD18_LINES.append((self.stage, line[:600]))
            self.held += 1
            return
        self._out(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{count}]" if count != "" else ""))
        if not ok:
            self.fails += 1
        else:
            self.passes += 1

    def skip(self, name, why):
        self._out(f"SKIP  {name}  [{why}]")
        self.skips += 1

    def info(self, name, value):
        self._out(f"INFO  {name}: {value}")

    def section(self, name):
        self._out(f"-- {name}")


# ---- independent reading of the sources -------------------------------------------------------------------------

def _lowfat(path):
    root = ET.parse(path).getroot()
    verses = [m.get("id") for m in root.iter("milestone") if m.get("unit") == "verse"]
    out = []
    for s in root.iter("sentence"):
        ws = []
        for w in s.iter("w"):
            ws.append((w.get(XID), w.text or "", w.get("ref"), w.get("lang"), w.get("pos"), w.get("type"),
                       w.get("class"), w.get("after") or "", w.get("frame"), w.get("participantref"),
                       w.get("subjref")))
        p = s.find("p")
        ptext = "".join(p.itertext()) if p is not None else ""
        out.append((ws, ptext))
    return verses, out


def _nodes(path):
    root = ET.parse(path).getroot()
    out = []
    for node in root.iter("Node"):
        if node.find("Node") is not None:
            continue
        c = node.find("c")
        ms = c.findall("m") if c is not None else ([node.find("m")] if node.find("m") is not None else [])
        for m in ms:
            out.append((m.get(XID), node.get("morphId"), m.text or ""))
    return out


def read_sources():
    ctx = mp.get_context("fork")
    with ctx.Pool(7) as pool:
        heb = pool.map(_lowfat, sorted(glob.glob(os.path.join(HEB_LOWFAT, "*-lowfat.xml"))), chunksize=4)
        grc = pool.map(_lowfat, sorted(glob.glob(os.path.join(GRC_LOWFAT, "*.xml"))), chunksize=2)
        nodes = pool.map(_nodes, sorted(glob.glob(os.path.join(HEB_NODES, "*.xml"))), chunksize=4)
    return heb, grc, [x for f in nodes for x in f]


def verse_key(ref):
    book, cv = ref.split(" ", 1)
    cv = cv.split("!")[0]
    c, v = cv.split(":")
    return book, int(c), int(v)


def ubs_table():
    senses, domains = C.defaultdict(set), C.defaultdict(set)
    with open(UBS, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            pid = ("o" if r["lang"] == "hbo" else "n") + r["key"]
            senses[pid].add(r["sense"])
            domains[pid].update(r["domains"].replace(";", " ").split())   # UBS's ";" between domains (SPEC 4.2: space)
    return senses, domains


# ---- stage 02 -------------------------------------------------------------------------------------------------

def load(build, lang):
    d = os.path.join(build, lang)
    W = pq.read_table(os.path.join(d, "words.parquet"))
    P = pq.read_table(os.path.join(d, "pieces.parquet"))
    with open(os.path.join(d, "lexemes.tsv"), encoding="utf-8", newline="") as fh:
        lines = fh.read().split("\n")
    header = lines[0].split("\t")
    lex = [dict(zip(header, ln.split("\t"))) for ln in lines[1:] if ln]
    with open(os.path.join(d, "categories.toml"), "rb") as fh:
        cats = tomllib.load(fh)
    return W, P, header, lex, cats


def stage02(R, build, src):
    heb, grc, nodes = src
    T = {lang: load(build, lang) for lang in ("hbo", "arc", "grc")}
    Wd = {lang: T[lang][0].to_pydict() for lang in T}
    Pd = {lang: T[lang][1].to_pydict() for lang in T}

    # -- words: columns, counts, keys
    for lang in T:
        R.check(f"{lang} words: columns are SPEC 4.1 in order", T[lang][0].column_names == WORD_COLS)
        R.check(f"{lang} pieces: columns are SPEC 4.2 in order",
                T[lang][1].column_names == ((PIECE_COLS_11 + (PIECE_13 if V13 else [])) if V11 else PIECE_COLS))
        if V11:
            for tab, cols in (("words", LATER_11["words"]), ("pieces", LATER_11["pieces"])):
                data = Wd[lang] if tab == "words" else Pd[lang]
                filled = sum(1 for c in cols for v in data[c] if v is not None)
                R.check(f"{lang} {tab}: columns of later stages present and null ({' '.join(cols)})", filled == 0,
                        filled)
        for tab, by in ({} if V11 else FILLED_BY).items():
            cols = [c for c, st in by.items() if st > UPTO]
            if not cols:
                continue
            data = Wd[lang] if tab == "words" else Pd[lang]
            filled = sum(1 for c in cols for v in data[c] if v is not None)
            R.check(f"{lang} {tab}: columns of later stages present and empty ({' '.join(cols)})", filled == 0, filled)
    want = {"hbo": 300689, "arc": 4828, "grc": 137779}
    for lang, n in want.items():
        R.check(f"{lang} words: {n:,} rows", len(Wd[lang]["t"]) == n, f"{len(Wd[lang]['t']):,}")
    tan_t = Wd["hbo"]["t"] + Wd["arc"]["t"]
    tan_id = Wd["hbo"]["id"] + Wd["arc"]["id"]
    R.check("hbo+arc words: 305,517 rows", len(tan_t) == 305517, f"{len(tan_t):,}")
    R.check("hbo+arc: every t once, and t runs 1..305,517 over both", sorted(tan_t) == list(range(1, 305518)),
            f"{len(set(tan_t)):,} distinct")
    R.check("hbo+arc: every id once", len(set(tan_id)) == len(tan_id), f"{len(set(tan_id)):,} distinct")
    R.check("grc: every t once, t runs 1..137,779", sorted(Wd["grc"]["t"]) == list(range(1, 137780)))
    R.check("grc: every id once", len(set(Wd["grc"]["id"])) == len(Wd["grc"]["id"]))

    # -- words against the source: ids, place, order, verses, text + after
    for name, files, langs in (("Tanakh", heb, ("hbo", "arc")), ("New Testament", grc, ("grc",))):
        src_words = {}   # word id -> (ref, [pieces in id order])
        order = []
        verses = []
        sent_of = {}
        s_no = 0
        ptexts = []
        for vs, sents in files:
            verses.extend(vs)
            for ws, ptext in sents:
                s_no += 1
                ptexts.append((s_no, ptext))
                ids = sorted({(w[0][:12] if name == "Tanakh" else w[0]) for w in ws})
                order.extend(ids)
                for w in ws:
                    k = w[0][:12] if name == "Tanakh" else w[0]
                    src_words.setdefault(k, [w[2], []])[1].append(w)
                    sent_of[k] = s_no
        rows = {}
        for lang in langs:
            for i in range(len(Wd[lang]["t"])):
                rows[Wd[lang]["id"][i]] = {k: Wd[lang][k][i] for k in WORD_COLS[:9]} | {"lang": lang}
        R.check(f"{name}: the word ids equal the source's", set(rows) == set(src_words),
                f"{len(rows):,} vs {len(src_words):,}")
        bad_order = sum(1 for i, k in enumerate(order) if rows.get(k, {}).get("t") != i + 1)
        R.check(f"{name}: t is the text order (file, sentence, word id)", bad_order == 0, bad_order)
        bad_place = 0
        for k, (ref, ws) in src_words.items():
            r = rows.get(k)
            book, rest = ref.split(" ", 1)
            cv, wn = rest.split("!")
            c, v = cv.split(":")
            if r is None or (r["book"], r["chapter"], r["verse"], r["w"]) != (book, int(c), int(v), int(wn)):
                bad_place += 1
        R.check(f"{name}: book, chapter, verse, w equal the source's ref", bad_place == 0, bad_place)
        src_verses = {verse_key(v + "!0") for v in verses}
        have = {(r["book"], r["chapter"], r["verse"]) for r in rows.values()}
        R.check(f"{name}: every verse of the source present ({len(src_verses):,} verse milestones)",
                src_verses <= have, f"missing {len(src_verses - have)}")
        R.check(f"{name}: no word outside the source's verses", have <= src_verses, f"extra {len(have - src_verses)}")
        if name == "Tanakh":
            # D1: the sentence is the verse; one running number over hbo and arc
            bad = sum(1 for k, r in rows.items() if r["sentence"] != sent_of[k])
            R.check("Tanakh: sentence = the source's sentence number (D1: the verse), shared by hbo and arc",
                    bad == 0, bad)
            per = C.defaultdict(set)
            for r in rows.values():
                per[r["sentence"]].add((r["book"], r["chapter"], r["verse"]))
            R.check("Tanakh: every sentence is one verse", all(len(v) == 1 for v in per.values())
                    and len(per) == 23213, f"{len(per):,} sentences")
            # word language = language of its stem piece (checked below with pieces)
        else:
            bad = sum(1 for k, r in rows.items() if r["sentence"] != sent_of[k])
            R.check("New Testament: sentence = MACULA's sentence, numbered 1..8,011 in file order",
                    bad == 0 and len(set(r["sentence"] for r in rows.values())) == 8011, bad)
        # text + after against the sentence's own <p> line (an independent reading of the writing)
        by_s = C.defaultdict(list)
        for r in rows.values():
            by_s[r["sentence"]].append(r)
        mism = []
        for s, ptext in ptexts:
            rs = sorted(by_s[s], key=lambda r: r["t"])
            ours = "".join(r["text"] + r["after"] for r in rs)
            a = re.sub(r"\s+", "", U.normalize("NFC", ours))
            b = re.sub(r"\s+", "", U.normalize("NFC", re.sub(r"[A-Z0-9]+ \d+:\d+", "", ptext)))
            if a != b:
                mism.append(s)
        R.info(f"{name}: sentences whose words + after differ from the source's <p> line (spaces ignored, NFC)",
               f"{len(mism)}" + (f", first sentences {mism[:5]}" if mism else ""))

    # -- pieces
    want = {"tan": 469476, "grc": 137779}
    n_tan = len(Pd["hbo"]["t"]) + len(Pd["arc"]["t"])
    R.check("hbo+arc pieces: 469,476 rows", n_tan == want["tan"], f"{n_tan:,}")
    R.check("grc pieces: 137,779 rows", len(Pd["grc"]["t"]) == want["grc"], f"{len(Pd['grc']['t']):,}")
    src_pieces = {}
    for files in (heb, grc):
        for _, sents in files:
            for ws, _ in sents:
                for w in ws:
                    src_pieces[w[0]] = w
    node_text = {pid: text for pid, mid, text in nodes}
    hidden = {pid for pid, w in src_pieces.items() if pid[0] == "o" and not w[1]}
    for lang in ("hbo", "arc", "grc"):
        P, W = Pd[lang], Wd[lang]
        words_t = {t: i for i, t in enumerate(W["t"])}
        keys = list(zip(P["t"], P["n"]))
        R.check(f"{lang} pieces: (t, n) unique and every t a word", len(set(keys)) == len(keys)
                and all(t in words_t for t in P["t"]))
        byt = C.defaultdict(list)
        for i, (t, n) in enumerate(keys):
            byt[t].append((n, i))
        R.check(f"{lang} pieces: every word has pieces, n runs from 1", set(byt) == set(words_t) and all(
            sorted(n for n, _ in v) == list(range(1, len(v) + 1)) for v in byt.values()))
        spell_bad, stem_bad, order_bad, pid_bad, lang_bad = [], 0, 0, 0, 0
        for t, v in byt.items():
            v.sort()
            idx = [i for _, i in v]
            text = "".join(P["text"][i] for i in idx)
            if text != W["text"][words_t[t]]:
                spell_bad.append(t)
            kinds = [P["kind"][i] for i in idx]
            if kinds.count("stem") != 1:
                stem_bad += 1
            else:
                s = kinds.index("stem")
                if any(k != "prefix" for k in kinds[:s]) or any(k != "suffix" for k in kinds[s + 1:]):
                    order_bad += 1
            pids = [P["pid"][i] for i in idx]
            if pids != sorted(pids) or any(p not in src_pieces for p in pids):
                pid_bad += 1
            if lang != "grc":
                stem_pid = pids[kinds.index("stem")] if "stem" in kinds else None
                if stem_pid and {"H": "hbo", "A": "arc"}.get(src_pieces[stem_pid][3]) != lang:
                    lang_bad += 1
        R.check(f"{lang} pieces: the pieces of each word spell its text", not spell_bad, len(spell_bad))
        R.check(f"{lang} pieces: exactly one stem per word, prefixes before it, suffixes after",
                stem_bad == 0 and order_bad == 0, f"{stem_bad} / {order_bad}")
        R.check(f"{lang} pieces: pid is the source's piece key, in writing order", pid_bad == 0, pid_bad)
        tbad = sum(1 for i, pid in enumerate(P["pid"]) if src_pieces[pid][1] != P["text"][i])
        R.check(f"{lang} pieces: text is the source's w text", tbad == 0, tbad)
        if lang != "grc":
            R.check(f"{lang}: every word is in the language of its stem piece (D5)", lang_bad == 0, lang_bad)
            nb = sum(1 for i, pid in enumerate(P["pid"]) if U.normalize("NFC", node_text.get(pid, "\0"))
                     != U.normalize("NFC", P["text"][i]))
            R.check(f"{lang} pieces: text equals the node files' m text (under NFC)", nb == 0, nb)
            raw = sum(1 for i, pid in enumerate(P["pid"]) if node_text.get(pid) != P["text"][i])
            R.info(f"{lang} pieces whose lowfat text and node-file text differ in code points only (NFC order)", raw)
            # D5 recomputed
            d5bad = 0
            for t, v in byt.items():
                idx = [i for _, i in v]
                ws = [src_pieces[P["pid"][i]] for i in idx]
                st = None
                for j, w in enumerate(ws):
                    if w[4] == "suffix" or (w[5] == "definite article" and j == len(ws) - 1 and j > 0):
                        continue
                    st = j
                if st is None or P["kind"][idx[st]] != "stem":
                    d5bad += 1
            R.check(f"{lang} pieces: kind follows D5 recomputed from the source", d5bad == 0, d5bad)
            # after = after of the last piece
            abad = sum(1 for t, v in byt.items() if W["after"][words_t[t]] != src_pieces[P["pid"][v[-1][1]]][7])
            R.check(f"{lang} words: after is the source's after of the last piece", abad == 0, abad)
        else:
            R.check("grc pieces: one piece per word (n = 1), pid = word id", all(n == 1 for n in P["n"])
                    and all(P["pid"][i] == W["id"][words_t[t]] for i, t in enumerate(P["t"])))
            abad = sum(1 for i, pid in enumerate(W["id"]) if W["after"][i] != src_pieces[pid][7])
            R.check("grc words: after is the source's after", abad == 0, abad)

    # fused
    fused = [f for lang in ("hbo", "arc") for f in Pd[lang]["fused"] if f]
    R.check("fused: 6,435 distinct letterless article pids", len(fused) == 6435 and len(set(fused)) == 6435
            and set(fused) == hidden, f"{len(set(fused)):,}; letterless in source {len(hidden):,}")
    fbad = 0
    for lang in ("hbo", "arc"):
        P = Pd[lang]
        for i, f in enumerate(P["fused"]):
            if f and (P["class"][i] != "prep" or not f.startswith(P["pid"][i])):
                fbad += 1
    R.check("fused: always on the preposition piece just before the article", fbad == 0, fbad)
    R.check("grc fused: empty", all(f == "" for f in Pd["grc"]["fused"]))

    # lexemes
    for lang in ("hbo", "arc", "grc"):
        W, P, header, lex, cats = T[lang]
        R.check(f"{lang} lexemes.tsv: columns are SPEC 4.6", header == LEX_COLS)
        lk = [r["lexeme"] for r in lex]
        R.check(f"{lang} lexemes.tsv: keys unique and sorted", len(set(lk)) == len(lk) and lk == sorted(lk))
        Pp = Pd[lang]
        used = C.Counter(Pp["lexeme"])
        R.check(f"{lang}: every lexeme of pieces is in lexemes.tsv, and no other",
                set(used) == set(lk), f"{len(set(used) - set(lk))} missing, {len(set(lk) - set(used))} extra")
        cbad = sum(1 for r in lex if int(r["count"]) != used.get(r["lexeme"]))
        R.check(f"{lang} lexemes.tsv: count = pieces", cbad == 0, cbad)
        # recompute class, first, books, senses, strong (independent of the builder)
        first, books, clsc, sens = {}, C.defaultdict(set), C.defaultdict(C.Counter), C.defaultdict(C.Counter)
        wbook = dict(zip(Wd[lang]["t"], Wd[lang]["book"]))
        for i, k in enumerate(Pp["lexeme"]):
            place = (Pp["t"][i], Pp["n"][i])
            if k not in first or place < first[k]:
                first[k] = place
            books[k].add(wbook[Pp["t"][i]])
            clsc[k][Pp["class"][i]] += 1
            sens[k].update(Pp["sense"][i].split())
        bad = 0
        for r in lex:
            k = r["lexeme"]
            cls = min(clsc[k].items(), key=lambda x: (-x[1], x[0]))[0]
            ss = " ".join(f"{c}:{n}" for c, n in sorted(sens[k].items(), key=lambda x: (-x[1], x[0])))
            if (r["first"] != f"{first[k][0]}.{first[k][1]}" or int(r["books"]) != len(books[k])
                    or r["class"] != cls or r["senses"] != ss):
                bad += 1
            if lang != "grc" and not k.endswith(":" + r["strong"]):
                bad += 1
        R.check(f"{lang} lexemes.tsv: class, books, senses, first, strong recomputed", bad == 0, bad)
        spaced = sum(1 for k in lk if " " in k)
        R.info(f"{lang} lexeme keys holding a space (lemma written with a space)", spaced)
        nostrong = sum(1 for k in lk if lang != "grc" and k.endswith(":"))
        R.check(f"{lang}: every lexeme key has a Strong's value", nostrong == 0, nostrong)

    # marks and categories.toml
    for lang in ("hbo", "arc", "grc"):
        cats = T[lang][4].get("pieces", {})
        if V11:   # the piece categories; head_basis and rel are declared too (checked in stage 15)
            cats = {c: d for c, d in cats.items() if d.get("column") in ("marks", "class", "kind")}
        declared = {(c, v["code"]) for c, d in cats.items() for v in d["values"]}
        dcount = {(c, v["code"]): v["count"] for c, d in cats.items() for v in d["values"]}
        P = Pd[lang]
        use = C.Counter()
        jbad = 0
        for m in P["marks"]:
            obj = json.loads(m)
            if json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) != m:
                jbad += 1
            if not set(obj) <= MARK_CATS[lang]:
                jbad += 1
            use.update(obj.items())
        use.update(("class", c) for c in P["class"])
        use.update(("kind", k) for k in P["kind"])
        R.check(f"{lang} marks: JSON with keys sorted, no spaces, only the categories of 4.10", jbad == 0, jbad)
        undeclared = set(use) - declared
        R.check(f"{lang}: every category and code in marks, class, kind is declared in categories.toml",
                not undeclared, len(undeclared))
        R.check(f"{lang} categories.toml: counts equal the pieces", all(dcount.get(k) == v for k, v in use.items())
                and set(dcount) == set(use))
        codes_ok = all(re.fullmatch(r"[a-z0-9]+(_[a-z0-9]+)*", c) for _, c in declared)
        vals = C.defaultdict(set)
        for c, d in cats.items():
            for v in d["values"]:
                vals[(c, v["code"])].add(v["value"])
        R.check(f"{lang} categories.toml: codes are code-shaped, one source value per code",
                codes_ok and all(len(v) == 1 for v in vals.values()))
        # marks against the source attribute values (via the declared value of the code)
        c0 = [(c, v["value"], v["code"]) for c, d in cats.items() for v in d["values"]
              if v["rule"] == "C0" and c in ("gender", "number", "person", "state", "case", "tense", "voice",
                                             "mood", "degree")]
        R.info(f"{lang}: closed-category values coded by C0", c0 or "none")

    # sense and domain against UBS
    senses, domains = ubs_table()
    for lang in ("hbo", "arc", "grc"):
        P = Pd[lang]
        bad = sum(1 for i, pid in enumerate(P["pid"]) if P["sense"][i] != " ".join(sorted(senses.get(pid, ())))
                  or P["domain"][i] != " ".join(sorted(domains.get(pid, ()))))
        R.check(f"{lang} pieces: sense and domain are UBS's for the piece", bad == 0, bad)
        R.info(f"{lang} pieces with two or more UBS senses (written space-separated)",
               sum(1 for s in P["sense"] if " " in s))
    allp = {pid for lang in Pd for pid in Pd[lang]["pid"]}
    R.info("UBS keys that name no piece of the tables", sum(1 for k in senses if k not in allp))

    # -- references (SPEC 10): through the morphId map
    mp_t = pq.read_table(os.path.join(build, "cache", "morphid.parquet")).to_pydict()
    cache_map = set(zip(mp_t["morphid"], mp_t["pid"]))
    own_map = {(mid, pid) for pid, mid, _ in nodes}
    R.check("cache/morphid.parquet equals the node files' morphId -> pid map", cache_map == own_map,
            f"{len(cache_map):,} rows")
    bym = C.defaultdict(set)
    for mid, pid in own_map:
        bym[mid].add(pid)
    allpieces = {pid for pid in src_pieces if pid[0] == "o"}
    res = C.Counter()
    for pid, w in src_pieces.items():
        if pid[0] != "o":
            continue
        for a, val in zip(("frame", "participantref", "subjref"), w[8:11]):
            for tok in re.findall(r"\d{12}", val or ""):
                res["targets"] += 1
                hit = bym.get(tok)
                if not hit:
                    res["unresolved"] += 1
                elif len(hit) > 1:
                    res["name a compound (several pieces)"] += 1
                if hit and not (hit - hidden):
                    res["name a letterless article"] += 1
                o = "o" + tok
                if o not in allpieces:
                    res["as xml:id: not at all"] += 1
                elif not hit or o not in hit:
                    res["as xml:id: another piece"] += 1
                elif len(hit) > 1:
                    res["as xml:id: one piece of the compound the morphId names"] += 1
    R.check("references: every Hebrew target (frame, participantref, subjref) resolves through morphId",
            res["unresolved"] == 0, f"{res['targets']:,} targets, unresolved {res['unresolved']}")
    if V11:
        empty = C.Counter()
        places, slots = [], []
        n_colon = 0
        for pid, w in src_pieces.items():
            if pid[0] == "o" and w[8]:
                n_colon += w[8].count(":;")
                for tok in w[8].split():
                    lab, _, ids = tok.partition(":")
                    if not [x for x in ids.split(";") if x]:
                        empty[lab] += 1
                        places.append(f"{pid} {tok}")
                    elif ids.startswith(";"):
                        slots.append(f"{pid} {tok}")
        # SPEC 10 says 1,292 (`A0:;` 1,289, `A1:;` 3): the count of the string `:;`. One of them (ISA 56:12) is an
        # empty slot before a target, so 1,291 entries have no target
        R.check("references: frame entries with no target: 1,291 (A0 1,288, A1 3), and 1 entry with an empty slot "
                "before its target: SPEC 10's 1,292 `:;`",
                sum(empty.values()) == 1291 and empty["A0"] == 1288 and empty["A1"] == 3 and len(slots) == 1
                and n_colon == 1292, f"{sum(empty.values()):,} {dict(empty)}; slots {slots}; `:;` {n_colon:,}")
        R.check("references: targets that name an id (217,768) + the 1,292 empty slots = 219,060",
                res["targets"] + n_colon == 219060, f"{res['targets']:,} + {n_colon:,}")
        STASH["empty frame places"] = places
        R.info("references: frame entries with no target, first places", " ".join(places[:6]))
    for k in ("as xml:id: another piece", "as xml:id: not at all", "name a compound (several pieces)",
              "as xml:id: one piece of the compound the morphId names", "name a letterless article"):
        R.info(f"references {k}", res[k])


# ---- stage 03: heads (D2p, D2w, D3, D4) --------------------------------------------------------------------------

UD_RELATIONS = {"acl", "advcl", "advmod", "amod", "appos", "aux", "case", "cc", "ccomp", "clf", "compound", "conj",
                "cop", "csubj", "dep", "det", "discourse", "dislocated", "expl", "fixed", "flat", "goeswith", "iobj",
                "list", "mark", "nmod", "nsubj", "nummod", "obj", "obl", "orphan", "parataxis", "punct",
                "reparandum", "root", "vocative", "xcomp"}


def _c0(v):
    return re.sub(r"[^a-z0-9]+", "_", v.lower()).strip("_")


def _role_ok(r):
    return r is not None and r != "" and not r.startswith("err_")


def _heads_file(pair):
    """One node file and its lowfat file -> per sentence (edges, letterless pids, all pids), and counts. An edge is
    (dependent pid, head pid or None, basis, label). Recursive over the XML elements (the builder works on pickled
    lists, iteratively)."""
    node_path, low_path = pair
    sys.setrecursionlimit(50000)
    greek = "greek" in node_path
    nsents = list(ET.parse(node_path).getroot().iter("Sentence"))
    lsents = list(ET.parse(low_path).getroot().iter("sentence"))
    if len(lsents) != len(nsents):
        raise ValueError(f"{node_path}: sentences differ")
    cnt = C.Counter()
    out = []
    for ns, ls in zip(nsents, lsents):
        outer = {}   # D3: the outermost lowfat element with exactly these pieces -> its role
        for el in ls.iter():
            if el.tag == "w":
                key = frozenset([el.get(XID)])
            elif el.tag in ("wg", "c"):
                key = frozenset(w.get(XID) for w in el.iter("w"))
            else:
                continue
            if key not in outer:
                outer[key] = el.get("role")
        edges = []
        hidden = set()

        def fallback(node_el, place, compound):
            if compound:
                return f"c:{place}"
            rule = node_el.get("Rule")
            return f"run:{place}" if rule is None else f"{rule}:{place}"

        def label(node_el, place, xset, compound):
            r = outer.get(xset)
            if _role_ok(r):
                return _c0(r)
            return fallback(node_el, place, compound)

        def visit(el, top=False):
            """-> (head pid, pids under el)"""
            c = el.find("c")
            if c is not None:
                ms = [m.get(XID) for m in c.findall("m")]
                cnt["D2p(b) compounds"] += 1
                for j, m in enumerate(ms[1:], 1):
                    edges.append((m, ms[0], "compound", label(el, j, frozenset([m]), True),
                                  fallback(el, j, True), True))
                return ms[0], ms
            kids = [k for k in el if k.tag == "Node"]
            if not kids:
                if greek:
                    pid = el.get(XID)
                else:
                    m = el.find("m")
                    pid = m.get(XID)
                    if not (m.text or ""):
                        hidden.add(pid)
                return pid, [pid]
            res = [visit(k) for k in kids]
            if len(kids) == 1:
                return res[0]
            pids = [p for _, ps in res for p in ps]
            hd = el.get("Head")
            if V11 and not greek and top and el.get("Cat") == "S" and el.get("Rule") is None:
                # SPEC 1.1 D2p(d): the first child of Cat CL, else the first child
                kc = [k.get("Cat") for k in kids]
                h, basis = (kc.index("CL") if "CL" in kc else 0), "sentence"
                cnt["D2p(d) branching sentence nodes"] += 1
            elif hd is not None:
                h, basis = int(hd), "index"
            else:
                conj = [j for j, k in enumerate(kids) if k.get("Cat") in ("conj", "cj", "cjp")]
                if len(kids) == 2 and len(conj) == 1:
                    h, basis = 1 - conj[0], "conj"
                    cnt["D2p(a) nodes"] += 1
                else:
                    h, basis = None, "none"
                    cnt["D2p(c) nodes"] += 1
            for j, (hp, ps) in enumerate(res):
                if j == h or (h is None and j == 0):
                    continue
                edges.append((hp, res[h][0] if h is not None else None, basis,
                              label(el, j, frozenset(ps), False), fallback(el, j, False), ps == [hp]))
            return (res[h][0] if h is not None else res[0][0]), pids

        tops = [k for t in ns.findall("./Trees/Tree") for k in t if k.tag == "Node"]
        cnt[f"sentences with {len(tops)} top node(s)"] += 1
        if tops[0].get("Cat") == "S" and tops[0].get("Rule") is None:
            cnt["sentence nodes (top node, Cat S, no Rule)"] += 1
        root, allp = visit(tops[0], top=True)
        edges.append((root, None, "root", "root", "root", False))
        out.append((edges, hidden, allp))
    return out, cnt


def heads_from_sources(lang):
    if lang == "grc":
        nf = sorted(glob.glob(os.path.join(HERE, "data/macula-nodes/greek/Nestle1904/nodes/*.xml")))
        lf = sorted(glob.glob(os.path.join(GRC_LOWFAT, "*.xml")))
    else:
        nf = sorted(glob.glob(os.path.join(HEB_NODES, "*.xml")))
        lf = sorted(glob.glob(os.path.join(HEB_LOWFAT, "*-lowfat.xml")))
    if [os.path.basename(f).replace("-lowfat", "") for f in lf] != [os.path.basename(f) for f in nf]:
        raise ValueError("node and lowfat files do not pair by name")
    with mp.get_context("fork").Pool(7) as pool:
        res = pool.map(_heads_file, list(zip(nf, lf)), chunksize=4)
    cnt = C.Counter()
    sents = []
    for out, c in res:
        cnt.update(c)
        sents.extend(out)
    return sents, cnt


def _no_loop(heads, zero):
    """Number of start points from which following `heads` does not reach `zero`."""
    state, loops = {}, 0
    for k in heads:
        path, x = [], k
        while x != zero and x not in state:
            state[x] = 1
            path.append(x)
            x = heads[x]
            if x in state and state[x] == 1:
                loops += 1
                break
        for y in path:
            state[y] = 2
    return loops


def stage03(R, build, src):
    tabs = {}
    for lang in ("hbo", "arc", "grc"):
        d = os.path.join(build, lang)
        tabs[lang] = (pq.read_table(os.path.join(d, "words.parquet")).to_pydict(),
                      pq.read_table(os.path.join(d, "pieces.parquet")).to_pydict())
    for group in (("hbo", "arc"), ("grc",)):
        gname = "+".join(group)
        want = {"hbo+arc": 23213, "grc": 8011}[gname]
        sents, cnt = heads_from_sources(group[0])
        exp, hidden = {}, set()
        oneword = STASH.get("grc one-word role_wrapped", {}) if V11 and gname == "grc" else {}
        relab = C.Counter()
        for edges, hid, allp in sents:
            hidden |= hid
            for dep, head, basis, lab, fb, single in edges:
                if dep in exp:
                    raise ValueError(f"two edges from {dep}")
                if dep in oneword and basis != "root" and single:
                    # SPEC 1.1 D3: a Greek one-word clause's edge: its role_wrapped where filled, else <rule>:<place>
                    new = oneword[dep] or fb
                    relab["changed" if new != lab else "same"] += 1
                    relab[f"from {lab if lab in ROLE_SET else 'other'}"] += new != lab
                    lab = new
                exp[dep] = (head, basis, lab)
        if V11 and gname == "grc":
            if not oneword:
                R.check("grc: the one-word clauses of stage 04's recount are at hand for D3", False)
            R.info("grc D3 (1.1): one-word clause edges relabelled by the recount (changed / same; changed from)",
                   dict(relab))
        through = 0
        for p, (h, b, lab) in list(exp.items()):
            if h in hidden:
                while h in hidden:
                    h = exp[h][0]
                through += 1
                exp[p] = (h, b, lab)
        place, pidx = {}, {}
        for lang in group:
            P = tabs[lang][1]
            for i, pid in enumerate(P["pid"]):
                place[pid] = (P["t"][i], P["n"][i])
                pidx[pid] = (lang, i)
        R.check(f"{gname}: every node-file leaf is a piece row or a letterless article",
                set(exp) == set(place) | hidden and not (set(place) & hidden),
                f"{len(place):,} rows + {len(hidden):,} letterless")
        badlab = sum(1 for lang in group for r in tabs[lang][1]["rel"] if not r or r.startswith("err"))
        R.check(f"{gname} pieces: no label is empty or a converter error string", badlab == 0, badlab)
        bad_head = bad_basis = bad_rel = 0
        for pid, (lang, i) in pidx.items():
            h, b, lab = exp[pid]
            P = tabs[lang][1]
            bad_head += (P["head_t"][i], P["head_n"][i]) != ((0, 0) if h is None else place[h])
            bad_basis += P["head_basis"][i] != b
            bad_rel += P["rel"][i] != lab
        R.check(f"{gname} pieces: head_t, head_n equal D2p recomputed from the node files", bad_head == 0, bad_head)
        R.check(f"{gname} pieces: head_basis equals D2p recomputed", bad_basis == 0, bad_basis)
        R.check(f"{gname} pieces: rel equals D3 recomputed from the node and lowfat files", bad_rel == 0, bad_rel)
        allowed = {"index", "conj", "compound", "none", "root"} | ({"sentence"} if V11 else set())
        badv = sum(1 for lang in group for b in tabs[lang][1]["head_basis"] if b not in allowed)
        R.check(f"{gname} pieces: head_basis is one of {' '.join(sorted(allowed))}", badv == 0, badv)
        head_of = {}
        for lang in group:
            P = tabs[lang][1]
            for i in range(len(P["t"])):
                head_of[(P["t"][i], P["n"][i])] = (P["head_t"][i], P["head_n"][i])
        missing = sum(1 for v in head_of.values() if v != (0, 0) and v not in head_of)
        R.check(f"{gname} pieces: every head names a piece or is 0 (root)", missing == 0, missing)
        loops = _no_loop(head_of, (0, 0))
        R.check(f"{gname} pieces: following heads from any piece ends at a root (no loop)", loops == 0, loops)
        sent_t = {}
        for lang in group:
            W = tabs[lang][0]
            sent_t.update(zip(W["t"], W["sentence"]))
        none_n = sum(1 for lang in group for b in tabs[lang][1]["head_basis"] if b == "none")
        roots = C.Counter(sent_t[k[0]] for k, v in head_of.items() if v == (0, 0))
        n_root_rows = sum(1 for lang in group for b in tabs[lang][1]["head_basis"] if b == "root")
        R.check(f"{gname} pieces: one root per sentence ({want:,} sentences) plus the D2p(c) cases ({none_n})",
                len(set(sent_t.values())) == want and len(roots) == want and n_root_rows == want
                and sum(roots.values()) == want + none_n,
                f"{sum(roots.values()):,} heads 0 in {len(roots):,} sentences")
        badroot = 0
        for lang in group:
            P = tabs[lang][1]
            for i in range(len(P["t"])):
                isroot = P["head_basis"][i] == "root"
                if isroot != (P["rel"][i] == "root") or (isroot and P["head_t"][i] != 0) \
                        or (P["head_t"][i] == 0 and P["head_basis"][i] not in ("root", "none")):
                    badroot += 1
        R.check(f"{gname} pieces: head 0 exactly on rows with head_basis root (rel root) or none", badroot == 0,
                badroot)
        cross = sum(1 for k, v in head_of.items() if v != (0, 0) and sent_t[v[0]] != sent_t[k[0]])
        R.check(f"{gname} pieces: every head lies in the same sentence", cross == 0, cross)
        split = sum(1 for _, _, allp in sents if len({sent_t[place[p][0]] for p in allp if p in place}) != 1)
        R.check(f"{gname}: every node-file sentence is one sentence of the tables", split == 0, split)
        if gname == "grc":
            R.check("grc: D2p(a) 9,693 nodes (one conjunction and one other part, no Head)",
                    cnt["D2p(a) nodes"] == 9693, cnt["D2p(a) nodes"])
            nb = sum(1 for b in tabs["grc"][1]["head_basis"] if b == "conj")
            R.check("grc pieces: head_basis conj on 9,693 pieces", nb == 9693, nb)
        else:
            R.check("hbo+arc: D2p(b) 832 compounds", cnt["D2p(b) compounds"] == 832, cnt["D2p(b) compounds"])
            nb = sum(1 for lang in group for b in tabs[lang][1]["head_basis"] if b == "compound")
            R.check("hbo+arc pieces: head_basis compound on 1,706 - 832 = 874 pieces", nb == 874, nb)
            R.check("hbo+arc: D2p(a) does not arise", cnt["D2p(a) nodes"] == 0, cnt["D2p(a) nodes"])
            if V11:
                R.check("hbo+arc: D2p(d) 23,213 sentence nodes (the top node of every sentence: Cat S, no Rule)",
                        cnt["sentence nodes (top node, Cat S, no Rule)"] == 23213,
                        f"{cnt['sentence nodes (top node, Cat S, no Rule)']:,}; branching "
                        f"{cnt['D2p(d) branching sentence nodes']:,}")
                nb = sum(1 for lang in group for b in tabs[lang][1]["head_basis"] if b == "sentence")
                R.info("hbo+arc pieces with head_basis sentence", f"{nb:,}")
        R.check(f"{gname}: D2p(c) nodes (expected 0)", cnt["D2p(c) nodes"] == 0, cnt["D2p(c) nodes"])
        R.check(f"{gname}: one top node per sentence",
                cnt["sentences with 1 top node(s)"] == want, cnt["sentences with 1 top node(s)"])
        if gname == "hbo+arc":
            fused = {f for lang in group for f in tabs[lang][1]["fused"] if f}
            R.check("hbo+arc: the letterless articles of the node files are the 6,435 fused pids (edges not "
                    "carried)", hidden == fused and len(hidden) == 6435, f"{len(hidden):,}")
            R.info("hbo+arc pieces whose head would be a letterless article (took its head; expected 0)", through)
        # D2w
        for lang in group:
            W, P = tabs[lang]
            byt = C.defaultdict(list)
            for i, t in enumerate(P["t"]):
                byt[t].append(i)
            ddepth = {}

            def dep_of(k):
                d, x = 0, k
                while head_of[x] != (0, 0):
                    x = head_of[x]
                    d += 1
                return d
            bad, notcarried, ties, nonstem = 0, 0, 0, C.Counter()
            moved = 0
            widx = {t: j for j, t in enumerate(W["t"])}
            for t, idx in byt.items():
                idx.sort(key=lambda i: P["n"][i])
                if V11:   # SPEC 1.1 D2w: a cj prefix is left out where another piece's head lies outside the word
                    full = list(idx)
                    idx = [i for i in idx if not (P["kind"][i] == "prefix" and P["class"][i] == "cj" and any(
                        j != i and P["head_t"][j] != t for j in full))]
                    moved += len(idx) != len(full)
                ds = [dep_of((t, P["n"][i])) for i in idx]
                md = min(ds)
                tied = [i for i, d in zip(idx, ds) if d == md]
                ties += len(tied) > 1
                st = [i for i in tied if P["kind"][i] == "stem"]
                top = st[0] if st else tied[0]
                if P["kind"][top] != "stem":
                    nonstem[P["class"][top]] += 1
                notcarried += sum(1 for i in (full if V11 else idx) if i != top and P["head_t"][i] != t)
                j = widx[t]
                if (W["head"][j], W["head_basis"][j], W["rel"][j]) != (P["head_t"][top], P["head_basis"][top],
                                                                       P["rel"][top]):
                    bad += 1
            R.check(f"{lang} words: head, head_basis, rel equal D2w (top piece) recomputed", bad == 0, bad)
            R.info(f"{lang} words with a tie for the top piece", ties)
            if V11:
                R.info(f"{lang} words with a cj prefix left out of the top-piece choice (D2w, 1.1)", f"{moved:,}")
            R.info(f"{lang} words whose top piece is not the stem, by class",
                   f"{sum(nonstem.values())} {dict(nonstem.most_common())}")
            R.info(f"{lang} piece edges that leave the word and are not carried at the word level", notcarried)
        whead = {}
        for lang in group:
            W = tabs[lang][0]
            whead.update(zip(W["t"], W["head"]))
        miss = sum(1 for v in whead.values() if v != 0 and v not in whead)
        R.check(f"{gname} words: every head names a word or is 0", miss == 0, miss)
        selfh = sum(1 for t, v in whead.items() if v == t)
        R.check(f"{gname} words: no word is its own head", selfh == 0, selfh)
        loops = _no_loop(whead, 0)
        R.check(f"{gname} words: following heads ends at a root (no loop)", loops == 0, loops)
        wroots = C.Counter(sent_t[t] for t, v in whead.items() if v == 0)
        R.check(f"{gname} words: one root per sentence ({want:,}) plus the D2p(c) cases ({none_n})",
                len(wroots) == want and sum(wroots.values()) == want + none_n,
                f"{sum(wroots.values()):,} roots in {len(wroots):,} sentences")
        wcross = sum(1 for t, v in whead.items() if v != 0 and sent_t[v] != sent_t[t])
        R.check(f"{gname} words: every head lies in the same sentence", wcross == 0, wcross)
        if gname == "hbo+arc":
            xl = C.Counter()
            lang_t = {t: lang for lang in group for t in tabs[lang][0]["t"]}
            for t, v in whead.items():
                if v and lang_t[v] != lang_t[t]:
                    xl[f"{lang_t[t]}->{lang_t[v]}"] += 1
            R.info("hbo+arc word heads in the other Tanakh table (GEN 31:47, DAN 2:4)", dict(xl) or 0)
        # D4 (in 1.1 built by stage 20)
        for lang in (() if V11 else group):
            W = tabs[lang][0]
            with open(os.path.join(build, lang, "relmap.tsv"), encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh, delimiter="\t"))
            R.check(f"{lang} relmap.tsv: columns label, shared, count",
                    bool(rows) and list(rows[0].keys()) == ["label", "shared", "count"])
            use = C.Counter(W["rel"])
            rmap = {r["label"]: r for r in rows}
            R.check(f"{lang} relmap.tsv: one row per word label, count = words with it",
                    set(rmap) == set(use) and all(int(rmap[k]["count"]) == v for k, v in use.items()), len(rows))
            n = len(W["rel"])
            unmapped = [k for k, v in use.items() if v / n >= 0.001 and rmap[k]["shared"] == "none"]
            R.check(f"{lang} relmap.tsv: every label covering at least 0.1% of the words is mapped", not unmapped,
                    len(unmapped))
            bad = sum(1 for r, s in zip(W["rel"], W["rel_shared"]) if rmap[r]["shared"] != s)
            R.check(f"{lang} words: rel_shared = rel read through relmap.tsv", bad == 0, bad)
            badud = sorted({r["shared"] for r in rows} - UD_RELATIONS - {"none"})
            R.check(f"{lang} relmap.tsv: every shared name is a Universal Dependencies relation or none",
                    not badud, " ".join(badud))
            nn = sum(1 for s in W["rel_shared"] if s == "none")
            R.info(f"{lang} words with rel_shared none", f"{nn:,} ({nn / n:.2%}); labels {len(rows)}, "
                   f"mapped {sum(1 for r in rows if r['shared'] != 'none')}")
            R.info(f"{lang} words by rel_shared", dict(C.Counter(W["rel_shared"]).most_common()))


# ---- stage 04: clauses and constituents (SPEC 3, 4.1 clause, 4.3, 4.4, D8) ------------------------------------

CLAUSE_COLS = ["clause", "book", "chapter", "verse", "first", "last", "gaps", "words", "parent", "depth", "via",
               "rule", "pattern", "role", "role_wrapped", "pred", "pred_kind", "marks", "shared", "quote", "speaker",
               "addressee", "line"]
CLAUSE_LATER = {"marks": "05", "shared": "09", "quote": "06", "speaker": "06", "addressee": "06", "line": "05"}
CONST_COLS = ["clause", "ord", "role", "head", "first", "last", "class", "frame_role", "sem_role", "prep"]
CONST_LATER = {"sem_role": "05"}
ROLE_SET = {"v", "s", "o", "o2", "io", "p", "vc", "aux", "pp", "adv"}   # SPEC 4.4
CLAUSE_COLS_11 = CLAUSE_COLS[:-1] + ["speech_basis", "line", "quote_model", "speaker_model", "addressee_model",
                                     "subject_model"]
CONST_COLS_11 = CONST_COLS[:-1] + ["sem_role_basis", "prep"]


def _clauses_file(path):
    """One lowfat file -> per sentence: (clauses, frames). A clause: (tag, rule, role, pids, parent clause index or
    -1, depth, via (tag, class, type, role) or None, slot index of its branch among the parent's children, number of
    the parent's children, direct children [(tag, role, class, type, rule, pids)]). Recursive over the XML."""
    sys.setrecursionlimit(50000)
    greek = "lowfat-src-grc" in path
    root = ET.parse(path).getroot()
    out = []
    for s in root.iter("sentence"):
        cls, frames, nd = [], {}, C.Counter()
        anc = []        # (element, clause index or None) of the wg/w/c ancestors, outermost first

        def kids_of(el):
            return [k for k in el if k.tag in ("wg", "w", "c")]

        def is_cl(el):
            return (el.tag == "wg" and el.get("class") == "cl") or \
                (greek and el.tag == "w" and el.get("rule") is not None)

        def pids_of(el):
            return [el.get(XID)] if el.tag == "w" else [w.get(XID) for w in el.iter("w")]

        def visit(el):
            if el.tag not in ("wg", "w", "c"):
                for k in el:
                    visit(k)
                return
            if el.tag == "w" and el.get("frame"):
                frames[el.get(XID)] = el.get("frame")
            if _role_ok(el.get("role")) and not (anc and anc[-1][1] is not None):
                nd[f"{el.tag} {el.get('role')}"] += 1
            ci = None
            if is_cl(el):
                up = [j for j, (e, c) in enumerate(anc) if c is not None]
                parent = anc[up[-1]][1] if up else -1
                via, slot, npk = None, -1, 0
                if up:
                    pel = anc[up[-1]][0]
                    branch = anc[up[-1] + 1][0] if up[-1] + 1 < len(anc) else el
                    if branch is not el:
                        via = (branch.tag, branch.get("class"), branch.get("type"), branch.get("role"),
                               pids_of(branch))
                    pk = kids_of(pel)
                    slot = next(i for i, k in enumerate(pk) if k is branch)
                    npk = len(pk)
                rule = el.get("rule") if el.get("rule") is not None else el.get("Rule")
                kids = [(k.tag, k.get("role"), k.get("class"), k.get("type"),
                         k.get("rule") if k.get("rule") is not None else k.get("Rule"), pids_of(k))
                        for k in kids_of(el)]
                ci = len(cls)
                cls.append((el.tag, rule or "", el.get("role"), pids_of(el), parent, len(up), via, slot, npk, kids))
            anc.append((el, ci))
            for k in el:
                visit(k)
            anc.pop()

        for k in s:
            visit(k)
        out.append((cls, frames, nd))
    return out


def _vc0(v):
    return _c0(v)


def stage04(R, build, src):
    heb, grc, nodes = src
    bym = C.defaultdict(list)
    for pid, mid, text in nodes:
        bym[mid].append(pid)
    tabs = {}
    for lang in ("hbo", "arc", "grc"):
        d = os.path.join(build, lang)
        ct = pq.read_table(os.path.join(d, "clauses.parquet"))
        kt = pq.read_table(os.path.join(d, "constituents.parquet"))
        R.check(f"{lang} clauses: columns are SPEC 4.3 in order",
                ct.column_names == ((CLAUSE_COLS_11 + (CLAUSE_13 if V13 else [])) if V11 else CLAUSE_COLS))
        R.check(f"{lang} constituents: columns are SPEC 4.4 in order",
                kt.column_names == ((CONST_COLS_11 + (CONST_13 if V13 else [])) if V11 else CONST_COLS))
        tabs[lang] = (pq.read_table(os.path.join(d, "words.parquet")).to_pydict(),
                      pq.read_table(os.path.join(d, "pieces.parquet")).to_pydict(), ct.to_pydict(), kt.to_pydict())
        for name, later, data in (("clauses", CLAUSE_LATER, tabs[lang][2]), ("constituents", CONST_LATER,
                                                                           tabs[lang][3])):
            cols = LATER_11[name] if V11 else [c for c, st in later.items() if st > UPTO]
            bad = sum(1 for c in cols for v in data[c] if v is not None)
            R.check(f"{lang} {name}: columns of later stages are null ({' '.join(cols)})", bad == 0, bad)
    for group in (("hbo", "arc"), ("grc",)):
        greek = group == ("grc",)
        gname = "+".join(group)
        files = sorted(glob.glob(os.path.join(GRC_LOWFAT, "*.xml"))) if greek else \
            sorted(glob.glob(os.path.join(HEB_LOWFAT, "*-lowfat.xml")))
        with mp.get_context("fork").Pool(7) as pool:
            res = pool.map(_clauses_file, files, chunksize=2)
        sents = [s for f in res for s in f]
        place, lang_of = {}, {}
        for lang in group:
            P = tabs[lang][1]
            for i, pid in enumerate(P["pid"]):
                place[pid] = (P["t"][i], P["n"][i])
                lang_of[pid] = lang
        rank = {p: r for r, p in enumerate(sorted(place, key=place.get))}
        head = {}
        pcls, plex, stem = {}, {}, {}
        for lang in group:
            P = tabs[lang][1]
            for i, pid in enumerate(P["pid"]):
                head[place[pid]] = (P["head_t"][i], P["head_n"][i])
                pcls[pid], plex[pid] = P["class"][i], P["lexeme"][i]
                if P["kind"][i] == "stem":
                    stem[P["t"][i]] = pid
        wpos, wsent, wclass, whead = {}, {}, {}, {}
        for lang in group:
            W = tabs[lang][0]
            for j, t in enumerate(W["t"]):
                wpos[t] = (lang, j)
                wsent[t] = W["sentence"][j]
                whead[t] = W["head"][j]
        # the clauses of the source, with every expected value
        allc = []
        for si, (cls, frames, _nd) in enumerate(sents):
            base = len(allc)
            for c in cls:
                tag, rule, role, pids, parent, depth, via, slot, npk, kids = c
                rows = sorted((p for p in pids if p in place), key=rank.get)
                allc.append(dict(tag=tag, rule=rule, role=role, rows=rows, parent=base + parent if parent >= 0
                                 else None, depth=depth, via=via, slot=slot, npk=npk, kids=kids, frames=frames))
        n_src = len(allc)
        n_wg = sum(1 for c in allc if c["tag"] == "wg")
        n_w = n_src - n_wg
        if greek:
            R.check("grc clauses in the source: 48,207 = 43,786 groups + 4,421 one-word clauses",
                    (n_src, n_wg, n_w) == (48207, 43786, 4421), f"{n_src:,} = {n_wg:,} + {n_w:,}")
        else:
            lc = C.Counter(frozenset(lang_of[p] for p in c["rows"]) for c in allc)
            R.check("hbo+arc clauses in the source: 102,124 = Hebrew 100,543 + Aramaic 1,580 + 1 mixed",
                    n_src == 102124 and lc[frozenset(["hbo"])] == 100543 and lc[frozenset(["arc"])] == 1580
                    and lc[frozenset(["hbo", "arc"])] == 1,
                    f"{n_src:,}: {lc[frozenset(['hbo'])]:,} + {lc[frozenset(['arc'])]:,} + "
                    f"{lc[frozenset(['hbo', 'arc'])]}")
        # keys
        same = C.defaultdict(list)
        for i, c in enumerate(allc):
            same[(c["rows"][0], len(c["rows"]))].append(i)
        for (pid, n), ix in same.items():
            ix.sort(key=lambda i: allc[i]["depth"])
            for k, i in enumerate(ix, 1):
                allc[i]["key"] = f"cl:{pid}:{n}" + (f":{k}" if k > 1 else "")
        for c in allc:
            c["lang"] = "grc" if greek else (
                "arc" if 2 * sum(1 for p in c["rows"] if lang_of[p] == "arc") > len(c["rows"]) else "hbo")
        tabkeys = [k for lang in group for k in tabs[lang][2]["clause"]]
        R.check(f"{gname} clauses: every key unique", len(set(tabkeys)) == len(tabkeys), f"{len(tabkeys):,} rows")
        exp_keys = {c["key"]: c for c in allc}
        R.check(f"{gname} clauses: the rows are the source's clauses, each in the table of its majority language",
                set(tabkeys) == set(exp_keys) and all(
                    exp_keys[k]["lang"] == lang for lang in group for k in tabs[lang][2]["clause"]),
                f"{len(set(tabkeys) ^ set(exp_keys))} keys differ")
        for lang in group:
            R.info(f"{lang} clauses", f"{len(tabs[lang][2]['clause']):,}")
        # innermost clause of every piece; words.clause
        inner = {}
        for i, c in enumerate(allc):
            for p in c["rows"]:
                if p not in inner or allc[inner[p]]["depth"] < c["depth"]:
                    inner[p] = i
        exp_wcl = {t: (allc[inner[p]]["key"] if p in inner else "") for t, p in stem.items()}
        badw = sum(1 for lang in group for t, v in zip(tabs[lang][0]["t"], tabs[lang][0]["clause"])
                   if v != exp_wcl[t])
        R.check(f"{gname} words: clause = the innermost clause that holds the stem piece", badw == 0, badw)
        allkeys = set(tabkeys)
        miss = sum(1 for lang in group for v in tabs[lang][0]["clause"] if v and v not in allkeys)
        R.check(f"{gname} words: every words.clause exists in clauses", miss == 0, miss)
        nul = sum(1 for lang in group for v in tabs[lang][0]["clause"] if v is None)
        R.check(f"{gname} words: clause is never null (empty outside every clause)", nul == 0, nul)
        for lang in group:
            out_cls = C.Counter(pcls[stem[t]] for t, v in zip(tabs[lang][0]["t"], tabs[lang][0]["clause"]) if not v)
            R.info(f"{lang} words in no clause, by class of the stem", f"{sum(out_cls.values()):,} "
                   f"{dict(out_cls.most_common())}")
        nwords = C.Counter(v for t, v in exp_wcl.items() if v)
        # expected columns of every clause
        bad = C.Counter()
        d8_lost, ow_rw = C.Counter(), {}
        tabrow = {}
        for lang in group:
            D = tabs[lang][2]
            for j, k in enumerate(D["clause"]):
                tabrow[k] = (lang, j)
        for i, c in enumerate(allc):
            k = c["key"]
            if k not in tabrow:
                continue
            lang, j = tabrow[k]
            D = tabs[lang][2]
            rows = c["rows"]
            t0 = place[rows[0]][0]
            wl, wj = wpos[t0]
            W = tabs[wl][0]
            rk = [rank[p] for p in rows]
            par = allc[c["parent"]] if c["parent"] is not None else None
            via = ""
            if c["via"] is not None:
                vt, vc, vty, vr = c["via"][:4]
                via = _vc0(vc) if vc else ("group" if greek and vty == "group" else
                                          ("run" if not greek and vt == "wg" else
                                           ("compound" if V11 and vt == "c" else "")))
            one = c["tag"] == "w"
            role = "" if one or not _role_ok(c["role"]) else _vc0(c["role"])
            parts = c["rule"].split("-")
            pattern = c["rule"] if c["rule"] and all(x and x == x.upper() and x.lower() in ROLE_SET
                                                     for x in parts) else ""
            # constituents
            cons = []
            for (ktag, krole, kcls, ktype, krule, kpids) in c["kids"]:
                if not _role_ok(krole):
                    continue
                kr = sorted((p for p in kpids if p in place), key=rank.get)
                inside = {place[p] for p in kr}
                outs = [p for p in kr if head[place[p]] == (0, 0) or head[place[p]] not in inside]
                kc = _vc0(kcls) if kcls else ("group" if greek and ktype == "group" else
                                              ("run" if not greek and ktag == "wg" else
                                               ("compound" if V11 and ktag == "c" else "")))
                rc = _vc0(krole)
                prep = ""
                if rc == "pp" or kc == "pp":
                    pp = [p for p in kr if pcls[p] == "prep"]
                    prep = plex[pp[0]] if pp else ""
                cons.append(dict(role=rc, head=place[outs[0]][0] if outs else None, first=place[kr[0]][0],
                                 last=place[kr[-1]][0], cls=kc, prep=prep, rows=set(kr),
                                 hp=outs[0] if outs else None,
                                 one=greek and ktag == "w" and krule is not None, r0=rank[kr[0]]))
            pred, pk = 0, "none"
            for kind in ("v", "vc", "p"):
                cand = sorted((x for x in cons if x["role"] == kind and not (kind == "v" and x["one"])),
                              key=lambda x: x["r0"])
                if cand:
                    pred, pk = cand[0]["head"], kind
                    break
            if V11 and one and c["rule"] in ("v2cl", "vc2cl", "p2cl"):
                pred, pk = t0, c["rule"][:-3]      # SPEC 1.1 B3: its own word
            rw = ""
            if not role:
                if c["via"] is not None and _role_ok(c["via"][3]):
                    # SPEC 1.1 B5: only where the clause heads the group (its pred word's edge, else its first
                    # word's, leaves the group; a root leaves it)
                    w0 = pred if pred else t0
                    gw = {place[p][0] for p in c["via"][4] if p in place}
                    if not V11 or whead[w0] == 0 or whead[w0] not in gw:
                        rw = _vc0(c["via"][3])
                    else:
                        d8_lost[(gname if greek else c["lang"], via)] += 1
                elif one and par is not None:
                    parts = par["rule"].split("-")
                    if all(x and x == x.upper() and x.lower() in ROLE_SET for x in parts) and len(parts) == c["npk"]:
                        rw = parts[c["slot"]].lower()
            if V11 and one:
                ow_rw[rows[0]] = rw
            if pred:
                fr = c["frames"].get(stem[pred], "")
                for tok in fr.split():
                    lab, _, ids = tok.partition(":")
                    tp = set()
                    for x in ids.split(";"):
                        if not x or x == "n00000000000":
                            continue
                        tp.update(h for h in ([x] if greek else bym.get(x, [])) if h in place)
                    for x in cons:
                        if tp & x["rows"]:
                            x.setdefault("labels", set()).add(lab)
            c["cons"] = cons
            exp = dict(book=W["book"][wj], chapter=W["chapter"][wj], verse=W["verse"][wj], first=t0,
                       last=place[rows[-1]][0], gaps=rk[-1] - rk[0] + 1 != len(rk), words=nwords[k],
                       parent=par["key"] if par else "", depth=c["depth"], via=via, rule=c["rule"], pattern=pattern,
                       role=role, role_wrapped=rw, pred=pred, pred_kind=pk)
            for col, v in exp.items():
                if D[col][j] != v:
                    bad[col] += 1
        for col in ("book", "chapter", "verse", "first", "last", "gaps", "words", "parent", "depth", "via", "rule",
                    "pattern", "role", "role_wrapped", "pred", "pred_kind"):
            R.check(f"{gname} clauses: {col} equals the value recomputed from the lowfat files", bad[col] == 0,
                    bad[col])
        # the parent tree
        info = {}
        for lang in group:
            D = tabs[lang][2]
            for j, k in enumerate(D["clause"]):
                info[k] = (D["parent"][j], D["depth"][j], D["first"][j], D["last"][j], D["pred"][j])
        nopar = sum(1 for k, v in info.items() if v[0] and v[0] not in info)
        R.check(f"{gname} clauses: every parent is a clause", nopar == 0, nopar)
        depthbad = sum(1 for k, v in info.items() if ((v[1] != 0) if not v[0] else
                                                       (v[0] in info and info[v[0]][1] + 1 != v[1])))
        R.check(f"{gname} clauses: depth 0 at the top, parent's depth + 1 below", depthbad == 0, depthbad)
        loops = _no_loop({k: v[0] or "" for k, v in info.items()}, "")
        R.check(f"{gname} clauses: following parents ends at the top (no loop)", loops == 0, loops)
        xs = sum(1 for k, v in info.items() if v[0] and wsent[v[2]] != wsent[info[v[0]][2]])
        R.check(f"{gname} clauses: every parent lies in the same sentence (a tree per sentence)", xs == 0, xs)
        notin = 0
        for c in allc:
            if c["parent"] is not None and not set(c["rows"]) <= set(allc[c["parent"]]["rows"]):
                notin += 1
        R.check(f"{gname} clauses: every clause's pieces lie inside its parent's pieces", notin == 0, notin)
        span = sum(1 for k, v in info.items() if v[4] and not (v[2] <= v[4] <= v[3]))
        R.check(f"{gname} clauses: pred, where not 0, lies inside the clause's span", span == 0, span)
        sumw = sum(v for lang in group for v in tabs[lang][2]["words"])
        withc = sum(1 for lang in group for v in tabs[lang][0]["clause"] if v)
        R.check(f"{gname} clauses: words sums to the words that have a clause", sumw == withc, f"{sumw:,}")
        for lang in group:
            D = tabs[lang][2]
            R.info(f"{lang} clauses with gaps", sum(1 for g in D["gaps"] if g))
            R.info(f"{lang} clauses by pred_kind", dict(C.Counter(D["pred_kind"]).most_common()))
            R.info(f"{lang} clauses without a predicate, by rule (top 15)",
                   dict(C.Counter(r for r, k in zip(D["rule"], D["pred_kind"]) if k == "none").most_common(15)))
            R.info(f"{lang} clauses by via", dict(C.Counter(D["via"]).most_common()))
            R.info(f"{lang} clauses: own role / role_wrapped / neither",
                   f"{sum(1 for r in D['role'] if r)} / {sum(1 for r in D['role_wrapped'] if r)} / "
                   f"{sum(1 for r, w in zip(D['role'], D['role_wrapped']) if not r and not w)}")
        if greek:
            one = [c for c in allc if c["tag"] == "w"]
            R.info("grc one-word clauses by rule", dict(C.Counter(c["rule"] for c in one).most_common()))
        if V11:
            for lg in group:
                lost = {v: n for (l2, v), n in sorted(d8_lost.items()) if l2 == lg}
                R.info(f"{lg} D8 (1.1, B5): clauses whose via group has a role they do not head (role_wrapped empty), "
                       f"by via", f"{sum(lost.values()):,} {lost}")
            if greek:
                STASH["grc one-word role_wrapped"] = ow_rw
                b3 = sum(1 for k, r, p in zip(tabs["grc"][2]["clause"], tabs["grc"][2]["rule"], tabs["grc"][2]["pred"])
                         if r in ("v2cl", "vc2cl", "p2cl") and k.endswith(":1") and p != 0)
                R.check("grc clauses: every one-word clause of rule v2cl, vc2cl, p2cl has its own word as pred (B3)",
                        all(place[c["rows"][0]][0] == tabs["grc"][2]["pred"][tabrow[c["key"]][1]] for c in one
                            if c["rule"] in ("v2cl", "vc2cl", "p2cl")),
                        f"{sum(1 for c in one if c['rule'] in ('v2cl', 'vc2cl', 'p2cl')):,} clauses; {b3:,} with pred")
            else:
                mixed = [(c["key"], c["lang"], sum(1 for p in c["rows"] if lang_of[p] == "hbo"),
                          sum(1 for p in c["rows"] if lang_of[p] == "arc")) for c in allc
                         if len({lang_of[p] for p in c["rows"]}) > 1]
                R.check("hbo+arc: the mixed clause is GEN 31:47 cl:o010310470012:6 (4 Hebrew, 2 Aramaic pieces), in hbo",
                        mixed == [("cl:o010310470012:6", "hbo", 4, 2)], mixed)
        # constituents
        kbad = C.Counter()
        exp_roles, n_rows = C.Counter(), 0
        excluded = C.Counter()
        for c in allc:
            for (ktag, krole, kcls, ktype, krule, kpids) in c["kids"]:
                if _role_ok(krole):
                    exp_roles[_vc0(krole)] += 1
                elif krole is not None:
                    excluded["error string" if krole.startswith("err_") else f"empty ({ktag})"] += 1
        tab_roles = C.Counter(r for lang in group for r in tabs[lang][3]["role"])
        for r in sorted(set(exp_roles) | set(tab_roles)):
            R.check(f"{gname} constituents: role {r} rows equal the source's count on direct children of clauses",
                    exp_roles[r] == tab_roles[r], f"{tab_roles[r]:,} / {exp_roles[r]:,}")
        R.check(f"{gname} constituents: every role is a role code of SPEC 4.4", set(tab_roles) <= ROLE_SET,
                " ".join(sorted(set(tab_roles) - ROLE_SET)))
        R.info(f"{gname} role values on direct children of clauses excluded (empty, error strings)", dict(excluded))
        if V11:
            badp = [f"{c['key']} {kt} {kr!r}" for c in allc for (kt, kr, _a, _b, _c, _d) in c["kids"]
                    if kr is not None and not _role_ok(kr)]
            want_n = 5 if greek else 2
            R.check(f"{gname} constituents: the {want_n} {'error strings' if greek else 'empty roles'} on direct "
                    "children of clauses are listed by place", len(badp) == want_n, " | ".join(b[:60] for b in badp))
        not_direct = C.Counter()
        for cls, frames, nd in sents:
            not_direct.update(nd)
        R.info(f"{gname} role-bearing elements that are not direct children of a clause (not constituents)",
               f"{sum(not_direct.values())} {dict(sorted(not_direct.items()))}")
        bycl = C.defaultdict(list)
        for lang in group:
            K = tabs[lang][3]
            for j, k in enumerate(K["clause"]):
                bycl[k].append((lang, j))
        multi_head = 0
        for c in allc:
            got = bycl.get(c["key"], [])
            if len(got) != len(c["cons"]):
                kbad["rows per clause"] += 1
                continue
            for o, ((lang, j), x) in enumerate(zip(sorted(got, key=lambda g: tabs[g[0]][3]["ord"][g[1]]),
                                                   c["cons"]), 1):
                K = tabs[lang][3]
                if lang != c["lang"]:
                    kbad["table"] += 1
                exp = dict(ord=o, role=x["role"], head=x["head"], first=x["first"], last=x["last"], cls=x["cls"],
                           frame_role=" ".join(sorted(x.get("labels", ()))), prep=x["prep"])
                for col, v in exp.items():
                    if K["class" if col == "cls" else col][j] != v:
                        kbad[col] += 1
        for col in ("rows per clause", "table", "ord", "role", "head", "first", "last", "cls", "frame_role",
                    "prep"):
            R.check(f"{gname} constituents: {'class' if col == 'cls' else col} equals the value recomputed",
                    kbad[col] == 0, kbad[col])
        cspan = {}
        for lang in group:
            D = tabs[lang][2]
            for j, k in enumerate(D["clause"]):
                cspan[k] = (D["first"][j], D["last"][j])
        outspan = 0
        for lang in group:
            K = tabs[lang][3]
            for k, f, l, h in zip(K["clause"], K["first"], K["last"], K["head"]):
                a, b = cspan[k]
                if not (a <= f <= l <= b and f <= h <= l):
                    outspan += 1
        R.check(f"{gname} constituents: every row's span (and head) lies in its clause's span", outspan == 0,
                outspan)
        for lang in group:
            K = tabs[lang][3]
            R.info(f"{lang} constituents", f"{len(K['clause']):,}; with frame_role "
                   f"{sum(1 for v in K['frame_role'] if v):,}; with prep {sum(1 for v in K['prep'] if v):,}")
        # for stage 05: the clauses as recomputed here, in document order
        STASH[gname] = dict(allc=allc, tabs={lang: tabs[lang] for lang in group}, group=group, plex=plex,
                            stem=stem)


STASH = {}


# ---- stage 05: clause values (SPEC 4.3 marks, line; 4.4 sem_role; 8; D9, D11, D12) -----------------------------

DATA = os.path.join(HERE, "data")
V_CATS = [("kind", "clause-columns", "kind"), ("force", "clause-columns", "force"),
          ("polarity", "clause-extras", "polarity"), ("negator", "clause-columns", "neg"),
          ("neg_scope", "clause-columns", "neg_scope"), ("connective", "connectives", "conn"),
          ("relation", "connectives", "relation"), ("time", "time-aspect", "time"),
          ("aspect", "time-aspect", "aspect"), ("line_kind", "time-aspect", "band"),
          ("voice", "clause-columns", "voice"), ("transitivity", "clause-columns", "m_trans"),
          ("subject_form", "clause-columns", "subj_form"), ("subject_switch", "clause-columns", "subj_switch"),
          ("fronted", "clause-columns", "front")]
# stage 05's decision (report, "For the specification"): readings whose values are English meaning words are
# joined but not carried; of the semantic roles only codes are carried
V_WITHHELD = {"relation", "time", "aspect", "line_kind"}
V_SEM_CODES = {"A2"}
V_NEG = {"lo": "לֹא", "en": "אַיִן", "al": "אַל", "bilti": "בִּלְתִּי", "bal": "בַּל", "la": "לָא",
         "ou": "οὐ", "me": "μή"}
V_LXX = {"lxx_dative", "lxx_nt", "lxx_nt_domain", "lxx_nt_domain+speech"}


def _v_tsv(path, corpus):
    with open(path, encoding="utf-8", newline="") as fh:
        rd = csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
        head = next(rd)
        return [dict(zip(head, r)) for r in rd if r[0] == corpus]


def _v_code(v):
    return re.sub(r"[^a-z0-9]+", "_", v.lower()).strip("_")


def stage05(R, build, src):
    import sqlite3
    nfc = lambda s: U.normalize("NFC", s)  # noqa: E731
    for gname, st in STASH.items():
        greek = gname == "grc"
        corpus = "grc" if greek else "hbo"
        allc, tabs, group, plex, stem = st["allc"], st["tabs"], st["group"], st["plex"], st["stem"]
        lemma, lexkeys = {}, set()
        cats = {}
        for lang in group:
            with open(os.path.join(build, lang, "lexemes.tsv"), encoding="utf-8", newline="") as fh:
                rd = csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
                next(rd)
                for r in rd:
                    lemma[r[0]] = r[1]
                    lexkeys.add(r[0])
            with open(os.path.join(build, lang, "categories.toml"), "rb") as fh:
                cats[lang] = tomllib.load(fh)
        tab = {}
        for lang in group:
            K = tabs[lang][2]
            for j, k in enumerate(K["clause"]):
                tab[k] = (lang, j)
        # the tables as written now (stage 05 rewrote clauses and constituents)
        K5 = {lang: pq.read_table(os.path.join(build, lang, "clauses.parquet")).to_pydict() for lang in group}
        N5 = {lang: pq.read_table(os.path.join(build, lang, "constituents.parquet")).to_pydict() for lang in group}
        for lang in group:
            for col in ("marks", "line"):
                nul = sum(1 for v in K5[lang][col] if v is None)
                R.check(f"{lang} clauses: {col} is filled on every row (never null)", nul == 0, nul)
            nul = sum(1 for v in N5[lang]["sem_role"] if v is None)
            R.check(f"{lang} constituents: sem_role is filled on every row (never null)", nul == 0, nul)
        inner = {}
        for i, c in enumerate(allc):
            for p in c["rows"]:
                if p not in inner or allc[inner[p]]["depth"] < c["depth"]:
                    inner[p] = i
        wid = {}
        for lang in group:
            for t, i in zip(tabs[lang][0]["t"], tabs[lang][0]["id"]):
                wid[t] = i

        def anchor(c):
            lang, j = tab[c["key"]]
            pred = K5[lang]["pred"][j]
            if greek:
                return wid[pred or K5[lang]["first"][j]][1:]
            return stem[pred][1:] if pred else c["rows"][0][1:]

        # layout
        segs = []
        if greek:
            for f in sorted(glob.glob(os.path.join(DATA, "nt-clause-layout/clauses/*/*.jsonl"))):
                b, ch = os.path.basename(f)[:-6].rsplit("_", 1)
                for ln in open(f, encoding="utf-8"):
                    r = json.loads(ln)
                    segs.append((f"{b}.{int(ch)}.{r['verse']}.{r['seg']}", r["words"], r["first"], None, None))
        else:
            for f in sorted(glob.glob(os.path.join(DATA, "clause-layout/clauses/*/*.jsonl"))):
                for ln in open(f, encoding="utf-8"):
                    r = json.loads(ln)
                    segs.append((f"{r['book']}.{r['chapter']}.{r['verse']}.{r['seg']}", r["words"], r["first"],
                                 r["clause_key"], r["clause"]))
        seg_of = {w: si for si, s in enumerate(segs) for w in s[1]}
        R.check(f"{gname} layout: every word key in one segment only", len(seg_of) == sum(len(s[1]) for s in segs),
                f"{len(seg_of):,} keys")
        lines = {s[0] for s in segs}
        R.check(f"{gname} layout: line keys unique", len(lines) == len(segs), f"{len(segs):,} segments")
        # D11
        bad = nol = 0
        for c in allc:
            si = seg_of.get(anchor(c))
            exp = segs[si][0] if si is not None else ""
            nol += exp == ""
            lang, j = tab[c["key"]]
            bad += K5[lang]["line"][j] != exp
        R.check(f"{gname} clauses: line equals D11 recomputed", bad == 0, bad)
        R.info(f"{gname} clauses without a line", nol)
        # D9: dataset rows -> clause
        cc_file = "clause-columns/greek-nt.parquet" if greek else "clause-columns/hebrew.parquet"
        data = {"clause-columns": pq.read_table(os.path.join(DATA, cc_file)).to_pylist()}
        for ds in ("clause-extras", "connectives", "time-aspect"):
            data[ds] = _v_tsv(os.path.join(DATA, ds, "clauses.tsv"), corpus)
        rows_of = {}
        depth_ix = {c["key"]: (c["depth"], i) for i, c in enumerate(allc)}
        if not greek:
            db = sqlite3.connect(f"file:{os.path.join(HERE, 'trees-macula.db')}?mode=ro", uri=True)
            tr = db.execute("select id, rule from nodes where corpus='hbo' and cls='cl' order by id").fetchall()
            db.close()
            R.check("hbo+arc D9: the tree store has as many cl rows as the lowfat files have clauses",
                    len(tr) == len(allc), f"{len(tr):,} / {len(allc):,}")
            diff = sum(1 for (tid, rule), c in zip(tr, allc) if (rule or "") != c["rule"])
            R.check("hbo+arc D9: the rule name is equal at every rank", diff == 0, f"{diff} ranks differ")
            rank_of = {tid: r for r, (tid, _x) in enumerate(tr)}
            k2c = C.defaultdict(set)
            for s in segs:
                k2c[s[3]].add(s[4])
            for ds, rows in data.items():
                got, why = {}, C.Counter()
                for r in rows:
                    ids = k2c.get(r["clause_key"], set())
                    if len(ids) != 1 or next(iter(ids)) not in rank_of:
                        why["no single tree-store clause through the layout"] += 1
                        continue
                    key = allc[rank_of[next(iter(ids))]]["key"]
                    if key in got:
                        why["second row for a clause"] += 1
                        continue
                    got[key] = r
                rows_of[ds] = got
                R.info(f"hbo+arc D9 {ds}: rows {len(rows):,}, joined {len(got):,}, found no clause", dict(why))
        else:
            first2 = {s[2]: si for si, s in enumerate(segs)}
            cand = C.defaultdict(list)
            for c in allc:
                si = seg_of.get(anchor(c))
                if si is not None:
                    cand[si].append(c["key"])
            chosen = {si: min(ks, key=depth_ix.get) for si, ks in cand.items()}
            R.info("grc D9 segments with a clause / without", f"{len(chosen):,} / {len(segs) - len(chosen):,}")
            for ds, rows in data.items():
                got, why = {}, C.Counter()
                for r in rows:
                    si = first2.get(r["clause_key"])
                    if si is None:
                        why["not a segment's first word"] += 1
                    elif si not in chosen:
                        why["no clause has its predicate (or first) word in the segment"] += 1
                    else:
                        got[chosen[si]] = r
                rows_of[ds] = got
                R.info(f"grc D9 {ds}: rows {len(rows):,}, joined {len(got):,}, found no clause", dict(why))

        def match(items, own):
            taken, out = set(), []
            for it in items:
                hit = next(((p, x) for p, x, lm in own if p not in taken and lm == it), None) or \
                    next(((p, x) for p, x, lm in own if p not in taken and nfc(lm) == nfc(it)), None)
                if hit:
                    taken.add(hit[0])
                    out.append(hit[1])
            return out

        bad = C.Counter()
        decl_use = {lang: C.defaultdict(C.Counter) for lang in group}
        for i, c in enumerate(allc):
            own = [(p, plex[p], lemma[plex[p]]) for p in c["rows"] if inner[p] == i]
            exp = {}
            for cat, ds, col in V_CATS:
                r = rows_of[ds].get(c["key"])
                if r is None or cat in V_WITHHELD:
                    continue
                v = r[col]
                if cat == "negator":
                    if v:
                        got = match([V_NEG[v]], own)
                        if got:
                            exp[cat] = got[0]
                elif cat == "connective":
                    got = match((v or "").split(), own)
                    if got:
                        exp[cat] = got
                elif cat == "transitivity":
                    if v is not None:
                        exp[cat] = _v_code(str(v))
                elif v not in (None, ""):
                    code = _v_code(str(v))
                    if cat == "force" and code == "declarative" and r.get("interrog") is True:
                        code = "interrogative"
                    exp[cat] = code
            lang, j = tab[c["key"]]
            have = json.loads(K5[lang]["marks"][j])
            if have != exp:
                bad["marks"] += 1
            if K5[lang]["marks"][j] != json.dumps(have, sort_keys=True, separators=(",", ":"), ensure_ascii=False):
                bad["marks JSON form"] += 1
            for cat, v in have.items():
                for x in (v if isinstance(v, list) else [v]):
                    if cat in ("negator", "connective") and x not in lexkeys:
                        bad["lexeme keys not in lexemes.tsv"] += 1
                for x in (set(v) if isinstance(v, list) else [v]):
                    decl_use[lang][cat][x] += 1
        R.check(f"{gname} clauses: marks equal D9 recomputed from the datasets", bad["marks"] == 0, bad["marks"])
        R.check(f"{gname} clauses: marks are JSON with keys sorted, no spaces", bad["marks JSON form"] == 0,
                bad["marks JSON form"])
        R.check(f"{gname} clauses: every lexeme key in negator, connective is in lexemes.tsv",
                bad["lexeme keys not in lexemes.tsv"] == 0, bad["lexeme keys not in lexemes.tsv"])
        for lang in group:
            cl = cats[lang].get("clauses", {})
            withheld = sorted(set(decl_use[lang]) & V_WITHHELD)
            R.check(f"{lang} clauses: no withheld category (English meaning words) in marks", not withheld,
                    " ".join(withheld))
            undeclared = sum(1 for cat, cc in decl_use[lang].items() for code in cc
                             if code not in {v["code"] for v in cl.get(cat, {}).get("values", [])})
            R.check(f"{lang} clauses: every value of marks is declared in categories.toml", undeclared == 0,
                    undeclared)
            cnt_bad = sum(1 for cat, d in cl.items() for v in d["values"]
                          if decl_use[lang][cat][v["code"]] != v["count"])
            R.check(f"{lang} categories.toml: every clause code's count equals the clauses with it", cnt_bad == 0,
                    cnt_bad)
            for cat, d in cl.items():
                ok = d.get("form_or_reading") and d.get("sha256") and d.get("dataset") and d.get("dataset_column")
                R.check(f"{lang} categories.toml clauses.{cat}: dataset, column, sha256, form or reading stated",
                        bool(ok))
                f = os.path.join(HERE, d["file"])
                R.check(f"{lang} categories.toml clauses.{cat}: sha256 is the file's", S_sha(f) == d["sha256"])
            n = len(K5[lang]["clause"])
            parsed = [json.loads(m) for m in K5[lang]["marks"]]
            for cat, _ds, _col in V_CATS:
                if cat in V_WITHHELD:
                    continue
                R.info(f"{lang} {cat}: clauses with a value", f"{sum(1 for m in parsed if cat in m):,} of {n:,}")
            R.info(f"{lang} clauses with marks not empty", f"{sum(1 for m in parsed if m):,} of {n:,}")
        # D12
        roles = _v_tsv(os.path.join(DATA, "arg-roles/roles.tsv"), corpus)
        byh = C.defaultdict(list)
        for r in roles:
            if r["head"]:
                byh[r["head"]].append(r)
        bad = C.Counter()
        sem_use = {lang: C.Counter() for lang in group}
        for c in allc:
            lang, j = tab[c["key"]]
            for o, x in enumerate(c["cons"], 1):
                cand = byh.get(x["hp"][1:], [])
                if len(cand) > 1:
                    cand = [r for r in cand if sorted(r["words"].split()) == sorted(p[1:] for p in x["rows"])]
                exp = ""
                if len(cand) == 1:
                    r = cand[0]
                    if r["role"] not in ("", "-") and r["role_basis"] not in V_LXX and r["role"] in V_SEM_CODES:
                        exp = _v_code(r["role"])
                sem_use[lang][exp] += 1
                x["exp_sem"] = exp
        for lang in group:
            N = N5[lang]
            idx = {(k, o): s for k, o, s in zip(N["clause"], N["ord"], N["sem_role"])}
            for c in allc:
                if tab[c["key"]][0] != lang:
                    continue
                for o, x in enumerate(c["cons"], 1):
                    if idx.get((c["key"], o)) != x["exp_sem"]:
                        bad["sem"] += 1
            decl = {v["code"]: v["count"] for v in cats[lang].get("constituents", {}).get("sem_role", {})
                    .get("values", [])}
            have = C.Counter(v for v in N["sem_role"] if v)
            R.check(f"{lang} constituents: every sem_role value is declared in categories.toml with its count",
                    have == C.Counter(decl), f"{dict(have)}")
            R.info(f"{lang} constituents with sem_role", f"{sum(have.values()):,} of {len(N['clause']):,}")
        R.check(f"{gname} constituents: sem_role equals D12 recomputed", bad["sem"] == 0, bad["sem"])


# ---- stage 06 -------------------------------------------------------------------------------------------------

P6_TYPES = ("person", "place", "group", "deity", "realia", "flora", "fauna")
P6_KIN = {"father", "mother", "offspring", "sibling", "partner", "tribe", "group_origin"}
P6_NO_WHO = {"hbo": {"cj", "prep", "art"}, "arc": {"cj", "prep", "art"}, "grc": {"conj", "prep", "det"}}
P6_PREFIX = {"hbo": "he:", "arc": "arc:", "grc": "el:"}
P6_ENT = re.compile(r"^(person|place|group|deity|realia|flora|fauna):e[0-9a-f]{10}$")
P6_FACT_COLS = ["subject", "relation", "object", "kind", "method", "source", "confidence", "count", "share", "tier"]


def _p6_tsv(path):
    csv.field_size_limit(1 << 30)
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader((ln for ln in fh if not ln.startswith("#")), delimiter="\t",
                                   quoting=csv.QUOTE_NONE))


def _p6_key(acai, etype):
    import hashlib
    return f"{etype}:e{hashlib.sha1(acai.encode('utf-8')).hexdigest()[:10]}"


def _p6_grc_refs(path):
    root = ET.parse(path).getroot()
    out = {}
    for w in root.iter("w"):
        r = w.get("referent") or w.get("subjref")
        if r:
            out[w.get(XID)] = r.split()
    return out


def _p6_script_ok(s, greek):
    """Every character in the script's blocks; a space between the words of a name (category Zs) is allowed."""
    for ch in s:
        o = ord(ch)
        if U.category(ch) == "Zs":
            continue
        if greek:
            if not (0x0370 <= o <= 0x03FF or 0x1F00 <= o <= 0x1FFF or U.category(ch).startswith("M")):
                return False
        elif not (0x0590 <= o <= 0x05FF or 0xFB1D <= o <= 0xFB4F):
            return False
    return True


def stage06(R, build, src):
    heb, grc, nodes = src
    ent_rows = {r["entity"]: r for r in _p6_tsv(os.path.join(DATA, "entities", "entities.tsv"))}

    def ent(acai):
        r = ent_rows.get(acai)
        if r is None or r["type"] not in P6_TYPES:
            return None
        return _p6_key(acai, r["type"])

    keys = C.Counter(_p6_key(a, r["type"]) for a, r in ent_rows.items() if r["type"] in P6_TYPES)
    R.check("ent keys: no two ACAI ids give one key", all(v == 1 for v in keys.values()),
            sum(1 for v in keys.values() if v > 1))
    words_rows = C.defaultdict(set)
    with open(os.path.join(DATA, "entities", "entity_words.tsv"), encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
            if r["kind"] in ("explicit", "pronominal", "subject"):
                e = ent(r["entity"])
                if e:
                    words_rows[(("n" if len(r["word"]) == 11 else "o") + r["word"], r["kind"])].add(e)
    morph = {mid: pid for pid, mid, _ in nodes}
    refs = {}
    for _, sents in heb:
        for ws, _ in sents:
            for w in ws:
                r = w[9] or w[10]
                if r:
                    refs[w[0]] = [morph.get(x) for x in r.split()]
    ctx = mp.get_context("fork")
    with ctx.Pool(7) as pool:
        for d in pool.map(_p6_grc_refs, sorted(glob.glob(os.path.join(GRC_LOWFAT, "*.xml")))):
            refs.update(d)
    chars = {r["character"]: ent(r["entity"]) if r["entity"] else None
             for r in _p6_tsv(os.path.join(DATA, "entities", "characters.tsv"))}
    addr = {}
    for r in _p6_tsv(os.path.join(DATA, "addressees", "quotations.tsv")):
        a = r["addressee"]
        addr[(r["corpus"], r["quote"])] = None if not a or a.startswith("lemma:") else ent(a)
    # the speech segments: Hebrew rebuilt layer (cache), Greek layout; speaker ids: the no-review tables (cache)
    seg = {}
    for f in glob.glob(os.path.join(build, "cache", "speech-hbo", "segments", "*.tsv")):
        b = os.path.basename(f)[:-4]
        for r in _p6_tsv(f):
            seg[f"{b}.{r['chapter']}.{r['verse']}.{r['seg']}"] = r["quotation"]
    for f in glob.glob(os.path.join(DATA, "nt-clause-layout", "clauses", "*", "*.jsonl")):
        b, ch = os.path.basename(f)[:-6].rsplit("_", 1)
        with open(f, encoding="utf-8") as fh:
            for ln in fh:
                r = json.loads(ln)
                seg[f"{b}.{int(ch)}.{r['verse']}.{r['seg']}"] = r["quotation"] or ""
    sid = {r["id"]: r["speaker_id"] for r in _p6_tsv(os.path.join(build, "cache", "speech-hbo", "quotations.tsv"))}
    gq = _p6_tsv(os.path.join(build, "cache", "speech-grc", "quotations.tsv"))
    sid.update({r["id"]: r["speaker_id"] for r in gq})
    nested = sum(1 for a in gq for b in gq if a is not b and a["id"][:2] == b["id"][:2]
                 and b["start"] <= a["start"] and a["end"] <= b["end"])
    R.info("grc quotations inside another quotation (span containment, recounted)", nested)
    kin = _p6_tsv(os.path.join(DATA, "entities", "kinship.tsv"))

    tabs = {}
    for lang in ("hbo", "arc", "grc"):
        d = os.path.join(build, lang)
        P = pq.read_table(os.path.join(d, "pieces.parquet"), columns=["t", "pid", "class", "who", "who_basis"]).to_pydict()
        K = pq.read_table(os.path.join(d, "clauses.parquet"),
                          columns=["clause", "line", "quote", "speaker", "addressee"]).to_pydict()
        tabs[lang] = (P, K)
    base = {}
    for lang, (P, _) in tabs.items():
        for pid in P["pid"]:
            for kind in ("explicit", "pronominal", "subject"):
                if words_rows.get((pid, kind)):
                    base[pid] = (words_rows[(pid, kind)], kind)
                    break
    for lang, (P, K) in tabs.items():
        greek = lang == "grc"
        bad = C.Counter()
        basis_n = C.Counter()
        for pid, cl, who, wb in zip(P["pid"], P["class"], P["who"], P["who_basis"]):
            got = base.get(pid)
            if got is None and pid in refs:
                es = set()
                for tp in refs[pid]:
                    if tp in base:
                        es |= base[tp][0]
                if es:
                    got = (es, "chain")
            if got is not None and cl in P6_NO_WHO[lang] and got[1] != "explicit":
                got = None
            want = ("", "") if got is None else (" ".join(sorted(got[0])), got[1])
            if (who, wb) != want:
                bad["differ"] += 1
            if who is None or wb is None:
                bad["null"] += 1
            if wb:
                basis_n[wb] += 1
            if (who == "") != (wb == ""):
                bad["who and who_basis not both empty"] += 1
            if who and any(not P6_ENT.match(x) for x in who.split()):
                bad["ent key form"] += 1
            if who and who.split() != sorted(set(who.split())):
                bad["not sorted or repeated"] += 1
        R.check(f"{lang} pieces: who and who_basis are never null", bad["null"] == 0, bad["null"])
        R.check(f"{lang} pieces: who, who_basis equal D7 recomputed", bad["differ"] == 0, bad["differ"])
        R.check(f"{lang} pieces: who and who_basis empty together", bad["who and who_basis not both empty"] == 0,
                bad["who and who_basis not both empty"])
        R.check(f"{lang} pieces: every who is ent keys, sorted, each once",
                bad["ent key form"] + bad["not sorted or repeated"] == 0,
                bad["ent key form"] + bad["not sorted or repeated"])
        R.check(f"{lang} pieces: who_basis only explicit, pronominal, subject, chain",
                set(basis_n) <= {"explicit", "pronominal", "subject", "chain"}, dict(basis_n))
        on_bad = C.Counter((cl, wb) for cl, wb in zip(P["class"], P["who_basis"]) if wb and cl in P6_NO_WHO[lang])
        R.check(f"{lang} pieces: no who on a {'/'.join(sorted(P6_NO_WHO[lang]))} piece unless explicit",
                all(wb == "explicit" for _, wb in on_bad), sum(v for (c, wb), v in on_bad.items() if wb != "explicit"))
        R.info(f"{lang} pieces with who on such a piece, basis explicit (allowed)", dict(on_bad))
        # D10
        corpus = "grc" if greek else "hbo"
        kb = C.Counter()
        for ck, line, q, s, a in zip(K["clause"], K["line"], K["quote"], K["speaker"], K["addressee"]):
            qq = seg.get(line, "")
            want = ("", "", "") if not qq else (f"q:{qq}", chars.get(sid.get(qq) or "") or "",
                                               addr.get((corpus, qq)) or "")
            if (q, s, a) != want:
                kb["differ"] += 1
            if q is None or s is None or a is None:
                kb["null"] += 1
            if (s or a) and not q:
                kb["speaker or addressee without quote"] += 1
        R.check(f"{lang} clauses: quote, speaker, addressee are never null", kb["null"] == 0, kb["null"])
        R.check(f"{lang} clauses: quote, speaker, addressee equal D10 recomputed", kb["differ"] == 0, kb["differ"])
        R.check(f"{lang} clauses: no speaker or addressee outside a quotation",
                kb["speaker or addressee without quote"] == 0, kb["speaker or addressee without quote"])
        # participants.tsv
        rows = _p6_tsv(os.path.join(build, lang, "participants.tsv"))
        have = {r["ent"]: r for r in rows}
        R.check(f"{lang} participants.tsv: columns ent, type, name, sex, words",
                bool(rows) and list(rows[0]) == ["ent", "type", "name", "sex", "words"], len(rows))
        R.check(f"{lang} participants.tsv: every ent once, sorted", [r["ent"] for r in rows] ==
                sorted(have) and len(have) == len(rows), len(rows))
        in_who = {x for w in P["who"] for x in w.split()}
        sp = {x for x in K["speaker"] if x}
        ad = {x for x in K["addressee"] if x}
        R.check(f"{lang} participants: every ent in who is in participants.tsv", in_who <= set(have),
                len(in_who - set(have)))
        R.check(f"{lang} participants: every speaker is a participant", sp <= set(have), len(sp - set(have)))
        R.check(f"{lang} participants: every addressee is a participant", ad <= set(have), len(ad - set(have)))
        R.check(f"{lang} participants.tsv: no row beyond who, speaker, addressee", set(have) <= in_who | sp | ad,
                len(set(have) - (in_who | sp | ad)))
        acai_of = {_p6_key(a, r["type"]): a for a, r in ent_rows.items() if r["type"] in P6_TYPES}
        wordset = C.defaultdict(set)
        for t, w in zip(P["t"], P["who"]):
            for x in w.split():
                wordset[x].add(t)
        pb = C.Counter()
        for e, r in have.items():
            a = acai_of.get(e)
            if a is None:
                pb["ent of no ACAI id"] += 1
                continue
            er = ent_rows[a]
            nm = next((x[len(P6_PREFIX[lang]):] for x in er["lemmas"].split(" | ") if x.startswith(P6_PREFIX[lang])),
                      "")
            want = {"ent": e, "type": er["type"], "name": nm, "sex": {"male": "m", "female": "f"}.get(er["gender"], ""),
                    "words": str(len(wordset.get(e, ())))}
            if r != want:
                pb["differ"] += 1
            if r["name"] and not _p6_script_ok(r["name"], greek):
                pb["name not in the script"] += 1
            if r["type"] != e.split(":")[0]:
                pb["type differs from the key"] += 1
        R.check(f"{lang} participants.tsv: rows equal those recomputed (type, name, sex, words)",
                pb["differ"] + pb["ent of no ACAI id"] + pb["type differs from the key"] == 0, dict(pb))
        R.check(f"{lang} participants.tsv: every name is in the language's script", pb["name not in the script"] == 0,
                pb["name not in the script"])
        R.info(f"{lang} participants: rows, with a name, with sex", f"{len(rows)}, "
               f"{sum(1 for r in rows if r['name'])}, {sum(1 for r in rows if r['sex'])}")
        # facts.parquet: kin relations
        F = pq.read_table(os.path.join(build, lang, "facts.parquet"))
        R.check(f"{lang} facts.parquet: the ten columns in order", F.column_names == P6_FACT_COLS, F.column_names)
        Fd = F.to_pydict()
        # the relations of later stages (08 rendered_by; 09 has_class, in_domain, sense_of, equivalent_of) are
        # checked by those stages; here only the rest, which must be the kin rows
        later = {"rendered_by", "has_class", "in_domain", "sense_of", "equivalent_of"}
        keep = [i for i, rel in enumerate(Fd["relation"]) if rel not in later]
        Fd = {k: [v[i] for i in keep] for k, v in Fd.items()}
        got = list(zip(Fd["subject"], Fd["relation"], Fd["object"]))
        want = sorted({(ent(r["entity"]), r["relation"], ent(r["other"])) for r in kin
                       if r["relation"] in P6_KIN and ent(r["entity"]) in have and ent(r["other"]) in have})
        R.check(f"{lang} facts: kin rows equal kinship.tsv between participants, sorted, each once", got == want,
                f"{len(got)} rows, recomputed {len(want)}")
        other = sum(1 for i in range(len(got)) if (Fd["kind"][i], Fd["method"][i], Fd["source"][i],
                                                   Fd["confidence"][i], Fd["count"][i], Fd["share"][i],
                                                   Fd["tier"][i]) != ("given", "kinship.tsv:relation", "acai", None,
                                                                      None, None, ""))
        R.check(f"{lang} facts: kind given, source acai, confidence and tier empty", other == 0, other)
        R.info(f"{lang} facts by relation", dict(sorted(C.Counter(Fd["relation"]).items())))


# ---- stage 07: the statement tables, recounted from the word tables -----------------------------------------------

S7_TABLES = ("forms", "paradigms", "markers", "constructions", "orders", "agreement", "frames", "pairs", "clause_links")
S7_GROUP = {"forms": ["lexeme", "marks", "form"], "paradigms": ["class", "marks"],
            "markers": ["lexeme", "kind", "category"], "constructions": ["level", "rule", "children"],
            "orders": ["rel", "head_class", "dep_class"], "agreement": ["rel", "category"],
            "frames": ["lexeme", "stem", "frame"], "pairs": ["head", "rel", "dep"],
            "clause_links": ["kind", "connective", "parent_kind", "role"]}
S7_EXTRA = {"paradigms": ["lexemes", "forms"], "markers": ["value"], "constructions": ["head_at"],
            "orders": ["before", "after"], "agreement": ["agree", "differ", "n_a"]}
S7_HEB_DROP = set(range(0x0591, 0x05B0)) | {0x05BD, 0x05C4, 0x05C5}
S7_PLACE_MAP = {}     # pid -> ((t, n), lang); set before the node-file pool forks


def _s7_norm_file(path):
    root = ET.parse(path).getroot()
    return [(w.get(XID), w.get("normalized")) for w in root.iter("w")]


def _s7_nodes_file(path):
    """Branching nodes of one node file: (level, rule, children, head index or -1, first place, aramaic, pieces)."""
    sys.setrecursionlimit(50000)
    greek = "greek" in path
    out = []

    def leaf_pids(el):
        c = el.find("c")
        if c is not None:
            return [m.get(XID) for m in c.findall("m")]
        if greek:
            return [el.get(XID)]
        m = el.find("m")
        return [m.get(XID)] if m is not None else []

    def visit(el):
        """-> (min place, aramaic row pieces, row pieces)"""
        kids = [k for k in el if k.tag == "Node"]
        if not kids:
            pids = leaf_pids(el)
            hits = [S7_PLACE_MAP[p] for p in pids if p in S7_PLACE_MAP]
            agg = (min(h[0] for h in hits) if hits else None, sum(1 for h in hits if h[1] == "arc"), len(hits))
            if el.find("c") is not None and len(pids) >= 2:
                out.append(("clause" if el.get("Cat") == "CL" else "phrase", "compound", "", 0) + agg)
            return agg
        res = [visit(k) for k in kids]
        mins = [r[0] for r in res if r[0] is not None]
        agg = (min(mins) if mins else None, sum(r[1] for r in res), sum(r[2] for r in res))
        if len(kids) >= 2:
            cats = [k.get("Cat") or "" for k in kids]
            hd = el.get("Head")
            if hd is not None:
                h = int(hd)
            elif len(kids) == 2 and sum(1 for c in cats if c in ("conj", "cj", "cjp")) == 1:
                h = 0 if cats[1] in ("conj", "cj", "cjp") else 1
            else:
                h = -1
            rule = el.get("Rule")
            if rule is None:
                rule = "run" if hd is not None else ""
            out.append(("clause" if el.get("Cat") == "CL" else "phrase", rule, " ".join(c.lower() for c in cats), h)
                       + agg)
        return agg

    for s in ET.parse(path).getroot().iter("Sentence"):
        for tree in s.findall("./Trees/Tree"):
            for k in tree:
                if k.tag == "Node":
                    visit(k)
    return out


def _s7_read(build, lang):
    d = os.path.join(build, lang)
    t = {n: pq.read_table(os.path.join(d, f"{n}.parquet")).to_pylist()
         for n in ("words", "pieces", "clauses", "constituents")}
    with open(os.path.join(d, "lexemes.tsv"), encoding="utf-8", newline="") as fh:
        t["lexemes"] = list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))
    for n in S7_TABLES + ("exceptions",):
        t["S:" + n] = pq.read_table(os.path.join(d, f"{n}.parquet")).to_pylist()
    return t


def _s7_expect(lang, t, word_stem, greek_norm, cons_nodes, kind_all):
    """The expected statement groups of one language: table -> {group key: (extra values, for, against)}, where
    `for` and `against` are lists of (sort key, place)."""
    exp = {n: {} for n in S7_TABLES}
    pieces = t["pieces"]

    def pl(p):
        return ((p["t"], p["n"]), f'{p["t"]}.{p["n"]}')

    def norm(p):
        if lang == "grc":
            return U.normalize("NFC", greek_norm[p["pid"]].lower())
        return U.normalize("NFC", "".join(ch for ch in p["text"] if ord(ch) not in S7_HEB_DROP))

    forms, para = C.defaultdict(list), C.defaultdict(lambda: [[], set(), set()])
    for p in pieces:
        f = norm(p)
        forms[(p["lexeme"], p["marks"], f)].append(pl(p))
        g = para[(p["class"], p["marks"])]
        g[0].append(pl(p))
        g[1].add(p["lexeme"])
        g[2].add(f)
    exp["forms"] = {k: ((), v, []) for k, v in forms.items()}
    exp["paradigms"] = {k: ((len(v[1]), len(v[2])), v[0], []) for k, v in para.items()}

    # markers
    nlex = C.Counter(r["class"] for r in t["lexemes"])
    wmark = {r["lexeme"] for r in t["lexemes"] if nlex[r["class"]] <= 40}
    head_of = {w["t"]: w["head"] for w in t["words"]}
    places = C.defaultdict(lambda: C.defaultdict(list))   # (lexeme, kind) -> category -> [(code, place)]
    for p in pieces:
        if p["kind"] != "stem":
            target = word_stem[p["t"]]
            kind = p["kind"]
        elif p["lexeme"] in wmark and head_of[p["t"]] != 0:
            target = word_stem[head_of[p["t"]]]
            kind = "word"
        else:
            continue
        for cat, code in json.loads(target["marks"]).items():
            places[(p["lexeme"], kind)][cat].append((code, pl(p)))
    for (lex, kind), cats in places.items():
        for cat, items in cats.items():
            tally = C.Counter(c for c, _ in items)
            value = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            if len(items) >= 20 and tally[value] >= 0.95 * len(items):
                exp["markers"][(lex, kind, cat)] = ((value,), [x for c, x in items if c == value],
                                                    [x for c, x in items if c != value])

    # constructions
    grp = C.defaultdict(list)
    for level, rule, children, h, place in cons_nodes:
        grp[(level, rule, children)].append((h, (place, f"{place[0]}.{place[1]}")))
    for k, items in grp.items():
        tally = C.Counter(h for h, _ in items)
        hat = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        exp["constructions"][k] = ((hat,), [x for h, x in items if h == hat], [x for h, x in items if h != hat])

    # word edges
    side = C.defaultdict(lambda: ([], []))
    agr = C.defaultdict(lambda: [[], [], 0])
    prs = C.defaultdict(list)
    for w in t["words"]:
        if w["head"] == 0:
            continue
        d, h = word_stem[w["t"]], word_stem[w["head"]]
        x = ((w["t"], 0), str(w["t"]))
        side[(w["rel"], h["class"], d["class"])][0 if w["t"] < w["head"] else 1].append(x)
        dm, hm = json.loads(d["marks"]), json.loads(h["marks"])
        for cat in ("gender", "number", "person", "case", "state"):
            if cat in dm and cat in hm:
                agr[(w["rel"], cat)][0 if dm[cat] == hm[cat] else 1].append(x)
            elif cat in dm or cat in hm:
                agr[(w["rel"], cat)][2] += 1
        prs[(h["lexeme"], w["rel"], d["lexeme"])].append(x)
    for k, (b, a) in side.items():
        big, small = (b, a) if len(b) >= len(a) else (a, b)
        exp["orders"][k] = ((len(b), len(a)), big, small)
    for k, (a, d, n) in agr.items():
        if a or d:
            exp["agreement"][k] = ((len(a), len(d), n), a, d)
    exp["pairs"] = {k: ((), v, []) for k, v in prs.items() if len(v) >= 2}

    # frames, clause_links
    corder = {c["clause"]: (c["first"], i) for i, c in enumerate(t["clauses"])}
    parts = C.defaultdict(list)
    for r in t["constituents"]:
        parts[r["clause"]].append(r)
    fr, cl = C.defaultdict(list), C.defaultdict(list)
    for c in t["clauses"]:
        x = (corder[c["clause"]], c["clause"])
        if c["pred_kind"] == "v":
            st = word_stem[c["pred"]]
            ps = sorted(parts[c["clause"]], key=lambda r: r["ord"])
            vs = [r for r in ps if r["role"] == "v" and r["head"] == c["pred"]]
            drop = vs[0]["ord"] if vs else None
            roles = sorted(("pp:" + r["prep"] if r["role"] == "pp" and r["prep"] else r["role"])
                           for r in ps if r["ord"] != drop)
            fr[(st["lexeme"], json.loads(st["marks"]).get("stem", ""), " ".join(roles))].append(x)
        m = json.loads(c["marks"])
        pk = kind_all[c["parent"]] if c["parent"] else "top"
        cl[(m.get("kind", ""), " ".join(m.get("connective", [])), pk, c["role"] or c["role_wrapped"])].append(x)
    exp["frames"] = {k: ((), v, []) for k, v in fr.items()}
    exp["clause_links"] = {k: ((), v, []) for k, v in cl.items()}
    return exp


def stage07(R, build, src):
    tabs = {lang: _s7_read(build, lang) for lang in ("hbo", "arc", "grc")}
    # stem piece of every word, over hbo+arc together and over grc
    stem = {"tan": {}, "grc": {}}
    for lang, t in tabs.items():
        grp = "grc" if lang == "grc" else "tan"
        for p in t["pieces"]:
            if p["kind"] == "stem":
                stem[grp][p["t"]] = p
    kinds = {"tan": {}, "grc": {}}
    for lang, t in tabs.items():
        for c in t["clauses"]:
            kinds["grc" if lang == "grc" else "tan"][c["clause"]] = json.loads(c["marks"]).get("kind", "")
    with mp.get_context("fork").Pool(7) as pool:
        gnorm = dict(x for f in pool.map(_s7_norm_file, sorted(glob.glob(os.path.join(GRC_LOWFAT, "*.xml"))))
                     for x in f)
    # node files, one text at a time (the pid map is inherited by the forked workers)
    cons = {"hbo": [], "arc": [], "grc": []}
    for grp, files, langs in (("tan", sorted(glob.glob(os.path.join(HEB_NODES, "*.xml"))), ("hbo", "arc")),
                              ("grc", sorted(glob.glob(os.path.join(
                                  HERE, "data/macula-nodes/greek/Nestle1904/nodes/*.xml"))), ("grc",))):
        S7_PLACE_MAP.clear()
        for lang in langs:
            for p in tabs[lang]["pieces"]:
                S7_PLACE_MAP[p["pid"]] = ((p["t"], p["n"]), lang)
        with mp.get_context("fork").Pool(7) as pool:
            res = pool.map(_s7_nodes_file, files, chunksize=4)
        none_place = 0
        for f in res:
            for level, rule, children, h, mn, na, nt in f:
                if mn is None:
                    none_place += 1
                    continue
                lang = "grc" if grp == "grc" else ("arc" if 2 * na > nt else "hbo")
                cons[lang].append((level, rule, children, h, mn))
        R.info(f"{grp} branching nodes with no row piece (not counted)", none_place)
    S7_PLACE_MAP.clear()
    for lang, t in tabs.items():
        grp = "grc" if lang == "grc" else "tan"
        exp = _s7_expect(lang, t, stem[grp], gnorm, cons[lang], kinds[grp])
        # a place may lie in the other Tanakh table (GEN 31:47, DAN 2:4): hbo and arc are read together (SPEC 1)
        both = ("hbo", "arc") if grp == "tan" else ("grc",)
        own_at = {f'{p["t"]}.{p["n"]}' for p in t["pieces"]} | {str(w["t"]) for w in t["words"]} \
            | {c["clause"] for c in t["clauses"]}
        pieces_at = {f'{p["t"]}.{p["n"]}' for x in both for p in tabs[x]["pieces"]}
        words_at = {str(w["t"]) for x in both for w in tabs[x]["words"]}
        clauses_at = {c["clause"] for x in both for c in tabs[x]["clauses"]}
        exc_by = C.defaultdict(list)
        for r in t["S:exceptions"]:
            exc_by[r["statement"]].append(r["place"])
        total_against, bad_place, other_place = 0, 0, C.Counter()
        for name in S7_TABLES:
            rows = t["S:" + name]
            gc, xc = S7_GROUP[name], S7_EXTRA.get(name, [])
            keys = [tuple(r[c] for c in gc) for r in rows]
            R.check(f"{lang} {name}: ids run 1..n in the sort order of the grouping columns",
                    [r["id"] for r in rows] == [f"{name}:{i}" for i in range(1, len(rows) + 1)]
                    and keys == sorted(keys) and len(set(keys)) == len(keys), len(rows))
            e = exp[name]
            R.check(f"{lang} {name}: rows equal the recomputed groups", set(keys) == set(e),
                    f"{len(set(keys) ^ set(e))} differ of {len(e)}")
            bad_count = bad_against = bad_extra = bad_places = bad_exc = 0
            for r, k in zip(rows, keys):
                if k not in e:
                    continue
                extra, pro, con = e[k]
                bad_count += r["count"] != len(pro)
                bad_against += r["against"] != len(con)
                bad_extra += tuple(r[c] for c in xc) != tuple(extra)
                bad_places += r["places"] != " ".join(p for _, p in sorted(pro)[:3])
                bad_exc += sorted(exc_by.get(r["id"], [])) != sorted(p for _, p in con)
                total_against += r["against"]
            R.check(f"{lang} {name}: every count equals the recount", bad_count == 0, bad_count)
            R.check(f"{lang} {name}: every against equals the recount", bad_against == 0, bad_against)
            if xc:
                R.check(f"{lang} {name}: {', '.join(xc)} equal the recount", bad_extra == 0, bad_extra)
            R.check(f"{lang} {name}: places are the first three in text order", bad_places == 0, bad_places)
            R.check(f"{lang} {name}: the exceptions of each statement are its against places", bad_exc == 0, bad_exc)
            if name not in S7_EXTRA or name == "paradigms":
                R.check(f"{lang} {name}: against is 0 (an attestation table)",
                        all(r["against"] == 0 for r in rows), sum(1 for r in rows if r["against"]))
            at = clauses_at if name in ("frames", "clause_links") else (
                words_at if name in ("orders", "agreement", "pairs") else pieces_at)
            bad_place += sum(1 for r in rows for p in r["places"].split() if p not in at)
            other_place[name] += sum(1 for r in rows for p in r["places"].split() if p in at and p not in own_at)
            for r in rows:
                bad_place += sum(1 for p in exc_by.get(r["id"], []) if p not in at)
                other_place[name] += sum(1 for p in exc_by.get(r["id"], []) if p in at and p not in own_at)
        ids = {r["id"] for n in S7_TABLES for r in t["S:" + n]}
        R.check(f"{lang} exceptions: rows equal the sum of all against", len(t["S:exceptions"]) == total_against,
                f"{len(t['S:exceptions'])} rows, sum {total_against}")
        R.check(f"{lang} exceptions: every statement exists", all(r["statement"] in ids for r in t["S:exceptions"]),
                sum(1 for r in t["S:exceptions"] if r["statement"] not in ids))
        R.check(f"{lang} statements: every place exists" + (" (in hbo or arc)" if grp == "tan" else ""),
                bad_place == 0, bad_place)
        R.info(f"{lang} statement places that lie in the other Tanakh table",
               {k: v for k, v in sorted(other_place.items()) if v})
        # the forms table against lexemes.tsv (stage 02 counted the distinct forms of each lexeme)
        nforms = C.Counter(r["lexeme"] for r in t["S:forms"])
        per_lex = C.defaultdict(set)
        for r in t["S:forms"]:
            per_lex[r["lexeme"]].add(r["form"])
        bad = sum(1 for r in t["lexemes"] if len(per_lex[r["lexeme"]]) != int(r["forms"]))
        R.check(f"{lang} forms: distinct forms per lexeme equal lexemes.tsv `forms`", bad == 0, bad)
        R.check(f"{lang} forms: count sums to the pieces", sum(r["count"] for r in t["S:forms"]) == len(t["pieces"]),
                len(t["pieces"]))
        R.info(f"{lang} statement rows", {n: len(t["S:" + n]) for n in S7_TABLES})
        R.info(f"{lang} lexemes in forms", len(nforms))


def S_sha(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---- stage 08: links ------------------------------------------------------------------------------------------

S8_ROOT = os.path.dirname(os.path.dirname(HERE))
S8_BRIDGE = os.path.join(S8_ROOT, "internal-docs/hebrew-greek-cf-release/v0.2/bridges/lxx.parquet")
S8_GLAUX = os.path.join(S8_ROOT, "shoresh/lxx/data/lxx-glaux.db")
S8_NUMBERS = os.path.join(S8_ROOT, "resources/lxx_bridge_tiers/greek_numbers.tsv")
S8_COMPACT = os.path.join(HERE, "data/compact-alignments-11583082")
S8_PUBLISH = os.path.expanduser("~/dev/bcv-commons/lexeme-aligner/publish/compact-alignments")
S8_HELLOAO = os.path.join(HERE, "data/helloao")
S8_BRIDGE_HOW = {"sure", "order", "neighbours", "number"}
S8_RULES = {"lemma", "form_near", "verse_form", "verse_lemma", "verse_number"}
S8_NT_HOW = {"E": "eflomal_09", "e": "eflomal_06", "G": "gloss_strong", "g": "gloss_weak", "f": "gapfill",
             "x": "spanext", "r": "residual"}
S8_STATES = {"linked", "outside_alignment", "never_a_word", "unplaced", "no_counterpart"}


def _s8_greek_file(path):
    out = []
    for w in ET.parse(path).getroot().iter("w"):
        out.append((w.get(XID), w.get("greek"), w.get("greekstrong")))
    return out


def _s8_plain(s):
    s = U.normalize("NFD", (s or "").lower())
    return "".join(ch for ch in s if not U.combining(ch)).replace("ς", "σ").strip(".,;·:!?'’\"")


def _s8_nums(s):
    return [m.lstrip("0") or "0" for m in re.findall(r"\d+", str(s or ""))]


def _s8_one_edit(a, b):
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    return any(b[:i] + b[i + 1:] == a for i in range(len(b)))


def _s8_script(s, scripts):
    """every letter of s is of the script (marks, signs, punctuation pass; U+02B9 is the Greek numeral sign)"""
    for ch in s or "":
        if U.category(ch)[0] == "L" and ord(ch) != 0x02B9 and not any(U.name(ch, "").startswith(x) for x in scripts):
            return False
    return True


def _s8_facts_check(R, lang, facts, lrows, lexeme_of, object_of, kept_expected):
    pair = C.Counter((lexeme_of[(r["t"], r["n"])], r["other"], object_of(r["other"], r["s"])) for r in lrows
                     if object_of(r["other"], r["s"]) is not None)
    total = C.Counter()
    for (lx, o, _), v in pair.items():
        total[(lx, o)] += v
    got = {(f["subject"], f["object"]): f for f in facts if f["relation"] == "rendered_by"}
    want = {(lx, obj): (v, v / total[(lx, o)]) for (lx, o, obj), v in pair.items()}
    bad = sum(1 for k, (v, sh) in want.items() if k not in got or got[k]["count"] != v
              or abs(got[k]["share"] - sh) > 1e-12 or got[k]["kind"] != "linked")
    R.check(f"{lang} facts: rendered_by rows equal the recount from links (count, share, kind linked)",
            bad == 0 and len(got) == len(want), f"{len(got)} rows, {bad} differ")
    # stage 09 adds has_class, in_domain, sense_of, equivalent_of; it checks them itself
    kept = sum(1 for f in facts if f["relation"] not in ("rendered_by",) + S9_RELATIONS)
    R.check(f"{lang} facts: the rows of stage 06 are kept", kept == kept_expected, kept)


def stage08(R, build, src):
    import sqlite3
    sys.path.append(os.path.join(HERE, "vendor_bibles"))
    import bcv_tokenize
    import helloao_to_usj
    import verse_text
    s6 = json.load(open(os.path.join(build, "cache", "stage06-counts.json"), encoding="utf-8"))["counts"]
    # --- the Septuagint ---
    con = sqlite3.connect(f"file:{S8_GLAUX}?mode=ro", uri=True)
    rows = [r for r in con.execute("select book, chapter, verse, idx, surface, lemma, pos, strong, glaux_id "
                                   "from lxx_words where canonical = 1")
            if not (r[0] == "DAN" and r[1] == 3 and 24 <= r[2] <= 90)]
    T = {}
    for lang in ("hbo", "arc"):
        d = os.path.join(build, lang)
        T[lang] = {"W": pq.read_table(os.path.join(d, "words.parquet"), columns=["t", "book", "chapter", "verse"]).to_pylist(),
                   "P": pq.read_table(os.path.join(d, "pieces.parquet"), columns=["t", "n", "pid", "class", "lexeme"]).to_pylist(),
                   "L": pq.read_table(os.path.join(d, "links.parquet")).to_pylist(),
                   "A": pq.read_table(os.path.join(d, "link_account.parquet")).to_pylist(),
                   "F": pq.read_table(os.path.join(d, "facts.parquet")).to_pylist(),
                   "O": os.path.join(d, "other", "lxx", "words.parquet")}
    R.check("lxx: other/lxx/words.parquet is the same file in hbo and arc",
            S_sha(T["hbo"]["O"]) == S_sha(T["arc"]["O"]))
    O = pq.read_table(T["hbo"]["O"]).to_pylist()
    order = list(dict.fromkeys(w["book"] for lang in ("hbo", "arc") for w in sorted(T[lang]["W"], key=lambda w: w["t"])))
    rank = {b: i for i, b in enumerate(order)}
    rows.sort(key=lambda r: (rank[r[0]], r[1], r[2], r[3]))
    R.check("lxx words: one row per GLAUx canonical word (Daniel 3:24-90 left out)", len(O) == len(rows), len(O))
    emptied = C.Counter()

    def given(v, src):                  # the source's value, or empty where it holds a letter of another script
        if v is None and src is not None and not _s8_script(src, ("GREEK",)):
            emptied["lxx"] += 1
            return src
        return v
    bad = sum(1 for o, r in zip(O, rows) if (o["book"], o["chapter"], o["verse"], o["w"], given(o["text"], r[4]),
                                             given(o["lemma"], r[5]), o["id"])
              != (r[0], r[1], r[2], r[3], r[4], r[5], str(r[8])) or o["class"] != _c0(r[6]))
    R.info("lxx values emptied (a letter of another script)", emptied["lxx"])
    R.check("lxx words: in order; s, id, place, text, lemma and class as GLAUx gives them", bad == 0 and
            [o["s"] for o in O] == list(range(1, len(O) + 1)), bad)
    R.check("lxx words: every id once", len({o["id"] for o in O}) == len(O))
    R.check("lxx words: text and lemma in Greek script", all(_s8_script(o["text"], ("GREEK",)) and
                                                           _s8_script(o["lemma"], ("GREEK",)) for o in O))
    s_of_key = {f"lxx {r[0]} {r[1]}:{r[2]} {r[3]}": i for i, r in enumerate(rows, start=1)}
    plain = {o["s"]: _s8_plain(r[4]) for o, r in zip(O, rows)}          # matching reads GLAUx's own values
    lemma = {o["s"]: r[5] for o, r in zip(O, rows)}
    lemma_out = {o["s"]: o["lemma"] for o in O}
    norm_out = {o["s"]: U.normalize("NFC", o["text"].lower()) if o["text"] else None for o in O}
    vers = {o["s"]: (o["book"], o["chapter"], o["verse"]) for o in O}
    to_nt = {}
    with open(S8_NUMBERS, encoding="utf-8") as fh:
        for line in fh.read().splitlines()[1:]:
            f = line.split("\t")
            if f[1]:
                to_nt[_s8_nums(f[0])[0]] = _s8_nums(f[1])[0]
    numbers = {o["s"]: {to_nt.get(x, x) for x in _s8_nums(r[7])} for o, r in zip(O, rows)}
    form_lemmas = C.defaultdict(set)
    for o in O:
        form_lemmas[plain[o["s"]]].add(lemma[o["s"]])
    with mp.get_context("fork").Pool(7) as pool:
        gr = pool.map(_s8_greek_file, sorted(glob.glob(os.path.join(HEB_LOWFAT, "*-lowfat.xml"))), chunksize=8)
    named = {i: (g, s) for f in gr for i, g, s in f}
    piece = {}
    for lang in ("hbo", "arc"):
        wv = {w["t"]: (w["book"], w["chapter"], w["verse"]) for w in T[lang]["W"]}
        for p in T[lang]["P"]:
            piece[(p["t"], p["n"])] = (lang, p, wv[p["t"]])
    pid_key = {p["pid"]: k for k, (lang, p, _) in piece.items()}
    bridge = pq.read_table(S8_BRIDGE).to_pylist()
    want_b = set()
    for r in bridge:
        want_b.add(pid_key["o" + r["hebrew_mid"]] + (s_of_key[r["lxx_key"]], r["how"]))
    L = [dict(r, lang=lang) for lang in ("hbo", "arc") for r in T[lang]["L"]]
    got_b = {(r["t"], r["n"], r["s"], r["how"]) for r in L if r["how"] in S8_BRIDGE_HOW}
    R.check("lxx links: the rows whose how comes from the bridge equal the bridge's rows",
            got_b == want_b and len(want_b) == 345461 and sum(r["how"] in S8_BRIDGE_HOW for r in L) == 345461,
            len(got_b))
    R.check("lxx links: every how is a bridge value or a rule of stage 08",
            all(r["how"] in S8_BRIDGE_HOW | S8_RULES for r in L))
    R.check("lxx links: every (t, n) is a piece of its table and every s a word of other/lxx",
            all(piece.get((r["t"], r["n"]), ("",))[0] == r["lang"] and r["s"] in plain and r["other"] == "lxx" for r in L))
    R.check("lxx links: agree is 1 on every row (no second model-free alignment)", all(r["agree"] == 1 for r in L))
    per_piece = C.Counter((r["t"], r["n"]) for r in L)
    R.check("lxx links: at most one link per piece", max(per_piece.values()) == 1, len(per_piece))
    # the rules of stage 08
    bridged = {(k[0], k[1]) for k in want_b}
    own = C.defaultdict(set)
    for k in want_b:
        own[piece[(k[0], k[1])][2]].add(vers[k[2]])
    s_use = C.Counter(r["s"] for r in L)
    by_rule, bad = C.Counter(), C.Counter()
    for r in L:
        if r["how"] not in S8_RULES:
            continue
        key = (r["t"], r["n"])
        by_rule[r["how"]] += 1
        lang, p, hv = piece[key]
        g = named.get(p["pid"], (None, None))
        f = _s8_plain(g[0])
        ls = form_lemmas.get(f, set())
        ok = key not in bridged and bool(g[0]) and g[0] not in ("’’", "^^^") and s_use[r["s"]] == 1
        in_own = vers[r["s"]] in own[hv]
        if r["how"] == "lemma":
            ok = ok and in_own and len(ls) == 1 and lemma[r["s"]] in ls
        elif r["how"] == "form_near":
            mine = {to_nt.get(x, x) for x in _s8_nums(g[1])}
            ok = ok and in_own and len(f) >= 5 and _s8_one_edit(plain[r["s"]], f) and (
                not mine or not numbers[r["s"]] or bool(mine & numbers[r["s"]]))
        elif r["how"] == "verse_form":
            ok = ok and not in_own and plain[r["s"]] == f
        elif r["how"] == "verse_lemma":
            ok = ok and not in_own and len(ls) == 1 and lemma[r["s"]] in ls
        else:
            ok = ok and not in_own and bool({to_nt.get(x, x) for x in _s8_nums(g[1])} & numbers[r["s"]])
        bad[r["how"]] += not ok
    R.check("lxx links: every stage-08 link meets its rule (named, not bridged, free word, the rule's match and verse)",
            sum(bad.values()) == 0, dict(bad))
    R.info("lxx links placed by stage-08 rules", dict(sorted(by_rule.items())))
    # D13
    linked = set(per_piece)
    allc, linc = C.Counter(), C.Counter()
    for k, (lang, p, _) in piece.items():
        allc[p["class"]] += 1
        linc[p["class"]] += k in linked
    naw = {c for c in allc if linc[c] / allc[c] < 0.05}
    R.info("lxx never_a_word classes (share linked, hbo+arc)", {c: round(linc[c] / allc[c], 4) for c in sorted(naw)})
    for lang in ("hbo", "arc"):
        A = T[lang]["A"]
        keys = [(a["t"], a["n"], a["other"]) for a in A]
        R.check(f"{lang} link_account: exactly one row per (piece, lxx)",
                len(keys) == len(set(keys)) == len(T[lang]["P"]) and all(a["other"] == "lxx" for a in A), len(A))
        badst = 0
        for a in A:
            _, p, _ = piece[(a["t"], a["n"])]
            g = named.get(p["pid"], (None, None))
            if (a["t"], a["n"]) in linked:
                want = ("linked", "")
            elif p["class"] in naw:
                want = ("never_a_word", p["class"])
            elif g[0] and g[0] not in ("’’", "^^^"):
                want = ("unplaced", g[0])
            else:
                want = ("no_counterpart", "")
            badst += (a["state"], a["reason"]) != want
        R.check(f"{lang} link_account: every state and reason as D13 gives them", badst == 0, badst)
        st = C.Counter(a["state"] for a in A)
        R.check(f"{lang} link_account: the account closes (states sum to the pieces)",
                sum(st.values()) == len(T[lang]["P"]) and set(st) <= S8_STATES, dict(sorted(st.items())))
        lex = {(p["t"], p["n"]): p["lexeme"] for p in T[lang]["P"]}
        _s8_facts_check(R, lang, T[lang]["F"], T[lang]["L"], lex,
                        lambda o, s: f"lxx:{lemma_out[s]}" if lemma_out[s] else (f"lxx:form:{norm_out[s]}"
                                                                                    if norm_out[s] else None),
                        s6[f"{lang} facts rows"])
    # --- the Hebrew New Testaments ---
    d = os.path.join(build, "grc")
    W = pq.read_table(os.path.join(d, "words.parquet"), columns=["t", "id", "book"]).to_pylist()
    P = pq.read_table(os.path.join(d, "pieces.parquet"), columns=["t", "n", "class", "lexeme", "marks"]).to_pylist()
    L = pq.read_table(os.path.join(d, "links.parquet")).to_pylist()
    A = pq.read_table(os.path.join(d, "link_account.parquet")).to_pylist()
    F = pq.read_table(os.path.join(d, "facts.parquet")).to_pylist()
    books = list(dict.fromkeys(w["book"] for w in sorted(W, key=lambda w: w["t"])))
    t_of = {w["id"]: w["t"] for w in W}
    cls = {p["t"]: p["class"] for p in P}
    proper = {p["t"] for p in P if json.loads(p["marks"] or "{}").get("type") == "proper"}
    man = json.load(open(os.path.join(S8_COMPACT, "manifest.json"), encoding="utf-8"))
    forms = {}
    for ed in ("heb_scg", "heb_mod"):
        O = pq.read_table(os.path.join(d, "other", ed, "words.parquet")).to_pylist()
        R.check(f"{ed} words: lemma and class empty (the text has no source of its own for them)",
                all(o["lemma"] is None and o["class"] is None for o in O))
        R.check(f"{ed} words: text in Hebrew script", all(_s8_script(o["text"], ("HEBREW",)) for o in O))
        at = {(o["book"], o["chapter"], o["verse"], o["w"]): o for o in O}
        tok_s = {}
        n_tok = n_label = n_empty = 0
        files_ok = True
        for b in books:
            chs = []
            for fpath in sorted(glob.glob(os.path.join(S8_HELLOAO, ed, f"{b}_*.json"))):
                chs.append(json.load(open(fpath, encoding="utf-8")))
            chs.sort(key=lambda x: x["chapter"]["number"])
            vt = verse_text.extract_usj(helloao_to_usj.merge_book_usj(b, chs))
            vv = {(int(c), int(x["verse"])): x["text"] for c, vs in vt.items() for x in vs}
            h = bcv_tokenize.file_hash(bcv_tokenize.fingerprints(vv)[0])
            files_ok &= os.path.exists(os.path.join(S8_COMPACT, "h", "heb", ed, f"{b}_{h}.json"))
            tok_s[b] = h
            for (c, v), text in vv.items():
                toks = bcv_tokenize.tokenize(text)
                for i, tk in enumerate(toks):
                    o = at.get((b, c, v, i))
                    if o is None:
                        n_label += 1
                        files_ok &= i == 0      # only a verse's first token (its number) may be left out
                        continue
                    n_tok += 1
                    if o["text"] is None:
                        n_empty += 1
                        files_ok &= not _s8_script(tk, ("HEBREW",))
                    elif bcv_tokenize.strip_marks(o["text"]) != tk:
                        files_ok = False
        R.check(f"{ed} words: every token of the text is a row or a left-out verse number, and spells the token",
                files_ok and n_tok == len(O) and [o["s"] for o in O] == list(range(1, len(O) + 1)),
                f"{n_tok} rows, {n_label} left out, {n_empty} emptied (another script)")
        s_at = {(o["book"], o["chapter"], o["verse"], o["w"]): o["s"] for o in O}
        forms[ed] = {o["s"]: U.normalize("NFC", "".join(ch for ch in o["text"] if not (0x0591 <= ord(ch) <= 0x05AF
                     or ord(ch) in (0x05BD, 0x05C4, 0x05C5)))) if o["text"] else None for o in O}
        E = man["languages"]["heb"]["editions"][ed]
        vmap = json.load(open(os.path.join(S8_PUBLISH, "_index", E["verse_map"]), encoding="utf-8"))["map"]
        want = {}
        skipped = 0
        for b in books:
            arr = json.load(open(os.path.join(S8_COMPACT, "h", "heb", ed, f"{b}_{tok_s[b]}.json"), encoding="utf-8"))
            lex = json.load(open(os.path.join(S8_COMPACT, "_index", f"{b}_lexemes.json"), encoding="utf-8"))
            keys = json.load(open(os.path.join(S8_PUBLISH, "_index", f"{b}_keys.json"), encoding="utf-8"))
            meta = json.load(open(os.path.join(S8_PUBLISH, "h", "heb", ed, f"{b}_{tok_s[b]}.meta.json"), encoding="utf-8"))
            for k, ref in enumerate(lex):
                if not arr[k]:
                    continue
                tgt = vmap.get(ref, ref)
                tb, tcv = tgt.split(" ", 1)
                if tcv.endswith(":title"):
                    continue
                tc, tv = (int(x) for x in tcv.split(":"))
                for j, item in enumerate(arr[k].split()):
                    o_, span = item.split(":")
                    ts = [t_of["n" + g] for g in keys[ref][int(o_)].split("+") if "n" + g in t_of]
                    m_, c_ = meta["method"][k][j], meta["conf"][k][j]
                    if m_ in "gG" and c_ == "1" and any(t in proper for t in ts):
                        skipped += 1
                        continue
                    for pc in span.split(","):
                        a0, _, z = pc.partition("-")
                        for p_ in range(int(a0), int(z or a0) + 1):
                            s = s_at.get((tb, tc, tv, p_))
                            if s is None:
                                continue
                            for t in ts:
                                h_ = S8_NT_HOW[m_]
                                if (t, s) not in want or h_ < want[(t, s)]:
                                    want[(t, s)] = h_
        got = {(r["t"], r["s"]): r["how"] for r in L if r["other"] == ed}
        R.check(f"{ed} links: equal the pinned compact alignment decoded again (gloss-only proper-noun entries out)",
                got == want, f"{len(got)} links, {skipped} entries left out")
        R.check(f"{ed} links: every s is a word of other/{ed}, n is 1, agree is 1",
                all(r["s"] in forms[ed] and r["n"] == 1 and r["agree"] == 1 for r in L if r["other"] == ed))
        Ae = [a for a in A if a["other"] == ed]
        R.check(f"{ed} link_account: exactly one row per Greek word",
                len(Ae) == len({a["t"] for a in Ae}) == len(P), len(Ae))
        linked = {t for (t, s) in got}
        allc = C.Counter(cls.values())
        linc = C.Counter(cls[t] for t in linked)
        naw = {c for c in ("noun", "verb", "adj") if linc[c] / allc[c] < 0.05}
        R.info(f"{ed} never_a_word classes", sorted(naw))
        badst = 0
        for a in Ae:
            c = cls[a["t"]]
            w_ = ("linked", "") if a["t"] in linked else ("outside_alignment", c) if c not in ("noun", "verb", "adj") \
                else ("never_a_word", c) if c in naw else ("no_counterpart", "")
            badst += (a["state"], a["reason"]) != w_
        R.check(f"{ed} link_account: every state and reason as D13 gives them (unplaced never: MACULA names no Hebrew word)",
                badst == 0, badst)
        st = C.Counter(a["state"] for a in Ae)
        R.check(f"{ed} link_account: the account closes", sum(st.values()) == len(P) and set(st) <= S8_STATES,
                dict(sorted(st.items())))
    lex = {(p["t"], p["n"]): p["lexeme"] for p in P}
    _s8_facts_check(R, "grc", F, L, lex, lambda o, s: f"{o}:form:{forms[o][s]}" if forms[o][s] else None,
                    s6["grc facts rows"])


# ---- stage 09: map.tsv, shared, the facts of the pieces and the equivalents, profile.tsv -------------------------

S9_RELATIONS = ("has_class", "in_domain", "sense_of", "equivalent_of")
S9_MAP_HEADER = ["table", "category", "code", "feature", "value", "reason", "count"]
S9_REASONS = {"upos_not_feature", "no_ud_feature", "no_ud_value", "unknown_value", "lexeme_value"}
# Universal Dependencies v2: the universal features and their values (https://universaldependencies.org/u/feat/)
S9_UD = {
    "PronType": {"Art", "Dem", "Emp", "Exc", "Ind", "Int", "Neg", "Prs", "Rcp", "Rel", "Tot"},
    "NumType": {"Card", "Dist", "Frac", "Mult", "Ord", "Range", "Sets"},
    "Poss": {"Yes"}, "Reflex": {"Yes"}, "Foreign": {"Yes"}, "Abbr": {"Yes"}, "Typo": {"Yes"},
    "Gender": {"Com", "Fem", "Masc", "Neut"}, "Animacy": {"Anim", "Hum", "Inan", "Nhum"},
    "NounClass": set(), "Number": {"Coll", "Count", "Dual", "Grpa", "Grpl", "Inv", "Pauc", "Plur", "Ptan", "Sing",
                                   "Tri"},
    "Case": {"Abs", "Acc", "Erg", "Nom", "Abe", "Ben", "Cau", "Cmp", "Cns", "Com", "Dat", "Dis", "Equ", "Gen", "Ins",
             "Par", "Tem", "Tra", "Voc", "Abl", "Add", "Ade", "All", "Del", "Ela", "Ess", "Ill", "Ine", "Lat", "Loc",
             "Per", "Sbe", "Sbl", "Spl", "Sub", "Sup", "Ter"},
    "Definite": {"Com", "Cons", "Def", "Ind", "Spec"}, "Deixis": set(), "Degree": {"Abs", "Cmp", "Equ", "Pos", "Sup"},
    "VerbForm": {"Conv", "Fin", "Gdv", "Ger", "Inf", "Part", "Sup", "Vnoun"},
    "Mood": {"Adm", "Cnd", "Des", "Imp", "Ind", "Int", "Irr", "Jus", "Nec", "Opt", "Pot", "Prp", "Qot", "Sub"},
    "Tense": {"Fut", "Imp", "Past", "Pqp", "Pres"}, "Aspect": {"Hab", "Imp", "Iter", "Perf", "Prog", "Prosp"},
    "Voice": {"Act", "Antip", "Bfoc", "Cau", "Dir", "Inv", "Lfoc", "Mid", "Pass", "Rcp"},
    "Evident": {"Fh", "Nfh"}, "Polarity": {"Neg", "Pos"}, "Person": {"0", "1", "2", "3", "4"},
    "Polite": {"Elev", "Form", "Humb", "Infm"}, "Clusivity": {"Ex", "In"},
}
S9_STATEMENT_TABLES = ("forms", "paradigms", "markers", "constructions", "orders", "agreement", "frames", "pairs",
                       "clause_links")
S9_EQUIV = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                        "internal-docs/aramaic-hebrew-equivalents-release/v0.1.1/data/words.parquet")
S9_EQUIV_SHA = "90f71ff81c4637fec8a3afe79efecce3c5b7b7732523fe3b587bbc1c87ce2b46"
S9_PARAMS = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                         "internal-docs/source-examples-work/tools/team_parameters.tsv")


def _s9_tsv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        lines = fh.read().split("\n")
    head = lines[0].split("\t")
    return head, [dict(zip(head, ln.split("\t"))) for ln in lines[1:] if ln]


def _s9_pairs(mj):
    if not mj:
        return set()
    out = set()
    for cat, v in json.loads(mj).items():
        for code in (v if isinstance(v, list) else [v]):
            out.add((cat, code))
    return out


def _s9_ud_ok(feature, value):
    if feature not in S9_UD:
        return False
    parts = value.split(",")
    return parts == sorted(parts) and len(set(parts)) == len(parts) and all(p in S9_UD[feature] for p in parts)


def _s9_equiv(P, hbo_lex):
    """equivalent_of recomputed: (arc lexeme, hbo lexeme) -> pieces; and the arc lexeme's pieces."""
    h = S_sha(S9_EQUIV)
    by_full, by_digits = C.defaultdict(set), C.defaultdict(set)
    for r in hbo_lex:
        lem = U.normalize("NFC", r["lemma"])
        st = r["strong"]
        by_full[(lem, st.lstrip("0"))].add(r["lexeme"])
        by_digits[(lem, "".join(ch for ch in st if ch.isdigit()).lstrip("0"))].add(r["lexeme"])
    lex = dict(zip(P["pid"], P["lexeme"]))
    got = C.Counter()
    for r in pq.read_table(S9_EQUIV).to_pylist():
        pid = "o" + r["key"]
        if pid not in lex or not r["hebrew_strong"] or not r["hebrew_lemma"]:
            continue
        k = (U.normalize("NFC", r["hebrew_lemma"]), r["hebrew_strong"].lstrip("0"))
        full, dig = by_full.get(k, set()), by_digits.get(k, set())
        hit = full if full else dig
        if len(hit) == 1:
            got[(lex[pid], next(iter(hit)))] += 1
    return h, got


def stage09(R, build, src):
    with open(S9_PARAMS, encoding="utf-8") as fh:
        params = [ln.rstrip("\n").split("\t") for ln in fh if ln.strip() and not ln.startswith("#")]
    R.check("team_parameters.tsv: header id, question and 195 rows", params[0] == ["id", "question"]
            and len(params) == 196, len(params) - 1)
    params = params[1:]
    hbo_lex = None
    for lang in ("hbo", "arc", "grc"):
        d = os.path.join(build, lang)
        P = pq.read_table(os.path.join(d, "pieces.parquet"),
                          columns=["pid", "lexeme", "class", "marks", "sense", "domain", "shared"]).to_pydict()
        K = pq.read_table(os.path.join(d, "clauses.parquet"), columns=["marks", "shared"]).to_pydict()
        cats = tomllib.load(open(os.path.join(d, "categories.toml"), "rb"))
        declared = {(tb, cat, v["code"]) for tb in ("pieces", "clauses") for cat, spec in cats.get(tb, {}).items()
                    for v in spec.get("values", [])}
        # -- map.tsv
        head, rows = _s9_tsv(os.path.join(d, "map.tsv"))
        R.check(f"{lang} map.tsv: columns {' '.join(S9_MAP_HEADER)}", head == S9_MAP_HEADER, head)
        use = C.Counter()
        for tb, col in (("pieces", P["marks"]), ("clauses", K["marks"])):
            for mj, n in C.Counter(col).items():
                for cat, code in _s9_pairs(mj):
                    use[(tb, cat, code)] += n
        by = C.defaultdict(list)
        for r in rows:
            by[(r["table"], r["category"], r["code"])].append(r)
        R.check(f"{lang} map.tsv: every code of pieces.marks and clauses.marks has a row (mapped or none)",
                set(use) <= set(by), f"{len(use)} codes, {len(set(use) - set(by))} without a row")
        R.check(f"{lang} map.tsv: no row for a code that does not occur", set(by) <= set(use),
                len(set(by) - set(use)))
        R.check(f"{lang} map.tsv: every code is declared in categories.toml", set(by) <= declared,
                sorted(set(by) - declared)[:5])
        bad_none = sum(1 for k, rs in by.items() if any(r["feature"] == "none" for r in rs)
                       and (len(rs) != 1 or rs[0]["value"] or rs[0]["reason"] not in S9_REASONS))
        R.check(f"{lang} map.tsv: a none row stands alone, has no value and a declared reason", bad_none == 0, bad_none)
        bad_ud = [f"{r['feature']}={r['value']}" for r in rows if r["feature"] != "none"
                  and (not _s9_ud_ok(r["feature"], r["value"]) or r["reason"])]
        R.check(f"{lang} map.tsv: every mapped row names a Universal Dependencies feature and value, no reason",
                not bad_ud, bad_ud[:5])
        dupf = sum(1 for rs in by.values() if len({r["feature"] for r in rs}) != len(rs))
        R.check(f"{lang} map.tsv: one value per feature for a code", dupf == 0, dupf)
        badc = sum(1 for r in rows if int(r["count"]) != use.get((r["table"], r["category"], r["code"]), -1))
        R.check(f"{lang} map.tsv: every count equals the recount of pieces (clauses) with the code", badc == 0, badc)
        dcount = {(tb, cat, v["code"]): v["count"] for tb in ("pieces", "clauses")
                  for cat, spec in cats.get(tb, {}).items() for v in spec.get("values", [])}
        badt = sum(1 for r in rows if int(r["count"]) != dcount.get((r["table"], r["category"], r["code"])))
        R.check(f"{lang} map.tsv: every count equals the code's count in categories.toml", badt == 0, badt)
        srt = [(r["table"], r["category"], r["code"], r["feature"]) for r in rows]
        R.check(f"{lang} map.tsv: rows sorted by table, category, code, feature", srt == sorted(srt))
        nones = sorted(k for k, rs in by.items() if rs[0]["feature"] == "none")
        R.info(f"{lang} map.tsv: codes, mapped, none", f"{len(by)}, {len(by) - len(nones)}, {len(nones)}")
        R.info(f"{lang} map.tsv: none by reason", dict(sorted(C.Counter(by[k][0]["reason"] for k in nones).items())))
        # -- shared = marks through map.tsv
        feats = {k: {r["feature"]: r["value"] for r in rs if r["feature"] != "none"} for k, rs in by.items()}
        for tb, D_ in (("pieces", P), ("clauses", K)):
            memo, bad, nulls, clash = {}, 0, 0, 0
            for mj, sh in zip(D_["marks"], D_["shared"]):
                if sh is None:
                    nulls += 1
                    continue
                if mj not in memo:
                    out = {}
                    for cat, code in sorted(_s9_pairs(mj)):
                        for f, v in feats.get((tb, cat, code), {}).items():
                            if f in out and out[f] != v:
                                clash += 1
                            out[f] = v
                    memo[mj] = json.dumps(out, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                bad += memo[mj] != sh
            R.check(f"{lang} {tb}: shared filled on every row", nulls == 0, nulls)
            R.check(f"{lang} {tb}: shared = marks read through map.tsv (D6), no feature given two values",
                    bad == 0 and clash == 0, f"{bad} differ, {clash} clashes")
            R.info(f"{lang} {tb} with at least one shared feature",
                   sum(1 for s in D_["shared"] if s and s != "{}"))
        # -- facts
        F = pq.read_table(os.path.join(d, "facts.parquet")).to_pylist()
        keys = [(f["subject"], f["relation"], f["object"]) for f in F]
        R.check(f"{lang} facts: sorted by (subject, relation, object), each once",
                keys == sorted(keys) and len(set(keys)) == len(keys), len(keys))
        nlex = C.Counter(P["lexeme"])
        want = {}
        for lx, c in zip(P["lexeme"], P["class"]):
            want[(lx, "has_class", c)] = want.get((lx, "has_class", c), 0) + 1
        for lx, dm in zip(P["lexeme"], P["domain"]):
            for code in set((dm or "").split()):
                want[(lx, "in_domain", code)] = want.get((lx, "in_domain", code), 0) + 1
        for lx, sn in zip(P["lexeme"], P["sense"]):
            if sn:
                want[(sn, "sense_of", lx)] = want.get((sn, "sense_of", lx), 0) + 1
        got = {(f["subject"], f["relation"], f["object"]): f for f in F if f["relation"] in S9_RELATIONS[:3]}
        bad = 0
        for k, n in want.items():
            f = got.get(k)
            share = None if k[1] == "sense_of" else n / nlex[k[0]]
            src_ok = f is not None and f["source"] == ("word-senses-ubs" if k[1] != "has_class" else
                                                       ("macula-greek" if lang == "grc" else "macula-hebrew"))
            if f is None or f["count"] != n or f["kind"] != "given" or not src_ok or f["confidence"] is not None \
                    or f["tier"] != "" or (share is None) != (f["share"] is None) \
                    or (share is not None and abs(f["share"] - share) > 1e-12):
                bad += 1
        for rel in S9_RELATIONS[:3]:
            R.info(f"{lang} facts {rel} rows", sum(1 for k in got if k[1] == rel))
        R.check(f"{lang} facts: has_class, in_domain, sense_of equal the recount from pieces (count, share, given)",
                bad == 0 and len(got) == len(want), f"{len(got)} rows, recount {len(want)}, {bad} differ")
        eq = [f for f in F if f["relation"] == "equivalent_of"]
        if lang == "arc":
            if hbo_lex is None:
                _, hbo_lex = _s9_tsv(os.path.join(build, "hbo", "lexemes.tsv"))
            h, want_eq = _s9_equiv(P, hbo_lex)
            R.check("aramaic-hebrew-equivalents words.parquet: sha256 as pinned", h == S9_EQUIV_SHA, h[:12])
            hbo_keys = {r["lexeme"] for r in hbo_lex}
            got_eq = {(f["subject"], f["object"]): f for f in eq}
            bad = sum(1 for k, n in want_eq.items() if k not in got_eq or got_eq[k]["count"] != n
                      or abs(got_eq[k]["share"] - n / nlex[k[0]]) > 1e-12 or got_eq[k]["kind"] != "linked")
            R.check("arc facts: equivalent_of equals the recount from the published list (count, share, linked)",
                    bad == 0 and len(got_eq) == len(want_eq), f"{len(got_eq)} rows, recount {len(want_eq)}, {bad} differ")
            R.check("arc facts: every equivalent_of joins an arc lexeme to an hbo lexeme",
                    all(f["subject"] in nlex and f["object"] in hbo_keys for f in eq), len(eq))
        else:
            R.check(f"{lang} facts: no equivalent_of (arc only)", not eq, len(eq))
        # -- profile.tsv
        head, prof = _s9_tsv(os.path.join(d, "profile.tsv"))
        R.check(f"{lang} profile.tsv: columns id, question, value, statement, count",
                head == ["id", "question", "value", "statement", "count"], head)
        R.check(f"{lang} profile.tsv: the 195 questionnaire rows, ids and questions as the list gives them",
                [(r["id"], r["question"]) for r in prof] == [tuple(p) for p in params], len(prof))
        stm = {}
        for tb in S9_STATEMENT_TABLES:
            t = pq.read_table(os.path.join(d, f"{tb}.parquet"), columns=["id", "count"]).to_pydict()
            stm.update(zip(t["id"], t["count"]))
        bad_val = [r["id"] for r in prof if r["value"] not in {"?", "0", "1", "2", "3"}]
        R.check(f"{lang} profile.tsv: every value is ?, 0, 1, 2 or 3", not bad_val, bad_val[:5])
        bad_ev, bad_q = [], []
        for r in prof:
            ids, cnts = r["statement"].split(), r["count"].split()
            if r["value"] == "?":
                if ids or cnts:
                    bad_q.append(r["id"])
                continue
            if not ids or len(ids) != len(cnts) or any(i not in stm or str(stm[i]) != c for i, c in zip(ids, cnts)):
                bad_ev.append(r["id"])
        R.check(f"{lang} profile.tsv: every answered row has evidence; every statement id resolves and its count is "
                f"the row's count", not bad_ev, bad_ev[:5])
        R.check(f"{lang} profile.tsv: an unanswered row (?) has no evidence", not bad_q, bad_q[:5])
        ans = [r for r in prof if r["value"] != "?"]
        R.info(f"{lang} profile answered", f"{len(ans)} of {len(prof)}: " + " ".join(f"{r['id']}={r['value']}"
                                                                                     for r in ans))


# ---- stage 10: sources.json, COLUMNS.md, READ-FIRST.md, glossed chapters, no English, rebuild ----------------------

import hashlib as _hl

S10_LANGS = ("hbo", "arc", "grc")
S10_ROOT = os.path.dirname(os.path.dirname(HERE))
S10_GLOSSED = os.path.join(S10_ROOT, "internal-docs/source-examples-work/glossed")
S10_CHAPTERS = [("hbo", "GEN", 22, "genesis-22"), ("hbo", "PSA", 23, "psalm-23"), ("hbo", "LEV", 19, "leviticus-19"),
                ("hbo", "ISA", 40, "isaiah-40"), ("arc", "DAN", 3, "daniel-3-aramaic"), ("grc", "MRK", 4, "mark-4"),
                ("grc", "ROM", 8, "romans-8"), ("grc", "HEB", 1, "hebrews-1")]
S10_GLOSS_HEADER = "| t.n | word | piece | kind | lexeme | class | marks | head | label | clause | participant |"
# SPEC section 4: the columns of every table that has a fixed list (in file order)
_ST = ["id"]
S10_SPEC_COLS = {
    "words.parquet": WORD_COLS, "pieces.parquet": PIECE_COLS, "clauses.parquet": CLAUSE_COLS,
    "constituents.parquet": CONST_COLS, "lexemes.tsv": LEX_COLS,
    "participants.tsv": ["ent", "type", "name", "sex", "words"],
    "forms.parquet": _ST + ["lexeme", "marks", "form", "count", "against", "places"],
    "paradigms.parquet": _ST + ["class", "marks", "lexemes", "forms", "count", "against", "places"],
    "markers.parquet": _ST + ["lexeme", "kind", "category", "value", "count", "against", "places"],
    "constructions.parquet": _ST + ["level", "rule", "children", "head_at", "count", "against", "places"],
    "orders.parquet": _ST + ["rel", "head_class", "dep_class", "before", "after", "count", "against", "places"],
    "agreement.parquet": _ST + ["rel", "category", "agree", "differ", "n_a", "count", "against", "places"],
    "frames.parquet": _ST + ["lexeme", "stem", "frame", "count", "against", "places"],
    "pairs.parquet": _ST + ["head", "rel", "dep", "count", "against", "places"],
    "clause_links.parquet": _ST + ["kind", "connective", "parent_kind", "role", "count", "against", "places"],
    "exceptions.parquet": ["statement", "place"],
    "facts.parquet": ["subject", "relation", "object", "kind", "method", "source", "confidence", "count", "share", "tier"],
    "links.parquet": ["t", "n", "other", "s", "how", "agree"],
    "link_account.parquet": ["t", "n", "other", "state", "reason"],
    "other/*/words.parquet": ["s", "id", "book", "chapter", "verse", "w", "text", "lemma", "class"],
}
S10_BOOKS = set("GEN EXO LEV NUM DEU JOS JDG RUT 1SA 2SA 1KI 2KI 1CH 2CH EZR NEH EST JOB PSA PRO ECC SNG ISA JER LAM EZK "
                "DAN HOS JOL AMO OBA JON MIC NAM HAB ZEP HAG ZEC MAL MAT MRK LUK JHN ACT ROM 1CO 2CO GAL EPH PHP COL 1TH "
                "2TH 1TI 2TI TIT PHM HEB JAS 1PE 2PE 1JN 2JN 3JN JUD REV".split())
# the format's own value lists (SPEC section 4, 6, 7): column -> codes
S10_FORMAT = {
    "kind": {"stem", "prefix", "suffix"}, "head_basis": {"index", "conj", "compound", "none", "root"},
    "who_basis": {"", "explicit", "pronominal", "subject", "chain"}, "pred_kind": {"v", "vc", "p", "none"},
    "frame_role": {"A0", "A1", "A2", "AA"}, "level": {"clause", "phrase"}, "markers.kind": {"prefix", "suffix", "word"},
    "agreement.category": {"gender", "number", "person", "case", "state"},
    "relation": {"has_class", "in_domain", "sense_of", "equivalent_of", "father", "mother", "offspring", "sibling",
                 "partner", "tribe", "group_origin", "rendered_by"},
    "facts.kind": {"given", "derived", "linked"}, "type": {"person", "place", "group", "deity", "realia", "flora", "fauna"},
    "sex": {"", "m", "f"}, "state": {"linked", "outside_alignment", "never_a_word", "unplaced", "no_counterpart"},
    "other": {"lxx", "heb_scg", "heb_mod"}, "profile.value": {"?", "0", "1", "2", "3"},
    "map.reason": {"", "upos_not_feature", "no_ud_feature", "no_ud_value", "unknown_value", "lexeme_value"},
    "map.table": {"pieces", "clauses"},
}
S10_HOMOGRAPH = re.compile(r" \((I|II|III|IV|V)\)$")
S10_C0 = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)*$")
S10_NAME = re.compile(r"^[A-Za-z0-9_\-]+$")
S10_DIGITS = re.compile(r"^[0-9]+$")
S10_ENT = re.compile(r"^(person|place|group|deity|realia|flora|fauna):e[0-9a-f]{10}$")
S10_LEX = re.compile(r"^lex:(hbo|arc|grc):.+")


def _s10_sha(path):
    h = _hl.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def _s10_d3(v, D):
    """A D3 label of an edge inside a word (not in relmap.tsv, which maps word labels): a role code, `root`,
    `<rule>:<place>`, `run:<place>` or `c:<place>`."""
    if v in D["role"] or v == "root":
        return True
    m = re.match(r"^([A-Za-z0-9\-]+):([0-9]+)$", v)
    return bool(m)


def _s10_try(fn, v):
    try:
        return bool(fn(v))
    except (ValueError, TypeError, KeyError):
        return False


def _s10_letters_ok(s):
    """Hebrew or Greek letters and marks, punctuation, spaces; nothing else (SPEC 10, no English)."""
    for ch in s:
        cp = ord(ch)
        if 0x0590 <= cp <= 0x05FF or 0xFB1D <= cp <= 0xFB4F or 0x0370 <= cp <= 0x03FF or 0x1F00 <= cp <= 0x1FFF:
            continue
        if 0x0300 <= cp <= 0x036F or cp == 0x02B9:   # U+02B9: the NFC form of U+0374 GREEK NUMERAL SIGN
            continue
        if U.category(ch)[0] in "PZ":
            continue
        return False
    return True


def _s10_gloss_vocab():
    files = sorted(glob.glob(os.path.join(HEB_LOWFAT, "*.xml"))) + sorted(glob.glob(os.path.join(GRC_LOWFAT, "*.xml")))
    pat = re.compile(r'\s(?:gloss|english)="([^"]*)"')
    word = re.compile(r"[A-Za-z]+")
    vocab = set()
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for g in pat.findall(fh.read()):
                vocab.update(w.lower() for w in word.findall(g))
    return vocab, len(files)


def _s10_table(path):
    if path.endswith(".parquet"):
        t = pq.read_table(path)
        return t.column_names, {c: t.column(c).to_pylist() for c in t.column_names}, t.num_rows
    head, rows = _s9_tsv(path)
    return head, {c: [r[c] for r in rows] for c in head}, len(rows)


def _s10_files(d):
    out = sorted(f for f in os.listdir(d) if f.endswith((".parquet", ".tsv")))
    out += sorted(os.path.join("other", o, "words.parquet") for o in os.listdir(os.path.join(d, "other")))
    return out


def _s10_columns_md(path):
    """file -> (rows, [column names]) as COLUMNS.md part 2 lists them."""
    out, cur = {}, None
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    part2 = text.split("## Part 2. The files as built", 1)[1]
    for ln in part2.split("\n"):
        m = re.match(r"^### `([^`]+)`: ([0-9,]+) rows, (\d+) columns", ln)
        if m:
            cur = m.group(1)
            out[cur] = (int(m.group(2).replace(",", "")), [])
            continue
        m = re.match(r"^\| `([^`]+)` \| ", ln)
        if m and cur:
            out[cur][1].append(m.group(1))
    return out, text


def _s10_declared(d, lang):
    """The declared code sets of one language: from categories.toml, relmap.tsv, map.tsv, lexemes, participants,
    clauses, sources.json, and the format's own lists."""
    with open(os.path.join(d, "categories.toml"), "rb") as fh:
        cats = tomllib.load(fh)
    D = {f"{t}.{c}": {v["code"] for v in sec["values"]} for t, secs in cats.items() for c, sec in secs.items()}
    _, rel = _s9_tsv(os.path.join(d, "relmap.tsv"))
    D["rel"] = {r["label"] for r in rel}
    D["rel_shared"] = {r["shared"] for r in rel}
    _, mp = _s9_tsv(os.path.join(d, "map.tsv"))
    D["map.feature"] = {r["feature"] for r in mp}
    D["map.value"] = {r["value"] for r in mp}
    _, lx = _s9_tsv(os.path.join(d, "lexemes.tsv"))
    D["lexeme"] = {r["lexeme"] for r in lx}
    _, pa_ = _s9_tsv(os.path.join(d, "participants.tsv"))
    D["ent"] = {r["ent"] for r in pa_}
    # SPEC 1: in GEN 31:47 and DAN 2:4 a clause or a parent may lie in the other Tanakh table, so hbo and arc read both
    tabs = [lang] if lang == "grc" else ["hbo", "arc"]
    D["clause"] = set().union(*(set(pq.read_table(os.path.join(os.path.dirname(d), t, "clauses.parquet"), columns=["clause"])
                                    .column("clause").to_pylist()) for t in tabs))
    with open(os.path.join(d, "sources.json"), encoding="utf-8") as fh:
        D["source"] = set(json.load(fh)["sources"])
    D["role"] = ROLE_SET
    D["category names"] = {c for secs in cats.values() for c in secs} | {r["category"] for r in mp}
    piece_cats = {k.split(".", 1)[1] for k in D if k.startswith("pieces.")} - {"class", "kind"}
    D["piece_codes"] = set().union(*(D[f"pieces.{c}"] for c in piece_cats))
    D["piece_cats"] = piece_cats
    return D


def _s10_coded(lang, f, cols, D):
    """(column, value) -> None if declared, else the reason. Covers the coded columns of SPEC 4.10; returns a dict
    column -> checker, and a set of columns whose codes are names of the source (not codes of 4.10: form check only)."""
    cls = D["pieces.class"]
    lex_or_empty = D["lexeme"] | {""}
    ck = {}
    names = {}

    def mem(s):
        return lambda v: v in s

    def toks(pred):
        return lambda v: v == "" or all(pred(x) for x in v.split(" "))

    def marks(prefix):
        def ok(v):
            m = json.loads(v)
            return all(f"{prefix}.{k}" in D and all(str(y) in D[f"{prefix}.{k}"] for y in (x if isinstance(x, list) else [x]))
                       for k, x in m.items())
        return ok

    def shared(v):
        m = json.loads(v)
        return all(k in D["map.feature"] and x in D["map.value"] for k, x in m.items())
    base = f.split("/")[-1] if not f.startswith("other/") else "other/*/words.parquet"
    if base in ("words.parquet",):
        ck.update(book=mem(S10_BOOKS), head_basis=mem(S10_FORMAT["head_basis"]), rel=mem(D["rel"]),
                  rel_shared=mem(D["rel_shared"]), clause=mem(D["clause"] | {""}))
    elif base == "pieces.parquet":
        ck.update(kind=mem(S10_FORMAT["kind"]), lexeme=mem(D["lexeme"]), **{"class": mem(cls)}, marks=marks("pieces"),
                  head_basis=mem(S10_FORMAT["head_basis"]), rel=lambda v: v in D["rel"] or _s10_d3(v, D), who=toks(mem(D["ent"])),
                  who_basis=mem(S10_FORMAT["who_basis"]), sense=toks(S10_DIGITS.match), domain=toks(S10_DIGITS.match),
                  shared=shared)
    elif base == "clauses.parquet":
        ck.update(book=mem(S10_BOOKS), parent=mem(D["clause"] | {""}), via=lambda v: v == "" or bool(S10_C0.match(v)),
                  role=mem(D["role"] | {""}), role_wrapped=mem(D["role"] | {""}), pred_kind=mem(S10_FORMAT["pred_kind"]),
                  marks=marks("clauses"), shared=shared, speaker=mem(D["ent"] | {""}), addressee=mem(D["ent"] | {""}))
        names.update(rule=S10_NAME.match, pattern=lambda v: v == "" or bool(S10_NAME.match(v)))
    elif base == "constituents.parquet":
        names.update(frame_role=toks(lambda x: bool(re.match(r"^A[0-9A]{1,2}$", x))))
        ck.update(clause=mem(D["clause"]), role=mem(D["role"]), **{"class": lambda v: v == "" or bool(S10_C0.match(v))}, sem_role=mem(D.get("constituents.sem_role", set()) | {""}),
                  prep=mem(lex_or_empty))
    elif base == "lexemes.tsv":
        ck.update(lexeme=mem(D["lexeme"]), **{"class": mem(cls)}, strong=toks(lambda x: bool(re.match(r"^[0-9]{4}[a-z]?$|^[0-9]+(\+[0-9]+)*$|^[0-9]{4}[a-z]?(\|[0-9]{4}[a-z]?)+$", x))),
                  senses=toks(lambda x: bool(re.match(r"^[0-9]+:[0-9]+$", x))), domains=toks(lambda x: bool(re.match(r"^[0-9]+:[0-9]+$", x))))
    elif base == "participants.tsv":
        ck.update(ent=mem(D["ent"]), type=mem(S10_FORMAT["type"]), sex=mem(S10_FORMAT["sex"]))
    elif base == "forms.parquet":
        ck.update(lexeme=mem(D["lexeme"]), marks=marks("pieces"))
    elif base == "paradigms.parquet":
        ck.update(**{"class": mem(cls)}, marks=marks("pieces"))
    elif base == "markers.parquet":
        ck.update(lexeme=mem(D["lexeme"]), kind=mem(S10_FORMAT["markers.kind"]), category=mem(D["piece_cats"]),
                  value=mem(D["piece_codes"]))
    elif base == "constructions.parquet":
        ck.update(level=mem(S10_FORMAT["level"]))
        names.update(rule=S10_NAME.match, children=toks(S10_NAME.match))
    elif base == "orders.parquet":
        ck.update(rel=mem(D["rel"]), head_class=mem(cls), dep_class=mem(cls))
    elif base == "agreement.parquet":
        ck.update(rel=mem(D["rel"]), category=mem(S10_FORMAT["agreement.category"]))
    elif base == "frames.parquet":
        ck.update(lexeme=mem(D["lexeme"]), stem=mem(D.get("pieces.stem", set()) | {""}),
                  frame=toks(lambda x: x in D["role"] or (x.startswith("pp:") and x[3:] in D["lexeme"])))
    elif base == "pairs.parquet":
        ck.update(head=mem(D["lexeme"]), rel=mem(D["rel"]), dep=mem(D["lexeme"]))
    elif base == "clause_links.parquet":
        ck.update(kind=mem(D.get("clauses.kind", set()) | {""}), connective=toks(mem(D["lexeme"])),
                  parent_kind=mem(D.get("clauses.kind", set()) | {"", "top"}), role=mem(D["role"] | {""}))
    elif base == "facts.parquet":
        ck.update(relation=mem(S10_FORMAT["relation"]), kind=mem(S10_FORMAT["facts.kind"]), source=mem(D["source"]))
        names.update(method=lambda v: bool(re.match(r"^[A-Za-z0-9_.:\-]+$", v)))
    elif base == "links.parquet":
        ck.update(other=mem(S10_FORMAT["other"]))
        names.update(how=S10_NAME.match)
    elif base == "link_account.parquet":
        ck.update(other=mem(S10_FORMAT["other"]), state=mem(S10_FORMAT["state"]))
    elif base == "other/*/words.parquet":
        ck.update(book=mem(S10_BOOKS))
        names.update(**{"class": lambda v: v in ("", None) or bool(S10_NAME.match(v))})
    elif base == "map.tsv":
        ck.update(table=mem(S10_FORMAT["map.table"]), reason=mem(S10_FORMAT["map.reason"]),
                  code=lambda v: v in D["piece_codes"] or any(v in s for k, s in D.items() if k.startswith(("clauses.", "pieces."))))
    elif base == "relmap.tsv":
        ck.update(label=mem(D["rel"]), shared=lambda v: v == "none" or v.split(":")[0] in UD_RELATIONS)
    elif base == "profile.tsv":
        ck.update(value=mem(S10_FORMAT["profile.value"]))
    return {c: v for c, v in ck.items() if c in cols}, {c: v for c, v in names.items() if c in cols}


S10_SCRIPT_COLS = {"words.parquet": ["text", "after"], "pieces.parquet": ["text"], "lexemes.tsv": ["lemma"],
                   "participants.tsv": ["name"], "forms.parquet": ["form"], "other/*/words.parquet": ["text", "lemma"]}
S10_JSON_COLS = {"marks", "shared"}


def _s10_tokens(col, v):
    if not isinstance(v, str) or v == "":
        return []
    if col in S10_JSON_COLS and v.startswith("{"):
        m = json.loads(v)
        return [str(k) for k in m] + [str(y) for x in m.values() for y in (x if isinstance(x, list) else [x])]
    if col == "question":
        return [v]   # the questionnaire's sentences: compared whole, as SPEC 10 states the check
    return v.split(" ")


def stage10(R, build, src, compare=None):
    R.section("sources.json")
    for lang in S10_LANGS:
        d = os.path.join(build, lang)
        p = os.path.join(d, "sources.json")
        R.check(f"{lang} sources.json exists", os.path.exists(p))
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            doc = json.load(fh)
        from validate_examples_s20 import committed_sha   # stage 56: a working copy changed outside the run
        nfiles, bad, missing, drifted = 0, [], [], []
        for key, s in sorted(doc["sources"].items()):
            for rel, meta in s["files"].items():
                nfiles += 1
                path = os.path.join(os.path.dirname(S10_ROOT), rel[3:]) if rel.startswith("../") else os.path.join(S10_ROOT, rel)
                if not os.path.exists(path):
                    missing.append(rel)
                elif _s10_sha(path) != meta["sha256"]:
                    (drifted if committed_sha(path) == meta["sha256"] else bad).append(rel)
        R.check(f"{lang} sources.json: every file listed exists and has the sha256 listed", not bad and not missing,
                f"{nfiles} files, {len(missing)} missing, {len(bad)} differ, "
                f"{len(drifted)} changed in a working copy but held unchanged at its repository's HEAD")
        for rel in drifted:
            R.info(f"{lang} sources.json: working copy differs from the listed sha256, HEAD's copy matches", rel)
        R.check(f"{lang} sources.json: every source has repository, pin, licence and at least one file",
                all(s.get("repository") and s.get("pin") and s.get("licence") and s["files"] for s in doc["sources"].values()),
                len(doc["sources"]))
        fsrc = set(pq.read_table(os.path.join(d, "facts.parquet"), columns=["source"]).column("source").to_pylist())
        R.check(f"{lang} sources.json: every facts.source is a key of sources.json", fsrc <= set(doc["sources"]), sorted(fsrc))
        R.check(f"{lang} sources.json: pyarrow version as running", doc["pyarrow"] == pq.pa.__version__ if hasattr(pq, "pa") else
                doc["pyarrow"] == __import__("pyarrow").__version__, doc["pyarrow"])
        bad_b = [k for k, v in doc["builder"]["files"].items() if _s10_sha(os.path.join(S10_ROOT, k)) != v["sha256"]]
        R.check(f"{lang} sources.json: builder files as listed (sha256)", not bad_b, f"{len(doc['builder']['files'])} files, {len(bad_b)} differ")
        R.info(f"{lang} sources.json builder commit", f"{doc['builder']['commit']}; files not committed: "
               f"{sum(1 for v in doc['builder']['files'].values() if not v['committed'])}")
        R.check(f"{lang} sources.json: licence of the example stated", bool(doc.get("licence")), doc.get("licence", "")[:40])
        glx = doc["sources"].get("glaux-lxx", {})
        if lang != "grc":
            R.check(f"{lang} sources.json: GLAUx's annotation method stated", "automatic" in glx.get("method", ""), glx.get("method", ""))

    R.section("COLUMNS.md")
    for lang in S10_LANGS:
        d = os.path.join(build, lang)
        p = os.path.join(d, "COLUMNS.md")
        R.check(f"{lang} COLUMNS.md exists", os.path.exists(p))
        listed, text = _s10_columns_md(p)
        files = _s10_files(d)
        R.check(f"{lang} COLUMNS.md: lists every table file of the folder, and no other", sorted(listed) == sorted(files),
                f"{len(files)} files, listed {len(listed)}")
        wrong, spec_wrong = [], []
        for f in files:
            cols, _, n = _s10_table(os.path.join(d, f))
            if listed.get(f) != (n, cols):
                wrong.append(f)
            key = "other/*/words.parquet" if f.startswith("other/") else f
            if key in S10_SPEC_COLS and cols != S10_SPEC_COLS[key]:
                spec_wrong.append((f, cols))
        R.check(f"{lang} COLUMNS.md: rows and columns of every file equal the file", not wrong, wrong)
        R.check(f"{lang} tables: columns as SPEC section 4 lists them (fixed-list tables)", not spec_wrong,
                f"{sum(1 for f in files if ('other/*/words.parquet' if f.startswith('other/') else f) in S10_SPEC_COLS)} files; {spec_wrong}")
        R.info(f"{lang} tables without a fixed column list in SPEC 4", [f for f in files if f not in S10_SPEC_COLS and not f.startswith("other/")])
        R.check(f"{lang} COLUMNS.md: holds SPEC section 4", "4.10 The small files" in text and "4.1 `words.parquet`" in text)

    R.section("READ-FIRST.md")
    for lang in S10_LANGS:
        p = os.path.join(build, lang, "READ-FIRST.md")
        ok = os.path.exists(p)
        text = open(p, encoding="utf-8").read() if ok else ""
        R.check(f"{lang} READ-FIRST.md: exists with its four sections", ok and all(f"## {i}." in text for i in (1, 2, 3, 4)))

    R.section("glossed chapters")
    gdir = S10_GLOSSED if os.path.basename(os.path.normpath(build)) == "b1" else os.path.join(build, "cache", "glossed")
    for lang, book, ch, name in S10_CHAPTERS:
        p = os.path.join(gdir, name + ".md")
        if not os.path.exists(p):
            R.check(f"glossed {name}.md exists", False)
            continue
        W = pq.read_table(os.path.join(build, lang, "words.parquet"), columns=["t", "book", "chapter", "verse"]).to_pylist()
        ts = {w["t"] for w in W if w["book"] == book and w["chapter"] == ch}
        verses = {w["verse"] for w in W if w["book"] == book and w["chapter"] == ch}
        npc = sum(1 for t in pq.read_table(os.path.join(build, lang, "pieces.parquet"), columns=["t"]).column("t").to_pylist() if t in ts)
        text = open(p, encoding="utf-8").read()
        heads = re.findall(rf"^## {book} {ch}:(\d+)$", text, re.M)
        rows = re.findall(r"^\| \d+\.\d+ \|", text, re.M)
        R.check(f"glossed {name}: one table per verse, one row per piece, the specified columns, no gloss column",
                sorted(map(int, heads)) == sorted(verses) and len(rows) == npc and text.count(S10_GLOSS_HEADER) == len(verses)
                and "gloss |" not in text.split("\n## ", 1)[-1].split("\n")[2],
                f"{len(heads)} verses of {len(verses)}, {len(rows)} rows of {npc} pieces")

    R.section("no English")
    vocab, nlow = _s10_gloss_vocab()
    R.info("MACULA gloss vocabulary (words of gloss and english, lower-cased)", f"{len(vocab)} words from {nlow} lowfat files")
    for lang in S10_LANGS:
        d = os.path.join(build, lang)
        D = _s10_declared(d, lang)
        undeclared, name_bad, script_bad = C.Counter(), C.Counter(), C.Counter()
        numeral, homograph = C.Counter(), C.Counter()
        script_n = 0
        code_words, english = C.Counter(), C.Counter()
        n_coded = n_names = n_strings = 0
        declared_any = set().union(*(v for v in D.values() if isinstance(v, set)))
        declared_any |= set().union(*S10_FORMAT.values()) | S10_BOOKS
        for f in _s10_files(d):
            cols, data, _ = _s10_table(os.path.join(d, f))
            ck, nm = _s10_coded(lang, f, cols, D)
            key = "other/*/words.parquet" if f.startswith("other/") else f
            for c, fn in ck.items():
                n_coded += 1
                for v, k in C.Counter(data[c]).items():
                    if v is None:
                        continue
                    if not fn(v):
                        undeclared[(f, c, v)] += k
            for c, fn in nm.items():
                n_names += 1
                for v, k in C.Counter(data[c]).items():
                    if v not in (None, "") and not fn(v):
                        name_bad[(f, c, v)] += k
            for c in S10_SCRIPT_COLS.get(key, []):
                for v, k in C.Counter(data[c]).items():
                    script_n += k
                    if v in (None, ""):
                        continue
                    if "\u02b9" in v:
                        numeral[(f, c, v)] += k
                    if lang == "grc" and key == "lexemes.tsv" and c == "lemma" and S10_HOMOGRAPH.search(v):
                        homograph[(f, c, v)] += k   # SPEC 3: the Greek lemma "with its homograph mark, δοῦλος (II)"
                        v = S10_HOMOGRAPH.sub("", v)
                    if not _s10_letters_ok(v):
                        script_bad[(f, c, v)] += k
            for c in cols:
                vals = data[c]
                if not vals or not isinstance(next((x for x in vals if x is not None), 0), str):
                    continue
                n_strings += 1
                for v, k in C.Counter(vals).items():
                    for tok in _s10_tokens(c, v):
                        if tok.lower() in vocab:
                            sub = ck.get(c) or nm.get(c)
                            declared = tok in declared_any or (not v.startswith("{") and sub is not None and _s10_try(sub, tok))
                            if declared:
                                code_words[(tok, f"{f}:{c}")] += k
                            else:
                                english[(f, c, tok)] += k
        R.check(f"{lang} no English (a): every value of a coded column is a declared code", not undeclared,
                f"{n_coded} coded columns; {sum(undeclared.values())} values off the lists: {sorted(undeclared.items())[:5]}")
        R.check(f"{lang} no English (a'): source names (rule, pattern, children, method, how, other class) are names, not prose",
                not name_bad, f"{n_names} columns; {sorted(name_bad.items())[:5]}")
        R.check(f"{lang} no English (b): text, after, lemma, name, form in Hebrew or Greek script, punctuation or empty",
                not script_bad, f"{script_n} values; {sum(script_bad.values())} off: {sorted(script_bad.items())[:5]}")
        CO = pq.read_table(os.path.join(d, "constituents.parquet"), columns=["class", "frame_role"]).to_pydict()
        R.info(f"{lang} constituents with an empty class (a compound `c` with a role; stage 04)", sum(1 for x in CO["class"] if x == ""))
        fr = C.Counter(x for v in CO["frame_role"] for x in v.split() if x not in S10_FORMAT["frame_role"])
        R.info(f"{lang} frame labels the specification does not list (given; SPEC 4.4 names A0, A1, A2, AA)", dict(sorted(fr.items())))
        R.info(f"{lang} script exceptions: Greek lemmas with the homograph mark SPEC 3 prescribes ((I), (II))",
               f"{sum(homograph.values())}: " + ", ".join(sorted(x[2] for x in homograph)))
        R.info(f"{lang} script exceptions: values with the Greek numeral sign (U+0374, NFC U+02B9)",
               f"{sum(numeral.values())}: " + ", ".join(f"{x[0]}:{x[1]} {x[2]}" for x in sorted(numeral)))
        R.check(f"{lang} no English (c): no string value equals a word of MACULA's gloss vocabulary unless a declared code",
                not english, f"{n_strings} string columns; {sum(english.values())} values: {sorted(english.items())[:8]}")
        by_code = C.defaultdict(lambda: [0, set()])
        for (tok, where), k in code_words.items():
            by_code[tok][0] += k
            by_code[tok][1].add(where)
        STASH[f"s10 {lang} code words"] = {t: (n, sorted(w)) for t, (n, w) in sorted(by_code.items())}
        R.info(f"{lang} exception list: declared codes that are also English gloss words",
               f"{len(by_code)} codes, {sum(v[0] for v in by_code.values())} values: " +
               ", ".join(f"{t} {n}" for t, (n, _) in sorted(by_code.items(), key=lambda kv: (-kv[1][0], kv[0]))))
        _, prof = _s9_tsv(os.path.join(d, "profile.tsv"))
        R.info(f"{lang} profile.tsv question: English sentences (Grambank's questionnaire) that the check's letter does not "
               f"catch; for the specification", f"{sum(1 for r in prof if r['question'])} values")

    if compare:
        R.section("rebuild")
        b2 = os.path.join(os.path.dirname(build), compare)

        def walk(root):
            out = {}
            for dp, _, fs in os.walk(root):
                for fn in fs:
                    out[os.path.relpath(os.path.join(dp, fn), root)] = os.path.join(dp, fn)
            return out
        A, B = walk(build), walk(b2)
        for lang in S10_LANGS:
            ka = {k for k in A if k.startswith(lang + "/") and not k.endswith("VALIDATION.md")}
            kb = {k for k in B if k.startswith(lang + "/") and not k.endswith("VALIDATION.md")}
            differ = [k for k in sorted(ka & kb) if _s10_sha(A[k]) != _s10_sha(B[k])]
            R.check(f"{lang} rebuild: every file of {os.path.basename(build)}/{lang} has the same sha256 in {compare} (VALIDATION.md aside)",
                    ka == kb and not differ, f"{len(ka)} files, {len(ka ^ kb)} in one build only, {len(differ)} differ {differ}")
        ga = {k: os.path.join(S10_GLOSSED, k) for k in os.listdir(S10_GLOSSED) if k.endswith(".md")} if os.path.basename(os.path.normpath(build)) == "b1" else {}
        gb = {k[len("cache/glossed/"):]: v for k, v in B.items() if k.startswith("cache/glossed/")}
        gdiff = [k for k in sorted(set(ga) & set(gb)) if _s10_sha(ga[k]) != _s10_sha(gb[k])]
        R.check(f"rebuild: the glossed chapters are the same in {compare}", set(ga) == set(gb) and not gdiff,
                f"{len(ga)} files, {len(gdiff)} differ")
        ca = {k for k in A if k.startswith("cache/")}
        cb = {k for k in B if k.startswith("cache/") and not k.startswith("cache/glossed/")}
        both = sorted(ca & cb)
        cdiff = [k for k in both if _s10_sha(A[k]) != _s10_sha(B[k])]
        R.info(f"rebuild, cache (not tables): files in both {len(both)}, same {len(both) - len(cdiff)}, differ {cdiff}; "
               f"only in {os.path.basename(build)} (scratch of earlier stages) {len(ca - cb)}; only in {compare} {len(cb - ca)}", "")


# ---- stage 14 (SPEC 1.1): terms.tsv ------------------------------------------------------------------------------
S14_MASTER = os.path.join(HERE, "..", "..", "internal-docs", "source-examples-spec", "terms.tsv")
S14_COLS = ["category", "code", "hbo", "grc", "from_hbo", "from_grc", "source_hbo", "source_grc", "note", "named_by",
            "checked"]
S14_CATS = ["relation", "time", "aspect", "line_kind", "sem_role", "ent_type"]
S14_ENT = ["person", "place", "group", "deity", "realia", "flora", "fauna"]   # SPEC 3


def _s14_c0(v):
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]", "_", v.lower())).strip("_")


def _s14_tsv(path):
    csv.field_size_limit(1 << 30)
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))


def _s14_script_ok(term, lang):
    if not term or term != term.strip() or "  " in term:
        return False
    for ch in term:
        o = ord(ch)
        if ch == " ":
            continue
        if lang == "hbo" and 0x0591 <= o <= 0x05F4:
            continue
        if lang == "grc" and (0x0370 <= o <= 0x03FF or 0x1F00 <= o <= 0x1FFF or 0x0300 <= o <= 0x036F):
            continue
        return False
    return True


def _s14_rule(R, b1):
    """Rule T recomputed: -> {(cat, code, lang): (lemma NFC, key)}."""
    arcv = {(r["book"], r["chapter"], r["verse"]) for r in
            pq.read_table(os.path.join(b1, "arc", "words.parquet"), columns=["book", "chapter", "verse"]).to_pylist()}
    ref = {}
    for r in pq.read_table(os.path.join(HERE, "data", "clause-columns", "hebrew.parquet"),
                           columns=["clause_key", "ref"]).to_pylist():
        bk, rest = r["ref"].split(" ", 1)
        ch, vs = rest.split(".")[0].split(":")
        ref[r["clause_key"]] = (bk, int(ch), int(vs))
    lex, used = {}, {}
    for lang in ("hbo", "grc"):
        lex[lang] = C.defaultdict(list)
        for r in _s14_tsv(os.path.join(b1, lang, "lexemes.tsv")):
            lex[lang][U.normalize("NFC", r["lemma"])].append(r)
        used[lang] = C.Counter(k for m in pq.read_table(os.path.join(b1, lang, "clauses.parquet"),
                                                        columns=["marks"]).column("marks").to_pylist()
                               for k in json.loads(m).get("connective", []))
    out = {}
    for cat, path, vcol, icol in (("relation", "connectives/clauses.tsv", "relation", "conn"),
                                  ("sem_role", "arg-roles/roles.tsv", "role", "prep_lemma")):
        n = {"hbo": C.Counter(), "grc": C.Counter()}
        tot = {"hbo": C.Counter(), "grc": C.Counter()}
        left = 0
        for r in _s14_tsv(os.path.join(HERE, "data", path)):
            lang, v = r["corpus"], r[vcol]
            if v in ("", "-"):
                continue
            if lang == "hbo" and ref.get(r["clause_key"]) in arcv:
                left += 1
                continue
            tot[lang][_s14_c0(v)] += 1
            for it in {U.normalize("NFC", x) for x in r[icol].split()}:
                n[lang][(_s14_c0(v), it)] += 1
        R.info(f"tan terms rule T {cat}: hbo rows left out (verse with Aramaic clauses)", left)
        for lang in ("hbo", "grc"):
            per_item = C.defaultdict(list)
            for (v, it), k in n[lang].items():
                per_item[it].append((k, v))
            cand = C.defaultdict(list)
            for it, lst in per_item.items():
                lst.sort(reverse=True)
                if len(lst) > 1 and lst[0][0] == lst[1][0]:
                    continue
                k, v = lst[0]
                if k >= 0.05 * tot[lang][v]:
                    cand[v].append((-k, it))
            for v, lst in cand.items():
                it = min(lst)[1]
                rows = lex[lang].get(it, [])
                if not rows:
                    continue
                if cat == "relation":
                    rows = sorted(rows, key=lambda r: (-used[lang][r["lexeme"]], -int(r["count"]), r["lexeme"]))
                else:
                    rows = sorted(rows, key=lambda r: (r["class"] != "prep", -int(r["count"]), r["lexeme"]))
                out[(cat, v, lang)] = (it, rows[0]["lexeme"])
    return out


def stage14(R, build, src):
    R.section("terms")
    b1 = os.path.join(os.path.dirname(build), "b1")
    with open(S14_MASTER, encoding="utf-8", newline="") as fh:
        raw = fh.read()
    lines = raw.split("\n")
    R.check("terms: master ends with one newline, no empty line inside", raw.endswith("\n") and "" not in lines[:-1])
    head = lines[0].split("\t")
    R.check("terms: columns as SPEC 4.10 (with named_by, checked)", head == S14_COLS, " ".join(head))
    rows = [dict(zip(S14_COLS, ln.split("\t") + [""] * len(S14_COLS))) for ln in lines[1:] if ln]  # short rows: fail below, no crash
    R.check("terms: every row has every column", all(len(ln.split("\t")) == len(head) for ln in lines[1:] if ln),
            len(rows))
    keys = [(r["category"], r["code"]) for r in rows]
    R.check("terms: one row per (category, code)", len(keys) == len(set(keys)), f"{len(keys)} rows")
    R.check("terms: categories are the six of SPEC 4.10", {k[0] for k in keys} <= set(S14_CATS),
            sorted({k[0] for k in keys}))
    R.check("terms: codes are C0 codes", all(re.fullmatch(r"[a-z0-9]+(_[a-z0-9]+)*", k[1]) for k in keys))
    # the values that occur
    occ = C.defaultdict(C.Counter)
    for r in _s14_tsv(os.path.join(HERE, "data", "connectives", "clauses.tsv")):
        if r["relation"]:
            occ["relation"][_s14_c0(r["relation"])] += 1
    for r in _s14_tsv(os.path.join(HERE, "data", "time-aspect", "clauses.tsv")):
        for cat, col in (("time", "time"), ("aspect", "aspect"), ("line_kind", "band")):
            if r[col]:
                occ[cat][_s14_c0(r[col])] += 1
    for r in _s14_tsv(os.path.join(HERE, "data", "arg-roles", "roles.tsv")):
        if r["role"] not in ("", "-"):
            occ["sem_role"][_s14_c0(r["role"])] += 1
    for lang in ("hbo", "arc", "grc"):
        for r in _s14_tsv(os.path.join(b1, lang, "participants.tsv")):
            occ["ent_type"][r["ent"].split(":")[0]] += 1
    have = set(keys)
    for cat in S14_CATS:
        want = set(occ[cat]) | (set(S14_ENT) if cat == "ent_type" else set())
        miss = sorted((cat, c) for c in want if (cat, c) not in have)
        R.check(f"terms: {cat}: every value that occurs in the datasets has a row", not miss,
                f"{len(want)} values, {len(miss)} missing {miss}")
        extra = sorted(c for (k, c) in have if k == cat and c not in want)
        R.check(f"terms: {cat}: no row for a value that does not occur", not extra, f"{len(extra)} {extra}")
    lex = {lang: {r["lexeme"]: r for r in _s14_tsv(os.path.join(b1, lang, "lexemes.tsv"))} for lang in ("hbo", "grc")}
    rule = _s14_rule(R, b1)
    for lang in ("hbo", "grc"):
        bad = [r[lang] for r in rows if not _s14_script_ok(r[lang], lang)]
        R.check(f"terms: every {lang} term is in {'Hebrew' if lang == 'hbo' else 'Greek'} script "
                "(letters, points, accents, spaces)", not bad, f"{len(rows)} terms, {len(bad)} not {bad[:5]}")
        for cat in S14_CATS:
            seen = C.Counter(U.normalize("NFC", r[lang]) for r in rows if r["category"] == cat)
            dup = sorted(t for t, n in seen.items() if n > 1)
            R.check(f"terms: {lang} {cat}: no two codes share a term", not dup, f"{len(seen)} terms, {dup}")
        frm = C.Counter(r[f"from_{lang}"] for r in rows)
        R.check(f"terms: from_{lang} is text, tradition or coined", set(frm) <= {"text", "tradition", "coined"},
                dict(frm))
        bad_t = [r["code"] for r in rows if r[f"from_{lang}"] == "text" and not (
            r[f"source_{lang}"] in lex[lang] and
            U.normalize("NFC", lex[lang][r[f"source_{lang}"]]["lemma"]) == U.normalize("NFC", r[lang]))]
        R.check(f"terms: {lang} text: source is a b1 lexeme key whose lemma is the term", not bad_t,
                f"{frm['text']} rows, {len(bad_t)} not {bad_t}")
        bad_r = [r["code"] for r in rows if r[f"from_{lang}"] == "tradition" and not r[f"source_{lang}"]]
        R.check(f"terms: {lang} tradition: source names the work", not bad_r, f"{frm['tradition']} rows, {bad_r}")
        bad_c = [r["code"] for r in rows if r[f"from_{lang}"] == "coined" and
                 (r[f"source_{lang}"] or f"{lang}: " not in r["note"])]
        R.check(f"terms: {lang} coined: source empty and the note says how", not bad_c,
                f"{frm['coined']} rows, {bad_c}")
        for cat in ("relation", "sem_role"):
            got = {r["code"]: (U.normalize("NFC", r[lang]), r[f"source_{lang}"]) for r in rows
                   if r["category"] == cat and r[f"from_{lang}"] == "text"}
            want = {c: v for (k, c, lg), v in rule.items() if k == cat and lg == lang}
            diff = sorted(set(got.items()) ^ set(want.items()))
            R.check(f"terms: {lang} {cat}: the text terms are exactly rule T's (recomputed)", not diff,
                    f"{len(want)} by rule, {len(diff)} differ {diff[:4]}")
        R.check(f"terms: {lang}: no text term outside relation, sem_role (rule T) and ent_type",
                not [r for r in rows if r[f"from_{lang}"] == "text" and r["category"] not in
                     ("relation", "sem_role", "ent_type")])
        R.info(f"terms: rows by from_{lang}", dict(sorted(frm.items())))
    R.check("terms: named_by is filled on every row", all(r["named_by"] for r in rows),
            sorted({r["named_by"] for r in rows}))
    R.check("terms: checked is empty on every row (no person has checked)", all(r["checked"] == "" for r in rows))
    for lang in ("hbo", "arc", "grc"):
        p = os.path.join(build, lang, "terms.tsv")
        same = os.path.exists(p) and open(p, "rb").read() == raw.encode("utf-8")
        R.check(f"{lang} terms: {os.path.basename(build)}/{lang}/terms.tsv equals the master byte for byte", same)
    R.info("terms: rows by category", dict(C.Counter(k[0] for k in keys)))


# ---- stage 15 (SPEC 1.1): core tables of build c1 ----------------------------------------------------------------

# SPEC 1.1, section 13: the columns of the stage-15 tables that must equal b1's, row by row on the key
UNCHANGED_15 = {
    "words": (("t",), ["t", "id", "book", "chapter", "verse", "w", "text", "after", "sentence", "clause"]),
    "pieces": (("t", "n"), ["t", "n", "pid", "text", "kind", "lexeme", "class", "marks", "fused", "sense", "domain"]),
    "clauses": (("clause",), ["clause", "book", "chapter", "verse", "first", "last", "gaps", "words", "parent",
                              "depth", "via", "rule", "pattern", "role"]),
    "constituents": (("clause", "ord"), ["clause", "ord", "role", "head", "first", "last", "frame_role", "prep"]),
}
CHANGED_15 = {"words": ["head", "head_basis", "rel"], "pieces": ["head_t", "head_n", "head_basis", "rel"],
              "clauses": ["role_wrapped", "pred", "pred_kind"], "constituents": ["class"]}


def _s15_table(build, lang, name):
    return pq.read_table(os.path.join(build, lang, f"{name}.parquet")).to_pydict()


def _s15_unchanged(R, build, b1):
    for lang in ("hbo", "arc", "grc"):
        for name, (key, cols) in UNCHANGED_15.items():
            cols = cols + (["pred", "pred_kind"] if name == "clauses" and lang != "grc" else [])
            A, B = _s15_table(build, lang, name), _s15_table(b1, lang, name)
            ka = [tuple(A[k][i] for k in key) for i in range(len(A[key[0]]))]
            kb = [tuple(B[k][i] for k in key) for i in range(len(B[key[0]]))]
            R.check(f"{lang} unchanged: {name} has the rows of b1 (the same keys {'+'.join(key)})",
                    sorted(ka) == sorted(kb) and len(set(ka)) == len(ka), f"{len(ka):,} / {len(kb):,}")
            ib = {k: i for i, k in enumerate(kb)}
            for c in cols:
                diff = sum(1 for i, k in enumerate(ka) if k not in ib or A[c][i] != B[c][ib[k]])
                R.check(f"{lang} unchanged: {name}.{c} equals b1 row by row", diff == 0, diff)
            for c in CHANGED_15[name]:
                if c in ("pred", "pred_kind") and lang != "grc":
                    continue
                pairs = C.Counter((B[c][ib[k]], A[c][i]) for i, k in enumerate(ka) if k in ib and A[c][i] != B[c][ib[k]])
                n = sum(pairs.values())
                if c in ("head", "head_t", "head_n", "pred"):
                    shown = f"{n:,} rows differ"
                else:
                    shown = f"{n:,} rows differ; b1 -> c1 (top 8): " + ", ".join(
                        f"{a!r}->{b!r} {m:,}" for (a, b), m in pairs.most_common(8))
                R.info(f"{lang} changed against b1: {name}.{c}", shown)
        la = open(os.path.join(build, lang, "lexemes.tsv"), "rb").read()
        lb = open(os.path.join(b1, lang, "lexemes.tsv"), "rb").read()
        R.check(f"{lang} unchanged: lexemes.tsv equals b1's byte for byte (every row, every column)", la == lb,
                f"{la.count(b'\n') - 1:,} rows")


def _s15_roots(R, build, b1):
    """SPEC 1.1 D2p(d), D2w: the roots and the cj prefixes against b1."""
    for lang in ("hbo", "arc"):
        A, B = _s15_table(build, lang, "pieces"), _s15_table(b1, lang, "pieces")
        rb = {(t, n) for t, n, h in zip(B["t"], B["n"], B["head_basis"]) if h == "root"}
        cls_b = {(t, n): c for t, n, c in zip(B["t"], B["n"], B["class"])}
        conj_b = {k for k in rb if cls_b[k] == "cj"}
        ra = {(t, n) for t, n, h in zip(A["t"], A["n"], A["head_basis"]) if h == "root"}
        conj_a = {k for k in ra if cls_b[k] == "cj"}
        R.info(f"{lang} roots that are a conjunction piece: b1 / c1", f"{len(conj_b):,} of {len(rb):,} / "
               f"{len(conj_a):,} of {len(ra):,}")
        R.check(f"{lang} D2p(d): no root is a conjunction piece where its sentence node has a CL child",
                len(conj_a) == 0, len(conj_a))
        WA, WB = _s15_table(build, lang, "words"), _s15_table(b1, lang, "words")
        top_cj = {}
        for D, Wd, tag in ((B, WB, "b1"), (A, WA, "c1")):
            # a word's edge is its cj prefix's where a cj prefix piece leaves the word with the word's head and rel
            edge = {t: (h, r) for t, h, r in zip(Wd["t"], Wd["head"], Wd["rel"])}
            top_cj[tag] = {t for t, k, c, h, r in zip(D["t"], D["kind"], D["class"], D["head_t"], D["rel"])
                           if k == "prefix" and c == "cj" and h != t and edge[t] == (h, r)}
        R.info(f"{lang} words whose edge is their cj prefix's: b1 / c1 (D2p d, D2w)",
               f"{len(top_cj['b1']):,} / {len(top_cj['c1']):,}")
        moved = sum(1 for i in range(len(WA["t"])) if (WA["head"][i], WA["rel"][i]) != (WB["head"][i], WB["rel"][i]))
        R.info(f"{lang} words whose head or rel differs from b1", f"{moved:,}")


def _s15_categories(R, build):
    """B13: the coded columns of 4.1 to 4.4 are declared in categories.toml with their counts."""
    for lang in ("hbo", "arc", "grc"):
        with open(os.path.join(build, lang, "categories.toml"), "rb") as fh:
            cats = tomllib.load(fh)
        W, P = _s15_table(build, lang, "words"), _s15_table(build, lang, "pieces")
        CL, K = _s15_table(build, lang, "clauses"), _s15_table(build, lang, "constituents")
        want = {("pieces", "head_basis"): C.Counter(P["head_basis"]), ("words", "head_basis"): C.Counter(W["head_basis"]),
                ("clauses", "via"): C.Counter(v for v in CL["via"] if v),
                ("clauses", "role"): C.Counter(v for v in CL["role"] if v),
                ("clauses", "role_wrapped"): C.Counter(v for v in CL["role_wrapped"] if v),
                ("clauses", "pred_kind"): C.Counter(CL["pred_kind"]),
                ("constituents", "role"): C.Counter(K["role"]),
                ("constituents", "class"): C.Counter(v for v in K["class"] if v),
                ("constituents", "frame_role"): C.Counter(x for v in K["frame_role"] for x in v.split())}
        for (tab, col), use in want.items():
            sec = cats.get(tab, {}).get(col)
            got = {v["code"]: v["count"] for v in sec["values"]} if sec and "values" in sec else None
            R.check(f"{lang} categories.toml: [{tab}.{col}] declares every value with its count",
                    got == dict(use), f"{len(use)} codes" if got == dict(use) else f"declared {got} used {dict(use)}")
        for tab, D in (("pieces", P), ("words", W)):
            sec = cats.get(tab, {}).get("rel")
            ok = sec is not None and "pattern" in sec and sec.get("distinct") == len(set(D["rel"]))
            forms = {f["form"]: f["count"] for f in sec.get("forms", [])} if sec else {}
            bad = [v for v in D["rel"] if not (v == "root" or v in ROLE_SET or re.fullmatch(r"[^:\s]+:\d+", v))]
            R.check(f"{lang} categories.toml: [{tab}.rel] declares the labels by pattern, every label fits it",
                    ok and not bad and sum(forms.values()) == len(D["rel"]) and not any(
                        k.startswith("OTHER") for k in forms), f"{len(set(D['rel'])):,} labels; {len(bad)} unfit")
        for col in ("rule", "pattern"):
            sec = cats.get("clauses", {}).get(col)
            R.check(f"{lang} categories.toml: [clauses.{col}] declared by pattern with its count",
                    sec is not None and sec.get("distinct") == len({v for v in CL[col] if v}),
                    sec.get("distinct") if sec else "missing")
        hb = {"index", "conj", "compound", "none", "sentence", "root"}
        R.check(f"{lang} pieces, words: head_basis is one of SPEC 4.2's codes",
                set(P["head_basis"]) <= hb and set(W["head_basis"]) <= hb)
        R.check(f"{lang} clauses: pred_kind is one of v, vc, p, none", set(CL["pred_kind"]) <= {"v", "vc", "p", "none"})
        R.check(f"{lang} constituents: class compound only on a c element (Hebrew, Aramaic)",
                lang != "grc" or "compound" not in K["class"])
        R.check(f"{lang} constituents: frame_role labels are A0, A1, A2, AA, AA2",
                {x for v in K["frame_role"] for x in v.split()} <= {"A0", "A1", "A2", "AA", "AA2"})


def stage15(R, build, src):
    global V11
    V11 = True
    b1 = os.path.join(os.path.dirname(os.path.normpath(build)), "b1")
    R.section("words, pieces, lexemes, references (the checks of 1.0's stage 02, with 1.1's columns)")
    stage02(R, build, src)
    R.section("clauses, constituents (stage 04's checks, with B3, B5, B6); they read the word heads checked below")
    stage04(R, build, src)
    R.section("heads (stage 03's checks, with D2p(d), D2w's cj rule, D3 for Greek one-word clauses)")
    stage03(R, build, src)
    tot = {}
    for lang in ("hbo", "arc", "grc"):
        K = _s15_table(build, lang, "constituents")
        tot[lang] = sum(1 for v in K["class"] if v == "compound")
    R.check("hbo+arc constituents: class compound on 146 c elements (B6)", tot["hbo"] + tot["arc"] == 146,
            f"{tot['hbo']} + {tot['arc']}")
    R.section("categories.toml: the coded columns (B13)")
    _s15_categories(R, build)
    R.section("unchanged: the columns SPEC 13 keeps equal b1's (and what changed, counted)")
    if not os.path.isdir(b1):
        R.skip("unchanged: equality with b1", "build b1 not present")
    else:
        _s15_unchanged(R, build, b1)
        _s15_roots(R, build, b1)


def write_validation_md(build, upto):
    """VALIDATION.md per language: the lines of the run that concern it, by stage, and every exception list."""
    for lang in S10_LANGS:
        others = [x for x in ("hbo", "arc", "grc", "tan") if x != lang and not (lang in ("hbo", "arc") and x == "tan")]
        L = [f"# VALIDATION: `{lang}`", "",
             f"Written by `validate_examples.py --build {os.path.basename(os.path.normpath(build))} --upto {upto} --write-md` "
             f"(SPEC {dict(c='1.1', d='1.2', e='1.3', f='1.4').get(os.path.basename(os.path.normpath(build))[:1], '1.0')}, section 10). Every exit condition the",
             "validator checks, with the count that met it (`PASS`/`FAIL`, the count in brackets), and the reported figures",
             "(`INFO`). Lines that name another language are left out; `tan` lines cover `hbo` and `arc` together. Then every",
             "exception list the builders wrote (`cache/stageNN-counts.json`) with its size.", ""]
        n_pass = n_fail = n_skip = 0
        stage = None
        for st, line in S10_STAGE_LINES:
            name = line[6:] if line[:4] in ("PASS", "FAIL", "INFO", "SKIP") else line
            if any(name.startswith(o + " ") or name.startswith(o + ":") for o in others):
                continue
            if st != stage:
                stage = st
                L += ["", f"## Stage {st}", ""]
            if line.startswith("--"):
                L += ["", f"### {line[3:]}", ""]
                continue
            n_pass += line.startswith("PASS")
            n_fail += line.startswith("FAIL")
            n_skip += line.startswith("SKIP")
            L.append(f"- {line}")
        L += ["", "## Exception lists", "", "| stage | list | size |", "|---|---|---|"]
        for f in sorted(glob.glob(os.path.join(build, "cache", "stage*-counts.json"))):
            with open(f, encoding="utf-8") as fh:
                doc = json.load(fh)
            for k, v in sorted(doc.get("exceptions", {}).items()):
                if any(k.startswith(o + " ") for o in others):
                    continue
                L.append(f"| {doc['stage']} | {k} | {v['count']:,} |")
        cw = STASH.get(f"s10 {lang} code words", {})
        L += ["", "## Declared codes that are also English words (the no-English exception list)", "",
              "A code here is declared (categories.toml, relmap.tsv, map.tsv, or the format's own lists of SPEC 4) and is",
              "also a word of MACULA's English gloss vocabulary. It stays a code: it names a form category, not a meaning.", "",
              "| code | values | columns |", "|---|---|---|"]
        L += [f"| `{t}` | {n:,} | {', '.join(w)} |" for t, (n, w) in sorted(cw.items(), key=lambda kv: (-kv[1][0], kv[0]))]
        L.insert(6, f"Result: {n_pass} PASS, {n_skip} SKIP, {n_fail} FAIL.")
        L.insert(7, "")
        with open(os.path.join(build, lang, "VALIDATION.md"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(L) + "\n")


STAGES = {"02": stage02, "03": stage03, "04": stage04, "05": stage05, "06": stage06, "07": stage07, "08": stage08,
          "09": stage09, "10": stage10}
# version 1.1 builds (c1, c2, ...): their own stages, 14 on (SPEC 1.1, section 14); b builds keep 02-10


def stage16(R, build, src):
    sys.path.append(HERE)
    import validate_examples_s16
    validate_examples_s16.UPTO = UPTO
    validate_examples_s16.V12 = V12
    if UPTO >= "17":
        import validate_examples_s17
        validate_examples_s16.EXTRA = validate_examples_s17.extra_data()
    if V13:     # SPEC 1.3: the clause keys of reference-status and implicit-args, joined by this stage's D9
        import validate_examples_s27
        validate_examples_s16.set13()
        validate_examples_s16.SCRATCH = SCRATCH
        ext = dict(getattr(validate_examples_s16, "EXTRA", {}) or {})
        for corpus in ("hbo", "grc"):
            ext[corpus] = dict(ext.get(corpus, {}), **{"v13-clause-keys": validate_examples_s27.v13_keys(corpus)})
        validate_examples_s16.EXTRA = ext
    validate_examples_s16.stage16(R, build, src, STASH)


def stage17(R, build, src):
    sys.path.append(HERE)
    import validate_examples_s17
    if V13:
        validate_examples_s17.set13()
        validate_examples_s17.SCRATCH = SCRATCH
    validate_examples_s17.stage17(R, build, src, STASH)


def stage18(R, build, src):
    sys.path.append(HERE)
    import validate_examples_s18
    validate_examples_s18.stage18(R, build, src, STASH)


def stage19(R, build, src):
    sys.path.append(HERE)
    import validate_examples_s19
    validate_examples_s19.V12 = V12
    validate_examples_s19.stage19(R, build, src, STASH)


def stage20(R, build, src, compare=None):
    sys.path.append(HERE)
    import validate_examples_s20
    validate_examples_s20.V12 = V12
    validate_examples_s20.V13 = V13
    validate_examples_s20.UPTO = UPTO
    validate_examples_s20.stage20(R, build, src, STASH, sys.modules[__name__], compare=compare)


def stage24(R, build, src, compare=None):
    sys.path.append(HERE)
    import validate_examples_s20
    validate_examples_s20.V12 = V12
    validate_examples_s20.UPTO = UPTO
    validate_examples_s20.stage24(R, build, src, STASH, sys.modules[__name__], compare=compare)


def stage14_12(R, build, src):
    sys.path.append(HERE)
    import validate_examples_s23
    validate_examples_s23.V13 = V13
    validate_examples_s23.terms12(R, build)


def stage23(R, build, src):
    sys.path.append(HERE)
    import validate_examples_s23
    validate_examples_s23.stage23(R, build)


V12 = False   # a d build (SPEC 1.2): set in main
V13 = False   # an e build (SPEC 1.3): set in main
V14 = False   # an f build (SPEC 1.4): set in main
V15 = False   # a g build (SPEC 1.5): set in main
V16 = False   # an h build (SPEC 1.6): set in main
PIECE_13 = ["clusivity", "clusivity_basis", "noun_rel", "noun_head_t", "noun_head_n"]   # SPEC 1.3, 4.2 to 4.4
CLAUSE_13 = ["marks_model"]
CONST_13 = ["ref_status", "ref_form"]
SCRATCH = None  # e builds: the validator's scratch (speech layers, strict view), outside the build (disk space)


def stage27(R, build, src):
    sys.path.append(HERE)
    import validate_examples_s27
    maps = validate_examples_s27.d9_from_stash(STASH)
    os.makedirs(SCRATCH, exist_ok=True)
    with open(os.path.join(SCRATCH, "d9-maps.json"), "w", encoding="utf-8") as fh:
        json.dump(maps, fh, ensure_ascii=False, sort_keys=True)
    validate_examples_s27.stage27(R, build, maps=maps)
STAGES_11 = {"14": stage14, "15": stage15, "16": stage16, "17": stage17, "18": stage18, "19": stage19, "20": stage20}
STAGES_12 = dict(STAGES_11, **{"14": stage14_12, "23": stage23, "24": stage24})   # SPEC 1.2: the 1.1 stages' checks with the 1.2 rules
STAGES_13 = {k: v for k, v in STAGES_12.items() if k not in ("23", "24")}   # SPEC 1.3: 1.2's checks, then 27
STAGES_13["27"] = stage27


def stage28(R, build, src):
    sys.path.append(HERE)
    import validate_examples_s28
    validate_examples_s28.stage28(R, build)


STAGES_13["28"] = stage28


def stage29(R, build, src, compare=None):
    sys.path.append(HERE)
    import validate_examples_s20
    import validate_examples_s29
    validate_examples_s20.V12 = True
    validate_examples_s20.V13 = True
    validate_examples_s20.UPTO = UPTO
    validate_examples_s29.stage29(R, build, STASH, sys.modules[__name__], compare=compare)


STAGES_13["29"] = stage29


def stage32(R, build, src, compare=None):
    sys.path.append(HERE)
    import validate_examples_s32
    validate_examples_s32.stage32(R, build, compare=compare, V=sys.modules[__name__])


STAGES_14 = dict(STAGES_13, **{"32": stage32})   # SPEC 1.4: every check of 1.3, then the new ones


def stage35(R, build, src, compare=None):
    sys.path.append(HERE)
    import validate_examples_s35
    validate_examples_s35.run(R, build)
    if compare and V16:     # SPEC 1.6: an h build's rebuild check is stage 38's (glossed-h1/)
        R.info("rebuild (SPEC 1.5): checked by stage 38 on an h build", compare)
    elif compare:     # SPEC 1.5 10: g2 against g1, every folder included
        R.section("rebuild (SPEC 1.5: every folder)")
        other = os.path.join(os.path.dirname(os.path.normpath(build)), compare) if not os.path.isabs(compare) else compare
        for sub in ("hbo", "arc", "grc", "lexicon", "other/heb_mod", "other/heb_scg"):
            a, b = os.path.join(build, sub), os.path.join(other, sub)
            fs = sorted(f for f in os.listdir(a) if f != "VALIDATION.md" and os.path.isfile(os.path.join(a, f)))
            diff = [f for f in fs if not os.path.exists(os.path.join(b, f)) or
                    validate_examples_s35._sha(os.path.join(a, f)) != validate_examples_s35._sha(os.path.join(b, f))]
            R.check(f"rebuild: every file of {os.path.basename(build)}/{sub} has the same sha256 in {compare} "
                    "(VALIDATION.md aside)", not diff, f"{len(fs)} files; differ {diff}")
        ga = os.path.join(os.path.dirname(os.path.dirname(HERE)), "internal-docs/source-examples-work/glossed-g1")
        gb = os.path.join(other, "cache", "glossed")
        fs = sorted(f for f in os.listdir(ga) if f.endswith(".md") and f not in ("mends-sample.md", "equivalents-sample.md"))
        diff = [f for f in fs if not os.path.exists(os.path.join(gb, f)) or
                validate_examples_s35._sha(os.path.join(ga, f)) != validate_examples_s35._sha(os.path.join(gb, f))]
        R.check(f"rebuild: the {len(fs)} glossed chapters of glossed-g1/ equal {compare}/cache/glossed/", not diff and len(fs) == 8, diff)
        sa = os.path.join(ga, "equivalents-sample.md")
        sb = os.path.join(other, "cache", "reader-sample", "equivalents-sample.md")
        R.check(f"rebuild: the lexicon's reader sample equals {compare}'s", os.path.exists(sb) and
                validate_examples_s35._sha(sa) == validate_examples_s35._sha(sb))


STAGES_15 = dict(STAGES_14, **{"35": stage35})   # SPEC 1.5: every check of 1.4 (with the 1.5 rules), then the new


def stage38(R, build, src, compare=None):
    sys.path.append(HERE)
    import validate_examples_s35
    import validate_examples_s38
    validate_examples_s38.run(R, build)
    if compare:     # SPEC 1.6 10: h2 against h1, every folder included
        R.section("rebuild (SPEC 1.6: every folder)")
        other = os.path.join(os.path.dirname(os.path.normpath(build)), compare) if not os.path.isabs(compare) else compare
        for sub in ("hbo", "arc", "grc", "lexicon", "other/heb_mod", "other/heb_scg"):
            a, b = os.path.join(build, sub), os.path.join(other, sub)
            fs = sorted(f for f in os.listdir(a) if f != "VALIDATION.md" and os.path.isfile(os.path.join(a, f)))
            diff = [f for f in fs if not os.path.exists(os.path.join(b, f)) or
                    validate_examples_s35._sha(os.path.join(a, f)) != validate_examples_s35._sha(os.path.join(b, f))]
            R.check(f"rebuild: every file of {os.path.basename(build)}/{sub} has the same sha256 in {compare} "
                    "(VALIDATION.md aside)", not diff, f"{len(fs)} files; differ {diff}")
        ga = os.path.join(os.path.dirname(os.path.dirname(HERE)), "internal-docs/source-examples-work/glossed-h1")
        gb = os.path.join(other, "cache", "glossed")
        fs = sorted(f for f in os.listdir(ga) if f.endswith(".md") and f not in ("mends-sample.md", "equivalents-sample.md"))
        diff = [f for f in fs if not os.path.exists(os.path.join(gb, f)) or
                validate_examples_s35._sha(os.path.join(ga, f)) != validate_examples_s35._sha(os.path.join(gb, f))]
        R.check(f"rebuild: the {len(fs)} glossed chapters of glossed-h1/ equal {compare}/cache/glossed/", not diff and len(fs) == 8, diff)
        sa = os.path.join(ga, "equivalents-sample.md")
        sb = os.path.join(other, "cache", "reader-sample", "equivalents-sample.md")
        R.check(f"rebuild: the lexicon's reader sample equals {compare}'s", os.path.exists(sb) and
                validate_examples_s35._sha(sa) == validate_examples_s35._sha(sb))


STAGES_16 = dict(STAGES_15, **{"38": stage38})   # SPEC 1.6: every check of 1.5 (read against g1), then the new
def stage49(R, build, src, compare=None):
    sys.path.append(HERE)
    import validate_examples_s49
    validate_examples_s49.run(R, build, compare=compare)


STAGES_17 = dict(STAGES_16, **{"49": stage49})
def stage52(R, build, src, compare=None):
    sys.path.append(HERE)
    import validate_examples_s52
    validate_examples_s52.run(R, build, compare=compare)


STAGES_18 = dict(STAGES_17, **{"52": stage52})


def stage55(R, build, src, compare=None):
    sys.path.append(HERE)
    import validate_examples_s55
    validate_examples_s55.run(R, build, compare=compare, held_names=sorted(HELD19))


STAGES_19 = dict(STAGES_18, **{"55": stage55})   # SPEC 1.9: every check up to 52 on k1, then the new   # SPEC 1.8: every check up to 49 on j1, then the new
#   # SPEC 1.7: every check up to 38 on the copied folders, then the new


def write_validation_md_17(build, upto):
    """SPEC 1.7: VALIDATION.md of each edition folder: the stage 49 lines that concern it (the copied folders keep h1's)."""
    for ed in ("heb_mod", "heb_scg"):
        other = "heb_scg" if ed == "heb_mod" else "heb_mod"
        L = [f"# VALIDATION: `{ed}`", "",
             f"Written by `validate_examples.py --build {os.path.basename(os.path.normpath(build))} --upto {upto} --write-md` "
             "(SPEC 1.7, section 10, the conditions new in 1.7). Every exit condition with the count that met it, and the "
             "reported figures (`INFO`). Lines that name the other edition are left out; `tan` lines cover both. The "
             "conditions up to stage 38 ran on the copied folders and are in their own VALIDATION.md (h1's).", ""]
        n = C.Counter()
        for st, line in S10_STAGE_LINES:
            if st != "49":
                continue
            name = line[6:] if line[:4] in ("PASS", "FAIL", "INFO", "SKIP") else line[3:]
            if name.startswith(other):
                continue
            if line.startswith("--"):
                L += ["", f"## {line[3:]}", ""]
                continue
            n[line[:4]] += 1
            L.append(f"- {line}")
        L += ["", f"Totals: {n['PASS']} PASS, {n['SKIP']} SKIP, {n['FAIL']} FAIL.", ""]
        with open(os.path.join(build, ed, "VALIDATION.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(L))


NEEDS_SRC = {"02", "03", "04", "05", "06", "07", "08", "09", "10", "15", "16"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upto", required=True)
    ap.add_argument("--build", default="b1")
    ap.add_argument("--root", default=os.path.join(HERE, "data/source-examples"))
    ap.add_argument("--compare", help="stage 10: the second build to compare file by file (rebuild condition)")
    ap.add_argument("--write-md", action="store_true", help="write <lang>/VALIDATION.md from this run")
    ap.add_argument("--only", action="append", help="run only these stages (a partial run; never for VALIDATION.md)")
    a = ap.parse_args()
    if a.write_md and a.only:
        raise SystemExit("--write-md needs the whole run up to --upto (no --only)")
    build = os.path.join(a.root, a.build)
    global UPTO
    UPTO = a.upto
    R = Report()
    global V12
    kind = os.path.basename(os.path.normpath(build))[:1]
    V12 = kind == "d"
    global V13, V14, SCRATCH, V15, V16
    V19 = kind == "k"     # SPEC 1.9: a k build is checked as a j build (every check up to 52), then by stage 55
    if V19:
        kind = "j"
    V18 = kind == "j"     # SPEC 1.8: a j build is checked as an i build (every check up to 49), then by stage 52
    V17 = kind in ("i", "j")     # SPEC 1.7: an i build is checked as an h build (its five folders are h1's), then by stage 49
    if V17:
        kind = "h"
    if V18:
        sys.path.append(HERE)
        import validate_examples_s49
        import validate_examples_s52
        validate_examples_s49.V18 = True
        validate_examples_s49.GLOSSED = os.path.join(build, "cache", "glossed")
        import validate_examples_s19
        import validate_examples_s23
        validate_examples_s19.V18 = validate_examples_s23.V18 = True
    if HERE not in sys.path:
        sys.path.append(HERE)
    import validate_examples_s20
    validate_examples_s20.COPIED = V17 and not V18   # a j build writes its own declarations (SPEC 1.8, stage 52)
    validate_examples_s20.V18 = V18
    if V18:
        import validate_examples_s29
        validate_examples_s29.V18 = True
    global HELD18_ON, HELD19_ON, HELD19
    HELD18_ON = V18
    if V19:
        HELD19_ON = True
        HELD19 = load_held19()
        validate_examples_s29.V19 = True
        validate_examples_s20.V19 = True
    if V18:
        import validate_examples_s32
        validate_examples_s32.V18 = True
    V16 = kind == "h"     # SPEC 1.6: an h build is checked as a g build (stage 35 read against g1), then by stage 38
    V15 = kind in ("g", "h")     # SPEC 1.5: a g build is checked as an f build with the 1.5 rules, then by stage 35
    V14 = kind in ("f", "g", "h")     # SPEC 1.4: an f build is checked as an e build (1.3, up to 29), then by stage 32
    V13 = kind in ("e", "f", "g", "h")
    if V14:
        sys.path.append(HERE)
        import validate_examples_s20
        import validate_examples_s27
        import validate_examples_s29
        validate_examples_s20.V14 = True
        validate_examples_s27.V14 = True
        validate_examples_s29.V14 = True
        if V15:
            import validate_examples_s16
            import validate_examples_s28
            import validate_examples_s32
            import validate_examples_s35
            for m in (validate_examples_s16, validate_examples_s20, validate_examples_s27, validate_examples_s28,
                      validate_examples_s29, validate_examples_s32):
                m.V15 = True
            validate_examples_s35.WRITE = a.write_md
            if V16:
                import validate_examples_s38
                validate_examples_s35.V16 = True
                validate_examples_s38.WRITE = a.write_md and not V17   # SPEC 1.7: glossed-h1/ stays h1's
                if V17:
                    validate_examples_s35.WRITE = False
                for m in (validate_examples_s16, validate_examples_s20, validate_examples_s27, validate_examples_s28,
                          validate_examples_s29, validate_examples_s32):
                    m.V16 = True
                validate_examples_s32.STATE_CODES = ("member", "nt_only", "function", "name", "no_number", "few_places",
                                                     "spread", "kept_out", "alone")     # SPEC 1.6 D27
    if V13:
        V12 = True
        SCRATCH = os.path.join("/tmp/claude-1000/source-examples", f"s27-validate-{a.build}")
    stages = STAGES_19 if V19 else STAGES_18 if V18 else STAGES_17 if V17 else STAGES_16 if V16 else STAGES_15 if V15 else STAGES_14 if V14 else STAGES_13 if V13 else STAGES_12 if V12 else STAGES_11 if kind == "c" else STAGES
    run = [st for st in sorted(stages) if st <= a.upto and (not a.only or st in a.only)]
    src = read_sources() if NEEDS_SRC & set(run) else None
    for st in sorted(stages):
        if st <= a.upto and (not a.only or st in a.only):
            print(f"== stage {st}")
            R.stage = st
            if st in ("10", "20", "24", "29", "32", "35", "38", "49", "52", "55"):
                # SPEC 1.7: on an i build the rebuild is stage 49's (every folder of i1 against i2); 1.8: and 52's;
                # 1.9: only 55's (k1 against k2)
                want = ("55",) if V19 else ("49", "52")
                stages[st](R, build, src, compare=a.compare if (not V17 or st in want) else None)
            else:
                stages[st](R, build, src)
    print(f"== {R.passes} PASS, {R.skips} SKIP, {R.fails} FAIL" + (f", {R.held} HELD (1.9: see validate_examples_held19.tsv)"
          if HELD19_ON else f", {R.held} HELD (1.8: see HELD18)" if HELD18_ON else ""))
    print(f"== {R.fails} condition(s) failed")
    if a.write_md and V18:
        write_validation_md_17(build, a.upto)
        validate_examples_s52.write_md(build, S10_STAGE_LINES, a.upto)
        if V19:
            import validate_examples_s55
            validate_examples_s55.write_md(build, S10_STAGE_LINES, a.upto, HELD18_LINES, HELD19)
        print("VALIDATION.md written for hbo, arc, grc (i1's, with the block new in 1.8) and heb_mod, heb_scg")
    elif a.write_md and V17:
        write_validation_md_17(build, a.upto)
        print("VALIDATION.md written for heb_mod, heb_scg (the copied folders keep h1's)")
    elif a.write_md:
        write_validation_md(build, a.upto)
        if V14 and a.upto >= "32":
            import validate_examples_s32
            validate_examples_s32.write_md(build, [x for x in S10_STAGE_LINES if x[0] == "32"])
        print("VALIDATION.md written for " + ", ".join(S10_LANGS))
    sys.exit(1 if R.fails else 0)


if __name__ == "__main__":
    main()
