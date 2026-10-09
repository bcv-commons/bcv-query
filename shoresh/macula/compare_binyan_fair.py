"""A fairer binyan measure for the lexeme base switch (NC exit step 2a; companion to compare_lexeme_bases section 3).

compare_lexeme_bases counts a verb lexeme as passing only when EVERY stem's dominant label differs, over each base's own set of lexemes (BHSA 691, MACULA 908).
That is strict (one synonym pair fails a four-stem verb) and compares different populations. This script matches the two bases on the same words:

  population  Strong's numbers that have 2+ stems in BOTH bases, only stems with at least --min tokens in BOTH (rare stems are noise), and, for the main table, only
              Strong's that are a single lexeme in both bases (no homograph mixing)
  strict      every stem distinct (as before), on the matched population
  pairwise    share of stem PAIRS with different dominant labels (a four-stem verb with one synonym pair scores 5/6, not 0)
  regression  the matched table: BHSA distinct x MACULA distinct. "BHSA distinct, MACULA same" are the real losses; "both same" is synonymy that BHSA has too

  cd shoresh && VERSE_SENSES_DB=macula/verse-senses-stem.db .venv/bin/python3 -m macula.compare_binyan_fair [--min 3] [--out ../internal-docs/binyan-fair-comparison.md]
"""
from __future__ import annotations

import argparse
import collections
import itertools
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
STEM = {"hif": "hiphil", "haf": "hiphil", "hof": "hophal", "hit": "hithpael", "nif": "niphal", "hotp": "hothpael", "hsht": "hishtaphel", "htpo": "hithpolel", "nit": "nithpael"}


def stems_of(data, codes, base: str) -> dict:
    """strong -> (set of lexemes, {stem: (dominant label, tokens)}), the label being the most frequent among that stem's labelled tokens."""
    os.environ["LEXEME_BASE"] = base
    out = {}
    for c in codes:
        rows = data.sense_concordance(c, 10**6).get("senses", [])
        lab = collections.defaultdict(collections.Counter)
        tot = collections.Counter()
        lexes = set()
        for g in rows:
            if not g.get("stem"):
                continue
            stem = STEM.get(g["stem"], g["stem"])
            lexes.add(g["lex"])
            tot[stem] += g["count"]
            if g["label"]:
                lab[stem][g["label"]] += g["count"]
        out[c] = (lexes, {s: (lab[s].most_common(1)[0][0] if lab[s] else None, tot[s]) for s in tot})
    return out


def score(st: dict) -> tuple[bool, float, int]:
    labels = [v for v in st.values()]
    distinct = len(set(labels)) == len(labels)
    pairs = list(itertools.combinations(labels, 2))
    return distinct, sum(a != b for a, b in pairs) / len(pairs), len(pairs)


def _words(label: str) -> set:
    import re
    return {re.sub(r"(ing|ed|es|en|s|eth)$", "", w) for w in re.findall(r"[a-z]+", (label or "").lower()) if w not in ("be", "to", "oneself", "someone", "something", "one", "a", "the")}


def agreement(rows) -> str:
    """Do our labels name what BHSA's hand-written label for the same Strong's and stem names? Share of labels sharing a content word (inflection stripped) with it.
    Measures label quality without rewarding distinctness; BHSA's gloss is the yardstick here only, nothing is copied."""
    n = hit = 0
    for _c, o, nw in rows:
        for s in o:
            n += 1
            hit += bool(_words(o[s]) & _words(nw[s]))
    return f"- our label shares a content word with BHSA's label for the same verb and stem: {100*hit/max(n,1):.1f}% of {n} stems"


def js(p: dict, q: dict) -> float:
    """Jensen-Shannon divergence (base 2, 0..1) of two count dicts."""
    import math
    sp, sq = sum(p.values()) or 1, sum(q.values()) or 1
    d = 0.0
    for f in set(p) | set(q):
        a, b = p.get(f, 0) / sp, q.get(f, 0) / sq
        m = (a + b) / 2
        if a:
            d += 0.5 * a * math.log2(a / m)
        if b:
            d += 0.5 * b * math.log2(b / m)
    return d


def evidence_section(cache: Path, rows, old, new, lo: float, hi: float) -> list[str]:
    """Label quality against the translation evidence itself: for pairs of stems of one verb, how far apart their English renderings are (JS divergence of the form
    distributions in the cache), and whether the labels of each base tell the two stems apart. Same yardstick for both label sets. The evidence is MACULA-side
    (aligner rend + attestations), so it does not favour BHSA's hand-written labels; it can favour ours, which are chosen from it, so read the over-split line first."""
    import pickle
    import sqlite3
    with cache.open("rb") as fh:
        per = pickle.load(fh)["per_lexeme"]
    sp = sqlite3.connect(f"file:{HERE / 'lexeme-spine-macula.db'}?mode=ro", uri=True)
    lex_of = collections.defaultdict(set)
    for lx, st in sp.execute("SELECT DISTINCT lexeme, strong FROM spine_words WHERE lexeme LIKE 'hbo:%'"):
        lex_of[f"H{st}"].add(lx)
    pairs = []
    for c, o, n in rows:
        lx = next(iter(lex_of.get(c, ())), None)
        if lx not in per:
            continue
        ev = {}
        for stem, (_a, _l, eng, _r) in per[lx].items():
            tot = collections.Counter()
            for cnt in eng.values():
                tot.update(cnt)
            ev[STEM.get(stem, stem)] = tot
        for s1, s2 in itertools.combinations(sorted(o), 2):
            if s1 in ev and s2 in ev and sum(ev[s1].values()) >= 3 and sum(ev[s2].values()) >= 3:
                pairs.append((js(ev[s1], ev[s2]), o[s1] != o[s2], n[s1] != n[s2]))
    L = ["## Labels against the translation evidence", f"- {len(pairs)} stem pairs with English evidence on both sides; JS divergence of their renderings: ≥ {hi} = clearly different, ≤ {lo} = alike",
         "| | BHSA labels | MACULA labels |", "|---|---|---|"]
    diff = [p for p in pairs if p[0] >= hi]
    like = [p for p in pairs if p[0] <= lo]
    L.append(f"| pairs whose renderings clearly differ ({len(diff)}): labels tell them apart | {100*sum(p[1] for p in diff)/max(len(diff),1):.1f}% | {100*sum(p[2] for p in diff)/max(len(diff),1):.1f}% |")
    L.append(f"| pairs whose renderings are alike ({len(like)}): labels still differ (over-split) | {100*sum(p[1] for p in like)/max(len(like),1):.1f}% | {100*sum(p[2] for p in like)/max(len(like),1):.1f}% |")
    L.append("")
    return L


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min", type=int, default=3, help="a stem counts only with at least this many tokens in both bases")
    ap.add_argument("--cache", type=Path, default=HERE / "data" / "stem_senses_cache.pkl", help="split cache of build_stem_senses (adds the evidence section)")
    ap.add_argument("--out", type=Path, default=HERE.parents[1] / "internal-docs" / "binyan-fair-comparison.md")
    a = ap.parse_args()
    import data
    from macula.compare_lexeme_bases import all_strongs
    codes = all_strongs()
    old = stems_of(data, codes, "bhsa")
    new = stems_of(data, codes, "macula")
    os.environ["LEXEME_BASE"] = "bhsa"

    def matched(single: bool):
        rows = []
        for c in codes:
            (lo, so), (ln, sn) = old[c], new[c]
            if single and (len(lo) != 1 or len(ln) != 1):
                continue
            common = {s for s in so if s in sn and so[s][1] >= a.min and sn[s][1] >= a.min and so[s][0] and sn[s][0]}
            if len(common) >= 2:
                rows.append((c, {s: so[s][0] for s in common}, {s: sn[s][0] for s in common}))
        return rows

    L = [f"# Binyan awareness on the same words, BHSA vs MACULA per-stem senses ({time.strftime('%Y-%m-%d')})", "",
         f"Generated by `shoresh/macula/compare_binyan_fair.py` (senses: `{os.environ.get('VERSE_SENSES_DB', 'verse-senses.db')}`). Stems with fewer than {a.min} tokens in either base are ignored.", ""]
    for single, title in ((True, "Strong's that are one lexeme in both bases"), (False, "all Strong's with 2+ common stems (homographs mixed)")):
        rows = matched(single)
        so_ = [score(o) for _, o, _ in rows]
        sn_ = [score(n) for _, _, n in rows]
        N = len(rows)
        grid = collections.Counter((x[0], y[0]) for x, y in zip(so_, sn_))
        pairs_o = sum(x[1] * x[2] for x in so_) / max(sum(x[2] for x in so_), 1)
        pairs_n = sum(y[1] * y[2] for y in sn_) / max(sum(y[2] for y in sn_), 1)
        L += [f"## {title}", f"- {N} verbs compared",
              f"- strict (every stem distinct): BHSA {100*sum(x[0] for x in so_)/max(N,1):.1f}%, MACULA {100*sum(y[0] for y in sn_)/max(N,1):.1f}%  -> ratio {sum(y[0] for y in sn_)/max(sum(x[0] for x in so_),1):.2f} (bar 0.80)",
              f"- pairwise (share of stem pairs with different dominant labels): BHSA {100*pairs_o:.1f}%, MACULA {100*pairs_n:.1f}%  -> ratio {pairs_n/max(pairs_o,1e-9):.2f}",
              f"- both distinct {grid[(True, True)]}; BHSA distinct, MACULA same (real losses) {grid[(True, False)]}; BHSA same, MACULA distinct {grid[(False, True)]}; both same (synonymy both have) {grid[(False, False)]}",
              agreement(rows),
              f"- losses as a share of the verbs BHSA gets right: {100*grid[(True, False)]/max(grid[(True, True)] + grid[(True, False)], 1):.1f}%", ""]
        if single:
            loss = [(c, o, n) for (c, o, n), x, y in zip(rows, so_, sn_) if x[0] and not y[0]]
            L.append("- examples of real losses (Strong's: BHSA stems -> MACULA stems):")
            for c, o, n in loss[:12]:
                L.append(f"  - {c}: " + ", ".join(f"{s} {o[s]}" for s in o) + "  ->  " + ", ".join(f"{s} {n[s]}" for s in n))
            L.append("")
            if a.cache.exists():
                L += evidence_section(a.cache, rows, old, new, 0.25, 0.5)
    a.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
