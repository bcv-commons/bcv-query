"""Build `verse-senses.db`: per-occurrence senses for /verse, from the openly licensed `hebrew-word-senses` release (CC BY 4.0, MACULA lexemes,
no BHSA). Input: the release files (occurrences.parquet: key, book, chapter, verse, lexeme, sense; senses.tsv: lexeme, strong, lemma, sense, label,
count, share), by default the local export in macula/data/hf_cards/hebrew-word-senses/. Output: a small SQLite file the service reads:

  occ(key PRIMARY KEY, lexeme, sense)         one row per MACULA token that has a sense
  senses(lexeme, sense, label, n, share)      the sense inventory; /verse shows a label only for lexemes with more than one sense
  meta(key, value)                            provenance

  python -m macula.build_verse_senses [--src DIR] [--out macula/verse-senses.db]
Ship it to the service data volume with deploy/deploy-data.sh (host dir /opt/shoresh/data, container /data/verse-senses.db).
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "data" / "hf_cards" / "hebrew-word-senses"
OUT = HERE / "verse-senses.db"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def build(src: Path, out: Path) -> dict:
    import pyarrow.parquet as pq
    occ = pq.read_table(src / "occurrences.parquet").to_pydict()
    if out.exists():
        out.unlink()
    db = sqlite3.connect(out)
    db.executescript("""
        CREATE TABLE occ(key TEXT PRIMARY KEY, lexeme TEXT NOT NULL, sense INTEGER NOT NULL) WITHOUT ROWID;
        CREATE TABLE senses(lexeme TEXT NOT NULL, sense INTEGER NOT NULL, label TEXT NOT NULL, n INTEGER, share REAL, PRIMARY KEY(lexeme, sense)) WITHOUT ROWID;
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
    """)
    db.executemany("INSERT INTO occ VALUES (?,?,?)", zip(occ["key"], occ["lexeme"], occ["sense"]))
    n_sense = 0
    with (src / "senses.tsv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            db.execute("INSERT INTO senses VALUES (?,?,?,?,?)", (r["lexeme"], int(r["sense"]), r["label"], int(r["count"] or 0), float(r["share"] or 0)))
            n_sense += 1
    multi = db.execute("SELECT count(*) FROM (SELECT lexeme FROM senses GROUP BY lexeme HAVING count(*) > 1)").fetchone()[0]
    meta = {"dataset": "bcv-commons/hebrew-word-senses (https://huggingface.co/datasets/bcv-commons/hebrew-word-senses)", "license": "CC BY 4.0",
            "occurrences_sha256": sha(src / "occurrences.parquet"), "senses_sha256": sha(src / "senses.tsv"),
            "built": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "note": "no BHSA input; keyed on MACULA token keys"}
    db.executemany("INSERT INTO meta VALUES (?,?)", meta.items())
    db.commit()
    db.execute("VACUUM")
    db.close()
    return {"occurrences": len(occ["key"]), "senses": n_sense, "lexemes_with_several_senses": multi}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=SRC)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    stats = build(a.src, a.out)
    print(f"{stats} -> {a.out} ({a.out.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
