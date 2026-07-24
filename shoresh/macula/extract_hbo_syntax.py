#!/usr/bin/env python3
"""Extract BHSA phrase-level syntax (function, chain/phrase grouping, construct-relation type)
per Hebrew word node — a companion to resources/occurrences/hbo.db, kept separate rather than
added to it since hbo.db's own builder (bcv-RAG/scripts/build_lex_occurrences.py) has a downstream
sense-population step this shouldn't risk disturbing.

Columns, per BHSA word node:
- `phrase` — the containing BHSA phrase node id. The natural grouping key for a construct chain
  or any other multi-word syntactic unit (e.g. Genesis 1:2's "רוח אלהים"/"Spirit of God" — one
  construct + one absolute word — share one phrase id). Verified directly against the local BHSA
  checkout: every word belongs to exactly one phrase.
- `function` — the phrase's own syntactic function (Subj/Pred/Objc/Time/Loca/Adju/Cmpl/...).
  100% coverage confirmed across all 253,203 Hebrew phrases in the OT — unlike MACULA's own `role`
  (absent entirely from the Hebrew TSV; see macula/build_spine_words.py's docstring), this is
  genuine, comprehensive Hebrew syntactic-role annotation.
- `rela` — the word's own BHSA subphrase relation, where present: `NA` marks the chain's head,
  `rec` marks a construct-governed dependent continuing the chain, `par` marks coordination, etc.
  Blank for words with no subphrase (e.g. a bare preposition outside any chain).

Output: resources/occurrences/hbo_syntax.db (gitignored, same as hbo.db — a build artifact,
regenerable from the local BHSA text-fabric checkout, same discipline as psalm_superscription_
clauses.tsv's one-time extraction, just at full-OT scale rather than committed as a small resource).

Run with the shoresh venv (it has text-fabric + the local BHSA text-fabric corpus):

  shoresh/.venv/bin/python -m macula.extract_hbo_syntax
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from tf.fabric import Fabric

ROOT = Path(__file__).resolve().parents[1]
BHSA = os.path.expanduser("~/text-fabric-data/github/ETCBC/bhsa/tf/2021")
OUT = ROOT.parent / "resources" / "occurrences" / "hbo_syntax.db"


def main() -> None:
    print(f"loading BHSA from {BHSA} …")
    TF = Fabric(locations=BHSA)
    api = TF.load("otype function rela")
    F, L = api.F, api.L

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.unlink(missing_ok=True)
    con = sqlite3.connect(OUT)
    con.execute("""CREATE TABLE syntax(
        node INTEGER PRIMARY KEY, phrase INTEGER, function TEXT, rela TEXT)""")

    rows = []
    for w in F.otype.s("word"):
        phrases = L.u(w, otype="phrase")
        phrase = phrases[0] if phrases else None
        function = F.function.v(phrase) if phrase else None
        subphrases = L.u(w, otype="subphrase")
        rela = F.rela.v(subphrases[0]) if subphrases else None
        rows.append((w, phrase, function, rela))

    con.executemany("INSERT INTO syntax VALUES (?,?,?,?)", rows)
    con.execute("CREATE INDEX ix_syntax_phrase ON syntax(phrase)")
    con.commit()

    n = len(rows)
    n_func = sum(1 for r in rows if r[2])
    n_rela = sum(1 for r in rows if r[3])
    con.close()
    print(f"wrote {OUT}: {n} words, {n_func} with function ({100*n_func/n:.1f}%), "
          f"{n_rela} with a subphrase rela ({100*n_rela/n:.1f}%)")


if __name__ == "__main__":
    main()
