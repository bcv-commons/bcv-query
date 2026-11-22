"""Stage 17 (SPEC 1.1, build c1): the columns of basis `model`.

    shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build c1 --stage 17

Fills, over the tables of stage 16 (whose strict columns and rows it leaves as they are):
- `pieces.concept`, `pieces.concept_by` (M1): hebrew-word-concepts-model v0.6 (hbo, arc), greek-nt-concepts-model v0.1
  (grc), joined by the piece key (`o` + the dataset's `key`; Greek `greek_id`). `-` where the row gives no concept.
- `clauses.quote_model`, `speaker_model`, `addressee_model` (M4, D10m): the reviewed layers (Hebrew:
  build_speaker_layer.py with its review rows, rebuilt into cache/speech-hbo-review/; Greek: the published layout) and
  every addressees row; written on every clause where one of the three differs from the strict value.
- `clauses.subject_model` (M3, D15m): clause-subjects-model v0.1 rows with `usable`, joined as D9 joins.
- `participants.tsv`: rows with `ent_basis` `model` for the ents only M columns name.
- the model part of categories.toml (after the people part, which is rewritten with the `model` count of `ent_basis`),
  and `sources.json` (the model sources; stage 20 writes the whole file and keeps this part).
Not filled (reported): `who` with basis `model` (D7m) and `participants.words_model`: entity-mentions-model is not on
disk in this repository (SPEC 5 / CHANGES-1.1 M2).
"""
import collections as C
import csv
import glob
import hashlib
import json
import os
import unicodedata

import pyarrow as pa
import pyarrow.parquet as pq

import examples_clauses as EC
import examples_common as X
import examples_people as EP
import examples_people11 as P11
import examples_src as S
import examples_values11 as V11

REPO = os.path.dirname(os.path.dirname(S.HERE))
DOCS = os.path.join(REPO, "internal-docs")
MARKER = "# ---- the model part (build_examples.py --stage 17) ----"
REVIEW_HBO = os.path.join(REPO, "resources", "speaker_layer", "review.tsv")
NT_REVIEW = os.path.join(REPO, "resources", "speaker_quotations", "nt_review.tsv")
NO_HUMAN = "no human check"

# the model datasets of SPEC 5; version and Hugging Face revision as SPEC 5 and internal-docs/dataset-pins.md record them
CONCEPTS = {
    "hbo": dict(key="hebrew-word-concepts-model", repo="bcv-commons/hebrew-word-concepts-model", version="v0.6",
                revision="dbdb2c9f", folder="hebrew-word-concepts-model-release/v0.6-release",
                file="data/tokens.parquet", licence="CC BY-SA 4.0"),
    "grc": dict(key="greek-nt-concepts-model", repo="bcv-commons/greek-nt-concepts-model", version="v0.1",
                revision="6f73ed21", folder="greek-nt-concepts-model-release/v0.1", file="data/words.parquet",
                licence="CC BY-SA 4.0"),
}
CONCEPTS["arc"] = CONCEPTS["hbo"]
SUBJECTS = dict(key="clause-subjects-model", repo="bcv-commons/clause-subjects-model", version="v0.1",
                revision="b241aa02d2248908ed39730bb34660847c0b7f1f", folder="clause-subjects-model-release/v0.1",
                files={"tan": "data/hebrew.parquet", "grc": "data/greek-nt.parquet"}, licence="as its card states",
                # the card's own words naming the model and the run (checked to stand in README.md)
                card_model="a language model (Jev, by typesafe.ai)", card_run="research's run of 2026-11-03")
MENTIONS = dict(key="entity-mentions-model", repo="bcv-commons/entity-mentions-model", version="v0.1",
                revision="fd066bec02a880a6f747406caf0cb7614434ab83",
                looked_in=["shoresh/macula/data/entity-mentions-model", "internal-docs/entity-mentions-model-release",
                           "shoresh/macula/data/entity-mentions", "internal-docs/entity-mentions-release"])


def nfc(s):
    return unicodedata.normalize("NFC", s)


def sha_file(p):
    return S.sha256(p)


def checked_release(folder):
    """Every line of the release's SHA256SUMS holds for the files on disk -> {file: sha256}."""
    d = os.path.join(DOCS, folder)
    out = {}
    with open(os.path.join(d, "SHA256SUMS"), encoding="utf-8") as fh:
        for ln in fh:
            h, f = ln.split(None, 1)
            f = f.strip()
            got = sha_file(os.path.join(d, f))
            if got != h:
                raise SystemExit(f"stage 17: {folder}/{f}: sha256 {got} is not the release's {h}")
            out[f] = h
    return out


# ---- M1 concepts ---------------------------------------------------------------------------------------------------

def concept_source(lang):
    c = CONCEPTS[lang]
    d = os.path.join(DOCS, c["folder"])
    files = checked_release(c["folder"])
    with open(os.path.join(d, "build.json"), encoding="utf-8") as fh:
        b = json.load(fh)
    if b["version"] != c["version"]:
        raise SystemExit(f"stage 17: {c['folder']}/build.json is version {b['version']}, not {c['version']}")
    if lang == "grc":
        models = [b["models"]]
        run = f"built {b['built']}, code {b['code']}"
        per_stage = None
    else:
        per_stage = []
        models = []
        for st, v in b["stages"].items():
            row = {"stage": st, "date": v.get("date"), "opus_model": v.get("opus_model"),
                   "jev_model": v.get("jev_model")}
            per_stage.append(row)
            for m in (v.get("opus_model"), v.get("jev_model")):
                if isinstance(m, str) and m and m not in models:
                    models.append(m)
        run = f"built {b['built']}; stages " + ", ".join(f"{r['stage']} ({r['date']})" for r in per_stage)
    return dict(c, files=files, models=models, per_stage=per_stage, run=run, human_check=NO_HUMAN,
                card=os.path.relpath(os.path.join(d, "README.md"), REPO),
                build_json=os.path.relpath(os.path.join(d, "build.json"), REPO))


def concepts(lang, P, cnt):
    c = CONCEPTS[lang]
    t = pq.read_table(os.path.join(DOCS, c["folder"], c["file"])).to_pylist()
    rows = {}
    if lang == "grc":
        for r in t:
            rows[r["greek_id"]] = ("-" if r["none"] or not r["concept"] else r["concept"], X.c0(r["labeller"]))
    else:
        for r in t:
            if r["lang"] == lang:
                rows["o" + r["key"]] = (r["concept"] or "-", X.c0(r["labeller"]))
    pids = set(P["pid"])
    cnt[f"{lang} M1 dataset rows"] = len(rows)
    cnt[f"{lang} M1 dataset rows with no piece"] = sum(1 for k in rows if k not in pids)
    if cnt[f"{lang} M1 dataset rows with no piece"]:
        raise SystemExit(f"stage 17: {lang} concept rows whose key is no piece")
    concept, by = [], []
    for pid, kind in zip(P["pid"], P["kind"]):
        got = rows.get(pid)
        concept.append(None if got is None else got[0])
        by.append(None if got is None else got[1])
        if got is not None:
            cnt[f"{lang} M1 pieces with a row, kind {kind}"] += 1
    return concept, by


# ---- M4 speech by the reviewed layers (D10m) ---------------------------------------------------------------------

def reviewed_sources(outdir):
    folder = os.path.join(outdir, "cache", "speech-hbo-review")
    log = folder + ".log"
    import subprocess
    import sys
    with open(log, "w", encoding="utf-8") as fh:
        r = subprocess.run([sys.executable, "-I", os.path.join(S.HERE, "examples_speech_src.py"), "hbo-review",
                            folder], stdout=fh, stderr=subprocess.STDOUT)
    if r.returncode:
        raise SystemExit(f"examples_speech_src.py hbo-review failed (log {log})")
    seg = {}
    for f in sorted(glob.glob(os.path.join(folder, "segments", "*.tsv"))):
        book = os.path.basename(f)[:-4]
        for row in EP.read_tsv(f):
            seg[f"{book}.{row['chapter']}.{row['verse']}.{row['seg']}"] = row["quotation"]
    quotes = {row["id"]: row for row in EP.read_tsv(os.path.join(folder, "quotations.tsv"))}
    return seg, quotes


def review_models(path):
    """The `source` of every review row, counted (the rows name their model)."""
    rows = EP.read_tsv(path)
    return dict(sorted(C.Counter(r["source"] for r in rows).items())), len(rows)


def d10m(K_by, greek, outdir, E, chars, cnt):
    tag = "grc" if greek else "tan"
    if greek:
        seg, _quotes, layout_sid = EP.grc_speech(outdir)
        sid = layout_sid
    else:
        seg, quotes = reviewed_sources(outdir)
        sid = {q: r["speaker_id"] for q, r in quotes.items()}
    addr = {}
    for r in EP.read_tsv(EP.ADDR):
        if r["corpus"] != ("grc" if greek else "hbo"):
            continue
        a = r["addressee"]
        if not a:
            addr[r["quote"]] = None
        elif a.startswith("lemma:"):
            cnt[f"{tag} D10m addressees rows whose addressee is lemma:<strong>, none"] += 1
            addr[r["quote"]] = None
        else:
            addr[r["quote"]] = E.ent(a, f"{tag} D10m addressee")
    out = {}
    for lang, K in K_by.items():
        qm, sm, am = [], [], []
        for line, q, s, a in zip(K["line"], K["quote"], K["speaker"], K["addressee"]):
            rq = seg.get(line, "") or ""
            if rq and rq not in sid:
                raise SystemExit(f"{lang}: reviewed quotation {rq} of line {line} not in its quotation table")
            c = sid.get(rq, "") if rq else ""
            rs = (chars.get(c) or "") if c else ""
            if c and c not in chars:
                cnt[f"{lang} D10m clauses whose reviewed character id is not in characters.tsv"] += 1
            ra = (addr.get(rq) or "") if rq else ""
            want = (f"q:{rq}" if rq else "", rs, ra)
            if want != (q, s, a):
                qm.append(want[0])
                sm.append(want[1])
                am.append(want[2])
                for col, x, y in (("quote", want[0], q), ("speaker", want[1], s), ("addressee", want[2], a)):
                    if x != y:
                        cnt[f"{lang} D10m clauses whose reviewed {col} differs from the strict one"] += 1
                        if not x:
                            cnt[f"{lang} D10m ... of them: reviewed {col} empty, strict filled"] += 1
                        elif not y:
                            cnt[f"{lang} D10m ... of them: reviewed {col} filled, strict empty"] += 1
                cnt[f"{lang} D10m clauses with the three _model columns written"] += 1
            else:
                qm.append(None)
                sm.append(None)
                am.append(None)
        out[lang] = (qm, sm, am)
    return out


# ---- M3 subjects (D15m) --------------------------------------------------------------------------------------------

def subjects(outdir, gl, greek, terms, cnt, T):
    tag = "grc" if greek else "tan"
    f = os.path.join(DOCS, SUBJECTS["folder"], SUBJECTS["files"][tag])
    allrows = pq.read_table(f).to_pylist()
    rows = [r for r in allrows if r["usable"]]
    cnt[f"{tag} D15m dataset rows / usable"] = f"{len(allrows)} / {len(rows)}"
    c2, e2, p2, x2 = C.Counter(), C.defaultdict(list), {}, {}
    ds = "clause-subjects-model"
    V = V11.compute(outdir, gl, greek, c2, e2, p2, x2, terms, more={ds: rows})
    for k, v in c2.items():
        if ds in k:
            cnt[k.replace("D9", "D15m (D9 join)")] = v
    got = V["rows_of"][("main", ds)]
    lex = C.defaultdict(list)
    for lg in gl:
        with open(os.path.join(outdir, lg, "lexemes.tsv"), encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
                lex[(lg, nfc(r["lemma"]))].append((r["lexeme"], r["strong"]))
    out = {}
    for lg in gl:
        K = T[lg]["K"]
        vals = []
        for ck in K["clause"]:
            r = got.get(ck)
            if r is None:
                vals.append(None)
                continue
            cands = lex.get((lg, nfc(r["participant"] or "")), [])
            if r["participant_strong"]:
                cands = [c for c in cands if "H" + c[1] == r["participant_strong"]]
            if len(cands) == 1:
                vals.append(cands[0][0])
                cnt[f"{lg} D15m clauses with subject_model"] += 1
            else:
                vals.append(None)
                why = "no lexeme" if not cands else "two or more lexemes"
                cnt[f"{lg} D15m joined rows left null: {why} with the lemma"
                    f"{' and Strong' if r['participant_strong'] else ''}"] += 1
        out[lg] = vals
    return out


def subject_vs_strict(lg, K, N, P, vals, cnt):
    """The subject_model lexeme against the stem lexeme of the head word of the clause's `s` constituents."""
    stem = {t: lx for t, k, lx in zip(P["t"], P["kind"], P["lexeme"]) if k == "stem"}
    s_of = C.defaultdict(set)
    for ck, role, h in zip(N["clause"], N["role"], N["head"]):
        if role == "s" and h:
            s_of[ck].add(stem.get(h))
    for ck, v in zip(K["clause"], vals):
        if v is None:
            continue
        if ck not in s_of:
            cnt[f"{lg} D15m subject_model on a clause with no s constituent"] += 1
        elif v in s_of[ck]:
            cnt[f"{lg} D15m subject_model equals the s constituent's head lexeme"] += 1
        else:
            cnt[f"{lg} D15m subject_model differs from the s constituent's head lexeme"] += 1


# ---- categories.toml, sources.json ---------------------------------------------------------------------------------

def tq(s):
    return X.toml_str(s)


def model_part(lang, P, K, prows, src):
    cs = src["concepts"]
    out = [MARKER, "",
           "# M2 (entity-mentions-model v0.1, fd066bec): not on disk in this repository; D7m is not applied, so no",
           "# `who` has basis `model` and `participants.words_model` is empty (SPEC 4.10: said so).", ""]
    files = cs["files"]
    out += ["[pieces.concept]", 'column = "concept"', 'basis = "model"', f"dataset = {tq(cs['repo'])}",
            f"version = {tq(cs['version'])}", f"revision = {tq(cs['revision'])}",
            "models = [" + ", ".join(tq(m) for m in cs["models"]) + "]", f"run = {tq(cs['run'])}",
            f"human_check = {tq(NO_HUMAN)}",
            f"source = {tq('internal-docs/' + cs['folder'] + '/' + cs['file'] + ' sha256 ' + files[cs['file']])}",
            'pattern = "the dataset\'s concept code (H<Strong>.<n>); - where its row gives none; null where no row"',
            f"count = {sum(1 for v in P['concept'] if v is not None)}",
            f"distinct = {len({v for v in P['concept'] if v is not None})}", ""]
    bc = C.Counter(v for v in P["concept_by"] if v is not None)
    out += ["[pieces.concept_by]", 'column = "concept_by"', 'basis = "model"', f"dataset = {tq(cs['repo'])}",
            f"version = {tq(cs['version'])}", f"revision = {tq(cs['revision'])}",
            "models = [" + ", ".join(tq(m) for m in cs["models"]) + "]", f"run = {tq(cs['run'])}",
            f"human_check = {tq(NO_HUMAN)}",
            f"source = {tq('the labeller column of ' + cs['file'])}", "values = ["]
    for code in sorted(bc):
        out.append(f"  {{ code = {tq(code)}, value = {tq(src['labeller_value'][code])}, rule = \"C0\", "
                   f"count = {bc[code]} }},")
    out += ["]", ""]
    sp = src["speech"]
    for col in ("quote_model", "speaker_model", "addressee_model"):
        vals = [v for v in K[col] if v is not None]
        out += [f"[clauses.{col}]", f'column = "{col}"', 'basis = "model"', f"dataset = {tq(sp['dataset'])}",
                f"version = {tq(sp['version'])}",
                "models = [" + ", ".join(tq(m) for m in sp["models"]) + "]", f"run = {tq(sp['run'])}",
                f"human_check = {tq(NO_HUMAN)}", f"source = {tq(sp['source'])}",
                f"pattern = {tq(('q:<quotation id>' if col == 'quote_model' else 'an ent key') + '; empty string where the reviewed layer has none; null where all three equal the strict columns')}",
                f"count = {len(vals)}", f"empty = {sum(1 for v in vals if v == '')}", ""]
    su = src["subjects"]
    out += ["[clauses.subject_model]", 'column = "subject_model"', 'basis = "model"', f"dataset = {tq(su['repo'])}",
            f"version = {tq(su['version'])}", f"revision = {tq(su['revision'])}",
            "models = [" + tq(su["card_model"]) + "]", f"run = {tq(su['card_run'])}", f"human_check = {tq(NO_HUMAN)}",
            f"source = {tq('internal-docs/' + su['folder'] + '/' + su['file'] + ' sha256 ' + su['sha256'])}",
            'pattern = "a lexeme key of lexemes.tsv (D15m); null where none"',
            f"count = {sum(1 for v in K['subject_model'] if v is not None)}", ""]
    out += ["[participants.words_model]", 'column = "words_model"', 'basis = "model"', f"dataset = {tq(MENTIONS['repo'])}",
            f"version = {tq(MENTIONS['version'])}", f"revision = {tq(MENTIONS['revision'])}", "filled = false",
            'why = "the dataset is not on disk in this repository (D7m not applied)"', ""]
    return "\n".join(out)


def sources_json(lang, src):
    greek = lang == "grc"
    cs = src["concepts"]
    model = {cs["key"]: {"repo": cs["repo"], "version": cs["version"], "revision": cs["revision"],
                         "path": cs["folder"], "files": cs["files"], "models": cs["models"],
                         "models_per_stage": cs["per_stage"], "run": cs["run"], "human_check": NO_HUMAN,
                         "licence": cs["licence"], "card": cs["card"], "build_json": cs["build_json"],
                         "columns": ["pieces.concept", "pieces.concept_by"], "basis": "model (M1)"}}
    su = src["subjects"]
    model[su["key"]] = {"repo": su["repo"], "version": su["version"], "revision": su["revision"],
                        "path": su["folder"], "files": su["all_files"], "models": [su["card_model"]],
                        "run": su["card_run"], "human_check": NO_HUMAN, "licence": su["licence"],
                        "card": os.path.join("internal-docs", su["folder"], "README.md"),
                        "columns": ["clauses.subject_model"], "basis": "model (M3)"}
    sp = src["speech"]
    model[sp["key"]] = {"dataset": sp["dataset"], "version": sp["version"], "files": sp["files"],
                        "models": sp["models"], "rows_by_source": sp["rows_by_source"], "run": sp["run"],
                        "human_check": NO_HUMAN, "columns": ["clauses.quote_model", "clauses.speaker_model",
                                                             "clauses.addressee_model"],
                        "basis": "model (M4)", "english_evidence": sp["english_evidence"]}
    model[MENTIONS["key"]] = {"repo": MENTIONS["repo"], "version": MENTIONS["version"],
                              "revision": MENTIONS["revision"], "status": "not on disk in this repository; not read",
                              "looked_in": MENTIONS["looked_in"], "columns_not_filled": [
                                  "pieces.who (basis model, D7m)", "participants.words_model"], "basis": "model (M2)"}
    return {"part": "stage 17: the model sources (SPEC 2.4, 4.10); stage 20 writes the whole file and keeps this part",
            "lang": lang, "model": model,
            "pyarrow": pa.__version__, "greek": greek}


# ---- build ---------------------------------------------------------------------------------------------------------

def build(outdir, langs, counts):
    ex = C.defaultdict(list)
    cnt = C.Counter()
    langs = set(langs)
    if {"hbo", "arc"} & langs and not {"hbo", "arc"} <= langs:
        raise SystemExit("stage 17: hbo and arc are built together")
    for p in MENTIONS["looked_in"]:
        if os.path.exists(os.path.join(REPO, p)):
            raise SystemExit(f"stage 17: {p} is now on disk; D7m (who by a model) is not implemented yet")
    terms = {lg: V11.read_terms(outdir, lg) for lg in langs}
    E = EP.Entities(cnt)
    chars = EP.characters(E, C.Counter())
    pins = {os.path.relpath(p, S.HERE): S.sha256(p) for p in (
        os.path.join(EP.ENT, "entity_words.tsv"), EP.ADDR)}
    su_files = checked_release(SUBJECTS["folder"])
    with open(os.path.join(DOCS, SUBJECTS["folder"], "README.md"), encoding="utf-8") as fh:
        card = fh.read()
    for k in ("card_model", "card_run"):
        if SUBJECTS[k] not in card:
            raise SystemExit(f"stage 17: the clause-subjects-model card does not say {SUBJECTS[k]!r}")
    rev_by, rev_n = review_models(REVIEW_HBO)
    nt_by, nt_n = review_models(NT_REVIEW)
    groups = ([(("hbo", "arc"), False)] if "hbo" in langs else []) + ([(("grc",), True)] if "grc" in langs else [])
    for gl, greek in groups:
        tag = "grc" if greek else "tan"
        T = {}
        for lg in gl:
            d = os.path.join(outdir, lg)
            T[lg] = dict(P=pq.read_table(os.path.join(d, "pieces.parquet")).to_pydict(),
                         K=pq.read_table(os.path.join(d, "clauses.parquet")).to_pydict(),
                         N=pq.read_table(os.path.join(d, "constituents.parquet"),
                                         columns=["clause", "role", "head"]).to_pydict())
            P = T[lg]["P"]
            if any(b not in ("", "explicit", "pronominal", "subject", "chain")
                   + (("reference",) if getattr(X, "V13", False) else ()) for b in P["who_basis"]):   # 1.3 D7r
                raise SystemExit(f"stage 17: {lg} who_basis holds a value stage 16 does not write")
        speech = d10m({lg: T[lg]["K"] for lg in gl}, greek, outdir, E, chars, cnt)
        subj = subjects(outdir, gl, greek, terms, cnt, T)
        if greek:
            sp = dict(key="greek-nt-clause-layout-reviewed", dataset="greek-nt-clause-layout (the published layout, "
                      "data/nt-clause-layout, with its review rows) and addressees",
                      version="data/nt-clause-layout build.json built 2026-10-29; data/addressees code 4ee0442",
                      models=sorted(nt_by), rows_by_source={"resources/speaker_quotations/nt_review.tsv": nt_by},
                      run="the review rows of resources/speaker_quotations/nt_review.tsv as the published layout "
                          "applied them",
                      files={"resources/speaker_quotations/nt_review.tsv": S.sha256(NT_REVIEW),
                             "data/addressees/quotations.tsv": pins["data/addressees/quotations.tsv"],
                             "data/nt-clause-layout/build.json": S.sha256(os.path.join(EP.D, "nt-clause-layout",
                                                                                       "build.json"))},
                      source="the published Greek layout's quotation and speaker_id; every data/addressees row")
        else:
            sp = dict(key="hebrew-speaker-layer-reviewed", dataset="hebrew speaker layer with its review rows "
                      "(build_speaker_layer.py, rebuilt into cache/speech-hbo-review/) and addressees",
                      version="resources/speaker_layer/review.tsv sha256 " + S.sha256(REVIEW_HBO)[:16]
                              + "; data/addressees code 4ee0442",
                      models=sorted(rev_by), rows_by_source={"resources/speaker_layer/review.tsv": rev_by},
                      run="the review rows of resources/speaker_layer/review.tsv (" + str(rev_n) + " rows)",
                      files={"resources/speaker_layer/review.tsv": S.sha256(REVIEW_HBO),
                             "data/addressees/quotations.tsv": pins["data/addressees/quotations.tsv"]},
                      source="build_speaker_layer.py with review rows; every data/addressees row")
        sp["english_evidence"] = ("as the strict speech columns (D10): quotation spans and speaker ids rest on "
                                  "English translations' marks and labels; no English value enters")
        for lg in gl:
            P, K, N = T[lg]["P"], T[lg]["K"], T[lg]["N"]
            d = os.path.join(outdir, lg)
            cs = concept_source(lg)
            P["concept"], P["concept_by"] = concepts(lg, P, cnt)
            K["quote_model"], K["speaker_model"], K["addressee_model"] = speech[lg]
            K["subject_model"] = subj[lg]
            subject_vs_strict(lg, K, N, P, K["subject_model"], cnt)
            # concept code's Strong's number against the piece's own (Hebrew; a check of the join)
            if not greek:
                strong = {}
                with open(os.path.join(d, "lexemes.tsv"), encoding="utf-8", newline="") as fh:
                    for r in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
                        strong[r["lexeme"]] = r["strong"]
                def num(x):
                    return x.lstrip("H").lstrip("0")
                for lx, cc in zip(P["lexeme"], P["concept"]):
                    if cc and cc != "-":
                        a_, b_ = num(strong[lx]), num(cc.split(".")[0])
                        how = ("equals" if a_ == b_ else "has the same number, another letter than" if
                               a_.rstrip("abcdefghijklmnopqrstuvwxyz") == b_.rstrip("abcdefghijklmnopqrstuvwxyz")
                               else "differs from")
                        cnt[f"{lg} M1 concept code's Strong's (leading zeros aside) {how} the piece's"] += 1
                        if how == "differs from":
                            ex[f"{lg} M1 concept code's Strong's differs from the piece's (concept strong)"].append(
                                f"{cc} {strong[lx]}")
            # participants: strict rows as stage 16 wrote them, then the model rows
            path = os.path.join(d, "participants.tsv")
            with open(path, encoding="utf-8", newline="") as fh:
                rdr = csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
                hdr = next(rdr)
                strict = [r for r in rdr if r[7] != "model"]
            if hdr != P11.PART_HEADER:
                raise SystemExit(f"stage 17: {path} header {hdr}")
            have = {r[0] for r in strict}
            mod = sorted({e for col in ("speaker_model", "addressee_model") for e in K[col] if e} - have)
            rows = [tuple(r) for r in strict]
            for e in mod:
                acai = E.acai_of[e]
                r = E.rows[acai]
                nm = P11.name_of_acai(E, acai, lg)
                rows.append((e, V11.term_of(terms, lg, "ent_type", r["type"]), nm, "given" if nm else "",
                             EP.SEX.get(r["gender"], ""), "0", "", "model"))
                cnt[f"{lg} participants with ent_basis model (named {'given' if nm else 'none'})"] += 1
            rows.sort(key=lambda r: r[0])
            X.write_tsv(path, P11.PART_HEADER, rows)
            counts[f"{lg} participants with ent_basis model"] = [[r[0], r[2]] for r in rows if r[7] == "model"]
            # tables
            X.write_parquet(os.path.join(d, "pieces.parquet"), P, pa.schema(P11.V11_PIECE_COLS()))
            X.write_parquet(os.path.join(d, "clauses.parquet"), K, pa.schema(EC.CLAUSE_COLS_11))
            su = dict(SUBJECTS, file=SUBJECTS["files"][tag], sha256=su_files[SUBJECTS["files"][tag]],
                      all_files=su_files)
            lab = {}
            t = pq.read_table(os.path.join(DOCS, cs["folder"], cs["file"]), columns=["labeller"]).to_pydict()
            for v in set(t["labeller"]):
                lab[X.c0(v)] = v
            src = dict(concepts=cs, speech=sp, subjects=su, labeller_value=lab)
            cpath = os.path.join(d, "categories.toml")
            with open(cpath, encoding="utf-8") as fh:
                text = fh.read()
            if P11.MARKER not in text:
                raise SystemExit(f"stage 17: {cpath} has no stage-16 people part; run stage 16 first")
            before = text.split(P11.MARKER)[0]
            prows = [tuple(r) for r in rows]
            X.write_text(cpath, before + P11.people_part(lg, P, K, prows, terms[lg], pins) + "\n"
                         + model_part(lg, P, K, prows, src))
            with open(os.path.join(d, "sources.json.tmp"), "w", encoding="utf-8", newline="\n") as fh:
                json.dump(sources_json(lg, src), fh, ensure_ascii=False, indent=1, sort_keys=True)
                fh.write("\n")
            os.replace(os.path.join(d, "sources.json.tmp"), os.path.join(d, "sources.json"))
            # coverage
            n = len(P["pid"])
            cnt[f"{lg} M1 pieces with concept (of {n})"] = sum(1 for v in P["concept"] if v is not None)
            cnt[f"{lg} M1 pieces with concept '-'"] = sum(1 for v in P["concept"] if v == "-")
            stems = [(k, cl, v) for k, cl, v in zip(P["kind"], P["class"], P["concept"]) if k == "stem"]
            for cl in sorted({x[1] for x in stems}):
                tot = sum(1 for x in stems if x[1] == cl)
                hit = sum(1 for x in stems if x[1] == cl and x[2] is not None)
                if hit:
                    counts.setdefault(f"{lg} M1 stem pieces with concept by class", {})[cl] = f"{hit} / {tot}"
            counts[f"{lg} M1 concept_by"] = dict(sorted(C.Counter(v for v in P["concept_by"] if v).items()))
            cnt[f"{lg} clauses (of {len(K['clause'])}) with subject_model"] = sum(
                1 for v in K["subject_model"] if v is not None)
    counts["review rows by source"] = {"resources/speaker_layer/review.tsv": rev_by,
                                       "resources/speaker_quotations/nt_review.tsv": nt_by}
    for k in sorted(cnt):
        counts[k] = cnt[k]
    return ex
