#!/usr/bin/env python3
"""Download UBS Hebrew + Greek dictionaries from BibleAquifer and build
a multilingual strongs_gloss.tsv.

Sources:
  - BibleAquifer/UBSHebrewDictionary  (eng, fra, por, spa, zhs, zht)
  - BibleAquifer/UBSGreekNTDictionary (eng, fra, spa, zhs, zht)
  - Existing strongs_gloss.tsv        (eng — keeps translit column)

Output: strongs_gloss.tsv with columns: strong, gloss, translit, lang

License: UBS dictionaries are CC BY-SA 4.0 via Aquifer.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

REPOS = {
    "UBSHebrewDictionary": "H",
    "UBSGreekNTDictionary": "G",
}

GITHUB_RAW = "https://raw.githubusercontent.com/BibleAquifer"
GITHUB_API = "https://api.github.com/repos/BibleAquifer"

OUTPUT = Path(__file__).resolve().parents[2] / "resources" / "strongs_gloss.tsv"
EXISTING = Path(__file__).resolve().parent.parent.parent / "shoresh" / "spine" / "strongs_gloss.tsv"


def _fetch_json(url: str) -> list | dict:
    req = urllib.request.Request(url, headers={"User-Agent": "bcv-query/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _list_files(repo: str, lang: str) -> list[str]:
    url = f"{GITHUB_API}/{repo}/contents/{lang}/json"
    items = _fetch_json(url)
    return sorted(f["name"] for f in items if f["name"].endswith(".content.json"))


def _extract_entries(repo: str, lang: str, prefix: str) -> dict[str, str]:
    """Returns {strong_code: gloss} for one repo+language."""
    files = _list_files(repo, lang)
    entries: dict[str, str] = {}

    for fname in files:
        url = f"{GITHUB_RAW}/{repo}/main/{lang}/json/{fname}"
        try:
            data = json.loads(urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": "bcv-query/1.0"}),
                timeout=30,
            ).read())
        except Exception as e:
            print(f"  skip {fname}: {e}", file=sys.stderr)
            continue

        for article in data:
            content = article.get("content", "")
            strongs = re.findall(r"([HG]\d{4,5}[a-z]?)", content)
            if not strongs:
                continue
            strong = strongs[0]
            if not strong.startswith(prefix):
                continue

            glosses = re.findall(r'lex-gloss[^>]*>([^<]+)<', content)
            if glosses:
                entries[strong] = glosses[0].strip()

    return entries


def _load_existing() -> dict[str, tuple[str, str]]:
    """Load existing English gloss file → {strong: (gloss, translit)}."""
    result: dict[str, tuple[str, str]] = {}
    if not EXISTING.exists():
        return result
    with EXISTING.open(encoding="utf-8") as fh:
        next(fh, None)
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3:
                result[parts[0]] = (parts[1], parts[2])
            elif len(parts) == 2:
                result[parts[0]] = (parts[1], "")
    return result


def main():
    existing = _load_existing()
    print(f"Loaded {len(existing)} existing English entries", file=sys.stderr)

    # Collect all languages per repo
    all_langs: dict[str, dict[str, dict[str, str]]] = {}  # {lang: {strong: gloss}}

    for repo, prefix in REPOS.items():
        # Discover available languages
        contents = _fetch_json(f"{GITHUB_API}/{repo}/contents/")
        langs = [f["name"] for f in contents
                 if f["type"] == "dir" and len(f["name"]) == 3 and f["name"] != "eng"]

        for lang in langs:
            print(f"Extracting {repo} / {lang}...", file=sys.stderr)
            entries = _extract_entries(repo, lang, prefix)
            print(f"  → {len(entries)} entries", file=sys.stderr)
            if lang not in all_langs:
                all_langs[lang] = {}
            all_langs[lang].update(entries)

    # Map Aquifer lang codes to our canonical tags (ISO 639-3 / BCP 47)
    LANG_MAP = {
        "fra": "fra",
        "por": "por",
        "spa": "spa",
        "zhs": "cmn-Hans",
        "zht": "cmn-Hant",
    }

    # Build output rows: strong, gloss, translit, lang
    rows: list[tuple[str, str, str, str]] = []

    # English from existing file (preserves translit)
    for strong, (gloss, translit) in sorted(existing.items()):
        rows.append((strong, gloss, translit, "eng"))

    # Other languages from UBS dictionaries
    for aquifer_lang, entries in sorted(all_langs.items()):
        lang = LANG_MAP.get(aquifer_lang, aquifer_lang)
        for strong, gloss in sorted(entries.items()):
            translit = existing.get(strong, ("", ""))[1]
            rows.append((strong, gloss, translit, lang))

    # Write output — canonical padded codes (G26→G0026) so the gloss file
    # joins cleanly with strongs_freq/keyness/strong_lemma (all padded).
    def _pad(c: str) -> str:
        m = re.match(r"^([HG])(\d+)([a-z]?)$", c)
        return f"{m.group(1)}{int(m.group(2)):04d}{m.group(3)}" if m else c

    with OUTPUT.open("w", encoding="utf-8") as fh:
        fh.write("strong\tgloss\ttranslit\tlang\n")
        for strong, gloss, translit, lang in rows:
            fh.write(f"{_pad(strong)}\t{gloss}\t{translit}\t{lang}\n")

    # Summary
    lang_counts: dict[str, int] = {}
    for _, _, _, lang in rows:
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
    print(f"\nWrote {len(rows)} total entries to {OUTPUT}", file=sys.stderr)
    for lang, count in sorted(lang_counts.items()):
        print(f"  {lang}: {count}", file=sys.stderr)


if __name__ == "__main__":
    main()
