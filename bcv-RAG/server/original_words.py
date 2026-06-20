"""Bridge 1: enrich BCV citations with original-language words from shoresh.

For each cited verse reference, calls shoresh /verse/{book}/{ch}/{v} over
private networking and returns a compact interlinear (surface, gloss, strong).
Fails silently — the enrichment is optional and should never break answers.
"""
from __future__ import annotations

import logging
import os
import re

import httpx

logger = logging.getLogger("bcv-rag.original_words")

SHORESH_URL = os.environ.get("SHORESH_URL", "").rstrip("/")

_REF_RE = re.compile(
    r"^(?P<book>[A-Z0-9]{3})\s+(?P<ch>\d+):(?P<v>\d+)$"
)


def _parse_ref(passage: str) -> tuple[str, int, int] | None:
    m = _REF_RE.match(passage.strip())
    if not m:
        return None
    return m.group("book"), int(m.group("ch")), int(m.group("v"))


def _compact_words(words: list[dict]) -> list[dict]:
    return [
        {"surface": w["surface"], "strong": w.get("strong", ""),
         "gloss": w.get("gloss", ""), "translit": w.get("translit", "")}
        for w in words if w.get("strong")
    ]


def enrich_citations(citations: list[dict]) -> list[dict]:
    """Add an `original_words` key to each citation that has a BCV passage."""
    if not SHORESH_URL:
        return citations
    refs: list[tuple[int, tuple[str, int, int]]] = []
    for i, c in enumerate(citations):
        parsed = _parse_ref(c.get("passage") or "")
        if parsed:
            refs.append((i, parsed))
    if not refs:
        return citations
    try:
        with httpx.Client(base_url=SHORESH_URL, timeout=5.0) as client:
            for idx, (book, ch, v) in refs:
                try:
                    resp = client.get(f"/verse/{book}/{ch}/{v}")
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    spine = data.get("spine")
                    if spine and spine.get("words"):
                        citations[idx]["original_words"] = {
                            "lang": spine["language"],
                            "words": _compact_words(spine["words"]),
                        }
                except Exception:
                    continue
    except Exception as e:
        logger.debug("shoresh enrichment failed: %s", e)
    return citations
