"""Verse citations as the rabbinic commentaries print them: "(שמואל ב טו ל)", "(תהלים קיט קסד)", "(ישעיה מ׳:א׳)".

    from macula import hebrew_refs
    hebrew_refs.find(text)    # -> [(start, end, book, chapter, verse)] for every parenthesised Tanakh citation that parses
    hebrew_refs.number("קסד") # -> 164
"""
from __future__ import annotations

import re

BOOKS = {
    "בראשית": "GEN", "שמות": "EXO", "ויקרא": "LEV", "במדבר": "NUM", "דברים": "DEU", "יהושע": "JOS", "שופטים": "JDG",
    "שמואל א": "1SA", "שמואל ב": "2SA", "ש\"א": "1SA", "ש\"ב": "2SA", "מלכים א": "1KI", "מלכים ב": "2KI", "מ\"א": "1KI", "מ\"ב": "2KI",
    "ישעיה": "ISA", "ישעיהו": "ISA", "ירמיה": "JER", "ירמיהו": "JER", "יחזקאל": "EZK", "הושע": "HOS", "יואל": "JOL", "עמוס": "AMO",
    "עובדיה": "OBA", "יונה": "JON", "מיכה": "MIC", "נחום": "NAM", "חבקוק": "HAB", "צפניה": "ZEP", "חגי": "HAG", "זכריה": "ZEC",
    "מלאכי": "MAL", "תהלים": "PSA", "תהילים": "PSA", "משלי": "PRO", "איוב": "JOB", "שיר השירים": "SNG", "רות": "RUT", "איכה": "LAM",
    "קהלת": "ECC", "אסתר": "EST", "דניאל": "DAN", "עזרא": "EZR", "נחמיה": "NEH", "דברי הימים א": "1CH", "דברי הימים ב": "2CH",
    "דה\"א": "1CH", "דה\"ב": "2CH",
}
VAL = {"א": 1, "ב": 2, "ג": 3, "ד": 4, "ה": 5, "ו": 6, "ז": 7, "ח": 8, "ט": 9, "י": 10, "כ": 20, "ך": 20, "ל": 30, "מ": 40, "ם": 40,
       "נ": 50, "ן": 50, "ס": 60, "ע": 70, "פ": 80, "ף": 80, "צ": 90, "ץ": 90, "ק": 100, "ר": 200, "ש": 300, "ת": 400}
NUM = r"[א-ת]{1,4}[׳'״\"]?[א-ת]?"
_NAMES = sorted(BOOKS, key=len, reverse=True)
_PAT = re.compile(r"\(\s*(" + "|".join(re.escape(n) for n in _NAMES) + r")[,\s]+(" + NUM + r")[\s:,.]+(" + NUM + r")\s*\)")


def number(s: str) -> int | None:
    s = re.sub(r"[׳'״\"]", "", s)
    if not s or any(c not in VAL for c in s):
        return None
    return sum(VAL[c] for c in s)


def norm(text: str) -> str:
    return text.replace("״", "\"").replace("׳", "'").replace("”", "\"")


def find(text: str) -> list[tuple[int, int, str, int, int]]:
    out = []
    for m in _PAT.finditer(norm(text)):
        c, v = number(m.group(2)), number(m.group(3))
        if c and v:
            out.append((m.start(), m.end(), BOOKS[m.group(1)], c, v))
    return out
