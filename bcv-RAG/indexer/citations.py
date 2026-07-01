"""Resolve a provenance reference back to a user-facing SourceLead.

Cards are what the UI shows. Every claim in an answer carries one card so
the user can see exactly which source backs it.

Provenance ids
--------------
A provenance id is the stable string the LLM cites and the validator
checks. Today the system has one kind: `chunk` — bare chunk ids like
``"56001001:0001"``. Stage 1 of the expansion plan introduces the
generalized form so future content (entities, lexicon entries, graph
relations) cites uniformly:

  chunk:<chunk_id>           (bare ``<chunk_id>`` is also accepted today)
  entity:<entity_id>
  lexicon:<lexicon_id>
  relation:<source>:<rel>:<target>

For chunk-based cards the field equals the chunk_id (no ``chunk:``
prefix), preserving the existing wire format. Non-chunk provenance kinds
are namespaced so chunk_ids and entity_ids can never collide.

See docs/expansion-plan.md for the design context.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import references

DEFAULT_DB = Path(__file__).resolve().parent / "index.db"
EXCERPT_LEN = 240


@dataclass
class SourceLead:
    chunk_id: str
    document_title: str
    passage: str | None        # human-readable, e.g. "Titus 1:1"
    tags: list[str]
    source: str                # source_path of the document
    excerpt: str               # body trimmed to EXCERPT_LEN chars
    metadata: dict             # the document's full metadata dict
    provenance_id: str = ""    # validated against LLM citations; defaults to chunk_id

    def __post_init__(self) -> None:
        if not self.provenance_id:
            self.provenance_id = self.chunk_id

    def asdict(self) -> dict:
        return asdict(self)


def _trim(text: str, n: int = EXCERPT_LEN) -> str:
    text = " ".join(text.split())  # collapse whitespace
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _passage_for(db: sqlite3.Connection, doc_id: str) -> str | None:
    rows = db.execute(
        "SELECT MIN(start_bbcccvvv), MAX(end_bbcccvvv) FROM passage_refs WHERE doc_id = ?",
        (doc_id,),
    ).fetchone()
    if not rows or rows[0] is None:
        return None
    return references.human(rows[0], rows[1])


def _tags_for(db: sqlite3.Connection, doc_id: str) -> list[str]:
    return [r[0] for r in db.execute("SELECT tag FROM tags WHERE doc_id = ? ORDER BY tag", (doc_id,))]


def resolve(db: sqlite3.Connection, chunk_id: str) -> SourceLead | None:
    row = db.execute(
        """
        SELECT chunks.body,
               documents.id, documents.title, documents.source_path, documents.metadata
        FROM chunks
        JOIN documents ON documents.id = chunks.doc_id
        WHERE chunks.id = ?
        """,
        (chunk_id,),
    ).fetchone()
    if not row:
        return None
    body, doc_id, title, source_path, meta_json = row
    try:
        meta = json.loads(meta_json) if meta_json else {}
    except json.JSONDecodeError:
        meta = {}
    return SourceLead(
        chunk_id=chunk_id,
        document_title=title,
        passage=_passage_for(db, doc_id),
        tags=_tags_for(db, doc_id),
        source=source_path,
        excerpt=_trim(body),
        metadata=meta,
        provenance_id=chunk_id,
    )


def resolve_many(db: sqlite3.Connection, chunk_ids: list[str]) -> list[SourceLead]:
    cards: list[SourceLead] = []
    for cid in chunk_ids:
        card = resolve(db, cid)
        if card is not None:
            cards.append(card)
    return cards
