"""Brenton's words joined to GLAUx's Septuagint words (the id standard of 2026-11-23, D3 (c)). Local, unpublished.

    cd shoresh && .venv/bin/python -m macula.build_brenton_glaux_join --ids DIR [--out DIR]

For every Brenton word of the books in the Hebrew canon (ids from build_text_ids, `bre:`), the GLAUx word it is (`lxx:` +
GLAUx's word id), or none. GLAUx: the bridge corpus' pinned stores (canonical books; Daniel by Theodotion for Brenton's DAG).

The verse: GLAUx's verse of the same reference (Brenton's ESG is Esther, DAG Daniel by Theodotion, EZR 11-23 Nehemiah 1-13).
When that verse is missing, or fewer than half of Brenton's words pair in it, the GLAUx verse of the same book that pairs
best is taken instead, if it pairs at least half (`verse_basis` searched; Proverbs 24-31, Jeremiah, Exodus 35-40, Malachi 4
are in another order in one of the texts). Each GLAUx verse is joined at most once.

In the verse, words pair in order by plain form (difflib's matching blocks; no marks, lowercase, final sigma, no elision
mark): `link` same. In a gap of the same length on both sides, word i pairs with word i: `variant` (forms alike, ratio >=
0.75: a spelling) or `differs` (another word in the same slot). Otherwise `none`.

Licence: the table holds GLAUx's ids, so it is CC BY-SA 4.0, as GLAUx.
"""
from __future__ import annotations

import argparse
import collections
import csv
import difflib
import json
import sqlite3
import unicodedata as ud
from pathlib import Path

from macula import build_lxx_parts as lp

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "internal-docs" / "brenton-glaux-join" / "v0.1"
RENAME = {"ESG": "EST", "DAG": "DAN"}


def plain(s: str) -> str:
    s = "".join(c for c in ud.normalize("NFD", s) if not ud.combining(c)).lower().replace("ς", "σ")
    return "".join(c for c in s if c.isalpha() and ud.category(c) != "Lm")


def glaux():
    st = lp.stores()
    out = collections.defaultdict(list)
    for name, sql, th in (("septuagint", "select book, chapter, verse, idx, glaux_id, surface from lxx_words where canonical = 1", False),
                          ("theodotion", "select book, chapter, verse, idx, glaux_id, surface from lxx_words where book = 'DAN'", True)):
        con = sqlite3.connect(f"file:{st[name]}?mode=ro", uri=True)
        for b, c, v, i, g, s in con.execute(sql + " order by book, chapter, verse, idx"):
            out[(b + ("-TH" if th else ""), c, v)].append((f"lxx:{g}", plain(s)))
    return out


def gref(b, c, v):
    if b == "EZR" and c >= 11:
        return ("NEH", c - 10, v)
    if b == "DAG":
        return ("DAN-TH", c, v)
    return (RENAME.get(b, b), c, v)


def pair(a, g):
    """[(i in a, j in g, link)]"""
    out = []
    i = j = 0
    for x in difflib.SequenceMatcher(None, a, g, autojunk=False).get_matching_blocks():
        ga, gg = list(range(i, x.a)), list(range(j, x.b))
        if ga and len(ga) == len(gg):
            for p, q in zip(ga, gg):
                out.append((p, q, "variant" if difflib.SequenceMatcher(None, a[p], g[q]).ratio() >= 0.75 else "differs"))
        out += [(x.a + k, x.b + k, "same") for k in range(x.size)]
        i, j = x.a + x.size, x.b + x.size
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", type=Path, required=True, help="build_text_ids' folder")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    if a.out.exists() and any(a.out.iterdir()):
        raise SystemExit(f"{a.out} is not empty; give a fresh folder")
    a.out.mkdir(parents=True)
    G = glaux()
    books = {k[0] for k in G}
    bre = collections.defaultdict(list)
    with open(a.ids / "bre" / "words.tsv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            bre[(r["book"], int(r["chapter"]), int(r["verse"]))].append((r["word_id"], plain(r["token"])))
    by_book = collections.defaultdict(list)
    for k in G:
        by_book[k[0]].append(k)
    used, rows, st = set(), [], collections.Counter()
    pending = []
    for k in sorted(bre, key=lambda k: (lp_order(k[0]), k[1], k[2])):
        g = gref(*k)
        if g[0] not in books:
            st["outside"] += len(bre[k]); continue
        toks = [t for _, t in bre[k]]
        got = pair(toks, [t for _, t in G[g]]) if g in G else []
        if g in G and sum(1 for x in got if x[2] == "same") >= 0.5 * len(toks):
            used.add(g); rows += emit(bre[k], G[g], got, g, "same_ref"); continue
        pending.append(k)
    for k in pending:                                          # the verses numbered otherwise: the best free verse of the book
        g0 = gref(*k)
        toks = [t for _, t in bre[k]]
        best, bg = None, None
        for g in by_book[g0[0]]:
            if g in used:
                continue
            got = pair(toks, [t for _, t in G[g]])
            n = sum(1 for x in got if x[2] == "same")
            if n >= 0.5 * len(toks) and (best is None or n > best[0]):
                best, bg = (n, got), g
        if best:
            used.add(bg); rows += emit(bre[k], G[bg], best[1], bg, "searched")
        else:
            rows += [(w, "", "none", "", "unpaired") for w, _ in bre[k]]
    for r in rows:
        st[f"link {r[2]}"] += 1; st[f"verse {r[4]}"] += 1
    with open(a.out / "join.tsv", "w", encoding="utf-8") as f:
        f.write("bre_word_id\tlxx_word_id\tlink\tlxx_verse\tverse_basis\n")
        f.writelines("\t".join(r) + "\n" for r in rows)
    n = len(rows)
    L = ["# Brenton -> GLAUx word join: checks", "", f"Brenton words in GLAUx's books: {n:,}", ""]
    L += [f"- {k}: {v:,} ({v / n:.1%})" for k, v in sorted(st.items()) if k != "outside"]
    L += ["", f"Brenton words outside GLAUx's books (not joined): {st['outside']:,}"]
    glaux_ids = [r[1] for r in rows if r[1]]
    L += [f"GLAUx words joined more than once: {len(glaux_ids) - len(set(glaux_ids))}"]
    (a.out / "checks.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (a.out / "build.json").write_text(json.dumps({"release": "Brenton-GLAUx join (local, unpublished)", "licence": "CC BY-SA 4.0",
                                                  "ids": str(a.ids.name), "rows": n}, indent=1) + "\n")
    print("\n".join(L))


def emit(bw, gw, got, g, basis):
    m = {i: (j, link) for i, j, link in got}
    ref = f"{g[0]} {g[1]}:{g[2]}"
    return [(w, gw[m[i][0]][0], m[i][1], ref, basis) if i in m else (w, "", "none", ref, basis) for i, (w, _) in enumerate(bw)]


def lp_order(b):
    from macula.build_text_ids import NUMBER
    return NUMBER.get(b, 99)


if __name__ == "__main__":
    main()
