#!/usr/bin/env python3
"""Septuagint (LXX) parser — original-language Greek OT into a per-word store.

Source: eliranwong/LXX-Rahlfs-1935, the assembled MyBible export
`11_end-users_files/MyBible/Bibles/LXX_final_main.csv` (B-text recension;
`LXX_final_alternate.csv` is the A-text). One row per verse:

    booknum <TAB> chapter <TAB> verse <TAB> <inline word tokens>

Each word token is `SURFACE<S>wordid</S><m>lxx.POS.FEAT</m><S>strong</S><S>lexid</S>`
— the Strong's number is the first `<S>` *after* the `<m>` tag (the leading
`<S>` is an instance id, the trailing one a lexeme id; both are skipped). Some
words carry no Strong's (rare words) — handled as NULL.

Output: `lxx.db` (SQLite, table `lxx_words`) — the LXX as a first-class
original-language word store, schema parallel to the spine's `spine_words`
so canonical-OT verses join LXX ↔ spine ↔ BHSA on (book, chapter, verse,
strong). Greek is stored both accented (`surface`) and as the monotonic,
de-accented `plain` form (via spine.common.to_modern_form) that matches the
orthography ancient-Greek models were trained on.

Licence: CATSS-derived (non-commercial; see ../legal/CATSS-user-declaration.md
and ../spine/ATTRIBUTION.md). The whole derived work is non-commercial.

CLI (run from shoresh/ with PYTHONPATH=.):
    python -m lxx.parse                      # smoke test: Genesis only
    python -m lxx.parse --canonical          # the 39 canonical OT books
    python -m lxx.parse --all                # full LXX incl. deuterocanon
    python -m lxx.parse --book PSA ISA       # specific books
    python -m lxx.parse --src /path/to.csv   # use a local CSV (skip download)
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

from spine.common import to_modern_form

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "lxx.db"
DATA_DIR = HERE / "data"

# Pinned source (matches the spine's pinned-tag discipline).
LXX_COMMIT = "a1b5ff1c739f93cdd18dbab4c9e3fc6b1043141c"
LXX_URL = (
    "https://raw.githubusercontent.com/eliranwong/LXX-Rahlfs-1935/"
    f"{LXX_COMMIT}/11_end-users_files/MyBible/Bibles/LXX_final_main.csv"
)

# MyBible book number -> (code, canonical?). Canonical OT uses USFM codes so
# verses join the spine/BHSA; deuterocanon keeps USFM-deutero codes, canonical=0.
BOOK_NUM: dict[int, tuple[str, int]] = {
    10: ("GEN", 1), 20: ("EXO", 1), 30: ("LEV", 1), 40: ("NUM", 1), 50: ("DEU", 1),
    60: ("JOS", 1), 70: ("JDG", 1), 80: ("RUT", 1), 90: ("1SA", 1), 100: ("2SA", 1),
    110: ("1KI", 1), 120: ("2KI", 1), 130: ("1CH", 1), 140: ("2CH", 1),
    150: ("EZR", 1), 160: ("NEH", 1), 190: ("EST", 1), 220: ("JOB", 1),
    230: ("PSA", 1), 240: ("PRO", 1), 250: ("ECC", 1), 260: ("SNG", 1),
    290: ("ISA", 1), 300: ("JER", 1), 310: ("LAM", 1), 330: ("EZK", 1),
    340: ("DAN", 1), 350: ("HOS", 1), 360: ("JOL", 1), 370: ("AMO", 1),
    380: ("OBA", 1), 390: ("JON", 1), 400: ("MIC", 1), 410: ("NAM", 1),
    420: ("HAB", 1), 430: ("ZEP", 1), 440: ("HAG", 1), 450: ("ZEC", 1),
    460: ("MAL", 1),
    # deuterocanon / LXX-only (canonical = 0)
    165: ("1ES", 0), 170: ("TOB", 0), 180: ("JDT", 0), 232: ("PSS", 0),
    270: ("WIS", 0), 279: ("SIR", 0), 280: ("SIR", 0), 315: ("LJE", 0),
    320: ("BAR", 0), 325: ("SUS", 0), 345: ("BEL", 0), 800: ("ODA", 0),
    462: ("1MA", 0), 464: ("2MA", 0), 466: ("3MA", 0), 467: ("4MA", 0),
}

CONTENT_POS = {"N", "V", "A"}  # noun / verb / adjective — matches the spine

_MORPH = re.compile(r"<m>lxx\.([^<]*)</m>")
_WORD = re.compile(r"^([^<\s]+)")
_STRONG = re.compile(r"<S>(\d+)</S>")

SCHEMA = """
CREATE TABLE IF NOT EXISTS lxx_words (
  book       TEXT NOT NULL,
  chapter    INTEGER NOT NULL,
  verse      INTEGER NOT NULL,
  idx        INTEGER NOT NULL,
  surface    TEXT NOT NULL,
  plain      TEXT NOT NULL,
  strong     INTEGER,
  morph      TEXT,
  pos        TEXT,
  is_content INTEGER NOT NULL,
  canonical  INTEGER NOT NULL,
  PRIMARY KEY (book, chapter, verse, idx)
);
CREATE INDEX IF NOT EXISTS idx_lxx_strong ON lxx_words(strong);
CREATE INDEX IF NOT EXISTS idx_lxx_book ON lxx_words(book, chapter, verse);
"""


def parse_word(tok: str):
    """One inline token -> (surface, strong|None, morph|None, pos)."""
    wm = _WORD.match(tok)
    if not wm:
        return None
    surface = wm.group(1).strip("·.,;:")
    if not surface:
        return None
    mm = _MORPH.search(tok)
    morph = mm.group(1) if mm else None
    pos = morph.split(".")[0] if morph else ""
    strong = None
    mpos = tok.find("<m>")
    if mpos >= 0:                       # Strong's = first <S> after <m>
        sm = _STRONG.search(tok, mpos)
        if sm:
            strong = int(sm.group(1))
    return surface, strong, morph, pos


def iter_words(src: Path, wanted: set[str] | None):
    """Yield (book, chapter, verse, idx, surface, strong, morph, pos) rows."""
    with src.open(encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            num, ch, v, text = parts[0], parts[1], parts[2], parts[3]
            try:
                booknum = int(num)
            except ValueError:
                continue
            code, _canon = BOOK_NUM.get(booknum, (f"X{booknum}", 0))
            if wanted is not None and code not in wanted:
                continue
            idx = 0
            for tok in text.split(" "):
                if not tok:
                    continue
                parsed = parse_word(tok)
                if not parsed:
                    continue
                surface, strong, morph, pos = parsed
                idx += 1
                yield (code, int(ch), int(v), idx, surface, strong, morph, pos)


def fetch(src: Path | None) -> Path:
    if src:
        return src
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = DATA_DIR / f"LXX_final_main.{LXX_COMMIT[:8]}.csv"
    if not cache.exists():
        import httpx

        print(f"downloading pinned LXX ({LXX_COMMIT[:8]}) …", file=sys.stderr)
        r = httpx.get(LXX_URL, timeout=300, follow_redirects=True)
        r.raise_for_status()
        cache.write_bytes(r.content)
    return cache


def build(wanted: set[str] | None, src: Path | None) -> None:
    source = fetch(src)
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    db.execute("DELETE FROM lxx_words" + ("" if wanted is None else
               " WHERE book IN (%s)" % ",".join("?" * len(wanted))),
               tuple(wanted) if wanted else ())
    n = 0
    for (code, ch, v, idx, surface, strong, morph, pos) in iter_words(source, wanted):
        db.execute(
            "INSERT OR REPLACE INTO lxx_words "
            "(book,chapter,verse,idx,surface,plain,strong,morph,pos,is_content,canonical) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (code, ch, v, idx, surface, to_modern_form(surface, "grc"),
             strong, morph, pos, 1 if pos in CONTENT_POS else 0, _canon_of(code)),
        )
        n += 1
    db.commit()
    _report(db, n)
    db.close()


_CANON_CODES = {c for (c, k) in BOOK_NUM.values() if k == 1}


def _canon_of(code: str) -> int:
    return 1 if code in _CANON_CODES else 0


def _report(db, n: int) -> None:
    books = db.execute("SELECT COUNT(DISTINCT book) FROM lxx_words").fetchone()[0]
    content = db.execute("SELECT COUNT(*) FROM lxx_words WHERE is_content=1").fetchone()[0]
    strong = db.execute("SELECT COUNT(*) FROM lxx_words WHERE strong IS NOT NULL").fetchone()[0]
    print(f"\nlxx.db: {n:,} words · {books} books · "
          f"{content:,} content ({100*content//max(n,1)}%) · "
          f"{strong:,} with Strong's ({100*strong//max(n,1)}%)", file=sys.stderr)
    row = db.execute(
        "SELECT surface, strong, morph FROM lxx_words "
        "WHERE book='GEN' AND chapter=1 AND verse=1 ORDER BY idx").fetchall()
    if row:
        print("GEN 1:1 →", " ".join(f"{s}/G{st or '?'}/{m}" for s, st, m in row),
              file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse the LXX into lxx.db")
    ap.add_argument("--all", action="store_true", help="full LXX incl. deuterocanon")
    ap.add_argument("--canonical", action="store_true", help="the 39 canonical OT books")
    ap.add_argument("--book", nargs="+", metavar="CODE", help="specific book code(s)")
    ap.add_argument("--src", type=Path, help="local CSV path (skip download)")
    args = ap.parse_args()

    if args.all:
        wanted = None
    elif args.canonical:
        wanted = set(_CANON_CODES)
    elif args.book:
        wanted = {b.upper() for b in args.book}
    else:
        wanted = {"GEN"}  # smoke test
    build(wanted, args.src)


if __name__ == "__main__":
    main()
