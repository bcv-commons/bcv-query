"""Language-tag normalization — the single source of truth for language codes.

Canonical internal form = **ISO 639-3 primary subtag within BCP 47 grammar**
(e.g. `eng`, `spa`, `arb`, `cmn-Hant`). This matches the Bible-data ecosystem
(eBible / Clear-Bible / Paratext / Door43 are all ISO 639-3) so external datasets
ingest with no impedance, while staying inside BCP 47 so script/region/variant
(`pt-BR`, `cmn-Hant`) and translation private-use subtags (`eng-x-bsb`) compose.

For the web / Hugging Face `language:` metadata field, emit the shortest tag with
`to_web()` (e.g. `eng -> en`, `cmn-Hant -> zh-Hant`).

`canon()` accepts the legacy 2-letter codes the project used before this migration
so old callers, URLs, and the existing index.db `lang:` tags keep working.
"""
from __future__ import annotations

# legacy 2-letter (ISO 639-1 / old project code) -> canonical (ISO 639-3 in BCP 47)
_LEGACY_TO_CANON = {
    "en": "eng", "es": "spa", "fr": "fra", "pt": "por", "ru": "rus",
    "ar": "arb", "hi": "hin", "bn": "ben", "as": "asm", "ha": "hau",
    "zh": "cmn-Hans", "zh-hant": "cmn-Hant", "zh-hans": "cmn-Hans",
}
# canonical -> shortest BCP 47 tag for the web / Hugging Face
_CANON_TO_WEB = {
    "eng": "en", "spa": "es", "fra": "fr", "por": "pt", "rus": "ru",
    "arb": "ar", "hin": "hi", "ben": "bn", "asm": "as", "hau": "ha",
    "cmn-Hans": "zh-Hans", "cmn-Hant": "zh-Hant",
}
_DISPLAY = {
    "eng": "English", "spa": "Spanish", "fra": "French", "por": "Portuguese",
    "rus": "Russian", "arb": "Arabic", "hin": "Hindi", "ben": "Bengali",
    "asm": "Assamese", "hau": "Hausa",
    "cmn-Hans": "Chinese (Simplified)", "cmn-Hant": "Chinese (Traditional)",
    # original-language corpus codes (already ISO 639-3)
    "hbo": "Hebrew", "grc": "Greek",
}
# every canonical tag the project currently ships (target/translation languages)
KNOWN = tuple(_CANON_TO_WEB.keys())


def _norm_script(tag: str) -> str:
    """Title-case a script subtag (BCP 47: language lowercase, script Titlecase)."""
    if "-" in tag:
        lang, _, rest = tag.partition("-")
        return f"{lang.lower()}-{rest[:1].upper()}{rest[1:].lower()}"
    return tag.lower()


def canon(tag: str) -> str:
    """Any accepted form (legacy 2-letter, ISO 639-3, BCP 47) -> canonical tag.

    Unknown tags pass through normalized (so new languages added with their ISO
    639-3 code Just Work without editing this table)."""
    if not tag:
        return tag
    t = tag.strip()
    low = t.lower()
    if low in _LEGACY_TO_CANON:
        return _LEGACY_TO_CANON[low]
    if t in _CANON_TO_WEB or t in _DISPLAY:
        return t
    return _norm_script(t)


def to_web(tag: str) -> str:
    """Canonical (or any) tag -> shortest BCP 47 tag for web / Hugging Face."""
    c = canon(tag)
    return _CANON_TO_WEB.get(c, c)


def display_name(tag: str) -> str:
    """Human-readable language name for a tag (falls back to the tag itself)."""
    return _DISPLAY.get(canon(tag), tag)
