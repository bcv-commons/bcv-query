"""Validator of the Hebrew levels build (SPEC-levels.md 0.1, section 10). Imports nothing from the builders.

  shoresh/.venv/bin/python -I shoresh/macula/validate_levels.py --build pilot-1 --upto 42 [--root DIR] [--no-rerun]

Prints every condition as PASS, SKIP or FAIL with its count, writes VALIDATION.md into the build folder, and ends
non-zero when one fails. Every table is recomputed here by this file's own code from the pinned inputs.
"""
import argparse
import csv
import hashlib
import json
import os
import pickle
import re
import subprocess
import sys
import time
import tomllib
import unicodedata
from bisect import bisect_right
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "shoresh" / "macula" / "data"
I1 = DATA / "source-examples" / "i1"
PY = REPO / "shoresh" / ".venv" / "bin" / "python"
SCRATCH = Path("/tmp/claude-1000/source-examples/levels42")
CONTENT_CLASSES = {"noun", "verb", "adj", "adv"}

# stage 40's counts (FEASIBILITY.md 1.2, 2, 6), printed beside ours
STAGE40 = {"single": {"mz": 10838, "rd": 3206, "mn": 1452, "mb": 618},
           "x_resolved": {"mz": 9247, "rd": 3056, "mn": 1292, "mb": 492},
           "x_and_y": {"mz": 5155, "rd": 2380, "mn": 657, "mb": 325},
           "vocabulary": 2193, "in_dv": 1364,
           "routes": {"lex": 8262, "ubs": 33984, "nt2": 10298, "rend": 3856, "lxx": 2689, "vec": 1516}}

# the basis of every column as SPEC-levels 4 and 5 give it
SPEC_BASIS = {
    "words/explanations.parquet": {"expl": "derived", "source": "given", "line": "given", "offset": "derived",
                                   "witness": "given", "kind": "derived", "cue": "given", "x_text": "given",
                                   "x_key": "derived", "x_lexeme": "derived", "x_state": "derived",
                                   "y_text": "given", "y_words": "derived", "y_content": "derived",
                                   "one_word": "derived"},
    "words/vocabulary.tsv": {"lexeme": "given", "lemma": "given", "uses": "derived", "sources": "derived",
                             "explains": "derived", "in_dv": "derived"},
    "words/levels.tsv": {"lexeme": "given", "lemma": "given", "lang": "given", "class": "given", "state": "given",
                         "count": "derived", "band": "derived", "kind": "derived", "level": "derived",
                         "uses": "derived", "explanations": "derived", "one_word": "derived", "senses": "given",
                         "count_model": "model", "level_model": "model"},
    "words/sense_levels.tsv": {"lexeme": "given", "sense": "given", "count": "derived", "share": "derived",
                               "level": "derived"},
    "near/pairs.parquet": {"a": "given", "b": "given", "route": "—", "basis": "—", "count": "derived",
                           "evidence": "derived", "meaning": "derived", "engine": "—", "places": "derived"},
    "near/rend_langs.parquet": {"a": "given", "b": "given", "lang": "given", "edition": "given",
                                "rendering_share_a": "linked", "rendering_share_b": "linked"},
    "near/distance.parquet": {"a": "given", "b": "given", "grade": "derived", "k": "derived", "routes": "derived",
                              "grade_strict": "derived", "k_strict": "derived", "routes_strict": "derived",
                              "group": "derived"},
}
ROUTE_BASIS = {"lex": {"given"}, "ubs": {"given"}, "nt2": {"linked", "model"}, "rend": {"linked"},
               "lxx": {"given"}, "vec": {"model"}}


class Report:
    def __init__(self):
        self.lines, self.fails, self.passes = [], 0, 0

    def out(self, s):
        print(s, flush=True)
        self.lines.append(s)

    def section(self, s):
        self.out(f"\n== {s}")

    def check(self, name, ok, detail=""):
        self.out(f"{'PASS' if ok else 'FAIL'} {name}  [{detail}]")
        if ok:
            self.passes += 1
        else:
            self.fails += 1

    def skip(self, name, why):
        self.out(f"SKIP {name}  [{why}]")

    def info(self, name, detail):
        self.out(f"INFO {name}: {detail}")


def h256(p):
    d = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            d.update(b)
    return d.hexdigest()


def read_tsv(p):
    with open(p, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def read_pq(p):
    return pq.read_table(p).to_pylist()


# ---------------------------------------------------------------- the validator's own reading of i1

class Tanakh:
    def __init__(self):
        self.lex = {r["lexeme"]: r for r in read_tsv(I1 / "lexicon" / "lexemes.tsv")}
        self.words, self.stem_of = {}, {}
        self.verse = defaultdict(list)
        self.pieces = {}
        for part in ("hbo", "arc"):
            w = pq.read_table(I1 / part / "words.parquet", columns=["t", "book", "chapter", "verse", "text"]).to_pydict()
            p = pq.read_table(I1 / part / "pieces.parquet",
                              columns=["t", "kind", "class", "lexeme", "sense", "pid"]).to_pydict()
            self.pieces[part] = p
            firsts, conts = {}, {}
            for t, k, c, lx in zip(p["t"], p["kind"], p["class"], p["lexeme"]):
                if k == "stem" and lx:
                    if t not in firsts:
                        firsts[t] = lx
                    if c in CONTENT_CLASSES and t not in conts:
                        conts[t] = lx
            for t in firsts:
                self.stem_of[(part, t)] = conts[t] if t in conts else firsts[t]
            for t, b, c, v, x in zip(w["t"], w["book"], w["chapter"], w["verse"], w["text"]):
                self.words[(part, t)] = x
                self.verse[(b, c, v)].append((part, t))
        self.forms = defaultdict(Counter)
        for (part, t), x in self.words.items():
            lx = self.stem_of.get((part, t))
            if lx is None:
                continue
            for seg in letters_only(x).split():
                self.forms[fold(seg)][lx] += 1
        self.lemmas = defaultdict(set)
        for lx, r in self.lex.items():
            if int(r["tanakh"] or 0) > 0:
                self.lemmas[fold(letters_only(r["lemma"]))].add(lx)

    def content(self, lx):
        r = self.lex.get(lx)
        return r is not None and r["class"] in CONTENT_CLASSES and r["state"] != "name" and r["state"] != "function"


def letters_only(s):
    """letters and single spaces only; maqaf and every other non-letter are spaces; marks dropped."""
    s = unicodedata.normalize("NFD", s or "")
    out = []
    for ch in s:
        if unicodedata.combining(ch):
            continue
        out.append(ch if 0x05D0 <= ord(ch) <= 0x05EA else " ")
    return " ".join("".join(out).split())


def fold(s):
    return s.replace(" ", "").translate({ord("ך"): "כ", ord("ם"): "מ", ord("ן"): "נ", ord("ף"): "פ", ord("ץ"): "צ"})


def vkey(s):
    return fold(letters_only(s))


# ---------------------------------------------------------------- W1, the validator's own parser

V_MEAN = ["ענין", "ענינו", "עניינו", "הוא", "היא", "הם", "ר״ל", 'ר"ל', "כעין", "פירוש", "פירושו", "ופירוש",
          "ופירושו", "כלומר", "פתרון", "פתרונו", "ופתרון"]
V_CUE = {
    "mz": dict([(c, "meaning") for c in V_MEAN] + [("כמו", "likeness"), ("מלשון", "derivation"),
               ("מל׳", "derivation"), ("מל'", "derivation"), ("תרגומו", "targum"), ("תרגם", "targum"),
               ("ת״י", "targum"), ("תרגום", "targum"), ("שם", "class"), ("מין", "class"), ("מקום", "class"),
               ("כלי", "class")]),
    "mb": dict([(c, "meaning") for c in V_MEAN] + [("כמו", "likeness"), ("מענין", "derivation"),
               ("מלשון", "derivation"), ("שם", "class"), ("מקום", "class")]),
    "rd": {c: "meaning" for c in ["פירוש", "פירושו", "ופירוש", "ופירושו", "פירושם", "כלומר", "ענין", "ענינו"]},
    "mn": dict([(c, "meaning") for c in ["ענין", "פתרון", "פתרונו", "ופתרון", "לשון"]] +
               [("כמשמעו", "literal"), ("מגזרת", "derivation")]),
}
V_STOP = set("וכן כמו והוא ר״ל או כי אבל וזה רוצה וכמוהו ובדברי וכלם והם שהוא על אשר".split()) | {'ר"ל'}
V_FORMULA = set("אחד כפי לפי פתרו ויסודתם".split())
V_RX = re.compile(r"<(?P<bt>b|strong)>(?P<bold>.*?)</(?P=bt)>"
                  r"|<a [^>]*data-ref=\"(?P<ref>[^\"]+)\"[^>]*>.*?</a>"
                  r"|<small>\((?P<sm>.*?)\)</small>"
                  r"|<[^>]+>"
                  r"|(?P<q>\s'[^'<]{1,60}')"
                  r"|(?P<w>[^<\s]+)", re.S)
V_TAG = re.compile(r"<[^>]+>")
HEB_RUN = re.compile(r"[\u0590-\u05FF\"״׳']+")
V_EN = dict(zip(["Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua", "Judges", "Ruth", "I Samuel",
                 "II Samuel", "I Kings", "II Kings", "I Chronicles", "II Chronicles", "Ezra", "Nehemiah", "Esther",
                 "Job", "Psalms", "Proverbs", "Ecclesiastes", "Song of Songs", "Isaiah", "Jeremiah", "Lamentations",
                 "Ezekiel", "Daniel", "Hosea", "Joel", "Amos", "Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk",
                 "Zephaniah", "Haggai", "Zechariah", "Malachi"],
                ["GEN", "EXO", "LEV", "NUM", "DEU", "JOS", "JDG", "RUT", "1SA", "2SA", "1KI", "2KI", "1CH", "2CH",
                 "EZR", "NEH", "EST", "JOB", "PSA", "PRO", "ECC", "SNG", "ISA", "JER", "LAM", "EZK", "DAN", "HOS",
                 "JOL", "AMO", "OBA", "JON", "MIC", "NAM", "HAB", "ZEP", "HAG", "ZEC", "MAL"]))
V_HE = {"בראשית": "GEN", "שמות": "EXO", "ויקרא": "LEV", "במדבר": "NUM", "דברים": "DEU", "יהושע": "JOS",
        "שופטים": "JDG", "רות": "RUT", 'ש"א': "1SA", 'ש"ב': "2SA", 'מ"א': "1KI", 'מ"ב': "2KI", "דה״א": "1CH",
        "דה״ב": "2CH", "עזרא": "EZR", "נחמיה": "NEH", "אסתר": "EST", "איוב": "JOB", "תהלים": "PSA",
        "משלי": "PRO", "קהלת": "ECC", "שיר": "SNG", "ישעיהו": "ISA", "ירמיהו": "JER", "ירמיה": "JER",
        "איכה": "LAM", "יחזקאל": "EZK", "דניאל": "DAN", "הושע": "HOS", "יואל": "JOL", "עמוס": "AMO",
        "עובדיה": "OBA", "יונה": "JON", "מיכה": "MIC", "נחום": "NAM", "חבקוק": "HAB", "צפניה": "ZEP",
        "חגי": "HAG", "זכריה": "ZEC", "מלאכי": "MAL"}
GEMATRIA = {}
for _i, _c in enumerate("אבגדהוזחטי"):
    GEMATRIA[_c] = _i + 1
for _i, _c in enumerate("כלמנסעפצק"):
    GEMATRIA[_c] = (_i + 2) * 10
for _i, _c in enumerate("רשת"):
    GEMATRIA[_c] = (_i + 2) * 100
GEMATRIA.update({"ך": 20, "ם": 40, "ן": 50, "ף": 80, "ץ": 90})


class Visible:
    """tag-free text of an html string and the map from html positions to it."""

    def __init__(self, html):
        self.starts, self.vis, parts = [], [], []
        pos, v = 0, 0
        for m in V_TAG.finditer(html):
            if m.start() > pos:
                self.starts.append(pos)
                self.vis.append(v)
                parts.append(html[pos:m.start()])
                v += m.start() - pos
            pos = m.end()
        if pos < len(html):
            self.starts.append(pos)
            self.vis.append(v)
            parts.append(html[pos:])
            v += len(html) - pos
        self.text = "".join(parts)
        self.html = html

    def at(self, i):
        """visible offset of html index i (inside a tag: the offset of the next visible character)."""
        k = bisect_right(self.starts, i) - 1
        if k < 0:
            return 0
        end_k = self.vis[k + 1] if k + 1 < len(self.vis) else len(self.text)
        return min(self.vis[k] + (i - self.starts[k]), end_k)


def v_tokens(html):
    vis = Visible(html)
    toks = []
    for m in V_RX.finditer(html):
        if m.group("bold") is not None:
            t = V_TAG.sub("", m.group("bold")).strip()
            if t:
                toks.append(["bold", t, vis.at(m.start()), vis.at(m.end())])
        elif m.group("ref") is not None:
            toks.append(["ref_en", m.group("ref"), vis.at(m.start()), vis.at(m.end())])
        elif m.group("sm") is not None:
            toks.append(["ref_he", m.group("sm"), vis.at(m.start()), vis.at(m.end())])
        elif m.group("q") is not None:
            toks.append(["quote", m.group("q").strip(), vis.at(m.start("q")), vis.at(m.end("q"))])
        elif m.group("w") is not None:
            w, w0 = m.group("w"), m.start("w")
            i = 0
            while i < len(w):
                h = HEB_RUN.match(w, i)
                if h and re.match(r"[\u0590-\u05FF]", h.group(0)):
                    run = h.group(0)
                    core = run.strip("'")
                    a = w0 + i + (len(run) - len(run.lstrip("'")))
                    toks.append(["word", core, vis.at(a), vis.at(a + len(core))])
                    i = h.end()
                elif h:   # a run of quote marks only: a punctuation piece
                    toks.append(["punct", h.group(0), vis.at(w0 + i), vis.at(w0 + h.end())])
                    i = h.end()
                else:
                    j = i
                    while j < len(w) and not HEB_RUN.match(w, j):
                        j += 1
                    toks.append(["punct", w[i:j], vis.at(w0 + i), vis.at(w0 + j)])
                    i = j
    return vis.text, toks


def v_num(s):
    s = "".join(ch for ch in s if ch not in "\"'״׳\u200e" and not ch.isspace())
    if not s or any(ch not in GEMATRIA for ch in s):
        return None
    return sum(GEMATRIA[ch] for ch in s)


def v_place_en(ref):
    m = re.match(r"(.+?) (\d+):(\d+)", ref)
    return (V_EN[m.group(1)], int(m.group(2)), int(m.group(3))) if m and m.group(1) in V_EN else None


def v_place_he(ref, prev_book):
    m = re.match(r"\s*(\S+)\s+(\S+),\s*(\S+)\s*$", ref.replace("\u200e", ""))
    if not m:
        return None
    book = prev_book if m.group(1) == "שם" else V_HE.get(m.group(1))
    c, v = v_num(m.group(2)), v_num(m.group(3))
    return (book, c, v) if book and c and v else None


def v_y(toks, i):
    j = i + 1
    if j < len(toks) and toks[j][0] == "quote":
        j += 1
    if j < len(toks) and toks[j][0] == "word" and toks[j][1] == "לומר":
        j += 1
    got = []
    while j < len(toks) and len(got) < 6:
        t = toks[j]
        if t[0] == "word" and t[1] not in V_STOP:
            got.append(t)
        elif t[0] == "punct" and t[1].strip() in ("", "-", "\"", "״"):
            pass
        else:
            break
        j += 1
    return got


def v_raw_statements():
    files = {"mz": "metzudat_zion_chapters.jsonl", "mb": "malbim_beur_hamilot_chapters.jsonl",
             "rd": "sefer_hashorashim_entries.jsonl", "mn": "mahberet_menahem_letters.jsonl"}
    out = []
    for src in ("mz", "mb", "rd", "mn"):
        with open(DATA / files[src], encoding="utf-8") as fh:
            lines = fh.read().split("\n")
        for ln, line in enumerate(lines):
            if not line.strip():
                continue
            rec = json.loads(line)
            if src in ("mz", "mb"):
                chunks = [(g, (rec["book"], int(rec["chapter"]), vi + 1)) for vi, vs in enumerate(rec["verses"]) for g in vs]
            elif src == "rd":
                chunks = [(rec["text"], None)]
            else:
                chunks = [(" ".join(e), None) for e in rec["entries"]]
            off0 = 0
            for html, place in chunks:
                text, toks = v_tokens(html)
                common = {"source": src, "line": ln, "text": text, "off0": off0}
                off0 += len(text) + 1
                if src in ("mz", "mb"):
                    out.append(v_gloss(common, toks, place))
                else:
                    out.extend(v_entry(common, toks, src))
    return out


def v_gloss(c, toks, place):
    src = c["source"]
    if not toks or toks[0][0] != "bold":
        return {**c, "place": place, "x": None, "cue": None, "kind": "", "y": [], "at": 0, "end": 0}
    x = toks[0]
    meaningful = [t for t in toks[1:] if not (t[0] == "punct" and t[1].strip() in ("", "."))]
    idx = next((i for i in range(1, len(toks)) if toks[i][0] == "word"), None)
    cue = toks[idx] if idx is not None else None
    kind = V_CUE[src].get(cue[1]) if cue else None
    if not meaningful or kind is None:
        return {**c, "place": place, "x": x, "cue": None, "kind": "", "y": [], "at": x[2], "end": x[3]}
    if kind == "class":
        y = [toks[idx + 1]] if idx + 1 < len(toks) and toks[idx + 1][0] == "word" else []
    elif kind == "literal":
        y = []
    else:
        y = v_y(toks, idx)
    if " " in letters_only(x[1]) or "," in x[1]:
        kind = "phrase"
    return {**c, "place": place, "x": x, "cue": cue, "kind": kind, "y": y, "at": cue[2],
            "end": (y[-1][3] if y else cue[3])}


def v_entry(c, toks, src):
    rows, bold, bold_place, book = [], None, None, None
    for i, t in enumerate(toks):
        if t[0] == "bold":
            bold, bold_place = t, None
        elif t[0] == "ref_en" or t[0] == "ref_he":
            pl = v_place_en(t[1]) if t[0] == "ref_en" else v_place_he(t[1], book)
            if pl:
                book = pl[0]
            if bold is not None and bold_place is None:
                bold_place = pl
        elif t[0] == "word" and t[1] in V_CUE[src]:
            kind = V_CUE[src][t[1]]
            y = [] if kind == "literal" else v_y(toks, i)
            if y and y[0][1] in V_FORMULA:
                kind = "formula"
            elif bold is not None and " " in letters_only(bold[1]):
                kind = "phrase"
            rows.append({**c, "place": bold_place if bold is not None else None, "x": bold, "cue": t, "kind": kind,
                         "y": y, "at": t[2], "end": (y[-1][3] if y else t[3])})
    return rows


def v_resolve_y(T, w):
    k = vkey(w)
    if len(k) < 2:
        return "", "short"
    tries = [(k, "")]
    if len(k) > 2 and k[0] in "והבלכמש":
        tries.append((k[1:], "_prefix"))
        if len(k) > 3 and k[1] in "והבלכמש":
            tries.append((k[2:], "_prefix"))
    for cand, suf in tries:
        f = T.forms.get(cand)
        if f:
            total = sum(f.values())
            best = sorted(f.items(), key=lambda kv: (-kv[1], kv[0]))[0]
            return (best[0], "form" + suf) if best[1] >= 0.9 * total else ("", "ambiguous")
        lem = T.lemmas.get(cand)
        if lem:
            return (sorted(lem)[0], "lemma" + suf) if len(lem) == 1 else ("", "ambiguous")
    return "", "none"


def v_resolve_x(T, x, place):
    k = vkey(x)
    found = {T.stem_of[(p, t)] for p, t in T.verse.get(place, []) if vkey(T.words[(p, t)]) == k and (p, t) in T.stem_of}
    found.discard("")
    if len(found) == 1:
        return found.pop(), "resolved"
    return ("", "ambiguous") if found else ("", "not_found")


def v_explanations(T):
    raw = v_raw_statements()
    raw.sort(key=lambda r: (r["source"], r["line"], r["off0"] + r["at"]))
    rows = []
    for i, r in enumerate(raw):
        x = r["x"]
        xt = unicodedata.normalize("NFC", x[1].strip().rstrip(".:").strip()) if x else ""
        wit = unicodedata.normalize("NFC", r["text"][x[2]:r["end"]].strip()) if x else ""
        if r["place"] is None:
            xk, xl, xs = "", "", "no_place"
        else:
            b, ch, v = r["place"]
            xk = f"{b} {ch}:{v}"
            xl, xs = v_resolve_x(T, xt, r["place"])
        yw = []
        for t in r["y"]:
            lx, rule = v_resolve_y(T, t[1])
            yw.append({"lexeme": lx, "rule": rule, "text": unicodedata.normalize("NFC", t[1])})
        yc = []
        for w in yw:
            if w["lexeme"] and T.content(w["lexeme"]) and w["lexeme"] not in yc:
                yc.append(w["lexeme"])
        rows.append({"expl": f"expl:{i + 1}", "source": r["source"], "line": r["line"], "offset": r["off0"] + r["at"],
                     "witness": wit, "kind": r["kind"],
                     "cue": unicodedata.normalize("NFC", r["cue"][1]) if r["cue"] else "",
                     "x_text": xt, "x_key": xk, "x_lexeme": xl, "x_state": xs,
                     "y_text": " ".join(w["text"] for w in yw), "y_words": yw, "y_content": yc,
                     "one_word": len(yc) == 1 and all(w["rule"] not in ("ambiguous", "none") for w in yw)})
    return rows


def explaining_rows(rows):
    return [r for r in rows if r["kind"] in ("meaning", "likeness", "derivation") and r["x_state"] == "resolved"]


# ---------------------------------------------------------------- W2 to W4

def v_level(n):
    return None if n <= 0 else 1 if n >= 100 else 2 if n >= 20 else 3 if n >= 5 else 4


def v_band(n):
    if n <= 0:
        return "0"
    for lo, code in ((500, "500"), (100, "100_499"), (20, "20_99"), (5, "5_19"), (2, "2_4"), (1, "1")):
        if n >= lo:
            return code


def v_words(T, ex):
    uses, srcs, xs = Counter(), defaultdict(set), defaultdict(set)
    nexpl, none = Counter(), Counter()
    for r in explaining_rows(ex):
        for y in r["y_content"]:
            uses[y] += 1
            srcs[y].add(r["source"])
            xs[y].add(r["x_lexeme"])
        if r["y_content"]:
            nexpl[r["x_lexeme"]] += 1
            none[r["x_lexeme"]] += int(r["one_word"])
    voc = {lx: [lx, T.lex[lx]["lemma"], str(n), " ".join(sorted(srcs[lx])), str(len(xs[lx])),
                "true" if n >= 2 else "false"] for lx, n in uses.items()}
    single = Counter()
    for part in ("hbo", "arc"):
        p = T.pieces[part]
        for lx, s in zip(p["lexeme"], p["sense"]):
            if lx and s and len(s.split()) == 1:
                single[(lx, s)] += 1
    nsense = Counter(lx for lx, _ in single)
    lev, levels = {}, []
    for lx in sorted(T.lex):
        r = T.lex[lx]
        cnt = int(r["tanakh"] or 0) + int(r["heb_mod"] or 0) + int(r["heb_scg"] or 0)
        cm = cnt + int(r["heb_mod_model"] or 0) + int(r["heb_scg_model"] or 0)
        if r["state"] == "name":
            kind = "name"
        elif r["state"] == "function" or r["class"] not in {"noun", "verb", "adj", "adv", "num"}:
            kind = "function"
        elif r["class"] == "num":
            kind = "number"
        elif uses[lx] >= 2:
            kind = "dv"
        elif nexpl[lx] > 0:
            kind = "explained"
        else:
            kind = "unexplained"
        fixed = {"name": 0, "function": 0, "number": 0, "dv": 1}.get(kind)
        lv = (fixed if fixed is not None else v_level(cnt)) if cnt > 0 else None
        lvm = (fixed if fixed is not None else v_level(cm)) if cm > 0 else None
        lev[lx] = lv
        levels.append([lx, r["lemma"], r["lang"], r["class"], r["state"], str(cnt), v_band(cnt), kind,
                       "" if lv is None else str(lv), str(uses[lx]), str(nexpl[lx]), str(none[lx]), str(nsense[lx]),
                       str(cm), "" if lvm == lv or lvm is None else str(lvm)])
    sl = []
    for (lx, s) in sorted(single):
        n = single[(lx, s)]
        tan = int(T.lex[lx]["tanakh"] or 0)
        cands = [x for x in (lev.get(lx), v_level(n)) if x is not None]
        sl.append((lx, s, n, n / tan if tan else None, max(cands) if cands else None))
    return voc, levels, sl


# ---------------------------------------------------------------- routes and distance

def v_routes(T, ex):
    lang = lambda lx: T.lex[lx]["lang"]  # noqa: E731
    rows = {}
    # lex
    acc = defaultdict(list)
    for r in explaining_rows(ex):
        x = r["x_lexeme"]
        if not T.content(x):
            continue
        for y in r["y_content"]:
            if y != x and lang(x) == lang(y):
                acc[tuple(sorted((x, y)))].append(r)
    for (a, b), st in acc.items():
        places = []
        for s in st:
            if s["x_key"] not in places:
                places.append(s["x_key"])
        rows[(a, b, "lex", "given")] = {
            "count": len(st),
            "evidence": {"kinds": sorted({s["kind"] for s in st}), "one_word": sum(1 for s in st if s["one_word"]),
                         "sources": sorted({s["source"] for s in st})},
            "meaning": any(s["kind"] == "meaning" and s["one_word"] for s in st), "engine": False,
            "places": "; ".join(places[:3])}
    # ubs
    main = {}
    for part in ("hbo", "arc"):
        for r in read_tsv(I1 / part / "lexemes.tsv"):
            if T.content(r["lexeme"]) and r["domains"].strip():
                best = None
                for item in r["domains"].split():
                    code, n = item.rsplit(":", 1)
                    if best is None or int(n) > best[1] or (int(n) == best[1] and code < best[0]):
                        best = (code, int(n))
                main[r["lexeme"]] = best[0]
    holders = defaultdict(list)
    for lx, d in main.items():
        holders[d].append(lx)
    for d, ls in holders.items():
        if len(ls) > 40:
            continue
        for a, b in combinations(sorted(ls), 2):
            if lang(a) == lang(b):
                rows[(a, b, "ubs", "given")] = {"count": 1, "evidence": {"domain": d}, "meaning": False,
                                                "engine": False, "places": ""}
    # nt2, lxx
    lp = pq.read_table(I1 / "lexicon" / "pairs.parquet").to_pylist()
    for r in lp:
        route = {"nt_editions": "nt2", "sept_number": "lxx"}.get(r["evidence"])
        if not route or not (T.content(r["a"]) and T.content(r["b"])) or lang(r["a"]) != lang(r["b"]):
            continue
        a, b = sorted((r["a"], r["b"]))
        basis = "given" if route == "lxx" else r["basis"]
        rows[(a, b, route, basis)] = {"count": r["count"], "evidence": {"via": json.loads(r["via"])},
                                      "meaning": False, "engine": route == "lxx", "places": r["places"]}
    # rend
    rend_langs = v_rend(T, rows)
    # vec
    v_vec(T, rows)
    return rows, rend_langs


def v_rend(T, rows):
    with open(DATA / "compact_renderings_80.pkl", "rb") as fh:
        pk = pickle.load(fh)
    lex_of = {}
    for part in ("hbo", "arc"):
        p = T.pieces[part]
        for pid, lx in zip(p["pid"], p["lexeme"]):
            if pid and lx and T.content(lx):
                lex_of[pid[1:]] = lx
    tokens = Counter()           # (language, lexeme) -> aligned places
    rend = defaultdict(Counter)  # (language, lexeme) -> rendering -> places
    for key, feats in pk["features"].items():
        lx = lex_of.get(key)
        if lx is None:
            continue
        seen = set()
        for lg, rr in feats:
            rend[(lg, lx)][rr] += 1
            seen.add(lg)
        for lg in seen:
            tokens[(lg, lx)] += 1
    owners = defaultdict(list)
    for (lg, lx), cnt in rend.items():
        n = tokens[(lg, lx)]
        if n >= 5:
            for rr, m in cnt.items():
                if m >= 0.3 * n:
                    owners[(lg, rr)].append((lx, m / n))
    best = defaultdict(dict)
    for (lg, rr), own in owners.items():
        if len(own) > 30:
            continue
        own.sort()
        for (a, sa), (b, sb) in combinations(own, 2):
            if T.lex[a]["lang"] != T.lex[b]["lang"]:
                continue
            cand = (min(sa, sb), sa + sb, rr, sa, sb)
            cur = best[(a, b)].get(lg)
            if cur is None or cand[:2] > cur[:2] or (cand[:2] == cur[:2] and rr < cur[2]):
                best[(a, b)][lg] = cand
    out = []
    for (a, b), per in best.items():
        if len(per) >= 10:
            rows[(a, b, "rend", "linked")] = {"count": len(per), "evidence": {"languages": len(per)},
                                              "meaning": False, "engine": False, "places": ""}
            for lg, c in per.items():
                code = lg[2:] if lg.startswith("x-") else lg
                out.append((a, b, code, pk["editions"][code], c[3], c[4]))
    out.sort()
    return out, pk["languages"]


def v_vec(T, rows):
    meta = json.load(open(DATA / "vector-store" / "lexemes.json", encoding="utf-8"))
    vec = np.load(DATA / "vector-store" / "lexemes.npy")
    by_number = defaultdict(list)
    for lx in sorted(T.lex):
        r = T.lex[lx]
        digits = re.sub(r"\D", "", r["strong"])
        if T.content(lx) and r["lang"] == "hbo" and digits:
            by_number[int(digits)].append(lx)
    sel = [(i, int(k[1:])) for i, k in enumerate(meta["keys"]) if re.fullmatch(r"h\d+", k) and int(k[1:]) in by_number]
    m = vec[[i for i, _ in sel]].astype(np.float32)
    m = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
    s = m @ m.T
    np.fill_diagonal(s, -1)
    order = np.argsort(-s, axis=1, kind="stable")[:, :5]
    top = [list(map(int, o)) for o in order]
    for i in range(len(sel)):
        for j in top[i]:
            if j > i and i in top[j]:
                la, lb = by_number[sel[i][1]][0], by_number[sel[j][1]][0]
                ri, rj = top[i].index(j) + 1, top[j].index(i) + 1
                if la < lb:
                    a, b, ra, rb = la, lb, ri, rj
                else:
                    a, b, ra, rb = lb, la, rj, ri
                rows[(a, b, "vec", "model")] = {"count": 1, "evidence": {"rank_a": ra, "rank_b": rb},
                                                "meaning": False, "engine": False, "places": ""}


def v_grade(rs, grp):
    names = sorted({r[0] for r in rs})
    ind = {r[0] for r in rs if r[0] in ("nt2", "rend", "lxx") or (r[0] == "lex" and r[1])}
    if grp:
        g = "d2"
    elif ind:
        g = "d3"
    elif "ubs" in names or any(r[0] == "lex" and not r[1] for r in rs):
        g = "d4"
    elif names == ["vec"]:
        g = "d5"
    else:
        g = "d6"
    return g, len(ind), names


def v_distance(rows):
    gr = pq.read_table(I1 / "lexicon" / "groups.parquet", columns=["group", "lexeme", "basis"]).to_pylist()
    members = defaultdict(set)
    for r in gr:
        if r["basis"] == "derived":
            members[r["group"]].add(r["lexeme"])
    gpairs = {p for ms in members.values() for p in combinations(sorted(ms), 2)}
    ev = defaultdict(list)
    for (a, b, route, basis), r in rows.items():
        ev[(a, b)].append((route, r["meaning"], basis))
    out = {}
    for p in set(ev) | gpairs:
        rs = ev.get(p, [])
        g, k, names = v_grade(rs, p in gpairs)
        gs, ks, ns = v_grade([r for r in rs if r[2] != "model"], p in gpairs)
        out[p] = (g, k, names, gs, ks, ns, p in gpairs)
    return out, gpairs


# ---------------------------------------------------------------- no English

LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
LEX_KEY = re.compile(r"^(lex|ntx):(hbo|arc):[^\s:]+:[0-9A-Za-z]*$")


def mismatches(a, b, limit=3):
    bad = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    return len(bad) + abs(len(a) - len(b)), [(a[i], b[i]) for i in bad[:limit]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", required=True)
    ap.add_argument("--upto", type=int, required=True)
    ap.add_argument("--root", default=str(DATA / "hebrew-levels"))
    ap.add_argument("--sample", default=str(REPO / "internal-docs" / "source-examples-work" / "levels" / "sample-42.md"))
    ap.add_argument("--sample43", default=str(REPO / "internal-docs" / "source-examples-work" / "levels" / "sample-43.md"))
    ap.add_argument("--no-rerun", action="store_true")
    a = ap.parse_args()
    B = Path(a.root) / a.build
    R = Report()
    R.out(f"validate_levels.py --build {a.build} --upto {a.upto}  ({B})")
    if a.upto < 42:
        R.skip("stage 42", "not asked")
        return finish(R, B)
    t0 = time.time()

    R.section("inputs")
    src = json.load(open(B / "sources.json", encoding="utf-8"))
    bad = [p for p, h in src["inputs"].items() if h256(REPO / p) != h]
    R.check("every input's sha256 equals sources.json", not bad, f"{len(src['inputs'])} inputs; {bad[:3]}")
    i1_files = sorted(p for p in I1.rglob("*") if p.is_file() and "cache" not in p.parts)
    newer = [str(p) for p in i1_files if p.stat().st_mtime > (B / "build.json").stat().st_mtime]
    R.check("i1 is not written: no file of i1 is newer than the build", not newer, f"{len(i1_files)} files; {newer[:3]}")
    bj = json.load(open(B / "build.json", encoding="utf-8"))
    badf = [f for f, h in bj["files"].items() if h256(B / f) != h]
    R.check("build.json's file hashes hold", not badf, f"{len(bj['files'])} files; {badf}")

    T = Tanakh()
    R.section("explanations (W1, recomputed by the validator's own parser)")
    mine = v_explanations(T)
    built = read_pq(B / "words" / "explanations.parquet")
    for r in built:
        r["y_words"], r["y_content"] = json.loads(r["y_words"]), json.loads(r["y_content"])
    cols = list(SPEC_BASIS["words/explanations.parquet"])
    n, ex = mismatches([tuple(json.dumps(r[c], ensure_ascii=False, sort_keys=True) for c in cols) for r in built],
                       [tuple(json.dumps(r[c], ensure_ascii=False, sort_keys=True) for c in cols) for r in mine])
    R.check("explanations equal W1 recomputed, row by row and column by column", n == 0,
            f"{len(built)} rows built, {len(mine)} recomputed, {n} differ {ex[:1]}")
    R.check("expl keys run expl:1 .. expl:N in (source, line, offset) order",
            [r["expl"] for r in built] == [f"expl:{i}" for i in range(1, len(built) + 1)]
            and [(r["source"], r["line"], r["offset"]) for r in built] == sorted((r["source"], r["line"], r["offset"]) for r in built),
            f"{len(built)}")
    for s in ("mz", "rd", "mn", "mb"):
        rs = [r for r in built if r["source"] == s]
        single = [r for r in rs if r["kind"] not in ("", "phrase", "formula") and r["x_state"] != "no_place"
                  and r["x_text"] and not (s in ("rd", "mn") and r["kind"] != "literal" and not r["y_text"])]
        xres = sum(1 for r in single if r["x_state"] == "resolved")
        xy = sum(1 for r in explaining_rows(rs) if r["y_content"])
        R.info(f"{s} rows / single-word statements / X resolved / explaining with content Y",
               f"{len(rs)} / {len(single)} (stage 40: {STAGE40['single'][s]}) / {xres} "
               f"(stage 40: {STAGE40['x_resolved'][s]}) / {xy} (stage 40, names counted as content and X not "
               f"required resolved in kind: {STAGE40['x_and_y'][s]})")
        R.info(f"{s} kind", dict(sorted(Counter(r["kind"] for r in rs).items())))
        R.info(f"{s} x_state", dict(sorted(Counter(r["x_state"] for r in rs).items())))
    files = {"mz": "metzudat_zion_chapters.jsonl", "mb": "malbim_beur_hamilot_chapters.jsonl",
             "rd": "sefer_hashorashim_entries.jsonl", "mn": "mahberet_menahem_letters.jsonl"}
    nlines = {s: sum(1 for _ in open(DATA / f, encoding="utf-8")) for s, f in files.items()}
    badl = [r["expl"] for r in built if not (0 <= r["line"] < nlines[r["source"]])]
    R.check("every line exists in its pinned file", not badl, f"{len(built)} rows; {badl[:3]}")
    badx = [r["expl"] for r in built if r["x_text"] not in r["witness"]]
    R.check("x_text stands in its witness", not badx, f"{len(built)} rows; {badx[:3]}")
    nowit = sum(1 for r in built if not r["witness"])
    R.info("rows with an empty witness (no headword: the gloss does not open with a bold word)", nowit)

    R.section("vocabulary, levels, sense_levels (W2, W3, W4 recomputed)")
    voc, levels, sl = v_words(T, mine)
    bv = read_tsv(B / "words" / "vocabulary.tsv")
    n, ex = mismatches([list(r.values()) for r in bv], [voc[k] for k in sorted(voc)])
    R.check("vocabulary equals W2", n == 0, f"{len(bv)} rows ({sum(r['in_dv'] == 'true' for r in bv)} in_dv; "
            f"stage 40: {STAGE40['vocabulary']} / {STAGE40['in_dv']}); {n} differ {ex[:1]}")
    bl = read_tsv(B / "words" / "levels.tsv")
    n, ex = mismatches([list(r.values()) for r in bl], levels)
    R.check("levels equals W3", n == 0, f"{len(bl)} rows; {n} differ {ex[:1]}")
    R.check("one levels row per lexicon key, sorted", [r["lexeme"] for r in bl] == sorted(T.lex),
            f"{len(bl)} rows, {len(T.lex)} keys")
    kinds = {"name", "function", "number", "dv", "explained", "unexplained"}
    R.check("one declared kind per row", all(r["kind"] in kinds for r in bl), f"{Counter(r['kind'] for r in bl)}")
    R.check("a level exactly where count > 0",
            all((r["level"] != "") == (int(r["count"]) > 0) for r in bl),
            f"{sum(1 for r in bl if r['level'])} with a level, {sum(1 for r in bl if int(r['count']) > 0)} with count > 0")
    tab = Counter((r["kind"], r["level"] or "-", r["band"]) for r in bl)
    R.out("INFO kind x level x band (rows):")
    bands = ["0", "1", "2_4", "5_19", "20_99", "100_499", "500"]
    R.out("    " + "kind/level".ljust(18) + "".join(b.rjust(9) for b in bands) + "    all")
    for kd in ["name", "function", "number", "dv", "explained", "unexplained"]:
        for lv in ["-", "0", "1", "2", "3", "4"]:
            row = [tab.get((kd, lv, b), 0) for b in bands]
            if sum(row):
                R.out("    " + f"{kd}/{lv}".ljust(18) + "".join(str(x).rjust(9) for x in row) + str(sum(row)).rjust(7))
    bs = read_tsv(B / "words" / "sense_levels.tsv")
    exp = [[lx, s, str(n), "" if sh is None else repr(round(sh, 6)), "" if lv is None else str(lv)]
           for lx, s, n, sh, lv in sl]
    n, ex = mismatches([list(r.values()) for r in bs], exp)
    R.check("sense_levels equals W4", n == 0, f"{len(bs)} rows; {n} differ {ex[:1]}")
    lvl = {r["lexeme"]: r["level"] for r in bl}
    worse = [r for r in bs if r["level"] and lvl[r["lexeme"]] and int(r["level"]) < int(lvl[r["lexeme"]])]
    R.check("no sense more common (lower level) than its lexeme", not worse, f"{len(worse)}")
    R.check("every sense code has 15 digits", all(re.fullmatch(r"\d{15}", r["sense"]) for r in bs), f"{len(bs)}")

    R.section("near/pairs (routes recomputed)")
    rows, (rend_langs, pickle_langs) = v_routes(T, mine)
    bp = read_pq(B / "near" / "pairs.parquet")
    got = {(r["a"], r["b"], r["route"], r["basis"]): {"count": r["count"], "evidence": json.loads(r["evidence"]),
                                                      "meaning": r["meaning"], "engine": r["engine"],
                                                      "places": r["places"]} for r in bp}
    R.check("pairs keys unique", len(got) == len(bp), f"{len(bp)} rows, {len(got)} keys")
    for route in ROUTE_BASIS:
        mk = {k for k in rows if k[2] == route}
        gk = {k for k in got if k[2] == route}
        diff = sum(1 for k in mk & gk if rows[k] != got[k])
        R.check(f"route {route}: rows equal the validator's own rule", mk == gk and diff == 0,
                f"{len(gk)} rows built (stage 40 pairs: {STAGE40['routes'][route]}), {len(mk)} recomputed, "
                f"{len(mk ^ gk)} keys differ, {diff} values differ; by basis "
                f"{dict(sorted(Counter(k[3] for k in gk).items()))}")
    R.check("pairs sorted by (route, basis, a, b)",
            [(r["route"], r["basis"], r["a"], r["b"]) for r in bp] == sorted((r["route"], r["basis"], r["a"], r["b"]) for r in bp), "")
    R.check("every row has one of the six routes and its basis", all(r["basis"] in ROUTE_BASIS.get(r["route"], ()) for r in bp),
            f"{Counter((r['route'], r['basis']) for r in bp)}")
    R.check("a < b; both keys in the lexicon, of one lang",
            all(r["a"] < r["b"] and r["a"] in T.lex and r["b"] in T.lex and T.lex[r["a"]]["lang"] == T.lex[r["b"]]["lang"]
                for r in bp), f"{len(bp)}")
    R.check("both lexemes are content lexemes (4.1)", all(T.content(r["a"]) and T.content(r["b"]) for r in bp), "")
    R.check("every vec row model; every lxx row engine; no other row engine",
            all((r["basis"] == "model") == (r["route"] == "vec") or r["route"] == "nt2" for r in bp)
            and all(r["engine"] == (r["route"] == "lxx") for r in bp), "")
    R.check("meaning only on lex rows", all(not r["meaning"] or r["route"] == "lex" for r in bp),
            f"{sum(r['meaning'] for r in bp)} rows true")
    brl = read_pq(B / "near" / "rend_langs.parquet")
    n, ex = mismatches([tuple(r.values()) for r in brl], rend_langs)
    R.check("rend_langs equals the validator's own rule", n == 0, f"{len(brl)} rows; {n} differ {ex[:1]}")
    per = Counter((r["a"], r["b"]) for r in brl)
    R.check("rend count = its rend_langs rows",
            all(per[(r["a"], r["b"])] == r["count"] for r in bp if r["route"] == "rend")
            and set(per) == {(r["a"], r["b"]) for r in bp if r["route"] == "rend"}, f"{len(per)} pairs")
    langs = {r["lang"] for r in brl} | {x[2:] if x.startswith("x-") else x for x in pickle_langs}
    R.check("no rend language is eng, heb or hbo (pickle and table)", not (langs & {"eng", "heb", "hbo"}),
            f"{len(pickle_langs)} pickle languages, {len({r['lang'] for r in brl})} used")
    by_lang = defaultdict(set)
    for r in brl:
        by_lang[r["lang"]].add((r["a"], r["b"]))
    loss = max(((sum(1 for p in ps if per[p] == 10), lg) for lg, ps in by_lang.items()), default=(0, ""))
    R.info("largest leave-one-language-out loss (pairs that fall below 10 languages)", f"{loss[0]} ({loss[1]}); stage 40: 158")

    R.section("near/distance (N7 recomputed)")
    dist, gpairs = v_distance(rows)
    bd = read_pq(B / "near" / "distance.parquet")
    gotd = {(r["a"], r["b"]): (r["grade"], r["k"], json.loads(r["routes"]), r["grade_strict"], r["k_strict"],
                               json.loads(r["routes_strict"]), r["group"]) for r in bd}
    R.check("one distance row per pair in any route or strict group, and none else", set(gotd) == set(dist),
            f"{len(bd)} rows, {len(dist)} expected, {len(set(gotd) ^ set(dist))} differ")
    nd = sum(1 for p in set(gotd) & set(dist) if gotd[p] != dist[p])
    R.check("every grade recomputed by N7, over all rows and over strict rows", nd == 0, f"{nd} differ")
    R.check("no pair graded without a route or group (all rows)",
            all(v[2] or v[6] for v in gotd.values()) and all(v[0] != "d6" for v in gotd.values()), "")
    R.check("distance sorted by (a, b)", [(r["a"], r["b"]) for r in bd] == sorted(gotd), "")
    R.info("grades (all rows)", dict(sorted(Counter(v[0] for v in gotd.values()).items())))
    R.info("grades (strict rows)", dict(sorted(Counter(v[3] for v in gotd.values()).items())))
    R.info("d3 by k (all / strict)", f"{dict(sorted(Counter(v[1] for v in gotd.values() if v[0] == 'd3').items()))} / "
           f"{dict(sorted(Counter(v[4] for v in gotd.values() if v[3] == 'd3').items()))}")
    mixed = Counter("+".join(v[2]) for v in gotd.values() if v[0] == "d4" and len(v[2]) > 1)
    R.info("d4 pairs held by more than one non-independent route (read as d4, 5.2)", dict(mixed.most_common(6)))

    R.section("counts by frequency band (recomputed from the tables; for the report)")
    bands = ["0", "1", "2_4", "5_19", "20_99", "100_499", "500"]
    band_of = {r["lexeme"]: r["band"] for r in bl}
    content = [r["lexeme"] for r in bl if T.content(r["lexeme"])]
    R.out("    " + "content lexemes".ljust(28) + "".join(b.rjust(9) for b in bands))
    R.out("    " + "all".ljust(28) + "".join(str(sum(1 for x in content if band_of[x] == b)).rjust(9) for b in bands))
    kind_of = {r["lexeme"]: r["kind"] for r in bl}
    for kd in ("dv", "explained", "unexplained"):
        R.out("    " + f"kind {kd}".ljust(28) + "".join(
            str(sum(1 for x in content if band_of[x] == b and kind_of[x] == kd)).rjust(9) for b in bands))
    reach = {route: {x for r in bp if r["route"] == route for x in (r["a"], r["b"])} for route in ROUTE_BASIS}
    for route in ROUTE_BASIS:
        R.out("    " + f"in route {route}".ljust(28) + "".join(
            str(sum(1 for x in reach[route] if band_of[x] == b)).rjust(9) for b in bands))
    anyr = set().union(*reach.values())
    strict_r = {x for r in bp if r["basis"] != "model" for x in (r["a"], r["b"])}
    ind = {x for r in bp if r["route"] in ("nt2", "rend", "lxx") or (r["route"] == "lex" and r["meaning"])
           for x in (r["a"], r["b"])}
    for name, s_ in (("in any route", anyr), ("in a strict route", strict_r), ("in an independent route", ind)):
        R.out("    " + name.ljust(28) + "".join(str(sum(1 for x in s_ if band_of[x] == b)).rjust(9) for b in bands))
    none_ = [x for x in content if x not in anyr]
    R.out("    " + "in no route".ljust(28) + "".join(str(sum(1 for x in none_ if band_of[x] == b)).rjust(9) for b in bands))
    nothing = [x for x in content if x not in anyr and kind_of[x] == "unexplained"]
    R.out("    " + "unexplained and in no route".ljust(28) + "".join(
        str(sum(1 for x in nothing if band_of[x] == b)).rjust(9) for b in bands))
    dv = {r["lexeme"] for r in bv if r["in_dv"] == "true"}
    for col in ("tanakh", "heb_mod", "heb_scg", "heb_mod_model", "heb_scg_model"):
        for lg in ("hbo", "arc"):
            tot = sum(int(T.lex[x][col] or 0) for x in content if T.lex[x]["lang"] == lg)
            cov = sum(int(T.lex[x][col] or 0) for x in content if T.lex[x]["lang"] == lg and x in dv)
            if tot:
                R.info(f"defining vocabulary covers {col} content pieces ({lg} keys)", f"{cov} of {tot} ({100 * cov / tot:.1f}%)")

    R.section("columns, codes, no English")
    colmd = open(B / "COLUMNS.md", encoding="utf-8").read()
    secs = dict(re.findall(r"^## (\S+)\n\n\| column \| basis \| meaning \|\n\|---\|---\|---\|\n((?:\|.*\n?)*)", colmd, re.M))
    badc = []
    for f, spec in SPEC_BASIS.items():
        listed = dict(re.findall(r"^\| `([^`]+)` \| ([^|]+?) \|", secs.get(f, ""), re.M))
        if f.endswith(".parquet"):
            real = pq.read_schema(B / f).names
        else:
            real = open(B / f, encoding="utf-8").readline().rstrip("\n").split("\t")
        if list(listed) != real or listed != spec:
            badc.append(f)
    R.check("every column of every table listed in COLUMNS.md with the basis SPEC-levels gives", not badc,
            f"{len(SPEC_BASIS)} tables; {badc}")
    cat = tomllib.load(open(B / "categories.toml", "rb"))["codes"]
    D = {k: set(v) for k, v in cat.items()}
    undeclared = Counter()

    def need(code_list, v, where):
        if v not in D.get(code_list, ()):
            undeclared[(where, v)] += 1

    for r in built:
        need("explanations.source", r["source"], "source")
        need("explanations.kind", r["kind"], "kind")
        need("explanations.x_state", r["x_state"], "x_state")
        for w in r["y_words"]:
            need("explanations.y_words.rule", w["rule"], "y_words.rule")
    for r in bl:
        need("levels.kind", r["kind"], "kind")
        need("levels.band", r["band"], "band")
        need("levels.lang", r["lang"], "lang")
        need("levels.class", r["class"], "class")
        need("levels.state", r["state"], "state")
        for c in ("level", "level_model"):
            if r[c]:
                need("levels.level", r[c], c)
    for r in bv:
        for s in r["sources"].split():
            need("explanations.source", s, "vocabulary.sources")
    for r in bs:
        if r["level"]:
            need("levels.level", r["level"], "sense level")
    for r in bp:
        need("pairs.route", r["route"], "route")
        need("pairs.basis", r["basis"], "basis")
        e = json.loads(r["evidence"])
        for k in e.get("kinds", []):
            need("pairs.evidence.kinds", k, "evidence.kinds")
        for s in e.get("sources", []):
            need("explanations.source", s, "evidence.sources")
    for r in brl:
        need("rend_langs.lang", r["lang"], "lang")
        need("rend_langs.edition", r["edition"], "edition")
    for r in bd:
        need("distance.grade", r["grade"], "grade")
        need("distance.grade", r["grade_strict"], "grade_strict")
        for x in json.loads(r["routes"]) + json.loads(r["routes_strict"]):
            need("distance.routes", x, "routes")
    R.check("every coded value declared in categories.toml", not undeclared,
            f"{sum(undeclared.values())} undeclared: {sorted(undeclared.items())[:5]}")
    # no English: free strings are Hebrew text, keys, places or Greek evidence; a Latin word is English
    eng, stray = Counter(), Counter()

    def text_ok(v, where):
        for m in LATIN_WORD.finditer(v or ""):
            eng[(where, m.group(0))] += 1
        for m in re.finditer(r"(?<![A-Za-z])[A-Za-z](?![A-Za-z])", v or ""):
            stray[(where, m.group(0))] += 1

    for r in built:
        for c in ("witness", "cue", "x_text", "y_text"):
            text_ok(r[c], f"explanations.{c}")
        for w in r["y_words"]:
            text_ok(w["text"], "explanations.y_words.text")
        if r["x_key"] and not re.fullmatch(r"[1-3A-Z]{3} \d+:\d+", r["x_key"]):
            eng[("explanations.x_key", r["x_key"])] += 1
    for r in bl:
        text_ok(r["lemma"], "levels.lemma")
    for r in bv:
        text_ok(r["lemma"], "vocabulary.lemma")
    keyset = set(T.lex)
    badkeys = sum(1 for r in bl + bv if r["lexeme"] not in keyset) + sum(
        1 for r in built if r["x_lexeme"] and r["x_lexeme"] not in keyset) + sum(
        1 for r in built for w in r["y_words"] if w["lexeme"] and w["lexeme"] not in keyset)
    for r in bp:
        pl = r["places"]
        if r["route"] == "lex":
            okp = all(re.fullmatch(r"[1-3A-Z]{3} \d+:\d+", x) for x in pl.split("; ")) if pl else True
        elif r["route"] == "nt2":
            okp = all(re.fullmatch(r"(heb_mod|heb_scg):\d+\.\d+(\+(heb_mod|heb_scg):\d+\.\d+)*", x) for x in pl.split())
        elif r["route"] == "lxx":
            okp = all(re.fullmatch(r"\d+\.\d+", x) for x in pl.split())
        else:
            okp = pl == ""
        if not okp:
            eng[("pairs.places", pl)] += 1
        e = json.loads(r["evidence"])
        for v in e.get("via", []):
            greek_key = v.startswith("lex:grc:") and re.search(r"[\u0370-\u03ff\u1f00-\u1fff]", v) and not re.search(
                r"[A-Za-z]", re.sub(r"\((I|II|III|IV|V)\)", "", v[8:]))   # a Greek lemma, its homograph mark allowed
            if not (re.fullmatch(r"g:\d+[a-z]?", v) or greek_key):
                eng[("pairs.evidence.via", v)] += 1
        if "domain" in e and not re.fullmatch(r"\d+", e["domain"]):
            eng[("pairs.evidence.domain", e["domain"])] += 1
    R.check("no English value: no Latin word in a text column, every key, place and evidence value of its form",
            not eng and badkeys == 0, f"{sum(eng.values())} values {sorted(eng.items())[:5]}; {badkeys} unknown keys")
    R.info("stray single Latin letters inside Hebrew source text (source errors, kept as given)",
           f"{sum(stray.values())}: {sorted(stray.items())}")

    R.section("sample-42.md")
    smp = open(a.sample, encoding="utf-8").read()
    ok_s, detail = True, []
    for lv in range(5):
        rs = [r["lexeme"] for r in bl if r["level"] == str(lv)]
        k = max(1, len(rs) // 10)
        want = rs[::k][:10]
        part = smp.split(f"## Level {lv} ", 1)[1].split("\n## ", 1)[0] if f"## Level {lv} " in smp else ""
        have = re.findall(r"^### `([^`]+)`", part, re.M)
        ok_s &= have == want
        detail.append(f"level {lv}: {len(have)}")
    for route in ROUTE_BASIS:
        rs = sorted((r for r in bp if r["route"] == route), key=lambda r: (r["a"], r["b"], r["basis"]))
        k = max(1, len(rs) // 40)
        want = [(r["a"], r["b"], r["basis"]) for r in rs[::k][:40]]
        part = smp.split(f"## Route {route} ", 1)[1].split("\n## ", 1)[0] if f"## Route {route} " in smp else ""
        have = [(x, y, z) for x, y, z in re.findall(r"^\| `([^`]+)` \| `([^`]+)` \| [^|]+ \| [^|]+ \| (\w+) \|", part, re.M)]
        ok_s &= have == want
        detail.append(f"{route}: {len(have)}")
    R.check("sample-42.md holds 50 lexemes (10 per level 0-4) and 40 pairs per route by the rule", ok_s, ", ".join(detail))

    if a.upto >= 43:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import validate_levels43 as V43   # the validator's own stage-43 code (imports nothing from the builders)
        got = V43.run(R, B, Path(a.root), a, bl)
        if got:
            cats_all = tomllib.load(open(B / "categories.toml", "rb"))
            V43.meta(R, B, cats_all.get("codes43", {}), got["ops"])
            V43.sample(R, B, a.sample43, got["cv"])
            cats_flat = dict(cats_all.get("codes", {}))
            cats_flat.update(cats_all.get("codes43", {}))
            V43.pack(R, B, cats_flat, read_tsv(B / "measures" / "reach.tsv"))
        if a.no_rerun:
            R.skip("the whole build rebuilt into pilot-1b gives the same bytes", "--no-rerun")
        else:
            V43.rebuild(R, Path(a.root), a.build, PY, Path(a.sample), Path(a.sample43))
    elif a.no_rerun:
        R.skip("rebuild gives the same bytes", "--no-rerun")
    else:
        R.section("rebuild")
        root2 = SCRATCH / f"rerun-{os.getpid()}-{int(time.time())}"
        cmd = [str(PY), "-I", str(REPO / "shoresh" / "macula" / "build_levels.py"), "--build", a.build, "--stage", "42",
               "--root", str(root2), "--sample", str(root2 / "sample-42.md")]
        res = subprocess.run(cmd, capture_output=True, text=True)
        B2 = root2 / a.build
        names = sorted(str(p.relative_to(B)) for p in B.rglob("*") if p.is_file() and p.name != "VALIDATION.md"
                       and "cache" not in p.relative_to(B).parts)
        diff = [f for f in names if not (B2 / f).exists() or h256(B / f) != h256(B2 / f)]
        extra = sorted(str(p.relative_to(B2)) for p in B2.rglob("*") if p.is_file() and not (B / p.relative_to(B2)).exists()) if B2.exists() else []
        same_sample = (root2 / "sample-42.md").exists() and h256(root2 / "sample-42.md") == h256(a.sample)
        R.check("the builder run a second time gives the same bytes (every file and the sample)",
                res.returncode == 0 and not diff and not extra and same_sample,
                f"exit {res.returncode}; {len(names)} files compared, {len(diff)} differ {diff[:3]}, extra {extra[:3]}, "
                f"sample equal {same_sample}; rerun in {root2}")
    R.info("time", f"{time.time() - t0:.0f} s")
    return finish(R, B)


def finish(R, B):
    R.out(f"\n== {R.passes} PASS, {R.fails} FAIL")
    try:
        with open(B / "VALIDATION.md", "w", encoding="utf-8") as fh:
            fh.write("# Validation of this build (validate_levels.py output; prose, exempt by name)\n\n```\n"
                     + "\n".join(R.lines) + "\n```\n")
    except OSError:
        pass
    sys.exit(1 if R.fails else 0)


if __name__ == "__main__":
    main()
