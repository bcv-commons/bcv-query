"""GET /api/search — keyword + structured + semantic retrieval."""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request

from indexer import citations as citations_mod
from indexer.db import has_vec
from query.analyzer import analyze
from query.concept_expand import filter_biblical_words
from lang import canon
from query.retrieve import Hit, retrieve
from server.deps import get_db
from server.ratelimit import LIMIT_SEARCH, limiter
from server.resolver import chunk_preview_from_card
from server.corpus_cards import resolve_corpus_hits

router = APIRouter()


@router.get("/search")
@limiter.limit(LIMIT_SEARCH)
def search(
    request: Request,
    q: str,
    lang: str = "en",
    kind: str | None = None,
    book: str | None = None,
    source: Literal["all", "door43", "aquifer"] = "all",
    top_k: int = 10,
    semantic: bool = False,
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="query (?q=) is required")
    if top_k < 1 or top_k > 50:
        raise HTTPException(status_code=400, detail="top_k must be 1..50")

    _timing = os.environ.get("RETRIEVER_TIMING") == "1"
    _stage: dict[str, float] = {}
    _s = time.perf_counter()

    analysis = analyze(q, lang=lang)
    if canon(lang) != "eng":
        analysis.fts_query = filter_biblical_words(q, lang=lang)
    if kind:
        analysis.tags.append(f"kind:{kind}")
    if book:
        analysis.tags.append(f"book:{book.upper()}")
    if _timing:
        _stage["analyze"] = time.perf_counter() - _s; _s = time.perf_counter()

    query_vec = None
    if semantic and has_vec(db):
        try:
            from indexer.embed import embed_texts
            query_vec = embed_texts([q], input_type="query")[0]
        except Exception as e:
            print(f"  search: embed failed ({type(e).__name__}: {e}); proceeding without vec", flush=True)
    if _timing:
        _stage["embed"] = time.perf_counter() - _s; _s = time.perf_counter()

    hits = retrieve(db, analysis, top_k=top_k, query_vec=query_vec, source_filter=source, lang=lang)
    if _timing:
        _stage["retrieve"] = time.perf_counter() - _s; _s = time.perf_counter()

    local_hits = [h for h in hits if not h.chunk_id.startswith("corpus:")]
    corpus_hits = [h for h in hits if h.chunk_id.startswith("corpus:")]

    cards = citations_mod.resolve_many(db, [h.chunk_id for h in local_hits])
    by_id = {c.chunk_id: c for c in cards}

    corpus_previews = resolve_corpus_hits(corpus_hits) if corpus_hits else {}

    enriched: list[dict] = []
    for h in hits:
        if h.chunk_id.startswith("corpus:"):
            preview = corpus_previews.get(h.chunk_id)
        else:
            card = by_id.get(h.chunk_id)
            preview = chunk_preview_from_card(card, lang=lang) if card else None
        if preview is None:
            continue
        preview["score"] = round(float(h.score), 6)
        preview["retrievers"] = h.retrievers
        enriched.append(preview)

    if _timing:
        _stage["enrich"] = time.perf_counter() - _s
        print("[stage-timing] " + ", ".join(f"{k}={v * 1000:.0f}ms" for k, v in _stage.items()),
              file=sys.stderr, flush=True)

    return {
        "query": q,
        "lang": lang,
        "filters": {"kind": kind, "book": book.upper() if book else None, "source": source},
        "semantic": bool(query_vec is not None),
        "analysis": {
            "fts_query": analysis.fts_query,
            "passages": [list(p) for p in analysis.passages],
            "tags": analysis.tags,
            "intent": analysis.intent,
        },
        "hits": enriched,
        "total": len(enriched),
    }
