#!/usr/bin/env python3
"""Single-command refresh: ingest -> build -> embed.

Designed as the entrypoint for a Railway cron service. Run it from inside
the same image the HTTP service uses, mounting the same volume:

    python -m indexer.refresh

Each step is incremental:
  1. `ingest.cli` re-pulls upstream sources into `ingest/_staging`
  2. `indexer.build` is idempotent (content-derived doc ids; DELETE+INSERT)
  3. `indexer.embed` only embeds chunks lacking a vector

So daily runs cost near-zero unless upstream actually changed.

Configurable via env vars (sensible defaults match the current corpus):
  BTMCP_REFRESH_SOURCES   default: "door43 aquifer"   (space-separated)
  BTMCP_REFRESH_BOOKS     default: all 66 books       (space-separated USFM codes)
  BTMCP_REFRESH_LANG      default: "en"

Required env (same as the HTTP server):
  OPENAI_API_KEY          for embeddings in step 3
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STAGING = REPO_ROOT / "ingest" / "_staging"


def _env_list(name: str, default: str) -> list[str]:
    raw = (os.environ.get(name) or default).strip()
    return raw.split() if raw else []


def _run(label: str, cmd: list[str]) -> int:
    started = time.time()
    print(f"[refresh] {label}: {' '.join(cmd)}", flush=True)
    rc = subprocess.call(cmd, cwd=REPO_ROOT)
    elapsed = time.time() - started
    print(f"[refresh] {label}: rc={rc} ({elapsed:.1f}s)", flush=True)
    return rc


_ALL_BOOKS = (
    "GEN EXO LEV NUM DEU JOS JDG RUT 1SA 2SA 1KI 2KI 1CH 2CH EZR "
    "NEH EST JOB PSA PRO ECC SNG ISA JER LAM EZK DAN HOS JOL AMO "
    "OBA JON MIC NAM HAB ZEP HAG ZEC MAL "
    "MAT MRK LUK JHN ACT ROM 1CO 2CO GAL EPH PHP COL 1TH 2TH 1TI "
    "2TI TIT PHM HEB JAS 1PE 2PE 1JN 2JN 3JN JUD REV"
)


def main() -> int:
    sources = _env_list("BTMCP_REFRESH_SOURCES", "door43 aquifer")
    books = _env_list("BTMCP_REFRESH_BOOKS", _ALL_BOOKS)
    lang = (os.environ.get("BTMCP_REFRESH_LANG") or "en").strip()

    if not sources or not books:
        print("[refresh] BTMCP_REFRESH_SOURCES / BTMCP_REFRESH_BOOKS must be non-empty",
              file=sys.stderr)
        return 2

    py = sys.executable

    # Honour INDEX_DB_PATH so build/embed write to the same DB the server reads.
    db_path = os.environ.get("INDEX_DB_PATH") or str(REPO_ROOT / "indexer" / "index.db")

    ingest_cmd = [py, "-m", "ingest.cli", "--lang", lang]
    for s in sources:
        ingest_cmd += ["--source", s]
    for b in books:
        ingest_cmd += ["--book", b]

    rc = _run("1/3 ingest", ingest_cmd)
    if rc != 0:
        return rc

    rc = _run("2/3 build", [py, "-m", "indexer.build", "--source", str(STAGING), "--db", db_path])
    if rc != 0:
        return rc

    rc = _run("3/3 embed", [py, "-m", "indexer.embed", "--db", db_path])
    return rc


if __name__ == "__main__":
    sys.exit(main())
