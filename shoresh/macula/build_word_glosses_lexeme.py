#!/usr/bin/env python3
"""Re-key resources/word_glosses/hbo/<Language>.csv (BibleOL glosses, MIT; keyed by BHSA `lex`) onto MACULA lexemes (NC exit step 2b).

Output shoresh/macula/data/word_glosses/hbo_lexeme/<Language>.csv: same layout, but the first column is `lexeme` (hbo:6942, hbo:0871a) and the stem columns carry MACULA's
stem names (nif -> niphal, hit -> hithpael, hif -> hiphil, ...), so serving needs no translation. The gloss text is unchanged.

Mapping BHSA lex -> MACULA lexeme: the local BHSA<->MACULA token bridge (bhsa-macula-bridge.db) joined with hbo.db (node -> lex) and lexeme-spine-macula.db
(key -> lexeme). Each lex goes to the lexeme most of its tokens land on (share reported); when several lexes land on one lexeme, the lex with the most tokens there
supplies the row and the others only fill cells it leaves empty. The mapping itself stays LOCAL (macula/data/lex_to_lexeme.tsv): it is BHSA-derived and is not published;
the published CSVs contain only MACULA lexeme ids and the MIT-licensed glosses.

  cd shoresh && .venv/bin/python3 -m macula.build_word_glosses_lexeme [--min-share 0.5]

Licence: BibleOL glosses (MIT) on CC BY MACULA lexeme ids; no BHSA data or ids. Built output, not tracked (so not in resources/LICENSES.md); the lex -> lexeme mapping stays local.
"""
from __future__ import annotations

import argparse
import collections
import csv
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT / "resources" / "word_glosses" / "hbo"
OUT = HERE / "data" / "word_glosses" / "hbo_lexeme"      # built output, not in git: shipped with deploy/deploy-data.sh to /data/word_glosses/hbo_lexeme
MAP_OUT = HERE / "data" / "lex_to_lexeme.tsv"
HBO = ROOT / "resources" / "occurrences" / "hbo.db"
BRIDGE = HERE / "bhsa-macula-bridge.db"
SPINE = HERE / "lexeme-spine-macula.db"

# BibleOL stem column -> MACULA stem name; columns without a MACULA stem (pasq, hotp, tif) are dropped
STEMS = {"qal": "qal", "nif": "niphal", "piel": "piel", "pual": "pual", "hit": "hithpael", "hif": "hiphil", "hof": "hophal", "hsht": "hishtaphel",
         "etpa": "ithpaal", "nit": "nithpael", "htpa": "hithpaal", "poal": "poal", "poel": "poel", "peal": "peal", "peil": "peil", "pael": "pael",
         "haf": "haphel", "afel": "aphel", "shaf": "shaphel", "htpe": "hithpeel", "etpe": "ithpeel"}


def lex_to_lexeme() -> dict[str, tuple[str, int, float]]:
    """{lex: (lexeme, tokens on it, share of the lex's bridged tokens)}."""
    con = sqlite3.connect(f"file:{BRIDGE}?mode=ro", uri=True)
    con.execute("ATTACH DATABASE ? AS h", (f"file:{HBO}?mode=ro",))
    con.execute("ATTACH DATABASE ? AS s", (f"file:{SPINE}?mode=ro",))
    counts: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for lex, lexeme in con.execute(
            "SELECT o.lex, w.lexeme FROM bridge b JOIN h.occurrence o ON o.node=b.node JOIN s.spine_words w ON w.key=b.key WHERE o.lex!='' AND w.lexeme LIKE 'hbo:%'"):
        counts[lex][lexeme] += 1
    out = {}
    for lex, c in counts.items():
        lexeme, n = c.most_common(1)[0]
        out[lex] = (lexeme, n, n / sum(c.values()))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-share", type=float, default=0.5, help="a lex whose tokens split with no majority is skipped")
    a = ap.parse_args()
    for f in (HBO, BRIDGE, SPINE):
        if not f.exists():
            sys.exit(f"missing {f}")
    mp = lex_to_lexeme()
    MAP_OUT.parent.mkdir(parents=True, exist_ok=True)
    MAP_OUT.write_text("lex\tlexeme\ttokens\tshare\n" + "".join(f"{l}\t{x}\t{n}\t{sh:.3f}\n" for l, (x, n, sh) in sorted(mp.items())), encoding="utf-8")
    # per lexeme, its lexes best first
    by_lexeme: dict[str, list[tuple[int, str]]] = collections.defaultdict(list)
    for lex, (lexeme, n, share) in mp.items():
        if share >= a.min_share:
            by_lexeme[lexeme].append((n, lex))
    # second pass: a lexeme the token bridge never reached takes the glosses of the lex(es) the corrected Strong's crosswalk gives for its Strong's number, but only
    # when that is unambiguous (the Strong's number has one lexeme in MACULA) and those lexes are not already placed on another lexeme
    strong_lexes: dict[str, list[str]] = collections.defaultdict(list)
    for ln in (ROOT / "resources" / "word_freq" / "hbo_strong.tsv").read_text(encoding="utf-8").splitlines()[1:]:
        c = ln.split("\t")
        if len(c) >= 2 and c[0]:
            strong_lexes[c[1].lstrip("H").lstrip("0")].append(c[0])
    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    lexemes_of: dict[str, set[str]] = collections.defaultdict(set)
    counts = dict(sp.execute("SELECT lexeme, count(*) FROM spine_words WHERE lexeme LIKE 'hbo:%' GROUP BY lexeme"))
    for lexeme in counts:
        lexemes_of[lexeme[4:8].lstrip("0")].add(lexeme)
    placed = {lex for lexs in by_lexeme.values() for _, lex in lexs}
    recovered = 0
    for strong, lexemes in lexemes_of.items():
        if len(lexemes) != 1:
            continue
        (lexeme,) = lexemes
        if lexeme in by_lexeme:
            continue
        cand = [l for l in strong_lexes.get(strong, []) if l not in placed]
        if cand:
            by_lexeme[lexeme] = [(0, l) for l in cand]
            recovered += 1
    print(f"second pass (Strong's crosswalk): {recovered} more lexemes")
    OUT.mkdir(parents=True, exist_ok=True)
    for src in sorted(SRC.glob("*.csv")):
        with src.open(encoding="utf-8-sig", newline="") as fh:
            rd = csv.reader(fh)
            header = [c.strip() for c in next(rd)]
            li = header.index("lex")
            cols = [(i, c) for i, c in enumerate(header) if c and i != li and (c == "default" or c in STEMS)]
            rows = {r[li].strip(): r for r in rd if len(r) > li and r[li].strip()}
        out_rows, merged = [], 0
        for lexeme in sorted(by_lexeme):
            cells = {}
            for n, lex in sorted(by_lexeme[lexeme], reverse=True):
                r = rows.get(lex)
                if not r:
                    continue
                for i, c in cols:
                    v = (r[i].strip() if i < len(r) else "")
                    if v and c not in cells:
                        cells[c] = v
                        merged += 1 if lex != sorted(by_lexeme[lexeme], reverse=True)[0][1] else 0
            if cells:
                out_rows.append([lexeme] + [cells.get(c, "") for _, c in cols])
        with (OUT / src.name).open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["lexeme"] + [STEMS.get(c, c) for _, c in cols])
            w.writerows(out_rows)
        src_rows = sum(1 for r in rows.values() if any(i < len(r) and r[i].strip() for i, _ in cols))           # lexes with a real gloss in a kept column
        print(f"{src.name:26s} BHSA lexes with glosses {src_rows:6d} -> MACULA lexemes {len(out_rows):6d} (cells filled from a second lex: {merged})")
    low = [l for l, (_, _, sh) in mp.items() if sh < a.min_share]
    print(f"lexes mapped {len(mp)}; skipped for no majority: {len(low)} {low[:6]}; lexemes with a lex: {len(by_lexeme)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
