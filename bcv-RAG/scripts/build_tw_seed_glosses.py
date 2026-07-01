#!/usr/bin/env python3
"""Pre-seed a language's Strong's glosses from mined Translation-Words article titles.

For the key terms + proper names that TW covers, the human-translated article TITLE is
an authoritative gloss — better than an LLM guess, and free. This writes those into
`resources/llm_strongs_glosses/<lang>.tsv` in the SAME format build_llm_glosses.py uses,
so that run treats them as already-done and SKIPS them — the LLM then only fills the long
tail of ordinary vocabulary TW doesn't cover.

Chain: strongs_tw.tsv (strong → primary slug, by n) → tw_articles/<lang3>.json (title).

  python3 scripts/build_tw_seed_glosses.py --lang ind          # writes ind.tsv seed
  python3 scripts/build_tw_seed_glosses.py --lang ind --force   # overwrite an existing file

Run BEFORE build_llm_glosses.py <lang>. GENERIC — parameterised by language.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TW_MAP = ROOT / "resources" / "strongs_tw.tsv"
FREQ = ROOT / "resources" / "strongs_freq.tsv"
ART = ROOT / "resources" / "tw_articles"
OUT_DIR = ROOT / "resources" / "llm_strongs_glosses"
MAX_TERMS = 4                         # cap a synonym-list title to keep the gloss tight
MIN_SHARE = 0.5                       # a word must be DOMINANTLY its top TW concept to seed


def _functions() -> set[str]:
    if not FREQ.exists():
        return set()
    with FREQ.open(encoding="utf-8") as fh:
        return {r["strong"] for r in csv.DictReader(fh, delimiter="\t")
                if (r.get("is_function") or "").strip() in ("1", "true", "True")}


def _primary() -> dict[str, tuple[str, str]]:
    """strong -> (primary slug, lemma) for DOMINANT, non-function words only.

    Gate (same idea as the semantic-domain labels): a function word or a word whose top
    TW slug isn't a majority of its links (e.g. the article ὁ spread across god/jesus/lord,
    or ἅγιος split holy/holyspirit/setapart) gets an incidental concept, not a gloss — so
    it's left for the LLM. Names + dominant key terms (theos→god 0.81) pass."""
    n: dict[str, dict] = collections.defaultdict(dict)
    lemma: dict[str, str] = {}
    top: dict[str, str] = {}
    with TW_MAP.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            s = (r.get("strong") or "").strip()
            if not (s and r.get("tw_article")):
                continue
            n[s][r["tw_article"]] = int(r.get("n") or 0)
            if s not in top:                     # file is n-desc per strong → first = primary
                top[s], lemma[s] = r["tw_article"], (r.get("lemma") or "").strip()
    func = _functions()
    out: dict[str, tuple[str, str]] = {}
    for s, slug in top.items():
        tot = sum(n[s].values())
        share = n[s][slug] / tot if tot else 0
        if s in func or share < MIN_SHARE:
            continue
        out[s] = (slug, lemma[s])
    return out


def _title(articles: dict, slug: str) -> str:
    a = articles.get(slug)
    if not a or not a.get("title"):
        return ""
    terms = [t.strip() for t in a["title"].split(",") if t.strip()]
    return ", ".join(terms[:MAX_TERMS])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, help="output key, e.g. ind (matches build_llm_glosses)")
    ap.add_argument("--lang3", help="tw_articles json key (ISO 639-3); defaults to --lang")
    args = ap.parse_args()
    lang3 = args.lang3 or args.lang
    out_path = OUT_DIR / f"{args.lang}.tsv"

    loc = json.loads((ART / f"{lang3}.json").read_text(encoding="utf-8"))
    eng = json.loads((ART / "eng.json").read_text(encoding="utf-8")) if (ART / "eng.json").exists() else {}
    primary = _primary()

    # merge: preserve any existing rows (e.g. an earlier LLM run), but authoritative TW
    # titles WIN for the codes TW covers → those never get (re-)LLM'd.
    merged: dict[str, tuple] = {}
    prior = 0
    if out_path.exists():
        with out_path.open(encoding="utf-8") as fh:
            for ln in fh:
                if ln.startswith("#") or ln.startswith("strong\t") or not ln.strip():
                    continue
                p = ln.rstrip("\n").split("\t")
                if p and p[0]:
                    merged[p[0]] = tuple(p[1:4]) if len(p) >= 4 else (p[1] if len(p) > 1 else "", "", p[-1])
                    prior += 1

    tw_new = tw_over = skipped = 0
    for strong, (slug, lemma) in primary.items():
        gloss = _title(loc, slug)
        if not gloss:
            skipped += 1                       # no localized article → leave for the LLM
            continue
        if strong in merged:
            tw_over += 1
        else:
            tw_new += 1
        merged[strong] = (lemma, _title(eng, slug), gloss)     # TW precedence

    OUT_DIR.mkdir(exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write("# source=tw (human-translated Translation-Words article titles) + llm "
                 "(remainder); anchored on the original lemma\n")
        fh.write("strong\tlemma_ref\ten_ref\tgloss\n")
        for s in sorted(merged):
            fh.write("\t".join((s, *merged[s])) + "\n")
    print(f"wrote {out_path}: {len(merged)} rows "
          f"({tw_new} TW-seeded, {tw_over} TW overrode prior, {prior} prior kept; "
          f"{skipped} TW codes had no {lang3} article → left for the LLM)")


if __name__ == "__main__":
    main()
