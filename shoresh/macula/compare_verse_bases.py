"""Acceptance report for the /verse Hebrew base switch (NC exit, step 1; design: internal-docs/nc-exit-step1-verse-design.md, section 8).

Compares the two bases of `GET /verse` for the Old Testament: UHB (`spine.db`, English-style numbering, OpenHebrewBible-reconciled) and MACULA
(`macula-spine.db`, Hebrew numbering). The two numberings are lined up with TVTMS (STEPBible, CC BY; bibles' org-to-eng map); then

  1. TEXT       word totals per verse group (a group = the Hebrew verses that map to one UHB verse; Psalm titles map to UHB verse 0)
  2. STRONG'S   word-by-word agreement of UHB's Strong's number with the head piece's, by sequence alignment (not by position); every
                difference is counted by kind and the most frequent pairs are listed
  3. COVERAGE   on a seeded sample of verses, through data.verse() itself: gloss, sense, group, setting, explanations, menahem per word,
                response size and time, for both bases
  4. GOLDEN     a few verses side by side

  cd shoresh && .venv/bin/python3 -m macula.compare_verse_bases [--sample 1500] [--out ../internal-docs/verse-base-comparison.md]

Acceptance thresholds are in the design document; this script only measures and prints PASS / CHECK next to each.
"""
from __future__ import annotations

import argparse
import collections
import difflib
import json
import os
import random
import re
import sqlite3
import statistics
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
MAP_URL = "https://cdn.bibel.wiki/_vrs/map/org-to-eng.json"


def load_map(src: str = MAP_URL) -> list[dict]:
    if re.match(r"https?://", src):
        req = urllib.request.Request(src, headers={"User-Agent": "bcv-query"})
        return json.load(urllib.request.urlopen(req, timeout=60))["map"]
    return json.load(open(src, encoding="utf-8"))["map"]


def ref(s: str) -> tuple[str, int, int]:
    m = re.match(r"([A-Z0-9]{3}) (\d+):(\d+|title)", s)
    return m.group(1), int(m.group(2)), 0 if m.group(3) == "title" else int(m.group(3))


def uhb_words() -> dict[tuple, list]:
    con = sqlite3.connect(f"file:{HERE.parent / 'spine' / 'spine.db'}?mode=ro", uri=True)
    out: dict = collections.defaultdict(list)
    for b, c, v, s in con.execute("SELECT book, chapter, verse, strong FROM spine_words ORDER BY book, chapter, verse, idx"):
        out[(b, c, v)].append(s)
    return out


def macula_words() -> dict[tuple, list]:
    import verse_hebrew
    from macula.build_spine_words import rollup_strong
    from spine.common import load_equivalences
    eq = load_equivalences()
    con = sqlite3.connect(f"file:{HERE / 'macula-spine.db'}?mode=ro", uri=True)
    cols = ["key", "text", "lemma", "strong", "class"]
    rows = con.execute("SELECT " + ",".join(f'"{c}"' for c in cols) + ", book, chapter, verse FROM macula_words WHERE lang='hbo' ORDER BY key").fetchall()
    out: dict = collections.defaultdict(list)
    cur, tokens = None, []

    def flush():
        for parts in verse_hebrew.group_words(tokens):
            h = parts[verse_hebrew.head_index(parts)]
            out[cur].append(rollup_strong(h["strong"], "hbo", eq) if h["strong"] else None)
    for r in rows:
        k = (r[5], r[6], r[7])
        if k != cur:
            if tokens:
                flush()
            cur, tokens = k, []
        tokens.append(dict(zip(cols, r[:5])))
    if tokens:
        flush()
    return out


def text_and_strongs(mapping: list[dict], u: dict, m: dict) -> dict:
    o2e = {ref(r["s"]): ref(r["t"]) for r in mapping}
    groups: dict = collections.defaultdict(list)                  # UHB verse -> Hebrew verses, in order
    for ov in sorted(m):
        groups[o2e.get(ov, ov)].append(ov)
    res = {"groups": 0, "equal_len": 0, "uhb_words": 0, "mac_words": 0, "only_uhb": [], "only_mac": [], "diff_len": [],
           "aligned_equal": 0, "uhb_missing": 0, "mac_missing": 0, "different": 0, "unmatched_uhb": 0, "unmatched_mac": 0}
    pairs = collections.Counter(); where: dict = {}
    for ev, ovs in sorted(groups.items()):
        if ev not in u:
            res["only_mac"].append(ev); continue
        a = u[ev]; b = [s for ov in ovs for s in m[ov]]
        res["groups"] += 1; res["uhb_words"] += len(a); res["mac_words"] += len(b)
        if len(a) == len(b):
            res["equal_len"] += 1
        else:
            res["diff_len"].append((ev, len(a), len(b)))
        sm = difflib.SequenceMatcher(None, [x or 0 for x in a], [y or 0 for y in b], autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                res["aligned_equal"] += i2 - i1
            elif tag == "replace" and i2 - i1 == j2 - j1:
                for x, y in zip(a[i1:i2], b[j1:j2]):
                    if not x:
                        res["uhb_missing"] += 1
                    elif not y:
                        res["mac_missing"] += 1
                    else:
                        res["different"] += 1; pairs[(x, y)] += 1; where.setdefault((x, y), ev)
            else:
                res["unmatched_uhb"] += i2 - i1; res["unmatched_mac"] += j2 - j1
    res["only_uhb"] = sorted(set(u) - {e for e in groups})
    res["top_pairs"] = [(x, y, n, where[(x, y)]) for (x, y), n in pairs.most_common(15)]
    return res


def coverage(sample: int, seed: int) -> dict:
    import data
    macula_keys = []
    con = sqlite3.connect(f"file:{HERE / 'macula-spine.db'}?mode=ro", uri=True)
    macula_keys = [tuple(r) for r in con.execute("SELECT DISTINCT book, chapter, verse FROM macula_words WHERE lang='hbo'")]
    random.Random(seed).shuffle(macula_keys)
    out = {}
    for base in ("uhb", "macula"):
        os.environ["VERSE_HEBREW_BASE"] = base
        st = collections.Counter(); times = []; sizes = []; n_verses = 0
        for b, c, v in macula_keys[:sample]:
            t0 = time.perf_counter()
            try:
                sp = data.verse(b, c, v)["spine"]
            except Exception as e:                                  # noqa: BLE001
                st["errors"] += 1; continue
            times.append(time.perf_counter() - t0)
            if not sp:
                st["verses_missing"] += 1; continue
            n_verses += 1; sizes.append(len(json.dumps(sp, ensure_ascii=False)))
            for w in sp["words"]:
                st["words"] += 1
                for f in ("gloss", "sense", "group", "setting", "explanations", "menahem"):
                    st[f] += 1 if w.get(f) else 0
        out[base] = {"verses": n_verses, **st, "median_ms": round(1000 * statistics.median(times), 1) if times else None,
                     "median_kb": round(statistics.median(sizes) / 1024, 1) if sizes else None}
    os.environ["VERSE_HEBREW_BASE"] = "uhb"
    return out


def golden() -> list[str]:
    import data
    lines = []
    for b, c, v in (("GEN", 1, 1), ("EXO", 20, 3), ("PSA", 23, 1), ("PSA", 51, 1), ("ISA", 53, 5), ("DAN", 2, 4), ("EZR", 4, 8), ("JOB", 3, 3)):
        row = [f"{b} {c}:{v}"]
        for base in ("uhb", "macula"):
            os.environ["VERSE_HEBREW_BASE"] = base
            sp = data.verse(b, c, v)["spine"]
            row.append(f"{base}: " + ("-" if not sp else f"{len(sp['words'])} words, " + " ".join(w["strong"] or "?" for w in sp["words"][:8])))
        lines.append(" | ".join(row))
    os.environ["VERSE_HEBREW_BASE"] = "uhb"
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--map", default=MAP_URL)
    ap.add_argument("--out", type=Path, default=HERE.parents[1] / "internal-docs" / "verse-base-comparison.md")
    a = ap.parse_args()
    u, m = uhb_words(), macula_words()
    OT = {k[0] for k in m}
    u = {k: v for k, v in u.items() if k[0] in OT}
    r = text_and_strongs(load_map(a.map), u, m)
    cov = coverage(a.sample, a.seed)
    gold = golden()
    tot = r["aligned_equal"] + r["uhb_missing"] + r["mac_missing"] + r["different"]
    agree = r["aligned_equal"] / max(tot, 1)
    wordgap = abs(r["uhb_words"] - r["mac_words"]) / max(r["uhb_words"], 1)
    L = [f"# /verse Hebrew base comparison: UHB vs MACULA ({time.strftime('%Y-%m-%d')})", "",
         "Generated by `shoresh/macula/compare_verse_bases.py`. Numbering lined up with TVTMS (org-to-eng).", "",
         "## 1. Text", f"- verse groups compared: {r['groups']}; word totals UHB {r['uhb_words']} vs MACULA {r['mac_words']} ({100*wordgap:.2f}% apart) "
         f"{'PASS' if wordgap <= 0.001 else 'CHECK'} (threshold 0.1%)",
         f"- groups with the same word count: {r['equal_len']} ({100*r['equal_len']/r['groups']:.1f}%); different: {len(r['diff_len'])}, e.g. {r['diff_len'][:6]}",
         f"- UHB verses with no Hebrew counterpart after mapping: {len(r['only_uhb'])} {r['only_uhb'][:5]}; Hebrew verses with no UHB verse: {len(r['only_mac'])} {r['only_mac'][:5]}", "",
         "## 2. Strong's number, head piece vs UHB (sequence-aligned)",
         f"- aligned words: {tot}; same number {r['aligned_equal']} = {100*agree:.2f}% {'PASS' if agree >= 0.97 else 'CHECK'} (threshold 97%)",
         f"- UHB has no Strong's number where MACULA does: {r['uhb_missing']}; MACULA has none where UHB does: {r['mac_missing']}; different number: {r['different']}",
         f"- words in blocks that do not line up one to one: UHB {r['unmatched_uhb']}, MACULA {r['unmatched_mac']}",
         "- most frequent differing pairs (UHB -> MACULA, count, first verse): " + "; ".join(f"H{x}->H{y} x{n} ({'%s %d:%d' % ev})" for x, y, n, ev in r["top_pairs"]), "",
         f"## 3. Coverage on a seeded sample of {a.sample} verses, through data.verse()"]
    for base in ("uhb", "macula"):
        c = cov[base]; w = max(c.get("words", 0), 1)
        L.append(f"- {base}: {c['verses']} verses, {c.get('words', 0)} words | with gloss {100*c.get('gloss',0)/w:.1f}% | sense {100*c.get('sense',0)/w:.1f}% | group {100*c.get('group',0)/w:.1f}% | "
                 f"setting {100*c.get('setting',0)/w:.1f}% | explanations {c.get('explanations',0)} | menahem {c.get('menahem',0)} | median {c['median_ms']} ms, {c['median_kb']} KB per verse | errors {c.get('errors',0)}")
    L += ["", "## 4. Golden verses (Strong's of the first words)"] + [f"- {g}" for g in gold]
    a.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
