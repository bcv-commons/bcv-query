#!/usr/bin/env python3
"""The connective that opens each clause and what kind of link it makes (wave 2 clause relation, development-phase plan; research's gap
list 2026-11-13: connectives tgl 0.65, ind 0.40 chrF3 of the oracle gap).

    cd shoresh && .venv/bin/python3 -m macula.build_connectives      (after build_clause_columns)

One row per layout clause (keys as in bcv-commons/clause-columns):
  conn        the clause's opening connective lemma(s) ('' when none): Hebrew conjunctions and discourse particles among its first
              three words (וְ, כִּי, אֲשֶׁר, אִם, פֶּן, לְמַעַן, גַּם, אַךְ, רַק, הִנֵּה, עַתָּה ...); Greek the conjunctions among its first four
              words (καί, δέ, γάρ, οὖν, ἀλλά, ὅτι, ἵνα, εἰ, ὡς, ὅτε ...), and the connective the layout moves to the clause
  link        sequence      Hebrew wayyiqtol, or וְ + weqatal (a chain of events, past or procedural)
              disjunctive   Hebrew וְ + a fronted constituent before the verb (background, contrast, simultaneity)
              circumstantial Hebrew וְ + a verbless clause
              episode       Hebrew וַיְהִי opening a clause with a time or circumstance phrase, or וְהָיָה likewise
              and_now       Hebrew וְעַתָּה / עַתָּה (a turn in speech to its point)
              look          הִנֵּה / ἰδού
              coordination  other וְ; Greek καί / τέ
              development   Greek δέ, οὖν (a new step), μέν … δέ
              contrast      Greek ἀλλά, πλήν; Hebrew אֲבָל, אֶפֶס, אַךְ, כִּי אִם
              reason        Greek γάρ, ὅτι, διότι, ἐπεί; Hebrew כִּי, יַעַן, עַל־כֵּן with relation causal
              content       ὅτι, כִּי, אֲשֶׁר with relation complement / speech
              purpose, condition, time, result, relative, comparison
                            from the layout's relation (purpose / conditional / temporal / consequence / relative / comparison)
              asyndetic     no connective
  relation    the layout's relation (Hebrew relation; Greek v0.7 relation), as is
  line        clause-columns `line` (main / background / setting / speech / non-narrative)
Output: macula/data/connectives/{clauses.tsv, checks.md, build.json} (git-ignored). Not read: BHSA, TBTA, English text.
"""
from __future__ import annotations

import collections
import datetime
import json
import sqlite3
import subprocess
import unicodedata
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = DATA / "connectives"
MSPINE = HERE / "macula-spine.db"
GRC_V07 = HERE.parent.parent / "internal-docs/greek-nt-clause-layout-release/v0.7/data/clauses.parquet"
HBO_PARTICLES = {"וְ", "כִּי", "אֲשֶׁר", "אִם", "פֶּן", "לְמַעַן", "גַּם", "אַךְ", "רַק", "הִנֵּה", "עַתָּה", "אֲבָל", "אֶפֶס", "יַעַן",
                 "כֵּן", "אוֹ", "לוּ", "לוּלֵא", "בַּעֲבוּר", "טֶרֶם", "כַּאֲשֶׁר", "אָז", "שֶׁ", "דִּי", "הֵן"}
GRC_CONJ = {"καί", "δέ", "γάρ", "οὖν", "ἀλλά", "ὅτι", "ἵνα", "εἰ", "ἐάν", "ὡς", "ὅτε", "ὅταν", "τέ", "μέν", "πλήν", "διότι", "ἐπεί",
            "ὥστε", "καθώς", "ὅπως", "ἤ", "οὐδέ", "μηδέ", "οὔτε", "ἕως", "διό", "ἰδού", "ἄρα", "τότε", "ὥσπερ", "εἴτε"}
HBO_PARTICLES = {unicodedata.normalize("NFC", x) for x in HBO_PARTICLES}      # MACULA's lemmas order dagesh and vowel otherwise
REL = {"purpose": "purpose", "conditional": "condition", "temporal": "time", "consequence": "result", "relative": "relative",
       "comparison": "comparison", "causal": "reason", "complement": "content", "speech": "content", "adversative": "contrast",
       "concession": "contrast", "circumstantial": "circumstantial"}


def N(x: str) -> str:
    return unicodedata.normalize("NFC", x)


def main() -> int:
    m = sqlite3.connect(f"file:{MSPINE}?mode=ro", uri=True)
    lem = {k: unicodedata.normalize("NFC", l or "") for k, l in m.execute("select key, lemma from macula_words")}
    cls = dict(m.execute("select key, class from macula_words"))
    cc = {}
    for name in ("hebrew", "greek-nt"):
        for r in pq.read_table(DATA / "clause-columns" / f"{name}.parquet", columns=["clause_key", "conj", "front", "line", "verb"]).to_pylist():
            cc[r["clause_key"]] = r
    grc_layout = {}
    if GRC_V07.exists():
        for r in pq.read_table(GRC_V07, columns=["first", "relation", "connective"]).to_pylist():
            grc_layout[r["first"]] = (r["relation"] or "", list(r["connective"] or []))
    rows, st = [], collections.Counter()
    for corpus, sub, field in (("hbo", "clause-layout", "clause_key"), ("grc", "nt-clause-layout", "first")):
        seen = set()
        for f in sorted((DATA / sub / "clauses").glob("*/*.jsonl")):
            for line in open(f, encoding="utf-8"):
                r = json.loads(line)
                k = r[field]
                if k in seen:
                    continue
                seen.add(k)
                ws = r["words"]
                c = cc.get(k, {})
                if corpus == "hbo":
                    rel = r.get("relation") or ""
                    first = [w for w in ws[:4]]
                    conns = [lem.get(w, "") for w in first[:3] if lem.get(w, "") in HBO_PARTICLES]
                    conj, front, verb = c.get("conj") or "", c.get("front") or "", c.get("verb") or ""
                    waw = N("וְ") in conns
                    lems = [lem.get(w, "") for w in ws]
                    if conj == "wayyiqtol" and lem.get(verb) == N("הָיָה") and len(ws) <= 3 and verb in ws[:2]:
                        link = "episode"
                    elif conj == "weqatal" and lem.get(verb) == N("הָיָה") and len(ws) <= 3:
                        link = "episode"
                    elif N("עַתָּה") in conns:
                        link = "and_now"
                    elif N("הִנֵּה") in conns:
                        link = "look"
                    elif conj in ("wayyiqtol", "weqatal"):
                        link = "sequence"
                    elif rel in REL and (conns or rel in ("relative",)):
                        link = REL[rel]
                    elif waw and front == "verbless":
                        link = "circumstantial"
                    elif waw and front and front != "verbless":
                        link = "disjunctive"
                    elif any(x in conns for x in (N("אֲבָל"), N("אֶפֶס"), N("אַךְ"))):
                        link = "contrast"
                    elif waw:
                        link = "coordination"
                    elif conns:
                        link = REL.get(rel, "other")
                    else:
                        link = "asyndetic"
                else:
                    rel, moved = grc_layout.get(k, ("", []))
                    conns = [lem.get(w, "") for w in ws[:4] if cls.get(w) in ("conj", "cj") or lem.get(w, "") in GRC_CONJ]
                    conns = [x for x in conns if x in GRC_CONJ] + [lem.get(w, "") for w in moved if lem.get(w, "") not in conns]
                    s = set(conns)
                    if "ἰδού" in s:
                        link = "look"
                    elif s & {"ἀλλά", "πλήν"}:
                        link = "contrast"
                    elif s & {"γάρ", "διότι", "ἐπεί"}:
                        link = "reason"
                    elif rel in REL and rel not in ("circumstantial",):
                        link = REL[rel]
                    elif s & {"δέ", "οὖν", "διό", "ἄρα", "τότε"}:
                        link = "development"
                    elif s & {"καί", "τέ", "οὐδέ", "μηδέ", "οὔτε"}:
                        link = "coordination"
                    elif rel == "circumstantial":
                        link = "circumstantial"
                    elif conns:
                        link = "other"
                    else:
                        link = "asyndetic"
                rows.append([corpus, k, " ".join(conns), link, rel, c.get("line") or ""])
                st[(corpus, link)] += 1
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "clauses.tsv", "w", encoding="utf-8") as f:
        f.write("corpus\tclause_key\tconn\tlink\trelation\tline\n")
        f.writelines("\t".join(r) + "\n" for r in rows)
    lines = ["# Connectives: checks", "", f"Clauses: {len(rows):,}.", "", "| corpus | link | clauses |", "|---|---|---|"]
    lines += [f"| {c} | {v} | {n:,} |" for (c, v), n in sorted(st.items(), key=lambda x: (x[0][0], -x[1]))]
    (OUT / "checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    code = subprocess.run(["git", "log", "-1", "--format=%h"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    (OUT / "build.json").write_text(json.dumps({"schema": 1, "built": datetime.date.today().isoformat(), "code": code,
                                                "greek_layout": "v0.7 (relation, connective)",
                                                "not_read": ["BHSA", "TBTA", "English text"]}, indent=1) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
