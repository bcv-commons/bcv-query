"""Strategy 4: Clause→RAG chain — BEREL Hebrew search → passage filter.

Translates the English query to Hebrew via gloss lookup, runs BEREL clause
search on shoresh, and returns the top BCV refs as passage ranges for the
main retrieval pipeline.

Effect: Hebrew semantic similarity finds passages that English keyword
search misses. Isaiah 65:17 "בורא שמים חדשים" surfaces for "creating
something new" even though no English word matches. The main pipeline
then enriches those finds with study notes, commentary, cross-refs.

Opt-in: "expand": ["clause"]. Cost: $0. Latency: +200-500ms.
"""
from __future__ import annotations

import logging
import os
import re

import httpx

from indexer.references import BOOK_ALIASES, BOOK_NUMBERS, _normalize_alias, encode

logger = logging.getLogger("bcv-rag.expand_clause")

SHORESH_URL = os.environ.get("SHORESH_URL", "").rstrip("/")


def clause_passages(question: str, k: int = 10) -> list[tuple[int, int]]:
    """Run BEREL clause search via shoresh and return BCV passage ranges."""
    if not SHORESH_URL:
        return []

    try:
        resp = httpx.get(
            f"{SHORESH_URL}/search",
            params={"q": question, "lang": "hbo", "translate": "gloss", "k": k},
            timeout=10.0,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return []

        ref_re = re.compile(r"^(\S+)\s+(\d+):(\d+)$")
        passages: list[tuple[int, int]] = []
        seen: set[int] = set()
        for r in results:
            if r.get("score", 0) < 0.5:
                continue
            m = ref_re.match(r.get("ref", ""))
            if not m:
                continue
            raw_bk, ch, v = m.group(1), int(m.group(2)), int(m.group(3))
            bk = BOOK_ALIASES.get(_normalize_alias(raw_bk), raw_bk)
            if bk not in BOOK_NUMBERS:
                continue
            try:
                bbcccvvv = encode(bk, ch, v)
            except ValueError:
                continue
            if bbcccvvv not in seen:
                seen.add(bbcccvvv)
                passages.append((bbcccvvv, bbcccvvv))
        return passages

    except Exception as e:
        logger.debug("clause search expansion failed: %s", e)
        return []
