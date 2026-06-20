"""Lexicon tree: language → Strong's range → Strong's number leaf.

```
/lexicon
  grc                ← Greek (LSJ + Abbott-Smith)
    G0001-G0099
    G0100-G0199
    ...
    G0001            ← leaf: lexicon chunks for that Strong's number
  hbo                ← Hebrew (BDB)
    H0001-H0099
    ...
```

Leaf returns every `kind:lexicon` chunk tagged `strongs:<X####>` —
usually multiple sources (LSJ + Abbott-Smith for Greek, BDB for Hebrew).
"""
from __future__ import annotations

import re
import sqlite3

from indexer import citations as citations_mod
from server.resolver import chunk_preview_from_card

LANGS = {
    "grc": ("Greek", "G"),
    "hbo": ("Hebrew", "H"),
}
RANGE_SIZE = 100  # G0001-G0099, G0100-G0199, etc.


def root(db: sqlite3.Connection, *, lang: str = "en") -> dict:
    children = []
    for code, (label, prefix) in LANGS.items():
        n = db.execute(
            "SELECT COUNT(DISTINCT t.tag) FROM tags t WHERE t.tag LIKE ?",
            (f"strongs:{prefix}%",),
        ).fetchone()[0]
        children.append({
            "id": code,
            "label": label,
            "child_count": n,
            "url": f"/{lang}/lexicon/{code}",
        })
    return {
        "tree": "lexicon",
        "lang": lang,
        "node": {"id": "root", "label": "Lexicons (Greek + Hebrew)"},
        "children": children,
    }


def descend(db: sqlite3.Connection, path: list[str], *, lang: str = "en") -> dict:
    if not path:
        return root(db, lang=lang)
    if len(path) == 1:
        return _language_view(db, path[0], lang=lang)
    if len(path) == 2:
        return _range_view(db, path[0], path[1], lang=lang)
    if len(path) == 3:
        return _strongs_leaf(db, path[2], lang=lang)
    raise ValueError(f"lexicon path too deep: {path}")


def _language_view(db, code: str, *, lang: str) -> dict:
    if code not in LANGS:
        raise ValueError(f"unknown lexicon language: {code}")
    label, prefix = LANGS[code]

    # Compute distinct ranges that have entries.
    rows = db.execute(
        "SELECT DISTINCT t.tag FROM tags t WHERE t.tag LIKE ?",
        (f"strongs:{prefix}%",),
    ).fetchall()
    nums: set[int] = set()
    for (tag,) in rows:
        m = re.match(rf"^strongs:{prefix}(\d+)[a-zA-Z]?$", tag)
        if m:
            nums.add(int(m.group(1)))

    ranges: dict[int, int] = {}  # range-base → count
    for n in nums:
        base = (n // RANGE_SIZE) * RANGE_SIZE or 1
        ranges[base] = ranges.get(base, 0) + 1

    children = []
    for base in sorted(ranges):
        end = base + RANGE_SIZE - 1
        rid = f"{prefix}{base:04d}-{prefix}{end:04d}"
        children.append({
            "id": rid,
            "label": rid,
            "child_count": ranges[base],
            "url": f"/{lang}/lexicon/{code}/{rid}",
        })
    return {
        "tree": "lexicon",
        "lang": lang,
        "node": {"id": code, "label": label},
        "children": children,
    }


def _range_view(db, code: str, range_id: str, *, lang: str) -> dict:
    if code not in LANGS:
        raise ValueError(f"unknown lexicon language: {code}")
    label, prefix = LANGS[code]
    m = re.match(rf"^{prefix}(\d{{4}})-{prefix}(\d{{4}})$", range_id)
    if not m:
        raise ValueError(f"bad range id: {range_id}")
    lo, hi = int(m.group(1)), int(m.group(2))

    rows = db.execute(
        "SELECT DISTINCT t.tag FROM tags t WHERE t.tag LIKE ?",
        (f"strongs:{prefix}%",),
    ).fetchall()
    entries: list[tuple[int, str]] = []
    for (tag,) in rows:
        mm = re.match(rf"^strongs:({prefix}\d+[a-zA-Z]?)$", tag)
        if not mm:
            continue
        s = mm.group(1)
        n = int(re.match(rf"^{prefix}(\d+)", s).group(1))
        if lo <= n <= hi:
            entries.append((n, s))

    children = []
    for _, strongs in sorted(entries):
        children.append({
            "id": strongs,
            "label": strongs,
            "url": f"/{lang}/lexicon/{code}/{range_id}/{strongs}",
        })
    return {
        "tree": "lexicon",
        "lang": lang,
        "node": {"id": f"{code}/{range_id}", "label": f"{label} {range_id}"},
        "children": children,
    }


def _strongs_leaf(db, strongs: str, *, lang: str) -> dict:
    rows = db.execute(
        """
        SELECT chunks.id FROM chunks
        JOIN tags k ON k.doc_id = chunks.doc_id AND k.tag = 'kind:lexicon'
        JOIN tags s ON s.doc_id = chunks.doc_id AND s.tag = ?
        """,
        (f"strongs:{strongs}",),
    ).fetchall()
    cards = citations_mod.resolve_many(db, [r[0] for r in rows])
    return {
        "tree": "lexicon",
        "lang": lang,
        "node": {"id": strongs, "label": strongs},
        "chunks": [chunk_preview_from_card(c, lang=lang) for c in cards],
    }
