"""Psalm superscription (title) spans for the MACULA spine -- load the committed table and mark spine tokens.

`is_superscription` in lexeme-spine-macula.db marks every token of a Psalm's title and no body token. The spans live in
the committed table `psalm_title_spans.tsv` (CC0 facts about the Hebrew text), produced by `build_psalm_title_spans.py`
from Hebrew-only sources: TVTMS (versification) for the psalms whose title is its own Hebrew verse(s), MACULA's clause
structure for the psalms whose title is the first words of verse 1, one hand-checked exception. No BHSA, no UHB, no
English text -- so the flag fits the file's CC BY licence.

A span is a key range (MACULA token keys sort in text order: BBCCCVVVWWWP), so it needs no tokenization assumptions:

  python -m macula.psalm_title_spans --apply macula/lexeme-spine-macula.db      # (re)mark an existing spine in place
  python -m macula.psalm_title_spans --check macula/lexeme-spine-macula.db      # compare the flag with the table
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TABLE = HERE / "psalm_title_spans.tsv"

SOURCE_NOTE = ("Psalm titles: versification (TVTMS, CC BY) for the psalms whose title is its own Hebrew verse(s); MACULA "
               "clause structure (CC BY) for those whose title opens verse 1; Hebrew-only, reviewed table "
               "macula/psalm_title_spans.tsv; no BHSA, UHB or English-translation input")


def load_spans(path: Path | None = None) -> list[dict]:
    """[{chapter, verses, evidence, first_key, last_key, words, hebrew}] from the committed table."""
    out = []
    with (path or TABLE).open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip() or line.startswith("#") or line.startswith("chapter\t"):
                continue
            c, verses, evidence, first, last, words, hebrew = line.rstrip("\n").split("\t")
            out.append({"chapter": int(c), "verses": verses, "evidence": evidence, "first_key": first,
                        "last_key": last, "words": int(words), "hebrew": hebrew})
    return out


def flagged_keys(keys: list[str], spans: list[dict]) -> set[str]:
    """The subset of PSA token `keys` that lies inside a span (inclusive key range, same chapter)."""
    inside: set[str] = set()
    for s in spans:
        lo, hi = s["first_key"], s["last_key"]
        inside.update(k for k in keys if lo <= k <= hi)
    return inside


def apply(db_path: Path, spans: list[dict] | None = None) -> tuple[int, int]:
    """Set spine_words.is_superscription from the table in an existing spine DB; returns (before, after) flagged counts."""
    spans = spans or load_spans()
    with sqlite3.connect(db_path) as db:
        before = db.execute("SELECT count(*) FROM spine_words WHERE is_superscription=1").fetchone()[0]
        db.execute("UPDATE spine_words SET is_superscription=0 WHERE is_superscription<>0")
        for s in spans:
            db.execute("UPDATE spine_words SET is_superscription=1 WHERE book='PSA' AND key BETWEEN ? AND ?",
                       (s["first_key"], s["last_key"]))
        after = db.execute("SELECT count(*) FROM spine_words WHERE is_superscription=1").fetchone()[0]
        db.execute("INSERT OR REPLACE INTO spine_meta(key, value) VALUES ('superscription_source', ?)", (SOURCE_NOTE,))
    return before, after


def check(db_path: Path, spans: list[dict] | None = None) -> list[str]:
    """Problems found comparing the DB's flag with the table (empty list = consistent)."""
    spans = spans or load_spans()
    problems: list[str] = []
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
        flagged = {k for (k,) in db.execute("SELECT key FROM spine_words WHERE is_superscription=1")}
        psa = [k for (k,) in db.execute("SELECT key FROM spine_words WHERE book='PSA' ORDER BY key")]
        want = flagged_keys(psa, spans)
        if want != flagged:
            problems.append(f"{len(want - flagged)} title tokens unflagged, {len(flagged - want)} flagged outside a title")
        for s in spans:
            n = sum(1 for k in psa if s["first_key"] <= k <= s["last_key"])
            if n == 0:
                problems.append(f"PSA {s['chapter']}: span matches no token")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", nargs="+", type=Path, metavar="DB")
    g.add_argument("--check", nargs="+", type=Path, metavar="DB")
    a = ap.parse_args()
    spans = load_spans()
    for p in (a.apply or a.check):
        if a.apply:
            b, n = apply(p, spans)
            print(f"{p}: is_superscription {b} -> {n} tokens")
        else:
            pr = check(p, spans)
            print(f"{p}: " + ("consistent with the table" if not pr else "; ".join(pr)))
            if pr:
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
