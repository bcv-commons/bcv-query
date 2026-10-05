"""Write a MACULA-only copy of lexeme-spine.db for the lexeme-aligner: no BHSA-derived columns.

BHSA (ETCBC) is CC BY-NC-SA 4.0, and the aligner publishes its outputs as CC0. Six spine columns come
from BHSA and are dropped here:
  phrase_id, function, rela   -- BHSA phrase-level syntax (via the BHSA<->MACULA bridge)
  sense, sense_conf, sense_source -- our sense clustering, built on BHSA clauses
Everything else is MACULA (CC BY 4.0). Added: `construct_role` (regens / rectum / regens+rectum) from the
lowfat tree's NPofNP groups, the MACULA-only stand-in for BHSA `rela='rec'`.

The full lexeme-spine.db is left untouched; the aligner keeps it as a private, unpublished baseline.

  python -m macula.parse_lowfat_hbo            # lowfat-hbo.db with construct_role
  python -m macula.export_spine_macula_only    # -> lexeme-spine-macula.db, prints its sha256
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sqlite3
import sys
from pathlib import Path

from macula.enrich_spine_lowfat import LOWFAT_DEFAULT, SPINE_DEFAULT, enrich

HERE = Path(__file__).resolve().parent
OUT_DEFAULT = HERE / "lexeme-spine-macula.db"
BHSA_COLUMNS = ("phrase_id", "function", "rela", "sense", "sense_conf", "sense_source")


def export(spine: Path, lowfat: Path, out: Path) -> dict:
    out.unlink(missing_ok=True)
    shutil.copyfile(spine, out)
    stats = enrich(out, lowfat)
    db = sqlite3.connect(out)
    present = {r[1] for r in db.execute("PRAGMA table_info(spine_words)")}
    for col in BHSA_COLUMNS:
        if col in present:
            db.execute(f"ALTER TABLE spine_words DROP COLUMN {col}")
    db.executemany("INSERT OR REPLACE INTO spine_meta(key, value) VALUES (?, ?)", [
        ("variant", "macula-only: no BHSA-derived columns (" + ", ".join(BHSA_COLUMNS) + ")"),
        ("license", "CC BY 4.0 (MACULA Hebrew/Greek, Clear Bible)"),
    ])
    from macula.spine_versification import declaration    # the spine's own verse numbering
    db.executemany("INSERT OR REPLACE INTO spine_meta(key, value) VALUES (?, ?)",
                   list(declaration(db, "nestle1904").items()))
    db.commit()
    db.execute("VACUUM")
    db.close()
    stats["construct_role_set"] = sqlite3.connect(f"file:{out}?mode=ro", uri=True).execute(
        "SELECT COUNT(*) FROM spine_words WHERE construct_role IS NOT NULL").fetchone()[0]
    stats["sha256"] = hashlib.sha256(out.read_bytes()).hexdigest()
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spine", type=Path, default=SPINE_DEFAULT)
    ap.add_argument("--lowfat", type=Path, default=LOWFAT_DEFAULT)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = ap.parse_args()
    if "construct_role" not in {r[1] for r in sqlite3.connect(f"file:{args.lowfat}?mode=ro", uri=True)
                                .execute("PRAGMA table_info(lowfat_words)")}:
        sys.exit(f"{args.lowfat} has no construct_role -- rebuild it with `python -m macula.parse_lowfat_hbo`")
    stats = export(args.spine, args.lowfat, args.out)
    print(f"construct_role: {stats['construct_role_set']} set; dropped {', '.join(BHSA_COLUMNS)}")
    print(f"-> {args.out}\nsha256 {stats['sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
