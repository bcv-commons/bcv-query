"""Per-verse binyan-correct senses — the OT linguistic core (hbo.db) joined to the curated,
multilingual sense labels (senses/hbo_lex.tsv). Powers the passage card's per-word sense, fixing
the stem-blind generic gloss (qadash niphal → "be shown holy", not a flat "consecrate").

hbo.db is Hebrew/OT only and shipped to the host as a data volume (HBO_DB_PATH; see
deploy/deploy-data.sh) — NOT in git. Best-effort: absent db / non-OT verse → empty, and the card
falls back to the /verse gloss. See internal-docs/passage-card-redesign.md.
"""
from __future__ import annotations

import functools
import os
import sqlite3

from resource_paths import resource_path


def _hbo_path() -> str:
    return os.environ.get("HBO_DB_PATH") or str(resource_path("occurrences/hbo.db"))


@functools.lru_cache(maxsize=1)
def _labels() -> dict:
    """(lex, stem, sense#) → curated multilingual sense label, from senses/hbo_lex.tsv."""
    out: dict = {}
    try:
        with open(resource_path("senses/hbo_lex.tsv"), encoding="utf-8") as f:
            next(f, None)                                   # header: lex stem sense gloss count share
            for line in f:
                c = line.rstrip("\n").split("\t")
                if len(c) >= 4:
                    out[(c[0], c[1], c[2])] = c[3]
    except Exception:
        pass
    return out


@functools.lru_cache(maxsize=1)
def _db():
    path = _hbo_path()
    if not os.path.exists(path):
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    except Exception:
        return None


@functools.lru_cache(maxsize=2048)
def verse_senses(bbcccvvv: int) -> dict:
    """{strong: binyan-correct sense label} for a verse's Hebrew words. Empty when the OT core is
    unavailable or the verse is non-OT (Greek). First occurrence of a strong wins."""
    db = _db()
    if db is None:
        return {}
    from indexer.references import decode
    try:
        code, ch, v = decode(bbcccvvv)
    except Exception:
        return {}
    labels = _labels()
    out: dict = {}
    try:
        rows = db.execute("SELECT strong, lex, stem, sense FROM occurrence "
                          "WHERE book=? AND chapter=? AND verse=?", (code, ch, v)).fetchall()
    except Exception:
        return {}
    for strong, lex, stem, sense in rows:
        if strong and strong not in out:
            label = labels.get((lex, stem or "", sense or ""))
            if label:
                out[strong] = label
    return out
