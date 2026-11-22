"""Stage 17 checks (SPEC 1.1, section 10: model attribution; strict view; speech, the model part).

Called by validate_examples.py --build c1 --upto 17. Imports none of the examples_* builders. It:
- recomputes `pieces.concept`, `concept_by` (M1) from the two concept releases (their SHA256SUMS checked);
- builds the reviewed Hebrew speaker layer itself (validate_examples_speech.py hbo-review) and recomputes
  `quote_model`, `speaker_model`, `addressee_model` (D10m) with the published Greek layout and every addressees row;
- recomputes `subject_model` (D15m) over stage 16's own D9 join (validate_examples_s16 joins the usable rows);
- checks that every M column names dataset, version and model(s) in categories.toml and sources.json, and that the
  models named stand in the dataset's card, build.json or review rows;
- builds the strict view (SPEC 2.3) from the build's own files, runs stage 16 (build_examples.py, a subprocess) on it
  in <build>/cache/validate17-strict/, and compares what stage 16 writes there with the strict view value by value.
"""
import collections as C
import csv
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
import unicodedata

import pyarrow as pa
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(HERE, "data")
DOCS = os.path.join(REPO, "internal-docs")
M_PIECES = ("concept", "concept_by")
M_CLAUSES = ("quote_model", "speaker_model", "addressee_model", "subject_model")
SCRATCH = None     # e builds: the validator's scratch (strict view, speech layers), set by validate_examples.py
V13 = False


def set13():
    """SPEC 1.3: marks_model is an M column; the strict view's stage 16 also writes added.parquet; the 1.3 part of
    categories.toml (stage 27's close) is left to stage 27's checks."""
    global M_CLAUSES, V13
    V13 = True
    if "marks_model" not in M_CLAUSES:
        M_CLAUSES = M_CLAUSES + ("marks_model",)
REL = {"hbo": "hebrew-word-concepts-model-release/v0.6-release", "arc": "hebrew-word-concepts-model-release/v0.6-release",
       "grc": "greek-nt-concepts-model-release/v0.1"}
SUBJ = "clause-subjects-model-release/v0.1"
TYPES = ("person", "place", "group", "deity", "realia", "flora", "fauna")
S16_FILES = ("pieces.parquet", "clauses.parquet", "constituents.parquet", "participants.tsv", "facts.parquet",
             "source_errors.tsv")


def nfc(s):
    return unicodedata.normalize("NFC", s)


def c0(v):
    import re
    return re.sub(r"[^a-z0-9]+", "_", v.lower()).strip("_")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def tsv(path, corpus=None):
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader((ln for ln in fh if not ln.startswith("#")), delimiter="\t",
                                   quoting=csv.QUOTE_NONE))
    return [r for r in rows if corpus is None or r.get("corpus") == corpus]


def ekey(acai, t):
    return f"{t}:e{hashlib.sha1(acai.encode('utf-8')).hexdigest()[:10]}"


def extra_data():
    """The usable clause-subjects-model rows, for stage 16's D9 join (corpus -> {dataset: rows})."""
    out = {}
    for corpus, f in (("hbo", "hebrew.parquet"), ("grc", "greek-nt.parquet")):
        rows = pq.read_table(os.path.join(DOCS, SUBJ, "data", f)).to_pylist()
        out[corpus] = {"clause-subjects-model": [r for r in rows if r["usable"]]}
    return out


def release_ok(folder):
    d = os.path.join(DOCS, folder)
    bad, files = 0, {}
    for ln in open(os.path.join(d, "SHA256SUMS"), encoding="utf-8"):
        h, f = ln.split(None, 1)
        f = f.strip()
        files[f] = h
        bad += sha(os.path.join(d, f)) != h
    return bad == 0, files


# ---- the strict view (SPEC 2.3) --------------------------------------------------------------------------------

LATER_FACTS = {"rendered_by", "has_class", "in_domain", "sense_of", "equivalent_of"}   # stages 19, 20
LATER_CATS = ("links", "link_account", "other", "map", "relmap", "profile", "terms")    # stages 19, 20 (23: terms)
# stage 20's sections inside tables stage 16 also declares (the shared part of categories.toml)
LATER_SECS = {"words": ("rel_shared",), "pieces": ("shared",), "clauses": ("shared",),
              "facts": ("rendered_by", "relation", "kind", "source", "method")}


def strict_view(build, lang):
    d = os.path.join(build, lang)
    P = pq.read_table(os.path.join(d, "pieces.parquet")).to_pydict()
    K = pq.read_table(os.path.join(d, "clauses.parquet")).to_pydict()
    for c in M_PIECES:
        P[c] = [None] * len(P["pid"])
    P["who"] = ["" if b == "model" else w for w, b in zip(P["who"], P["who_basis"])]
    P["who_basis"] = ["" if b == "model" else b for b in P["who_basis"]]
    for c in M_CLAUSES:
        K[c] = [None] * len(K["clause"])
    with open(os.path.join(d, "participants.tsv"), encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))
    hdr, body = rows[0], rows[1:]
    wm, eb = hdr.index("words_model"), hdr.index("ent_basis")
    model_rows = [r for r in body if r[eb] == "model"]
    body = [r[:wm] + [""] + r[wm + 1:] for r in body if r[eb] != "model"]
    with open(os.path.join(d, "categories.toml"), "rb") as fh:
        cats = tomllib.load(fh)
    for tab in list(cats):
        if not isinstance(cats[tab], dict):
            continue
        for col in list(cats[tab]):
            sec = cats[tab][col]
            if isinstance(sec, dict) and sec.get("basis") == "model":
                del cats[tab][col]
    # the people part counts the model rows too: take them out
    part = cats.get("participants", {})
    sub = {"ent_basis": C.Counter(r[eb] for r in model_rows),
           "type": C.Counter(r[hdr.index("type")] for r in model_rows),
           "name_basis": C.Counter(r[hdr.index("name_basis")] for r in model_rows if r[hdr.index("name_basis")])}
    for col, cc in sub.items():
        sec = part.get(col)
        if not sec:
            continue
        key = "term" if col == "type" else "code"
        vals = []
        for v in sec.get("values", []):
            v = dict(v, count=v["count"] - cc.get(v[key], 0))
            if v["count"] > 0:
                vals.append(v)
        sec["values"] = vals
    return P, K, hdr, body, cats, model_rows


def write_view(build, out, langs):
    """The strict view as stage 16's input: c1's files with the M columns and model rows taken out."""
    for lang in langs:
        P, K, hdr, body, _cats, _m = strict_view(build, lang)
        d = os.path.join(out, lang)
        os.makedirs(d, exist_ok=True)
        for f in ("words.parquet", "constituents.parquet", "lexemes.tsv", "terms.tsv", "facts.parquet",
                  "source_errors.tsv", "categories.toml"):
            shutil.copyfile(os.path.join(build, lang, f), os.path.join(d, f))
        sp = pq.read_schema(os.path.join(build, lang, "pieces.parquet"))
        sk = pq.read_schema(os.path.join(build, lang, "clauses.parquet"))
        pq.write_table(pa.Table.from_pydict(P, schema=sp), os.path.join(d, "pieces.parquet"))
        pq.write_table(pa.Table.from_pydict(K, schema=sk), os.path.join(d, "clauses.parquet"))
        with open(os.path.join(d, "participants.tsv"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\t".join(hdr) + "\n")
            for r in body:
                fh.write("\t".join(r) + "\n")
    os.makedirs(os.path.join(out, "cache"), exist_ok=True)
    shutil.copyfile(os.path.join(build, "cache", "morphid.parquet"), os.path.join(out, "cache", "morphid.parquet"))


def strict_check(R, build):
    # under the build: the speaker-layer builder writes only below data/source-examples/
    root = os.path.join(build, "cache", "validate17-strict")
    bname = os.path.basename(os.path.normpath(build))[0] + "1"      # c1 or d1: the view gets the build's kind
    if bname == "f1":     # SPEC 1.4: stage 16 is a builder of 1.3; an f build's view is run as an e build
        bname = "e1"
    # SPEC 1.5: a g build's view runs stage 16 as a g build (the 1.5 switch on); build_examples.py takes --stage 16 there
    out = os.path.join(root, bname)
    if os.path.exists(out):                       # never delete: an earlier run's folder is moved aside
        n = 1
        while os.path.exists(os.path.join(root, f"old-{n}")):
            n += 1
        os.rename(out, os.path.join(root, f"old-{n}"))
    langs = ("hbo", "arc", "grc")
    write_view(build, out, langs)
    log = os.path.join(root, "stage16.log")
    with open(log, "w", encoding="utf-8") as fh:
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "build_examples.py"), "--build", bname,
                            "--stage", "16", "--root", root], stdout=fh, stderr=subprocess.STDOUT)
    R.check("strict view: stage 16 runs on the strict view built from c1's own files", r.returncode == 0, log)
    if r.returncode:
        return
    for lang in langs:
        P, K, hdr, body, cats, model_rows = strict_view(build, lang)
        d = os.path.join(out, lang)
        A = pq.read_table(os.path.join(d, "pieces.parquet")).to_pydict()
        diff = {c: sum(1 for x, y in zip(A[c], P[c]) if x != y) for c in A}
        R.check(f"{lang} strict view: pieces equal stage 16's, value by value (M columns null)",
                list(A) == list(P) and len(A["pid"]) == len(P["pid"]) and not any(diff.values()),
                {c: v for c, v in diff.items() if v} or f"{len(P['pid']):,} rows")
        A = pq.read_table(os.path.join(d, "clauses.parquet")).to_pydict()
        if V13:
            for c in M_CLAUSES:
                A[c] = [None] * len(A["clause"])
        diff = {c: sum(1 for x, y in zip(A[c], K[c]) if x != y) for c in A}
        R.check(f"{lang} strict view: clauses equal stage 16's, value by value (M columns null)",
                list(A) == list(K) and len(A["clause"]) == len(K["clause"]) and not any(diff.values()),
                {c: v for c, v in diff.items() if v} or f"{len(K['clause']):,} rows")
        with open(os.path.join(d, "participants.tsv"), encoding="utf-8", newline="") as fh:
            got = list(csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))
        R.check(f"{lang} strict view: participants.tsv without its {len(model_rows)} model rows equals stage 16's",
                got == [hdr] + body, f"{len(body):,} rows")
        for f in ("constituents.parquet", "source_errors.tsv") + (("added.parquet", "who_account.parquet") if V13 else ()):
            R.check(f"{lang} strict view: {f} equals stage 16's (sha256)", sha(os.path.join(d, f)) ==
                    sha(os.path.join(build, lang, f)))
        # facts and categories.toml: later stages (19 links, 20 shared) add their own rows and sections; stage 16's
        # part is compared, the later parts are checked by their stages
        mine = [r for r in pq.read_table(os.path.join(build, lang, "facts.parquet")).to_pylist()
                if r["relation"] not in LATER_FACTS]
        R.check(f"{lang} strict view: facts.parquet rows of stage 16 equal stage 16's (later relations "
                f"{sorted(LATER_FACTS)} left to their stages)",
                mine == pq.read_table(os.path.join(d, "facts.parquet")).to_pylist(), f"{len(mine):,} rows")
        with open(os.path.join(d, "categories.toml"), "rb") as fh:
            want = tomllib.load(fh)
        if V13:       # the 1.3 part (stage 27's close) is checked by stage 27
            with open(os.path.join(build, lang, "categories.toml"), encoding="utf-8") as fh:
                t13 = fh.read().split("# ---- the 1.3 part (build_examples.py --stage 27) ----")
            for tab, secs in (tomllib.loads(t13[1]).items() if len(t13) > 1 else ()):
                for sec in secs:
                    cats.get(tab, {}).pop(sec, None)
                if tab in cats and not cats[tab]:
                    cats.pop(tab)
        for tab in LATER_CATS:
            cats.pop(tab, None)
        for tab, secs in LATER_SECS.items():
            for sec in secs:
                if tab in cats:
                    cats[tab].pop(sec, None)
            if tab in cats and not cats[tab]:
                cats.pop(tab)
        R.check(f"{lang} strict view: categories.toml without its model sections, model counts and later stages' "
                f"sections ({', '.join(LATER_CATS)}, facts.rendered_by; stage 20's shared part) equals stage 16's", cats == want)
        R.check(f"{lang} strict view: no value of basis model in it (who_basis, ent_basis, M columns)",
                "model" not in P["who_basis"] and all(r[hdr.index("ent_basis")] != "model" for r in body)
                and all(v is None for c in M_PIECES for v in P[c]) and all(v is None for c in M_CLAUSES for v in K[c]))


# ---- attribution -------------------------------------------------------------------------------------------------

def attribution(R, build):
    for lang in ("hbo", "arc", "grc"):
        d = os.path.join(build, lang)
        with open(os.path.join(d, "categories.toml"), "rb") as fh:
            cats = tomllib.load(fh)
        try:
            src = json.load(open(os.path.join(d, "sources.json"), encoding="utf-8"))["model"]
        except (OSError, KeyError, ValueError):
            src = {}
        R.check(f"{lang} sources.json: holds the model sources", bool(src))
        for tab, col in [("pieces", c) for c in M_PIECES] + [("clauses", c) for c in M_CLAUSES]:
            sec = cats.get(tab, {}).get(col, {})
            ok = sec.get("basis") == "model" and sec.get("dataset") and sec.get("version") and sec.get("models") \
                and all(isinstance(m, str) and m for m in sec["models"]) and sec.get("human_check") == "no human check"
            R.check(f"{lang} categories.toml {tab}.{col}: basis model, dataset, version, model(s), no human check",
                    bool(ok), f"{sec.get('dataset')} {sec.get('version')}")
        wm = cats.get("participants", {}).get("words_model", {})
        prow = tsv(os.path.join(d, "participants.tsv"))
        P = pq.read_table(os.path.join(d, "pieces.parquet"), columns=["who_basis"]).to_pydict()
        R.check(f"{lang} M2 not on disk: words_model declared not filled and empty; no who of basis model",
                wm.get("filled") is False and wm.get("dataset") and all(r["words_model"] == "" for r in prow)
                and "model" not in P["who_basis"], wm.get("why"))
        # the models named stand in the sources' own records
        rel = REL[lang]
        ok, files = release_ok(rel)
        R.check(f"{lang} M1 release {rel}: every SHA256SUMS line holds", ok)
        cs = src.get("greek-nt-concepts-model" if lang == "grc" else "hebrew-word-concepts-model", {})
        bj = open(os.path.join(DOCS, rel, "build.json"), encoding="utf-8").read()
        bjd = json.loads(bj)
        R.check(f"{lang} M1 sources.json: files and sha256 as the release, version as its build.json",
                cs.get("files") == files and cs.get("version") == bjd["version"] and cs.get("revision"))
        R.check(f"{lang} M1: every model named stands in the release's build.json",
                bool(cs.get("models")) and all(json.dumps(m, ensure_ascii=False)[1:-1] in bj for m in cs["models"]),
                cs.get("models"))
        R.check(f"{lang} M1 categories.toml: the models are the sources.json models",
                cats["pieces"]["concept"]["models"] == cs.get("models") == cats["pieces"]["concept_by"]["models"])
        ok, files = release_ok(SUBJ)
        su = src.get("clause-subjects-model", {})
        card = open(os.path.join(DOCS, SUBJ, "README.md"), encoding="utf-8").read()
        R.check(f"{lang} M3 release: SHA256SUMS holds; sources.json files equal; the model named stands in its card",
                ok and su.get("files") == files and bool(su.get("models")) and all(m in card for m in su["models"])
                and su.get("run", "") in card, su.get("models"))
        sp = next((v for k, v in src.items() if k.endswith("-reviewed")), {})
        rf = os.path.join(REPO, "resources", "speaker_quotations" if lang == "grc" else "speaker_layer",
                          "nt_review.tsv" if lang == "grc" else "review.tsv")
        by = dict(sorted(C.Counter(r["source"] for r in tsv(rf)).items()))
        R.check(f"{lang} M4: the models named are the review rows' own sources, counted",
                sp.get("models") == sorted(by) and list(sp.get("rows_by_source", {}).values()) == [by],
                f"{sum(by.values())} rows: {by}")
        for col in ("quote_model", "speaker_model", "addressee_model"):
            R.check(f"{lang} categories.toml clauses.{col}: models equal sources.json's",
                    cats["clauses"][col]["models"] == sp.get("models"))
        mm = src.get("entity-mentions-model", {})
        R.check(f"{lang} M2 sources.json: entity-mentions-model named, its version, said not read",
                mm.get("version") == "v0.1" and "not" in mm.get("status", ""), mm.get("status"))


# ---- recomputations ------------------------------------------------------------------------------------------------

def concepts(R, build):
    for lang in ("hbo", "arc", "grc"):
        t = pq.read_table(os.path.join(DOCS, REL[lang], "data", "words.parquet" if lang == "grc" else
                                       "tokens.parquet")).to_pylist()
        if lang == "grc":
            want = {r["greek_id"]: ("-" if r["none"] or not r["concept"] else r["concept"], c0(r["labeller"]))
                    for r in t}
        else:
            want = {"o" + r["key"]: (r["concept"] or "-", c0(r["labeller"])) for r in t if r["lang"] == lang}
        P = pq.read_table(os.path.join(build, lang, "pieces.parquet"),
                          columns=["pid", "concept", "concept_by"]).to_pydict()
        got = {p: (c, b) for p, c, b in zip(P["pid"], P["concept"], P["concept_by"])}
        bad = sum(1 for p, v in got.items() if v != want.get(p, (None, None)))
        R.check(f"{lang} pieces: concept, concept_by equal M1 recomputed from the release", bad == 0, bad)
        R.check(f"{lang} M1: every dataset row of the language lands on a piece", set(want) <= set(got),
                f"{len(want):,} rows")
        n = sum(1 for v in P["concept"] if v is not None)
        R.info(f"{lang} M1 coverage: pieces with concept / '-' / all", f"{n:,} / "
               f"{sum(1 for v in P['concept'] if v == '-'):,} / {len(P['pid']):,}")
        with open(os.path.join(build, lang, "categories.toml"), "rb") as fh:
            cats = tomllib.load(fh)
        bc = C.Counter(v for v in P["concept_by"] if v is not None)
        sec = cats["pieces"]["concept_by"]
        R.check(f"{lang} categories.toml pieces.concept_by: every code declared with its count",
                {v["code"]: v["count"] for v in sec["values"]} == dict(bc), dict(bc))
        R.check(f"{lang} categories.toml pieces.concept: count", cats["pieces"]["concept"]["count"] == n, n)
        R.check(f"{lang} concept and concept_by null together", all((c is None) == (b is None) for c, b in
                                                                    zip(P["concept"], P["concept_by"])))


def speech_model(R, build):
    f = os.path.join(SCRATCH or os.path.join(build, "cache"), "validate17-speech-hbo-review")
    os.makedirs(f, exist_ok=True)
    log = f + ".log"
    with open(log, "w", encoding="utf-8") as fh:
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "validate_examples_speech.py"), "hbo-review", f],
                           stdout=fh, stderr=subprocess.STDOUT)
    R.check("hbo speech: the validator built the reviewed layer itself", r.returncode == 0, log)
    seg, sid = {}, {}
    for p in glob.glob(os.path.join(f, "segments", "*.tsv")):
        b = os.path.basename(p)[:-4]
        for x in tsv(p):
            seg[f"{b}.{x['chapter']}.{x['verse']}.{x['seg']}"] = x["quotation"]
    hq = {x["id"]: x for x in tsv(os.path.join(f, "quotations.tsv"))}
    pub = {x["id"]: x for x in tsv(os.path.join(DATA, "speaker-layer", "quotations.tsv"))}
    R.info("hbo speech: the validator's reviewed layer against the published layer: quotations / differ",
           f"{len(hq):,} / {len(set(hq) ^ set(pub)) + sum(1 for q in hq if q in pub and (hq[q]['first'], hq[q]['last'], hq[q]['speaker_id']) != (pub[q]['first'], pub[q]['last'], pub[q]['speaker_id']))}")
    for q, x in hq.items():
        sid[("hbo", q)] = x["speaker_id"]
    for p in glob.glob(os.path.join(DATA, "nt-clause-layout", "clauses", "*", "*.jsonl")):
        b, ch = os.path.basename(p)[:-6].rsplit("_", 1)
        for ln in open(p, encoding="utf-8"):
            x = json.loads(ln)
            seg[f"{b}.{int(ch)}.{x['verse']}.{x['seg']}"] = x["quotation"] or ""
            if x["quotation"]:
                sid[("grc", x["quotation"])] = x["speaker_id"] or ""
    ent_rows = {x["entity"]: x for x in tsv(os.path.join(DATA, "entities", "entities.tsv"))}

    def ent(a):
        x = ent_rows.get(a)
        return ekey(a, x["type"]) if x and x["type"] in TYPES else None

    chars = {x["character"]: (ent(x["entity"]) if x["entity"] else None)
             for x in tsv(os.path.join(DATA, "entities", "characters.tsv"))}
    addr = {}
    for x in tsv(os.path.join(DATA, "addressees", "quotations.tsv")):
        a = x["addressee"]
        addr[(x["corpus"], x["quote"])] = None if not a or a.startswith("lemma:") else ent(a)
    for lang in ("hbo", "arc", "grc"):
        corpus = "grc" if lang == "grc" else "hbo"
        K = pq.read_table(os.path.join(build, lang, "clauses.parquet"), columns=[
            "clause", "line", "quote", "speaker", "addressee", "quote_model", "speaker_model",
            "addressee_model"]).to_pydict()
        bad, diff = C.Counter(), C.Counter()
        for i in range(len(K["clause"])):
            q = seg.get(K["line"][i], "") or ""
            c = sid.get((corpus, q), "") if q else ""
            want = (f"q:{q}" if q else "", (chars.get(c) or "") if c else "", (addr.get((corpus, q)) or "") if q else "")
            strict = (K["quote"][i], K["speaker"][i], K["addressee"][i])
            exp = want if want != strict else (None, None, None)
            got = (K["quote_model"][i], K["speaker_model"][i], K["addressee_model"][i])
            bad["differ"] += got != exp
            if want != strict:
                diff["clauses written"] += 1
                for j, col in enumerate(("quote", "speaker", "addressee")):
                    diff[f"{col} differs"] += want[j] != strict[j]
        R.check(f"{lang} clauses: quote_model, speaker_model, addressee_model equal D10m over the validator's "
                "reviewed layers (written only where one differs from the strict value)", bad["differ"] == 0,
                bad["differ"])
        R.info(f"{lang} D10m: clauses written / quote differs / speaker differs / addressee differs",
               f"{diff['clauses written']:,} / {diff['quote differs']:,} / {diff['speaker differs']:,} / "
               f"{diff['addressee differs']:,}")


def subjects(R, build, STASH):
    for gname, group, greek in (("hbo+arc", ("hbo", "arc"), False), ("grc", ("grc",), True)):
        rows_of = STASH.get(f"s16 rows_of {gname}")
        if rows_of is None:
            R.check(f"{gname} D15m needs stage 16's D9 join (run --upto 17 whole)", False)
            continue
        got = rows_of[("main", "clause-subjects-model")]
        lex = C.defaultdict(list)
        for lg in group:
            for r in tsv(os.path.join(build, lg, "lexemes.tsv")):
                lex[(lg, nfc(r["lemma"]))].append((r["lexeme"], r["strong"]))
        for lg in group:
            K = pq.read_table(os.path.join(build, lg, "clauses.parquet"), columns=["clause", "subject_model"]).to_pydict()
            bad = 0
            for ck, v in zip(K["clause"], K["subject_model"]):
                r = got.get(ck)
                want = None
                if r is not None:
                    cands = lex.get((lg, nfc(r["participant"] or "")), [])
                    if r["participant_strong"]:
                        cands = [c for c in cands if "H" + c[1] == r["participant_strong"]]
                    want = cands[0][0] if len(cands) == 1 else None
                bad += v != want
            n = sum(1 for v in K["subject_model"] if v is not None)
            R.check(f"{lg} clauses: subject_model equals D15m recomputed (usable rows, D9 join, one lexeme)",
                    bad == 0, bad)
            R.info(f"{lg} D15m: clauses with subject_model / rows joined to the language's clauses",
                   f"{n:,} / {sum(1 for ck in K['clause'] if ck in got):,}")
            lk = {r["lexeme"] for r in tsv(os.path.join(build, lg, "lexemes.tsv"))}
            R.check(f"{lg} subject_model: every value is a lexeme key of lexemes.tsv",
                    all(v in lk for v in K["subject_model"] if v is not None))


def participants_model(R, build):
    ent_rows = {x["entity"]: x for x in tsv(os.path.join(DATA, "entities", "entities.tsv"))}
    acai = {ekey(a, x["type"]): a for a, x in ent_rows.items() if x["type"] in TYPES}
    for lang in ("hbo", "arc", "grc"):
        prow = tsv(os.path.join(build, lang, "participants.tsv"))
        K = pq.read_table(os.path.join(build, lang, "clauses.parquet"), columns=[
            "speaker_model", "addressee_model"]).to_pydict()
        strict = {r["ent"] for r in prow if r["ent_basis"] != "model"}
        model = {r["ent"]: r for r in prow if r["ent_basis"] == "model"}
        want = {e for c in ("speaker_model", "addressee_model") for e in K[c] if e} - strict
        R.check(f"{lang} participants: the model rows are exactly the ents only M columns name", set(model) == want,
                f"{len(model)} rows")
        ok = all(r["words"] == "0" and r["words_model"] == "" and e in acai and
                 r["sex"] == {"male": "m", "female": "f"}.get(ent_rows[acai[e]]["gender"], "") for e, r in model.items())
        R.check(f"{lang} participants: model rows have words 0, words_model empty (M2 absent), ACAI sex", ok)


def stage17(R, build, src, STASH):
    R.section("model attribution: every M column names dataset, version, model(s) (SPEC 2.4, 10)")
    attribution(R, build)
    R.section("M1 concepts recomputed")
    concepts(R, build)
    R.section("speech (model part): the validator's own reviewed layers (D10m)")
    speech_model(R, build)
    R.section("M3 subjects (D15m) recomputed over stage 16's D9 join")
    subjects(R, build, STASH)
    R.section("participants with ent_basis model")
    participants_model(R, build)
    R.section("strict view (SPEC 2.3): stage 16 rerun on the strict view equals it value by value")
    strict_check(R, build)
