"""BHSA clause-level dependency graph -- ingest.

Writes resources/bhsa_hierarchy/clause_mother.tsv (shoresh/macula/build_hierarchy_relations.py) into
clause_dependencies (indexer/schema.sql). Text and BBCCCVVV addressing are precomputed in that TSV
(shoresh has live BHSA/cfabric access; bcv-RAG doesn't and has no other use for it) -- this ingest is
a pure load, no BHSA/text-fabric dependency here.

  python -m ingest.clause_dependencies              # read the shared resources/ TSV, write to index.db
  python -m ingest.clause_dependencies --reset       # delete existing rows first

Deviation from the standard ingest pattern
-------------------------------------------
Same reasoning as ingest/theographic.py and ingest/torah_weave.py: graph data, not chunk-shaped
text, written straight into dedicated tables.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from indexer.build import init_schema
from indexer.db import open_db
from indexer.env import load_env
from resource_paths import resource_path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "indexer" / "index.db"
DEFAULT_SRC = resource_path("bhsa_hierarchy/clause_mother.tsv")


def parse_rows(path: Path) -> list[tuple]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("dependent_node"):
                continue
            parts = line.rstrip("\n").split("\t")
            (dep_node, _dep_ref, dep_start, dep_end, dep_text,
             mom_node, mom_otype, _mom_ref, mom_start, mom_end, mom_text, rela) = parts
            rows.append((
                int(dep_node), int(dep_start), int(dep_end), dep_text,
                int(mom_node), mom_otype, int(mom_start), int(mom_end), mom_text, rela,
            ))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--reset", action="store_true", help="delete existing rows before ingest")
    args = ap.parse_args()

    load_env()

    if not args.src.is_file():
        print(f"missing {args.src} -- run `python -m macula.build_hierarchy_relations` "
              f"in shoresh/ first", file=sys.stderr)
        return 2

    rows = parse_rows(args.src)
    print(f"  parsed: {len(rows)} clause-dependency rows", file=sys.stderr)

    db = open_db(args.db)
    init_schema(db)  # CREATE ... IF NOT EXISTS throughout -- cheap to re-run

    if args.reset:
        db.execute("DELETE FROM clause_dependencies")
        db.commit()

    started = time.time()
    db.executemany(
        "INSERT OR REPLACE INTO clause_dependencies "
        "(dependent_node, dependent_start_bbcccvvv, dependent_end_bbcccvvv, dependent_text, "
        " mother_node, mother_otype, mother_start_bbcccvvv, mother_end_bbcccvvv, mother_text, rela) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
               ("clause_dependencies_indexed_at", str(int(time.time()))))
    db.commit()
    elapsed = time.time() - started
    db.close()

    print(f"  wrote {len(rows)} rows in {elapsed:.2f}s -> {args.db}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
