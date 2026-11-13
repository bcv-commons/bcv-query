#!/usr/bin/env python3
"""Every constituent of every layout clause with its grammatical relation, macrorole and semantic role (wave 1c, development-phase
plan 2026-11-13). The ingredients TBTA's grammars read most for noun phrases: semantic role, grammatical relation, the clause's voice.

    cd shoresh && .venv/bin/python3 -m macula.build_arg_roles

One row per constituent: the words of a layout clause grouped under their nearest MACULA tree node with a clause-level role
(s, o, o2, io, p, adv, pp; the verb, conjunctions and words with no such node are left out). Columns:

  corpus, clause_key   the layout's clause key (Hebrew `clause_key`, Greek `first`), as in bcv-commons/clause-columns
  words                the constituent's word keys inside the clause, in text order (space-joined)
  head                 its first noun / pronoun / adjective / number word ('' when none: an adverb, a clause)
  relation             the tree role of the constituent: s | o | o2 | io | p | adv | pp
  verb                 the clause's main verb (clause-columns `verb`); '' in a verbless clause
  voice                the clause's voice (clause-columns)
  macrorole            the verb frame's label for the constituent's words (MACULA frames: A0, A1, A2, AA ...); '' when the frame
                       does not list them
  case                 Greek: the head's case; Hebrew ''
  prep, prep_lemma     the constituent's first preposition word and its lemma ('' when none)
  prep_ln              Greek: the Louw-Nida subdomain of that preposition's sense in this verse (UBS Greek dictionary, CC BY-SA 4.0)
  prep_lxx             Hebrew: the Septuagint's form MACULA Hebrew aligns to the preposition (its `greek` column), for a later rule
  role                 actor | undergoer | A2 (core, from the frame and voice) or, for a Greek preposition phrase, the role its
                       Louw-Nida subdomain names: agent, instrument, source_event, responsibility, viewpoint, content, guarantor,
                       opposition, beneficiary, reason_participant, experiencer (LN 90), source, goal, path (LN 84), location (LN 83),
                       time (LN 67), reason, result, purpose, condition, concession, means, circumstance, manner, accompaniment,
                       basis, specification, relation, standard, separation, origin, distribution (LN 89), accompaniment (LN 34),
                       partitive (LN 63.D), state (LN 13); experiencer becomes addressee when the verb's sense is one of speaking
                       (LN 33); '' when no rule applies
  role_basis           frame | frame_passive | ln | ln_speech | '' : which rule gave `role`

Codes only; no English content values. Licence of the output: CC BY-SA 4.0 (the Hebrew layout's keys; the UBS senses).
Not read: BHSA, TBTA, English text.

Out: macula/data/arg-roles/{roles.tsv, checks.md, build.json} (git-ignored until a release).
"""
from __future__ import annotations

import collections
import csv
import datetime
import json
import sqlite3
import subprocess
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = DATA / "arg-roles"
TREES = HERE / "trees-macula.db"
LSPINE = HERE / "lexeme-spine-macula.db"
MSPINE = HERE / "macula-spine.db"
LOWFAT = HERE / "lowfat-hbo.db"
ROLES = ("s", "o", "o2", "io", "p", "adv", "pp")
NOMINAL = {"noun", "pron", "adj", "num"}
COLS = ["corpus", "clause_key", "words", "head", "relation", "verb", "voice", "macrorole", "case", "prep", "prep_lemma", "prep_ln",
        "prep_lxx", "role", "role_basis"]
LN = {"090001": "agent", "090002": "instrument", "090003": "source_event", "090004": "responsibility", "090005": "viewpoint",
      "090006": "content", "090007": "guarantor", "090008": "opposition", "090009": "beneficiary", "090010": "reason_participant",
      "090011": "agent", "090012": "agent", "090013": "experiencer", "090014": "experiencer",
      "084001": "source", "084002": "goal", "084003": "path",
      "089006": "basis", "089007": "reason", "089008": "result", "089009": "purpose", "089010": "condition", "089011": "concession",
      "089012": "means", "089026": "means", "089013": "circumstance", "089014": "manner", "089022": "accompaniment",
      "089004": "specification", "089001": "relation", "089005": "standard", "089021": "separation", "089003": "origin",
      "089016": "distribution", "063004": "partitive"}
LN_DOMAIN = {"083": "location", "067": "time", "013": "state", "034": "accompaniment"}


def _ro(p: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


def _layout_clauses(corpus: str):
    """(clause_key, [word keys]) in layout order; a Hebrew clause split into segments is read whole"""
    root = DATA / ("clause-layout" if corpus == "hbo" else "nt-clause-layout") / "clauses"
    for d in sorted(root.iterdir()):
        acc = collections.OrderedDict()
        for f in sorted(d.glob("*.jsonl")):
            for line in open(f, encoding="utf-8"):
                r = json.loads(line)
                acc.setdefault(r["clause_key"] if corpus == "hbo" else r["first"], []).extend(r["words"])
        for k, ws in acc.items():
            yield k, sorted(set(ws))


def _constituents(t, corpus):
    """word key -> (node id, relation) of its nearest ancestor with a clause-level role, stopping at a clause node"""
    node = {i: (par, cls, role) for i, par, cls, role in t.execute("select id, parent, cls, role from nodes where corpus=?", (corpus,))}
    out = {}
    for k, role, par in t.execute("select key, role, parent from words where corpus=?", (corpus,)):
        if role in ROLES:
            out[k] = (("w", k), role)
            continue
        p = par
        while p in node:
            pp, cls, r = node[p]
            if r in ROLES:
                out[k] = (p, r)
                break
            if cls == "cl" or r in ("v", "vc"):
                break
            p = pp
    return out


def main() -> int:
    t = _ro(TREES)
    m = _ro(MSPINE)
    cls_of, lemma_of = {}, {}
    for k, cl, lem in m.execute("select key, class, lemma from macula_words"):
        cls_of[k], lemma_of[k] = cl or "", lem or ""
    case = {k: c or "" for k, c in _ro(LSPINE).execute("select key, case_ from spine_words where length(key)=11")}
    lxx = {k: g or "" for k, g in _ro(LOWFAT).execute("select key, greek from lowfat_words where class='prep' and is_inserted=0")}
    frame_lab = collections.defaultdict(dict)                 # verb -> word -> label
    for v, lab, a in m.execute("select verb_key, role, arg_key from frames"):
        if a:
            frame_lab[v].setdefault(a, lab)
    prep_ln, dom = {}, {}
    for r in csv.DictReader(open(DATA / "word-senses-ubs/words.tsv", encoding="utf-8"), delimiter="\t"):
        if r["lang"] == "grc" and r["subdomains"]:
            prep_ln.setdefault(r["key"], r["subdomains"].split(";")[0])
        if r["lang"] == "grc" and r["domains"]:
            dom.setdefault(r["key"], r["domains"].split(";")[0])
    cc = {}
    for name, corpus in (("hebrew", "hbo"), ("greek-nt", "grc")):
        for r in pq.read_table(DATA / "clause-columns" / f"{name}.parquet", columns=["clause_key", "verb", "voice"]).to_pylist():
            cc[(corpus, r["clause_key"])] = (r["verb"] or "", r["voice"] or "")
    rows, st = [], collections.Counter()
    for corpus in ("hbo", "grc"):
        con = _constituents(t, corpus)
        for ck, ws in _layout_clauses(corpus):
            verb, voice = cc.get((corpus, ck), ("", ""))
            groups = collections.OrderedDict()
            for w in ws:
                if w in con and w != verb:
                    groups.setdefault(con[w], []).append(w)
            labs = frame_lab.get(verb, {})
            for (nid, rel), gw in groups.items():
                head = next((w for w in gw if cls_of.get(w) in NOMINAL), "")
                mr = next((labs[w] for w in gw if w in labs), "")
                prep = next((w for w in gw if cls_of.get(w) == "prep"), "")
                ln = prep_ln.get(prep, "") if corpus == "grc" and prep else ""
                role, basis = "", ""
                if mr == "A0":
                    role, basis = "actor", "frame"
                elif mr == "A1":
                    role, basis = "undergoer", ("frame_passive" if voice == "passive" and rel == "s" else "frame")
                elif mr == "A2":
                    role, basis = "A2", "frame"
                elif ln:
                    role = LN.get(ln) or LN_DOMAIN.get(ln[:3], "")
                    basis = "ln" if role else ""
                    if role == "experiencer" and dom.get(verb, "")[:3] == "033":   # LN 90 M with a verb of speaking (LN 33)
                        role, basis = "addressee", "ln_speech"
                rows.append([corpus, ck, " ".join(gw), head, rel, verb, voice, mr, case.get(head, "") if corpus == "grc" else "",
                             prep, lemma_of.get(prep, "") if prep else "", ln, lxx.get(prep, "") if corpus == "hbo" and prep else "",
                             role, basis])
                st[(corpus, "rows")] += 1
                st[(corpus, "role:" + (role or "-"))] += 1
                if prep:
                    st[(corpus, "prep")] += 1
                    st[(corpus, "prep_with_role" if basis == "ln" else "prep_no_role")] += 1
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "roles.tsv", "w", encoding="utf-8") as f:
        f.write("\t".join(COLS) + "\n")
        f.writelines("\t".join(r) + "\n" for r in rows)
    lines = ["# Argument roles per constituent: checks", "", "| corpus | count | value |", "|---|---|---|"]
    lines += [f"| {c} | {n:,} | {k} |" for (c, k), n in sorted(st.items(), key=lambda x: (x[0][0], -x[1]))]
    (OUT / "checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    code = subprocess.run(["git", "log", "-1", "--format=%h"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", str(Path(__file__))], cwd=HERE, capture_output=True, text=True).stdout
    (OUT / "build.json").write_text(json.dumps({"schema": 1, "built": datetime.date.today().isoformat(),
                                                "code": code + ("+uncommitted" if dirty.strip() else ""), "licence": "CC BY-SA 4.0",
                                                "not_read": ["BHSA", "TBTA", "English text"],
                                                "counts": {f"{c}:{k}": n for (c, k), n in st.items()}}, indent=1) + "\n")
    print(f"{OUT}: {len(rows):,} rows")
    for c in ("hbo", "grc"):
        print(c, {k: n for (cc_, k), n in st.most_common() if cc_ == c})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
