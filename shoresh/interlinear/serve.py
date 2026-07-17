"""Serving layer for the interlinear data — a Python/FastAPI port of data-api's 5 endpoints
(example/aleph/data-api/src/server.js + db/*.js), reading the .db files build_hebrew_greek.py and
build_gloss.py produce. Core contract only: `/chapter`, `/word`, `/languages`, `/similar` — the
Berean Standard Bible full-text (`eng_bsb.db`) and SDBH/SDBG lexicon meanings (`sdbh.db`/`sdbg.db`)
are pre-baked assets from the original Flutter app, not derived from the globalbibletools/data JSON
this module builds from — deferred (see shoresh/interlinear/README.md).

Word ids are packed BBCCCVVVWW (book, chapter, verse, word-in-verse) — same USFM book numbering as
shoresh/references.BOOK_NUMBERS (verified: GEN=1, EXO=2, MAT=40, matching gbt's own book ids).
"""
from __future__ import annotations

import re
import sqlite3
from functools import lru_cache
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from references import BOOK_NUMBERS, book_name, norm_strong  # noqa: E402

from interlinear.language_names import LANGUAGE_NAMES
from interlinear.morphology import expand_grammar

HERE = Path(__file__).resolve().parent
HG_DB = HERE / "data" / "hebrew_greek.db"
GLOSS_DIR = HERE / "data" / "gloss"
ASSETS_DIR = HERE / "data" / "assets"
TRANSLATION_DB = ASSETS_DIR / "eng_bsb.db"
HEBREW_LEXICON_DB = ASSETS_DIR / "sdbh.db"
GREEK_LEXICON_DB = ASSETS_DIR / "sdbg.db"

BOOK_CODE_BY_ID = {v: k for k, v in BOOK_NUMBERS.items()}
LEMMA_ID_OFFSET = 1_000_000_000

_VERSE_ID_BOOK_MULT = 1_000_000
_VERSE_ID_CHAPTER_MULT = 1_000

_WORD_ID_BOOK_MULT = 100_000_000
_WORD_ID_CHAPTER_MULT = 100_000


def _ro(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    # check_same_thread=False: this connection is @lru_cache'd (created once, reused across
    # requests), but FastAPI dispatches sync route handlers across a threadpool — a later request
    # can land on a different thread than the one that created the connection. Safe here because
    # every use in this module is a read (SELECT); sqlite3 permits concurrent reads from multiple
    # threads on one connection, it only disallows the DEFAULT same-thread-only check.
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


@lru_cache(maxsize=1)
def _hg_db() -> sqlite3.Connection | None:
    return _ro(HG_DB)


@lru_cache(maxsize=64)
def _gloss_db(lang: str) -> sqlite3.Connection | None:
    return _ro(GLOSS_DIR / f"{lang}.db")


@lru_cache(maxsize=1)
def _translation_db() -> sqlite3.Connection | None:
    return _ro(TRANSLATION_DB)


@lru_cache(maxsize=2)
def _lexicon_db(strongs_code: str) -> sqlite3.Connection | None:
    """sdbh.db for Hebrew (H-) codes, sdbg.db for Greek (G-) codes."""
    return _ro(HEBREW_LEXICON_DB if strongs_code.startswith("H") else GREEK_LEXICON_DB)


def word_id_chapter_bounds(book_id: int, chapter: int) -> tuple[int, int]:
    lower = book_id * _WORD_ID_BOOK_MULT + chapter * _WORD_ID_CHAPTER_MULT
    upper = book_id * _WORD_ID_BOOK_MULT + (chapter + 1) * _WORD_ID_CHAPTER_MULT
    return lower, upper


def verse_id_chapter_bounds(book_id: int, chapter: int) -> tuple[int, int]:
    lower = book_id * _VERSE_ID_BOOK_MULT + chapter * _VERSE_ID_CHAPTER_MULT
    upper = book_id * _VERSE_ID_BOOK_MULT + (chapter + 1) * _VERSE_ID_CHAPTER_MULT
    return lower, upper


def is_ready() -> bool:
    return _hg_db() is not None


@lru_cache(maxsize=1)
def list_languages() -> list[dict]:
    """{code, name} for every gloss db built in data/gloss/ — name falls back to the raw code
    for languages LANGUAGE_NAMES doesn't have a confirmed display name for."""
    if not GLOSS_DIR.exists():
        return []
    codes = sorted(p.stem for p in GLOSS_DIR.glob("*.db"))
    return [{"code": c, "name": LANGUAGE_NAMES.get(c, c)} for c in codes]


def get_chapter(book_id: int, chapter: int) -> list[dict] | None:
    db = _hg_db()
    if db is None:
        return None
    lower, upper = word_id_chapter_bounds(book_id, chapter)
    rows = db.execute(
        """SELECT v._id AS id, t.text AS text, l.code AS strongsCode
           FROM verses v
           JOIN text t ON v.text = t._id
           JOIN strongs l ON v.strongs = l._id
           WHERE v._id >= ? AND v._id < ?
           ORDER BY v._id ASC""",
        (lower, upper),
    ).fetchall()
    return [dict(r) for r in rows]


def get_word(word_id: int) -> dict | None:
    db = _hg_db()
    if db is None:
        return None
    row = db.execute(
        """SELECT t.text AS text, l.code AS strongsCode, g.grammar AS grammar, l.root AS strongsRoot
           FROM verses v
           JOIN text t ON v.text = t._id
           JOIN strongs l ON v.strongs = l._id
           JOIN grammar g ON v.grammar = g._id
           WHERE v._id = ?""",
        (word_id,),
    ).fetchone()
    return dict(row) if row else None


def get_translation_chapter(book_id: int, chapter: int) -> list[dict]:
    """The English (Berean Standard Bible) lines of a chapter — verse text plus any non-verse lines
    (headings, blank markers) sharing its BCCCVVV reference range. `[]` if eng_bsb.db isn't fetched
    (see interlinear.fetch.fetch_study_app_assets) rather than a hard failure, since translation
    text is presentational — a caller can still render the Hebrew/Greek without it."""
    db = _translation_db()
    if db is None:
        return []
    lower, upper = verse_id_chapter_bounds(book_id, chapter)
    rows = db.execute(
        """SELECT reference, text, format FROM bible
           WHERE reference >= ? AND reference < ? ORDER BY _id ASC""",
        (lower, upper),
    ).fetchall()
    return [dict(r) for r in rows]


_REF_TAG_RE = re.compile(r"\{L:([^{]*?)<SDB[GH]:([^:]*?)(:.*?)?>\}")
_VERSE_TAG_RE = re.compile(r"\{S:(\d{3})(\d{3})(\d{3})\d{5}\}")
_NOTE_TAG_RE = re.compile(r"\{N:\d+\}")


def _replace_references(text: str | None) -> str | None:
    """Expand SDBH/SDBG's inline reference markup into plain text, ported from
    example/aleph/data-api/src/db/lexicon.js's replaceReferences (itself ported from
    study-app's LexiconMeaning._replaceReferences)."""
    if text is None:
        return None

    def _lex_tag(m: re.Match) -> str:
        part1, part2 = m.group(1), m.group(2)
        return part1 if part1 == part2 else f"{part1} ({part2})"

    def _verse_tag(m: re.Match) -> str:
        book = book_name(BOOK_CODE_BY_ID.get(int(m.group(1)), ""), "en")
        return f"{book} {int(m.group(2))}:{int(m.group(3))}"

    result = _REF_TAG_RE.sub(_lex_tag, text)
    result = _VERSE_TAG_RE.sub(_verse_tag, result)
    result = _NOTE_TAG_RE.sub("", result)
    return result.replace("◄ ", "").replace("► ", "")


def get_meanings_for_strongs(strongs_code: str) -> list[dict]:
    """SDBH (Hebrew) / SDBG (Greek) lexicon meanings for a Strong's code — the granular,
    English-only lexicon entries a Strong's code can conflate (>1 lemma). `[]` if the relevant
    lexicon db isn't fetched."""
    db = _lexicon_db(strongs_code)
    if db is None:
        return []
    rows = db.execute(
        f"""SELECT m.lex_id AS lexId, m.Lemma AS lemma, m.definition_short AS definitionShort,
                   m.comments AS comments, m.glosses AS glosses, g.text AS grammar
            FROM meanings AS m
            JOIN strongs AS s ON (m.lex_id / {LEMMA_ID_OFFSET}) = s.lemma_id
            LEFT JOIN grammar AS g ON m.grammar_id = g._id
            WHERE s.strongs_code = ?""",
        (strongs_code,),
    ).fetchall()
    return [
        {
            "lexId": r["lexId"],
            "lemma": r["lemma"],
            "grammar": r["grammar"],
            "definitionShort": _replace_references(r["definitionShort"]),
            "comments": _replace_references(r["comments"]),
            "glosses": r["glosses"],
        }
        for r in rows
    ]


def get_gloss(lang: str, word_id: int) -> str | None:
    db = _gloss_db(lang)
    if db is None:
        return None
    row = db.execute(
        """SELECT t.text AS text FROM verses v JOIN text t ON v.text = t._id WHERE v._id = ?""",
        (word_id,),
    ).fetchone()
    return row["text"] if row else None


def get_verse_ids_for_strongs(strongs_code: str, limit: int) -> list[int]:
    """Distinct BCCCVVV verse ids (book*1_000_000 + chapter*1_000 + verse) containing this Strong's
    code, deduplicated + capped in SQL (a common word like the Greek article occurs 20k+ times —
    requires idx_verses_strongs, built by build_hebrew_greek.py, or this is a full table scan)."""
    db = _hg_db()
    if db is None:
        return []
    rows = db.execute(
        """SELECT DISTINCT (v._id / 100) AS verseId
           FROM verses v JOIN strongs l ON v.strongs = l._id
           WHERE l.code = ? ORDER BY verseId ASC LIMIT ?""",
        (norm_strong(strongs_code), limit),
    ).fetchall()
    return [r["verseId"] for r in rows]


def count_verses_for_strongs(strongs_code: str) -> int:
    db = _hg_db()
    if db is None:
        return 0
    row = db.execute(
        """SELECT COUNT(DISTINCT (v._id / 100)) AS total
           FROM verses v JOIN strongs l ON v.strongs = l._id WHERE l.code = ?""",
        (norm_strong(strongs_code),),
    ).fetchone()
    return row["total"] if row else 0


def extract_reference_from_verse_id(verse_id: int) -> dict:
    book_id = verse_id // 1_000_000
    remainder = verse_id % 1_000_000
    chapter = remainder // 1_000
    verse = remainder % 1_000
    code = BOOK_CODE_BY_ID.get(book_id)
    return {
        "bookId": book_id,
        "bookName": book_name(code, "en") if code else None,
        "book": code,
        "chapter": chapter,
        "verse": verse,
    }
