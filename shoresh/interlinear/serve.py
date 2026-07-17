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

import sqlite3
from functools import lru_cache
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from references import BOOK_NUMBERS  # noqa: E402

HERE = Path(__file__).resolve().parent
HG_DB = HERE / "data" / "hebrew_greek.db"
GLOSS_DIR = HERE / "data" / "gloss"

BOOK_CODE_BY_ID = {v: k for k, v in BOOK_NUMBERS.items()}

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


def word_id_chapter_bounds(book_id: int, chapter: int) -> tuple[int, int]:
    lower = book_id * _WORD_ID_BOOK_MULT + chapter * _WORD_ID_CHAPTER_MULT
    upper = book_id * _WORD_ID_BOOK_MULT + (chapter + 1) * _WORD_ID_CHAPTER_MULT
    return lower, upper


def is_ready() -> bool:
    return _hg_db() is not None


@lru_cache(maxsize=1)
def list_languages() -> list[str]:
    """Language codes with a built gloss db in data/gloss/."""
    if not GLOSS_DIR.exists():
        return []
    return sorted(p.stem for p in GLOSS_DIR.glob("*.db"))


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
        (strongs_code, limit),
    ).fetchall()
    return [r["verseId"] for r in rows]


def count_verses_for_strongs(strongs_code: str) -> int:
    db = _hg_db()
    if db is None:
        return 0
    row = db.execute(
        """SELECT COUNT(DISTINCT (v._id / 100)) AS total
           FROM verses v JOIN strongs l ON v.strongs = l._id WHERE l.code = ?""",
        (strongs_code,),
    ).fetchone()
    return row["total"] if row else 0


def extract_reference_from_verse_id(verse_id: int) -> dict:
    book_id = verse_id // 1_000_000
    remainder = verse_id % 1_000_000
    chapter = remainder // 1_000
    verse = remainder % 1_000
    return {"bookId": book_id, "book": BOOK_CODE_BY_ID.get(book_id), "chapter": chapter, "verse": verse}
