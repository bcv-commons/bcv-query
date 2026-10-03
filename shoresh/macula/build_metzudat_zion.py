#!/usr/bin/env python3
"""Metzudat Zion word-gloss pairs: Hebrew explaining Hebrew.

Metzudat Zion (David and Hillel Altschuler, 18th c.) is a word-by-word glossary-commentary on the
Prophets and Writings. Each comment quotes a word of the verse in bold and explains it, very often with
another Hebrew word: `<b>לידידי.</b> אהובי` ("to my beloved: my loved one"), or with the sense marker
ענין: `<b>בנאות.</b> ענין מדור` ("in the sense of dwelling"). Hebrew text Public Domain, via Sefaria
("On Your Way" edition). A Hebrew-internal synonym signal from the Jewish exegetical tradition, of a
different kind from Radak's root dictionary (build_sefer_hashorashim.py).

Extraction, deliberately narrow:
  - the bold head word is resolved through its own verse in lexeme-spine.db (surface or lemma,
    consonants only), the same verse-anchored resolution as build_sefer_hashorashim;
  - the gloss is the first word of the comment, or the word after ענין; comments that open with an
    etymology (מלשון, מל׳, תרגום) or a parallel citation (וכן, כמו) are skipped, since those relate a word
    to its own root or to the same word elsewhere, not to a synonym;
  - the gloss word is resolved by consonants against Biblical Hebrew lemmas, trying it as written and
    with one common prefix letter removed; it must resolve to exactly one content Strong's number,
    different from the head's.

  cd shoresh && .venv/bin/python3 -m macula.build_metzudat_zion            # fetch (resumable) + extract
  cd shoresh && .venv/bin/python3 -m macula.build_metzudat_zion --no-fetch
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine.common import to_modern_form  # noqa: E402

from macula.build_sefer_hashorashim import BOOK_MAP  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPINE = HERE / "lexeme-spine.db"
CACHE = HERE / "data" / "metzudat_zion_chapters.jsonl"
OUT = ROOT / "resources" / "metzudat_zion" / "candidate_pairs.tsv"
API = "https://www.sefaria.org/api/v3/texts/"
TORAH = {"Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy"}
SKIP_OPENERS = ("מלשון", "מל׳", "מל'", "תרגום", "וכן", "כמו", "עיין", "ר״ל", "רצה")
PREFIXES = "והבלמכש"


def _get(ref: str) -> dict | None:
    url = API + urllib.parse.quote(ref) + "?version=hebrew"
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"user-agent": "bcv-query/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(min(2 ** attempt, 20))
    return None


def chapter_counts() -> dict[str, int]:
    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    code2name = {v: k for k, v in BOOK_MAP.items()}
    return {code2name[b]: n for b, n in sp.execute(
        "SELECT book, MAX(chapter) FROM spine_words WHERE lexeme LIKE 'hbo:%' GROUP BY book") if b in code2name}


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
                ref = f"Metzudat Zion on {book} {ch}"
                if ref in done:
                    continue
                d = _get(ref)
                v = (d or {}).get("versions") or []
                if not v or not v[0].get("text"):
                    if ch == 1:
                        print(f"[metzudat-zion] no commentary for {book}", file=sys.stderr)
                        break
                    continue
                fh.write(json.dumps({"ref": ref, "book": BOOK_MAP[book], "chapter": ch,
                                     "license": v[0].get("license"), "version": v[0].get("versionTitle"),
                                     "verses": v[0]["text"]}, ensure_ascii=False) + "\n")
                fh.flush()
                time.sleep(0.15)
            print(f"[metzudat-zion] {book} done", file=sys.stderr)


def excluded() -> set[str]:
    """Proper names, function words, and Strong's numbers with no spine lemma (MACULA-only codes such as
    name compounds) are kept out on both sides of a pair."""
    from macula.build_semantic_neighbors import non_content_strongs, proper_strongs
    from macula.domain_providers import lemma_of
    lemmas = lemma_of()
    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    no_lemma = {f"H{int(s):04d}" for (s,) in sp.execute(
        "SELECT DISTINCT strong FROM spine_words WHERE lexeme LIKE 'hbo:%' AND strong IS NOT NULL")
        if f"H{int(s):04d}" not in lemmas}
    return proper_strongs() | non_content_strongs() | no_lemma


def _bare_index(drop: set[str]) -> dict[str, set[str]]:
    """consonantal lemma -> content Hebrew Strong's numbers."""
    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    idx: dict[str, set[str]] = collections.defaultdict(set)
    for lemma, strong in sp.execute("SELECT DISTINCT lemma, strong FROM spine_words "
                                    "WHERE lexeme LIKE 'hbo:%' AND is_content=1 AND strong IS NOT NULL"):
        s = f"H{int(strong):04d}"
        if lemma and s not in drop:
            idx[to_modern_form(lemma, "hbo")].add(s)
    return idx


def _resolve_gloss(word: str, idx: dict[str, set[str]]) -> set[str]:
    bare = to_modern_form(word, "hbo")
    if len(bare) < 2:
        return set()
    hits = idx.get(bare, set())
    if not hits and bare[0] in PREFIXES and len(bare) > 3:
        hits = idx.get(bare[1:], set())
    return hits


def _gloss_word(body: str) -> str | None:
    words = re.findall(r"[א-ת׳״֑-ׇ״׳'\"]+", body)
    if not words:
        return None
    if words[0].startswith(SKIP_OPENERS):
        return None
    if words[0] == "ענין":
        return words[1] if len(words) > 1 else None
    return words[0]


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
                head = to_modern_form(m.group(1).split()[0] if m.group(1).split() else "", "hbo")
                heads = {s for sb, lb, s in vwords if head and (head == sb or head == lb) and s not in drop}
                if not heads:
                    continue
                stats["head_resolved"] += 1
                gw = _gloss_word(re.sub(r"<[^>]+>", "", m.group(2)))
                if not gw:
                    continue
                stats["gloss_found"] += 1
                hits = _resolve_gloss(gw, idx)
                if len(hits) != 1:
                    continue
                g = next(iter(hits))
                for h in heads:
                    if h != g:
                        pairs[frozenset((h, g))] += 1
                        stats["pairs"] += 1
    print(f"[metzudat-zion] {dict(stats)} -> {len(pairs)} distinct pairs", file=sys.stderr)
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
        fh.write("# CANDIDATE Hebrew Strong's pairs from Metzudat Zion (Altschuler, 18th c.; Hebrew text Public "
                 "Domain, via Sefaria):\n# a verse word and the Hebrew word Metzudat Zion explains it with. "
                 "Derived data CC0. `count` = number of\n# comments giving the pair. See "
                 "shoresh/macula/build_metzudat_zion.py.\n")
        fh.write("strong_a\tstrong_b\tcount\n")
        for pair, cnt in sorted(pairs.items(), key=lambda kv: (-kv[1], sorted(kv[0]))):
            a, b = sorted(pair)
            fh.write(f"{a}\t{b}\t{cnt}\n")
    print(f"[metzudat-zion] -> {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
