"""Transcript tree (BibleProject): series → video → chunks.

```
/transcript                    series listing (Insight-Videos / Redemption / …)
  Insight-Videos               video listing
    Nissah-Test                leaf: chunks for that video (timestamp + bible_reference + semantic strategies)
```

Series are derived from `series:` tags emitted by `ingest.bibleproject`;
videos are aggregated by `documents.title` (which carries the
PDF/transcript title from the BibleProject pipeline). The leaf returns
all chunks for the video across the three chunking strategies — group
client-side by `chunk_strategy:` tag if needed.
"""
from __future__ import annotations

import sqlite3

from indexer import citations as citations_mod
from server.resolver import chunk_preview_from_card


def root(db: sqlite3.Connection, *, lang: str = "en") -> dict:
    rows = db.execute(
        """
        SELECT REPLACE(t.tag, 'series:', '') AS series, COUNT(DISTINCT chunks.doc_id)
        FROM tags t
        JOIN chunks ON chunks.doc_id = t.doc_id
        JOIN tags k ON k.doc_id = t.doc_id AND k.tag = 'kind:video-transcript'
        WHERE t.tag LIKE 'series:%'
        GROUP BY series ORDER BY series
        """
    ).fetchall()
    children = []
    for series, n in rows:
        children.append({
            "id": series,
            "label": series.replace("-", " ").title(),
            "child_count": n,
            "url": f"/{lang}/transcript/{series}",
        })
    return {
        "tree": "transcript",
        "lang": lang,
        "node": {"id": "root", "label": "BibleProject Transcripts"},
        "children": children,
    }


def descend(db: sqlite3.Connection, path: list[str], *, lang: str = "en") -> dict:
    if not path:
        return root(db, lang=lang)
    if len(path) == 1:
        return _series_view(db, path[0], lang=lang)
    if len(path) == 2:
        return _video_leaf(db, path[0], path[1], lang=lang)
    raise ValueError(f"transcript path too deep: {path}")


def _series_view(db, series: str, *, lang: str) -> dict:
    rows = db.execute(
        """
        SELECT documents.title, COUNT(*)
        FROM documents
        JOIN tags k ON k.doc_id = documents.id AND k.tag = 'kind:video-transcript'
        JOIN tags s ON s.doc_id = documents.id AND s.tag = ?
        GROUP BY documents.title ORDER BY documents.title
        """,
        (f"series:{series}",),
    ).fetchall()
    # Derive a slug per video from the title (the title carries the
    # PDF title with the chunk-strategy suffix the BibleProject pipeline
    # produces, e.g. "BibleProject — 02 Wisdom of Solomon Transcript (timestamp)").
    # We collapse those back to a per-video slug.
    seen: dict[str, int] = {}
    children = []
    for title, n in rows:
        # Strip leading "BibleProject — " and trailing " (strategy)" if present.
        bare = title
        if bare.startswith("BibleProject"):
            parts = bare.split("—", 1)
            if len(parts) == 2:
                bare = parts[1].strip()
        if bare.endswith(")") and "(" in bare:
            bare = bare.rsplit("(", 1)[0].strip()
        slug = _slugify(bare)
        if slug in seen:
            seen[slug] += n
            continue
        seen[slug] = n
        children.append({"id": slug, "label": bare, "child_count": n,
                         "url": f"/{lang}/transcript/{series}/{slug}",
                         "_count_so_far": n})
    # Update child_count totals (multiple titles can collapse to same slug).
    for c in children:
        c["child_count"] = seen[c["id"]]
        del c["_count_so_far"]
    return {
        "tree": "transcript",
        "lang": lang,
        "node": {"id": series, "label": series.replace("-", " ").title()},
        "children": children,
    }


def _video_leaf(db, series: str, video_slug: str, *, lang: str) -> dict:
    # Find documents whose title slugifies to video_slug, scoped to this series.
    rows = db.execute(
        """
        SELECT documents.id, documents.title
        FROM documents
        JOIN tags k ON k.doc_id = documents.id AND k.tag = 'kind:video-transcript'
        JOIN tags s ON s.doc_id = documents.id AND s.tag = ?
        """,
        (f"series:{series}",),
    ).fetchall()
    matching_doc_ids: list[str] = []
    for doc_id, title in rows:
        bare = title
        if bare.startswith("BibleProject"):
            parts = bare.split("—", 1)
            if len(parts) == 2:
                bare = parts[1].strip()
        if bare.endswith(")") and "(" in bare:
            bare = bare.rsplit("(", 1)[0].strip()
        if _slugify(bare) == video_slug:
            matching_doc_ids.append(doc_id)

    if not matching_doc_ids:
        raise ValueError(f"unknown video: {series}/{video_slug}")

    placeholders = ",".join("?" * len(matching_doc_ids))
    chunk_rows = db.execute(
        f"SELECT id FROM chunks WHERE doc_id IN ({placeholders}) ORDER BY doc_id, chunk_index",
        matching_doc_ids,
    ).fetchall()
    cards = citations_mod.resolve_many(db, [r[0] for r in chunk_rows])
    return {
        "tree": "transcript",
        "lang": lang,
        "node": {"id": f"{series}/{video_slug}", "series": series, "label": video_slug.replace("-", " ").title()},
        "chunks": [chunk_preview_from_card(c, lang=lang) for c in cards],
    }


def _slugify(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
