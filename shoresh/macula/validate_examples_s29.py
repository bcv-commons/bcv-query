"""Stage 29 of the source examples (SPEC 1.3, section 14: close13): the checks of the closing documents of an e build.

Called by validate_examples.py --build e1 --upto 29 [--compare e2] [--write-md]. It imports nothing from the builders.
It checks:
  sources.json     every file listed exists with its sha256; every source has repository, pin, licence, basis; the five
                   sources new in 1.3 are sources of their own, hashed; the terms master with both notes files; the
                   model part names M7's D9m values; SPEC 1.3; the entry names stages 28 and 29
  terms-notes.md   one section per row of terms.tsv; the sections of terms-notes-1.3-rows.md stand in it unchanged
  COLUMNS.md       every file listed with its rows and columns; the column lists of SPEC 1.3 section 4; section 4 itself
  READ-FIRST.md    sections 1 to 5; glossed-e1 and stage 29 named; the account of who is meant recounted, and no share
                   of pieces with a participant; section 5's model counts recounted, with the D9m values and the C2 count
  glossed chapters one table per verse and one row per piece, the 1.3 columns; the model column; every meaning value a
                   term; every semantic role, reference status and added kind a term of its category; every realisation
                   a declared code; the account, the piece values, marks_model and the added rows equal the tables
  no English       as stage 24, over every table of the folder (the three new tables among them); terms.tsv no exception
  rebuild          every file of e1 has the same sha256 in e2 (VALIDATION.md aside), and the glossed chapters
"""
import collections as C
import json
import os
import re
import tomllib

import pyarrow.parquet as pq

import validate_examples_s20 as S

HERE = S.HERE
ROOT = S.ROOT
LANGS = S.LANGS
SPEC_DIR = os.path.join(ROOT, "internal-docs/source-examples-spec")
NEW13 = {"reference-status": ["shoresh/macula/data/reference-status/np.tsv"],
         "implicit-args": ["shoresh/macula/data/implicit-args/args.tsv"],
         "inclusive-we": ["shoresh/macula/data/we-layer/words.tsv", "shoresh/macula/data/we-votes/verses.tsv"],
         "noun-relations": ["shoresh/macula/data/noun-relations/pairs.tsv"],
         "passage-facts": ["shoresh/macula/data/bridge-corpus/inputs/passage-facts@v0.1/PIN.json"]}
STATES = ("participant", "generic", "not_referring", "entity_not_taken", "no_entity", "unresolved", "no_row")
HEAD_KINDS = ("noun", "pronoun", "suffix", "verb_zero")
HDR = ("| t.n | word | piece | kind | lexeme | class | marks | head | label | shared | clause | part | participant | "
       "account | piece values | concept | model |")
CL_HDR = "| clause | key | rule | parent | marks | speech | model |"
AD_HDR = "| + | clause | verb | role | kind | where | form | person | number | gender | antecedent | who |"
MEANING = ("relation", "time", "aspect", "line_kind", "mood", "time_abs")
TERM_CAT = {"time_abs": "time"}

V14 = False   # an f build (SPEC 1.4): set by validate_examples.py
V15 = False   # a g build (SPEC 1.5): set by validate_examples.py
V16 = False   # an h build (SPEC 1.6): set by validate_examples.py


def _cells(ln):
    """The cells of a markdown table row; `\\|` inside a cell is kept."""
    parts = re.split(r"(?<!\\)\|", ln.strip())
    return [p.strip() for p in parts[1:-1]]


# ---- sources.json, terms-notes.md -------------------------------------------------------------------------------

def check_sources13(R, build, lang):
    S.check_sources(R, build, lang)
    d = os.path.join(build, lang)
    with open(os.path.join(d, "sources.json"), encoding="utf-8") as fh:
        doc = json.load(fh)
    src = doc["sources"]
    bad = []
    for k, paths in NEW13.items():
        s = src.get(k)
        if not s or not s.get("basis") or not s.get("licence"):
            bad.append(k)
            continue
        for p in paths:
            if s["files"].get(p, {}).get("sha256") != S.sha(os.path.join(ROOT, p)):
                bad.append(f"{k}:{p}")
    npf = len(src.get("passage-facts", {}).get("files", {}))
    R.check(f"{lang} sources.json: the five sources new in 1.3 are sources of their own, with basis and licence, their "
            f"files hashed as on disk", not bad, f"{len(NEW13)} sources (passage-facts {npf} files); {bad}")
    nob = sorted(k for k, s in src.items() if not s.get("basis"))
    R.check(f"{lang} sources.json: every source names its basis (SPEC 5)", not nob, f"{len(src)} sources; {nob}")
    tf = src.get("terms", {}).get("files", {})
    want = ("terms.tsv", "terms-notes.md", "terms-notes-1.3-rows.md")
    R.check(f"{lang} sources.json: the terms master and both notes files hashed as on disk",
            all(tf.get(f"internal-docs/source-examples-spec/{f}", {}).get("sha256") == S.sha(os.path.join(SPEC_DIR, f))
                for f in want), sorted(tf))
    m7 = doc.get("model", {}).get("time-aspect-lxx-parse", {})
    R.check(f"{lang} sources.json: the model part names M7's D9m values (models, version, no human check)",
            bool(m7.get("models")) and bool(m7.get("version")) and m7.get("human_check") == "no human check", sorted(m7))
    if V16:
        R.check(f"{lang} sources.json: the builder entry names stage 38 of build h1 (SPEC 1.6)",
                "--build h1 --stage 38" in doc["builder"]["entry"], doc["builder"]["entry"])
    elif V15:
        R.check(f"{lang} sources.json: the builder entry names stage 35 of build g1 (SPEC 1.5)",
                "--build g1 --stage 35" in doc["builder"]["entry"], doc["builder"]["entry"])
    elif V14:
        R.check(f"{lang} sources.json: the builder entry names stage 32 of build f1 (SPEC 1.4)",
                "--build f1 --stage 32" in doc["builder"]["entry"], doc["builder"]["entry"])
    else:
        R.check(f"{lang} sources.json: the builder entry names stages 28 and 29 of build e1",
                "--build e1 --stage 28" in doc["builder"]["entry"] and "--stage 29" in doc["builder"]["entry"],
                doc["builder"]["entry"])
    R.check(f"{lang} sources.json: the stage-27 part `v13` kept", bool(doc.get("v13")), sorted(doc.get("v13", {})))


def check_notes13(R, build, lang):
    p = os.path.join(build, lang, "terms-notes.md")
    text = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    _, tcols, n = S.table(os.path.join(build, lang, "terms.tsv"))
    miss = [f"{c}:{k}" for c, k in zip(tcols["category"], tcols["code"]) if f"\n### {c} `{k}`\n" not in text]
    R.check(f"{lang} terms-notes.md: one section per (category, code) of terms.tsv", not miss and n > 0, f"{n} rows; {miss[:5]}")
    rows = open(os.path.join(SPEC_DIR, "terms-notes-1.3-rows.md"), encoding="utf-8").read()
    secs = ["### " + s.rstrip("\n") for s in rows.split("\n## The rows\n", 1)[1].split("\n### ")[1:]]
    missing = [s.split("\n", 1)[0] for s in secs if s not in text]
    R.check(f"{lang} terms-notes.md: the {len(secs)} sections of terms-notes-1.3-rows.md stand in it unchanged",
            len(secs) == 30 and not missing, missing[:3])
    R.info(f"{lang} terms-notes.md: exempt from the no-English check by name (SPEC 4.10); not a table", f"{len(text):,} characters")


# ---- READ-FIRST.md -------------------------------------------------------------------------------------------------

def check_read_first13(R, build, lang):
    d = os.path.join(build, lang)
    p = os.path.join(d, "READ-FIRST.md")
    text = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    R.check(f"{lang} READ-FIRST.md: exists with sections 1 to 5 (5: what is model, and how much)",
            all(f"## {i}." in text for i in (1, 2, 3, 4, 5)) and "## 5. What is model" in text)
    gname, sname = ("glossed-h1", "--stage 38") if V16 else ("glossed-g1", "--stage 35") if V15 else ("glossed-e1", "--stage 29")
    R.check(f"{lang} READ-FIRST.md: names the chapters ({gname}/) and {sname[2:]}, no older chapters or stage",
            f"source-examples-work/{gname}/" in text and sname in text
            and not any(x in text for x in ("glossed-d1/", "glossed-c1/", "source-examples-work/glossed/", "--stage 24",
                                            "--stage 20", "--stage 10")))
    A = pq.read_table(os.path.join(d, "who_account.parquet"), columns=["head_kind", "state"]).to_pydict()
    tab = C.Counter(zip(A["head_kind"], A["state"]))
    sec = text.split("### The account of who is meant", 1)[-1].split("## 2.", 1)[0]
    got = {}
    for ln in sec.split("\n"):
        c = _cells(ln) if ln.startswith("| `") else []
        if c:
            got[c[0].strip("`")] = [int(x.replace(",", "")) for x in c[1:]]
    want = {k: [tab[(k, s)] for s in STATES] + [sum(tab[(k, s)] for s in STATES)]
            for k in HEAD_KINDS if any(tab[(k, s)] for s in STATES)}
    R.check(f"{lang} READ-FIRST.md: the account of who is meant (D19) equals who_account.parquet, per head kind and state",
            got == want and bool(want), f"{len(A['state']):,} heads; {len(want)} head kinds")
    pl = [ln for ln in text.split("\n") if ln.startswith("- pieces with a participant:")]
    R.check(f"{lang} READ-FIRST.md: the account stands in place of a share of pieces with a participant",
            len(pl) == 1 and not re.search(r"\(0\.\d{3}\)", pl[0]) and "account of who is meant follows" in pl[0], pl[:1])
    P = pq.read_table(os.path.join(d, "pieces.parquet"), columns=["concept", "who_basis"]).to_pydict()
    K = pq.read_table(os.path.join(d, "clauses.parquet"), columns=["subject_model", "marks_model"]).to_pydict()
    LK = pq.read_table(os.path.join(d, "links.parquet"), columns=["other", "basis", "agree_model"]).to_pydict()
    F = pq.read_table(os.path.join(d, "facts.parquet"), columns=["kind"]).column("kind").to_pylist()
    mk = C.Counter(k for v in K["marks_model"] if v is not None for k in json.loads(v))
    want5 = {"pieces.concept (M1)": sum(v is not None for v in P["concept"]),
             "pieces.who with who_basis model (M2)": sum(v == "model" for v in P["who_basis"]),
             "clauses.subject_model (M3)": sum(v is not None for v in K["subject_model"]),
             "links with basis model (M5, M7)": sum(v == "model" for v in LK["basis"]),
             "facts with kind model (M7)": sum(v == "model" for v in F),
             "clauses with marks_model (M7, D9m)": sum(v is not None for v in K["marks_model"])}
    for k in ("time", "aspect", "mood", "time_abs"):
        want5[f"marks_model.{k} (M7, D9m)"] = mk[k]
    for o in sorted(set(LK["other"])):
        want5[f"strict links to {o} where a model alignment agrees (agree_model >= 1; OPEN-1.2 C2)"] = sum(
            1 for t, b, a in zip(LK["other"], LK["basis"], LK["agree_model"]) if t == o and b != "model" and a is not None and a >= 1)
    sec5 = text.split("## 5. What is model", 1)[-1]
    bad = [k for k, v in want5.items() if f"| {k} | {v:,} |" not in sec5]
    R.check(f"{lang} READ-FIRST.md section 5: the model counts equal the recount (with the D9m values and the C2 count)",
            not bad, f"{len(want5)} rows; {bad}")
    R.info(f"{lang} READ-FIRST.md section 5: C2 and D9m counts",
           {k: v for k, v in want5.items() if "C2" in k or "D9m" in k})


# ---- glossed chapters ----------------------------------------------------------------------------------------------

def check_glossed13(R, build, gdir, terms, cats):
    tot = C.Counter()
    for lang, book, ch, name in S.CHAPTERS:
        p = os.path.join(gdir, name + ".md")
        if not os.path.exists(p):
            R.check(f"glossed {name}.md exists", False)
            continue
        d = os.path.join(build, lang)
        W = [w for w in pq.read_table(os.path.join(d, "words.parquet"), columns=["t", "book", "chapter", "verse", "clause"]).to_pylist()
             if w["book"] == book and w["chapter"] == ch]
        ts = {w["t"] for w in W}
        verses = {w["verse"] for w in W}
        P = {(r["t"], r["n"]): r for r in pq.read_table(os.path.join(d, "pieces.parquet"),
             columns=["t", "n", "concept", "who_basis", "clusivity", "noun_rel", "noun_head_t"]).to_pylist() if r["t"] in ts}
        acc = {(r["t"], r["n"]): r["state"] for r in pq.read_table(os.path.join(d, "who_account.parquet"),
                                                                   columns=["t", "n", "state"]).to_pylist() if r["t"] in ts}
        shown = {w["clause"] for w in W if w["clause"]}
        mm = {c["clause"] for c in pq.read_table(os.path.join(d, "clauses.parquet"), columns=["clause", "marks_model"]).to_pylist()
              if c["clause"] in shown and c["marks_model"] is not None}
        AD = [r for r in pq.read_table(os.path.join(d, "added.parquet"), columns=["verb", "kind"]).to_pylist() if r["verb"] in ts]
        text = open(p, encoding="utf-8").read()
        lines = text.split("\n")
        heads = re.findall(rf"^## {book} {ch}:(\d+)$", text, re.M)
        rows = [_cells(ln) for ln in lines if re.match(r"^\| \d+\.\d+ \|", ln)]
        crow = [_cells(ln) for ln in lines if re.match(r"^\| \d+ \| `cl:", ln)]
        arow = [_cells(ln) for ln in lines if ln.startswith("| + | ") and not ln.startswith(AD_HDR)]
        R.check(f"glossed {name}: one table per verse, one row per piece, the 1.3 columns, names SPEC 1.3",
                sorted(map(int, heads)) == sorted(verses) and len(rows) == len(P) and text.count(HDR) == len(verses)
                and all(len(r) == 17 for r in rows) and "(SPEC 1.3)" in text,
                f"{len(heads)} verses of {len(verses)}, {len(rows)} rows of {len(P)} pieces")
        key = {tuple(map(int, r[0].split("."))): r for r in rows}
        nmodel = {k for k, v in P.items() if v["concept"] is not None or v["who_basis"] == "model"}
        marked = {k for k, r in key.items() if r[16]}
        R.check(f"glossed {name}: the model column marks exactly the pieces with a model value", marked == nmodel,
                f"{len(marked)} marked, {len(nmodel)} pieces with concept or who_basis model")
        acc_shown = {k: r[13].split(" (")[0] for k, r in key.items() if r[13]}
        R.check(f"glossed {name}: the account column equals who_account.parquet on every piece", acc_shown == acc,
                f"{len(acc)} referring heads, {len(acc_shown)} shown")
        pv = {k: r[14] for k, r in key.items()}
        clu = {k for k, v in pv.items() if "clusivity=" in v}
        nr = {k for k, v in pv.items() if "noun_rel=" in v or "noun→" in v}
        badpv = [v for v in pv.values() for x in re.findall(r"(?:clusivity|noun_rel)=([^(→;]+)", v)
                 if x.strip() not in terms[lang]["clusivity"] | terms[lang]["noun_rel"]]
        R.check(f"glossed {name}: clusivity and noun_rel shown exactly where the pieces have them, as terms",
                clu == {k for k, v in P.items() if v["clusivity"]} and nr == {k for k, v in P.items() if v["noun_head_t"] is not None}
                and not badpv, f"clusivity {len(clu)}, noun pairs {len(nr)}; {badpv[:3]}")
        parts = [x for r in rows for x in r[11].split("; ") if x]
        sems, refs, forms = [], [], []
        for x in parts:
            for f in x.split(" · ")[1:]:
                if f.startswith("sem="):
                    sems.append(re.sub(r" \(linked\)$", "", f[4:]))
                elif f.startswith("ref="):
                    refs.append(f[4:])
                elif f.startswith("form="):
                    forms.append(f[5:])
        rform = {v["code"] for v in cats[lang].get("constituents", {}).get("ref_form", {}).get("values", [])}
        bad = [x for x in sems if x not in terms[lang]["sem_role"]] + [x for x in refs if x not in terms[lang]["ref_status"]] \
            + [x for x in forms if x not in rform]
        R.check(f"glossed {name}: every semantic role and reference status shown in `part` is a term of its category, every "
                f"realisation a declared ref_form code", not bad and len(refs) == len(forms),
                f"{len(sems)} roles, {len(refs)} statuses, {len(forms)} forms of {len(parts)} parts; {bad[:3]}")
        vals = [(c, v.strip()) for r in crow for c, v in re.findall(r"(?:^|; )(\w+)=([^;]+)", r[4]) if c in MEANING]
        mvals = [(c, v.strip()) for r in crow for m in re.findall(r"marks_model ([^(]+) \(model\)", r[6])
                 for c, v in re.findall(r"(\w+)=([^,]+)", m)]
        badm = [f"{c}={v}" for c, v in vals + mvals if v not in terms[lang][TERM_CAT.get(c, c)]]
        R.check(f"glossed {name}: every meaning value shown (marks and marks_model; relation, time, aspect, line_kind, mood, "
                f"time_abs) is a term of the language", not badm and bool(vals),
                f"{len(vals)} values, {len(mvals)} model values; {badm[:3]}")
        mshown = {r[1].strip("`") for r in crow if "marks_model " in r[6]}
        R.check(f"glossed {name}: marks_model shown, marked model, on exactly the shown clauses that have it", mshown == mm,
                f"{len(mm)} clauses")
        badk = [r[4] for r in arow if r[4] not in terms[lang]["added_kind"]]
        vof = {w["t"]: w["verse"] for w in W}
        nvad = len({vof[r["verb"]] for r in AD})
        R.check(f"glossed {name}: the added arguments stand apart, each marked `+`, one row per added.parquet row of the "
                f"chapter, kind a term of added_kind", len(arow) == len(AD) and not badk
                and text.count("**Added: arguments the text does not say**") == nvad,
                f"{len(arow)} rows of {len(AD)} in {nvad} verses; {badk[:3]}")
        tot["pieces"] += len(rows)
        tot["added"] += len(arow)
        tot["refs"] += len(refs)
        tot["moods"] += sum(1 for c, _ in vals if c == "mood")
        tot["model clauses"] += len(mshown)
    R.info("glossed chapters (1.3): totals", dict(tot))


# ---- the stage -----------------------------------------------------------------------------------------------------

def stage29(R, build, STASH, V, compare=None):
    cats = {}
    for lang in LANGS:
        with open(os.path.join(build, lang, "categories.toml"), "rb") as fh:
            cats[lang] = tomllib.load(fh)
    R.section("sources.json (as stage 29 wrote it)")
    for lang in LANGS:
        check_sources13(R, build, lang)
    R.section("terms-notes.md (SPEC 4.10, 1.3)")
    for lang in LANGS:
        check_notes13(R, build, lang)
    R.section("COLUMNS.md and READ-FIRST.md")
    for lang in LANGS:
        S.check_columns(R, build, lang)
        check_read_first13(R, build, lang)
    R.section("glossed chapters (glossed-e1/)")
    terms = {}
    for lang in LANGS:
        _, cols, _ = S.table(os.path.join(build, lang, "terms.tsv"))
        col = "grc" if lang == "grc" else "hbo"
        terms[lang] = C.defaultdict(set)
        for cat, t in zip(cols["category"], cols[col]):
            if t:
                terms[lang][cat].add(t)
    check_glossed13(R, build, S.glossed_dir(build), terms, cats)
    R.section("no English")
    vocab, nlow = V._s10_gloss_vocab()
    R.info("MACULA gloss vocabulary (words of gloss and english, lower-cased)", f"{len(vocab)} words from {nlow} files")
    for lang in LANGS:
        STASH[f"s10 {lang} code words"] = S.check_english(R, V, build, lang, cats[lang], vocab)
    R.section("rebuild")
    if compare:
        S.check_rebuild(R, build, compare)
    else:
        R.skip("rebuild: a second build compared file by file", "no --compare given")
