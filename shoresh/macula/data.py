"""Read access to macula-spine.db — coreference, frames, participants.

CC BY 4.0 (Clear.Bible MACULA frame/referent layers); no UBS domain/sense data.
"""
from __future__ import annotations

import os
import re
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


def _macula_strong(code: str) -> str:
    """Normalize a user Strong's (H0430 / G0026 / g26) to MACULA's stored form:
    Hebrew zero-padded to 4 (+ optional letter), Greek unpadded. e.g.
    H0430→'0430', H871a→'0871a', G0026→'26', G2424→'2424'."""
    m = re.match(r"^([HhGg])0*(\d+)([a-z]?)$", (code or "").strip())
    if not m:
        return (code or "").strip()
    prefix, num, suf = m.group(1).upper(), int(m.group(2)), m.group(3)
    return f"{num:04d}{suf}" if prefix == "H" else f"{num}{suf}"


def _frame_by_key(con: sqlite3.Connection, verb_key: str) -> dict | None:
    v = con.execute(
        "SELECT book, chapter, verse, word, lemma, gloss FROM macula_words WHERE key=?",
        (verb_key,)).fetchone()
    if not v:
        return None
    roles = []
    for role, arg in con.execute(
            "SELECT role, arg_key FROM frames WHERE verb_key=? ORDER BY role", (verb_key,)):
        t = _tok(arg)
        if t:
            roles.append({"role": role, "arg": t})
    return {"ref": f"{v[0]} {v[1]}:{v[2]}", "word": v[3],
            "verb": {"lemma": v[4], "gloss": (v[5] or "").strip()}, "roles": roles}


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
        return {"verb": None, "roles": []}
    row = con.execute(
        "SELECT DISTINCT f.verb_key FROM frames f JOIN macula_words w ON w.key=f.verb_key "
        "WHERE w.book=? AND w.chapter=? AND w.verse=? AND w.word=?",
        (book.upper(), chapter, verse, word)).fetchone()
    if not row:
        return {"book": book.upper(), "chapter": chapter, "verse": verse, "word": word,
                "verb": None, "roles": []}
    return {"book": book.upper(), "chapter": chapter, "verse": verse, "word": word,
            **_frame_by_key(con, row[0])}


def frame_search(role: str | None = None, arg_strong: str | None = None,
                 arg_lemma: str | None = None, verb_strong: str | None = None,
                 verb_lemma: str | None = None, book: str | None = None,
                 limit: int = 50) -> dict:
    """Search frames: e.g. "where is God (arg_strong=H0430) the agent (role=A0)" →
    every verb (clause) with that role filler, each as a resolved frame. Combine
    arg_*/role with verb_*/book filters. Returns {total, results}."""
    con = _con()
    if con is None:
        return {"total": 0, "results": []}
    where, params = [], []
    sql = "SELECT DISTINCT f.verb_key FROM frames f"
    if arg_strong or arg_lemma:
        sql += " JOIN macula_words a ON a.key=f.arg_key"
    if verb_strong or verb_lemma or book:
        sql += " JOIN macula_words v ON v.key=f.verb_key"
    if role:
        where.append("f.role=?"); params.append(role.upper())
    if arg_strong:
        where.append("a.strong=?"); params.append(_macula_strong(arg_strong))
    if arg_lemma:
        where.append("a.lemma=?"); params.append(arg_lemma)
    if verb_strong:
        where.append("v.strong=?"); params.append(_macula_strong(verb_strong))
    if verb_lemma:
        where.append("v.lemma=?"); params.append(verb_lemma)
    if book:
        where.append("v.book=?"); params.append(book.upper())
    if not where:
        return {"error": "give at least one filter (arg_strong/arg_lemma/verb_strong/"
                         "verb_lemma/role/book)", "total": 0, "results": []}
    total = con.execute(sql.replace("SELECT DISTINCT f.verb_key", "SELECT COUNT(DISTINCT f.verb_key)")
                        + " WHERE " + " AND ".join(where), params).fetchone()[0]
    keys = [r[0] for r in con.execute(
        sql + " WHERE " + " AND ".join(where) + " LIMIT ?", params + [limit]).fetchall()]
    results = [f for f in (_frame_by_key(con, k) for k in keys) if f]
    return {"total": total, "count": len(results), "results": results}


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
