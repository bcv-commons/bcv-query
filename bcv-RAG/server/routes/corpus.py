"""Corpus endpoints — BHSA/Nestle1904 via the embedded Context-Fabric engine.

Exposes the subset of the former bcv-corpus API needed by shoresh's
search.build (clause listing) and general corpus queries.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/books")
def list_books(corpus: str = "hebrew"):
    from corpus import engine
    try:
        books = engine.list_books(corpus)
        return [b.model_dump() for b in books]
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/clauses")
def list_clauses(corpus: str = "hebrew", book: str | None = None,
                 clause_type: str | None = None):
    from corpus import engine
    return engine.list_clauses(corpus, book, clause_type)


@router.get("/passage")
def get_passage(book: str, chapter: int, verse_start: int = 1,
                verse_end: int | None = None, corpus: str = "hebrew"):
    from corpus import engine
    try:
        result = engine.get_passage(book, chapter, verse_start, verse_end, corpus)
        return result.model_dump()
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/context")
def get_context(book: str, chapter: int, verse: int,
                word_index: int = 0, corpus: str = "hebrew"):
    from corpus import engine
    return engine.get_context(book, chapter, verse, word_index, corpus)
