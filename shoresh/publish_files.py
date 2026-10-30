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

A versioned set of other files (e.g. the source-structure cache built for bsb-add-books) is added with --set: every file
named in <dir>/set.json is published as <set>-<file> (flat names: /files/{name} serves no paths), next to the files already
in the manifest. A published name is never given new content: build a new version (v2, ...) instead.

  cd shoresh && .venv/bin/python3 publish_files.py --set source-structure-v1 /path/to/dir
  set.json: {"files": {"heb-open.sqlite.gz": {"license": "...", "source": "...", "description": "..."}, ...}}

files.qombi.com replaces a spine in place, so a pin on its URL breaks with every new build. Each spine build therefore
also gets its own GitHub release in bcv-commons/spine-releases (public, immutable releases): tag <name>-<build date>, one
asset <name>.db.zst, notes with the sha256 of the .zst and of the .db, spine_content_sha256 and what changed. A build
already released (its .db sha256 is in a release's notes) is not released again. For a new build, say what changed:

  cd shoresh && .venv/bin/python3 publish_files.py --changes "adds the columns greek, greekstrong"

The asset and notes are staged in macula/data/public/releases/<tag>/; the gh commands are printed with the others.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
STAGE = HERE / "macula" / "data" / "public"
REMOTE_DIR = "/opt/shoresh/data/public"          # mounted as /data/public in the shoresh container
DEFAULT = ["macula/lexeme-spine-macula.db", "macula/rp2018-spine.db", "macula/tr-textus-receptus-spine.db"]
RELEASE_REPO = "bcv-commons/spine-releases"
RELEASES = STAGE / "releases"
NOTES_DB_SHA = re.compile(r"decompressed[^|]*\| `([0-9a-f]{64})`")   # the .db sha256 in a release's notes
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
            "spine_content_sha256": meta.get("spine_content_sha256", ""),
            "description": DESCRIPTION.get(path.name, ""),
            "modified": datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc)
                        .isoformat(timespec="seconds")}


def released() -> dict[str, tuple[str, str]]:
    """{.db sha256: (tag, asset url)} of the spine releases on GitHub (read without a token)."""
    import urllib.request
    url = f"https://api.github.com/repos/{RELEASE_REPO}/releases?per_page=100"
    with urllib.request.urlopen(url, timeout=30) as r:
        out = {}
        for rel in json.load(r):
            for h in NOTES_DB_SHA.findall(rel.get("body") or ""):
                out[h] = (rel["tag_name"], rel["assets"][0]["browser_download_url"] if rel["assets"] else "")
        return out


def stage_release(path: Path, e: dict, changes: str, tags: set[str]) -> tuple[str, Path, Path]:
    """Write <tag>/<name>.zst and <tag>/NOTES.md for a spine build not yet released; returns (tag, asset, notes)."""
    from compression import zstd
    tag = f"{path.stem}-{e['modified'][:10]}"
    if tag in tags:
        sys.exit(f"{tag} is already released with other content; build again on another day or rename the tag by hand")
    d = RELEASES / tag
    d.mkdir(parents=True, exist_ok=True)
    z = d / f"{path.name}.zst"
    z.write_bytes(zstd.compress(path.read_bytes(), level=19))
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    cols = ", ".join(r[1] for r in db.execute("PRAGMA table_info(spine_words)"))
    tables = ", ".join(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))
    import subprocess
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    (d / "NOTES.md").write_text(f"""`{z.name}`: zstd-compressed `{path.name}` (decompress: `zstd -d {z.name}`, or Python 3.14 `compression.zstd`).

| | sha256 |
|---|---|
| `{z.name}` ({z.stat().st_size:,} bytes) | `{sha256(z)}` |
| `{path.name}` decompressed ({e['bytes']:,} bytes) | `{e['sha256']}` |
| `spine_content_sha256` (in `spine_meta`) | `{e['spine_content_sha256']}` |

Built by bcv-query commit {commit}. Licence: {e['license']}.

**What changed:** {changes}

Tables: {tables}. Columns of spine_words: {cols}.

This asset is never replaced; a new build gets a new release.
""", encoding="utf-8")
    return tag, z, d / "NOTES.md"


def publish_set(name: str, folder: Path) -> int:
    """Add the files of <folder>/set.json as <name>-<file> to the existing manifest (kept as it is otherwise)."""
    spec = json.loads((folder / "set.json").read_text(encoding="utf-8"))["files"]
    current = json.loads((STAGE / "manifest.json").read_text(encoding="utf-8"))
    published = {f["name"]: f for f in current["files"]}
    added = []
    for file, meta in spec.items():
        path = folder / file
        if not path.exists():
            sys.exit(f"missing: {path}")
        if not meta.get("license"):
            sys.exit(f"{file}: no licence in set.json")
        e = {"name": f"{name}-{file}", "bytes": path.stat().st_size, "sha256": sha256(path), "license": meta["license"],
             "source": meta.get("source", ""), "description": meta.get("description", ""), "set": name,
             "modified": datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc)
                         .isoformat(timespec="seconds")}
        old = published.get(e["name"])
        if old and old["sha256"] != e["sha256"]:
            sys.exit(f"refusing {e['name']}: already published with other content; publish a new version instead")
        published[e["name"]] = e
        added.append((path, e))
    manifest = {"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "files": list(published.values())}
    (STAGE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for path, e in added:
        print(f"{e['name']:40s} {e['bytes'] / 1e6:7.1f} MB  {e['sha256'][:16]}…  {e['license'][:50]}", file=sys.stderr)
    print(f"\nmanifest -> {STAGE / 'manifest.json'}\n\nship (files first, manifest last):", file=sys.stderr)
    for path, e in added:
        print(f"deploy/deploy-data.sh {path} {e['name']} {REMOTE_DIR}")
    print(f"deploy/deploy-data.sh shoresh/{(STAGE / 'manifest.json').relative_to(HERE)} manifest.json {REMOTE_DIR}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", default=DEFAULT, help="paths relative to shoresh/")
    ap.add_argument("--changes", help="what changed since the previous build (release notes of a new spine build)")
    ap.add_argument("--set", nargs=2, metavar=("NAME", "DIR"), help="add a versioned set of files (see above)")
    a = ap.parse_args()
    if a.set:
        return publish_set(a.set[0], Path(a.set[1]).resolve())
    paths = [HERE / f for f in a.files]
    for p in paths:
        if p.name in REFUSE:
            sys.exit(f"refusing {p.name}: {REFUSE[p.name]}")
        if not p.exists():
            sys.exit(f"missing: {p}")
    from macula.spine_stamp import stamp
    for p in paths:                       # the content version the aligner pins; it changes with any row
        stamp(p)
    files = [entry(p) for p in paths]
    for f in files:
        if not f["license"]:
            sys.exit(f"{f['name']}: no licence in its spine_meta; add one before publishing")
    have = released()
    new = []                              # spine builds not yet on GitHub: stage a release each
    for p, f in zip(paths, files):
        if f["sha256"] in have:
            f["release"] = have[f["sha256"]][1]
            continue
        if not a.changes:
            sys.exit(f"{p.name} is a new build ({f['sha256'][:16]}…, not in {RELEASE_REPO}): say what changed with --changes")
        tag, z, notes = stage_release(p, f, a.changes, {t for t, _ in have.values()})
        f["release"] = f"https://github.com/{RELEASE_REPO}/releases/download/{tag}/{z.name}"
        new.append((tag, z, notes))
    names = {f["name"] for f in files}
    try:                                  # keep the published sets (--set) when the spines are republished
        kept = [f for f in json.loads((STAGE / "manifest.json").read_text(encoding="utf-8"))["files"]
                if f.get("set") and f["name"] not in names]
    except (OSError, ValueError, KeyError):
        kept = []
    manifest = {"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "files": files + kept}
    STAGE.mkdir(parents=True, exist_ok=True)
    (STAGE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                                         encoding="utf-8")
    for f in files:
        print(f"{f['name']:32s} {f['bytes'] / 1e6:7.1f} MB  {f['sha256'][:16]}…  {f['license'][:60]}",
              file=sys.stderr)
    print(f"\nmanifest -> {STAGE / 'manifest.json'}\n\nship (releases and files first, manifest last):", file=sys.stderr)
    for tag, z, notes in new:
        print(f"gh release create {tag} shoresh/{z.relative_to(HERE)} -R {RELEASE_REPO} --title {tag} "
              f"--notes-file shoresh/{notes.relative_to(HERE)} --latest=false")
    for p in paths:
        print(f"deploy/deploy-data.sh shoresh/{p.relative_to(HERE)} {p.name} {REMOTE_DIR}")
    print(f"deploy/deploy-data.sh shoresh/{(STAGE / 'manifest.json').relative_to(HERE)} manifest.json {REMOTE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
