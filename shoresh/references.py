"""Bible reference encoding/decoding helpers.

Three encodings interoperate here:
    USFM book code   - 3-letter, e.g. "TIT"           — used in tags + ingest
    Canonical number - 1..66 (Protestant order)       — used in BBCCCVVV
    BBCCCVVV         - 8-digit integer BBCCCVVV       — used in passage_refs

"Romans 3:24" → BBCCCVVV 45003024 → human "Romans 3:24"

Note on numbering: this module uses **canonical Protestant numbering**
(GEN=1 … MAL=39, MAT=40 … REV=66). Door43's filename prefixes use a
different (Paratext) numbering with a skipped slot at 40 — that mapping
is in `ingest.door43` and only affects URL construction, not BBCCCVVV.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

# fmt: off
BOOK_NUMBERS: dict[str, int] = {
    # Old Testament (1–39)
    "GEN":  1, "EXO":  2, "LEV":  3, "NUM":  4, "DEU":  5,
    "JOS":  6, "JDG":  7, "RUT":  8, "1SA":  9, "2SA": 10,
    "1KI": 11, "2KI": 12, "1CH": 13, "2CH": 14, "EZR": 15,
    "NEH": 16, "EST": 17, "JOB": 18, "PSA": 19, "PRO": 20,
    "ECC": 21, "SNG": 22, "ISA": 23, "JER": 24, "LAM": 25,
    "EZK": 26, "DAN": 27, "HOS": 28, "JOL": 29, "AMO": 30,
    "OBA": 31, "JON": 32, "MIC": 33, "NAM": 34, "HAB": 35,
    "ZEP": 36, "HAG": 37, "ZEC": 38, "MAL": 39,
    # New Testament (40–66)
    "MAT": 40, "MRK": 41, "LUK": 42, "JHN": 43, "ACT": 44,
    "ROM": 45, "1CO": 46, "2CO": 47, "GAL": 48, "EPH": 49,
    "PHP": 50, "COL": 51, "1TH": 52, "2TH": 53, "1TI": 54,
    "2TI": 55, "TIT": 56, "PHM": 57, "HEB": 58, "JAS": 59,
    "1PE": 60, "2PE": 61, "1JN": 62, "2JN": 63, "3JN": 64,
    "JUD": 65, "REV": 66,
}
# fmt: on

# book_names.json lives in the shared resources/ root (baked to /app/resources in the
# image via $BCV_RESOURCES_DIR; repo-root resources/ in a dev checkout) — same convention
# as data._resources_dir(). Was previously ../book_names.json, which never existed → this
# module silently fell back to English-only names.
_RES_DIR = Path(os.environ["BCV_RESOURCES_DIR"]) if os.environ.get("BCV_RESOURCES_DIR") \
    else Path(__file__).resolve().parent.parent / "resources"
_BOOK_NAMES_JSON = _RES_DIR / "book_names.json"

_ENGLISH_BOOK_NAMES: dict[str, str] = {
    "GEN": "Genesis", "EXO": "Exodus", "LEV": "Leviticus", "NUM": "Numbers", "DEU": "Deuteronomy",
    "JOS": "Joshua", "JDG": "Judges", "RUT": "Ruth", "1SA": "1 Samuel", "2SA": "2 Samuel",
    "1KI": "1 Kings", "2KI": "2 Kings", "1CH": "1 Chronicles", "2CH": "2 Chronicles", "EZR": "Ezra",
    "NEH": "Nehemiah", "EST": "Esther", "JOB": "Job", "PSA": "Psalms", "PRO": "Proverbs",
    "ECC": "Ecclesiastes", "SNG": "Song of Songs", "ISA": "Isaiah", "JER": "Jeremiah", "LAM": "Lamentations",
    "EZK": "Ezekiel", "DAN": "Daniel", "HOS": "Hosea", "JOL": "Joel", "AMO": "Amos",
    "OBA": "Obadiah", "JON": "Jonah", "MIC": "Micah", "NAM": "Nahum", "HAB": "Habakkuk",
    "ZEP": "Zephaniah", "HAG": "Haggai", "ZEC": "Zechariah", "MAL": "Malachi",
    "MAT": "Matthew", "MRK": "Mark", "LUK": "Luke", "JHN": "John", "ACT": "Acts",
    "ROM": "Romans", "1CO": "1 Corinthians", "2CO": "2 Corinthians", "GAL": "Galatians", "EPH": "Ephesians",
    "PHP": "Philippians", "COL": "Colossians", "1TH": "1 Thessalonians", "2TH": "2 Thessalonians",
    "1TI": "1 Timothy", "2TI": "2 Timothy", "TIT": "Titus", "PHM": "Philemon", "HEB": "Hebrews",
    "JAS": "James", "1PE": "1 Peter", "2PE": "2 Peter", "1JN": "1 John", "2JN": "2 John",
    "3JN": "3 John", "JUD": "Jude", "REV": "Revelation",
}

BOOK_NAMES: dict[str, str] = _ENGLISH_BOOK_NAMES


# book_names.json keys are canonical ISO 639-3 (BCP 47); accept legacy 2-letter.
_LEGACY_LANG = {
    "en": "eng", "es": "spa", "fr": "fra", "pt": "por", "ru": "rus", "ar": "arb",
    "hi": "hin", "bn": "ben", "as": "asm", "ha": "hau", "id": "ind",
    "zh": "cmn-Hans", "zh-Hant": "cmn-Hant",
}


@lru_cache(maxsize=8)
def _load_book_i18n(lang: str) -> dict[str, str]:
    lang = _LEGACY_LANG.get(lang, lang)
    if _BOOK_NAMES_JSON.exists():
        data = json.loads(_BOOK_NAMES_JSON.read_text(encoding="utf-8"))
        names = data.get("names", {})
        if lang in names:
            return names[lang]
        if "eng" in names:
            return names["eng"]
    return _ENGLISH_BOOK_NAMES


def book_name(code: str, lang: str = "en") -> str:
    return _load_book_i18n(lang).get(code, code)

NUMBER_TO_CODE: dict[int, str] = {n: c for c, n in BOOK_NUMBERS.items()}


def _normalize_alias(name: str) -> str:
    # Drop whitespace AND periods so "1. Korinther" / "1. Corinthians" collapse to the
    # same key as the "1 Korinther" space form ("1korinther").
    return re.sub(r"[\s.]+", "", name).lower()


# Map normalized natural-language / abbreviation forms → USFM code.
BOOK_ALIASES: dict[str, str] = {}


def _seed_aliases() -> None:
    if _BOOK_NAMES_JSON.exists():
        data = json.loads(_BOOK_NAMES_JSON.read_text(encoding="utf-8"))
        for lang, names in data.get("names", {}).items():
            for code, name in names.items():
                BOOK_ALIASES[_normalize_alias(name)] = code
                no_num = re.sub(r"^\d+\s+", lambda m: m.group().strip(), name)
                if no_num != name:
                    BOOK_ALIASES[_normalize_alias(no_num)] = code
        for lang, extras in data.get("extra_aliases", {}).items():
            for code, aliases in extras.items():
                for alias in aliases:
                    BOOK_ALIASES[_normalize_alias(alias)] = code
    else:
        for code, name in _ENGLISH_BOOK_NAMES.items():
            BOOK_ALIASES[_normalize_alias(name)] = code
    for code in BOOK_NUMBERS:
        BOOK_ALIASES[_normalize_alias(code)] = code


_seed_aliases()


def encode(book_code: str, chapter: int, verse: int) -> int:
    """Encode (book_code, chapter, verse) → BBCCCVVV integer."""
    book = BOOK_NUMBERS.get(book_code.upper())
    if book is None:
        raise ValueError(f"unknown book code: {book_code}")
    if not (1 <= chapter <= 999) or not (1 <= verse <= 999):
        raise ValueError(f"chapter/verse out of range: {chapter}:{verse}")
    return book * 1_000_000 + chapter * 1_000 + verse


def decode(bbcccvvv: int) -> tuple[str, int, int]:
    """Decode BBCCCVVV integer → (book_code, chapter, verse)."""
    book_num = bbcccvvv // 1_000_000
    chapter = (bbcccvvv // 1_000) % 1_000
    verse = bbcccvvv % 1_000
    code = NUMBER_TO_CODE.get(book_num)
    if code is None:
        raise ValueError(f"unknown book number: {book_num}")
    return code, chapter, verse


def human(start_bbcccvvv: int, end_bbcccvvv: int | None = None,
         lang: str = "en") -> str:
    """Render a passage range as 'Romans 3:24', localized by lang."""
    names = _load_book_i18n(lang)
    s_code, s_ch, s_v = decode(start_bbcccvvv)
    s_name = names.get(s_code, s_code)
    if end_bbcccvvv is None or end_bbcccvvv == start_bbcccvvv:
        return f"{s_name} {s_ch}:{s_v}"
    e_code, e_ch, e_v = decode(end_bbcccvvv)
    e_name = names.get(e_code, e_code)
    if s_code != e_code:
        return f"{s_name} {s_ch}:{s_v} – {e_name} {e_ch}:{e_v}"
    if s_ch == e_ch:
        return f"{s_name} {s_ch}:{s_v}-{e_v}"
    return f"{s_name} {s_ch}:{s_v}-{e_ch}:{e_v}"


# Match natural-language references like "Titus 1:1", "Rom 3:24-25",
# "1 Corinthians 13:4-7", "1Cor 13", "Genesis 1", "Ruth chapter 1", "Ruth ch 1".
#
# Note: a chapter number is REQUIRED. Bare book names ("Titus", "Ruth") do
# NOT extract a passage filter, because two-letter book aliases like "is"
# (Isaiah), "am" (Amos), "ti" (Titus), "ge" (Genesis) collide catastrophically
# with common English words. If a user wants whole-book scope they should
# write "Titus 1" or "Ruth 1" — explicit chapter disambiguates.
_REF_RE = re.compile(
    r"""
    \b
    ((?:[123]\s*\.?\s*)?[A-Za-z]+)       # book name (optional 1/2/3 prefix, "1 " or "1. ")
    \s+(?:chapter\s+|chap\.?\s+|ch\.?\s+)?  # optional "chapter" / "chap." / "ch." filler
    (\d+)                                # chapter number (REQUIRED)
    (?:                                  # optional verse(s)
      (?::|\s+verse\s+|\s+v\.?\s*)        # ":" or "verse" or "v"/"v." before verse number
      (\d+)
      (?:-(\d+)(?::(\d+))?)?
    )?
    \b
    """,
    re.VERBOSE,
)


def parse_references(text: str) -> list[tuple[int, int]]:
    """Find natural-language refs in `text`, return list of (start, end) BBCCCVVV pairs.

    Notes:
      • Bare book names ("Titus", "Ruth") expand to the whole-book range.
      • Whole-chapter queries ("Titus 1") expand to verse 1..999 of that chapter.
      • Cross-chapter ranges ("Romans 3:24-4:2") are honored.
      • Unknown book names are silently skipped — this is a best-effort
        analyzer, not a validator. The synthesis layer is the trust boundary.
    """
    out: list[tuple[int, int]] = []
    for m in _REF_RE.finditer(text):
        book_raw, ch_s, v_s, v_or_ch_e, v_e = m.groups()
        code = BOOK_ALIASES.get(_normalize_alias(book_raw))
        if not code:
            continue
        ch = int(ch_s)
        try:
            if v_s is None:
                start = encode(code, ch, 1)
                end = encode(code, ch, 999)
            elif v_or_ch_e is None:
                start = encode(code, ch, int(v_s))
                end = start
            elif v_e is None:
                start = encode(code, ch, int(v_s))
                end = encode(code, ch, int(v_or_ch_e))
            else:
                start = encode(code, ch, int(v_s))
                end = encode(code, int(v_or_ch_e), int(v_e))
        except ValueError:
            continue
        out.append((start, end) if start <= end else (end, start))
    return out
