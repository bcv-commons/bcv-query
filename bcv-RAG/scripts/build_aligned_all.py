#!/usr/bin/env python3
"""Build aligned_lex/<lang>.tsv for EVERY language published by
Clear-Bible/Alignments — fetched from the repo's `data-latest` release.

The release exposes one self-contained zip per language
(`alignments-<iso3>.zip`) that bundles the shared original-language sources
(SBLGNT / WLCM) plus that language's targets + alignments for all 66 books.
So onboarding a language is just: download its asset, unzip, run the emitter.
No 186 MB git clone, no manual file shuffling.

Pipeline per language:
  1. download alignments-<iso3>.zip  -> .cache/alignments/zips/   (skip if cached)
  2. unzip                           -> .cache/alignments/extracted/<iso3>/  (skip if present)
  3. discover aligned versions, aggregate surface→Strong's (build_aligned_lex)
  4. write aligned_lex/<code>.tsv    (code = our 2-letter where one exists)

The .cache/ tree is git-ignored and re-derivable; only aligned_lex/*.tsv is
committed (like glosses_llm/*.tsv). The cached extracts are also what B1
(verse-text → index.db) will later read, so they're worth keeping around.

Usage:
  python3 scripts/build_aligned_all.py                 # all languages
  python3 scripts/build_aligned_all.py --langs spa,fra # subset (iso3 or 2-letter)
  python3 scripts/build_aligned_all.py --list          # just list what's available
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from scripts.build_aligned_lex import discover_versions, emit_lexicon  # noqa: E402
from lang import canon                                                  # noqa: E402

RELEASE_API = ("https://api.github.com/repos/Clear-Bible/Alignments/"
               "releases/tags/data-latest")
CACHE = HERE / ".cache" / "alignments"
OUT_DIR = HERE.parent / "resources" / "aligned_lex"

# The Clear-Bible asset/dir name is the ISO-639-3 code, which IS our canonical
# language tag — so the output file is <iso3>.tsv directly. canon() maps any
# legacy 2-letter / BCP-47 input on the CLI to that canonical form.


def list_assets() -> dict[str, str]:
    """{iso3: download_url} for every alignments-<iso3>.zip in the release."""
    with urllib.request.urlopen(RELEASE_API, timeout=60) as resp:
        rel = json.loads(resp.read())
    out: dict[str, str] = {}
    for a in rel.get("assets", []):
        m = re.match(r"alignments-([a-z]{3})\.zip$", a["name"])
        if m and m.group(1) != "leg":            # skip alignments-legacy.zip
            out[m.group(1)] = a["browser_download_url"]
    return out


def fetch_extract(iso3: str, url: str) -> Path:
    """Download + unzip the language asset (idempotent). Returns its data/ dir."""
    zips = CACHE / "zips"
    extracted = CACHE / "extracted" / iso3
    data_dir = extracted / "data"
    if data_dir.exists():
        return data_dir
    zips.mkdir(parents=True, exist_ok=True)
    zpath = zips / f"{iso3}.zip"
    if not zpath.exists():
        print(f"  downloading {url} …", file=sys.stderr)
        tmp = zpath.with_suffix(".zip.part")
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(zpath)
    print(f"  extracting {zpath.name} …", file=sys.stderr)
    extracted.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(extracted)
    return data_dir


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", help="comma-separated subset (iso3 or 2-letter)")
    ap.add_argument("--min-count", type=int, default=1)
    ap.add_argument("--list", action="store_true", help="list available, run nothing")
    args = ap.parse_args()

    assets = list_assets()
    if args.langs:
        want = {canon(x.strip()) for x in args.langs.split(",")}  # accept 2-letter too
        assets = {k: v for k, v in assets.items() if k in want}

    print(f"{len(assets)} language asset(s): {', '.join(sorted(assets))}",
          file=sys.stderr)
    if args.list:
        return

    OUT_DIR.mkdir(exist_ok=True)
    summary = []
    for iso3 in sorted(assets):
        code = iso3                          # iso3 IS the canonical tag
        print(f"\n=== {iso3} -> aligned_lex/{code}.tsv ===", file=sys.stderr)
        try:
            data_dir = fetch_extract(iso3, assets[iso3])
            versions = discover_versions(data_dir, iso3)
            if not versions:
                print(f"  no aligned versions found; skipping", file=sys.stderr)
                continue
            st = emit_lexicon(data_dir, iso3, versions, OUT_DIR / f"{code}.tsv",
                              args.min_count)
            print(f"  {'+'.join(versions)}: {st['verses']} verses, "
                  f"{st['surfaces']} surfaces, {st['rows']} rows, "
                  f"{st['codes']} codes", file=sys.stderr)
            summary.append((code, iso3, st))
        except Exception as e:
            print(f"  FAILED {iso3}: {e}", file=sys.stderr)

    print("\n=== aligned_lex summary ===", file=sys.stderr)
    print(f"  {'lang':6} {'iso3':5} {'versions':18} {'verses':>7} "
          f"{'surfaces':>9} {'rows':>7} {'codes':>6}", file=sys.stderr)
    for code, iso3, st in summary:
        print(f"  {code:6} {iso3:5} {'+'.join(st['versions']):18} "
              f"{st['verses']:>7} {st['surfaces']:>9} {st['rows']:>7} "
              f"{st['codes']:>6}", file=sys.stderr)


if __name__ == "__main__":
    main()
