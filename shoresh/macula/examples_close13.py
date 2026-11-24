"""Stage 29 of the source examples (SPEC 1.3, section 14: close13). It closes an e build that stage 28 has built.

    shoresh/.venv/bin/python -I shoresh/macula/build_examples.py --build e1 --stage 29

Writes, per language folder (`hbo`, `arc`, `grc`):
  sources.json     anew, by the rule of stage 24 (examples_shared11.sources_doc11), now for SPEC 1.3: every source with
                   repository, pin, licence, its basis (SPEC 5) and the sha256 of every file read; the five sources new
                   in 1.3 (reference-status, implicit-args, inclusive-we, noun-relations, passage-facts) as sources of
                   their own; the terms master with both notes files; the model part (with M7's D9m values) and the
                   `v13` part of stage 27 kept; the builder files and commit; SPEC 1.3 with its sha256
  COLUMNS.md       SPEC section 4 (version 1.3) as it stands, then every table file with its columns read from the file
  READ-FIRST.md    the reading sheet (examples_read_sheet.py), with the account of who is meant (who_account.parquet,
                   D19) in place of the share of pieces with a participant, the 1.3 columns in section 1, and section 5:
                   what is model and how much (the D9m values of marks_model; the Septuagint agree_model counted as
                   the strict rows where a model alignment agrees, OPEN-1.2 C2)
And the eight glossed chapters: for e1 into internal-docs/source-examples-work/glossed-e1/, for any other build into
<build>/cache/glossed/ (so a rebuild can be compared file by file). They show, beside the 1.2 columns, the reference
status and realisation of each part, the who account of each referring head, clusivity and the noun relation of a
piece, mood and absolute time in the clause marks, the D9m values (model), the units of passages.parquet, and under
each verse the arguments the text does not say (added.parquet), set apart and marked `+`.

It reads only the build's own tables and the files sources.json hashes; it changes no table. VALIDATION.md is the
validator's (validate_examples.py --build e1 --upto 29 --compare e2 --write-md).
"""
import collections as C
import json
import os
import sys

import pyarrow.parquet as pq

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import examples_common as X  # noqa: E402
import examples_read_sheet  # noqa: E402
import examples_reading as RD  # noqa: E402
import examples_shared11 as S20  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LANGS = ("hbo", "arc", "grc")
NEED = ("words.parquet", "pieces.parquet", "clauses.parquet", "constituents.parquet", "links.parquet", "terms.tsv",
        "terms-notes.md", "categories.toml", "sources.json", "source_errors.tsv", "profile.tsv", "added.parquet",
        "who_account.parquet", "passages.parquet")
M = "shoresh/macula/"

# SPEC 1.3 section 5: the basis of each source, by its key in sources.json
BASIS = {
    "macula-hebrew": "given", "macula-hebrew-nodes": "given", "macula-greek": "given", "macula-greek-nodes": "given",
    "trees-macula": "given", "word-senses-ubs": "given",
    "clause-layout": "derived", "nt-clause-layout": "derived (strict fields); model (review fields, M4)",
    "clause-columns": "derived", "connectives": "derived", "clause-extras": "derived; model where D9m moves a mood",
    "time-aspect": "derived; model where a row read the Septuagint verb's parse (D9m, M7)",
    "speaker-layer-inputs": "linked (D10); model for the review rows (M4)", "nt-speech-inputs": "linked (D10); model for the review rows (M4)",
    "speaker-layer-published": "linked (counted only)", "acai": "given, derived (D7, D7n)", "addressees": "linked (D10); model (M4)",
    "arg-roles": "derived, linked (D12)", "hebrew-greek-cf": "linked; model for the number links (M7)",
    "glaux-lxx": "given (text); model (lemma, class: M7)", "compact-alignments": "linked", "helloao": "given",
    "aramaic-hebrew-equivalents": "linked", "grambank-questionnaire": "given (ids only)", "terms": "chosen (a model named the terms; unchecked)",
    "reference-status": "derived", "implicit-args": "derived", "inclusive-we": "linked (votes), derived (rules)",
    "noun-relations": "derived", "passage-facts": "given (marks, layouts); derived (units, D22)",
}
NEW13 = [   # SPEC 1.3 section 5, the sources new in 1.3
    dict(key="reference-status", name="reference-status (np.tsv)", repository="bcv-commons/bcv-query (shoresh/macula/data/reference-status)",
         pin="local build 4ee0442; release v0.2 7612f663", licence="CC BY-SA 4.0", licence_from="SPEC 5; the release card",
         reads="stage 16 (D17 ref_status, ref_form), stage 28 (D7r (a) referents, D19 states and reasons). Rule-made from ACAI, "
               "MACULA's references and UBS domains; its build names no model", paths=[M + "data/reference-status/np.tsv"]),
    dict(key="implicit-args", name="implicit-args (args.tsv)", repository="bcv-commons/bcv-query (shoresh/macula/data/implicit-args)",
         pin="local build cd2c348; not released", licence="CC BY-SA 4.0 (built from MACULA, our layouts, reference-status)",
         licence_from="SPEC 5", reads="stage 16 (D18 added.parquet), stage 28 (D7r (b) verb referents, D19 verb_zero states); "
                                      "its build names no model", paths=[M + "data/implicit-args/args.tsv"]),
    dict(key="inclusive-we", name="inclusive-we (we-layer words.tsv, with the we-votes verses behind it)",
         repository="bcv-commons/bcv-query (shoresh/macula/data/we-layer, data/we-votes)",
         pin="local build fc06571; release v0.1 d2d67cf4", licence="CC BY-SA 4.0", licence_from="SPEC 5; the release card",
         reads="stage 16 (D21 clusivity, clusivity_basis). The votes count the inclusive and exclusive forms of a closed list in "
               "nine openly licensed editions (Tagalog, Cebuano, Hiligaynon, Malayalam, Tamil, Telugu, Hawaiian, Tongan, "
               "Vietnamese; Marathi counted, not voting), per verse, without alignment and without their text; no model named",
         paths=[M + "data/we-layer/words.tsv", M + "data/we-votes/verses.tsv"]),
    dict(key="noun-relations", name="noun-relations (pairs.tsv)", repository="bcv-commons/bcv-query (shoresh/macula/data/noun-relations)",
         pin="local build 75dc6e1; release v0.1", licence="CC BY-SA 4.0", licence_from="SPEC 5; the release card",
         reads="stage 16 (D20 noun_rel, noun_head_t, noun_head_n). Rule-made from UBS domains, ACAI types and fixed lists; "
               "no model named", paths=[M + "data/noun-relations/pairs.tsv"]),
    dict(key="passage-facts", name="passage-facts v0.1 (the input copy of the bridge corpus, with its PIN.json)",
         repository="bcv-commons/passage-facts (Hugging Face), copy in shoresh/macula/data/bridge-corpus/inputs/passage-facts@v0.1",
         pin="v0.1, Hugging Face commit bbb9b2e3; built by build_passage_facts.py at 97c1728",
         licence="CC BY-SA 4.0 (MAM); OSHB CC BY 4.0; Nestle 1904 public domain", licence_from="SPEC 5",
         reads="stage 27 sub-stage 13 (D22 passages.parquet): the section facts (OSHB, MAM) and the form facts of MAM and "
               "Nestle 1904 only; the fm.tr.poetry facts (English translations' lines) are not taken",
         paths=[M + "data/bridge-corpus/inputs/passage-facts@v0.1/**"]),
]
READS13 = {
    "clause-extras": "stage 16 (D9: polarity; mood, SPEC 1.3 section 8; the D9m moods to marks_model)",
    "time-aspect": "stage 16 (D9: time, aspect, band, carried as terms of terms.tsv; D9m: the rows whose basis holds lxx go "
                   "to marks_model, M7), stage 28 (D16 time_abs reads these times)",
    "acai": "stage 16 (D7 who, D7n names, participants.tsv, D10 speaker through characters.tsv, kin facts, SE1, SE2), stage 28 "
            "(D7r entity types and keyterms, the 34 catch-all entities of SPEC 4.5, D19)",
    "terms": "stage 27/28 sub-stage 14: terms.tsv copied unchanged into each language folder (82 rows of 1.2, 30 of 1.3; a model "
             "named the terms, named_by; unchecked); terms-notes.md written as the 1.2 notes with the three 1.3 reference "
             "codes added to the list at the head and the sections of terms-notes-1.3-rows.md appended unchanged. "
             "terms-notes.md may hold English and is no table (SPEC 4.10)",
}
EXAMPLE_LICENCE13 = S20.EXAMPLE_LICENCE11 + (
    " SPEC 1.3 adds CC BY-SA 4.0 sources (reference-status, implicit-args, inclusive-we, noun-relations, passage-facts "
    "for MAM) and the OSHB section marks (CC BY 4.0) and Nestle 1904's layout (public domain); ShareAlike still holds.")


def sources_doc13(lang, d, counts):
    with open(os.path.join(d, "sources.json"), encoding="utf-8") as fh:
        old = json.load(fh)
    doc = S20.sources_doc11(lang, d, counts)
    for s in NEW13:
        files = {}
        for pat in s["paths"]:
            got = RD._expand(pat)
            if not got:
                raise SystemExit(f"sources.json: {s['key']}: nothing matches {pat}")
            for label, p in got:
                files[label] = {"bytes": os.path.getsize(p), "sha256": RD._sha(p)}
        entry = {k: s[k] for k in ("name", "repository", "pin", "licence", "licence_from", "reads")}
        entry["files"] = dict(sorted(files.items()))
        doc["sources"][s["key"]] = entry
        counts[f"{lang} sources.json {s['key']} files"] = len(files)
    for k, v in READS13.items():
        if k in doc["sources"]:
            doc["sources"][k]["reads"] = v
    if "terms" in doc["sources"]:
        doc["sources"]["terms"]["name"] = "the terms of the language for meaning values, and their notes (masters)"
    missing = sorted(k for k in doc["sources"] if k not in BASIS)
    if missing:
        raise SystemExit(f"sources.json: no basis named for {missing}")
    for k, s in doc["sources"].items():
        s["basis"] = BASIS[k]
    if "v13" not in old:
        raise SystemExit("sources.json: the v13 part of stage 27 is missing; run --stage 28 first")
    doc["v13"] = old["v13"]
    doc["licence"] = EXAMPLE_LICENCE13
    return doc


# ---- READ-FIRST.md -------------------------------------------------------------------------------------------------

STATES = ("participant", "generic", "not_referring", "entity_not_taken", "no_entity", "unresolved", "no_row")
HEAD_KINDS = ("noun", "pronoun", "suffix", "verb_zero")
NAMES = {"hbo": "Hebrew of the Tanakh", "arc": "Aramaic of the Tanakh", "grc": "Greek of the New Testament"}


def _pc(x, y):
    return f"{x / y:.3f}" if y else "-"


def _split(counter, total, n=8):
    return ", ".join(f"`{k if k != '' else '(empty)'}` {v:,} ({_pc(v, total)})"
                     for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))[:n])


def account_part(d):
    A = pq.read_table(os.path.join(d, "who_account.parquet"), columns=["head_kind", "state", "reason"]).to_pydict()
    tab = C.Counter(zip(A["head_kind"], A["state"]))
    kinds = [k for k in HEAD_KINDS if any(tab[(k, s)] for s in STATES)]
    L = ["### The account of who is meant (`who_account.parquet`, D19)", "",
         "In place of a share of pieces with a participant: every referring head (a noun or pronoun stem, a pronoun",
         "suffix, the predicate verb of a clause whose subject is zero) has exactly one state, the first that holds.",
         "`no_entity`: the reference row names a lemma, not an entity (for a noun most often its own lemma, for a",
         "pronoun, suffix or verb most often the antecedent's; stage 28 counted both); `no_row`: no reference row has",
         "the head. Counts of rows:", "",
         "| head kind | " + " | ".join(STATES) + " | all |", "|---|" + "---|" * (len(STATES) + 1)]
    for k in kinds:
        L.append(f"| `{k}` | " + " | ".join(f"{tab[(k, s)]:,}" for s in STATES) + f" | {sum(tab[(k, s)] for s in STATES):,} |")
    L.append("| all | " + " | ".join(f"{sum(tab[(k, s)] for k in kinds):,}" for s in STATES) + f" | {len(A['state']):,} |")
    reasons = C.Counter((s, r) for s, r in zip(A["state"], A["reason"]) if r and s in ("entity_not_taken", "no_entity"))
    L += ["", "Reasons: " + "; ".join(f"`{s}` {r} {n:,}" for (s, r), n in sorted(reasons.items(), key=lambda kv: (kv[0][0], -kv[1], kv[0][1]))), ""]
    return "\n".join(L), {f"{k} {s}": tab[(k, s)] for k in kinds for s in STATES}


def lines13(outdir, lang):
    d = os.path.join(outdir, lang)
    P = pq.read_table(os.path.join(d, "pieces.parquet"), columns=["who", "who_basis", "clusivity", "clusivity_basis",
                                                                   "noun_rel", "noun_head_t"]).to_pydict()
    K = pq.read_table(os.path.join(d, "clauses.parquet"), columns=["marks", "marks_model"]).to_pydict()
    N = pq.read_table(os.path.join(d, "constituents.parquet"), columns=["ref_status", "ref_form"]).to_pydict()
    A = pq.read_table(os.path.join(d, "added.parquet"), columns=["kind", "form", "who"]).to_pydict()
    S = pq.read_table(os.path.join(d, "passages.parquet"), columns=["source", "kind", "crossing"]).to_pydict()
    nk, nn, na = len(K["marks"]), len(N["ref_status"]), len(A["kind"])
    marks = [json.loads(m) for m in K["marks"]]
    nwho = sum(1 for v in P["who"] if v)
    pairs = sum(1 for v in P["noun_head_t"] if v is not None)
    we = sum(1 for v in P["clusivity"] if v)
    L = [f"- pieces with a participant: {nwho:,}; by basis: "
         + ", ".join(f"`{k}` {v:,}" for k, v in sorted(C.Counter(b for w, b in zip(P['who'], P['who_basis']) if w).items(),
                                                     key=lambda kv: (-kv[1], kv[0])))
         + " (a share is not given: the account of who is meant follows this list)",
         f"- pieces with inclusive or exclusive \"we\" (`clusivity`): {we:,}; by term: {_split(C.Counter(v for v in P['clusivity'] if v), we)}; "
         f"by basis: {_split(C.Counter(v for v in P['clusivity_basis'] if v), we)}",
         f"- noun-to-noun pairs (`noun_head_t` filled): {pairs:,}; with a kind (`noun_rel`): "
         f"{sum(1 for v in P['noun_rel'] if v):,} ({_pc(sum(1 for v in P['noun_rel'] if v), pairs)}); commonest: "
         f"{_split(C.Counter(v for v in P['noun_rel'] if v), pairs, 6)}",
         f"- clauses with a `mood` in `marks`: {sum(1 for m in marks if 'mood' in m):,} ({_pc(sum(1 for m in marks if 'mood' in m), nk)}); "
         f"by term: {_split(C.Counter(m['mood'] for m in marks if 'mood' in m), nk, 5)}",
         f"- clauses with a `time` in `marks`: {sum(1 for m in marks if 'time' in m):,}; with a `time_abs`: "
         f"{sum(1 for m in marks if 'time_abs' in m):,} ({_pc(sum(1 for m in marks if 'time_abs' in m), sum(1 for m in marks if 'time' in m))} "
         f"of those with a time)",
         f"- clauses with `marks_model` (M7, D9m): {sum(1 for v in K['marks_model'] if v is not None):,}",
         f"- constituents with a reference status: {sum(1 for v in N['ref_status'] if v):,} ({_pc(sum(1 for v in N['ref_status'] if v), nn)}); "
         f"by term: {_split(C.Counter(v for v in N['ref_status'] if v), nn, 6)}; realisation (`ref_form`): "
         f"{_split(C.Counter(v for v in N['ref_form'] if v), sum(1 for v in N['ref_form'] if v), 6)}",
         f"- arguments the text does not say (`added.parquet`): {na:,} ({na / nk:.2f} per clause); by kind: "
         f"{_split(C.Counter(A['kind']), na, 4)}; with a participant: {sum(1 for v in A['who'] if v):,}",
         f"- units above the clause (`passages.parquet`): {len(S['kind']):,}; by source and kind: "
         + ", ".join(f"`{a}` `{b}` {n:,}" for (a, b), n in sorted(C.Counter(zip(S['source'], S['kind'])).items()))
         + f"; clauses crossing a unit's end: {sum(S['crossing']):,}"]
    return L


def model_section13(outdir, lang):
    d = os.path.join(outdir, lang)
    text = S20.model_section(outdir, lang)
    K = pq.read_table(os.path.join(d, "clauses.parquet"), columns=["marks_model"]).column("marks_model").to_pylist()
    LK = pq.read_table(os.path.join(d, "links.parquet"), columns=["other", "basis", "agree_model"]).to_pydict()
    keys = C.Counter(k for v in K if v is not None for k in json.loads(v))
    rows = [("clauses with marks_model (M7, D9m)", sum(1 for v in K if v is not None), len(K), "clauses")]
    for k in ("time", "aspect", "mood", "time_abs"):
        rows.append((f"marks_model.{k} (M7, D9m)", keys[k], len(K), "clauses"))
    for o in sorted(set(LK["other"])):
        strict = [a for t, b, a in zip(LK["other"], LK["basis"], LK["agree_model"]) if t == o and b != "model"]
        rows.append((f"strict links to {o} where a model alignment agrees (agree_model >= 1; OPEN-1.2 C2)",
                     sum(1 for a in strict if a is not None and a >= 1), len(strict), "strict links"))
    add = "\n".join(f"| {a} | {b:,} | {c:,} | {_pc(b, c)} | {u} |" for a, b, c, u in rows)
    ns = sum(1 for b in LK["basis"] if b != "model")
    nsf = sum(1 for b, a in zip(LK["basis"], LK["agree_model"]) if b != "model" and a is not None)
    nm = sum(1 for b in LK["basis"] if b == "model")
    nmf = sum(1 for b, a in zip(LK["basis"], LK["agree_model"]) if b == "model" and a is not None)
    note = ["", f"`agree_model` is filled on {nsf:,} of {ns:,} strict links and {nmf:,} of {nm:,} model links (0 where no model",
            "alignment agrees), so its filled count above is not a count of agreements; the C2 rows count the strict links",
            "where a model alignment agrees. The D9m values",
            "(`marks_model`) are the Hebrew and Aramaic clause times and aspects that the time-aspect dataset chose by",
            "the Septuagint verb's automatic parse (GLAUx, M7), the moods `irrealis` and `declarative` that rest on that",
            "time, and every `time_abs` that reads such a time (the clause's own or an ancestor's, D16). Their keys are",
            "absent from `marks` on those clauses. Greek has none."]
    return text.rstrip("\n") + "\n" + add + "\n" + "\n".join(note) + "\n", rows


def sheet13(outdir, lang, counts):
    d = os.path.join(outdir, lang)
    sheet = examples_read_sheet.sheet(d, lang).replace("SPEC 1.0", "SPEC 1.3")
    old_head = ("Written by `build_examples.py --stage 10` (`examples_read_sheet.py`) from this folder's tables.",
                "(`internal-docs/source-examples-work/glossed/`).")
    new_head = ("Written by `build_examples.py --stage 29` (`examples_read_sheet.py`, `examples_close13.py`) from "
                "this folder's tables.",
                "(`internal-docs/source-examples-work/glossed-e1/`, the chapters of build `e1`; a rebuild writes "
                "the same chapters into its `cache/glossed/`).")
    if getattr(X, "V15", False):     # SPEC 1.5: the build g1 and its chapters (SPEC 1.6: h1)
        b_, s_ = ("k1", "55") if getattr(X, "V19", False) else ("j1", "52") if getattr(X, "V18", False) else ("h1", "38") if getattr(X, "V16", False) else ("g1", "35")
        new_head = (f"Written by `build_examples.py --build {b_} --stage {s_}` (`examples_read_sheet.py`, `examples_close13.py`) "
                    "from this folder's tables.",
                    f"(`internal-docs/source-examples-work/glossed-{b_}/`, the chapters of build `{b_}`; a rebuild writes "
                    "the same chapters into its `cache/glossed/`).")
    for o, n in zip(old_head, new_head):
        if sheet.count(o) != 1:
            raise SystemExit(f"stage 29: the reading sheet's head has changed; cannot find {o!r}")
        sheet = sheet.replace(o, n)
    lines = sheet.split("\n")
    i = [j for j, ln in enumerate(lines) if ln.startswith("- pieces with a participant:")]
    if len(i) != 1:
        raise SystemExit("stage 29: the reading sheet's participant line is not found once")
    lines[i[0]:i[0] + 1] = lines13(outdir, lang)
    sheet = "\n".join(lines)
    acc, tab = account_part(d)
    mark = "## 2. The 60 commonest written forms"
    if sheet.count(mark) != 1:
        raise SystemExit("stage 29: the reading sheet's section 2 is not found once")
    sheet = sheet.replace(mark, acc + "\n" + mark)
    m5, rows = model_section13(outdir, lang)
    for k, v in tab.items():
        counts[f"{lang} READ-FIRST account {k}"] = v
    for a, b, c, u in rows:
        counts[f"{lang} READ-FIRST {a}"] = b
    return sheet.rstrip("\n") + "\n\n" + m5


# ---- the glossed chapters (1.3) -----------------------------------------------------------------------------------

GLOSS_HEADER13 = ("| t.n | word | piece | kind | lexeme | class | marks | head | label | shared | clause | part | "
                  "participant | account | piece values | concept | model |")
CLAUSE_HEADER13 = "| clause | key | rule | parent | marks | speech | model |"
ADDED_HEADER13 = "| + | clause | verb | role | kind | where | form | person | number | gender | antecedent | who |"
ADDED_CAPTION = ("**Added: arguments the text does not say** (`added.parquet`, D18). Not words of the text: each row "
                 "is marked `+`.")
_cell = S20._cell


def gloss_chapter13(build, lang, book, ch, kind):
    d = os.path.join(build, lang)
    W = [w for w in pq.read_table(os.path.join(d, "words.parquet"),
                                  columns=["t", "book", "chapter", "verse", "text", "clause", "rel_shared"]).to_pylist()
         if w["book"] == book and w["chapter"] == ch]
    ts = {w["t"] for w in W}
    wtext = {w["t"]: w["text"] for w in W}
    P = C.defaultdict(list)
    for p in pq.read_table(os.path.join(d, "pieces.parquet"),
                           columns=["t", "n", "text", "kind", "lexeme", "class", "marks", "head_t", "head_n", "head_basis",
                                    "rel", "who", "who_basis", "concept", "clusivity", "clusivity_basis", "noun_rel",
                                    "noun_head_t", "noun_head_n"]).to_pylist():
        if p["t"] in ts:
            P[p["t"]].append(p)
    need = {(p["head_t"], p["head_n"]) for ps in P.values() for p in ps}
    need |= {(p["noun_head_t"], p["noun_head_n"]) for ps in P.values() for p in ps if p["noun_head_t"] is not None}
    AD = [r for r in pq.read_table(os.path.join(d, "added.parquet")).to_pylist() if r["verb"] in ts]
    for r in AD:
        if r["antecedent"]:
            a, b = r["antecedent"].split(".")
            need.add((int(a), int(b)))
    text_of = {}
    for other in (["hbo", "arc"] if lang in ("hbo", "arc") else [lang]):
        for p in pq.read_table(os.path.join(build, other, "pieces.parquet"), columns=["t", "n", "text"]).to_pylist():
            if (p["t"], p["n"]) in need:
                text_of[(p["t"], p["n"])] = p["text"]
    KC = {c["clause"]: c for c in pq.read_table(os.path.join(d, "clauses.parquet"),
                                               columns=["clause", "rule", "parent", "book", "chapter", "marks", "quote",
                                                        "speaker", "addressee", "speech_basis", "quote_model",
                                                        "speaker_model", "addressee_model", "subject_model",
                                                        "marks_model"]).to_pylist()
          if c["book"] == book and c["chapter"] == ch}
    part = {}
    for r in pq.read_table(os.path.join(d, "constituents.parquet"),
                           columns=["clause", "role", "head", "sem_role", "sem_role_basis", "ref_status", "ref_form"]).to_pylist():
        if r["clause"] in KC and r["head"] in ts:
            s = [r["role"]]
            if r["sem_role"]:
                s.append(f"sem={r['sem_role']}" + (" (linked)" if r["sem_role_basis"] == "linked" else ""))
            if r["ref_status"]:
                s.append(f"ref={r['ref_status']}")
            if r["ref_form"]:
                s.append(f"form={r['ref_form']}")
            part.setdefault(r["head"], []).append(" · ".join(s))
    acc = {(r["t"], r["n"]): r for r in pq.read_table(os.path.join(d, "who_account.parquet")).to_pylist() if r["t"] in ts}
    name = {r["ent"]: r["name"] for r in S20._tsv(os.path.join(d, "participants.tsv"))}
    PS = pq.read_table(os.path.join(d, "passages.parquet"), columns=["passage", "source", "kind", "first", "last"]).to_pylist()
    starts, ends = C.defaultdict(list), C.defaultdict(list)
    for u in PS:
        if u["first"] in ts:
            starts[u["first"]].append(u)
        if u["last"] in ts:
            ends[u["last"]].append(u)

    def ents(v):
        return " ".join(f"`{e}`" + (f" {name[e]}" if name.get(e) else "") for e in (v or "").split())
    out = [f"# {book} {ch} ({lang}, {kind}): the tables, piece by piece", "",
           f"Written by `build_examples.py --stage 29` (`examples_close13.py`) from the source examples (SPEC 1.3). One",
           "table per verse, one row per piece (`pieces.parquet`). `marks`: the piece's codes; `head`: the piece it depends",
           "on as `t.n` and its letters (`root` for the root), with `head_basis` where it is not `index`; `label`:",
           "`pieces.rel`; `shared`: the word's `rel_shared` (on its first piece); `clause`: the word's innermost clause,",
           "numbered in the verse; `part`: on the head word of a constituent, its role code, then `sem=` its semantic role",
           "as a term of the language (`(linked)` where placed through the Septuagint), `ref=` its reference status as a",
           "term and `form=` how the source realises the mention (`ref_form`), parts of one word separated by `; `;",
           "`participant`: `pieces.who` with the name `participants.tsv` gives and the basis; `account`: on a referring",
           "head, its state in `who_account.parquet` (with the reason in brackets); `piece values`: `clusivity` (with",
           "its basis) and `noun_rel` with the head noun of the pair (`noun→` where the pair has no kind); `concept`:",
           "the concept code a model chose (M1). `model` names every value of the row that is model-made. Under each",
           "verse its clauses: the meaning values of `marks` (relation, time, aspect, line_kind, mood, time_abs) are",
           "terms of the language; `speech` is the strict quotation, speaker and addressee; `model` the D9m values",
           "(`marks_model`, M7), the reviewed layers' values (M4) and the model's subject (M3). Then, set apart, the",
           "arguments the text does not say (`added.parquet`), each row marked `+`, and the units of `passages.parquet`",
           "that begin or end in the verse. No gloss: nothing English is read.", ""]
    nverse = npiece = nadded = 0
    for v in sorted({w["verse"] for w in W}):
        ws = sorted((w for w in W if w["verse"] == v), key=lambda w: w["t"])
        vt = {w["t"] for w in ws}
        nverse += 1
        order = []
        for w in ws:
            if w["clause"] and w["clause"] not in order:
                order.append(w["clause"])
        num = {c: i + 1 for i, c in enumerate(order)}
        out += [f"## {book} {ch}:{v}", "", GLOSS_HEADER13, "|" + "---|" * 17]
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
                a = acc.get((p["t"], p["n"]))
                account = "" if a is None else (a["state"] + (f" ({a['reason']})" if a["reason"] else ""))
                pv = []
                if p["clusivity"]:
                    pv.append(f"clusivity={p['clusivity']} ({p['clusivity_basis']})")
                if p["noun_head_t"] is not None:
                    hk = (p["noun_head_t"], p["noun_head_n"])
                    pv.append((f"noun_rel={p['noun_rel']} → " if p["noun_rel"] else "noun→ ")
                              + f"{hk[0]}.{hk[1]} {text_of.get(hk, '?')}")
                model = []
                if p["who_basis"] == "model":
                    model.append("participant")
                if p["concept"] is not None:
                    model.append("concept")
                out.append("| " + " | ".join(_cell(x) for x in [
                    f"{p['t']}.{p['n']}", w["text"] if i == 0 else "", p["text"], p["kind"], p["lexeme"], p["class"],
                    marks, head, p["rel"], w["rel_shared"] if i == 0 else "", cl, pt,
                    ents(p["who"]) + (f" ({p['who_basis']})" if p["who"] else ""), account, "; ".join(pv),
                    "" if p["concept"] is None else p["concept"], " ".join(model)]) + " |")
        out += ["", CLAUSE_HEADER13, "|---|---|---|---|---|---|---|"]
        for c in order:
            k = KC.get(c, {})
            mk = json.loads(k["marks"]) if k.get("marks") else {}
            marks = "; ".join(f"{a}={X.jdump(b) if isinstance(b, list) else b}" for a, b in sorted(mk.items()))
            speech = ""
            if k.get("quote"):
                speech = f"`{k['quote']}` " + ents(k["speaker"]) + (f" → {ents(k['addressee'])}" if k["addressee"] else "") \
                         + f" ({k['speech_basis']})"
            mod = []
            if k.get("marks_model") is not None:
                mm = json.loads(k["marks_model"])
                mod.append("marks_model " + ", ".join(f"{a}={b}" for a, b in sorted(mm.items())) + " (model)")
            if k.get("quote_model") is not None:
                mod.append(f"quote `{k['quote_model'] or '-'}` {ents(k['speaker_model']) or '-'} → "
                           f"{ents(k['addressee_model']) or '-'} (model)")
            if k.get("subject_model") is not None:
                mod.append(f"subject {k['subject_model']} (model)")
            out.append("| " + " | ".join(_cell(x) for x in [num[c], f"`{c}`", k.get("rule", "?"),
                                                          f"`{k['parent']}`" if k.get("parent") else "", marks, speech,
                                                          "; ".join(mod)]) + " |")
        ad = sorted((r for r in AD if r["verb"] in vt), key=lambda r: (r["verb"], r["clause"], r["role"]))
        v16 = getattr(X, "V16", False)     # SPEC 1.6 section 10 (R10): every added row shows who_reason and form
        if ad:
            out += ["", ADDED_CAPTION, "", ADDED_HEADER13 + (" who_reason |" if v16 else ""), "|" + "---|" * (13 if v16 else 12)]
            for r in ad:
                nadded += 1
                ant = ""
                if r["antecedent"]:
                    a, b = r["antecedent"].split(".")
                    ant = f"{r['antecedent']} {text_of.get((int(a), int(b)), '?')}"
                out.append("| " + " | ".join(_cell(x) for x in [
                    "+", (f"{num[r['clause']]} " if r["clause"] in num else "") + f"`{r['clause']}`",
                    f"{r['verb']} {wtext.get(r['verb'], '?')}", r["role"], r["kind"], r["where"], r["form"],
                    r["person"], r["number"], r["gender"], ant, ents(r["who"])] + ([r["who_reason"]] if v16 else [])) + " |")
        pl = []
        for w in ws:
            for u in sorted(starts.get(w["t"], []), key=lambda u: u["passage"]):
                pl.append(f"begins at {w['t']}: `{u['passage']}` ({u['source']} {u['kind']})")
            for u in sorted(ends.get(w["t"], []), key=lambda u: u["passage"]):
                pl.append(f"ends at {w['t']}: `{u['passage']}` ({u['source']} {u['kind']})")
        if pl:
            out += ["", "Passages (`passages.parquet`): " + "; ".join(pl) + "."]
        out.append("")
    return "\n".join(out), nverse, npiece, nadded


def glossed_all13(build, gdir, counts):
    for lang, book, ch, kind, fname in S20.CHAPTERS:
        text, nv, npc, nad = gloss_chapter13(build, lang, book, ch, kind)
        X.write_text(os.path.join(gdir, fname + ".md"), text)
        counts[f"glossed {lang} {book} {ch}"] = f"{nv} verses, {npc} pieces, {nad} added"


# ---- the stage -----------------------------------------------------------------------------------------------------

def build(outdir, langs, counts):
    if set(langs) != set(LANGS):
        raise SystemExit("stage 29 closes hbo, arc and grc together")
    if not X.V13:
        raise SystemExit("stage 29 closes an e build (SPEC 1.3)")
    missing = [f"{lg}/{f}" for lg in LANGS for f in NEED if not os.path.exists(os.path.join(outdir, lg, f))]
    if missing:
        raise SystemExit(f"stage 29: stage 28 has not built {missing[:5]} ({len(missing)} files); run --stage 28 first")
    ex = {}
    for lang in LANGS:
        d = os.path.join(outdir, lang)
        doc = sources_doc13(lang, d, counts)
        X.write_text(os.path.join(d, "sources.json"), json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        counts[f"{lang} sources"] = len(doc["sources"])
        counts[f"{lang} model sources"] = len(doc["model"])
        counts[f"{lang} files hashed"] = sum(len(s["files"]) for s in doc["sources"].values())
        unc = [k for k, v in doc["builder"]["files"].items() if not v["committed"]]
        if unc:
            ex[f"{lang} builder files not committed when built"] = unc
    for lang in LANGS:
        d = os.path.join(outdir, lang)
        X.write_text(os.path.join(d, "COLUMNS.md"), S20.columns_md11(d, lang))
        X.write_text(os.path.join(d, "READ-FIRST.md"), sheet13(outdir, lang, counts))
        for f in ("COLUMNS.md", "READ-FIRST.md"):
            counts[f"{lang} {f} bytes"] = os.path.getsize(os.path.join(d, f))
    gl = S20.glossed_dir(outdir)
    glossed_all13(outdir, gl, counts)
    counts["glossed folder"] = os.path.relpath(gl, ROOT)
    return ex
