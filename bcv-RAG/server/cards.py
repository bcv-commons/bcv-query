"""Synthesis reference cards — the card family.

Per-kind strategies (see internal-docs/card-family.md): each kind is a self-contained
`CardStrategy` — its OWN confidence, build, and two projections (the gated `to_synthesis` and
the never-exclusive `to_ux`). The shared layer (`assemble` + `render_synthesis`/`render_ux`) only
routes, builds, ranks, and projects. Adding a kind = adding a strategy to STRATEGIES — never
touching the others; "completely varying strategies" is the expected shape.

Two projections, opposite economics:
  • to_synthesis → paid prose: GATED (a wrong/redundant card misdirects the model). May return
    None even when the card is built (e.g. concept on a bare word-lookup — the prose self-defines).
  • to_ux → $0 structured: never-exclusive (always shown if built), ranked by confidence, by kind.
"""
from __future__ import annotations

from dataclasses import dataclass


def _concept_line(card: dict | None) -> str | None:
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


@dataclass
class BuiltCard:
    kind: str
    confidence: float
    data: dict
    strategy: "CardStrategy"


class CardStrategy:
    """One card kind. Subclasses own confidence / build / the two projections."""
    kind = "?"

    def confidence(self, analysis, db) -> float:
        """Does this kind fire, and how prominently (0 = doesn't fire). Deterministic, $0."""
        return 0.0

    def build(self, analysis, db, query: str, lang: str) -> dict | None:
        """Assemble the card data (or None)."""
        return None

    def to_synthesis(self, data: dict, analysis) -> str | None:
        """GATED prose projection — may be None even when built."""
        return None

    def to_ux(self, data: dict, analysis) -> dict | None:
        """Never-exclusive UX projection — a by-kind headline + drill-in endpoint."""
        return None


# ── Concept / Sense ────────────────────────────────────────────────────────────────────────
# Suppressed on intents that want a DIFFERENT card (A/B-validated: the losses clustered here).
_CONCEPT_SUPPRESS_INTENTS = {"genealogy", "entity_lookup", "speaker", "methodology"}


class ConceptStrategy(CardStrategy):
    """Concept / Sense — gloss · binyan-correct sense · cross-lang equiv · keyness · domain.

    Confidence: fires on concept-bearing intents (not entity/speaker/genealogy/methodology).
    Synthesis gate: require co-domain siblings AND suppress BARE word-lookups — the prose
    self-defines the looked-up word, so the card is redundant there (A/B: anchor lookups added only
    losses). UX: always show when built — including the very bare lookup synthesis suppresses."""
    kind = "concept"
    _PROMINENCE = {"word_study": 1.0, "thematic": 0.7, "topic": 0.6}

    def confidence(self, analysis, db) -> float:
        intent = getattr(analysis, "intent", "") or ""
        if intent in _CONCEPT_SUPPRESS_INTENTS:
            return 0.0
        return self._PROMINENCE.get(intent, 0.5)

    def build(self, analysis, db, query, lang) -> dict | None:
        from server.word_study import word_study_anchor, word_study_card
        tags = getattr(analysis, "concept_tags", None) or getattr(analysis, "tags", [])
        return word_study_card(tags, query, anchor_strongs=word_study_anchor(db, analysis))

    def to_synthesis(self, data, analysis) -> str | None:
        if not (data or {}).get("siblings"):              # weak fallback match = noise
            return None
        bare = bool(getattr(analysis, "word_study_terms", None)
                    or getattr(analysis, "word_study_strongs", None))
        if bare:                                          # bare lookup → prose self-defines it
            return None
        return _concept_line(data)

    def to_ux(self, data, analysis) -> dict | None:
        line = _concept_line(data)
        if not line:
            return None
        strong = (data or {}).get("strong")
        return {"kind": self.kind, "headline": line, "anchor": strong,
                "drill": f"/wordstudy/{strong}" if strong else None}


# The family registry — steps 3-4 append SpeakerStrategy / EntityStrategy / PassageStrategy / ...
STRATEGIES: list[CardStrategy] = [ConceptStrategy()]


def assemble(analysis, db, query: str = "", lang: str = "en") -> list[BuiltCard]:
    """Route + build every kind that fires, highest-confidence first. The shared layer — strategies
    do the kind-specific work; this only routes, builds, and ranks."""
    built: list[BuiltCard] = []
    for strat in STRATEGIES:
        conf = strat.confidence(analysis, db)
        if conf <= 0:
            continue
        data = strat.build(analysis, db, query, lang)
        if data:
            built.append(BuiltCard(kind=strat.kind, confidence=conf, data=data, strategy=strat))
    built.sort(key=lambda b: -b.confidence)
    return built


def render_synthesis(built: list[BuiltCard], analysis) -> str | None:
    """The GATED synthesis projection — each kind's to_synthesis (may be None even when built)."""
    lines = [b.strategy.to_synthesis(b.data, analysis) for b in built]
    lines = [ln for ln in lines if ln]
    if not lines:
        return None
    return ("REFERENCE (original-language facts — ground the answer in these; do NOT cite them "
            "by chunk id):\n" + "\n".join(f"• {ln}" for ln in lines))


def render_ux(built: list[BuiltCard], analysis) -> list[dict]:
    """The never-exclusive UX projection — every built card as a by-kind headline, ranked by
    confidence (the prominent one leads). Part B folds these into branched retrieval."""
    return [ux for ux in (b.strategy.to_ux(b.data, analysis) for b in built) if ux]


def concept_data(built: list[BuiltCard]) -> dict | None:
    """The concept card's raw /wordstudy data (for the JSON `word_study` field)."""
    for b in built:
        if b.kind == "concept":
            return b.data
    return None
