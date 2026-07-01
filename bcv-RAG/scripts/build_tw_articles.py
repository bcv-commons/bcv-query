#!/usr/bin/env python3
"""Extract a language's Translation-Words articles into a compact serving resource.

GENERIC — parameterised by language. Reads an extracted `<lang>_tw` Door43 repo and
the language-neutral Strong's→slug map (the existing `resources/strongs_tw.tsv`), and
writes `resources/tw_articles/<lang3>.json` = {slug: {title, definition}}. Only the
slugs that a Strong's number actually maps to are kept (the rest are unreachable from
a word). `strongs_tw.tsv` supplies strong→slug; this adds the localized article TEXT.

Article shape (unfoldingWord tw markdown):
    # term, synonyms
    ## Definition:            (or a localized heading)
    <prose>
    ## Translation Suggestions:  ← definition ends here
So the "definition" = the prose between the title and the first `##` subsection.

Usage:
    python3 scripts/build_tw_articles.py --lang ind --tw <extracted lang_tw dir>
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAP = ROOT / "resources" / "strongs_tw.tsv"        # existing strong -> slug map (tw_article column)


def _wanted_slugs() -> set[str]:
    import csv
    with MAP.open(encoding="utf-8") as fh:
        return {r["tw_article"] for r in csv.DictReader(fh, delimiter="\t") if r.get("tw_article")}


def _parse_article(md: str) -> tuple[str, str]:
    """(title, definition) from a tw markdown article. The definition is the prose of
    the first `## ` section (the "Definition" heading); if the article has no
    subsections, all prose after the title."""
    lines = md.splitlines()
    title = ""
    idx = 0
    for i, ln in enumerate(lines):
        if ln[:2] == "# ":
            title = ln[2:].strip(); idx = i + 1; break
    rest = lines[idx:]
    has_heading = any(l.startswith("## ") for l in rest)
    body: list[str] = []
    in_sec = False
    for ln in rest:
        if ln.startswith("## "):
            if in_sec:                              # reached the NEXT subsection → stop
                break
            in_sec = True                           # first `## ` = the definition heading
            continue
        if in_sec or not has_heading:
            body.append(ln)
    definition = re.sub(r"\n{2,}", "\n", "\n".join(body)).strip()
    definition = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", definition)   # strip md links
    return title, definition


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, help="ISO 639-3 output key, e.g. ind")
    ap.add_argument("--tw", required=True, help="extracted <lang>_tw repo dir")
    args = ap.parse_args()
    wanted = _wanted_slugs()
    out: dict[str, dict] = {}
    missing = 0
    for md in Path(args.tw).rglob("*.md"):
        # slug = bible/<cat>/<name>  (path tail under the repo)
        parts = md.with_suffix("").parts
        if "bible" not in parts:
            continue
        slug = "/".join(parts[parts.index("bible"):])
        if slug not in wanted:
            continue
        title, definition = _parse_article(md.read_text(encoding="utf-8", errors="replace"))
        if title and definition:
            out[slug] = {"title": title, "definition": definition}
    for s in wanted:
        if s not in out:
            missing += 1
    dest = ROOT / "resources" / "tw_articles" / f"{args.lang}.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8")
    print(f"wrote {dest}: {len(out)} articles ({missing}/{len(wanted)} wanted slugs absent in {args.lang}_tw)")


if __name__ == "__main__":
    main()
