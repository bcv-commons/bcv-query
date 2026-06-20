"""B1: ingest a Clear-Bible/Alignments target Bible as searchable verse chunks.

Emits one markdown file per verse (frontmatter tags + body text) under
ingest/_staging/<version>/, mirroring ingest/bsb.py — then
`python -m indexer.build --source ingest/_staging/<version>` turns them into
kind:bible chunks (FTS via chunks_fts_bible + display) in index.db. This is
what makes a non-English Bible actually searchable and renderable; concept
expansion (Strong's tags) already worked, but FTS was querying English text.

Generic over language + version (reuses ingest.clear_aligned, which is the same
reader the A2 lexicon is built from). Reads the extracted Alignments data cached
by scripts/build_aligned_all.py (.cache/alignments/extracted/<iso3>/data).

  python -m ingest.aligned_bible --build              # spa / RV09 -> lang:es, then index
  python -m ingest.aligned_bible --iso por --version JFA11 --lang pt --build

Without --build it only stages markdown; finish with
`python -m indexer.build --source ingest/_staging/<version>`.

Verse paths are prefixed with the version (RV09/<USFM>/…) so the relative-path
doc-id hash never collides with another resource's verses (e.g. bsb's verses/…).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import yaml

from indexer.references import decode
from lang import canon, to_web
from ingest.clear_aligned import read_aligned

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STAGING = REPO_ROOT / "ingest" / "_staging"
DEFAULT_CACHE = REPO_ROOT / ".cache" / "alignments" / "extracted"
DEFAULT_DB = REPO_ROOT / "indexer" / "index.db"

# RV09 (Reina-Valera 1909) = public domain; alignment = CC-BY-4.0.
ORG = {"RV09": "reina-valera"}


def emit(iso: str, version: str, lang: str, data_dir: Path, out_root: Path) -> dict:
    """Write one markdown file per verse. Returns counts."""
    # Clear stale emit so removed verses don't leave orphans.
    if out_root.is_dir():
        for old in out_root.rglob("*.md"):
            old.unlink()

    org = ORG.get(version)
    n = skipped = 0
    for v in read_aligned(data_dir, iso, version):
        text = (v["text"] or "").strip()
        if not text:
            skipped += 1
            continue
        try:
            book, chap, vnum = decode(v["ref"])          # bbcccvvv -> USFM, ch, vs
        except (ValueError, KeyError):
            skipped += 1
            continue

        tags = [
            "kind:bible",
            f"book:{book}",
            f"lang:{to_web(canon(lang))}",
            f"resource:{version.lower()}",
        ]
        if org:
            tags.append(f"org:{org}")
        tags += [f"strongs:{s}" for s in v["strongs"]]

        front = {
            "title": f"{version} — {book} {chap}:{vnum}",
            "tags": sorted(set(tags)),
            "passages": [[v["ref"], v["ref"]]],
        }
        out_dir = out_root / book / str(chap)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{chap:03d}_{vnum:03d}.md").write_text(
            "---\n" + yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip()
            + "\n---\n\n" + text + "\n",
            encoding="utf-8",
        )
        n += 1
    return {"verses": n, "skipped": skipped}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iso", default="spa", help="ISO-639-3 dir name (spa, por, …)")
    ap.add_argument("--version", default="RV09", help="aligned version (RV09, JFA11, …)")
    ap.add_argument("--lang", default="es", help="our language code for lang: tag")
    ap.add_argument("--data-dir", type=Path,
                    help="Alignments data/ dir (default: the build_aligned_all cache)")
    ap.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--build", action="store_true",
                    help="run indexer.build on the staged verses afterwards")
    args = ap.parse_args()

    data_dir = args.data_dir or (DEFAULT_CACHE / args.iso / "data")
    if not data_dir.exists():
        print(f"missing aligned data: {data_dir}\n"
              f"run: python3 scripts/build_aligned_all.py --langs {args.iso}",
              file=sys.stderr)
        return 2

    # All aligned Bibles stage under a shared `aligned/` root, each in its own
    # <VERSION>/ subdir. Building with --source = the aligned/ root means the
    # version is part of every file's path-relative-to-root, so the markdown
    # adapter's doc-id hash (sha256 of that relative path) is unique per
    # version — otherwise every translation's "JHN/3/003_016.md" collides and
    # later ingests overwrite earlier ones. It also lets all versions be built
    # in ONE pass (one FTS rebuild), which is both faster and avoids repeated
    # external-content FTS5 rebuilds.
    aligned_root = args.staging / "aligned"
    out_root = aligned_root / args.version
    started = time.time()
    counts = emit(args.iso, args.version, args.lang, data_dir, out_root)
    print(f"{args.version} ({args.lang}): {counts['verses']} verses → {out_root} "
          f"({counts['skipped']} skipped, {round(time.time()-started,1)}s)", file=sys.stderr)

    if args.build:
        print(f"building all aligned Bibles → {args.db}", file=sys.stderr)
        return subprocess.run(
            [sys.executable, "-m", "indexer.build",
             "--source", str(aligned_root), "--db", str(args.db)],
            cwd=REPO_ROOT,
        ).returncode
    print(f"next: python -m indexer.build --source {aligned_root}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
