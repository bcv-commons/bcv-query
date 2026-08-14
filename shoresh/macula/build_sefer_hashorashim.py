#!/usr/bin/env python3
"""Sefer HaShorashim ("Book of Roots") candidate pairs — Radak (Rabbi David Kimchi, Provence,
c.1185-1235 CE), a medieval Hebrew root dictionary from WITHIN the Jewish exegetical tradition, a
genuinely different lineage from BDB (19th-c. German-Protestant biblical criticism) and Wiktionary
(modern crowd-sourced). Public Domain, hosted + API-served by Sefaria (Sefaria requires every text in
its library to carry an open license — Public Domain/CC0/CC-BY/CC-BY-SA).

Prototyped 2026-08 against a naive BDB-prose extraction (see build_wiktionary_roots.py-era session
notes / domain-replacement-roadmap.md) — Sefer HaShorashim's candidates came out cleaner (35.6% SDBH
core-agreement pre-LLM vs. BDB-prose's 15.5%, SDBH-era measurement) and far cheaper to fully build
(~10-15k candidate pairs vs. BDB-prose's ~200k), so this is the one that got built out fully. SDBH
retired as the validation yardstick 2026-08-14 (internal-docs/text-anchored-semantics-plan.md);
`--validate` now scores against the text-anchored intrinsic yardstick instead.

Method: page through every dictionary entry via Sefaria's `next` ref chain (DictionaryNode text,
~1,500-3,000 entries — no bulk-export endpoint, so this is ~1 API call per entry). Within each entry,
extract every `<strong>form</strong>` (a Hebrew word form Radak discusses) and pair it with the nearest
FOLLOWING biblical verse citation. Resolve each form to a Strong's number by looking up that exact
verse's actual words in `lexeme-spine.db` (surface OR lemma match, bare-consonant-normalized) — this
verse-anchored resolution is far more reliable than blind bare-consonant matching alone (validated
2026-08: 38.9% vs ~18% hit rate), since Radak typically cites the INFLECTED verse-form, not a dictionary
lemma. All Strong's resolved within one entry become a candidate pair set (combinations) — these are
CANDIDATES, not verified pairs: a bold form can be the entry's own root family, a rival etymological
theory Radak cites for comparison, or an Aramaic/comparative-Semitic cognate — that distinction lives in
surrounding Hebrew prose, not markup, and needs an LLM pass (verify_pairs_llm.py) to resolve, not this
script.

Fetches incrementally to a local JSONL cache (resumable — a crash mid-fetch only costs the in-flight
entry, not the whole run; same lesson learned 2026-08 from an earlier LLM-verification run that lost
~20 minutes of progress to a single network error before its own incremental-write fix).

  python -m macula.build_sefer_hashorashim              # fetch (resumable) + extract + write candidates
  python -m macula.build_sefer_hashorashim --no-fetch    # extract only, from existing cache
"""
from __future__ import annotations

import argparse
import collections
import itertools
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

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPINE = HERE / "lexeme-spine.db"
DATA_DIR = HERE / "data"
CACHE = DATA_DIR / "sefer_hashorashim_entries.jsonl"
OUT_DIR = ROOT / "resources" / "sefer_hashorashim"

API_BASE = "https://www.sefaria.org/api/v3/texts/"
START_REF = "Sefer HaShorashim, אבב"   # the dictionary's first entry (headwordMap['א'][0])

BOOK_MAP = {
    "Genesis": "GEN", "Exodus": "EXO", "Leviticus": "LEV", "Numbers": "NUM", "Deuteronomy": "DEU",
    "Joshua": "JOS", "Judges": "JDG", "Ruth": "RUT", "I Samuel": "1SA", "II Samuel": "2SA",
    "I Kings": "1KI", "II Kings": "2KI", "Isaiah": "ISA", "Jeremiah": "JER", "Ezekiel": "EZK",
    "Hosea": "HOS", "Joel": "JOL", "Amos": "AMO", "Obadiah": "OBA", "Jonah": "JON", "Micah": "MIC",
    "Nahum": "NAM", "Habakkuk": "HAB", "Zephaniah": "ZEP", "Haggai": "HAG", "Zechariah": "ZEC",
    "Malachi": "MAL", "Psalms": "PSA", "Proverbs": "PRO", "Job": "JOB", "Song of Songs": "SNG",
    "Lamentations": "LAM", "Ecclesiastes": "ECC", "Esther": "EST", "Daniel": "DAN", "Ezra": "EZR",
    "Nehemiah": "NEH", "I Chronicles": "1CH", "II Chronicles": "2CH",
}


def _cached_refs() -> set[str]:
    if not CACHE.exists():
        return set()
    refs = set()
    with CACHE.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                refs.add(json.loads(line)["ref"])
            except (json.JSONDecodeError, KeyError):
                continue
    return refs


def _last_cached_entry():
    """(ref, next) of the last cached row, to resume the `next`-chain walk."""
    last = None
    if CACHE.exists():
        with CACHE.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    last = json.loads(line)
                except json.JSONDecodeError:
                    continue
    return last


def fetch(max_entries: int = 0) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    last = _last_cached_entry()
    ref = last["next"] if last and last.get("next") else START_REF
    if last and not last.get("next"):
        print("[sefer-hashorashim] cache already complete (last entry had no `next`)", file=sys.stderr)
        return

    n = len(_cached_refs())
    fh = CACHE.open("a", encoding="utf-8")
    try:
        while ref:
            if max_entries and n >= max_entries:
                break
            url = API_BASE + urllib.parse.quote(ref)
            for attempt in range(5):
                try:
                    with urllib.request.urlopen(url, timeout=20) as resp:
                        d = json.load(resp)
                    break
                except (urllib.error.URLError, TimeoutError, OSError) as e:
                    wait = min(2 ** attempt, 20)
                    print(f"[sefer-hashorashim] network error on {ref!r} (try {attempt+1}): {e} "
                          f"— retrying in {wait}s", file=sys.stderr)
                    time.sleep(wait)
            else:
                print(f"[sefer-hashorashim] giving up on {ref!r} after 5 tries — stopping", file=sys.stderr)
                break
            text = d["versions"][0]["text"][0] if d.get("versions") and d["versions"][0].get("text") else ""
            row = {"ref": ref, "text": text, "next": d.get("next")}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            n += 1
            if n % 100 == 0:
                print(f"[sefer-hashorashim] fetched {n} entries (at {ref!r})", file=sys.stderr)
            ref = d.get("next")
            time.sleep(0.12)
    finally:
        fh.close()
    print(f"[sefer-hashorashim] fetch done — {n} entries cached -> {CACHE}", file=sys.stderr)


def _verse_words(ref_text: str, conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    m = re.match(r"^(.*?)\s+(\d+):(\d+)", ref_text.strip())
    if not m:
        return []
    book = BOOK_MAP.get(m.group(1))
    if not book:
        return []
    out = []
    for surface, lemma, strong in conn.execute(
            "SELECT surface, lemma, strong FROM spine_words WHERE book=? AND chapter=? AND verse=? "
            "AND strong IS NOT NULL AND lexeme LIKE 'hbo:%'",
            (book, int(m.group(2)), int(m.group(3)))):
        out.append((to_modern_form(surface, "hbo"), to_modern_form(lemma, "hbo") if lemma else None,
                    f"H{int(strong):04d}"))
    return out


def extract() -> collections.Counter:
    """Counter[frozenset({H_a, H_b})] -> number of entries corroborating the pair."""
    from macula.build_hwn_benchmark import load_bare_to_strongs
    bare2strongs = load_bare_to_strongs()
    conn = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)

    pairs: collections.Counter = collections.Counter()
    n_entries = n_forms = n_resolved = 0
    with CACHE.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            n_entries += 1
            text = row["text"]
            parts = re.split(r'(<a class="refLink"[^>]*>[^<]*</a>)', text)
            pending: list[str] = []
            entry_strongs: set[str] = set()
            for part in parts:
                forms = [f.strip() for f in re.findall(r"<strong>([^<]+)</strong>", part) if len(f.strip()) > 1]
                if forms:
                    pending.extend(forms)
                m = re.search(r'data-ref="([^"]+)"', part)
                if m and pending:
                    vwords = _verse_words(m.group(1), conn)
                    for f in pending:
                        n_forms += 1
                        fbare = to_modern_form(f, "hbo")
                        matched = {s for sbare, lbare, s in vwords if fbare and (fbare == sbare or fbare == lbare)}
                        if not matched:
                            matched = bare2strongs.get(fbare, set())
                        if matched:
                            n_resolved += 1
                            entry_strongs |= matched
                    pending = []
            # leftover forms with no trailing citation in this entry -> bare-match fallback only
            for f in pending:
                n_forms += 1
                fbare = to_modern_form(f, "hbo")
                matched = bare2strongs.get(fbare, set())
                if matched:
                    n_resolved += 1
                    entry_strongs |= matched
            for a, b in itertools.combinations(sorted(entry_strongs), 2):
                pairs[frozenset((a, b))] += 1

    print(f"[sefer-hashorashim] {n_entries} entries, {n_forms} bold forms, {n_resolved} resolved "
          f"({100*n_resolved/max(n_forms,1):.1f}%) -> {len(pairs)} candidate pairs", file=sys.stderr)
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-fetch", action="store_true", help="skip fetching, extract from existing cache only")
    ap.add_argument("--max-entries", type=int, default=0, help="cap #entries fetched (0 = all)")
    ap.add_argument("--out", type=Path, default=OUT_DIR / "candidate_pairs.tsv")
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()

    if not args.no_fetch:
        fetch(max_entries=args.max_entries)

    pairs = extract()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write("# CANDIDATE Hebrew Strong's pairs from Sefer HaShorashim (Radak, c.1185-1235 CE, "
                  "Public Domain,\n# via Sefaria). Same-entry co-membership only — NOT yet verified: a "
                  "pair can be genuine same-root\n# family, a rival etymological theory Radak cites for "
                  "comparison, or a comparative-Semitic cognate.\n# Needs LLM verification (see "
                  "verify_pairs_llm.py) before treating as a real relation. `count` =\n# number of "
                  "entries the pair co-occurred in. See build_sefer_hashorashim.py.\n")
        fh.write("strong_a\tstrong_b\tcount\n")
        for pair, cnt in sorted(pairs.items(), key=lambda kv: (-kv[1], sorted(kv[0]))):
            a, b = sorted(pair)
            fh.write(f"{a}\t{b}\t{cnt}\n")
    print(f"[sefer-hashorashim] -> {args.out}", file=sys.stderr)

    if args.validate:
        from macula.intrinsic_yardstick import Yardstick, validate_pairs

        ys = Yardstick()
        validate_pairs(ys, "pre-LLM candidate quality", [tuple(p) for p in pairs])
    return 0


if __name__ == "__main__":
    sys.exit(main())
