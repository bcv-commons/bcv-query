"""Stage 19 of the source examples: links to another text as SPEC 1.1 defines them (4.8 `rendered_by`, 4.9, D13,
D13a, D13m, D14; model data M5, M6, M7).

Writes:
  <build>/other/lxx/words.parquet          once per text: s, id, book, chapter, verse, w, text, lemma, class
                                            (values as stage 08 wrote them; `lemma`, `class` are GLAUx's automatic
                                            annotation, basis M7)
  <build>/other/heb_scg|heb_mod/words.parquet   the same columns, plus `analysis`, `analysis_basis` (D14, M6)
  <lang>/links.parquet          t, n, other, s, how, agree, basis, agree_model
  <lang>/link_account.parquet   t, n, other, state, reason, state_model
  <lang>/facts.parquet          anew: the rows of earlier stages kept, `rendered_by` rows rebuilt
  <lang>/categories.toml        the links part (after the earlier parts)
  <lang>/sources.json           the model entries of M5, M6, M7 added to stage 17's `model` part; a `links` part

The placement is stage 08's (examples_links.lxx_place, examples_links.nt_compute), so the strict links are those of
`b1`. Basis `model` (SPEC 4.9, M7) goes to every link whose rule reads GLAUx's lemma or the Strong's number GLAUx's
store makes from that lemma (shoresh/lxx/build_glaux.py: "strong: lemma -> Strong's number"):
  bridge `number`       the bridge (bridge_corpus_lxx.place) matches the Septuagint word's number, i.e. GLAUx's lemma
  `lemma`, `verse_lemma` stage 08's rules on GLAUx's lemma (D13a names them)
  `verse_number`        stage 08's rule on the Septuagint word's number
  `form_near`           only where its number guard (which reads the same numbers) removed a candidate, so that the
                        numbers chose the word; where it removed none, the link rests on the form and stays `linked`
`agree` = 1 on a `linked` row (one model-free alignment gives it), 0 on a `model` row.

D13m: every link of hebrew-nt-bridge v0.1 (`internal-docs/hebrew-nt-bridge-release/v0.1/`, revision 525db08f; the
working copy's reviewed heb_mod has no revision that can be named) whose `link` is a review class, resolved to
(Greek word t, edition word s), that no strict link has, is a row with basis `model`, how `review_<C0 of the class>`;
where one (t, s) has several classes, the first code by code point. `agree_model` of a Hebrew New Testament row = (a
reviewed link gives (t, s)) + (a part link of hebrew-nt-part-links 2026-11-19 with runs >= 3 gives it). Septuagint
rows: null (no model alignment of the Septuagint exists).

D13 is counted over strict links only; `state_model` = `linked` where a model link exists and `state` is not.

D14: the parts of hebrew-nt-analysis v0.2 per edition token, in order, as {"class": C0 of class, "lemma", "text"};
`analysis_basis` `derived` where every part has source `macula`, else `model`. A token whose own `token` holds no
Hebrew letter (the English book names in heb_mod) gets no analysis (counted).

`rendered_by` (4.8) from the `linked` rows only: to `<text>:form:<normalised form>` with kind `linked`, and for the
Septuagint also to `lxx:<GLAUx lemma>` with kind `model` (M7) where GLAUx has a lemma. `count` = links, `share` = count
over the lexeme's links to that text that give a row of that kind.
"""
import collections as C
import hashlib
import json
import os

import pyarrow as pa
import pyarrow.parquet as pq

import examples_common as X
import examples_links as EL
from examples_people import FACT_SCHEMA

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DOCS = os.path.join(ROOT, "internal-docs")
MARKER = "# ---- the links part (build_examples.py --stage 19) ----"
NO_HUMAN = "no human check"
MODEL_HOW_LXX = ("number", "lemma", "verse_lemma", "verse_number")     # read GLAUx's lemma (or its number) always
REVIEW = ("kept", "inside", "part", "edited", "edited-wide")
NTB = {"key": "hebrew-nt-bridge", "repo": "bcv-commons/hebrew-nt-bridge", "version": "v0.1",
       "revision": "525db08f", "folder": "hebrew-nt-bridge-release/v0.1",
       "models": ["Jev (TypeSafe), the review of the heb_scg links (bcv-commons/alignments-by-id v1.0)"],
       "run": "release v0.1, built 2026-11-16 from bcv-query 6c5fece", "licence": "CC BY 4.0",
       "card_phrase": "were reviewed by a model (Jev, TypeSafe)"}
PARTS = {"key": "hebrew-nt-part-links", "folder": "shoresh/macula/data/hebrew-nt-part-links/2026-11-19",
         "version": "2026-11-19", "min_runs": 3,
         "models": ["eflomal (5 runs) over the parts of hebrew-nt-analysis v0.2 (the tagger) with its verses paired "
                    "through hebrew-nt-bridge v0.1's heb_scg links (Jev's review), as its build.json inputs state"],
         "run": "build.json of 2026-11-19 (runs 5, min_split 0.9)", "licence": "as its build.json states"}
ANA = {"key": "hebrew-nt-analysis", "repo": "bcv-commons/hebrew-nt-analysis", "version": "v0.2",
       "revision": "0c9132c3", "folder": "hebrew-nt-analysis-release/v0.2",
       "models": ["the tagger trained on MACULA Hebrew (python -m macula.clause_tagger; heb_mod: the unpointed model)"],
       "run": "release v0.2 (model files' SHA-256 in each edition's manifest.json)", "licence": "CC BY 4.0",
       "card_phrase": "come from a tagger trained on MACULA Hebrew"}
GLAUX = {"key": "glaux", "dataset": "GLAUx (KU Leuven, A. Keersmaekers), shoresh/lxx/data/lxx-glaux.db",
         "version": "spine release lxx-glaux-2026-10-10", "sha256": EL.GLAUX_SHA,
         "models": ["GLAUx's automatic lemmatisation and part-of-speech tagging by its makers (Genesis hand-checked "
                    "in Pedalion Trees, the rest automatic, as shoresh/lxx/build_glaux.py states)"],
         "run": "GLAUx's own annotation", "licence": "CC BY-SA 4.0"}

OTHER_SCHEMA = EL.OTHER_SCHEMA
HEB_SCHEMA = pa.schema(list(EL.OTHER_SCHEMA) + [("analysis", pa.string()), ("analysis_basis", pa.string())])
LINK_SCHEMA = pa.schema([("t", pa.int64()), ("n", pa.int64()), ("other", pa.string()), ("s", pa.int64()),
                         ("how", pa.string()), ("agree", pa.int64()), ("basis", pa.string()),
                         ("agree_model", pa.int64())])
ACCOUNT_SCHEMA = pa.schema([("t", pa.int64()), ("n", pa.int64()), ("other", pa.string()), ("state", pa.string()),
                            ("reason", pa.string()), ("state_model", pa.string())])
LXX_HOW_SOURCE = {"sure": "hebrew-greek-cf v0.2 bridges/lxx.parquet", "order": "hebrew-greek-cf v0.2 bridges/lxx.parquet",
                  "neighbours": "hebrew-greek-cf v0.2 bridges/lxx.parquet",
                  "number": "hebrew-greek-cf v0.2 bridges/lxx.parquet",
                  "lemma": "D13a", "form_near": "D13a", "verse_form": "D13a", "verse_lemma": "D13a",
                  "verse_number": "D13a"}


def sha(path):
    return EL.sha256(path)


def checked_release(folder):
    """{file: sha256} of a release folder, each file checked against its SHA256SUMS"""
    out = {}
    with open(os.path.join(folder, "SHA256SUMS"), encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                h, f = line.split(None, 1)
                f = f.strip()
                if sha(os.path.join(folder, f)) != h:
                    raise SystemExit(f"{folder}/{f}: sha256 is not the one in SHA256SUMS")
                out[f] = h
    return out


def card_has(folder, phrase):
    with open(os.path.join(folder, "README.md"), encoding="utf-8") as fh:
        if phrase not in fh.read():
            raise SystemExit(f"{folder}/README.md no longer says {phrase!r}; the model attribution must be read again")


def write_rows(path, rows, schema):
    X.write_parquet(path, {f.name: [r[i] for r in rows] for i, f in enumerate(schema)}, schema)


# ---- the Septuagint ------------------------------------------------------------------------------------------------

def build_lxx(outdir, counts, ex, cnt):
    st = C.Counter()
    decisive = set()
    R = EL.lxx_place(outdir, ex, st, decisive=decisive)
    words, pieces, links, want = R["words"], R["pieces"], R["links"], R["want"]
    counts["lxx placement (stage 08's)"] = dict(st)
    # what the strict links of stage 08's later rules owe to the model steps: the placement without them
    st2 = C.Counter()
    R2 = EL.lxx_place(outdir, {}, st2, skip=frozenset(MODEL_HOW_LXX))
    # basis per link
    rows = {}                                         # pid -> [(s, how, basis)]
    for pid, ls in links.items():
        rows[pid] = [(s, how, "model" if how in MODEL_HOW_LXX or (how == "form_near" and pid in decisive)
                      else "linked") for s, how in ls]
    strict = {pid for pid, ls in rows.items() if any(b == "linked" for _, _, b in ls)}
    model_only = {pid for pid, ls in rows.items() if pid not in strict}
    cnt["lxx form_near links whose number guard chose the word (basis model)"] = len(decisive)
    cnt["lxx form_near links"] = sum(1 for ls in links.values() for _, h in ls if h == "form_near")
    a = {pid: {(s, h) for s, h in ls if h not in MODEL_HOW_LXX and not (h == "form_near" and pid in decisive)}
         for pid, ls in links.items()}
    b = {pid: {(s, h) for s, h in ls} for pid, ls in R2["links"].items()}
    differ = sorted(pid for pid in set(a) | set(b) if a.get(pid, set()) != b.get(pid, set()))
    cnt["lxx strict links that would differ without the model steps (bridge number, lemma, verse_lemma, "
        "verse_number left out)"] = sum(1 for pid in differ if a.get(pid))
    cnt["lxx pieces a strict rule would place only without the model steps"] = sum(
        1 for pid in differ if not a.get(pid) and b.get(pid))
    cnt["lxx pieces a strict rule would place only without the model steps: on the word of the model link"] = sum(
        1 for pid in differ if not a.get(pid) and b.get(pid)
        and {s for s, _ in b[pid]} <= {s for s, _ in links.get(pid, ())})
    cnt["lxx pieces a strict rule would place only without the model steps: by rule"] = dict(sorted(C.Counter(h for pid in differ if not a.get(pid)
                                                      for _, h in b.get(pid, ())).items()))
    ex["lxx pieces whose strict link would differ without the model steps"] = differ
    # D13 over strict links, the Tanakh as one text
    cls_all, cls_linked = C.Counter(), C.Counter()
    for p in pieces:
        cls_all[p[3]] += 1
        cls_linked[p[3]] += p[2] in strict
    share = {c: cls_linked[c] / cls_all[c] for c in cls_all}
    naw = {c for c, v in share.items() if v < EL.NAW_SHARE}
    counts["lxx class shares over strict links (hbo+arc)"] = {c: [cls_linked[c], cls_all[c], round(share[c], 4)]
                                                              for c in sorted(cls_all)}
    counts["lxx never_a_word classes"] = sorted(naw)
    write_rows(os.path.join(outdir, "other", "lxx", "words.parquet"), words, OTHER_SCHEMA)
    out = {}
    for lang in ("hbo", "arc"):
        lrows, arows = [], []
        for p in pieces:
            if p[5] != lang:
                continue
            t, n, pid = p[0], p[1], p[2]
            for s, how, basis in sorted(rows.get(pid, ())):
                lrows.append((t, n, "lxx", s, how, 1 if basis == "linked" else 0, basis, None))
            g = want(p)
            if pid in strict:
                state, reason = "linked", ""
            elif p[3] in naw:
                state, reason = "never_a_word", p[3]
            elif g:
                state, reason = "unplaced", g[0]
            else:
                state, reason = "no_counterpart", ""
            arows.append((t, n, "lxx", state, reason, "linked" if pid in model_only else None))
        out[lang] = (lrows, arows)
    lem = {w[0]: w[7] for w in words}
    frm = {w[0]: X.norm_grc(w[6]) if w[6] else None for w in words}

    def objects(s):
        o = []
        if frm[s]:
            o.append((f"lxx:form:{frm[s]}", "linked", "links.parquet", "hebrew-greek-cf"))
        if lem[s]:
            o.append((f"lxx:{lem[s]}", "model", "links.parquet:glaux_lemma", "glaux"))
        return o
    return out, objects, {w[0]: w for w in words}


# ---- the Hebrew New Testaments -------------------------------------------------------------------------------------

def analysis_rows(ed, cnt):
    folder = os.path.join(DOCS, ANA["folder"])
    rows = pq.read_table(os.path.join(folder, ed, "words.parquet"),
                         columns=["book", "chapter", "verse", "i", "part", "token", "text", "class", "lemma",
                                  "source"]).to_pylist()
    by = C.defaultdict(list)
    for r in rows:
        by[(r["book"], r["chapter"], r["verse"], r["i"])].append(r)
    return by


def pclass(v):
    """C0 of an analysis class; the dataset's `-` (no class) has no C0 code and is written empty (reported)"""
    return "" if v == "-" else X.c0(v)


def heb_letter(s):
    return any("א" <= ch <= "ת" for ch in s or "")


def build_nt(outdir, counts, ex, cnt):
    st = C.Counter()
    all_l, all_a, other_words, P = EL.nt_compute(outdir, ex, st, counts)
    counts["nt (stage 08's)"] = dict(st)
    W = pq.read_table(os.path.join(outdir, "grc", "words.parquet"), columns=["t", "id"]).to_pylist()
    t_of = {w["id"]: w["t"] for w in W}
    cls = {p["t"]: p["class"] for p in P}
    checked_release(os.path.join(DOCS, NTB["folder"]))
    card_has(os.path.join(DOCS, NTB["folder"]), NTB["card_phrase"])
    checked_release(os.path.join(DOCS, ANA["folder"]))
    card_has(os.path.join(DOCS, ANA["folder"]), ANA["card_phrase"])
    strict = C.defaultdict(set)                    # ed -> {(t, s)}
    for t, n, ed, s, how, agree in all_l:
        strict[ed].add((t, s))
    lrows, mrows = [], []
    model_t = C.defaultdict(set)
    heb_words = {}
    for ed in EL.EDITIONS:
        s_of = {(r[2], r[3], r[4], r[5]): r[0] for r in other_words[ed]}
        # D14
        by = analysis_rows(ed, cnt)
        out = []
        for r in other_words[ed]:
            parts = sorted(by.get((r[2], r[3], r[4], r[5]), []), key=lambda x: x["part"])
            if not parts:
                cnt[f"{ed} words with no analysis row"] += 1
                out.append(tuple(r) + (None, None))
                continue
            if not heb_letter(parts[0]["token"]):
                cnt[f"{ed} words whose token holds no Hebrew letter: no analysis"] += 1
                ex.setdefault(f"{ed} words whose token holds no Hebrew letter", []).append(r[1])
                out.append(tuple(r) + (None, None))
                continue
            an = [{"class": pclass(x["class"]), "lemma": x["lemma"], "text": x["text"]} for x in parts]
            for x in parts:
                if pclass(x["class"]) == "":
                    cnt[f"{ed} analysis parts whose class {x['class']!r} has no C0 code (written empty)"] += 1
            srcs = {x["source"] for x in parts}
            basis = "derived" if srcs == {"macula"} else "model"
            if len(srcs) > 1:
                cnt[f"{ed} words whose parts mix sources"] += 1
            cnt[f"{ed} analysis_basis {basis}"] += 1
            out.append(tuple(r) + (X.jdump(an), basis))
        heb_words[ed] = out
        # M5: the reviewed links and the part links
        rev = C.defaultdict(set)
        if True:
            tab = pq.read_table(os.path.join(DOCS, NTB["folder"], "links", f"{ed}.parquet"),
                                columns=["greek_id", "book", "chapter", "verse", "i", "link"]).to_pylist()
            for r in tab:
                if r["link"] not in REVIEW:
                    cnt[f"{ed} bridge rows not a review class ({r['link']})"] += 1
                    continue
                t = t_of.get(r["greek_id"])
                s = s_of.get((r["book"], r["chapter"], r["verse"], r["i"]))
                if t is None or s is None:
                    cnt[f"{ed} reviewed rows that resolve to no word ({'greek' if t is None else 'edition'})"] += 1
                    continue
                rev[(t, s)].add(X.c0(r["link"]))
        cnt[f"{ed} reviewed (t, s) pairs"] = len(rev)
        cnt[f"{ed} reviewed (t, s) pairs with two or more classes"] = sum(1 for v in rev.values() if len(v) > 1)
        pf = os.path.join(ROOT, PARTS["folder"], ed)
        with open(os.path.join(pf, "build.json"), encoding="utf-8") as fh:
            bj = json.load(fh)
        if sha(os.path.join(pf, "part_links.parquet")) != bj["sha256"]:
            raise SystemExit(f"{pf}: part_links.parquet is not the file its build.json names")
        part = set()
        for r in pq.read_table(os.path.join(pf, "part_links.parquet"),
                               columns=["book", "chapter", "verse", "i", "greek_id", "runs"]).to_pylist():
            if r["runs"] < PARTS["min_runs"]:
                continue
            t = t_of.get(r["greek_id"])
            s = s_of.get((r["book"], r["chapter"], r["verse"], r["i"]))
            if t is None or s is None:
                cnt[f"{ed} part links (runs >= 3) that resolve to no word"] += 1
                continue
            part.add((t, s))
        cnt[f"{ed} part-link (t, s) pairs with runs >= 3"] = len(part)

        def am(ts):
            return int(ts in rev) + int(ts in part)
        S = strict[ed]
        for t, n, e, s, how, agree in all_l:
            if e == ed:
                lrows.append((t, n, ed, s, how, agree, "linked", am((t, s))))
        rev_t = C.defaultdict(set)
        for (t, s) in rev:
            rev_t[t].add(s)
        strict_t = C.defaultdict(set)
        for (t, s) in S:
            strict_t[t].add(s)
        for (t, s), classes in sorted(rev.items()):
            if (t, s) in S:
                continue
            mrows.append((t, 1, ed, s, "review_" + min(classes), 0, "model", am((t, s))))
            model_t[ed].add(t)
            cnt[f"{ed} model links added beside a strict link of the word" if strict_t.get(t)
                else f"{ed} model links added on a word with no strict link"] += 1
            if t in cls and cls[t] not in EL.NT_CONTENT:
                cnt[f"{ed} model links added on a word outside the alignment's classes"] += 1
        cnt[f"{ed} strict links confirmed by a reviewed link"] = sum(1 for ts in S if ts in rev)
        cnt[f"{ed} strict links contradicted (the reviewed links give the word only other words)"] = sum(
            1 for (t, s) in S if (t, s) not in rev and rev_t.get(t))
        cnt[f"{ed} strict links with no reviewed link on the word"] = sum(1 for (t, s) in S if not rev_t.get(t))
        cnt[f"{ed} strict links confirmed by a part link (runs >= 3)"] = sum(1 for ts in S if ts in part)
        cnt[f"{ed} strict links by agree_model"] = dict(sorted(C.Counter(am(ts) for ts in S).items()))
    arows = [(t, n, ed, state, reason, "linked" if state != "linked" and t in model_t[ed] else None)
             for t, n, ed, state, reason in all_a]
    for ed in EL.EDITIONS:
        write_rows(os.path.join(outdir, "other", ed, "words.parquet"), heb_words[ed], HEB_SCHEMA)
    forms = {ed: {r[0]: X.norm_heb(r[6]) if r[6] else None for r in other_words[ed]} for ed in EL.EDITIONS}

    def objects(ed):
        return lambda s: ([(f"{ed}:form:{forms[ed][s]}", "linked", "links.parquet", "compact-alignments")]
                          if forms[ed][s] else [])
    return lrows + mrows, arows, objects, heb_words


# ---- facts, categories, sources --------------------------------------------------------------------------------------

def write_facts(d, lang, lrows, object_fns, lexeme_of, cnt):
    path = os.path.join(d, "facts.parquet")
    old = [r for r in pq.read_table(path).to_pylist() if r["relation"] != "rendered_by"]
    pair = C.Counter()
    meta = {}
    for t, n, other, s, how, agree, basis, am in lrows:
        if basis != "linked":
            continue
        objs = object_fns[other](s)
        if not objs:
            cnt[f"{lang} strict links giving no rendered_by (word emptied)"] += 1
        for obj, kind, method, source in objs:
            k = (lexeme_of[(t, n)], other, kind, obj)
            pair[k] += 1
            meta[k] = (method, source)
    total = C.Counter()
    for (lx, other, kind, _), v in pair.items():
        total[(lx, other, kind)] += v
    new = [{"subject": lx, "relation": "rendered_by", "object": obj, "kind": kind, "method": meta[k][0],
            "source": meta[k][1], "confidence": None, "count": v, "share": v / total[(lx, other, kind)], "tier": ""}
           for k, v in pair.items() for (lx, other, kind, obj) in [k]]
    rows = sorted(old + new, key=lambda r: (r["subject"], r["relation"], r["object"]))
    X.write_parquet(path, {f.name: [r[f.name] for r in rows] for f in FACT_SCHEMA}, FACT_SCHEMA)
    cnt[f"{lang} facts rendered_by rows"] = len(new)
    for kind, v in sorted(C.Counter(r["kind"] for r in new).items()):
        cnt[f"{lang} facts rendered_by rows kind {kind}"] = v
    cnt[f"{lang} facts other rows kept"] = len(old)
    return new


def tq(s):
    return X.toml_str(s)


def values_block(name, column, basis, counter, value_of, extra=()):
    out = [f"[{name}]", f"column = {tq(column)}", f"basis = {tq(basis)}"] + list(extra) + ["values = ["]
    for code in sorted(counter):
        out.append(f"  {{ code = {tq(code)}, value = {tq(value_of(code))}, rule = \"C0\", count = {counter[code]} }},")
    return out + ["]", ""]


def attribution(src, revision=True):
    out = [f"dataset = {tq(src.get('repo') or src.get('dataset') or src['folder'])}", f"version = {tq(src['version'])}"]
    if revision and src.get("revision"):
        out.append(f"revision = {tq(src['revision'])}")
    out += ["models = [" + ", ".join(tq(m) for m in src["models"]) + "]", f"run = {tq(src['run'])}",
            f"human_check = {tq(NO_HUMAN)}"]
    return out


def links_part(lang, lrows, arows, other_rows, facts_new):
    out = [MARKER, ""]
    how = C.Counter(r[4] for r in lrows)
    hb = C.defaultdict(C.Counter)
    for r in lrows:
        hb[r[4]][r[6]] += 1
    out += ["[links.how]", 'column = "how"', 'basis = "the basis of each row is in links.basis"', "values = ["]
    for code in sorted(how):
        if lang == "grc":
            src = ("hebrew-nt-bridge v0.1 link class " + code[7:].replace("_", "-")) if code.startswith("review_") \
                else "lexeme-aligner method (compact-alignments .meta.json)"
        else:
            src = LXX_HOW_SOURCE[code]
        bases = ", ".join(f"{b} = {v}" for b, v in sorted(hb[code].items()))
        out.append(f"  {{ code = {tq(code)}, value = {tq(code if not code.startswith('review_') else code[7:].replace('_', '-'))}, "
                   f"source = {tq(src)}, count = {how[code]}, by_basis = {{ {bases} }} }},")
    out += ["]", ""]
    out += values_block("links.basis", "basis", "D (SPEC 4.9: model where a model placed or reviewed the link, or its "
                        "rule read a GLAUx lemma or class)", C.Counter(r[6] for r in lrows), lambda c: c)
    out += ["[links.agree]", 'column = "agree"', 'basis = "linked"',
            'pattern = "the number of model-free alignments that give the link: 1 on a linked row, 0 on a model row"',
            f"count = {len(lrows)}", ""]
    am = [r[7] for r in lrows if r[7] is not None]
    out += ["[links.agree_model]", 'column = "agree_model"', 'basis = "model"']
    if lang == "grc":
        out += attribution(NTB) + [f"also = {tq(PARTS['key'] + ' ' + PARTS['version'] + ': ' + PARTS['models'][0])}",
                                   'pattern = "reviewed links of hebrew-nt-bridge v0.1 that give (t, other, s) + part links with runs >= 3 that give it"',
                                   f"count = {len(am)}",
                                   "by_value = { " + ", ".join(f'"{k}" = {v}' for k, v in sorted(C.Counter(am).items())) + " }", ""]
    elif X.V12:
        out += attribution(GLAUX) + [
            'pattern = "strict rows: 1 where a bridge number link of the piece (it reads GLAUx\'s lemma through its Strong\'s number, M7) names the same Septuagint word, else 0; model rows: null (SPEC 1.2 D13a)"',
            f"count = {len(am)}",
            "by_value = { " + ", ".join(f'"{k}" = {v}' for k, v in sorted(C.Counter(am).items())) + " }", ""]
    else:
        out += ['filled = false', 'why = "no model alignment of the Septuagint exists; null on every row"', ""]
    out += values_block("link_account.state", "state", "derived (D13, strict links only)",
                        C.Counter(r[3] for r in arows), lambda c: c)
    out += ["[link_account.reason]", 'column = "reason"', 'basis = "derived (D13)"',
            'pattern = "the class code for outside_alignment and never_a_word; the named Greek word for unplaced; empty otherwise"',
            f"count = {sum(1 for r in arows if r[4])}", ""]
    sm = C.Counter(r[5] for r in arows if r[5] is not None)
    out += ["[link_account.state_model]", 'column = "state_model"', 'basis = "model"']
    out += (attribution(NTB) if lang == "grc" else attribution(GLAUX))
    out += ['pattern = "linked where a model link of the piece and text exists and state is not linked; else null"',
            "values = ["] + [f"  {{ code = {tq(k)}, value = {tq(k)}, count = {v} }}," for k, v in sorted(sm.items())] + ["]", ""]
    for text, rows in sorted(other_rows.items()):
        if text == "lxx":
            cc = C.Counter(r[8] for r in rows if r[8])
            out += values_block("other.lxx.class", "class", "model (M7)", cc, lambda c: c.upper(),
                                extra=attribution(GLAUX) + ['source = "lxx-glaux.db lxx_words.pos"'])
            out += ["[other.lxx.lemma]", 'column = "lemma"', 'basis = "model (M7)"'] + attribution(GLAUX) + [
                'source = "lxx-glaux.db lxx_words.lemma"', f"count = {sum(1 for r in rows if r[7])}", ""]
        else:
            ab = C.Counter(r[10] for r in rows if r[10])
            out += values_block(f"other.{text}.analysis_basis", "analysis_basis", "derived (D14) / model (M6), row by row",
                                ab, lambda c: c, extra=attribution(ANA))
            pc = C.Counter(p["class"] for r in rows if r[9] for p in json.loads(r[9]))
            out += values_block(f"other.{text}.analysis_class", "analysis (class of each part)",
                                "derived (D14) / model (M6), with analysis_basis", pc,
                                lambda c: c or "-", extra=['source = "hebrew-nt-analysis v0.2 words.parquet class"'])
    rk = C.Counter(r["kind"] for r in facts_new)
    out += ["[facts.rendered_by]", 'column = "kind"', 'basis = "linked; model where the object is a GLAUx lemma (M7)"',
            "values = ["] + [f"  {{ code = {tq(k)}, value = {tq(k)}, count = {v} }}," for k, v in sorted(rk.items())] + ["]"]
    if lang != "grc":
        out += attribution(GLAUX)
    out.append("")
    return "\n".join(out)


def update_sources(d, lang):
    path = os.path.join(d, "sources.json")
    with open(path, encoding="utf-8") as fh:
        sj = json.load(fh)
    model = sj.setdefault("model", {})
    if lang == "grc":
        nf = checked_release(os.path.join(DOCS, NTB["folder"]))
        model[NTB["key"]] = {"repo": NTB["repo"], "version": NTB["version"], "revision": NTB["revision"],
                             "path": NTB["folder"], "files": {f: h for f, h in nf.items() if f.startswith("links/") or f == "README.md"},
                             "models": NTB["models"], "run": NTB["run"], "human_check": NO_HUMAN, "licence": NTB["licence"],
                             "columns": ["links rows with basis model (D13m)", "links.agree_model", "link_account.state_model"],
                             "basis": "model (M5)",
                             "why_not_the_working_copy": "shoresh/macula/data/hebrew-nt-bridge/heb_mod (reviewed) names no "
                                                         "revision that can be found; release v0.1's heb_mod is compact only"}
        pf = os.path.join(ROOT, PARTS["folder"])
        model[PARTS["key"]] = {"path": PARTS["folder"], "version": PARTS["version"],
                               "files": {f"{ed}/{f}": sha(os.path.join(pf, ed, f)) for ed in EL.EDITIONS
                                         for f in ("build.json", "part_links.parquet")},
                               "models": PARTS["models"], "run": PARTS["run"], "human_check": NO_HUMAN,
                               "licence": PARTS["licence"], "columns": ["links.agree_model (runs >= 3 of 5)"],
                               "basis": "model (M5)"}
        af = checked_release(os.path.join(DOCS, ANA["folder"]))
        model[ANA["key"]] = {"repo": ANA["repo"], "version": ANA["version"], "revision": ANA["revision"],
                             "path": ANA["folder"], "files": af, "models": ANA["models"], "run": ANA["run"],
                             "human_check": NO_HUMAN, "licence": ANA["licence"],
                             "columns": ["other/heb_scg, other/heb_mod: analysis, analysis_basis (D14 derived / M6 model)"],
                             "basis": "model (M6), derived (D14) row by row"}
    else:
        model[GLAUX["key"]] = {"dataset": GLAUX["dataset"], "version": GLAUX["version"], "sha256": GLAUX["sha256"],
                               "models": GLAUX["models"], "run": GLAUX["run"], "human_check": NO_HUMAN,
                               "licence": GLAUX["licence"], "method": "automatic (GLAUx's makers)",
                               "columns": ["other/lxx: lemma, class", "links rows with basis model (rules reading the "
                                           "GLAUx lemma or its number)", "facts rendered_by with kind model"],
                               "basis": "model (M7)"}
    sj["links"] = {"stage": "19", "other_texts": "<build>/other/<text>/words.parquet",
                   "lxx": {"bridge lxx.parquet": EL.BRIDGE_SHA, "lxx-glaux.db": EL.GLAUX_SHA,
                           "greek_numbers.tsv": sha(EL.NUMBERS)} if lang != "grc" else None,
                   "nt": {"compact": "data/compact-alignments-11583082 (companion files from lexeme-aligner's publish "
                                     "folder, checked byte-identical)", "texts": "data/helloao heb_scg, heb_mod (public domain)"}
                   if lang == "grc" else None}
    sj["links"] = {k: v for k, v in sj["links"].items() if v is not None}
    with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(sj, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(path + ".tmp", path)


def categories(d, text):
    path = os.path.join(d, "categories.toml")
    with open(path, encoding="utf-8") as fh:
        old = fh.read()
    before = old.split(MARKER)[0].rstrip("\n") + "\n\n"
    X.write_text(path, before + text)


def build(outdir, langs, counts):
    ex = {}
    cnt = C.Counter()
    langs = set(langs)
    if {"hbo", "arc"} & langs:
        if not {"hbo", "arc"} <= langs:
            raise SystemExit("stage 19 builds hbo and arc together (one Tanakh against one Septuagint)")
        if X.V12:
            import examples_links12
            out, objects, words = examples_links12.build_lxx12(outdir, counts, ex, cnt)
        else:
            out, objects, words = build_lxx(outdir, counts, ex, cnt)
        lxx_rows = [words[s] for s in sorted(words)]
        for lang in ("hbo", "arc"):
            d = os.path.join(outdir, lang)
            lrows, arows = out[lang]
            lrows.sort(key=lambda r: (r[2], r[0], r[1], r[3]))
            arows.sort(key=lambda r: (r[2], r[0], r[1]))
            write_rows(os.path.join(d, "links.parquet"), lrows, LINK_SCHEMA)
            write_rows(os.path.join(d, "link_account.parquet"), arows, ACCOUNT_SCHEMA)
            P = pq.read_table(os.path.join(d, "pieces.parquet"), columns=["t", "n", "lexeme"]).to_pylist()
            new = write_facts(d, lang, lrows, {"lxx": objects}, {(p["t"], p["n"]): p["lexeme"] for p in P}, cnt)
            categories(d, links_part(lang, lrows, arows, {"lxx": lxx_rows}, new))
            update_sources(d, lang)
            note(counts, lang, lrows, arows)
    if "grc" in langs:
        lrows, arows, objects, heb_words = build_nt(outdir, counts, ex, cnt)
        d = os.path.join(outdir, "grc")
        lrows.sort(key=lambda r: (r[2], r[0], r[1], r[3]))
        arows.sort(key=lambda r: (r[2], r[0], r[1]))
        write_rows(os.path.join(d, "links.parquet"), lrows, LINK_SCHEMA)
        write_rows(os.path.join(d, "link_account.parquet"), arows, ACCOUNT_SCHEMA)
        P = pq.read_table(os.path.join(d, "pieces.parquet"), columns=["t", "n", "lexeme"]).to_pylist()
        new = write_facts(d, "grc", lrows, {ed: objects(ed) for ed in EL.EDITIONS},
                          {(p["t"], p["n"]): p["lexeme"] for p in P}, cnt)
        categories(d, links_part("grc", lrows, arows, heb_words, new))
        update_sources(d, "grc")
        note(counts, "grc", lrows, arows)
    counts["stage 19"] = dict(sorted(cnt.items()))
    return ex


def note(counts, lang, lrows, arows):
    counts[f"{lang} links rows"] = len(lrows)
    counts[f"{lang} links by other, how and basis"] = {f"{o} {h} {b}": v for (o, h, b), v in
                                                      sorted(C.Counter((r[2], r[4], r[6]) for r in lrows).items())}
    counts[f"{lang} account by other and state"] = {f"{o} {s}": v for (o, s), v in
                                                   sorted(C.Counter((r[2], r[3]) for r in arows).items())}
    counts[f"{lang} account state_model linked"] = sum(1 for r in arows if r[5])
