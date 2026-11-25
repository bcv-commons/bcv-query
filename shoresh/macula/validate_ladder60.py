"""Stage 60 checks of the Hebrew ladder (SPEC-ladder 7.5), called by validate_ladder.py --upto 60.

Imports nothing from the builders: the chooser input, rule SP, the step-1 splice and the counts are recomputed here
from the bank, k1 and the step-2 text. It hashes sealed/chooser_sample.tsv (bytes only) and prints nothing of it.
"""
import collections, hashlib, json, re, subprocess, sys, tomllib, unicodedata as ud
from pathlib import Path

import pyarrow.parquet as pq

MAC = Path(__file__).resolve().parent
REPO = MAC.parent.parent
DATA = MAC / "data"
K1 = DATA / "source-examples" / "k1"
L2 = DATA / "hebrew-levels" / "pilot-2" / "texts" / "z_r_a" / "hbo"
BOOKS = ("JON", "PSA", "ISA")
KINDS = ("restates", "restates_adds", "explains")
HEAD = ["comment", "kind", "c_from", "c_to", "v_from", "v_to"]
CREDIT = ("Kind and spans chosen by the model claude-opus-5-5 (the stage 60 session of the Hebrew ladder pilot 1, "
          "2026-11), from Metzudat David's comments and the Masoretic text; no human check.")
MODEL = "claude-opus-5-5"
COLS = [("choice", "string"), ("key", "string"), ("portion", "string"), ("kind_model", "string"),
        ("c_from_model", "int64"), ("c_to_model", "int64"), ("v_from_model", "int64"), ("v_to_model", "int64"),
        ("check", "string"), ("refusal", "string"), ("figure", "bool"), ("splice_kind", "string")]
FIN = str.maketrans("ךםןףץ", "כמנפצ")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def cons(s):
    return "".join(c for c in ud.normalize("NFD", s or "") if 0x05D0 <= ord(c) <= 0x05EA).translate(FIN)


def portion(book, ch):
    return {"JON": "JON"}.get(book) or ("PSA1-41" if book == "PSA" and ch <= 41 else
                                        "ISA40-55" if book == "ISA" and 40 <= ch <= 55 else "")


FIGURE = [x.split() for x in ("מליצה", "משל", "דרך השאלה", "לשון השאלה")]     # rule FIG's `figure` phrases (SPEC-ladder 4.3)


def fig_in_span(body, cf, ct, lead=4):
    """FIG-SPAN (OPEN-ladder 12) recomputed: a figure phrase overlaps the span [cf, ct] or the 4 tokens before it.
    body: [(i, text without trailing punctuation)] of the comment's body tokens in order. A phrase's first word may
    carry one prefix letter of ובהכלש."""
    body = sorted(body)
    def is_(tok, w, first): return tok == w or (first and len(tok) > 1 and tok[0] in "ובהכלש" and tok[1:] == w)
    for ph in FIGURE:
        for k in range(len(body) - len(ph) + 1):
            if all(is_(body[k + j][1], ph[j], j == 0) for j in range(len(ph))):
                if body[k][0] <= ct and body[k + len(ph) - 1][0] >= cf - lead: return True
    return False


def ival(s):
    s = s.strip()
    if not s: return None
    return int(s) if s.isdigit() else "bad"


class Check60:
    def __init__(self, d, cond, say):
        self.d, self.cond, self.say = d, cond, say

    # ---- the input, recomputed -------------------------------------------------------------------------------------
    def expected_inputs(self):
        d = self.d
        P = [r for r in pq.read_table(d / "banks" / "paraphrase.parquet").to_pylist() if r["in_pilot"]]
        keys = {r["key"] for r in P}; want = {r["comment"] for r in P}
        T = collections.defaultdict(list)
        for r in pq.read_table(d / "banks" / "paraphrase_tokens.parquet").to_pylist():
            if r["comment"] in want: T[r["comment"]].append(r)
        s5 = collections.defaultdict(list); wof = {}
        k1 = pq.read_table(K1 / "hbo" / "words.parquet", columns=["t", "book", "chapter", "verse", "w", "text"]).to_pylist()
        for r in sorted(k1, key=lambda r: r["t"]):
            k = f"{r['book']} {r['chapter']}:{r['verse']}"
            if k in keys: s5[k].append({"w": r["w"], "text": r["text"]}); wof[r["t"]] = r["w"]
        src = collections.defaultdict(set)
        for l in pq.read_table(L2 / "links.parquet", columns=["t", "s"]).to_pylist():
            if l["s"] in wof: src[l["t"]].add(wof[l["s"]])
        s2 = collections.defaultdict(list); nosrc = 0
        for r in sorted(pq.read_table(L2 / "words.parquet", columns=["t", "book", "chapter", "verse", "text"]).to_pylist(), key=lambda r: r["t"]):
            k = f"{r['book']} {r['chapter']}:{r['verse']}"
            if k not in keys: continue
            if not src[r["t"]]: nosrc += 1; continue
            s2[k].append({"w": min(src[r["t"]]), "text": r["text"]})
        anch = [r for r in P if r["anchor_state"] == "anchored"]
        byv = collections.defaultdict(list)
        for r in anch: byv[r["key"]].append(r)
        exp = collections.defaultdict(list)
        for r in anch:
            exp[r["book"]].append({
                "comment": r["comment"], "key": r["key"], "verse_step2": s2[r["key"]], "verse_step5": s5[r["key"]],
                "anchor": {"anchor_w_from": r["anchor_w_from"], "anchor_w_to": r["anchor_w_to"], "anchor_tier": r["anchor_tier"]},
                "lemma": r["lemma"],
                "tokens": [{"i": t["i"], "written": t["written"], "part": t["part"]} for t in sorted(T[r["comment"]], key=lambda t: t["i"])],
                "markers": json.loads(r["markers"]),
                "others": [{"comment": x["comment"], "w_from": x["anchor_w_from"], "w_to": x["anchor_w_to"]}
                           for x in byv[r["key"]] if x["comment"] != r["comment"]]})
        return P, exp, nosrc

    # ---- rule SP, recomputed ---------------------------------------------------------------------------------------
    @staticmethod
    def rule_sp(objs, dec):
        acc = collections.defaultdict(list); out = {}
        for o in objs:
            x = dec[o["comment"]]; kind = x[1]; cf, ct, vf, vt = (ival(v) for v in x[2:6])
            body = {t["i"] for t in o["tokens"] if t["part"] == "body"}
            cite = {t["i"] for t in o["tokens"] if t["part"] == "cite"}
            ws = {w["w"] for w in o["verse_step5"]}
            r = ""
            if kind not in KINDS: r = "bad_kind"
            elif "bad" in (cf, ct, vf, vt) or (cf is None) != (ct is None) or (vf is None) != (vt is None): r = "bad_span"
            elif cf is not None and (cf > ct or not all(i in body for i in range(cf, ct + 1)) or any(cf <= i <= ct for i in cite)): r = "bad_span"
            elif vf is not None and (vf > vt or vf not in ws or vt not in ws): r = "bad_span"
            elif kind == "explains" and (cf is not None or vf is not None): r = "spans_for_explains"
            elif kind != "explains" and (cf is None or vf is None): r = "no_spans"
            elif kind != "explains":
                A = acc[o["key"]]
                if any(vf <= a[1] and vt >= a[0] for a in A): r = "overlap"
                elif any(vf < a[0] for a in A): r = "order"
                elif not " ".join(t["written"] for t in o["tokens"] if cf <= t["i"] <= ct).split(): r = "empty_written"
            chk = "refused" if r else ("no_splice" if kind == "explains" else "accepted")
            if chk == "accepted": acc[o["key"]].append((vf, vt, cf, ct, o["comment"]))
            out[o["comment"]] = (chk, r)
        return out, acc

    def run(self, rebuild=True):
        cond, say, d = self.cond, self.say, self.d
        say("\n# Stage 60: the chooser\n")
        say("## Input (7.2), recomputed from the bank, k1 and the step-2 text")
        P, exp, nosrc = self.expected_inputs()
        objs = []; same = True
        for b in BOOKS:
            got = [json.loads(l) for l in (d / "chooser" / "input" / f"{b}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
            same = same and got == exp[b]; objs += got
            say(f"      {b}: {len(got)} input objects")
        cond("chooser/input/<BOOK>.jsonl equal the input recomputed here", same, f"{len(objs)} objects; step-2 words without a k1 source: {nosrc}")
        unanch = [r for r in P if r["anchor_state"] != "anchored"]
        say(f"      step-1 scope: {len(P)} comments, {len(P) - len(unanch)} anchored, {len(unanch)} not anchored:")
        for r in unanch: say(f"        {r['comment']} ({r['anchor_state']})")

        say("\n## Decisions (the model's raw output)")
        dec = {}; hdr = True; dup = 0; shape = 0
        for b in BOOKS:
            L = (d / "chooser" / "decisions" / f"{b}.tsv").read_text(encoding="utf-8").splitlines()
            hdr = hdr and L[0].split("\t") == HEAD
            for l in L[1:]:
                x = l.split("\t")
                if len(x) != 6: shape += 1; continue
                if x[0] in dec: dup += 1
                dec[x[0]] = x
        ids = [o["comment"] for o in objs]
        miss = [c for c in ids if c not in dec]; extra = sorted(set(dec) - set(ids))
        cond("decisions: header as 7.3, six fields a row, no comment twice", hdr and not dup and not shape, f"{dup} twice, {shape} bad rows")
        cond("one choice per anchored comment of the step-1 scope, none else", not miss and not extra and len(dec) == len(ids),
             f"{len(dec)} choices for {len(ids)} anchored comments; missing {len(miss)}, extra {len(extra)}")
        own = sum(1 for x in dec.values() if any(v.strip() and not v.strip().isdigit() for v in x[2:6]))
        cond("every kind one of three", all(x[1] in KINDS for x in dec.values()), dict(collections.Counter(x[1] for x in dec.values())))
        cond("the decisions hold kind codes and integers only (no word of the model's own)", own == 0, f"{own} rows with other values")

        say("\n## choices_model.parquet")
        t = pq.read_table(d / "chooser" / "choices_model.parquet")
        cond("columns and types as 7.3 (model values only in the _model columns)",
             [(f.name, str(f.type)) for f in t.schema] == COLS, ", ".join(f.name for f in t.schema))
        rows = t.to_pylist(); byc = {r["choice"]: r for r in rows}
        sp, acc = self.rule_sp(objs, dec)
        self.fig_toks = collections.defaultdict(list)
        for x in pq.read_table(d / "banks" / "paraphrase_tokens.parquet", columns=["comment", "i", "text", "part"]).to_pylist():
            if x["part"] == "body": self.fig_toks[x["comment"]].append((x["i"], re.sub(r"[.:,;]+$", "", x["text"])))
        bank = {r["comment"]: r for r in P}
        bad_row = bad_sp = 0; bad_list = []
        for o in objs:
            c = o["comment"]; r = byc.get(c); x = dec[c]
            if r is None: bad_row += 1; continue
            vals = [ival(v) for v in x[2:6]]
            vals = [v if isinstance(v, int) else None for v in vals]
            if (r["kind_model"], r["c_from_model"], r["c_to_model"], r["v_from_model"], r["v_to_model"]) != (x[1], *vals): bad_row += 1
            b = bank[c]
            if (r["key"], r["portion"], r["figure"]) != (o["key"], portion(b["book"], b["chapter"]), bool(b["figure"])): bad_row += 1
            if (r["check"], r["refusal"]) != sp[c]: bad_sp += 1; bad_list.append(c)
            skind = ("F" if fig_in_span(self.fig_toks.get(c, []), r["c_from_model"], r["c_to_model"]) else "P") \
                if sp[c][0] == "accepted" else ""                     # FIG-SPAN (OPEN-ladder 12)
            if r["splice_kind"] != skind: bad_row += 1
        cond("decisions and choices_model.parquet agree row for row; key, portion, figure, splice_kind recomputed",
             bad_row == 0 and len(rows) == len(objs) and [r["choice"] for r in rows] == ids, f"{len(rows)} rows, {bad_row} differ")
        cond("every check and refusal recomputed (rule SP, 7.4)", bad_sp == 0, f"{bad_sp} differ {bad_list[:5]}")

        say("\n## Counts")
        say("      portion x kind x check x refusal:")
        cnt = collections.Counter((r["portion"], r["kind_model"], r["check"], r["refusal"] or "-") for r in rows)
        for k, v in sorted(cnt.items()): say(f"        {' | '.join(k)}: {v}")
        say("      per book x check:")
        bk = collections.Counter((r["choice"].split(":")[1], r["check"]) for r in rows)
        for b in BOOKS: say(f"        {b}: " + ", ".join(f"{c} {bk[(b, c)]}" for c in ("accepted", "no_splice", "refused")))
        say("      per kind: " + ", ".join(f"{k} {sum(1 for r in rows if r['kind_model'] == k)}" for k in KINDS))
        nref = sum(1 for r in rows if r["check"] == "refused"); nres = sum(1 for r in rows if r["kind_model"] != "explains")
        say(f"      refused: {nref} of {len(rows)} choices ({100 * nref / len(rows):.2f}%); of the {nres} restating choices {100 * nref / nres:.2f}%")
        for r in rows:
            if r["check"] == "refused": say(f"        refused {r['choice']}: {r['refusal']}")
        sk = collections.Counter(r["splice_kind"] for r in rows if r["splice_kind"])
        say(f"      splice_kind: P {sk['P']}, F {sk['F']}")

        say("\n## Step 1 recomputed (7.4: every step-1 verse is verse words plus comment words, in order)")
        byk = {}
        for o in objs: byk.setdefault(o["key"], o)
        byo = {o["comment"]: o for o in objs}
        fail = []; nverse = nsplice = nwords = 0; dbl = []
        for k, A in sorted(acc.items()):
            s2 = byk[k]["verse_step2"]; nverse += 1
            out = []; i = 0; spans = sorted(A)
            pos = {}
            for vf, vt, cf, ct, c in spans:
                idx = [j for j, x in enumerate(s2) if vf <= x["w"] <= vt]
                if not idx or idx != list(range(idx[0], idx[-1] + 1)): fail.append((c, "span not a run of step-2 words")); continue
                pos[c] = (idx[0], idx[-1])
            if any(c not in pos for *_, c in spans): continue
            order = sorted(spans, key=lambda a: pos[a[4]][0])
            if [a[4] for a in order] != [a[4] for a in spans]: fail.append((k, "splices not in verse order"))
            j = 0; kept = []
            for vf, vt, cf, ct, c in order:
                a, b = pos[c]
                out += [x["text"] for x in s2[j:a]]; kept += s2[j:a]
                cw = " ".join(t["written"] for t in byo[c]["tokens"] if cf <= t["i"] <= ct).split()
                out += cw; nsplice += 1
                if a > 0 and cons(cw[0]) == cons(s2[a - 1]["text"]): dbl.append((c, "start", cw[0]))
                if b + 1 < len(s2) and cons(cw[-1]) == cons(s2[b + 1]["text"]): dbl.append((c, "end", cw[-1]))
                j = b + 1
            out += [x["text"] for x in s2[j:]]; kept += s2[j:]
            covered = {id(x) for vf, vt, cf, ct, c in spans for x in s2[pos[c][0]:pos[c][1] + 1]}
            if [x for x in s2 if id(x) not in covered] != kept: fail.append((k, "a step-2 word added, dropped or moved"))
            nwords += len(out)
        cond("every spliced step-1 verse passes the rule check", not fail,
             f"{nverse} verses with splices, {nsplice} splices, {nwords} step-1 words in them; failures {fail[:4]}")
        cond("doubled words at splice edges (same consonants as the step-2 word beside the span)", not dbl, f"{len(dbl)} {dbl[:4]}")

        say("\n## Credit, sources, build.json")
        sj = json.loads((d / "sources.json").read_text(encoding="utf-8"))
        cat = tomllib.loads((d / "categories.toml").read_text(encoding="utf-8"))
        ok = True
        for b in BOOKS:
            q = f"shoresh/macula/data/hebrew-ladder/{d.name}/chooser/decisions/{b}.tsv"; e = sj.get(q, {})
            ok = ok and e.get("credit") == CREDIT and e.get("basis") == "model" and e.get("model") == MODEL \
                and e.get("human_check") == "none" and "spend_usd" in e and e.get("sha256") == sha(d / "chooser" / "decisions" / f"{b}.tsv")
        spend = sj.get(f"shoresh/macula/data/hebrew-ladder/{d.name}/chooser/decisions/JON.tsv", {}).get("spend_usd")
        cond("sources.json: the decisions files with sha256, basis model, the credit line, model, spend, no human check", ok, f"spend {spend}")
        cr = cat.get("credit", {})
        cond("categories.toml: the credit line, model, session, spend, human check false",
             cr.get("chooser") == CREDIT and cr.get("chooser_model") == MODEL and cr.get("chooser_human_check") is False
             and "chooser_spend_usd" in cr and cr.get("chooser_session") == "stage 60", f"spend {cr.get('chooser_spend_usd')}")
        cond("categories.toml: the codes of kind_model, check, refusal", tuple(cat.get("codes", {}).get("kind_model", [])) == KINDS
             and set(cat["codes"].get("check", [])) == {"accepted", "refused", "no_splice"}
             and {r["refusal"] for r in rows if r["refusal"]} <= set(cat["codes"].get("refusal", [])), "")
        zr = [p for p in sorted(L2.glob("*.parquet"))]
        cond("sources.json pins the step-2 text read", all(sj.get(str(p.relative_to(REPO)), {}).get("sha256") == sha(p) for p in zr), f"{len(zr)} files")
        bj = json.loads((d / "build.json").read_text(encoding="utf-8"))
        ss = sha(d / "sealed" / "chooser_sample.tsv")
        cond("sealed/chooser_sample.tsv has its sha256 in build.json (files and sealed_chooser)",
             bj.get("sealed_chooser") == ss and bj.get("files", {}).get("sealed/chooser_sample.tsv") == ss, ss[:16])
        fb = [k for k, v in bj.get("files", {}).items() if not (d / k).is_file() or sha(d / k) != v]
        want = {"chooser/choices_model.parquet", "categories.toml"} | {f"chooser/{x}/{b}.{e}" for b in BOOKS for x, e in (("input", "jsonl"), ("decisions", "tsv"))}
        cond("build.json lists every stage-60 file with its sha256", not fb and want <= set(bj.get("files", {})), f"{len(bj.get('files', {}))} files, {len(fb)} differ")
        s60 = bj.get("stage60", {})
        cond("build.json: stage60 entry, model, credit, input shas; code shas equal the code",
             s60.get("model") == MODEL and s60.get("credit") == CREDIT
             and all(s60.get("inputs", {}).get(b) == sha(d / "chooser" / "input" / f"{b}.jsonl") for b in BOOKS)
             and all(sha(REPO / c) == v for c, v in bj.get("code", {}).items()), f"{len(bj.get('code', {}))} code files")

        if not rebuild:
            cond("two --check rebuilds give the same sha256", None, "skipped (--no-rebuild)"); return
        base = Path("/tmp/claude-1000/source-examples/ladder60"); n = 1
        while (base / f"rebuild-{n}").exists(): n += 1
        sums = []
        names = ["chooser/choices_model.parquet", "categories.toml", "sources.json", "COLUMNS.md", "build.json"]
        for k in (n, n + 1):
            o = base / f"rebuild-{k}"
            subprocess.run([sys.executable, "-I", str(MAC / "build_ladder.py"), "--build", d.name, "--stage", "60", "--check",
                            "--out", str(o)], check=True, capture_output=True)
            sums.append({x: sha(o / x) for x in names})
        mine = {x: sha(d / x) for x in names}
        diff = [x for x in names if not (sums[0][x] == sums[1][x] == mine[x])]
        cond("two --check rebuilds give the same sha256 for the parquet, categories.toml, sources.json, COLUMNS.md, build.json"
             " (and equal the build)", not diff, f"differ: {diff} (scratch rebuild-{n}, rebuild-{n + 1})")
