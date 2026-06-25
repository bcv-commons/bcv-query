"""English → Hebrew query translation for BEREL clause search.

Two strategies, matching the access-mode ladder from the roadmap:

- **gloss** (Mode A, $0): deterministic lookup via the reverse gloss index.
  Splits the English query into words, maps each to Hebrew lemmas via
  spine_glosses.tsv, picks the highest-frequency lemma per word. Fast,
  free, approximate — works well for concrete nouns/verbs, weaker for
  abstract concepts and phrases.

- **llm** (Mode B/C, near-$0): sends the English query to a cheap LLM
  (Groq llama-3.3-70b by default) with a one-shot prompt asking for a
  Biblical Hebrew paraphrase. Better for phrases, idioms, and abstract
  concepts. Requires GROQ_API_KEY (or OPENAI_API_KEY as fallback).
"""
from __future__ import annotations

import os
from functools import lru_cache


_STOP_WORDS = {"the", "a", "an", "and", "or", "of", "in", "on", "to", "for",
               "with", "by", "from", "at", "is", "was", "are", "were", "be",
               "been", "has", "have", "had", "do", "does", "did", "will",
               "would", "shall", "should", "may", "might", "can", "could",
               "not", "no", "but", "if", "then", "than", "that", "this",
               "these", "those", "it", "its", "my", "your", "his", "her",
               "our", "their", "who", "whom", "which", "what", "where",
               "when", "how", "why", "all", "each", "every", "both",
               "few", "more", "most", "other", "some", "such", "only"}


def _word_forms(w: str) -> list[str]:
    """Generate candidate forms: original + stemmed variants."""
    forms = [w]
    for suffix in ("d", "s", "es", "ed", "ing", "er", "est", "ly", "ness"):
        if w.endswith(suffix) and len(w) > len(suffix) + 2:
            forms.append(w[:-len(suffix)])
    return forms


def gloss_translate(query: str) -> str:
    """Translate English query to Hebrew lemmas via the reverse gloss index.

    Prefers Hebrew (H) Strong's numbers over Greek, and picks the
    highest-frequency match whose gloss exactly equals the query word
    (not just contains it).
    """
    import data
    words = query.lower().split()
    hebrew_parts: list[str] = []
    for w in words:
        w = w.strip(".,;:!?\"'()[]")
        if not w or w in _STOP_WORDS:
            continue
        candidates: list[dict] = []
        for form in _word_forms(w):
            result = data.gloss_lookup(form)
            if result["matches"]:
                candidates.extend(result["matches"])
        if not candidates:
            continue
        seen = set()
        matches = []
        for m in candidates:
            if m["strong"] not in seen:
                seen.add(m["strong"])
                matches.append(m)
        exact = [m for m in matches if m["gloss"].lower() == w]
        if exact:
            matches = exact
        heb_matches = [m for m in matches if m["lang"] == "hbo"]
        if heb_matches:
            matches = heb_matches
        matches.sort(key=lambda m: -m["count"])
        best = matches[0]
        code = best["strong"]
        num = int(code[1:])
        if code.startswith("H"):
            scon = data._ro(data.SPINE_DB)
            if scon:
                row = scon.execute(
                    "SELECT lemma FROM spine_words WHERE strong=? LIMIT 1",
                    (num,)).fetchone()
                scon.close()
                if row and row["lemma"]:
                    hebrew_parts.append(row["lemma"])
                    continue
        else:
            lcon = data._ro(data.LXX_DB)
            if lcon:
                row = lcon.execute(
                    "SELECT plain FROM lxx_words WHERE strong=? LIMIT 1",
                    (num,)).fetchone()
                lcon.close()
                if row and row["plain"]:
                    hebrew_parts.append(row["plain"])
                    continue
    return " ".join(hebrew_parts) if hebrew_parts else query


_TRANSLATE_PROMPT = """Translate this English phrase into Biblical Hebrew (consonantal script, no vowels).
Return ONLY the Hebrew text, nothing else. Keep it short — a clause, not a paragraph.

English: {query}
Hebrew:"""


def llm_translate(query: str) -> str:
    """Translate English query to Hebrew via a cheap LLM call."""
    groq_key = os.environ.get("GROQ_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")

    if groq_key:
        return _groq_translate(query, groq_key)
    elif openai_key:
        return _openai_translate(query, openai_key)
    return gloss_translate(query)


def _groq_translate(query: str, api_key: str) -> str:
    import httpx
    resp = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user",
                          "content": _TRANSLATE_PROMPT.format(query=query)}],
            "max_tokens": 100, "temperature": 0.0,
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _openai_translate(query: str, api_key: str) -> str:
    import httpx
    resp = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user",
                          "content": _TRANSLATE_PROMPT.format(query=query)}],
            "max_tokens": 100, "temperature": 0.0,
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()
