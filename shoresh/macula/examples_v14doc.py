"""SPEC 1.4 (stage 32): the documents of <build>/lexicon/ (SAMPLE.md by D28, COLUMNS.md, READ-FIRST.md,
categories.toml, sources.json), the declarations of D24a in arc/, and the reader's sample of 40 groups
(glossed-f1/equivalents-sample.md for f1, <build>/cache/reader-sample/ for any other build). Called by examples_v14.build
after the tables are written; reads only the build's own files and the specification."""
import collections as C
import csv
import json
import os
import re

import pyarrow.parquet as pq

import examples_common as X
import examples_v14 as V

LANGS = ("hbo", "arc", "grc")


def tq(s):
    return json.dumps(s, ensure_ascii=False)


def _lex(L):
    return V.tsv(os.path.join(L, "lexemes.tsv"))


def _pq(path):
    return pq.read_table(path).to_pylist()


def _groups(rows):
    g = C.defaultdict(list)
    for r in rows:
        g[r["group"]].append(r)
    return g


# ---- D28: SAMPLE.md ------------------------------------------------------------------------------------------------

def sample_selection(G):
    """D28: [(section code, [group keys])]."""
    strict = sorted(k for k, v in G.items() if v[0]["basis"] == "derived")
    model = sorted(k for k, v in G.items() if v[0]["basis"] == "model")
    anch = [k for k in strict if G[k][0]["anchor"]]
    top = sorted(anch, key=lambda k: (-sum(r["count"] for r in G[k]), k))[:20]
    tenth = [strict[i] for i in range(9, len(strict), 10)]
    d26 = [k for k in strict if any(r["joined_by"] == "aramaic_list" for r in G[k])]
    d26 = sorted(d26, key=lambda k: (-sum(r["count"] for r in G[k] if r["joined_by"] == "aramaic_list" and
                                          r["lexeme"].startswith("lex:arc:")), k))[:10]
    mtop = sorted(model, key=lambda k: (-sum(r["count"] for r in G[k]), k))[:5]
    if not V15():
        return [("top_places", top), ("every_tenth", tenth), ("aramaic_list", d26), ("model_places", mtop)]
    # SPEC 1.5 D28: the groups with a member joined under the floor, the loose groups, the aramaic_cognate groups
    import examples_v15b as V15B
    under = sorted(k for k in strict if any(r["lexeme"] in V15B.UNDER for r in G[k]))
    loose = sorted(k for k in strict if any(r["ubs_depth"] is not None and r["ubs_depth"] < 3 for r in G[k]))
    cog = [k for k in strict if any(r["joined_by"] == "aramaic_cognate" for r in G[k])]
    cog = sorted(cog, key=lambda k: (-sum(r["count"] for r in G[k] if r["joined_by"] == "aramaic_cognate" and
                                          r["lexeme"].startswith("lex:arc:")), k))[:10]
    return [("top_places", top), ("every_tenth", tenth), ("aramaic_list", d26), ("aramaic_cognate", cog),
            ("under_floor", under), ("loose", loose), ("model_places", mtop)]


def V15():
    return getattr(X, "V15", False)


def V16():
    return getattr(X, "V16", False)


def BNAME():
    """The build these documents name: h1 (SPEC 1.6, stage 38), g1 (1.5, stage 35), f1 (1.4, stage 32)."""
    return ("j1", "52", "1.8") if getattr(X, "V18", False) else ("h1", "38", "1.6") if V16() else ("g1", "35", "1.5") if V15() else ("f1", "32", "1.4")


def sample16(lex):
    """SPEC 1.6 D28: every member step 2b takes out (step2b_out), and every kept_out lexeme with the group or head of
    its anchor and class. Codes and keys only (no English), as the other sections."""
    import examples_v15b as V15B
    rec = V15B.STEP2B["cg"]
    lx = {r["lexeme"]: r for r in lex}
    out = [f"## step2b_out ({len(rec['out'])})", "",
           "| member | lemma | head | head_lemma | group | ubs_depth | share | weak_by | lacks | state |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for k in sorted(rec["out"]):
        r = rec["out"][k]
        out.append(f"| {k} | {lx[k]['lemma']} | {r['head']} | {lx[r['head']]['lemma']} | {r['group']} | "
                   f"{'-' if r['ubs_depth'] is None else r['ubs_depth']} | {r['share']:.4f} | "
                   f"{'under_floor' if r['why'] == 'under the floor' else 'loose'} | sept_number nt_editions same_strong | "
                   f"{lx[k]['state']} |")
    out.append("")
    by_ac = {}
    for r in lex:
        if r["state"] == "member" and r["group"].startswith("cg:") and r["anchor"]:
            by_ac.setdefault((r["anchor"], r["class"]), set()).add(r["group"])
    dis = {(a, cl): (k, h) for k, (h, a, cl) in rec["dissolved"].items()}
    kept = sorted(r["lexeme"] for r in lex if r["state"] == "kept_out")
    out += [f"## kept_out ({len(kept)})", "",
            "| lexeme | lemma | anchor | class | group | dissolved_head |", "|---|---|---|---|---|---|"]
    for k in kept:
        r = lx[k]
        gs = " ".join(sorted(by_ac.get((r["anchor"], r["class"]), ())))
        d = dis.get((r["anchor"], r["class"]))
        out.append(f"| {k} | {r['lemma']} | {r['anchor']} | {r['class']} | {gs or '-'} | "
                   f"{(d[1] + ' ' + lx[d[1]]['lemma']) if d else '-'} |")
    out.append("")
    return out


def sample_md(L):
    lex = {r["lexeme"]: r for r in _lex(L)}
    G = _groups(_pq(os.path.join(L, "groups.parquet")))
    pairs = C.defaultdict(list)
    for r in _pq(os.path.join(L, "pairs.parquet")):
        pairs[(r["a"], r["b"])].append(r)
    out = ["# lexicon/SAMPLE.md", "", "D28", ""]
    for code, keys in sample_selection(G):
        out += [f"## {code} ({len(keys)})", ""]
        for k in keys:
            rows = sorted(G[k], key=lambda r: r["lexeme"])
            out += [f"### {k}", "", f"anchor `{rows[0]['anchor']}` · joined_by "
                    + " ".join(sorted({r['joined_by'] for r in rows})) + f" · basis {rows[0]['basis']}", "",
                    "| head | lemma | lang | tanakh | heb_mod | heb_scg | count | against | same_strong |"
                    + (" joined_by | ubs_depth | senses_out |" if V15() else ""),
                    "|---|---|---|---|---|---|---|---|---|" + ("---|---|---|" if V15() else "")]
            for r in rows:
                x = lex[r["lexeme"]]
                out.append(f"| {'*' if r['head'] else ''} | {x['lemma']} | {x['lang']} | {x['tanakh']} | {x['heb_mod']} | "
                           f"{x['heb_scg']} | {r['count']} | {r['against']} | {len(json.loads(r['same_strong']))} |"
                           + (f" {r['joined_by']} | {'-' if r['ubs_depth'] is None else r['ubs_depth']} | "
                              f"{'-' if r['senses_out'] is None else ' '.join(json.loads(r['senses_out'])) or '[]'} |"
                              if V15() else ""))
            mem = [r["lexeme"] for r in rows]
            pr = []
            for i in range(len(mem)):
                for j in range(i + 1, len(mem)):
                    a, b = sorted((mem[i], mem[j]))
                    for p in pairs.get((a, b), []):
                        pr.append(f"| {lex[a]['lemma']} | {lex[b]['lemma']} | {p['evidence']} | {p['basis']} | "
                                  f"{p['count']} | {p['a_other']} | {p['b_other']} |")
            out += ["", "| a | b | evidence | basis | count | a_other | b_other |", "|---|---|---|---|---|---|---|"]
            out += sorted(pr) if pr else ["| | | | | | | |"]
            out.append("")
    if V16():
        out += sample16(list(lex.values()))
    return "\n".join(out).rstrip("\n") + "\n"


# ---- the reader's sample (stage 32's brief) ------------------------------------------------------------------------

def reader_sample(outdir, L):
    lex = {r["lexeme"]: r for r in _lex(L)}
    G = _groups(_pq(os.path.join(L, "groups.parquet")))
    strict = sorted(k for k, v in G.items() if v[0]["basis"] == "derived")
    n = len(strict)
    pick = [strict[(k * n) // 40] for k in range(40)] if n >= 40 else strict
    want = {r["lexeme"] for k in pick for r in G[k]}
    # Tanakh places: the first two pieces of each member, with their word
    W = {}
    for lang in ("hbo", "arc"):
        for r in pq.read_table(os.path.join(outdir, lang, "words.parquet"), columns=["t", "book", "chapter", "verse", "text"]).to_pylist():
            W[r["t"]] = r
    tp = C.defaultdict(list)
    for lang in ("hbo", "arc"):
        for r in pq.read_table(os.path.join(outdir, lang, "pieces.parquet"), columns=["t", "n", "lexeme"]).to_pylist():
            if r["lexeme"] in want and len(tp[r["lexeme"]]) < 2:
                tp[r["lexeme"]].append((r["t"], r["n"]))
    npl = C.defaultdict(list)
    for ed in V.EDS:
        OW = {r["s"]: r for r in pq.read_table(os.path.join(outdir, "other", ed, "words.parquet"),
                                               columns=["s", "book", "chapter", "verse", "text"]).to_pylist()}
        seen = C.Counter()
        for r in pq.read_table(os.path.join(outdir, "other", ed, "parts.parquet"), columns=["s", "p", "lexeme", "basis"]).to_pylist():
            if r["lexeme"] in want and r["basis"] == "derived" and seen[r["lexeme"]] < 2:
                seen[r["lexeme"]] += 1
                w = OW[r["s"]]
                npl[r["lexeme"]].append(f"{ed}:{r['s']}.{r['p']} {w['book']} {w['chapter']}:{w['verse']} {w['text']}")
    pairs = C.defaultdict(list)
    for r in _pq(os.path.join(L, "pairs.parquet")):
        if r["a"] in want and r["b"] in want:
            pairs[(r["a"], r["b"])].append(r)
    # the same text for every build, so that a rebuild stays byte-equal (as the 1.3 documents do)
    out = [f"# The reader's sample of build {BNAME()[0]}: 40 \"same concept\" groups",
           "",
           f"Written by `build_examples.py --stage {BNAME()[1]}` (`examples_v14doc.py`) from `lexicon/` and the build's tables. "
           f"The rule: the strict groups in key order ({n}), and of them the groups at positions floor(k * {n} / 40), "
           "k = 0 to 39. For each group: its anchor, every member (Tanakh Hebrew `hbo`, Aramaic `arc`) with its pieces "
           "in the Tanakh and its parts in the two Hebrew New Testaments (`heb_mod`, `heb_scg`; `derived` parts, and "
           "the tagger's `model` parts apart), its places under the anchor (`count`) and against it; the first two "
           "Tanakh places and the first two New Testament places of each member, with the written word; and every "
           "`pairs.parquet` row between two members, with its first places. Nothing here is a gloss.", ""]
    for i, k in enumerate(pick, 1):
        rows = sorted(G[k], key=lambda r: (not r["head"], r["lexeme"]))
        out += [f"## {i}. {k}", "", f"anchor `{rows[0]['anchor'] or '-'}`, joined_by "
                + ", ".join(sorted({r['joined_by'] for r in rows})) + f", {len(rows)} members", "",
                "| | lemma | lang | tanakh | heb_mod | heb_scg | heb_mod_model | heb_scg_model | count | against |",
                "|---|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            x = lex[r["lexeme"]]
            out.append(f"| {'head' if r['head'] else ''} | {x['lemma']} | {x['lang']} | {x['tanakh']} | {x['heb_mod']} | "
                       f"{x['heb_scg']} | {x['heb_mod_model']} | {x['heb_scg_model']} | {r['count']} | {r['against']} |")
        out.append("")
        for r in rows:
            x = lex[r["lexeme"]]
            tpl = "; ".join(f"{t}.{nn} {W[t]['book']} {W[t]['chapter']}:{W[t]['verse']} {W[t]['text']}" for t, nn in tp[r["lexeme"]])
            out.append(f"- {x['lemma']} ({x['lang']}): Tanakh {tpl or '-'}; New Testament "
                       + ("; ".join(npl[r["lexeme"]]) or "-"))
        mem = [r["lexeme"] for r in rows]
        pr = []
        for a_ in range(len(mem)):
            for b_ in range(a_ + 1, len(mem)):
                a, b = sorted((mem[a_], mem[b_]))
                for p in pairs.get((a, b), []):
                    pr.append(f"| {lex[a]['lemma']} | {lex[b]['lemma']} | {p['evidence']} | {p['basis']} | {p['count']} | "
                              f"{p['a_other']} | {p['b_other']} | {p['ubs_depth'] if p['ubs_depth'] is not None else '-'} | "
                              f"{p['places']} |")
        out += ["", "| a | b | evidence | basis | count | a_other | b_other | ubs_depth | places |",
                "|---|---|---|---|---|---|---|---|---|"] + (sorted(pr) or ["| (no pair row between members) | | | | | | | | |"])
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n", len(pick)


# ---- categories.toml, sources.json, COLUMNS.md, READ-FIRST.md ------------------------------------------------------

def _values(name, column, basis, cc, extra=()):
    out = [f"[{name}]", f"column = {tq(column)}", f"basis = {tq(basis)}"] + list(extra) + ["values = ["]
    out += [f"  {{ code = {tq(k)}, count = {v} }}," for k, v in sorted(cc.items())]
    return out + ["]", ""]


def _ana_attr():
    import examples_links11 as L11
    return L11.attribution(L11.ANA)


def _glaux_attr():
    import examples_links11 as L11
    return L11.attribution(L11.GLAUX)


def categories(outdir, L):
    lex = _lex(L)
    P = _pq(os.path.join(L, "pairs.parquet"))
    G = _pq(os.path.join(L, "groups.parquet"))
    parts = [r for ed in V.EDS for r in pq.read_table(os.path.join(outdir, "other", ed, "parts.parquet"),
                                                       columns=["class", "key_rule", "basis"]).to_pylist()]
    out = [f"# lexicon/categories.toml: every code of the lexicon folder and of other/heb_*/parts.parquet (SPEC {BNAME()[2]}, 4.14,",
           "# 4.9), with its count; the model columns and rows name their dataset, version and model (SPEC 2.4).", ""]
    out += _values("lexemes.state", "state", "derived (D27)", C.Counter(r["state"] for r in lex))
    out += _values("lexemes.lang", "lang", "given", C.Counter(r["lang"] for r in lex))
    out += _values("lexemes.class", "class", "given (Tanakh keys); the commonest class of the parts (ntx keys)",
                   C.Counter(r["class"] for r in lex))
    out += ["[lexemes.heb_mod_model]", 'column = "heb_mod_model, heb_scg_model"', 'basis = "counted over model rows (M6)"'] + _ana_attr() + [""]
    out += ["[lexemes.group_model]", 'column = "group_model"', 'basis = "model (D25m over the tagger\'s places, M6)"',
            'null = "the empty field: no model group other than the strict one"',
            'empty = "written \\"\\" : the lexeme is in a strict group and in no model group"'] + _ana_attr() + [""]
    out += _values("pairs.evidence", "evidence", "the kind of evidence (D24)", C.Counter(r["evidence"] for r in P))
    out += _values("pairs.basis", "basis", "given (sept_number); linked or model (nt_editions); derived or model (aramaic_list)",
                   C.Counter(r["basis"] for r in P))
    nm = sum(1 for r in P if r["evidence"] == "nt_editions" and r["basis"] == "model")
    am = sum(1 for r in P if r["evidence"] == "aramaic_list" and r["basis"] == "model")
    out += ["[pairs.nt_editions.model]", 'column = "basis"', 'basis = "model where a part of the pair rests on the tagger (M6)"',
            f"count = {nm}"] + _ana_attr() + [""]
    out += ["[pairs.aramaic_list.model]", 'column = "basis"',
            'basis = "model where the list row\'s evidence is greek_verse: GLAUx\'s automatic Strong\'s numbers (D24a, M7)"',
            f"count = {am}"] + _glaux_attr() + [""]
    out += _values("groups.joined_by", "joined_by", "derived (D25, D26)", C.Counter(r["joined_by"] for r in G))
    out += _values("groups.basis", "basis", "derived (D25, D26); model (D25m)", C.Counter(r["basis"] for r in G))
    if V15():     # SPEC 1.5 4.14
        out += _values("groups.ubs_depth", "ubs_depth", "given, counted (UBS domains of the member and the head; "
                       "null on the head and where either has none)",
                       C.Counter("null" if r["ubs_depth"] is None else str(r["ubs_depth"]) for r in G))
        out += _values("groups.senses_out", "senses_out", "derived (D25 1.5 step 5: the member's UBS senses whose own "
                       "anchor is another number; null: no anchor, or no sense with 5 places)",
                       C.Counter("null" if r["senses_out"] is None else "[]" if r["senses_out"] == "[]" else "senses"
                                 for r in G))
    gm = sum(1 for r in G if r["basis"] == "model")
    out += ["[groups.model]", 'column = "basis"', 'basis = "model: D25m with the tagger\'s New Testament places (M6)"',
            f"count = {gm}"] + _ana_attr() + [""]
    out += _values("parts.key_rule", "key_rule", "derived (D23)", C.Counter(r["key_rule"] for r in parts))
    out += _values("parts.basis", "basis", "derived (D14 lookup) / model (M6 tagger), the word's analysis_basis",
                   C.Counter(r["basis"] for r in parts), extra=_ana_attr())
    out += _values("parts.class", "class", "given (hebrew-nt-analysis v0.2 class; `-` written empty)",
                   C.Counter(r["class"] for r in parts))
    return "\n".join(out).rstrip("\n") + "\n"


def sources(outdir, L):
    import examples_links11 as L11
    hs = V.tsv  # noqa
    with open(os.path.join(outdir, "hbo", "sources.json"), encoding="utf-8") as fh:
        hbo = json.load(fh)
    rel = lambda p: os.path.relpath(p, V.ROOT)  # noqa: E731
    lowfat = {rel(p): {"bytes": os.path.getsize(p), "sha256": V.sha(p)} for p in V.SRC.heb_lowfat_files()}
    if lowfat != hbo["sources"]["macula-hebrew"]["files"]:
        raise SystemExit("lexicon sources.json: the lowfat files read are not those hbo/sources.json pins")
    srcs = {
        "macula-hebrew": {"name": "MACULA Hebrew, WLC lowfat trees", "repository": "Clear-Bible/macula-hebrew",
                          "pin": "commit 47db250", "licence": "CC BY 4.0", "basis": "given",
                          "reads": "greekstrong of every w element (D24, D25): the Septuagint word's number MACULA names per piece",
                          "files": lowfat},
        "greek-numbers": {"name": "resources/lxx_bridge_tiers/greek_numbers.tsv", "repository": "bcv-commons/bcv-query",
                          "pin": "sha256", "licence": "CC BY 4.0", "basis": "derived (built by rule from MACULA Hebrew and Greek)",
                          "reads": "D24n: source_strong -> nt_strong", "files": {rel(V.GNUM): V.GNUM_SHA}},
        "hebrew-nt-analysis": {"name": "hebrew-nt-analysis v0.2 words.parquet", "repository": "bcv-commons/hebrew-nt-analysis",
                               "pin": "v0.2 (0c9132c3)", "licence": "CC BY 4.0", "basis": "given; model (M6) where source is model",
                               "reads": "lexeme, lemma, strong, class, text, part, source (D23)",
                               "files": {rel(os.path.join(V.ANA_DIR, ed, "words.parquet")): V.ANA_SHA[ed] for ed in V.EDS}},
        "aramaic-hebrew-equivalents": {"name": "our published Aramaic equivalents list", "pin": "v0.1.1",
                                       "repository": "bcv-commons/bcv-query (aramaic-hebrew-equivalents v0.1.1)",
                                       "licence": "CC BY-SA 4.0",
                                       "basis": "derived; model where the row's evidence is greek_verse (D24a, M7)",
                                       "reads": "hebrew_strong, hebrew_lemma, evidence (pairs.aramaic_list, D26)",
                                       "files": {rel(V.EQUIV): V.EQUIV_SHA}},
        "word-senses-ubs": {"name": "UBS domains, through the language's lexemes.tsv domains", "basis": "given",
                            "reads": "ubs_depth (a check)", "pin": "as hbo/sources.json and arc/sources.json pin it",
                            "licence": "CC BY-SA 4.0", "files": {}},
    }
    a = L11.ANA
    model = {
        "hebrew-nt-analysis": {"repo": a["repo"], "version": a["version"], "revision": a["revision"], "models": a["models"],
                               "run": a["run"], "human_check": L11.NO_HUMAN, "licence": a["licence"], "basis": "model (M6)",
                               "columns": ["other/heb_*/parts.parquet rows with basis model", "lexemes.heb_mod_model, heb_scg_model",
                                           "lexemes.group_model", "pairs rows nt_editions with basis model",
                                           "groups rows with basis model (D25m)"]},
        "glaux": {"dataset": L11.GLAUX["dataset"], "version": L11.GLAUX["version"], "models": L11.GLAUX["models"],
                  "run": L11.GLAUX["run"], "human_check": L11.NO_HUMAN, "licence": L11.GLAUX["licence"], "basis": "model (M7)",
                  "columns": ["pairs rows aramaic_list with basis model (the list's greek_verse evidence, D24a)"]},
    }
    doc = {"language": "lexicon", "builder": hbo["builder"], "python": hbo["python"], "pyarrow": hbo["pyarrow"],
           "specification": hbo["specification"], "sources": srcs, "model": model,
           "build_tables_read": ["hbo/lexemes.tsv", "arc/lexemes.tsv", "hbo/pieces.parquet", "arc/pieces.parquet",
                                 "grc/pieces.parquet", "grc/lexemes.tsv", "grc/links.parquet",
                                 "other/heb_mod/words.parquet", "other/heb_scg/words.parquet"]}
    return json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def spec_section(start, stop):
    with open(os.path.join(V.DOCS, "source-examples-spec/SPEC.md"), encoding="utf-8") as fh:
        text = fh.read()
    i = text.index(start)
    j = text.index(stop, i)
    return text[i:j].rstrip("\n")


def columns_md():
    s414 = spec_section("### 4.14 `lexicon/`", "Expected from `d1`")
    row = [ln for ln in spec_section("### 4.9 Links to another text", "### 4.10").splitlines()
           if ln.startswith("| `other/heb_*/parts.parquet`")]
    return (f"# lexicon/: the columns (SPEC {BNAME()[2]}, 4.14; and other/heb_*/parts.parquet, 4.9)\n\n" + s414 + "\n\n"
            "### other/heb_*/parts.parquet (SPEC 4.9)\n\n| file | content | basis |\n|---|---|---|\n" + "\n".join(row) + "\n\n"
            "### Where this build fills a point the specification leaves open\n\n"
            "- `lexemes.tsv` `group_model`: a TSV field cannot hold null apart from the empty string. Null is the empty "
            "field; the empty string is written `\"\"` (two quotation marks).\n"
            "- `pairs.parquet` `nt_editions`: rows of basis `linked` follow D24 over the parts of basis `derived` only; rows "
            "of basis `model` follow it over all parts, where a part that carries the pair is `model`. `a_other`, "
            "`b_other` are counted in the same view as the row.\n"
            "- `pairs.parquet` `aramaic_list`: `a_other` (the Aramaic side) counts the lexeme's list rows that pick no "
            "Hebrew key or another one; for a `derived` row the `model` rows are left out.\n"
            "- `groups.parquet` for a group that D26 forms: the Hebrew member's `count` is the Aramaic pieces whose list "
            "row picks it, its `against` 0.\n"
            "- D25m runs D25 and then D26 (the `derived` list rows) with the tagger's places added.\n"
            "- A lowfat `greekstrong` that holds two numbers (`1722|1698`) is no Septuagint place.\n")


def read_first(outdir, L, counts):
    lex = _lex(L)
    G = _groups(_pq(os.path.join(L, "groups.parquet")))
    acc = C.Counter((r["lang"], r["state"]) for r in lex)
    big = C.Counter((r["lang"], r["state"]) for r in lex if not r["lexeme"].startswith("ntx:") and int(r["tanakh"]) >= 5)
    out = ["# lexicon/: read first", "",
           f"One Hebrew lexicon for the whole Bible (SPEC {BNAME()[2]}, 4.14): every lexeme key of the Tanakh tables (`hbo`, `arc`) "
           "and of the two Hebrew New Testaments (`other/heb_*/parts.parquet`, D23), with \"same concept\" groups within "
           "Hebrew made by one named rule over counted evidence (D24 to D27). Greek numbers and Greek keys stand only "
           "as evidence (`anchor`, `via`). Built by "
           + (f"`build_examples.py --build {BNAME()[0]} --stage {BNAME()[1]}` (`examples_v14.py`, `examples_v15b.py`, " if V15() else
              "`build_examples.py --build f1 --stage 32` (`examples_v14.py`, ")
           + "`examples_v14doc.py`; a rebuild writes the same text); "
           f"checked by `validate_examples.py --upto {BNAME()[1]}`.", "",
           "Files: `lexemes.tsv` (one row per key, with its state), `pairs.parquet` (the evidence, pair by pair), "
           "`groups.parquet` (one row per member), `SAMPLE.md` (D28), `COLUMNS.md`, `categories.toml`, `sources.json`, "
           "`VALIDATION.md` (written by the validator).", "",
           "Strict view: drop the rows of basis `model` of `pairs.parquet`, `groups.parquet` and `parts.parquet`, set "
           "`heb_mod_model`, `heb_scg_model` to 0 and empty `group_model`.", "",
           "## The account (D27), every key, per lang and state", "",
           "| lang | " + " | ".join(V.STATES) + " | all |", "|---" * (len(V.STATES) + 2) + "|"]
    for lang in ("hbo", "arc"):
        out.append(f"| {lang} | " + " | ".join(str(acc[(lang, s)]) for s in V.STATES) + f" | {sum(v for (l, _), v in acc.items() if l == lang)} |")
    out += ["", "The same over Tanakh lexemes with 5 or more pieces:", "",
            "| lang | " + " | ".join(V.STATES) + " | all |", "|---" * (len(V.STATES) + 2) + "|"]
    for lang in ("hbo", "arc"):
        out.append(f"| {lang} | " + " | ".join(str(big[(lang, s)]) for s in V.STATES) + f" | {sum(v for (l, _), v in big.items() if l == lang)} |")
    strict = [k for k, v in G.items() if v[0]["basis"] == "derived"]
    model = [k for k, v in G.items() if v[0]["basis"] == "model"]
    sz = C.Counter(len(G[k]) for k in strict)
    out += ["", "## Groups", "",
            f"Strict groups: {len(strict)} with {sum(len(G[k]) for k in strict)} members (by size: "
            + ", ".join(f"{n} of {s}" for s, n in sorted(sz.items())) + "); "
            f"{sum(1 for k in strict if any(r['lexeme'].startswith('lex:arc:') for r in G[k]))} with an Aramaic member; "
            f"{sum(1 for k in strict if not G[k][0]['anchor'])} formed by D26. "
            f"Model groups (D25m) whose members differ from every strict group: {len(model)}.", "",
            ("`kept_out` (1.6): anchored, and kept out of the members of its anchor and class by a rule of D25 (the UBS "
             "gate under the floor, or step 2b: a weak join without a second route); read it as `alone` if the reason "
             "does not matter. " if V16() else "")
            + ("`alone`: no other member stands at the lexeme's anchor and class (1.5). " if V15() else
             "`alone` is information too: the concept has one Hebrew word in these texts, so no commoner word stands for it. ")
            + "`spread`: no number holds half of the lexeme's places.", ""]
    if V15():     # SPEC 1.5 4.14 (L9): the loose members, listed
        lexd = {r["lexeme"]: r for r in lex}
        loose = sorted((r["group"], r["lexeme"], r["ubs_depth"]) for k in strict for r in G[k]
                       if r["ubs_depth"] is not None and r["ubs_depth"] < 3)
        out += [f"Loose members (`ubs_depth` to the head under 3): {len(loose)}. Members with no UBS domain (null, not "
                f"the head): {sum(1 for k in strict for r in G[k] if r['ubs_depth'] is None and not r['head'])}.", "",
                "| group | member | lemma | ubs_depth |", "|---|---|---|---|"]
        out += [f"| {g} | {lx} | {lexd[lx]['lemma']} | {d} |" for g, lx, d in loose]
        out += [""]
    if V16():     # SPEC 1.6 D25, D28: the one wrong join left, named
        lexd = {r["lexeme"]: r for r in lex}
        lil = [r for r in lex if r["lang"] == "arc" and r["lemma"] == "לֵילֵי"]
        hod = [r for r in lex if r["lang"] == "hbo" and r["lemma"] == "חֹדֶשׁ"]
        gl_ = lil[0]["group"] if lil else ""
        out += ["Named, not mended (1.6): the D26 join of Aramaic לֵילֵי"
                + (f" (`{lil[0]['lexeme']}`)" if lil else "") + " with Hebrew חֹדֶשׁ"
                + (f" (`{hod[0]['lexeme']}`)" if hod else "") + (f" in `{gl_}`" if gl_ else "")
                + ": the Aramaic list picks חֹדֶשׁ for 3 of the word's 4 pieces, and no rule of the list catches it "
                "without a reading (counted 1). Step 2b (D25 in 1.6) tests only Hebrew members joined by the anchor.", ""]
    out += [
            "## The New Testament keys (D23)", ""]
    for ed in V.EDS:
        if V15():
            c = counts.get(f"D23 1.5 {ed} parts by key_rule and basis", {})
            out.append(f"- `{ed}` (1.5): " + "; ".join(f"{k} {v}" for k, v in c.items()))
            continue
        c = counts.get(f"D23 {ed}", {})
        out.append(f"- `{ed}`: " + "; ".join(f"{k} {v}" for k, v in c.items()))
    out += ["", "No meaning value of this folder needs a term: its values are keys, counts and codes of form or basis "
            "(`categories.toml`). Nothing here is called checked; no person has read it."]
    return "\n".join(out) + "\n"


# ---- arc: the declarations of D24a ---------------------------------------------------------------------------------

def arc_declarations(outdir, counts):
    d = os.path.join(outdir, "arc")
    F = pq.read_table(os.path.join(d, "facts.parquet"), columns=["relation", "kind", "count"]).to_pylist()
    kc = C.Counter(r["kind"] for r in F if r["relation"] == "equivalent_of")
    path = os.path.join(d, "categories.toml")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if "\n[facts.equivalent_of]\n" in text:     # a second run of --stage 32.new: the block stands last; write it anew
        text = text[:text.index("\n[facts.equivalent_of]\n")]
    block = ["", "[facts.equivalent_of]", 'column = "kind"',
             'basis = "derived (list evidence cognate_meaning, domain, greek_word); model where the evidence is greek_verse '
             '(GLAUx\'s automatic Strong\'s numbers of the Septuagint verse, M7) (D24a)"',
             "values = ["] + [f"  {{ code = {tq(k)}, value = {tq(k)}, count = {v} }}," for k, v in sorted(kc.items())] + ["]"]
    block += _glaux_attr()
    X.write_text(path, text.rstrip("\n") + "\n" + "\n".join(block) + "\n")
    sp = os.path.join(d, "sources.json")
    with open(sp, encoding="utf-8") as fh:
        sj = json.load(fh)
    cols = sj["model"]["glaux"]["columns"]
    add = "facts equivalent_of with kind model (D24a: the list's greek_verse evidence)"
    if add not in cols:
        cols.append(add)
    X.write_text(sp, json.dumps(sj, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    counts["arc equivalent_of rows by kind"] = dict(sorted(kc.items()))
    counts["arc equivalent_of pieces by kind"] = {k: sum(r["count"] for r in F if r["relation"] == "equivalent_of" and r["kind"] == k)
                                                  for k in sorted(kc)}


def write_all(outdir, counts, ex):
    L = os.path.join(outdir, "lexicon")
    X.write_text(os.path.join(L, "SAMPLE.md"), sample_md(L))
    X.write_text(os.path.join(L, "categories.toml"), categories(outdir, L))
    X.write_text(os.path.join(L, "sources.json"), sources(outdir, L))
    X.write_text(os.path.join(L, "COLUMNS.md"), columns_md())
    X.write_text(os.path.join(L, "READ-FIRST.md"), read_first(outdir, L, counts))
    arc_declarations(outdir, counts)
    text, n = reader_sample(outdir, L)
    base = os.path.basename(os.path.normpath(outdir))
    gdir = (V.GLOSSED_F1 if base == "f1" and not V15() else V.GLOSSED_F1.replace("glossed-f1", "glossed-g1")
            if base == "g1" and V15() and not V16() else V.GLOSSED_F1.replace("glossed-f1", "glossed-h1")
            if base == "h1" and V16() else os.path.join(outdir, "cache", "reader-sample"))
    X.write_text(os.path.join(gdir, "equivalents-sample.md"), text)
    counts["reader's sample"] = f"{os.path.relpath(os.path.join(gdir, 'equivalents-sample.md'), V.ROOT)}: {n} groups"
