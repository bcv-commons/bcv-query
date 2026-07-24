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
from spine.superscriptions import all_chapter_vocab, classify_leading_run

HERE = Path(__file__).resolve().parent
IN_DEFAULT = HERE / "macula-spine.db"
OUT_DEFAULT = HERE / "lexeme-spine.db"
SPINE_DB_DEFAULT = HERE.parent / "spine" / "spine.db"

# MACULA upstream (tracked in macula/parse.py) — recorded in spine_meta for provenance.
GRC_SRC = "Clear-Bible/macula-greek@main Nestle1904/tsv"
HBO_SRC = "Clear-Bible/macula-hebrew@main WLC/tsv"

# Content = the open lexical classes. Kept parallel to the STEPBible spine's N/V/A head-POS
# (spine/common._CONTENT_POS) so the two spines' `is_content` — and every coverage number keyed
# off it — stay directly comparable. Widen here (e.g. add "adv") only deliberately, in lockstep.
_CONTENT_CLASSES = {"noun", "verb", "adj"}

# MACULA splits Hebrew prefix morphemes (ל/ב/כ = prep, ו = cj, ה-definite = art) into their own
# rows rather than fusing them onto the following word the way spine.db does — used by the
# superscription pass below to let these pass through classify_leading_run transparently.
_BOUND_MORPHEME_CLASSES = {"prep", "cj", "art"}

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


def build(in_path: Path, out_path: Path, spine_db_path: Path = SPINE_DB_DEFAULT) -> tuple[int, int]:
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
            is_superscription INTEGER NOT NULL DEFAULT 0,   -- Psalm title token — see spine.superscriptions
            PRIMARY KEY (book, chapter, verse, idx)
        );
        CREATE UNIQUE INDEX ix_ls_key ON spine_words(key);
        CREATE INDEX ix_ls_lexeme ON spine_words(lexeme);
        CREATE INDEX ix_ls_strong ON spine_words(strong);
        CREATE TABLE spine_meta (key TEXT PRIMARY KEY, value TEXT);
    """)

    # MACULA tokenizes finer than STEPBible: a pointed word is split into morpheme sub-tokens that
    # share `word` (e.g. וּמִלְמַעְלָה = 5 rows, word=1), ordered by the globally-unique `key`. So idx
    # is a running per-verse position in key order — one row per MACULA token — not `word`. This
    # idx scheme does NOT match spine.db's (different tokenization), so the two spines' rows can't
    # be joined directly — see the superscription pass below, which works around that.
    rows, content_rows, content_with_strong = [], 0, 0
    psa_verse1: dict[int, list[tuple[int, int | None, bool, int]]] = {}  # chapter -> [(idx, s_roll, is_bound, row_pos)]
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
        if book == "PSA" and v == 1:
            psa_verse1.setdefault(ch, []).append((idx, s_roll, cls in _BOUND_MORPHEME_CLASSES, len(rows)))
        rows.append((book, ch, v, idx, key, text, lexeme, s_roll, lemma, is_content,
                     "", gloss, role, stem or "",    # morph "" (kept empty; structured cols replace it)
                     person, number, gender, case_, tense, voice, mood, degree, state))

    # Psalm superscriptions: MACULA merges the title into verse 1 for EVERY titled psalm (unlike
    # UHB, which spine.db builds from and which separates ~64 of them into their own verse 0) — so
    # every titled chapter here goes through the leading-run classifier, using each chapter's own
    # EXACT, trustworthy vocabulary (all_chapter_vocab — spine.db's verse=0 ground truth for ~64
    # psalms, the committed BHSA-clause resource for the other ~52; no frequency-based guessing
    # anywhere). A chapter absent from this dict has no ground truth on either side and is simply
    # left unflagged, not guessed at.
    # MACULA also splits Hebrew prefixes (ל/ב/כ, ו, ה) into their own tokens with non-lexical
    # Strong's-like ids — classify_leading_run's is_bound_morpheme lets these pass through the run
    # transparently instead of breaking it, as long as the token right after is a real vocab hit.
    superscription = [0] * len(rows)
    chapter_vocab = all_chapter_vocab(spine_db_path)
    if chapter_vocab:
        for chapter, candidates in psa_verse1.items():
            vocab = chapter_vocab.get(chapter)
            if not vocab:
                continue
            flagged = classify_leading_run([(i, s, bound) for i, s, bound, _ in candidates], vocab)
            for i, _s, _bound, pos in candidates:
                if i in flagged:
                    superscription[pos] = 1

    db.executemany(
        "INSERT INTO spine_words VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [row + (flag,) for row, flag in zip(rows, superscription)],
    )

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
    ap.add_argument("--spine-db", type=Path, default=SPINE_DB_DEFAULT,
                     help="spine.db, for the Psalm-superscription vocabulary (optional — "
                          "is_superscription stays 0 everywhere if missing)")
    args = ap.parse_args()
    if not args.in_path.exists():
        sys.exit(f"missing input {args.in_path} — build it first: python -m macula.parse")

    n, (content, content_strong) = build(args.in_path, args.out, args.spine_db)
    out_sha = hashlib.sha256(args.out.read_bytes()).hexdigest()
    cov = 100 * content_strong / max(1, content)
    print(f"{n} tokens -> {args.out}")
    print(f"  content (N/V/A): {content}  with Strong's: {cov:.1f}%")
    if cov < 99:
        print(f"  ! content Strong's coverage {cov:.1f}% (<99%) — check the MACULA source", file=sys.stderr)
    with sqlite3.connect(f"file:{args.out}?mode=ro", uri=True) as con:
        n_super = con.execute("SELECT COUNT(*) FROM spine_words WHERE is_superscription=1").fetchone()[0]
    if n_super:
        print(f"  {n_super} Psalm superscription tokens flagged (from {args.spine_db})")
    elif args.spine_db.exists():
        print(f"  ! 0 superscription tokens flagged despite {args.spine_db} existing — check the pipeline", file=sys.stderr)
    else:
        print(f"  0 superscription tokens flagged — {args.spine_db} not found, run spine.parse first for this")
    print(f"  build sha256: {out_sha}")
    print("  → pin this sha256 in the consumer's data/PROVENANCE.txt (contract §1)")


if __name__ == "__main__":
    main()
