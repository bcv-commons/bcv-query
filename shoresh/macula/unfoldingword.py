"""unfoldingWord (CC BY-SA 4.0) on MACULA's words: the ULT's poetic lines through its word alignment, and the Translation Notes'
support articles through their Hebrew or Greek quotes. No English is read into the facts: from the ULT only the paragraph markers
and the alignment's original-language words, from the notes only the article name (SupportReference), the Quote and Occurrence.

    from macula import unfoldingword as uw
    uw.ult_lines(book, verse_words)   # -> [{"marker": "q1", "verse": (c, v), "words": [index, ...]}] in text order
    uw.notes(book, verse_words)       # -> [{"slug": "figs-rquestion", "verse": (c, v), "words": [index, ...], "fit": "exact", "id": "a1b2"}]

`verse_words` is {(chapter, verse): [(index, normalised surface), ...]} in the book's own numbering, one entry per word (Hebrew: the
morphemes of one word joined). ULT and the notes use English verse numbers; each verse is looked up in the verses vrsmap maps it to and
in the same verse number, and the one where the words are found is used. Words not found are left out (counted in `misses`).

Files: git.door43.org/unfoldingWord/en_ult and en_tn at tag TAG, cached in macula/.cache/unfoldingword/<TAG> ($UW_DIR to override).
"""
from __future__ import annotations

import collections
import csv
import difflib
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TAG = "v91"
RAW = "https://git.door43.org/unfoldingWord/{repo}/raw/tag/" + TAG + "/{name}"
CACHE = Path(os.environ.get("UW_DIR", HERE / ".cache" / "unfoldingword" / TAG))
NUM = {"GEN": 1, "EXO": 2, "LEV": 3, "NUM": 4, "DEU": 5, "JOS": 6, "JDG": 7, "RUT": 8, "1SA": 9, "2SA": 10, "1KI": 11, "2KI": 12, "1CH": 13,
       "2CH": 14, "EZR": 15, "NEH": 16, "EST": 17, "JOB": 18, "PSA": 19, "PRO": 20, "ECC": 21, "SNG": 22, "ISA": 23, "JER": 24, "LAM": 25,
       "EZK": 26, "DAN": 27, "HOS": 28, "JOL": 29, "AMO": 30, "OBA": 31, "JON": 32, "MIC": 33, "NAM": 34, "HAB": 35, "ZEP": 36, "HAG": 37,
       "ZEC": 38, "MAL": 39, "MAT": 41, "MRK": 42, "LUK": 43, "JHN": 44, "ACT": 45, "ROM": 46, "1CO": 47, "2CO": 48, "GAL": 49, "EPH": 50,
       "PHP": 51, "COL": 52, "1TH": 53, "2TH": 54, "1TI": 55, "2TI": 56, "TIT": 57, "PHM": 58, "HEB": 59, "JAS": 60, "1PE": 61, "2PE": 62,
       "1JN": 63, "2JN": 64, "3JN": 65, "JUD": 66, "REV": 67}
misses: collections.Counter = collections.Counter()


def _file(repo: str, name: str) -> Path | None:
    """The release's file, or None where the release has no such book (a marker file remembers that)."""
    p, gone = CACHE / f"{repo}_{name}", CACHE / f"{repo}_{name}.absent"
    if gone.exists():
        return None
    if not p.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        for attempt in range(4):
            try:
                p.write_bytes(urllib.request.urlopen(RAW.format(repo=repo, name=name), timeout=120).read())
                break
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                gone.write_text("not in the release\n")
                return None
            except (TimeoutError, urllib.error.URLError):
                if attempt == 3:
                    raise
                time.sleep(5 * (attempt + 1))
    return p


def norm(s: str) -> str:
    """Letters only, without points, accents or breathings, case-folded (final sigma as sigma)."""
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c)[0] == "L").casefold().replace("ς", "σ")


def _candidates(book: str, c: int, v: int, hebrew: bool) -> list[tuple[int, int]]:
    out = []
    if hebrew:
        sys.path.insert(0, str(HERE.parent))
        from vrsmap import from_eng
        out = [(c2, v2) for _, c2, v2 in from_eng((book, c, v), "org")]
    return out + [(c, v)] if (c, v) not in out else out


class _Verse:
    """Finds original-language words of an English-numbered verse among the book's words."""

    def __init__(self, book: str, verse_words: dict, hebrew: bool):
        self.book, self.vw, self.hebrew = book, verse_words, hebrew

    def nth(self, c: int, v: int, word: str, occurrence: int) -> int | None:
        w = norm(word)
        for cv in _candidates(self.book, c, v, self.hebrew):
            hits = [i for i, s in self.vw.get(cv, []) if s == w]
            if len(hits) >= occurrence > 0:
                return hits[occurrence - 1]
        return None

    def phrase(self, c: int, v: int, quote: str, occurrence: int) -> tuple[list[int], str] | None:
        """The words of a note's Quote (parts joined by '&', each a run of words) at its Occurrence in the verse, and "exact"; else, for
        a first occurrence, the verse's words that match at least 80% of the quote's words in order, and "partial"."""
        parts = [[norm(t) for t in re.split(r"[\s\u05be]+", p) if norm(t)] for p in quote.split("&")]
        parts = [p for p in parts if p]
        if not parts:
            return None
        for cv in _candidates(self.book, c, v, self.hebrew):
            ws = self.vw.get(cv, [])
            starts = [j for j in range(len(ws)) if [s for _, s in ws[j:j + len(parts[0])]] == parts[0]]
            if occurrence < 1 or len(starts) < occurrence:
                continue
            j = starts[occurrence - 1]
            got = [ws[k][0] for k in range(j, j + len(parts[0]))]
            pos = j + len(parts[0])
            for p in parts[1:]:
                nxt = next((k for k in range(pos, len(ws)) if [s for _, s in ws[k:k + len(p)]] == p), None)
                if nxt is None:
                    got = None
                    break
                got += [ws[k][0] for k in range(nxt, nxt + len(p))]
                pos = nxt + len(p)
            if got:
                return got, "exact"
        if occurrence != 1:
            return None
        flat = [t for p in parts for t in p]
        for cv in _candidates(self.book, c, v, self.hebrew):       # the quoted text differs a little from ours (UGNT, UHB)
            ws = self.vw.get(cv, [])
            sm = difflib.SequenceMatcher(None, flat, [s for _, s in ws], autojunk=False)
            got = [ws[j + d][0] for _, j, n in sm.get_matching_blocks() for d in range(n)]
            if len(flat) >= 2 and len(got) >= 0.8 * len(flat):
                return got, "partial"
        return None


def ult_lines(book: str, verse_words: dict, hebrew: bool) -> list[dict]:
    """Each paragraph of the ULT with its marker and the book's words aligned to it, in text order."""
    f = _file("en_ult", f"{NUM[book]:02d}-{book}.usfm")
    if f is None:
        misses["ult_book_absent"] += 1
        return []
    text = f.read_text(encoding="utf-8")
    find = _Verse(book, verse_words, hebrew)
    out: list[dict] = []
    c = v = 0
    cur = None
    for m in re.finditer(r"\\([a-z]+\d?)(-[se])?\b\s*(\|[^\\]*\\\*)?|\\([a-z]+\d?)\*", text):
        tag, attrs = m[1], m[3] or ""
        if tag == "c":
            c = int(re.match(r"\s*(\d+)", text[m.end():])[1])
        elif tag == "v":
            v = int(re.match(r"\s*(\d+)", text[m.end():])[1])
            if cur is not None:
                cur["verses"].add((c, v))
        elif tag in ("p", "m", "q", "q1", "q2", "q3", "q4", "qm1", "qm2", "pi", "pi1", "pi2", "nb", "li", "li1", "li2", "d", "qc", "qr"):
            cur = {"marker": tag, "verse": (c, v), "verses": {(c, v)}, "words": []}
            out.append(cur)
        elif tag == "zaln" and m[2] == "-s" and cur is not None and c and v:
            a = dict(re.findall(r'(x-[a-z]+)="([^"]*)"', attrs))
            i = find.nth(c, v, a.get("x-content", ""), int(a.get("x-occurrence", "1") or 1))
            if i is None:
                misses["ult"] += 1
                continue
            misses["ult_found"] += 1
            if i not in cur["words"]:
                cur["words"].append(i)
    return [p for p in out if p["words"]]


def notes(book: str, verse_words: dict, hebrew: bool, slugs: set[str]) -> list[dict]:
    """The Translation Notes of the given support articles, with the book's words of their Quote."""
    find = _Verse(book, verse_words, hebrew)
    out = []
    path = _file("en_tn", f"tn_{book}.tsv")
    if path is None:
        misses["tn_book_absent"] += 1
        return out
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            slug = (r.get("SupportReference") or "").rsplit("/", 1)[-1]
            m = re.fullmatch(r"(\d+):(\d+)(?:-(\d+))?", r.get("Reference") or "")
            if slug not in slugs or not m or not r.get("Quote"):
                continue
            hit = find.phrase(int(m[1]), int(m[2]), r["Quote"], int(r.get("Occurrence") or 1))
            if hit is None:
                misses["tn"] += 1
                continue
            misses["tn_found"] += 1
            out.append({"slug": slug, "verse": (int(m[1]), int(m[2])), "words": hit[0], "fit": hit[1], "id": r["ID"]})
    return out
