"""BSB (Berean Standard Bible) ingest from BSB-publishing/bsb-data-output.

  python -m ingest.bsb                # fetch + emit + write cross-refs (stage only)
  python -m ingest.bsb --no-fetch     # use already-staged JSONL
  python -m ingest.bsb --build        # also run indexer.build on the staged chunks

Lands three things in one ingest pass:

1. **BSB verses** — 30,969 chunks tagged `kind:scripture`, `lang:en`,
   `resource:bsb`, with Strong's-number tags per verse and `book:<USFM>`.
   One markdown file per verse under `ingest/_staging/bsb/verses/`.
2. **TSK cross-references** — ~430k verse↔verse links from the bundled
   `x` field, written directly to the `cross_references` table.
3. **Section headings** (s1/s2 levels) — the BSB pericope titles like
   "The Creation" / "The Sermon on the Mount", emitted as
   `kind:section-heading` chunks anchored to the verse where each
   heading sits. Parallel-passage refs (level=`r`) are also written as
   cross-references with attribution `bsb-parallel`.

Source data
-----------
https://github.com/BSB-publishing/bsb-data-output (CC0 + CC-BY 4.0)
- `base/index-cc-by/bible-index.jsonl` — verses + Strong's + TSK xrefs +
  morphology + heading anchors. License: CC-BY 4.0 (includes OSHB
  morphology); for CC0-only deploys swap to `vector-db/index-pd/` once
  that artifact ships.
- `base/headings.jsonl` — section + parallel-passage headings.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, Iterator

import httpx
import yaml

from indexer.build import init_schema
from indexer.db import open_db
from indexer.env import load_env
from indexer.references import BOOK_NUMBERS, encode

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "indexer" / "index.db"
DEFAULT_STAGING = REPO_ROOT / "ingest" / "_staging" / "bsb"

BASE_RAW = "https://raw.githubusercontent.com/BSB-publishing/bsb-data-output/main"
URLS: dict[str, str] = {
    "bible-index.jsonl": f"{BASE_RAW}/base/index-cc-by/bible-index.jsonl",
    "headings.jsonl":    f"{BASE_RAW}/base/headings.jsonl",
}

# The hosted output's verse `id` and cross-ref formats use uppercase USFM
# 3-letter book codes (GEN, EXO, …, MAT, REV) — same as our BOOK_NUMBERS
# keys. So no aliasing needed; we just split on '.' and look up.
_REF_RE = re.compile(r"^([1-3]?[A-Z]{2,3})\.(\d+)\.(\d+)(?:-(\d+))?$")


# ---------- helpers ----------

def _safe_filename(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]", "_", s)


def _bbcccvvv(book: str, chap: int, verse: int) -> int | None:
    if book not in BOOK_NUMBERS:
        return None
    try:
        return encode(book, chap, verse)
    except ValueError:
        return None


def _parse_xref_id(xref: str) -> tuple[int, int] | None:
    """Parse a cross-reference id like 'PRO.8.22' or 'PRO.8.22-30'.
    Returns (start_bbcccvvv, end_bbcccvvv) or None on parse failure."""
    m = _REF_RE.match(xref.strip())
    if not m:
        return None
    book, chap_s, vstart_s, vend_s = m.group(1), m.group(2), m.group(3), m.group(4)
    try:
        chap = int(chap_s)
        vstart = int(vstart_s)
        vend = int(vend_s) if vend_s else vstart
    except ValueError:
        return None
    s = _bbcccvvv(book, chap, vstart)
    e = _bbcccvvv(book, chap, vend)
    if s is None or e is None:
        return None
    return s, e


def _parse_heading_ref(ref_text: str) -> list[tuple[int, int]]:
    """Parse a heading ref like 'JHN 1:1-5' or 'HEB 11:1-3' into BBCCCVVV pairs.
    Heading 'refs' use space-separated USFM-ish format with colons. Loosely matched."""
    out: list[tuple[int, int]] = []
    for piece in re.split(r"[;,]\s*", ref_text):
        m = re.match(r"^([1-3]?\s?[A-Za-z]{2,3})\s+(\d+):(\d+)(?:[-–](\d+))?$", piece.strip())
        if not m:
            continue
        book = re.sub(r"\s+", "", m.group(1)).upper()
        try:
            chap = int(m.group(2))
            v1 = int(m.group(3))
            v2 = int(m.group(4)) if m.group(4) else v1
        except ValueError:
            continue
        s = _bbcccvvv(book, chap, v1)
        e = _bbcccvvv(book, chap, v2)
        if s is not None and e is not None:
            out.append((s, e))
    return out


# ---------- fetch ----------

def fetch(staging: Path, *, timeout: float = 300.0) -> None:
    staging.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for fname, url in URLS.items():
            print(f"  fetch {fname}", flush=True)
            with client.stream("GET", url) as r:
                r.raise_for_status()
                dest = staging / fname
                with dest.open("wb") as f:
                    for chunk in r.iter_bytes(chunk_size=64 * 1024):
                        f.write(chunk)


# ---------- emit verses ----------

def _emit_verse_md(verse: dict, out_root: Path) -> Path | None:
    book = verse.get("b") or ""
    chap = verse.get("c")
    vnum = verse.get("v")
    text = (verse.get("t") or "").strip()
    if not (book and isinstance(chap, int) and isinstance(vnum, int) and text):
        return None
    bb = _bbcccvvv(book, chap, vnum)
    if bb is None:
        return None

    # Strong's tags — dedup and normalize.
    strongs_set = set()
    for s in verse.get("s") or []:
        s = s.strip()
        m = re.match(r"^([GH])(\d+)([a-zA-Z]?)$", s)
        if m:
            strongs_set.add(f"{m.group(1)}{int(m.group(2)):04d}{m.group(3)}")

    # Tag BSB verses as `kind:bible` (NOT `kind:scripture`). Why: scripture
    # in our v2 taxonomy is the small Door43 ULT/UST set used as the
    # translator's primary literal/simplified pair. BSB is a much larger
    # general-readability translation — adding 31k chunks under the same
    # kind would re-rank Door43 results for thematic queries. Per-kind FTS
    # isolation (chunks_fts_bsb) keeps BSB searchable on its own corpus
    # stats. Stage-3 retrievers can opt in to BSB explicitly.
    tags = [
        "kind:bible",
        f"book:{book}",
        "lang:en",
        "resource:bsb",
        "org:berean",
    ]
    tags += [f"strongs:{s}" for s in sorted(strongs_set)]

    front = {
        "title": f"BSB — {book} {chap}:{vnum}",
        "tags": sorted(set(tags)),
        "passages": [[bb, bb]],
    }

    out_dir = out_root / book / str(chap)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{chap:03d}_{vnum:03d}.md"
    out_path.write_text(
        "---\n"
        + yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip()
        + "\n---\n\n"
        + text + "\n",
        encoding="utf-8",
    )
    return out_path


# ---------- emit headings ----------

def _emit_heading_md(heading: dict, out_root: Path) -> Path | None:
    """Emit s1/s2 section headings as kind:section-heading chunks."""
    level = (heading.get("level") or "").strip()
    if level not in ("s1", "s2"):
        return None
    book = heading.get("b") or ""
    chap = heading.get("c")
    before_v = heading.get("before_v")
    text = (heading.get("text") or "").strip()
    if not (book and isinstance(chap, int) and isinstance(before_v, int) and text):
        return None
    bb = _bbcccvvv(book, chap, before_v)
    if bb is None:
        return None

    front = {
        "title": f"Heading: {text}",
        "tags": sorted({
            "kind:section-heading",
            f"book:{book}",
            "lang:en",
            "resource:bsb",
            f"heading-level:{level}",
        }),
        "passages": [[bb, bb]],
    }

    hid = heading.get("id") or f"{book}.{level}.{chap}.{before_v}"
    out_dir = out_root / book / str(chap)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_safe_filename(hid)}.md"
    out_path.write_text(
        "---\n"
        + yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip()
        + "\n---\n\n"
        + text + "\n",
        encoding="utf-8",
    )
    return out_path


# ---------- write cross-references ----------

def _write_cross_refs(
    db,
    staging: Path,
    *,
    chunk_size: int = 5000,
) -> dict:
    """Stream bible-index.jsonl + headings.jsonl, write cross-refs to DB.

    Why two passes: TSK xrefs live on each bible-index verse (the `x`
    field); 'r'-level headings encode parallel-passage refs. Both go
    into the same `cross_references` table with different attributions.
    """
    counts = {"tsk": 0, "bsb-parallel": 0, "skipped": 0}

    # Wipe previously-written rows so re-runs are idempotent. Scoped to
    # the attributions we own.
    db.execute("DELETE FROM cross_references WHERE source_attribution IN ('tsk','bsb-parallel')")
    db.commit()

    # Pass 1: TSK from bible-index.jsonl
    tsk_buf: list[tuple] = []
    bible_index = staging / "bible-index.jsonl"
    with bible_index.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                verse = json.loads(line)
            except json.JSONDecodeError:
                counts["skipped"] += 1
                continue
            book = verse.get("b") or ""
            chap = verse.get("c")
            v = verse.get("v")
            if not (book and isinstance(chap, int) and isinstance(v, int)):
                continue
            src = _bbcccvvv(book, chap, v)
            if src is None:
                continue
            for rank, xref in enumerate(verse.get("x") or [], start=1):
                tgt = _parse_xref_id(xref)
                if tgt is None:
                    counts["skipped"] += 1
                    continue
                tsk_buf.append((src, tgt[0], tgt[1], "tsk", rank))
                if len(tsk_buf) >= chunk_size:
                    db.executemany(
                        "INSERT OR IGNORE INTO cross_references"
                        "(source_bbcccvvv, target_start_bbcccvvv, target_end_bbcccvvv, source_attribution, rank) "
                        "VALUES (?, ?, ?, ?, ?)",
                        tsk_buf,
                    )
                    counts["tsk"] += len(tsk_buf)
                    tsk_buf = []
    if tsk_buf:
        db.executemany(
            "INSERT OR IGNORE INTO cross_references"
            "(source_bbcccvvv, target_start_bbcccvvv, target_end_bbcccvvv, source_attribution, rank) "
            "VALUES (?, ?, ?, ?, ?)",
            tsk_buf,
        )
        counts["tsk"] += len(tsk_buf)
    db.commit()

    # Pass 2: parallel-passage refs from headings.jsonl
    par_buf: list[tuple] = []
    headings = staging / "headings.jsonl"
    with headings.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                h = json.loads(line)
            except json.JSONDecodeError:
                counts["skipped"] += 1
                continue
            if (h.get("level") or "") != "r":
                continue
            book = h.get("b") or ""
            chap = h.get("c")
            before_v = h.get("before_v")
            if not (book and isinstance(chap, int) and isinstance(before_v, int)):
                continue
            src = _bbcccvvv(book, chap, before_v)
            if src is None:
                continue
            for raw_ref in h.get("refs") or []:
                for tgt_start, tgt_end in _parse_heading_ref(raw_ref):
                    par_buf.append((src, tgt_start, tgt_end, "bsb-parallel", None))
                    if len(par_buf) >= chunk_size:
                        db.executemany(
                            "INSERT OR IGNORE INTO cross_references"
                            "(source_bbcccvvv, target_start_bbcccvvv, target_end_bbcccvvv, source_attribution, rank) "
                            "VALUES (?, ?, ?, ?, ?)",
                            par_buf,
                        )
                        counts["bsb-parallel"] += len(par_buf)
                        par_buf = []
    if par_buf:
        db.executemany(
            "INSERT OR IGNORE INTO cross_references"
            "(source_bbcccvvv, target_start_bbcccvvv, target_end_bbcccvvv, source_attribution, rank) "
            "VALUES (?, ?, ?, ?, ?)",
            par_buf,
        )
        counts["bsb-parallel"] += len(par_buf)
    db.commit()

    return counts


# ---------- CLI ----------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--build", action="store_true",
                    help="run indexer.build on the staged verses/headings afterwards")
    args = ap.parse_args()
    load_env()

    raw_dir = args.staging / "_raw"
    verses_dir = args.staging / "verses"
    headings_dir = args.staging / "headings"

    if not args.no_fetch:
        print(f"fetching BSB JSONL → {raw_dir}", flush=True)
        fetch(raw_dir)

    bible_index = raw_dir / "bible-index.jsonl"
    headings_path = raw_dir / "headings.jsonl"
    for p in (bible_index, headings_path):
        if not p.is_file():
            print(f"missing: {p}", file=sys.stderr)
            return 2

    # Wipe previous emit so removed verses don't leave stale staged files.
    for d in (verses_dir, headings_dir):
        if d.is_dir():
            for old in d.rglob("*.md"):
                old.unlink()

    started = time.time()

    # Emit verses
    n_verses = 0
    n_skipped = 0
    print("emitting BSB verse markdown", flush=True)
    with bible_index.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                verse = json.loads(line)
            except json.JSONDecodeError:
                n_skipped += 1
                continue
            if _emit_verse_md(verse, verses_dir) is not None:
                n_verses += 1
            else:
                n_skipped += 1

    # Emit s1/s2 headings
    n_headings = 0
    print("emitting BSB heading markdown", flush=True)
    with headings_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                h = json.loads(line)
            except json.JSONDecodeError:
                continue
            if _emit_heading_md(h, headings_dir) is not None:
                n_headings += 1

    # Write cross-references directly to DB
    print("writing cross-references", flush=True)
    db = open_db(args.db)
    init_schema(db)  # ensures cross_references table exists on existing indexes
    xref_counts = _write_cross_refs(db, raw_dir)
    db.close()

    elapsed = round(time.time() - started, 2)
    print(json.dumps({
        "elapsed_seconds": elapsed,
        "verses_emitted": n_verses,
        "headings_emitted": n_headings,
        "verses_skipped": n_skipped,
        **{f"xref_{k}": v for k, v in xref_counts.items()},
    }, indent=2))

    if args.build:
        print(f"building staged chunks → {args.db}", flush=True)
        return subprocess.run(
            [sys.executable, "-m", "indexer.build",
             "--source", str(args.staging), "--db", str(args.db)],
            cwd=REPO_ROOT,
        ).returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
