"""Stage 60 of the Hebrew ladder: the chooser (SPEC-ladder 7).

    cd shoresh && .venv/bin/python -I macula/build_ladder.py --build pilot-1 --stage 60 --prepare [--batch N]
    cd shoresh && .venv/bin/python -I macula/build_ladder.py --build pilot-1 --stage 60 --check [--out DIR]

`--prepare` writes chooser/input/<BOOK>.jsonl (7.2) and, for the session's reading only, a compact view of the same
input in cache/chooser/view/<BOOK>-<NN>.txt (batches of whole verses). The session (the model) writes
chooser/decisions/<BOOK>.tsv (7.3). `--check` applies rule SP (7.4), writes chooser/choices_model.parquet and
categories.toml, and extends sources.json, COLUMNS.md and build.json. It reads nothing in sealed/ except its sha256.
"""
import collections, hashlib, json, unicodedata as ud
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from macula import ladder_banks as LB

MODEL = "claude-opus-5-5"
SPEND = 11.25                   # the stage 60 session's spend (USD) up to its --check run (the report gives the end figure)
CREDIT = ("Kind and spans chosen by the model claude-opus-5-5 (the stage 60 session of the Hebrew ladder pilot 1, "
          "2026-11), from Metzudat David's comments and the Masoretic text; no human check.")
KINDS = ("restates", "restates_adds", "explains")
REFUSALS = ("bad_kind", "bad_span", "spans_for_explains", "no_spans", "overlap", "order", "empty_written")
BOOKS = ("JON", "PSA", "ISA")
L2 = LB.DATA / "hebrew-levels" / "pilot-2"
CODE60 = ["shoresh/macula/build_ladder.py", "shoresh/macula/ladder_stage60.py"]
HEAD = ["comment", "kind", "c_from", "c_to", "v_from", "v_to"]


def unpoint(s):
    return "".join(c for c in ud.normalize("NFD", s or "") if ud.category(c) != "Mn" and c not in "|׀")


def cons(s):
    return "".join(c for c in ud.normalize("NFD", s or "") if 0x05D0 <= ord(c) <= 0x05EA).translate(LB.FINALS)


def load_inputs():
    """the anchored step-1 comments, their tokens, and the verse at steps 2 and 5"""
    P = [r for r in pq.read_table(LB.HERE / "data/hebrew-ladder/pilot-1/banks/paraphrase.parquet").to_pylist() if r["in_pilot"]]
    want = {r["comment"] for r in P}
    T = collections.defaultdict(list)
    for r in pq.read_table(LB.HERE / "data/hebrew-ladder/pilot-1/banks/paraphrase_tokens.parquet").to_pylist():
        if r["comment"] in want: T[r["comment"]].append(r)
    keys = {r["key"] for r in P}
    k1w = [r for r in pq.read_table(LB.K1 / "hbo" / "words.parquet", columns=["t", "book", "chapter", "verse", "w", "text"]).to_pylist()
           if f"{r['book']} {r['chapter']}:{r['verse']}" in keys]
    s5 = collections.defaultdict(list); wof = {}
    for r in sorted(k1w, key=lambda r: r["t"]):
        s5[f"{r['book']} {r['chapter']}:{r['verse']}"].append({"w": r["w"], "text": r["text"]}); wof[r["t"]] = r["w"]
    d = L2 / "texts" / "z_r_a" / "hbo"
    src = collections.defaultdict(set)
    for l in pq.read_table(d / "links.parquet", columns=["t", "s"]).to_pylist():
        if l["s"] in wof: src[l["t"]].add(wof[l["s"]])
    s2 = collections.defaultdict(list)
    for r in sorted(pq.read_table(d / "words.parquet", columns=["t", "book", "chapter", "verse", "text"]).to_pylist(), key=lambda r: r["t"]):
        k = f"{r['book']} {r['chapter']}:{r['verse']}"
        if k in keys: s2[k].append({"w": min(src[r["t"]]), "text": r["text"]})
    return P, T, s2, s5


def inputs():
    P, T, s2, s5 = load_inputs()
    byverse = collections.defaultdict(list)
    for r in P:
        if r["anchor_state"] == "anchored": byverse[r["key"]].append(r)
    out = collections.defaultdict(list)
    for r in P:
        if r["anchor_state"] != "anchored": continue
        o = {"comment": r["comment"], "key": r["key"], "verse_step2": s2[r["key"]], "verse_step5": s5[r["key"]],
             "anchor": {"anchor_w_from": r["anchor_w_from"], "anchor_w_to": r["anchor_w_to"], "anchor_tier": r["anchor_tier"]},
             "lemma": r["lemma"],
             "tokens": [{"i": t["i"], "written": t["written"], "part": t["part"]} for t in sorted(T[r["comment"]], key=lambda t: t["i"])],
             "markers": json.loads(r["markers"]),
             "others": [{"comment": x["comment"], "w_from": x["anchor_w_from"], "w_to": x["anchor_w_to"]}
                        for x in byverse[r["key"]] if x["comment"] != r["comment"]]}
        out[r["book"]].append(o)
    unanchored = [r["comment"] for r in P if r["anchor_state"] != "anchored"]
    return out, unanchored, {r["comment"]: r for r in P}


def view_verse(objs):
    """one verse, all its comments: the reading view of the same input (unpointed, numbered)"""
    o = objs[0]
    v5 = o["verse_step5"]; t5 = {x["w"]: unpoint(x["text"]) for x in v5}
    lines = [f"## {o['key']}", " ".join(f"{x['w']}{unpoint(x['text'])}" for x in v5)]
    diff = []; seen = collections.Counter()
    for x in o["verse_step2"]:
        seen[x["w"]] += 1; tx = unpoint(x["text"])
        if seen[x["w"]] > 1 or tx != t5.get(x["w"]): diff.append(f"{x['w']}{'+' if seen[x['w']] > 1 else '='}{tx}")
    if diff: lines.append("s2: " + " ".join(diff))
    for o in objs:
        a = o["anchor"]; n = o["comment"].rsplit(":", 1)[1]
        m = ",".join(o["markers"])
        lines.append(f"#{n} a{a['anchor_w_from']}-{a['anchor_w_to']}{'' if a['anchor_tier'] == 'exact' else ' ' + a['anchor_tier']}"
                     f"{' m=' + m if m else ''} [{o['lemma']}]")
        toks = []
        for t in o["tokens"]:
            w = t["written"].replace(" ", "_")
            toks.append(f"{t['i']}{w}" if t["part"] == "body" else f"({t['i']}{w})")
        lines.append(" ".join(toks))
    return "\n".join(lines)


def prepare(out, batch=150):
    data, unanchored, _ = inputs()
    (out / "chooser" / "input").mkdir(parents=True, exist_ok=True)
    vd = out / "cache" / "chooser" / "view"; vd.mkdir(parents=True, exist_ok=True)
    plan = []
    for b in BOOKS:
        objs = data[b]
        with open(out / "chooser" / "input" / f"{b}.jsonl", "w", encoding="utf-8") as f:
            for o in objs: f.write(json.dumps(o, ensure_ascii=False, sort_keys=True) + "\n")
        verses = collections.OrderedDict()
        for o in objs: verses.setdefault(o["key"], []).append(o)
        cur, n, nb = [], 0, 1
        def flush():
            nonlocal cur, n, nb
            if not cur: return
            (vd / f"{b}-{nb:02d}.txt").write_text("\n".join(cur) + "\n", encoding="utf-8")
            plan.append((f"{b}-{nb:02d}", n)); cur, n, nb = [], 0, nb + 1
        for k, vs in verses.items():
            cur.append(view_verse(vs)); n += len(vs)
            if n >= batch: flush()
        flush()
    return {"inputs": {b: len(data[b]) for b in BOOKS}, "unanchored": unanchored, "batches": plan}


KIND_CODE = {"r": "restates", "ra": "restates_adds", "e": "explains"}


def ingest(out, batch):
    """append the session's answers of one batch (cache/chooser/answers/<batch>.txt, written by the session in short
    form: a line `BOOK ch:v`, then per comment `n kind [c_from-c_to v_from-v_to]`, kind r / ra / e or a full code) to
    chooser/decisions/<BOOK>.tsv. A pure re-writing: every value is the session's."""
    book = batch.split("-")[0]
    lines = (out / "cache" / "chooser" / "answers" / f"{batch}.txt").read_text(encoding="utf-8").splitlines()
    have = read_decisions(out); rows = []; key = None
    for l in lines:
        l = l.split("#")[0].strip()
        if not l: continue
        if l.startswith(book + " "):
            key = l.split()[1]; continue
        x = l.split(); n, k = x[0], KIND_CODE.get(x[1], x[1])
        sp = ["", "", "", ""]
        if len(x) >= 4:
            a, b = x[2].split("-"); c, d = x[3].split("-"); sp = [a, b, c, d]
        ch, v = key.split(":")
        c = f"md:{book}:{ch}:{v}:{n}"
        assert c not in have and c not in {r[0] for r in rows}, f"{c} twice"
        rows.append([c, k] + sp)
    p = out / "chooser" / "decisions" / f"{book}.tsv"; p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.is_file()
    with open(p, "a", encoding="utf-8") as f:
        if new: f.write("\t".join(HEAD) + "\n")
        for r in rows: f.write("\t".join(r) + "\n")
    return len(rows)


def read_decisions(out):
    rows = {}
    for b in BOOKS:
        p = out / "chooser" / "decisions" / f"{b}.tsv"
        if not p.is_file(): continue
        L = p.read_text(encoding="utf-8").splitlines()
        assert L[0].split("\t") == HEAD, f"{p}: header"
        for l in L[1:]:
            if not l.strip(): continue
            x = l.split("\t"); x += [""] * (6 - len(x))
            assert x[0] not in rows, f"{x[0]} twice"
            rows[x[0]] = x
    return rows


def as_int(s):
    s = (s or "").strip()
    if not s: return None
    try: return int(s)
    except ValueError: return "bad"


def check(src, out, spend=SPEND):
    """rule SP over the decisions of `src`; writes into `out` (the same folder unless a rebuild)"""
    objs = []
    for b in BOOKS:
        with open(src / "chooser" / "input" / f"{b}.jsonl", encoding="utf-8") as f:
            objs += [json.loads(l) for l in f]
    dec = read_decisions(src)
    bank = {r["comment"]: r for r in pq.read_table(src / "banks" / "paraphrase.parquet").to_pylist() if r["in_pilot"]}
    accepted = collections.defaultdict(list)          # key -> [(v_from, v_to, c_from, c_to, comment)]
    rows, missing = [], []
    for o in objs:
        c = o["comment"]; x = dec.get(c)
        if x is None: missing.append(c); continue
        kind = x[1].strip(); cf, ct, vf, vt = (as_int(v) for v in x[2:6])
        body = {t["i"] for t in o["tokens"] if t["part"] == "body"}
        cite = {t["i"] for t in o["tokens"] if t["part"] == "cite"}
        ws = {w["w"] for w in o["verse_step5"]}
        sp = (cf, ct, vf, vt); ref = ""
        if kind not in KINDS: ref = "bad_kind"
        elif "bad" in sp: ref = "bad_span"
        elif (cf is None) != (ct is None) or (vf is None) != (vt is None): ref = "bad_span"
        elif cf is not None and (cf > ct or any(i not in body for i in range(cf, ct + 1)) or any(cf <= i <= ct for i in cite)): ref = "bad_span"
        elif vf is not None and (vf > vt or vf not in ws or vt not in ws): ref = "bad_span"   # k1's w has gaps (ketiv); both ends must be words
        elif kind == "explains" and (cf is not None or vf is not None): ref = "spans_for_explains"
        elif kind != "explains" and (cf is None or vf is None): ref = "no_spans"
        elif kind != "explains":
            acc = accepted[o["key"]]
            if any(not (vt < a[0] or vf > a[1]) for a in acc): ref = "overlap"
            elif any(vf < a[0] for a in acc): ref = "order"
            else:
                wr = [t["written"] for t in o["tokens"] if cf <= t["i"] <= ct]
                if not " ".join(wr).split(): ref = "empty_written"
        check_ = "no_splice" if (kind == "explains" and not ref) else ("refused" if ref else "accepted")
        if check_ == "accepted": accepted[o["key"]].append((vf, vt, cf, ct, c))
        b = bank[c]; acc_ = check_ == "accepted"
        rows.append({"choice": c, "key": o["key"], "portion": LB.portion_of(b["book"], b["chapter"]),
                     "kind_model": kind, "c_from_model": cf if isinstance(cf, int) else None, "c_to_model": ct if isinstance(ct, int) else None,
                     "v_from_model": vf if isinstance(vf, int) else None, "v_to_model": vt if isinstance(vt, int) else None,
                     "check": check_, "refusal": ref, "figure": bool(b["figure"]),
                     "splice_kind": ("F" if b["figure"] else "P") if acc_ else ""})
    extra = sorted(set(dec) - {o["comment"] for o in objs})
    lint = lint_splices(objs, accepted)
    if missing or extra:
        return {"missing": len(missing), "missing_first": missing[:5], "extra": extra[:5], "lint": lint,
                "so_far": dict(collections.Counter(r["check"] + ":" + r["refusal"] for r in rows)),
                "refused": [(r["choice"], r["refusal"]) for r in rows if r["check"] == "refused"]}
    (out / "chooser").mkdir(parents=True, exist_ok=True)
    sch = pa.schema([("choice", pa.string()), ("key", pa.string()), ("portion", pa.string()), ("kind_model", pa.string()),
                     ("c_from_model", pa.int64()), ("c_to_model", pa.int64()), ("v_from_model", pa.int64()), ("v_to_model", pa.int64()),
                     ("check", pa.string()), ("refusal", pa.string()), ("figure", pa.bool_()), ("splice_kind", pa.string())])
    pq.write_table(pa.Table.from_pylist(rows, schema=sch), out / "chooser" / "choices_model.parquet", compression="zstd")
    cnt = collections.Counter((r["portion"], r["kind_model"], r["check"], r["refusal"]) for r in rows)
    return {"rows": len(rows), "counts": {"|".join(k): v for k, v in sorted(cnt.items())},
            "accepted": sum(r["check"] == "accepted" for r in rows), "lint": lint}


def lint_splices(objs, accepted):
    """for the session: doubled words at splice edges (a comment word equal to the step-2 word beside the span)"""
    byc = {o["comment"]: o for o in objs}; byk = {o["key"]: o for o in objs}
    dbl = []
    for k, acc in accepted.items():
        s2 = byk[k]["verse_step2"]
        for vf, vt, cf, ct, c in acc:
            cw = " ".join(t["written"] for t in byc[c]["tokens"] if cf <= t["i"] <= ct).split()
            before = [x for x in s2 if x["w"] < vf]; after = [x for x in s2 if x["w"] > vt]
            if before and cw and cons(cw[0]) == cons(before[-1]["text"]): dbl.append((c, "start", cw[0]))
            if after and cw and cons(cw[-1]) == cons(after[0]["text"]): dbl.append((c, "end", cw[-1]))
    return dbl


COLUMNS_60 = """
# Columns (stage 60: the chooser)

## chooser/input/<BOOK>.jsonl (written by the builder before the session; SPEC-ladder 7.2)

One json object per anchored comment of the step-1 scope, in comment order: `comment`, `key`; `verse_step2` (the
step-2 text of hebrew-levels/pilot-2 level `z_r_a`, `{w, text}`, `w` the k1 source word's `w`; a word written in by
switch A carries its host's `w`), `verse_step5` (k1/hbo, `{w, text}`: the real text, step 5 of SPEC-ladder 0.1 and step 4
since 0.2; the key keeps the name the stage 60 session saw); `anchor` (`anchor_w_from`, `anchor_w_to`,
`anchor_tier`); `lemma`; `tokens` (`{i, written, part}`); `markers`; `others` (the anchors of the verse's other
comments: `comment`, `w_from`, `w_to`). All derived or given from the bank and the texts; nothing English.

## chooser/decisions/<BOOK>.tsv (the model's raw output, kept as written)

`comment`, `kind`, `c_from`, `c_to`, `v_from`, `v_to`: basis `model` (written by the stage 60 session, claude-opus-5-5).

## chooser/choices_model.parquet

| column | basis | meaning |
|---|---|---|
| choice, key, portion | derived | the comment key, its verse, its portion |
| kind_model | model | `restates`, `restates_adds`, `explains` |
| c_from_model, c_to_model, v_from_model, v_to_model | model | the comment span (`i`, inclusive) and the verse span (`w`, inclusive); null for `explains` |
| check | derived | rule SP: `accepted`, `refused`, `no_splice` |
| refusal | derived | the first reason of SP that holds; `""` otherwise |
| figure | derived | the bank's `figure` |
| splice_kind | derived | `F` (accepted, figure), `P` (accepted otherwise), `""` |

Credit: %s
"""

CATEGORIES = """# Coded values of hebrew-ladder/pilot-1 (SPEC-ladder 7)

[credit]
chooser = %s
chooser_model = "%s"
chooser_session = "stage 60"
chooser_date = "2026-11-24"
chooser_human_check = false
chooser_spend_usd = %s

[codes]
kind_model = %s
check = ["accepted", "refused", "no_splice"]
refusal = %s
splice_kind = ["P", "F"]
"""


def finish(src, out, sha, rel, repo, spend=SPEND):
    """write categories.toml, extend sources.json, COLUMNS.md and build.json (after check())"""
    old = (src / "categories.toml").read_text(encoding="utf-8") if (src / "categories.toml").is_file() else ""
    _, mark, tail = old.partition("\n# English aid (stage 62)\n")      # a later stage's section is kept as it stands
    (out / "categories.toml").write_text(CATEGORIES % (json.dumps(CREDIT, ensure_ascii=False), MODEL, json.dumps(spend),
                                                       json.dumps(list(KINDS)), json.dumps(list(REFUSALS))) + mark + tail,
                                         encoding="utf-8")
    sj = json.loads((src / "sources.json").read_text(encoding="utf-8"))
    for p in sorted((L2 / "texts" / "z_r_a" / "hbo").glob("*.parquet")):
        sj[rel(p)] = {"sha256": sha(p), "read_for": "stage 60: the step-2 text of the chooser input"}
    for b in BOOKS:
        p = src / "chooser" / "decisions" / f"{b}.tsv"
        q = Path("shoresh/macula/data/hebrew-ladder") / src.name / "chooser" / "decisions" / f"{b}.tsv"
        sj[str(q)] = {"sha256": sha(p), "basis": "model", "credit": CREDIT, "model": MODEL, "spend_usd": spend,
                      "human_check": "none"}
    (out / "sources.json").write_text(json.dumps(sj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    col = (src / "COLUMNS.md").read_text(encoding="utf-8")
    head, sep, tail = col.partition("\n# Columns (stage 61")      # a later stage's section is kept as it stands
    col = head.split("\n# Columns (stage 60")[0]
    (out / "COLUMNS.md").write_text(col + COLUMNS_60 % CREDIT + sep + tail, encoding="utf-8")
    bj = json.loads((src / "build.json").read_text(encoding="utf-8"))
    files = {}
    for p in sorted(out.rglob("*")):
        r = p.relative_to(out)
        if p.is_file() and p.name not in ("build.json", "VALIDATION.md") and r.parts[0] not in ("cache", "sealed", "trash") \
                and not r.parts[0].startswith("rebuild"):
            files[str(r)] = sha(p)
    if out != src:      # a rebuild: copy the stage-58 files it did not write, so the list is whole
        for k, v in bj["files"].items(): files.setdefault(k, v)
    files["sealed/chooser_sample.tsv"] = bj["sealed_chooser"]
    bj["files"] = dict(sorted(files.items()))
    bj["code"] = dict(sorted({**bj["code"], **{c: sha(repo / c) for c in CODE60}}.items()))
    bj["stage60"] = {"entry": "shoresh/.venv/bin/python -I shoresh/macula/build_ladder.py --build pilot-1 --stage 60 --check",
                     "model": MODEL, "credit": CREDIT, "spend_usd": spend, "human_check": "none",
                     "inputs": {b: sha(src / "chooser" / "input" / f"{b}.jsonl") for b in BOOKS}}
    (out / "build.json").write_text(json.dumps(bj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return bj
