"""The printed layout of Nestle's Greek New Testament of 1904, on MACULA Greek's words.

resources/passage_facts/nestle1904_layout.tsv lists the passages the edition prints set apart (poetic lines, a narrower block, lines
quoted from the Scriptures), read from the page images. It is a reviewed table and gives verse ranges only. The printed lines inside
a range come from the digital edition (github.com/biblicalhumanities/Nestle1904, `xhtml/`, public domain: one <p> per printed line),
whose words are matched one to one to MACULA Greek's words (the same edition's text).

    from macula import nestle1904_layout
    rows = nestle1904_layout.passages("LUK", words)   # words: [(key, surface)] of the book in text order
    # -> [{"start", "end", "class", "lines", "leaf", "first", "last", "line_spans": [(first, last), ...] or None, "note"}]

`line_spans` is None where the digital lines do not fit the table (the count differs from the printed count, or the block starts
inside a paragraph): then only the span is given, and for a range that starts or ends inside a verse (`b`, `a`) the span is the whole
verses with `precision` "p.verse".

The xhtml files are read from $N1904_XHTML_DIR or downloaded once to macula/.cache/nestle1904-xhtml (commit PIN).
"""
from __future__ import annotations

import csv
import difflib
import html
import os
import re
import unicodedata
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TABLE = HERE.parents[1] / "resources" / "passage_facts" / "nestle1904_layout.tsv"
PIN = "713f28a3b7d4d66132f5aa809fa223fe79762e5d"
RAW = f"https://raw.githubusercontent.com/biblicalhumanities/Nestle1904/{PIN}/xhtml/"
CACHE = HERE / ".cache" / "nestle1904-xhtml"
FILES = {"MAT": "Matthew", "MRK": "Mark", "LUK": "Luke", "JHN": "John", "ACT": "Acts", "ROM": "Romans", "1CO": "1-Corinthians",
         "2CO": "2-Corinthians", "GAL": "Galatians", "EPH": "Ephesians", "PHP": "Philippians", "COL": "Colossians",
         "1TH": "1-Thessalonians", "2TH": "2-Thessalonians", "1TI": "1-Timothy", "2TI": "2-Timothy", "TIT": "Titus", "PHM": "Philemon",
         "HEB": "Hebrews", "JAS": "James", "1PE": "1-Peter", "2PE": "2-Peter", "1JN": "1-John", "2JN": "2-John", "3JN": "3-John",
         "JUD": "Jude", "REV": "Revelation"}


def _xhtml(book: str) -> str:
    name = FILES[book] + "-ap.xhtml"
    d = Path(os.environ.get("N1904_XHTML_DIR", CACHE))
    for cand in (d / name, d / (FILES[book] + ".xhtml")):
        if cand.exists():
            return cand.read_text(encoding="utf-8")
    d.mkdir(parents=True, exist_ok=True)
    data = urllib.request.urlopen(RAW + name, timeout=60).read()
    (d / name).write_bytes(data)
    return data.decode("utf-8")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c)[0] == "L").casefold()


def paragraphs(book: str) -> list[list[str]]:
    """The book's <p> elements as lists of normalised Greek words (verse numbers and headings dropped)."""
    body = _xhtml(book).split("<body", 1)[1]
    out = []
    for m in re.finditer(r"<p[^>]*>(.*?)</p>", body, re.S):
        text = html.unescape(re.sub(r"<[^>]+>", " ", m[1])).replace("\xa0", " ")
        toks = [t for t in (_norm(w) for w in text.split()) if t]
        if toks:
            out.append(toks)
    return out


def align(book: str, words: list[tuple[str, str]]) -> list[tuple[int, int]]:
    """Each paragraph as (index of its first word, index of its last word) in `words`. The two texts are the same edition; they are
    matched as two word sequences (MACULA's key order differs from the text order in a few places, and the file has headings), and a
    paragraph none of whose words match is left out."""
    norm = [_norm(s) for _, s in words]
    paras = paragraphs(book)
    flat = [t for toks in paras for t in toks]
    at = [-1] * len(flat)
    for i, j, n in difflib.SequenceMatcher(None, flat, norm, autojunk=False).get_matching_blocks():
        for d in range(n):
            at[i + d] = j + d
    out, pos = [], 0
    for toks in paras:
        hit = [x for x in at[pos:pos + len(toks)] if x >= 0]
        pos += len(toks)
        if hit and len(hit) * 2 >= len(toks):
            out.append((min(hit), max(hit)))
    return out


def _ref(s: str) -> tuple[int, int, str]:
    m = re.match(r"(\d+):(\d+)([ab]?)$", s)
    return int(m[1]), int(m[2]), m[3]


def table(book: str) -> list[dict]:
    with open(TABLE, encoding="utf-8") as f:
        return [r for r in csv.DictReader((l for l in f if not l.startswith("#")), delimiter="\t") if r["book"] == book]


def passages(book: str, words: list[tuple[str, str]]) -> list[dict]:
    """The table's rows for a book with their word spans; see the module text."""
    cv = [(int(k[2:5]), int(k[5:8])) for k, _ in words]
    paras = align(book, words)
    out = []
    for r in table(book):
        (c1, v1, p1), (c2, v2, p2) = _ref(r["start"]), _ref(r["end"])
        idx = [i for i, x in enumerate(cv) if (c1, v1) <= x <= (c2, v2)]
        if not idx:
            out.append({**r, "first": None, "last": None, "line_spans": None, "precision": "p.verse", "note": "verses not in the text"})
            continue
        lo, hi = idx[0], idx[-1]
        cand = [(a, b) for a, b in paras if lo <= a and b <= hi]
        if p1 == "b" and cand and cand[0][0] == lo:               # the paragraph that opens the verse is the lead-in, not a line
            cand = cand[1:]
        want = int(r["lines"]) if r["lines"] else 1
        row = {**r, "line_spans": None, "note": ""}
        if r["class"] == "block":
            fit = cand[:1] if cand else []
            if p2 == "" and fit and fit[0][1] != hi and len(cand) == 1:
                fit = []                                          # the block must run to the end of its last verse
        else:
            fit = cand[:want] if len(cand) >= want else []
            if p2 == "" and fit and fit[-1][1] != hi:
                fit = []
        if fit:
            row.update(first=words[fit[0][0]][0], last=words[fit[-1][1]][0], precision="p.word",
                       line_spans=[(words[a][0], words[b][0]) for a, b in fit] if r["class"] != "block" else None)
        else:
            row.update(first=words[lo][0], last=words[hi][0], precision="p.word" if not (p1 or p2) else "p.verse",
                       note=f"digital lines do not fit ({len(cand)} paragraphs in range, {want} printed)")
        out.append(row)
    return out
