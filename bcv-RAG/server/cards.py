"""Synthesis reference cards — compact resource blocks fed to the answer-writer so it reasons
from original-language FACTS, not memory. Routed by intent; grows into the full family
(concept · entity · speaker · passage · xref). See internal-docs/card-family.md.

Step 1+2: the layer + the Concept/Sense card. `cards_for()` is the router seam — today it
renders the concept card from an already-fetched /wordstudy card; the other members slot in
here (each a small assembler over data we already serve).
"""
from __future__ import annotations


def _concept_card(card: dict | None) -> str | None:
    """Render shoresh's /wordstudy data into a compact CONCEPT line."""
    if not card:
        return None
    parts: list[str] = []
    head = " ".join(x for x in (card.get("strong"), card.get("translit")) if x)
    gloss = card.get("gloss")
    parts.append(f"{head} = {gloss}" if gloss else head)

    # the binyan-correct sense — the Hebrew-context sense layer (dominant sense per stem)
    senses: list[str] = []
    for entry in (card.get("lex_senses") or [])[:1]:        # primary lexeme
        for stem, ss in (entry.get("stems") or {}).items():
            if ss:
                senses.append(f"{stem or 'noun'}: {ss[0]['gloss']}")
    if senses:
        parts.append("sense — " + "; ".join(senses[:4]))

    cross = card.get("cross_language") or []
    if cross:
        parts.append("equiv: " + ", ".join(
            " ".join(x for x in (c.get("strong"), c.get("gloss")) if x) for c in cross[:2]))

    keyness = card.get("keyness") or {}
    if keyness.get("score"):
        parts.append(f"keyness {keyness['score']} (distinctively biblical)")

    domains = card.get("domains") or []
    if domains and domains[0].get("label"):
        parts.append("domain: " + domains[0]["label"])

    return "CONCEPT — " + " | ".join(p for p in parts if p)


# The concept card misdirects SYNTHESIS on intents that want a different card (A/B-validated:
# the losses clustered here). The deterministic UX still shows it — just demoted, by kind.
_CONCEPT_SUPPRESS_INTENTS = {"genealogy", "entity_lookup", "speaker", "methodology"}


def cards_for(analysis, study_card: dict | None, lang: str = "en") -> str | None:
    """Assemble the GATED synthesis reference block (the paid-prose projection — top-confidence
    card(s) only, since a wrong card misdirects the model). The deterministic-UX projection
    (all cards, featured + by-kind drill-down) is built separately. Today: the concept card,
    routed by intent + confidence. The family grows here — entity / speaker / passage / xref."""
    intent = getattr(analysis, "intent", "") or ""
    blocks: list[str] = []
    if intent not in _CONCEPT_SUPPRESS_INTENTS:
        # Fire only when the card adds a lexical lens the prose LACKS: a confident FOCAL concept
        # (carries co-domain siblings) embedded in a broader question. Two A/B-validated guards:
        #  - require `siblings` — a weak fallback match is noise, not signal;
        #  - suppress BARE word-lookups ("what does AGAPE mean", "Strong's G3962" → explicit anchor):
        #    the prose already defines the word, so the card is redundant (anchor lookups added only
        #    losses, never wins). The deterministic UX still shows them — see internal-docs/card-family.md.
        bare_lookup = bool(getattr(analysis, "word_study_terms", None)
                           or getattr(analysis, "word_study_strongs", None))
        if (study_card or {}).get("siblings") and not bare_lookup:
            cc = _concept_card(study_card)
            if cc:
                blocks.append(cc)
    if not blocks:
        return None
    return ("REFERENCE (original-language facts — ground the answer in these; do NOT cite them "
            "by chunk id):\n" + "\n".join(f"• {b}" for b in blocks))
