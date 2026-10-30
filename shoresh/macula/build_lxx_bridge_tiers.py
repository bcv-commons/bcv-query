"""The Hebrew <-> Greek lexeme bridge with every pair and its tier, for both directions (resources/lxx_bridge_tiers/).

resources/lxx_bridge.tsv keeps the top 4 Greek per Hebrew lexeme (count >= 3), which is right for Hebrew -> Greek expansion but cuts the
tail of Greek -> Hebrew. These files keep every pair with count >= 3, one file per licence:

  macula.tsv  MACULA Hebrew's per-occurrence `greekstrong` column (WLC TSV), CC BY 4.0. count = occurrences, score = P(greek | hebrew)
              over the Hebrew lexeme's occurrences that have a greekstrong. Counted as bcv-RAG/scripts/build_lxx_bridge.py counts them
              (`strongnumberx` without its homonym letter, the first Greek number), so lxx_bridge.tsv is exactly this tier's top 4.
  glaux.tsv   verse co-occurrence of the Hebrew text (spine, Hebrew numbering) and the Septuagint (lxx-glaux.db, GLAUx, CC BY-SA 4.0;
              Septuagint numbering), both converted to the English scheme with vrsmap (bibles' TVTMS maps); content words of the canonical
              books only. count = verses with both, score = Dice over the two verse sets, kept at Dice >= 0.3. CC BY-SA 4.0.

The Hebrew key is MACULA's `strongnumberx` in both, not the spine's `strong`: the spine merges some numbers (H0582 into H0376, H2009 into
H2005, H3069 into H3068), and the bridge is looked up by the number a reader has. Columns of both: hebrew_strong, greek_strong, tier, count, score (codes zero-padded as in lxx_bridge.tsv). Make-tanakh-grammar's
lab/bridge/strong_bridge.py was the reference (2026-10-30); the thresholds are theirs.

  python -m macula.build_lxx_bridge_tiers [--min-count 3] [--min-dice 0.3]    # MACULA_HBO_TSV=<cached macula-hebrew.tsv>, else downloaded
"""
from __future__ import annotations

import argparse
import collections
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import vrsmap  # noqa: E402
from macula.parse import HBO_URL, _rows, _src  # noqa: E402

ROOT = HERE.parents[1]
SPINE = HERE / "lexeme-spine-macula.db"
GLAUX = HERE.parent / "lxx" / "data" / "lxx-glaux.db"
OUT = ROOT / "resources" / "lxx_bridge_tiers"
HEADER = "hebrew_strong\tgreek_strong\ttier\tcount\tscore\n"


def hebrew_words(path: Path) -> dict[str, tuple[int, int | None]]:
    """{spine key: (Hebrew strong, Greek strong or None)} from the MACULA Hebrew TSV, numbers as build_lxx_bridge.py reads them."""
    out = {}
    for row in _rows(path):
        h = re.match(r"(\d+)", (row.get("strongnumberx") or "").strip())
        if h:
            g = re.match(r"(\d+)", (row.get("greekstrong") or "").strip())
            out[row["xml:id"][1:]] = (int(h.group(1)), int(g.group(1)) if g else None)
    return out


def macula_tier(words: dict, min_count: int) -> dict[tuple[int, int], tuple[int, float]]:
    pairs = collections.Counter((h, g) for h, g in words.values() if g)
    tot: collections.Counter = collections.Counter()
    for (h, _), c in pairs.items():
        tot[h] += c
    return {k: (c, round(c / tot[k[0]], 5)) for k, c in pairs.items() if c >= min_count}


def verse_sets(rows, scheme: str, multi: bool = False) -> dict[tuple, set]:
    """{English verse: set of the rows' values}; with multi, a list with every occurrence (build_grammar_bridge)."""
    out: dict[tuple, set | list] = collections.defaultdict(list if multi else set)
    eng: dict[tuple, list] = {}
    for b, c, v, s in rows:
        r = (b, c, v)
        if r not in eng:
            eng[r] = vrsmap.to_eng(r, scheme)
        for e in eng[r]:
            out[e].append(s) if multi else out[e].add(s)
    return out


def glaux_tier(words: dict, spine: sqlite3.Connection, glaux: sqlite3.Connection, min_count: int, min_dice: float) -> tuple[dict, dict]:
    content = spine.execute("SELECT key, book, chapter, verse FROM spine_words WHERE lexeme LIKE 'hbo:%' AND is_content = 1")
    hv = verse_sets(((b, c, v, words[k][0]) for k, b, c, v in content if k in words), "org")
    gv = verse_sets(glaux.execute("SELECT book, chapter, verse, strong FROM lxx_words WHERE canonical = 1 AND is_content = 1 "
                                  "AND strong IS NOT NULL"), "lxx")
    both = set(hv) & set(gv)
    ch, cg, chg = collections.Counter(), collections.Counter(), collections.Counter()
    for r in both:
        ch.update(hv[r]); cg.update(gv[r])
        chg.update((h, g) for h in hv[r] for g in gv[r])
    out = {}
    for (h, g), c in sorted(chg.items()):
        if c >= min_count and (d := 2 * c / (ch[h] + cg[g])) >= min_dice:
            out[(h, g)] = (c, round(d, 3))
    return out, {"hebrew_verses": len(hv), "septuagint_verses": len(gv), "matched_verses": len(both)}


def write(path: Path, tier: str, pairs: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(HEADER)
        # ties keep the order of the pairs dict (macula: first occurrence in the text, as build_lxx_bridge.py; glaux: Greek number)
        for (h, g), (c, s) in sorted(pairs.items(), key=lambda kv: (kv[0][0], -kv[1][0])):
            f.write(f"H{h:04d}\tG{g:04d}\t{tier}\t{c}\t{s}\n")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-count", type=int, default=3)
    ap.add_argument("--min-dice", type=float, default=0.3)
    a = ap.parse_args(argv)
    words = hebrew_words(_src(HBO_URL, "MACULA_HBO_TSV"))
    mac = macula_tier(words, a.min_count)
    lxx, stats = glaux_tier(words, sqlite3.connect(SPINE), sqlite3.connect(GLAUX), a.min_count, a.min_dice)
    OUT.mkdir(parents=True, exist_ok=True)
    write(OUT / "macula.tsv", "macula", mac)
    write(OUT / "glaux.tsv", "glaux", lxx)
    for name, p in (("macula", mac), ("glaux", lxx)):
        print(f"{name}: {len(p):,} pairs, Hebrew {len({h for h, _ in p}):,}, Greek {len({g for _, g in p}):,}")
    print(f"glaux: {stats}; in both tiers {len(set(mac) & set(lxx)):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
