"""Stage 20 of the validator (SPEC 1.1, section 14: shared-reading): relmap, map, shared, the facts of stage 20,
profile, sources.json, COLUMNS.md, READ-FIRST.md, the glossed chapters, no English, rebuild.

Called by validate_examples.py (stage 20), which passes itself as `V` for its own readers (_s9_tsv, _s9_equiv, the
gloss vocabulary, S9_UD, UD_RELATIONS). Imports no builder; reads nothing from a build's cache/.
"""
import collections as C
import glob
import hashlib
import json
import os
import re
import tomllib
import unicodedata as U

import pyarrow
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LANGS = ("hbo", "arc", "grc")
OTHER = {"hbo": ["lxx"], "arc": ["lxx"], "grc": ["heb_mod", "heb_scg"]}
MEANING = ("relation", "time", "aspect", "line_kind")
V15 = False   # SPEC 1.5 (g builds): the specification version, the glossed chapters of g1
V16 = False   # SPEC 1.6 (h builds)
COPIED = False   # SPEC 1.7 (i builds): hbo, arc, grc are h1's files byte for byte (section 13; stage 49 checks the sha256);
#                  their declarations name SPEC 1.6 and h1's builder, so they are read against SPEC-v1.6.md, and the builder
#                  files stage 49 changed (COPIED_CHANGED) are named, not failed
COPIED_CHANGED = ("shoresh/macula/build_examples.py",)
V14 = False   # SPEC 1.4 (f builds): equivalent_of is one row per (subject, object, kind), kind by D24a (stage 32 checks it)
V13 = False   # SPEC 1.3 (e builds): mood is a meaning category of clauses; the new coded columns have map.tsv rows
UPOS = {"ADJ", "ADP", "ADV", "AUX", "CCONJ", "DET", "INTJ", "NOUN", "NUM", "PART", "PRON", "PROPN", "PUNCT", "SCONJ",
        "SYM", "VERB", "X"}
GLOSSED_C1 = os.path.join(ROOT, "internal-docs/source-examples-work/glossed-c1")
GLOSSED_D1 = os.path.join(ROOT, "internal-docs/source-examples-work/glossed-d1")     # SPEC 1.2, stage 24
GLOSSED_E1 = os.path.join(ROOT, "internal-docs/source-examples-work/glossed-e1")     # SPEC 1.3, stage 29
TERMS_NOTES = os.path.join(ROOT, "internal-docs/source-examples-spec/terms-notes.md")
CHAPTERS = [("hbo", "GEN", 22, "genesis-22"), ("hbo", "PSA", 23, "psalm-23"), ("hbo", "LEV", 19, "leviticus-19"),
            ("hbo", "ISA", 40, "isaiah-40"), ("arc", "DAN", 3, "daniel-3-aramaic"), ("grc", "MRK", 4, "mark-4"),
            ("grc", "ROM", 8, "romans-8"), ("grc", "HEB", 1, "hebrews-1")]
_ST = ["id"]
SPEC_COLS = {   # SPEC 1.1 section 4: the column lists, in order
    "words.parquet": ["t", "id", "book", "chapter", "verse", "w", "text", "after", "sentence", "clause", "head",
                      "head_basis", "rel", "rel_shared"],
    "pieces.parquet": ["t", "n", "pid", "text", "kind", "lexeme", "class", "marks", "fused", "head_t", "head_n",
                       "head_basis", "rel", "who", "who_basis", "sense", "domain", "shared", "concept", "concept_by"],
    "clauses.parquet": ["clause", "book", "chapter", "verse", "first", "last", "gaps", "words", "parent", "depth", "via",
                        "rule", "pattern", "role", "role_wrapped", "pred", "pred_kind", "marks", "shared", "quote",
                        "speaker", "addressee", "speech_basis", "line", "quote_model", "speaker_model",
                        "addressee_model", "subject_model"],
    "constituents.parquet": ["clause", "ord", "role", "head", "first", "last", "class", "frame_role", "sem_role",
                             "sem_role_basis", "prep"],
    "participants.tsv": ["ent", "type", "name", "name_basis", "sex", "words", "words_model", "ent_basis"],
    "lexemes.tsv": ["lexeme", "lemma", "strong", "class", "count", "forms", "books", "senses", "domains", "first"],
    "forms.parquet": _ST + ["lexeme", "marks", "form", "count", "against", "places"],
    "paradigms.parquet": _ST + ["class", "marks", "lexemes", "forms", "count", "against", "places"],
    "markers.parquet": _ST + ["marker", "kind", "category", "value", "count", "against", "places"],
    "constructions.parquet": _ST + ["level", "rule", "children", "head_at", "count", "against", "places"],
    "orders.parquet": _ST + ["rel", "head_class", "dep_class", "before", "after", "count", "against", "places"],
    "agreement.parquet": _ST + ["rel", "category", "agree", "differ", "n_a", "count", "against", "places"],
    "frames.parquet": _ST + ["lexeme", "stem", "frame", "count", "against", "places"],
    "pairs.parquet": _ST + ["head", "rel", "dep", "count", "against", "places"],
    "clause_links.parquet": _ST + ["kind", "connective", "parent_kind", "role", "count", "against", "places"],
    "exceptions.parquet": ["statement", "place"],
    "facts.parquet": ["subject", "relation", "object", "kind", "method", "source", "confidence", "count", "share", "tier"],
    "links.parquet": ["t", "n", "other", "s", "how", "agree", "basis", "agree_model"],
    "link_account.parquet": ["t", "n", "other", "state", "reason", "state_model"],
    "map.tsv": ["table", "category", "code", "feature", "value", "reason", "count"],
    "relmap.tsv": ["label", "class", "shared", "count"],
    "profile.tsv": ["id", "value", "statement", "count"],
    "terms.tsv": ["category", "code", "hbo", "grc", "from_hbo", "from_grc", "source_hbo", "source_grc", "note",
                  "named_by", "checked"],
    "source_errors.tsv": ["rule", "source", "place", "value", "count"],
    "../other/lxx/words.parquet": ["s", "id", "book", "chapter", "verse", "w", "text", "lemma", "class"],
    "../other/heb_scg/words.parquet": ["s", "id", "book", "chapter", "verse", "w", "text", "lemma", "class", "analysis",
                                       "analysis_basis"],
    "../other/heb_mod/words.parquet": ["s", "id", "book", "chapter", "verse", "w", "text", "lemma", "class", "analysis",
                                       "analysis_basis"],
}
SCRIPT_COLS = {"words.parquet": ["text", "after"], "pieces.parquet": ["text"], "lexemes.tsv": ["lemma"],
               "participants.tsv": ["name"], "forms.parquet": ["form"], "terms.tsv": ["hbo", "grc"],
               "../other/lxx/words.parquet": ["text", "lemma"], "../other/heb_scg/words.parquet": ["text"],
               "../other/heb_mod/words.parquet": ["text"]}
# columns whose values hold words of the source's own description of a term (SPEC 4.10 `note`): checked by the gloss
# check like every column, and listed apart (for the specification)
NOTE_COLS = {("terms.tsv", "note"), ("terms.tsv", "source_hbo"), ("terms.tsv", "source_grc")}
HMARK = re.compile(r"^\((I|II|III|IV|V)\)$")
HOMOGRAPH = re.compile(r" \((I|II|III|IV|V)\)$")


V12 = False          # set by validate_examples.py for a d build (SPEC 1.2)
UPTO = "20"          # set by validate_examples.py


V18 = False   # SPEC 1.8 (j builds, stage 52): the declarations name 1.8 and SPEC.md (set by validate_examples.py)


def ver():
    return "1.8" if V18 else "1.6" if V16 else "1.5" if V15 else "1.3" if V13 else "1.2" if V12 else "1.1"


def spec_cols():
    """SPEC section 4's column lists of the build's version: 1.2 drops terms.tsv `note` (to terms-notes.md)."""
    if not V12:
        return SPEC_COLS
    out = dict(SPEC_COLS)
    out["terms.tsv"] = [c for c in SPEC_COLS["terms.tsv"] if c != "note"]
    if V13:     # SPEC 1.3: the column lists of the tables with a section of their own, read from SPEC.md section 4
        out.update(spec_section_cols())
    return out


def spec_section_cols():
    """The column lists SPEC.md section 4 gives in the tables of its sections `4.N `<file>``: every backticked name of
    a row's first cell, in order (the statement tables and facts.parquet have no such table)."""
    with open(os.path.join(ROOT, "internal-docs/source-examples-spec/SPEC.md"), encoding="utf-8") as fh:
        spec = fh.read()
    sec = spec[spec.index("## 4. The tables"):spec.index("## 5. Sources")]
    out = {}
    for part in re.split(r"\n### ", sec)[1:]:
        m = re.match(r"4\.\d+ `([^`]+\.(?:parquet|tsv))`", part)
        if not m or m.group(1) == "facts.parquet":
            continue
        cols = []
        for ln in part.split("\n"):
            if ln.startswith("| `"):
                cols += re.findall(r"`([^`]+)`", ln.split("|")[1])
        out[m.group(1)] = cols
    return out


def glossed_dir(build):
    base = os.path.basename(os.path.normpath(build))
    return {"c1": GLOSSED_C1, "d1": GLOSSED_D1, "e1": GLOSSED_E1,
            "g1": os.path.join(ROOT, "internal-docs/source-examples-work/glossed-g1"),
            "h1": os.path.join(ROOT, "internal-docs/source-examples-work/glossed-h1"),
            "i1": os.path.join(ROOT, "internal-docs/source-examples-work/glossed-h1")}.get(   # SPEC 1.7: i1's Tanakh and Greek are h1's
        base, os.path.join(build, "cache", "glossed"))


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def table(path):
    if path.endswith(".parquet"):
        t = pq.read_table(path)
        return t.column_names, {c: t.column(c).to_pylist() for c in t.column_names}, t.num_rows
    with open(path, encoding="utf-8", newline="") as fh:
        lines = fh.read().split("\n")
    head = lines[0].split("\t")
    rows = [ln.split("\t") for ln in lines[1:] if ln]
    return head, {c: [r[i] for r in rows] for i, c in enumerate(head)}, len(rows)


def files_of(d, lang):
    return sorted(f for f in os.listdir(d) if f.endswith((".parquet", ".tsv"))) + \
        [f"../other/{o}/words.parquet" for o in OTHER[lang]]


def letters_ok(s):
    for ch in s:
        cp = ord(ch)
        if 0x0590 <= cp <= 0x05FF or 0xFB1D <= cp <= 0xFB4F or 0x0370 <= cp <= 0x03FF or 0x1F00 <= cp <= 0x1FFF:
            continue
        if 0x0300 <= cp <= 0x036F or cp == 0x02B9:
            continue
        if U.category(ch)[0] in "PZ":
            continue
        return False
    return True


# ---- relmap, map, shared, facts, profile ---------------------------------------------------------------------------

def check_shared(R, V, build, lang, cats):
    d = os.path.join(build, lang)
    W = pq.read_table(os.path.join(d, "words.parquet"), columns=["t", "rel", "rel_shared", "head"]).to_pydict()
    P = pq.read_table(os.path.join(d, "pieces.parquet"),
                      columns=["t", "pid", "kind", "lexeme", "class", "marks", "sense", "domain", "shared"]).to_pydict()
    K = pq.read_table(os.path.join(d, "clauses.parquet"), columns=["marks", "shared", "pred"]).to_pydict()
    cls = {t: c for t, k, c in zip(P["t"], P["kind"], P["class"]) if k == "stem"}
    if V12 and lang != "grc":       # SPEC 1.2 D4: a verb word that is no clause's pred is verb_nonpred in relmap.tsv
        preds = set(K["pred"]) - {0}
        cls = {t: ("verb_nonpred" if c == "verb" and t not in preds else c) for t, c in cls.items()}
        mv = C.Counter(r for t, r in zip(W["t"], W["rel"]) if cls[t] == "verb_nonpred")
        R.info(f"{lang} D4 words of class verb_nonpred, by label pp / adv / all (c1 counts: hbo 457 / 597, arc 3 / 3)",
               f"{mv['pp']} / {mv['adv']} / {sum(mv.values())}")
    # -- relmap.tsv (D4)
    head, rows, n = table(os.path.join(d, "relmap.tsv"))
    R.check(f"{lang} relmap.tsv: columns label, class, shared, count", head == ["label", "class", "shared", "count"], head)
    rmap = {(a, b): (s, int(c)) for a, b, s, c in zip(rows["label"], rows["class"], rows["shared"], rows["count"])}
    pairs = C.Counter((r, cls[t]) for t, r in zip(W["t"], W["rel"]))
    R.check(f"{lang} relmap.tsv: one row per (label, class of the stem piece) of the words, count = words",
            len(rmap) == n and {k: v[1] for k, v in rmap.items()} == dict(pairs), f"{n} rows, {len(pairs)} pairs")
    nw = len(W["t"])
    big = [k for k, v in pairs.items() if v >= 0.001 * nw]
    unm = [k for k in big if rmap.get(k, ("none",))[0] == "none"]
    R.check(f"{lang} relmap.tsv: every pair covering at least 0.1% of the words is mapped (D4)", not unm,
            f"{len(big)} pairs, {len(unm)} none {unm[:5]}")
    bad = [s for s, _ in rmap.values() if s != "none" and s not in V.UD_RELATIONS]
    R.check(f"{lang} relmap.tsv: every shared name is a Universal Dependencies relation or none", not bad, bad[:5])
    bad = sum(1 for t, r, s in zip(W["t"], W["rel"], W["rel_shared"]) if rmap.get((r, cls[t]), (None,))[0] != s)
    R.check(f"{lang} words: rel_shared = (rel, class) read through relmap.tsv", bad == 0, bad)
    bad = sum(1 for h, r, s in zip(W["head"], W["rel"], W["rel_shared"]) if (h == 0) != (s == "root"))
    R.check(f"{lang} words: rel_shared root exactly on the roots", bad == 0, bad)
    nn = sum(1 for s in W["rel_shared"] if s == "none")
    nd = sum(1 for s in W["rel_shared"] if s == "dep")
    R.info(f"{lang} words with rel_shared none / dep (D4 reports both)", f"{nn:,} ({nn / nw:.2%}) / {nd:,} ({nd / nw:.2%})")
    # -- map.tsv (D6, G1, G2, G3)
    head, mrows, _ = table(os.path.join(d, "map.tsv"))
    R.check(f"{lang} map.tsv: columns {' '.join(SPEC_COLS['map.tsv'])}", head == SPEC_COLS["map.tsv"], head)
    mrows = [dict(zip(head, x)) for x in zip(*[mrows[c] for c in head])]
    t2c = {cat: {v["term"]: v["code"] for v in cats["clauses"][cat]["values"]}
           for cat in MEANING + (("mood", "time_abs") if V13 else ()) if cat in cats.get("clauses", {})}

    def codes(tb, mj, c):
        out = {("class", c)} if tb == "pieces" else set()
        for cat, v in (json.loads(mj).items() if mj else []):
            for x in (v if isinstance(v, list) else [v]):
                out.add((cat, t2c[cat][x] if tb == "clauses" and cat in t2c else x))  # 1.3: Greek pieces have a mood too
        return out
    use = C.Counter()
    for (mj, c), k in C.Counter(zip(P["marks"], P["class"])).items():
        for cat, code in codes("pieces", mj, c):
            use[("pieces", cat, code)] += k
    for mj, k in C.Counter(K["marks"]).items():
        for cat, code in codes("clauses", mj, None):
            use[("clauses", cat, code)] += k
    if V13:   # SPEC 1.3 13: the new meaning columns (term -> code) and ref_form, added.form
        def t2(tb, cat):
            return {v["term"]: v["code"] for v in cats.get(tb, {}).get(cat, {}).get("values", [])}
        P13 = pq.read_table(os.path.join(d, "pieces.parquet"), columns=["clusivity", "noun_rel"]).to_pydict()
        N13 = pq.read_table(os.path.join(d, "constituents.parquet"), columns=["ref_status", "ref_form"]).to_pydict()
        A13 = pq.read_table(os.path.join(d, "added.parquet"), columns=["kind", "form"]).to_pydict()
        for tb, cat, col, conv in (("pieces", "clusivity", P13["clusivity"], t2("pieces", "clusivity")),
                                   ("pieces", "noun_rel", P13["noun_rel"], t2("pieces", "noun_rel")),
                                   ("constituents", "ref_status", N13["ref_status"], t2("constituents", "ref_status")),
                                   ("constituents", "ref_form", N13["ref_form"], None),
                                   ("added", "kind", A13["kind"], t2("added", "kind")), ("added", "form", A13["form"], None)):
            for v in col:
                if v:
                    use[(tb, cat, conv.get(v, "NO CODE " + v) if conv is not None else v)] += 1
    by = C.defaultdict(list)
    for r in mrows:
        by[(r["table"], r["category"], r["code"])].append(r)
    R.check(f"{lang} map.tsv: every code of pieces.class, pieces.marks and clauses.marks has a row (mapped or none)",
            set(use) <= set(by), f"{len(use)} codes, {len(set(use) - set(by))} without")
    R.check(f"{lang} map.tsv: no row for a code that does not occur", set(by) <= set(use), len(set(by) - set(use)))
    declared = {(tb, cat, v["code"]) for tb in ("pieces", "clauses") + (("constituents", "added") if V13 else ())
                for cat, sec in cats.get(tb, {}).items()
                for v in sec.get("values", []) if "code" in v}
    R.check(f"{lang} map.tsv: every code is declared in categories.toml", set(by) <= declared,
            sorted(set(by) - declared)[:5])
    clsc = {k[2] for k in use if k[:2] == ("pieces", "class")}
    R.check(f"{lang} map.tsv: every class code has a UPOS row or none (G2)",
            all(by[("pieces", "class", c)][0]["feature"] in ("UPOS", "none") for c in clsc), f"{len(clsc)} codes")
    bad_none = sum(1 for rs in by.values() if any(r["feature"] == "none" for r in rs)
                   and (len(rs) != 1 or rs[0]["value"] or rs[0]["reason"] not in V.S9_REASONS | ({"reading"} if V12 else set())
                                         | ({"realisation_not_a_feature"} if V13 else set())))
    R.check(f"{lang} map.tsv: a none row stands alone, has no value and one of the {'six' if V12 else 'five'} reasons (G1)", bad_none == 0, bad_none)
    if V12:
        rd = [k for k, rs in by.items() if k[0] == "clauses" and (k[1] in ("relation", "time", "aspect", "line_kind")
                                                                 + (("mood", "time_abs") if V13 else ())
                                                                 or (k[1] == "voice" and lang != "grc"))]
        badr = [k for k in rd if not (len(by[k]) == 1 and by[k][0]["reason"] == "reading")]
        R.check(f"{lang} map.tsv: meaning categories{' and the clause voice' if lang != 'grc' else ''} map to none with "
                "the reason reading (SPEC 1.2, 4.10)", not badr, f"{len(rd)} codes; {badr[:5]}")

    def ud_ok(f, v):
        if f == "UPOS":
            return v in UPOS
        return V._s9_ud_ok(f, v)
    bad = [f"{r['feature']}={r['value']}" for r in mrows if r["feature"] != "none" and (not ud_ok(r["feature"], r["value"])
                                                                                       or r["reason"])]
    R.check(f"{lang} map.tsv: every mapped row names a UD feature (or UPOS) and value, no reason", not bad, bad[:5])
    reading = [k for k in by if k[0] == "clauses" and (k[1] in MEANING or (k[1] == "voice" and lang != "grc"))]
    bad = [k for k in reading if by[k][0]["feature"] != "none"]
    R.check(f"{lang} map.tsv: readings and meaning categories map to none (G3; Hebrew clause voice is a reading)",
            not bad, f"{len(reading)} codes; {bad[:3]}")
    badc = sum(1 for r in mrows if int(r["count"]) != use.get((r["table"], r["category"], r["code"]), -1))
    R.check(f"{lang} map.tsv: every count equals the recount", badc == 0, badc)
    srt = [(r["table"], r["category"], r["code"], r["feature"]) for r in mrows]
    R.check(f"{lang} map.tsv: rows sorted by table, category, code, feature", srt == sorted(srt))
    nones = [k for k, rs in by.items() if rs[0]["feature"] == "none"]
    R.info(f"{lang} map.tsv codes / mapped / none, by reason", f"{len(by)} / {len(by) - len(nones)} / {len(nones)} "
           f"{dict(sorted(C.Counter(by[k][0]['reason'] for k in nones).items()))}")
    feats = {k: {r["feature"]: r["value"] for r in rs if r["feature"] != "none"} for k, rs in by.items()}
    for tb, D_ in (("pieces", P), ("clauses", K)):
        memo, bad, nulls = {}, 0, 0
        cl = D_["class"] if tb == "pieces" else [None] * len(D_["marks"])
        for mj, c, s in zip(D_["marks"], cl, D_["shared"]):
            if s is None:
                nulls += 1
                continue
            key = (mj, c)
            if key not in memo:
                out = {}
                for cat, code in sorted(codes(tb, mj, c)):
                    out.update(feats.get((tb, cat, code), {}))
                memo[key] = json.dumps(out, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            bad += memo[key] != s
        R.check(f"{lang} {tb}: shared filled on every row", nulls == 0, nulls)
        R.check(f"{lang} {tb}: shared = {'marks and class' if tb == 'pieces' else 'marks'} read through map.tsv (D6)",
                bad == 0, bad)
    npu = sum(1 for s in P["shared"] if '"UPOS"' in (s or ""))
    R.info(f"{lang} pieces with UPOS", f"{npu:,} of {len(P['shared']):,}")
    # -- facts: has_class, in_domain, sense_of, equivalent_of
    F = pq.read_table(os.path.join(d, "facts.parquet")).to_pylist()
    keys = [(f["subject"], f["relation"], f["object"]) + ((f["kind"],) if V14 else ()) for f in F]
    R.check(f"{lang} facts: sorted by (subject, relation, object{', kind' if V14 else ''}), each once",
            keys == sorted(keys) and len(set(keys)) == len(keys), len(keys))
    nlex = C.Counter(P["lexeme"])
    want = C.Counter()
    for lx, c, dm, sn in zip(P["lexeme"], P["class"], P["domain"], P["sense"]):
        want[(lx, "has_class", c)] += 1
        for code in set((dm or "").split()):
            want[(lx, "in_domain", code)] += 1
        if sn:
            want[(sn, "sense_of", lx)] += 1
    got = {(f["subject"], f["relation"], f["object"]): f for f in F if f["relation"] in V.S9_RELATIONS[:3]}
    src_hc = "macula-greek" if lang == "grc" else "macula-hebrew"
    bad = 0
    for k, n_ in want.items():
        f = got.get(k)
        share = None if k[1] == "sense_of" else n_ / nlex[k[0]]
        if f is None or f["count"] != n_ or f["kind"] != "given" or f["confidence"] is not None or f["tier"] != "" \
                or f["source"] != (src_hc if k[1] == "has_class" else "word-senses-ubs") \
                or (share is None) != (f["share"] is None) or (share is not None and abs(f["share"] - share) > 1e-12):
            bad += 1
    R.check(f"{lang} facts: has_class, in_domain, sense_of equal the recount from pieces (G9: sense_of share empty)",
            bad == 0 and len(got) == len(want), f"{len(got)} rows, recount {len(want)}, {bad} differ")
    eq = [f for f in F if f["relation"] == "equivalent_of"]
    if lang == "arc":
        _, hbo_lex = V._s9_tsv(os.path.join(build, "hbo", "lexemes.tsv"))
        h, want_eq = V._s9_equiv(P, hbo_lex)
        R.check("arc aramaic-hebrew-equivalents words.parquet: sha256 as pinned", h == V.S9_EQUIV_SHA, h[:12])
        if V14:   # SPEC 1.4 D24a: rows per kind; here their sum per (subject, object); stage 32 recounts each kind
            ge = {}
            for f in eq:
                g_ = ge.setdefault((f["subject"], f["object"]), {"count": 0, "share": 0.0, "kind": "linked"})
                g_["count"] += f["count"]
                g_["share"] += f["share"]
                if f["kind"] not in ("derived", "model"):
                    g_["kind"] = "bad"
        else:
            ge = {(f["subject"], f["object"]): f for f in eq}
        bad = sum(1 for k, n_ in want_eq.items() if k not in ge or ge[k]["count"] != n_ or ge[k]["kind"] != "linked"
                  or abs(ge[k]["share"] - n_ / nlex[k[0]]) > 1e-9)
        R.check("arc facts: equivalent_of equals the recount from the published list (G8)"
                + ("; SPEC 1.4: summed over kind, every kind derived or model" if V14 else ""),
                bad == 0 and len(ge) == len(want_eq), f"{len(ge)} rows, {bad} differ")
    else:
        R.check(f"{lang} facts: no equivalent_of (arc only)", not eq, len(eq))
    kept = C.Counter(f["relation"] for f in F if f["relation"] not in V.S9_RELATIONS)
    R.check(f"{lang} facts: besides stage 20's relations only kin and rendered_by rows (stages 16, 19)",
            set(kept) <= {"father", "mother", "offspring", "sibling", "partner", "tribe", "group_origin", "rendered_by"},
            dict(sorted(kept.items())))


def svo_shares(T):
    svo = {"V-S-O": "initial", "V-O-S": "initial", "S-V-O": "medial", "O-V-S": "medial", "S-O-V": "final",
           "O-S-V": "final"}
    per = C.Counter()
    for r in T:
        if r["level"] == "clause" and r["rule"] in svo:
            per[svo[r["rule"]]] += r["count"]
    return per


def check_profile(R, V, build, lang, cats):
    d = os.path.join(build, lang)
    with open(V.S9_PARAMS, encoding="utf-8") as fh:
        params = [ln.rstrip("\n").split("\t") for ln in fh if ln.strip() and not ln.startswith("#")][1:]
    head, cols, n = table(os.path.join(d, "profile.tsv"))
    prof = [dict(zip(head, x)) for x in zip(*[cols[c] for c in head])]
    R.check(f"{lang} profile.tsv: columns id, value, statement, count (G5: no question)", head == SPEC_COLS["profile.tsv"], head)
    R.check(f"{lang} profile.tsv: the 195 questionnaire ids in order", [r["id"] for r in prof] == [p[0] for p in params], n)
    R.check(f"{lang} profile.tsv: every value is ?, 0, 1, 2 or 3",
            all(r["value"] in {"?", "0", "1", "2", "3"} for r in prof))
    stm = {}
    for tb in V.S9_STATEMENT_TABLES:
        t = pq.read_table(os.path.join(d, f"{tb}.parquet"), columns=["id", "count"]).to_pydict()
        stm.update(zip(t["id"], t["count"]))
    bad_ev, bad_q, small, g7 = [], [], [], []
    for r in prof:
        ids, cnts = r["statement"].split(), r["count"].split()
        if r["value"] == "?":
            if ids or cnts:
                bad_q.append(r["id"])
            continue
        if len(ids) == 1 and ids[0].startswith("categories.toml:"):
            tb, cat = ids[0].split(":", 1)[1].split(".", 1)
            sec = cats.get(tb, {}).get(cat)
            ok = sec is not None and r["value"] == "0" and cnts == [str(sum(v["count"] for v in sec["values"]))]
            g7.append(r["id"])
            if not ok:
                bad_ev.append(r["id"])
            continue
        if not ids or len(ids) != len(cnts) or any(i not in stm or str(stm[i]) != c for i, c in zip(ids, cnts)):
            bad_ev.append(r["id"])
        elif sum(int(c) for c in cnts) < 50:
            small.append(r["id"])
    R.check(f"{lang} profile.tsv: every answer's evidence resolves (statement ids with their counts, or "
            f"categories.toml:<category> for a 0 with the category's count, G7)", not bad_ev, bad_ev[:5])
    R.check(f"{lang} profile.tsv: an unanswered row has no evidence", not bad_q, bad_q[:5])
    R.check(f"{lang} profile.tsv: every answer from the statement tables rests on at least 50 places (G10)", not small, small)
    G = {r["id"]: r["value"] for r in prof}
    for qid, cat in (("GB043", "du"),):
        sec = cats.get("pieces", {}).get("number")
        if sec and cat not in {v["code"] for v in sec["values"]}:
            R.check(f"{lang} profile {qid}: 0, since pieces.number has no code {cat} (G7)", G[qid] == "0", G[qid])
    # G6, recomputed: the clause-order questions
    T = pq.read_table(os.path.join(d, "constructions.parquet"), columns=["level", "rule", "count"]).to_pylist()
    per = svo_shares(T)
    tot = sum(per.values())
    exp = {}
    if tot >= 50:
        top = max(per.values())
        winners = [k for k, v in per.items() if v == top]
        for qid, typ in (("GB131", "initial"), ("GB132", "medial"), ("GB133", "final")):
            if len(winners) != 1 or top / tot < 0.5:
                exp[qid] = "?"
            elif typ == winners[0]:
                exp[qid] = "1"
            else:
                exp[qid] = "0" if per.get(typ, 0) / tot < 0.10 else "?"
    else:
        exp = {"GB131": "?", "GB132": "?", "GB133": "?"}
    R.check(f"{lang} profile GB131-133: the commonest clause order answers only where it covers 0.5 (G6), recomputed",
            all(G[k] == v for k, v in exp.items()), f"{dict((k, G[k]) for k in exp)}; shares "
            + ", ".join(f"{k} {v / tot:.2f}" for k, v in sorted(per.items())) if tot else "no clauses")
    ans = [r for r in prof if r["value"] != "?"]
    R.info(f"{lang} profile answered", f"{len(ans)} of {len(prof)} ({len(g7)} by categories.toml): "
           + " ".join(f"{r['id']}={r['value']}" for r in ans))


# ---- sources.json, COLUMNS.md, READ-FIRST.md -----------------------------------------------------------------------

def check_sources(R, build, lang):
    d = os.path.join(build, lang)
    with open(os.path.join(d, "sources.json"), encoding="utf-8") as fh:
        doc = json.load(fh)
    nfiles, bad, missing = 0, [], []
    for key, s in sorted(doc["sources"].items()):
        for rel, meta in s["files"].items():
            nfiles += 1
            path = os.path.join(os.path.dirname(ROOT), rel[3:]) if rel.startswith("../") else os.path.join(ROOT, rel)
            if not os.path.exists(path):
                missing.append(rel)
            elif sha(path) != meta["sha256"]:
                bad.append(rel)
    R.check(f"{lang} sources.json: every file listed exists and has the sha256 listed", not bad and not missing,
            f"{len(doc['sources'])} sources, {nfiles} files, {len(missing)} missing, {len(bad)} differ")
    R.check(f"{lang} sources.json: every source has repository, pin, licence and at least one file",
            all(s.get("repository") and s.get("pin") and s.get("licence") and s["files"] for s in doc["sources"].values()))
    need = {"compact-alignments", "helloao"} if lang == "grc" else {"hebrew-greek-cf", "glaux-lxx"}
    R.check(f"{lang} sources.json: the link sources are hashed ({', '.join(sorted(need))})", need <= set(doc["sources"]),
            sorted(need - set(doc["sources"])))
    M = doc.get("model", {})
    badm = []
    for k, m in M.items():
        if m.get("status", "").startswith("not on disk"):
            if m.get("columns"):
                badm.append(k)
            continue
        if not (m.get("models") and m.get("human_check") == "no human check" and (m.get("version") or m.get("revision"))):
            badm.append(k)
    R.check(f"{lang} sources.json: every model source names version, model(s) and no human check (or is not read and "
            f"fills no column)", not badm, f"{len(M)} model sources; {badm}")
    fsrc = set(pq.read_table(os.path.join(d, "facts.parquet"), columns=["source"]).column("source").to_pylist())
    R.check(f"{lang} sources.json: every facts.source is a key of sources or model", fsrc <= set(doc["sources"]) | set(M),
            sorted(fsrc))
    ee = [k for k, s in doc["sources"].items() if s.get("english_evidence")]
    R.check(f"{lang} sources.json: the English evidence of the speech sources is named (D10)", bool(ee), ee)
    if lang != "grc":
        R.check(f"{lang} sources.json: GLAUx's method stated as automatic",
                "automatic" in doc["sources"]["glaux-lxx"].get("method", "") and "automatic" in M.get("glaux", {}).get("method", ""))
    R.check(f"{lang} sources.json: pyarrow version as running", doc["pyarrow"] == pyarrow.__version__, doc["pyarrow"])
    bad_b = [k for k, v in doc["builder"]["files"].items() if sha(os.path.join(ROOT, k)) != v["sha256"]]
    if COPIED:
        R.info(f"{lang} sources.json (1.7 copy): builder files changed since h1 by stage 49, named not failed",
               [k for k in bad_b if k in COPIED_CHANGED])
        bad_b = [k for k in bad_b if k not in COPIED_CHANGED]
    R.check(f"{lang} sources.json: builder files as listed (sha256), commit named", not bad_b and bool(doc["builder"]["commit"]),
            f"{len(doc['builder']['files'])} files, {len(bad_b)} differ")
    spec = doc["specification"]
    spath = "internal-docs/source-examples-spec/SPEC-v1.6.md" if COPIED else spec["path"]
    R.check(f"{lang} sources.json: specification {ver()} with its sha256" + (" (SPEC-v1.6.md, 1.7 copy)" if COPIED else ""),
            spec["version"] == ver() and spec["sha256"] == sha(os.path.join(ROOT, spath)))
    R.check(f"{lang} sources.json: licence of the example stated", bool(doc.get("licence")))
    R.info(f"{lang} sources.json builder", f"commit {doc['builder']['commit']}; files not committed: "
           f"{sum(1 for v in doc['builder']['files'].values() if not v['committed'])}")


def check_columns(R, build, lang):
    d = os.path.join(build, lang)
    with open(os.path.join(d, "COLUMNS.md"), encoding="utf-8") as fh:
        text = fh.read()
    listed, cur = {}, None
    for ln in text.split("## Part 2. The files as built", 1)[1].split("\n"):
        m = re.match(r"^### `([^`]+)`: ([0-9,]+) rows, (\d+) columns", ln)
        if m:
            cur = m.group(1)
            listed[cur] = (int(m.group(2).replace(",", "")), [])
            continue
        m = re.match(r"^\| `([^`]+)` \| ", ln)
        if m and cur:
            listed[cur][1].append(m.group(1))
    fs = files_of(d, lang)
    R.check(f"{lang} COLUMNS.md: lists every table file of the folder and the texts it links to, no other",
            sorted(listed) == sorted(fs), f"{len(fs)} files, listed {len(listed)}")
    wrong, spec_wrong = [], []
    for f in fs:
        cols, _, n = table(os.path.normpath(os.path.join(d, f)))
        if listed.get(f) != (n, cols):
            wrong.append(f)
        if f in spec_cols() and cols != spec_cols()[f]:
            spec_wrong.append((f, cols))
    R.check(f"{lang} COLUMNS.md: rows and columns of every file equal the file", not wrong, wrong)
    R.check(f"{lang} tables: columns as SPEC {ver()} section 4 lists them, in order", not spec_wrong,
            f"{sum(1 for f in fs if f in spec_cols())} files; {spec_wrong}")
    sec4 = ""
    with open(os.path.join(ROOT, "internal-docs/source-examples-spec/SPEC-v1.6.md" if COPIED else
                           "internal-docs/source-examples-spec/SPEC.md"), encoding="utf-8") as fh:
        spec = fh.read()
    sec4 = spec[spec.index("## 4. The tables"):spec.index("## 5. Sources")].rstrip()
    sec4 = sec4.replace("\n## ", "\n### ").replace("\n### 4.", "\n#### 4.").split("\n", 1)[1]
    R.check(f"{lang} COLUMNS.md: holds SPEC {ver()} section 4 as " + ("SPEC-v1.6.md has it (1.7 copy)" if COPIED else
            "SPEC.md has it now"), "4.10 The small files" in text
            and f"version {ver()}" in text and "4.9 Links to another text" in text and (not V12 or sec4 in text))


def check_read_first(R, build, lang):
    d = os.path.join(build, lang)
    p = os.path.join(d, "READ-FIRST.md")
    text = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    R.check(f"{lang} READ-FIRST.md: exists with sections 1 to 5 (5: what is model, and how much)",
            all(f"## {i}." in text for i in (1, 2, 3, 4, 5)) and "## 5. What is model" in text)
    # stage 21: the sheet must send the reader to the 1.1 chapters, not to the 1.0 ones (1.2: glossed-d1, stage 24)
    gn, st = ("glossed-d1", "24") if V12 else ("glossed-c1", "20")
    R.check(f"{lang} READ-FIRST.md: names the {ver()} chapters ({gn}/) and stage {st}, not glossed/ or stage 10",
            f"source-examples-work/{gn}/" in text and "source-examples-work/glossed/" not in text
            and f"--stage {st}" in text and "--stage 10" not in text
            and (not V12 or ("glossed-c1/" not in text and "--stage 20" not in text)))
    R.check(f"{lang} READ-FIRST.md: section 1 holds the normal ranges", "## 1. Whole text (the normal ranges)" in text)
    P = pq.read_table(os.path.join(d, "pieces.parquet"), columns=["concept", "who_basis"]).to_pydict()
    K = pq.read_table(os.path.join(d, "clauses.parquet"), columns=["quote_model", "subject_model"]).to_pydict()
    LK = pq.read_table(os.path.join(d, "links.parquet"), columns=["basis"]).column("basis").to_pylist()
    F = pq.read_table(os.path.join(d, "facts.parquet"), columns=["kind"]).column("kind").to_pylist()
    want = {"pieces.concept (M1)": sum(v is not None for v in P["concept"]),
            "pieces.who with who_basis model (M2)": sum(v == "model" for v in P["who_basis"]),
            "clauses.subject_model (M3)": sum(v is not None for v in K["subject_model"]),
            "links with basis model (M5, M7)": sum(v == "model" for v in LK),
            "facts with kind model (M7)": sum(v == "model" for v in F)}
    sec5 = text.split("## 5. What is model", 1)[-1]
    bad = [k for k, v in want.items() if f"| {k} | {v:,} |" not in sec5]
    R.check(f"{lang} READ-FIRST.md section 5: the model counts equal the recount", not bad, f"{want}; {bad}")


# ---- glossed chapters ----------------------------------------------------------------------------------------------

def check_glossed(R, build, gdir, terms):
    for lang, book, ch, name in CHAPTERS:
        p = os.path.join(gdir, name + ".md")
        if not os.path.exists(p):
            R.check(f"glossed {name}.md exists", False)
            continue
        d = os.path.join(build, lang)
        W = pq.read_table(os.path.join(d, "words.parquet"), columns=["t", "book", "chapter", "verse"]).to_pylist()
        ts = {w["t"] for w in W if w["book"] == book and w["chapter"] == ch}
        verses = {w["verse"] for w in W if w["book"] == book and w["chapter"] == ch}
        P = [p_ for p_ in pq.read_table(os.path.join(d, "pieces.parquet"), columns=["t", "n", "concept", "who_basis"]).to_pylist()
             if p_["t"] in ts]
        nmodel = sum(1 for p_ in P if p_["concept"] is not None or p_["who_basis"] == "model")
        text = open(p, encoding="utf-8").read()
        heads = re.findall(rf"^## {book} {ch}:(\d+)$", text, re.M)
        rows = [ln for ln in text.split("\n") if re.match(r"^\| \d+\.\d+ \|", ln)]
        hdr = "| t.n | word | piece | kind | lexeme | class | marks | head | label | shared | clause | part | participant | concept | model |"
        R.check(f"glossed {name}: one table per verse, one row per piece, the {ver()} columns, no gloss column, "
                f"names SPEC {ver()}",
                sorted(map(int, heads)) == sorted(verses) and len(rows) == len(P) and text.count(hdr) == len(verses)
                and "gloss |" not in hdr and f"(SPEC {ver()})" in text, f"{len(heads)} verses of {len(verses)}, {len(rows)} rows of {len(P)} pieces")
        marked = sum(1 for ln in rows if ln.rstrip().rsplit("|", 2)[1].strip())
        R.check(f"glossed {name}: the model column marks exactly the pieces with a model value", marked == nmodel,
                f"{marked} marked, {nmodel} pieces with concept or who_basis model")
        cl = [(c, v.strip()) for c, v in re.findall(r"(?:^|; |\| )(relation|time|aspect|line_kind)=([^;|]+)", text, re.M)]
        bad = [v for c, v in cl if v not in terms[lang][c]]
        R.check(f"glossed {name}: every meaning value shown is a term of the language (terms.tsv)", not bad and bool(cl),
                f"{len(cl)} values; {bad[:3]}")
        if V12:     # SPEC 1.2, stage 24: the semantic role in `part` is a term of the language too
            parts = [x.strip() for ln in rows for x in ln.split(" | ")[11].split("; ") if x.strip()]
            roles = [re.sub(r" \(linked\)$", "", x).split(" ", 1)[1] for x in parts if " " in re.sub(r" \(linked\)$", "", x)]
            badr = [r for r in roles if r not in terms[lang]["sem_role"]]
            R.check(f"glossed {name}: every semantic role shown in `part` is a sem_role term of the language",
                    not badr and bool(roles), f"{len(roles)} roles of {len(parts)} parts; {badr[:3]}")


# ---- no English ----------------------------------------------------------------------------------------------------

def declared_tokens(build, lang, cats):
    d = os.path.join(build, lang)
    tok = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("code", "term", "value", "form", "feature"):
                    if isinstance(v, str):
                        tok.add(v)
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(cats)
    for f, colsets in (("relmap.tsv", ("label", "class", "shared")), ("map.tsv", ("category", "code", "feature", "value", "reason", "table"))):
        _, cols, _ = table(os.path.join(d, f))
        for c in colsets:
            tok |= set(cols[c])
    tok |= {c for secs in cats.values() for c in secs}
    _, tcols, _ = table(os.path.join(d, "terms.tsv"))
    tok |= set(tcols["code"]) | set(tcols["category"])
    tok |= {"class", "lemma", "text"}          # SPEC 4.9: the keys of an `analysis` part
    tok |= {"text", "tradition", "coined"}     # SPEC 4.10: the codes of terms.tsv from_hbo, from_grc
    for v in cats.get("pieces", {}).get("shared", {}).get("values", []) + cats.get("clauses", {}).get("shared", {}).get("values", []):
        tok |= set(v["code"].split("="))
    return tok


def check_english(R, V, build, lang, cats, vocab):
    d = os.path.join(build, lang)
    D = declared_tokens(build, lang, cats) | V.S10_BOOKS | set().union(*V.S10_FORMAT.values()) | {"top"}
    script_bad, english, notes, homograph, code_words = C.Counter(), C.Counter(), C.Counter(), C.Counter(), C.Counter()
    undeclared, hmarks = C.Counter(), C.Counter()
    nstr = nscript = 0
    secs = {(t, c): s for t, ss in cats.items() for c, s in ss.items() if isinstance(s, dict)}
    for f in files_of(d, lang):
        cols, data, _ = table(os.path.normpath(os.path.join(d, f)))
        base = f.split("/")[-1] if not f.startswith("..") else f
        tname = base.rsplit(".", 1)[0]
        # (a) a coded column that categories.toml declares with its values: every value is a declared code or term
        for c in cols:
            s = secs.get((tname, c))
            if not s or "values" not in s or s.get("column", c) != c:
                continue
            ok = {v.get("code") for v in s["values"]} | {v.get("term") for v in s["values"] if "term" in v}
            if V13 and (tname, c) == ("who_account", "reason"):
                # SPEC 1.3 D19: the reason of `no_row` is the word's `rel`, a label declared by pattern (4.10);
                # stage 28 recomputes every reason row by row
                ok |= set(table(os.path.join(d, "words.parquet"))[1]["rel"])
            for v, k in C.Counter(data[c]).items():
                if v in (None, ""):
                    continue
                if c == "shared" and v.startswith("{"):
                    items = [f"{a}={b}" for a, b in json.loads(v).items()]
                elif V13 and c == "marks_model" and v.startswith("{"):
                    items = list(json.loads(v).values())      # SPEC 1.3 4.3: a JSON object of terms
                elif v not in ok and " " in v:
                    items = v.split(" ")
                else:
                    items = [v]
                if any(x not in ok for x in items):
                    undeclared[(f, c, v)] += k
        # (b) script
        for c in SCRIPT_COLS.get(f if f.startswith("..") else base, []):
            for v, k in C.Counter(data[c]).items():
                nscript += k
                if v in (None, ""):
                    continue
                if lang == "grc" and (base, c) in (("lexemes.tsv", "lemma"), ("participants.tsv", "name")) and HOMOGRAPH.search(v):
                    homograph[v] += k
                    v = HOMOGRAPH.sub("", v)
                if not letters_ok(v):
                    script_bad[(f, c, v)] += k
        # (c) gloss vocabulary, over every string value (JSON keys and values, space-separated items)
        for c in cols:
            vals = data[c]
            if not any(isinstance(x, str) for x in vals[:1000] if x is not None):
                continue
            nstr += 1
            for v, k in C.Counter(vals).items():
                if not isinstance(v, str) or not v:
                    continue
                try:
                    m = json.loads(v) if v[:1] in "{[" else None
                except ValueError:
                    m = None
                if m is not None:
                    items = m if isinstance(m, list) else list(m.keys()) + list(m.values())
                    toks = []
                    for x in items:
                        if isinstance(x, dict):
                            toks += [str(y) for kv in x.items() for y in kv]
                        elif isinstance(x, list):
                            toks += [str(y) for y in x]
                        else:
                            toks.append(str(x))
                else:
                    toks = v.split(" ")
                for tk in toks:
                    if HMARK.match(tk):
                        hmarks[(f, c)] += k       # SPEC 3: the homograph mark of a Greek lemma, allowed by name
                        continue
                    for t_ in {tk, tk.strip("'.,;()")}:
                        if t_.lower() in vocab:
                            if (f, c) in NOTE_COLS and not V12:
                                notes[t_] += k
                            elif t_ in D or tk in D:
                                code_words[(t_, f"{f}:{c}")] += k
                            else:
                                english[(f, c, t_)] += k
                            break
    R.check(f"{lang} no English (a): every value of a column categories.toml declares is a declared code or term",
            not undeclared, f"{sum(undeclared.values())} values off: {sorted(undeclared.items())[:5]}")
    R.check(f"{lang} no English (b): text, after, lemma, name, form and terms in Hebrew or Greek script, punctuation or empty",
            not script_bad, f"{nscript:,} values; {sorted(script_bad.items())[:5]}")
    R.info(f"{lang} script exceptions: Greek lemmas (and names taken from them, D7n) with the homograph mark of SPEC 3", f"{sum(homograph.values())}: "
           + ", ".join(sorted(homograph)))
    R.check(f"{lang} no English (c): no string value of a table equals a word of MACULA's gloss vocabulary unless a "
            f"declared code " + ("(terms.tsv is a table: no exception, SPEC 1.2 section 10)" if V12 else
                                 "(terms.tsv note, source_hbo, source_grc listed apart)"), not english,
            f"{nstr} string columns; {sum(english.values())} values: {sorted(english.items())[:8]}")
    if V12:
        R.check(f"{lang} no English: terms.tsv holds no gloss word in any of its ten columns (no exception)",
                not notes and not any(f == "terms.tsv" for f, _, _ in english),
                f"{sum(k for (f, _, _), k in english.items() if f == 'terms.tsv') + sum(notes.values())} English values")
    else:
        R.info(f"{lang} terms.tsv note, source_hbo, source_grc: English words in SPEC 4.10's descriptive columns (how a "
           f"coined term was built; the grammarian or work); for the specification",
           f"{len(notes)} words, {sum(notes.values())} uses: " + ", ".join(sorted(notes)))
    R.info(f"{lang} homograph marks (I), (II) inside values (SPEC 3), by column",
           dict(sorted((f"{a}:{b}", n) for (a, b), n in hmarks.items())))
    by = C.defaultdict(lambda: [0, set()])
    for (t_, where), k in code_words.items():
        by[t_][0] += k
        by[t_][1].add(where)
    R.info(f"{lang} exception list: declared codes that are also English gloss words",
           f"{len(by)} codes, {sum(v[0] for v in by.values()):,} values: "
           + ", ".join(f"{t} {n}" for t, (n, _) in sorted(by.items(), key=lambda kv: (-kv[1][0], kv[0]))))
    return {t: (n, sorted(w)) for t, (n, w) in sorted(by.items())}


# ---- rebuild -------------------------------------------------------------------------------------------------------

def check_rebuild(R, build, compare):
    b2 = os.path.join(os.path.dirname(os.path.normpath(build)), compare)
    if not os.path.isdir(b2):
        R.check(f"rebuild: build {compare} present", False)
        return

    def walk(root, skip_cache=True):
        out = {}
        for dp, _, fs in os.walk(root):
            for fn in fs:
                rel = os.path.relpath(os.path.join(dp, fn), root)
                if (skip_cache and rel.startswith("cache/")) or rel.endswith("VALIDATION.md") or rel.endswith(".tmp"):
                    continue
                out[rel] = os.path.join(dp, fn)
        return out
    A, B = walk(build), walk(b2)
    for part in LANGS + ("other",):
        ka = {k for k in A if k.startswith(part + "/")}
        kb = {k for k in B if k.startswith(part + "/")}
        differ = [k for k in sorted(ka & kb) if sha(A[k]) != sha(B[k])]
        R.check(f"rebuild: every file of {os.path.basename(build)}/{part} has the same sha256 in {compare} "
                f"(VALIDATION.md aside)", ka == kb and not differ and bool(ka),
                f"{len(ka)} files, {len(ka ^ kb)} in one build only {sorted(ka ^ kb)[:3]}, {len(differ)} differ {differ[:5]}")
    ga = glossed_dir(build)
    gb = os.path.join(b2, "cache", "glossed")
    fa = sorted(f for f in os.listdir(ga) if f.endswith(".md") and not (
        V15 and f in ("mends-sample.md", "equivalents-sample.md"))) if os.path.isdir(ga) else []    # SPEC 1.5: samples
    fb = sorted(f for f in os.listdir(gb) if f.endswith(".md")) if os.path.isdir(gb) else []
    gd = [f for f in set(fa) & set(fb) if sha(os.path.join(ga, f)) != sha(os.path.join(gb, f))]
    R.check(f"rebuild: the glossed chapters are the same in {compare}", fa == fb and not gd and bool(fa),
            f"{len(fa)} files, {len(gd)} differ")
    CA = {k: v for k, v in walk(build, False).items() if k.startswith("cache/stage")}
    CB = {k: v for k, v in walk(b2, False).items() if k.startswith("cache/stage")}
    cd = [k for k in sorted(set(CA) & set(CB)) if sha(CA[k]) != sha(CB[k])]
    R.info(f"rebuild, cache/stageNN-counts.json (not tables)", f"{len(set(CA) & set(CB))} in both, differ {cd}")


# ---- the stage -----------------------------------------------------------------------------------------------------

def stage20(R, build, src, STASH, V, compare=None):
    cats = {}
    for lang in LANGS:
        with open(os.path.join(build, lang, "categories.toml"), "rb") as fh:
            cats[lang] = tomllib.load(fh)
    R.section("relmap, map, shared, facts of stage 20 (D4, D6, 4.8)")
    for lang in LANGS:
        check_shared(R, V, build, lang, cats[lang])
    R.section("profile.tsv (G5, G6, G7, G10)")
    for lang in LANGS:
        check_profile(R, V, build, lang, cats[lang])
    R.section("sources.json")
    for lang in LANGS:
        check_sources(R, build, lang)
    if V12:     # SPEC 1.2 section 14: COLUMNS.md, READ-FIRST.md, the glossed chapters, no English, rebuild: stage 24
        if UPTO < "24":
            R.section("COLUMNS.md, READ-FIRST.md, glossed chapters, no English (SPEC 1.2: stage 24)")
            R.skip("COLUMNS.md, READ-FIRST.md, the glossed chapters (glossed-d1/) and the no-English condition",
                   "SPEC 1.2 section 14 gives them to stage 24 (close12); run --upto 24")
        return
    docs(R, build, STASH, V, compare, cats)


def stage24(R, build, src, STASH, V, compare=None):
    """SPEC 1.2, stage 24 (close12): sources.json again, terms-notes.md, COLUMNS.md, READ-FIRST.md, the glossed
    chapters (glossed-d1/), no English with terms.tsv as a table, rebuild."""
    cats = {}
    for lang in LANGS:
        with open(os.path.join(build, lang, "categories.toml"), "rb") as fh:
            cats[lang] = tomllib.load(fh)
    R.section("sources.json (as stage 24 wrote it)")
    for lang in LANGS:
        check_sources(R, build, lang)
        with open(os.path.join(build, lang, "sources.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        tf = doc["sources"].get("terms", {}).get("files", {})
        R.check(f"{lang} sources.json: terms.tsv and terms-notes.md hashed as the masters",
                tf.get("internal-docs/source-examples-spec/terms-notes.md", {}).get("sha256") == sha(TERMS_NOTES)
                and tf.get("internal-docs/source-examples-spec/terms.tsv", {}).get("sha256")
                == sha(os.path.join(ROOT, "internal-docs/source-examples-spec/terms.tsv")), sorted(tf))
        R.check(f"{lang} sources.json: the builder entry names stages 23 and 24",
                "--stage 23" in doc["builder"]["entry"] and "--stage 24" in doc["builder"]["entry"], doc["builder"]["entry"])
    R.section("terms-notes.md (SPEC 4.10)")
    for lang in LANGS:
        p = os.path.join(build, lang, "terms-notes.md")
        R.check(f"{lang} terms-notes.md: a byte copy of the master", os.path.exists(p) and sha(p) == sha(TERMS_NOTES))
        _, tcols, n = table(os.path.join(build, lang, "terms.tsv"))
        text = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
        miss = [f"{c}:{k}" for c, k in zip(tcols["category"], tcols["code"]) if f"\n### {c} `{k}`\n" not in text]
        R.check(f"{lang} terms-notes.md: one section per (category, code) of terms.tsv", not miss, f"{n} rows; {miss[:5]}")
        R.info(f"{lang} terms-notes.md: exempt from the no-English check by name (SPEC 4.10); not a table",
               f"{len(text):,} characters")
    docs(R, build, STASH, V, compare, cats)


def docs(R, build, STASH, V, compare, cats):
    R.section("COLUMNS.md and READ-FIRST.md")
    for lang in LANGS:
        check_columns(R, build, lang)
        check_read_first(R, build, lang)
    R.section("glossed chapters")
    terms = {}
    for lang in LANGS:
        _, cols, _ = table(os.path.join(build, lang, "terms.tsv"))
        col = "grc" if lang == "grc" else "hbo"
        terms[lang] = C.defaultdict(set)
        for cat, t in zip(cols["category"], cols[col]):
            terms[lang][cat].add(t)
    check_glossed(R, build, glossed_dir(build), terms)
    R.section("no English")
    vocab, nlow = V._s10_gloss_vocab()
    R.info("MACULA gloss vocabulary (words of gloss and english, lower-cased)", f"{len(vocab)} words from {nlow} files")
    for lang in LANGS:
        STASH[f"s10 {lang} code words"] = check_english(R, V, build, lang, cats[lang], vocab)
    R.section("rebuild")
    if compare:
        check_rebuild(R, build, compare)
    else:
        R.skip("rebuild: a second build compared file by file", "no --compare given")
