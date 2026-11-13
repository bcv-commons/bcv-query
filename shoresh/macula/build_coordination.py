#!/usr/bin/env python3
"""What every "and" joins: a clause to the one before, or items inside a phrase (wave 2; research's over-production of dan / na,
2026-11-13: dropping the clause-level ones lowered chrF, so the surplus is phrase-level).

    cd shoresh && .venv/bin/python3 -m macula.build_coordination      (after build_arg_roles)

One row per Hebrew וְ and Greek καί (conjunction):
  corpus, key, clause_key
  kind       clause   the word opens its layout clause (it is the clause key, or only conjunctions stand before it)
             phrase   it stands inside a constituent of roles.tsv: it joins items of one phrase ("bread and wine")
             other    elsewhere (between constituents, or a clause the layout does not split)
  items      phrase only: how many items the phrase's conjunctions join (conjunctions + 1)
  position   phrase only: this conjunction's place among the phrase's conjunctions (1 = first)
  last       phrase only: 1 when it is the phrase's last conjunction (where many languages write their only "and" in a list)
Output: macula/data/coordination/{words.tsv, checks.md, build.json} (git-ignored). Not read: BHSA, TBTA, English text.
"""
from __future__ import annotations

import collections
import csv
import datetime
import json
import sqlite3
import subprocess
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = DATA / "coordination"
MSPINE = HERE / "macula-spine.db"
WAW = unicodedata.normalize("NFC", "וְ")


def main() -> int:
    m = sqlite3.connect(f"file:{MSPINE}?mode=ro", uri=True)
    conj = {}
    for k, lang, lem, cls in m.execute("select key, lang, lemma, class from macula_words"):
        lem = unicodedata.normalize("NFC", lem or "")
        if (lang == "hbo" and lem == WAW) or (lang == "grc" and lem == "καί" and cls == "conj"):
            conj[k] = lang
    cls_of = dict(m.execute("select key, class from macula_words"))
    wclause, first_words = {}, {}
    for corpus, sub, field in (("hbo", "clause-layout", "clause_key"), ("grc", "nt-clause-layout", "first")):
        for f in sorted((DATA / sub / "clauses").glob("*/*.jsonl")):
            for line in open(f, encoding="utf-8"):
                r = json.loads(line)
                ck = r[field]
                ws = sorted(r["words"])
                for w in ws:
                    wclause.setdefault(w, ck)
                if ck not in first_words:
                    lead = []
                    for w in ws:
                        lead.append(w)
                        if cls_of.get(w) not in ("cj", "conj"):
                            break
                    first_words[ck] = set(lead)
    in_phrase = {}
    for r in csv.DictReader(open(DATA / "arg-roles/roles.tsv", encoding="utf-8"), delimiter="\t"):
        ws = sorted(r["words"].split())
        cs = [w for w in ws if w in conj and w != ws[0]]          # a conjunction leading the constituent links the clause
        for i, w in enumerate(cs):
            in_phrase[w] = (len(cs) + 1, i + 1, i == len(cs) - 1)
    rows, st = [], collections.Counter()
    for k in sorted(conj):
        corpus = "hbo" if conj[k] == "hbo" else "grc"
        ck = wclause.get(k, "")
        if ck and (k == ck or k in first_words.get(ck, ())):
            kind, items, pos, last = "clause", "", "", ""
        elif k in in_phrase:
            n, p, la = in_phrase[k]
            kind, items, pos, last = "phrase", str(n), str(p), "1" if la else "0"
        else:
            kind, items, pos, last = "other", "", "", ""
        rows.append([corpus, k, ck, kind, items, pos, last])
        st[(corpus, kind)] += 1
        if kind == "phrase":
            st[(corpus, f"phrase items={min(int(items), 4)}{'+' if int(items) >= 4 else ''} last={last}")] += 1
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "words.tsv", "w", encoding="utf-8") as f:
        f.write("corpus\tkey\tclause_key\tkind\titems\tposition\tlast\n")
        f.writelines("\t".join(r) + "\n" for r in rows)
    lines = ["# Coordination: checks", "", f"Conjunctions: {len(rows):,}.", "", "| corpus | value | count |", "|---|---|---|"]
    lines += [f"| {c} | {v} | {n:,} |" for (c, v), n in sorted(st.items())]
    (OUT / "checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    code = subprocess.run(["git", "log", "-1", "--format=%h"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    (OUT / "build.json").write_text(json.dumps({"schema": 1, "built": datetime.date.today().isoformat(), "code": code,
                                                "not_read": ["BHSA", "TBTA", "English text"]}, indent=1) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
