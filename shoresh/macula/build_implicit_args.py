#!/usr/bin/env python3
"""Implicit arguments: roles of a verb's frame that the clause does not say in words, with who they are (wave 2, development-phase
plan 2026-11-13). A target language that needs an overt object or subject pronoun where Hebrew or Greek leaves it out ("he took
[it] and gave [it] to them") needs the referent's person, number and gender.

    cd shoresh && .venv/bin/python3 -m macula.build_implicit_args     (after build_clause_args and build_reference_status)

One row per (clause, verb, frame role) whose words lie outside the clause or are not expressed at all (macula/data/clause-args
args.tsv `where` != in_clause). Columns:
  corpus, clause_key, verb, role (A0 A1 A2 AA)
  where        earlier_clause | later_clause | unexpressed | mixed (args.tsv)
  in_verb      1 when the verb's own ending carries the subject (Hebrew / Greek finite verbs with A0), else 0
  antecedent   the nearest word the frame names for the role ('' when unexpressed)
  distance     clauses between the clause and that word (layout order; '' when unexpressed)
  person, number, gender
               of the referent: A0 from the verb's ending when in_verb, else from the antecedent word (nouns third person)
  referent     the antecedent's referent as in reference-status (ACAI entity, reference chain or lemma)
Also role POSS: a constituent headed by an inalienable noun (body part, kin; fixed lists) with no possessor in the source; then
`antecedent` is the noun itself, `where` none, and person / number / gender / referent are a guess: the clause's subject (from the
verb's ending and subject reference).
Output: macula/data/implicit-args/{args.tsv, checks.md, build.json} (git-ignored). Not read: BHSA, TBTA, English text.
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
OUT = DATA / "implicit-args"
MSPINE = HERE / "macula-spine.db"
COLS = ["corpus", "clause_key", "verb", "role", "where", "in_verb", "antecedent", "distance", "person", "number", "gender", "referent"]
P = {"first": "1", "second": "2", "third": "3"}
N = {"singular": "s", "plural": "p", "dual": "d"}
G = {"masculine": "m", "feminine": "f", "common": "c", "neuter": "n", "both": "c"}


# inalienable nouns (body parts, kin; not אִישׁ / אִשָּׁה / ἀνήρ / γυνή, mostly 'man' / 'woman' / 'each one') whose possessor a target language often writes where the source leaves it out
INALIENABLE = {
    "hbo": {"יָד", "רֹאשׁ", "עַיִן", "פֶּה", "לֵב", "לֵבָב", "רֶגֶל", "פָּנֶה", "פָּנִים", "אֹזֶן", "נֶפֶשׁ", "זְרוֹעַ", "כַּף", "לָשׁוֹן",
            "שָׂפָה", "בֶּטֶן", "אַף", "צַוָּאר", "כָּתֵף", "בָּשָׂר", "עֶצֶם", "יָמִין", "אֶצְבַּע", "שֵׁן", "מֵעֶה", "קֶרֶב",
            "אָב", "אֵם", "אָח", "אָחוֹת", "בֵּן", "בַּת", "זֶרַע", "חָם", "חוֹתֵן", "כַּלָּה"},
    "grc": {"χείρ", "κεφαλή", "ὀφθαλμός", "στόμα", "καρδία", "πούς", "πρόσωπον", "οὖς", "ψυχή", "γλῶσσα", "χεῖλος", "σάρξ", "σῶμα",
            "δεξιός", "γόνυ", "πατήρ", "μήτηρ", "ἀδελφός", "ἀδελφή", "υἱός", "θυγάτηρ", "τέκνον", "σπέρμα"},
}


def main() -> int:
    m = sqlite3.connect(f"file:{MSPINE}?mode=ro", uri=True)
    w = {k: (cls or "", person or "", number or "", gender or "") for k, cls, person, number, gender in
         m.execute("select key, class, person, number, gender from macula_words")}
    order, wclause = {}, {}
    for corpus, sub, field in (("hbo", "clause-layout", "clause_key"), ("grc", "nt-clause-layout", "first")):
        i = 0
        for f in sorted((DATA / sub / "clauses").glob("*/*.jsonl")):
            for line in open(f, encoding="utf-8"):
                r = json.loads(line)
                ck = r[field]
                if (corpus, ck) not in order:
                    order[(corpus, ck)] = i
                    i += 1
                for x in r["words"]:
                    wclause.setdefault(x, ck)
    referent = {}
    rs = DATA / "reference-status" / "np.tsv"
    if rs.exists():
        for r in csv.DictReader(open(rs, encoding="utf-8"), delimiter="\t"):
            referent[r["head"]] = r["referent"]
    ent = {}
    for r in csv.DictReader(open(DATA / "entities/entity_words.tsv", encoding="utf-8"), delimiter="\t"):
        if r["kind"] in ("explicit", "pronominal", "subject"):
            ent.setdefault(r["word"], r["entity"].split(".")[0])
    rows, st = [], collections.Counter()
    for r in csv.DictReader(open(DATA / "clause-args/args.tsv", encoding="utf-8"), delimiter="\t"):
        if r["where"] == "in_clause":
            continue
        corpus, ck, v = r["corpus"], r["clause_key"], r["verb_key"]
        keys = r["arg_keys"].split()
        here = order.get((corpus, ck))
        ante, dist = "", ""
        if keys and here is not None:
            cands = [(abs(order.get((corpus, wclause.get(k, "")), here) - here), k) for k in keys if wclause.get(k)]
            if cands:
                d, ante = min(cands)
                dist = str(d)
        in_verb = r["subject_in_verb"] == "1" and r["role"] == "A0"
        src = v if in_verb else ante
        cls, person, number, gender = w.get(src, ("", "", "", ""))
        if not in_verb and cls in ("noun", "adj", "num", "adjective", "noun_proper"):
            person = person or "third"
        rows.append([corpus, ck, v, r["role"], r["where"], "1" if in_verb else "0", ante, dist, P.get(person, ""), N.get(number, ""),
                     G.get(gender, ""), referent.get(ante) or ent.get(ante, "") if ante else ""])
        st[(corpus, r["role"], "in_verb" if in_verb else r["where"])] += 1
    # implicit possessors: a constituent headed by an inalienable noun with no possessor in the source (Hebrew: no pronominal suffix,
    # not a construct head; Greek: no genitive pronoun or noun after it in the constituent). The guess for the possessor is the
    # clause's subject: person / number / gender from the verb's ending, referent from the verb's subject reference
    lemma = {k: unicodedata.normalize("NFC", l or "") for k, l in m.execute("select key, lemma from macula_words")}
    inal = {c: {unicodedata.normalize("NFC", x) for x in v} for c, v in INALIENABLE.items()}   # MACULA orders dagesh / vowel otherwise
    case = dict(m.execute("select key, case_ from macula_words where lang='grc'"))
    lf = sqlite3.connect(f"file:{HERE / 'lowfat-hbo.db'}?mode=ro", uri=True)
    sfx, construct = set(), set()
    for k, c_, typ, state in lf.execute("select key, class, type, state from lowfat_words"):
        if c_ == "pron" and typ == "pronominal":
            sfx.add(k[:11])
        if state == "construct":
            construct.add(k)
    subjref = collections.defaultdict(list)
    for s_, t, kind in m.execute("select src_key, tgt_key, kind from refs where kind='subjref'"):
        subjref[s_].append(t)
    for r in csv.DictReader(open(DATA / "arg-roles/roles.tsv", encoding="utf-8"), delimiter="\t"):
        h, corpus = r["head"], r["corpus"]
        if not h or lemma.get(h) not in inal[corpus]:
            continue
        ws = r["words"].split()
        if corpus == "hbo":
            if h[:11] in sfx or h in construct:
                continue
        elif any(x > h and case.get(x) == "genitive" for x in ws):
            continue
        v = r["verb"]
        _, person, number, gender = w.get(v, ("", "", "", "")) if v else ("", "", "", "")
        ref = (subjref.get(v) or [""])[0] if v else ""
        rows.append([corpus, r["clause_key"], v, "POSS", "none", "0", h, "", P.get(person, ""), N.get(number, ""), G.get(gender, ""),
                     referent.get(ref) or ent.get(ref, "") or ent.get(v, "") if v else ""])
        st[(corpus, "POSS", "none")] += 1
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "args.tsv", "w", encoding="utf-8") as f:
        f.write("\t".join(COLS) + "\n")
        f.writelines("\t".join(r) + "\n" for r in rows)
    filled = collections.Counter((r[0], r[3], bool(r[9])) for r in rows)
    lines = ["# Implicit arguments: checks", "", f"Rows: {len(rows):,}.", "", "| corpus | role | where | rows |", "|---|---|---|---|"]
    lines += [f"| {c} | {ro} | {wh} | {n:,} |" for (c, ro, wh), n in sorted(st.items())]
    lines += ["", "Rows with the referent's number known:", "", "| corpus | role | known | unknown |", "|---|---|---|---|"]
    for c, ro in sorted({(a, b) for a, b, _ in filled}):
        lines.append(f"| {c} | {ro} | {filled[(c, ro, True)]:,} | {filled[(c, ro, False)]:,} |")
    (OUT / "checks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    code = subprocess.run(["git", "log", "-1", "--format=%h"], cwd=HERE, capture_output=True, text=True).stdout.strip()
    (OUT / "build.json").write_text(json.dumps({"schema": 1, "built": datetime.date.today().isoformat(), "code": code,
                                                "not_read": ["BHSA", "TBTA", "English text"]}, indent=1) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
