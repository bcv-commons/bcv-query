"""Hebrew verse <-> GLAUx Septuagint verse, for lookups that look for a word in "the same verse" of the Septuagint.

GLAUx numbers the Septuagint's own way (Psalms 10-147 one off, Jeremiah 25-51 in another order, Exodus 35-40, 1 Kings 20-21,
...). A lookup keyed by the Hebrew chapter and verse found MACULA's aligned Greek word in its GLAUx verse for 0.785 of Hebrew words
(Psalms 0.13, Jeremiah 0.45); through these keys 0.867. Both sides go to the English scheme with vrsmap (bibles' TVTMS maps), except
Daniel, whose GLAUx text carries the Greek additions in chapter 3: there the Hebrew verse is moved to the Greek one directly.
"""
from __future__ import annotations

import functools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vrsmap  # noqa: E402


def dan_greek_verse(ch: int, v: int) -> tuple[int, int]:
    """Hebrew / Aramaic Daniel verse -> GLAUx verse (the Greek carries the 3:24-90 additions; MT 3:31-33 is Greek 4:1-3)"""
    if ch == 3 and 24 <= v <= 30:
        return 3, v + 67
    if ch == 3 and v >= 31:
        return 4, v - 30
    if ch == 4:
        return 4, v + 3
    return ch, v


@functools.lru_cache(maxsize=None)
def greek_keys(book: str, ch: int, v: int) -> tuple:
    """the keys a GLAUx verse is filed under"""
    if book == "DAN":
        return ((book, ch, v),)
    return tuple(tuple(e) for e in vrsmap.to_eng((book, ch, v), "lxx"))


@functools.lru_cache(maxsize=None)
def hebrew_keys(book: str, ch: int, v: int) -> tuple:
    """the keys to look a Hebrew verse up under, in the same key space as greek_keys"""
    if book == "DAN":
        return ((book,) + dan_greek_verse(ch, v),)
    return tuple(tuple(e) for e in vrsmap.to_eng((book, ch, v), "org"))


GLAUX = Path(__file__).resolve().parents[1] / "lxx" / "data" / "lxx-glaux.db"
THEODOTION = Path(__file__).resolve().parents[1] / "lxx" / "data" / "lxx-glaux-dan-theodotion.db"   # build_glaux --doc DAN=57


def dan_hebrew_verse(ch: int, v: int):
    """GLAUx Daniel verse -> Hebrew / Aramaic verse; None for the Greek-only verses (3:24-90, the Prayer and the Song)"""
    if ch == 3 and 24 <= v <= 90:
        return None
    if ch == 3 and v >= 91:
        return 3, v - 67
    if ch == 4 and v <= 3:
        return 3, v + 30
    if ch == 4:
        return 4, v - 3
    return ch, v


def verse_rows(sql: str):
    """for verse-level reads (the bridge's co-occurrence tiers): (scheme, rows) pairs, rows starting with book, chapter, verse.
    Daniel is read from Theodotion, which follows the Hebrew and Aramaic closely, in Hebrew numbering; every other book from GLAUx's
    default documents in the Septuagint's numbering. Word-level reads keep the Old Greek: MACULA aligns Daniel's words to it."""
    import sqlite3
    with sqlite3.connect(f"file:{GLAUX}?mode=ro", uri=True) as g:
        yield "lxx", [r for r in g.execute(sql) if r[0] != "DAN"]
    with sqlite3.connect(f"file:{THEODOTION}?mode=ro", uri=True) as t:
        dan = []
        for r in t.execute(sql):
            if r[0] == "DAN" and (hv := dan_hebrew_verse(r[1], r[2])):
                dan.append((r[0],) + hv + tuple(r[3:]))
        yield "org", dan
