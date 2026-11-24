"""Stage 49 (SPEC 1.7), part 3: map.tsv, relmap.tsv, categories.toml, sources.json, COLUMNS.md, READ-FIRST.md of the
two edition folders, and the reader's sheets (glossed-i1/: the chapters per edition and carry-sample.md).
Called by examples_v17doc.build_rest. Nothing here makes a value of a table.
"""
import collections as C
import hashlib
import json
import os
import re
import sys

import pyarrow as pa
import pyarrow.parquet as pq

import examples_common as X
import examples_v17doc as D

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


# ---- map.tsv, relmap.tsv ----------------------------------------------------------------------------------------------

def map_relmap(E, G, outdir, d):
    M = D.read_map(outdir)
    hterm = {}
    for r in D.tsv(D.TERMS):
        hterm[(r["category"], r["hbo"])] = r["code"]
    use = C.Counter()
    for t in E.ts:
        for p in E.parts[t]:
            if p["class"]:
                use[("pieces", "class", p["class"])] += 1
            for cat, code in p["marks"].items():
                use[("pieces", cat, code)] += 1
    for i in range(len(E.K["clause"])):
        for src in (E.K["marks"][i], E.K["marks_model"][i]):
            if not src:
                continue
            for key, v in json.loads(src).items():
                if key in ("connective",):
                    for lx in v:
                        use[("clauses", key, lx)] += 1
                elif key in ("relation", "time", "aspect", "line_kind", "mood", "time_abs"):
                    use[("clauses", key, hterm[("time" if key == "time_abs" else key, v)])] += 1
                else:
                    use[("clauses", key, v)] += 1
    for i in range(len(E.KS["clause"])):
        if E.KS["ref_form"][i]:
            use[("constituents", "ref_form", E.KS["ref_form"][i])] += 1
        if E.KS["ref_status"][i]:
            use[("constituents", "ref_status", hterm[("ref_status", E.KS["ref_status"][i])])] += 1
    for i in range(len(E.A["clause"])):
        use[("added", "form", E.A["form"][i])] += 1
        use[("added", "kind", hterm[("added_kind", E.A["kind"][i])])] += 1
    rows, missing = [], []
    for k in sorted(use):
        rs = M.get(k)
        if not rs:
            missing.append(k)
            same = {(r["feature"], r["reason"]) for kk, v in M.items() if kk[:2] == k[:2] for r in v}
            # the category's one row kind in hbo's map (connective: none, lexeme_value), else not_in_hbo_map
            rs = [{"feature": "none", "value": "", "reason": next(iter(same))[1]}] if len(same) == 1 and \
                next(iter(same))[0] == "none" else [{"feature": "none", "value": "", "reason": "not_in_hbo_map"}]
        for r in rs:
            rows.append([k[0], k[1], k[2], r["feature"], r["value"], r["reason"], str(use[k])])
    E.c["D43 map.tsv codes not in hbo's map.tsv"] = len(missing)
    E.ex[f"{E.ed} D43 map.tsv codes not in hbo's map.tsv"] = [" ".join(k) for k in missing]
    X.write_tsv(os.path.join(d, "map.tsv"), ["table", "category", "code", "feature", "value", "reason", "count"], rows)
    gr = {(r["label"], r["class"]): r["shared"] for r in G.relmap}
    ec = C.Counter()
    for t, g in E.one.items():
        if t in E.head:
            ec[(G.w[g]["rel"], G.p[g]["class"])] += 1
    X.write_tsv(os.path.join(d, "relmap.tsv"), ["label", "class", "shared", "count"],
                [[k[0], k[1], gr.get(k, "none"), str(n)] for k, n in sorted(ec.items())])
    E.c["D43 relmap rows"] = len(ec)


# ---- categories.toml --------------------------------------------------------------------------------------------------

M6 = "M6: hebrew-nt-analysis v0.2 (0c9132c3), the tagger trained on MACULA Hebrew (python -m macula.clause_tagger); no human check"
M4 = "M4: the reviewed speech layers of grc (resources/speaker_quotations/nt_review.tsv, agent:claude-opus-5-5:nt-characters-v1), carried as they stand"
M5 = "M5: hebrew-nt-bridge v0.1 (525db08f), Jev-reviewed links (heb_scg)"
CODED = {
    "words": ["head_basis", "rel", "rel_shared", "clause_basis"],
    "pieces": ["kind", "class", "head_basis", "rel", "who_basis", "basis"],
    "clauses": ["role", "pred_kind", "speech_basis"],
    "constituents": ["role", "class", "sem_role", "sem_role_basis", "ref_status", "ref_form", "own_basis"],
    "added": ["role", "kind", "where", "form", "person", "number", "gender", "who_reason", "own_basis"],
    "who_account": ["head_kind", "state", "reason", "basis"],
    "passages": ["source", "kind"],
    "links": ["how", "basis", "agree", "agree_model"],
    "link_account": ["state", "reason", "state_model"],
    "differ": ["other", "state", "basis"],
}
BASIS = {"clause_basis": "linked (D30) / derived (D31)", "basis": "derived / model (M6), the part's basis",
         "own_basis": "derived / model (M6)", "who_basis": "linked / model (M6: the tagger's split chose the piece)",
         "state_model": "model (M5)"}
MEANING = {("constituents", "sem_role"): "sem_role", ("constituents", "ref_status"): "ref_status",
           ("added", "kind"): "added_kind"}


def toml_values(vals, terms=None):
    out = ["values = ["]
    for code, n in sorted(vals.items(), key=lambda kv: str(kv[0])):
        s = f'  {{ code = {X.toml_str(str(code))}, count = {n}'
        if terms is not None and code in terms:
            s += f', term_code = {X.toml_str(terms[code])}'
        out.append(s + " },")
    out.append("]")
    return out


def categories(E, d, tabs, lr, prow, fr, acc, drows, to_hbo):
    hcode = {}
    for r in D.tsv(D.TERMS):
        hcode[(r["category"], r["hbo"])] = r["code"]
    L = [f"# categories.toml of `{E.ed}` (SPEC 1.7, 4.15, D43): every coded column, its values as codes (or terms",
         "# with their code), their counts, the basis and the source. Written by examples_v17doc2.py.", ""]
    tabs = dict(tabs, differ=drows)
    for table, cols in CODED.items():
        for col in cols:
            vals = C.Counter(r[col] for r in tabs[table] if not D.empty(r[col]))
            cat = MEANING.get((table, col))
            L += [f"[{table}.{col}]", f'column = "{col}"',
                  f'basis = {X.toml_str(BASIS.get(col, "as SPEC 4.15 gives the column"))}',
                  f'source = {X.toml_str("terms.tsv (hbo term of the code)" if cat else "SPEC 1.7 4.15 and D29 to D44")}']
            L += toml_values(vals, {v: hcode.get((cat, v), "") for v in vals} if cat else None)
            if col in ("basis", "own_basis", "who_basis") or (table == "links" and col == "basis"):
                L.append(f'model = {X.toml_str(M5 if table == "links" else M6)}')
            L.append("")
    pc = C.defaultdict(C.Counter)
    for r in tabs["pieces"]:
        for k, v in json.loads(r["marks"]).items():
            pc[k][v] += 1
    for k in sorted(pc):
        L += [f"[pieces.{k}]", 'column = "marks"', 'basis = "given (D36 a, the analysis) / derived (D36 b, the Tanakh '
              'lookup); model where the part\'s basis is model (M6)"',
              f'source = {X.toml_str("hebrew-nt-analysis v0.2 form, person" if k in ("type", "person") else "the build hbo, arc pieces (D36 b)")}',
              f'model = {X.toml_str(M6)}']
        L += toml_values(pc[k]) + [""]
    cc = C.defaultdict(C.Counter)
    for r in tabs["clauses"]:
        for src in ("marks", "marks_model"):
            if r[src]:
                for k, v in json.loads(r[src]).items():
                    cc[(src, k)][json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v] += 1
    for (src, k) in sorted(cc):
        cat = "time" if k == "time_abs" else k
        L += [f"[clauses.{src}.{k}]", f'column = "{src}"',
              f'basis = {X.toml_str("model (M6: read off a model part)" if src == "marks_model" else "own, derived (D37 c)" if k in ("connective", "negator") else "derived (D16 over the carried tree)" if k == "time_abs" else "linked (D37 a)")}',
              f'kind = {X.toml_str("form" if k in ("force", "polarity", "connective", "negator") else "reading")}']
        if src == "marks_model":
            L.append(f'model = {X.toml_str(M6)}')
        L += toml_values(cc[(src, k)], {v: hcode.get((cat, v), "") for v in cc[(src, k)]}
                         if k in ("relation", "time", "aspect", "line_kind", "mood", "time_abs") else None) + [""]
    for col in ("quote_model", "speaker_model", "addressee_model"):
        n = sum(1 for r in tabs["clauses"] if r[col] is not None)
        L += [f"[clauses.{col}]", f'column = "{col}"', 'basis = "model (M4), carried as it stands"',
              f'model = {X.toml_str(M4)}', f"rows = {n}", ""]
    for col, vals in (("type", C.Counter(r["type"] for r in prow)), ("name_basis", C.Counter(r["name_basis"] for r in prow if r["name_basis"])),
                      ("ent_basis", C.Counter(r["ent_basis"] for r in prow))):
        L += [f"[participants.{col}]", f'column = "{col}"', 'basis = "D43"']
        L += toml_values(vals, {v: hcode.get(("ent_type", v), "") for v in vals} if col == "type" else None) + [""]
    L += ["[facts.relation]", 'column = "relation"', 'basis = "D43"'] + toml_values(C.Counter(r["relation"] for r in fr)) + [""]
    L += ["[facts.kind]", 'column = "kind"', 'basis = "D43"', f'model = {X.toml_str(M6)}'] + \
        toml_values(C.Counter(r["kind"] for r in fr)) + [""]
    L += ["[facts.source]", 'column = "source"', 'basis = "D43"'] + toml_values(C.Counter(r["source"] for r in fr)) + [""]
    L += ["[facts.method]", 'column = "method"', 'basis = "D43"'] + toml_values(C.Counter(r["method"] for r in fr)) + [""]
    for col in ("table", "column", "state", "basis", "reason"):
        i = ("table", "column", "state", "basis", "reason").index(col)
        vals = C.Counter()
        for k, n in acc.items():
            if k[i]:
                vals[k[i]] += 1
        L += [f"[carry_account.{col}]", f'column = "{col}"', 'basis = "D44"'] + toml_values(vals) + [""]
    for tb, cols in (("markers", ("kind", "category", "value")), ("orders", ("rel", "head_class", "dep_class")),
                     ("agreement", ("rel", "category")), ("pairs", ("rel",)), ("frames", ("stem", "frame")),
                     ("paradigms", ("class",))):
        rows = pq.read_table(os.path.join(d, f"{tb}.parquet"), columns=list(cols)).to_pylist()
        for col in cols:
            L += [f"[{tb}.{col}]", f'column = "{col}"', 'basis = "counted over the strict view (section 7)"']
            if col in ("rel", "frame"):
                L += [f'pattern = {X.toml_str("grc/words.rel labels, carried by D33" if col == "rel" else "constituent role codes and pp:<lexeme>, separated by a space")}',
                      f"distinct = {len({r[col] for r in rows})}"]
                if col == "frame":
                    L.append("")
                    continue
            L += toml_values(C.Counter(r[col] for r in rows)) + [""]
    L += ["[lexemes.class]", 'column = "class"', 'basis = "D43"'] + toml_values(C.Counter(r["class"] for r in lr)) + [""]
    L += ["[profile.value]", 'column = "value"', 'basis = "derived"', 'values = [', '  { code = "0" },', '  { code = "1" },',
          '  { code = "?" },', "]", ""]
    L += ["[model.M6]", f'what = {X.toml_str(M6)}', 'dataset = "hebrew-nt-analysis"', 'version = "v0.2"',
          'revision = "0c9132c3"', 'columns = "every value whose basis, own_basis or who_basis is model; pieces of basis model; marks_model"', "",
          "[model.M4]", f'what = {X.toml_str(M4)}', 'columns = "clauses.quote_model, speaker_model, addressee_model"', ""]
    if E.ed == "heb_scg":
        L += ["[model.M5]", f'what = {X.toml_str(M5)}', 'columns = "links rows of basis model; link_account.state_model"', ""]
    X.write_text(os.path.join(d, "categories.toml"), "\n".join(L).rstrip("\n") + "\n")


# ---- sources.json, COLUMNS.md, READ-FIRST.md -------------------------------------------------------------------------

def spec_section(start, stop):
    text = open(D.SPEC, encoding="utf-8").read()
    i = text.index(start)
    j = text.index(stop, i)
    return text[i:j].rstrip() + "\n"


def docs(E, d, outdir, shas, drows, lexicon, counts):
    import pyarrow
    import examples_v18 as V18M
    V18 = getattr(X, "V18", False)     # SPEC 1.8 (stage 52)
    gs = json.load(open(os.path.join(outdir, "grc", "sources.json"), encoding="utf-8"))
    ls = json.load(open(os.path.join(outdir, "lexicon", "sources.json"), encoding="utf-8"))
    read = {}
    for rel in ["grc/words.parquet", "grc/pieces.parquet", "grc/clauses.parquet", "grc/constituents.parquet",
                "grc/added.parquet", "grc/who_account.parquet", "grc/passages.parquet", "grc/links.parquet",
                "grc/facts.parquet", "grc/participants.tsv", "grc/relmap.tsv", f"other/{E.ed}/words.parquet",
                f"other/{E.ed}/parts.parquet", "lexicon/lexemes.tsv", "hbo/words.parquet", "hbo/pieces.parquet",
                "arc/words.parquet", "arc/pieces.parquet", "hbo/map.tsv", "hbo/terms.tsv", "hbo/terms-notes.md"]:
        if V18:     # SPEC 1.8 section 13: built anew in this build, not copied
            read[rel] = {"sha256": shas[rel], "path": f"shoresh/macula/data/source-examples/<build>/{rel}"}
        else:
            read[rel] = {"sha256": shas[rel], "h1_path": f"shoresh/macula/data/source-examples/h1/{rel}"}
    ana = os.path.join(D.ROOT, "internal-docs/hebrew-nt-analysis-release/v0.2", E.ed, "words.parquet")
    builders = {}
    for f in ("build_examples.py", "examples_v17.py", "examples_v17doc.py", "examples_v17doc2.py", "examples_shared11.py") + (
            ("examples_v18.py", "hebrew_nt_level1_fixes.py", "hebrew_nt_strong_fixes.py") if V18 else ()):
        builders[f"shoresh/macula/{f}"] = {"sha256": D.sha(os.path.join(HERE, f)), "committed": False}
    model = {"hebrew-nt-analysis": dict(ls["model"]["hebrew-nt-analysis"], basis="model (M6)",
                                        columns=["pieces rows of basis model (kind, lexeme, class, marks, shared)",
                                                 "pieces.who_basis model", "constituents.own_basis model",
                                                 "added.own_basis model", "who_account.basis model",
                                                 "clauses.marks_model", "lexemes.count_model",
                                                 "facts rows of kind model", "differ rows of basis model"])}
    for k, v in gs["model"].items():
        if "reviewed" in k:
            model[k] = dict(v, columns=["clauses.quote_model", "clauses.speaker_model", "clauses.addressee_model"],
                            carried="carried from grc as it stands (4.15)")
    if E.ed == "heb_scg":
        for k, v in gs["model"].items():
            if "bridge" in k:
                model[k] = dict(v, columns=["links rows of basis model", "link_account.state_model"])
    doc = {"language": E.ed,
           "specification": {"version": ("1.9" if getattr(X, "V19", False) else "1.8") if V18 else "1.7", "sha256": D.sha(D.SPEC)},
           "description": "a description of a translation (SPEC 4.15): the edition's own words and analysis, the grc "
                          "description carried through the strict word links (linked), rules D29 to D44",
           "read": read,
           "sources": {"hebrew-nt-analysis v0.2": {"file": os.path.relpath(ana, D.ROOT), "sha256": D.sha(ana),
                                                   "columns": ["form", "person"], "revision": "0c9132c3"},
                       "terms": {"file": "internal-docs/source-examples-spec/terms.tsv", "sha256": D.sha(D.TERMS)},
                       "entities": {"file": "shoresh/macula/data/entities/entities.tsv",
                                    "sha256": D.sha(os.path.join(HERE, "data/entities/entities.tsv")),
                                    "columns": ["entity (the catch-all ids, 4.5)"]},
                       "lexeme-aligner": {"through": "grc/links.parquet rows of basis linked (compact alignments, as grc/sources.json names them)"},
                       "acai": {"through": "grc/pieces.who, grc/facts.parquet kin rows"},
                       **({"fix tables (1.8, M3)": {"files": V18M.fix_pins(), "applied": "hebrew_nt_level1_fixes.apply, "
                           "then hebrew_nt_strong_fixes.apply, on every read of hebrew-nt-analysis words (D14 in 1.8)"}}
                          if V18 else {})},
           "model": model,
           "not_read": ["hebrew-nt-analysis role and clauses.parquet (the tagger's parse)", "data/hebrew-nt-morph/",
                        "hebrew-nt-part-links", "hebrew-nt-bridge as a carrier"],
           "licence": "as each source of grc states (MACULA CC BY 4.0; ACAI, our datasets CC BY-SA 4.0); the editions' texts public domain (helloao)",
           "builder": {"entry": "shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build <build> --stage "
                                + (("55" if getattr(X, "V19", False) else "52") if V18 else "49"),
                       "files": builders,
                       "commit": gs["builder"].get("commit", ""), "note": "the stage 49 modules are not committed; their sha256 names them"},
           "pyarrow": pyarrow.__version__, "python": sys.version.split()[0]}
    with open(os.path.join(d, "sources.json"), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    # COLUMNS.md
    L = [f"# COLUMNS: `{E.ed}`", "", "Written by `examples_v17doc2.py` (stage " + (("55" if getattr(X, "V19", False) else "52") if V18 else "49") + "). The text of SPEC "
         + (("1.9" if getattr(X, "V19", False) else "1.8") if V18 else "1.7") + " section 4.15, then the "
         "columns of every file as read from the file. The Greek lexeme keys stand only as the objects of `renders` "
         "rows of `facts.parquet` (`AGENT-FORMAT.md` 5); `from_*` columns and `links.s` name Greek places by key.", ""]
    L.append(spec_section("### 4.15 `heb_mod/`", "## 5. Sources"))
    L += ["", "## The files, column by column", ""]
    for f in sorted(os.listdir(d)):
        p = os.path.join(d, f)
        if f.endswith(".parquet"):
            s = pq.read_schema(p)
            L.append(f"- `{f}` ({pq.read_metadata(p).num_rows:,} rows): " + ", ".join(f"`{x.name}` {x.type}" for x in s))
        elif f.endswith(".tsv"):
            with open(p, encoding="utf-8") as fh:
                L.append(f"- `{f}`: " + ", ".join(f"`{x}`" for x in fh.readline().rstrip("\n").split("\t")))
    X.write_text(os.path.join(d, "COLUMNS.md"), "\n".join(L) + "\n")
    # READ-FIRST.md
    c = E.c
    n = len(E.ts)
    dis = C.Counter()
    for r in drows:
        if r["state"] == "disjoint" and r["basis"] == "derived":
            a = " ".join(lexicon.get(x, {}).get("lemma", x) for x in json.loads(r["lexemes"]))
            b = " ".join(lexicon.get(x, {}).get("lemma", x) for x in json.loads(r["other_lexemes"]))
            dis[(a, b)] += 1
    pb = C.Counter(p["basis"] for t in E.ts for p in E.parts[t])
    L = [f"# READ FIRST: `{E.ed}`, a description of a translation (SPEC {('1.9' if getattr(X, 'V19', False) else '1.8') if V18 else '1.7'})", "",
         "## 1. What this folder is", "",
         f"The Hebrew of {'Delitzsch' if E.ed == 'heb_mod' else 'Salkinson and Ginsburg'}'s New Testament in the tables of a "
         "language folder. Every value comes from the edition itself (its tokens and `hebrew-nt-analysis` v0.2), from "
         "the Greek description `grc/` carried through the strict word links (`linked`), or from a rule over both (D29 "
         "to D44). No Hebrew tree, clause or role was parsed: the clauses, heads, roles and referents are the Greek's, "
         "carried. `carry_account.tsv` says, per table and column, what came, on which basis, and what did not and why.", "",
         "## 2. Normal ranges (this build)", "",
         f"- words {n:,}; pieces {sum(pb.values()):,} (derived {pb['derived']:,}, model {pb['model']:,});",
         f"- words with a strict link {c['D29 words with a strict link']:,} ({100 * c['D29 words with a strict link'] / n:.1f}%), one-to-one {c['D29 one-to-one words']:,};",
         f"- words in a clause {c['placement words in a clause']:,} ({100 * c['placement words in a clause'] / n:.1f}%); unplaced {c['placement N4']:,};",
         f"- carried clauses {c['clauses carried']:,}: one unbroken run {c['clauses one unbroken run']:,}, with gaps {c['clauses with gaps']:,}; empty Greek clauses {c['clauses empty (Greek clauses with no placed word)']:,};",
         f"- heads: direct {c['D33 direct']:,}, through an ancestor {c['D33 ancestor']:,}, root {c['D33 root, Greek root'] + c['D33 root, no one-to-one ancestor']:,}, none {c['D33 no head']:,};",
         f"- who: (a) {c['D34 pieces with who by (a)']:,}, (b) {c['D34 pieces with who by (b)']:,}, (c) {c['D34 pieces with who by (c)']:,} pieces.", "",
         "## 3. What is `model`, and how much", "",
         f"The tagger's analysis (M6) stands under {pb['model']:,} of {sum(pb.values()):,} pieces ({100 * pb['model'] / sum(pb.values()):.1f}%): "
         "their `kind`, `lexeme`, `class`, `marks`, `shared` are model values (`basis` `model`), and so is every value a "
         "rule reads off them (`who_basis`, `own_basis`, `who_account.basis` `model`, `clauses.marks_model`). The strict "
         "view empties them. The reviewed speech columns (`*_model`, M4) are carried from `grc` as they stand."
         + (" The `heb_scg` model links (M5) stand in `links.parquet` as `model` rows and carry nothing." if E.ed == "heb_scg" else ""), "",
         "## 4. What is empty, and the commonest disjoint pairs", "",
         "- `constructions.parquet` and `clause_links.parquet` have no row: there is no node tree and no clause `kind` "
         "in an edition (D43).",
         "- `orders`, `agreement`, `pairs` and the `profile.tsv` answers that read them rest on D33's edges: the edge is "
         "the Greek's, the order of the two words and their classes and marks are the edition's.",
         "- The columns 4.15 calls empty (MACULA, UBS and the examples' own sources) are empty on every row.", "",
         "The 20 commonest pairs of lemmas where the two editions render one Greek word by disjoint content lexemes, "
         "on derived parts only (`differ.parquet`; this edition first, the other second):", ""]
    for (a, b), k in sorted(dis.items(), key=lambda kv: (-kv[1], kv[0]))[:20]:
        L.append(f"- {a} / {b}: {k:,}")
    X.write_text(os.path.join(d, "READ-FIRST.md"), "\n".join(L) + "\n")


# ---- the reader's sheets ----------------------------------------------------------------------------------------------

def pick(items, n=20, first=5):
    if len(items) <= n:
        return list(items)
    rest = items[first:]
    k = max(1, (len(rest)) // (n - first))
    return list(items[:first]) + rest[::k][:n - first]


def cell(s):
    return str(s).replace("|", "\\|") if s not in (None, "") else ""


def sheets(eds, G, outdir, lexicon):
    dirs = [os.path.join(outdir, "cache", "glossed")]
    if os.path.basename(os.path.normpath(outdir)) == "i1":
        dirs.append(D.GLOSSED_I1)
    files = {}
    for ed, E in eds.items():
        K = {E.K["clause"][i]: i for i in range(len(E.K["clause"]))}
        role_on = C.defaultdict(list)
        for r in E.cons_rows:
            if r["head"]:
                role_on[r["head"]].append(r)
        ann = {}
        for i in range(len(E.wa["t"])):
            ann[(E.wa["t"][i], E.wa["n"][i])] = (E.wa["state"][i], E.wa["reason"][i])
        added = C.defaultdict(list)
        for r in E.added_rows:
            added[r["verb"]].append(r)
        for book, ch, name in D.CHAPTERS:
            L = [f"# {book} {ch} ({ed}): the carried description, part by part", "",
                 "Written by `build_examples.py --stage 49` (`examples_v17doc2.py`) from the tables of `" + ed + "`. For the "
                 "reader only: a sheet is not data. One table per verse, one row per part (`pieces.parquet`): `t.n`, the "
                 "Hebrew part and its word, `kind`, the lexeme key, `class`, `marks`; `clause`: the word's carried clause, "
                 "numbered in the verse (`[n]`), with `L` where D30 placed it through a link and `D` where D31 placed it by "
                 "its neighbours; `head`: the word it depends on (D33) with `head_basis`; `role`: on the head word of a "
                 "carried part of a clause, its role, `sem=` its semantic role and `ref=` its reference status (Hebrew "
                 "terms) and `form=` (`ref_form`); `who`: the participant carried (D34, with the rule) and its name; "
                 "`account`: the referring head's state (D40); `Greek`: the Greek word(s) the word renders (strict links; "
                 "`m:` a model link), for the reader only; `basis`: every `linked` and `model` value of the row. Under each "
                 "verse its clauses (carried marks as Hebrew terms, the own connective and negator, speech) and the added "
                 "rows. No gloss.", ""]
            vs = sorted({(E.wby[t]["verse"]) for t in E.ts if E.wby[t]["book"] == book and E.wby[t]["chapter"] == ch})
            for v in vs:
                ts = [t for t in E.byverse.get((book, ch, v), [])]
                L += [f"## {book} {ch}:{v}", "",
                      "| t.n | word | part | kind | lexeme | class | marks | clause | head | role | who | account | Greek | basis |",
                      "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
                cnum = {}
                for t in ts:
                    k = E.place_.get(t)
                    if k and E.key[k] not in cnum:
                        cnum[E.key[k]] = len(cnum) + 1
                for t in ts:
                    k = E.place_.get(t)
                    ck = E.key[k] if k else ""
                    hd = E.head.get(t)
                    gk = " ".join(G.w[g]["text"] for g in sorted(E.h2g.get(t, ())))
                    if E.mlinks.get(t):
                        gk += (" " if gk else "") + "m:" + " ".join(G.w[g]["text"] for g in sorted(E.mlinks[t]))
                    for p in E.parts[t]:
                        bs = []
                        stem = p["kind"] == "stem"
                        if p["basis"] == "model":
                            bs.append("model:part")
                        if stem and ck:
                            bs.append("linked:clause" if E.case[t].startswith("D30") else "derived:clause")
                        hcell = ""
                        if stem and hd:
                            hcell = "root" if hd[0] == 0 else f"{hd[0]} {E.wby[hd[0]]['text']}"
                            hcell += f" ({hd[1]})"
                            bs.append("linked:head")
                        rc = ""
                        if stem and t in role_on:
                            rc = "; ".join(r["role"] + (f" · sem={r['sem_role']}" if r["sem_role"] else "") +
                                           (f" · ref={r['ref_status']}" if r["ref_status"] else "") +
                                           (f" · form={r['ref_form']}" if r["ref_form"] else "") for r in role_on[t])
                            bs.append("linked:role")
                        wv = E.whov.get((t, p["n"]))
                        wc = ""
                        if wv:
                            wc = f"`{wv[0]}` ({wv[2]})"
                            bs.append(("model" if p["basis"] == "model" else "linked") + ":who")
                        ac = ann.get((t, p["n"]))
                        acs = f"{ac[0]}" + (f" ({ac[1]})" if ac and ac[1] else "") if ac else ""
                        L.append("| " + " | ".join(cell(x) for x in (
                            f"{t}.{p['n']}", E.wby[t]["text"] if p["n"] == 1 else "", p["text"], p["kind"], p["lexeme"],
                            p["class"], " ".join(f"{a}={b}" for a, b in sorted(p["marks"].items())),
                            f"[{cnum[ck]}]" if ck and stem else "", hcell, rc, wc, acs, gk if stem else "",
                            " ".join(bs))) + " |")
                L.append("")
                if cnum:
                    L += ["| clause | key | role | parent | marks (L carried, own) | own model | speech | from |",
                          "|---|---|---|---|---|---|---|---|"]
                    for ck, i in sorted(cnum.items(), key=lambda kv: kv[1]):
                        j = K[ck]
                        sp = " ".join(x for x in (E.K["quote"][j], E.K["speaker"][j], E.K["addressee"][j]) if x)
                        L.append("| " + " | ".join(cell(x) for x in (
                            f"[{i}]", ck, E.K["role"][j], E.K["parent"][j], E.K["marks"][j], E.K["marks_model"][j] or "",
                            sp, E.K["from_clause"][j])) + " |")
                    L.append("")
                ad = [r for t in ts for r in added.get(t, [])]
                if ad:
                    L += ["Added (not words of the text):", ""]
                    for r in ad:
                        L.append(f"- `+` {r['clause']} verb {r['verb']} {E.wby[r['verb']]['text']}: {r['role']} {r['kind']} "
                                 f"form={r['form']} {r['person']}{r['number']}{r['gender']} who={r['who'] or '-'} "
                                 f"({r['who_reason']}) ant={r['antecedent'] or '-'} own_basis={r['own_basis']}")
                    L.append("")
            files[f"{ed}-{name}.md"] = "\n".join(L).rstrip("\n") + "\n"
    files["carry-sample.md"] = carry_sample(eds, G)
    for dd in dirs:
        os.makedirs(dd, exist_ok=True)
        for f, text in files.items():
            X.write_text(os.path.join(dd, f), text)


def carry_sample(eds, G):
    L = ["# The carry sample (SPEC 1.7, section 14): every rule of D30 to D40, per edition", "",
         "Written by `build_examples.py --stage 49` (`examples_v17doc2.py`). For each rule: its count and a fixed sample "
         "of its places in text order (the first 5, then every k-th, 20 in all), each with the Hebrew word, its verse, "
         "the value the rule gave, and the Greek word(s) of its link for the reader. No gloss.", ""]
    for ed, E in eds.items():
        def gtext(t):
            return " ".join(G.w[g]["text"] for g in sorted(E.h2g.get(t, ())))

        def w(t):
            return f"{t} {E.wby[t]['text']} ({E.ref(t)})"
        rules = []
        for case in ("D30a", "D30b", "D30c", "N1", "N2a", "N2b", "N2c", "N3", "N4"):
            its = [t for t in E.ts if E.case.get(t) == case]
            items = []
            for t in its:
                k = E.place_.get(t)
                pq_ = E.PQ.get(t)
                ctx = ""
                if pq_:
                    ctx = " P=" + (str(pq_[0]) if pq_[0] else "-") + " Q=" + (str(pq_[1]) if pq_[1] else "-")
                items.append(f"{w(t)} -> {E.key[k] if k else '(unplaced)'}{ctx} | Greek {gtext(t) or '-'}")
            rules.append((f"D{'30' if case.startswith('D30') else '31'} {case}", items))
        items = [f"{w(t)} -> head {E.head[t][0]}{' ' + E.wby[E.head[t][0]]['text'] if E.head[t][0] else ''} ({E.head[t][1]}, "
                 f"{G.w[E.one[t]]['rel']}) | Greek {G.w[E.one[t]]['text']}" for t in E.ts if t in E.head]
        rules.append(("D33 heads", items))
        for r_ in ("a", "b", "c"):
            items = [f"{w(t)} piece {t}.{n} {E.parts[t][n - 1]['text']} -> {v} | Greek {G.w[g]['text']} ({g})"
                     for (t, n), (v, g, rr) in sorted(E.whov.items()) if rr == r_]
            rules.append((f"D34 ({r_})", items))
        items = [f"{r['clause']} ord {r['ord']} {r['role']} head {r['head'] or '-'} {E.wby[r['head']]['text'] if r['head'] else ''} "
                 f"span {r['first']}-{r['last']} sem={r['sem_role'] or '-'} ref={r['ref_status'] or '-'} form={r['ref_form'] or '-'}"
                 for r in sorted(E.cons_rows, key=lambda r: (r["first"], r["clause"], r["ord"]))]
        rules.append(("D38 constituents", items))
        items = [f"{w(r['verb'])} {r['role']} {r['kind']} form={r['form']} {r['person']}{r['number']}{r['gender']} "
                 f"ant={r['antecedent'] or '-'} who={r['who'] or '-'}" for r in sorted(E.added_rows, key=lambda r: (r["verb"], r["role"]))]
        rules.append(("D39 added", items))
        items = [f"{E.wa['t'][i]}.{E.wa['n'][i]} {E.parts[E.wa['t'][i]][E.wa['n'][i] - 1]['text']} ({E.ref(E.wa['t'][i])}) "
                 f"{E.wa['head_kind'][i]}: {E.wa['state'][i]}{' (' + E.wa['reason'][i] + ')' if E.wa['reason'][i] else ''}"
                 f" from {E.wa['from_t'][i] or '-'}" for i in range(len(E.wa["t"]))]
        rules.append(("D40 who account", items))
        L += [f"## {ed}", ""]
        for title, items in rules:
            L += [f"### {title}: {len(items):,}", ""]
            L += [f"- {x}" for x in pick(items)]
            L.append("")
    return "\n".join(L).rstrip("\n") + "\n"
