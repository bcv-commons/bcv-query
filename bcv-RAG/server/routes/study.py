"""POST /api/study — deterministic Bible study packet ($0, no LLM).

Like /api/ask but replaces the LLM synthesis with structured assembly:
  analyze → search → concept expand → LXX bridge → morph filter
  → clause search → cross-ref snowball → original-word enrichment

Returns a rich JSON study packet that a frontend can render directly.
"""
from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from indexer import citations as citations_mod
from indexer.db import has_vec
from query.analyzer import analyze
from lang import canon
from query.concept_expand import expand_concepts, filter_biblical_words
from query.retrieve import retrieve
from server.corpus_cards import resolve_corpus_hits
from server.deps import get_db
from server.original_words import enrich_citations
from server.word_study import word_study_card
from server.ratelimit import LIMIT_SEARCH, limiter
from server.resolver import chunk_preview_from_card

router = APIRouter()


class StudyScope(BaseModel):
    source: Literal["all", "door43", "aquifer"] = "all"
    book: str | None = None


class StudyRequest(BaseModel):
    question: str = Field(..., min_length=1)
    lang: str = "en"
    scope: StudyScope | None = None
    top_k: int = 10
    expand: list[str] = Field(default_factory=lambda: ["all"])


@router.post("/study")
@limiter.limit(LIMIT_SEARCH)
def study(request: Request, req: StudyRequest, db: sqlite3.Connection = Depends(get_db)) -> dict:
    if req.top_k < 1 or req.top_k > 50:
        raise HTTPException(status_code=400, detail="top_k must be 1..50")
    return run_study(
        db,
        req.question,
        lang=req.lang,
        source_filter=(req.scope.source if req.scope else "all"),
        book=(req.scope.book if req.scope else None),
        top_k=req.top_k,
        expand=req.expand,
    )


def run_study(
    db: sqlite3.Connection,
    question: str,
    *,
    lang: str = "en",
    source_filter: str = "all",
    book: str | None = None,
    top_k: int = 10,
    expand: list[str] | None = None,
) -> dict:
    """Core deterministic study pipeline (no LLM, no HTTP) — shared by the
    /study route and the MCP `study` tool. Returns the cited study packet."""
    if expand is None:
        expand = ["all"]

    analysis = analyze(question, lang=lang)
    if book:
        analysis.tags.append(f"book:{book.upper()}")

    # For non-English: positive-filter query words through the gloss index.
    # Drops function words ("dice", "sobre", "que", "dit", etc.) automatically.
    # English analyzer already has good stop word handling.
    if canon(lang) != "eng":
        analysis.fts_query = filter_biblical_words(question, lang=lang)

    # Strategy 1: concept expansion (filtered words → Strong's tags)
    concept_tags = expand_concepts(analysis.fts_query, analysis.tags, lang=lang)
    analysis.tags.extend(concept_tags)

    # Strategy 2: LXX bridge (Hebrew Strong's → Greek Strong's)
    lxx_tags: list[str] = []
    try:
        from query.lxx_expand import expand_lxx
        lxx_tags = expand_lxx(analysis.tags)
        analysis.tags.extend(lxx_tags)
    except Exception:
        pass

    # Strategy 3: morph pre-filter
    morph_refs: list[tuple[int, int]] = []
    try:
        from query.morph_prefilter import detect_morph_pattern, morph_passages, _extract_book_code
        pattern = detect_morph_pattern(analysis.fts_query)
        if pattern:
            book_code = _extract_book_code(analysis.passages)
            morph_refs = morph_passages(pattern, book=book_code)
            if morph_refs:
                analysis.passages.extend(morph_refs)
    except Exception:
        pass

    # Semantic vector search via Cloudflare BGE-M3 ($0)
    query_vec = None
    if has_vec(db):
        try:
            from indexer.embed import embed_texts
            query_vec = embed_texts([question], input_type="query")[0]
        except Exception:
            pass

    expand_set = {e.lower() for e in expand}
    if "all" in expand_set:
        expand_set = {"clause", "crossref", "topic"}

    # Strategy 4: clause search expansion (BEREL Hebrew semantic)
    clause_refs: list[tuple[int, int]] = []
    if "clause" in expand_set:
        try:
            from query.expand_clause import clause_passages
            clause_refs = clause_passages(question)
            if clause_refs:
                analysis.passages.extend(clause_refs)
        except Exception:
            pass

    # Use thematic weights for balanced retrieval — the strategies layer
    # additional signal on top instead of letting intent skew weights.
    original_intent = analysis.intent
    analysis.intent = "thematic"
    hits = retrieve(db, analysis, top_k=top_k, query_vec=query_vec, source_filter=source_filter, lang=lang)
    analysis.intent = original_intent

    # Strategy 5: cross-ref snowball
    if "crossref" in expand_set:
        try:
            from query.expand_crossref import crossref_snowball
            hits = crossref_snowball(db, hits, intent=analysis.intent, top_k=top_k)
        except Exception:
            pass

    # Strategy 6: topic→clause expansion
    if "topic" in expand_set and analysis.topic_query:
        try:
            from query.expand_topic import topic_clause_expand
            hits = topic_clause_expand(db, analysis.topic_query, hits, top_k=top_k)
        except Exception:
            pass

    # Resolve hits into displayable cards
    local_hits = [h for h in hits if not h.chunk_id.startswith("corpus:")]
    corpus_hits = [h for h in hits if h.chunk_id.startswith("corpus:")]

    cards = citations_mod.resolve_many(db, [h.chunk_id for h in local_hits])
    by_id = {c.chunk_id: c for c in cards}
    corpus_previews = resolve_corpus_hits(corpus_hits) if corpus_hits else {}

    citations_out: list[dict] = []
    for n, h in enumerate(hits, start=1):
        if h.chunk_id.startswith("corpus:"):
            preview = corpus_previews.get(h.chunk_id)
        else:
            card = by_id.get(h.chunk_id)
            preview = chunk_preview_from_card(card, lang=lang) if card else None
        if preview is None:
            continue
        preview["n"] = n
        preview["score"] = round(float(h.score), 6)
        preview["retrievers"] = h.retrievers
        citations_out.append(preview)

    # Enrich with original-language words from shoresh
    citations_out = enrich_citations(citations_out)
    study_card = word_study_card(analysis.tags)  # S2 discovery nudge (best-effort)

    # Build the strategies-applied summary
    strategies: list[str] = []
    if concept_tags:
        strategies.append("concept_expand")
    if lxx_tags:
        strategies.append("lxx_bridge")
    if morph_refs:
        strategies.append("morph_prefilter")
    if query_vec is not None:
        strategies.append("semantic_search")
    if clause_refs:
        strategies.append("clause_search")
    if "crossref" in expand_set:
        strategies.append("crossref_snowball")
    if "topic" in expand_set and analysis.topic_query:
        strategies.append("topic_clause")

    return {
        "question": question,
        "citations": citations_out,
        "total": len(citations_out),
        "lang": lang,
        "strategies": strategies,
        "word_study": study_card,
        "analysis": {
            "fts_query": analysis.fts_query,
            "passages": [list(p) for p in analysis.passages],
            "tags": analysis.tags,
            "intent": original_intent,
            "concept_tags": concept_tags,
            "lxx_tags": lxx_tags,
            "expand": sorted(expand_set) if expand_set else [],
        },
    }
