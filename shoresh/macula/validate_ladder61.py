"""Stage 61 of the Hebrew ladder: the exit conditions of SPEC-ladder 8.7 (and 9, 11), recomputed here.

Called by validate_ladder.py --upto 61. Imports nothing from the builders: every rule it checks is written again here.
"""
import collections, hashlib, json, random, re, subprocess, sys, tomllib, unicodedata as ud
from pathlib import Path

import pyarrow.parquet as pq

MAC = Path(__file__).resolve().parent
DATA = MAC / "data"
K1 = DATA / "source-examples" / "k1"
REPO = MAC.parent.parent
PARTS = ("hbo", "heb_mod", "heb_scg")
# the four steps of SPEC-ladder 0.2 (8.1); old step 4 (R only) was dropped on 2026-11-24, old step 5 is step 4
NAMES = {1: "easiest", 2: "easy", 3: "more advanced", 4: "real"}
SWITCHES = {1: ["P", "F", "V", "A", "R"], 2: ["V", "A", "R"], 3: ["V", "R"], 4: []}
LEVELS = {2: {"hbo": "z_r_a", "heb_mod": "r", "heb_scg": "r"}, 3: {"hbo": "zr_r", "heb_mod": "r", "heb_scg": "r"},
          4: {"hbo": "l0", "heb_mod": "l0", "heb_scg": "l0"}}
LAST = 4                                   # the real text
STEPS = tuple(range(1, LAST + 1))
UPPER = tuple(range(2, LAST + 1))          # the steps that read a pilot-2 level
PAIRS = tuple((a, a + 1) for a in range(1, LAST))
ALL = ["JON", "PSA1-41", "ISA40-55", "RUT", "GEN22-25", "MRK"]
STEP1 = ["JON", "PSA1-41", "ISA40-55"]
MISSING = {"heb_mod": {"V": "no_gloss_bank", "A": "not_in_editions"}, "heb_scg": {"V": "no_gloss_bank", "A": "not_in_editions"},
           "RUT": {"V": "no_gloss_bank"}, "GEN22-25": {"V": "no_gloss_bank"}}
TESTS = ["JON 1:3", "JON 4:11", "PSA 2:7", "PSA 23:1", "PSA 41:14", "ISA 40:1", "ISA 53:5", "ISA 55:13", "RUT 1:16",
         "GEN 22:8", "MRK 1:1", "MRK 4:35"]
CARD_KEYS = ["key", "part", "step", "name", "text", "next", "who", "hard_words", "passage", "similar", "layout", "sources", "witness"]
TEXTKEYS = {"lemma", "body", "text", "written", "core", "fit_form", "before", "after", "line", "text_here", "text_next", "name"}
LATIN = re.compile(r"[A-Za-z]")
KEEP = set(range(0x05B0, 0x05BD)) | {0x05C1, 0x05C2, 0x05C7}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def por(book, ch):
    if book in ("JON", "RUT", "MRK"): return book
    if book == "PSA" and 1 <= ch <= 41: return "PSA1-41"
    if book == "ISA" and 40 <= ch <= 55: return "ISA40-55"
    if book == "GEN" and 22 <= ch <= 25: return "GEN22-25"
    return ""


def kpor(key):
    b, cv = key.split(" "); return por(b, int(cv.split(":")[0]))


def closed(key):
    b, cv = key.split(" "); c = int(cv.split(":")[0])
    return b in ("RUT", "JON") or (b, c) in {("GEN", 22), ("LUK", 1), ("LUK", 2), ("LUK", 15), ("PHP", 3), ("ACT", 1), ("MAT", 21)}


def form(raw, f):
    s = ud.normalize("NFD", raw)
    out = []
    for c in s:
        if c == "־": out.append(" ")
        elif "א" <= c <= "ת" or c == " ": out.append(c)
        elif ud.category(c) == "Mn":
            if f == "point" and ord(c) in KEEP: out.append(c)
        else: out.append(" ")
    return " ".join("".join(out).split())


def tsv(p):
    L = p.read_text(encoding="utf-8").split("\n")
    h = L[0].split("\t")
    return h, [dict(zip(h, l.split("\t"))) for l in L[1:] if l]


def latin_walk(x, hits, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            if path == "" and k == "name": continue     # the step's name: a code of profiles.toml (SPEC-ladder 9.1), not a text value
            if k in TEXTKEYS and isinstance(v, str):
                if LATIN.search(v): hits.append((path + "." + k, v[:40]))
            else: latin_walk(v, hits, path + "." + k)
    elif isinstance(x, list):
        for v in x: latin_walk(v, hits, path)


def key_of(w):
    return f"{w['book']} {w['chapter']}:{w['verse']}"


class Check61:
    def __init__(self, d, d59, cond, say):
        self.d, self.d59, self.cond, self.say = Path(d).resolve(), Path(d59).resolve(), cond, say

    def rd(self, p):
        return pq.read_table(p).to_pylist()

    def run(self, rebuild=True):
        cond, say, d = self.cond, self.say, self.d
        say("\n# Stage 61: the ladder\n")
        self.profiles()
        self.texts()
        self.changes()
        self.lines()
        self.layout()
        self.sample()
        self.guide()
        self.files()
        self.card()
        self.latin()
        self.rebuild(rebuild)

    # ---------------------------------------------------------------- 8.1
    def profiles(self):
        say, cond = self.say, self.cond
        say("## profiles.toml (8.1)")
        try:
            P = tomllib.loads((self.d / "profiles.toml").read_text(encoding="utf-8")); ok = True
        except Exception as e:
            P = {"step": []}; ok = False
        st = {s["step"]: s for s in P.get("step", [])}
        good = ok and sorted(st) == list(STEPS) and all(st[n]["name"] == NAMES[n] and st[n]["switches"] == SWITCHES[n] for n in st)
        good = good and st[1].get("base_level") == "z_r_a" and st[1]["portions"] == STEP1 and all(st[n].get("level") == LEVELS[n] and st[n]["portions"] == ALL for n in UPPER)
        good = good and st[3].get("v") == "rare" and P.get("missing") == MISSING and P.get("meta", {}).get("levels_build") == "hebrew-levels/pilot-2"
        nest = all(set(st[n + 1]["switches"]) <= set(st[n]["switches"]) for n in STEPS[:-1]) if good else False
        lv = all((self.d59 / "texts" / l / p / "words.parquet").is_file() for n in UPPER for p, l in LEVELS[n].items()) if good else False
        cond("profiles.toml parses and holds the four profiles of 8.1", good, f"{len(st)} steps")
        cond("the profiles nest (each step's switches hold the next step's; V all at 2, V rare at 3) and name pilot-2 levels that exist", nest and lv, "")
        self.st = st

    # ---------------------------------------------------------------- 8.2
    def load_step(self, n, part):
        t = self.d / "texts" / f"step{n}" / part
        return self.rd(t / "words.parquet"), self.rd(t / "pieces.parquet"), self.rd(t / "links.parquet")

    def own_step1(self, W2, P2, K2):
        kw = {}
        for part in ("hbo", "arc"):
            for r in pq.read_table(K1 / part / "words.parquet", columns=["t", "w"]).to_pylist(): kw[(part, r["t"])] = r["w"]
        W2 = [w for w in W2 if kpor(key_of(w)) in STEP1]
        lk = collections.defaultdict(list); pc = collections.defaultdict(list)
        for k in K2: lk[k["t"]].append(k)
        for p in P2: pc[p["t"]].append(p)
        ch = [c for c in self.rd(self.d / "chooser" / "choices_model.parquet") if c["check"] == "accepted"]
        toks = collections.defaultdict(dict)
        for r in self.rd(self.d / "banks" / "paraphrase_tokens.parquet"): toks[r["comment"]][r["i"]] = r["written"]
        byk = collections.defaultdict(list)
        for c in ch: byk[c["key"]].append(c)
        verses = collections.defaultdict(list)
        for w in W2: verses[key_of(w)].append(w)
        W, P, K = [], [], []; t = 0; spans_done = 0; reach_fail = []
        for key in dict.fromkeys(key_of(w) for w in W2):
            ws = verses[key]; pos = 0
            vmin = [min(kw[(k["other"], k["s"])] for k in lk[w["t"]]) for w in ws]
            spans = sorted(byk.get(key, []), key=lambda c: c["v_from_model"])
            i = 0
            while i < len(ws):
                c = next((c for c in spans if c["v_from_model"] <= vmin[i] <= c["v_to_model"]), None)
                if not c:
                    t += 1; pos += 1; w = ws[i]
                    W.append(dict(w, t=t, w=pos)); P += [dict(p, t=t) for p in pc[w["t"]]]
                    K += [dict(k, t=t, comment="", i=None) for k in lk[w["t"]]]; i += 1; continue
                gone = []
                while i < len(ws) and c["v_from_model"] <= vmin[i] <= c["v_to_model"]: gone.append(ws[i]); i += 1
                spans.remove(c); spans_done += 1
                srcs = sorted({(k["s"], k["s_n"], k["other"]) for g in gone for k in lk[g["t"]]})
                words = [(x, j) for j in range(c["c_from_model"], c["c_to_model"] + 1) for x in toks[c["choice"]].get(j, "").split()]
                for m, (x, j) in enumerate(words):
                    t += 1; pos += 1
                    W.append({"t": t, "book": gone[0]["book"], "chapter": gone[0]["chapter"], "verse": gone[0]["verse"], "w": pos, "text": x,
                              "after": " " if m < len(words) - 1 else gone[-1]["after"], "sentence": gone[0]["sentence"],
                              "clause": gone[0]["clause"], "op": c["choice"]})
                    P.append({"t": t, "n": 1, "text": x, "kind": "comment", "lexeme": "", "class": "", "marks": "{}", "who": "",
                              "who_basis": "", "basis": "model", "op": c["choice"]})
                    K += [{"t": t, "n": 1, "s": s, "agree": None, "agree_model": 1, "other": o, "how": "comment", "basis": "model",
                           "s_n": n, "comment": c["choice"], "i": j} for s, n, o in srcs]
            if spans: reach_fail.append(key)
        return (W, P, K), spans_done, reach_fail, len(ch)

    def texts(self):
        say, cond, d = self.say, self.cond, self.d
        say("\n## Step texts (8.2)")
        self.T = {}
        miss = [f"step{n}/{p}" for n in STEPS for p in (["hbo"] if n == 1 else PARTS) if not (d / "texts" / f"step{n}" / p / "links.parquet").is_file()]
        extra = [str(x.relative_to(d)) for x in (d / "texts").glob("step1/*") if x.name != "hbo"] + \
                [str(x.relative_to(d)) for x in (d / "texts").glob("*") if x.name not in {f"step{n}" for n in STEPS}]
        cond("texts/step<N>/<part>/ present: step 1 hbo only, steps 2-4 the three parts", not miss and not extra, f"missing {miss}, extra {extra}")
        for n in STEPS:
            for p in (["hbo"] if n == 1 else PARTS): self.T[(n, p)] = self.load_step(n, p)
        # steps 2-4 equal the pilot-2 level texts
        diff = []
        for n in UPPER:
            for p in PARTS:
                for f in ("words", "pieces", "links"):
                    a = pq.read_table(d / "texts" / f"step{n}" / p / f"{f}.parquet"); b = pq.read_table(self.d59 / "texts" / LEVELS[n][p] / p / f"{f}.parquet")
                    if not a.equals(b): diff.append(f"step{n}/{p}/{f}")
        cond("steps 2-4 are the pilot-2 level texts profiles.toml names, row for row (words, pieces, links)", not diff, f"differ {diff[:4]}")
        # step 1 recomputed
        (W, P, K), nsp, rf, nacc = self.own_step1(*self.T[(2, "hbo")])
        W1, P1, K1_ = self.T[(1, "hbo")]
        same = W == W1 and P == P1 and K == K1_
        cond("step 1 recomputed here (the step-2 text with every accepted splice, 7.4, 8.2) equals texts/step1/hbo row for row",
             same and not rf and nsp == nacc, f"{len(W1)} words, {len(P1)} pieces, {len(K1_)} links; {nsp} splices of {nacc} accepted; unplaced {rf[:3]}")
        out = [key_of(w) for w in W1 if kpor(key_of(w)) not in STEP1]
        cond("no step-1 row outside JON, PSA 1-41, ISA 40-55", not out, f"{len(out)} rows outside")
        cw = [p for p in P1 if p["kind"] == "comment"]
        bad = [p for p in cw if p["basis"] != "model" or p["lexeme"] or p["who"] or p["marks"] != "{}"]
        badk = [k for k in K1_ if k["how"] == "comment" and (k["basis"] != "model" or not k["comment"])]
        cond("commentator words: one piece of kind comment, basis model; links how comment, basis model, with comment and i",
             not bad and not badk and len(cw) == len({p["t"] for p in cw}), f"{len(cw)} commentator words; bad pieces {len(bad)}, bad links {len(badk)}")
        self.say(f"      step 1: {len(W1)} words, of them {len(cw)} commentator words; verses {len({key_of(w) for w in W1})}")
        # full links, both directions; source pieces reached; verse keys equal the real step's
        src = {}
        for p in PARTS:
            sw = pq.read_table(K1 / p / "words.parquet", columns=["t", "book", "chapter", "verse", "text"]).to_pylist()
            src[p] = [w for w in sw if kpor(key_of(w)) in ALL]
        self.src = src
        srcp = {}
        for p in PARTS:
            ts = {w["t"] for w in src[p]}
            srcp[p] = {(r["t"], r["n"]) for r in pq.read_table(K1 / p / "pieces.parquet", columns=["t", "n"]).to_pylist() if r["t"] in ts}
        fails = []; keysbad = []
        for (n, p), (W_, P_, K_) in sorted(self.T.items()):
            wt = {w["t"] for w in W_}; pt = {(x["t"], x["n"]) for x in P_}; lt = {(k["t"], k["n"]) for k in K_}
            scope = STEP1 if n == 1 else ALL
            keys_src = {key_of(w) for w in src[p] if kpor(key_of(w)) in scope}
            ts_scope = {w["t"] for w in src[p] if kpor(key_of(w)) in scope}
            need = {(t, m) for (t, m) in srcp[p] if t in ts_scope}
            reached = {(k["s"], k["s_n"]) for k in K_}
            nolink_w = len(wt - {t for t, _ in lt}); nopiece_w = len(wt - {t for t, _ in pt})
            nolink_p = len(pt - lt); orphan = len(lt - pt); unreached = len(need - reached); stray = len(reached - srcp[p])
            if nolink_w or nopiece_w or nolink_p or orphan or unreached or stray:
                fails.append((n, p, nolink_w, nopiece_w, nolink_p, orphan, unreached, stray))
            ks = list(dict.fromkeys(key_of(w) for w in W_))
            k5 = [k for k in dict.fromkeys(key_of(w) for w in self.T[(LAST, p)][0]) if kpor(k) in scope]
            if ks != k5 or set(ks) != keys_src: keysbad.append((n, p, len(ks), len(k5)))
        cond("every step text has full links: every word and piece links to a k1 source piece, no link without a piece, "
             "every source piece of the scope reached", not fails, f"{len(self.T)} texts; failures (step, part, words w/o link, words w/o piece, pieces w/o link, orphan links, unreached, stray) {fails[:3]}")
        cond("the verse keys of every step equal step 4's, the real text (in order)", not keysbad, f"{keysbad[:3]}")
        bad5 = []
        for p in PARTS:
            a = [(key_of(w), w["text"]) for w in self.T[(LAST, p)][0]]; b = [(key_of(w), w["text"]) for w in src[p]]
            if a != b: bad5.append(p)
            ps = {(r["t"], r["n"]): r["text"] for r in pq.read_table(K1 / p / "pieces.parquet", columns=["t", "n", "text"]).to_pylist()}
            lk = {}
            for k in self.T[(LAST, p)][2]: lk.setdefault((k["t"], k["n"]), (k["s"], k["s_n"]))
            if any(ps.get(lk[(x["t"], x["n"])]) != x["text"] for x in self.T[(LAST, p)][1]) or any(k["how"] != "copy" for k in self.T[(LAST, p)][2]):
                bad5.append(p + "/pieces")
        cond("step 4 (the real text) equals the source text word for word (k1 words, in order; every piece a copy of its source piece)", not bad5,
             f"{', '.join(f'{p} {len(self.T[(LAST, p)][0])}' for p in PARTS)} words; differ {bad5}")

    # ---------------------------------------------------------------- 8.3
    def own_changes(self):
        ops = collections.defaultdict(dict)
        for r in self.rd(self.d59 / "ops.parquet"):
            if r["state"] == "applied": ops[(r["level"], r["text"])][(r["switch"], r["src_t"], r["src_n"])] = r
        rows = []
        for s in UPPER[:-1]:
            for p in PARTS:
                la, lb = LEVELS[s][p], LEVELS[s + 1][p]
                if la == lb: continue
                Wa, _, Ka = self.T[(s, p)]; Wb, _, Kb = self.T[(s + 1, p)]
                txa = {w["t"]: w["text"] for w in Wa}; txb = {w["t"]: w["text"] for w in Wb}
                la_ = collections.defaultdict(list); lb_ = collections.defaultdict(list)
                for k in Ka: la_[k["t"]].append(k)
                for k in Kb: lb_[k["t"]].append(k)
                byp = collections.defaultdict(set)
                for k in Kb:
                    if k["how"] in ("copy", "replace"): byp[(k["other"], k["s"], k["s_n"])].add(k["t"])
                bypa = collections.defaultdict(set)
                for k in Ka:
                    if k["how"] in ("copy", "replace"): bypa[(k["other"], k["s"], k["s_n"])].add(k["t"])
                A, B = ops[(la, p)], ops[(lb, p)]
                for x in set(A) | set(B):
                    a, b = A.get(x), B.get(x)
                    if a and b and a["after"] == b["after"]: continue
                    here = json.loads(a["draft_t"]) if a else sorted({t for t2 in json.loads(b["draft_t"]) for k in lb_[t2] if k["how"] in ("copy", "replace") for t in bypa[(k["other"], k["s"], k["s_n"])]})
                    nxt = json.loads(b["draft_t"]) if b else sorted({t for t1 in here for k in la_[t1] if k["how"] in ("copy", "replace") for t in byp[(k["other"], k["s"], k["s_n"])]})
                    src = sorted({(k["s"], k["s_n"]) for t in here for k in la_[t]} | {(k["s"], k["s_n"]) for t in nxt for k in lb_[t]})
                    o = a or b
                    rows.append((s, p, o["key"], x[0].upper(), o["op"], here, nxt, [list(y) for y in src],
                                 " ".join(txa[t] for t in here), " ".join(txb[t] for t in nxt), [], "derived"))
        return rows

    def changes(self):
        say, cond = self.say, self.cond
        say("\n## changes.parquet (8.3, rule CH)")
        C = self.rd(self.d / "changes.parquet"); self.C = C
        cols = list(pq.read_table(self.d / "changes.parquet").schema.names)
        want = ["change", "step", "part", "key", "kind", "source", "words_here", "words_next", "src", "text_here", "text_next", "under_splice", "basis_here"]
        cond("changes.parquet: the columns of 8.3", cols == want, ",".join(cols))
        got = sorted((r["step"], r["part"], r["key"], r["kind"], r["source"], json.loads(r["words_here"]), json.loads(r["words_next"]),
                      json.loads(r["src"]), r["text_here"], r["text_next"], json.loads(r["under_splice"]), r["basis_here"])
                     for r in C if r["step"] > 1)
        own = sorted(self.own_changes())
        cond("rule CH recomputed here: the changes of steps 2-3 equal the table", got == own, f"{len(got)} rows; recomputed {len(own)}")
        # step 1: one change per accepted choice
        acc = {c["choice"]: c for c in self.rd(self.d / "chooser" / "choices_model.parquet") if c["check"] == "accepted"}
        c1 = [r for r in C if r["step"] == 1]
        W1 = {w["t"]: w for w in self.T[(1, "hbo")][0]}; W2 = {w["t"]: w for w in self.T[(2, "hbo")][0]}
        ops2 = {w["op"] for w in W2.values() if w["op"]}
        bad = [r["change"] for r in c1 if r["source"] not in acc or r["kind"] != acc[r["source"]]["splice_kind"] or r["basis_here"] != "model"
               or any(W1[t]["op"] != r["source"] for t in json.loads(r["words_here"]))
               or r["text_here"] != " ".join(W1[t]["text"] for t in json.loads(r["words_here"]))
               or r["text_next"] != " ".join(W2[t]["text"] for t in json.loads(r["words_next"]))
               or sorted({w["op"] for t in json.loads(r["words_next"]) for w in [W2[t]] if w["op"]}) != sorted(set(json.loads(r["under_splice"])) & ops2)]
        cond("step 1: one change per accepted splice, kind its splice_kind, basis model, texts and under_splice as the words say",
             not bad and len(c1) == len(acc) == len({r["source"] for r in c1}), f"{len(c1)} changes, {len(acc)} accepted; bad {bad[:3]}")
        ids = [r["change"] for r in C]
        order = sorted(C, key=lambda r: (r["step"], r["part"], min(map(tuple, json.loads(r["src"]))) if json.loads(r["src"]) else (0, 0), r["kind"], r["source"]))
        num = collections.Counter(); exp = []
        for r in order: num[(r["step"], r["part"])] += 1; exp.append(f"ch:{r['step']}:{r['part']}:{num[(r['step'], r['part'])]}")
        cond("change keys ch:<step>:<part>:<n> in the sort order of 8.3", ids == exp and [r["change"] for r in order] == ids, f"{len(ids)} keys")
        c3 = collections.Counter((r["part"], r["kind"]) for r in C if r["step"] == LAST - 1)
        okc3 = set(k for p, k in c3 if p == "hbo") <= {"V", "R"} and all(k == "R" for p, k in c3 if p != "hbo")
        cond("the changes from step 3 to step 4 hold rare-word V and R (hbo) and R only (the editions); no step above 4", okc3 and max(r["step"] for r in C) == LAST - 1,
             f"{dict(sorted(c3.items()))}")
        under = sum(len(json.loads(r["under_splice"])) for r in c1)
        say(f"      changes per step x part x kind: {dict(sorted(collections.Counter((r['step'], r['part'], r['kind']) for r in C).items()))}")
        say(f"      pilot-2 ops of z_r_a under an accepted splice (not at step 1): {under}")
        # replay
        fails = []; nverse = 0; after_moved = 0
        byv = collections.defaultdict(list)
        for r in C: byv[(r["step"], r["part"], r["key"])].append(r)
        for (s, p) in sorted(k for k in self.T if (k[0] + 1, k[1]) in self.T):
            Ws, _, _ = self.T[(s, p)]; Wn, _, Kn = self.T[(s + 1, p)]
            vs = collections.defaultdict(list); vn = collections.defaultdict(list)
            for w in Ws: vs[key_of(w)].append(w)
            for w in Wn: vn[key_of(w)].append(w)
            lk = collections.defaultdict(set)
            for k in Kn: lk[k["t"]].add((k["s"], k["s_n"]))
            for key, ws in vs.items():
                nverse += 1
                ch = byv.get((s, p, key), [])
                first = {}; skip = set(); ins = collections.defaultdict(list)
                seq = [w["t"] for w in vn[key]]
                for r in sorted(ch, key=lambda r: json.loads(r["words_here"])[0] if json.loads(r["words_here"]) else 0):
                    wn = json.loads(r["words_next"]); here = r["text_here"].split(" ") if r["text_here"] else []
                    if wn:
                        first[wn[0]] = here; skip |= set(wn)
                    else:
                        sp = {tuple(x) for x in json.loads(r["src"])}
                        anc = [t for t in seq if lk[t] & sp]
                        ins[anc[-1] if anc else None].append(here)
                out = []
                for t in seq:
                    if t in first: out += first[t]
                    elif t not in skip: out.append(next(w["text"] for w in vn[key] if w["t"] == t))
                    for h in ins.get(t, []): out += h
                if ins.get(None): fails.append((s, p, key, "no anchor"))
                if out != [w["text"] for w in ws]: fails.append((s, p, key))
                if not ch and [(w["text"], w["after"]) for w in ws] != [(w["text"], w["after"]) for w in vn[key]]: fails.append((s, p, key, "after"))
                elif ch: after_moved += sum(1 for a, b in zip(ws, vn[key]) if a["text"] == b["text"] and a["after"] != b["after"])
        cond("rule CH replays: the step-(s+1) verse with its changes put back gives the step-s verse, word for word, every verse",
             not fails, f"{nverse} verse pairs; failures {len(fails)} {fails[:4]}")
        say(f"      (word texts compared; in verses without a change also every `after`. Words whose `after` moved beside an insertion, by SPEC-levels 7.2: up to {after_moved} counted by position)")

    # ---------------------------------------------------------------- 8.4
    def lines(self):
        say, cond, d = self.say, self.cond, self.d
        say("\n## Lines, differ.tsv, thin.tsv (8.4)")
        self.L = {}
        for (n, p), (W, _, _) in self.T.items():
            raw = collections.OrderedDict()
            for w in W:
                raw.setdefault(key_of(w), []).append(w["text"] + w["after"] if p == "hbo" else w["text"])
            self.L[(n, p)] = {k: ("".join(v) if p == "hbo" else " ".join(v)) for k, v in raw.items()}
        bad = []; lat = []
        for (n, p), raw in sorted(self.L.items()):
            for f in ("cons", "point"):
                pth = d / "lines" / f"step{n}" / f"{p}.{f}.tsv"
                if not pth.is_file(): bad.append(str(pth.name)); continue
                h, rows = tsv(pth)
                nxt = self.L.get((n + 1, p))
                exp = [{"key": k, "part": p, "step": str(n), "form": f, "scoring_closed": "true" if closed(k) else "false",
                        "changed": "true" if (n < LAST and form(r, "point") != form(nxt[k], "point")) else "false", "line": form(r, f)} for k, r in raw.items()]
                if h != ["key", "part", "step", "form", "scoring_closed", "changed", "line"] or rows != exp: bad.append(f"step{n}/{p}.{f}")
                if any(not r["line"] for r in rows): bad.append(f"empty line step{n}/{p}.{f}")
        cond("lines/step<N>/<part>.<form>.tsv recomputed (rule IN, changed against step N+1, scoring_closed)", not bad, f"{len(self.L) * 2} files; differ {bad[:4]}")
        # differ / thin
        exp_d, exp_t = [], []
        for po in ALL:
            for p in (("heb_mod", "heb_scg") if po == "MRK" else ("hbo",)):
                m = {**MISSING.get(p, {}), **MISSING.get(po, {})}
                for a, b in PAIRS:
                    if (a, p) not in self.L or (a == 1 and po not in STEP1): continue
                    ks = [k for k in self.L[(a, p)] if kpor(k) == po]
                    dif = sum(form(self.L[(a, p)][k], "point") != form(self.L[(b, p)][k], "point") for k in ks)
                    exp_d.append({"portion": po, "part": p, "pair": f"{a}/{b}", "verses": str(len(ks)), "differ": str(dif), "share": f"{dif / len(ks):.4f}"})
                    exp_t.append({"portion": po, "part": p, "pair": f"{a}/{b}", "verses": str(len(ks)), "equal": str(len(ks) - dif),
                                  "share": f"{(len(ks) - dif) / len(ks):.4f}", "missing": json.dumps(dict(sorted(m.items())), ensure_ascii=False, separators=(",", ":"))})
        _, gd = tsv(d / "differ.tsv"); _, gt = tsv(d / "thin.tsv")
        cond("differ.tsv recomputed (verses whose point line differs, per portion x part x pair)", gd == exp_d, f"{len(gd)} rows")
        cond("thin.tsv recomputed (verses equal at both steps; the switches [missing] names)", gt == exp_t, f"{len(gt)} rows")
        say("\n      Verses that differ, per book and step pair (four steps; old step 4, R only, dropped 2026-11-24)")
        say("      | portion | part | verses | 1/2 | 2/3 | 3/4 |")
        say("      |---|---|---|---|---|---|")
        for po in ALL:
            for p in (("heb_mod", "heb_scg") if po == "MRK" else ("hbo",)):
                cell = {r["pair"]: f"{r['differ']} ({r['share']})" for r in exp_d if r["portion"] == po and r["part"] == p}
                nv = next(r["verses"] for r in exp_d if r["portion"] == po and r["part"] == p)
                say(f"      | {po} | {p} | {nv} | {cell.get('1/2', '-')} | {cell.get('2/3', '-')} | {cell.get('3/4', '-')} |")
        tk = sum(int(r["differ"]) for r in exp_d if r["pair"] == "3/4" and r["part"] == "hbo")
        say(f"      3/4 over the five Tanakh portions: {tk} verses differ")

    # ---------------------------------------------------------------- 8.5
    def layout(self):
        say, cond, d = self.say, self.cond, self.d
        say("\n## Layout (8.5)")
        bad = []; nrows = 0; join_bad = 0; nodepth = 0
        for p in PARTS:
            dep = {r["clause"]: r["depth"] for r in pq.read_table(K1 / p / "clauses.parquet", columns=["clause", "depth"]).to_pylist()}
            for n in STEPS:
                if (n, p) not in self.T: continue
                W = self.T[(n, p)][0]; exp = []
                for w in W:
                    piece = w["text"] + w["after"] if p == "hbo" else w["text"]
                    if exp and exp[-1][0] == key_of(w) and exp[-1][1] == w["clause"]: exp[-1][3].append(piece)
                    else: exp.append([key_of(w), w["clause"], dep.get(w["clause"]), [piece]])
                sep = "" if p == "hbo" else " "
                exp = [{"key": k, "clause": c, "depth": "" if x is None else str(x), "line": sep.join(ps)} for k, c, x, ps in exp]
                h, got = tsv(d / "layout" / f"step{n}" / f"{p}.tsv")
                if h != ["key", "clause", "depth", "line"] or got != exp: bad.append(f"step{n}/{p}")
                nrows += len(got); nodepth += sum(1 for r in got if r["depth"] == "")
                byk = collections.defaultdict(list)
                for r in got: byk[r["key"]].append(r["line"])
                join_bad += sum(1 for k, raw in self.L[(n, p)].items() if sep.join(byk[k]) != raw)
        cond("layout/step<N>/<part>.tsv recomputed (clause runs in text order, k1 depth)", not bad, f"{nrows} rows; differ {bad[:3]}; rows without a clause {nodepth}")
        cond("every layout verse joins to its raw line, word for word", join_bad == 0, f"{join_bad} verses do not")

    # ---------------------------------------------------------------- 8.6
    def sample(self):
        cond = self.cond
        rng = random.Random("ladder-2026-11-24-steps"); exp = []
        st = {r["change"]: r["step"] for r in self.C}
        for kind in ("P", "F", "V", "A", "R"):
            ids = sorted((r["change"] for r in self.C if r["kind"] == kind), key=lambda x: (int(x.split(":")[1]), x.split(":")[2], int(x.split(":")[3])))
            for x in (rng.sample(ids, 20) if len(ids) >= 20 else ids): exp.append({"sample": "change", "group": kind, "id": x, "step": str(st[x])})
        for po in ALL:
            s = 1 if po in STEP1 else 2; p = "heb_mod" if po == "MRK" else "hbo"
            ks = sorted(k for k in self.L[(s, p)] if kpor(k) == po)
            for k in rng.sample(ks, 10): exp.append({"sample": "verse", "group": po, "id": k, "step": str(s)})
        _, got = tsv(self.d / "sealed" / "step_sample.tsv")
        bj = json.loads((self.d / "build.json").read_text(encoding="utf-8"))
        h = sha(self.d / "sealed" / "step_sample.tsv")
        cond("sealed/step_sample.tsv recomputed (seed ladder-2026-11-24-steps; 20 changes per kind, 10 verses per portion) and its sha256 in build.json",
             got == exp and bj.get("sealed_steps") == h and bj.get("files", {}).get("sealed/step_sample.tsv") == h,
             f"{len(got)} rows: {dict(collections.Counter(r['group'] for r in got))}; {h[:16]}")

    # ---------------------------------------------------------------- 11
    def guide(self):
        g = (self.d / "GUIDE.md").read_text(encoding="utf-8") if (self.d / "GUIDE.md").is_file() else ""
        need = ["How to climb", "What each change means", "Whose reading", "thin", "English aid", "tools", "**P (phrase).**",
                "**F (figure).**", "**V (vocabulary).**", "**A (added).**", "**R (referent).**", "step 4 decides", "Isaiah 53", "Psalm 2",
                "thin.tsv", "not part of the verse card", "Metzudat David", "Metzudat Zion", "`who`, `added`"]
        miss = [x for x in need if x not in g]
        self.cond("GUIDE.md holds the six parts of section 11", not miss and (self.d / "README.md").is_file(), f"missing {miss}; README.md {'present' if (self.d / 'README.md').is_file() else 'absent'}")

    def files(self):
        d, cond = self.d, self.cond
        bj = json.loads((d / "build.json").read_text(encoding="utf-8"))
        mine = [str(p.relative_to(d)) for p in d.rglob("*") if p.is_file() and (p.relative_to(d).parts[0] in ("texts", "lines", "layout")
                or str(p.relative_to(d)) in ("profiles.toml", "changes.parquet", "differ.tsv", "thin.tsv", "sealed/step_sample.tsv", "GUIDE.md", "README.md"))]
        bad = [k for k in mine if bj.get("files", {}).get(k) != sha(d / k)]
        code = ["shoresh/macula/build_ladder.py", "shoresh/macula/ladder_stage61.py", "shoresh/macula/ladder_card.py"]
        okc = all(bj.get("code", {}).get(c) == sha(REPO / c) for c in code) and "stage61" in bj
        cond("build.json lists every stage-61 file with its sha256; the stage61 entry; code shas equal the code", not bad and okc, f"{len(mine)} files, {len(bad)} differ")
        sj = json.loads((d / "sources.json").read_text(encoding="utf-8"))
        need = [DATA / "clauses-similar" / "hebrew.parquet", DATA / "clauses-similar" / "tanakh-nt.parquet",
                DATA / "clause-keys" / "2026-11-19" / "clause_keys.parquet", self.d59 / "ops.parquet", K1 / "lexicon" / "lexemes.tsv"]
        need += [K1 / p / f for p in PARTS for f in ("words.parquet", "pieces.parquet", "clauses.parquet", "passages.parquet", "participants.tsv")]
        if self.d59 == DATA / "hebrew-levels" / "pilot-2":     # the level texts the profiles name (8.1), each part
            need += sorted({self.d59 / "texts" / l / p / f"{f}.parquet" for n in UPPER for p, l in LEVELS[n].items()
                            for f in ("words", "pieces", "links")})
        badp = [str(p) for p in need if sj.get(str(p.resolve().relative_to(REPO)), {}).get("sha256") != sha(p)]
        cond("sources.json pins every input of stage 61 and the card by sha256", not badp, f"{len(need)} inputs; differ {badp[:3]}")

    # ---------------------------------------------------------------- 9
    def card_call(self, key, step, part=None):
        b, cv = key.split(" ")
        cmd = [sys.executable, "-m", "macula.ladder_card", b, cv, "--step", str(step), "--build", str(self.d.relative_to(DATA / "hebrew-ladder"))]
        if part: cmd += ["--part", part]
        r = subprocess.run(cmd, cwd=MAC.parent, capture_output=True, text=True)
        try: return r.returncode, json.loads(r.stdout)
        except Exception: return r.returncode, {"_raw": r.stdout[:200], "_err": r.stderr[-300:]}

    def card_fields(self, c, key, step, part):
        """every field the card gives, found in the dataset it names; returns the list of faults"""
        f = []
        b, cv = key.split(" "); ch, v = (int(x) for x in cv.split(":"))
        if [k for k in CARD_KEYS if k not in c]: return [("keys", [k for k in CARD_KEYS if k not in c])]
        if c["key"] != key or c["part"] != part or c["step"] != step or c["name"] != NAMES[step]: f.append("head")
        W, P, K = self.T[(step, part)]
        Wv = [w for w in W if key_of(w) == key]
        lk = collections.defaultdict(list)
        for k in K: lk[k["t"]].append(k)
        ops = self.ops_v
        exp_words = []
        for w in Wv:
            hows = sorted({k["how"] for k in lk[w["t"]]})
            wit = lk[w["t"]][0]["comment"] if "comment" in hows else ops.get(w["op"], "")
            exp_words.append({"t": w["t"], "text": w["text"], "src": [list(x) for x in sorted({(k["s"], k["s_n"]) for k in lk[w["t"]]})], "how": "+".join(hows), "witness": wit})
        if c["text"].get("words") != exp_words: f.append("text.words")
        if c["text"].get("line") != form(self.L[(step, part)][key], "point"): f.append("text.line")
        nx = [{"change": r["change"], "kind": r["kind"], "text_here": r["text_here"], "text_next": r["text_next"],
               "words_here": json.loads(r["words_here"]), "words_next": json.loads(r["words_next"])}
              for r in self.C if r["step"] == step and r["part"] == part and r["key"] == key]
        if c["next"] != nx: f.append("next")
        if step == LAST and c["next"]: f.append("next at the real step")
        # who
        sw = [w["t"] for w in self.src[part] if key_of(w) == key]
        pcs = [r for t in range(sw[0], sw[-1] + 1) for r in self.pbyt[part].get(t, [])]
        ents = {e for r in pcs if r["who"] and r["who_basis"] != "model" for e in r["who"].split()}
        pt = self.parts[part]
        for e in c["who"]:
            if e["ent"] not in ents or pt.get(e["ent"], {}).get("name", "") != e["name"] or pt.get(e["ent"], {}).get("type", "") != e["type"] \
                    or not set(e["words_here"]) <= {w["t"] for w in Wv}:
                f.append(("who", e["ent"]))
        if {e["ent"] for e in c["who"]} != ents: f.append("who set")
        # hard words
        for h in c["hard_words"]:
            ps = [r for r in pcs if r["t"] == h["t"]]
            stem = next((r for r in ps if r["kind"] == "stem"), None)
            cnt = self.lex.get(h["lexeme"])
            if not stem or stem["lexeme"] != h["lexeme"] or h["tanakh_count"] != cnt: f.append(("hard", h["t"])); continue
            if h["gloss"] is not None:
                g = self.gloss.get(h["gloss"]["gloss"])
                if not g or g["key"] != key or h["t"] not in json.loads(g["anchor_t"]) or g["core"] != h["gloss"]["core"] or g["body"] != h["gloss"]["body"]:
                    f.append(("gloss", h["t"]))
            elif not (cnt is not None and cnt < 20): f.append(("not hard", h["t"]))
            have = {x for r in ps for x in re.split(r"[\s,;|]+", (r["sense"] or "") + " " + (r["domain"] or "")) if x}
            if not set(h["sense"]) | set(h["domain"]) <= have: f.append(("sense", h["t"]))
        # passages
        pas = self.passages[part]
        for x in c["passage"]:
            r = pas.get(x["passage"])
            if not r or r["source"] != x["source"] or r["kind"] != x["kind"] or r["fact"] != x["fact"] or r["first"] > sw[-1] or r["last"] < sw[0]:
                f.append(("passage", x["passage"]))
        nexp = sum(1 for r in pas.values() if r["first"] <= sw[-1] and r["last"] >= sw[0])
        if nexp != len(c["passage"]): f.append("passage count")
        # similar: the ids stand in the named table for that clause
        for x in c["similar"]:
            if x.get("reason") == "no_join":
                if x["tanakh"] or x["nt"]: f.append(("similar no_join", x["clause"]))
                self.nojoin[part] += 1; continue
            self.join[part] += 1
            if part == "hbo":
                i = re.match(r"cl:o(\d{12}):", x["clause"]).group(1)
                if x["tanakh"] != self.sim_h(i) or x["nt"] != self.sim_n(i): f.append(("similar", x["clause"]))
            else:
                if any(not self.sim_rev_ok(cl, x["clause"], part) for cl in x["tanakh"]) or x["nt"]: f.append(("similar", x["clause"]))
        _, lay = self.lay[(step, part)]
        el = [{"clause": r["clause"], "depth": int(r["depth"]) if r["depth"] else None, "line": r["line"]} for r in lay if r["key"] == key]
        if c["layout"] != el: f.append("layout")
        for k, lst in c["sources"].items():
            for s in lst:
                p = REPO / s["path"]
                if not p.is_file() or sha(p) != s["sha256"] or s["basis"] not in ("given", "derived", "linked", "model"): f.append(("source", k, s["path"]))
        if set(c["sources"]) - set(CARD_KEYS): f.append("source keys")
        wits = [w["witness"] for w in exp_words if w["witness"]]
        ew = {"code": "jewish_reading_aid" if wits else "", "comments": sorted({x for x in wits if x.startswith("md:")}), "glosses": sorted({x for x in wits if x.startswith("mz:")})}
        if c["witness"] != ew: f.append("witness")
        return f

    def sim_h(self, i):
        return [r["other"] for r in sorted(self.H.get(i, []), key=lambda r: r["rank"])][:5]

    def sim_n(self, i):
        return [r["nt_clause"] for r in sorted(self.N.get(i, []), key=lambda r: r["rank"])][:5]

    def sim_rev_ok(self, tanakh_clause, clause, part):
        fc = self.from_clause[part].get(clause, "")
        m = re.match(r"cl:n(\d{11}):", fc or "")
        return bool(m) and any(r["nt_clause"] == m.group(1) for r in self.N.get(tanakh_clause, []))

    def card(self):
        say, cond = self.say, self.cond
        say("\n## The verse card (9)")
        self.pieces = {p: pq.read_table(K1 / p / "pieces.parquet", columns=["t", "n", "kind", "lexeme", "who", "who_basis", "sense", "domain"]).to_pylist() for p in PARTS}
        self.pbyt = {p: collections.defaultdict(list) for p in PARTS}
        for p in PARTS:
            for r in self.pieces[p]: self.pbyt[p][r["t"]].append(r)
        self.parts = {p: {r["ent"]: r for r in tsv(K1 / p / "participants.tsv")[1]} for p in PARTS}
        self.lex = {r["lexeme"]: (int(r["tanakh"]) if r["tanakh"] else None) for r in tsv(K1 / "lexicon" / "lexemes.tsv")[1]}
        self.gloss = {r["gloss"]: r for r in self.rd(self.d / "banks" / "gloss.parquet")}
        self.passages = {p: {r["passage"]: r for r in pq.read_table(K1 / p / "passages.parquet", columns=["passage", "source", "kind", "first", "last", "fact"]).to_pylist()} for p in PARTS}
        self.lay = {k: tsv(self.d / "layout" / f"step{k[0]}" / f"{k[1]}.tsv") for k in self.T}
        self.ops_v = {r["op"]: json.loads(r["detail"]).get("gloss", "") for r in self.rd(self.d59 / "ops.parquet") if r["switch"] == "v" and r["state"] == "applied"}
        self.H = collections.defaultdict(list); self.N = collections.defaultdict(list)
        for r in pq.read_table(DATA / "clauses-similar" / "hebrew.parquet").to_pylist(): self.H[r["clause_key"]].append(r)
        for r in pq.read_table(DATA / "clauses-similar" / "tanakh-nt.parquet").to_pylist(): self.N[r["clause_key"]].append(r)
        self.from_clause = {p: {r["clause"]: r["from_clause"] for r in pq.read_table(K1 / p / "clauses.parquet", columns=["clause", "from_clause"]).to_pylist()} for p in PARTS[1:]}
        self.join = collections.Counter(); self.nojoin = collections.Counter()
        self.outs = []
        def steps_of(key, part):
            po = kpor(key)
            return [n for n in STEPS if (n, part) in self.T and (po in STEP1 or n > 1)]
        calls = []
        for key in TESTS:
            part = "heb_mod" if key.startswith("MRK") else "hbo"
            calls += [(key, n, part, "test") for n in steps_of(key, part)]
        calls.append(("MRK 4:35", LAST, "heb_scg", "test"))
        pool = sorted({(p, key_of(w)) for p in PARTS for w in self.T[(LAST, p)][0]})
        rng = random.Random("ladder-2026-11-24-card")
        drawn = rng.sample(pool, 20)
        for p, key in drawn: calls += [(key, n, p, "seed") for n in steps_of(key, p)]
        say(f"      20 verses drawn with random.Random('ladder-2026-11-24-card') from the {len(pool)} (part, verse) pairs: "
            + ", ".join(f"{k} {p}" for p, k in drawn))
        faults = []; missing = []; n_ok = 0
        for key, n, p, why in calls:
            rc, c = self.card_call(key, n, p if p != ("heb_mod" if key.startswith("MRK") else "hbo") else None)
            if rc != 0 or "error" in c: faults.append((key, n, p, "exit", rc, str(c)[:120])); continue
            self.outs.append(c)
            if [k for k in CARD_KEYS if k not in c]: missing.append((key, n, p))
            f = self.card_fields(c, key, n, p)
            if f: faults.append((key, n, p, f[:4]))
            else: n_ok += 1
        tests = [x for x in calls if x[3] == "test"]
        cond("the card runs for the 12 test verses at every step each has (and MRK 4:35 in heb_scg) and returns every key of 9.1",
             not [x for x in faults if (x[0], x[1], x[2]) in {(a, b, c) for a, b, c, _ in tests}] and not missing,
             f"{len(tests)} calls; with a fault {len([x for x in faults if (x[0], x[1], x[2]) in {(a, b, c) for a, b, c, _ in tests}])}")
        cond("the card answers for 20 verses drawn by seed across the scope, at every step each has; every field it gives is found in the dataset it names",
             not faults, f"{len(calls)} calls, {n_ok} without fault; faults {faults[:3]}")
        rc, c = self.card_call("RUT 1:16", 1)
        cond("a step the verse does not have: exit code 2 and a json error naming the lowest step", rc == 2 and c.get("lowest_step") == 2, f"exit {rc}, {c}")
        say(f"      similar clauses joined (9.2) over the cards' clauses: {dict(self.join)}; no_join: {dict(self.nojoin)}")
        # the join's coverage over the whole scope (an exit count, no bar)
        ck = {(r["lang"], r["clause"]) for r in pq.read_table(DATA / "clause-keys" / "2026-11-19" / "clause_keys.parquet", columns=["clause", "lang"]).to_pylist()}
        cov = {}
        for p in PARTS:
            cl = {w["clause"] for w in self.T[(LAST, p)][0] if w["clause"]}
            if p == "hbo":
                j = sum(1 for c_ in cl if (m := re.match(r"cl:o(\d{12}):", c_)) and ("hbo", m.group(1)) in ck)
                jn = sum(1 for c_ in cl if (m := re.match(r"cl:o(\d{12}):", c_)) and m.group(1) in self.H)
            else:
                ids = [re.match(r"cl:n(\d{11}):", self.from_clause[p].get(c_) or "") for c_ in cl]
                j = sum(1 for m in ids if m and ("grc", m.group(1)) in ck)
                ntk = {r["nt_clause"] for rs in self.N.values() for r in rs} if not hasattr(self, "_ntk") else self._ntk
                self._ntk = ntk
                jn = sum(1 for m in ids if m and m.group(1) in ntk)
            cov[p] = f"{j} of {len(cl)} k1 clauses find an id in clause-keys; {jn} have rows in the similar table"
        cond("the join's coverage (9.2), counted over the scope (no bar)", True, json.dumps(cov, ensure_ascii=False))

    def latin(self):
        hits = []
        for (n, p), (W, P, K) in self.T.items():
            hits += [(f"step{n}/{p}/words", w["text"]) for w in W if LATIN.search(w["text"])]
            hits += [(f"step{n}/{p}/pieces", x["text"]) for x in P if LATIN.search(x["text"])]
        hits += [("changes", r["change"]) for r in self.C if LATIN.search(r["text_here"] + r["text_next"])]
        for pth in list((self.d / "lines").rglob("*.tsv")) + list((self.d / "layout").rglob("*.tsv")):
            _, rows = tsv(pth); hits += [(pth.name, r["key"]) for r in rows if LATIN.search(r["line"])]
        ch = []
        for c in self.outs: latin_walk(c, ch)
        self.cond("the Latin-letter check passes on every step file (texts, changes, lines, layout) and every card output (the card's top-level `name`, the step's code name, exempt)",
                  not hits and not ch, f"files {len(hits)} {hits[:3]}; card values {len(ch)} {ch[:3]} ({len(self.outs)} cards)")

    def rebuild(self, rebuild):
        cond = self.cond
        if not rebuild:
            cond("two stage-61 rebuilds give the same sha256", None, "skipped (--no-rebuild)"); return
        base = Path("/tmp/claude-1000/source-examples/ladder61"); n = 1
        while (base / f"rebuild-{n}").exists(): n += 1
        sums = []
        for k in (n, n + 1):
            o = base / f"rebuild-{k}"
            subprocess.run([sys.executable, "-I", str(MAC / "build_ladder.py"), "--build", self.d.name, "--stage", "61", "--out", str(o)],
                           check=True, capture_output=True)
            sums.append({str(p.relative_to(o)): sha(p) for p in o.rglob("*") if p.is_file()})
        mine = {k: sha(self.d / k) for k in sums[0] if (self.d / k).is_file()}
        diff = [k for k in sorted(set(sums[0]) | set(sums[1])) if not (sums[0].get(k) == sums[1].get(k) == mine.get(k))]
        cond("two stage-61 rebuilds give the same sha256 for every file they write (and equal the build)", not diff,
             f"{len(sums[0])} files; differ {diff[:5]} (scratch rebuild-{n}, rebuild-{n + 1})")

