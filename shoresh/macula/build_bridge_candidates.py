"""Candidates for the lexemes the Septuagint tiers leave without a partner, from Hebrew and Greek evidence only.

    python -m macula.build_bridge_candidates --lexemes LIST.json [--min-dice 0.08] [--top 6]

The user's rule (2026-11-17): the bridge's Jev tier is rebuilt with candidates found through Hebrew and Greek, never through English
glosses (research's packet 33 found them by gloss words and is held back). Here a lexeme's candidates are
  - the Hebrew NT bridges (resources/hebrew_nt_bridge/heb_scg.tsv, heb_mod.tsv: Greek NT word -> the Hebrew word part a translator
    wrote for it; pairs with count >= 3), both directions, ranked by the summed count;
  - the weak Septuagint co-occurrence pairs: build_lxx_bridge_tiers.glaux_tier at Dice >= --min-dice (the published glaux tier keeps
    0.3 and up; below that make-tanakh-grammar found collocates as often as equivalents, so these are only candidates), ranked by Dice.
Up to --top per lexeme, Hebrew NT pairs first. --lexemes is the list of lexemes to cover: {"nt": [Greek Strong's], "ot": [Hebrew
Strong's]} (research's packet 33 jev_candidates.json is read for its lexeme numbers only). A judge (Jev, on the verses, with no
glosses shown) chooses one candidate or none; that run is separate and needs the user's go for its cost.

Writes macula/data/bridge-candidates/candidates.json: {"nt": [...], "ot": [...]}, per lexeme its strong, lemma, tokens and candidates
(strong, lemma, tokens, evidence: hnt count per edition, dice and co-occurring verses), and a summary to stdout. No English.
"""
from __future__ import annotations

import argparse
import collections
import json
import sqlite3
from pathlib import Path

from macula import build_lxx_bridge_tiers as T

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "data" / "bridge-candidates"


def code(s: str) -> int:
    return int(s[1:])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lexemes", type=Path, required=True)
    ap.add_argument("--min-dice", type=float, default=0.08)
    ap.add_argument("--top", type=int, default=6)
    a = ap.parse_args()
    want = json.loads(a.lexemes.read_text(encoding="utf-8"))
    want = {side: [x["strong"] if isinstance(x, dict) else x for x in v] for side, v in want.items()}
    # Hebrew NT pairs
    hnt = collections.defaultdict(lambda: collections.Counter())
    for ed in ("heb_scg", "heb_mod"):
        for l in (ROOT / "resources" / "hebrew_nt_bridge" / f"{ed}.tsv").read_text().splitlines()[1:]:
            h, g, _, c, *_ = l.split("\t")
            hnt[(code(h), code(g))][ed] += int(c)
    # weak Septuagint co-occurrence, with the published tiers' Greek numbers
    forms: collections.Counter = collections.Counter()
    words = T.hebrew_words(T._src(T.HBO_URL, "MACULA_HBO_TSV"), forms)
    to_nt = {g: t for g, t, *_ in T.greek_number_map(forms) if t}
    words = {k: (h, tuple(to_nt.get(g, g) for g in gs)) for k, (h, gs) in words.items()}
    weak, stats = T.glaux_tier(words, sqlite3.connect(T.SPINE), sqlite3.connect(T.GLAUX), 3, a.min_dice)
    sp = sqlite3.connect(T.SPINE)
    lemma, freq = {}, collections.Counter()
    for lang, s, l in sp.execute("select substr(lexeme,1,3), strong, lemma from spine_words where strong is not null and (lexeme like 'hbo:%' or lexeme like 'grc:%')"):
        lemma.setdefault((lang, s), l); freq[(lang, s)] += 1
    out, summary = {}, {}
    for side, me, other in (("nt", "grc", "hbo"), ("ot", "hbo", "grc")):
        rows, n = [], collections.Counter()
        for s in want.get(side, []):
            key = (lambda t: (t, s)) if side == "nt" else (lambda t: (s, t))
            ev = collections.defaultdict(dict)
            for (h, g), c in hnt.items():
                if (g if side == "nt" else h) == s:
                    ev[h if side == "nt" else g]["hnt"] = dict(c)
            for (h, g), (c, d) in weak.items():
                if (g if side == "nt" else h) == s:
                    ev[h if side == "nt" else g].update({"dice": d, "verses": c})
            order = sorted(ev, key=lambda t: (-sum(ev[t].get("hnt", {}).values()), -ev[t].get("dice", 0)))[:a.top]
            n["lexemes"] += 1
            n["with a candidate"] += bool(order)
            n["with a Hebrew NT candidate"] += any("hnt" in ev[t] for t in order)
            n["with a Septuagint candidate"] += any("dice" in ev[t] for t in order)
            rows.append({"strong": s, "lemma": lemma.get((me, s)), "tokens": freq[(me, s)],
                         "candidates": [{"strong": t, "lemma": lemma.get((other, t)), "tokens": freq[(other, t)], "evidence": ev[t]} for t in order]})
        out[side], summary[side] = rows, dict(n)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "candidates.json").write_text(json.dumps(out, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(json.dumps({"min_dice": a.min_dice, "weak pairs": len(weak), **stats, "summary": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
