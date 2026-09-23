"""Enrich lexeme-spine.db's Hebrew rows from lowfat-hbo.db (macula.parse_lowfat_hbo). Answers the
still-open items in the 2026-09-23 aligner wishlist -- see parse_lowfat_hbo.py's docstring for the
full reasoning; this module only joins that already-extracted data onto the published spine.

Additive only, by design: `head_idx`, `phrase_role`, `construct_group` are new NULLABLE columns on
the EXISTING spine_words rows (ALTER TABLE ADD COLUMN -- no row deleted, no idx/PK touched). The
assimilated article (#10) is NOT spliced into spine_words as a new row -- (book,chapter,verse,idx)
is a published, pinned join key (data-contracts.md); inserting a row would shift idx for every
downstream token in an affected verse, breaking that contract for a zero-width token. Instead it's
a new, clearly-separate table, `spine_assimilated_articles`, pointing at the idx it attaches after.

Verified end to end on the confirmed example: Joshua 1:14 word 5 ("in the land") -- see the
docstring in parse_lowfat_hbo.py and this module's own printed spot-check.

  python -m macula.enrich_spine_lowfat                    # lexeme-spine.db in place
  python -m macula.enrich_spine_lowfat --spine PATH --lowfat PATH
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPINE_DEFAULT = HERE / "lexeme-spine.db"
LOWFAT_DEFAULT = HERE / "lowfat-hbo.db"


def _add_columns(db: sqlite3.Connection) -> None:
    existing = {r[1] for r in db.execute("PRAGMA table_info(spine_words)")}
    for col in ("head_idx", "phrase_role", "construct_group"):
        if col not in existing:
            coltype = "INTEGER" if col == "head_idx" else "TEXT"
            db.execute(f"ALTER TABLE spine_words ADD COLUMN {col} {coltype}")
    db.execute("""
        CREATE TABLE IF NOT EXISTS spine_assimilated_articles (
            book TEXT NOT NULL, chapter INTEGER NOT NULL, verse INTEGER NOT NULL,
            after_idx INTEGER NOT NULL,   -- attaches immediately after this spine_words.idx
                                           -- (same book/chapter/verse) -- does NOT get its own idx
            lemma TEXT, gloss TEXT, strong TEXT,
            PRIMARY KEY (book, chapter, verse, after_idx)
        )
    """)
    db.commit()


def enrich(spine_path: Path, lowfat_path: Path) -> dict:
    db = sqlite3.connect(spine_path)
    lf = sqlite3.connect(f"file:{lowfat_path}?mode=ro", uri=True)
    _add_columns(db)

    # key -> idx, per (book,chapter,verse), needed both to resolve head_idx (a key -> idx lookup)
    # and to place the assimilated-article rows (their neighboring real token's idx).
    key_to_idx: dict[str, tuple[str, int, int, int]] = {}
    for book, chapter, verse, idx, key in db.execute(
        "SELECT book, chapter, verse, idx, key FROM spine_words WHERE lexeme LIKE 'hbo:%'"
    ):
        key_to_idx[key] = (book, chapter, verse, idx)

    n_role = n_head = n_cg = n_head_unresolved = 0
    for key, head_key, phrase_role, construct_group in lf.execute(
        "SELECT key, head_key, phrase_role, construct_group FROM lowfat_words WHERE is_inserted=0"
    ):
        if key not in key_to_idx:
            continue  # shouldn't happen (word-count parity verified 0 mismatched books), but never fail on it
        head_idx = None
        if head_key is not None:
            resolved = key_to_idx.get(head_key)
            if resolved:
                head_idx = resolved[3]
            else:
                n_head_unresolved += 1
        db.execute(
            "UPDATE spine_words SET head_idx=?, phrase_role=?, construct_group=? WHERE key=?",
            (head_idx, phrase_role, construct_group, key),
        )
        n_head += head_idx is not None
        n_role += phrase_role is not None
        n_cg += construct_group is not None
    db.commit()

    # Assimilated articles: attach after the nearest PRECEDING real token in the same verse, by
    # lowfat's own document order (`seq`), which already interleaves inserted rows correctly.
    n_articles = 0
    for book, chapter, verse in lf.execute(
        "SELECT DISTINCT book, chapter, verse FROM lowfat_words WHERE is_inserted=1"
    ):
        rows = lf.execute(
            "SELECT seq, is_inserted, key, lemma, class, strong "
            "FROM lowfat_words WHERE book=? AND chapter=? AND verse=? ORDER BY seq",
            (book, chapter, verse),
        ).fetchall()
        prev_idx = None
        for seq, is_inserted, key, lemma, cls, strong in rows:
            if not is_inserted:
                resolved = key_to_idx.get(key)
                prev_idx = resolved[3] if resolved else prev_idx
                continue
            if prev_idx is None:
                continue  # an assimilated article can't be the verse's very first token; not observed
            db.execute(
                "INSERT OR REPLACE INTO spine_assimilated_articles "
                "(book, chapter, verse, after_idx, lemma, gloss, strong) VALUES (?,?,?,?,?,?,?)",
                (book, chapter, verse, prev_idx, lemma, "the", strong),
            )
            n_articles += 1
    db.commit()
    db.close()
    return {"head_idx_set": n_head, "head_idx_unresolved": n_head_unresolved,
            "phrase_role_set": n_role, "construct_group_set": n_cg,
            "assimilated_articles": n_articles}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spine", type=Path, default=SPINE_DEFAULT)
    ap.add_argument("--lowfat", type=Path, default=LOWFAT_DEFAULT)
    args = ap.parse_args()

    if not args.lowfat.exists():
        sys.exit(f"missing {args.lowfat} -- run `python -m macula.parse_lowfat_hbo` first")
    stats = enrich(args.spine, args.lowfat)
    print(f"head_idx: {stats['head_idx_set']} set ({stats['head_idx_unresolved']} unresolved)")
    print(f"phrase_role: {stats['phrase_role_set']} set")
    print(f"construct_group: {stats['construct_group_set']} set")
    print(f"assimilated articles: {stats['assimilated_articles']} rows in spine_assimilated_articles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
