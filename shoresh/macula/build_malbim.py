#!/usr/bin/env python3
"""Malbim, Beur HaMilot: near-synonym pairs Malbim sets out to distinguish. Hebrew explaining Hebrew.

Malbim (Meir Leibush Wisser, 19th c.) holds that the Bible has no true synonyms, and his word commentary
(Beur HaMilot, on the Prophets and Writings) explains the difference between words that stand side by
side in a verse: `<b>גוי, עם.</b> ההבדל ביניהם...` ("nation, people: the difference between them..."),
`<b>פצע וחבורה.</b>`. A pair he distinguishes is, by his own premise, a pair of near-synonyms. Hebrew
text Public Domain, via Sefaria ("On Your Way" edition).

Extraction:
  - a bold heading of exactly two items ("X, Y" or "X וY"); each item is resolved through its own verse
    in lexeme-spine.db (surface or lemma, consonants only), as in build_metzudat_zion.py;
  - the explicit phrase נרדף עם ("synonymous with") X in a comment body: the heading word and X, with X
    resolved by consonants against Biblical Hebrew lemmas and kept only if unique;
  - proper names and function words are dropped on both sides; the two Strong's numbers must differ.

  cd shoresh && .venv/bin/python3 -m macula.build_malbim            # fetch (resumable) + extract
  cd shoresh && .venv/bin/python3 -m macula.build_malbim --no-fetch
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine.common import to_modern_form  # noqa: E402

from macula.build_metzudat_zion import _bare_index, _get, _resolve_gloss, chapter_counts, excluded  # noqa: E402
from macula.build_sefer_hashorashim import BOOK_MAP  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPINE = HERE / "lexeme-spine.db"
CACHE = HERE / "data" / "malbim_beur_hamilot_chapters.jsonl"
OUT = ROOT / "resources" / "malbim" / "candidate_pairs.tsv"
TORAH = {"Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy"}
_SYN = re.compile(r"נרדף\s+(?:עם|ל|את)\s*(?:פעל\s+|שם\s+)?([א-ת][א-ת֑-ׇ]*)")


def fetch() -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if CACHE.exists():
        done = {json.loads(l)["ref"] for l in CACHE.read_text(encoding="utf-8").splitlines() if l}
    with CACHE.open("a", encoding="utf-8") as fh:
        for book, n_ch in chapter_counts().items():
            if book in TORAH:
                continue
            for ch in range(1, n_ch + 1):
                ref = f"Malbim Beur Hamilot on {book} {ch}"
                if ref in done:
                    continue
                d = _get(ref)
                v = (d or {}).get("versions") or []
                if not v or not v[0].get("text"):
                    if ch == 1:
                        print(f"[malbim] no Beur HaMilot for {book}", file=sys.stderr)
                        break
                    continue
                fh.write(json.dumps({"ref": ref, "book": BOOK_MAP[book], "chapter": ch,
                                     "license": v[0].get("license"), "version": v[0].get("versionTitle"),
                                     "verses": v[0]["text"]}, ensure_ascii=False) + "\n")
                fh.flush()
                time.sleep(0.15)
            print(f"[malbim] {book} done", file=sys.stderr)


def _items(head: str) -> list[str]:
    """'גוי, עם' / 'פצע וחבורה' -> the two items; anything else -> []."""
    head = re.sub(r"[.:]\s*$", "", head.strip())
    parts = [p.strip() for p in head.split(",") if p.strip()]
    if len(parts) == 1:
        words = parts[0].split()
        if len(words) == 2 and words[1].startswith("ו") and len(words[1]) > 2:
            parts = words
    return parts if len(parts) == 2 else []


def _in_verse(item: str, vwords, drop: set[str]) -> set[str]:
    for w in item.split():
        b = to_modern_form(w, "hbo")
        hits = {s for sb, lb, s in vwords if b and (b == sb or b == lb) and s not in drop}
        if hits:
            return hits
    return set()


def extract() -> collections.Counter:
    from macula.build_sefer_hashorashim import _verse_words

    drop = excluded()
    idx = _bare_index(drop)
    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    code2name = {v: k for k, v in BOOK_MAP.items()}
    pairs: collections.Counter = collections.Counter()
    stats = collections.Counter()
    for line in CACHE.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        for vi, comments in enumerate(row["verses"], start=1):
            comments = comments if isinstance(comments, list) else [comments]
            if not any(comments):
                continue
            vwords = _verse_words(f"{code2name[row['book']]} {row['chapter']}:{vi}", sp)
            for c in comments:
                m = re.match(r"\s*<b>([^<]+)</b>\s*\.?\s*(.*)", c or "", re.S)
                if not m:
                    continue
                stats["comments"] += 1
                items = _items(m.group(1))
                if items:
                    stats["two_item_heads"] += 1
                    a, b = (_in_verse(x, vwords, drop) for x in items)
                    if len(a) == 1 and len(b) == 1 and a != b:
                        pairs[frozenset(a | b)] += 1
                        stats["head_pairs"] += 1
                body = re.sub(r"<[^>]+>", "", m.group(2))
                for syn in _SYN.findall(body):
                    heads = _in_verse(m.group(1), vwords, drop)
                    hits = _resolve_gloss(syn, idx)
                    if len(heads) == 1 and len(hits) == 1 and heads != hits:
                        pairs[frozenset(heads | hits)] += 1
                        stats["nirdaf_pairs"] += 1
    print(f"[malbim] {dict(stats)} -> {len(pairs)} distinct pairs", file=sys.stderr)
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-fetch", action="store_true")
    args = ap.parse_args()
    if not args.no_fetch:
        fetch()
    pairs = extract()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        fh.write("# CANDIDATE Hebrew Strong's pairs from Malbim, Beur HaMilot (19th c.; Hebrew text Public Domain, "
                 "via Sefaria):\n# word pairs Malbim distinguishes (two-item headings) or calls synonymous "
                 "(נרדף עם). Derived data CC0.\n# `count` = number of comments giving the pair. See "
                 "shoresh/macula/build_malbim.py.\n")
        fh.write("strong_a\tstrong_b\tcount\n")
        for pair, cnt in sorted(pairs.items(), key=lambda kv: (-kv[1], sorted(kv[0]))):
            a, b = sorted(pair)
            fh.write(f"{a}\t{b}\t{cnt}\n")
    print(f"[malbim] -> {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
