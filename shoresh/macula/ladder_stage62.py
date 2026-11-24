"""Stage 62 of the Hebrew ladder: the English aid (SPEC-ladder 10).

`--prepare` writes the input of the session per chapter into cache/english/input/<portion>/<BOOK>-<ch>.txt: per verse
the step-4 (real) `point` line, then each lower step's `point` line only where it differs from the step above (`changed`).
The session (the translator, model claude-opus-5-5) writes one answer file per chapter (`v<TAB>step<TAB>English`);
`--ingest FILE...` checks each against the input and merges it into english/raw/<portion>.tsv (key, step, text).
`--check [--spend USD]` checks the raw files whole and writes english/english_model.parquet, english/README.md, and
extends sources.json, categories.toml and build.json. Nothing English is written anywhere else.

Four steps since SPEC-ladder 0.2 (2026-11-24). The raw files keep the numbering the stage 62 session wrote in, the five
steps of SPEC-ladder 0.1 (`raw_step`). Rule RN (SPEC-ladder 10.2) maps them: step 1 <- raw 1, 2 <- raw 2, 3 <- raw 3,
else raw 4 (old step 4 had the same Hebrew where old step 3 pointed to it), 4 <- raw 5. A raw row of old step 4 that no
step takes is dropped (counted). `--ingest` writes new answers in the raw numbering (step 4 as raw 5).
"""
import collections, hashlib, json, re
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

PORTIONS = ["JON", "PSA1-41", "ISA40-55", "RUT", "GEN22-25"]
STEP1 = {"JON", "PSA1-41", "ISA40-55"}
MODEL = "claude-opus-5-5"
DATE = "2026-11-24"
CREDIT = ("English aid by the model claude-opus-5-5 (the stage 62 session of the Hebrew ladder pilot 1, 2026-11), "
          "translated from the Hebrew of each step only, with no English Bible; an aid beside the Hebrew, not a "
          "translation of record; no human check.")
CODE62 = ["shoresh/macula/build_ladder.py", "shoresh/macula/ladder_stage62.py"]
CAT_MARK = "\n# English aid (stage 62)\n"
LAST = 4                                     # the real text (SPEC-ladder 0.2)
RAW_OF = {1: (1,), 2: (2,), 3: (3, 4), 4: (5,)}   # rule RN: a step's text from the first raw step that has one
RAW_WRITE = {1: 1, 2: 2, 3: 3, 4: 5}              # --ingest: a step's answer stored under this raw step
RAW_STEPS = ("the five steps of SPEC-ladder 0.1 (raw 5 = the real text); mapped onto the four steps of SPEC-ladder 0.2 "
             "by rule RN: 1<-1, 2<-2, 3<-3 else 4, 4<-5")
HEB = re.compile(r"[֐-׿]")
SCHEMA = pa.schema([("key", pa.string()), ("portion", pa.string()), ("step", pa.int64()), ("text_model", pa.string()),
                    ("same_as", pa.int64()), ("hebrew_sha", pa.string()), ("aid", pa.bool_())])


def por(key):
    b, cv = key.split(" "); c = int(cv.split(":")[0])
    if b in ("JON", "RUT"): return b
    if b == "PSA" and 1 <= c <= 41: return "PSA1-41"
    if b == "ISA" and 40 <= c <= 55: return "ISA40-55"
    if b == "GEN" and 22 <= c <= 25: return "GEN22-25"
    return ""


def tsv(p):
    L = p.read_text(encoding="utf-8").split("\n")
    h = L[0].split("\t")
    return [dict(zip(h, l.split("\t"))) for l in L[1:] if l]


def lines(src):
    """{step: {key: point line}} for hbo, and the verse keys in text order (the real step)"""
    S, order = {}, []
    for s in range(1, LAST + 1):
        rows = tsv(src / "lines" / f"step{s}" / "hbo.point.tsv")
        S[s] = {r["key"]: r["line"] for r in rows}
        if s == LAST: order = [r["key"] for r in rows]
    return S, order


def steps_of(key):
    return list(range(1, LAST + 1)) if por(key) in STEP1 else list(range(2, LAST + 1))


def wanted(S, order):
    """(key, step) that need an English text: the real step, and a lower step whose line differs from the step above"""
    W = []
    for k in order:
        for s in sorted(steps_of(k), reverse=True):
            if s == LAST or S[s][k] != S[s + 1][k]: W.append((k, s))
    return W


def chap(key):
    b, cv = key.split(" "); return b, int(cv.split(":")[0])


def prepare(src):
    S, order = lines(src)
    W = set(wanted(S, order))
    base = src / "cache" / "english" / "input"
    files = {}
    for k in order:
        if not por(k): continue
        b, c = chap(k)
        f = base / por(k) / f"{b}-{c}.txt"
        v = k.split(":")[1]
        txt = files.setdefault(f, [f"# {b} {c}"])
        txt.append(f"@{v}")
        for s in sorted(steps_of(k), reverse=True):
            if (k, s) in W: txt.append(f"{s} {S[s][k]}")
    for f, txt in files.items():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("\n".join(txt) + "\n", encoding="utf-8")
    return {"chapters": len(files), "texts_wanted": len(W)}


def read_raw(p):
    if not p.is_file(): return {}
    return {(r["key"], int(r["step"])): r["text"] for r in tsv(p)}


def write_raw(p, R, order):
    pos = {k: i for i, k in enumerate(order)}
    rows = sorted(R.items(), key=lambda x: (pos[x[0][0]], -x[0][1]))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("key\tstep\ttext\n" + "".join(f"{k}\t{s}\t{t}\n" for (k, s), t in rows), encoding="utf-8")


def ingest(src, files):
    """merge answer files (per chapter a line `# BOOK ch`, then `v<TAB>step<TAB>text`) into english/raw/<portion>.tsv"""
    S, order = lines(src)
    W = set(wanted(S, order))
    res = []
    secs = []                           # a file may hold several chapters, each opened by its `# BOOK ch` line
    for fn in files:
        for l in Path(fn).read_text(encoding="utf-8").split("\n"):
            if not l.strip(): continue
            if l.startswith("# "): secs.append((f"{Path(fn).name} {l[2:]}", [l]))
            else: secs[-1][1].append(l)
    for fn, L in secs:
        b, c = L[0].lstrip("# ").split(); c = int(c)
        keys = [k for k in order if chap(k) == (b, c)]
        want = {(k, s) for (k, s) in W if k in keys}
        got, bad = {}, []
        for l in L[1:]:
            x = l.split("\t")
            if len(x) != 3: bad.append(("fields", l[:30])); continue
            k = f"{b} {c}:{x[0].strip()}"
            try: s = int(x[1])
            except ValueError: bad.append(("step", l[:30])); continue
            t = " ".join(x[2].split())
            if (k, s) not in want: bad.append(("unwanted", k, s)); continue
            if (k, s) in got: bad.append(("twice", k, s)); continue
            if not t or HEB.search(t): bad.append(("text", k, s)); continue
            got[(k, s)] = t
        miss = sorted(want - set(got), key=lambda x: (order.index(x[0]), -x[1]))
        if bad or miss:
            res.append({"file": fn, "bad": bad[:10], "missing": miss[:10], "n_bad": len(bad), "n_missing": len(miss)})
            continue
        p = src / "english" / "raw" / f"{por(keys[0])}.tsv"
        R = read_raw(p)
        for (k, s), t in got.items():
            R[(k, RAW_WRITE[s])] = t
            if s == 3: R.pop((k, 4), None)       # a new step-3 answer replaces a text taken from raw step 4
        write_raw(p, R, order)
        res.append({"file": fn, "rows": len(got)})
    return res


def renumber(R, W):
    """rule RN: {(key, step): text} for the wanted (key, step) from the raw rows {(key, raw step): text}; the raw rows
    used; the raw rows of old step 4 no step takes (dropped); the raw rows of other steps no step takes (an error)"""
    T, used = {}, set()
    for k, s in W:
        o = next((o for o in RAW_OF[s] if (k, o) in R), None)
        if o is not None: T[(k, s)] = R[(k, o)]; used.add((k, o))
    rest = [x for x in R if x not in used]
    return T, used, [x for x in rest if x[1] == 4], [x for x in rest if x[1] != 4]


def check(src, out):
    S, order = lines(src)
    W = wanted(S, order)
    Rraw = {}
    for po in PORTIONS:
        Rraw.update(read_raw(src / "english" / "raw" / f"{po}.tsv"))
    R, used, dropped, extra = renumber(Rraw, W)
    miss = [x for x in W if x not in R]
    if miss or extra:
        return {"missing": len(miss), "first_missing": miss[:5], "extra": len(extra), "first_extra": extra[:5]}
    rows = []
    for k in order:
        po = por(k)
        if not po: continue
        for s in steps_of(k):
            line = S[s][k]
            if (k, s) in R:
                t, same = R[(k, s)], None
            else:
                t, same = "", next(u for u in range(s + 1, LAST + 1) if (k, u) in R)
            rows.append({"key": k, "portion": po, "step": s, "text_model": t, "same_as": same,
                         "hebrew_sha": hashlib.sha256(line.encode("utf-8")).hexdigest(), "aid": True})
    (out / "english").mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), out / "english" / "english_model.parquet",
                   compression="zstd", use_dictionary=False, write_statistics=False)
    by = {}
    for r in rows:
        x = by.setdefault(f"{r['portion']} step {r['step']}", [0, 0]); x[0 if r["text_model"] else 1] += 1
    taken = collections.Counter(f"{s}<-raw {o}" for k, s in W for o in [next(o for o in RAW_OF[s] if (k, o) in Rraw)])
    return {"rows": len(rows), "texts": len(R), "same_as": len(rows) - len(R), "by_portion_step_text_same": by,
            "raw_rows": len(Rraw), "rule_rn": dict(sorted(taken.items())), "raw_step4_dropped": len(dropped)}


README = """# English aid (stage 62 of the Hebrew ladder pilot 1)

**%s**

Spend of the stage session: USD %s. Basis `model`. An aid for orientation beside the Hebrew; it is not part of the
verse card, of any other table, or of any line; step 4 (the real Hebrew) decides.

What it is: each verse of the five Tanakh portions (Jonah, Psalms 1-41, Isaiah 40-55, Ruth, Genesis 22-25), at each
step it has, put into English by the model from that step's `point` line alone. Step 4 in full; a lower step only where
its Hebrew line differs from the step above, keeping the English of the step above elsewhere, so the English differs
where the Hebrew does. Step 1 carries Metzudat David's wording; its English renders what the commentator says. Mark is
not translated.

What it is not: a translation of record, a reviewed text, or evidence for any Hebrew fact.

## Files

- `raw/<portion>.tsv`: the session's texts as written (key, step, text): one row per (verse, step) translated. An
  input once written (not rebuilt). Its `step` is the numbering the session wrote in: the five steps of SPEC-ladder
  0.1 (raw 5 = the real text). The ladder has four steps since SPEC-ladder 0.2 (2026-11-24; old step 4, R only, was
  dropped). Rule RN maps the raw rows: step 1 <- raw 1, step 2 <- raw 2, step 3 <- raw 3, else raw 4 (the same
  Hebrew: old step 3 pointed to old step 4 there), step 4 <- raw 5. A raw-4 row no step takes is not used. Nothing was
  translated again.
- `english_model.parquet`: one row per verse and step the verse has, built by
  `build_ladder.py --build pilot-1 --stage 62 --check`.

## Columns of english_model.parquet

| column | type | basis | meaning |
|---|---|---|---|
| key | string | derived | the verse, `BOOK ch:v` |
| portion | string | derived | JON, PSA1-41, ISA40-55, RUT, GEN22-25 |
| step | int | derived | 1-4 (1 only in JON, PSA1-41, ISA40-55; 4 the real text) |
| text_model | string | model | the English of this step's Hebrew (the raw row rule RN names); `""` where `same_as` is set |
| same_as | int | derived | the nearest step above whose row has a text, where this step's `point` line equals that step's (the lines of all steps between are equal); null where `text_model` is set |
| hebrew_sha | string | derived | sha256 (UTF-8) of this step's `point` line in `lines/step<N>/hbo.point.tsv` (a changed Hebrew shows a stale English) |
| aid | bool | derived | true on every row |
"""


def finish(src, out, sha, rel, repo, spend):
    (out / "english" / "README.md").write_text(README % (CREDIT, json.dumps(spend)), encoding="utf-8")
    sj = json.loads((src / "sources.json").read_text(encoding="utf-8"))
    for po in PORTIONS:
        p = src / "english" / "raw" / f"{po}.tsv"
        q = f"shoresh/macula/data/hebrew-ladder/{src.name}/english/raw/{po}.tsv"
        sj[q] = {"sha256": sha(p), "basis": "model", "credit": CREDIT, "model": MODEL, "session": "stage 62",
                 "date": DATE, "spend_usd": spend, "human_check": "none", "aid": True, "raw_steps": RAW_STEPS}
    (out / "sources.json").write_text(json.dumps(sj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    cat = (src / "categories.toml").read_text(encoding="utf-8").split(CAT_MARK)[0].rstrip("\n") + "\n"
    cat += CAT_MARK + "\n[credit_english]\n" + "\n".join([
        f"english = {json.dumps(CREDIT)}", f'english_model = "{MODEL}"', 'english_session = "stage 62"',
        f'english_date = "{DATE}"', "english_human_check = false", f"english_spend_usd = {json.dumps(spend)}",
        "english_aid = true"]) + "\n"
    (out / "categories.toml").write_text(cat, encoding="utf-8")
    bj = json.loads((src / "build.json").read_text(encoding="utf-8"))
    files = dict(bj["files"])
    for r in ("english/english_model.parquet", "english/README.md", "sources.json", "categories.toml"):
        files[r] = sha(out / r)
    for po in PORTIONS:
        files[f"english/raw/{po}.tsv"] = sha(src / "english" / "raw" / f"{po}.tsv")
    bj["files"] = dict(sorted(files.items()))
    bj["code"] = {c: sha(repo / c) for c in sorted(set(bj["code"]) | set(CODE62))}     # every pinned code file, refreshed
    bj["stage62"] = {"entry": "shoresh/.venv/bin/python -I shoresh/macula/build_ladder.py --build pilot-1 --stage 62 --check --spend USD",
                     "model": MODEL, "session": "stage 62", "date": DATE, "credit": CREDIT, "spend_usd": spend,
                     "human_check": "none", "aid": True, "raw_steps": RAW_STEPS}
    (out / "build.json").write_text(json.dumps(bj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return bj
