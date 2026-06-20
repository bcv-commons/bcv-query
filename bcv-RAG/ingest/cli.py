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
from ingest import aquifer, door43  # noqa: E402
from lang import canon  # noqa: E402

DEFAULT_STAGING = Path(__file__).resolve().parent / "_staging"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", action="append", choices=["door43", "aquifer"],
                    help="repeatable; default: door43 only. Use both for full coverage.")
    ap.add_argument("--book", action="append", required=True,
                    help="USFM book code; repeatable (e.g. --book TIT --book RUT)")
    ap.add_argument("--lang", default="eng")
    ap.add_argument("--staging", type=Path, default=DEFAULT_STAGING,
                    help="root staging dir (a per-source subdir is created underneath)")
    args = ap.parse_args()
    load_env()

    if canon(args.lang) != "eng":
        print("v1: English only", file=sys.stderr)
        return 2

    book_codes = [b.upper() for b in args.book]
    sources = args.source or ["door43"]

    results: dict[str, dict] = {}
    if "door43" in sources:
        results["door43"] = door43.ingest_books(book_codes, args.staging / "door43")
    if "aquifer" in sources:
        results["aquifer"] = aquifer.ingest_books(book_codes, args.staging / "aquifer")

    print(json.dumps({
        "sources": sources,
        "books": book_codes,
        "staged_files": results,
        "staging_dir": str(args.staging),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
