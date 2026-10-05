"""Publish data files for direct download from shoresh (GET /files, GET /files/{name}).

Downstream projects (the lexeme-aligner first) used to receive the spines as hand-copied files. Instead,
shoresh serves an allowlist of files from its data volume: `manifest.json` lists each file with its size,
sha256, licence and source, and only files listed there can be downloaded. Consumers download by URL and
verify the sha256 against the manifest.

This script writes the manifest for the chosen files and prints the commands that ship them to the host's
data volume (deploy/deploy-data.sh: atomic swap, previous version kept as .bak). The manifest goes last,
so it never lists a file whose new version has not arrived yet. Only openly licensed files belong here:
the BHSA-bearing spines (lexeme-spine.db and its baseline copy; BHSA is CC BY-NC-SA) are refused.

  cd shoresh && .venv/bin/python3 publish_files.py              # the default set below
  cd shoresh && .venv/bin/python3 publish_files.py macula/rp2018-spine.db
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
STAGE = HERE / "macula" / "data" / "public"
REMOTE_DIR = "/opt/shoresh/data/public"          # mounted as /data/public in the shoresh container
DEFAULT = ["macula/lexeme-spine-macula.db", "macula/rp2018-spine.db", "macula/tr-textus-receptus-spine.db"]
REFUSE = {"lexeme-spine.db": "carries BHSA-derived columns (CC BY-NC-SA)",
          "lexeme-spine-bhsa-baseline.db": "carries BHSA-derived columns (CC BY-NC-SA)"}
DESCRIPTION = {
    "lexeme-spine-macula.db": "Original-language token spine (Hebrew WLC + Greek Nestle 1904) from MACULA, "
                              "one row per token with lexeme, Strong's, gloss, morphology and syntax roles "
                              "(spine_words), no BHSA-derived columns. The lexeme-aligner's active spine.",
    "rp2018-spine.db": "Greek NT spine for the Robinson-Pierpont 2018 Byzantine Textform, same schema.",
    "tr-textus-receptus-spine.db": "Greek NT spine for the Textus Receptus (Robinson), same schema.",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def spine_meta(path: Path) -> dict:
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        return dict(db.execute("SELECT key, value FROM spine_meta").fetchall())
    except sqlite3.Error:
        return {}


def entry(path: Path) -> dict:
    meta = spine_meta(path)
    source = "; ".join(v for k, v in sorted(meta.items()) if k.startswith("source_") and not k.endswith("sha256"))
    return {"name": path.name, "bytes": path.stat().st_size, "sha256": sha256(path),
            "license": meta.get("license", ""), "source": source,
            "description": DESCRIPTION.get(path.name, ""),
            "modified": datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc)
                        .isoformat(timespec="seconds")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", default=DEFAULT, help="paths relative to shoresh/")
    a = ap.parse_args()
    paths = [HERE / f for f in a.files]
    for p in paths:
        if p.name in REFUSE:
            sys.exit(f"refusing {p.name}: {REFUSE[p.name]}")
        if not p.exists():
            sys.exit(f"missing: {p}")
    files = [entry(p) for p in paths]
    for f in files:
        if not f["license"]:
            sys.exit(f"{f['name']}: no licence in its spine_meta; add one before publishing")
    manifest = {"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "files": files}
    STAGE.mkdir(parents=True, exist_ok=True)
    (STAGE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                                         encoding="utf-8")
    for f in files:
        print(f"{f['name']:32s} {f['bytes'] / 1e6:7.1f} MB  {f['sha256'][:16]}…  {f['license'][:60]}",
              file=sys.stderr)
    print(f"\nmanifest -> {STAGE / 'manifest.json'}\n\nship (files first, manifest last):", file=sys.stderr)
    for p in paths:
        print(f"deploy/deploy-data.sh shoresh/{p.relative_to(HERE)} {p.name} {REMOTE_DIR}")
    print(f"deploy/deploy-data.sh shoresh/{(STAGE / 'manifest.json').relative_to(HERE)} manifest.json {REMOTE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
