"""Word-study discovery nudge (S2 layer).

The semantic-domain/sense/bridge data is weak as a ranking signal but strong as a
DISCOVERY surface. For a query's primary concept Strong's, fetch a word-study card
from shoresh `/wordstudy` and attach it to the answer — gloss + TW concept article(s)
(nudge: study the concept) + senses + cross-language equivalent + related co-domain
words (nudge: follow the chain ahav → agapaō → eleos …). A question becomes a guided
word-study journey. Additive and best-effort — never breaks answers.

See internal-docs/macula-semantic-layer-plan.md §11.
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger("bcv-rag.word_study")

SHORESH_URL = os.environ.get("SHORESH_URL", "").rstrip("/")
_TIMEOUT = 2.0


# Ubiquitous frame-words (God / Lord / say): studiable, but rarely the user's FOCUS
# when a more specific concept co-occurs (keyness over-ranks them). Sorted LAST, not
# excluded — so "who is God" still yields a card, while "God is faithful" picks faithful.
_UBIQUITOUS = {
    "H0430", "H0410", "H0433", "H3068", "H0136", "H0113",  # God / LORD / Lord
    "G2316", "G2962",                                      # theos / kurios
    "H0559", "G3004",                                      # amar / legō (say)
}


def _concept_strongs(tags: list[str]) -> list[str]:
    """Query Strong's as concept candidates: specific concepts first (by keyness),
    ubiquitous frame-words last."""
    from query.concept_expand import _normalize_code, strong_keyness
    scored: list[tuple[str, float]] = []
    seen: set[str] = set()
    for t in tags:
        if not t.startswith("strongs:"):
            continue
        code = _normalize_code(t.split(":", 1)[1])
        if code in seen:
            continue
        seen.add(code)
        scored.append((code, strong_keyness(code)))
    scored.sort(key=lambda x: (x[0] in _UBIQUITOUS, -x[1]))
    return [c for c, k in scored if k > 0]


def word_study_card(tags: list[str]) -> dict | None:
    """A word-study card for the query's primary concept Strong's, or None.

    Tries the top concept candidates (by keyness) and returns the first that resolves
    to a real lexical entry (has a semantic domain or senses)."""
    if not SHORESH_URL:
        return None
    cands = _concept_strongs(tags)
    if not cands:
        return None
    try:
        with httpx.Client(base_url=SHORESH_URL, timeout=_TIMEOUT) as client:
            for strong in cands[:3]:
                try:
                    resp = client.get(f"/wordstudy/{strong}")
                except Exception:
                    continue
                if resp.status_code == 200:
                    card = resp.json()
                    if card.get("domains") or card.get("senses"):
                        return card
    except Exception as exc:  # shoresh down / unreachable
        logger.debug("word_study unavailable: %s", exc)
    return None
