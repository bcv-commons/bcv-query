"""Yardstick for the Hebrew level-2 parts: BHSA's morpheme marks (CC BY-NC 4.0, read here only to measure; no BHSA value
goes into any output but counts).

    cd shoresh && .venv/bin/python -m macula.check_hebrew_parts_bhsa [--parts PARTS.tsv] [--out checks_bhsa.md]

Per MACULA part joined to a BHSA word (bhsa-macula-bridge.db), the number of letters of our prefix is compared with BHSA's
preformative (pfm), and the letters of our ending with BHSA's verbal + nominal ending and paragogic letter (vbe + nme + uvf).
BHSA's pointed marks (g_pfm, g_vbe, g_nme, g_uvf) are counted, so that a word is compared by the letters it is written with.
A paragogic letter (uvf) counts either way; where BHSA's ending letter stands in the part MACULA itself split off as a
suffix (אֱלֹהָ|יו, תְּנָ|ה), the case is counted apart (MACULA's level-1 boundary is kept). BHSA's stem formatives (vbs) and the participle's / infinitive's מ- or ה- preformative are counted apart, because the
standard keeps them in the stem on purpose. Writes counts and the commonest disagreements, by MACULA's morph code and
lemma (our side only).
"""
from __future__ import annotations

import argparse
import collections
import csv
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TF = Path.home() / "text-fabric-data/github/ETCBC/bhsa/tf/2021"
PARTS = HERE.parent.parent / "internal-docs" / "word-parts-v1" / "hebrew" / "parts.tsv"
LETTERS = set(">BGDHWZXVJKLMNS<PYQRFCT")
csv.field_size_limit(sys.maxsize)


def read_tf(p):
    vals, node, body = {}, 0, False
    for line in open(p, encoding="utf-8"):
        line = line.rstrip("\n")
        if not body:
            body = line == ""
            continue
        if "\t" in line:
            k, v = line.split("\t", 1)
            if "-" in k:
                a, b = map(int, k.split("-"))
                for i in range(a, b + 1):
                    vals[i] = v
                node = b
                continue
            node = int(k)
        else:
            node, v = node + 1, line
        vals[node] = v
    return vals


def n_letters(v):
    return 0 if v in (None, "absent", "n/a") else sum(1 for ch in v if ch in LETTERS)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parts", type=Path, default=PARTS)
    ap.add_argument("--bridge", type=Path, default=HERE / "bhsa-macula-bridge.db")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    # the pointed marks (g_*): the letters as written, so a short spelling (אֲבֹתֵי without the waw) counts as written
    f = {k: read_tf(TF / f"g_{k}.tf") for k in ("pfm", "vbe", "nme", "uvf", "vbs")}
    plain_pfm = read_tf(TF / "pfm.tf")
    bridge = {}
    for node, key in sqlite3.connect(f"file:{a.bridge}?mode=ro", uri=True).execute("SELECT node, key FROM bridge"):
        bridge[key] = node
    ours = collections.defaultdict(lambda: {"prefix": 0, "ending": 0, "fused": False, "morph": "", "text": [], "kind": "",
                                            "word": "", "n1": 0})
    with open(a.parts, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
            o = ours[r["macula_id"]]
            k = r["kind"]
            cons = sum(1 for ch in r["text"] if "א" <= ch <= "ת")
            if k == "prefix":
                o["prefix"] = cons
            elif k == "ending":
                o["ending"] = cons
            elif k == "fused":
                o["fused"] = True
            if k in ("prefix", "ending", "fused"):
                o["morph"] = r["features"]
            o["text"].append(r["text"]); o["kind"] = o["kind"] or k
            o["word"], o["n1"] = r["word_id"], int(r["macula_id"][-1])
    nxt = {}
    for key, o in ours.items():
        nxt[(o["word"], o["n1"])] = o
    cnt, dis = collections.Counter(), collections.Counter()
    for key, o in ours.items():
        node = bridge.get(key)
        if node is None:
            cnt["not joined to BHSA"] += 1
            continue
        if o["kind"] in ("particle", "suffix"):
            continue
        cnt["compared"] += 1
        bp, bv = plain_pfm.get(node), f["vbs"].get(node)
        be = n_letters(f["vbe"].get(node)) + n_letters(f["nme"].get(node)) + n_letters(f["uvf"].get(node))
        if o["fused"]:
            cnt["fused (not compared)"] += 1
            continue
        pm = n_letters(f["pfm"].get(node))
        if bp in ("M", "H", "L") and o["prefix"] == 0:
            cnt["prefix: BHSA M-/H-/L- preformative, kept in the stem (convention)"] += 1
        elif o["prefix"] == pm:
            cnt["prefix: same"] += 1
        else:
            cnt["prefix: differs"] += 1
            dis[("prefix", "ours %d, BHSA %d" % (o["prefix"], pm), o["morph"][:3] or "-", "|".join(o["text"]))] += 1
        if n_letters(bv):
            cnt["stem formative (vbs) present, kept in the stem"] += 1
        nx = nxt.get((o["word"], o["n1"] + 1))
        uv = n_letters(f["uvf"].get(node))
        if o["ending"] == be or uv and o["ending"] == be - uv:
            cnt["ending: same"] += 1
        elif o["ending"] < be and nx is not None and nx["kind"] != "particle":
            cnt["ending: BHSA's letter is in MACULA's suffix part (level 1, kept)"] += 1
        else:
            cnt["ending: differs"] += 1
            dis[("ending", "ours %d, BHSA %d" % (o["ending"], be), o["morph"][:3] or "-", "|".join(o["text"]))] += 1
    pre = cnt["prefix: same"] + cnt["prefix: differs"]
    end = cnt["ending: same"] + cnt["ending: differs"]
    L = ["# Hebrew level 2 against BHSA's morpheme marks (counts only)", "",
         f"Prefix: same letters as BHSA's preformative in {cnt['prefix: same']:,} of {pre:,} ({cnt['prefix: same'] / max(pre, 1):.1%}).",
         f"Ending: same letters as BHSA's endings in {cnt['ending: same']:,} of {end:,} ({cnt['ending: same'] / max(end, 1):.1%}).", "",
         "| count | what |", "|---|---|"] + [f"| {v:,} | {k} |" for k, v in sorted(cnt.items())]
    kinds = collections.Counter()
    for (side, how, m, _), v in dis.items():
        kinds[(side, how, m)] += v
    L += ["", "## Disagreements by side, letters and MACULA morph (first 3 characters)", "", "| count | side | letters | morph |",
          "|---|---|---|---|"] + [f"| {v:,} | {s} | {h} | {m} |" for (s, h, m), v in kinds.most_common(40)]
    L += ["", "## Commonest disagreeing parts (our cut)", ""] + \
         [f"- {v} x {t} ({s}, {h}, {m})" for (s, h, m, t), v in dis.most_common(60)]
    txt = "\n".join(L) + "\n"
    if a.out:
        a.out.write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
