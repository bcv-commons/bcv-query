"""Stage 49 (SPEC 1.7), part 2: the files over the carried tables of `heb_mod/`, `heb_scg/` (D43, D44) and the
reader's sheets. Called by examples_v17.build.

Writes per edition: lexemes.tsv, participants.tsv, facts.parquet, the statement tables of 4.7 over the strict view
(section 7, "the queries over heb_mod, heb_scg"), exceptions.parquet, profile.tsv, terms.tsv, terms-notes.md, map.tsv,
relmap.tsv, source_errors.tsv, carry_account.tsv, differ.parquet, categories.toml, sources.json, COLUMNS.md,
READ-FIRST.md. And the sheets: `<build>/cache/glossed/` (always) and, for build i1,
`internal-docs/source-examples-work/glossed-i1/` (the reading sheets of MRK 4, JHN 1, ACT 2, ROM 8 per edition, and
carry-sample.md). VALIDATION.md is the validator's.
"""
import collections as C
import hashlib
import json
import os
import shutil
import sys
import unicodedata

import pyarrow as pa
import pyarrow.parquet as pq

import examples_common as X

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SPEC = os.path.join(ROOT, "internal-docs/source-examples-spec/SPEC.md")
TERMS = os.path.join(ROOT, "internal-docs/source-examples-spec/terms.tsv")
GLOSSED_I1 = os.path.join(ROOT, "internal-docs/source-examples-work/glossed-i1")
EDS = ("heb_mod", "heb_scg")
S_, I_, F_ = pa.string(), pa.int64(), pa.float64()
AGREE = ("gender", "number", "person", "case", "state")
CHAPTERS = (("MRK", 4, "mark-4"), ("JHN", 1, "john-1"), ("ACT", 2, "acts-2"), ("ROM", 8, "romans-8"))
STAT = {
    "forms": [("id", S_), ("lexeme", S_), ("marks", S_), ("form", S_), ("count", I_), ("against", I_), ("places", S_)],
    "paradigms": [("id", S_), ("class", S_), ("marks", S_), ("lexemes", I_), ("forms", I_), ("count", I_),
                  ("against", I_), ("places", S_)],
    "markers": [("id", S_), ("marker", S_), ("kind", S_), ("category", S_), ("value", S_), ("count", I_),
                ("against", I_), ("places", S_)],
    "constructions": [("id", S_), ("level", S_), ("rule", S_), ("children", S_), ("head_at", I_), ("count", I_),
                      ("against", I_), ("places", S_)],
    "orders": [("id", S_), ("rel", S_), ("head_class", S_), ("dep_class", S_), ("before", I_), ("after", I_),
               ("count", I_), ("against", I_), ("places", S_)],
    "agreement": [("id", S_), ("rel", S_), ("category", S_), ("agree", I_), ("differ", I_), ("n_a", I_),
                  ("count", I_), ("against", I_), ("places", S_)],
    "frames": [("id", S_), ("lexeme", S_), ("stem", S_), ("frame", S_), ("count", I_), ("against", I_), ("places", S_)],
    "pairs": [("id", S_), ("head", S_), ("rel", S_), ("dep", S_), ("count", I_), ("against", I_), ("places", S_)],
    "clause_links": [("id", S_), ("kind", S_), ("connective", S_), ("parent_kind", S_), ("role", S_), ("count", I_),
                     ("against", I_), ("places", S_)],
}


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def tsv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        lines = fh.read().split("\n")
    head = lines[0].split("\t")
    return [dict(zip(head, ln.split("\t"))) for ln in lines[1:] if ln]


# ---- D6 through hbo's map.tsv ---------------------------------------------------------------------------------------

def read_map(outdir):
    M = C.defaultdict(list)
    for r in tsv(os.path.join(outdir, "hbo", "map.tsv")):
        M[(r["table"], r["category"], r["code"])].append(r)
    return M


def shared_fn(outdir):
    M = read_map(outdir)

    def f(p):
        out = {}
        for cat, code in sorted(p["marks"].items()):
            for r in M.get(("pieces", cat, code), []):
                if r["feature"] != "none":
                    out[r["feature"]] = r["value"]
        for r in M.get(("pieces", "class", p["class"]), []):
            if r["feature"] != "none":
                out[r["feature"]] = r["value"]
        return X.jdump(out)
    return f


# ---- the strict view (4.15) -----------------------------------------------------------------------------------------

def norm_form(ed, text):
    return X.norm_heb(text) if ed == "heb_scg" else unicodedata.normalize("NFC", text)


def emit(name, keys, row_of, pro, con, exc):
    cols = {c: [] for c, _ in STAT[name]}
    for i, k in enumerate(keys, 1):
        sid = f"{name}:{i}"
        p, q = pro(k), con(k)
        row = row_of(k)
        row.update({"id": sid, "count": len(p), "against": len(q), "places": " ".join(x for _, x in sorted(p)[:3])})
        for c in cols:
            cols[c].append(row[c])
        for _, x in sorted(q):
            exc.append((sid, x))
    return cols


def statements(E, lexrows):
    """Section 7 over the edition's strict view: model pieces are not counted, model own values are empty."""
    ed = E.ed
    strict = {}
    for t in E.ts:
        for p in E.parts[t]:
            if p["basis"] != "model":
                strict[(t, p["n"])] = p
    stem = {t: E.stem[t] for t in E.ts if E.stem[t]["basis"] != "model"}
    out, exc = {}, []
    fg, pg, plex, pform = C.defaultdict(list), C.defaultdict(list), C.defaultdict(set), C.defaultdict(set)
    for (t, n), p in sorted(strict.items()):
        o, pl = (t, n), f"{t}.{n}"
        m = X.jdump(p["marks"])
        f = norm_form(ed, p["text"])
        fg[(p["lexeme"], m, f)].append((o, pl))
        pg[(p["class"], m)].append((o, pl))
        plex[(p["class"], m)].add(p["lexeme"])
        pform[(p["class"], m)].add(f)
    out["forms"] = emit("forms", sorted(fg), lambda k: {"lexeme": k[0], "marks": k[1], "form": k[2]},
                        lambda k: fg[k], lambda k: [], exc)
    out["paradigms"] = emit("paradigms", sorted(pg), lambda k: {"class": k[0], "marks": k[1], "lexemes": len(plex[k]),
                                                                "forms": len(pform[k])},
                            lambda k: pg[k], lambda k: [], exc)
    per_class = C.Counter(r["class"] for r in lexrows if int(r["count"]) > 0)
    lexclass = {r["lexeme"]: r["class"] for r in lexrows if int(r["count"]) > 0}
    wm = {lx for lx, cl in lexclass.items() if per_class[cl] <= 40}
    head = {t: E.head[t][0] for t in E.head}
    mk = C.defaultdict(list)
    for (t, n), p in sorted(strict.items()):
        if p["kind"] in ("prefix", "suffix"):
            if t not in stem:
                continue
            marker = p["lexeme"]
            if p["kind"] == "suffix" and p["class"] == "pron" and all(c in p["marks"] for c in ("person", "gender", "number")):
                marker = f"sfx:hbo:{p['marks']['person']}.{p['marks']['gender']}.{p['marks']['number']}"
            mk[(marker, p["kind"])].append(((t, n), f"{t}.{n}", stem[t]["marks"]))
        if p["lexeme"] in wm and p["kind"] == "stem":
            h = head.get(t)
            if h and h in stem:
                mk[(p["lexeme"], "word")].append(((t, n), f"{t}.{n}", stem[h]["marks"]))
    mrows = {}
    for (lx, kind), places in mk.items():
        bycat = C.defaultdict(list)
        for o, pl, marks in places:
            for cat, code in marks.items():
                bycat[cat].append((o, pl, code))
        for cat, items in bycat.items():
            vals = C.Counter(x[2] for x in items)
            top = max(vals.values())
            value = min(v for v, n in vals.items() if n == top)
            if len(items) >= 20 and top / len(items) >= 0.95:
                mrows[(lx, kind, cat)] = (value, [(o, pl) for o, pl, c in items if c == value],
                                          [(o, pl) for o, pl, c in items if c != value])
    out["markers"] = emit("markers", sorted(mrows), lambda k: {"marker": k[0], "kind": k[1], "category": k[2],
                                                                "value": mrows[k][0]},
                          lambda k: mrows[k][1], lambda k: mrows[k][2], exc)
    out["constructions"] = emit("constructions", [], None, None, None, exc)
    og = C.defaultdict(lambda: ([], []))
    ag = C.defaultdict(lambda: ([], [], [0]))
    pr = C.defaultdict(list)
    for t in E.ts:
        h = head.get(t)
        if not h or t not in stem or h not in stem:
            continue
        rel = E.G.w[E.one[t]]["rel"]
        d, hh = stem[t], stem[h]
        o = ((t, 0), str(t))
        og[(rel, hh["class"], d["class"])][0 if t < h else 1].append(o)
        for cat in AGREE:
            a, b = d["marks"].get(cat), hh["marks"].get(cat)
            if a is None and b is None:
                continue
            g = ag[(rel, cat)]
            if a is None or b is None:
                g[2][0] += 1
            elif a == b:
                g[0].append(o)
            elif a in ("c", "b", "x") or b in ("c", "b", "x"):
                g[2][0] += 1
            else:
                g[1].append(o)
        pr[(hh["lexeme"], rel, d["lexeme"])].append(o)

    def side(k):
        b, a = og[k]
        return (b, a) if len(b) >= len(a) else (a, b)
    out["orders"] = emit("orders", sorted(og), lambda k: {"rel": k[0], "head_class": k[1], "dep_class": k[2],
                                                           "before": len(og[k][0]), "after": len(og[k][1])},
                         lambda k: side(k)[0], lambda k: side(k)[1], exc)
    ak = sorted(k for k, g in ag.items() if len(g[0]) + len(g[1]) >= 1)
    out["agreement"] = emit("agreement", ak, lambda k: {"rel": k[0], "category": k[1], "agree": len(ag[k][0]),
                                                         "differ": len(ag[k][1]), "n_a": ag[k][2][0]},
                            lambda k: ag[k][0], lambda k: ag[k][1], exc)
    pk = sorted(k for k, v in pr.items() if len(v) >= 2)
    out["pairs"] = emit("pairs", pk, lambda k: {"head": k[0], "rel": k[1], "dep": k[2]}, lambda k: pr[k],
                        lambda k: [], exc)
    K, KS = E.K, E.KS
    cons = C.defaultdict(list)
    for i, k in enumerate(KS["clause"]):
        prep = KS["prep"][i] if KS["own_basis"][i] != "model" else ""
        cons[k].append((KS["ord"][i], KS["role"][i], KS["head"][i], prep))
    fr = C.defaultdict(list)
    for i, k in enumerate(K["clause"]):
        pred = K["pred"][i]
        if K["pred_kind"][i] != "v" or not pred or pred not in stem:
            continue
        sp = stem[pred]
        parts = sorted(cons.get(k, []))
        pv = [x for x in parts if x[1] == "v" and x[2] == pred]
        skip = pv[0][0] if pv else None
        roles = []
        for o, role, hd, prep in parts:
            if o == skip:
                continue
            roles.append((f"pp:{prep}" if prep else "pp") if role == "pp" else role)
        fr[(sp["lexeme"], sp["marks"].get("stem", ""), " ".join(sorted(roles)))].append(((K["first"][i], i), k))
    out["frames"] = emit("frames", sorted(fr), lambda k: {"lexeme": k[0], "stem": k[1], "frame": k[2]},
                         lambda k: fr[k], lambda k: [], exc)
    out["clause_links"] = emit("clause_links", [], None, None, None, exc)
    return out, exc


# ---- D43 --------------------------------------------------------------------------------------------------------------

def lexemes(E, lexicon):
    ed = E.ed
    per = C.defaultdict(list)
    for t in E.ts:
        for p in E.parts[t]:
            per[p["lexeme"]].append((t, p))
    rows = []
    for lx in sorted(per):
        ps = per[lx]
        der = [x for x in ps if x[1]["basis"] == "derived"]
        base = der or ps
        cc = C.Counter(p["class"] for _, p in base)
        top = max(cc.values())
        cls = min(k for k, v in cc.items() if v == top)
        L = lexicon.get(lx, {})
        f0 = min((t, p["n"]) for t, p in base)
        rows.append({"lexeme": lx, "lemma": L.get("lemma", ""), "strong": L.get("strong", ""), "class": cls,
                     "count": str(len(der)), "forms": str(len({norm_form(ed, p["text"]) for _, p in base})),
                     "books": str(len({E.wby[t]["book"] for t, _ in base})), "senses": "", "domains": "",
                     "first": f"{f0[0]}.{f0[1]}", "count_model": str(len(ps) - len(der))})
    return rows


def participants(E, G, to_hbo, catch):
    gpart = {r["ent"]: r for r in tsv(os.path.join(E.outdir, "grc", "participants.tsv"))}
    strict, model = C.defaultdict(set), C.defaultdict(set)
    named = C.defaultdict(C.Counter)
    for t in E.ts:
        for p in E.parts[t]:
            wv = E.whov.get((t, p["n"]))
            if not wv:
                continue
            for e in wv[0].split():
                (model if p["basis"] == "model" else strict)[e].add(t)
                if p["basis"] != "model" and p["kind"] == "stem" and p["class"] in ("noun", "adj") and p["lemma"] \
                        and unicodedata.normalize("NFC", p["lemma"]) != "הַ":
                    named[e][unicodedata.normalize("NFC", p["lemma"])] += 1
    sc, mc = set(strict), set(model)
    for i in range(len(E.K["clause"])):
        for col in ("speaker", "addressee"):
            sc.update(E.K[col][i].split())
        for col in ("speaker_model", "addressee_model"):
            if E.K[col][i]:
                mc.update(E.K[col][i].split())
    for v in E.A["who"]:
        sc.update(v.split())
    rows = []
    unnamed = 0
    for e in sorted(sc | mc):
        g = gpart.get(e)
        if g is None:
            raise SystemExit(f"{E.ed}: participant {e} not in grc/participants.tsv")
        name = ""
        if e not in catch and named.get(e):
            top = max(named[e].values())
            name = min(k for k, v in named[e].items() if v == top)
        unnamed += not name
        rows.append({"ent": e, "type": to_hbo[("ent_type", e.split(":")[0])], "name": name,
                     "name_basis": "derived" if name else "", "sex": g["sex"], "words": str(len(strict.get(e, ()))),
                     "words_model": str(len(model.get(e, ()))), "ent_basis": "given" if e in sc else "model"})
    E.c["D43 participants unnamed"] = unnamed
    return rows


def facts(E, G, prows):
    ents = {r["ent"] for r in prows if r["ent_basis"] == "given"}
    out = []
    per = C.defaultdict(C.Counter)
    tot = C.Counter()
    for t in E.ts:
        for p in E.parts[t]:
            per[(p["lexeme"], p["basis"])][p["class"]] += 1
            tot[(p["lexeme"], p["basis"])] += 1
    for (lx, b), cc in sorted(per.items()):
        for cl, n in sorted(cc.items()):
            out.append({"subject": lx, "relation": "has_class", "object": cl, "kind": b, "method": "pieces.class",
                        "source": "hebrew-nt-analysis", "confidence": None, "count": n, "share": n / tot[(lx, b)],
                        "tier": ""})
    for r in G.facts:
        if r["subject"] in ents and r["object"] in ents and r["relation"] in (
                "father", "mother", "offspring", "sibling", "partner", "tribe", "group_origin"):
            out.append(dict(r))
    rn = C.Counter()
    lt = C.Counter()
    for t in E.ts:
        st = E.stem[t]
        for g in sorted(E.h2g.get(t, ())):
            rn[(st["lexeme"], G.p[g]["lexeme"], "model" if st["basis"] == "model" else "linked")] += 1
            lt[st["lexeme"]] += 1
    for (a, b, k), n in sorted(rn.items()):
        out.append({"subject": a, "relation": "renders", "object": b, "kind": k, "method": "links",
                    "source": "lexeme-aligner", "confidence": None, "count": n, "share": n / lt[a], "tier": ""})
    return out


# ---- D44 --------------------------------------------------------------------------------------------------------------

SRC = {"pieces": {"pid", "fused", "sense", "domain", "concept", "concept_by", "clusivity", "clusivity_basis",
                  "noun_rel", "noun_head_t", "noun_head_n"},
       "words": {"after"}, "clauses": {"via", "rule", "pattern", "role_wrapped", "line", "subject_model"},
       "constituents": {"frame_role"}, "lexemes": {"senses", "domains"}}
GIVEN = {"words": {"t", "id", "book", "chapter", "verse", "w", "text"}, "pieces": {"t", "n", "text"},
         "clauses": {"book", "chapter", "verse"}, "who_account": {"t", "n"}}
META = {"clause_basis", "who_basis", "speech_basis", "sem_role_basis", "own_basis", "basis", "name_basis", "ent_basis"}


def empty(v):
    return v is None or v == "" or v == "{}" or v == "[]"


def acc_row(table, col, r, E):
    """-> (state, basis, reason) of one value of an edition table (SPEC D44)."""
    v = r[col]
    if table in SRC and col in SRC[table]:
        return ("not_carried", "", "greek_only" if table in ("clauses", "constituents") else "src")
    if empty(v) and not (table == "clauses" and col == "pred") and not (table in ("pieces",) and col in ("head_t", "head_n")):
        if col in ("head", "head_basis", "rel", "rel_shared", "from_t") and table == "words":
            return ("not_carried", "", "not_one_to_one")
        if col in ("head_t", "head_n", "head_basis", "rel") and table == "pieces":
            return ("not_carried", "", "not_stem" if r["kind"] != "stem" else "not_one_to_one")
        if table == "words" and col in ("clause", "clause_basis", "sentence"):
            return ("not_carried", "", "unplaced")
        if table == "constituents" and col == "head":
            return ("not_carried", "", "not_linked")
        if table == "added" and col == "antecedent":
            return ("not_carried", "", "not_linked")
        if table == "pieces" and col == "class":
            return ("not_carried", "", "tagger_dash")
        return ("not_carried", "", "none")
    if col in META:
        return ("own", "derived", "")
    if table in GIVEN and col in GIVEN[table]:
        return ("own", "given", "")
    if table == "words":
        if col == "clause":
            return ("carried", r["clause_basis"], "")
        if col in ("sentence", "head", "rel", "rel_shared", "from_t"):
            return ("carried", "linked", "")
        if col == "head_basis":
            return ("carried", "derived", "")
    if table == "pieces":
        if col in ("head_t", "head_n"):
            if v is None:
                return ("not_carried", "", "not_stem" if r["kind"] != "stem" else "not_one_to_one")
            return ("carried", "linked", "")
        if col in ("head_basis", "rel"):
            return ("carried", "linked", "")
        if col == "who":
            return ("carried", r["who_basis"], "")
        if col == "who_from":
            return ("carried", "linked", "")
        return ("own", r["basis"], "")
    if table == "clauses":
        if col == "pred" and not v:
            return ("not_carried", "", "not_linked")
        if col in ("quote_model", "speaker_model", "addressee_model"):
            return ("carried", "model", "")
        if col == "marks_model":
            return ("own", "model", "")
        if col in ("clause", "first", "last", "gaps", "words"):
            return ("carried", "derived", "")
        if col == "shared":
            return ("own", "derived", "")
        return ("carried", "linked", "")
    if table == "constituents":
        if col in ("class", "prep", "ref_form"):
            return ("own", r["own_basis"], "")
        if col in ("clause", "ord", "first", "last"):
            return ("carried", "derived", "")
        return ("carried", "linked", "")
    if table == "added":
        if col in ("kind", "form") or (col in ("person", "number", "gender") and r["form"] == "ending"):
            return ("own", r["own_basis"], "")
        if col == "clause":
            return ("carried", "derived", "")
        return ("carried", "linked", "")
    if table == "who_account":
        if col in ("state", "reason"):
            if r["from_t"] is not None and r["state"] not in ("participant", "generic", "not_referring", "unresolved", "no_row"):
                return ("carried", "linked", "")
            return ("own", r["basis"], "")
        if col == "from_t":
            return ("carried", "linked", "")
        return ("own", r["basis"], "")
    if table == "passages":
        if col in ("first_clause", "last_clause", "clauses", "crossing", "passage"):
            return ("own", "derived", "")
        return ("carried", "linked", "")
    if table == "links":
        return ("carried", r["basis"], "")
    return ("own", "derived", "")


def account(E, tabs, gside):
    acc = C.Counter()
    for table, rows in tabs.items():
        cols = list(rows[0].keys()) if rows else []
        for col in cols:
            for r in rows:
                if table == "clauses" and col == "marks":
                    m = json.loads(r["marks"])
                    for key in sorted(MARK_KEYS):
                        if key in m:
                            st = ("own", "derived", "") if key in ("connective", "negator") else \
                                ("carried", "derived" if key == "time_abs" else "linked", "")
                        elif key in NOT_CARRIED:
                            st = ("not_carried", "", "greek_form_key")
                        else:
                            st = ("not_carried", "", "none")
                        acc[(table, f"marks.{key}") + st] += 1
                    continue
                if table == "pieces" and col == "marks":
                    m = json.loads(r["marks"])
                    for key in PIECE_CATS:
                        st = ("own", r["basis"], "") if key in m else ("not_carried", "", "none")
                        acc[(table, f"marks.{key}") + st] += 1
                    continue
                acc[(table, col) + acc_row(table, col, r, E)] += 1
    for k, n in gside.items():
        acc[k] += n
    return acc


MARK_KEYS = ("relation", "time", "aspect", "line_kind", "mood", "force", "polarity", "time_abs", "connective",
             "negator", "kind", "voice", "transitivity", "subject_form", "subject_switch", "fronted", "neg_scope")
NOT_CARRIED = ("kind", "voice", "transitivity", "subject_form", "subject_switch", "fronted", "neg_scope")
PIECE_CATS = ("type", "stem", "person", "gender", "number", "state")


def greek_side(E, G):
    """The Greek rows each carried column could be carried from: carried, or not_carried with a reason."""
    a = C.Counter()
    # clauses
    for r in G.clauses:
        k = r["clause"]
        on = k in E.key
        m = json.loads(r["marks"])
        for key in sorted(m):
            if key in ("connective", "negator"):
                continue
            st = ("not_carried", "", "greek_form_key") if key in NOT_CARRIED else \
                (("carried", "linked", "") if on else ("not_carried", "", "empty_clause"))
            a[("grc/clauses", f"marks.{key}") + st] += 1
        for col in ("role", "quote", "speaker", "addressee", "quote_model", "speaker_model", "addressee_model"):
            if empty(r[col]):
                continue
            a[("grc/clauses", col) + (("carried", "model" if col.endswith("_model") else "linked", "") if on
                                      else ("not_carried", "", "empty_clause"))] += 1
        if r["pred"]:
            st = ("not_carried", "", "empty_clause") if not on else \
                (("carried", "linked", "") if E.pred.get(k) else ("not_carried", "", "not_linked"))
            a[("grc/clauses", "pred") + st] += 1
        for col in ("via", "rule", "pattern", "role_wrapped", "line", "subject_model"):
            if not empty(r[col]):
                a[("grc/clauses", col, "not_carried", "", "greek_only")] += 1
        a[("grc/clauses", "clause") + (("carried", "derived", "") if on else ("not_carried", "", "empty_clause"))] += 1
    # words: the clause of a word, the head
    for r in G.words:
        g = r["t"]
        a[("grc/words", "head") + (("carried", "linked", "") if g in E.g_one else
                                   ("not_carried", "", "not_linked" if g not in E.g2h else "not_one_to_one"))] += 1
    # pieces: who
    came = set()
    for (t, n), (v, g, rule) in E.whov.items():
        came.add(g)
        if rule == "a":
            for x in E.h2g[t]:
                if G.p[x]["who"] == v:
                    came.add(x)
    for g, p in G.p.items():
        if not p["who"]:
            continue
        if g in came:
            st = ("carried", "linked", "")
        elif g in E.g2h:
            two = any(len({G.p[x]["who"] for x in E.h2g[t] if G.p[x]["who"]}) > 1 for t in E.g2h[g])
            st = ("not_carried", "", "two_values" if two else "stem_class")
        elif p["class"] == "pron":
            st = ("not_carried", "", "no_host_suffix")
        else:
            st = ("not_carried", "", "not_linked")
        a[("grc/pieces", "who") + st] += 1
    # constituents
    taken = {(r["from_ord"], r["clause"]) for r in E.cons_rows}
    keyrev = {v: k for k, v in E.key.items()}
    took = {(keyrev[r["clause"]], r["from_ord"]) for r in E.cons_rows}
    hd = {(keyrev[r["clause"]], r["from_ord"]): r["head"] for r in E.cons_rows}
    for r in G.cons:
        k = (r["clause"], r["ord"])
        on = k in took
        why = "empty_clause" if r["clause"] not in E.key else "not_linked"
        for col in ("role", "sem_role", "ref_status", "head"):
            if empty(r[col]):
                continue
            if col == "head":
                st = ("carried", "linked", "") if on and hd[k] is not None else ("not_carried", "", why if not on else "not_linked")
            else:
                st = ("carried", "linked", "") if on else ("not_carried", "", why)
            a[("grc/constituents", col) + st] += 1
    # added
    tk = {(r["from_clause"], r["from_t"], r["role"]) for r in E.added_rows}
    for r in G.added:
        on = (r["clause"], r["verb"], r["role"]) in tk
        why = "not_linked" if E.lfirst(r["verb"]) is None else ("unplaced" if not E.place_.get(E.lfirst(r["verb"], True)) else "key_taken")
        for col in ("role", "where", "who", "who_reason", "antecedent"):
            if empty(r[col]):
                continue
            a[("grc/added", col) + (("carried", "linked", "") if on else ("not_carried", "", why))] += 1
    # who_account
    used = {x for x in E.wa["from_t"] if x is not None}
    for g in G.acc:
        a[("grc/who_account", "state") + (("carried", "linked", "") if g in used else ("not_carried", "", "not_linked"))] += 1
    # passages
    fp = set(E.PS["from_passage"])
    for r in G.passages:
        a[("grc/passages", "passage") + (("carried", "linked", "") if r["passage"] in fp else ("not_carried", "", "not_linked"))] += 1
    return a


# ---- D44 differ --------------------------------------------------------------------------------------------------------

def differ(eds):
    sets = {}
    for ed, E in eds.items():
        d = {}
        for g, ss in E.g2h.items():
            lx, md = {}, False
            for s in ss:
                for p in E.parts[s]:
                    if p["class"] in ("noun", "verb", "adj", "adv"):
                        lx.setdefault(s, set()).add(p["lexeme"])
            if lx:
                d[g] = lx
        sets[ed] = d
    rows = {ed: [] for ed in eds}
    stc = C.Counter()
    for g in sorted(set(sets["heb_mod"]) | set(sets["heb_scg"])):
        a, b = sets["heb_mod"].get(g), sets["heb_scg"].get(g)
        if not a or not b:
            stc["one edition only"] += 1
            continue
        A = set().union(*a.values())
        B = set().union(*b.values())
        mdl = any(p["basis"] == "model" for ed, x in (("heb_mod", a), ("heb_scg", b)) for s in x for p in eds[ed].parts[s])
        if A == B:
            stc[f"same {'model' if mdl else 'derived'}"] += 1
            continue
        st = "overlap" if A & B else "disjoint"
        stc[f"{st} {'model' if mdl else 'derived'}"] += 1
        for ed, mine, other, oed in (("heb_mod", a, b, "heb_scg"), ("heb_scg", b, a, "heb_mod")):
            for s in sorted(mine):
                for o in sorted(other):
                    bm = any(p["basis"] == "model" for p in eds[ed].parts[s]) or \
                        any(p["basis"] == "model" for p in eds[oed].parts[o])
                    rows[ed].append({"from_t": g, "t": s, "lexemes": X.jdump(sorted(mine[s])), "other": oed,
                                     "other_t": o, "other_lexemes": X.jdump(sorted(other[o])), "state": st,
                                     "basis": "model" if bm else "derived"})
    return rows, stc


DIFFER_SCHEMA = pa.schema([("from_t", I_), ("t", I_), ("lexemes", S_), ("other", S_), ("other_t", I_),
                           ("other_lexemes", S_), ("state", S_), ("basis", S_)])


# ---- writing ----------------------------------------------------------------------------------------------------------

def write_tsv(path, header, rows):
    X.write_tsv(path, header, [[r[h] for h in header] for r in rows])


def build_rest(outdir, eds, G, to_code, to_hbo, catch, shas, counts, ex):
    import examples_v17doc2 as D2
    lexicon = {r["lexeme"]: r for r in tsv(os.path.join(outdir, "lexicon", "lexemes.tsv"))}
    drows, dstc = differ(eds)
    counts["D44 differ: Greek pieces by state and basis"] = dict(sorted(dstc.items()))
    for ed, E in eds.items():
        E.outdir = outdir
        d = os.path.join(outdir, ed)
        lr = lexemes(E, lexicon)
        write_tsv(os.path.join(d, "lexemes.tsv"), ["lexeme", "lemma", "strong", "class", "count", "forms", "books",
                                                   "senses", "domains", "first", "count_model"], lr)
        prow = participants(E, G, to_hbo, catch)
        write_tsv(os.path.join(d, "participants.tsv"), ["ent", "type", "name", "name_basis", "sex", "words",
                                                        "words_model", "ent_basis"], prow)
        fr = facts(E, G, prow)
        fs = pq.read_schema(os.path.join(outdir, "grc", "facts.parquet"))
        X.write_parquet(os.path.join(d, "facts.parquet"), {f.name: [r[f.name] for r in fr] for f in fs}, fs)
        st, exc = statements(E, lr)
        for name, cols in st.items():
            X.write_parquet(os.path.join(d, f"{name}.parquet"), cols, pa.schema(STAT[name]))
        X.write_parquet(os.path.join(d, "exceptions.parquet"), {"statement": [a for a, _ in exc], "place": [b for _, b in exc]},
                        pa.schema([("statement", S_), ("place", S_)]))
        for f in ("terms.tsv", "terms-notes.md"):
            shutil.copyfile(os.path.join(outdir, "hbo", f), os.path.join(d, f))
        X.write_tsv(os.path.join(d, "source_errors.tsv"), ["rule", "source", "place", "value", "count"], [])
        X.write_parquet(os.path.join(d, "differ.parquet"),
                        {f.name: [r[f.name] for r in drows[ed]] for f in DIFFER_SCHEMA}, DIFFER_SCHEMA)
        D2.map_relmap(E, G, outdir, d)
        tabs = {"words": pq.read_table(os.path.join(d, "words.parquet")).to_pylist(),
                "pieces": pq.read_table(os.path.join(d, "pieces.parquet")).to_pylist(),
                "clauses": pq.read_table(os.path.join(d, "clauses.parquet")).to_pylist(),
                "constituents": pq.read_table(os.path.join(d, "constituents.parquet")).to_pylist(),
                "added": pq.read_table(os.path.join(d, "added.parquet")).to_pylist(),
                "who_account": pq.read_table(os.path.join(d, "who_account.parquet")).to_pylist(),
                "passages": pq.read_table(os.path.join(d, "passages.parquet")).to_pylist(),
                "links": pq.read_table(os.path.join(d, "links.parquet")).to_pylist(),
                "link_account": pq.read_table(os.path.join(d, "link_account.parquet")).to_pylist()}
        from examples_v17 import tick
        tick(f"{ed} files before the account")
        acc = account(E, tabs, greek_side(E, G))
        tick(f"{ed} account")
        X.write_tsv(os.path.join(d, "carry_account.tsv"), ["table", "column", "state", "basis", "reason", "count"],
                    [list(k) + [str(n)] for k, n in sorted(acc.items())])
        D2.categories(E, d, tabs, lr, prow, fr, acc, drows[ed], to_hbo)
        from examples_shared11 import build_profile
        build_profile("hbo", d, E.c)
        D2.docs(E, d, outdir, shas, drows[ed], lexicon, counts)
        counts[f"D43-D44 {ed}"] = dict(sorted((k, v) for k, v in E.c.items() if k.startswith(("D43", "hbo profile"))))
    D2.sheets(eds, G, outdir, lexicon)
    from examples_v17 import tick
    tick("sheets")
