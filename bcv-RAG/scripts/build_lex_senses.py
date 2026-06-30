#!/usr/bin/env python3
"""Phase 2+3 — occurrence-anchored sense layer (derive coarser views, don't impose them).

The atomic datum is the OCCURRENCE and its contextual gloss (MACULA), attached to the BHSA
occurrence (which already carries node, lex, stem, strong). BHSA and MACULA share the
WLC/ETCBC text, so we align their words by Strong's sequence (LCS — MACULA splits pronominal
suffixes into extra rows, which become skippable). Then EVERYTHING derives upward from that
atomic record:
  - per-occurrence sense  = its own gloss's cluster within its (lex, stem)   → sidecar.sense
  - sense inventory       = group occurrences by (lex, stem), cluster glosses → senses/hbo_lex.tsv
  - (per-lex / per-Strong's senses are further rollups, not built here)

Because we group by (lex, stem) BEFORE clustering, binyan meanings stay distinct (qal "be
holy" vs hif "declare holy" become different senses, not one). No match-down to coarse
Strong's labels, so no fallback — every aligned content word defines its own sense.

  python3 bcv-RAG/scripts/build_lex_senses.py     # stdlib only
"""
from __future__ import annotations

import collections
import csv
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OCC = ROOT / "resources/occurrences/hbo.db"
MACULA = ROOT / "shoresh/macula/macula-spine.db"
OUT = ROOT / "resources/senses/hbo_lex.tsv"

_USFM = ["GEN", "EXO", "LEV", "NUM", "DEU", "JOS", "JDG", "RUT", "1SA", "2SA", "1KI", "2KI",
         "1CH", "2CH", "EZR", "NEH", "EST", "JOB", "PSA", "PRO", "ECC", "SNG", "ISA", "JER",
         "LAM", "EZK", "DAN", "HOS", "JOL", "AMO", "OBA", "JON", "MIC", "NAM", "HAB", "ZEP",
         "HAG", "ZEC", "MAL"]
NUM = {u: i + 1 for i, u in enumerate(_USFM)}
_BRACKET = re.compile(r"\[[^\]]*\]")
# inflection/function words to drop so a contextual gloss reduces to its lexical SENSE
_STOP = set((
    "he she it i you they we him her them us me my your his its our their thy thee "
    "will would shall should can could may might must let "
    "have has had having do does did doing done "
    "be been being am is are was were "
    "to of the a an as at in on for with by from into unto upon out off up down "
    "yourself yourselves himself herself itself themselves myself ourselves "
    "not surely indeed so then there that this who whom which and or but very well"
).split())
_SUF = ("ating", "ated", "ates", "ate", "ying", "ied", "ies", "ing", "ed", "es", "y", "e", "s")


def _stem(w: str) -> str:
    for suf in _SUF:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[:-len(suf)]
    return w


def _norm(g: str) -> str:
    """Reduce a contextual gloss to its lexical SENSE: drop brackets, function/inflection
    words, and stem the rest so 'he.will.consecrate' and 'I.consecrated' both → 'consecr'."""
    g = (g or "").lower()
    g = _BRACKET.sub("", g)
    g = re.sub(r"[()\[\]{},;:?!]", "", g).replace(".", " ")
    toks = [_stem(t) for t in g.split() if t and t not in _STOP]
    return " ".join(toks)


def _digits(strong: str) -> str:
    m = re.search(r"(\d+)", strong or "")
    return str(int(m.group(1))) if m else ""


def _lcs_align(bstr: list[str], mstr: list[str]) -> list[tuple[int, int]]:
    """Match BHSA ↔ MACULA words by Strong's (digit) sequence via LCS (skips MACULA's extra
    suffix rows). Returns matched (i, j) pairs."""
    n, m = len(bstr), len(mstr)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for a in range(n - 1, -1, -1):
        row, nxt = dp[a], dp[a + 1]
        for b in range(m - 1, -1, -1):
            row[b] = nxt[b + 1] + 1 if (bstr[a] and bstr[a] == mstr[b]) else max(nxt[b], row[b + 1])
    pairs, a, b = [], 0, 0
    while a < n and b < m:
        if bstr[a] and bstr[a] == mstr[b]:
            pairs.append((a, b)); a += 1; b += 1
        elif dp[a + 1][b] >= dp[a][b + 1]:
            a += 1
        else:
            b += 1
    return pairs


def _macula_by_ref() -> dict[int, list[tuple[str, str]]]:
    con = sqlite3.connect(MACULA)
    out: dict[int, list] = collections.defaultdict(list)
    for book, ch, vs, strong, gloss in con.execute(
            "SELECT book, chapter, verse, strong, gloss FROM macula_words "
            "WHERE lang='hbo' ORDER BY key"):
        n = NUM.get(book)
        if n:
            out[n * 1_000_000 + ch * 1_000 + vs].append((strong, gloss))
    con.close()
    return out


def main() -> None:
    occ = sqlite3.connect(OCC)
    cols = {r[1] for r in occ.execute("PRAGMA table_info(occurrence)")}
    if "gloss" not in cols:
        occ.execute("ALTER TABLE occurrence ADD COLUMN gloss TEXT")
    occ.execute("UPDATE occurrence SET sense=NULL, sense_source=NULL, sense_conf=NULL, gloss=NULL")

    by_ref: dict[int, list] = collections.defaultdict(list)
    for node, ref, lex, stem, strong in occ.execute(
            "SELECT node, ref, lex, stem, strong FROM occurrence ORDER BY node"):
        by_ref[ref].append((node, lex, stem, strong))
    macula = _macula_by_ref()

    # 1. align → atomic records: (node, lex, stem, raw gloss, normalized gloss)
    records = []
    aligned = skipped = 0
    for ref, bwords in by_ref.items():
        mwords = macula.get(ref)
        if not mwords:
            skipped += 1
            continue
        pairs = _lcs_align([_digits(s) for (_n, _l, _st, s) in bwords],
                           [_digits(ms) for (ms, _g) in mwords])
        if not pairs:
            skipped += 1
            continue
        aligned += 1
        for i, j in pairs:
            node, lex, stem, _strong = bwords[i]
            raw = (mwords[j][1] or "").strip()
            ng = _norm(raw)
            if lex and ng:
                records.append((node, lex, stem, raw, ng))

    # 2. derive senses bottom-up: per (lex, stem), rank distinct normalized glosses by count
    by_ls = collections.defaultdict(collections.Counter)          # (lex,stem) -> Counter(norm)
    raw_form = collections.defaultdict(collections.Counter)        # (lex,stem,norm) -> Counter(raw)
    for node, lex, stem, raw, ng in records:
        by_ls[(lex, stem)][ng] += 1
        raw_form[(lex, stem, ng)][raw] += 1
    sense_of = {}                                                  # (lex,stem,norm) -> (sense#, share)
    inv_rows = []
    for (lex, stem), counter in by_ls.items():
        total = sum(counter.values())
        for rank, (ng, c) in enumerate(counter.most_common(), 1):
            sense_of[(lex, stem, ng)] = (rank, round(c / total, 3))
            # display the most lemma-like raw form (fewest dot-segments → least inflection)
            canon = min(raw_form[(lex, stem, ng)].items(),
                        key=lambda kv: (kv[0].count("."), -kv[1]))[0]
            inv_rows.append((lex, stem, rank, canon, c, round(c / total, 3)))

    # 3. write per-occurrence sense (the atomic anchor + its derived sense)
    updates = []
    for node, lex, stem, raw, ng in records:
        rank, share = sense_of[(lex, stem, ng)]
        updates.append((str(rank), raw, share, node))
    occ.executemany("UPDATE occurrence SET sense=?, gloss=?, sense_conf=?, "
                    "sense_source='macula-derived' WHERE node=?", updates)
    occ.commit()
    occ.close()

    inv_rows.sort(key=lambda r: (r[0], r[1], r[2]))
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["lex", "stem", "sense", "gloss", "count", "share"])
        w.writerows(inv_rows)

    nls = len(by_ls)
    polysemous = sum(1 for c in by_ls.values() if len(c) >= 2)
    print(f"aligned {aligned} verses (skipped {skipped}); {len(records)} occurrences sense-assigned")
    print(f"  wrote {OUT.relative_to(ROOT)}: {len(inv_rows)} senses over {nls} (lex,stem) "
          f"({polysemous} polysemous); no fallback — every sense derived from its own glosses")


if __name__ == "__main__":
    main()
