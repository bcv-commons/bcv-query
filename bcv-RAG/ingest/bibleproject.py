"""BibleProject video-transcript ingest with multi-strategy chunking.

  python -m ingest.bibleproject

Reads pre-built BibleProject chunks from
`ingest/_staging/bibleproject/chunks/all_chunks_for_embedding.json` and
emits per-chunk markdown for `indexer.build` to absorb under
`kind:video-transcript`.

The pre-built chunks come from the vendored pipeline at
`ingest/_tools/bibleproject/` (scripts copied from
larsgson/bible-study-assistant). Each source PDF is chunked three ways
in parallel — by timestamp, by Bible-reference, by semantic-window —
matching the bible-study-assistant project's design that we adopted.
See docs/expansion-plan.md "Multi-strategy chunking (ingest principle
from bible-study-assistant)" for the architectural rationale.

To re-derive the chunks (e.g. when BibleProject publishes new content):

    python ingest/_tools/bibleproject/scrape_pdfs.py        # download PDFs
    python ingest/_tools/bibleproject/step1_extract.py      # PDF → metadata JSON
    python ingest/_tools/bibleproject/step2_chunk.py        # metadata → chunks JSON

License: BibleProject content is generally CC BY-SA on transcripts;
verify per-asset before redistributing the derived index publicly.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import yaml

from indexer.env import load_env
from indexer.references import BOOK_NUMBERS, encode

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STAGING = REPO_ROOT / "ingest" / "_staging" / "bibleproject"
DEFAULT_CHUNKS_FILE = DEFAULT_STAGING / "chunks" / "all_chunks_for_embedding.json"

# BibleProject's book labels are common English forms (singular "Psalm",
# "Song of Solomon", numeric prefixes like "1 Samuel"). Convert to USFM.
_BIBLEPROJECT_TO_USFM: dict[str, str] = {
    "Genesis": "GEN", "Exodus": "EXO", "Leviticus": "LEV", "Numbers": "NUM", "Deuteronomy": "DEU",
    "Joshua": "JOS", "Judges": "JDG", "Ruth": "RUT",
    "1 Samuel": "1SA", "2 Samuel": "2SA", "1 Kings": "1KI", "2 Kings": "2KI",
    "1 Chronicles": "1CH", "2 Chronicles": "2CH", "Ezra": "EZR", "Nehemiah": "NEH",
    "Esther": "EST", "Job": "JOB", "Psalm": "PSA", "Psalms": "PSA",
    "Proverbs": "PRO", "Ecclesiastes": "ECC",
    "Song of Solomon": "SNG", "Song of Songs": "SNG",
    "Isaiah": "ISA", "Jeremiah": "JER", "Lamentations": "LAM", "Ezekiel": "EZK", "Daniel": "DAN",
    "Hosea": "HOS", "Joel": "JOL", "Amos": "AMO", "Obadiah": "OBA",
    "Jonah": "JON", "Micah": "MIC", "Nahum": "NAM", "Habakkuk": "HAB",
    "Zephaniah": "ZEP", "Haggai": "HAG", "Zechariah": "ZEC", "Malachi": "MAL",
    "Matthew": "MAT", "Mark": "MRK", "Luke": "LUK", "John": "JHN", "Acts": "ACT",
    "Romans": "ROM", "1 Corinthians": "1CO", "2 Corinthians": "2CO",
    "Galatians": "GAL", "Ephesians": "EPH", "Philippians": "PHP", "Colossians": "COL",
    "1 Thessalonians": "1TH", "2 Thessalonians": "2TH",
    "1 Timothy": "1TI", "2 Timothy": "2TI", "Titus": "TIT", "Philemon": "PHM",
    "Hebrews": "HEB", "James": "JAS",
    "1 Peter": "1PE", "2 Peter": "2PE",
    "1 John": "1JN", "2 John": "2JN", "3 John": "3JN", "Jude": "JUD", "Revelation": "REV",
}


def _safe_filename(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]", "_", s)[:120] or "chunk"


def _book_to_usfm(book: str | None) -> str | None:
    if not book:
        return None
    return _BIBLEPROJECT_TO_USFM.get(book.strip())


def _passage_for_ref(book: str | None, chap: int | None, verse: int | None) -> tuple[int, int] | None:
    """Convert a (book, chapter, verse) triple to a BBCCCVVV pair. If verse is
    None we span the whole chapter (verse 1..999)."""
    usfm = _book_to_usfm(book)
    if usfm is None or usfm not in BOOK_NUMBERS:
        return None
    try:
        c = int(chap) if chap is not None else None
        v = int(verse) if verse is not None else None
    except (TypeError, ValueError):
        return None
    if c is None:
        return None
    try:
        if v is None:
            # Whole-chapter range
            return encode(usfm, c, 1), encode(usfm, c, 999)
        return encode(usfm, c, v), encode(usfm, c, v)
    except ValueError:
        return None


def _collect_passages(metadata: dict) -> tuple[list[list[int]], set[str]]:
    """Walk the metadata, return ([[start, end], …], {book:USFM tags…}).

    Different chunking strategies surface references differently:
      * `bible_reference` strategy: `reference_details[]` carries
        (book, chapter, [verse?])
      * `timestamp` & `semantic` strategies: `bible_references[]` carries
        the same shape under a different key.
    """
    passages: list[list[int]] = []
    book_tags: set[str] = set()

    candidates = metadata.get("reference_details") or metadata.get("bible_references") or []
    if not isinstance(candidates, list):
        return passages, book_tags

    seen: set[tuple[int, int]] = set()
    for ref in candidates:
        if not isinstance(ref, dict):
            continue
        rng = _passage_for_ref(
            ref.get("book"),
            ref.get("chapter"),
            ref.get("verse_start") if ref.get("verse_start") is not None else ref.get("verse"),
        )
        if rng is None:
            continue
        if rng not in seen:
            seen.add(rng)
            passages.append([rng[0], rng[1]])
        usfm = _book_to_usfm(ref.get("book"))
        if usfm:
            book_tags.add(f"book:{usfm}")

    # Also pick up the primary_* fields on bible_reference-strategy chunks.
    primary = _passage_for_ref(
        metadata.get("primary_book"),
        metadata.get("primary_chapter"),
        metadata.get("primary_verse"),
    )
    if primary is not None and primary not in seen:
        seen.add(primary)
        passages.append([primary[0], primary[1]])
    primary_usfm = _book_to_usfm(metadata.get("primary_book"))
    if primary_usfm:
        book_tags.add(f"book:{primary_usfm}")

    return passages, book_tags


def _chunk_to_markdown(chunk: dict, out_root: Path) -> Path | None:
    text = (chunk.get("text") or "").strip()
    if not text:
        return None
    cid = chunk.get("id") or chunk.get("strategy_id") or ""
    if not cid:
        return None
    strategy = chunk.get("strategy") or "unknown"
    md = chunk.get("metadata") or {}

    passages, book_tags = _collect_passages(md)

    tags = [
        "kind:video-transcript",
        "lang:en",
        "resource:bibleproject",
        "org:bibleproject",
        f"chunk_strategy:{strategy}",
    ]
    tags.extend(book_tags)
    series = md.get("series") or md.get("category")
    if series:
        tags.append(f"series:{re.sub(r'[^A-Za-z0-9_-]+', '-', series).strip('-').lower()}")

    title_parts = ["BibleProject", md.get("title") or cid]
    if strategy != "unknown":
        title_parts.append(f"({strategy})")
    title = " — ".join(title_parts)

    front: dict = {
        "title": title,
        "tags": sorted(set(tags)),
    }
    if passages:
        front["passages"] = passages

    # Compact metadata for downstream debugging / cross-ref use. Skip
    # heavy fields (reference_details, etc.) — they're already encoded
    # into tags + passages above.
    extra = {}
    for key in ("series", "category", "type", "filename", "original_url",
                "video_timestamp", "start_time", "end_time", "page_count"):
        val = md.get(key)
        if val not in (None, "", []):
            extra[key] = val
    if extra:
        front.update(extra)

    out_dir = out_root / strategy
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_safe_filename(cid)}.md"
    out_path.write_text(
        "---\n"
        + yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip()
        + "\n---\n\n"
        + text
        + "\n",
        encoding="utf-8",
    )
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_FILE,
                    help="path to all_chunks_for_embedding.json")
    ap.add_argument("--out", type=Path, default=DEFAULT_STAGING / "verses",
                    help="staging directory for emitted markdown")
    args = ap.parse_args()
    load_env()

    if not args.chunks.is_file():
        print(f"missing chunks file: {args.chunks}", file=sys.stderr)
        print("Re-derive via the vendored pipeline in ingest/_tools/bibleproject/, "
              "or copy the cached file from examples/bible-study-assistant/imports/tbp/chunks/.",
              file=sys.stderr)
        return 2

    if args.out.is_dir():
        for old in args.out.rglob("*.md"):
            old.unlink()

    started = time.time()

    chunks = json.loads(args.chunks.read_text(encoding="utf-8"))
    if not isinstance(chunks, list):
        print(f"expected a list in {args.chunks}", file=sys.stderr)
        return 2

    counts = {"total": len(chunks), "emitted": 0, "skipped": 0, "by_strategy": {}}
    for c in chunks:
        path = _chunk_to_markdown(c, args.out)
        if path is None:
            counts["skipped"] += 1
            continue
        counts["emitted"] += 1
        s = c.get("strategy", "unknown")
        counts["by_strategy"][s] = counts["by_strategy"].get(s, 0) + 1

    counts["elapsed_seconds"] = round(time.time() - started, 2)
    print(json.dumps(counts, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
