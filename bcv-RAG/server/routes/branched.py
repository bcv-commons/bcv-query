"""Branched (tree) retrieval surface.

GET  /api/search/branched — results GROUPED by kind into featured/collapsed
                            branches with drill-down; no LLM, deterministic.
POST /api/ask/branched    — same tree + ONE narrative answer synthesized over
                            the featured branches, plus suggested drill-down.
"""
from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from indexer.db import has_vec
from query.analyzer import analyze
from query.concept_expand import filter_biblical_words
from query.lang_detect import resolve_lang
from lang import canon
from server.auth import require_password
from server.branched import build_branches
from server.deps import get_db
from server.ratelimit import LIMIT_ASK, LIMIT_SEARCH, limiter

router = APIRouter()


def _prep(q: str, lang: str, book: str | None) -> "object":
    """Analyze a query the same way /search does (concept/LXX/morph expansion
    happens downstream inside retrieve_branched, so we don't pre-expand here)."""
    analysis = analyze(q, lang=lang)
    if canon(lang) != "eng":
        analysis.fts_query = filter_biblical_words(q, lang=lang)
    if book:
        analysis.tags.append(f"book:{book.upper()}")
    return analysis


def _cards(db: sqlite3.Connection, analysis, query: str, lang: str):
    """Assemble the card family for the branched surface — the featured HEADLINES that lead the
    tree (UX projection, prominent-first by kind) + the gated synthesis block. concept_expand is
    $0 (local gloss reverse-lookup), so it's safe on the deterministic /search/branched surface.
    Returns (ux_cards, reference_block)."""
    from query.concept_expand import expand_concepts
    from server.cards import assemble, render_synthesis, render_ux
    analysis.concept_tags = expand_concepts(analysis.fts_query, analysis.tags, lang=lang)
    built = assemble(analysis, db, query, lang)
    return render_ux(built, analysis), render_synthesis(built, analysis)


def _embed(db: sqlite3.Connection, q: str) -> list[float] | None:
    if not has_vec(db):
        return None
    try:
        from indexer.embed import embed_texts
        return embed_texts([q], input_type="query")[0]
    except Exception as e:
        print(f"  branched: embed failed ({type(e).__name__}: {e}); proceeding without vec", flush=True)
        return None


@router.get("/search/branched")
@limiter.limit(LIMIT_SEARCH)
def search_branched(
    request: Request,
    q: str,
    lang: str | None = None,   # absent/"auto" → detect from query text
    book: str | None = None,
    source: Literal["all", "door43", "aquifer"] = "all",
    per_branch: int = 8,
    force: str | None = None,   # comma-separated branch keys to force-expand
    semantic: bool = False,
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="query (?q=) is required")
    if per_branch < 1 or per_branch > 50:
        raise HTTPException(status_code=400, detail="per_branch must be 1..50")

    lang = resolve_lang(q, lang)
    analysis = _prep(q, lang, book)
    query_vec = _embed(db, q) if semantic else None
    result = build_branches(
        db, analysis, query_vec=query_vec, source_filter=source, lang=lang,
        per_branch=per_branch, force=[f for f in (force or "").split(",") if f],
    )
    ux_cards = _cards(db, analysis, q, lang)[0]
    from server.cards import branched_layout
    return {
        "query": q,
        "lang": lang,
        "semantic": bool(query_vec is not None),
        "analysis": {
            "fts_query": analysis.fts_query,
            "intent": analysis.intent,
            "tags": analysis.tags,
        },
        "cards": ux_cards,   # featured headlines, prominent-first by kind (each with confidence/featured)
        "branches": result["branches"],
        "suggested_layout": branched_layout(result["branches"], ux_cards),  # advisory (Phase 3 contract)
        "suggested_drilldown": result["suggested_drilldown"],
    }


class AskBranchedRequest(BaseModel):
    question: str = Field(..., min_length=1)
    lang: str | None = None   # absent/"auto" → detect from question text
    book: str | None = None
    source: Literal["all", "door43", "aquifer"] = "all"
    per_branch: int = 8
    force: list[str] = Field(default_factory=list)


@router.post("/ask/branched", dependencies=[Depends(require_password)])
@limiter.limit(LIMIT_ASK)
def ask_branched(
    request: Request, req: AskBranchedRequest, db: sqlite3.Connection = Depends(get_db)
) -> dict:
    if req.per_branch < 1 or req.per_branch > 50:
        raise HTTPException(status_code=400, detail="per_branch must be 1..50")

    lang = resolve_lang(req.question, req.lang)
    analysis = _prep(req.question, lang, req.book)
    query_vec = _embed(db, req.question)
    result = build_branches(
        db, analysis, query_vec=query_vec, source_filter=req.source,
        lang=lang, per_branch=req.per_branch, force=req.force,
    )

    ux_cards, reference_block = _cards(db, analysis, req.question, lang)

    # One narrative over the FEATURED branches; the tree carries the rest. The gated card family
    # grounds the prose (parity with /ask); the UX cards lead the tree.
    from query.synthesize import synthesize  # lazy: pulls openai SDK
    synth = synthesize(req.question, result["featured_cards"], db=db,
                       analysis=analysis, lang=lang, reference_block=reference_block)

    from server.cards import branched_layout
    return {
        "question": req.question,
        "answer": synth["answer"],
        "confidence": synth["confidence"],
        "citations": synth["citations"],
        "cards": ux_cards,   # featured headlines, prominent-first by kind (each with confidence/featured)
        "branches": result["branches"],
        "suggested_layout": branched_layout(result["branches"], ux_cards),  # advisory (Phase 3 contract)
        "suggested_drilldown": result["suggested_drilldown"],
        "lang": lang,
        "analysis": {
            "fts_query": analysis.fts_query,
            "intent": analysis.intent,
            "tags": analysis.tags,
        },
    }
