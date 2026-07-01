"""Shared assembly for branched (tree) retrieval responses.

Used by the REST /api/search/branched + /api/ask/branched routes and the MCP
`search_branched` tool, so all three return the same branch shape. Wraps
query.retrieve.retrieve_branched and resolves each branch's hits to the same
preview cards the flat /search already returns.
"""
from __future__ import annotations

import sqlite3

from indexer import citations as citations_mod
from query.analyzer import QueryAnalysis
from query.retrieve import retrieve_branched
from server.corpus_cards import resolve_corpus_hits
from server.resolver import chunk_preview_from_card


def build_branches(
    db: sqlite3.Connection,
    analysis: QueryAnalysis,
    *,
    query_vec: list[float] | None = None,
    source_filter: str = "all",
    lang: str = "en",
    per_branch: int = 8,
    force: list[str] | None = None,
) -> dict:
    """Run branched retrieval and resolve every branch's hits to preview cards.

    Returns {branches, suggested_drilldown, featured_cards}:
      • branches            — [{key, label, featured, total, items:[preview]}]
      • suggested_drilldown — collapsed-but-non-empty branches [{key,label,total}]
      • featured_cards      — the SourceLeads backing FEATURED branches, for a
                              synthesis step to narrate over (REST /ask/branched).
    """
    branches = retrieve_branched(
        db, analysis, query_vec=query_vec, source_filter=source_filter,
        lang=lang, per_branch=per_branch, force=force,
    )

    # Resolve all local hits across branches in one batch; corpus hits separately.
    all_hits = [h for b in branches for h in b.hits]
    local_ids = [h.chunk_id for h in all_hits if not h.chunk_id.startswith("corpus:")]
    corpus_hits = [h for h in all_hits if h.chunk_id.startswith("corpus:")]
    cards = citations_mod.resolve_many(db, local_ids)
    by_id = {c.chunk_id: c for c in cards}
    corpus_previews = resolve_corpus_hits(corpus_hits) if corpus_hits else {}

    def _preview(h):
        if h.chunk_id.startswith("corpus:"):
            return corpus_previews.get(h.chunk_id)
        card = by_id.get(h.chunk_id)
        if card is None:
            return None
        p = chunk_preview_from_card(card, lang=lang)
        if p is not None:
            p["score"] = round(float(h.score), 6)
            p["retrievers"] = h.retrievers
        return p

    def _lead(p: dict, kind: str, featured: bool) -> dict:
        """A preview → a lead in the unified contract shape (keeps the rich preview fields too)."""
        p = dict(p)
        p["kind"] = kind
        p["headline"] = p.get("passage") or p.get("title") or p.get("document_title") or p.get("name") or ""
        p["confidence"] = round(min(1.0, float(p.get("score", 0) or 0)), 2)
        p["featured"] = featured
        p["drill"] = p.get("chunk_id")
        return p

    out_branches: list[dict] = []
    featured_cards: list = []
    suggested: list[dict] = []
    for b in branches:
        items = [p for p in (_preview(h) for h in b.hits) if p is not None]
        out_branches.append({          # unified contract shape (shared with /ask's to_branches)
            "kind": b.key, "label": b.label, "featured": b.featured,
            "n": b.total, "leads": [_lead(p, b.key, b.featured) for p in items],
        })
        if b.featured:
            featured_cards.extend(by_id[h.chunk_id] for h in b.hits if h.chunk_id in by_id)
        elif b.total:
            suggested.append({"kind": b.key, "label": b.label, "n": b.total})

    return {
        "branches": out_branches,
        "suggested_drilldown": suggested,
        "featured_cards": featured_cards,
    }
