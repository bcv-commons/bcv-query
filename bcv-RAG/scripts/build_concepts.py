#!/usr/bin/env python3
"""Build concepts.tsv — the Strong's-anchored concept registry (Phase 1b).

The language-independent spine: one node per prefixed Strong's code, carrying
its original-language lemma (L1) + the clean per-code attributes already
computed elsewhere. Members are **self-only** in Phase 1 (Option A) — all
synonym grouping (LXX-bridge H↔G, LN/SDBH) is deferred to Phase 3b, because the
LXX bridge is a positional heuristic that shouldn't bake noise into identity.

Joins (all keyed on padded prefixed Strong's — H####/G####):
  strong_lemma.tsv   → lemma, lemma_variants, lang, count   (Phase 1a)
  strongs_keyness.tsv → keyness                              (Strategy 2)
  strongs_freq.tsv    → is_function                          (Strategy 1)
  strongs_gloss.tsv   → gloss_en (bootstrap English label)   (en rows only)

Columns: concept_id, strong, lang, lemma, lemma_variants, gloss_en,
         keyness, is_function, count, members
  concept_id = strong (the stable id for now); members = concept_id (self).

BUILD-TIME ONLY. Run from bcv-RAG/ after build_strong_lemma.py.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
LEMMA = HERE / "strong_lemma.tsv"
KEYNESS = HERE / "strongs_keyness.tsv"
FREQ = HERE / "strongs_freq.tsv"
GLOSS = HERE / "strongs_gloss.tsv"
TW_LINKS = HERE / "tw_links.tsv"
OUTPUT = HERE / "concepts.tsv"


def _load(path: Path, key_col: int, val_cols: tuple[int, ...]) -> dict:
    out: dict[str, tuple] = {}
    if not path.exists():
        print(f"WARN: {path.name} missing", file=sys.stderr)
        return out
    with path.open(encoding="utf-8") as fh:
        next(fh, None)
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) <= max(key_col, *val_cols):
                continue
            out[p[key_col]] = tuple(p[c] for c in val_cols)
    return out


def main() -> None:
    if not LEMMA.exists():
        print(f"ERROR: {LEMMA} missing — run build_strong_lemma.py first", file=sys.stderr)
        sys.exit(1)

    lemma = _load(LEMMA, 0, (1, 2, 3, 4))      # strong -> (lang, lemma, variants, count)
    keyness = _load(KEYNESS, 0, (1,))          # strong -> (keyness,)
    is_func = _load(FREQ, 0, (2,))             # strong -> (is_function,)

    # TW links → per-Strong's TW article + key-term flag, derived from the
    # occurrence-level tw_links.tsv. Head-only attribution (#b): only the head
    # token of a TW link contributes its article/kt flag to that concept.
    tw_articles: dict[str, set] = {}
    tw_kt: dict[str, bool] = {}
    if TW_LINKS.exists():
        with TW_LINKS.open(encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                p = line.rstrip("\n").split("\t")
                # tw_article, category, is_kt, book, ch, vs, idx, strong, lemma, is_head
                if len(p) >= 10 and p[9] == "1":  # head only
                    code = p[7]
                    if not code:
                        continue
                    tw_articles.setdefault(code, set()).add(p[0])
                    if p[2] == "1":
                        tw_kt[code] = True
    else:
        print(f"WARN: {TW_LINKS.name} missing — tw columns empty", file=sys.stderr)

    # English gloss only (bootstrap label)
    gloss_en: dict[str, str] = {}
    if GLOSS.exists():
        with GLOSS.open(encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 4 and p[3] == "en" and p[0] not in gloss_en:
                    gloss_en[p[0]] = p[1]

    # --- Phase 2: importance = blend(tw_kt, lexical elaboration) ---
    # Lexical elaboration: how many distinct CONTENT codes share a concept,
    # via the English gloss (interim English-grouped proxy; Phase 3b LN/SDBH
    # replaces it with original-language grouping). Helper gloss words are
    # filtered so the count isn't dominated by "be"/"of"/"make".
    _STOP = {"be", "of", "in", "with", "to", "for", "the", "a", "an", "and",
             "or", "on", "at", "from", "by", "as", "that", "this", "his", "her",
             "its", "their", "one", "make", "take", "go", "do", "not", "no",
             "who", "what", "which", "up", "out", "off", "down", "over", "into",
             "upon", "before", "after", "away", "is", "are", "was", "were", "it"}

    def _is_content(code: str) -> bool:
        return is_func.get(code, ("0",))[0] != "1"

    word2codes: dict[str, set] = {}
    for code, gloss in gloss_en.items():
        if not _is_content(code):
            continue
        for w in re.findall(r"[a-z]{2,}", gloss.lower()):
            if w not in _STOP:
                word2codes.setdefault(w, set()).add(code)

    def _elaboration(code: str) -> int:
        gloss = gloss_en.get(code, "")
        best = 1
        for w in re.findall(r"[a-z]{2,}", gloss.lower()):
            if w not in _STOP and w in word2codes:
                best = max(best, len(word2codes[w]))
        return best

    rows = []
    for code, (lang, lem, variants, count) in lemma.items():
        is_kt = bool(tw_kt.get(code))
        elab = _elaboration(code)
        # importance: elaboration (log2, diminishing) + key-term bonus.
        # Complements keyness — surfaces common-but-central words ("love").
        importance = round(math.log2(elab) + (1.0 if is_kt else 0.0), 2)
        rows.append((
            code,                                   # concept_id
            code,                                   # strong (alias)
            lang,
            lem,
            variants,
            gloss_en.get(code, ""),
            keyness.get(code, ("",))[0],
            is_func.get(code, ("0",))[0],
            count,
            "1" if is_kt else "0",                  # tw_kt
            ";".join(sorted(tw_articles.get(code, ()))),  # tw_ref
            elab,                                   # elaboration
            importance,                             # importance
            code,                                   # members (self-only, Phase 1)
        ))
    rows.sort(key=lambda r: (r[0][0], int(r[0][1:5]), r[0]))

    with OUTPUT.open("w", encoding="utf-8") as fh:
        fh.write("concept_id\tstrong\tlang\tlemma\tlemma_variants\tgloss_en\t"
                 "keyness\tis_function\tcount\ttw_kt\ttw_ref\telaboration\t"
                 "importance\tmembers\n")
        for r in rows:
            fh.write("\t".join(str(x) for x in r) + "\n")

    n_key = sum(1 for r in rows if r[6])
    n_gloss = sum(1 for r in rows if r[5])
    n_tw = sum(1 for r in rows if r[10])
    n_kt = sum(1 for r in rows if r[9] == "1")
    print(f"Wrote {len(rows)} concepts to {OUTPUT} "
          f"({n_gloss} gloss, {n_key} keyness, {n_tw} with TW article, {n_kt} key-term)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
