"""Stage 62 checks of the Hebrew ladder (SPEC-ladder 10, the English aid), called by validate_ladder.py --upto 62.

Imports nothing from the builders: the wanted (verse, step) set, same_as and hebrew_sha are recomputed here from the
step lines (lines/step<N>/hbo.point.tsv); the English is read from english/raw and english/english_model.parquet.
Standalone (the tamper test):
    shoresh/.venv/bin/python -I shoresh/macula/validate_ladder62.py --dir DIR [--no-rebuild]
"""
import argparse, collections, hashlib, json, re, subprocess, sys, tomllib
from pathlib import Path

import pyarrow.parquet as pq

MAC = Path(__file__).resolve().parent
REPO = MAC.parent.parent
PORTIONS = ["JON", "PSA1-41", "ISA40-55", "RUT", "GEN22-25"]
STEP1 = {"JON", "PSA1-41", "ISA40-55"}
MODEL = "claude-opus-5-5"
DATE = "2026-11-24"
CREDIT = ("English aid by the model claude-opus-5-5 (the stage 62 session of the Hebrew ladder pilot 1, 2026-11), "
          "translated from the Hebrew of each step only, with no English Bible; an aid beside the Hebrew, not a "
          "translation of record; no human check.")
COLS = [("key", "string"), ("portion", "string"), ("step", "int64"), ("text_model", "string"), ("same_as", "int64"),
        ("hebrew_sha", "string"), ("aid", "bool")]
HEB = re.compile(r"[֐-׿]")
LATIN = re.compile(r"[A-Za-z]")
WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
TEXT_COLS = {"body", "core", "fit_form", "lemma", "text", "written", "text_here", "text_next", "line", "before", "after"}
SHINGLE = 6
CODE = ["shoresh/macula/build_ladder.py", "shoresh/macula/ladder_stage62.py"]
LAST = 4                                            # four steps since SPEC-ladder 0.2; step 4 is the real text
RAW_OF = {1: (1,), 2: (2,), 3: (3, 4), 4: (5,)}     # rule RN (10.2): the raw rows keep the five steps of 0.1
RAW_LEVEL = {2: "z_r_a", 3: "zr_r", 4: "r", 5: "l0"}  # the pilot-2 level each old (raw) step 2-5 read for hbo
L2 = MAC / "data" / "hebrew-levels" / "pilot-2"
OLD = MAC / "data" / "hebrew-ladder" / "trash-2026-11-24" / "pilot-1-five-steps" / "english" / "english_model.parquet"


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def tsv(p):
    L = p.read_text(encoding="utf-8").split("\n")
    h = L[0].split("\t")
    return h, [dict(zip(h, l.split("\t"))) for l in L[1:] if l]


def por(key):
    b, cv = key.split(" "); c = int(cv.split(":")[0])
    if b in ("JON", "RUT"): return b
    if b == "PSA" and 1 <= c <= 41: return "PSA1-41"
    if b == "ISA" and 40 <= c <= 55: return "ISA40-55"
    if b == "GEN" and 22 <= c <= 25: return "GEN22-25"
    return ""


def steps(key):
    return list(range(1, LAST + 1)) if por(key) in STEP1 else list(range(2, LAST + 1))


def shingles(s):
    w = [x.lower() for x in WORD.findall(s)]
    return {" ".join(w[i:i + SHINGLE]) for i in range(len(w) - SHINGLE + 1)}


def skip(r):
    return r.parts[0] in ("english", "cache") or r.parts[0].startswith(("trash", "rebuild")) or r.name == "VALIDATION.md"


class Check62:
    def __init__(self, d, cond, say):
        self.d, self.cond, self.say = d, cond, say

    def run(self, rebuild=True):
        cond, say, d = self.cond, self.say, self.d
        say("\n# Stage 62: the English aid\n")
        S, order = {}, []
        for s in range(1, LAST + 1):
            _, rows = tsv(d / "lines" / f"step{s}" / "hbo.point.tsv")
            S[s] = {r["key"]: r["line"] for r in rows}
            if s == LAST: order = [r["key"] for r in rows]
        keys = [k for k in order if por(k)]
        want = [(k, s) for k in keys for s in sorted(steps(k), reverse=True) if s == LAST or S[s][k] != S[s + 1][k]]
        W = set(want)
        say(f"      scope: {len(keys)} verses of {len(PORTIONS)} portions (of {len(order)} step-4 verses of hbo); "
            f"{len(W)} texts wanted (step 4 and each lower step whose `point` line differs from the step above)")
        for s in range(1, LAST + 1):
            say(f"        step {s}: {sum(1 for x in W if x[1] == s)} wanted")

        say("\n## english/raw (the session's texts as written, in the five-step numbering of SPEC-ladder 0.1)")
        Rraw = {}; bad = []; R = Rraw
        for po in PORTIONS:
            p = d / "english" / "raw" / f"{po}.tsv"
            h, rows = tsv(p)
            if h != ["key", "step", "text"]: bad.append((po, "header"))
            for r in rows:
                x = (r["key"], int(r["step"]))
                if x in R: bad.append((po, "twice", x))
                if por(r["key"]) != po: bad.append((po, "portion", x))
                R[x] = r["text"]
            say(f"      {po}: {len(rows)} rows")
        cond("raw files: header key, step, text; each row in its portion's file; no (verse, step) twice", not bad, f"{bad[:4]}")
        # the Hebrew the session translated (its input, kept in cache/english/input)
        H = {}
        for p in sorted((d / "cache" / "english" / "input").glob("*/*.txt")):
            bk = None
            for l in p.read_text(encoding="utf-8").split("\n"):
                if l.startswith("# "): bk = l[2:]
                elif l.startswith("@"): vv = l[1:]
                elif l.strip():
                    a, line = l.split(" ", 1); H[(f"{bk}:{vv}", int(a))] = line
        noh = [x for x in Rraw if x not in H]
        cond("every raw row has the Hebrew line the session translated (cache/english/input)", not noh, f"{len(H)} input lines; raw rows without {len(noh)} {noh[:3]}")
        # rule RN with EN-STALE (2026-11-25), recomputed: a step's text from the first raw step of RAW_OF that has a row
        # whose session Hebrew equals the step's line now; else the step is untranslated (aid false)
        R, src_of = {}, {}
        for k, s in want:
            o = next((o for o in RAW_OF[s] if (k, o) in Rraw and H.get((k, o)) == S[s][k]), None)
            if o is not None: R[(k, s)] = Rraw[(k, o)]; src_of[(k, s)] = o
        used = {(k, o) for (k, s), o in src_of.items()}
        rest = [x for x in Rraw if x not in used]
        dropped = [x for x in rest if x[1] == 4]
        miss = [x for x in want if x not in R]
        stale = [x for x in rest if x[1] != 4]
        cond("rule RN with EN-STALE: every wanted (verse, step) takes at most one raw text, translated from the Hebrew that stands there now",
             all(H.get((k, o)) == S[s][k] for (k, s), o in src_of.items()) and all(1 <= x[1] <= 5 for x in Rraw),
             f"{len(Rraw)} raw rows -> {len(R)} texts for {len(W)} wanted; untranslated (the Hebrew changed after the session) {len(miss)} {miss[:3]}; "
             f"raw rows of steps 1-3, 5 not used {len(stale)} {stale[:3]}")
        tk = collections.Counter((s, o) for (k, s), o in src_of.items())
        say(f"      taken (step <- raw step): " + ", ".join(f"{s}<-{o} {n}" for (s, o), n in sorted(tk.items()))
            + f"; raw rows of old step 4 not used: {len(dropped)} (of {sum(1 for x in Rraw if x[1] == 4)})")
        say(f"      untranslated by step: " + ", ".join(f"{s} {n}" for s, n in sorted(collections.Counter(s for _, s in miss).items())))
        self.rn = {"raw": len(Rraw), "taken": dict(tk), "dropped": len(dropped), "untranslated": len(miss)}
        hb = [(k, s, o) for (k, s), o in src_of.items() if H.get((k, o)) != S[s][k]]
        cond("every kept text stands on the Hebrew it was translated from: the session's input line equals this step's line",
             not hb, f"{len(src_of)} texts compared; differ {len(hb)} {hb[:3]}")
        if OLD.is_file():
            old = {(r["key"], r["step"]): r["hebrew_sha"] for r in pq.read_table(OLD).to_pylist()}
            rf = d / "english" / "raw" / "refills.json"            # texts of a later refill session are not in the old build
            refilled = {(k, s) for r in (json.loads(rf.read_text(encoding="utf-8")) if rf.is_file() else []) for k, s in r["rows"]}
            ob = [(k, s, o) for (k, s), o in src_of.items() if (k, s) not in refilled
                  and old.get((k, o)) != hashlib.sha256(S[s][k].encode("utf-8")).hexdigest()]
            cond("against the five-step build (trash-2026-11-24/pilot-1-five-steps): every kept text's hebrew_sha there equals this step's line (texts of english/raw/refills.json apart)",
                 not ob, f"{len(src_of) - len(refilled)} texts compared, {len(refilled)} refilled apart; differ {len(ob)} {ob[:3]}")
        else:
            cond("against the five-step build (trash-2026-11-24/pilot-1-five-steps)", None, f"skipped: {OLD} absent")
        heb = [x for x, t in Rraw.items() if HEB.search(t)]
        noen = [x for x, t in Rraw.items() if not t.strip() or not LATIN.search(t) or t != " ".join(t.split())]
        cond("no Hebrew letter in the English; every text non-empty, in Latin letters, single-spaced", not heb and not noen,
             f"Hebrew in {len(heb)} {heb[:3]}; empty or odd {len(noen)} {noen[:3]}")

        say("\n## english/english_model.parquet")
        t = pq.read_table(d / "english" / "english_model.parquet")
        cond("columns and types as the README (model values only in text_model)",
             [(f.name, str(f.type)) for f in t.schema] == COLS, ", ".join(f.name for f in t.schema))
        rows = t.to_pylist()
        exp_keys = [(k, s) for k in keys for s in steps(k)]
        got_keys = [(r["key"], r["step"]) for r in rows]
        cond("one row per verse and step it has, in text order (steps 1-4 in JON, PSA1-41, ISA40-55; 2-4 in RUT, GEN22-25); no Mark row",
             got_keys == exp_keys and not any(r["key"].startswith("MRK") for r in rows),
             f"{len(rows)} rows for {len(exp_keys)} expected ({len(keys)} verses)")
        byk = {(r["key"], r["step"]): r for r in rows}
        b1 = b2 = b3 = b4 = 0
        for (k, s), r in byk.items():
            up0 = s if (k, s) in W else next((u for u in range(s + 1, LAST + 1) if (k, u) in W), None)
            if r["portion"] != por(k) or r["aid"] is not ((k, up0) in R): b1 += 1
            if r["hebrew_sha"] != hashlib.sha256(S[s][k].encode("utf-8")).hexdigest(): b2 += 1
            if (k, s) in W:
                if r["text_model"] != R.get((k, s), "") or r["same_as"] is not None: b3 += 1
            else:
                up = next((u for u in range(s + 1, LAST + 1) if (k, u) in W), None)
                if r["text_model"] != "" or r["same_as"] != up: b4 += 1
        cond("portion recomputed; aid true where an English text stands for the row (own or same_as), false where untranslated (EN-STALE)", b1 == 0,
             f"{b1} differ; aid false on {sum(1 for r in rows if r['aid'] is not True)} rows")
        cond("hebrew_sha recomputed: sha256 of the step's `point` line", b2 == 0, f"{b2} differ")
        cond("text_model equals the raw text rule RN names where the Hebrew differs from the step above (and step 4), '' where untranslated; same_as null there",
             b3 == 0, f"{b3} differ")
        cond("elsewhere text_model empty and same_as the nearest step above with a text", b4 == 0, f"{b4} differ")

        def eng(k, s):
            r = byk[(k, s)]
            return r["text_model"] if r["same_as"] is None else eng(k, r["same_as"])
        eq_bad = ne_own = same_text = 0; pairs = 0
        for k in keys:
            st = steps(k)
            for s in st[:-1]:
                pairs += 1
                if S[s][k] == S[s + 1][k]:
                    if eng(k, s) != eng(k, s + 1): eq_bad += 1
                else:
                    if byk[(k, s)]["same_as"] is not None: ne_own += 1
                    elif eng(k, s) == eng(k, s + 1): same_text += 1
        cond("where two neighbouring steps have equal Hebrew, the English is equal", eq_bad == 0, f"{pairs} neighbour pairs; {eq_bad} differ")
        cond("where they differ, the lower step has its own text", ne_own == 0, f"{ne_own} without; "
             f"{same_text} own texts happen to equal the English of the step above (allowed; listed in the report)")
        ab = 0; apairs = 0; untr = []
        for k in keys:
            st = steps(k)
            for i, a in enumerate(st):
                for b in st[i + 1:]:
                    if S[a][k] == S[b][k]:
                        apairs += 1
                        if byk[(k, a)]["aid"] is not True or byk[(k, b)]["aid"] is not True:
                            untr.append((k, a, b)); continue     # EN-STALE: an untranslated step has no English
                        if eng(k, a) != eng(k, b): ab += 1
        cond("the English of equal Hebrew is equal: any two steps of a verse whose `point` lines are equal have the same English (both translated)",
             ab == 0, f"{apairs} pairs of steps with equal Hebrew (any distance); {ab} differ; "
             f"{len(untr)} pairs with an untranslated step (EN-STALE) not compared {untr[:4]}")
        say("      portion x step: texts / same_as")
        cnt = collections.Counter((r["portion"], r["step"], r["same_as"] is None) for r in rows)
        for po in PORTIONS:
            say(f"        {po}: " + ", ".join(f"step {s} {cnt[(po, s, True)]}/{cnt[(po, s, False)]}" for s in range(1, LAST + 1)
                                            if cnt[(po, s, True)] + cnt[(po, s, False)]))
        say(f"      total: {len(rows)} rows, {sum(1 for r in rows if r['same_as'] is None)} texts, "
            f"{sum(1 for r in rows if r['same_as'] is not None)} same_as; "
            f"{sum(len(WORD.findall(x)) for x in R.values())} English words in use ({sum(len(WORD.findall(x)) for x in Rraw.values())} in the raw files)")

        say("\n## No English anywhere else in the build")
        hits = []; nfiles = nvals = 0
        def walk(f, o, k=None):
            nonlocal nvals
            if isinstance(o, dict):
                for kk, v in o.items(): walk(f, v, kk)
            elif isinstance(o, list):
                for v in o: walk(f, v, k)
            elif isinstance(o, str) and k in TEXT_COLS:
                nvals += 1
                if LATIN.search(o): hits.append((f, k, o[:30]))
        SH = set()
        for x in Rraw.values(): SH |= shingles(x)
        leak = []
        for p in sorted(d.rglob("*")):
            r = p.relative_to(d)
            if not p.is_file() or skip(r): continue
            f = str(r); nfiles += 1
            if p.suffix == ".parquet":
                tb = pq.read_table(p).to_pylist()
                for row in tb: walk(f, row)
                blob = "\n".join(str(v) for row in tb for v in row.values() if isinstance(v, str))
            else:
                blob = p.read_text(encoding="utf-8", errors="replace")
                if p.suffix == ".tsv":
                    h, rs = tsv(p)
                    for row in rs: walk(f, row)
                elif p.suffix == ".jsonl":
                    for l in blob.splitlines():
                        if l.strip(): walk(f, json.loads(l))
            if p.suffix in (".parquet", ".tsv", ".jsonl", ".json", ".md", ".toml", ".txt"):
                common = shingles(blob) & SH
                if common: leak.append((f, len(common), sorted(common)[:2]))
        cond("the Latin-letter check passes on every text column of every other table (parquet, tsv, jsonl; "
             + ", ".join(sorted(TEXT_COLS)) + ")", not hits, f"{nfiles} files, {nvals} text values; {len(hits)} with Latin letters {hits[:3]}")
        cond(f"no run of {SHINGLE} words of the English aid appears in any other file of the build", not leak,
             f"{len(SH)} distinct {SHINGLE}-word runs; {len(leak)} files hit {leak[:3]}")
        cin = [str(p.relative_to(d)) for p in (d / "cache" / "english").rglob("*") if p.is_file() and LATIN.search(
            "\n".join(l for l in p.read_text(encoding="utf-8").splitlines() if not l.startswith("#")))]
        cond("the session input (cache/english/input) holds Hebrew lines only (headers aside)", not cin, f"{len(cin)} files with Latin {cin[:3]}")

        say("\n## Credit, sources, build.json")
        sj = json.loads((d / "sources.json").read_text(encoding="utf-8"))
        bj = json.loads((d / "build.json").read_text(encoding="utf-8"))
        s62 = bj.get("stage62", {}); spend = s62.get("spend_usd")
        ok = True
        for po in PORTIONS:
            q = [k for k in sj if k.startswith("shoresh/macula/data/hebrew-ladder/") and k.endswith(f"/english/raw/{po}.tsv")]
            e = sj[q[0]] if len(q) == 1 else {}      # by suffix, so a --dir copy (the tamper test) finds its build's entry
            ok = ok and e.get("sha256") == sha(d / "english" / "raw" / f"{po}.tsv") and e.get("basis") == "model" \
                and e.get("credit") == CREDIT and e.get("model") == MODEL and e.get("session") == "stage 62" \
                and e.get("date") == DATE and e.get("human_check") == "none" and e.get("aid") is True and e.get("spend_usd") == spend \
                and "SPEC-ladder 0.1" in e.get("raw_steps", "")
        cond("sources.json: the raw files with sha256, basis model, credit, model, session, date, spend, no human check, aid, raw numbering", ok, f"spend USD {spend}")
        cr = tomllib.loads((d / "categories.toml").read_text(encoding="utf-8")).get("credit_english", {})
        cond("categories.toml [credit_english]: credit, model, session, date, human check false, spend, aid",
             cr == {"english": CREDIT, "english_model": MODEL, "english_session": "stage 62", "english_date": DATE,
                    "english_human_check": False, "english_spend_usd": spend, "english_aid": True}, f"{sorted(cr)}")
        rd = (d / "english" / "README.md").read_text(encoding="utf-8")
        cond("english/README.md: the credit, the spend, what it is and is not, the column table",
             CREDIT in rd and f"USD {json.dumps(spend)}" in rd and "What it is not" in rd
             and all(f"| {c} |" in rd for c, _ in COLS), "")
        fs = ["english/english_model.parquet", "english/README.md", "sources.json", "categories.toml"] + [f"english/raw/{po}.tsv" for po in PORTIONS]
        fb = [k for k in fs if bj.get("files", {}).get(k) != sha(d / k)]
        cond("build.json lists every stage-62 file with its sha256", not fb, f"{len(fs)} files; differ {fb}")
        cond("build.json: stage62 entry (model, session, date, credit, spend, no human check, aid); code shas equal the code",
             s62.get("model") == MODEL and s62.get("credit") == CREDIT and s62.get("session") == "stage 62" and s62.get("date") == DATE
             and s62.get("human_check") == "none" and s62.get("aid") is True and all(c in bj.get("code", {}) for c in CODE)
             and all(sha(REPO / c) == v for c, v in bj.get("code", {}).items()), f"{len(bj.get('code', {}))} code files")

        if not rebuild:
            cond("two --check rebuilds give the same sha256", None, "skipped (--no-rebuild)"); return
        base = Path("/tmp/claude-1000/source-examples/ladder62"); n = 1
        while (base / f"rebuild-{n}").exists(): n += 1
        names = ["english/english_model.parquet", "english/README.md", "categories.toml", "sources.json", "build.json"]
        sums = []
        for k in (n, n + 1):
            o = base / f"rebuild-{k}"
            subprocess.run([sys.executable, "-I", str(MAC / "build_ladder.py"), "--build", d.name, "--stage", "62", "--check",
                            "--spend", str(spend), "--out", str(o)], check=True, capture_output=True)
            sums.append({x: sha(o / x) for x in names})
        mine = {x: sha(d / x) for x in names}
        diff = [x for x in names if not (sums[0][x] == sums[1][x] == mine[x])]
        cond("two --check rebuilds give the same sha256 for the parquet, README, categories.toml, sources.json, build.json"
             " (and equal the build)", not diff, f"differ: {diff} (scratch rebuild-{n}, rebuild-{n + 1})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True); ap.add_argument("--no-rebuild", action="store_true")
    a = ap.parse_args()
    res = []
    def say(s=""): print(s)
    def cond(name, ok, detail):
        tag = "SKIP" if ok is None else ("PASS" if ok else "FAIL"); res.append(tag)
        print(f"  [{tag}] {name}: {detail}")
    Check62(Path(a.dir), cond, say).run(rebuild=not a.no_rebuild)
    c = collections.Counter(res)
    print(f"\nPASS {c['PASS']}, SKIP {c['SKIP']}, FAIL {c['FAIL']}")
    sys.exit(1 if c["FAIL"] else 0)


if __name__ == "__main__":
    main()
