"""Detect the query language from text, constrained to supported languages.

Used by the routes when the client omits `lang` (or passes "auto"). An explicit
`lang` is always authoritative — this is only a fallback for the common case of a
client that forgets to send it (which silently defaulted to English and dropped,
e.g., Spanish study notes via the language gate).

Dependency-free, reuses data we already ship:
  1. Script detection (Cyrillic→rus, Arabic→arb, Devanagari→hin, …) — certain.
  2. Stopword overlap against analyzer_lang/<lang>.json for Latin scripts.
  3. Confidence gate → fall back to DEFAULT when the signal is weak (short /
     proper-noun queries like "Boaz" match no stopwords; better en than a guess).

Only the languages with an analyzer_lang config are candidates — detecting a
language we have no content/analyzer for would be useless.

Known limit: very short queries in closely-related languages that share function
words (e.g. "Que tipos de amor a Bíblia menciona" — valid Portuguese AND Spanish)
are inherently ambiguous from text alone. Adding gloss-surface scoring would help
the family but break the proper-noun fallback (names live in the gloss index), so
we keep it stopword-only. The client sending an explicit `lang` remains the
reliable path; this is a best-effort fallback.
"""
from __future__ import annotations

import re
from functools import lru_cache

from resource_paths import resource_path
from query.concept_expand import _lang_stopwords  # cached per-lang stopword loader

DEFAULT_LANG = "eng"
# Min share of query words that must be stopwords of the winner to trust it.
# Tuned via eval/lang_detect.py: spa 0.44 / eng 0.70 / fra 0.62 / por 0.33 pass;
# "Boaz" 0.0 falls back. 0.15 leaves headroom for terse multi-content queries.
_MIN_STOPWORD_SHARE = 0.15

# Unambiguous script → ISO 639-3 (first match wins). Covers our non-Latin langs.
_SCRIPTS: list[tuple[str, re.Pattern]] = [
    ("rus", re.compile(r"[Ѐ-ӿ]")),   # Cyrillic
    ("arb", re.compile(r"[؀-ۿ]")),   # Arabic
    ("hin", re.compile(r"[ऀ-ॿ]")),   # Devanagari
    ("ben", re.compile(r"[ঀ-৿]")),   # Bengali
    ("heb", re.compile(r"[֐-׿]")),   # Hebrew
]


@lru_cache(maxsize=1)
def _supported() -> tuple[str, ...]:
    return tuple(sorted(p.stem for p in resource_path("analyzer_lang").glob("*.json")))


def detect_lang(query: str, *, default: str = DEFAULT_LANG) -> str:
    """Best-guess ISO 639-3 for a query; `default` when the signal is weak."""
    if not query or not query.strip():
        return default
    for code, rx in _SCRIPTS:
        if rx.search(query):
            return code
    words = re.findall(r"[^\W\d_]{2,}", query.lower())
    if not words:
        return default
    best, best_hits = default, 0
    for code in _supported():
        stops = _lang_stopwords(code)
        if not stops:
            continue
        hits = sum(w in stops for w in words)
        if hits > best_hits:
            best, best_hits = code, hits
    if best_hits / len(words) < _MIN_STOPWORD_SHARE:
        return default
    return best


def resolve_lang(text: str, lang: str | None) -> str:
    """Route helper: trust an explicit `lang`; detect when absent or "auto"."""
    if lang and lang.strip().lower() != "auto":
        return lang
    return detect_lang(text)
