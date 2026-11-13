#!/usr/bin/env python3
"""Inclusive / exclusive "we": one value per first-person plural word of the Hebrew Bible and the Greek NT (wave 1d,
development-phase plan 2026-11-13). Combines the verse votes and the rules of macula/build_we_votes.py (run that first).

    cd shoresh && .venv/bin/python3 -m macula.build_we_layer

Per word (macula/data/we-layer/words.tsv):
  key, lang, book, chapter, verse, clause_key (the layout clause holding the word, as in bcv-commons/clause-columns)
  form           verb | pronoun | suffix (Hebrew pronominal suffix) | possessive (Greek ἡμέτερος)
  value          i (inclusive: speaker and addressee) | e (exclusive: speaker's group without the addressee) | split (translators
                 differ: both readings are real) | unknown (too little evidence)
  alternative    the other reading where one is attested: for split both are; for i / e the minority vote or a disagreeing rule
  basis          votes (75% of 3+ decisive votes from the open editions) | rule:to_god | rule:let_us | votes+rule:<name> (both agree)
                 | rule:<name>,votes_split (the rule settles a split verse)
  n_i, n_e       the verse's decisive inclusive / exclusive votes (9 voting editions)
  agree          the majority's share among them
The value is per verse: several "we" words in one verse share it (research 2026-11-13: about 5% of edition votes are mixed;
word-level resolution later, only where several editions say "mixed").
Codes only; no translation text. Not read: BHSA, TBTA, English text.
"""
from __future__ import annotations

import collections
import csv
import datetime
import json
import sqlite3
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
VOTES = DATA / "we-votes" / "verses.tsv"
OUT = DATA / "we-layer"
MSPINE = HERE / "macula-spine.db"
COLS = ["key", "lang", "book", "chapter", "verse", "clause_key", "form", "value", "alternative", "basis", "n_i", "n_e", "agree"]


def word_clause() -> dict[str, str]:
    out = {}
    for corpus, sub, field in (("hbo", "clause-layout", "clause_key"), ("grc", "nt-clause-layout", "first")):
        for f in sorted((DATA / sub / "clauses").glob("*/*.jsonl")):
            for line in open(f, encoding="utf-8"):
                r = json.loads(line)
                for w in r["words"]:
                    out.setdefault(w, r[field])
    return out


def main() -> int:
    m = sqlite3.connect(f"file:{MSPINE}?mode=ro", uri=True)
    info = {k: (lang, cls or "", lem or "") for k, lang, cls, lem in m.execute("select key, lang, class, lemma from macula_words")}
    wc = word_clause()
    rows, st = [], collections.Counter()
    for r in csv.DictReader(open(VOTES, encoding="utf-8"), delimiter="\t"):
        v, rule, rb = r["value"], r["rule"], r["rule_basis"]
        n_i, n_e = int(r["n_i"]), int(r["n_e"])
        alt = ""
        if v in ("i", "e"):
            value = v
            minority = "e" if v == "i" else "i"
            if rule and rule != v:
                basis, alt = "votes", rule
            elif rule:
                basis = f"votes+rule:{rb}"
            else:
                basis = "votes"
            if not alt and (n_e if v == "i" else n_i):
                alt = minority
        elif v == "split":
            if rule:
                value, basis, alt = rule, f"rule:{rb},votes_split", ("e" if rule == "i" else "i")
            else:
                value, basis, alt = "split", "votes", "i e"
        else:
            value, basis = (rule, f"rule:{rb}") if rule else ("unknown", "")
        for k in r["src_keys"].split():
            lang, cls, lem = info.get(k, ("", "", ""))
            form = ("possessive" if lem == "ἡμέτερος" else "verb" if cls == "verb" else
                    "suffix" if lang == "hbo" and cls == "pron" and len(k) == 12 and k[-1] != "1" else "pronoun")
            rows.append([k, lang or ("hbo" if len(k) == 12 else "grc"), r["book"], r["chapter"], r["verse"], wc.get(k, ""), form,
                         value, alt, basis, str(n_i), str(n_e), r["agree"]])
            st[(rows[-1][1], value)] += 1
            st[(rows[-1][1], "basis:" + basis.split(",")[0].split("+")[0])] += 1
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "words.tsv", "w", encoding="utf-8") as f:
        f.write("\t".join(COLS) + "\n")
        f.writelines("\t".join(r) + "\n" for r in rows)
    lines = ["# Inclusive / exclusive \"we\" per word: checks", "", f"Words: {len(rows):,}.", "", "| lang | value or basis | words |",
             "|---|---|---|"]
    lines += [f"| {l} | {k} | {n:,} |" for (l, k), n in sorted(st.items())]
    (OUT / "checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    code = subprocess.run(["git", "log", "-1", "--format=%h"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    (OUT / "build.json").write_text(json.dumps({"schema": 1, "built": datetime.date.today().isoformat(), "code": code,
                                                "inputs": {"we-votes": str(VOTES.relative_to(HERE))},
                                                "not_read": ["BHSA", "TBTA", "English text"]}, indent=1) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
