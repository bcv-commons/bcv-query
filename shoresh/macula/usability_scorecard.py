#!/usr/bin/env python3
"""Usability scorecard, deterministic part: M1 coverage and shape, plus the contract gate.

Runs over the frozen provider tables from macula.domain_providers, so "now" (P0 = SDBH `core` as
served) and every "later" candidate are measured identically. No LLM calls; seconds to run.

M1, per provider:
  token_cov          share of Old Testament tokens with a Strong's number that /verse would label
  content_token_cov  same, over content tokens only (proper names and function words removed, using the
                     semantic-neighbors pack's own proper_strongs() / non_content_strongs())
  content_type_cov   share of distinct content words that get a label
  book_min           lowest per-book content_token_cov (and which book)
  wordstudy_cov      share of content words with at least one group row (what /wordstudy would list)
  groups, size_med, size_p90   served groups and their sizes (in distinct words)
  label_entropy      entropy in bits of the served label over labelled content tokens; low means a few
                     broad labels cover everything, i.e. labels that don't tell words apart

Contract gate (current serving only, since candidates are not wired into shoresh yet): /verse word shape
on sample verses, and how many /wordstudy lookups would 404 if core/ctx rows were removed.

  cd shoresh && .venv/bin/python3 -m macula.usability_scorecard --report
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import random
import sqlite3
import statistics
import sys
from pathlib import Path

from macula.domain_providers import OUT as PROVIDERS_DIR, SPINE_DB, load_provider

HERE = Path(__file__).resolve().parent
SHORESH = HERE.parent
RESULTS = HERE / "data" / "usability" / "scorecard"
PROVIDERS = ("P0", "P0none", "P1", "P2", "PR-P0", "PR-P2", "P1nb", "P2nb", "PR-P2nb", "A1", "A2", "P2nbmz")


def ot_tokens() -> list[tuple[str, str]]:
    """(book, H####) for every Old Testament token with a Strong's number in spine.db."""
    db = sqlite3.connect(f"file:{SPINE_DB}?mode=ro", uri=True)
    return [(b, f"H{int(s):04d}") for b, s in db.execute(
        "SELECT book, strong FROM spine_words WHERE strong IS NOT NULL "
        "AND (morph LIKE 'He,%' OR morph LIKE 'Ar,%')")]


def excluded_strongs() -> set[str]:
    from macula.build_semantic_neighbors import non_content_strongs, proper_strongs
    return proper_strongs() | non_content_strongs()


def m1(name: str, tokens: list[tuple[str, str]], excluded: set[str]) -> dict:
    rows, groups = load_provider(name, PROVIDERS_DIR)
    served = {s: g for s, _a, g, _sh, sv in rows if sv}
    any_row = {s for s, *_ in rows}
    content = [(b, s) for b, s in tokens if s not in excluded]
    content_types = {s for _b, s in content}

    per_book: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    label_ct: collections.Counter = collections.Counter()
    for b, s in content:
        per_book[b][1] += 1
        if s in served:
            per_book[b][0] += 1
            label_ct[served[s]] += 1
    book_cov = {b: hit / tot for b, (hit, tot) in per_book.items() if tot}
    worst = min(book_cov, key=book_cov.get)
    total_lab = sum(label_ct.values())
    entropy = -sum((n / total_lab) * math.log2(n / total_lab) for n in label_ct.values()) if total_lab else 0.0
    sizes = sorted(collections.Counter(served.values()).values())

    return {
        "provider": name,
        "token_cov": sum(s in served for _b, s in tokens) / len(tokens),
        "content_token_cov": sum(s in served for _b, s in content) / len(content),
        "content_type_cov": len(content_types & set(served)) / len(content_types),
        "book_min": round(book_cov[worst], 4), "book_min_book": worst,
        "wordstudy_cov": len(content_types & any_row) / len(content_types),
        "groups": len(sizes),
        "size_med": statistics.median(sizes) if sizes else 0,
        "size_p90": sizes[int(0.9 * (len(sizes) - 1))] if sizes else 0,
        "label_entropy": round(entropy, 3),
    }


def contract_gate(n_verses: int = 200, seed: int = 13) -> dict:
    """Current serving (CC0 semantic groups since 2026-10): /verse Hebrew word shape, and how many Hebrew
    content words' /wordstudy would 404 (no domains, senses or gloss)."""
    sys.path.insert(0, str(SHORESH))
    import data

    db = sqlite3.connect(f"file:{SPINE_DB}?mode=ro", uri=True)
    verses = db.execute("SELECT DISTINCT book, chapter, verse FROM spine_words WHERE morph LIKE 'He,%'").fetchall()
    sample = random.Random(seed).sample(verses, n_verses)
    shape_errors = labelled = tokens = 0
    for b, c, v in sample:
        for gloss_flag in (False, True):
            for w in (data.verse(b, c, v, "English", gloss_flag).get("spine") or {}).get("words", []):
                if gloss_flag:
                    continue
                tokens += 1
                if "domain" in w:
                    labelled += 1
                    g = w.get("group") or {}
                    if not isinstance(w["domain"], str) or not {"id", "label", "confidence"} <= set(g):
                        shape_errors += 1
    hebrew = {f"H{int(s):04d}" for (s,) in db.execute(
        "SELECT DISTINCT strong FROM spine_words WHERE strong IS NOT NULL AND morph LIKE 'He,%'")}
    would_404 = []
    for strong in sorted(hebrew):
        ws = data.word_study(strong)
        if not ws.get("domains") and not ws.get("senses") and not ws.get("gloss"):
            would_404.append(strong)
    return {"verses_checked": n_verses, "tokens": tokens, "labelled": labelled,
            "verse_shape_errors": shape_errors, "hebrew_strongs": len(hebrew),
            "wordstudy_404": len(would_404), "examples": would_404[:10]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--providers", nargs="*", default=list(PROVIDERS))
    args = ap.parse_args()

    manifest = json.loads((PROVIDERS_DIR / "manifest.json").read_text(encoding="utf-8"))
    tokens, excluded = ot_tokens(), excluded_strongs()
    results = []
    for name in args.providers:
        if name not in manifest["providers"]:
            print(f"[scorecard] skip {name}: not in provider manifest", file=sys.stderr)
            continue
        rec = m1(name, tokens, excluded)
        rec["members_sha256"] = manifest["providers"][name]["members"]
        results.append(rec)
    gate = contract_gate()

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "m1.json").write_text(json.dumps({"m1": results, "contract_gate": gate}, indent=2,
                                                ensure_ascii=False) + "\n", encoding="utf-8")

    if args.report:
        cols = ("token_cov", "content_token_cov", "content_type_cov", "book_min", "wordstudy_cov",
                "groups", "size_med", "size_p90", "label_entropy")
        print(f"{'provider':10}" + "".join(f"{c:>18}" for c in cols))
        for r in results:
            cells = []
            for c in cols:
                v = r[c]
                cells.append(f"{v:18.3f}" if isinstance(v, float) else f"{v:>18}")
            print(f"{r['provider']:10}" + "".join(cells) + f"   worst book: {r['book_min_book']}")
        print(f"\ncontract gate: {json.dumps(gate, ensure_ascii=False)}")
    print(f"[scorecard] -> {RESULTS / 'm1.json'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
