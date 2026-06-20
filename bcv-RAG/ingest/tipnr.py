"""STEPBible TIPNR (Translators' Individualised Proper Names with all
References) ingest. CC-BY 4.0.

  python -m ingest.tipnr
  python -m ingest.tipnr --no-fetch

TIPNR is the proper-name disambiguation companion to STEPBible's
tagged-text data. Each person, place, and "other" entity is keyed by
a unique `<Name>@<First.Mention>` identifier (e.g. `Aaron@Exo.4.14`),
which lets TIPNR distinguish things Theographic conflates (six different
Marys, four Jameses, multiple Bethlehems with overlapping references).

This module overlays TIPNR onto our existing Theographic-imported
`entities` table:

* For each TIPNR person/place, find a matching Theographic entity by
  name + verse-overlap. If a unique high-confidence match exists,
  **enrich** the Theographic entity's `metadata` with TIPNR fields
  (tipnr_unique_name, extended_strongs, hebrew_greek, translations).
* If multiple candidates and verse-overlap can't decide,
  **insert** the TIPNR entity as new with id `<type>:tipnr-<slug>`.
* If no match, **insert** as new TIPNR-attributed entity.

Source: https://github.com/robertrouse/STEPBible-Data/tree/master/json
Files: TIPNR_people.json, TIPNR_places.json, TIPNR_other.json (BOM-prefixed UTF-8).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx

from indexer.build import init_schema
from indexer.db import open_db
from indexer.env import load_env
from indexer.references import BOOK_NUMBERS, encode

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "indexer" / "index.db"
DEFAULT_STAGING = REPO_ROOT / "ingest" / "_staging" / "tipnr"

BASE_URL = "https://raw.githubusercontent.com/robertrouse/STEPBible-Data/master/json"
FILES = ("TIPNR_people.json", "TIPNR_places.json", "TIPNR_other.json")

# OSIS book code mapping. SBL/OSIS-style 3-letter codes (Gen, Exod, …, Jhn).
# TIPNR uses these in references (e.g., "Exo.4.14"); our schema uses USFM
# (EXO, …, JHN). Reuse the same mapping as ingest.naves_topical &
# ingest.openbible_geocoding.
_OSIS_TO_USFM: dict[str, str] = {
    "Gen": "GEN", "Exo": "EXO", "Lev": "LEV", "Num": "NUM", "Deu": "DEU",
    "Jos": "JOS", "Jdg": "JDG", "Rut": "RUT", "1Sa": "1SA", "2Sa": "2SA",
    "1Ki": "1KI", "2Ki": "2KI", "1Ch": "1CH", "2Ch": "2CH",
    "Ezr": "EZR", "Neh": "NEH", "Est": "EST", "Job": "JOB",
    "Psa": "PSA", "Pro": "PRO", "Ecc": "ECC", "Sng": "SNG",
    "Isa": "ISA", "Jer": "JER", "Lam": "LAM", "Ezk": "EZK", "Dan": "DAN",
    "Hos": "HOS", "Jol": "JOL", "Amo": "AMO", "Oba": "OBA",
    "Jon": "JON", "Mic": "MIC", "Nam": "NAM", "Hab": "HAB", "Zep": "ZEP",
    "Hag": "HAG", "Zec": "ZEC", "Mal": "MAL",
    "Mat": "MAT", "Mrk": "MRK", "Luk": "LUK", "Jhn": "JHN", "Act": "ACT",
    "Rom": "ROM", "1Co": "1CO", "2Co": "2CO", "Gal": "GAL", "Eph": "EPH",
    "Php": "PHP", "Col": "COL", "1Th": "1TH", "2Th": "2TH",
    "1Ti": "1TI", "2Ti": "2TI", "Tit": "TIT", "Phm": "PHM",
    "Heb": "HEB", "Jas": "JAS", "1Pe": "1PE", "2Pe": "2PE",
    "1Jn": "1JN", "2Jn": "2JN", "3Jn": "3JN", "Jud": "JUD", "Rev": "REV",
}


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return s or "unknown"


def _parse_unique_name(unique: str) -> tuple[str, int | None]:
    """'Aaron@Exo.4.14' → ('Aaron', 2004014). The integer is the BBCCCVVV
    of the first mention; None if the suffix can't be parsed (rare)."""
    if "@" not in unique:
        return unique, None
    name, _, ref = unique.partition("@")
    name = name.strip()
    m = re.match(r"^([1-3]?[A-Za-z]+)\.(\d+)\.(\d+)$", ref.strip())
    if not m:
        return name, None
    usfm = _OSIS_TO_USFM.get(m.group(1))
    if usfm is None or usfm not in BOOK_NUMBERS:
        return name, None
    try:
        return name, encode(usfm, int(m.group(2)), int(m.group(3)))
    except ValueError:
        return name, None


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


def _name_normalize(s: str) -> str:
    s = re.sub(r"\s+\d+\s*$", "", s.strip())
    return re.sub(r"\s+", " ", s).strip().lower()


# ---------- fetch ----------

def fetch(staging: Path, *, timeout: float = 120.0) -> None:
    staging.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for fname in FILES:
            url = f"{BASE_URL}/{fname}"
            print(f"  fetch {fname}", flush=True)
            r = client.get(url)
            r.raise_for_status()
            (staging / fname).write_bytes(r.content)


# ---------- parse ----------

def _read_tipnr(path: Path) -> list[dict]:
    """TIPNR JSON files are BOM-prefixed UTF-8."""
    with path.open(encoding="utf-8-sig") as f:
        return json.load(f)


def _all_refs(entry: dict) -> list[int]:
    """Collect every exhaustiveReferences osis ref across all `names` rows."""
    refs: list[int] = []
    for n in entry.get("names") or []:
        for r in n.get("exhaustiveReferences") or []:
            bb = _osis_to_bb(r)
            if bb is not None:
                refs.append(bb)
    # Also include the first-mention from uniqueName so people without
    # exhaustive refs still anchor somewhere.
    _, first = _parse_unique_name(entry.get("uniqueName") or "")
    if first is not None:
        refs.append(first)
    return sorted(set(refs))


def _summarize_names(entry: dict) -> dict:
    """Extract a compact view of the `names` section for metadata storage."""
    out_names = []
    for n in entry.get("names") or []:
        item = {}
        for key in ("ESV_translation", "KJV_translation", "NIV_translation",
                    "Hebrew_Greek", "extendedStrongs"):
            val = n.get(key)
            if val:
                item[key] = val
        if item:
            out_names.append(item)
    return {"names": out_names} if out_names else {}


# ---------- match + write ----------

def _build_theo_index(db, entity_type: str) -> dict[str, list[str]]:
    rows = db.execute(
        "SELECT id, name FROM entities WHERE type = ? AND id NOT LIKE ? AND id NOT LIKE ?",
        (entity_type, f"{entity_type}:tipnr-%", f"{entity_type}:openbible-%"),
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


def _process_entries(
    db,
    entries: list[dict],
    entity_type: str,  # 'person' | 'place'
) -> dict:
    counts = {
        "total": len(entries),
        "enriched_existing": 0,
        "inserted_new": 0,
        "ambiguous_inserted_new": 0,
        "passages_added": 0,
    }

    # Idempotent per entity_type: drop previously-inserted TIPNR-attributed
    # entities of this type. Cascading FK takes their entity_passages.
    db.execute(
        "DELETE FROM entities WHERE id LIKE ?",
        (f"{entity_type}:tipnr-%",),
    )
    db.commit()

    theo_by_name = _build_theo_index(db, entity_type)

    for entry in entries:
        unique = (entry.get("uniqueName") or "").strip()
        if not unique:
            continue
        name, _ = _parse_unique_name(unique)
        refs = _all_refs(entry)

        norm = _name_normalize(name)
        candidates = theo_by_name.get(norm, [])
        target_id: str | None = None

        if len(candidates) == 1:
            target_id = candidates[0]
        elif len(candidates) > 1 and refs:
            ref_set = set(refs)
            best, best_overlap = None, 0
            for cid in candidates:
                tp = _theo_passages_for(db, cid)
                ov = len(ref_set & tp)
                if ov > best_overlap:
                    best, best_overlap = cid, ov
            target_id = best  # may be None if zero overlap

        # Compose metadata patch (whether enriching or inserting fresh).
        patch = {
            "tipnr_unique_name": unique,
            "tipnr_description": (entry.get("description") or "").strip() or None,
        }
        patch.update(_summarize_names(entry))
        patch = {k: v for k, v in patch.items() if v not in (None, "", [], {})}

        if target_id is not None:
            row = db.execute("SELECT metadata FROM entities WHERE id = ?", (target_id,)).fetchone()
            try:
                meta = json.loads(row[0]) if row and row[0] else {}
            except json.JSONDecodeError:
                meta = {}
            meta.update(patch)
            db.execute(
                "UPDATE entities SET metadata = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), target_id),
            )
            counts["enriched_existing"] += 1
            ent_id = target_id
        else:
            ent_id = f"{entity_type}:tipnr-{_slug(unique.replace('@', '-at-'))}"
            db.execute(
                "INSERT OR REPLACE INTO entities(id, type, name, metadata) VALUES (?, ?, ?, ?)",
                (ent_id, entity_type, name, json.dumps(patch, ensure_ascii=False)),
            )
            if len(candidates) > 1:
                counts["ambiguous_inserted_new"] += 1
            else:
                counts["inserted_new"] += 1

        # Add all exhaustive references as entity_passages.
        if refs:
            db.executemany(
                "INSERT OR IGNORE INTO entity_passages(entity_id, start_bbcccvvv, end_bbcccvvv) "
                "VALUES (?, ?, ?)",
                [(ent_id, r, r) for r in refs],
            )
            counts["passages_added"] += len(refs)

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
        print(f"fetching TIPNR → {args.staging}", flush=True)
        fetch(args.staging)

    for fname in FILES:
        if not (args.staging / fname).is_file():
            print(f"missing: {args.staging / fname}", file=sys.stderr)
            return 2

    started = time.time()
    db = open_db(args.db)
    init_schema(db)

    print("processing TIPNR_people.json", flush=True)
    people = _read_tipnr(args.staging / "TIPNR_people.json")
    p_counts = _process_entries(db, people, "person")
    print("processing TIPNR_places.json", flush=True)
    places = _read_tipnr(args.staging / "TIPNR_places.json")
    pl_counts = _process_entries(db, places, "place")
    # TIPNR_other (~112 entries — peoples, deities, etc.) — for now treat as
    # 'event' type to keep them queryable without polluting people/places.
    # Future: a dedicated entity type if useful.
    print("processing TIPNR_other.json", flush=True)
    other = _read_tipnr(args.staging / "TIPNR_other.json")
    o_counts = _process_entries(db, other, "event")

    db.close()
    print(json.dumps({
        "elapsed_seconds": round(time.time() - started, 2),
        "people": p_counts,
        "places": pl_counts,
        "other": o_counts,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
