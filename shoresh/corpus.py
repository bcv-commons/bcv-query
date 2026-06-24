"""Client for the corpus engine (BHSA + Nestle1904) over private networking.

The corpus engine — the former bcv-corpus service, now bcv-RAG's /api/passage +
/api/context routes — exposes the original-language text as a linguistic graph
(morphology, clauses, phrases, sentences). shoresh reaches it at CORPUS_URL
(e.g. `http://bcv-corpus.railway.internal:8000`) — $0, private, no public hop.
Two views are proxied:

  passage(book, ch, v)            -> /api/passage : verse words + morphology
  context(book, ch, v, word_idx)  -> /api/context : clause/phrase/sentence
                                                     hierarchy for one word

Book mapping replicates bcv-RAG's proven scheme: bcv-corpus returns its own
book names per corpus ("hebrew" = BHSA, "greek" = Nestle1904) in canonical
order, zipped positionally against the USFM codes in the same order.
"""
from __future__ import annotations

import os
from functools import lru_cache

import httpx

from references import BOOK_NUMBERS

CORPUS_URL = os.environ.get("CORPUS_URL", "").rstrip("/")
_TIMEOUT = 10.0


@lru_cache(maxsize=1)
def _book_map() -> dict[str, tuple[str, str]]:
    """USFM code -> (corpus_book_name, corpus_id). Empty if CORPUS_URL unset."""
    if not CORPUS_URL:
        return {}
    mapping: dict[str, tuple[str, str]] = {}
    with httpx.Client(base_url=CORPUS_URL, timeout=_TIMEOUT) as client:
        for corpus_id, (lo, hi) in [("hebrew", (1, 40)), ("greek", (40, 100))]:
            resp = client.get("/api/books", params={"corpus": corpus_id})
            resp.raise_for_status()
            names = [b["name"] for b in resp.json()]
            codes = sorted(
                [(u, n) for u, n in BOOK_NUMBERS.items() if lo <= n < hi],
                key=lambda x: x[1],
            )
            for (usfm, _num), name in zip(codes, names):
                mapping[usfm] = (name, corpus_id)
    return mapping


def configured() -> bool:
    return bool(CORPUS_URL)


def _resolve(book: str) -> tuple[str, str] | None:
    return _book_map().get(book.upper())


def passage(book: str, chapter: int, verse: int) -> dict:
    """bcv-corpus /api/passage for one verse (morphological annotations)."""
    if not CORPUS_URL:
        return {"error": "CORPUS_URL not configured"}
    resolved = _resolve(book)
    if not resolved:
        return {"error": f"no corpus mapping for book '{book}'"}
    name, corpus_id = resolved
    with httpx.Client(base_url=CORPUS_URL, timeout=_TIMEOUT) as client:
        resp = client.get("/api/passage", params={
            "book": name, "chapter": chapter,
            "verse_start": verse, "verse_end": verse, "corpus": corpus_id,
        })
        resp.raise_for_status()
        return {"corpus": corpus_id, "corpus_book": name, "data": resp.json()}


def context(book: str, chapter: int, verse: int, word_index: int = 0) -> dict:
    """bcv-corpus /api/context: clause/phrase/sentence hierarchy for one word."""
    if not CORPUS_URL:
        return {"error": "CORPUS_URL not configured"}
    resolved = _resolve(book)
    if not resolved:
        return {"error": f"no corpus mapping for book '{book}'"}
    name, corpus_id = resolved
    with httpx.Client(base_url=CORPUS_URL, timeout=_TIMEOUT) as client:
        resp = client.get("/api/context", params={
            "book": name, "chapter": chapter, "verse": verse,
            "word_index": word_index, "corpus": corpus_id,
        })
        resp.raise_for_status()
        return {"corpus": corpus_id, "corpus_book": name, "data": resp.json()}
