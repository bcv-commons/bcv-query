"""The grammar bridge beside the lexeme bridge (resources/grammar_bridge/): Hebrew verb form against Greek verb form over the Septuagint.

A Hebrew verb and a Greek verb count as a pair when they stand in the same verse (both converted to the English scheme with vrsmap, as
build_lxx_bridge_tiers does) and their Strong's numbers are a pair in resources/lxx_bridge_tiers (macula.tsv and glaux.tsv, every row).
Each pair counts once; no weighting, no threshold.

  hebrew_form  MACULA Hebrew's `type` and `stem` of a word with class = verb, "type|stem" (wayyiqtol|qal), "?" where one is empty
  greek_form   GLAUx's tense, voice and mood (lxx_words.morph "V.<t><v><m>...", canonical books), "tense|voice|mood"; person and
               number are left out. M and D are both imperative.

The Hebrew lexeme is MACULA's `strongnumberx` (as in the tier files), not the spine's `strong`: the spine merges some verb numbers
(H0977, H8055), which the tier files do not know. --spine-strong uses the spine's number instead, which is how make-tanakh-grammar's
lab/bridge/grammar_bridge.py (the reference, 2026-10-30) counts.

Output grammar_bridge.tsv: hebrew_form, greek_form, count, p_greek_given_hebrew, p_hebrew_given_greek. CC BY-SA 4.0 (GLAUx).

  python -m macula.build_grammar_bridge [--spine-strong] [--out PATH]    # MACULA_HBO_TSV=<cached macula-hebrew.tsv>, else downloaded
"""
from __future__ import annotations

import argparse
import collections
import csv
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from macula.build_lxx_bridge_tiers import GLAUX, OUT as TIERS, SPINE, ROOT, verse_sets  # noqa: E402
from macula.parse import HBO_URL, _rows, _src  # noqa: E402

OUT = ROOT / "resources" / "grammar_bridge" / "grammar_bridge.tsv"
TENSE = {"P": "present", "I": "imperfect", "F": "future", "A": "aorist", "X": "perfect", "Y": "pluperfect"}
VOICE = {"A": "active", "M": "middle", "P": "passive", "E": "middle/passive", "D": "middle deponent", "O": "passive deponent",
         "N": "middle/passive deponent"}
MOOD = {"I": "indicative", "S": "subjunctive", "O": "optative", "M": "imperative", "D": "imperative", "N": "infinitive", "P": "participle"}


def greek_form(morph: str | None) -> str | None:
    m = re.match(r"V\.([PIFAXY])([AMPEDON])([ISOMDNP])", morph or "")
    return f"{TENSE[m[1]]}|{VOICE[m[2]]}|{MOOD[m[3]]}" if m else None


def lexeme_pairs() -> set[tuple[int, int]]:
    out = set()
    for name in ("macula.tsv", "glaux.tsv"):
        with open(TIERS / name, encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                out.add((int(r["hebrew_strong"][1:]), int(r["greek_strong"][1:])))
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spine-strong", action="store_true", help="key Hebrew verbs by the spine's strong (the reference's way)")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    verbs = {}                                                  # spine key -> (strongnumberx, form)
    for row in _rows(_src(HBO_URL, "MACULA_HBO_TSV")):
        h = re.match(r"(\d+)", (row.get("strongnumberx") or "").strip())
        if row["class"] == "verb" and h:
            verbs[row["xml:id"][1:]] = (int(h[1]), f"{row.get('type') or '?'}|{row.get('stem') or '?'}")
    spine = sqlite3.connect(SPINE)
    hrows = ((b, c, v, ((s if a.spine_strong else verbs[k][0]), verbs[k][1]))
             for k, b, c, v, s in spine.execute("SELECT key, book, chapter, verse, strong FROM spine_words WHERE lexeme LIKE 'hbo:%' "
                                                "AND strong IS NOT NULL") if k in verbs)
    hv = verse_sets(hrows, "org", multi=True)
    grows = ((b, c, v, (s, gf)) for b, c, v, s, m in sqlite3.connect(GLAUX).execute(
        "SELECT book, chapter, verse, strong, morph FROM lxx_words WHERE canonical = 1 AND strong IS NOT NULL AND morph LIKE 'V.%'")
        if (gf := greek_form(m)))
    gv = verse_sets(grows, "lxx", multi=True)
    eq = lexeme_pairs()
    pairs: collections.Counter = collections.Counter()
    both = set(hv) & set(gv)
    for r in both:
        for hs, hf in hv[r]:
            for gs, gf in gv[r]:
                if (hs, gs) in eq:
                    pairs[(hf, gf)] += 1
    hc, gc = collections.Counter(), collections.Counter()
    for (hf, gf), c in pairs.items():
        hc[hf] += c; gc[gf] += c
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("hebrew_form\tgreek_form\tcount\tp_greek_given_hebrew\tp_hebrew_given_greek\n")
        for (hf, gf), c in sorted(pairs.items(), key=lambda x: (x[0][0], -x[1], x[0][1])):
            f.write(f"{hf}\t{gf}\t{c}\t{c / hc[hf]:.5f}\t{c / gc[gf]:.5f}\n")
    print(f"verses with verbs on both sides {len(both):,}; verb pairs {sum(pairs.values()):,}; form pairs {len(pairs):,} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
