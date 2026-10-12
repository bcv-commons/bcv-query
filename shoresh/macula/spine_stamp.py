"""Content version of a spine DB, and the two Greek lexemes MACULA leaves without a Strong's number.

`spine_meta.macula_spine_sha256` pins the MACULA input, so it stays the same when one of our derived columns changes (is_superscription,
construct_role, ...). Consumers that pin a spine (the lexeme-aligner) need a key that changes with any row: `spine_content_sha256` is a
sha256 over the column names and every spine_words row in key order. It does not depend on the file's bytes (VACUUM, page layout).

MACULA Greek gives Strong's 0 to two lemmas that classic Strong's lacks (its Textus Receptus has neither word). They get STEPBible's
extended Strong's numbers (TBESG, Tyndale House, CC BY 4.0) so that they have a real lexeme id, like every other content word.

  python -m macula.spine_stamp macula/lexeme-spine-macula.db [more.db ...]     # fill the gaps (lexeme spines) and stamp
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import unicodedata
from pathlib import Path

# MACULA lemma (Greek, Strong's 0) -> extended Strong's from STEPBible TBESG
STRONG_GAPS = {"Ἀρνί": 6095,         # LUK 3:33, Arni (Ruth 4:19 Ram)
               "ἄμωμον": 6007}       # REV 18:13, amomum (a spice)
_GAPS = {unicodedata.normalize("NFC", k): v for k, v in STRONG_GAPS.items()}


def gap_strong(lang: str, strong: str | int | None, lemma: str | None) -> int | None:
    """The extended Strong's for a MACULA Greek token with Strong's 0, else None."""
    if lang != "grc" or str(strong or "0").strip("0") or not lemma:
        return None
    return _GAPS.get(unicodedata.normalize("NFC", lemma))


def fill_strong_gaps(db: sqlite3.Connection) -> int:
    """Give the Strong's-0 Greek tokens of a lexeme spine their extended number; returns rows changed."""
    cols = {r[1] for r in db.execute("PRAGMA table_info(spine_words)")}
    if "lexeme" not in cols:
        return 0
    n = 0
    for key, lemma in db.execute("SELECT key, lemma FROM spine_words WHERE lexeme IN ('grc:0', 'grc:')").fetchall():
        s = gap_strong("grc", 0, lemma)
        if s is not None:
            db.execute("UPDATE spine_words SET lexeme=?, strong=? WHERE key=?", (f"grc:{s}", s, key))
            n += 1
    return n


def content_sha256(db: sqlite3.Connection) -> str:
    cur = db.execute("SELECT * FROM spine_words ORDER BY key")
    h = hashlib.sha256(json.dumps([d[0] for d in cur.description]).encode())
    for row in cur:
        h.update(b"\n" + json.dumps(row, ensure_ascii=False).encode())
    return h.hexdigest()


def stamp(path: Path) -> dict:
    """Fill the Strong's gaps and write spine_meta.spine_content_sha256. Returns {'filled': n, 'spine_content_sha256': ...}."""
    with sqlite3.connect(path) as db:
        filled = fill_strong_gaps(db)
        digest = content_sha256(db)
        db.executemany("INSERT OR REPLACE INTO spine_meta(key, value) VALUES (?, ?)", [
            ("spine_content_sha256", digest),
            ("spine_content_rule", "sha256 over the spine_words column names and every row in key order (JSON); changes with any row or "
                                   "column, unlike macula_spine_sha256, which pins only the MACULA input"),
        ])
    return {"filled": filled, "spine_content_sha256": digest}


def main(argv: list[str]) -> int:
    for p in argv or ["macula/lexeme-spine-macula.db"]:
        r = stamp(Path(p))
        print(f"{p}: {r['filled']} Strong's gaps filled, spine_content_sha256 {r['spine_content_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
