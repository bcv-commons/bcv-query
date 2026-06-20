"""Strategy 6: Topic → Strong's → Clause search pipeline.

After Nave's topic retriever returns canonical verses, extracts Strong's
numbers from those verses via shoresh /verse, builds Hebrew lemma queries,
and runs BEREL clause search to find semantically related passages beyond
the Nave's list.

Effect: "What does the Bible teach about holiness?" → Nave's gives the
canonical verses → Strong's extraction finds H6918 (קָדוֹשׁ), H6942 (קָדַשׁ)
→ BEREL search finds the long tail of semantically related clauses Nave's
doesn't list.

Opt-in: "expand": ["topic"]. Cost: $0. Latency: +300-600ms.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3

import httpx

from indexer.references import BOOK_ALIASES, BOOK_NUMBERS, NUMBER_TO_CODE, _normalize_alias, encode
from query.retrieve import Hit, passage_search

logger = logging.getLogger("bcv-rag.expand_topic")

SHORESH_URL = os.environ.get("SHORESH_URL", "").rstrip("/")


def _topic_passages(db: sqlite3.Connection, topic_query: str,
                    limit: int = 10) -> list[tuple[str, int, int]]:
    """Get BCV refs from Nave's topic index."""
    rows = db.execute(
        "SELECT id FROM topics WHERE LOWER(name) = LOWER(?) LIMIT 3",
        (topic_query,),
    ).fetchall()
    if not rows:
        rows = db.execute(
            "SELECT id FROM topics WHERE LOWER(name) LIKE LOWER(?) LIMIT 3",
            (topic_query + "%",),
        ).fetchall()
    if not rows:
        return []
    topic_ids = [r[0] for r in rows]
    placeholders = ",".join("?" * len(topic_ids))
    refs = db.execute(
        f"SELECT start_bbcccvvv FROM topic_passages "
        f"WHERE topic_id IN ({placeholders}) "
        f"ORDER BY start_bbcccvvv LIMIT ?",
        [*topic_ids, limit],
    ).fetchall()
    result = []
    for r in refs:
        bbcccvvv = r[0]
        book_num = bbcccvvv // 1_000_000
        ch = (bbcccvvv % 1_000_000) // 1_000
        v = bbcccvvv % 1_000
        code = NUMBER_TO_CODE.get(book_num)
        if code:
            result.append((code, ch, v))
    return result


def _extract_strongs_from_verses(
    refs: list[tuple[str, int, int]], max_words: int = 20
) -> list[str]:
    """Call shoresh /verse for each ref, extract top Hebrew Strong's lemmas."""
    if not SHORESH_URL or not refs:
        return []
    lemmas: dict[str, int] = {}
    try:
        with httpx.Client(base_url=SHORESH_URL, timeout=5.0) as client:
            for book, ch, v in refs[:8]:
                try:
                    resp = client.get(f"/verse/{book}/{ch}/{v}")
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    spine = data.get("spine")
                    if not spine or not spine.get("words"):
                        continue
                    if spine.get("language") != "hbo":
                        continue
                    for w in spine["words"]:
                        lemma = w.get("lemma", "")
                        strong = w.get("strong", "")
                        if lemma and strong and strong.startswith("H"):
                            lemmas[lemma] = lemmas.get(lemma, 0) + 1
                except Exception:
                    continue
    except Exception as e:
        logger.debug("shoresh verse lookup failed: %s", e)
        return []

    sorted_lemmas = sorted(lemmas.items(), key=lambda x: -x[1])
    return [lemma for lemma, _ in sorted_lemmas[:max_words]]


def _clause_search_with_lemmas(
    lemmas: list[str], k: int = 10
) -> list[tuple[int, int]]:
    """Run BEREL clause search with Hebrew lemmas as the query."""
    if not SHORESH_URL or not lemmas:
        return []
    query = " ".join(lemmas[:5])
    try:
        resp = httpx.get(
            f"{SHORESH_URL}/search",
            params={"q": query, "lang": "hbo", "k": k},
            timeout=10.0,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        results = data.get("results", [])
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
        logger.debug("BEREL clause search failed: %s", e)
        return []


def topic_clause_expand(
    db: sqlite3.Connection,
    topic_query: str | None,
    first_pass_hits: list[Hit],
    top_k: int = 10,
) -> list[Hit]:
    """Expand topic results via Strong's extraction + BEREL clause search."""
    if not topic_query or not SHORESH_URL:
        return first_pass_hits

    topic_refs = _topic_passages(db, topic_query)
    if not topic_refs:
        return first_pass_hits

    lemmas = _extract_strongs_from_verses(topic_refs)
    if not lemmas:
        return first_pass_hits

    clause_refs = _clause_search_with_lemmas(lemmas)
    if not clause_refs:
        return first_pass_hits

    clause_hits = passage_search(db, clause_refs)
    if not clause_hits:
        return first_pass_hits

    for h in clause_hits:
        h.retrievers = ["topic_clause"]

    from query.retrieve import rrf
    fused = rrf(
        [first_pass_hits, clause_hits],
        weights=[1.0, 0.5],
    )
    return fused[:top_k]
