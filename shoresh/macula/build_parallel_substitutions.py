"""Word substitutions between parallel passages: synonym evidence from the Hebrew Bible itself.

Where Samuel-Kings and Chronicles (or Psalms and Samuel, Isaiah and Kings, Jeremiah 52 and Kings) tell the
same thing, the later text sometimes uses another word in the same place: a substitution the writers made
themselves. Steps:
1. passage pairs: BSB section headings carry parallel references ("(2 Samuel 5:1-10)"); a section runs to the
   next heading in its book. OT-to-OT pairs only. (BSB is public domain; only its section boundaries and
   references are used.)
2. verse alignment: each verse of one passage is matched to the most similar verse of the other by shared
   MACULA lexemes weighted by rarity (idf); pairs below MIN_SIM are dropped.
3. substitution: in an aligned verse pair, exactly one content word (noun/verb/adjective, not a name) on
   each side that the other lacks, with the same part of speech -> a candidate pair.

  python -m macula.build_parallel_substitutions        # -> resources/parallel_substitutions/candidate_pairs.tsv
"""
from __future__ import annotations

import collections
import json
import math
import re
import sqlite3
import sys
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPINE = HERE / "lexeme-spine-macula.db"
HEADINGS = HERE.parent / "interlinear" / "data" / "bsb" / "base" / "headings.jsonl"
OUT = ROOT / "resources" / "parallel_substitutions" / "candidate_pairs.tsv"
OT = {"GEN", "EXO", "LEV", "NUM", "DEU", "JOS", "JDG", "RUT", "1SA", "2SA", "1KI", "2KI", "1CH", "2CH", "EZR",
      "NEH", "EST", "JOB", "PSA", "PRO", "ECC", "SNG", "ISA", "JER", "LAM", "EZK", "DAN", "HOS", "JOL", "AMO",
      "OBA", "JON", "MIC", "NAM", "HAB", "ZEP", "HAG", "ZEC", "MAL"}
MIN_SIM = 0.35


def passage_pairs() -> list[tuple]:
    """[(book_a, (c, v) start, (c, v) end, book_b, (c, v) start, (c, v) end)]."""
    rows = [json.loads(l) for l in HEADINGS.read_text(encoding="utf-8").splitlines() if l]
    sections = collections.defaultdict(list)          # book -> [(c, v)] section starts
    for r in rows:
        if r.get("level", "").startswith("s"):
            sections[r["b"]].append((r["c"], r["before_v"]))
    pairs = []
    for r in rows:
        if r.get("level") != "r" or r["b"] not in OT:
            continue
        start = (r["c"], r["before_v"])
        nxt = [s for s in sorted(sections[r["b"]]) if s > start]
        end = (nxt[0][0], nxt[0][1] - 1) if nxt and nxt[0][1] > 1 else ((nxt[0][0] - 1, 999) if nxt else (999, 999))
        for ref in r.get("refs") or []:
            m = re.match(r"^(\w+) (\d+):(\d+)(?:-(?:(\d+):)?(\d+))?$", ref.replace("–", "-"))
            if not m or m.group(1) not in OT:
                continue
            c1, v1 = int(m.group(2)), int(m.group(3))
            c2 = int(m.group(4)) if m.group(4) else c1
            v2 = int(m.group(5)) if m.group(5) else v1
            pairs.append((r["b"], start, end, m.group(1), (c1, v1), (c2, v2)))
    return pairs


def main() -> int:
    pos = {r["lexeme"]: r["pos"] for r in pq.read_table(ROOT / "resources" / "prior_pack" / "prior_pack.parquet",
                                                         columns=["lexeme", "pos"]).to_pylist()}
    db = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    verses: dict = collections.defaultdict(collections.Counter)
    strong_of = {}
    for b, c, v, lx, s in db.execute("SELECT book, chapter, verse, lexeme, strong FROM spine_words "
                                     "WHERE lexeme LIKE 'hbo:%'"):
        verses[(b, c, v)][lx] += 1
        if s is not None:
            strong_of[lx] = f"H{int(s):04d}"
    df = collections.Counter(lx for vs in verses.values() for lx in vs)
    n = len(verses)
    idf = {lx: math.log(n / d) for lx, d in df.items()}

    def sim(a, b):
        wa = {lx: idf[lx] for lx in a}
        wb = {lx: idf[lx] for lx in b}
        inter = sum(min(wa[x], wb[x]) for x in set(wa) & set(wb))
        union = sum(max(wa.get(x, 0), wb.get(x, 0)) for x in set(wa) | set(wb))
        return inter / union if union else 0.0

    def in_range(book, s, e):
        return [k for k in verses if k[0] == book and s <= (k[1], k[2]) <= e]

    content = lambda lx: pos.get(lx) in ("noun", "verb", "adj")
    pairs = collections.Counter()
    examples = collections.defaultdict(list)
    st = collections.Counter()
    seen_verse_pairs = set()
    for ba, sa, ea, bb, sb, eb in passage_pairs():
        st["passage_pairs"] += 1
        A, B = in_range(ba, sa, ea), in_range(bb, sb, eb)
        for va in A:
            if not B:
                break
            vb, score = max(((x, sim(verses[va], verses[x])) for x in B), key=lambda t: t[1])
            if score < MIN_SIM:
                continue
            key = tuple(sorted((va, vb)))
            if key in seen_verse_pairs:
                continue
            seen_verse_pairs.add(key)
            st["aligned_verses"] += 1
            only_a = [lx for lx in verses[va] if lx not in verses[vb] and content(lx)]
            only_b = [lx for lx in verses[vb] if lx not in verses[va] and content(lx)]
            if len(only_a) == 1 and len(only_b) == 1 and pos[only_a[0]] == pos[only_b[0]]:
                x, y = only_a[0], only_b[0]
                if strong_of.get(x) and strong_of.get(y) and strong_of[x] != strong_of[y]:
                    pair = tuple(sorted((x, y)))
                    pairs[pair] += 1
                    examples[pair].append(f"{va[0]} {va[1]}:{va[2]} // {vb[0]} {vb[1]}:{vb[2]}")
                    st["substitutions"] += 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        fh.write("# CANDIDATE Hebrew pairs from parallel passages: one content word substituted for another where "
                 "two\n# passages tell the same thing (Samuel-Kings // Chronicles etc.). Passage pairs from BSB "
                 "section references\n# (public domain); words from MACULA Hebrew (CC BY 4.0). Derived data CC0. "
                 "Built by shoresh/macula/build_parallel_substitutions.py.\n")
        fh.write("strong_a\tstrong_b\tlexeme_a\tlexeme_b\tcount\texamples\n")
        for (x, y), c in sorted(pairs.items(), key=lambda kv: -kv[1]):
            a, b = sorted(((strong_of[x], x), (strong_of[y], y)))
            fh.write(f"{a[0]}\t{b[0]}\t{a[1]}\t{b[1]}\t{c}\t{'; '.join(examples[(x, y)][:3])}\n")
    print(f"[parallel-substitutions] {dict(st)} -> {len(pairs)} distinct pairs -> {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
