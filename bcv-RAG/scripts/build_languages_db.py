#!/usr/bin/env python3
"""Phase C of languages.db — compile the registry TSVs into an indexed SQLite DB.

The flat TSVs (resources/languages/{languages,related,code_alias}.tsv) stay the git-tracked
source of truth; this builds the fast indexed lookup (resources/languages/languages.db,
git-ignored + re-derivable — same "TSV source → built .db" pattern as spine.db / lxx.db).

  python -m scripts.build_languages_db
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "resources" / "languages"
DB = SRC / "languages.db"


def _rows(name: str) -> list[dict]:
    with (SRC / name).open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def build() -> None:
    if not (SRC / "languages.tsv").exists():
        sys.exit("resources/languages/languages.tsv missing — run build_languages_registry first")

    DB.unlink(missing_ok=True)
    db = sqlite3.connect(DB)
    db.executescript("""
        CREATE TABLE language(
            iso639_3 TEXT PRIMARY KEY, iso639_1 TEXT, name TEXT, glottocode TEXT,
            stock TEXT, group_ TEXT, branch TEXT, scripts TEXT, macrolanguage TEXT,
            classification TEXT);
        CREATE TABLE relatedness(
            iso639_3 TEXT, related_iso639_3 TEXT, rank INTEGER, distance REAL, basis TEXT);
        CREATE TABLE code_alias(old_code TEXT PRIMARY KEY, current_code TEXT);
    """)

    langs = _rows("languages.tsv")
    db.executemany(
        "INSERT INTO language VALUES(?,?,?,?,?,?,?,?,?,?)",
        [(r["iso639_3"], r["iso639_1"], r["name"], r["glottocode"], r["stock"],
          r["group"], r["branch"], r["scripts"], r["macrolanguage"],
          r.get("classification", "")) for r in langs])

    rel = _rows("related.tsv") if (SRC / "related.tsv").exists() else []
    db.executemany(
        "INSERT INTO relatedness VALUES(?,?,?,?,?)",
        [(r["iso639_3"], r["related_iso639_3"], int(r["rank"]), float(r["distance"]),
          r["basis"]) for r in rel])

    alias = _rows("code_alias.tsv") if (SRC / "code_alias.tsv").exists() else []
    db.executemany("INSERT INTO code_alias VALUES(?,?)",
                   [(r["old_code"], r["current_code"]) for r in alias])

    db.executescript("""
        CREATE INDEX rel_by_code ON relatedness(iso639_3, rank);
        CREATE INDEX lang_by_1 ON language(iso639_1);
        CREATE INDEX lang_by_macro ON language(macrolanguage);
    """)
    db.commit()
    db.close()
    print(f"languages.db: {len(langs)} languages, {len(rel)} relatedness edges, "
          f"{len(alias)} code aliases", file=sys.stderr)


if __name__ == "__main__":
    build()
    raise SystemExit(0)
