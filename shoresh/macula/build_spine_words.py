#!/usr/bin/env python3
"""Build the lexeme-anchored `spine_words` export — data contract §1 (shoresh → strongs-aligner).

Companion to `spine/parse.py` (the STEPBible `spine.db`). This build target reads the CC-BY MACULA
token layer in `macula-spine.db` and emits a spine keyed on the **canonical lexeme id** —
`(lang, augmented Strong's)`, e.g. `hbo:0871a` — with the bare Strong's as a derived *rollup*
attribute (not the key), plus `gloss`/`role` (projection channel #1) and a class-derived
`is_content`. shoresh owns the MACULA→lexeme logic; the aligner consumes this artifact with a thin
SELECT (see internal-docs/data-contracts.md).

Why lexeme, not Strong's, is the anchor: MACULA distinguishes homographs that share a Strong's
number by an augment letter (`0871a` vs `0871b` = different lexemes). The augmented id is the
join-able identity; the bare Strong's rolls several lexemes together and is only an attribute.

  python -m macula.build_spine_words          # macula/macula-spine.db -> macula/lexeme-spine.db
  python -m macula.build_spine_words --in … --out …
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine.common import load_equivalences  # variant→canonical Hebrew Strong's (spine.db parity)

HERE = Path(__file__).resolve().parent
IN_DEFAULT = HERE / "macula-spine.db"
OUT_DEFAULT = HERE / "lexeme-spine.db"

# MACULA upstream (tracked in macula/parse.py) — recorded in spine_meta for provenance.
GRC_SRC = "Clear-Bible/macula-greek@main Nestle1904/tsv"
HBO_SRC = "Clear-Bible/macula-hebrew@main WLC/tsv"

# Content = the open lexical classes. Kept parallel to the STEPBible spine's N/V/A head-POS
# (spine/common._CONTENT_POS) so the two spines' `is_content` — and every coverage number keyed
# off it — stay directly comparable. Widen here (e.g. add "adv") only deliberately, in lockstep.
_CONTENT_CLASSES = {"noun", "verb", "adj"}

_DIGITS = re.compile(r"\d+")


def rollup_strong(raw: str | None, lang: str, eq: dict[int, int]) -> int | None:
    """Augmented MACULA Strong's (`0871a`, `976`) → bare int, augment letter dropped. Hebrew is
    equivalence-canonicalized so the rollup matches spine.db's Strong's for cross-resource joins."""
    if not raw:
        return None
    m = _DIGITS.search(raw)
    if not m:
        return None
    n = int(m.group())
    return eq.get(n, n) if lang == "hbo" else n


def build(in_path: Path, out_path: Path) -> tuple[int, int]:
    src = sqlite3.connect(f"file:{in_path}?mode=ro", uri=True)
    eq = load_equivalences()

    out_path.unlink(missing_ok=True)
    db = sqlite3.connect(out_path)
    db.executescript("""
        CREATE TABLE spine_words (
            book TEXT NOT NULL, chapter INTEGER NOT NULL, verse INTEGER NOT NULL,
            idx INTEGER NOT NULL,
            key TEXT NOT NULL,           -- MACULA token id: the per-occurrence NODE (bridge join key)
            surface TEXT NOT NULL,
            lexeme TEXT NOT NULL,        -- ANCHOR: lang:augmented-strong (e.g. hbo:0871a)
            strong INTEGER,              -- rollup attribute: augment stripped, eq-canonicalized
            lemma TEXT, is_content INTEGER NOT NULL, morph TEXT,
            gloss TEXT, role TEXT,
            stem TEXT,                   -- verbal stem (Hebrew binyan), CC-BY — clean sense-key dim
            person TEXT, number TEXT, gender TEXT, case_ TEXT, tense TEXT, voice TEXT,
            mood TEXT, degree TEXT, state TEXT,   -- structured morphology (wishlist #2); "" = n/a
            PRIMARY KEY (book, chapter, verse, idx)
        );
        CREATE UNIQUE INDEX ix_ls_key ON spine_words(key);
        CREATE INDEX ix_ls_lexeme ON spine_words(lexeme);
        CREATE INDEX ix_ls_strong ON spine_words(strong);
        CREATE TABLE spine_meta (key TEXT PRIMARY KEY, value TEXT);
    """)

    # MACULA tokenizes finer than STEPBible: a pointed word is split into morpheme sub-tokens that
    # share `word` (e.g. וּמִלְמַעְלָה = 5 rows, word=1), ordered by the globally-unique `key`. So idx
    # is a running per-verse position in key order — one row per MACULA token — not `word`.
    rows, content_rows, content_with_strong = [], 0, 0
    q = ("SELECT lang, book, chapter, verse, key, text, strong, lemma, gloss, role, class, stem, "
         "person, number, gender, case_, tense, voice, mood, degree, state "
         "FROM macula_words ORDER BY book, chapter, verse, key")
    idx, prev = 0, None
    for (lang, book, ch, v, key, text, strong, lemma, gloss, role, cls, stem,
         person, number, gender, case_, tense, voice, mood, degree, state) in src.execute(q):
        cvk = (book, ch, v)
        idx = idx + 1 if cvk == prev else 0
        prev = cvk
        lexeme = f"{lang}:{strong}" if strong else f"{lang}:"
        is_content = 1 if cls in _CONTENT_CLASSES else 0
        content_rows += is_content
        s_roll = rollup_strong(strong, lang, eq)
        content_with_strong += is_content and s_roll is not None
        rows.append((book, ch, v, idx, key, text, lexeme, s_roll, lemma, is_content,
                     "", gloss, role, stem or "",    # morph "" (kept empty; structured cols replace it)
                     person, number, gender, case_, tense, voice, mood, degree, state))

    db.executemany("INSERT INTO spine_words VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)

    in_sha = hashlib.sha256(in_path.read_bytes()).hexdigest()
    db.executemany("INSERT INTO spine_meta VALUES (?,?)", [
        ("anchor", "lexeme = lang:augmented-strong"),
        ("strong_rollup", "augment-stripped; Hebrew equivalence-canonicalized (spine.db parity)"),
        ("content_classes", ",".join(sorted(_CONTENT_CLASSES)) + " (= STEPBible spine N/V/A)"),
        ("source_greek", GRC_SRC), ("source_hebrew", HBO_SRC),
        ("macula_spine_sha256", in_sha),            # the pinned input (contract §1 pin point)
        ("words", str(len(rows))),
    ])
    db.commit()
    db.close()
    return len(rows), (content_rows, content_with_strong)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the lexeme-anchored spine_words (data contract §1).")
    ap.add_argument("--in", dest="in_path", type=Path, default=IN_DEFAULT, help="macula-spine.db")
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT, help="output lexeme-spine.db")
    args = ap.parse_args()
    if not args.in_path.exists():
        sys.exit(f"missing input {args.in_path} — build it first: python -m macula.parse")

    n, (content, content_strong) = build(args.in_path, args.out)
    out_sha = hashlib.sha256(args.out.read_bytes()).hexdigest()
    cov = 100 * content_strong / max(1, content)
    print(f"{n} tokens -> {args.out}")
    print(f"  content (N/V/A): {content}  with Strong's: {cov:.1f}%")
    if cov < 99:
        print(f"  ! content Strong's coverage {cov:.1f}% (<99%) — check the MACULA source", file=sys.stderr)
    print(f"  build sha256: {out_sha}")
    print("  → pin this sha256 in the consumer's data/PROVENANCE.txt (contract §1)")


if __name__ == "__main__":
    main()
