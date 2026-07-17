"""Fetch a pinned snapshot of globalbibletools/data (CC0-1.0 — org-wide default license;
confirmed no per-repo override).

No dependency on any pre-baked externally-fetched .db beyond the strongs-code->root-word TEXT
files below (fetch_strongs_data — small, license-clean, and unrelated to the lexicon/translation
.db question). eng_bsb.db / sdbh.db / sdbg.db (study-app's bundled SQLite assets) were fetched here
at one point and are deliberately no longer used — see shoresh/interlinear/serve.py's module
docstring and internal-docs/gbt-alignment-handover.md for what replaced each.

Same discipline as shoresh/macula/parse.py's MACULA fetch and shoresh/lxx/parse.py's LXX_COMMIT:
pinned to a commit SHA, re-pinned deliberately — NOT a live `git pull` to whatever HEAD happens to
be. A tarball fetch (not a full `git clone`) keeps this dependency-free (stdlib only) and avoids
pulling repo history we don't need.

  python -m interlinear.fetch            # downloads + extracts the pinned commit to data/
  GBT_DATA_COMMIT=<sha> python -m interlinear.fetch   # override the pin for a deliberate bump
"""
from __future__ import annotations

import os
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data" / "gbt"
STRONGS_DATA_DIR = HERE / "data" / "strongs-data"

# Pinned commit (matches the clone this was evaluated against — see the design conversation this
# module came from). Re-pin deliberately: bump this SHA, re-run fetch + build, re-verify coverage.
GBT_DATA_COMMIT = "f5af0eb89e4b845b2b30beb9f4360b50ddb08f6a"
GBT_DATA_URL = "https://github.com/globalbibletools/data/archive/{commit}.tar.gz"

# strongs-greek.txt / strongs-hebrew.txt (Strong's code -> root word) aren't part of the `data` repo
# above — they're a small static asset from the ORIGINAL Flutter app's own repo (also CC0-1.0). Fetch
# them from their true source instead of vendoring a static copy into shoresh, so this stays rebuilt-
# from-pin like everything else (no file committed here that isn't either code or a small derived
# resource genuinely owned by this repo).
STUDY_APP_COMMIT = "4e934948a5a6ebd17f5404191b05ab1f1c652efd"
STUDY_APP_STRONGS_BASE = (
    "https://raw.githubusercontent.com/globalbibletools/study-app/{commit}/"
    "database_builder/lib/src/hebrew_greek/strongs_data/{filename}"
)

def fetch(commit: str | None = None) -> Path:
    """Download + extract the pinned globalbibletools/data commit to DATA_DIR. Idempotent — a
    `commit`-stamped marker file skips re-download if already present at that exact pin."""
    commit = commit or os.environ.get("GBT_DATA_COMMIT") or GBT_DATA_COMMIT
    marker = DATA_DIR / ".commit"
    if DATA_DIR.exists() and marker.exists() and marker.read_text().strip() == commit:
        print(f"[interlinear] already fetched at {commit[:8]}, skipping", file=sys.stderr)
        return DATA_DIR

    url = GBT_DATA_URL.format(commit=commit)
    print(f"[interlinear] downloading globalbibletools/data @ {commit[:8]} …", file=sys.stderr)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz") as tmp:
        urllib.request.urlretrieve(url, tmp.name)
        with tempfile.TemporaryDirectory() as extract_dir:
            with tarfile.open(tmp.name) as tf:
                tf.extractall(extract_dir)  # noqa: S202 (trusted, pinned source)
            # GitHub tarballs extract to a single top-level "<repo>-<sha>/" dir
            (extracted,) = Path(extract_dir).iterdir()
            if DATA_DIR.exists():
                import shutil
                shutil.rmtree(DATA_DIR)
            DATA_DIR.parent.mkdir(parents=True, exist_ok=True)
            extracted.rename(DATA_DIR)

    marker.write_text(commit)
    n_langs = sum(1 for d in DATA_DIR.iterdir() if d.is_dir() and not d.name.startswith("."))
    print(f"[interlinear] fetched {n_langs} language dirs -> {DATA_DIR}", file=sys.stderr)
    return DATA_DIR


def fetch_strongs_data(commit: str | None = None) -> Path:
    """Download strongs-greek.txt / strongs-hebrew.txt from the pinned study-app commit. Same
    idempotent-marker pattern as fetch() above."""
    commit = commit or os.environ.get("STUDY_APP_COMMIT") or STUDY_APP_COMMIT
    marker = STRONGS_DATA_DIR / ".commit"
    if STRONGS_DATA_DIR.exists() and marker.exists() and marker.read_text().strip() == commit:
        print(f"[interlinear] strongs-data already fetched at {commit[:8]}, skipping", file=sys.stderr)
        return STRONGS_DATA_DIR

    STRONGS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    for filename in ("strongs-greek.txt", "strongs-hebrew.txt"):
        url = STUDY_APP_STRONGS_BASE.format(commit=commit, filename=filename)
        urllib.request.urlretrieve(url, STRONGS_DATA_DIR / filename)
    marker.write_text(commit)
    print(f"[interlinear] fetched strongs-data @ {commit[:8]} -> {STRONGS_DATA_DIR}", file=sys.stderr)
    return STRONGS_DATA_DIR


if __name__ == "__main__":
    fetch()
    fetch_strongs_data()
