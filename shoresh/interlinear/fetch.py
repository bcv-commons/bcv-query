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
BSB_DATA_DIR = HERE / "data" / "bsb"

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

# BSB-publishing/bsb-data-output — English (Berean Standard Bible) translation lines for
# /interlinear/chapter's translationLines. base/display/ (CC0) has per-chapter word spans with an
# explicit elided-word marker (fixed 2026-07-17, previously a literal "-" placeholder); base/
# headings.jsonl (unchanged path) has section/parallel-passage headings. Small repo (~15MB) — a full
# tarball fetch is simpler than the ~1,189 individual per-chapter raw-file requests this now takes,
# same reasoning as globalbibletools/data above.
#
# Re-pinned 2026-07-17 (a0bcfbb -> dcaf1b0): the first pin still had systemic corruption in `eng`
# spans (visible [bracket]/{brace} markup, literal "vvv" garbage tokens, duplicated-Strong's
# ellipsis spans — reported upstream). Verified at dcaf1b0 across the full Bible (1,189 chapters,
# 30,969 verses): all three bug classes gone; one narrower residual (~92 verses, 0.3%) reported
# separately — see internal-docs/gbt-alignment-handover.md.
BSB_DATA_OUTPUT_COMMIT = "dcaf1b0bfa1aa91394d52613e7aac67b3b058478"
BSB_DATA_OUTPUT_URL = "https://github.com/BSB-publishing/bsb-data-output/archive/{commit}.tar.gz"


def _fetch_tarball(url: str, dest_dir: Path, commit: str, label: str) -> Path:
    """Download + extract a GitHub tarball at a pinned commit to dest_dir. Idempotent — a
    commit-stamped marker file skips re-download if already present at that exact pin."""
    marker = dest_dir / ".commit"
    if dest_dir.exists() and marker.exists() and marker.read_text().strip() == commit:
        print(f"[interlinear] {label} already fetched at {commit[:8]}, skipping", file=sys.stderr)
        return dest_dir

    print(f"[interlinear] downloading {label} @ {commit[:8]} …", file=sys.stderr)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz") as tmp:
        urllib.request.urlretrieve(url, tmp.name)
        with tempfile.TemporaryDirectory() as extract_dir:
            with tarfile.open(tmp.name) as tf:
                tf.extractall(extract_dir)  # noqa: S202 (trusted, pinned source)
            # GitHub tarballs extract to a single top-level "<repo>-<sha>/" dir
            (extracted,) = Path(extract_dir).iterdir()
            if dest_dir.exists():
                import shutil
                shutil.rmtree(dest_dir)
            dest_dir.parent.mkdir(parents=True, exist_ok=True)
            extracted.rename(dest_dir)

    marker.write_text(commit)
    return dest_dir


def fetch(commit: str | None = None) -> Path:
    """Download + extract the pinned globalbibletools/data commit to DATA_DIR."""
    commit = commit or os.environ.get("GBT_DATA_COMMIT") or GBT_DATA_COMMIT
    out = _fetch_tarball(GBT_DATA_URL.format(commit=commit), DATA_DIR, commit, "globalbibletools/data")
    n_langs = sum(1 for d in DATA_DIR.iterdir() if d.is_dir() and not d.name.startswith("."))
    print(f"[interlinear] {n_langs} language dirs -> {DATA_DIR}", file=sys.stderr)
    return out


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


def fetch_bsb(commit: str | None = None) -> Path:
    """Download + extract the pinned BSB-publishing/bsb-data-output commit to BSB_DATA_DIR."""
    commit = commit or os.environ.get("BSB_DATA_OUTPUT_COMMIT") or BSB_DATA_OUTPUT_COMMIT
    return _fetch_tarball(
        BSB_DATA_OUTPUT_URL.format(commit=commit), BSB_DATA_DIR, commit, "BSB-publishing/bsb-data-output"
    )


if __name__ == "__main__":
    fetch()
    fetch_strongs_data()
    fetch_bsb()
