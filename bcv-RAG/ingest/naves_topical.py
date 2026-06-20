"""Nave's Topical Bible ingest from CCEL (public domain).

  python -m ingest.naves_topical                 # fetch + parse + write
  python -m ingest.naves_topical --no-fetch      # use already-staged XML

Pulls https://www.ccel.org/ccel/nave/bible.xml (CCEL ThML format) and
loads it into the `topics` and `topic_passages` tables. No chunks are
written — Nave's data is structured (topic → verse list), not prose;
retrievers in stage 3 will join `topic_passages` against the existing
chunks/passage_refs to surface "verses about <topic>" answers.

Source format
-------------
ThML XML with `<glossary><term>TOPIC</term><def>…<scripRef
osisRef="Bible:Gen.1.1">…</scripRef>…</def></glossary>` shape. The
parser walks all elements; on each `<term>` updates the current topic,
on each `<scripRef>` adds the parsed verse to that topic.

License: public domain (CCEL).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import httpx

from indexer.build import init_schema
from indexer.db import open_db
from indexer.env import load_env
from indexer.references import BOOK_NUMBERS, encode

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "indexer" / "index.db"
DEFAULT_STAGING = REPO_ROOT / "ingest" / "_staging" / "naves_topical"

NAVES_URL = "https://www.ccel.org/ccel/nave/bible.xml"

# CCEL/OSIS abbreviations → our USFM 3-letter codes. From bsb-data's
# enrich_topics.py reference table (we extend their list rather than re-derive).
_OSIS_TO_USFM: dict[str, str] = {
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

def _slug(name: str) -> str:
    """'Faith, Steadfastness in' → 'faith-steadfastness-in'."""
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "unknown"


def _parse_single_osis(ref: str) -> tuple[str, int, int] | None:
    """'Gen.1.1' → ('GEN', 1, 1). Returns None on unknown book or malformed input."""
    m = re.match(r"^([1-3]?[A-Za-z]+)\.(\d+)\.(\d+)$", ref.strip())
    if not m:
        return None
    osis_book = m.group(1)
    usfm = _OSIS_TO_USFM.get(osis_book)
    if usfm is None or usfm not in BOOK_NUMBERS:
        return None
    try:
        return usfm, int(m.group(2)), int(m.group(3))
    except ValueError:
        return None


def _parse_osis_ref(osis_ref: str) -> list[tuple[int, int]]:
    """'Bible:Gen.1.1' or 'Bible:Gen.1.1-Gen.1.3' → list of (start, end) BBCCCVVV pairs.

    For ranges within the same chapter we expand to (start, end). For
    cross-chapter or cross-book ranges we yield only the start verse
    (matching bsb-data's enrich_topics behavior).
    """
    if not osis_ref:
        return []
    if osis_ref.startswith("Bible:"):
        osis_ref = osis_ref[6:]

    if "-" not in osis_ref:
        ref = _parse_single_osis(osis_ref)
        if ref is None:
            return []
        bb = encode(ref[0], ref[1], ref[2])
        return [(bb, bb)]

    parts = osis_ref.split("-", 1)
    start = _parse_single_osis(parts[0])
    end = _parse_single_osis(parts[1])
    if start is None:
        return []
    if end is None or start[0] != end[0] or start[1] != end[1]:
        bb = encode(start[0], start[1], start[2])
        return [(bb, bb)]
    s_bb = encode(start[0], start[1], start[2])
    e_bb = encode(end[0], end[1], end[2])
    return [(s_bb, e_bb)]


# ---------- fetch ----------

def fetch(staging: Path, *, timeout: float = 120.0) -> None:
    staging.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        print(f"  fetch {NAVES_URL}", flush=True)
        r = client.get(NAVES_URL)
        r.raise_for_status()
        (staging / "naves-topical-bible.xml").write_bytes(r.content)


# ---------- parse ----------

def parse(staging: Path) -> dict[str, list[tuple[int, int]]]:
    """Return {topic_name: [(start_bbcccvvv, end_bbcccvvv), ...]}."""
    path = staging / "naves-topical-bible.xml"
    tree = ET.parse(path)
    root = tree.getroot()

    topics: dict[str, list[tuple[int, int]]] = defaultdict(list)
    current_topic: str | None = None

    # ThML uses no XML namespace by default, so plain tag names work.
    for elem in root.iter():
        if elem.tag == "term":
            txt = (elem.text or "").strip()
            if txt:
                current_topic = txt
        elif elem.tag == "scripRef" and current_topic:
            osis_ref = elem.get("osisRef") or ""
            for s, e in _parse_osis_ref(osis_ref):
                topics[current_topic].append((s, e))

    # Dedup verses per topic (preserve order).
    out: dict[str, list[tuple[int, int]]] = {}
    for name, refs in topics.items():
        seen: set[tuple[int, int]] = set()
        unique = []
        for r in refs:
            if r not in seen:
                seen.add(r)
                unique.append(r)
        if unique:
            out[name] = unique
    return out


# ---------- write ----------

def write(db, topics: dict[str, list[tuple[int, int]]]) -> dict:
    counts = {"topics": 0, "passages": 0, "skipped_dup_slugs": 0}

    # Idempotent: wipe Nave's-attributed rows. Cascading FK cleans topic_passages.
    db.execute("DELETE FROM topics WHERE source = 'naves'")
    db.commit()

    seen_slugs: dict[str, str] = {}
    for name, refs in topics.items():
        slug = _slug(name)
        if slug in seen_slugs:
            # Two distinct topic names slugged the same — append source suffix
            # to disambiguate. (E.g., 'Faith' vs 'Faith.' in CCEL data.)
            counts["skipped_dup_slugs"] += 1
            slug = f"{slug}-{counts['skipped_dup_slugs']}"
        seen_slugs[slug] = name

        topic_id = slug
        db.execute(
            "INSERT OR REPLACE INTO topics(id, name, source, metadata) VALUES (?, ?, ?, ?)",
            (topic_id, name, "naves", "{}"),
        )
        counts["topics"] += 1

        rows = [(topic_id, s, e) for s, e in refs]
        db.executemany(
            "INSERT OR IGNORE INTO topic_passages(topic_id, start_bbcccvvv, end_bbcccvvv) "
            "VALUES (?, ?, ?)",
            rows,
        )
        counts["passages"] += len(rows)

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
        print(f"fetching Nave's → {args.staging}", flush=True)
        fetch(args.staging)

    if not (args.staging / "naves-topical-bible.xml").is_file():
        print(f"missing: {args.staging / 'naves-topical-bible.xml'}", file=sys.stderr)
        return 2

    print("parsing Nave's XML", flush=True)
    started = time.time()
    topics = parse(args.staging)

    db = open_db(args.db)
    init_schema(db)
    counts = write(db, topics)
    db.close()

    print(json.dumps({
        "elapsed_seconds": round(time.time() - started, 2),
        **counts,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
