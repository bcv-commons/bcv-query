"""Bridge 1: enrich BCV citations with original-language words from shoresh.

For each cited verse reference, calls shoresh /verse/{book}/{ch}/{v} over
private networking and returns a compact interlinear (surface, lemma, gloss, strong).
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
# Citations carry the DISPLAY name ("Genesis 1:1"), not USFM ("GEN 1:1") — reverse the
# book-name map so enrichment fires on either form (this also repairs original_words).
_NAME_RE = re.compile(r"^(?P<book>.+?)\s+(?P<ch>\d+):(?P<v>\d+)$")
try:
    from indexer.references import BOOK_NAMES
    _NAME_TO_CODE = {name.lower(): code for code, name in BOOK_NAMES.items()}
except Exception:
    _NAME_TO_CODE = {}


def _parse_ref(passage: str) -> tuple[str, int, int] | None:
    p = (passage or "").strip()
    m = _REF_RE.match(p)
    if m:
        return m.group("book"), int(m.group("ch")), int(m.group("v"))
    m = _NAME_RE.match(p)
    if m:
        code = _NAME_TO_CODE.get(m.group("book").lower())
        if code:
            return code, int(m.group("ch")), int(m.group("v"))
    return None


def _compact_words(words: list[dict]) -> list[dict]:
    # Keep `lemma` (BHSA lex, present for Hebrew; "" for Greek): it distinguishes the
    # homographs a shared Strong's number conflates, and is the key into per-stem glosses.
    return [
        {"surface": w["surface"], "strong": w.get("strong", ""),
         "lemma": w.get("lemma", ""),
         "gloss": w.get("gloss", ""), "translit": w.get("translit", "")}
        for w in words if w.get("strong")
    ]


def verse_interlinear(book: str, ch: int, v: int) -> dict | None:
    """{lang, words, lxx} for a single verse via shoresh /verse, or None. `lxx` = the compact LXX
    Greek parallel (present for OT verses, [] otherwise). Reusable by the PassageStrategy card."""
    if not SHORESH_URL:
        return None
    try:
        with httpx.Client(base_url=SHORESH_URL, timeout=3.0) as client:
            resp = client.get(f"/verse/{book}/{ch}/{v}")
            if resp.status_code != 200:
                return None
            data = resp.json() or {}
    except Exception as e:
        logger.debug("verse_interlinear failed: %s", e)
        return None
    words = _compact_words((data.get("spine") or {}).get("words") or [])
    if not words:
        return None
    return {"lang": (data.get("spine") or {}).get("language", ""), "words": words,
            "lxx": _compact_words((data.get("lxx") or {}).get("words") or [])}


def verse_speaker(book: str, ch: int, v: int) -> dict | None:
    """{name, divine} of who speaks this verse (red-letter), or None — via shoresh /speakers/at."""
    if not SHORESH_URL:
        return None
    try:
        with httpx.Client(base_url=SHORESH_URL, timeout=3.0) as client:
            resp = client.get(f"/speakers/at/{book}/{ch}/{v}")
            if resp.status_code != 200:
                return None
            speakers = (resp.json() or {}).get("speakers") or []
    except Exception:
        return None
    if not speakers:
        return None
    return {"name": speakers[0].get("speaker", ""), "divine": bool(speakers[0].get("divine"))}


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


def enrich_participants(citations: list[dict], max_verses: int = 8) -> list[dict]:
    """Add a `participants` key to each cited verse — the coreference chain (pronoun →
    the entity it refers to), from shoresh /participants (MACULA, CC-BY). Resolves
    "who is 'he/his/it' here" right in the study packet. Capped + best-effort; never
    breaks answers."""
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
            for idx, (book, ch, v) in refs[:max_verses]:
                try:
                    resp = client.get(f"/participants/{book}/{ch}/{v}")
                    if resp.status_code != 200:
                        continue
                    parts = resp.json().get("participants", [])
                    compact = [
                        {"word": p["text"], "lemma": p.get("lemma", ""),
                         "refers_to": (p["refers_to"].get("gloss") or p["refers_to"].get("lemma") or ""),
                         "at": p["refers_to"].get("ref", "")}
                        for p in parts if p.get("refers_to")
                    ]
                    if compact:
                        citations[idx]["participants"] = compact[:12]
                except Exception:
                    continue
    except Exception as e:
        logger.debug("shoresh participants enrichment failed: %s", e)
    return citations
