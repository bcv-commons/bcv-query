"""Stage 07 (statements) of the source-examples build, SPEC 1.0: the statement tables of section 4.7 with the queries
of section 7.

Reads per language words.parquet, pieces.parquet, clauses.parquet, constituents.parquet, lexemes.tsv (stages 02-06),
the MACULA node trees (for `constructions`) and, for Greek, MACULA's `normalized` of every word (for the normalised
form). Writes per language forms, paradigms, markers, constructions, orders, agreement, frames, pairs, clause_links
and exceptions (all .parquet). Nothing else is written; counts and exception lists go to cache/stage07-counts.json
(through build_examples.py).

Readings this module takes where section 7 leaves a choice (each is in the stage report, "For the specification"):
- A place is `t.n` (a piece) for forms, paradigms, markers and constructions; `t` (the dependent word) for orders,
  agreement and pairs; the clause key for frames and clause_links. Text order: (t, n); clauses by (first, row order of
  clauses.parquet).
- markers (b): the places of a word marker are the pieces of the lexeme that are the stem of their word.
- constructions: `children` are the `Cat` of the node's direct children (not of the node a unary chain leads to);
  a compound's children are `m` elements without `Cat`, so its `children` is empty. A node's place is its first
  piece (that is a row) in text order; a Tanakh node goes to `arc` when most of its pieces are Aramaic.
- frames: the predicate constituent is the `v` constituent whose `head` is the clause's `pred`; a `pp` whose `prep`
  is empty is written `pp`.
- clause_links: `parent_kind` is `top` where the clause has no parent, the parent's `marks.kind`, or empty.

Stage 18 (SPEC 1.1, `build11`, build c1) runs the same code with `V11` set:
- it reads only the strict columns listed in STRICT_READ_11 (SPEC 2.5; no statement table over an M column);
- markers: the column is `marker`; a `suffix` piece of class `pron` stands as `sfx:<lang>:<person>.<gender>.<number>`
  of its own marks (E5); one without those three marks keeps its lexeme key (counted and listed);
- constructions: at a Hebrew or Aramaic sentence node (the top node, Cat S, no Rule) the head index is the one D2p(d)
  uses (its first CL child, else its first child);
- agreement: codes that differ where one is `c`, `b` or `x` count as `n_a` (E8);
- clause_links: `connective` is `marks.connective` as its JSON array (C10), empty where marks has none.
"""
import collections as C
import json
import os

import pyarrow as pa
import pyarrow.parquet as pq

import examples_common as X
import examples_src as S

AGREE_CATS = ("gender", "number", "person", "case", "state")
CONJ_CATS = {"conj", "cj", "cjp"}       # D2p(a), as stage 03
MARKER_MAX_LEXEMES = 40
MARKER_MIN_PLACES = 20
MARKER_MIN_SHARE = 0.95
TABLES = ("forms", "paradigms", "markers", "constructions", "orders", "agreement", "frames", "pairs", "clause_links")

S_ = pa.string()
I_ = pa.int64()
SCHEMAS = {
    "forms": [("id", S_), ("lexeme", S_), ("marks", S_), ("form", S_), ("count", I_), ("against", I_),
              ("places", S_)],
    "paradigms": [("id", S_), ("class", S_), ("marks", S_), ("lexemes", I_), ("forms", I_), ("count", I_),
                  ("against", I_), ("places", S_)],
    "markers": [("id", S_), ("lexeme", S_), ("kind", S_), ("category", S_), ("value", S_), ("count", I_),
                ("against", I_), ("places", S_)],
    "constructions": [("id", S_), ("level", S_), ("rule", S_), ("children", S_), ("head_at", I_), ("count", I_),
                      ("against", I_), ("places", S_)],
    "orders": [("id", S_), ("rel", S_), ("head_class", S_), ("dep_class", S_), ("before", I_), ("after", I_),
               ("count", I_), ("against", I_), ("places", S_)],
    "agreement": [("id", S_), ("rel", S_), ("category", S_), ("agree", I_), ("differ", I_), ("n_a", I_),
                  ("count", I_), ("against", I_), ("places", S_)],
    "frames": [("id", S_), ("lexeme", S_), ("stem", S_), ("frame", S_), ("count", I_), ("against", I_),
               ("places", S_)],
    "pairs": [("id", S_), ("head", S_), ("rel", S_), ("dep", S_), ("count", I_), ("against", I_), ("places", S_)],
    "clause_links": [("id", S_), ("kind", S_), ("connective", S_), ("parent_kind", S_), ("role", S_),
                     ("count", I_), ("against", I_), ("places", S_)],
}
EXC_SCHEMA = [("statement", S_), ("place", S_)]
# SPEC 1.1 (stage 18): `markers.lexeme` is named `marker` (it holds a lexeme key or an `sfx` key, E5)
SCHEMAS_11 = dict(SCHEMAS, markers=[("marker" if c == "lexeme" else c, t) for c, t in SCHEMAS["markers"]])
# SPEC 1.1, 2.5: statements are counted over the strict columns only. These are the only columns stage 18 reads;
# none of them has basis `model` (no concept, concept_by, who, ..._model, subject_model).
STRICT_READ_11 = {
    "words": ["t", "head", "rel"],
    "pieces": ["t", "n", "pid", "text", "kind", "lexeme", "class", "marks"],
    "clauses": ["clause", "first", "parent", "role", "role_wrapped", "pred", "pred_kind", "marks"],
    "constituents": ["clause", "ord", "role", "head", "prep"],
}
V11 = False   # set by build11 (stage 18)


def read_lang(outdir, lang):
    d = os.path.join(outdir, lang)
    tabs = {t: pq.read_table(os.path.join(d, f"{t}.parquet"),
                             columns=STRICT_READ_11[t] if V11 else None).to_pydict()
            for t in ("words", "pieces", "clauses", "constituents")}
    with open(os.path.join(d, "lexemes.tsv"), encoding="utf-8", newline="") as fh:
        lines = fh.read().split("\n")
    head = lines[0].split("\t")
    tabs["lexemes"] = [dict(zip(head, ln.split("\t"))) for ln in lines[1:] if ln]
    return tabs


# ---- statements: a group key -> places for, places against ----------------------------------------------------

class Groups:
    """Collects, per group key, the places for and against, each with its text-order key."""

    def __init__(self):
        self.pro = C.defaultdict(list)
        self.con = C.defaultdict(list)

    def add(self, key, order, place, against=False):
        (self.con if against else self.pro)[key].append((order, place))


def first3(items):
    return " ".join(p for _, p in sorted(items)[:3])


def emit(name, keys_sorted, row_of, places_for, places_against, exc):
    """Rows of one table in sort order with ids; `row_of(key)` gives the grouping/extra columns (a dict),
    `places_for(key)` and `places_against(key)` lists of (order, place)."""
    cols = {c: [] for c, _ in (SCHEMAS_11 if V11 else SCHEMAS)[name]}
    for i, key in enumerate(keys_sorted, 1):
        sid = f"{name}:{i}"
        pro, con = places_for(key), places_against(key)
        row = row_of(key)
        row.update({"id": sid, "count": len(pro), "against": len(con), "places": first3(pro)})
        for c in cols:
            cols[c].append(row[c])
        for _, p in sorted(con):
            exc.append((sid, p))
    return cols


def write(outdir, lang, name, cols, schema):
    X.write_parquet(os.path.join(outdir, lang, f"{name}.parquet"), cols, pa.schema(schema))


# ---- the word-level view -----------------------------------------------------------------------------------------

def index_lang(T):
    """Per word t: its stem piece's (lexeme, class, marks dict); per piece row its normal fields."""
    P = T["pieces"]
    stem = {}
    for i, t in enumerate(P["t"]):
        if P["kind"][i] == "stem":
            if t in stem:
                raise ValueError(f"word {t} has two stem pieces")
            stem[t] = (P["lexeme"][i], P["class"][i], json.loads(P["marks"][i]), i)
    return stem


def build_lang(lang, T, stems_all, greek_norm, node_rows, cnt, ex):
    """All nine tables of one language. `stems_all`: t -> stem tuple over hbo+arc (or grc). Returns
    (tables dict name -> columns, exceptions list)."""
    W, P, Cl, K, LX = T["words"], T["pieces"], T["clauses"], T["constituents"], T["lexemes"]
    out, exc = {}, []
    porder = [(P["t"][i], P["n"][i]) for i in range(len(P["t"]))]
    pplace = [f"{t}.{n}" for t, n in porder]

    def form_of(i):
        if lang == "grc":
            return X.norm_grc(greek_norm[P["pid"][i]])
        return X.norm_heb(P["text"][i])

    # forms, paradigms -------------------------------------------------------------------------------------------
    fg, pg = C.defaultdict(list), C.defaultdict(list)
    plex, pform = C.defaultdict(set), C.defaultdict(set)
    for i in range(len(P["t"])):
        f = form_of(i)
        fg[(P["lexeme"][i], P["marks"][i], f)].append((porder[i], pplace[i]))
        k = (P["class"][i], P["marks"][i])
        pg[k].append((porder[i], pplace[i]))
        plex[k].add(P["lexeme"][i])
        pform[k].add(f)
    out["forms"] = emit("forms", sorted(fg), lambda k: {"lexeme": k[0], "marks": k[1], "form": k[2]},
                        lambda k: fg[k], lambda k: [], exc)
    out["paradigms"] = emit("paradigms", sorted(pg),
                            lambda k: {"class": k[0], "marks": k[1], "lexemes": len(plex[k]), "forms": len(pform[k])},
                            lambda k: pg[k], lambda k: [], exc)

    # markers -----------------------------------------------------------------------------------------------------
    per_class = C.Counter(r["class"] for r in LX)
    word_markers = {r["lexeme"] for r in LX if per_class[r["class"]] <= MARKER_MAX_LEXEMES}
    cnt[f"{lang} classes with at most {MARKER_MAX_LEXEMES} lexemes"] = sum(
        1 for c, n in per_class.items() if n <= MARKER_MAX_LEXEMES)
    cnt[f"{lang} word-marker lexemes"] = len(word_markers)
    whead = dict(zip(W["t"], W["head"]))
    mk = C.defaultdict(list)       # (lexeme, kind) -> [(order, place, target marks)]
    left_out = 0
    for i in range(len(P["t"])):
        kind, lex, t = P["kind"][i], P["lexeme"][i], P["t"][i]
        if kind in ("prefix", "suffix"):
            marker = lex
            if V11 and kind == "suffix" and P["class"][i] == "pron":
                # E5: a pronoun suffix stands as sfx:<lang>:<person>.<gender>.<number> of its own marks
                own = json.loads(P["marks"][i])
                if all(c in own for c in ("person", "gender", "number")):
                    marker = f"sfx:{lang}:{own['person']}.{own['gender']}.{own['number']}"
                    cnt[f"{lang} markers (a): pronoun suffix pieces as an sfx key"] += 1
                else:
                    cnt[f"{lang} markers (a): pronoun suffix pieces without person, gender, number (lexeme kept)"] += 1
                    ex[f"{lang} markers (a): pronoun suffix pieces without person, gender, number (lexeme kept)"]\
                        .append(f"{pplace[i]} {P['pid'][i]} {lex} {P['marks'][i]}")
            mk[(marker, kind)].append((porder[i], pplace[i], stems_all[t][2]))
        if lex in word_markers:
            if kind != "stem":
                left_out += 1
                continue
            h = whead[t]
            if h == 0:
                cnt[f"{lang} word-marker places at a root (no target)"] += 1
                continue
            mk[(lex, "word")].append((porder[i], pplace[i], stems_all[h][2]))
    cnt[f"{lang} word-marker pieces that are not a stem (not word places)"] = left_out
    mrows = {}
    for (lex, kind), places in mk.items():
        bycat = C.defaultdict(list)
        for order, place, marks in places:
            for cat, code in marks.items():
                bycat[cat].append((order, place, code))
        for cat, items in bycat.items():
            vals = C.Counter(code for _, _, code in items)
            top = max(vals.values())
            value = min(v for v, n in vals.items() if n == top)
            if len(items) >= MARKER_MIN_PLACES and top / len(items) >= MARKER_MIN_SHARE:
                mrows[(lex, kind, cat)] = (value, [(o, p) for o, p, c in items if c == value],
                                           [(o, p) for o, p, c in items if c != value])
            else:
                cnt[f"{lang} marker x category pairs below the threshold"] += 1
    if V11:
        cnt[f"{lang} markers (a): distinct sfx keys"] = len({m for m, k in mk if m.startswith("sfx:")})
    out["markers"] = emit("markers", sorted(mrows),
                          lambda k: {("marker" if V11 else "lexeme"): k[0], "kind": k[1], "category": k[2],
                                     "value": mrows[k][0]},
                          lambda k: mrows[k][1], lambda k: mrows[k][2], exc)

    # constructions -------------------------------------------------------------------------------------------------
    cg = C.defaultdict(list)       # (level, rule, children) -> [(head index, order, place)]
    for level, rule, children, h, order in node_rows:
        cg[(level, rule, children)].append((h, order, f"{order[0]}.{order[1]}"))
    crow = {}
    for k, items in cg.items():
        hs = C.Counter(h for h, _, _ in items)
        top = max(hs.values())
        hat = min(h for h, n in hs.items() if n == top)
        crow[k] = (hat, [(o, p) for h, o, p in items if h == hat], [(o, p) for h, o, p in items if h != hat])
    out["constructions"] = emit("constructions", sorted(crow),
                                lambda k: {"level": k[0], "rule": k[1], "children": k[2], "head_at": crow[k][0]},
                                lambda k: crow[k][1], lambda k: crow[k][2], exc)

    # word edges: orders, agreement, pairs --------------------------------------------------------------------------
    og = C.defaultdict(lambda: ([], []))
    ag = C.defaultdict(lambda: ([], [], [0]))
    pr = C.defaultdict(list)
    for j, t in enumerate(W["t"]):
        h = W["head"][j]
        if h == 0:
            continue
        rel = W["rel"][j]
        dlex, dcls, dmarks, _ = stems_all[t]
        hlex, hcls, hmarks, _ = stems_all[h]
        o = ((t, 0), str(t))
        og[(rel, hcls, dcls)][0 if t < h else 1].append(o)
        for cat in AGREE_CATS:
            a, b = dmarks.get(cat), hmarks.get(cat)
            if a is None and b is None:
                continue
            g = ag[(rel, cat)]
            if a is None or b is None:
                g[2][0] += 1
            elif a == b:
                g[0].append(o)
            elif V11 and (a in ("c", "b", "x") or b in ("c", "b", "x")):
                g[2][0] += 1     # E8: codes differ, but one is c, b or x: n_a
                cnt[f"{lang} agreement: edges with differing codes where one is c, b or x (n_a, E8)"] += 1
            else:
                g[1].append(o)
        pr[(hlex, rel, dlex)].append(o)
        if lang != "grc" and (h in T["_other_t"]):
            cnt[f"{lang} word edges whose head lies in the other Tanakh table"] += 1

    def ord_side(k):
        b, a = og[k]
        return (b, a) if len(b) >= len(a) else (a, b)
    out["orders"] = emit("orders", sorted(og),
                         lambda k: {"rel": k[0], "head_class": k[1], "dep_class": k[2], "before": len(og[k][0]),
                                    "after": len(og[k][1])},
                         lambda k: ord_side(k)[0], lambda k: ord_side(k)[1], exc)
    akeys = sorted(k for k, g in ag.items() if len(g[0]) + len(g[1]) >= 1)
    cnt[f"{lang} agreement groups with agree + differ = 0 (not written)"] = len(ag) - len(akeys)
    out["agreement"] = emit("agreement", akeys,
                            lambda k: {"rel": k[0], "category": k[1], "agree": len(ag[k][0]), "differ": len(ag[k][1]),
                                       "n_a": ag[k][2][0]},
                            lambda k: ag[k][0], lambda k: ag[k][1], exc)
    pkeys = sorted(k for k, v in pr.items() if len(v) >= 2)
    out["pairs"] = emit("pairs", pkeys, lambda k: {"head": k[0], "rel": k[1], "dep": k[2]},
                        lambda k: pr[k], lambda k: [], exc)

    # frames, clause_links -----------------------------------------------------------------------------------------
    corder = {c: (Cl["first"][i], i) for i, c in enumerate(Cl["clause"])}
    cons = C.defaultdict(list)
    for i, c in enumerate(K["clause"]):
        cons[c].append((K["ord"][i], K["role"][i], K["head"][i], K["prep"][i]))
    fr = C.defaultdict(list)
    for i, c in enumerate(Cl["clause"]):
        if Cl["pred_kind"][i] != "v":
            continue
        pred = Cl["pred"][i]
        lex, _, marks, _ = stems_all[pred]
        parts = sorted(cons.get(c, []))
        pv = [x for x in parts if x[1] == "v" and x[2] == pred]
        if not pv:
            cnt[f"{lang} frames: clauses with no v constituent headed by pred"] += 1
            ex[f"{lang} frames: clauses with no v constituent headed by pred"].append(c)
        if len(pv) > 1:
            cnt[f"{lang} frames: clauses with two v constituents headed by pred (first taken)"] += 1
        skip = pv[0][0] if pv else None
        roles = []
        for o, role, hd, prep in parts:
            if o == skip:
                continue
            if role == "pp":
                if prep:
                    roles.append(f"pp:{prep}")
                else:
                    roles.append("pp")
                    cnt[f"{lang} frames: pp constituents with no prep (written pp)"] += 1
            else:
                roles.append(role)
        key = (lex, marks.get("stem", ""), " ".join(sorted(roles)))
        fr[key].append((corder[c], c))
    out["frames"] = emit("frames", sorted(fr), lambda k: {"lexeme": k[0], "stem": k[1], "frame": k[2]},
                         lambda k: fr[k], lambda k: [], exc)

    kind_of = T["_kind_of"]
    cl = C.defaultdict(list)
    for i, c in enumerate(Cl["clause"]):
        m = json.loads(Cl["marks"][i])
        par = Cl["parent"][i]
        pk = "top" if par == "" else kind_of[par]
        role = Cl["role"][i] or Cl["role_wrapped"][i]
        if V11:
            # C10: the connective as its JSON array; empty where marks has no connective
            if "connective" in m:
                conn = json.dumps(m["connective"], ensure_ascii=False, separators=(",", ":"))
            else:
                conn = ""
                cnt[f"{lang} clause_links: clauses with no marks.connective (connective empty)"] += 1
        else:
            conn = " ".join(m.get("connective", []))
        key = (m.get("kind", ""), conn, pk, role)
        cl[key].append((corder[c], c))
        if par and par not in corder:
            cnt[f"{lang} clause_links: parent in the other Tanakh table"] += 1
    out["clause_links"] = emit("clause_links", sorted(cl),
                               lambda k: {"kind": k[0], "connective": k[1], "parent_kind": k[2], "role": k[3]},
                               lambda k: cl[k], lambda k: [], exc)
    return out, exc


# ---- node rows for constructions ---------------------------------------------------------------------------------

def node_rows(trees, place_of, lang_of_pid, cnt, ex, tag):
    """Every branching node (a node with two or more Node children, or a compound with two or more m) ->
    (lang, level, rule, children, head index, order of its first row piece)."""
    rows = []
    for _, sents in trees:
        for sref, tops, nodes, leafcat in sents:
            agg = [None] * len(nodes)       # (min order, aramaic pieces, row pieces)
            order, stack = [], list(tops)
            while stack:
                i = stack.pop()
                order.append(i)
                if nodes[i][4] == "n":
                    stack.extend(nodes[i][3])
            for i in reversed(order):
                cat, rule, head, kids, kind = nodes[i]
                if kind in ("w", "c"):
                    ps = [place_of[p] for p in kids if p in place_of]
                    na = sum(1 for p in kids if p in place_of and lang_of_pid[p] == "arc")
                    agg[i] = (min(ps) if ps else None, na, len(ps))
                else:
                    ms = [agg[k][0] for k in kids if agg[k][0] is not None]
                    agg[i] = (min(ms) if ms else None, sum(agg[k][1] for k in kids), sum(agg[k][2] for k in kids))
                if kind == "w":
                    continue
                if kind == "c":
                    if len(kids) < 2:
                        cnt[f"{tag} compounds with one m (not branching)"] += 1
                        continue
                    level = "clause" if cat == "CL" else "phrase"
                    rows.append((agg[i], level, "compound", "", 0))
                    cnt[f"{tag} constructions: compounds (children empty: m has no Cat)"] += 1
                    continue
                if len(kids) < 2:
                    continue
                kc = [nodes[k][0] for k in kids]
                if any(c is None for c in kc):
                    cnt[f"{tag} constructions: children without Cat"] += 1
                children = " ".join((c or "").lower() for c in kc)
                if V11 and tag == "tan" and i == tops[0] and cat == "S" and rule is None:
                    # D2p(d): the head index used at a sentence node is its first CL child, else its first child
                    h = kc.index("CL") if "CL" in kc else 0
                    cnt[f"{tag} constructions: sentence nodes, head index by D2p(d)"] += 1
                    if h != int(head if head is not None else 0):
                        cnt[f"{tag} constructions: sentence nodes whose D2p(d) index differs from Head"] += 1
                elif head is not None:
                    h = int(head)
                else:
                    conj = [j for j, c in enumerate(kc) if c in CONJ_CATS]
                    if len(kids) == 2 and len(conj) == 1:
                        h = 1 - conj[0]
                    else:
                        h = -1
                        cnt[f"{tag} constructions: nodes with no head index (D2p c)"] += 1
                if rule is not None:
                    r = rule
                elif head is not None:
                    r = "run"
                else:
                    r = ""
                    cnt[f"{tag} constructions: nodes with neither Rule nor Head"] += 1
                level = "clause" if cat == "CL" else "phrase"
                rows.append((agg[i], level, r, children, h))
    out = C.defaultdict(list)
    for (mn, na, nt), level, r, children, h in rows:
        if mn is None:
            cnt[f"{tag} constructions: nodes with no row piece"] += 1
            ex[f"{tag} constructions: nodes with no row piece"].append(f"{level} {r} {children}")
            continue
        lang = "grc" if tag == "grc" else ("arc" if 2 * na > nt else "hbo")
        if tag != "grc" and 0 < na < nt:
            cnt[f"{tag} constructions: nodes with pieces of both languages"] += 1
        out[lang].append((level, r, children, h, mn))
    return out


# ---- build -------------------------------------------------------------------------------------------------------

def build(outdir, langs, counts):
    ex = C.defaultdict(list)
    cnt = C.Counter()
    groups = []
    if {"hbo", "arc"} & set(langs):
        if not {"hbo", "arc"} <= set(langs):
            raise SystemExit("stage 07: hbo and arc are built together (heads and parents cross them)")
        groups.append(("hbo", "arc"))
    if "grc" in langs:
        groups.append(("grc",))
    for gl in groups:
        T = {lang: read_lang(outdir, lang) for lang in gl}
        stems_all, place_of, lang_of_pid = {}, {}, {}
        for lang in gl:
            stems_all.update(index_lang(T[lang]))
            P = T[lang]["pieces"]
            for i, pid in enumerate(P["pid"]):
                place_of[pid] = (P["t"][i], P["n"][i])
                lang_of_pid[pid] = lang
        kind_of = {}
        for lang in gl:
            Cl = T[lang]["clauses"]
            for c, m in zip(Cl["clause"], Cl["marks"]):
                kind_of[c] = json.loads(m).get("kind", "")
        for lang in gl:
            T[lang]["_kind_of"] = kind_of
            T[lang]["_other_t"] = set().union(*[set(T[o]["words"]["t"]) for o in gl if o != lang]) \
                if len(gl) > 1 else set()
        if gl == ("grc",):
            greek_norm = {p["id"]: p["normalized"] for _, _, sents in S.grc_lowfat() for ps, _ in sents for p in ps}
            nrows = node_rows(S.grc_trees(), place_of, lang_of_pid, cnt, ex, "grc")
        else:
            greek_norm = None
            nrows = node_rows(S.heb_trees(), place_of, lang_of_pid, cnt, ex, "tan")
        for lang in gl:
            tabs, exc = build_lang(lang, T[lang], stems_all, greek_norm, nrows[lang], cnt, ex)
            for name in TABLES:
                write(outdir, lang, name, tabs[name], (SCHEMAS_11 if V11 else SCHEMAS)[name])
                cnt[f"{lang} {name} rows"] = len(tabs[name]["id"])
                cnt[f"{lang} {name} against (sum)"] = sum(tabs[name]["against"])
            write(outdir, lang, "exceptions", {"statement": [s for s, _ in exc], "place": [p for _, p in exc]},
                  EXC_SCHEMA)
            cnt[f"{lang} exceptions rows"] = len(exc)
    for k in sorted(cnt):
        counts[k] = cnt[k]
    return ex


def build11(outdir, langs, counts):
    """Stage 18 (SPEC 1.1): the statement tables over the strict columns of a c build (E5, E8, C10, D2p d)."""
    global V11
    V11 = True
    try:
        return build(outdir, langs, counts)
    finally:
        V11 = False
