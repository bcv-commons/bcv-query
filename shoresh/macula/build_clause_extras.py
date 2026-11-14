#!/usr/bin/env python3
"""Small clause-record values TBTA's grammars read everywhere: polarity, mood, reflexivity and degree (wave 2, development-phase
plan 2026-11-13). By rule from MACULA and the layouts; cheap.

    cd shoresh && .venv/bin/python3 -m macula.build_clause_extras      (after clause-columns, connectives, time-aspect, arg-roles)

clauses.tsv, one row per clause of bcv-commons/clause-columns:
  polarity    negative | affirmative ; neg_word the negator's lemma (לֹא, אַל, אֵין, οὐ, μή ...) as in clause-columns `neg`
  mood        declarative | interrogative | directive (imperative, jussive, cohortative, prohibitive) | conditional (the clause
              is a condition: relation conditional / link condition) | irrealis (subjunctive / optative / modal yiqtol, not a
              directive) | ''
  reflexive   reflexive (a reflexive pronoun ἑαυτοῦ / σεαυτοῦ / ἐμαυτοῦ, or a Hebrew hithpael / hithpolel with no object: a candidate,
              basis stem; Greek middles are left out, most are deponents) | reciprocal (ἀλλήλων, clause-columns recip) | ''
  reflexive_basis
degree.tsv, one row per degree word:
  corpus, key, clause_key, degree    intensifier (מְאֹד, σφόδρα, λίαν, μᾶλλον as "more"), comparative (Greek comparative form; a
                                     Hebrew מִן phrase in a clause whose predicate is a quality: an adjective or a stative verb),
                                     superlative (Greek superlative form, μάλιστα; Hebrew "X of Xs": a construct noun followed by
                                     its own lemma, קֹדֶשׁ הַקֳּדָשִׁים)
Output: macula/data/clause-extras/ (git-ignored). Not read: BHSA, TBTA, English text.
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
OUT = DATA / "clause-extras"
MSPINE = HERE / "macula-spine.db"
N = lambda x: unicodedata.normalize("NFC", x or "")  # noqa: E731
INTENS = {N("מְאֹד"), "σφόδρα", "λίαν", "σφοδρῶς", "περισσῶς"}
REFLEX = {"ἑαυτοῦ", "σεαυτοῦ", "ἐμαυτοῦ"}
QUALITY_HBO = {"1431", "2388", "3513", "6105", "7235", "1361", "3190", "2896", "1419", "7227", "6996", "2389", "6099", "3303",
               "4966", "2450", "6662", "3477", "7311", "6105", "3201", "5293"}     # be great / strong / heavy / many / high / good ...


def main() -> int:
    m = sqlite3.connect(f"file:{MSPINE}?mode=ro", uri=True)
    W = {}
    for k, lang, lem, cls, st, deg, stem, voice, state in m.execute(
            "select key, lang, lemma, class, strong, degree, stem, voice, state from macula_words"):
        W[k] = (lang, N(lem), cls or "", (st or "").zfill(4)[:4] if lang == "hbo" else "", deg or "", stem or "", voice or "", state or "")
    words = {}
    for corpus, sub, field in (("hbo", "clause-layout", "clause_key"), ("grc", "nt-clause-layout", "first")):
        for f in sorted((DATA / sub / "clauses").glob("*/*.jsonl")):
            for line in open(f, encoding="utf-8"):
                r = json.loads(line)
                words.setdefault(r[field], []).extend(r["words"])
    link = {r["clause_key"]: (r["link"], r["relation"]) for r in csv.DictReader(open(DATA / "connectives/clauses.tsv", encoding="utf-8"), delimiter="\t")}
    tm = {r["clause_key"]: r["time"] for r in csv.DictReader(open(DATA / "time-aspect/clauses.tsv", encoding="utf-8"), delimiter="\t")}
    mn_clauses = set()
    for r in csv.DictReader(open(DATA / "arg-roles/roles.tsv", encoding="utf-8"), delimiter="\t"):
        if r["corpus"] == "hbo" and N(r["prep_lemma"]) == N("מִן"):
            mn_clauses.add(r["clause_key"])
    rows, deg_rows, st = [], [], collections.Counter()
    for corpus, name in (("hbo", "hebrew"), ("grc", "greek-nt")):
        for c in pq.read_table(DATA / "clause-columns" / f"{name}.parquet").to_pylist():
            k = c["clause_key"]
            ws = sorted(set(words.get(k, [])))
            force = c["force"] or ""
            ln, rel = link.get(k, ("", ""))
            pol = "negative" if c["neg"] else "affirmative"
            if force in ("imperative", "jussive", "cohortative", "prohibitive"):
                mood = "directive"
            elif force == "interrogative" or c.get("interrog"):
                mood = "interrogative"
            elif ln == "condition" or rel == "conditional":
                mood = "conditional"
            elif tm.get(k) == "irrealis":
                mood = "irrealis"
            else:
                mood = "declarative"
            refl, rb = "", ""
            lems = {W.get(w, ("",) * 8)[1] for w in ws}
            if lems & REFLEX:
                refl, rb = "reflexive", "pronoun"
            elif "ἀλλήλων" in lems:                            # (clause-columns `recip` is "has a recipient", not reciprocal)
                refl, rb = "reciprocal", "pronoun"
            else:
                v = c["verb"] or ""
                lang, _, _, _, _, stem, voice, _ = W.get(v, ("",) * 8)
                if lang == "hbo" and stem in ("hithpael", "hithpolel") and c["undergoer"] == "none":
                    refl, rb = "reflexive", "stem"
            rows.append([corpus, k, pol, c["neg"] or "", mood, refl, rb])
            st[(corpus, "polarity:" + pol)] += 1
            st[(corpus, "mood:" + mood)] += 1
            if refl:
                st[(corpus, f"reflexive:{refl}:{rb}")] += 1
            # degree words
            quality = any(W.get(w, ("",) * 8)[2] in ("adj", "adjective") or W.get(w, ("",) * 8)[3] in QUALITY_HBO for w in ws)
            for i, w in enumerate(ws):
                lang, lem, cls, sg, dg, _, _, state = W.get(w, ("",) * 8)
                d = ""
                if lem in INTENS or lem == "μᾶλλον":
                    d = "intensifier"
                elif dg == "comparative":
                    d = "comparative"
                elif dg == "superlative" or lem == "μάλιστα":
                    d = "superlative"
                elif lang == "hbo" and N(lem) == N("מִן") and k in mn_clauses and quality and c["kind"] in ("NC", "VC") and \
                        (c["kind"] == "NC" or W.get(c["verb"] or "", ("",) * 8)[3] in QUALITY_HBO):
                    d = "comparative"
                elif lang == "hbo" and cls == "noun" and state == "construct":
                    nxt = [x for x in ws[i + 1:i + 3] if W.get(x, ("",) * 8)[2] == "noun"]
                    if nxt and W.get(nxt[0], ("",) * 8)[1] == lem:
                        d = "superlative"
                if d:
                    deg_rows.append([corpus, w, k, d])
                    st[(corpus, "degree:" + d)] += 1
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "clauses.tsv", "w", encoding="utf-8") as f:
        f.write("corpus\tclause_key\tpolarity\tneg_word\tmood\treflexive\treflexive_basis\n")
        f.writelines("\t".join(r) + "\n" for r in rows)
    with open(OUT / "degree.tsv", "w", encoding="utf-8") as f:
        f.write("corpus\tkey\tclause_key\tdegree\n")
        f.writelines("\t".join(r) + "\n" for r in deg_rows)
    lines = ["# Clause extras: checks", "", f"Clauses: {len(rows):,}; degree words: {len(deg_rows):,}.", "",
             "| corpus | value | count |", "|---|---|---|"]
    lines += [f"| {c} | {v} | {n:,} |" for (c, v), n in sorted(st.items())]
    (OUT / "checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    code = subprocess.run(["git", "log", "-1", "--format=%h"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    (OUT / "build.json").write_text(json.dumps({"schema": 1, "built": datetime.date.today().isoformat(), "code": code,
                                                "not_read": ["BHSA", "TBTA", "English text"]}, indent=1) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
