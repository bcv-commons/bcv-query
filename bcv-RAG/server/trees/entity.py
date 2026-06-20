"""Entity tree (people / places / events / deities): type → name-letter → entity.

Leaf returns the entity's full record (relations + verse list) — same
shape as `GET /api/entity/<id>` but reachable through tree navigation.
"""
from __future__ import annotations

import json
import sqlite3
import string

from indexer.references import decode, human

ENTITY_TYPES = ("person", "place", "event", "deity")


def root(db: sqlite3.Connection, *, lang: str = "en") -> dict:
    children = []
    for typ in ENTITY_TYPES:
        n = db.execute("SELECT COUNT(*) FROM entities WHERE type = ?", (typ,)).fetchone()[0]
        children.append({
            "id": typ,
            "label": typ.capitalize() + ("s" if not typ.endswith("s") else ""),
            "child_count": n,
            "url": f"/{lang}/entity/{typ}",
        })
    return {
        "tree": "entity",
        "lang": lang,
        "node": {"id": "root", "label": "Entities (people, places, events)"},
        "children": children,
    }


def descend(db: sqlite3.Connection, path: list[str], *, lang: str = "en") -> dict:
    if not path:
        return root(db, lang=lang)
    if len(path) == 1:
        return _type_view(db, path[0], lang=lang)
    if len(path) == 2:
        return _letter_view(db, path[0], path[1], lang=lang)
    if len(path) == 3:
        return _entity_leaf(db, path[2], lang=lang)
    raise ValueError(f"entity path too deep: {path}")


def _type_view(db, typ: str, *, lang: str) -> dict:
    if typ not in ENTITY_TYPES:
        raise ValueError(f"unknown entity type: {typ}")
    rows = db.execute(
        "SELECT UPPER(SUBSTR(name, 1, 1)) AS letter, COUNT(*) "
        "FROM entities WHERE type = ? GROUP BY letter ORDER BY letter",
        (typ,),
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
            "url": f"/{lang}/entity/{typ}/{letter_id}",
        })
    return {
        "tree": "entity",
        "lang": lang,
        "node": {"id": typ, "label": typ.capitalize() + "s"},
        "children": children,
    }


def _letter_view(db, typ: str, letter_id: str, *, lang: str) -> dict:
    if typ not in ENTITY_TYPES:
        raise ValueError(f"unknown entity type: {typ}")
    if letter_id == "_other":
        rows = db.execute(
            "SELECT id, name FROM entities "
            "WHERE type = ? AND UPPER(SUBSTR(name, 1, 1)) NOT BETWEEN 'A' AND 'Z' "
            "ORDER BY name LIMIT 200",
            (typ,),
        ).fetchall()
        label = "Other"
    else:
        if len(letter_id) != 1 or not letter_id.isalpha():
            raise ValueError(f"bad letter: {letter_id}")
        rows = db.execute(
            "SELECT id, name FROM entities WHERE type = ? AND UPPER(SUBSTR(name, 1, 1)) = ? "
            "ORDER BY name, id LIMIT 200",
            (typ, letter_id.upper()),
        ).fetchall()
        label = letter_id.upper()

    children = []
    for eid, name in rows:
        # We store the full entity_id (including 'person:' prefix etc.)
        # in the `id` field so the leaf URL is unambiguous.
        children.append({
            "id": eid,
            "label": name,
            "url": f"/{lang}/entity/{typ}/{letter_id}/{eid}",
        })
    return {
        "tree": "entity",
        "lang": lang,
        "node": {"id": f"{typ}/{letter_id}", "label": f"{typ.capitalize()} ({label})"},
        "children": children,
    }


def _entity_leaf(db, entity_id: str, *, lang: str) -> dict:
    row = db.execute(
        "SELECT id, type, name, metadata FROM entities WHERE id = ?",
        (entity_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown entity: {entity_id}")
    try:
        metadata = json.loads(row[3]) if row[3] else {}
    except json.JSONDecodeError:
        metadata = {}

    relations = []
    for tgt, rel, name, typ in db.execute(
        """
        SELECT er.target_id, er.relation, e.name, e.type
        FROM entity_relations er LEFT JOIN entities e ON e.id = er.target_id
        WHERE er.source_id = ? ORDER BY er.relation, e.name
        """,
        (entity_id,),
    ):
        relations.append({"direction": "outgoing", "relation": rel,
                          "target_id": tgt, "target_name": name, "target_type": typ})
    for src, rel, name, typ in db.execute(
        """
        SELECT er.source_id, er.relation, e.name, e.type
        FROM entity_relations er LEFT JOIN entities e ON e.id = er.source_id
        WHERE er.target_id = ? ORDER BY er.relation, e.name
        """,
        (entity_id,),
    ):
        relations.append({"direction": "incoming", "relation": rel,
                          "source_id": src, "source_name": name, "source_type": typ})

    verses = []
    for s, e in db.execute(
        "SELECT start_bbcccvvv, end_bbcccvvv FROM entity_passages "
        "WHERE entity_id = ? ORDER BY start_bbcccvvv",
        (entity_id,),
    ):
        try:
            code, ch, v = decode(s)
            book_num = s // 1_000_000
            testament = "ot" if book_num <= 39 else "nt"
            url = f"/{lang}/scripture/{testament}/{code}/{ch}/{v}"
            h = human(s, e)
        except ValueError:
            url = None
            h = f"BBCCCVVV {s}-{e}"
        verses.append({"start_bbcccvvv": s, "end_bbcccvvv": e, "human": h, "url": url})

    return {
        "tree": "entity",
        "lang": lang,
        "node": {
            "id": row[0],
            "label": row[2],
            "type": row[1],
            "metadata": metadata,
            "relation_count": len(relations),
            "passage_count": len(verses),
        },
        "relations": relations,
        "verses": verses,
    }
