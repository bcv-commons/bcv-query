"""Miqra according to the Masorah (MAM; Hebrew Wikisource, CC BY-SA 4.0) on MACULA's words: the song layout (the line breaks the
Masoretic tradition gives the songs, `מ:ששש`) and MAM's own paragraph marks (`פפ` petuchah, `סס` setumah), from MAM-parsed plus.

    from macula import mam
    mam.verses("EXO")                      # -> {(c, v): [("w", word) | ("break", "song") | ("pe" | "sa", None), ...]}
    mam.songs("EXO", verse_words)          # -> [{"verses": [(c, v), ...], "lines": [(first index, last index), ...]}]
    mam.sections("EXO", verse_words)       # -> [("pe" | "sa", index of the word the paragraph ends with)]

Only the words' places are read (to put a break between two MACULA words); MAM's text is not carried. `verse_words` is
{(chapter, verse): [(index, normalised word), ...]} as in unfoldingword. Files: github.com/bdenckla/MAM-basics, MAM-parsed/plus,
commit PIN, cached in macula/.cache/mam/<PIN> ($MAM_DIR to override).
"""
from __future__ import annotations

import difflib
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

from macula.unfoldingword import norm

HERE = Path(__file__).resolve().parent
PIN = "cfdbb64ef8fc24e777d4d296efb7fe4ac966346d"
RAW = f"https://raw.githubusercontent.com/bdenckla/MAM-basics/{PIN}/MAM-parsed/plus/"
CACHE = Path(os.environ.get("MAM_DIR", HERE / ".cache" / "mam" / PIN))
FILES = {"GEN": ("A1-Genesis", None), "EXO": ("A2-Exodus", None), "LEV": ("A3-Levit", None), "NUM": ("A4-Numbers", None),
         "DEU": ("A5-Deuter", None), "JOS": ("B1-Joshua", None), "JDG": ("B2-Judges", None), "1SA": ("BA-Samuel", 0),
         "2SA": ("BA-Samuel", 1), "1KI": ("BC-Kings", 0), "2KI": ("BC-Kings", 1), "ISA": ("C1-Isaiah", None),
         "JER": ("C2-Jeremiah", None), "EZK": ("C3-Ezekiel", None), "PSA": ("D1-Psalms", None), "PRO": ("D2-Proverbs", None),
         "JOB": ("D3-Job", None), "SNG": ("E1-Song of Songs", None), "RUT": ("E2-Ruth", None), "LAM": ("E3-Lamentations", None),
         "ECC": ("E4-Ecclesiastes", None), "EST": ("E5-Esther", None), "DAN": ("F1-Daniel", None), "EZR": ("FA-Ezra-Nexemiah", 0),
         "NEH": ("FA-Ezra-Nexemiah", 1), "1CH": ("FC-Chronicles", 0), "2CH": ("FC-Chronicles", 1)}
TWELVE = ["HOS", "JOL", "AMO", "OBA", "JON", "MIC", "NAM", "HAB", "ZEP", "HAG", "ZEC", "MAL"]
FILES.update({b: ("CA-The-12-Minor-Prophets", i) for i, b in enumerate(TWELVE)})
BREAKS = {"מ:ששש": "song", "פפ": "pe", "סס": "sa", "ססס": "sa", "ר0": "r0", "ר1": "r1", "ר2": "r2", "ר3": "r3", "ר4": "r4"}
LINE_BREAKS = {"r0", "r1", "r2", "r3", "r4"}        # the poetic line breaks of Psalms, Proverbs and Job, with the template that gives them
NOTES = {"ש", "מ:הערה-2", "מ:קישור בהערה", "מ:אין פרשה בתחילת פרק", "מ:ספר חדש", "מ:פסוק", "מ:עלייה", "מ:פסק"}


def _book(book: str) -> dict:
    name, i = FILES[book]
    p = CACHE / f"{name}.json"
    if not p.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        p.write_bytes(urllib.request.urlopen(RAW + urllib.parse.quote(name) + ".json", timeout=120).read())
    b39 = json.loads(p.read_text(encoding="utf-8"))["book39s"]
    return b39[i or 0]


def _text(x, out: list):
    """The Scripture text of a MAM item, with the breaks as markers; notes are skipped, the first branch of a choice is taken."""
    if isinstance(x, str):
        out.append(("t", x))
    elif isinstance(x, list):
        for y in x:
            _text(y, out)
    elif isinstance(x, dict):
        name, params = x.get("tmpl_name"), x.get("tmpl_params") or {}
        if name in BREAKS:
            out.append((BREAKS[name], None))
        elif name in NOTES:
            return
        elif name in ("כו״ק", "קו״כ", "מ:כו״ק מיוחד", "מ:קו״כ-אם-2"):
            _text(params.get("1", ""), out)                         # one branch (the ketiv); MACULA keeps the written text
        elif "1" in params:
            _text(params["1"], out)


def verses(book: str) -> dict[tuple[int, int], list]:
    out = {}
    for c, vs in _book(book)["chapters"].items():
        for v, parts in vs.items():
            items: list = []
            _text(parts, items)
            seq, buf = [], ""
            for kind, val in items + [("end", None)]:
                if kind == "t":
                    buf += val
                    continue
                for w in re.split(r"[\s־]+", buf):
                    if norm(w):
                        seq.append(("w", w))
                buf = ""
                if kind != "end":
                    seq.append((kind, None))
            out[(int(c), int(v))] = seq
    return out


def _align(seq: list, words: list) -> list[int | None]:
    """For each MAM word of a verse, the index of the MACULA word it is (None where the texts differ)."""
    mw = [norm(w) for k, w in seq if k == "w"]
    at: list[int | None] = [None] * len(mw)
    for i, j, n in difflib.SequenceMatcher(None, mw, [s for _, s in words], autojunk=False).get_matching_blocks():
        for d in range(n):
            at[i + d] = words[j + d][0]
    return at


def songs(book: str, verse_words: dict) -> list[dict]:
    """The passages MAM sets in song layout, each line as (index of its first word, index of its last word's first morpheme)."""
    vs = verses(book)
    order = sorted(vs)
    song = [any(k == "song" for k, _ in vs[cv]) for cv in order]
    for n in range(1, len(order) - 1):                  # a one-line verse inside a song has no break of its own (2 Sam 22:13)
        if not song[n] and song[n - 1] and song[n + 1] and order[n - 1][0] == order[n + 1][0]:
            song[n] = True
    runs, cur = [], []
    for cv, on in zip(order, song):
        if on:
            cur.append(cv)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    out = []
    for run in runs:
        lines, line = [], []
        started = False
        for n, cv in enumerate(run):
            seq = vs[cv]
            if n and not any(k == "song" for k, _ in seq):
                if line:
                    lines.append(line)
                line, started = [], True
            at = iter(_align(seq, verse_words.get(cv, [])))
            for k, _ in seq:
                if k == "song":
                    if line:
                        lines.append(line)
                    line, started = [], True
                elif k == "w":
                    i = next(at)
                    if started and i is not None:
                        line.append(i)
            if n == len(run) - 1 and line:
                lines.append(line)
        lines = [(min(l), max(l)) for l in lines if l]
        if lines:
            out.append({"verses": run, "lines": lines})
    return out


def poem_lines(book: str, verse_words: dict) -> list[dict]:
    """MAM's poetic lines (Psalms, Proverbs, Job): runs of verses that carry line breaks (ר0-ר4); a line starts at each verse and at
    each break. Each line as (index of its first word, index of its last word's first morpheme), with the break that opens it
    ("v" at a verse start, else the template: r0 ... r4)."""
    vs = verses(book)
    order = sorted(vs)
    on = [any(k in LINE_BREAKS for k, _ in vs[cv]) for cv in order]
    for n in range(1, len(order) - 1):
        if not on[n] and on[n - 1] and on[n + 1] and order[n - 1][0] == order[n + 1][0]:
            on[n] = True
    runs, cur = [], []
    for cv, flag in zip(order, on):
        if flag and cur and cv[0] != cur[-1][0]:
            runs.append(cur)
            cur = []
        if flag:
            cur.append(cv)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    out = []
    for run in runs:
        lines, marks = [], []
        for cv in run:
            seq = vs[cv]
            at = iter(_align(seq, verse_words.get(cv, [])))
            line, mark = [], "v"
            for k, _ in seq:
                if k in LINE_BREAKS:
                    if line:
                        lines.append(line); marks.append(mark)
                    line, mark = [], k
                elif k == "w":
                    i = next(at)
                    if i is not None:
                        line.append(i)
            if line:
                lines.append(line); marks.append(mark)
        if lines:
            out.append({"verses": run, "lines": [(min(l), max(l)) for l in lines], "markers": marks})
    return out


def sections(book: str, verse_words: dict) -> list[tuple[str, int]]:
    """MAM's petuchah/setumah as ("pe" | "sa", index of the MACULA word the paragraph ends with). A mark before a verse's first word
    ends the verse before it; one inside a verse (פסקא באמצע פסוק) ends at the word before it."""
    vs = verses(book)
    order = sorted(vs)
    out = []
    for n, cv in enumerate(order):
        seq = vs[cv]
        at = _align(seq, verse_words.get(cv, []))
        w = 0
        for k, _ in seq:
            if k == "w":
                w += 1
            elif k in ("pe", "sa"):
                if w == 0:
                    prev = verse_words.get(order[n - 1], []) if n else []
                    if prev:
                        out.append((k, prev[-1][0]))
                elif at[w - 1] is not None:
                    out.append((k, at[w - 1]))
    return sorted(set(out), key=lambda x: x[1])
