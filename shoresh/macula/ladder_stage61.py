"""Stage 61 of the Hebrew ladder: the four steps (SPEC-ladder 0.2, sections 8, 9, 11).

    cd shoresh && .venv/bin/python -I macula/build_ladder.py --build pilot-1 --stage 61 [--out DIR]

Writes into pilot-1/: profiles.toml (8.1), texts/step<N>/<part>/ (8.2), changes.parquet (8.3), lines/, differ.tsv,
thin.tsv (8.4), layout/ (8.5), sealed/step_sample.tsv (8.6), README.md; extends sources.json, COLUMNS.md, build.json.
GUIDE.md is prose written beside the build (it is copied in from internal-docs/source-examples-work/ladder/GUIDE.md).
Reads hebrew-levels/pilot-2 (steps 2-4), chooser/choices_model.parquet and banks/paraphrase_tokens.parquet (step 1).
Every output is a function of those inputs and of profiles.toml; nothing is written by hand.
"""
import collections, json, random, shutil, tomllib
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from macula import ladder_banks as LB
from macula import ladder_switches as LS

L43, L = LS.L43, LS.L
L2 = LB.DATA / "hebrew-levels" / "pilot-2"
PARTS = ("hbo", "heb_mod", "heb_scg")
LAST = 4                    # the real text (SPEC-ladder 0.2: old step 4, R only, dropped 2026-11-24; old step 5 is 4)
PAIRS = tuple((a, a + 1) for a in range(1, LAST))
SEED = "ladder-2026-11-24-steps"
CODE61 = ["shoresh/macula/build_ladder.py", "shoresh/macula/ladder_stage61.py", "shoresh/macula/ladder_card.py"]
GUIDE_SRC = LB.HERE.parent.parent / "internal-docs" / "source-examples-work" / "ladder" / "GUIDE.md"
I, S = pa.int64(), pa.string()
LINKS1 = pa.schema(list(L43.LINKS) + [("comment", S), ("i", I)])
CHANGES = pa.schema([("change", S), ("step", I), ("part", S), ("key", S), ("kind", S), ("source", S), ("words_here", S),
                     ("words_next", S), ("src", S), ("text_here", S), ("text_next", S), ("under_splice", S), ("basis_here", S)])
STEP_FILES = ("profiles.toml", "changes.parquet", "differ.tsv", "thin.tsv", "sealed/step_sample.tsv", "GUIDE.md", "README.md")

PROFILES = '''[meta]
spec = "Ladder specification, version 0.2"
levels_build = "hebrew-levels/pilot-2"

[[step]]
step = 1
name = "easiest"
switches = ["P", "F", "V", "A", "R"]
base_level = "z_r_a"            # the step-2 text, with the accepted splices of stage 60 over it
portions = ["JON", "PSA1-41", "ISA40-55"]

[[step]]
step = 2
name = "easy"
switches = ["V", "A", "R"]
level = { hbo = "z_r_a", heb_mod = "r", heb_scg = "r" }
portions = ["JON", "PSA1-41", "ISA40-55", "RUT", "GEN22-25", "MRK"]

[[step]]
step = 3
name = "more advanced"
switches = ["V", "R"]
v = "rare"                     # rule RARE: Tanakh count below 20
level = { hbo = "zr_r", heb_mod = "r", heb_scg = "r" }
portions = ["JON", "PSA1-41", "ISA40-55", "RUT", "GEN22-25", "MRK"]

[[step]]
step = 4
name = "real"
switches = []
level = { hbo = "l0", heb_mod = "l0", heb_scg = "l0" }
portions = ["JON", "PSA1-41", "ISA40-55", "RUT", "GEN22-25", "MRK"]

[missing]                      # a switch a profile names that a part (heb_*) or a portion has no source for
heb_mod = { V = "no_gloss_bank", A = "not_in_editions" }
heb_scg = { V = "no_gloss_bank", A = "not_in_editions" }
RUT = { V = "no_gloss_bank" }
"GEN22-25" = { V = "no_gloss_bank" }
'''


def jd(x):
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def vk(r):
    return f"{r['book']} {r['chapter']}:{r['verse']}"


def wparquet(path, rows, schema):
    LS.write_parquet(path, L43.cols(rows, schema), schema)


def profiles(out):
    (out / "profiles.toml").write_text(PROFILES, encoding="utf-8")
    P = tomllib.loads((out / "profiles.toml").read_text(encoding="utf-8"))
    steps = {s["step"]: s for s in P["step"]}
    return P, steps


def steps_from(out):
    return {s["step"]: s for s in tomllib.loads((out / "profiles.toml").read_text(encoding="utf-8"))["step"]}


def parts_of(st):
    """the parts a step has: step 1 hbo only (its portions are Tanakh portions)"""
    if "level" in st: return [p for p in PARTS if p in st["level"]]
    return ["hbo"]


def read_level(level, part):
    d = L2 / "texts" / level / part
    return tuple(pq.read_table(d / f).to_pylist() for f in ("words.parquet", "pieces.parquet", "links.parquet"))


def in_portions(rows_w, portions):
    return [w for w in rows_w if LS.portion(w["book"], w["chapter"]) in portions]


def k1_w():
    """(other, source t) -> the source word's w, over hbo and arc"""
    out = {}
    for part in ("hbo", "arc"):
        for r in pq.read_table(LB.K1 / part / "words.parquet", columns=["t", "w"]).to_pylist():
            out[(part, r["t"])] = r["w"]
    return out


def step1(src, W2, P2, K2, portions):
    """SPEC-ladder 8.2: the step-2 text with every accepted splice applied; returns the tables and the step-1 changes"""
    W2 = in_portions(W2, portions); keep = {w["t"] for w in W2}
    P2 = [p for p in P2 if p["t"] in keep]; K2 = [k for k in K2 if k["t"] in keep]
    kw = k1_w(); links = collections.defaultdict(list); pieces = collections.defaultdict(list)
    for k in K2: links[k["t"]].append(k)
    for p in P2: pieces[p["t"]].append(p)
    sw = {w["t"]: min(kw[(k["other"], k["s"])] for k in links[w["t"]]) for w in W2}
    toks = collections.defaultdict(list)
    for r in pq.read_table(src / "banks" / "paraphrase_tokens.parquet").to_pylist(): toks[r["comment"]].append(r)
    acc = collections.defaultdict(list)
    for c in pq.read_table(src / "chooser" / "choices_model.parquet").to_pylist():
        if c["check"] == "accepted": acc[c["key"]].append(c)
    byv = collections.OrderedDict()
    for w in W2: byv.setdefault(vk(w), []).append(w)
    W, P, K, ch = [], [], [], []
    t = 0
    for key, ws in byv.items():
        spans = sorted(acc.get(key, []), key=lambda c: c["v_from_model"])
        pos = 0; j = 0
        while j < len(ws):
            sp = next((c for c in spans if c["v_from_model"] <= sw[ws[j]["t"]] <= c["v_to_model"]), None)
            if sp is None:
                w = ws[j]; t += 1; pos += 1
                W.append({**w, "t": t, "w": pos})
                P += [{**p, "t": t} for p in pieces[w["t"]]]
                K += [{**k, "t": t, "comment": "", "i": None} for k in links[w["t"]]]
                j += 1; continue
            gone = []
            while j < len(ws) and sp["v_from_model"] <= sw[ws[j]["t"]] <= sp["v_to_model"]:
                gone.append(ws[j]); j += 1
            spans.remove(sp)
            cw = [(x, tk["i"]) for tk in toks[sp["choice"]] if sp["c_from_model"] <= tk["i"] <= sp["c_to_model"]
                  for x in tk["written"].split()]
            srcp = sorted({(k["other"], k["s"], k["s_n"]) for g in gone for k in links[g["t"]]}, key=lambda x: (x[1], x[2], x[0]))
            here = []
            for m, (x, i) in enumerate(cw):
                t += 1; pos += 1; here.append(t)
                W.append({"t": t, "book": gone[0]["book"], "chapter": gone[0]["chapter"], "verse": gone[0]["verse"], "w": pos,
                          "text": x, "after": gone[-1]["after"] if m == len(cw) - 1 else " ", "sentence": gone[0]["sentence"],
                          "clause": gone[0]["clause"], "op": sp["choice"]})
                P.append({"t": t, "n": 1, "text": x, "kind": "comment", "lexeme": "", "class": "", "marks": "{}", "who": "",
                          "who_basis": "", "basis": "model", "op": sp["choice"]})
                K += [{"t": t, "n": 1, "s": s, "agree": None, "agree_model": 1, "other": o, "how": "comment", "basis": "model",
                       "s_n": n, "comment": sp["choice"], "i": i} for o, s, n in srcp]
            under = sorted({g["op"] for g in gone if g["op"]} | {p["op"] for g in gone for p in pieces[g["t"]] if p["op"]})
            ch.append({"step": 1, "part": "hbo", "key": key, "kind": sp["splice_kind"], "source": sp["choice"],
                       "words_here": here, "words_next": [g["t"] for g in gone], "src": [[s, n] for _, s, n in srcp],
                       "text_here": " ".join(x for x, _ in cw), "text_next": " ".join(g["text"] for g in gone),
                       "under_splice": under, "basis_here": "model"})
        if spans: raise SystemExit(f"step 1: splices of {key} not applied: {[c['choice'] for c in spans]}")
    return (W, P, K), ch


def reach(Kx, Ky, ts):
    """the words of text Y that link (copy, replace) to a source piece the words ts of text X link to (copy, replace)"""
    hows = ("copy", "replace")
    want = {(k["other"], k["s"], k["s_n"]) for t in ts for k in Kx[t] if k["how"] in hows}
    return sorted({k["t"] for ks in Ky.values() for k in ks if k["how"] in hows and (k["other"], k["s"], k["s_n"]) in want})


def ops_applied():
    A = collections.defaultdict(dict); dup = []
    for r in pq.read_table(L2 / "ops.parquet").to_pylist():
        if r["state"] != "applied": continue
        k = (r["switch"], r["src_t"], r["src_n"])
        if k in A[(r["level"], r["text"])]: dup.append(r["op"])
        A[(r["level"], r["text"])][k] = r
    if dup: raise SystemExit(f"rule CH: ops with the same (switch, src_t, src_n) in one level: {dup[:5]}")
    return A


def changes_ch(steps, T, A):
    """rule CH (8.3) for the pairs 2/3, 3/4"""
    out = []; only_next = 0
    for s in range(2, LAST):
        for part in parts_of(steps[s + 1]):
            la, lb = steps[s]["level"][part], steps[s + 1]["level"][part]
            if la == lb: continue
            (Wa, _, Ka), (Wb, _, Kb) = T[(s, part)], T[(s + 1, part)]
            ka, kb = collections.defaultdict(list), collections.defaultdict(list)
            for k in Ka: ka[k["t"]].append(k)
            for k in Kb: kb[k["t"]].append(k)
            wa, wb = {w["t"]: w for w in Wa}, {w["t"]: w for w in Wb}
            oa, ob = A.get((la, part), {}), A.get((lb, part), {})
            for key in sorted(set(oa) | set(ob), key=lambda x: (x[1], x[2], x[0])):
                a, b = oa.get(key), ob.get(key)
                if a and b and a["after"] == b["after"]: continue
                here = json.loads(a["draft_t"]) if a else reach(kb, ka, json.loads(b["draft_t"]))
                nxt = json.loads(b["draft_t"]) if b else reach(ka, kb, here)
                if not a: only_next += 1
                src = sorted({(k["s"], k["s_n"]) for t in here for k in ka[t]} | {(k["s"], k["s_n"]) for t in nxt for k in kb[t]})
                op = a or b
                out.append({"step": s, "part": part, "key": op["key"], "kind": key[0].upper(), "source": op["op"],
                            "words_here": here, "words_next": nxt, "src": [list(x) for x in src],
                            "text_here": " ".join(wa[t]["text"] for t in here), "text_next": " ".join(wb[t]["text"] for t in nxt),
                            "under_splice": [], "basis_here": "derived"})
    return out, only_next


def raw_lines(part, W):
    return {L.vkey(*k): raw for k, raw in L43.raw_lines(part, W)}


def layout_rows(part, W, depth):
    rows = []; cur = None
    for w in W:
        k = vk(w); piece = w["text"] + w["after"] if part == "hbo" else w["text"]
        if cur and cur[0] == k and cur[1] == w["clause"]:
            cur[3].append(piece)
        else:
            cur = [k, w["clause"], depth.get(w["clause"]), [piece]]; rows.append(cur)
    j = "" if part == "hbo" else " "
    return [(k, c, d, j.join(ps)) for k, c, d, ps in rows]


def build(src, out):
    """everything of stage 61 into `out` (src: the build folder with stages 58-60)"""
    out.mkdir(parents=True, exist_ok=True)
    P, steps = profiles(out)
    T = {}; ch1 = []
    for n in range(2, LAST + 1):
        for part in parts_of(steps[n]):
            W, Pc, K = read_level(steps[n]["level"][part], part)
            W = in_portions(W, steps[n]["portions"]); keep = {w["t"] for w in W}
            T[(n, part)] = (W, [p for p in Pc if p["t"] in keep], [k for k in K if k["t"] in keep])
    T[(1, "hbo")], ch1 = step1(src, *T[(2, "hbo")], steps[1]["portions"])
    for (n, part), (W, Pc, K) in sorted(T.items()):
        d = out / "texts" / f"step{n}" / part
        wparquet(d / "words.parquet", W, L43.WORDS)
        wparquet(d / "pieces.parquet", Pc, LS.PIECES)
        wparquet(d / "links.parquet", K, LINKS1 if n == 1 else L43.LINKS)
    A = ops_applied()
    chs, only_next = changes_ch(steps, T, A)
    allc = ch1 + chs
    allc.sort(key=lambda c: (c["step"], c["part"], min(map(tuple, c["src"])) if c["src"] else (0, 0), c["kind"], c["source"]))
    num = collections.Counter(); rows = []
    for c in allc:
        num[(c["step"], c["part"])] += 1
        rows.append({**c, "change": f"ch:{c['step']}:{c['part']}:{num[(c['step'], c['part'])]}",
                     **{k: jd(c[k]) for k in ("words_here", "words_next", "src", "under_splice")}})
    wparquet(out / "changes.parquet", rows, CHANGES)
    # lines (8.4)
    lines = {}
    for (n, part), (W, _, _) in T.items():
        raw = raw_lines(part, W)
        lines[(n, part)] = {k: (L43.norm_cons(r), L43.norm_point(r)) for k, r in raw.items()}
    for (n, part), lv in sorted(lines.items()):
        nxt = lines.get((n + 1, part), {})
        for fi, form in enumerate(("cons", "point")):
            recs = []
            for k, f in lv.items():
                b, cv = k.split(" "); c = int(cv.split(":")[0])
                recs.append((k, part, n, form, L.scoring_closed(b, c), n < LAST and f[1] != nxt[k][1], f[fi]))
            LS.write_tsv(out / "lines" / f"step{n}" / f"{part}.{form}.tsv",
                         ["key", "part", "step", "form", "scoring_closed", "changed", "line"], recs)
    # differ.tsv, thin.tsv
    miss = P["missing"]; drows, trows = [], []
    for por in steps[LAST]["portions"]:
        for part in (PARTS[1:] if por == "MRK" else ("hbo",)):
            m = {**miss.get(part, {}), **miss.get(por, {})}
            for a, b in PAIRS:
                if (a, part) not in lines or por not in steps[a]["portions"]: continue
                ks = [k for k in lines[(a, part)] if LS.portion(k.split(" ")[0], int(k.split(" ")[1].split(":")[0])) == por]
                dif = sum(lines[(a, part)][k][1] != lines[(b, part)][k][1] for k in ks)
                drows.append((por, part, f"{a}/{b}", len(ks), dif, f"{dif / len(ks):.4f}"))
                trows.append((por, part, f"{a}/{b}", len(ks), len(ks) - dif, f"{(len(ks) - dif) / len(ks):.4f}", jd(dict(sorted(m.items())))))
    LS.write_tsv(out / "differ.tsv", ["portion", "part", "pair", "verses", "differ", "share"], drows)
    LS.write_tsv(out / "thin.tsv", ["portion", "part", "pair", "verses", "equal", "share", "missing"], trows)
    # layout (8.5)
    for part in PARTS:
        depth = {r["clause"]: r["depth"] for r in pq.read_table(LB.K1 / part / "clauses.parquet", columns=["clause", "depth"]).to_pylist()}
        for (n, p), (W, _, _) in sorted(T.items()):
            if p != part: continue
            LS.write_tsv(out / "layout" / f"step{n}" / f"{part}.tsv", ["key", "clause", "depth", "line"], layout_rows(part, W, depth))
    # the sealed step sample (8.6)
    rng = random.Random(SEED); srows = []
    for kind in ("P", "F", "V", "A", "R"):
        ids = sorted((r["change"] for r in rows if r["kind"] == kind), key=lambda x: (int(x.split(":")[1]), x.split(":")[2], int(x.split(":")[3])))
        step_of = {r["change"]: r["step"] for r in rows}
        for x in (rng.sample(ids, 20) if len(ids) >= 20 else ids): srows.append(("change", kind, x, step_of[x]))
    for por in steps[LAST]["portions"]:
        st = 1 if por in steps[1]["portions"] else 2
        part = "heb_mod" if por == "MRK" else "hbo"
        ks = sorted(k for k in lines[(st, part)] if LS.portion(k.split(" ")[0], int(k.split(" ")[1].split(":")[0])) == por)
        for k in rng.sample(ks, 10): srows.append(("verse", por, k, st))
    LS.write_tsv(out / "sealed" / "step_sample.tsv", ["sample", "group", "id", "step"], srows)
    info = {"changes": dict(collections.Counter(f"{r['step']}:{r['part']}:{r['kind']}" for r in rows)),
            "applied_at_next_only": only_next, "step1_words": len(T[(1, "hbo")][0])}
    return info


def finish(src, out, sha, rel, repo, info):
    """README.md, GUIDE.md; extend sources.json, COLUMNS.md, build.json"""
    (out / "README.md").write_text(README, encoding="utf-8")
    shutil.copyfile(GUIDE_SRC, out / "GUIDE.md")
    sj = json.loads((src / "sources.json").read_text(encoding="utf-8"))
    ins = []                            # the level texts profiles.toml names, each (level, part) once
    named = sorted({(st["level"][part], part) for st in steps_from(out).values() if "level" in st for part in st["level"]})
    for lv, part in named:
        ins += [L2 / "texts" / lv / part / f for f in ("links.parquet", "pieces.parquet", "words.parquet")]
    ins += [L2 / "ops.parquet"]
    for part in PARTS:
        ins += [LB.K1 / part / f for f in ("words.parquet", "pieces.parquet", "clauses.parquet", "passages.parquet", "participants.tsv")]
    ins += [LB.K1 / "lexicon" / "lexemes.tsv", LB.DATA / "clauses-similar" / "hebrew.parquet",
            LB.DATA / "clauses-similar" / "tanakh-nt.parquet", LB.DATA / "clause-keys" / "2026-11-19" / "clause_keys.parquet"]
    for p in ins:                       # an entry an earlier stage wrote stays as it is (its sha256 must agree)
        if rel(p) in sj:
            if sj[rel(p)].get("sha256") != sha(p): raise SystemExit(f"stage 61: {rel(p)} changed since an earlier stage pinned it")
            continue
        e = {"sha256": sha(p), "read_for": "stage 61: " + ("the step texts" if "hebrew-levels" in str(p) else "the verse card")}
        if "clauses-similar" in str(p): e["kind"] = "vector neighbour table"
        sj[rel(p)] = e
    (out / "sources.json").write_text(json.dumps(sj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    col = (src / "COLUMNS.md").read_text(encoding="utf-8").split("\n# Columns (stage 61")[0]
    (out / "COLUMNS.md").write_text(col + COLUMNS_61, encoding="utf-8")
    bj = json.loads((src / "build.json").read_text(encoding="utf-8"))
    files = dict(bj["files"])
    for k in [k for k in files if k.split("/")[0] in ("texts", "lines", "layout") or k in STEP_FILES]: del files[k]
    for p in sorted(out.rglob("*")):
        r = p.relative_to(out)
        if p.is_file() and (r.parts[0] in ("texts", "lines", "layout") or str(r) in STEP_FILES + ("sources.json", "COLUMNS.md")):
            files[str(r)] = sha(p)
    bj["files"] = dict(sorted(files.items()))
    bj["code"] = dict(sorted({**bj["code"], **{c: sha(repo / c) for c in CODE61}}.items()))
    bj["sealed_steps"] = files["sealed/step_sample.tsv"]
    bj["stage61"] = {"entry": "shoresh/.venv/bin/python -I shoresh/macula/build_ladder.py --build pilot-1 --stage 61",
                     "card": "cd shoresh && .venv/bin/python -m macula.ladder_card <BOOK> <ch>:<v> --step N [--part P]",
                     "guide_from": rel(GUIDE_SRC), "notes": info}
    (out / "build.json").write_text(json.dumps(bj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return bj


README = """# The Hebrew ladder, pilot 1

Four steps of the same verses (SPEC-ladder, version 0.2): step 1 easiest, step 2 easy, step 3 more advanced, step 4
the real text. Scope: Jonah, Psalms 1-41, Isaiah 40-55 (steps 1-4), Ruth and Genesis 22-25 (steps 2-4), Mark in the
two Hebrew editions of Delitzsch (`heb_mod`) and Salkinson (`heb_scg`) (steps 2-4). Read `GUIDE.md` first; the columns
are in `COLUMNS.md`. Version 0.1 had five steps; its step 4 (R only) was dropped on 2026-11-24, and its step 5 is now
step 4.

- `profiles.toml`: what each step is (its switches and the level text it reads).
- `texts/step<N>/<part>/`: each step's words, pieces and links to the source pieces of build `k1`.
- `changes.parquet`: what changes from step N to step N+1 (the places to revise when climbing).
- `lines/`, `layout/`: plain verse lines and clause lines per step.
- `differ.tsv`, `thin.tsv`: how many verses differ (or are equal) between neighbouring steps.
- `banks/`, `chooser/`: Metzudat David's comments and Metzudat Zion's glosses, and the model's choice of the
  restating spans (basis `model`, credited in `sources.json` and `categories.toml`; no human check).
- The verse card: `cd shoresh && .venv/bin/python -m macula.ladder_card PSA 23:1 --step 2`.

Basis. Steps 2-4 are the rule texts of `hebrew-levels/pilot-2`; their pieces copied from the Hebrew editions keep
those editions' basis (often `model`, the editions' model parses). Step 1's commentator words rest on the model's
choice (basis `model` on their pieces and links). The lower steps are a Jewish reading (Metzudot, peshat), an aid
beside the real text: step 4 decides.

Metzudat David and Metzudat Zion: David and Yechiel Hillel Altschuler, Public Domain, Sefaria ("On Your Way").
"""

COLUMNS_61 = """
# Columns (stage 61: the ladder)

## profiles.toml

The four steps as data (SPEC-ladder 0.2, 8.1): `step`, `name`, `switches`, `level` per part (step 1: `base_level`),
`portions`; `[missing]` names the switches a part or portion has no source for. Derived (it is the specification's).

## texts/step<N>/<part>/ (N 1-4; step 1 `hbo` only, JON, PSA 1-41, ISA 40-55; step 4 the real text)

Steps 2-4: hebrew-levels/pilot-2 `texts/<level>/<part>/` of the level `profiles.toml` names, copied row for row
(`words`, `pieces`, `links`; columns as there, SPEC-levels 7.2 plus `basis`). Step 1: the step-2 text (`z_r_a`) with
every accepted splice of `chooser/choices_model.parquet` applied (SPEC-ladder 7.4, 8.2); `t` renumbered from 1 in text
order, `w` the position in the step's verse.

- `words.parquet`: t, book, chapter, verse, w, text, after, sentence, clause (linked), op. A commentator word: `text`
  as the bank writes it (unpointed), `after` `" "` (the last of a splice: the replaced span's last word's), `sentence`
  and `clause` the span's first word's, `op` the choice id (= the comment id).
- `pieces.parquet`: t, n, text, kind, lexeme, class, marks, who, who_basis, basis, op. A commentator word has one
  piece: `kind` `comment`, `lexeme` `class` `who` `who_basis` `""`, `marks` `{}`, `basis` `model`, `op` the choice id.
- `links.parquet`: t, n, s, agree, agree_model, other, how, basis, s_n; step 1 adds `comment`, `i`. A commentator word
  links to every source piece of the span it replaces: `how` `comment`, `basis` `model`, `agree` null, `agree_model`
  1, `comment` the comment id, `i` the comment token it was written from. On every other row `comment` is `""` and
  `i` null.

## changes.parquet (rule CH, SPEC-ladder 8.3; all derived except as `basis_here` says)

| column | basis | meaning |
|---|---|---|
| change | derived | `ch:<step>:<part>:<n>`, sorted by (step, part, the first source piece of `src`, kind, source) |
| step, part, key | derived | the change is what a drafter revises going from `step` to `step`+1 |
| kind | derived | `P`, `F` (step 1: the choice's `splice_kind`), `V`, `A`, `R` (the op's switch) |
| source | derived | the choice id (step 1) or the pilot-2 op id (the op at `step`'s level; where only the next level applied it, that op) |
| words_here | derived | json: the step words `t` the change covers (the op's `draft_t`; step 1: the commentator words) |
| words_next | derived | json: the step-(s+1) words it becomes: the next level op's `draft_t`, else the next step's words that link (copy, replace) to the source pieces `words_here` link to (copy, replace); `[]` for an insertion (A, and R's `r_subject`) |
| src | derived | json `[[t, n], ...]`: every source piece the words of both sides link to |
| text_here, text_next | derived | the words' `text` joined by one space |
| under_splice | derived | step 1: the pilot-2 op ids that wrote a word inside the replaced span; else `[]` |
| basis_here | derived | `model` for a P/F change (it rests on the model's choice), else `derived` |

Replay (the exit check): the step-(s+1) verse with each change put back gives the step-s verse; an insertion goes
after the next step's word that links to the change's `src` piece (after the words already put there).

## lines/step<N>/<part>.<form>.tsv

Rule IN of SPEC-levels 7.3 (`cons`, `point`) on the step's words. Header key, part, step, form, scoring_closed
(SPEC-levels 7.4), changed (the `point` line differs from step N+1's; false at step 4), line. Derived.

## differ.tsv, thin.tsv

`differ.tsv`: portion, part, pair (`1/2`, `2/3`, `3/4`), verses, differ (verses whose `point` line differs), share.
`thin.tsv`: portion, part, pair, verses, equal (verses whose `point` line is equal at both steps), share, missing
(json: the switches `[missing]` of profiles.toml names for the part and the portion, with the reason). Derived.

## layout/step<N>/<part>.tsv

key, clause (the k1 clause key of the word; a commentator word: the span's first word's), depth (k1 `clauses.depth`;
empty where the word has no clause), line (one row per run of consecutive words of one clause in the verse; `hbo`: the
words' `text` + `after`, so the lines of a verse joined with nothing give its raw line; the editions: `text` joined by
one space, the lines joined by one space). Derived (clause and depth given/linked from k1).

## sealed/step_sample.tsv

sample (`change`, `verse`), group (the change kind or the portion), id (change key or verse key), step. Drawn with
`random.Random("ladder-2026-11-24-steps")` on one generator: 20 changes per kind in the order P, F, V, A, R (all where
fewer exist), the ids sorted by (step, part, number); then 10 verses per portion in the order of profiles.toml (step 1
where the portion has it, else step 2; MRK in `heb_mod`). Derived. For stage 63.

## The verse card (`macula/ladder_card.py`)

Keys as SPEC-ladder 9.1. `text.words[].witness`: the comment id for a commentator word, the gloss id for a word V
wrote (Metzudat Zion), else `""`. `similar`: the join of 9.2 below; `reason` `no_join` where a clause finds no id.
`sources`: per key, the dataset, path, sha256 (sources.json for inputs, build.json for the build's own files) and basis.

**The join of 9.2.** A `hbo` clause key `cl:o<12 digits>:<n>` maps to the MACULA clause id `<12 digits>`; it joins when
that id is a `clause` of `clause-keys/2026-11-19/clause_keys.parquet` with `lang` `hbo`; then `tanakh` = the `other`
ids of `clauses-similar/hebrew.parquet` and `nt` = the `nt_clause` ids of `tanakh-nt.parquet` for that `clause_key`,
the top 5 by `rank`. A Mark clause of `heb_mod` or `heb_scg` maps through its `from_clause` `cl:n<11 digits>:<n>` to the
Greek id `<11 digits>` (`lang` `grc` in clause-keys); `tanakh` = the `clause_key` of the rows of `tanakh-nt.parquet` whose
`nt_clause` is that id, best 5 by (`rank`, then `score` descending, then id); `nt` = `[]` (no Greek-to-Greek table is
read).
"""
