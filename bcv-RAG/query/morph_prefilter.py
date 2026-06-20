"""Strategy 3: Morphological pre-filter via shoresh /morph endpoint.

Detects morphological keywords in the query (imperative, participle, etc.),
calls shoresh `/morph` with the pattern + any book filter from the analyzer,
and returns BCV passage ranges to use as a pre-filter for the main retrieval.

Effect: "Find all imperatives in Deuteronomy" → shoresh returns the exact
verses containing imperative verbs → main retrieval searches only within
those verses for study notes, commentary, cross-refs.

Runs at $0, ~50-150ms. Only fires when morph keywords are detected.
"""
from __future__ import annotations

import logging
import os
import re

import httpx

from indexer.references import BOOK_ALIASES, BOOK_NUMBERS, NUMBER_TO_CODE, _normalize_alias, encode

logger = logging.getLogger("bcv-rag.morph_prefilter")

SHORESH_URL = os.environ.get("SHORESH_URL", "").rstrip("/")

MORPH_KEYWORDS = {
    "imperative": "imperative",
    "imperatives": "imperative",
    "command": "imperative",
    "commands": "imperative",
    "participle": "participle",
    "participles": "participle",
    "perfect": "perfect",
    "imperfect": "imperfect",
    "infinitive": "infinitive",
    "infinitives": "infinitive",
    "noun": "noun",
    "nouns": "noun",
    "adjective": "adjective",
    "adjectives": "adjective",
    "verb": "verb",
    "verbs": "verb",
}


def _extract_book_code(passages: list[tuple[int, int]]) -> str | None:
    """Extract a 3-letter book code from a passage range if it's a whole-book or chapter filter."""
    if not passages:
        return None
    start = passages[0][0]
    book_num = start // 1_000_000
    code = NUMBER_TO_CODE.get(book_num)
    return code


def detect_morph_pattern(fts_query: str) -> str | None:
    """Check if the FTS query contains a morphological keyword."""
    words = fts_query.lower().split()
    for w in words:
        w = w.strip()
        if w in MORPH_KEYWORDS:
            return MORPH_KEYWORDS[w]
    return None


def morph_passages(pattern: str, book: str | None = None,
                   chapter: int | None = None,
                   limit: int = 200) -> list[tuple[int, int]]:
    """Call shoresh /morph and return BCV passage ranges for matching verses."""
    if not SHORESH_URL:
        return []

    params: dict = {"pattern": pattern, "limit": limit}
    if book:
        params["book"] = book
    if chapter is not None:
        params["chapter"] = chapter

    try:
        resp = httpx.get(f"{SHORESH_URL}/morph", params=params, timeout=3.0)
        if resp.status_code != 200:
            return []
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return []

        seen: set[tuple[int, int]] = set()
        passages: list[tuple[int, int]] = []
        ref_re = re.compile(r"^(\S+)\s+(\d+):(\d+)$")
        for r in results:
            m = ref_re.match(r.get("ref", ""))
            if not m:
                continue
            bk, ch, v = m.group(1), int(m.group(2)), int(m.group(3))
            bk = BOOK_ALIASES.get(_normalize_alias(bk), bk)
            if bk not in BOOK_NUMBERS:
                continue
            try:
                bbcccvvv = encode(bk, ch, v)
            except ValueError:
                continue
            pair = (bbcccvvv, bbcccvvv)
            if pair not in seen:
                seen.add(pair)
                passages.append(pair)
        return passages

    except Exception as e:
        logger.debug("morph pre-filter failed: %s", e)
        return []
