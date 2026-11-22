"""Stage 09 of the source examples (SPEC 1.0): the shared profile.

    shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --stage 09

Writes, in each language folder of the build:
  map.tsv           D6: every (table, category, code) of `pieces.marks` and `clauses.marks` -> a Universal Dependencies
                    feature and value, or `none` with a reason code. Columns: table, category, code, feature, value,
                    reason, count. A code that maps to two features has two rows. `count` = pieces (or clauses) that
                    carry the code; for the list-valued `connective`, the clauses whose list holds it.
  pieces.parquet    anew, with `shared` = `marks` read through map.tsv (a JSON object of UD feature -> value, keys
                    sorted, no spaces; `{}` where nothing maps)
  clauses.parquet   anew, with `shared` the same way
  facts.parquet     anew: the rows of stages 06 and 08 kept; `has_class`, `in_domain`, `sense_of` and (arc only)
                    `equivalent_of` written anew; all rows sorted by (subject, relation, object)
  profile.tsv       the 195 rows of the questionnaire (tools/team_parameters.tsv, Grambank v1.0.2, CC BY 4.0):
                    id, question, value, statement, count. A row is answered only where a rule of PROFILE below finds
                    statement rows that answer it; `statement` holds their ids and `count` their `count`, both
                    space-separated in the same order. Every other row has value `?` and no evidence.

The map is written here by hand, as SPEC 4.10 asks ("written as tables inside the builder"). Principle: a code is mapped
only where Universal Dependencies has a universal feature whose value names the same form category; a code whose UD
value would be a reading of the form (Hebrew stem formations, the Greek aorist and perfect) or that UD treats as a part
of speech rather than a feature is `none`. Reason codes:
  upos_not_feature   UD expresses it as a part of speech (UPOS), not as a feature
  no_ud_feature      UD has no universal feature for this category
  no_ud_value        UD has the feature, but no value that names this code without a reading of its meaning
  unknown_value      the source's "unknown" value
  lexeme_value       the value is a lexeme key, not a feature value

The facts (SPEC 4.8):
  has_class      lexeme -> class code; count = its pieces with that class, share = count / its pieces (given, pieces.class)
  in_domain      lexeme -> UBS domain code; count = its pieces whose `domain` holds the code, share = count / its pieces
                 (given, pieces.domain)
  sense_of       UBS sense code -> lexeme; count = pieces with that sense and lexeme (given, pieces.sense); share empty
  equivalent_of  (arc only) Aramaic lexeme -> Hebrew lexeme, from our published list aramaic-hebrew-equivalents v0.1.1
                 (data/words.parquet, sha256 pinned below; its build.json names no model). Each list row is one Aramaic
                 piece (`key` = pid without `o`) with its Hebrew pick (`hebrew_strong`, `hebrew_lemma`). The Hebrew
                 lexeme is the hbo lexeme whose lemma (NFC) and strong number are those of the pick; where the hbo
                 number carries a letter the list does not write, the hbo lexeme with that lemma and that number without
                 its letter, when exactly one exists. Rows with no pick, or no single hbo lexeme, are left out and counted
                 by reason. count = the Aramaic lexeme's pieces with that pick; share = count / the Aramaic lexeme's
                 pieces. kind linked.
"""
import collections as C
import csv
import hashlib
import json
import os
import re
import unicodedata as U

import pyarrow.parquet as pq

import examples_common as X
from examples_people import FACT_SCHEMA

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PARAMS = os.path.join(ROOT, "internal-docs/source-examples-work/tools/team_parameters.tsv")
EQUIV = os.path.join(ROOT, "internal-docs/aramaic-hebrew-equivalents-release/v0.1.1/data/words.parquet")
EQUIV_SHA = "90f71ff81c4637fec8a3afe79efecce3c5b7b7732523fe3b587bbc1c87ce2b46"
EQUIV_BUILD = os.path.join(ROOT, "internal-docs/aramaic-hebrew-equivalents-release/v0.1.1/build.json")
S9_RELATIONS = ("has_class", "in_domain", "sense_of", "equivalent_of")
SOURCE_OF = {"hbo": "macula-hebrew", "arc": "macula-hebrew", "grc": "macula-greek"}
MAP_HEADER = ["table", "category", "code", "feature", "value", "reason", "count"]
PROFILE_HEADER = ["id", "question", "value", "statement", "count"]

# ---- D6: the map ---------------------------------------------------------------------------------------------------
# MAP[(table, category)] = {code: [(feature, value), ...] or ("none", reason)}; a category given as a str maps every
# code to none with that reason. Language keys override per language.
_N = lambda r: ("none", r)  # noqa: E731
_GENDER = {"m": [("Gender", "Masc")], "f": [("Gender", "Fem")], "n": [("Gender", "Neut")], "c": [("Gender", "Com")],
           "b": [("Gender", "Fem,Masc")], "x": _N("unknown_value")}
_NUMBER = {"sg": [("Number", "Sing")], "pl": [("Number", "Plur")], "du": [("Number", "Dual")], "x": _N("unknown_value")}
_PERSON = {"1": [("Person", "1")], "2": [("Person", "2")], "3": [("Person", "3")], "x": _N("unknown_value")}
_FIN = ("VerbForm", "Fin")
_HEB_TYPE = {
    # nouns and adjectives: the subtype is a part of speech in UD
    "common": _N("upos_not_feature"), "proper": _N("upos_not_feature"), "adjective": _N("upos_not_feature"),
    "gentilic": _N("no_ud_feature"),
    "cardinal_number": [("NumType", "Card")], "ordinal_number": [("NumType", "Ord")],
    # verbs: the conjugations are finite forms; UD's Tense and Aspect would be a reading of them
    "qatal": [_FIN], "yiqtol": [_FIN], "wayyiqtol": [_FIN], "weqatal": [_FIN],
    "imperative": [("Mood", "Imp"), _FIN], "jussive": [("Mood", "Jus"), _FIN],
    "cohortative": [_FIN],          # UD has no cohortative value; only the finiteness maps
    "infinitive_construct": [("VerbForm", "Inf")], "infinitive_absolute": [("VerbForm", "Inf")],
    "participle_active": [("VerbForm", "Part"), ("Voice", "Act")],
    "participle_passive": [("VerbForm", "Part"), ("Voice", "Pass")],
    # pronouns and particles
    "personal": [("PronType", "Prs")], "pronominal": [("PronType", "Prs")], "demonstrative": [("PronType", "Dem")],
    "interrogative": [("PronType", "Int")], "relative": [("PronType", "Rel")], "indefinite": [("PronType", "Ind")],
    "definite_article": [("PronType", "Art")], "negative": [("Polarity", "Neg")],
    "affirmation": _N("no_ud_value"), "exhortation": _N("no_ud_feature"), "interjection": _N("upos_not_feature"),
    "direct_object_marker": _N("no_ud_value"), "directional_he": _N("no_ud_value"),
    "paragogic_he": _N("no_ud_feature"), "paragogic_nun": _N("no_ud_feature"),
    "unknown_x": _N("unknown_value"),
}
_GRC_TYPE = {
    "common": _N("upos_not_feature"), "proper": _N("upos_not_feature"),
    "personal": [("PronType", "Prs")], "demonstrative": [("PronType", "Dem")], "indefinite": [("PronType", "Ind")],
    "interrogative": [("PronType", "Int")], "relative": [("PronType", "Rel")], "possessive": [("Poss", "Yes")],
    "adverbial": _N("no_ud_value"),
}
_FORCE = {"imperative": [("Mood", "Imp")], "jussive": [("Mood", "Jus")], "declarative": _N("no_ud_value"),
          "interrogative": _N("no_ud_value"), "prohibitive": _N("no_ud_value"), "cohortative": _N("no_ud_value"),
          "hortatory": _N("no_ud_value")}
_CLAUSE_VOICE = {"active": [("Voice", "Act")], "passive": [("Voice", "Pass")], "middle": [("Voice", "Mid")],
                 "middlepassive": [("Voice", "Mid,Pass")]}
MAP = {
    "all": {
        ("pieces", "gender"): _GENDER, ("pieces", "number"): _NUMBER, ("pieces", "person"): _PERSON,
        ("pieces", "stem"): "no_ud_feature",
        ("pieces", "state"): {"cstr": [("Definite", "Cons")], "det": [("Definite", "Def")], "abs": _N("no_ud_value")},
        ("pieces", "type"): _HEB_TYPE,
        ("pieces", "tense"): {"pres": [("Tense", "Pres")], "fut": [("Tense", "Fut")], "impf": [("Tense", "Imp")],
                              "plprf": [("Tense", "Pqp")], "aor": _N("no_ud_value"), "prf": _N("no_ud_value")},
        ("pieces", "voice"): {"act": [("Voice", "Act")], "mid": [("Voice", "Mid")], "pass": [("Voice", "Pass")],
                              "midpass": [("Voice", "Mid,Pass")]},
        ("pieces", "mood"): {"ind": [("Mood", "Ind")], "sbjv": [("Mood", "Sub")], "opt": [("Mood", "Opt")],
                             "imp": [("Mood", "Imp")], "inf": [("VerbForm", "Inf")], "ptcp": [("VerbForm", "Part")]},
        ("pieces", "case"): {"nom": [("Case", "Nom")], "gen": [("Case", "Gen")], "dat": [("Case", "Dat")],
                             "acc": [("Case", "Acc")], "voc": [("Case", "Voc")]},
        ("pieces", "degree"): {"cmpr": [("Degree", "Cmp")], "sprl": [("Degree", "Sup")]},
        ("clauses", "kind"): "no_ud_feature",
        ("clauses", "force"): _FORCE,
        ("clauses", "polarity"): {"affirmative": [("Polarity", "Pos")], "negative": [("Polarity", "Neg")]},
        ("clauses", "negator"): "lexeme_value",
        ("clauses", "neg_scope"): "no_ud_feature",
        ("clauses", "connective"): "lexeme_value",
        ("clauses", "voice"): _CLAUSE_VOICE,
        ("clauses", "transitivity"): "no_ud_feature",
        ("clauses", "subject_form"): "no_ud_feature",
        ("clauses", "subject_switch"): "no_ud_feature",
        ("clauses", "fronted"): "no_ud_feature",
    },
    # Aramaic: the absolute state stands against the determined (emphatic) state, so it is UD's indefinite
    "arc": {("pieces", "state"): {"cstr": [("Definite", "Cons")], "det": [("Definite", "Def")],
                                  "abs": [("Definite", "Ind")]}},
    "grc": {("pieces", "type"): _GRC_TYPE},
}


def map_of(lang, table, cat, code):
    m = MAP.get(lang, {}).get((table, cat), MAP["all"].get((table, cat)))
    if m is None:
        raise ValueError(f"{lang}: category {table}.{cat} has no row in MAP")
    if isinstance(m, str):
        return ("none", m)
    if code not in m:
        raise ValueError(f"{lang}: {table}.{cat} code {code!r} has no row in MAP")
    return m[code]


def _codes(marks_json):
    """(category, code) pairs of a marks value; a list value gives one pair per item."""
    if not marks_json:
        return []
    out = []
    for cat, v in json.loads(marks_json).items():
        for code in (v if isinstance(v, list) else [v]):
            out.append((cat, code))
    return out


def shared_of(lang, table, marks_json, cache, ex):
    if marks_json is None:
        return None
    hit = cache.get(marks_json)
    if hit is not None:
        return hit
    feats = {}
    for cat, code in _codes(marks_json):
        m = map_of(lang, table, cat, code)
        if isinstance(m, tuple):
            continue
        for f, v in m:
            if f in feats and feats[f] != v:
                ex[f"{lang} {table}: two codes give one feature two values"].append(f"{marks_json} {f}")
                raise ValueError(f"{lang} {table}: {marks_json} gives {f} two values")
            feats[f] = v
    out = X.jdump(feats)
    cache[marks_json] = out
    return out


def build_map(lang, P, K, cnt, ex):
    use = C.Counter()
    for table, col in (("pieces", P["marks"]), ("clauses", K["marks"])):
        for mj, n in C.Counter(col).items():
            for cat, code in set(_codes(mj)):
                use[(table, cat, code)] += n
    rows = []
    for (table, cat, code), n in sorted(use.items()):
        m = map_of(lang, table, cat, code)
        if isinstance(m, tuple):
            rows.append([table, cat, code, "none", "", m[1], n])
            ex[f"{lang} map: codes with no shared feature"].append(f"{table}.{cat}={code} ({m[1]}) {n}")
        else:
            for f, v in sorted(m):
                rows.append([table, cat, code, f, v, "", n])
    cnt[f"{lang} map.tsv rows"] = len(rows)
    cnt[f"{lang} map codes"] = len(use)
    cnt[f"{lang} map codes none"] = sum(1 for k in use if isinstance(map_of(lang, *k), tuple))
    return rows


# ---- facts ---------------------------------------------------------------------------------------------------------

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _fact(s, rel, o, kind, method, source, count, share):
    return {"subject": s, "relation": rel, "object": o, "kind": kind, "method": method, "source": source,
            "confidence": None, "count": count, "share": share, "tier": ""}


def piece_facts(lang, P):
    per_lex = C.Counter(P["lexeme"])
    cls, dom, sen = C.Counter(), C.Counter(), C.Counter()
    for lx, c, d, s in zip(P["lexeme"], P["class"], P["domain"], P["sense"]):
        cls[(lx, c)] += 1
        for code in sorted(set((d or "").split())):
            dom[(lx, code)] += 1
        if s:
            sen[(s, lx)] += 1
    src = SOURCE_OF[lang]
    rows = [_fact(lx, "has_class", c, "given", "pieces.class", src, n, n / per_lex[lx]) for (lx, c), n in cls.items()]
    rows += [_fact(lx, "in_domain", d, "given", "pieces.domain", "word-senses-ubs", n, n / per_lex[lx])
             for (lx, d), n in dom.items()]
    rows += [_fact(s, "sense_of", lx, "given", "pieces.sense", "word-senses-ubs", n, None) for (s, lx), n in sen.items()]
    return rows


def equivalent_facts(P, hbo_lexemes, cnt, ex):
    got = sha256(EQUIV)
    if got != EQUIV_SHA:
        raise SystemExit(f"aramaic-hebrew-equivalents words.parquet: sha256 {got}, pinned {EQUIV_SHA}")
    with open(EQUIV_BUILD, encoding="utf-8") as fh:
        build = json.load(fh)
    if re.search(r"model|llm|claude|gpt|opus|sonnet|haiku", json.dumps(build), re.I):
        raise SystemExit("aramaic-hebrew-equivalents build.json names a model: equivalent_of not written")
    exact, digits = C.defaultdict(list), C.defaultdict(list)
    for r in hbo_lexemes:
        lem = U.normalize("NFC", r["lemma"])
        exact[(lem, r["strong"].lstrip("0"))].append(r["lexeme"])
        digits[(lem, re.sub(r"[a-z]", "", r["strong"]).lstrip("0"))].append(r["lexeme"])
    lex_of = {pid: lx for pid, lx in zip(P["pid"], P["lexeme"])}
    per_lex = C.Counter(P["lexeme"])
    pair = C.Counter()
    why = C.Counter()
    for r in pq.read_table(EQUIV).to_pylist():
        pid = "o" + r["key"]
        if pid not in lex_of:
            why["list key is no arc piece"] += 1
            ex["arc equivalent_of: list key is no arc piece"].append(r["key"])
            continue
        if not r["hebrew_strong"]:
            why["no pick in the list"] += 1
            continue
        if not r["hebrew_lemma"]:
            why["pick without a Hebrew lemma"] += 1
            ex["arc equivalent_of: pick without a Hebrew lemma"].append(f"{r['key']} {r['hebrew_strong']}")
            continue
        k = (U.normalize("NFC", r["hebrew_lemma"]), r["hebrew_strong"].lstrip("0"))
        if len(exact.get(k, [])) == 1:
            hx = exact[k][0]
            why["resolved: lemma and number"] += 1
        elif not exact.get(k) and len(digits.get(k, [])) == 1:
            hx = digits[k][0]
            why["resolved: lemma and number without its letter"] += 1
        else:
            n = len(exact.get(k) or digits.get(k) or [])
            reason = "no hbo lexeme with that lemma and number" if n == 0 else "several hbo lexemes"
            why[reason] += 1
            ex[f"arc equivalent_of: {reason}"].append(f"{r['key']} {r['hebrew_lemma']} {r['hebrew_strong']}")
            continue
        if X.V14:     # SPEC 1.4 D24a: the row's basis follows its evidence (greek_verse reads GLAUx's lemma: M7)
            pair[(lex_of[pid], hx, D24A_KIND[r["evidence"]])] += 1
        else:
            pair[(lex_of[pid], hx)] += 1
    cnt["arc equivalent_of: list rows by outcome"] = dict(sorted(why.items()))
    if X.V14:
        return [_fact(ax, "equivalent_of", hx, kind, "words.parquet:hebrew_strong", "aramaic-hebrew-equivalents",
                      n, n / per_lex[ax]) for (ax, hx, kind), n in pair.items()]
    return [_fact(ax, "equivalent_of", hx, "linked", "words.parquet:hebrew_strong", "aramaic-hebrew-equivalents",
                  n, n / per_lex[ax]) for (ax, hx), n in pair.items()]


# SPEC 1.4 D24a: the basis of a list row by its evidence (a row without a pick gives nothing)
D24A_KIND = {"cognate_meaning": "derived", "domain": "derived", "greek_word": "derived", "greek_verse": "model"}


def write_facts(d, lang, new, cnt):
    path = os.path.join(d, "facts.parquet")
    old = [r for r in pq.read_table(path).to_pylist() if r["relation"] not in S9_RELATIONS]
    if X.V14:     # SPEC 1.4 D24a: equivalent_of is one row per (subject, object, kind)
        rows = sorted(old + new, key=lambda r: (r["subject"], r["relation"], r["object"], r["kind"]))
        keys = [(r["subject"], r["relation"], r["object"], r["kind"]) for r in rows]
    else:
        rows = sorted(old + new, key=lambda r: (r["subject"], r["relation"], r["object"]))
        keys = [(r["subject"], r["relation"], r["object"]) for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError(f"{lang} facts: a (subject, relation, object) twice")
    X.write_parquet(path, {f.name: [r[f.name] for r in rows] for f in FACT_SCHEMA}, FACT_SCHEMA)
    cnt[f"{lang} facts rows kept (stages 06, 08)"] = len(old)
    for rel in S9_RELATIONS:
        cnt[f"{lang} facts {rel}"] = sum(1 for r in new if r["relation"] == rel)


# ---- profile.tsv ---------------------------------------------------------------------------------------------------
# A rule names the statement rows that answer a question, per language ("*" = every language), and how the value
# follows from them. MIN: the places a rule needs before it answers. Kinds:
#   exists   1 where some selected row has count >= MIN (and, if given, `lexemes` >= min_lexemes); evidence: the
#            selected row with the largest count. Else `?`.
#   all      1 where each of several selectors finds such a row; evidence: one row per selector. Else `?`.
#   order    over the selected `orders` rows: B = sum of before, A = sum of after; with B + A >= MIN, the dominant
#            side's value where the other side is under 10%, else the value for both; evidence: every selected row
#   side     1 where the named side (before | after) of the selected `orders` rows sums to >= MIN; else `?`
#   agree    over the selected `agreement` rows: 1 where sum(agree) >= MIN and agree / (agree + differ) >= 0.75; else `?`
#   corder   the `constructions` clause rows whose rule is exactly one of the patterns; shares per order type:
#            1 for a type with share >= 0.25, 0 for a type with share < 0.10, else `?`; evidence: every such row
#   fixed    over the same rows: 1 where one pattern has share >= 0.99, 0 where none has 0.90, else `?`
# Values of the multistate questions are Grambank's codes (GB024: 1 Num-N, 2 N-Num, 3 both; GB025 Dem; GB065
# 1 possessor first; GB130 1 SV, 2 VS, 3 both; GB193 1 adjective first; GB203 1 'all' first).
MIN = 20
SVO = {"V-S-O": "initial", "V-O-S": "initial", "S-V-O": "medial", "O-V-S": "medial", "S-O-V": "final",
       "O-S-V": "final"}
_ORD3 = {"before": "1", "after": "2", "both": "3"}
_NOUNHEAD = {"head_class": "noun"}
PROFILE = {
    "GB020": {"*": ("exists", "paradigms", {"class": {"art", "det"}})},
    "GB022": {"hbo": ("exists", "markers", {"kind": "prefix", "lex_class": "art"}),
              "arc": ("exists", "markers", {"kind": "prefix", "lex_class": "art"}),
              "grc": ("side", "before", {"rel": {"DetNP:0"}, "dep_class": "det", **_NOUNHEAD})},
    "GB023": {"hbo": ("exists", "markers", {"kind": "suffix", "lex_class": "art"}),
              "arc": ("exists", "markers", {"kind": "suffix", "lex_class": "art"}),
              "grc": ("side", "after", {"rel": {"DetNP:0"}, "dep_class": "det", **_NOUNHEAD})},
    "GB024": {"*": ("order", _ORD3, {"rel": {"NumpNP:0", "NpNump:1"}, "dep_class": "num", **_NOUNHEAD})},
    "GB025": {"*": ("order", _ORD3, {"rel": {"NP-Demo:1", "Demo-NP:0"}, "dep_class": "pron", **_NOUNHEAD})},
    "GB030": {"*": ("all", "paradigms", [{"class": "pron", "marks_has": {"type": "personal", "person": "3",
                                                                          "gender": "m"}},
                                         {"class": "pron", "marks_has": {"type": "personal", "person": "3",
                                                                          "gender": "f"}}])},
    "GB043": {"*": ("exists", "paradigms", {"class": "noun", "marks_has": {"number": "du"}, "min_lexemes": 10})},
    "GB044": {"*": ("exists", "paradigms", {"class": "noun", "marks_has": {"number": "pl"}, "min_lexemes": 10})},
    "GB065": {"*": ("order", _ORD3, {"rel": {"NPofNP:1"}, "dep_class": {"noun", "pron"}, **_NOUNHEAD})},
    "GB070": {"*": ("all", "paradigms", [{"class": "noun", "marks_has": {"case": "nom"}},
                                         {"class": "noun", "marks_has": {"case": "acc"}}])},
    "GB071": {"*": ("all", "paradigms", [{"class": "pron", "marks_has": {"type": "personal", "case": "nom"}},
                                         {"class": "pron", "marks_has": {"type": "personal", "case": "acc"}}])},
    "GB072": {"*": ("exists", "paradigms", {"class": "noun", "marks_has": {"case": {"dat", "gen"}}})},
    "GB073": {"*": ("exists", "paradigms", {"class": "pron", "marks_has": {"type": "personal",
                                                                            "case": {"dat", "gen"}}})},
    "GB074": {"*": ("side", "before", {"rel": {"PrepNp:0"}, "dep_class": "prep"})},
    "GB084": {"*": ("exists", "paradigms", {"class": "verb", "marks_has": {"tense": "fut"}})},
    "GB117": {"*": ("exists", "constructions", {"level": "clause", "rule_has": {"VC", "P"}})},
    "GB130": {"*": ("order_clause", {"S-V": "1", "V-S": "2", "both": "3"})},
    "GB131": {"*": ("corder", "initial")},
    "GB132": {"*": ("corder", "medial")},
    "GB133": {"*": ("corder", "final")},
    "GB136": {"*": ("fixed",)},
    "GB147": {"*": ("exists", "paradigms", {"class": "verb", "marks_has": {"voice": "pass"}})},
    "GB170": {"*": ("agree", {"rel": {"NpAdjp:1", "AdjpNp:0", "NPDetAdj:1"}, "category": "gender"})},
    "GB171": {"*": ("agree", {"rel": {"NP-Demo:1", "Demo-NP:0"}, "category": "gender"})},
    "GB172": {"*": ("agree", {"rel": {"DetNP:0"}, "category": "gender"})},
    "GB184": {"*": ("agree", {"rel": {"NpAdjp:1", "AdjpNp:0", "NPDetAdj:1"}, "category": "number"})},
    "GB185": {"*": ("agree", {"rel": {"NP-Demo:1", "Demo-NP:0"}, "category": "number"})},
    "GB186": {"*": ("agree", {"rel": {"DetNP:0"}, "category": "number"})},
    "GB193": {"*": ("order", _ORD3, {"rel": {"NpAdjp:1", "AdjpNp:0", "NPDetAdj:1"}, "dep_class": "adj",
                                     **_NOUNHEAD})},
    "GB196": {"*": ("all", "paradigms", [{"class": "pron", "marks_has": {"type": "personal", "person": "2",
                                                                          "gender": "m"}},
                                         {"class": "pron", "marks_has": {"type": "personal", "person": "2",
                                                                          "gender": "f"}}])},
    "GB197": {"*": ("all", "paradigms", [{"class": "pron", "marks_has": {"type": "personal", "person": "1",
                                                                          "gender": "m"}},
                                         {"class": "pron", "marks_has": {"type": "personal", "person": "1",
                                                                          "gender": "f"}}])},
    "GB198": {"*": ("agree", {"rel": {"NumpNP:0", "NpNump:1"}, "category": "gender"})},
    "GB203": {"*": ("order", _ORD3, {"rel": {"All-NP:0"}, "dep_class": {"adj", "noun"}, **_NOUNHEAD})},
    "GB275": {"*": ("exists", "paradigms", {"class": "adj", "marks_has": {"degree": "cmpr"}})},
    "GB299": {"*": ("exists", "paradigms", {"marks_eq": {"type": "negative"}})},
    "GB312": {"hbo": ("exists", "paradigms", {"class": "verb", "marks_has": {"type": {"jussive", "cohortative"}}}),
              "arc": ("exists", "paradigms", {"class": "verb", "marks_has": {"type": {"jussive", "cohortative"}}}),
              "grc": ("exists", "paradigms", {"class": "verb", "marks_has": {"mood": {"sbjv", "opt"}}})},
    "GB327": {"*": ("side", "after", {"rel": {"NpRelp:1", "NpCL:1", "NP-CL:1"}, **_NOUNHEAD})},
    "GB433": {"*": ("exists", "markers", {"kind": "suffix", "lex_class": "pron", "category": "state",
                                          "value": "cstr"})},
    "GB522": {"*": ("exists", "frames", {"frame_lacks": "s"})},
}


def _num(sid):
    return int(sid.rsplit(":", 1)[1])


def _is(v, want):
    return v in want if isinstance(want, set) else v == want


def select(rows, sel, lex_class):
    out = []
    for r in rows:
        ok = True
        for k, want in sel.items():
            if k == "min_lexemes":
                continue
            if k == "marks_has":
                m = json.loads(r["marks"])
                ok = all(c in m and _is(m[c], w) for c, w in want.items())
            elif k == "marks_eq":
                ok = json.loads(r["marks"]) == want
            elif k == "lex_class":
                ok = lex_class.get(r["lexeme"]) == want
            elif k == "rule_has":
                ok = want <= set(r["rule"].split("-"))
            elif k == "frame_lacks":
                ok = want not in r["frame"].split(" ")
            else:
                ok = _is(r[k], want)
            if not ok:
                break
        if ok:
            out.append(r)
    return out


def _largest(rows, sel):
    good = [r for r in rows if r["count"] >= MIN and r.get("lexemes", MIN) >= sel.get("min_lexemes", 0)]
    return min(good, key=lambda r: (-r["count"], _num(r["id"]))) if good else None


def _svo_rows(T):
    return sorted((r for r in T["constructions"] if r["level"] == "clause" and r["rule"] in SVO),
                  key=lambda r: _num(r["id"]))


def answer(rule, T, lex_class):
    """-> (value, [rows of evidence])"""
    kind = rule[0]
    if kind == "exists":
        r = _largest(select(T[rule[1]], rule[2], lex_class), rule[2])
        return ("1", [r]) if r else ("?", [])
    if kind == "all":
        ev = [_largest(select(T[rule[1]], s, lex_class), s) for s in rule[2]]
        return ("1", ev) if all(ev) else ("?", [])
    if kind in ("order", "side"):
        rows = sorted(select(T["orders"], rule[2], lex_class), key=lambda r: _num(r["id"]))
        b, a = sum(r["before"] for r in rows), sum(r["after"] for r in rows)
        if kind == "side":
            side = b if rule[1] == "before" else a
            return ("1", [r for r in rows if r[rule[1]] > 0]) if side >= MIN else ("?", [])
        if b + a < MIN:
            return ("?", [])
        if min(a, b) / (a + b) < 0.10:
            return (rule[1]["before" if b > a else "after"], rows)
        return (rule[1]["both"], rows)
    if kind == "agree":
        rows = sorted(select(T["agreement"], rule[1], lex_class), key=lambda r: _num(r["id"]))
        ag, df = sum(r["agree"] for r in rows), sum(r["differ"] for r in rows)
        return ("1", rows) if ag >= MIN and ag / (ag + df) >= 0.75 else ("?", [])
    if kind == "order_clause":
        rows = sorted((r for r in T["constructions"] if r["level"] == "clause" and r["rule"] in ("S-V", "V-S")),
                      key=lambda r: _num(r["id"]))
        sv = sum(r["count"] for r in rows if r["rule"] == "S-V")
        vs = sum(r["count"] for r in rows if r["rule"] == "V-S")
        if sv + vs < MIN:
            return ("?", [])
        if min(sv, vs) / (sv + vs) < 0.10:
            return (rule[1]["S-V" if sv > vs else "V-S"], rows)
        return (rule[1]["both"], rows)
    if kind in ("corder", "fixed"):
        rows = _svo_rows(T)
        tot = sum(r["count"] for r in rows)
        if tot < MIN:
            return ("?", [])
        if kind == "corder":
            share = sum(r["count"] for r in rows if SVO[r["rule"]] == rule[1]) / tot
            return ("1", rows) if share >= 0.25 else ("0", rows) if share < 0.10 else ("?", [])
        per = C.Counter()
        for r in rows:
            per[r["rule"]] += r["count"]
        top = max(per.values()) / tot
        return ("1", rows) if top >= 0.99 else ("0", rows) if top < 0.90 else ("?", [])
    raise ValueError(kind)


def build_profile(lang, d, cnt):
    T = {}
    for tb in ("paradigms", "markers", "orders", "agreement", "constructions", "frames"):
        cols = [c for c in pq.read_schema(os.path.join(d, f"{tb}.parquet")).names if c != "places"]
        T[tb] = pq.read_table(os.path.join(d, f"{tb}.parquet"), columns=cols).to_pylist()
    with open(os.path.join(d, "lexemes.tsv"), encoding="utf-8") as fh:
        lex_class = {r["lexeme"]: r["class"] for r in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)}
    with open(PARAMS, encoding="utf-8") as fh:
        params = [ln.rstrip("\n").split("\t") for ln in fh if ln.strip() and not ln.startswith("#")]
    if params[0] != ["id", "question"] or len(params) != 196:
        raise SystemExit(f"team_parameters.tsv: header {params[0]}, {len(params) - 1} rows (195 expected)")
    unknown = sorted(set(PROFILE) - {p[0] for p in params[1:]})
    if unknown:
        raise SystemExit(f"PROFILE names ids the questionnaire lacks: {unknown}")
    rows, by = [], C.Counter()
    for pid, question in params[1:]:
        rule = PROFILE.get(pid, {})
        rule = rule.get(lang, rule.get("*"))
        value, ev = answer(rule, T, lex_class) if rule else ("?", [])
        by[value] += 1
        rows.append([pid, question, value, " ".join(r["id"] for r in ev), " ".join(str(r["count"]) for r in ev)])
    X.write_tsv(os.path.join(d, "profile.tsv"), PROFILE_HEADER, rows)
    cnt[f"{lang} profile rows"] = len(rows)
    cnt[f"{lang} profile answered"] = sum(v for k, v in by.items() if k != "?")
    cnt[f"{lang} profile by value"] = dict(sorted(by.items()))
    cnt[f"{lang} profile answered ids"] = " ".join(f"{r[0]}={r[2]}" for r in rows if r[2] != "?")


# ---- the stage -----------------------------------------------------------------------------------------------------

def _read(path):
    t = pq.read_table(path)
    return t.to_pydict(), t.schema


def build(outdir, langs, counts):
    ex = C.defaultdict(list)
    hbo_lex = None
    for lang in langs:
        d = os.path.join(outdir, lang)
        P, Ps = _read(os.path.join(d, "pieces.parquet"))
        K, Ks = _read(os.path.join(d, "clauses.parquet"))
        rows = build_map(lang, P, K, counts, ex)
        X.write_tsv(os.path.join(d, "map.tsv"), MAP_HEADER, rows)
        cache_p, cache_k = {}, {}
        P["shared"] = [shared_of(lang, "pieces", m, cache_p, ex) for m in P["marks"]]
        K["shared"] = [shared_of(lang, "clauses", m, cache_k, ex) for m in K["marks"]]
        counts[f"{lang} pieces with a shared feature"] = sum(1 for s in P["shared"] if s and s != "{}")
        counts[f"{lang} clauses with a shared feature"] = sum(1 for s in K["shared"] if s and s != "{}")
        X.write_parquet(os.path.join(d, "pieces.parquet"), P, Ps)
        X.write_parquet(os.path.join(d, "clauses.parquet"), K, Ks)
        new = piece_facts(lang, P)
        if lang == "arc":
            if hbo_lex is None:
                with open(os.path.join(outdir, "hbo", "lexemes.tsv"), encoding="utf-8") as fh:
                    hbo_lex = list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))
            new += equivalent_facts(P, hbo_lex, counts, ex)
        write_facts(d, lang, new, counts)
        build_profile(lang, d, counts)
    counts["sources read"] = {"aramaic-hebrew-equivalents v0.1.1 data/words.parquet": EQUIV_SHA,
                              "team_parameters.tsv": sha256(PARAMS)}
    return dict(ex)
