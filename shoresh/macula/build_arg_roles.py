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
  lxx_case             Hebrew: the case of the Septuagint word MACULA aligns to the phrase's first noun (GLAUx parse, its verse first)
  role_basis           frame | frame_passive | ln | ln_speech | lxx_nt_domain | lxx_nt | hebrew_domain | '' : which rule gave `role`.
                       Hebrew preposition phrases: lxx_nt_domain = the Septuagint's preposition + case + the LN domain its noun's lemma
                       has in the NT, read through the NT's Greek rows (8+ rows, 60%); lxx_nt = the same without the domain (20+, 60%);
                       hebrew_domain = Hebrew preposition + head noun's SDBH domain, learned from the Hebrew rows the first two labelled;
                       lxx_dative = לְ the Septuagint gives as a bare dative -> recipient; hebrew_prep = כְּ -> standard;
                       a `+speech` suffix: a goal turned addressee because the verb is one of speaking

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
import unicodedata
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
        "prep_lxx", "lxx_case", "role", "role_basis"]
LXX = HERE.parent / "lxx" / "data" / "lxx-glaux.db"
SPEAK_HBO = {"0559", "1696", "7121", "6680", "6030", "7592", "5046", "2199", "6817", "6419", "0560", "4449"}
CASE = {"N": "nominative", "G": "genitive", "D": "dative", "A": "accusative", "V": "vocative"}
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


def _lxx_lookup():
    """GLAUx Septuagint: (book, chapter, verse, plain form) -> (lemma, case letter); plain form -> commonest (lemma, case)"""
    from macula.build_clause_columns import plain
    verse, glob_ = {}, collections.defaultdict(collections.Counter)
    for b, c, v, surf, lem, morph in _ro(LXX).execute("select book, chapter, verse, surface, lemma, morph from lxx_words"):
        mm = (morph or "").split(".", 1)
        cs = mm[1][0] if len(mm) == 2 and mm[1][:1] in CASE and mm[0][:1] in ("N", "A", "R") else ""   # N.NSM: case first
        if mm[0] == "P":
            cs = ""
        key = plain(surf)
        verse.setdefault((b, c, v, key), (lem or "", cs))
        glob_[key][(lem or "", cs)] += 1
    return plain, verse, {k: c.most_common(1)[0][0] for k, c in glob_.items()}


def main() -> int:
    t = _ro(TREES)
    m = _ro(MSPINE)
    cls_of, lemma_of = {}, {}
    for k, cl, lem in m.execute("select key, class, lemma from macula_words"):
        cls_of[k], lemma_of[k] = cl or "", lem or ""
    case = {k: c or "" for k, c in _ro(LSPINE).execute("select key, case_ from spine_words where length(key)=11")}
    lxx, hpos = {}, {}
    for k, g, b, c, v in _ro(LOWFAT).execute("select key, greek, book, chapter, verse from lowfat_words where is_inserted=0"):
        lxx[k], hpos[k] = (g or "").strip('"'), (b, c, v)
    plain, lxx_verse, lxx_glob = _lxx_lookup()

    def lxx_word(k):
        """the Septuagint word MACULA aligns to Hebrew word k: (lemma, case letter), its own verse first"""
        g = lxx.get(k, "")
        if not g:
            return "", ""
        b, c, v = hpos[k]
        pl = plain(g.split()[-1])
        return lxx_verse.get((b, c, v, pl)) or lxx_glob.get(pl, ("", ""))
    nt_table = collections.defaultdict(collections.Counter)    # (Greek preposition lemma, case[, noun's LN domain]) -> roles, NT
    frame_lab = collections.defaultdict(dict)                 # verb -> word -> label
    for v, lab, a in m.execute("select verb_key, role, arg_key from frames"):
        if a:
            frame_lab[v].setdefault(a, lab)
    prep_ln, dom = {}, {}
    for r in csv.DictReader(open(DATA / "word-senses-ubs/words.tsv", encoding="utf-8"), delimiter="\t"):
        if r["lang"] == "grc" and r["subdomains"]:
            prep_ln.setdefault(r["key"], r["subdomains"].split(";")[0])
        if r["domains"]:                                     # Greek LN / Hebrew SDBH domain of each word (first sense)
            dom.setdefault(r["key"], r["domains"].split(";")[0])
    lemma_dom_c = collections.defaultdict(collections.Counter)  # Greek lemma -> its LN domains in the NT
    for k, d in dom.items():
        lemma_dom_c[lemma_of.get(k, "")][d[:3]] += 1
    lemma_dom = {l: c.most_common(1)[0][0] for l, c in lemma_dom_c.items() if l}
    cc = {}
    for name, corpus in (("hebrew", "hbo"), ("greek-nt", "grc")):
        for r in pq.read_table(DATA / "clause-columns" / f"{name}.parquet", columns=["clause_key", "verb", "voice"]).to_pylist():
            cc[(corpus, r["clause_key"])] = (r["verb"] or "", r["voice"] or "")
    rows, st = [], collections.Counter()
    for corpus in ("grc", "hbo"):            # Greek first: its preposition roles teach the table the Hebrew rows read
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
                # the preposition heading the constituent: its first word after conjunctions (a preposition nested deeper, as
                # διά in "Παῦλος κλητὸς ἀπόστολος ... διὰ θελήματος θεοῦ", does not give the whole constituent a role)
                first = next((w for w in gw if cls_of.get(w) not in ("cj", "conj")), "")
                prep = first if cls_of.get(first) == "prep" else ""
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
                    if role:
                        nt_table[(lemma_of.get(prep, ""), case.get(head, ""))][role] += 1
                        nt_table[(lemma_of.get(prep, ""), case.get(head, ""), dom.get(head, "")[:3])][role] += 1
                lxx_case = ""
                if corpus == "hbo" and prep and not mr:
                    # the Septuagint's preposition for this one and the case of the word it gives for the head noun, read
                    # through the NT: the role Greek preposition + case most often has there (at least 20 phrases, 60%)
                    # first with the LN domain the Septuagint noun's lemma has in the NT, then without it
                    plem = lxx_word(prep)[0]
                    after = [w for w in gw if w > prep and cls_of.get(w) in NOMINAL]
                    nlem, ncase = lxx_word(after[0]) if after else ("", "")
                    lxx_case = CASE.get(ncase, "")
                    for key, minimum, b_ in (((plem, lxx_case, lemma_dom.get(nlem, "")), 8, "lxx_nt_domain"),
                                             ((plem, lxx_case), 20, "lxx_nt")):
                        dist = nt_table.get(key)
                        if plem and lxx_case and all(key) and dist and sum(dist.values()) >= minimum:
                            top, n = dist.most_common(1)[0]
                            if n / sum(dist.values()) >= 0.6:
                                role, basis = top, b_
                                break
                rows.append([corpus, ck, " ".join(gw), head, rel, verb, voice, mr, case.get(head, "") if corpus == "grc" else "",
                             prep, lemma_of.get(prep, "") if prep else "", ln, lxx.get(prep, "") if corpus == "hbo" and prep else "",
                             lxx_case, role, basis])
                st[(corpus, "rows")] += 1
                st[(corpus, "role:" + (role or "-"))] += 1
                if prep:
                    st[(corpus, "prep")] += 1
                    st[(corpus, "prep_with_role" if basis in ("ln", "ln_speech", "lxx_nt", "lxx_nt_domain") else
                                "prep_core" if mr else "prep_no_role")] += 1
    # Hebrew rules for what the Septuagint route cannot see: לְ that the Septuagint gives as a bare dative (no preposition: the
    # aligned form is an article or nothing, the noun dative) -> recipient; כְּ -> standard (a comparison)
    I = {c: i for i, c in enumerate(COLS)}
    for r in rows:
        if r[0] != "hbo" or not r[I["prep"]] or r[I["role"]] or r[I["macrorole"]]:
            continue
        new = ""
        if r[I["prep_lemma"]] == "לְ" and r[I["lxx_case"]] == "dative" and lxx_word(r[I["prep"]])[0] in ("", "ὁ"):
            new, b_ = "recipient", "lxx_dative"
        elif unicodedata.normalize("NFC", r[I["prep_lemma"]]) == unicodedata.normalize("NFC", "כְּ"):   # MACULA orders dagesh / vowel otherwise
            new, b_ = "standard", "hebrew_prep"
        if new:
            r[I["role"]], r[I["role_basis"]] = new, b_
            st[("hbo", "prep_no_role")] -= 1
            st[("hbo", "prep_with_role")] += 1
            st[("hbo", "role:-")] -= 1
            st[("hbo", "role:" + new)] += 1
            st[("hbo", "basis:" + b_)] += 1
    # second Hebrew step: (Hebrew preposition lemma, head noun's SDBH domain at two levels) -> role, learned from the Hebrew rows
    # the Septuagint route labelled (at least 8 rows, 60%), applied to the Hebrew preposition phrases still without a role
    I = {c: i for i, c in enumerate(COLS)}
    learn = collections.defaultdict(collections.Counter)

    def hkey(r):
        ws = r[I["words"]].split()
        p_ = r[I["prep"]]
        nom = [w for w in ws if w > p_ and cls_of.get(w) in NOMINAL]
        return (r[I["prep_lemma"]], dom.get(nom[0], "")[:6]) if nom and dom.get(nom[0]) else None
    for r in rows:
        if r[0] == "hbo" and r[I["role_basis"]] in ("lxx_nt", "lxx_nt_domain") and hkey(r):
            learn[hkey(r)][r[I["role"]]] += 1
    for r in rows:
        if r[0] == "hbo" and r[I["prep"]] and not r[I["role"]] and not r[I["macrorole"]] and hkey(r):
            dist = learn.get(hkey(r))
            if dist and sum(dist.values()) >= 8:
                top, n = dist.most_common(1)[0]
                if n / sum(dist.values()) >= 0.6:
                    r[I["role"]], r[I["role_basis"]] = top, "hebrew_domain"
                    st[("hbo", "prep_no_role")] -= 1
                    st[("hbo", "prep_with_role")] += 1
                    st[("hbo", "role:-")] -= 1
                    st[("hbo", "role:" + top)] += 1
                    st[("hbo", "basis:hebrew_domain")] += 1
    # goal -> addressee with a verb of speaking (research 2026-11-13: Tagalog kay / sa): Hebrew אֶל / לְ / עַל / Aramaic לְ with
    # אָמַר, דָּבַר, קָרָא, צָוָה, עָנָה, שָׁאַל, נָגַד, זָעַק, צָעַק, פָּלַל, Aramaic אֲמַר, מָלַל; Greek: a goal with a verb whose sense is speaking (LN 33)
    strong_of = dict(m.execute("select key, strong from macula_words where lang='hbo'"))
    for r in rows:
        if r[I["role"]] != "goal":
            continue
        v = r[I["verb"]]
        speech = ((strong_of.get(v) or "").zfill(4)[:4] in SPEAK_HBO and r[I["prep_lemma"]] in ("אֶל", "לְ", "עַל"))\
            if r[0] == "hbo" else dom.get(v, "")[:3] == "033"
        if speech:
            r[I["role"]], r[I["role_basis"]] = "addressee", r[I["role_basis"]] + "+speech"
            st[(r[0], "role:goal")] -= 1
            st[(r[0], "role:addressee")] += 1
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
