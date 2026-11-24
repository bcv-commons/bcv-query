"""Stage 20 of the source examples (SPEC 1.1, section 14: shared-reading). It closes a c build.

    shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build c1 --stage 20

Writes per language (hbo, arc, grc; all three in one run), in <build>/<lang>/:
  relmap.tsv       D4: one row per (label, class of the dependent word's stem piece) that occurs on a word edge:
                   label, class, shared, count (= words). `shared` is a Universal Dependencies relation (universal
                   name, no subtype) or `none`. The table is RELMAP11 below (written by hand, as SPEC 4.10 asks).
  words.parquet    anew, with `rel_shared` (D4); nothing else changes
  map.tsv          D6: one row per (table, category, code, feature): `class` -> UPOS (G2), the piece categories, and
                   the clause categories (form categories mapped where UD has a feature; readings and meaning
                   categories `none`, G3). Columns table, category, code, feature, value, reason, count. For a meaning
                   category `code` is the code of terms.tsv (the clause holds its term). A code that maps to two
                   features has two rows; a `none` row stands alone with one of the five reason codes (G1).
  pieces.parquet   anew, with `shared` = `marks` and `class` read through map.tsv (`UPOS` from `class`)
  clauses.parquet  anew, with `shared` = the form categories of `marks` read through map.tsv; `{}` where none maps
  facts.parquet    anew: the rows of stages 16 and 19 (kin, rendered_by) kept; has_class, in_domain, sense_of,
                   equivalent_of (arc) written anew (examples_shared.piece_facts, equivalent_facts; G8, G9)
  profile.tsv      id, value, statement, count (G5: no question). MIN = 50 places (G10). An order question is answered
                   only where the commonest order covers at least 0.5 of its places (G6). An answer 0 may rest on
                   categories.toml: the category is present and has no such code (G7); its evidence is
                   `categories.toml:<table>.<category>` and the count of rows that carry the category.
  categories.toml  the shared part appended (after a marker; an older shared part is replaced): words.rel_shared,
                   pieces.shared, clauses.shared, map.reason, map.feature, relmap.shared, facts.relation, facts.kind,
                   facts.source, facts.method, profile.value
  sources.json     the whole file: every source with repository, pin, licence and the sha256 of every file read; the
                   `model` and `links` parts of stages 17 and 19 kept as they are; the builder's files and commit; the
                   Python and pyarrow versions; the specification; what is not read; the licence of the example
  COLUMNS.md       SPEC section 4 (version 1.1) as it stands, then every table file with its columns read from the file,
                   and the build-level texts this language links to (<build>/other/<text>/words.parquet)
  READ-FIRST.md    the reading sheet (examples_read_sheet.sheet) and a section 5: what is `model` and how much
And the glossed chapters: for c1 into internal-docs/source-examples-work/glossed-c1/, for any other build into
<build>/cache/glossed/ (so a rebuild can be compared). VALIDATION.md is written by validate_examples.py --write-md.
"""
import collections as C
import csv
import json
import os
import platform
import re
import sys
import tomllib

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import examples_common as X  # noqa: E402
import examples_read_sheet  # noqa: E402
import examples_reading as RD  # noqa: E402
import examples_shared as S9  # noqa: E402
from examples_relmap import RELMAP as R10  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SPEC = os.path.join(ROOT, "internal-docs/source-examples-spec/SPEC.md")
GLOSSED_C1 = os.path.join(ROOT, "internal-docs/source-examples-work/glossed-c1")
GLOSSED_D1 = os.path.join(ROOT, "internal-docs/source-examples-work/glossed-d1")     # SPEC 1.2, stage 24
GLOSSED_E1 = os.path.join(ROOT, "internal-docs/source-examples-work/glossed-e1")     # SPEC 1.3, stage 29
GLOSSED_G1 = os.path.join(ROOT, "internal-docs/source-examples-work/glossed-g1")     # SPEC 1.5, stage 35
GLOSSED_H1 = os.path.join(ROOT, "internal-docs/source-examples-work/glossed-h1")     # SPEC 1.6, stage 38


def _ver():
    """The specification version of the build being written: 1.2 for a d build (examples_common.V12), else 1.1."""
    return "1.8" if getattr(X, "V18", False) else "1.6" if getattr(X, "V16", False) else "1.5" if getattr(X, "V15", False) else "1.3" if X.V13 else "1.2" if X.V12 else "1.1"


def _doc_stage():
    """The stage that writes COLUMNS.md, READ-FIRST.md and the glossed chapters: 24 (SPEC 1.2) or 20 (SPEC 1.1)."""
    if X.V13:
        return ("29", "examples_close13.py")
    return ("24", "examples_close12.py") if X.V12 else ("20", "examples_shared11.py")


def glossed_dir(outdir):
    """The glossed chapters of c1 (1.1) and d1 (1.2) go to internal-docs; any other build writes its cache/glossed."""
    base = os.path.basename(os.path.normpath(outdir))
    return {"c1": GLOSSED_C1, "d1": GLOSSED_D1, "e1": GLOSSED_E1, "g1": GLOSSED_G1, "h1": GLOSSED_H1}.get(
        base, os.path.join(outdir, "cache", "glossed"))


MARKER = "# ---- the shared part (build_examples.py --stage 20) ----"
LANGS = ("hbo", "arc", "grc")
OTHER = {"hbo": ["lxx"], "arc": ["lxx"], "grc": ["heb_mod", "heb_scg"]}
S20_RELATIONS = S9.S9_RELATIONS
MEANING = ("relation", "time", "aspect", "line_kind")

# ---- D4: relmap by (label, class) -----------------------------------------------------------------------------------
# The label rows of 1.0 (examples_relmap.RELMAP) stay the default of a label. A4 keys the map on the class of the
# dependent word's stem piece as well; the rows below override the label's default for one class. How they were chosen
# (counts of c1, internal-docs/source-examples-work/reports/20-shared-reading.md): a role `adv` or `pp` held by a noun
# or a pronoun is a nominal adverbial (UD `obl`), by a verb a clause (`advcl`), by an adverb or a particle `advmod`, by
# an interjection `discourse`. A demonstrative pronoun in an adjective slot is `det`. An interjection standing as a
# clause beside a clause is `discourse`. Greek role `aux` held by a noun or adjective is a vocative, by a verb (ἰδού,
# ἄγε) `discourse`. A Hebrew or Aramaic run (`run:<place>`, which also names the children of a sentence node, D2p d):
# a conjunction is `cc`, an adverb `advmod`, an interjection `discourse`, everything else `conj`.
_BY_CLASS = {
    "all": {
        ("adv", "noun"): "obl", ("adv", "pron"): "obl", ("adv", "verb"): "advcl", ("adv", "adv"): "advmod",
        ("adv", "ptcl"): "advmod", ("adv", "ij"): "discourse", ("adv", "intj"): "discourse",
        ("pp", "verb"): "advcl",
        ("pp", "verb_nonpred"): "obl", ("adv", "verb_nonpred"): "advmod",      # SPEC 1.2 D4 (hbo, arc only)
        ("NpAdjp:1", "pron"): "det",
        ("ClCl:1", "ij"): "discourse", ("ClCl2:0", "ij"): "discourse",
    },
    "grc": {
        ("adv", "det"): "obl",
        ("aux", "verb"): "discourse", ("aux", "noun"): "vocative", ("aux", "adj"): "vocative",
    },
}
_RUN_CLASS = {"cj": "cc", "adv": "advmod", "ij": "discourse"}


def shared_rel(lang, label, cls):
    """D4: (label, class) -> UD relation or `none`."""
    hit = _BY_CLASS.get(lang, {}).get((label, cls)) or _BY_CLASS["all"].get((label, cls))
    if hit:
        return hit
    if re.fullmatch(r"run:[0-9]+", label):
        return _RUN_CLASS.get(cls, "conj")
    return R10.get(lang, {}).get(label) or R10["all"].get(label) or "none"


def build_relmap(lang, W, P, cnt, K=None):
    cls = {t: c for t, k, c in zip(P["t"], P["kind"], P["class"]) if k == "stem"}
    if X.V12 and lang != "grc":
        # SPEC 1.2 D4: a Hebrew or Aramaic verb word that is the pred of no clause has the class verb_nonpred here
        preds = set(K["pred"]) - {0}
        moved = C.Counter()
        for t, r in zip(W["t"], W["rel"]):
            if cls[t] == "verb" and t not in preds:
                moved[r] += 1
        cls = {t: ("verb_nonpred" if c == "verb" and t not in preds else c) for t, c in cls.items()}
        cnt[f"{lang} D4 words of class verb that are no clause's pred (verb_nonpred), by label (pp, adv)"] = {
            k: moved[k] for k in ("pp", "adv")}
        cnt[f"{lang} D4 words of class verb_nonpred"] = sum(moved.values())
    pairs = C.Counter((r, cls[t]) for t, r in zip(W["t"], W["rel"]))
    rows = [[lab, c, shared_rel(lang, lab, c), n] for (lab, c), n in sorted(pairs.items())]
    shared = {(r[0], r[1]): r[2] for r in rows}
    W["rel_shared"] = [shared[(r, cls[t])] for t, r in zip(W["t"], W["rel"])]
    n = len(W["t"])
    thr = 0.001 * n
    cnt[f"{lang} relmap rows (label, class)"] = len(rows)
    cnt[f"{lang} relmap pairs covering at least 0.1% of the words"] = sum(1 for r in rows if r[3] >= thr)
    cnt[f"{lang} relmap pairs at least 0.1% mapped none"] = sum(1 for r in rows if r[3] >= thr and r[2] == "none")
    nn = sum(1 for v in W["rel_shared"] if v == "none")
    nd = sum(1 for v in W["rel_shared"] if v == "dep")
    cnt[f"{lang} words rel_shared none"] = f"{nn} ({nn / n:.4f})"
    cnt[f"{lang} words rel_shared dep"] = f"{nd} ({nd / n:.4f})"
    return rows


# ---- D6: the map ----------------------------------------------------------------------------------------------------
_N = S9._N
_UPOS_HEB = {"adj": [("UPOS", "ADJ")], "adv": [("UPOS", "ADV")], "art": [("UPOS", "DET")], "cj": _N("no_ud_value"),
             "ij": [("UPOS", "INTJ")], "noun": [("UPOS", "NOUN")], "num": [("UPOS", "NUM")], "om": [("UPOS", "ADP")],
             "prep": [("UPOS", "ADP")], "pron": [("UPOS", "PRON")], "ptcl": [("UPOS", "PART")],
             "rel": [("UPOS", "SCONJ")], "verb": [("UPOS", "VERB")], "x": _N("no_ud_value")}
_UPOS_GRC = {"adj": [("UPOS", "ADJ")], "adv": [("UPOS", "ADV")], "conj": _N("no_ud_value"), "det": [("UPOS", "DET")],
             "intj": [("UPOS", "INTJ")], "noun": [("UPOS", "NOUN")], "num": [("UPOS", "NUM")],
             "prep": [("UPOS", "ADP")], "pron": [("UPOS", "PRON")], "ptcl": [("UPOS", "PART")],
             "verb": [("UPOS", "VERB")]}
MAP11 = {
    "all": {**S9.MAP["all"], ("pieces", "class"): _UPOS_HEB,
            ("clauses", "relation"): "no_ud_feature", ("clauses", "line_kind"): "no_ud_feature",
            ("clauses", "time"): "no_ud_value", ("clauses", "aspect"): "no_ud_value",
            # G3: the Hebrew clause voice is a reading (from stem formation and verb form)
            ("clauses", "voice"): "no_ud_value"},
    "arc": dict(S9.MAP["arc"]),
    "grc": {**S9.MAP["grc"], ("pieces", "class"): _UPOS_GRC, ("clauses", "voice"): S9._CLAUSE_VOICE},
}


def map_of(lang, table, cat, code):
    m = MAP11.get(lang, {}).get((table, cat), MAP11["all"].get((table, cat)))
    if X.V12 and table == "clauses" and (cat in MEANING or (cat == "voice" and lang != "grc")):
        return ("none", "reading")        # SPEC 1.2 4.10 (item 20.6): meaning categories and readings
    if m is None:
        raise ValueError(f"{lang}: category {table}.{cat} has no row in MAP11")
    if isinstance(m, str):
        return ("none", m)
    if code not in m:
        raise ValueError(f"{lang}: {table}.{cat} code {code!r} has no row in MAP11")
    return m[code]


def term_codes(d):
    """clause meaning category -> term -> code, from categories.toml (stage 16)."""
    with open(os.path.join(d, "categories.toml"), "rb") as fh:
        cats = tomllib.load(fh)
    return {cat: {v["term"]: v["code"] for v in cats["clauses"][cat]["values"]}
            for cat in MEANING if cat in cats.get("clauses", {})}


def _codes(table, marks_json, cls, tc):
    out = [("class", cls)] if table == "pieces" else []
    if marks_json:
        for cat, v in json.loads(marks_json).items():
            for code in (v if isinstance(v, list) else [v]):
                out.append((cat, tc[cat][code] if table == "clauses" and cat in tc else code))  # 1.3: Greek pieces have a mood too
    return out


def shared_of(lang, table, marks_json, cls, tc, memo):
    key = (marks_json, cls)
    if key in memo:
        return memo[key]
    feats = {}
    for cat, code in _codes(table, marks_json, cls, tc):
        m = map_of(lang, table, cat, code)
        if isinstance(m, tuple):
            continue
        for f, v in m:
            if f in feats and feats[f] != v:
                raise ValueError(f"{lang} {table}: {marks_json} gives {f} two values")
            feats[f] = v
    memo[key] = X.jdump(feats)
    return memo[key]


def build_map(lang, P, K, tc, cnt):
    use = C.Counter()
    for (mj, cls), n in C.Counter(zip(P["marks"], P["class"])).items():
        for cat, code in set(_codes("pieces", mj, cls, tc)):
            use[("pieces", cat, code)] += n
    for mj, n in C.Counter(K["marks"]).items():
        for cat, code in set(_codes("clauses", mj, None, tc)):
            use[("clauses", cat, code)] += n
    rows = []
    for (table, cat, code), n in sorted(use.items()):
        m = map_of(lang, table, cat, code)
        if isinstance(m, tuple):
            rows.append([table, cat, code, "none", "", m[1], n])
        else:
            for f, v in sorted(m):
                rows.append([table, cat, code, f, v, "", n])
    cnt[f"{lang} map.tsv rows"] = len(rows)
    cnt[f"{lang} map codes"] = len(use)
    cnt[f"{lang} map codes none"] = sum(1 for k in use if isinstance(map_of(lang, *k), tuple))
    cnt[f"{lang} map codes none by reason"] = dict(sorted(C.Counter(map_of(lang, *k)[1] for k in use
                                                                     if isinstance(map_of(lang, *k), tuple)).items()))
    return rows


# ---- profile.tsv (SPEC 1.1, 4.10; G5, G6, G7, G10) -------------------------------------------------------------------
MIN = 50
PROFILE_HEADER = ["id", "value", "statement", "count"]
# G7: (table, category, code) whose absence from a present category answers 0, per language ("*" = every language)
NOCODE = {"GB043": {"*": ("pieces", "number", "du")}}


def answer11(rule, T, lex_class):
    """The rules of examples_shared.answer with MIN 50 (G10) and G6. -> (value, rows of evidence)"""
    kind = rule[0]
    if kind in ("corder",):
        rows = S9._svo_rows(T)
        tot = sum(r["count"] for r in rows)
        if tot < MIN:
            return ("?", [])
        per = C.Counter()
        for r in rows:
            per[S9.SVO[r["rule"]]] += r["count"]
        top, ntop = min(per.items(), key=lambda kv: (-kv[1], kv[0]))
        if ntop / tot < 0.5 or list(per.values()).count(ntop) > 1:
            return ("?", [])                      # G6: no order covers half of the places
        share = per.get(rule[1], 0) / tot
        if rule[1] == top:
            return ("1", rows)
        return ("0", rows) if share < 0.10 else ("?", [])
    if kind in ("order", "order_clause"):
        if kind == "order":
            rows = sorted(S9.select(T["orders"], rule[2], lex_class), key=lambda r: S9._num(r["id"]))
            b, a = sum(r["before"] for r in rows), sum(r["after"] for r in rows)
            labels = rule[1]
        else:
            rows = sorted((r for r in T["constructions"] if r["level"] == "clause" and r["rule"] in ("S-V", "V-S")),
                          key=lambda r: S9._num(r["id"]))
            b = sum(r["count"] for r in rows if r["rule"] == "S-V")
            a = sum(r["count"] for r in rows if r["rule"] == "V-S")
            labels = {"before": rule[1]["S-V"], "after": rule[1]["V-S"], "both": rule[1]["both"]}
        if b + a < MIN or a == b:
            return ("?", [])                      # G10; on a tie no order is the commonest (G6)
        if min(a, b) / (a + b) < 0.10:
            return (labels["before" if b > a else "after"], rows)
        return (labels["both"], rows)
    old = S9.MIN
    S9.MIN = MIN
    try:
        return S9.answer(rule, T, lex_class)
    finally:
        S9.MIN = old


def build_profile(lang, d, cnt):
    T = {}
    for tb in ("paradigms", "markers", "orders", "agreement", "constructions", "frames"):
        cols = [c for c in pq.read_schema(os.path.join(d, f"{tb}.parquet")).names if c != "places"]
        T[tb] = pq.read_table(os.path.join(d, f"{tb}.parquet"), columns=cols).to_pylist()
    if "marker" in pq.read_schema(os.path.join(d, "markers.parquet")).names:
        for r in T["markers"]:
            r["lexeme"] = r["marker"]       # 1.1 renamed the column (E5); the 1.0 selectors read `lexeme`
    with open(os.path.join(d, "lexemes.tsv"), encoding="utf-8") as fh:
        lex_class = {r["lexeme"]: r["class"] for r in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)}
    for r in T["markers"]:
        if r["lexeme"].startswith("sfx:"):
            lex_class[r["lexeme"]] = "pron"   # E5: a pronoun suffix's marker key; its pieces are of class pron
    with open(os.path.join(d, "categories.toml"), "rb") as fh:
        cats = tomllib.load(fh)
    with open(S9.PARAMS, encoding="utf-8") as fh:
        params = [ln.rstrip("\n").split("\t") for ln in fh if ln.strip() and not ln.startswith("#")]
    if params[0] != ["id", "question"] or len(params) != 196:
        raise SystemExit(f"team_parameters.tsv: header {params[0]}, {len(params) - 1} rows (195 expected)")
    rows, by, how = [], C.Counter(), C.Counter()
    for pid, _question in params[1:]:
        rule = S9.PROFILE.get(pid, {})
        rule = rule.get(lang, rule.get("*"))
        value, ev = answer11(rule, T, lex_class) if rule else ("?", [])
        stmt, count = " ".join(r["id"] for r in ev), " ".join(str(r["count"]) for r in ev)
        nc = NOCODE.get(pid, {})
        nc = nc.get(lang, nc.get("*"))
        if value == "?" and nc:
            tb, cat, code = nc
            sec = cats.get(tb, {}).get(cat)
            if sec and code not in {v["code"] for v in sec["values"]}:
                value, stmt, count = "0", f"categories.toml:{tb}.{cat}", str(sum(v["count"] for v in sec["values"]))
                how["categories.toml (G7)"] += 1
        if value != "?" and not stmt.startswith("categories.toml"):
            how["statement tables"] += 1
        by[value] += 1
        rows.append([pid, value, stmt, count])
    X.write_tsv(os.path.join(d, "profile.tsv"), PROFILE_HEADER, rows)
    cnt[f"{lang} profile answered"] = sum(v for k, v in by.items() if k != "?")
    cnt[f"{lang} profile by value"] = dict(sorted(by.items()))
    cnt[f"{lang} profile answered by evidence"] = dict(sorted(how.items()))
    cnt[f"{lang} profile answered ids"] = " ".join(f"{r[0]}={r[1]}" for r in rows if r[1] != "?")
    return rows


# ---- categories.toml: the shared part --------------------------------------------------------------------------------

def _vals(counter):
    return ["values = ["] + [f"  {{ code = {X.toml_str(k)}, count = {v} }}," for k, v in sorted(counter.items())] + ["]"]


def categories_part(lang, W, P, K, rel_rows, map_rows, facts, prof):
    L = [MARKER, "# D4, D6, the facts of stage 20 and the profile. `count` = rows of the table with the value.", ""]
    L += ["[words.rel_shared]", 'column = "rel_shared"', 'basis = "derived"',
          'source = "rule D4: (rel, class of the stem piece) through relmap.tsv (examples_shared11.RELMAP11)"']
    L += _vals(C.Counter(W["rel_shared"])) + [""]
    L += ["[relmap.shared]", 'column = "shared"', 'basis = "derived"', 'source = "rule D4, the table inside the builder"']
    L += _vals(C.Counter(r[2] for r in rel_rows)) + [""]
    for tb, col in (("pieces", P["shared"]), ("clauses", K["shared"])):
        fv = C.Counter()
        for s, n in C.Counter(col).items():
            for k, v in json.loads(s).items():
                fv[f"{k}={v}"] += n
        L += [f"[{tb}.shared]", 'column = "shared"', 'basis = "derived"',
              f'source = "rule D6: {"marks and class" if tb == "pieces" else "the form categories of marks"} through map.tsv"',
              'pattern = "a JSON object of Universal Dependencies feature -> value; each value below is feature=value"']
        L += _vals(fv) + [""]
    L += ["[map.reason]", 'column = "reason"', 'basis = "derived"',
          'source = "rule D6: why a code maps to none (G1): upos_not_feature, no_ud_feature, no_ud_value, '
          'unknown_value, lexeme_value"']
    L += _vals(C.Counter(r[5] for r in map_rows if r[3] == "none")) + [""]
    L += ["[map.feature]", 'column = "feature"', 'basis = "derived"', 'source = "Universal Dependencies feature names, UPOS"']
    L += _vals(C.Counter(r[3] for r in map_rows)) + [""]
    for col in ("relation", "kind", "source", "method"):
        L += [f"[facts.{col}]", f'column = "{col}"', 'basis = "as the row\'s kind says"',
              f'source = "SPEC 4.8; stages 16, 19, 20"']
        L += _vals(C.Counter(f[col] for f in facts)) + [""]
    L += ["[profile.value]", 'column = "value"', 'basis = "derived"',
          'source = "SPEC 4.10: Grambank codes 0-3 where a count answers, else ?"']
    L += _vals(C.Counter(r[1] for r in prof)) + [""]
    return "\n".join(L)


def write_categories(d, text):
    path = os.path.join(d, "categories.toml")
    with open(path, encoding="utf-8") as fh:
        old = fh.read()
    X.write_text(path, old.split(MARKER)[0].rstrip("\n") + "\n\n" + text)


# ---- sources.json ---------------------------------------------------------------------------------------------------
M = "shoresh/macula/"
ENGLISH_EVIDENCE = ("English translations are evidence here, never a value: Clear's quotation spans projected from "
                    "English translations' quotation marks, the nesting votes of eight English translations and the "
                    "BSB, speaker ids of English labels (Glyssen, Clear), resources/proper_nouns/eng.tsv")


def _sources11():
    keep = {s["key"]: dict(s) for s in RD.SOURCES}
    keep["macula-hebrew"]["reads"] = ("stages 15-19: words, pieces, morphology, classes, roles, clauses, rules, frames, "
                                      "references, the Septuagint word per piece. Not read: sdbh, lexdomain, coredomain, "
                                      "contextualdomain, sensenumber, domain, ln, gloss, english, mandarin, lowfat head")
    keep["macula-hebrew-nodes"]["reads"] = "stages 15, 18: Head of every branching node, morphId, compound StrongNumberX"
    keep["macula-greek"]["reads"] = "stages 15-19 and the Greek speech rebuild; not read: gloss, english, ln, domain, head"
    keep["macula-greek-nodes"]["reads"] = "stages 15, 18: Head of every branching node"
    keep["word-senses-ubs"]["reads"] = "stage 15 (pieces.sense, pieces.domain; UBS's ; becomes a space), stage 20 (facts)"
    keep["clause-layout"]["reads"] = "stage 16 (D9 join, D11 line, D10 join), stage 17 (D15m join)"
    keep["nt-clause-layout"]["reads"] = ("stage 16 (D9, D11; D10: quotation and speaker_id recomputed with no review "
                                         "row), stage 17 (the published layout's speech fields, M4)")
    keep["clause-columns"]["reads"] = "stage 16 (D9: kind, force, interrog, neg, neg_scope, voice, m_trans, subj_form, subj_switch, front)"
    keep["time-aspect"]["reads"] = "stage 16 (D9: time, aspect, band, carried as terms of terms.tsv)"
    keep["connectives"]["reads"] = "stage 16 (D9: conn as lexeme keys; relation carried as terms of terms.tsv)"
    keep["clause-extras"]["reads"] = "stage 16 (D9: polarity)"
    keep["trees-macula"]["reads"] = "stage 16 (D9 rank check), stages 16-17 (the speech rebuilds)"
    keep["speaker-layer-inputs"]["reads"] = ("stage 16 (D10, build_speaker_layer.py --no-review into the build's cache; "
                                             "corrections.tsv and prophets.tsv are hand files, speech_basis derived). "
                                             "Stage 17 reads review.tsv for the M4 columns (model part)")
    keep["speaker-layer-inputs"]["english_evidence"] = ENGLISH_EVIDENCE
    keep["nt-speech-inputs"]["reads"] = "stage 16 (D10, no review row). Stage 17 reads nt_review.tsv (model part)"
    keep["nt-speech-inputs"]["english_evidence"] = ENGLISH_EVIDENCE
    keep["speaker-layer-published"]["reads"] = "stage 16, only to count the difference with the review-free layer"
    keep["acai"]["reads"] = "stage 16 (D7 who, D7n names, participants.tsv, D10 speaker through characters.tsv, kin facts, SE1, SE2)"
    keep["addressees"]["reads"] = "stage 16 (D10 addressee, strict rows), stage 17 (every row, M4)"
    keep["arg-roles"]["reads"] = "stage 16 (D12 sem_role, sem_role_basis)"
    keep["hebrew-greek-cf"]["reads"] = "stage 19 (Septuagint links, rendered_by)"
    keep["glaux-lxx"]["reads"] = "stage 19 (other/lxx/words.parquet; lemma and class are M7, see the model part)"
    keep["compact-alignments"]["reads"] = "stage 19 (links to heb_scg, heb_mod; rendered_by)"
    keep["helloao"]["reads"] = "stage 19 (other/heb_scg, other/heb_mod words)"
    keep["aramaic-hebrew-equivalents"]["reads"] = "stage 20 (equivalent_of; its build.json names no model)"
    keep["grambank-questionnaire"]["reads"] = "stage 20 (profile.tsv: the ids only; the English questions are not carried)"
    out = list(keep.values())
    out.append(dict(key="terms", langs=LANGS, name="the terms of the language for meaning values (master)",
                    repository="bcv-commons/bcv-query (internal-docs/source-examples-spec)", pin="the file as hashed here",
                    licence="CC BY-SA 4.0 (as the example)", licence_from="SPEC 4.10",
                    reads="stage 14 (copied unchanged into each language folder); a model named the terms (named_by), "
                          "unchecked", paths=["internal-docs/source-examples-spec/terms.tsv"]))
    return out


SOURCES11 = _sources11()
EXAMPLE_LICENCE11 = (
    "CC BY-SA 4.0. The tables hold values of CC BY-SA 4.0 sources (UBS senses and domains, ACAI's entities, our clause "
    "columns and argument roles, GLAUx's Septuagint words and the bridge links, the concept datasets), so ShareAlike "
    "holds for the whole. The CC BY 4.0 sources (MACULA, our layouts and speaker layer, hebrew-nt-bridge) ask for "
    "attribution, which `sources` and `model` give. The Hebrew New Testament texts are public domain, the compact "
    "alignments CC0 1.0. Model-made values (basis model) are named in `model`, with no human check.")
NOT_READ11 = ["BHSA and everything derived from it", "TBTA",
              "MACULA's inline sdbh, lexdomain, coredomain, contextualdomain, sensenumber, domain, ln, gloss, english, "
              "mandarin; the lowfat head attribute",
              "the concept definitions of the concept datasets (English)", "the English labels alt_eng",
              "vector tables (-similar), passage moods, commentary terms, phrase types, lexeme-bridge models (SPEC 9)"]


def sources_doc11(lang, d, counts):
    with open(os.path.join(d, "sources.json"), encoding="utf-8") as fh:
        old = json.load(fh)
    srcs = {}
    for s in SOURCES11:
        if lang not in s["langs"]:
            continue
        files = {}
        paths = list(s["paths"])
        if X.V12 and s["key"] == "terms":       # SPEC 1.2, 4.10: terms-notes.md is written and copied with terms.tsv
            paths.append("internal-docs/source-examples-spec/terms-notes.md")
        if X.V13 and s["key"] == "terms":       # SPEC 1.3, 4.10: the sections of the 30 new rows, appended
            paths.append("internal-docs/source-examples-spec/terms-notes-1.3-rows.md")
        for pat in paths:
            got = RD._expand(pat)
            if not got:
                raise SystemExit(f"sources.json: {s['key']}: nothing matches {pat}")
            for label, p in got:
                files[label] = {"bytes": os.path.getsize(p), "sha256": RD._sha(p)}
        entry = {k: s[k] for k in ("name", "repository", "pin", "licence", "licence_from", "reads")}
        if X.V12 and s["key"] == "terms":
            entry["name"] = "the terms of the language for meaning values, and their notes (masters)"
            entry["reads"] = ("stage 23 (sub-stage 14: terms.tsv and terms-notes.md copied unchanged into each language "
                              "folder); a model named the terms (named_by), unchecked; terms-notes.md may hold English "
                              "and is no table (SPEC 4.10)")
        for k in ("method", "english_evidence"):
            if s.get(k):
                entry[k] = s[k]
        entry["files"] = dict(sorted(files.items()))
        srcs[s["key"]] = entry
        counts[f"{lang} sources.json {s['key']} files"] = len(files)
    tracked = set((RD._git("ls-files", "--", "shoresh/macula") or "").split("\n"))
    changed = set((RD._git("diff", "--name-only", "HEAD", "--", "shoresh/macula") or "").split("\n"))
    bfiles = {}
    for pat in RD.BUILDER:
        for p in sorted(__import__("glob").glob(os.path.join(HERE, pat))):
            rel = os.path.relpath(p, ROOT)
            bfiles[rel] = {"sha256": RD._sha(p), "committed": rel in tracked and rel not in changed}
    return {
        "language": lang,
        "builder": {"repository": "bcv-commons/bcv-query", "commit": RD._git("rev-parse", "HEAD"),
                    "note": "the builder files below are those of this build; `committed` = tracked and unchanged against "
                            "`commit` when the build ran", "files": bfiles,
                    "entry": ("shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build j1 --stage 52"
                              if getattr(X, "V18", False) else
                              "shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build h1 --stage 38"
                              if getattr(X, "V16", False) else
                              "shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build g1 --stage 35"
                              if getattr(X, "V15", False) else
                              "shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build f1 --stage 32"
                              if X.V14 else
                              "shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build e1 --stage 28, then "
                              "--stage 29" if X.V13 else
                              "shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build d1 --stage 23, then "
                              "--stage 24" if X.V12 else
                              "shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build c1 --stage 14 ... 20")},
        "python": platform.python_version(), "pyarrow": pa.__version__,
        "specification": {"path": "internal-docs/source-examples-spec/SPEC.md", "version": _ver(), "sha256": RD._sha(SPEC)},
        "sources": srcs, "model": old.get("model", {}), "links": old.get("links", {}),
        "not_read": NOT_READ11, "licence": EXAMPLE_LICENCE11,
    }


# ---- COLUMNS.md -----------------------------------------------------------------------------------------------------

def columns_md11(d, lang):
    st, mod = _doc_stage()
    L = [f"# COLUMNS: `{lang}`", "",
         f"Written by `build_examples.py --stage {st}` (`{mod}`). Part 1 is section 4 of the specification",
         f"(`internal-docs/source-examples-spec/SPEC.md`, version {_ver()}) as it stands. Part 2 lists every table file of this",
         "folder, and the build-level texts this language links to (`../other/<text>/words.parquet`), with their columns",
         "as read from the file: type, rows filled (not null, not empty), distinct values; a column with 40 or fewer",
         "distinct values has them listed with their counts. Codes are declared in `categories.toml`, labels in",
         "`relmap.tsv`, shared features in `map.tsv`, terms in `terms.tsv`.", "", "## Part 1. The specification, section 4", "",
         RD._spec_section4().replace("\n## ", "\n### ").replace("\n### 4.", "\n#### 4."), "## Part 2. The files as built", ""]
    files = sorted(f for f in os.listdir(d) if f.endswith((".parquet", ".tsv")))
    others = [os.path.join("..", "other", o, "words.parquet") for o in OTHER[lang]]
    for f in files + others:
        p = os.path.normpath(os.path.join(d, f))
        n, cols = RD._describe_parquet(p) if f.endswith(".parquet") else RD._describe_tsv(p)
        L += [f"### `{f}`: {n:,} rows, {len(cols)} columns", "", "| column | type | filled | distinct | values (40 or fewer) |",
              "|---|---|---|---|---|"]
        for name, typ, filled, distinct in cols:
            vals = ""
            if len(distinct) <= 40:
                vals = ", ".join(f"`{'' if k is None else k}` {v:,}" for k, v in
                                 sorted(distinct.items(), key=lambda kv: (-kv[1], str(kv[0]))))
                vals = vals.replace("|", "\\|")
            L.append(f"| `{name}` | {typ} | {filled:,} | {len(distinct):,} | {vals} |")
        L.append("")
    if X.V13:
        L += ["- `categories.toml`: the categories and coded columns with their codes, terms, bases, sources and counts "
              "(stage 28)", "- `sources.json`: the sources, their pins, bases and sha256, the model part (stage 28, again at 29)",
              "- `terms-notes.md`: the notes on `terms.tsv` for the scholar (the 1.2 notes with the sections of the 1.3 rows "
              "appended; it may hold English and is no table)",
              "- `READ-FIRST.md`: the reading sheet, with the account of who is meant and what is model (stage 29)",
              "- `VALIDATION.md`: the exit conditions with their counts "
              "(`validate_examples.py --build e1 --upto 29 --compare e2 --write-md`)"]
        return "\n".join(L) + "\n"
    if X.V12:
        L += ["- `categories.toml`: the categories and coded columns with their codes, terms, bases, sources and counts "
              "(stage 23)", "- `sources.json`: the sources, their pins and sha256, the model part (stage 23, again at 24)",
              "- `terms-notes.md`: the notes on `terms.tsv` for the scholar (a copy of the master; it may hold English and "
              "is no table)",
              "- `READ-FIRST.md`: the reading sheet, with what is model (stage 24)",
              "- `VALIDATION.md`: the exit conditions with their counts "
              "(`validate_examples.py --build d1 --upto 24 --compare d2 --write-md`)"]
        return "\n".join(L) + "\n"
    L += ["- `categories.toml`: the categories and coded columns with their codes, terms, bases, sources and counts "
          "(stages 15-20)", "- `sources.json`: the sources, their pins and sha256, the model part (stage 20)",
          "- `READ-FIRST.md`: the reading sheet, with what is model (stage 20)",
          "- `VALIDATION.md`: the exit conditions with their counts (`validate_examples.py --build c1 --upto 20 --write-md`)"]
    return "\n".join(L) + "\n"


# ---- READ-FIRST.md, section 5: what is model ------------------------------------------------------------------------

def _tsv(path):
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    head = lines[0].split("\t")
    return [dict(zip(head, ln.split("\t"))) for ln in lines[1:] if ln]


def model_section(outdir, lang):
    d = os.path.join(outdir, lang)
    P = pq.read_table(os.path.join(d, "pieces.parquet"), columns=["concept", "who_basis"]).to_pydict()
    K = pq.read_table(os.path.join(d, "clauses.parquet"),
                      columns=["quote_model", "speaker_model", "addressee_model", "subject_model"]).to_pydict()
    LK = pq.read_table(os.path.join(d, "links.parquet"), columns=["basis", "agree_model"]).to_pydict()
    LA = pq.read_table(os.path.join(d, "link_account.parquet"), columns=["state", "state_model"]).to_pydict()
    F = pq.read_table(os.path.join(d, "facts.parquet"), columns=["kind"]).column("kind").to_pylist()
    PA = _tsv(os.path.join(d, "participants.tsv"))
    n, nk = len(P["concept"]), len(K["quote_model"])
    pc = lambda x, y: f"{x / y:.3f}" if y else "-"  # noqa: E731
    rows = [
        ("pieces.concept (M1)", sum(v is not None for v in P["concept"]), n, "pieces"),
        ("pieces.who with who_basis model (M2)", sum(v == "model" for v in P["who_basis"]), n, "pieces"),
        ("clauses.quote_model, speaker_model, addressee_model filled (M4)", sum(v is not None for v in K["quote_model"]), nk, "clauses"),
        ("clauses.subject_model (M3)", sum(v is not None for v in K["subject_model"]), nk, "clauses"),
        ("participants with ent_basis model", sum(r["ent_basis"] == "model" for r in PA), len(PA), "participants"),
        ("links with basis model (M5, M7)", sum(v == "model" for v in LK["basis"]), len(LK["basis"]), "links"),
        ("links with agree_model filled (M5)", sum(v is not None for v in LK["agree_model"]), len(LK["basis"]), "links"),
        ("link_account.state_model linked", sum(v == "linked" for v in LA["state_model"]), len(LA["state"]), "(piece, text)"),
        ("facts with kind model (M7)", sum(v == "model" for v in F), len(F), "facts"),
    ]
    if X.V12:       # SPEC 1.2, 4.10: the terms are a model's naming, unchecked
        T = _tsv(os.path.join(d, "terms.tsv"))
        rows.append(("terms.tsv rows whose term a model named (named_by; checked empty)", sum(bool(r["named_by"]) for r in T),
                     len(T), "terms"))
    for o in OTHER[lang]:
        W = pq.read_table(os.path.join(outdir, "other", o, "words.parquet")).to_pydict()
        if o == "lxx":
            rows.append(("other/lxx lemma and class (M7: GLAUx, automatic)", sum(bool(v) for v in W["lemma"]), len(W["s"]), "words"))
        else:
            rows.append((f"other/{o} analysis_basis model (M6: the tagger)", sum(v == "model" for v in W["analysis_basis"]),
                         len(W["s"]), "words"))
    L = ["## 5. What is model, and how much", "",
         "Model-made values have the basis `model` (SPEC 2.2). They stand only in the columns and rows below; the strict",
         "view (every M column emptied, every `model` row removed) is what the statement tables count. Each model source is",
         "named in `sources.json` (`model`) and `categories.toml` with its dataset, version, model(s) and run. No human",
         "check is claimed for any of it.", "", "| what | model | of | share | unit |", "|---|---|---|---|---|"]
    L += [f"| {a} | {b:,} | {c:,} | {pc(b, c)} | {u} |" for a, b, c, u in rows]
    return "\n".join(L) + "\n"


# ---- the glossed chapters (1.1) -------------------------------------------------------------------------------------
CHAPTERS = [("hbo", "GEN", 22, "narrative", "genesis-22"), ("hbo", "PSA", 23, "psalm", "psalm-23"),
            ("hbo", "LEV", 19, "law", "leviticus-19"), ("hbo", "ISA", 40, "prophecy", "isaiah-40"),
            ("arc", "DAN", 3, "Aramaic narrative", "daniel-3-aramaic"), ("grc", "MRK", 4, "gospel narrative", "mark-4"),
            ("grc", "ROM", 8, "letter, argument", "romans-8"), ("grc", "HEB", 1, "letter, exposition", "hebrews-1")]
GLOSS_HEADER = ("| t.n | word | piece | kind | lexeme | class | marks | head | label | shared | clause | part | "
                "participant | concept | model |")
CLAUSE_HEADER = "| clause | key | rule | parent | marks | speech | model |"


def _cell(s):
    return str(s).replace("|", "\\|")


def gloss_chapter(build, lang, book, ch, kind):
    d = os.path.join(build, lang)
    W = [w for w in pq.read_table(os.path.join(d, "words.parquet"),
                                  columns=["t", "book", "chapter", "verse", "text", "clause", "rel_shared"]).to_pylist()
         if w["book"] == book and w["chapter"] == ch]
    ts = {w["t"] for w in W}
    P = C.defaultdict(list)
    for p in pq.read_table(os.path.join(d, "pieces.parquet"),
                           columns=["t", "n", "text", "kind", "lexeme", "class", "marks", "head_t", "head_n", "head_basis",
                                    "rel", "who", "who_basis", "concept"]).to_pylist():
        if p["t"] in ts:
            P[p["t"]].append(p)
    need = {(p["head_t"], p["head_n"]) for ps in P.values() for p in ps}
    text_of = {}
    for other in (["hbo", "arc"] if lang in ("hbo", "arc") else [lang]):
        for p in pq.read_table(os.path.join(build, other, "pieces.parquet"), columns=["t", "n", "text"]).to_pylist():
            if (p["t"], p["n"]) in need:
                text_of[(p["t"], p["n"])] = p["text"]
    KC = {c["clause"]: c for c in pq.read_table(os.path.join(d, "clauses.parquet"),
                                               columns=["clause", "rule", "parent", "book", "chapter", "marks", "quote",
                                                        "speaker", "addressee", "speech_basis", "quote_model",
                                                        "speaker_model", "addressee_model", "subject_model"]).to_pylist()
          if c["book"] == book and c["chapter"] == ch}
    part = {}
    for r in pq.read_table(os.path.join(d, "constituents.parquet"),
                           columns=["clause", "role", "head", "sem_role", "sem_role_basis"]).to_pylist():
        if r["clause"] in KC and r["head"] in ts:
            s = r["role"] + (f" {r['sem_role']}" if r["sem_role"] else "") + (" (linked)" if r["sem_role_basis"] == "linked" else "")
            part.setdefault(r["head"], []).append(s)
    name = {r["ent"]: r["name"] for r in _tsv(os.path.join(d, "participants.tsv"))}

    def ents(v):
        return " ".join(f"`{e}`" + (f" {name[e]}" if name.get(e) else "") for e in (v or "").split())
    out = [f"# {book} {ch} ({lang}, {kind}): the tables, piece by piece", "",
           f"Written by `build_examples.py --stage {_doc_stage()[0]}` (`examples_shared11.py`) from the source examples "
           f"(SPEC {_ver()}). One",
           "table per verse, one row per piece (`pieces.parquet`). `marks`: the piece's codes; `head`: the piece it depends",
           "on as `t.n` and its letters (`root` for the root), with `head_basis` where it is not `index`; `label`:",
           "`pieces.rel`; `shared`: the word's `rel_shared` (on its first piece); `clause`: the word's innermost clause,",
           "numbered in the verse; `part`: on the head word of a constituent, its role code and its semantic role as a term",
           "of the language (`(linked)` where placed through the Septuagint); `participant`: `pieces.who` with the name",
           "`participants.tsv` gives; `concept`: the concept code a model chose (M1). `model` names every value of the",
           "row that is model-made. Under each verse its clauses: the meaning values of `marks` are terms of the language;",
           "`speech` is the strict quotation, speaker and addressee; `model` the reviewed layers' values (M4) and the",
           "model's subject (M3); the clause's values are separated by `; `. No gloss: nothing English is read.", ""]
    nverse = npiece = 0
    for v in sorted({w["verse"] for w in W}):
        ws = sorted((w for w in W if w["verse"] == v), key=lambda w: w["t"])
        nverse += 1
        order = []
        for w in ws:
            if w["clause"] and w["clause"] not in order:
                order.append(w["clause"])
        num = {c: i + 1 for i, c in enumerate(order)}
        out += [f"## {book} {ch}:{v}", "", GLOSS_HEADER, "|" + "---|" * 15]
        for w in ws:
            for i, p in enumerate(sorted(P[w["t"]], key=lambda p: p["n"])):
                npiece += 1
                m = json.loads(p["marks"])
                marks = " ".join(f"{k}={m[k]}" for k in sorted(m))
                if p["head_basis"] == "root":
                    head = "root"
                else:
                    head = f"{p['head_t']}.{p['head_n']} {text_of.get((p['head_t'], p['head_n']), '?')}"
                    if p["head_basis"] != "index":
                        head += f" ({p['head_basis']})"
                cl = f"{num[w['clause']]}" if (w["clause"] and i == 0) else ""
                pt = "; ".join(part.get(w["t"], [])) if p["kind"] == "stem" else ""
                model = []
                if p["who_basis"] == "model":
                    model.append("participant")
                if p["concept"] is not None:
                    model.append("concept")
                out.append("| " + " | ".join(_cell(x) for x in [
                    f"{p['t']}.{p['n']}", w["text"] if i == 0 else "", p["text"], p["kind"], p["lexeme"], p["class"],
                    marks, head, p["rel"], w["rel_shared"] if i == 0 else "", cl, pt,
                    ents(p["who"]) + (f" ({p['who_basis']})" if p["who"] else ""),
                    "" if p["concept"] is None else p["concept"], " ".join(model)]) + " |")
        out += ["", CLAUSE_HEADER, "|---|---|---|---|---|---|---|"]
        for c in order:
            k = KC.get(c, {})
            mk = json.loads(k["marks"]) if k.get("marks") else {}
            marks = "; ".join(f"{a}={X.jdump(b) if isinstance(b, list) else b}" for a, b in sorted(mk.items()))
            speech = ""
            if k.get("quote"):
                speech = f"`{k['quote']}` " + ents(k["speaker"]) + (f" → {ents(k['addressee'])}" if k["addressee"] else "") \
                         + f" ({k['speech_basis']})"
            mod = []
            if k.get("quote_model") is not None:
                mod.append(f"quote `{k['quote_model'] or '-'}` {ents(k['speaker_model']) or '-'} → "
                           f"{ents(k['addressee_model']) or '-'} (model)")
            if k.get("subject_model") is not None:
                mod.append(f"subject {k['subject_model']} (model)")
            out.append("| " + " | ".join(_cell(x) for x in [num[c], f"`{c}`", k.get("rule", "?"),
                                                          f"`{k['parent']}`" if k.get("parent") else "", marks, speech,
                                                          "; ".join(mod)]) + " |")
        out.append("")
    return "\n".join(out), nverse, npiece


def glossed_all(build, outdir, counts):
    for lang, book, ch, kind, fname in CHAPTERS:
        text, nv, npc = gloss_chapter(build, lang, book, ch, kind)
        X.write_text(os.path.join(outdir, fname + ".md"), text)
        counts[f"glossed {lang} {book} {ch}"] = f"{nv} verses, {npc} pieces"


# ---- the stage ------------------------------------------------------------------------------------------------------

def _read(path):
    t = pq.read_table(path)
    return t.to_pydict(), t.schema


def build(outdir, langs, counts):
    if set(langs) != set(LANGS):
        raise SystemExit("stage 20 builds hbo, arc and grc together")
    ex = C.defaultdict(list)
    hbo_lex = None
    for lang in LANGS:
        d = os.path.join(outdir, lang)
        W, Ws = _read(os.path.join(d, "words.parquet"))
        P, Ps = _read(os.path.join(d, "pieces.parquet"))
        K, Ks = _read(os.path.join(d, "clauses.parquet"))
        rel_rows = build_relmap(lang, W, P, counts, K)
        X.write_tsv(os.path.join(d, "relmap.tsv"), ["label", "class", "shared", "count"], rel_rows)
        X.write_parquet(os.path.join(d, "words.parquet"), W, Ws)
        tc = term_codes(d)
        map_rows = build_map(lang, P, K, tc, counts)
        for r in map_rows:
            if r[3] == "none":
                ex[f"{lang} map: codes with no shared feature"].append(f"{r[0]}.{r[1]}={r[2]} ({r[5]}) {r[6]}")
        X.write_tsv(os.path.join(d, "map.tsv"), S9.MAP_HEADER, map_rows)
        memo_p, memo_k = {}, {}
        P["shared"] = [shared_of(lang, "pieces", m, c, tc, memo_p) for m, c in zip(P["marks"], P["class"])]
        K["shared"] = [shared_of(lang, "clauses", m, None, tc, memo_k) for m in K["marks"]]
        counts[f"{lang} pieces with a shared feature"] = sum(1 for s in P["shared"] if s != "{}")
        counts[f"{lang} pieces with UPOS"] = sum(1 for s in P["shared"] if '"UPOS"' in s)
        counts[f"{lang} clauses with a shared feature"] = sum(1 for s in K["shared"] if s != "{}")
        X.write_parquet(os.path.join(d, "pieces.parquet"), P, Ps)
        X.write_parquet(os.path.join(d, "clauses.parquet"), K, Ks)
        new = S9.piece_facts(lang, P)
        if lang == "arc":
            if hbo_lex is None:
                with open(os.path.join(outdir, "hbo", "lexemes.tsv"), encoding="utf-8") as fh:
                    hbo_lex = list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))
            new += S9.equivalent_facts(P, hbo_lex, counts, ex)
        S9.write_facts(d, lang, new, counts)
        counts.pop(f"{lang} facts rows kept (stages 06, 08)", None)
        facts = pq.read_table(os.path.join(d, "facts.parquet"), columns=["relation", "kind", "source", "method"]).to_pylist()
        counts[f"{lang} facts rows kept (stages 16, 19)"] = sum(1 for f in facts if f["relation"] not in S20_RELATIONS)
        prof = build_profile(lang, d, counts)
        write_categories(d, categories_part(lang, W, P, K, rel_rows, map_rows, facts, prof))
        doc = sources_doc11(lang, d, counts)
        X.write_text(os.path.join(d, "sources.json"), json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        counts[f"{lang} sources"] = len(doc["sources"])
        counts[f"{lang} model sources"] = len(doc["model"])
        counts[f"{lang} files hashed"] = sum(len(s["files"]) for s in doc["sources"].values())
        unc = [k for k, v in doc["builder"]["files"].items() if not v["committed"]]
        if unc:
            ex[f"{lang} builder files not committed when built"] = unc
    if X.V12:       # SPEC 1.2 section 14: COLUMNS.md, READ-FIRST.md and the glossed chapters are stage 24's
        counts["sources read"] = {"aramaic-hebrew-equivalents v0.1.1 data/words.parquet": S9.EQUIV_SHA,
                                  "team_parameters.tsv": S9.sha256(S9.PARAMS)}
        return dict(ex)
    write_docs(outdir, counts)
    counts["sources read"] = {"aramaic-hebrew-equivalents v0.1.1 data/words.parquet": S9.EQUIV_SHA,
                              "team_parameters.tsv": S9.sha256(S9.PARAMS)}
    return dict(ex)


def write_docs(outdir, counts):
    """COLUMNS.md, READ-FIRST.md per language and the glossed chapters (stage 20 of a c build; stage 24 of a d build)."""
    for lang in LANGS:
        d = os.path.join(outdir, lang)
        X.write_text(os.path.join(d, "COLUMNS.md"), columns_md11(d, lang))
        sheet = examples_read_sheet.sheet(d, lang).replace("SPEC 1.0", "SPEC 1.2" if X.V12 else "SPEC 1.1")
        # Stage 21: the sheet of a 1.1 build names this stage and the 1.1 chapters (SPEC 1.1, stage 20 row:
        # glossed-c1), not stage 10 and the 1.0 chapters in glossed/. The text is the same for every build, so a
        # rebuild stays byte-equal.
        old_head = ("Written by `build_examples.py --stage 10` (`examples_read_sheet.py`) from this folder's tables.",
                    "(`internal-docs/source-examples-work/glossed/`).")
        st, mod = _doc_stage()
        gname = "glossed-d1" if X.V12 else "glossed-c1"
        new_head = (f"Written by `build_examples.py --stage {st}` (`examples_read_sheet.py`, `{mod}`) from "
                    "this folder's tables.",
                    f"(`internal-docs/source-examples-work/{gname}/`, the chapters of build `{gname[-2:]}`; a rebuild writes "
                    "the same chapters into its `cache/glossed/`).")
        for o, n in zip(old_head, new_head):
            if sheet.count(o) != 1:
                raise SystemExit(f"stage {st}: the reading sheet's head has changed; cannot find {o!r}")
            sheet = sheet.replace(o, n)
        X.write_text(os.path.join(d, "READ-FIRST.md"), sheet.rstrip("\n") + "\n\n" + model_section(outdir, lang))
    gl = glossed_dir(outdir)
    glossed_all(outdir, gl, counts)
    counts["glossed folder"] = os.path.relpath(gl, ROOT)
