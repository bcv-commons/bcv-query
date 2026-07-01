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
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from resource_paths import resource_path
from lang import canon

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

NUMBER_TO_CODE: dict[int, str] = {n: c for c, n in BOOK_NUMBERS.items()}

# book_names.json lives in the shared resources/ dir (resolved by resource_paths:
# $BCV_RESOURCES_DIR, else the nearest ancestor's resources/). Without it the
# container falls back to English-only aliases and localized refs silently fail.
_BOOK_NAMES = resource_path("book_names.json")


def _book_names_path() -> Path | None:
    return _BOOK_NAMES if _BOOK_NAMES.exists() else None


@lru_cache(maxsize=8)
def _load_book_i18n(lang: str) -> dict[str, str]:
    """Load book names for a language from book_names.json, fallback to English."""
    lang = canon(lang)
    path = _book_names_path()
    if path is not None:
        data = json.loads(path.read_text(encoding="utf-8"))
        names = data.get("names", {})
        if lang in names:
            return names[lang]
        if "eng" in names:
            return names["eng"]
    return _ENGLISH_BOOK_NAMES


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


def book_name(code: str, lang: str = "en") -> str:
    """Get localized book name for a USFM code."""
    return _load_book_i18n(lang).get(code, code)


# Arabic short-vowel/diacritic marks (harakat, tatweel, etc.) — optional in
# normal writing, so fold them away for matching ("اَلتَّكْوِينُ" == "التكوين").
# This is the Arabic range only; Indic vowel signs are essential letters and
# must NOT be stripped.
_ARABIC_DIACRITICS = re.compile(
    r"[ؐ-ًؚ-ٰٟۖ-ۜ۟-۪ۨ-ۭـ]")


def _fold_digits(s: str) -> str:
    """Map any script's decimal digits to ASCII (১→1, ٢→2) so numbered books
    match regardless of the digit script the user typed."""
    out = []
    for c in s:
        if not c.isascii() and c.isdigit():
            try:
                out.append(str(unicodedata.digit(c)))
                continue
            except (ValueError, TypeError):
                pass
        out.append(c)
    return "".join(out)


def _to_int(s: str) -> int:
    return int(_fold_digits(s))


def _normalize_alias(name: str) -> str:
    # Drop whitespace AND periods so "1. Korinther" / "1. Corinthians" collapse to the
    # same key as the "1 Korinther" space form ("1korinther").
    return _fold_digits(re.sub(r"[\s.]+", "", _ARABIC_DIACRITICS.sub("", name)).lower())


# Map normalized natural-language / abbreviation forms → USFM code.
BOOK_ALIASES: dict[str, str] = {}


def _seed_aliases() -> None:
    path = _book_names_path()
    if path is not None:
        data = json.loads(path.read_text(encoding="utf-8"))
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
# A "name word": any run of letters/marks in ANY script — i.e. not whitespace,
# not a digit (those are chapter/verse numbers), not underscore, not separator
# punctuation. Unlike [^\W\d_] this INCLUDES combining marks, without which
# Devanagari/Bengali names tokenize wrong (यूहन्ना → just य, breaking at the
# first vowel matra). Latin, Cyrillic, Arabic and Indic book names all match.
_NAMEWORD = r"[^\s\d_.,:;!?()\[\]{}«»\"'“”’/\\।॥]"
_REF_RE = re.compile(
    rf"""
    \b
    ((?:\d\s*\.?\s*)?{_NAMEWORD}+(?:\s+{_NAMEWORD}+){{0,6}})  # book name: up to 7 words
                                        # (optional 1/2/3 prefix). Multi-word lets
                                        # "От Иоанна" / "Song of Songs" and long formal
                                        # titles ("রিসَالَةُ … رُومِيَةَ") match;
                                        # parse_references keeps the longest word-suffix
                                        # that is a known alias (so prose prefixes drop).
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
        # The capture may include leading prose ("the gospel of John"). Try the
        # longest word-suffix first; the first one that is a known alias wins —
        # so "John" resolves while "the gospel of" is discarded, and full
        # multi-word names ("От Иоанна", "Song of Songs") match as a whole.
        words = book_raw.split()
        code = None
        for i in range(len(words)):
            code = BOOK_ALIASES.get(_normalize_alias(" ".join(words[i:])))
            if code:
                break
        if not code:
            continue
        try:
            ch = _to_int(ch_s)
            if v_s is None:
                start = encode(code, ch, 1)
                end = encode(code, ch, 999)
            elif v_or_ch_e is None:
                start = encode(code, ch, _to_int(v_s))
                end = start
            elif v_e is None:
                start = encode(code, ch, _to_int(v_s))
                end = encode(code, ch, _to_int(v_or_ch_e))
            else:
                start = encode(code, ch, _to_int(v_s))
                end = encode(code, _to_int(v_or_ch_e), _to_int(v_e))
        except ValueError:
            continue
        out.append((start, end) if start <= end else (end, start))
    return out
