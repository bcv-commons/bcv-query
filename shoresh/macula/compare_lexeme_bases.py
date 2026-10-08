"""Acceptance report for the lexeme/sense base switch (NC exit, step 2a; design: internal-docs/nc-exit-step2-lexeme-design.md).

Compares LEXEME_BASE=bhsa (hbo.db + senses/hbo_lex.tsv, BHSA-keyed, NC) with LEXEME_BASE=macula (lexeme-spine-macula.db + verse-senses.db, CC BY) through data.py itself:

  1. OCCURRENCES  per Hebrew Strong's, the number of occurrences each base finds (the same text, MACULA vs BHSA tokenisation)
  2. COVERAGE     share of occurrences that carry a sense label, and Strong's with at least one sense
  3. BINYAN       verbs with 2+ stems: share whose stems get DIFFERENT dominant senses (the old inventory was per stem; the new one is per lexeme)
  4. HOMOGRAPHS   Strong's codes that split into 2+ lexemes
  5. CONTRACT     response shape of /senses, /wordstudy, /word, lexeme profile and SDBH meanings: same keys in both bases
  6. SPEED        median ms of sense_concordance and word_study per base

  cd shoresh && .venv/bin/python3 -m macula.compare_lexeme_bases [--sample 400] [--out ../internal-docs/lexeme-base-comparison.md]

Thresholds are written next to each line as PASS / CHECK; a CHECK is a finding to decide on, not a crash.
"""
from __future__ import annotations

import argparse
import collections
import os
import random
import sqlite3
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


def set_base(name: str) -> None:
    os.environ["LEXEME_BASE"] = name


def all_strongs() -> list[str]:
    con = sqlite3.connect(f"file:{HERE / 'lexeme-spine-macula.db'}?mode=ro", uri=True)
    return [f"H{r[0]}" for r in con.execute("SELECT DISTINCT strong FROM spine_words WHERE lexeme LIKE 'hbo:%' AND strong IS NOT NULL ORDER BY strong")]


def sense_stats(data, codes) -> dict:
    out = {}
    for c in codes:
        rows = data.sense_concordance(c, 10**6).get("senses", [])
        out[c] = rows
    return out


def shapes(data, code: str) -> dict:
    return {
        "sense_concordance": sorted(data.sense_concordance(code)),
        "sense_group": sorted((data.sense_concordance(code).get("senses") or [{}])[0]),
        "word_study": sorted(data.word_study(code)),
        "concordance": sorted(data.concordance(code, 3)),
        "concordance_occurrence": sorted((data.concordance(code, 3)["occurrences"] or [{}])[0]),
        "meanings": sorted((data.lexicon_meanings_for_strongs(code, "x") or [{}])[0]),
        "lex_senses": sorted((data.word_study(code)["lex_senses"] or [{}])[0]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", type=int, default=400)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--out", type=Path, default=HERE.parents[1] / "internal-docs" / "lexeme-base-comparison.md")
    a = ap.parse_args()
    import data
    import lexeme_macula
    if not lexeme_macula.available():
        print("MACULA lexeme databases not found"); return 1
    codes = all_strongs()
    sample = random.Random(a.seed).sample(codes, min(a.sample, len(codes)))
    res: dict = {}
    for base in ("bhsa", "macula"):
        set_base(base)
        t0 = time.perf_counter(); sc = sense_stats(data, codes); res[f"{base}_sc"] = sc; res[f"{base}_sc_s"] = time.perf_counter() - t0
        ts = []
        for c in sample[:100]:
            t = time.perf_counter(); data.word_study(c); ts.append(time.perf_counter() - t)
        res[f"{base}_ws_ms"] = 1000 * statistics.median(ts)
        ts = []
        for c in sample[:100]:
            t = time.perf_counter(); data.sense_concordance(c); ts.append(time.perf_counter() - t)
        res[f"{base}_sc_ms"] = 1000 * statistics.median(ts)
    ex = [c for c in sample if res["bhsa_sc"].get(c) and res["macula_sc"].get(c)][:1] or sample[:1]
    set_base("bhsa"); shp_old = shapes(data, ex[0]); set_base("macula"); shp_new = shapes(data, ex[0])
    set_base("bhsa")

    old, new = res["bhsa_sc"], res["macula_sc"]
    occ_old = {c: sum(g["count"] for g in rows) for c, rows in old.items()}
    occ_new = {c: sum(g["count"] for g in rows) for c, rows in new.items()}
    tot_old, tot_new = sum(occ_old.values()), sum(occ_new.values())
    lab_old = sum(g["count"] for rows in old.values() for g in rows if g["label"])
    lab_new = sum(g["count"] for rows in new.values() for g in rows if g["label"])
    has_old, has_new = sum(1 for c in codes if old.get(c)), sum(1 for c in codes if new.get(c))

    def verbs(rows):
        by = collections.defaultdict(dict)
        c = collections.defaultdict(collections.Counter)
        for g in rows:
            if g["stem"]:
                c[(g["lex"], g["stem"])][g["label"]] += g["count"]
        for (lex, stem), cnt in c.items():
            by[lex][stem] = cnt.most_common(1)[0][0]
        multi = [v for v in by.values() if len(v) >= 2]
        distinct = sum(1 for v in multi if len(set(v.values())) == len(v))
        return len(multi), distinct
    vo = [verbs(rows) for rows in old.values() if rows]; vn = [verbs(rows) for rows in new.values() if rows]
    vo_n, vo_d = sum(x[0] for x in vo), sum(x[1] for x in vo); vn_n, vn_d = sum(x[0] for x in vn), sum(x[1] for x in vn)
    hom_old = sum(1 for c in codes if len({g["lex"] for g in old.get(c, [])}) > 1)
    hom_new = sum(1 for c in codes if len({g["lex"] for g in new.get(c, [])}) > 1)
    gap = abs(tot_old - tot_new) / max(tot_old, 1)
    cov_o, cov_n = tot_old, tot_new
    diff = sorted(codes, key=lambda c: -abs(occ_old.get(c, 0) - occ_new.get(c, 0)))[:8]
    shape_ok = all(set(shp_old[k]) <= set(shp_new[k]) for k in shp_old)           # added keys are compatible; removed keys are not
    L = [f"# Lexeme/sense base comparison: BHSA (hbo.db) vs MACULA ({time.strftime('%Y-%m-%d')})", "",
         f"Generated by `shoresh/macula/compare_lexeme_bases.py`, through `data.py` (LEXEME_BASE=bhsa|macula), {len(codes)} Hebrew Strong's numbers.", "",
         "## 1. Occurrences found, and how many carry a sense label",
         f"- found: BHSA {tot_old}, MACULA {tot_new} ({'+' if tot_new >= tot_old else ''}{100*(tot_new-tot_old)/max(tot_old,1):.1f}%): different tokenisation (MACULA splits prefixes and suffixes into tokens)",
         f"- with a sense label: BHSA {lab_old} ({100*lab_old/max(tot_old,1):.1f}% of found), MACULA {lab_new} ({100*lab_new/max(tot_new,1):.1f}% of found); labelled count "
         f"{'PASS' if lab_new >= lab_old else 'CHECK'} (threshold: MACULA labels at least as many occurrences as BHSA)",
         "- largest per-Strong's differences (code: BHSA -> MACULA): " + "; ".join(f"{c}: {occ_old.get(c,0)} -> {occ_new.get(c,0)}" for c in diff), "",
         "## 2. Coverage",
         f"- Strong's with at least one sense group: BHSA {has_old}, MACULA {has_new}  {'PASS' if has_new >= has_old else 'CHECK'} (threshold: not fewer)", "",
         "## 3. Binyan awareness (verbs with 2+ stems)",
         f"- BHSA: {vo_n} verb lexemes, {vo_d} ({100*vo_d/max(vo_n,1):.1f}%) give every stem its own dominant sense",
         f"- MACULA: {vn_n} verb lexemes, {vn_d} ({100*vn_d/max(vn_n,1):.1f}%) give every stem its own dominant sense  "
         f"{'PASS' if vn_n and vn_d/vn_n >= 0.8*(vo_d/max(vo_n,1)) else 'CHECK'} (threshold: at least 80% of BHSA's share). Senses are global per lexeme in hebrew-word-senses; the stem comes from the token.", "",
         "## 4. Homographs",
         f"- Strong's codes that split into 2+ lexemes: BHSA {hom_old}, MACULA {hom_new}  {'PASS' if hom_new >= 0.9*hom_old else 'CHECK'} (threshold: 90% of BHSA)", "",
         "## 5. Contract (same keys in both bases, example " + ex[0] + ")",
         f"- {'PASS' if shape_ok else 'CHECK'}: " + ("every BHSA key is present; added in MACULA: " + str({k: sorted(set(shp_new[k]) - set(shp_old[k])) for k in shp_old if set(shp_new[k]) - set(shp_old[k])}) if shape_ok else "; ".join(f"{k}: BHSA-only {sorted(set(shp_old[k]) - set(shp_new[k]))}, MACULA-only {sorted(set(shp_new[k]) - set(shp_old[k]))}" for k in shp_old if shp_old[k] != shp_new[k])), "",
         "## 6. Speed (median over 100 Strong's)",
         f"- sense_concordance: BHSA {res['bhsa_sc_ms']:.1f} ms, MACULA {res['macula_sc_ms']:.1f} ms; word_study: BHSA {res['bhsa_ws_ms']:.1f} ms, MACULA {res['macula_ws_ms']:.1f} ms  "
         f"{'PASS' if res['macula_ws_ms'] <= 3*res['bhsa_ws_ms'] + 20 else 'CHECK'} (threshold: within 3x + 20 ms)"]
    a.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
