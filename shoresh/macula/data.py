"""Read access to macula-spine.db — coreference, frames, participants.

CC BY 4.0 (Clear.Bible MACULA frame/referent layers); no UBS domain/sense data.
"""
from __future__ import annotations

import os
import sqlite3
from functools import lru_cache
from pathlib import Path

_DB = Path(os.environ.get("MACULA_DB", Path(__file__).resolve().parent / "macula-spine.db"))


@lru_cache(maxsize=1)
def _con() -> sqlite3.Connection | None:
    if not _DB.exists():
        return None
    return sqlite3.connect(f"file:{_DB}?mode=ro", uri=True, check_same_thread=False)


def available() -> bool:
    return _con() is not None


def _tok(key: str) -> dict | None:
    con = _con()
    if con is None:
        return None
    r = con.execute(
        "SELECT lang, book, chapter, verse, word, lemma, strong, gloss, text "
        "FROM macula_words WHERE key=?", (key,)).fetchone()
    if not r:
        return None
    return {"ref": f"{r[1]} {r[2]}:{r[3]}", "word": r[4], "lemma": r[5],
            "strong": r[6] or None, "gloss": (r[7] or "").strip(), "text": (r[8] or "").strip()}


def coref(book: str, chapter: int, verse: int, word: int) -> dict:
    """For the word at this reference, who/what its referent pointers point to —
    'who is "he/his" here'. Reads referent (Greek) / participantref (Hebrew) / subjref."""
    con = _con()
    if con is None:
        return {"refers_to": []}
    rows = con.execute(
        "SELECT r.kind, r.tgt_key, w.text, w.lemma FROM refs r "
        "JOIN macula_words w ON w.key = r.src_key "
        "WHERE w.book=? AND w.chapter=? AND w.verse=? AND w.word=?",
        (book.upper(), chapter, verse, word)).fetchall()
    out = []
    for kind, tgt, text, lemma in rows:
        t = _tok(tgt)
        if t:
            out.append({"kind": kind, "from": {"text": (text or "").strip(), "lemma": lemma}, "refers_to": t})
    return {"book": book.upper(), "chapter": chapter, "verse": verse, "word": word, "refers_to": out}


def frame(book: str, chapter: int, verse: int, word: int) -> dict:
    """The semantic frame of the verb at this reference — PropBank roles (A0 agent,
    A1 patient, …) resolved to their argument tokens (glossed)."""
    con = _con()
    if con is None:
        return {"roles": []}
    rows = con.execute(
        "SELECT f.verb_key, f.role, f.arg_key, w.lemma, w.gloss FROM frames f "
        "JOIN macula_words w ON w.key = f.verb_key "
        "WHERE w.book=? AND w.chapter=? AND w.verse=? AND w.word=?",
        (book.upper(), chapter, verse, word)).fetchall()
    verb = None
    roles = []
    for _vk, role, arg, lemma, gloss in rows:
        verb = {"lemma": lemma, "gloss": (gloss or "").strip()}
        t = _tok(arg)
        if t:
            roles.append({"role": role, "arg": t})
    return {"book": book.upper(), "chapter": chapter, "verse": verse, "word": word,
            "verb": verb, "roles": roles}


def participants(book: str, chapter: int, verse: int) -> dict:
    """All participant/referent links in a verse — the participant chain: each
    referring word and the entity it points to."""
    con = _con()
    if con is None:
        return {"participants": []}
    rows = con.execute(
        "SELECT w.word, w.text, w.lemma, r.kind, r.tgt_key FROM refs r "
        "JOIN macula_words w ON w.key = r.src_key "
        "WHERE w.book=? AND w.chapter=? AND w.verse=? ORDER BY w.word",
        (book.upper(), chapter, verse)).fetchall()
    out = []
    for word, text, lemma, kind, tgt in rows:
        t = _tok(tgt)
        if t:
            out.append({"word": word, "text": (text or "").strip(), "lemma": lemma,
                        "kind": kind, "refers_to": t})
    return {"book": book.upper(), "chapter": chapter, "verse": verse, "participants": out}
