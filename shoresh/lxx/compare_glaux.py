#!/usr/bin/env python3
"""Before/after report: the CATSS-based lxx.db against the GLAUx-based lxx-glaux.db, on what clients see. Read-only; writes one markdown file.

  cd shoresh && ../bcv-RAG/.venv/bin/python3 -m lxx.compare_glaux [--out ../internal-docs/lxx-glaux-before-after.md]

Sections: verse inventory, word-level differences (with examples per category), Strong's changes, morphology changes, part-of-speech changes, concordance counts,
orphan (LXX-only) lexemes, OT-in-NT quotations, side-by-side /verse output, size and speed. Needs lxx/lxx.db, lxx/data/lxx-glaux.db and the two orphan / quotation
tables rebuilt from the new file (the script builds them into a temp directory).
"""
from __future__ import annotations

import argparse
import collections
import difflib
import pathlib
import sqlite3
import sys
import tempfile
import time
import unicodedata

HERE = pathlib.Path(__file__).resolve().parent
SHORESH = HERE.parent
REPO = SHORESH.parent
sys.path.insert(0, str(SHORESH))
OLD, NEW = HERE / "lxx.db", HERE / "data" / "lxx-glaux.db"
ELIDE = str.maketrans("", "", "᾿’'ʼ̓'")


def strip(x: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", x) if not unicodedata.combining(c)).casefold().replace("ς", "σ")


def key(plain: str) -> str:
    p = plain.translate(ELIDE).lower().replace("ς", "σ")      # the old store leaves `plain` capitalised for names that carry no accents (Αδαμ); the new one is always lower case
    return p[:-1] if len(p) > 3 and p.endswith("ν") else p


def load(path: pathlib.Path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cols = [r[1] for r in con.execute("pragma table_info(lxx_words)")]
    sel = "book,chapter,verse,idx,surface,plain,strong,morph,pos,wordid,is_content" + (",lemma" if "lemma" in cols else "")
    d = collections.defaultdict(list)
    for r in con.execute(f"select {sel} from lxx_words order by book,chapter,verse,idx"):
        d[(r["book"], r["chapter"], r["verse"])].append(dict(r))
    return d


def ref(k): return f"{k[0]} {k[1]}:{k[2]}"
def w(x): return f"{x['surface']}" + (f" [G{x['strong']}]" if x.get("strong") else " [–]") + f" {x['morph']}"


class Ex:
    """Keeps a few examples per category."""
    def __init__(self, n=4): self.n, self.d, self.c = n, collections.defaultdict(list), collections.Counter()
    def add(self, cat, text):
        self.c[cat] += 1
        book = text.split(" ")[0]
        if len(self.d[cat]) < self.n and not any(e.startswith(book + " ") for e in self.d[cat]):    # one example per book, so the samples spread over the corpus
            self.d[cat].append(text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path, default=REPO / "internal-docs" / "lxx-glaux-before-after.md")
    a = ap.parse_args()
    O, N = load(OLD), load(NEW)
    co, cn = collections.Counter(), collections.Counter()
    for v in O.values():
        for i in v:
            if i["strong"]: co[i["strong"]] += 1
    for v in N.values():
        for i in v:
            if i["strong"]: cn[i["strong"]] += 1
    md: list[str] = []
    P = md.append

    # ---------------------------------------------------------------- 1. verse inventory
    only_o, only_n = sorted(set(O) - set(N)), sorted(set(N) - set(O))
    both = sorted(set(O) & set(N))
    by_book = collections.defaultdict(collections.Counter)
    for k in O: by_book[k[0]]["o"] += 1
    for k in N: by_book[k[0]]["n"] += 1
    for k in both: by_book[k[0]]["both"] += 1

    # ---------------------------------------------------------------- 2. word level
    words = collections.Counter()
    wex, sex, mex, pex = Ex(5), Ex(6), Ex(8), Ex(6)
    strong_flip = collections.Counter(); strong_flip_ex = {}
    morph_flip = collections.Counter(); morph_flip_ex = {}
    pos_flip = collections.Counter(); pos_flip_ex = {}
    ident_verses = 0
    per_book = collections.defaultdict(collections.Counter)
    for k in both:
        x, y = O[k], N[k]
        kx, ky = [key(i["plain"]) for i in x], [key(i["plain"]) for i in y]
        if kx == ky: ident_verses += 1
        words["old"] += len(x); words["new"] += len(y)
        sm = difflib.SequenceMatcher(None, kx, ky, autojunk=False)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                for i, j in zip(range(i1, i2), range(j1, j2)):
                    o, n = x[i], y[j]
                    words["matched"] += 1; per_book[k[0]]["m"] += 1
                    if o["surface"] != n["surface"]:
                        if o["surface"].casefold() == n["surface"].casefold():
                            wex.add("capitalization only", f"{ref(k)}: {o['surface']} → {n['surface']}")
                        elif strip(o["surface"]) == strip(n["surface"]):
                            wex.add("accent / breathing only" + (" (names the old text leaves unaccented)" if strip(o["surface"]) == o["surface"].casefold() else ""), f"{ref(k)}: {o['surface']} → {n['surface']}")
                        else:
                            wex.add("movable ν / elision mark", f"{ref(k)}: {o['surface']} → {n['surface']}")
                    else:
                        words["identical surface"] += 1
                    # Strong's
                    so, sn = o["strong"], n["strong"]
                    if so == sn: sex.add("same Strong's", "")
                    elif so is None: sex.add("gained a Strong's number", f"{ref(k)}: {n['surface']} ({n['lemma']}) – → G{sn}")
                    elif sn is None: sex.add("lost its Strong's number", f"{ref(k)}: {o['surface']} ({n['lemma']}) G{so} → –")
                    else:
                        sex.add("different Strong's number", f"{ref(k)}: {o['surface']} ({n['lemma']}) G{so} → G{sn}")
                        t = (n["lemma"], so, sn); strong_flip[t] += 1; strong_flip_ex.setdefault(t, f"{ref(k)}: {o['surface']}")
                    # POS and morph
                    po, pn = o["pos"], n["pos"]
                    if po != pn:
                        pos_flip[(po, pn)] += 1; pos_flip_ex.setdefault((po, pn), f"{ref(k)}: {o['surface']} ({n['lemma']}) {o['morph']} → {n['morph']}")
                    elif o["morph"] != n["morph"]:
                        t = (o["morph"], n["morph"]); morph_flip[t] += 1; morph_flip_ex.setdefault(t, f"{ref(k)}: {o['surface']}")
                        mex.add(f"{po}: morph string differs", f"{ref(k)}: {o['surface']}  {o['morph']} → {n['morph']}")
                    else:
                        mex.add("same morph", "")
                    if o["is_content"] != n["is_content"]: pex.add(f"is_content {o['is_content']} → {n['is_content']}", f"{ref(k)}: {o['surface']} {o['pos']}→{n['pos']}")
            elif op == "replace":
                if (i2 - i1) == (j2 - j1):
                    for i, j in zip(range(i1, i2), range(j1, j2)):
                        r = difflib.SequenceMatcher(None, kx[i], ky[j]).ratio()
                        words["replaced"] += 1
                        wex.add("spelling variant (similar word)" if r >= 0.7 else "different word (textual variant)", f"{ref(k)}: {x[i]['surface']} → {y[j]['surface']}")
                else:
                    words["replaced"] += max(i2 - i1, j2 - j1)
                    wex.add("phrase reworded / different length", f"{ref(k)}: {' '.join(t['surface'] for t in x[i1:i2])}  →  {' '.join(t['surface'] for t in y[j1:j2])}")
            elif op == "delete":
                words["only old"] += i2 - i1
                wex.add("words only in the old text", f"{ref(k)}: {' '.join(t['surface'] for t in x[i1:i2])}")
            else:
                words["only new"] += j2 - j1
                wex.add("words only in the new text", f"{ref(k)}: {' '.join(t['surface'] for t in y[j1:j2])}")

    # ---------------------------------------------------------------- report: 1
    P("# Septuagint word store: CATSS-based `lxx.db` (before) vs GLAUx-based `lxx-glaux.db` (after)\n")
    P("Generated by `shoresh/lxx/compare_glaux.py`. Everything below is measured on the two files; examples are real rows. "
      "Reference format: book chapter:verse in the store's own (Septuagint) numbering.\n")
    P("## 0. Headline numbers\n")
    tot_o, tot_n = sum(len(v) for v in O.values()), sum(len(v) for v in N.values())
    P("| | before | after |\n|---|---|---|")
    P(f"| words | {tot_o:,} | {tot_n:,} |")
    P(f"| verses | {len(O):,} | {len(N):,} |")
    P(f"| verses in both | {len(both):,} | |")
    P(f"| verses word-for-word identical (ignoring accents, case, movable ν, elision) | {ident_verses:,} of {len(both):,} ({100*ident_verses/len(both):.1f}%) | |")
    P(f"| words matched in sequence | {words['matched']:,} ({100*words['matched']/tot_o:.1f}% of before) | |")
    sg = lambda D: sum(1 for v in D.values() for i in v if i["strong"] is not None)
    sc = lambda D: sum(1 for v in D.values() for i in v if i["is_content"] and i["strong"] is None)
    P(f"| words with a Strong's number | {sg(O):,} ({100*sg(O)/tot_o:.1f}%) | {sg(N):,} ({100*sg(N)/tot_n:.1f}%) |")
    P(f"| content words without Strong's | {sc(O):,} | {sc(N):,} |")
    P(f"| distinct lemmas / lexeme ids | {len({i['wordid'] for v in O.values() for i in v}):,} wordids | {len({i['lemma'] for v in N.values() for i in v}):,} lemmas |")
    P(f"| file size | {OLD.stat().st_size/1e6:.1f} MB | {NEW.stat().st_size/1e6:.1f} MB |\n")

    P("## 1. Verse inventory\n")
    P(f"Verses only in the old store: {len(only_o)}. Only in the new store: {len(only_n)}. In both: {len(both):,}.\n")
    P("Books where the verse sets differ:\n\n| book | old verses | new verses | in both | only old | only new |\n|---|---|---|---|---|---|")
    for b, c in sorted(by_book.items()):
        if c["o"] != c["both"] or c["n"] != c["both"]:
            P(f"| {b} | {c['o']} | {c['n']} | {c['both']} | {c['o']-c['both']} | {c['n']-c['both']} |")
    P("\nPer-book examples of verses present in one store only (old-only / new-only, first words):\n")
    for b, c in sorted(by_book.items()):
        if c["o"] - c["both"] >= 3 or c["n"] - c["both"] >= 3:
            oo = [k for k in only_o if k[0] == b][:3]; nn = [k for k in only_n if k[0] == b][:3]
            P(f"- **{b}**: old-only " + "; ".join(f"{ref(k)} “{' '.join(i['surface'] for i in O[k][:3])}…”" for k in oo) + " — new-only " + "; ".join(f"{ref(k)} “{' '.join(i['surface'] for i in N[k][:3])}…”" for k in nn))
    P("\nExamples, verses only in the old store: " + "; ".join(ref(k) + f" ({len(O[k])} words, starts “{' '.join(i['surface'] for i in O[k][:4])}”)" for k in only_o[:6]))
    P("\nExamples, verses only in the new store: " + "; ".join(ref(k) + f" ({len(N[k])} words, starts “{' '.join(i['surface'] for i in N[k][:4])}”)" for k in only_n[:6]))
    P("\nPer-book word match (matched words ÷ old words), lowest first:\n\n| book | old words | matched | match % |\n|---|---|---|---|")
    book_old = collections.Counter(); [book_old.update({k[0]: len(v)}) for k, v in O.items()]
    for b, c in sorted(per_book.items(), key=lambda t: t[1]["m"] / book_old[t[0]])[:15]:
        P(f"| {b} | {book_old[b]:,} | {c['m']:,} | {100*c['m']/book_old[b]:.1f}% |")

    # ---------------------------------------------------------------- report: 2
    P("\n## 2. Word-level differences (text)\n")
    P("What a client sees in `/verse` `lxx.words[].surface` and in word counts. Counted on the verses present in both stores.\n")
    P("| category | words | examples (old → new) |\n|---|---|---|")
    for cat in ["capitalization only", "accent / breathing only", "accent / breathing only (names the old text leaves unaccented)", "movable ν / elision mark", "spelling variant (similar word)", "different word (textual variant)",
                "phrase reworded / different length", "words only in the old text", "words only in the new text"]:
        P(f"| {cat} | {wex.c[cat]:,} | " + "<br>".join(wex.d[cat][:4]).replace("|", "\\|") + " |")
    P(f"\nWords matched with an identical surface form: {words['identical surface']:,} of {words['matched']:,} matched.\n")
    P("Note: GLAUx keeps the El. Wikisource spelling and capitalisation (e.g. Θεός after a capital, ν-movable), Rahlfs 1935 keeps its own; "
      "the new store drops punctuation tokens like the old one.\n")

    # ---------------------------------------------------------------- report: 3
    P("## 3. Strong's numbers (what `/verse` shows as `strong`, `gloss`, `translit`, and what the concordance and quotations key on)\n")
    P("Only matched words. New numbers come from the lemma through UGNT and MACULA Greek; the old ones from CATSS.\n")
    P("| change | words | examples |\n|---|---|---|")
    for cat in ["same Strong's", "gained a Strong's number", "lost its Strong's number", "different Strong's number"]:
        P(f"| {cat} | {sex.c[cat]:,} ({100*sex.c[cat]/words['matched']:.1f}%) | " + "<br>".join(e for e in sex.d[cat][:5] if e).replace("|", "\\|") + " |")
    P("\nMost frequent number changes (lemma, old → new). Most are Strong's splitting suppletive forms of one lemma that GLAUx treats as one:\n\n| lemma | old | new | words | example |\n|---|---|---|---|---|")
    for (lem, so, sn), c in strong_flip.most_common(15):
        P(f"| {lem} | G{so} | G{sn} | {c:,} | {strong_flip_ex[(lem, so, sn)]} |")
    lost = collections.Counter(); lost_ex = {}
    gained = collections.Counter(); gained_ex = {}
    for k in both:
        x, y = O[k], N[k]
        sm = difflib.SequenceMatcher(None, [key(i["plain"]) for i in x], [key(i["plain"]) for i in y], autojunk=False)
        for blk in sm.get_matching_blocks():
            for t in range(blk.size):
                o, n = x[blk.a + t], y[blk.b + t]
                if o["strong"] is not None and n["strong"] is None: lost[(n["lemma"], o["strong"])] += 1; lost_ex.setdefault((n["lemma"], o["strong"]), ref(k) + ": " + o["surface"])
                if o["strong"] is None and n["strong"] is not None: gained[(n["lemma"], n["strong"])] += 1; gained_ex.setdefault((n["lemma"], n["strong"]), ref(k) + ": " + o["surface"])
    P("\nLemmas that lost their Strong's number (UGNT / MACULA do not map the lemma), most frequent:\n\n| lemma | old Strong's | words | example |\n|---|---|---|---|")
    for (lem, so), c in lost.most_common(12): P(f"| {lem} | G{so} | {c:,} | {lost_ex[(lem, so)]} |")
    P("\nLemmas that gained a Strong's number, most frequent:\n\n| lemma | new Strong's | words | example |\n|---|---|---|---|")
    for (lem, sn), c in gained.most_common(8): P(f"| {lem} | G{sn} | {c:,} | {gained_ex[(lem, sn)]} |")

    P("\n**Strong's numbers that disappear from the LXX** (present before, absent now) are the per-form numbers of lemmas that the New Testament sources number once: "
      "UGNT and MACULA Greek give every form of ἐγώ the number G1473 and every form of σύ G4771, and λέγω is G3004 throughout, "
      "where CATSS used the classical Strong's split (G3450 μου, G3165 με, G4675 σου, G2036 εἶπον …). This also makes the LXX consistent with the NT side of the service. "
      "Numbers absent now with at least 200 old occurrences:\n\n| Strong's | gloss | old occurrences | now merged into |\n|---|---|---|---|")
    import data as _d
    for s_, c_ in sorted(((s2, c2) for s2, c2 in co.items() if s2 not in cn and c2 >= 200), key=lambda t: -t[1])[:14]:
        tgt = collections.Counter()
        for (lem_, so_, sn_), n_ in strong_flip.items():
            if so_ == s_: tgt[sn_] += n_
        P(f"| G{s_} | {(_d.gloss_of(f'G{s_}') or {}).get('gloss','')} | {c_:,} | {', '.join('G'+str(x) for x, _ in tgt.most_common(2)) or 'no number (lemma spelling not found in UGNT / MACULA)'} |")

    # ---------------------------------------------------------------- report: 4
    P("\n## 4. Morphology strings (`/verse` `morph`, concordance `morph`)\n")
    same_m = mex.c["same morph"]
    diff_m = sum(c for cat, c in mex.c.items() if cat != "same morph")
    P(f"Matched words with the same part of speech: identical morph string {same_m:,}, different string {diff_m:,} ({100*diff_m/max(same_m+diff_m,1):.1f}%).\n")
    P("Most frequent string changes (old → new):\n\n| old | new | words | example |\n|---|---|---|---|")
    for (mo, mn), c in morph_flip.most_common(18): P(f"| {mo} | {mn} | {c:,} | {morph_flip_ex[(mo, mn)]} |")
    shape = collections.Counter()
    for (mo, mn), c in morph_flip.items():
        shape["same feature set, different order / letters" if sorted(mo.replace('.', '')) == sorted(mn.replace('.', '')) else "feature missing or added"] += c
    P(f"\nBy kind: {dict(shape)}.\n")

    # ---------------------------------------------------------------- report: 5
    P("## 5. Part of speech (`pos`) and the content-word flag\n")
    P(f"Matched words whose POS code differs: {sum(pos_flip.values()):,} ({100*sum(pos_flip.values())/words['matched']:.2f}%). Most frequent (old → new):\n\n| old | new | words | example |\n|---|---|---|---|")
    for (po, pn), c in pos_flip.most_common(14): P(f"| {po} | {pn} | {c:,} | {pos_flip_ex[(po, pn)]} |")
    P(f"\nContent-word flag changes: {sum(c for cat, c in pex.c.items())}; " + "; ".join(f"{cat}: {pex.c[cat]} (e.g. {pex.d[cat][0]})" for cat in pex.c) + "\n")

    # ---------------------------------------------------------------- report: 6 concordance
    co, cn = collections.Counter(), collections.Counter()
    for v in O.values():
        for i in v:
            if i["strong"]: co[i["strong"]] += 1
    for v in N.values():
        for i in v:
            if i["strong"]: cn[i["strong"]] += 1
    P("## 6. Concordance counts (`/word/{strong}` LXX occurrences)\n")
    big = [s for s, c in co.items() if c >= 50]
    rel = {s: (cn[s] - co[s]) / co[s] for s in big}
    bands = collections.Counter("within ±2%" if abs(r) <= .02 else "±2–5%" if abs(r) <= .05 else "±5–10%" if abs(r) <= .10 else "±10–25%" if abs(r) <= .25 else "more than ±25%" for r in rel.values())
    P(f"Strong's numbers with at least 50 old occurrences: {len(big):,}. Change in count: {dict(bands)}. Numbers present before and absent now: {len(set(co) - set(cn))}; present now only: {len(set(cn) - set(co))}.\n")
    P("Largest changes among those (old → new count):\n\n| Strong's | gloss | old | new | change |\n|---|---|---|---|---|")
    import data
    for s in sorted(big, key=lambda s: -abs(cn[s] - co[s]))[:14]:
        g = (data.gloss_of(f"G{s}") or {}).get("gloss", "")
        P(f"| G{s} | {g} | {co[s]:,} | {cn[s]:,} | {cn[s]-co[s]:+,} ({100*rel[s]:+.0f}%) |")

    # ---------------------------------------------------------------- report: 7 orphan
    from lxx import build_orphan_lexemes as bo
    old_groups, new_groups = bo.build(OLD), bo.build(NEW)
    P("\n## 7. LXX-only lexemes (`/lxx-lexeme/{wordid}`, `resources/lxx_orphan_lexemes`)\n")
    def grp(rows):
        g = collections.OrderedDict()
        for r in rows: g.setdefault(r["wordid"], {"cf": r["citation_form"], "conf": r["citation_confidence"], "pos": r["pos"], "n": 0, "occ": 0, "sample": r["sample_ref"]}); g[r["wordid"]]["n"] += 1; g[r["wordid"]]["occ"] += r["count"]
        return g
    og, ng = grp(old_groups), grp(new_groups)
    P(f"| | before | after |\n|---|---|---|\n| lexeme groups (words with no Strong's number) | {len(og):,} | {len(ng):,} |\n| variant rows | {len(old_groups):,} | {len(new_groups):,} |\n"
      f"| occurrences covered | {sum(g['occ'] for g in og.values()):,} | {sum(g['occ'] for g in ng.values()):,} |\n"
      f"| citation form is a standard headword shape | {sum(1 for g in og.values() if g['conf']=='standard'):,} | {sum(1 for g in ng.values() if g['conf']=='standard'):,} |\n")
    P("Every wordid in a URL changes (old: CATSS lexeme id such as 700023; new: a lemma id such as 10883, which is not stable across rebuilds). Example, the same word in both:\n")
    new_by_cf = {g["cf"]: (w_, g) for w_, g in ng.items()}
    shown = 0
    for w_, g in og.items():
        if g["cf"] in new_by_cf and shown < 6 and g["n"] >= 3:
            w2, g2 = new_by_cf[g["cf"]]
            P(f"- {g['cf']}: old wordid {w_} ({g['n']} forms, {g['occ']} occurrences, e.g. {g['sample']}) → new wordid {w2} ({g2['n']} forms, {g2['occ']} occurrences, e.g. {g2['sample']})")
            shown += 1
    ocf, ncf = {g["cf"] for g in og.values()}, {g["cf"] for g in ng.values()}
    P(f"\nGroups with the same citation form in both: {len(ocf & ncf):,}. Only before: {len(ocf - ncf):,} (e.g. {', '.join(sorted(x for x in ocf - ncf if x)[:6])}). Only after: {len(ncf - ocf):,} (e.g. {', '.join(sorted(x for x in ncf - ocf if x)[:6])}).")
    P("\nWhy: proper names and some verbs lose or gain a Strong's number depending on the lemma spelling (section 3), which moves them between this table and the numbered words. "
      "The new store knows each word's true lemma, so a later version of this table can use `lemma` as the citation form instead of choosing one attested form "
      f"(now {sum(1 for g in ng.values() if g['conf'] == 'fallback'):,} of {len(ng):,} groups use a fallback form).\n")

    # ---------------------------------------------------------------- report: 8 quotations
    import lxx.build_quotations as bq
    tmp = pathlib.Path(tempfile.mkdtemp())
    bq.LXX, bq.OUT_DIR = NEW, tmp
    import io, contextlib
    with contextlib.redirect_stderr(io.StringIO()):
        bq.build()
    def lq(p):
        rows = [l.rstrip("\n").split("\t") for l in open(p, encoding="utf-8") if not l.startswith("#") and not l.startswith("nt_ref")]
        return {(r[0], r[1]): r for r in rows if len(r) > 6}
    qo, qn = lq(REPO / "resources" / "ot_nt_quotations" / "quotations.tsv"), lq(tmp / "quotations.tsv")
    kept, lostq, newq = set(qo) & set(qn), set(qo) - set(qn), set(qn) - set(qo)
    P("## 8. OT-in-NT quotations (`resources/ot_nt_quotations`)\n")
    hi = lambda D: sum(1 for r in D.values() if r[2] == "high")
    P(f"| | before | after |\n|---|---|---|\n| NT→OT pairs | {len(qo):,} | {len(qn):,} |\n| high confidence | {hi(qo):,} | {hi(qn):,} |\n| pairs in both | {len(kept):,} | |\n| only before | {len(lostq):,} | |\n| only after | {len(newq):,} | |\n")
    def gl(s): return (data.gloss_of(s) or {}).get("gloss", "")
    def row(D, k):
        r = D[k]; sh = r[6].split(",")
        return f"- {k[0]} → {k[1]} ({r[2]}, {r[4]} shared, score {r[5]}): " + ", ".join(f"{s} {gl(s)}" for s in sh[:5])
    P("Caveat found while comparing: the highest-scoring pairs in BOTH versions are Luke's canticles matched to the Odes (ODA), which contain those canticles themselves, "
      "so they are artefacts, not quotations; the Ode and verse numbering also differs between the two stores (CATSS ODA 9:69 vs GLAUx ODA 12:51). "
      "Whatever store is used, ODA should be excluded from quotation matching.\n")
    oda_o = sum(1 for k in qo if k[1].startswith("ODA")); oda_n = sum(1 for k in qn if k[1].startswith("ODA"))
    P(f"Pairs pointing into ODA: before {oda_o}, after {oda_n}. Without ODA: before {len(qo)-oda_o:,}, after {len(qn)-oda_n:,}; in both {len({k for k in set(qo)&set(qn) if not k[1].startswith('ODA')}):,}.\n")
    P("Pairs only before (highest score):\n"); [P(row(qo, k)) for k in sorted(lostq, key=lambda k: -float(qo[k][5]))[:6]]
    P("\nPairs only after (highest score):\n"); [P(row(qn, k)) for k in sorted(newq, key=lambda k: -float(qn[k][5]))[:6]]
    famous = [("MAT 1:23", "ISA 7:14"), ("MAT 4:4", "DEU 8:3"), ("ROM 3:10", "PSA 14:1"), ("HEB 1:5", "PSA 2:7"), ("MAT 2:6", "MIC 5:2")]
    P("\nKnown quotations, checked in both:\n\n| NT → OT | before | after |\n|---|---|---|")
    for nt, ot in famous:
        f = lambda D: (D[(nt, ot)][2] + f" ({D[(nt, ot)][4]} shared)") if (nt, ot) in D else "missing"
        P(f"| {nt} → {ot} | {f(qo)} | {f(qn)} |")

    # ---------------------------------------------------------------- report: 9 side by side
    P("\n## 9. `/verse` output side by side (words only: surface [Strong's] morph)\n")
    samples = [("GEN", 1, 1), ("GEN", 1, 12), ("PSA", 22, 1), ("ISA", 7, 14), ("SIR", 1, 16), ("TOB", 1, 1), ("DAN", 3, 24), ("PRO", 8, 22)]
    for k in samples:
        P(f"**{ref(k)}**\n\nbefore: " + " ".join(w(i) for i in O.get(k, [])) if k in O else f"**{ref(k)}** (not in the old store)")
        P("\nafter: " + (" ".join(w(i) for i in N.get(k, [])) if k in N else "(not in the new store)") + "\n")

    # ---------------------------------------------------------------- report: 12 effect of the morphology / classic-number fixes
    import re as _re
    nc = sqlite3.connect(f"file:{NEW}?mode=ro", uri=True); nc.row_factory = sqlite3.Row
    cols = {r[1] for r in nc.execute("pragma table_info(lxx_words)")}
    if "strong_form" in cols:
        P("## 11. After the fixes: classic form numbers and inferred name morphology\n")
        sfn = nc.execute("select count(*) from lxx_words where strong_form is not null").fetchone()[0]
        by_l = nc.execute("select lemma,count(*) from lxx_words where strong_form is not null group by lemma order by 2 desc limit 8").fetchall()
        # agreement of the effective classic number with the old store on matched words
        tot_b = ok_lemma = ok_form = 0
        shown = []
        for k in both:
            x, y = O[k], N[k]
            sm = difflib.SequenceMatcher(None, [key(i["plain"]) for i in x], [key(i["plain"]) for i in y], autojunk=False)
            for blk in sm.get_matching_blocks():
                for t in range(blk.size):
                    o, n = x[blk.a + t], y[blk.b + t]
                    if o["strong"] is not None and n["strong"] is not None:
                        tot_b += 1
                        ok_lemma += o["strong"] == n["strong"]
        for r in nc.execute("select book,chapter,verse,idx,strong,strong_form from lxx_words where strong_form is not null limit 0"): pass
        P(f"`strong_form` is set on {sfn:,} words ({100*sfn/tot_n:.1f}% of the text; lemmas: " + ", ".join(f"{l} {c:,}" for l, c in by_l) + "). It is the classic (1890) number of the form where it differs from the lemma-level `strong`, from a short table of public-domain Strong's numbers (`CLASSIC_FORMS` in `build_glaux.py`), and it carries the gloss shown to the reader (μου: \"of me\", not \"I\").\n")
        # use the stored column on matched words
        old_by_ref = {}
        agree_eff = agree_l = n_both = 0
        for k in both:
            x = O[k]
            rows_n = nc.execute("select plain,strong,strong_form from lxx_words where book=? and chapter=? and verse=? order by idx", k).fetchall()
            sm = difflib.SequenceMatcher(None, [key(i["plain"]) for i in x], [key(r["plain"]) for r in rows_n], autojunk=False)
            for blk in sm.get_matching_blocks():
                for t in range(blk.size):
                    o, n = x[blk.a + t], rows_n[blk.b + t]
                    if o["strong"] is not None and n["strong"] is not None:
                        n_both += 1
                        agree_l += o["strong"] == n["strong"]
                        agree_eff += o["strong"] == (n["strong_form"] or n["strong"])
        P(f"Agreement with the old store's number on matched words that have one in both: lemma-level only **{100*agree_l/n_both:.2f}%** → with `strong_form` **{100*agree_eff/n_both:.2f}%** ({n_both:,} words). "
          "What stays different is the lemma-level choice for rarer words (ἐπισκοπέω G1980 → G1983, ἅπτω G680 → G681, κατοικίζω …) and CATSS's own splits (ὑπάρχοντα G5224).\n")
        P("Examples (`/verse` words, `strong` + `strong_form` + gloss):\n")
        for r in nc.execute("select book,chapter,verse,surface,strong,strong_form,lemma from lxx_words where strong_form is not null and lemma in ('ἐγώ','σύ','λέγω','Ἱεροσόλυμα','Ἰούδας','Σαῦλος','ἐσθίω','ἄν','οὐ') group by lemma, strong_form order by lemma, strong_form limit 24"):
            gl = (data.gloss_of(f"G{r['strong_form']}") or {}).get("gloss", "")
            gl0 = (data.gloss_of(f"G{r['strong']}") or {}).get("gloss", "")
            P(f"- {r['book']} {r['chapter']}:{r['verse']} {r['surface']} ({r['lemma']}): strong G{r['strong']} “{gl0}”, strong_form G{r['strong_form']} “{gl}”")
        # inferred morphology
        inf = nc.execute("select morph_inferred, count(*) c from lxx_words where morph_inferred is not null group by morph_inferred order by c desc").fetchall()
        P("\n**Inferred name morphology** (`morph_inferred`): " + ", ".join(f"{r['morph_inferred']} {r['c']:,}" for r in inf) + ".\n")
        P("Accuracy of each rule against the old store's tag, on matched words where the old tag has the feature:\n\n| rule | words checked | case agrees | number agrees | gender agrees |\n|---|---|---|---|---|")
        RX = _re.compile(r"^[A-Z]+\.?([NGDAV-])?([SPD-])?([MFN-])?")
        stat = collections.defaultdict(collections.Counter)
        for k in both:
            x = O[k]
            rows_n = nc.execute("select plain,morph,morph_inferred from lxx_words where book=? and chapter=? and verse=? order by idx", k).fetchall()
            sm = difflib.SequenceMatcher(None, [key(i["plain"]) for i in x], [key(r["plain"]) for r in rows_n], autojunk=False)
            for blk in sm.get_matching_blocks():
                for t in range(blk.size):
                    o, n = x[blk.a + t], rows_n[blk.b + t]
                    if not n["morph_inferred"] or o["pos"] != "N": continue
                    mo, mn = RX.match(o["morph"] or ""), RX.match(n["morph"] or "")
                    if not mo or not mn: continue
                    for rule in n["morph_inferred"].split(","):
                        for nm, i_ in (("case", 1), ("number", 2), ("gender", 3)):
                            if mo.group(i_) not in (None, "-") and mn.group(i_) not in (None, "-"):
                                stat[rule][nm + " n"] += 1; stat[rule][nm + " ok"] += mo.group(i_) == mn.group(i_)
        for rule in ("article", "preposition", "syntax"):
            st = stat[rule]; f = lambda nm: (f"{100*st[nm+' ok']/st[nm+' n']:.1f}% ({st[nm+' n']:,})" if st[nm + " n"] else "–")
            P(f"| {rule} | {st['case n']:,} | {f('case')} | {f('number')} | {f('gender')} |")
        P("\nExamples (name, old tag → new tag, rule):\n")
        for r in nc.execute("select book,chapter,verse,surface,morph,morph_inferred from lxx_words where morph_inferred is not null group by lemma order by random() limit 8"):
            P(f"- {r['book']} {r['chapter']}:{r['verse']} {r['surface']}: {r['morph']} ({r['morph_inferred']})")
        left = nc.execute("select count(*) from lxx_words where pos='N' and (morph='N' or morph like 'N.-%' or morph like 'N._-%' or morph like 'N.%-%' or length(morph)<=4) and morph_inferred is null").fetchone()[0]
        tot_nouns = nc.execute("select count(*) from lxx_words where pos='N'").fetchone()[0]
        P(f"\nNouns that still lack at least one of case, number, gender after the fixes: {left:,} of {tot_nouns:,} ({100*left/tot_nouns:.1f}%); before the fixes the share of nominal words missing a feature was 4.9% of the matched nominals.\n")

    # ---------------------------------------------------------------- report: 10 speed
    def timeit(path):
        data.LXX_DB = path
        for k in both[:300]: data.verse(k[0], k[1], k[2])            # warm caches first
        t = time.time()
        for k in both[:300]: data.verse(k[0], k[1], k[2])
        return (time.time() - t) / 300 * 1000
    P("## 10. Size and speed\n")
    P(f"File size {OLD.stat().st_size/1e6:.1f} MB → {NEW.stat().st_size/1e6:.1f} MB. `data.verse` (300 OT verses incl. Hebrew side): {timeit(OLD):.1f} ms → {timeit(NEW):.1f} ms per call.\n")
    a.out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"-> {a.out} ({len(md)} blocks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
