"""LLM-driven answer synthesis with strict citation constraint.

The prompt forces the model to cite only chunk_ids that appear in its
SOURCES list. Downstream validation drops any citation not in that set,
so a hallucinated source_id can't survive into the rendered answer.

Note on chunk body vs. excerpt: CitationCard.excerpt is the 240-char
display preview shown alongside citations in the UI. The LLM gets the
FULL chunk body (capped at MAX_BODY_CHARS) — otherwise it can't see
content past the excerpt boundary. Translator notes commonly bury the
operative word ("blameless", "loyalty oath", etc.) past 240 chars; TW
and TA articles often only show generic definitional openers in 240
chars while the substantive theological content lives below.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import TYPE_CHECKING

from .llm import chat_completion
from lang import canon

if TYPE_CHECKING:
    from indexer.citations import CitationCard

MAX_BODY_CHARS = 1500

# Per-kind body cap. Short content (verses, headings) gets a tight cap so
# more chunks fit in the prompt; long-form content (term articles, lexicon
# entries, video transcripts) gets the full default. Anything not in the
# table falls back to MAX_BODY_CHARS.
_KIND_BODY_CAPS: dict[str, int] = {
    "scripture":        500,
    "bible":            500,
    "section-heading":  200,
    "morphology":       600,
    "question":         800,
    "translator-note":  800,
    "study-note":      1200,
    "term":            1500,
    "methodology":     1500,
    "lexicon":         1200,
    "dictionary":      1500,
    "ane-context":     1200,
    "video-transcript":1500,
    "book-intro":      1200,
}


def _body_cap_for_kind(kind: str | None) -> int:
    if not kind:
        return MAX_BODY_CHARS
    return _KIND_BODY_CAPS.get(kind, MAX_BODY_CHARS)


def _kind_from_tags(tags: list[str]) -> str | None:
    for t in tags:
        if t.startswith("kind:"):
            return t[len("kind:"):]
    return None


SYSTEM_PROMPT = """You answer Bible-translation and Bible-study questions using ONLY the SOURCES provided.

SOURCES come in many shapes — render the answer naturally regardless of which appear:

Door43 translator pair + helps:
  - ULT/UST: scripture (Literal Text / Simplified Text) — translator-grade English
  - TN: translation notes — explanations, alternate translations, guidance
  - TQ: translation questions WITH their responses — these directly answer
        comprehension questions about the passage
  - TW: term definitions (people, places, key biblical concepts)
  - TA: translation methodology articles
  - TWL: passage→term link metadata

Reader-grade Bible & navigation:
  - BSB: Berean Standard Bible — full Bible, readable English, Strong's-tagged
  - Section headings: pericope titles ("The Creation", "The Sermon on the Mount")

Original-language scholarship:
  - Lexicon: Greek (LSJ, Abbott-Smith) and Hebrew (BDB) entries with definitions,
            etymology, and citations — keyed by Strong's number
  - Morphology: verse-level word-by-word parses — original word + lemma +
                Strong's + parse code + English gloss
  - Aquifer study notes / FIA materials: editorial commentary

Long-form study:
  - BibleProject video transcripts: theological/contextual narrative; transcripts
    may be chunked by timestamp, by Bible reference, or by semantic window —
    cite from the most relevant strategy

ALL of these count as valid answers when they speak to the user's question. TQ
rows ARE answers — surface them when the user asks comprehension questions.
Lexicon entries ARE answers when asked about Greek/Hebrew word meanings. Section
headings provide pericope context for "what's happening at <passage>" queries.

Hard rules:
1. Use ONLY the SOURCES — do not bring in outside knowledge or speculate.
2. Every claim MUST cite at least one provenance id inline using square brackets,
   e.g. [56001001:0001] for a chunk; future answers may also cite [entity:<id>],
   [topic:<id>], or [lexicon:<strongs>] when those forms appear in SOURCES.
3. When citing a Greek/Hebrew word, give both the original-script form and an
   English transliteration if the SOURCES include them.
4. If the SOURCES truly do not contain anything that speaks to the question,
   set "answer" to:
   "I don't see an answer to that in the indexed sources."
   and "citations" to the chunk_ids of the closest related sources.
5. Be concise. No preamble, no meta-commentary, no opinions.

Reply with a single JSON object only:
{
  "answer":     "<text with inline [chunk_id] citations>",
  "citations":  ["<chunk_id>", ...],
  "confidence": "low" | "medium" | "high"
}
"""

# --- B3: in-language synthesis -------------------------------------------------
# Sources are often mixed-language (English helps + the query-language Bible).
# We instruct the model to compose the answer in the query language regardless,
# keeping citation ids / original-script words / Strong's verbatim.
_LANG_NAMES = {
    "eng": "English", "spa": "Spanish", "fra": "French", "por": "Portuguese",
    "rus": "Russian", "arb": "Arabic", "hin": "Hindi", "ben": "Bengali",
    "asm": "Assamese", "hau": "Hausa",
}
# Localized form of the rule-4 refusal. English is the canonical phrase the eval's
# refusal regex matches; the others mirror it so non-en answers refuse in-language.
_REFUSAL = {
    "eng": "I don't see an answer to that in the indexed sources.",
    "spa": "No encuentro una respuesta a eso en las fuentes indexadas.",
    "fra": "Je ne trouve pas de réponse à cela dans les sources indexées.",
    "por": "Não encontro uma resposta para isso nas fontes indexadas.",
    "rus": "Я не нахожу ответа на это в проиндексированных источниках.",
    "arb": "لا أجد إجابة على ذلك في المصادر المفهرسة.",
    "hin": "मुझे अनुक्रमित स्रोतों में इसका उत्तर नहीं मिलता।",
    "ben": "সূচিকৃত উৎসগুলিতে আমি এর উত্তর খুঁজে পাই না।",
    "asm": "সূচীভুক্ত উৎসবোৰত মই ইয়াৰ উত্তৰ বিচাৰি নাপাওঁ।",
    "hau": "Ban sami amsar wannan a cikin tushen da aka ƙididdige ba.",
}


def _refusal(lang: str) -> str:
    return _REFUSAL.get(canon(lang), _REFUSAL["eng"])


def _language_directive(lang: str) -> str:
    """Extra system-prompt block telling the model to answer in `lang`. Empty for
    English (the base prompt is already English)."""
    lang = canon(lang)
    name = _LANG_NAMES.get(lang)
    if not name or lang == "eng":
        return ""
    return (
        f"\n\nLANGUAGE:\n"
        f"- Write the \"answer\" field entirely in {name}, in natural fluent {name}.\n"
        f"- The SOURCES may be in English or other languages; compose your answer in "
        f"{name} regardless of the source language.\n"
        f"- Keep VERBATIM (do not translate): citation ids in [brackets], original-script "
        f"Greek/Hebrew words, transliterations, and Strong's numbers (e.g. G4102, H2580).\n"
        f"- For rule 4, if the sources do not answer the question, set \"answer\" to "
        f"exactly: \"{_refusal(lang)}\""
    )


USER_TEMPLATE = """SOURCES:

{sources}

QUESTION: {question}

Reply only with the JSON object specified."""


def _format_sources(cards: list["CitationCard"], bodies: dict[str, str]) -> str:
    """Render SOURCES block with FULL chunk bodies (per-kind capped) — not
    the 240-char display excerpt. Per-kind caps tighten the prompt: a verse
    needs ~50 chars, a lexicon entry can use up to 1200, a section heading
    is just the title."""
    blocks = []
    for c in cards:
        passage = c.passage or "no passage"
        body = bodies.get(c.chunk_id) or c.excerpt
        kind = _kind_from_tags(c.tags)
        cap = _body_cap_for_kind(kind)
        if len(body) > cap:
            body = body[:cap].rstrip() + "…"
        blocks.append(f"[{c.provenance_id}] {c.document_title} — {passage}\n  {body}")
    return "\n\n".join(blocks)


def _fetch_bodies(db: sqlite3.Connection | None, chunk_ids: list[str]) -> dict[str, str]:
    """Look up full chunk bodies. Returns {} if no db (caller falls back to excerpts)."""
    if db is None or not chunk_ids:
        return {}
    placeholders = ",".join("?" * len(chunk_ids))
    rows = db.execute(
        f"SELECT id, body FROM chunks WHERE id IN ({placeholders})",
        chunk_ids,
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def _extract_inline_citations(answer: str) -> list[str]:
    return re.findall(r"\[([A-Za-z0-9:_\-]+)\]", answer)


def _intent_context_for(analysis) -> str | None:
    """Build the optional one-liner that explains *why* the chunks were
    retrieved. Used for stage-3 intents where the connection between query
    and chunks isn't obvious from the chunk bodies alone (Nave's groups
    Bible verses by *story*, not vocabulary; xrefs anchor to a source verse;
    word-study chunks are lexicon entries that may need framing)."""
    if analysis is None:
        return None
    intent = getattr(analysis, "intent", None)
    if intent == "topic" and getattr(analysis, "topic_query", None):
        topic = analysis.topic_query
        return f"Nave's Topical Bible groups the following Bible verses under '{topic}'"
    if intent == "xref" and getattr(analysis, "xref_source", None):
        bb = analysis.xref_source
        try:
            from indexer.references import human
            ref = human(bb, bb)
            return f"TSK + BSB-parallel cross-references for {ref}"
        except Exception:
            return f"Cross-references for BBCCCVVV {bb}"
    if intent == "genealogy" and getattr(analysis, "entity_query", None):
        eq = analysis.entity_query
        rel = (eq.get("relation") or "").replace("-rev", "")
        name = eq.get("name", "?")
        return f"Entity-graph traversal: {rel} of {name} (with surrounding context)"
    if intent == "word_study":
        return "Lexicon entries (LSJ / Abbott-Smith / BDB) for the queried word"
    return None


def synthesize(
    question: str,
    cards: list["CitationCard"],
    db: sqlite3.Connection | None = None,
    *,
    intent_context: str | None = None,
    analysis=None,
    lang: str = "en",
) -> dict:
    """Return {answer, citations, confidence, raw}.

    `db`, when supplied, lets the synthesizer pull full chunk bodies for the
    LLM prompt (instead of the truncated 240-char display excerpts).
    `citations` is the validated union of inline-cited and explicitly-listed
    chunk_ids that actually exist in `cards`. Hallucinated ids are dropped.

    `intent_context` is an optional one-line prefix prepended to the SOURCES
    block — used by stage-3 intents that need to tell the LLM why the chunks
    are relevant. If not given but `analysis` is, derived automatically.
    """
    if intent_context is None and analysis is not None:
        intent_context = _intent_context_for(analysis)
    if not cards:
        # Use the same phrase the LLM is instructed to emit in its refusal exit,
        # so the eval's refusal regex catches both paths uniformly. Localized to
        # the query language (English unchanged → eval still matches).
        return {
            "answer": _refusal(lang),
            "citations": [],
            "confidence": "low",
            "raw": None,
        }

    valid_ids = {c.provenance_id for c in cards}
    bodies = _fetch_bodies(db, [c.chunk_id for c in cards])
    sources_block = _format_sources(cards, bodies)
    if intent_context:
        sources_block = f"({intent_context})\n\n{sources_block}"
    user = USER_TEMPLATE.format(sources=sources_block, question=question)

    system = SYSTEM_PROMPT + _language_directive(lang)
    raw = chat_completion(system=system, user=user, response_format="json")

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {
            "answer": (raw or "(empty)").strip(),
            "citations": [],
            "confidence": "low",
            "raw": raw,
        }

    answer = parsed.get("answer", "") or ""
    listed = parsed.get("citations") or []
    inline = _extract_inline_citations(answer)
    cited = []
    seen = set()
    for cid in [*inline, *listed]:
        if cid in valid_ids and cid not in seen:
            cited.append(cid)
            seen.add(cid)

    # Strip inline [chunk_id] markers that aren't in valid_ids.
    def _replace(match: re.Match[str]) -> str:
        return match.group(0) if match.group(1) in valid_ids else ""

    answer = re.sub(r"\[([A-Za-z0-9:_\-]+)\]", _replace, answer)
    answer = re.sub(r"\s{2,}", " ", answer).strip()

    return {
        "answer": answer,
        "citations": cited,
        "confidence": parsed.get("confidence", "medium"),
        "raw": raw,
    }
