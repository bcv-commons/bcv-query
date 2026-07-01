"""POST /api/ask — full RAG: free-form question → cited answer."""
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
from server.auth import require_password
from server.corpus_cards import resolve_corpus_hits
from server.deps import get_db
from server.original_words import enrich_citations
from server.ratelimit import LIMIT_ASK, limiter
from server.resolver import chunk_preview_from_card

router = APIRouter()


class AskScope(BaseModel):
    source: Literal["all", "door43", "aquifer"] = "all"
    book: str | None = None


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    lang: str = "en"
    scope: AskScope | None = None
    top_k: int = 10
    expand: list[str] = Field(default_factory=list)


@router.post("/ask", dependencies=[Depends(require_password)])
@limiter.limit(LIMIT_ASK)
def ask(request: Request, req: AskRequest, db: sqlite3.Connection = Depends(get_db)) -> dict:
    if req.top_k < 1 or req.top_k > 50:
        raise HTTPException(status_code=400, detail="top_k must be 1..50")

    analysis = analyze(req.question, lang=req.lang)
    if req.scope and req.scope.book:
        analysis.tags.append(f"book:{req.scope.book.upper()}")

    # For non-English: positive-filter query words through the gloss index
    # (drops function words in any language). English uses the analyzer's stops.
    if canon(req.lang) != "eng":
        analysis.fts_query = filter_biblical_words(req.question, lang=req.lang)

    # Concept expansion (query words → Strong's tags)
    concept_tags = expand_concepts(analysis.fts_query, analysis.tags, lang=req.lang)
    analysis.tags.extend(concept_tags)
    analysis.concept_tags = concept_tags  # clean pre-LXX concept set — the concept strategy's anchor

    # LXX bridge (Hebrew Strong's → Greek Strong's)
    try:
        from query.lxx_expand import expand_lxx
        analysis.tags.extend(expand_lxx(analysis.tags))
    except Exception:
        pass

    # Morphology pre-filter
    try:
        from query.morph_prefilter import detect_morph_pattern, morph_passages, _extract_book_code
        pattern = detect_morph_pattern(analysis.fts_query)
        if pattern:
            refs = morph_passages(pattern, book=_extract_book_code(analysis.passages))
            if refs:
                analysis.passages.extend(refs)
    except Exception:
        pass

    query_vec = None
    if has_vec(db):
        try:
            from indexer.embed import embed_texts
            query_vec = embed_texts([req.question], input_type="query")[0]
        except Exception as e:
            print(f"  ask: embed failed ({type(e).__name__}: {e}); proceeding without vec", flush=True)

    source_filter = req.scope.source if req.scope else "all"

    expand = {e.lower() for e in req.expand}
    if "all" in expand:
        expand = {"clause", "crossref", "topic"}

    # Strategy 4: pre-retrieval clause search expansion
    if "clause" in expand:
        from query.expand_clause import clause_passages
        clause_refs = clause_passages(req.question)
        if clause_refs:
            analysis.passages.extend(clause_refs)

    hits = retrieve(db, analysis, top_k=req.top_k, query_vec=query_vec, source_filter=source_filter, lang=req.lang)

    # Strategy 5: post-retrieval cross-ref snowball
    if "crossref" in expand:
        from query.expand_crossref import crossref_snowball
        hits = crossref_snowball(db, hits, intent=analysis.intent, top_k=req.top_k)

    # Strategy 6: post-retrieval topic→clause expansion
    if "topic" in expand and analysis.topic_query:
        from query.expand_topic import topic_clause_expand
        hits = topic_clause_expand(db, analysis.topic_query, hits, top_k=req.top_k)

    local_hits = [h for h in hits if not h.chunk_id.startswith("corpus:")]
    corpus_hits = [h for h in hits if h.chunk_id.startswith("corpus:")]

    cards = citations_mod.resolve_many(db, [h.chunk_id for h in local_hits])
    corpus_previews = resolve_corpus_hits(corpus_hits) if corpus_hits else {}

    corpus_cards = []
    for cid, preview in corpus_previews.items():
        card = citations_mod.CitationCard(
            chunk_id=cid,
            document_title=preview["title"],
            passage=preview["passage"],
            tags=preview["tags"],
            source="bcv-corpus",
            excerpt=preview["excerpt"],
            metadata={},
        )
        corpus_cards.append(card)

    all_cards = cards + corpus_cards

    from server.cards import (assemble, concept_data, render_synthesis, render_ux,
                              source_leads, suggested_layout, to_branches)
    built = assemble(analysis, db, req.question, req.lang)  # the card family, routed by intent
    reference_block = render_synthesis(built, analysis)    # gated projection → synthesis prompt
    study = concept_data(built)                            # concept card → JSON word_study field
    ux_cards = render_ux(built, analysis)                  # never-exclusive projection → UX, by kind

    from query.synthesize import synthesize  # lazy: pulls openai SDK
    synth = synthesize(req.question, all_cards, db=db, analysis=analysis, lang=req.lang,
                       reference_block=reference_block)

    by_id = {c.chunk_id: c for c in all_cards}
    citations_out: list[dict] = []
    for n, cid in enumerate(synth["citations"], start=1):
        if cid.startswith("corpus:"):
            preview = corpus_previews.get(cid)
        else:
            card = by_id.get(cid)
            preview = chunk_preview_from_card(card, lang=req.lang) if card else None
        if preview is None:
            continue
        preview["n"] = n
        citations_out.append(preview)

    citations_out = enrich_citations(citations_out)  # `study` already fetched above (reused)

    # Phase 3 — the leads-by-branch contract + advisory layout hint (client owns the actual layout).
    branches = to_branches(ux_cards, source_leads(citations_out))

    return {
        "question": req.question,
        "answer": synth["answer"],
        "citations": citations_out,
        "confidence": synth["confidence"],
        "lang": req.lang,
        "word_study": study,
        "cards": ux_cards,  # never-exclusive UX projection (prominent first, by kind) — grows with the family
        "branches": branches,               # leads grouped by branch (cards + source verses), confidence-scored
        "suggested_layout": suggested_layout(branches),   # advisory: hero | deck | tree | explore
        "analysis": {
            "fts_query": analysis.fts_query,
            "passages": [list(p) for p in analysis.passages],
            "tags": analysis.tags,
            "intent": analysis.intent,
            "expand": sorted(expand) if expand else [],
        },
    }
