"""OpenBible Bible-Geocoding-Data ingest (CC-BY 4.0).

  python -m ingest.openbible_geocoding
  python -m ingest.openbible_geocoding --no-fetch

Pulls https://github.com/openbibleinfo/Bible-Geocoding-Data/tree/main/data
(`ancient.jsonl` + `modern.jsonl`) and overlays the data onto our existing
`entities` table:

* Where an OpenBible ancient place matches a Theographic-imported place
  by name + verse-overlap (and the match is unambiguous), we **enrich**
  the existing entity's `metadata` JSON in place — adding `latitude`,
  `longitude`, `place_types`, `modern_name`, `wikidata_id`, `name_variants`.
* Where there's no match (or multiple Theographic places share the
  name), we **insert** the OpenBible place as a fresh entity with id
  `place:openbible-<slug>`. Stage-3 disambiguation may merge these later.
* `entity_passages` rows are added in either case so passage-anchored
  retrievers see the new place.

Scope is places only (`type='place'`); OpenBible doesn't carry people
or events.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Iterable

import httpx

from indexer.build import init_schema
from indexer.db import open_db
from indexer.env import load_env
from indexer.references import BOOK_NUMBERS, encode

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "indexer" / "index.db"
DEFAULT_STAGING = REPO_ROOT / "ingest" / "_staging" / "openbible_geocoding"

BASE_URL = "https://raw.githubusercontent.com/openbibleinfo/Bible-Geocoding-Data/main/data"
FILES = ("ancient.jsonl", "modern.jsonl")

_OSIS_TO_USFM: dict[str, str] = {
    # Same mapping as ingest.naves_topical (CCEL/OSIS abbreviations).
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


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return s or "unknown"


def _osis_to_bb(osis: str) -> int | None:
    m = re.match(r"^([1-3]?[A-Za-z]+)\.(\d+)\.(\d+)$", osis.strip())
    if not m:
        return None
    usfm = _OSIS_TO_USFM.get(m.group(1))
    if usfm is None or usfm not in BOOK_NUMBERS:
        return None
    try:
        return encode(usfm, int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# ---------- fetch ----------

def fetch(staging: Path, *, timeout: float = 300.0) -> None:
    staging.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for fname in FILES:
            url = f"{BASE_URL}/{fname}"
            print(f"  fetch {fname}", flush=True)
            r = client.get(url)
            r.raise_for_status()
            (staging / fname).write_bytes(r.content)


# ---------- parse ----------

def _extract_lonlat(entry: dict) -> tuple[float, float] | None:
    """Walk identifications → resolutions to find the first usable lonlat string."""
    for ident in entry.get("identifications") or []:
        for res in ident.get("resolutions") or []:
            ll = res.get("lonlat")
            if isinstance(ll, str) and "," in ll:
                try:
                    lon, lat = (float(x) for x in ll.split(",", 1))
                    return lon, lat
                except ValueError:
                    continue
    return None


def _extract_wikidata(entry: dict) -> str | None:
    """linked_data['s7cc8b2'] holds Wikidata IDs ('Q765106') when present."""
    ld = entry.get("linked_data") or {}
    wd = ld.get("s7cc8b2") or {}
    val = wd.get("id")
    return val if isinstance(val, str) and val.startswith("Q") else None


def _modern_associations(entry: dict) -> list[dict]:
    out = []
    for mid, info in (entry.get("modern_associations") or {}).items():
        out.append({
            "id": mid,
            "name": info.get("name"),
            "score": info.get("score"),
            "url_slug": info.get("url_slug"),
        })
    return out


def parse_ancient(path: Path) -> list[dict]:
    """Yield place dicts ready for write-time matching."""
    out: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = (entry.get("friendly_id") or "").strip()
            if not name:
                continue
            types = entry.get("types") or []
            verses = []
            for v in entry.get("verses") or []:
                bb = _osis_to_bb(v.get("osis", ""))
                if bb is not None:
                    verses.append(bb)
            lonlat = _extract_lonlat(entry)
            wd = _extract_wikidata(entry)
            modern = _modern_associations(entry)
            translation_names = entry.get("translation_name_counts") or {}
            out.append({
                "name": name,
                "openbible_id": entry.get("id") or "",
                "types": types,
                "verses": verses,
                "lonlat": lonlat,
                "wikidata_id": wd,
                "modern_associations": modern,
                "name_variants": [
                    {"name": n, "count": c} for n, c in translation_names.items()
                ],
            })
    return out


# ---------- match + write ----------

def _name_normalize(s: str) -> str:
    """Lowercase + collapse whitespace + strip OpenBible's trailing
    disambiguator numbers ('Bethlehem 1' → 'bethlehem'). Theographic
    handles its own disambiguation via id suffix (bethlehem_218 vs
    bethlehem_219), so OpenBible's `<name> <N>` friendly-ids should
    fall back to verse-overlap matching against the Theographic peers."""
    s = re.sub(r"\s+\d+\s*$", "", s.strip())
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _build_theo_index(db) -> dict[str, list[str]]:
    """Index Theographic place entities by normalized name → list of entity ids."""
    rows = db.execute(
        "SELECT id, name FROM entities WHERE type = 'place' AND id LIKE 'place:%' AND id NOT LIKE 'place:openbible-%'"
    ).fetchall()
    out: dict[str, list[str]] = {}
    for eid, name in rows:
        out.setdefault(_name_normalize(name), []).append(eid)
    return out


def _theo_passages_for(db, entity_id: str) -> set[int]:
    rows = db.execute(
        "SELECT start_bbcccvvv FROM entity_passages WHERE entity_id = ?",
        (entity_id,),
    ).fetchall()
    return {r[0] for r in rows}


def write(db, places: list[dict]) -> dict:
    counts = {
        "openbible_total": len(places),
        "enriched_existing": 0,
        "inserted_new": 0,
        "ambiguous_match_inserted_new": 0,
        "passages_added": 0,
    }

    # Idempotent: re-runs replace OpenBible-attributed entities cleanly. We
    # leave Theographic entities in place; their metadata is updated below.
    db.execute("DELETE FROM entities WHERE id LIKE 'place:openbible-%'")
    db.commit()

    theo_by_name = _build_theo_index(db)

    for p in places:
        norm = _name_normalize(p["name"])
        candidates = theo_by_name.get(norm, [])
        target_id: str | None = None

        if len(candidates) == 1:
            target_id = candidates[0]
        elif len(candidates) > 1 and p["verses"]:
            # Multiple Theographic places share this name (e.g., 2 different
            # Bethlehems). Disambiguate by max verse-overlap.
            verse_set = set(p["verses"])
            best_id, best_overlap = None, 0
            for cid in candidates:
                tp = _theo_passages_for(db, cid)
                overlap = len(verse_set & tp)
                if overlap > best_overlap:
                    best_id, best_overlap = cid, overlap
            target_id = best_id  # may stay None if no overlap

        if target_id is not None:
            # Enrich existing Theographic entity.
            row = db.execute(
                "SELECT metadata FROM entities WHERE id = ?", (target_id,)
            ).fetchone()
            try:
                meta = json.loads(row[0]) if row and row[0] else {}
            except json.JSONDecodeError:
                meta = {}
            meta["openbible_id"] = p["openbible_id"]
            if p["lonlat"]:
                meta["latitude"] = p["lonlat"][1]
                meta["longitude"] = p["lonlat"][0]
            if p["types"]:
                meta["place_types"] = p["types"]
            if p["wikidata_id"]:
                meta["wikidata_id"] = p["wikidata_id"]
            if p["modern_associations"]:
                meta["modern_associations"] = p["modern_associations"]
            if p["name_variants"]:
                meta["name_variants"] = p["name_variants"]
            db.execute(
                "UPDATE entities SET metadata = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), target_id),
            )
            counts["enriched_existing"] += 1
            ent_id = target_id
        else:
            # Insert as new OpenBible-attributed place.
            ent_id = f"place:openbible-{_slug(p['name'])}"
            meta = {
                "openbible_id": p["openbible_id"],
                "place_types": p["types"] or None,
                "latitude": p["lonlat"][1] if p["lonlat"] else None,
                "longitude": p["lonlat"][0] if p["lonlat"] else None,
                "wikidata_id": p["wikidata_id"],
                "modern_associations": p["modern_associations"] or None,
                "name_variants": p["name_variants"] or None,
            }
            meta = {k: v for k, v in meta.items() if v not in (None, [], {})}
            db.execute(
                "INSERT OR REPLACE INTO entities(id, type, name, metadata) VALUES (?, ?, ?, ?)",
                (ent_id, "place", p["name"], json.dumps(meta, ensure_ascii=False)),
            )
            if len(candidates) > 1:
                counts["ambiguous_match_inserted_new"] += 1
            else:
                counts["inserted_new"] += 1

        # Always add passage refs (deduped by INSERT OR IGNORE on PK).
        if p["verses"]:
            db.executemany(
                "INSERT OR IGNORE INTO entity_passages(entity_id, start_bbcccvvv, end_bbcccvvv) "
                "VALUES (?, ?, ?)",
                [(ent_id, v, v) for v in p["verses"]],
            )
            counts["passages_added"] += len(p["verses"])

    db.commit()
    return counts


# ---------- CLI ----------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--no-fetch", action="store_true")
    args = ap.parse_args()
    load_env()

    if not args.no_fetch:
        print(f"fetching OpenBible → {args.staging}", flush=True)
        fetch(args.staging)

    ancient = args.staging / "ancient.jsonl"
    if not ancient.is_file():
        print(f"missing: {ancient}", file=sys.stderr)
        return 2

    print("parsing ancient.jsonl", flush=True)
    places = parse_ancient(ancient)

    started = time.time()
    db = open_db(args.db)
    init_schema(db)
    counts = write(db, places)
    db.close()

    print(json.dumps({
        "elapsed_seconds": round(time.time() - started, 2),
        **counts,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
