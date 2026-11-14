#!/usr/bin/env python3
"""Time and aspect per clause, with TBTA's policy (wave 2, development-phase plan 2026-11-13: "main line = discourse time, absolute
distance only inside speech, relative time in complement and relative clauses"). For the target's tense and aspect words
(Indonesian sudah / sedang / akan, Swahili -li- / -na- / -ta- / -ka-, Tagalog aspect).

    cd shoresh && .venv/bin/python3 -m macula.build_time_aspect      (after build_clause_columns and build_connectives)

One row per clause of bcv-commons/clause-columns (both corpora):
  band     the clause-columns `line` (main / background / setting / speech / non-narrative): the salience band
  time     past | present | future | timeless | anterior | simultaneous | posterior | irrealis | ''
           absolute (past / present / future) for main clauses; relative (anterior / simultaneous / posterior) for relative,
           complement, purpose, temporal and circumstantial clauses and for participles / infinitives; irrealis for commands,
           wishes, prohibitions and the subjunctive / optative; timeless for law, wisdom and poetry yiqtol / weqatal outside
           speech (general truths and statutes)
  aspect   perfective | imperfective | progressive | resultative | stative | ''
  basis    the rule: <corpus>:<verb form>:<context>, e.g. hbo:wayyiqtol:narration, grc:present_indicative:historical
  lxx      Hebrew only: the time the Septuagint's verb form gives (past / present / future / irrealis / ''), for checking
  agree    Hebrew only: 1 when `time` and `lxx` agree, 0 when both are set and differ, '' otherwise and on rows the
           Septuagint itself decided
Rules (Hebrew): wayyiqtol past perfective; qatal past perfective, but with the Septuagint's future in prophecy and poetry
(the "prophetic perfect") future, and with its present or perfect a present resultative / stative; yiqtol future imperfective in
speech and prophecy (in speech the Septuagint's form decides when it is modal, present or past: basis ...:lxx), past
imperfective (habitual) in narration, timeless in law / wisdom / poetry outside speech; weqatal the
time of the chain (future in speech and prophecy, past habitual in narration, timeless in law); participle progressive, present
in speech, past in narration, future after הִנֵּה ("about to"); verbless clauses stative, present in speech, past in narration.
Greek: the tense-form and mood, with the present indicative in narration as a historical present (past).
Output: macula/data/time-aspect/{clauses.tsv, checks.md, build.json} (git-ignored). Not read: BHSA, TBTA, English text.
"""
from __future__ import annotations

import collections
import csv
import datetime
import json
import subprocess
import unicodedata
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = DATA / "time-aspect"
COLS = ["corpus", "clause_key", "band", "time", "aspect", "basis", "lxx", "agree"]
RELATIVE = {"relative", "complement", "purpose", "temporal", "circumstantial", "time", "condition", "result"}
DIRECTIVE = {"imperative", "jussive", "cohortative", "prohibitive"}
LXX_TIME = {"aorist": "past", "imperfect": "past", "pluperfect": "past", "present": "present", "perfect": "present", "future": "future"}


def hebrew(c, rel, look):
    conj, force, speech, genre, kind = c["conj"] or "", c["force"] or "", c["speech"] or 0, c["genre"] or "", c["kind"]
    lt, lm = c["lxx_tense"] or "", c["lxx_mood"] or ""
    narr = speech == 0 and genre == "narrative"
    plain_ = speech == 0 and genre in ("law", "wisdom", "poetry")
    ctx = "narration" if narr else "speech" if speech else genre or "other"
    if force in DIRECTIVE or conj in ("imperative", "jussive", "cohortative"):
        return "irrealis", "", f"hbo:{conj or force}:directive"
    if rel in RELATIVE and conj in ("qatal", "yiqtol", "ptc", "ptc_pass", "inf_c"):
        t = {"qatal": "anterior", "yiqtol": "posterior", "ptc": "simultaneous", "ptc_pass": "simultaneous",
             "inf_c": "posterior" if rel == "purpose" else "simultaneous"}[conj]
        a = {"qatal": "perfective", "yiqtol": "imperfective", "ptc": "progressive", "ptc_pass": "resultative", "inf_c": ""}[conj]
        return t, a, f"hbo:{conj}:{rel}"
    if conj == "inf_c":
        return ("posterior" if rel == "purpose" else "simultaneous"), "", f"hbo:inf_c:{rel or 'other'}"
    if conj == "wayyiqtol":
        return "past", "perfective", f"hbo:wayyiqtol:{ctx}"
    if conj == "qatal":
        if genre in ("prophecy", "poetry", "apocalyptic") and lt == "future":
            return "future", "perfective", f"hbo:qatal:prophetic_perfect"
        if lt in ("present", "perfect") and lm == "indicative" and not narr:
            return "present", ("resultative" if lt == "perfect" else "stative"), f"hbo:qatal:{ctx}:lxx_present"
        return "past", "perfective", f"hbo:qatal:{ctx}"
    if conj == "yiqtol":
        if narr:
            return "past", "imperfective", "hbo:yiqtol:narration"
        if plain_:
            return "timeless", "imperfective", f"hbo:yiqtol:{genre}"
        # yiqtol in speech is future, modal, habitual present or (in poetry) past: the Septuagint's verb form decides when it has one
        if lm in ("subjunctive", "imperative", "optative"):
            return "irrealis", "imperfective", f"hbo:yiqtol:{ctx}:lxx"
        if lm == "indicative" and lt in ("present",):
            return "present", "imperfective", f"hbo:yiqtol:{ctx}:lxx"
        if lm == "indicative" and lt in ("aorist", "imperfect"):
            return "past", "imperfective", f"hbo:yiqtol:{ctx}:lxx"
        return "future", "imperfective", f"hbo:yiqtol:{ctx}"
    if conj == "weqatal":
        if narr:
            return "past", "imperfective", "hbo:weqatal:narration"
        if plain_ or (genre == "law" and not speech):
            return "timeless", "imperfective", f"hbo:weqatal:{genre}"
        return "future", "perfective", f"hbo:weqatal:{ctx}"
    if conj in ("ptc", "ptc_pass"):
        a = "progressive" if conj == "ptc" else "resultative"
        if look:
            return "future", a, f"hbo:{conj}:hinneh"
        return ("past" if narr else "present"), a, f"hbo:{conj}:{ctx}"
    if kind == "NC" or not conj:
        if plain_:
            return "timeless", "stative", f"hbo:verbless:{genre}"
        return ("past" if narr else "present"), "stative", f"hbo:verbless:{ctx}"
    return "", "", f"hbo:{conj}:unknown"


def greek(c, rel):
    conj, speech, line = c["conj"] or "", c["speech"] or 0, c["line"] or ""
    if not conj or c["kind"] == "NC":
        return ("past" if speech == 0 and line in ("main", "background", "setting") else "present"), "stative", "grc:verbless"
    tense, _, mood = conj.partition("_")
    asp = {"aorist": "perfective", "present": "imperfective", "imperfect": "imperfective", "future": "",
           "perfect": "resultative", "pluperfect": "resultative"}.get(tense, "")
    if mood in ("imperative", "subjunctive", "optative"):
        return "irrealis", asp, f"grc:{conj}"
    if mood in ("participle", "infinitive"):
        t = {"aorist": "anterior", "perfect": "anterior", "pluperfect": "anterior", "future": "posterior"}.get(tense, "simultaneous")
        if mood == "infinitive" and rel == "purpose":
            t = "posterior"
        return t, ("progressive" if tense == "present" and mood == "participle" else asp), f"grc:{conj}"
    if tense == "present" and speech == 0 and line in ("main", "background"):
        return "past", "imperfective", f"grc:{conj}:historical"
    t = {"aorist": "past", "imperfect": "past", "pluperfect": "past", "present": "present", "perfect": "present",
         "future": "future"}.get(tense, "")
    if rel in RELATIVE and t:
        t = {"past": "anterior", "present": "simultaneous", "future": "posterior"}[t]
    return t, ("progressive" if tense == "imperfect" else asp), f"grc:{conj}"


def main() -> int:
    rel = {}
    look = set()
    for r in csv.DictReader(open(DATA / "connectives/clauses.tsv", encoding="utf-8"), delimiter="\t"):
        rel[r["clause_key"]] = r["link"] if r["link"] in RELATIVE else (r["relation"] or "")
        if r["link"] == "look":
            look.add(r["clause_key"])
    rows, st = [], collections.Counter()
    for corpus, name in (("hbo", "hebrew"), ("grc", "greek-nt")):
        for c in pq.read_table(DATA / "clause-columns" / f"{name}.parquet").to_pylist():
            k = c["clause_key"]
            if corpus == "hbo":
                t, a, b = hebrew(c, rel.get(k, ""), k in look)
                lx = "irrealis" if (c["lxx_mood"] or "") in ("imperative", "subjunctive", "optative") else LXX_TIME.get(c["lxx_tense"] or "", "")
                if (c["lxx_mood"] or "") in ("participle", "infinitive"):
                    lx = ""
                comparable = t in ("past", "present", "future", "irrealis") and lx and not b.endswith(":lxx") and "lxx_present" not in b \
                    and "prophetic" not in b                   # rows the Septuagint decided are not a check of the rule
                ag = ("1" if t == lx else "0") if comparable else ""
            else:
                t, a, b = greek(c, rel.get(k, ""))
                lx, ag = "", ""
            rows.append([corpus, k, c["line"] or "", t, a, b, lx, ag])
            st[(corpus, "time:" + (t or "-"))] += 1
            st[(corpus, "aspect:" + (a or "-"))] += 1
            if ag:
                st[(corpus, "lxx_agree:" + ag)] += 1
                st[(corpus, f"agree_by:{b.split(':')[1]}:{ag}")] += 1
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "clauses.tsv", "w", encoding="utf-8") as f:
        f.write("\t".join(COLS) + "\n")
        f.writelines("\t".join(r) + "\n" for r in rows)
    lines = ["# Time and aspect: checks", "", f"Clauses: {len(rows):,}.", "",
             "Hebrew: agreement with the Septuagint's verb form where both give an absolute time or irrealis (a check, not a gold):",
             "", "| corpus | value | count |", "|---|---|---|"]
    lines += [f"| {c} | {v} | {n:,} |" for (c, v), n in sorted(st.items())]
    (OUT / "checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    code = subprocess.run(["git", "log", "-1", "--format=%h"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    (OUT / "build.json").write_text(json.dumps({"schema": 1, "built": datetime.date.today().isoformat(), "code": code,
                                                "not_read": ["BHSA", "TBTA", "English text"]}, indent=1) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
