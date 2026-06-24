"""Top-level ingest CLI.

    python3 -m ingest.cli --source door43 --book TIT
    python3 -m ingest.cli --source aquifer --book TIT   # NotImplemented in v1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from indexer.env import load_env  # noqa: E402
from indexer.references import NUMBER_TO_CODE  # noqa: E402
from ingest import aquifer, door43  # noqa: E402
from lang import canon  # noqa: E402

DEFAULT_STAGING = Path(__file__).resolve().parent / "_staging"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", action="append", choices=["door43", "aquifer"],
                    help="repeatable; default: door43 only. Use both for full coverage.")
    ap.add_argument("--book", action="append",
                    help="USFM book code; repeatable (e.g. --book TIT --book RUT)")
    ap.add_argument("--all-books", action="store_true",
                    help="ingest all 66 books (BSB already covers scripture; this "
                         "pulls the full TN/TQ/TW/TA + complete TW term-article set).")
    ap.add_argument("--tw-langs", action="append", metavar="LANG",
                    help="canonical language code for native TW articles from Door43-Catalog "
                         "(e.g. --tw-langs spa --tw-langs fra). Repeatable. "
                         "Available: spa, fra, hin, por, rus, ben. "
                         "Pass 'all' to ingest all available languages.")
    ap.add_argument("--tw-langs-only", action="store_true",
                    help="fetch non-English TW articles only (skips book ingest). "
                         "Requires --tw-langs. Articles get no passage/book tags "
                         "(acceptable — Strong's anchoring still works).")
    ap.add_argument("--lang", default="eng")
    ap.add_argument("--staging", type=Path, default=DEFAULT_STAGING,
                    help="root staging dir (a per-source subdir is created underneath)")
    args = ap.parse_args()
    if not args.tw_langs_only and not args.book and not args.all_books:
        ap.error("pass --book <CODE> (repeatable), --all-books, or --tw-langs-only")
    load_env()

    if canon(args.lang) != "eng":
        print("v1: English only", file=sys.stderr)
        return 2

    if args.tw_langs_only:
        book_codes = []
    elif args.all_books:
        book_codes = [NUMBER_TO_CODE[n] for n in range(1, 67) if n in NUMBER_TO_CODE]
    else:
        book_codes = [b.upper() for b in args.book]
    sources = args.source or ["door43"]

    _ALL_TW_LANGS = list(door43._LANG_TW_REPOS.keys())
    raw_tw_langs = args.tw_langs or []
    if "all" in raw_tw_langs:
        tw_langs = _ALL_TW_LANGS
    else:
        tw_langs = raw_tw_langs

    results: dict[str, dict] = {}
    if args.tw_langs_only:
        if not tw_langs:
            ap.error("--tw-langs-only requires at least one --tw-langs <LANG>")
        results["door43"] = {}
        for lang in tw_langs:
            n = door43.ingest_tw_lang(lang, args.staging / "door43")
            results["door43"][f"tw_{lang}"] = n
            print(f"  tw/{lang}: {n} articles staged")
    else:
        if "door43" in sources:
            results["door43"] = door43.ingest_books(
                book_codes, args.staging / "door43", extra_langs=tw_langs or None
            )
        if "aquifer" in sources:
            results["aquifer"] = aquifer.ingest_books(book_codes, args.staging / "aquifer")

    print(json.dumps({
        "sources": sources,
        "books": book_codes,
        "tw_langs": tw_langs,
        "staged_files": results,
        "staging_dir": str(args.staging),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
