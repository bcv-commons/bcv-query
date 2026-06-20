#!/usr/bin/env python3
"""Spine parser — UHB + UGNT → per-word records.

Fetches the pinned UHB (Hebrew OT) and UGNT (Greek NT) USFM from Door43,
parses the `\\w surface|lemma=… strong=… x-morph=…\\w*` markup into one
record per word, applies the Strong's equivalence table, runs fidelity
assertions, and writes a SQLite spine.

Spec: ../docs/spine-parser.md

Usage:
    python -m spine.parse              # all books (OT + NT) -> spine/spine.db
    python -m spine.parse --ot         # OT only
    python -m spine.parse --book GEN RUT
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

from spine.common import (
    FILENUM, JOINER, NT_BOOKS, OT_BOOKS, UGNT_TAG, UGNT_URL, UHB_TAG, UHB_URL,
    content_strong_field, head_pos, is_content, load_equivalences, morph_body,
    norm_strong,
)

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "spine.db"

_W = re.compile(r'\\w ([^|]*)\|([^\\]*?)\\w\*')   # \w surface|attrs\w*
_ATTR = re.compile(r'(\w[\w-]*)="([^"]*)"')
_CV = re.compile(r'\\([cv]) (\d+)')


@dataclass
class SpineWord:
    book: str
    chapter: int
    verse: int
    index: int        # 0-based word position within the verse
    surface: str
    strong: int | None
    lemma: str
    morph: str
    is_content: bool


def fetch_book(code: str, lang: str) -> str:
    url = (UHB_URL if lang == "hbo" else UGNT_URL).format(nn=FILENUM[code], code=code)
    r = httpx.get(url, timeout=120, follow_redirects=True)
    r.raise_for_status()
    return r.text


def parse_usfm(text: str, code: str, lang: str, eq: dict[int, int]) -> list[SpineWord]:
    words: list[SpineWord] = []
    chapter = verse = 0
    idx = 0
    # iterate chapter/verse markers and \w words in document order
    for m in re.finditer(r'\\c (\d+)|\\v (\d+)|\\w ([^|]*)\|([^\\]*?)\\w\*', text):
        if m.group(1):
            # new chapter: reset verse so pre-\v words (e.g. Psalm superscriptions
            # in \d) land in verse 0, not the previous chapter's last verse.
            chapter = int(m.group(1)); verse = 0; idx = 0
        elif m.group(2):
            verse = int(m.group(2)); idx = 0
        elif m.group(3) is not None:
            surface, attrs_s = m.group(3), m.group(4)
            attrs = dict(_ATTR.findall(attrs_s))
            morph = attrs.get("x-morph", "")
            s_raw = content_strong_field(attrs.get("strong", ""))
            strong = norm_strong(s_raw, lang)
            if strong is not None:
                strong = eq.get(strong, strong)
            words.append(SpineWord(
                book=code, chapter=chapter, verse=verse, index=idx,
                surface=surface, strong=strong, lemma=attrs.get("lemma", ""),
                morph=morph, is_content=is_content(morph, lang),
            ))
            idx += 1
    return words


def check_fidelity(words: list[SpineWord], code: str, lang: str) -> list[str]:
    """Return a list of warnings (does not raise)."""
    warn = []
    # triangulation (Hebrew only): surface joiner-pieces == morph :-segments.
    # A small rate (<1%) is expected (ketiv/qere, multi-part forms); warn only
    # on an anomalous rate, which would signal a parsing regression.
    if lang == "hbo" and words:
        bad = sum(1 for w in words
                  if len(w.surface.split(JOINER)) != len(morph_body(w.morph).split(":")))
        if bad / len(words) > 0.01:
            warn.append(f"{code}: {bad}/{len(words)} ({100*bad/len(words):.1f}%) fail "
                        "surface↔morph triangulation — possible parse regression")
    # Strong's coverage over CONTENT words (the meaningful metric; function
    # particles legitimately lack a Strong's). Baseline from reconciliation ~99%.
    content = [w for w in words if w.is_content]
    have = sum(1 for w in content if w.strong is not None)
    if content and have / len(content) < 0.99:
        warn.append(f"{code}: content Strong's coverage {100*have/len(content):.1f}% (<99%)")
    return warn


def write_sqlite(records: list[SpineWord], db_path: Path) -> None:
    db_path.unlink(missing_ok=True)
    db = sqlite3.connect(db_path)
    db.executescript("""
        CREATE TABLE spine_words (
            book TEXT NOT NULL, chapter INTEGER NOT NULL, verse INTEGER NOT NULL,
            idx INTEGER NOT NULL, surface TEXT NOT NULL, strong INTEGER,
            lemma TEXT, morph TEXT, is_content INTEGER NOT NULL,
            PRIMARY KEY (book, chapter, verse, idx)
        );
        CREATE INDEX ix_spine_strong ON spine_words(strong);
        CREATE TABLE spine_meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    db.executemany(
        "INSERT INTO spine_words VALUES (?,?,?,?,?,?,?,?,?)",
        [(w.book, w.chapter, w.verse, w.index, w.surface, w.strong, w.lemma,
          w.morph, int(w.is_content)) for w in records],
    )
    db.executemany("INSERT INTO spine_meta VALUES (?,?)", [
        ("uhb_tag", UHB_TAG), ("ugnt_tag", UGNT_TAG), ("words", str(len(records))),
    ])
    db.commit()
    db.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse UHB/UGNT into the spine.")
    ap.add_argument("--ot", action="store_true", help="OT only (UHB)")
    ap.add_argument("--nt", action="store_true", help="NT only (UGNT)")
    ap.add_argument("--book", nargs="*", help="specific book codes")
    ap.add_argument("--out", type=Path, default=DB_PATH)
    args = ap.parse_args()

    if args.book:
        targets = [(c, "hbo" if FILENUM[c] <= 39 else "grc") for c in (b.upper() for b in args.book)]
    elif args.ot:
        targets = [(c, "hbo") for c in OT_BOOKS]
    elif args.nt:
        targets = [(c, "grc") for c in NT_BOOKS]
    else:
        targets = [(c, "hbo") for c in OT_BOOKS] + [(c, "grc") for c in NT_BOOKS]

    eq = load_equivalences()
    records: list[SpineWord] = []
    warnings: list[str] = []
    for code, lang in targets:
        words = parse_usfm(fetch_book(code, lang), code, lang, eq)
        records.extend(words)
        warnings.extend(check_fidelity(words, code, lang))
        content = sum(1 for w in words if w.is_content)
        print(f"  {code} ({lang}): {len(words)} words, {content} content", file=sys.stderr)

    write_sqlite(records, args.out)
    print(f"\n{len(records)} words -> {args.out}")
    if warnings:
        print("warnings:")
        for w in warnings:
            print(f"  ! {w}")


if __name__ == "__main__":
    main()
