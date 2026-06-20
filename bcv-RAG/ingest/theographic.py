"""Theographic Bible Metadata ingest.

Pulls 4 CSV files from github.com/robertrouse/theographic-bible-metadata
and writes them into our entities + entity_relations + entity_passages
tables.

  python -m ingest.theographic
  python -m ingest.theographic --no-fetch    # use already-staged CSVs
  python -m ingest.theographic --reset       # delete existing rows first

Deviation from the standard ingest pattern
------------------------------------------
Other ingest modules (door43, aquifer) write per-row markdown files to
`ingest/_staging/<source>/` and let `indexer.build` parse them via the
MarkdownAdapter into chunks. This module instead writes directly into
the index DB because graph data is not chunk-shaped — there is no
text-body intermediate that markdown could carry. CSVs are still staged
under `ingest/_staging/theographic/` so re-runs are inspectable and
offline-resumable.

Upstream license
----------------
github.com/robertrouse/theographic-bible-metadata. Verify the upstream
LICENSE file before redistributing the derived index. As of writing,
content is generally available under permissive terms but the project
README is the source of truth.

Output
------
Tables populated (idempotent — INSERT OR REPLACE):

  entities          (id, type, name, metadata)
                    type ∈ {person, place, event}
                    id format: '<type>:<personLookup|placeLookup|eventID>'
  entity_relations  (source_id, target_id, relation, metadata)
                    relations: father-of, mother-of, partner-of, sibling-of,
                               participates-in (person→event),
                               occurred-at (event→place)
  entity_passages   (entity_id, start_bbcccvvv, end_bbcccvvv)
                    each verse mention encoded into the standard BBCCCVVV
                    integer used elsewhere in the schema.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Iterable, Iterator

import httpx

from indexer.build import init_schema
from indexer.db import open_db
from indexer.env import load_env
from indexer.references import BOOK_NUMBERS, encode

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "indexer" / "index.db"
DEFAULT_STAGING = REPO_ROOT / "ingest" / "_staging" / "theographic"

RAW_BASE = "https://raw.githubusercontent.com/robertrouse/theographic-bible-metadata/master/CSV"
FILES = ("People.csv", "Places.csv", "Events.csv", "PeopleGroups.csv")

# Theographic verse refs use SBL-style book abbreviations.
# Mapping is local to this module — the rest of the codebase uses USFM
# 3-letter codes (BOOK_NUMBERS keys). Cases match Theographic exactly so
# the lookup is a single string compare.
_THEOGRAPHIC_TO_USFM: dict[str, str] = {
    "Gen": "GEN", "Exod": "EXO", "Lev": "LEV", "Num": "NUM", "Deut": "DEU",
    "Josh": "JOS", "Judg": "JDG", "Ruth": "RUT", "1Sam": "1SA", "2Sam": "2SA",
    "1Kgs": "1KI", "2Kgs": "2KI", "1Chr": "1CH", "2Chr": "2CH",
    "Ezra": "EZR", "Neh": "NEH", "Esth": "EST", "Job": "JOB",
    "Ps": "PSA", "Prov": "PRO", "Eccl": "ECC", "Song": "SNG",
    "Isa": "ISA", "Jer": "JER", "Lam": "LAM", "Ezek": "EZK", "Dan": "DAN",
    "Hos": "HOS", "Joel": "JOL", "Amos": "AMO", "Obad": "OBA",
    "Jonah": "JON", "Mic": "MIC", "Nah": "NAM", "Hab": "HAB", "Zeph": "ZEP",
    "Hag": "HAG", "Zech": "ZEC", "Mal": "MAL",
    "Matt": "MAT", "Mark": "MRK", "Luke": "LUK", "John": "JHN", "Acts": "ACT",
    "Rom": "ROM", "1Cor": "1CO", "2Cor": "2CO", "Gal": "GAL", "Eph": "EPH",
    "Phil": "PHP", "Col": "COL", "1Thess": "1TH", "2Thess": "2TH",
    "1Tim": "1TI", "2Tim": "2TI", "Titus": "TIT", "Phlm": "PHM",
    "Heb": "HEB", "Jas": "JAS", "1Pet": "1PE", "2Pet": "2PE",
    "1John": "1JN", "2John": "2JN", "3John": "3JN", "Jude": "JUD", "Rev": "REV",
}


# ---------- helpers ----------

def _split_csv_field(value: str | None) -> list[str]:
    """Theographic CSVs use comma-separated values inside columns. Empty → []."""
    if not value:
        return []
    return [s.strip() for s in value.split(",") if s.strip()]


def _maybe_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value.replace(",", ""))
    except ValueError:
        return None


def _maybe_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _verse_ref_to_bbcccvvv(ref: str) -> int | None:
    """Convert 'Gen.1.1' → 1001001. Returns None on unknown book or malformed input."""
    parts = ref.strip().split(".")
    if len(parts) != 3:
        return None
    book, chap, verse = parts
    usfm = _THEOGRAPHIC_TO_USFM.get(book)
    if usfm is None:
        return None
    try:
        return encode(usfm, int(chap), int(verse))
    except ValueError:
        return None


# ---------- fetch ----------

def fetch(staging: Path, *, timeout: float = 30.0) -> None:
    staging.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for fname in FILES:
            url = f"{RAW_BASE}/{fname}"
            dest = staging / fname
            print(f"  fetch {fname}", flush=True)
            r = client.get(url)
            r.raise_for_status()
            dest.write_bytes(r.content)


# ---------- parsers ----------

def _read_csv(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f)


def parse_people(staging: Path) -> tuple[list[tuple], list[tuple], list[tuple]]:
    """Return (entity_rows, family_edges, verse_mentions)."""
    entities: list[tuple] = []
    edges: list[tuple] = []
    mentions: list[tuple] = []

    for row in _read_csv(staging / "People.csv"):
        pid = row.get("personLookup", "").strip()
        if not pid:
            continue
        eid = f"person:{pid}"
        name = (row.get("name") or row.get("displayTitle") or pid).strip()
        meta = {
            "alsoCalled": _split_csv_field(row.get("alsoCalled")),
            "gender": row.get("gender") or None,
            "birthYear": _maybe_int(row.get("birthYear")),
            "deathYear": _maybe_int(row.get("deathYear")),
            "birthPlace": (
                f"place:{row['birthPlace'].strip()}" if row.get("birthPlace") else None
            ),
            "deathPlace": (
                f"place:{row['deathPlace'].strip()}" if row.get("deathPlace") else None
            ),
            "description": (row.get("dictText") or "").strip() or None,
        }
        meta = {k: v for k, v in meta.items() if v not in (None, [], "")}
        entities.append((eid, "person", name, json.dumps(meta, ensure_ascii=False)))

        # Family edges
        for fid in _split_csv_field(row.get("father")):
            edges.append((f"person:{fid}", eid, "father-of", "{}"))
        for mid in _split_csv_field(row.get("mother")):
            edges.append((f"person:{mid}", eid, "mother-of", "{}"))
        for sid in _split_csv_field(row.get("partners")):
            edges.append((eid, f"person:{sid}", "partner-of", "{}"))
        # Siblings stored one direction only (lex-min source) to dedupe.
        for sid in _split_csv_field(row.get("siblings")):
            sib = f"person:{sid}"
            if eid < sib:
                edges.append((eid, sib, "sibling-of", "{}"))

        # Verse mentions
        for ref in _split_csv_field(row.get("verses")):
            bb = _verse_ref_to_bbcccvvv(ref)
            if bb is not None:
                mentions.append((eid, bb, bb))

    return entities, edges, mentions


def parse_places(staging: Path) -> tuple[list[tuple], list[tuple]]:
    """Return (entity_rows, verse_mentions)."""
    entities: list[tuple] = []
    mentions: list[tuple] = []

    for row in _read_csv(staging / "Places.csv"):
        pid = row.get("placeLookup", "").strip()
        if not pid:
            continue
        eid = f"place:{pid}"
        name = (row.get("displayTitle") or row.get("kjvName") or pid).strip()
        meta = {
            "latitude": _maybe_float(row.get("openBibleLat") or row.get("latitude")),
            "longitude": _maybe_float(row.get("openBibleLong") or row.get("longitude")),
            "featureType": row.get("featureType") or None,
        }
        meta = {k: v for k, v in meta.items() if v is not None}
        entities.append((eid, "place", name, json.dumps(meta, ensure_ascii=False)))

        for ref in _split_csv_field(row.get("verses")):
            bb = _verse_ref_to_bbcccvvv(ref)
            if bb is not None:
                mentions.append((eid, bb, bb))

    return entities, mentions


def parse_events(
    staging: Path,
) -> tuple[list[tuple], list[tuple], list[tuple], list[tuple]]:
    """Return (entity_rows, person_event_edges, event_place_edges, verse_mentions)."""
    entities: list[tuple] = []
    pe_edges: list[tuple] = []
    ep_edges: list[tuple] = []
    mentions: list[tuple] = []

    for row in _read_csv(staging / "Events.csv"):
        eid_raw = (row.get("eventID") or "").strip()
        if not eid_raw:
            continue
        eid = f"event:{eid_raw}"
        title = (row.get("title") or eid_raw).strip()
        meta = {
            "startYear": _maybe_int(row.get("startDate")),
            "duration": row.get("duration") or None,
            "sortKey": _maybe_float(row.get("sortKey")),
        }
        meta = {k: v for k, v in meta.items() if v is not None}
        entities.append((eid, "event", title, json.dumps(meta, ensure_ascii=False)))

        for pid in _split_csv_field(row.get("participants")):
            pe_edges.append((f"person:{pid}", eid, "participates-in", "{}"))
        for plid in _split_csv_field(row.get("locations")):
            ep_edges.append((eid, f"place:{plid}", "occurred-at", "{}"))
        for ref in _split_csv_field(row.get("verses")):
            bb = _verse_ref_to_bbcccvvv(ref)
            if bb is not None:
                mentions.append((eid, bb, bb))

    return entities, pe_edges, ep_edges, mentions


# ---------- write ----------

def _write(db, entities: Iterable[tuple], relations: Iterable[tuple], passages: Iterable[tuple]) -> dict:
    counts = {"entities": 0, "relations": 0, "passages": 0, "skipped_relations": 0}

    # Entities first — relations FK to entities.id, so insert order matters.
    for row in entities:
        db.execute(
            "INSERT OR REPLACE INTO entities(id, type, name, metadata) VALUES (?, ?, ?, ?)",
            row,
        )
        counts["entities"] += 1

    # Build entity-id set so we can drop dangling relation rows (stable
    # validation rather than letting the FK error abort the whole run).
    known: set[str] = {r[0] for r in db.execute("SELECT id FROM entities")}

    for src, tgt, rel, meta in relations:
        if src not in known or tgt not in known:
            counts["skipped_relations"] += 1
            continue
        db.execute(
            "INSERT OR REPLACE INTO entity_relations(source_id, target_id, relation, metadata) "
            "VALUES (?, ?, ?, ?)",
            (src, tgt, rel, meta),
        )
        counts["relations"] += 1

    for ent_id, s, e in passages:
        if ent_id not in known:
            continue
        db.execute(
            "INSERT OR IGNORE INTO entity_passages(entity_id, start_bbcccvvv, end_bbcccvvv) "
            "VALUES (?, ?, ?)",
            (ent_id, s, e),
        )
        counts["passages"] += 1

    db.commit()
    return counts


# ---------- CLI ----------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--no-fetch", action="store_true", help="use already-staged CSVs; skip download")
    ap.add_argument("--reset", action="store_true", help="delete theographic rows before ingest")
    args = ap.parse_args()

    load_env()

    if not args.no_fetch:
        print(f"fetching theographic CSVs → {args.staging}", flush=True)
        fetch(args.staging)

    missing = [f for f in FILES if not (args.staging / f).is_file()]
    if missing:
        print(f"missing staged files: {missing}", file=sys.stderr)
        return 2

    print("parsing CSVs", flush=True)
    p_ents, fam, p_mentions = parse_people(args.staging)
    pl_ents, pl_mentions = parse_places(args.staging)
    e_ents, pe_edges, ep_edges, e_mentions = parse_events(args.staging)

    entities = p_ents + pl_ents + e_ents
    relations = fam + pe_edges + ep_edges
    passages = p_mentions + pl_mentions + e_mentions

    print(f"  parsed: {len(entities)} entities, {len(relations)} relations, {len(passages)} passage refs",
          flush=True)

    db = open_db(args.db)
    # Ensure schema exists in case this module runs before `indexer.build`.
    # init_schema is `CREATE … IF NOT EXISTS` throughout, so cheap to re-run.
    init_schema(db)

    if args.reset:
        # entity_relations + entity_passages cascade via FK ON DELETE CASCADE.
        db.execute(
            "DELETE FROM entities "
            "WHERE id LIKE 'person:%' OR id LIKE 'place:%' OR id LIKE 'event:%'"
        )
        db.commit()

    started = time.time()
    counts = _write(db, entities, relations, passages)
    elapsed = time.time() - started

    db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
               ("theographic_indexed_at", str(int(time.time()))))
    db.commit()
    db.close()

    print(json.dumps({
        "elapsed_seconds": round(elapsed, 2),
        **counts,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
