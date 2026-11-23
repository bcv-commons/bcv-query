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
from macula import text_faults

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "internal-docs" / "brenton-glaux-join" / "v0.2"
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
    faults, dropped = text_faults.load("grc_bre"), []
    with open(a.ids / "bre" / "words.tsv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if r["word_id"] in faults and faults[r["word_id"]]["fix"] == "drop":
                dropped.append(r["word_id"]); continue
            tok = faults[r["word_id"]]["fixed"] if r["word_id"] in faults and faults[r["word_id"]]["fix"] == "replace" else r["token"]
            bre[(r["book"], int(r["chapter"]), int(r["verse"]))].append((r["word_id"], plain(tok)))
    by_book = collections.defaultdict(list)
    for k in G:
        by_book[k[0]].append(k)
    # 1. chapter by chapter: Brenton's chapter against GLAUx's chapter of the same reference, word by word, so a verse
    #    boundary drawn elsewhere costs nothing (Brenton GEN 47:4 holds GLAUx 47:4 and the start of 47:5)
    used, rows, st = set(), {}, collections.Counter()
    gch = collections.defaultdict(list)
    for k in sorted(G, key=lambda k: (k[1], k[2])):
        gch[(k[0], k[1])] += [(gid, t, k) for gid, t in G[k]]
    bch = collections.defaultdict(list)
    for k in sorted(bre, key=lambda k: (lp_order(k[0]), k[1], k[2])):
        bch[(k[0], k[1])].append(k)
    pending = []
    for (b, c), vks in sorted(bch.items(), key=lambda x: (lp_order(x[0][0]), x[0][1])):
        g0 = gref(b, c, 1)
        if g0[0] not in books:
            st["outside"] += sum(len(bre[k]) for k in vks); continue
        bw = [(w, t, k) for k in vks for w, t in bre[k]]
        gw = gch.get(g0[:2], [])
        got = pair([t for _, t, _ in bw], [t for _, t, _ in gw]) if gw else []
        m = {i: (j, link) for i, j, link in got}
        for k in vks:                                         # a verse keeps the chapter's pairing if half its words are `same`
            idx = [i for i, x in enumerate(bw) if x[2] == k]
            if sum(1 for i in idx if i in m and m[i][1] == "same") >= 0.5 * len(idx):
                own = gref(*k)
                for i in idx:
                    if i in m:
                        j, link = m[i]; gid, _, gk = gw[j]
                        used.add(gid)
                        rows[bw[i][0]] = (bw[i][0], gid, link, f"{gk[0]} {gk[1]}:{gk[2]}", "same_ref" if gk == own else "neighbour")
                    else:
                        rows[bw[i][0]] = (bw[i][0], "", "none", "", "same_ref")
            else:
                pending.append(k)
    # 2. the verses left (chapters numbered or ordered otherwise: Jeremiah, Exodus 35-40, Proverbs 24-31): the GLAUx verse of
    #    the same book whose free words pair best, if half the verse's words pair `same` and at least two of them are not
    #    short function words (καί alone does not make a match)
    book_verses = {b: sorted(ks, key=lambda k: (k[1], k[2])) for b, ks in by_book.items()}

    def search(toks, g0):
        """the best run of up to six consecutive GLAUx verses (free words only) for these Brenton words, or None"""
        content = {t for t in toks if len(t) > 3}
        vs = book_verses[g0[0]]
        best = None
        for n, g in enumerate(vs):
            if not content & {t for _, t in G[g]}:
                continue
            for w in range(1, 7):
                run = vs[n:n + w]
                free = [(gid, t, gk) for gk in run for gid, t in G[gk] if gid not in used]
                if not free:
                    continue
                got = pair(toks, [t for _, t, _ in free])
                same = [x for x in got if x[2] == "same"]
                near = any(gk[:2] == g0[:2] and abs(gk[2] - g0[2]) <= 1 for gk in run)
                nc = sum(1 for x in same if len(toks[x[0]]) > 3)
                # half the words (a quarter at the verse's own place), with two content words; or a long stretch outright
                # (20 words, 10 of them content words: not chance)
                if ((len(same) >= (0.25 if near else 0.5) * len(toks) and nc >= 2) or (len(same) >= 20 and nc >= 10)) \
                        and (best is None or len(same) > best[0] or (len(same) == best[0] and len(free) < len(best[2]))):
                    best = (len(same), got, free)
                if len(free) > 2 * len(toks):
                    break
        return best

    for k in pending:
        g0 = gref(*k)
        words = bre[k]
        hit = {}                                               # word index -> (gid, link, gk)
        todo = [list(range(len(words)))]
        while todo:                                            # a match, then the stretches it left (Brenton PRO 24:22 holds
            seg = todo.pop()                                   # GLAUx 24:22 and 30:1-14)
            best = search([words[i][1] for i in seg], g0)
            if not best:
                continue
            _, got, free = best
            m = {seg[i]: (free[j][0], link, free[j][2]) for i, j, link in got}
            for i, x in m.items():
                used.add(x[0]); hit[i] = x
            run = []
            for i in seg + [None]:
                if i is not None and i not in m:
                    run.append(i); continue
                if len(run) >= 5:
                    todo.append(run)
                run = []
        for i, (w, _) in enumerate(words):
            if i in hit:
                gid, link, gk = hit[i]
                rows[w] = (w, gid, link, f"{gk[0]} {gk[1]}:{gk[2]}", "searched")
            else:
                rows[w] = (w, "", "none", "", "searched" if hit else "unpaired")
    for w in dropped:
        rows[w] = (w, "", "none", "", f"fault:{faults[w]['fault_id']}")
    rows = sorted(rows.values(), key=lambda r: r[0])
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
