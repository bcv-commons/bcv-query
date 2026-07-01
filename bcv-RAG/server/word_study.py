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
import re

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
    "G1446", "G1447", "G1673", "G1676",                   # Hebrew/Greek language NAMES — framing
}                                                          # in "the Hebrew word X", never the subject


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


def _get_card(client: "httpx.Client", strong: str, gloss_lang: str = "English") -> dict | None:
    """Fetch + validate one /wordstudy card (a real lexical entry: has domains or senses).
    `gloss_lang` localizes the gloss + lex_senses labels (shoresh resolves per-stem multilingual glosses)."""
    try:
        resp = client.get(f"/wordstudy/{strong}", params={"gloss_lang": gloss_lang})
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    card = resp.json()
    return card if (card.get("domains") or card.get("senses")) else None


def word_study_card(tags: list[str], query: str = "",
                    anchor_strongs: list[str] | None = None,
                    gloss_lang: str = "English") -> dict | None:
    """A word-study card for the query's primary concept Strong's, or None.

    `anchor_strongs` — the Strong's the user EXPLICITLY named ("the Hebrew word AB",
    "Strong's G3962"); briefed directly, *ahead* of the keyness/gloss heuristic, which over-ranks
    framing words ("the Hebrew word AB" → AB=father, not G1446 *Hebrew*). See word_study_anchor.

    Otherwise tries the top concept candidates (keyness order) and prefers the one whose gloss is
    actually a word in the question — cuts through concept_expand noise (e.g. "love your neighbor"
    emits both H0157 *love* and a spurious H4960 *feast*; keyness ranks feast first, but only
    *love* is in the query). Falls back to the first candidate that resolves to a lexical entry."""
    if not SHORESH_URL:
        return None
    cands = _concept_strongs(tags)
    if not (cands or anchor_strongs):
        return None
    qtokens = set(re.findall(r"[a-z]{3,}", query.lower()))
    fallback: dict | None = None
    thin_match: dict | None = None  # gloss matches but card has no related words
    try:
        with httpx.Client(base_url=SHORESH_URL, timeout=_TIMEOUT) as client:
            # explicit anchor wins: the user named the word — brief it before any heuristic.
            for strong in (anchor_strongs or []):
                card = _get_card(client, strong, gloss_lang)
                if card:
                    return card
            for strong in cands[:4]:
                card = _get_card(client, strong, gloss_lang)
                if card is None:
                    continue
                if fallback is None:
                    fallback = card
                gloss = (card.get("gloss") or "").lower()
                if gloss and (gloss in qtokens or any(t in qtokens for t in gloss.split())):
                    if card.get("siblings"):
                        return card  # gloss matches AND has the related-words chain
                    if thin_match is None:
                        thin_match = card  # a love word, but rare (no siblings) — keep looking
    except Exception as exc:  # shoresh down / unreachable
        logger.debug("word_study unavailable: %s", exc)
        return None
    return thin_match or fallback


def _lemma_to_strongs(db, term: str) -> list[str]:
    """A transliteration the user typed ("AB"/"AGAPE") → Strong's code(s), via the lexicon's
    paired `lemma:`/`strongs:` tags. Selective on `lemma:<slug>`, so the tags join is cheap."""
    slug = re.sub(r"[^a-z0-9]+", "", term.lower())
    if not slug or db is None:
        return []
    try:
        rows = db.execute(
            "SELECT DISTINCT s.tag FROM tags l "
            "JOIN tags s ON s.doc_id = l.doc_id AND s.tag LIKE 'strongs:%' "
            "JOIN tags k ON k.doc_id = l.doc_id AND k.tag = 'kind:lexicon' "
            "WHERE l.tag = ?",
            (f"lemma:{slug}",),
        ).fetchall()
    except Exception:
        return []
    from query.concept_expand import _normalize_code
    return [_normalize_code(r[0].split(":", 1)[1]) for r in rows]


def word_study_anchor(db, analysis) -> list[str]:
    """The Strong's the user EXPLICITLY named — an explicit "Strong's G####" or a transliteration
    ("the Hebrew word AB"). Anchors the concept card directly, ahead of the keyness/gloss heuristic
    (which over-ranks framing language-name words). Empty when the query names no specific word."""
    from query.concept_expand import _normalize_code
    out: list[str] = []
    for t in getattr(analysis, "word_study_strongs", None) or []:
        out.append(_normalize_code(t.split(":", 1)[1] if ":" in t else t))
    for term in getattr(analysis, "word_study_terms", None) or []:
        out.extend(_lemma_to_strongs(db, term))
    return list(dict.fromkeys(out))
