#!/usr/bin/env python3
"""Rebuild every FTS5 partition from the current `chunks` table.

The corruption-safe FTS refresh: each partition is wiped with 'delete-all'
(one command, not per-row deletes) then repopulated with a single
INSERT-FROM-SELECT. This is exactly what `indexer.build` does at the end of a
build; we expose it standalone so the hybrid incremental-deploy path can refresh
FTS after import_delta.py without re-running a full build.

Runs inside the bcv-rag image:  PYTHONPATH=/app python rebuild_fts.py --db /data/index.db.work

⚠️  KEEP IN SYNC WITH indexer/build.py. The routing below mirrors the
`V3_KIND_TO_FTS` map + the aquifer/main exclusion logic there. If build.py adds
a new per-kind FTS partition, add it here too. (Future cleanup: extract build's
FTS block into a shared `indexer.fts.repopulate(db)` and call it from both —
deferred to avoid touching the proven build path before a deploy.)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app")
try:
    from indexer.db import open_db
except ImportError:                  # local repo run (parents[2] = bcv-RAG root)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from indexer.db import open_db

# Mirror of indexer/build.py:V3_KIND_TO_FTS
V3_KIND_TO_FTS = {
    "kind:lexicon":          "chunks_fts_lexicon",
    "kind:morphology":       "chunks_fts_morphology",
    "kind:bible":            "chunks_fts_bible",
    "kind:section-heading":  "chunks_fts_section_heading",
    "kind:video-transcript": "chunks_fts_video_transcript",
}
AQUIFER_FTS = "chunks_fts_aquifer"
AQUIFER_TAG = "resource:aquifer"


def repopulate(db) -> dict:
    t = {}
    # Per-kind partitions: each carries only chunks of one kind.
    for kind_tag, fts in V3_KIND_TO_FTS.items():
        t0 = time.time()
        db.execute(f"INSERT INTO {fts}({fts}) VALUES('delete-all')")
        db.execute(
            f"INSERT INTO {fts}(rowid, body) "
            f"SELECT chunks.rowid, chunks.body FROM chunks "
            f"JOIN tags ON tags.doc_id = chunks.doc_id WHERE tags.tag = ?",
            (kind_tag,),
        )
        t[fts] = round(time.time() - t0, 1)

    # Aquifer partition: isolated by resource, not kind.
    t0 = time.time()
    db.execute(f"INSERT INTO {AQUIFER_FTS}({AQUIFER_FTS}) VALUES('delete-all')")
    db.execute(
        f"INSERT INTO {AQUIFER_FTS}(rowid, body) "
        f"SELECT chunks.rowid, chunks.body FROM chunks "
        f"JOIN tags ON tags.doc_id = chunks.doc_id WHERE tags.tag = '{AQUIFER_TAG}'"
    )
    t[AQUIFER_FTS] = round(time.time() - t0, 1)

    # Main chunks_fts: everything NOT routed into a v3 partition or aquifer.
    t0 = time.time()
    v3 = list(V3_KIND_TO_FTS.keys())
    ph = ",".join("?" * len(v3))
    db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('delete-all')")
    db.execute(
        "INSERT INTO chunks_fts(rowid, body) "
        "SELECT chunks.rowid, chunks.body FROM chunks "
        "WHERE chunks.doc_id NOT IN ("
        f"  SELECT DISTINCT doc_id FROM tags WHERE tag IN ({ph}) OR tag = '{AQUIFER_TAG}'"
        ")",
        v3,
    )
    t["chunks_fts"] = round(time.time() - t0, 1)
    return t


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    args = ap.parse_args()

    db = open_db(Path(args.db))
    timings = repopulate(db)
    db.commit()

    chk = db.execute("PRAGMA quick_check").fetchone()[0]
    db.close()
    print("FTS rebuild timings (s):", timings)
    print(f"quick_check: {chk}")
    return 0 if chk == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
