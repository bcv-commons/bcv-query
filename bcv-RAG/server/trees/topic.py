"""Topic tree (Nave's): A-Z letter index → topic id → leaf.

Leaf returns the topic's verses with each verse pre-resolved to a Bible-tree
URL plus the topic_id and source. Counts are computed at the letter and
topic levels so the UI can render the tree without extra round trips.
"""
from __future__ import annotations

import sqlite3
import string

from indexer.references import decode, human


def root(db: sqlite3.Connection, *, lang: str = "en") -> dict:
    """Letter index — only letters that have at least one topic."""
    rows = db.execute(
        "SELECT UPPER(SUBSTR(name, 1, 1)) AS letter, COUNT(*) "
        "FROM topics GROUP BY letter ORDER BY letter"
    ).fetchall()
    children = []
    for letter, n in rows:
        if not letter or letter not in string.ascii_uppercase:
            letter_id = "_other"
            label = "Other"
        else:
            letter_id = letter.lower()
            label = letter
        children.append({
            "id": letter_id,
            "label": label,
            "child_count": n,
            "url": f"/{lang}/topic/{letter_id}",
        })
    return {
        "tree": "topic",
        "lang": lang,
        "node": {"id": "root", "label": "Topics (Nave's)"},
        "children": children,
    }


def descend(db: sqlite3.Connection, path: list[str], *, lang: str = "en") -> dict:
    if not path:
        return root(db, lang=lang)
    if len(path) == 1:
        return _letter_view(db, path[0], lang=lang)
    if len(path) == 2:
        return _topic_leaf(db, path[1], lang=lang)
    raise ValueError(f"topic path too deep: {path}")


def _letter_view(db, letter_id: str, *, lang: str) -> dict:
    if letter_id == "_other":
        rows = db.execute(
            "SELECT id, name FROM topics "
            "WHERE UPPER(SUBSTR(name, 1, 1)) NOT BETWEEN 'A' AND 'Z' "
            "ORDER BY name"
        ).fetchall()
        label = "Other"
    else:
        if len(letter_id) != 1 or not letter_id.isalpha():
            raise ValueError(f"bad letter: {letter_id}")
        rows = db.execute(
            "SELECT id, name FROM topics "
            "WHERE UPPER(SUBSTR(name, 1, 1)) = ? ORDER BY name",
            (letter_id.upper(),),
        ).fetchall()
        label = letter_id.upper()

    children = []
    for tid, name in rows:
        n = db.execute(
            "SELECT COUNT(*) FROM topic_passages WHERE topic_id = ?", (tid,)
        ).fetchone()[0]
        children.append({
            "id": tid,
            "label": name,
            "child_count": n,
            "url": f"/{lang}/topic/{letter_id}/{tid}",
        })
    return {
        "tree": "topic",
        "lang": lang,
        "node": {"id": letter_id, "label": label},
        "children": children,
    }


def _topic_leaf(db, topic_id: str, *, lang: str) -> dict:
    row = db.execute("SELECT id, name, source FROM topics WHERE id = ?", (topic_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown topic: {topic_id}")
    pass_rows = db.execute(
        "SELECT start_bbcccvvv, end_bbcccvvv FROM topic_passages "
        "WHERE topic_id = ? ORDER BY start_bbcccvvv",
        (topic_id,),
    ).fetchall()

    verses = []
    for s, e in pass_rows:
        try:
            code, ch, v = decode(s)
            book_num = s // 1_000_000
            testament = "ot" if book_num <= 39 else "nt"
            url = f"/{lang}/scripture/{testament}/{code}/{ch}/{v}"
            h = human(s, e)
        except ValueError:
            url = None
            h = f"BBCCCVVV {s}-{e}"
        verses.append({
            "start_bbcccvvv": s,
            "end_bbcccvvv": e,
            "human": h,
            "url": url,
        })

    return {
        "tree": "topic",
        "lang": lang,
        "node": {
            "id": row[0],
            "label": row[1],
            "source": row[2],
            "passage_count": len(verses),
        },
        # Topic verse lists aren't chunks per se — they're verse references.
        # We surface them under `verses` instead of `chunks` so the client
        # can render them as links into the scripture/bible tree.
        "verses": verses,
    }
