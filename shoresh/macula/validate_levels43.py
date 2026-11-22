"""Exit conditions of stage 43 of the Hebrew levels (SPEC-levels 6, 7, 8, 9, 10). Called by validate_levels.py.

Imports nothing from the builders: the candidate sets, the reasons of R and A, rules AF, NF and IN, the measurements
and the anatomy are recomputed here by this file's own code from i1 and the built tables.
"""
import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[2]
I1 = REPO / "shoresh" / "macula" / "data" / "source-examples" / "i1"
BOOKS = ("GEN", "RUT", "JON")
TEXTS = ("hbo", "heb_mod", "heb_scg")
LEVELS = {"l0": TEXTS, "v2": TEXTS, "r": TEXTS, "rall": TEXTS, "a": ("hbo",), "v2_r": TEXTS, "v2_r_a": ("hbo",)}
SWITCHES = {"l0": (), "v2": ("v",), "r": ("r:amb",), "rall": ("r:all",), "a": ("a",), "v2_r": ("v", "r:amb"),
            "v2_r_a": ("v", "r:amb", "a")}
CONTENT = {"noun", "verb", "adj", "adv"}
FINITE = {"qatal", "wayyiqtol", "yiqtol", "weqatal", "imperative", "jussive", "cohortative"}
POINT_KEEP = {chr(c) for c in range(0x05B0, 0x05BD)} | {"\u05c1", "\u05c2", "\u05c7"}
LETTERS = {chr(c) for c in range(0x05D0, 0x05EB)}
GREEK = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
LATIN = re.compile(r"[A-Za-z_]+")
CLOSED_PATH = re.compile(r"(?i)[\w./-]*[/\\][\w./-]*(hebm95|tbta|bhsa)[\w./-]*|(hebm95|tbta|bhsa)[\w-]*\.(db|tsv|parquet|json|txt|zip|xml|csv)")
KEYLIKE = [re.compile(x) for x in (
    r"(heb_mod|heb_scg):\d+\.\d+", r"(lex|ntx):(hbo|arc|grc):\S+", r"\b[a-z_]+:e[0-9a-f]{10}\b", r"cl:\S+", r"op:\S+", r"cg:\S+", r"g:\d+[a-z]?",
    r"expl:\d+", r"\b[1-3A-Z]{3} \d+:\d+\b", r"(heb_mod|heb_scg):\d+\.\d+", r"\b[A-Z]{3}\.\d+\b")]


def closed(book, ch):
    return book in ("RUT", "JON") or (book, ch) in {("GEN", 22), ("LUK", 1), ("LUK", 2), ("LUK", 15), ("PHP", 3),
                                                    ("ACT", 1), ("MAT", 21)}


def vk(b, c, v):
    return f"{b} {c}:{v}"


def h256(p):
    d = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            d.update(b)
    return d.hexdigest()


def tsv(p):
    with open(p, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def pqr(p, cols=None):
    if cols:
        have = pq.ParquetFile(p).schema_arrow.names
        cols = [c for c in cols if c in have]
    return pq.read_table(p, columns=cols).to_pylist()


def E(who):
    return [x for x in (who or "").split() if x]


def gok(a, b):
    return a == b or (a in "cb" and b in "mfcb") or (b in "cb" and a in "mfcb")


def cons_form(s):
    s = unicodedata.normalize("NFD", s)
    out = []
    for ch in s:
        if unicodedata.category(ch) == "Mn":
            continue
        out.append(ch if ch in LETTERS or ch == " " else " ")
    return " ".join("".join(out).split())


def point_form(s):
    s = unicodedata.normalize("NFD", s)
    out = []
    for ch in s:
        if unicodedata.category(ch) == "Mn" and ch not in POINT_KEEP:
            continue
        out.append(ch if ch in LETTERS or ch in POINT_KEEP or ch == " " else " ")
    return " ".join("".join(out).split())


def nomarks(s):
    return "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")


# ------------------------------------------------------------------ i1, read by this file

class Src:
    def __init__(self, name):
        self.name = name
        self.w = {r["t"]: r for r in pqr(I1 / name / "words.parquet",
                                         ["t", "id", "book", "chapter", "verse", "text", "after", "clause", "sentence"])}
        self.p = defaultdict(list)
        for r in pqr(I1 / name / "pieces.parquet", ["t", "n", "text", "kind", "lexeme", "class", "marks", "fused",
                                                     "who", "who_basis", "sense", "domain", "basis"]):
            r["m"] = json.loads(r["marks"] or "{}")
            r.setdefault("basis", "")
            self.p[r["t"]].append(r)
        for t in self.p:
            self.p[t].sort(key=lambda r: r["n"])
        self.pp = {(q["t"], q["n"]): q for ps in self.p.values() for q in ps}
        self.cl = {}
        rank = []
        for i, c in enumerate(pqr(I1 / name / "clauses.parquet")):
            c["m"] = json.loads(c["marks"] or "{}")
            self.cl[c["clause"]] = c
            rank.append((c["first"], i, c["clause"]))
        self.corder = [c for _, _, c in sorted(rank)]
        self.crank = {c: i for i, c in enumerate(self.corder)}
        self.cons = defaultdict(list)
        for c in pqr(I1 / name / "constituents.parquet"):
            self.cons[c["clause"]].append(c)
        self.wa = pqr(I1 / name / "who_account.parquet")
        self.added = pqr(I1 / name / "added.parquet") if (I1 / name / "added.parquet").exists() else []
        self.passages = pqr(I1 / name / "passages.parquet")
        self.bycl = defaultdict(list)
        self.byverse = defaultdict(list)
        for t in sorted(self.w):
            if self.w[t]["clause"]:
                self.bycl[self.w[t]["clause"]].append(t)
            x = self.w[t]
            self.byverse[vk(x["book"], x["chapter"], x["verse"])].append(t)

    def stem(self, t):
        return next(q for q in self.p[t] if q["kind"] == "stem")


def strict(q):
    return q.get("basis", "") != "model"


def strict_who(q):
    return strict(q) and q["who_basis"] != "model" and bool(q["who"])


class Scope:
    def __init__(self, code, S):
        if code == "hbo":
            self.parts = {"hbo": S["hbo"], "arc": S["arc"]}
            self.order = [(pn, t) for _, pn, t in sorted((S[pn].w[t]["id"], pn, t) for pn in ("hbo", "arc")
                                                         for t in S[pn].w if S[pn].w[t]["book"] in BOOKS)]
        else:
            self.parts = {code: S[code]}
            self.order = [(code, t) for t in sorted(S[code].w)]
        self.part_of = {t: pn for pn, t in self.order}

    def w(self, t):
        return self.parts[self.part_of[t]].w[t]


# ------------------------------------------------------------------ AF and NF, this file's own

class Attested:
    def __init__(self, parts, strict_only=False, strip=False):
        self.by = defaultdict(list)
        for P in parts:
            for t in sorted(P.w):
                ps = P.p[t]
                if strict_only and not all(strict(q) for q in ps):
                    continue
                st = [q for q in ps if q["kind"] == "stem"][0]
                pre = [q for q in ps if q["kind"] == "prefix"]
                suf = [q for q in ps if q["kind"] == "suffix"]
                tx = P.w[t]["text"]
                tail = "".join(q["text"] for q in ps[len(pre):])
                if strip:
                    tx, tail = nomarks(tx), nomarks(tail)
                self.by[st["lexeme"]].append((tuple(q["lexeme"] for q in pre), st["m"],
                                              tuple((q["m"].get("person", ""), q["m"].get("gender", ""),
                                                     q["m"].get("number", "")) for q in suf),
                                              unicodedata.normalize("NFC", tx), unicodedata.normalize("NFC", tail),
                                              any(q["fused"] for q in ps), st["class"]))

    def pick(self, lx, want, suf, pre, step):
        c = Counter()
        for pl, m, sf, tx, tail, fu, _ in self.by.get(lx, ()):
            if sf != suf:
                continue
            ok = True
            for k, v in want.items():
                hv = m.get(k)
                if not hv or (not gok(v, hv) if k == "gender" else v != hv):
                    ok = False
                    break
            if not ok:
                continue
            if step == "whole":
                if pl == pre:
                    c[tx] += 1
            else:
                c[tail] += 1
        return min(c, key=lambda x: (-c[x], x)) if c else None


class AF:
    def __init__(self, S):
        tan = [S["hbo"], S["arc"]]
        t = Attested(tan)
        self.chain = {"hbo": [(t, "whole", "joined")],
                      "heb_mod": [(Attested([S["heb_mod"]], True), "whole", "joined"),
                                  (Attested(tan, strip=True), "whole_tanakh", "joined_tanakh")],
                      "heb_scg": [(Attested([S["heb_scg"]], True), "whole", "joined"), (t, "whole_tanakh", "joined_tanakh")]}

    def run(self, text, lx, want, suf, pre_pieces, fused):
        pre = tuple(q["lexeme"] for q in pre_pieces)
        for src, rw, rj in self.chain[text]:
            x = src.pick(lx, want, suf, pre, "whole")
            if x is not None:
                return rw, x
            if fused:
                continue
            x = src.pick(lx, want, suf, pre, "joined")
            if x is not None:
                return rj, "".join(q["text"] for q in pre_pieces) + x
        return None


def nf_index(P):
    idx = defaultdict(list)
    for t in sorted(P.w):
        ps = P.p[t]
        st = [q for q in ps if q["kind"] == "stem"][0]
        if st["class"] != "noun" or not strict_who(st) or st["m"].get("state", "abs") not in ("abs", ""):
            continue
        if any(q["kind"] == "suffix" or q["fused"] for q in ps):
            continue
        art = [q for q in ps if q["kind"] == "prefix" and q["class"] == "art"][-1:]
        txt = "".join(q["text"] for q in art + [st])
        for e in E(st["who"]):
            idx[e].append((st["m"].get("type") == "proper", txt, t, bool(art)))
    return idx


def nf(NF, ent, chain):
    for pn in chain:
        rows = NF[pn].get(ent)
        if not rows:
            continue
        for proper in (True, False):
            rs = [r for r in rows if r[0] == proper]
            if rs:
                c, first = Counter(r[1] for r in rs), {}
                for r in rs:
                    first.setdefault(r[1], r)
                best = min(c, key=lambda x: (-c[x], first[x][2]))
                return best, proper or first[best][3]
    return None


# ------------------------------------------------------------------ the checks

def run(R, B, root, a, levels_tsv):
    S = {n: Src(n) for n in ("hbo", "arc", "heb_mod", "heb_scg")}
    lev = {r["lexeme"]: r for r in levels_tsv}
    terms = tsv(I1 / "hbo" / "terms.tsv")
    kind_code = {r["hbo"]: r["code"] for r in terms if r["category"] == "added_kind"}
    af = AF(S)
    NF = {n: nf_index(S[n]) for n in S}
    dist = {(r["a"], r["b"]): r for r in pqr(B / "near" / "distance.parquet")}
    ops = pqr(B / "ops.parquet")
    for o in ops:
        o["_detail"] = json.loads(o["detail"])
    byLT = defaultdict(list)
    for o in ops:
        byLT[(o["level"], o["text"])].append(o)
    opk = {o["op"]: o for o in ops}
    D = {}
    R.section("stage 43: files")
    missing = []
    for lv, texts in LEVELS.items():
        for tx in texts:
            d = B / "texts" / lv / tx
            for f in ("words.parquet", "pieces.parquet", "links.parquet", "lexemes.tsv"):
                if not (d / f).exists():
                    missing.append(f"{lv}/{tx}/{f}")
            for form in ("cons", "point"):
                if not (B / "lines" / lv / f"{tx}.{form}.tsv").exists():
                    missing.append(f"lines/{lv}/{tx}.{form}")
    for f in ("ops.parquet", "changed_verses.tsv", "measures/kept.parquet", "measures/pair.parquet",
              "measures/reach.tsv", "measures/referents.parquet", "measures/referents_by_ent.tsv", "anatomy.parquet"):
        if not (B / f).exists():
            missing.append(f)
    extra_lt = sorted({(o["level"], o["text"]) for o in ops} - {(lv, tx) for lv, ts in LEVELS.items() for tx in ts})
    R.check("every level text, line file and table of stage 43 is there; no level built outside 6.1", not missing
            and not extra_lt, f"missing {missing[:5]}; extra {extra_lt}")
    if missing:
        return
    for lv, texts in LEVELS.items():
        for tx in texts:
            d = B / "texts" / lv / tx
            D[(lv, tx)] = (pqr(d / "words.parquet"), pqr(d / "pieces.parquet"), pqr(d / "links.parquet"))
    SC = {tx: Scope(tx, S) for tx in TEXTS}

    # -------- l0 byte for byte; draft words trace; links
    R.section("stage 43: level texts")
    bad = []
    for tx in TEXTS:
        W = D[("l0", tx)][0]
        src = [(SC[tx].w(t)["text"], SC[tx].w(t)["after"] if tx == "hbo" else "") for _, t in SC[tx].order]
        mine = [(w["text"], w["after"]) for w in W]
        if src != mine or any(w["op"] for w in W):
            bad.append(tx)
    R.check("l0 of every text equals the source byte for byte (words' text and after, in order; no op)", not bad,
            f"differ: {bad}")
    trace_bad, copy_bad, nolink, unreached, dt_bad = Counter(), Counter(), Counter(), Counter(), Counter()
    for (lv, tx), (W, P, K) in D.items():
        Sc = SC[tx]
        lk = defaultdict(list)
        for k in K:
            lk[(k["t"], k["n"])].append(k)
        pw = defaultdict(list)
        for p in P:
            pw[p["t"]].append(p)
        reached = set()
        for k in K:
            reached.add((k["other"], k["s"], k["s_n"]))
        for w in W:
            if w["op"]:
                o = opk.get(w["op"])
                if not o or o["state"] != "applied" or o["level"] != lv or o["text"] != tx or w["t"] not in json.loads(o["draft_t"]) and not any(
                        w["t"] in json.loads(x["draft_t"]) for x in byLT[(lv, tx)] if x["state"] == "applied"):
                    trace_bad[(lv, tx)] += 1
            else:
                ls = [k for p in pw[w["t"]] for k in lk[(p["t"], p["n"])]]
                srcs = {(k["other"], k["s"]) for k in ls}
                ok = len(srcs) == 1 and all(k["how"] == "copy" for k in ls)
                if ok:
                    pn, s = next(iter(srcs))
                    sw = S[pn].w[s]
                    sp = S[pn].p[s]
                    ok = (w["text"] == sw["text"] and len(pw[w["t"]]) == len(sp)
                          and all(p["text"] == q["text"] and p["lexeme"] == q["lexeme"] and p["who"] == q["who"]
                                  for p, q in zip(pw[w["t"]], sp)))
                    if tx == "hbo" and ok and w["after"] != sw["after"]:
                        ok = any(o["state"] == "applied" and o["src_t"] == s and o["rule"] in (
                            "r_subject", "r_object", "a_subject", "a_object") for o in byLT[(lv, tx)]) and w["after"] == " "
                if not ok:
                    copy_bad[(lv, tx)] += 1
        for p in P:
            if not lk.get((p["t"], p["n"])):
                nolink[(lv, tx)] += 1
        for pn, t in Sc.order:
            for q in S[pn].p[t]:
                if (pn, t, q["n"]) not in reached:
                    unreached[(lv, tx)] += 1
        for o in byLT[(lv, tx)]:
            if o["state"] == "applied":
                for t in json.loads(o["draft_t"]):
                    if not (1 <= t <= len(W)):
                        dt_bad[(lv, tx)] += 1
    R.check("every draft word with an op traces to an applied op row of its level and text that wrote it",
            not trace_bad, f"{sum(trace_bad.values())} words {dict(trace_bad)}")
    R.check("every draft word with no op is a copy of one source word (text, after, pieces, links `copy`)",
            not copy_bad, f"{sum(copy_bad.values())} words {dict(copy_bad)}")
    R.check("every applied op's draft_t exists", not dt_bad, f"{dict(dt_bad)}")
    R.check("every draft piece has a link; every source piece of the scope is reached", not nolink and not unreached,
            f"no link {dict(nolink)}; unreached {dict(unreached)}")

    # -------- candidate places and the switches
    R.section("stage 43: switch V (6.2)")
    v_cands = {}
    for tx in TEXTS:
        s = set()
        for pn, t in SC[tx].order:
            for q in S[pn].p[t]:
                r = lev.get(q["lexeme"])
                if (q["kind"] == "stem" and q["class"] in CONTENT and strict(q) and r and r["state"] not in ("name", "function")
                        and r["kind"] in ("explained", "unexplained") and r["level"] != "" and int(r["level"]) > 2):
                    s.add((t, q["n"]))
        v_cands[tx] = s
    bad_set, bad_ex, marks_bad, form_bad = [], Counter(), [], []
    per = Counter()
    for (lv, tx), os_ in byLT.items():
        if "v" not in SWITCHES[lv]:
            if any(o["switch"] == "v" for o in os_):
                bad_set.append((lv, tx, "v rows in a level without V"))
            continue
        vs = [o for o in os_ if o["switch"] == "v"]
        got = Counter((o["src_t"], o["src_n"]) for o in vs)
        if set(got) != v_cands[tx] or any(c != 1 for c in got.values()):
            bad_set.append((lv, tx, len(got), len(v_cands[tx])))
        W, P, K = D[(lv, tx)]
        pt = {(p["t"], p["n"]): p for p in P}
        pw = defaultdict(list)
        for p in P:
            pw[p["t"]].append(p)
        for o in vs:
            gen = "genesis" if tx == "hbo" and o["key"].startswith("GEN ") else "rest"
            per[(lv, tx, gen, o["state"], o["tier"] or o["reason"])] += 1
            if o["state"] != "applied":
                continue
            x, y = o["lexeme_before"], o["lexeme_after"]
            ry, rx = lev.get(y), lev.get(x)
            g = "d0" if x == y else (dist.get((min(x, y), max(x, y))) or {}).get("grade", "d6")
            if not (ry and ry["level"] != "" and int(ry["level"]) <= 2 and ry["class"] == rx["class"]
                    and ry["lang"] == rx["lang"] and g in ("d2", "d3") and g == o["grade"]):
                bad_ex[(lv, tx)] += 1
            pn = SC[tx].part_of[o["src_t"]]
            sps = S[pn].p[o["src_t"]]
            sst = S[pn].stem(o["src_t"])
            t = json.loads(o["draft_t"])[0]
            w = W[t - 1]
            dst = [p for p in pw[t] if p["kind"] == "stem"]
            if w["op"] != o["op"]:
                continue   # rewritten by R (r_construct over V, 6.9); R's checks cover it
            dm = json.loads(dst[0]["marks"]) if dst else {}
            for k in ("gender", "number", "state", "person", "type", "stem"):
                v = sst["m"].get(k)
                if v and not (dm.get(k) and (gok(v, dm[k]) if k == "gender" else v == dm[k])):
                    marks_bad.append((o["op"], k, v, dm.get(k)))
            want = {k: sst["m"][k] for k in ("type", "stem", "person", "gender", "number", "state") if sst["m"].get(k)}
            pre = [q for q in sps if q["kind"] == "prefix"]
            suf = tuple((q["m"].get("person", ""), q["m"].get("gender", ""), q["m"].get("number", ""))
                        for q in sps if q["kind"] == "suffix")
            mine = None
            for src, rw, rj in af.chain[tx]:
                if o["form_rule"] == rw:
                    xx = src.pick(y, want, suf, tuple(q["lexeme"] for q in pre), "whole")
                    mine = xx
                elif o["form_rule"] == rj:
                    xx = src.pick(y, want, suf, (), "joined")
                    mine = "".join(q["text"] for q in pre) + xx if xx is not None else None
            if mine is None or unicodedata.normalize("NFC", w["text"]) != unicodedata.normalize("NFC", mine):
                form_bad.append((o["op"], o["form_rule"]))
    R.check("V: every candidate place (strict content piece, level 3 or 4, explained or unexplained) has exactly one op row",
            not bad_set, f"{bad_set[:4]}")
    R.check("V: every applied op's lexeme_after has level <= 2, the class and lang of lexeme_before, grade d2 or d3",
            not bad_ex, f"{dict(bad_ex)}")
    R.check("V: every applied form is attested as form_rule says (recomputed: the commonest attested form)",
            not form_bad, f"{len(form_bad)} {form_bad[:4]}")
    R.check("V agreement: the draft piece's marks agree with the source piece's (gender, number, state, person, type, stem)",
            not marks_bad, f"{len(marks_bad)} disagreements {marks_bad[:4]}")
    R.info("V per text, Genesis apart (level, text, scope, state, tier or reason: places)",
           "; ".join(f"{k[0]}/{k[1]}/{k[2]}/{k[3]}/{k[4]}: {v}" for k, v in sorted(per.items())))

    # -------- R
    R.section("stage 43: switch R (6.3)")
    catch = {}
    for pn, P in S.items():
        c = set()
        for r in P.wa:
            if r["state"] == "generic":
                q = P.pp.get((r["t"], r["n"]))
                if q and len(E(q["who"])) == 1:
                    c.add(E(q["who"])[0])
        catch[pn] = c
    r_c = {}
    for tx in TEXTS:
        rows = []
        for pn, P in SC[tx].parts.items():
            scope = {t for p_, t in SC[tx].order if p_ == pn}
            for r in P.wa:
                if r["t"] in scope and r["head_kind"] in ("pronoun", "suffix", "verb_zero") and r["state"] == "participant":
                    q = P.pp[(r["t"], r["n"])]
                    if q["m"].get("person") == "3":
                        rows.append((pn, r, q))
        r_c[tx] = rows
    set_bad, reason_bad, ent_bad, subj_dis, pron_dis, cstr_bad, obj_bad = [], Counter(), [], [], [], [], []
    perR = Counter()
    ex_reason = []
    free_bad = []
    for (lv, tx), os_ in byLT.items():
        sw = [s for s in SWITCHES[lv] if s.startswith("r:")]
        rs = [o for o in os_ if o["switch"] == "r"]
        if not sw:
            if rs:
                set_bad.append((lv, tx, "r rows in a level without R"))
            continue
        setting = sw[0][2:]
        got = Counter((o["src_t"], o["src_n"]) for o in rs)
        want = {(r["t"], r["n"]) for _, r, _ in r_c[tx]}
        if set(got) != want or any(c != 1 for c in got.values()):
            set_bad.append((lv, tx, len(got), len(want)))
        oi = {(o["src_t"], o["src_n"]): o for o in rs}
        W, P, K = D[(lv, tx)]
        pw = defaultdict(list)
        for p in P:
            pw[p["t"]].append(p)
        vrep = {o["src_t"] for o in os_ if o["switch"] == "v" and o["state"] == "applied"}
        for pn, r, q in r_c[tx]:
            o = oi.get((r["t"], r["n"]))
            if o is None:
                continue
            Pt = S[pn]
            es = E(q["who"])
            model = r.get("basis") == "model" or not strict(q) or q["who_basis"] == "model"
            if r["head_kind"] == "suffix" and not strict(Pt.stem(r["t"])):
                model = True
            # the window (D-6), own code
            cands = set()
            cl = Pt.w[r["t"]]["clause"]
            if cl and cl in Pt.crank and not model:
                i = Pt.crank[cl]
                hg, hn = q["m"].get("gender", ""), q["m"].get("number", "")
                for c in Pt.corder[max(0, i - 2): i + 1]:
                    for wt in Pt.bycl.get(c, ()):
                        for z in Pt.p[wt]:
                            if z["kind"] == "stem" and z["class"] == "noun" and strict_who(z):
                                g, n = z["m"].get("gender", ""), z["m"].get("number", "")
                                if g and n and (not hg or gok(hg, g)) and (not hn or hn == n):
                                    cands |= {e for e in E(z["who"]) if e not in es}
            named = bool(cl) and len(es) == 1 and any(
                z["kind"] == "stem" and z["class"] == "noun" and strict_who(z) and es[0] in E(z["who"])
                for wt in Pt.bycl.get(cl, ()) for z in Pt.p[wt])
            reason = ""
            if model:
                reason = "model_input"
            elif len(es) != 1:
                reason = "several_referents"
            elif es[0] in catch[pn]:
                reason = "catch_all"
            elif named:
                reason = "named_in_clause"
            elif setting == "amb" and not cands:
                reason = "not_ambiguous"
            if not reason:
                chain = ("arc", "hbo") if pn == "arc" else (pn,)
                name = nf(NF, es[0], chain)
                hk = r["head_kind"]
                st = Pt.stem(r["t"])
                if hk == "suffix":
                    stc = st["class"]
                    ty = st["m"].get("type", "")
                    if r["t"] in vrep:   # V wrote the host: its class stays (V keeps the class)
                        pass
                    host = ("prep" if stc in ("prep", "om") else "noun" if stc == "noun" else
                            "finite" if stc == "verb" and ty in FINITE else
                            "host_infinitive" if stc == "verb" and ty.startswith("infinitive") else
                            "host_participle" if stc == "verb" and ty.startswith("participle") else "host_other")
                else:
                    host = hk
                if name is None:
                    reason = "no_name_form"
                elif host == "finite" and not name[1]:
                    reason = "indefinite"
                elif host.startswith("host_"):
                    reason = host
            if o["state"] == "applied":
                if reason or o["reason"]:
                    reason_bad[(lv, tx, reason or "?", "applied")] += 1
            elif o["reason"] != reason and not (reason == "" and o["reason"] == "form_unattested"):
                reason_bad[(lv, tx, reason or "applicable", o["reason"])] += 1
                if len(ex_reason) < 6:
                    ex_reason.append((o["op"], reason, o["reason"]))
            if json.loads(o["detail"]) != sorted(cands):
                reason_bad[(lv, tx, "window", "detail")] += 1
            gen = "genesis" if tx == "hbo" and o["key"].startswith("GEN ") else "rest"
            perR[(lv, tx, gen, o["state"], o["rule"] or o["reason"])] += 1
            if o["state"] != "applied":
                continue
            dts = json.loads(o["draft_t"])
            newp = [p for t in dts for p in pw[t] if p["who_basis"] == "inserted"]
            if not newp or any(p["who"] != es[0] or o["ent"] != es[0] for p in newp):
                ent_bad.append(o["op"])
            if o["rule"] in ("r_subject",):
                vm = q["m"]
                st_new = [p for p in newp if p["kind"] == "stem"]
                nm = json.loads(st_new[0]["marks"]) if st_new else {}
                if not (gok(vm.get("gender", nm.get("gender", "")), nm.get("gender", vm.get("gender", "")))
                        and (not vm.get("number") or not nm.get("number") or vm["number"] == nm["number"])):
                    subj_dis.append((o["op"], o["key"], vm.get("gender", ""), vm.get("number", ""),
                                     nm.get("gender", ""), nm.get("number", "")))
                nmw = nf(NF, es[0], ("arc", "hbo") if pn == "arc" else (pn,))
                if not nmw or W[dts[0] - 1]["text"] != nmw[0]:
                    ent_bad.append(o["op"] + ":nf")
            if o["rule"] == "r_pronoun":
                st_new = [p for p in newp if p["kind"] == "stem"]
                nm = json.loads(st_new[0]["marks"]) if st_new else {}
                if not (gok(q["m"].get("gender", nm.get("gender", "")), nm.get("gender", q["m"].get("gender", "")))
                        and (not q["m"].get("number") or not nm.get("number") or q["m"]["number"] == nm["number"])):
                    pron_dis.append((o["op"], o["key"]))
            if o["rule"] == "r_construct":
                st0 = [p for p in pw[dts[0]] if p["kind"] == "stem"]
                if not st0 or json.loads(st0[0]["marks"]).get("state") != "cstr" or any(
                        p["kind"] == "suffix" for p in pw[dts[0]]):
                    cstr_bad.append(o["op"])
            if o["rule"] == "r_prep_free":   # stage 44: the free form stands as a bare word of its lexeme (6.3)
                fst = [p for p in pw[dts[0]] if p["kind"] == "stem"]
                fx = nomarks("".join(p["text"] for p in fst))
                if not fst or not any(pl == () and sf == () and nomarks(tx_) == fx
                                      for src, _, _ in af.chain[tx] for pl, _m, sf, tx_, _t, _f, _c
                                      in src.by.get(fst[0]["lexeme"], ())):
                    free_bad.append((o["op"], o["key"], fx))
            if o["rule"] == "r_object":
                om = [p for p in pw[dts[0]] if p["kind"] == "stem"]
                name = nf(NF, es[0], ("arc", "hbo") if pn == "arc" else (pn,))
                if not om or om[0]["class"] != "om" or not name or not name[1] or W[dts[1] - 1]["text"] != name[0]:
                    obj_bad.append(o["op"])
    R.check("R: every candidate place (3rd-person pronoun, suffix, zero subject with a participant) has exactly one op row",
            not set_bad, f"{set_bad[:4]}")
    R.check("R: the window, the ambiguity and every reason recomputed by this file's own code equal the op rows",
            not reason_bad, f"{sum(reason_bad.values())} {sorted(reason_bad.items())[:6]} e.g. {ex_reason[:3]}")
    R.check("R: every applied op's new name pieces carry exactly the head's ent (and the name form of NF)",
            not ent_bad, f"{len(ent_bad)} {ent_bad[:4]}")
    R.check("R: the construct form under r_construct has state cstr and no suffix", not cstr_bad, f"{cstr_bad[:4]}")
    R.check("R: every r_prep_free free form stands in the form source as a bare word of its lexeme (no lone ל, ב, כ)",
            not free_bad, f"{len(free_bad)} {free_bad[:4]}")
    R.check("R: after r_object the inserted pair is the object marker and a definite name form", not obj_bad,
            f"{obj_bad[:4]}")
    R.info("R agreement: r_subject names whose gender or number differ from the verb's (applied, listed, not hidden)",
           f"{len(subj_dis)}: {subj_dis[:12]}")
    R.info("R agreement: r_pronoun names whose gender or number differ from the pronoun's", f"{len(pron_dis)}: {pron_dis[:12]}")
    R.info("R per text, Genesis apart", "; ".join(f"{k[0]}/{k[1]}/{k[2]}/{k[3]}/{k[4]}: {v}" for k, v in sorted(perR.items())))

    # -------- A
    R.section("stage 43: switch A (6.4)")
    a_bad, a_reason, a_dis, a_who = [], Counter(), [], []
    perA = Counter()
    for (lv, tx), os_ in byLT.items():
        As = [o for o in os_ if o["switch"] == "a"]
        if "a" not in SWITCHES[lv]:
            if As:
                a_bad.append((lv, tx, "a rows outside A"))
            continue
        Sc = SC[tx]
        rows = []
        for pn, P in Sc.parts.items():
            scope = {t for p_, t in Sc.order if p_ == pn}
            for r in P.added:
                if r["verb"] in scope and kind_code.get(r["kind"]) in ("in_verb", "elsewhere"):
                    rows.append((pn, r))
        key = lambda pn, r: (r["verb"], r["clause"], r["role"])
        got = Counter((o["src_t"], o["added_clause"], o["added_role"]) for o in As)
        want = {key(pn, r) for pn, r in rows}
        if set(got) != want or any(c != 1 for c in got.values()):
            a_bad.append((lv, tx, len(got), len(want)))
        oi = {(o["src_t"], o["added_clause"], o["added_role"]): o for o in As}
        rsub = {o["src_t"] for o in os_ if o["switch"] == "r" and o["state"] == "applied" and o["rule"] == "r_subject"}
        W, P, K = D[(lv, tx)]
        pw = defaultdict(list)
        for p in P:
            pw[p["t"]].append(p)
        for pn, r in rows:
            o = oi.get(key(pn, r))
            if o is None:
                continue
            Pt = S[pn]
            es = E(r["who"])
            st = Pt.stem(r["verb"])
            caus = st["m"].get("stem", "") in ("hiphil", "haphel", "aphel", "shaphel")
            has_aa = any(x["verb"] == r["verb"] and x["clause"] == r["clause"] and x["role"] == "AA"
                         for x in Pt.added if x["verb"] == r["verb"]) or any(
                "AA" in re.split(r"[^A-Za-z0-9]+", c["frame_role"] or "") for c in Pt.cons.get(r["clause"], ()))
            subj = r["role"] == ("AA" if caus and has_aa else "A0")
            said = any(set(E(z["who"])) & set(es) for wt in Pt.bycl.get(r["clause"], ()) if wt != r["verb"]
                       for z in Pt.p[wt])
            reason = ""
            if r.get("own_basis") == "model":
                reason = "model_input"
            elif not es:
                reason = "no_who"
            elif len(es) > 1:
                reason = "several_referents"
            elif r["person"] in ("1", "2"):
                reason = "person_1_2"
            elif said:
                reason = "said_in_clause"
            elif subj and r["verb"] in rsub:
                reason = "taken_by_r"
            elif not subj and r["role"] != "A1":
                reason = "role_other"
            else:
                name = nf(NF, es[0], ("arc", "hbo") if pn == "arc" else (pn,))
                if name is None:
                    reason = "no_name_form"
                elif not subj and not name[1]:
                    reason = "indefinite"
            if (o["state"] == "applied") != (reason == "") or (reason and o["reason"] != reason):
                a_reason[(lv, reason or "applicable", o["reason"] or "applied")] += 1
            gen = "genesis" if o["key"].startswith("GEN ") else "rest"
            perA[(lv, gen, o["state"], r["role"], o["rule"] or o["reason"])] += 1
            if o["state"] == "applied":
                if said:
                    a_bad.append((o["op"], "said"))
                dts = json.loads(o["draft_t"])
                newp = [p for t in dts for p in pw[t] if p["who_basis"] == "inserted"]
                if not newp or any(p["who"] != es[0] for p in newp):
                    a_who.append(o["op"])
                if o["rule"] == "a_subject":
                    nm = json.loads([p for p in newp if p["kind"] == "stem"][0]["marks"])
                    vg, vn = r["gender"] or st["m"].get("gender", ""), r["number"] or st["m"].get("number", "")
                    if not ((not vg or not nm.get("gender") or gok(vg, nm["gender"]))
                            and (not vn or not nm.get("number") or vn == nm["number"])):
                        a_dis.append((o["op"], o["key"], vg, vn, nm.get("gender", ""), nm.get("number", "")))
    R.check("A: every candidate (added rows in_verb, elsewhere) has exactly one op row; none applied that its clause says",
            not a_bad, f"{a_bad[:4]}")
    R.check("A: every reason recomputed by this file's own code equals the op row", not a_reason,
            f"{sorted(a_reason.items())[:6]}")
    R.check("A: every applied op's new pieces carry the added row's who", not a_who, f"{a_who[:4]}")
    R.info("A agreement: inserted subjects whose gender or number differ from the verb's (applied, listed, not hidden)",
           f"{len(a_dis)}: {a_dis[:12]}")
    R.info("A per level, Genesis apart (level, scope, state, role, rule or reason)",
           "; ".join(f"{k[0]}/{k[1]}/{k[2]}/{k[3]}/{k[4]}: {v}" for k, v in sorted(perA.items())))

    # -------- ops: keys, sort, scoring_closed
    R.section("stage 43: the log, lines, changed verses")
    srt = sorted(ops, key=lambda o: (o["level"], o["text"], o["src_t"], o["src_n"], o["switch"]))
    sorted_ok = [(o["level"], o["text"], o["src_t"], o["src_n"], o["switch"]) for o in ops] == \
                [(o["level"], o["text"], o["src_t"], o["src_n"], o["switch"]) for o in srt]
    keys_ok = all(o["op"] == f"op:{o['level']}:{o['text']}:{i}" for (lt), os_ in byLT.items()
                  for i, o in enumerate(os_, 1))
    sc_bad = [o["op"] for o in ops if o["scoring_closed"] != closed(o["key"].split()[0], int(o["key"].split()[1].split(":")[0]))]
    key_bad = [o["op"] for o in ops if not re.fullmatch(r"[1-3A-Z]{3} \d+:\d+", o["key"])]
    R.check("ops: sorted by (level, text, src_t, src_n, switch); keys op:<level>:<text>:<n> in that order; keys BOOK ch:v",
            sorted_ok and keys_ok and not key_bad, f"sorted {sorted_ok}, keys {keys_ok}, bad verse keys {len(key_bad)}")
    R.check("ops: scoring_closed on every row, true exactly on the verses of 7.4", not sc_bad, f"{len(sc_bad)} {sc_bad[:3]}")
    cv = tsv(B / "changed_verses.tsv")
    cvset = {(r["level"], r["text"], r["key"]) for r in cv}
    want_cv = defaultdict(set)
    for o in ops:
        if o["state"] == "applied":
            want_cv[(o["level"], o["text"], o["key"])].add(o["switch"])
    cv_ok = cvset == set(want_cv) and all(json.loads(r["switches"]) == sorted(want_cv[(r["level"], r["text"], r["key"])])
                                          for r in cv)
    R.check("changed_verses.tsv: one row per (level, text, verse) with an applied op, its switches", cv_ok,
            f"{len(cvset)} rows, {len(want_cv)} recomputed")
    line_bad = Counter()
    gen_lines = Counter()
    for lv, texts in LEVELS.items():
        for tx in texts:
            W = D[(lv, tx)][0]
            raw, order = defaultdict(list), []
            for w in W:
                k = vk(w["book"], w["chapter"], w["verse"])
                if k not in raw:
                    order.append(k)
                raw[k].append(w["text"] + w["after"] if tx == "hbo" else w["text"])
            src_raw, src_order = defaultdict(list), []
            for pn, t in SC[tx].order:
                x = SC[tx].w(t)
                k = vk(x["book"], x["chapter"], x["verse"])
                if k not in src_raw:
                    src_order.append(k)
                src_raw[k].append(x["text"] + x["after"] if tx == "hbo" else x["text"])
            files = {}
            for form in ("cons", "point"):
                rows = tsv(B / "lines" / lv / f"{tx}.{form}.tsv")
                files[form] = rows
                fn = cons_form if form == "cons" else point_form
                j = "" if tx == "hbo" else " "
                if [r["key"] for r in rows] != src_order or [r["key"] for r in rows] != order:
                    line_bad[(lv, tx, form, "verses")] += 1
                for r in rows:
                    k = r["key"]
                    b, cv_ = k.split()[0], k.split()[1]
                    ch = int(cv_.split(":")[0])
                    if r["text"] != tx or r["level"] != lv or r["form"] != form:
                        line_bad[(lv, tx, form, "names")] += 1
                    if not re.fullmatch(r"[1-3A-Z]{3} \d+:\d+", k):
                        line_bad[(lv, tx, form, "key")] += 1
                    if r["scoring_closed"] != ("true" if closed(b, ch) else "false"):
                        line_bad[(lv, tx, form, "scoring_closed")] += 1
                    if r["changed"] != ("true" if (lv, tx, k) in cvset else "false"):
                        line_bad[(lv, tx, form, "changed")] += 1
                    s = r["line"]
                    allowed = LETTERS | {" "} | (POINT_KEEP if form == "point" else set())
                    if not s or any(ch_ not in allowed for ch_ in s):
                        line_bad[(lv, tx, form, "charset")] += 1
                    if "  " in s or s != s.strip():
                        line_bad[(lv, tx, form, "spaces")] += 1
                    if s != fn(j.join(raw.get(k, []))):
                        line_bad[(lv, tx, form, "rule IN")] += 1
                    if lv == "l0" and s != fn(j.join(src_raw[k])):
                        line_bad[(lv, tx, form, "l0 != source")] += 1
                    if tx == "hbo" and b == "GEN":
                        gen_lines[(lv, form)] += 1
            if tx == "heb_mod" and [r["line"] for r in files["cons"]] != [r["line"] for r in files["point"]]:
                line_bad[(lv, tx, "point", "point != cons")] += 1
    R.check("lines: one row per verse of the scope in every file, text order, none empty; key BOOK ch:v; the text and level "
            "named on every line; scoring_closed by 7.4; changed exactly on changed_verses", not any(
                k[3] in ("verses", "names", "key", "scoring_closed", "changed") for k in line_bad),
            f"{sorted((k, v) for k, v in line_bad.items() if k[3] in ('verses', 'names', 'key', 'scoring_closed', 'changed'))[:5]}")
    R.check("lines: cons holds only U+05D0-U+05EA and the space; point only those and U+05B0-U+05BC, U+05C1, U+05C2, "
            "U+05C7; no double, leading or trailing space", not any(k[3] in ("charset", "spaces") for k in line_bad),
            f"{sorted((k, v) for k, v in line_bad.items() if k[3] in ('charset', 'spaces'))[:5]}")
    R.check("lines: every line equals rule IN applied to its level text; l0 equals rule IN applied to i1 directly; "
            "heb_mod point = cons", not any(k[3] in ("rule IN", "l0 != source", "point != cons") for k in line_bad),
            f"{sorted((k, v) for k, v in line_bad.items() if k[3] in ('rule IN', 'l0 != source', 'point != cons'))[:5]}")
    nl = {tx: len(tsv(B / "lines" / "l0" / f"{tx}.cons.tsv")) for tx in TEXTS}
    R.info("verse lines per text (expected 1,666 / 7,947 / 7,957)", f"{nl}; Genesis lines per level {gen_lines[('l0','cons')]}")

    # -------- measurements
    R.section("stage 43: measurements 1, 2, 4, 5 (recomputed by this file's own code)")
    measures(R, B, S, SC, D, ops, byLT, lev, dist)
    # -------- anatomy
    R.section("stage 43: the error-anatomy join table")
    anat = pqr(B / "anatomy.parquet", ["text", "t", "n", "changed_in", "ops", "scoring_closed", "key", "lexeme", "level"])
    want_keys = [(tx, t, q["n"]) for tx in TEXTS for pn, t in sorted(SC[tx].order, key=lambda x: x[1])
                 for q in S[pn].p[t]]
    want_keys.sort()
    have_keys = [(r["text"], r["t"], r["n"]) for r in anat]
    reach = defaultdict(set)
    for (lv, tx), (W, P, K) in D.items():
        pop = {(p["t"], p["n"]): p["op"] for p in P}
        for k in K:
            if pop[(k["t"], k["n"])]:
                reach[(tx, k["s"], k["s_n"])].add(lv)
    ch_bad = sum(1 for r in anat if json.loads(r["changed_in"]) != sorted(reach.get((r["text"], r["t"], r["n"]), ())))
    lv_bad = sum(1 for r in anat if (lev.get(r["lexeme"], {}).get("level", "") or None) != (
        str(r["level"]) if r["level"] is not None else None))
    R.check("anatomy: one row per source piece of the scope, sorted (text, t, n); changed_in recomputed from the drafts; "
            "level as words/levels.tsv", have_keys == want_keys and ch_bad == 0 and lv_bad == 0,
            f"{len(have_keys)} rows, {len(want_keys)} pieces; changed_in differ {ch_bad}; level differ {lv_bad}")
    return {"ops": ops, "cv": cv}


def measures(R, B, S, SC, D, ops, byLT, lev, dist):
    # measurement 4
    cnt = Counter()
    for o in ops:
        sc = ["all"] + (["genesis"] if o["text"] == "hbo" and o["key"].startswith("GEN ") else []) + (
            [] if o["scoring_closed"] else ["open"])
        for s in sc:
            cnt[(o["level"], o["text"], o["switch"], o["setting"], s, o["state"], o["reason"])] += 1
    reach = tsv(B / "measures" / "reach.tsv")
    have = {(r["level"], r["text"], r["switch"], r["setting"], r["scope"], r["state"], r["reason"]): int(r["places"])
            for r in reach}
    R.check("measurement 4 (reach.tsv) equals the SQL of 8.4 recomputed from ops", have == dict(cnt),
            f"{len(have)} rows, {len(cnt)} recomputed")
    # measurement 1
    kept = pqr(B / "measures" / "kept.parquet")
    gw = pqr(I1 / "grc" / "words.parquet", ["t", "clause"])
    gcl = {r["t"]: r["clause"] for r in gw}
    gents = defaultdict(set)
    for r in pqr(I1 / "grc" / "pieces.parquet", ["t", "who"]):
        if r["who"] and gcl.get(r["t"]):
            gents[gcl[r["t"]]].update(r["who"].split())
    mine = {}
    for (lv, tx), os_ in byLT.items():
        if lv == "l0":
            continue
        W, P, K = D[(lv, tx)]
        Sc = SC[tx]
        dp = {(p["t"], p["n"]): p for p in P}
        rch = defaultdict(list)
        rt = defaultdict(set)
        for k in K:
            rch[(k["other"], k["s"], k["s_n"])].append(dp[(k["t"], k["n"])])
            rt[(k["other"], k["s"])].add(k["t"])
        wcl = defaultdict(set)
        wop = {}
        for w in W:
            wop[w["t"]] = w["op"]
        for p in P:
            wcl[W[p["t"] - 1]["clause"]].update(E(p["who"]))
        app = [o for o in os_ if o["state"] == "applied"]
        aent = defaultdict(set)
        for o in app:
            if o["switch"] == "a":
                aent[o["added_clause"]].update(E(o["ent"]))
        vok = {(o["src_t"], o["src_n"]) for o in app if o["switch"] == "v" and o["grade"] in ("d2", "d3")}
        cls = set()
        for o in app:
            pn = Sc.part_of[o["src_t"]]
            for c in (S[pn].w[o["src_t"]]["clause"], o["added_clause"]):
                if c:
                    cls.add((pn, c))
        for pn, c in cls:
            P_ = S[pn]
            sp = [q for t in P_.bycl.get(c, ()) for q in P_.p[t]]
            cov = all(rch.get((pn, q["t"], q["n"])) for q in sp)
            ws = {e for q in sp for e in E(q["who"])}
            wd = wcl.get(c, set())
            wk = ws <= wd and (wd - ws) <= aent.get(c, set())
            rk = True
            for con in P_.cons.get(c, ()):
                Dc = set()
                for s in range(con["first"], con["last"] + 1):
                    Dc |= rt.get((pn, s), set())
                if Dc and any(x not in Dc and wop[x] == "" for x in range(min(Dc), max(Dc) + 1)):
                    rk = False
            cl = P_.cl.get(c)
            ev = True
            if cl and cl["pred"]:
                st = P_.stem(cl["pred"])
                ev = any(d["kind"] == "stem" and (d["lexeme"] == st["lexeme"] or (st["t"], st["n"]) in vok)
                         for d in rch.get((pn, st["t"], st["n"]), ()))
            lk = True
            if cl:
                neg, con_ = cl["m"].get("negator") or "", cl["m"].get("connective") or []
                lk = all(any(d["lexeme"] == q["lexeme"] for d in rch.get((pn, q["t"], q["n"]), ()))
                         for q in sp if q["lexeme"] and (q["lexeme"] == neg or q["lexeme"] in con_))
            an = True
            if tx != "hbo" and cl and cl.get("from_clause"):
                an = (gents.get(cl["from_clause"], set()) & ws) <= wd
            mine[(lv, tx, c)] = (cov, wk, rk, ev, lk, an, cov and wk and rk and ev and lk and an)
    hk = {(r["level"], r["text"], r["clause"]): (r["covered"], r["who_kept"], r["roles_kept"], r["event_kept"],
                                                 r["links_kept"], r["anchor_kept"], r["ok"]) for r in kept}
    R.check("measurement 1 (kept.parquet) equals the SQL of 8.1 recomputed: one row per clause with an applied op",
            hk == mine, f"{len(hk)} rows, {len(mine)} recomputed, {sum(1 for k in hk if hk.get(k) != mine.get(k))} differ")
    fails = defaultdict(Counter)
    for k, v in mine.items():
        for name, x in zip(("covered", "who_kept", "roles_kept", "event_kept", "links_kept", "anchor_kept"), v):
            if not x:
                fails[(k[0], k[1])][name] += 1
    okshare = Counter()
    for k, v in mine.items():
        okshare[(k[0], k[1], v[6])] += 1
    R.info("measurement 1 per (level, text): clauses checked, ok share, failures by check",
           "; ".join(f"{lv}/{tx}: {okshare[(lv, tx, True)] + okshare[(lv, tx, False)]} clauses, ok "
                     f"{okshare[(lv, tx, True)] / max(1, okshare[(lv, tx, True)] + okshare[(lv, tx, False)]):.3f}"
                     f"{', fail ' + str(dict(fails[(lv, tx)])) if fails[(lv, tx)] else ''}"
                     for lv, tx in sorted({(k[0], k[1]) for k in mine})))
    failing = sorted(k for k, v in mine.items() if not v[6])
    R.info("measurement 1: every failing clause (level, text, clause)", f"{len(failing)}: {failing}")
    # measurement 2
    pair = pqr(B / "measures" / "pair.parquet")
    lk = {}
    for e in ("heb_mod", "heb_scg"):
        m = defaultdict(set)
        for r in pqr(I1 / e / "links.parquet", ["t", "n", "other", "s", "basis"]):
            if r["other"] == "grc" and r["basis"] == "linked":
                m[(r["t"], r["n"])].add(r["s"])
        lk[e] = m

    def Sset(e, lv):
        W, P, K = D[(lv, e)]
        dp = {(p["t"], p["n"]): p for p in P}
        out, ed = defaultdict(set), set()
        for k in K:
            gs = lk[e].get((k["s"], k["s_n"]))
            if not gs:
                continue
            d = dp[(k["t"], k["n"])]
            r = lev.get(d["lexeme"])
            if d["kind"] == "stem" and r and r["class"] in CONTENT and r["state"] not in ("name", "function"):
                for g in gs:
                    out[g].add(d["lexeme"])
            if d["op"]:
                ed |= gs
        return out, ed

    def st(a, b):
        if a == b:
            return "same"
        if a & b:
            return "overlap"
        if any((dist.get((min(x, y), max(x, y))) or {}).get("grade_strict") in ("d2", "d3") for x in a for y in b):
            return "near"
        return "disjoint"

    b0 = {e: Sset(e, "l0")[0] for e in ("heb_mod", "heb_scg")}
    gs = sorted(set(b0["heb_mod"]) & set(b0["heb_scg"]))
    mine2 = []
    for lv in ("l0", "v2", "r", "rall", "v2_r"):
        sm, em = Sset("heb_mod", lv)
        ss, es = Sset("heb_scg", lv)
        for g in gs:
            mine2.append((lv, g, json.dumps([e for e, x in (("heb_mod", em), ("heb_scg", es)) if g in x]),
                          st(b0["heb_mod"][g], b0["heb_scg"][g]), st(sm.get(g, set()), b0["heb_scg"][g]),
                          st(b0["heb_mod"][g], ss.get(g, set())), st(sm.get(g, set()), ss.get(g, set()))))
    have2 = [(r["level"], r["g"], json.dumps(json.loads(r["edited"])), r["state_l0"], r["state_mod"], r["state_scg"],
              r["state_both"]) for r in pair]
    R.check("measurement 2 (pair.parquet) equals the SQL of 8.2 recomputed", sorted(have2) == sorted(mine2),
            f"{len(have2)} rows, {len(mine2)} recomputed")
    trans = Counter()
    lost = []
    for r in mine2:
        for name, x in (("mod", r[4]), ("scg", r[5]), ("both", r[6])):
            trans[(r[0], name, r[3], x)] += 1
            if r[3] in ("same", "overlap") and x in ("near", "disjoint") and name in ("mod", "scg"):
                lost.append((r[0], name, r[1], r[3], x))
    l0n = Counter(r[3] for r in mine2 if r[0] == "l0")
    R.info("measurement 2: the noise floor (l0 disjoint share)", f"{l0n['disjoint'] / max(1, sum(l0n.values())):.3f} of {sum(l0n.values())}")
    R.info("measurement 2: transitions state_l0 -> state (level, edition, from, to: Greek words)",
           "; ".join(f"{k[0]}/{k[1]}/{k[2]}->{k[3]}: {v}" for k, v in sorted(trans.items()) if k[0] != "l0" and k[2] != k[3]))
    R.info("measurement 2: lost under state_mod and state_scg, place by place (level, edition, g, from, to)",
           f"{len(lost)}: {lost}")
    # participants as a pair
    fc = {e: {c: r.get("from_clause", "") for c, r in S[e].cl.items()} for e in ("heb_mod", "heb_scg")}
    shared = {}
    for lv in ("l0", "v2", "r", "rall", "v2_r"):
        m = {}
        for e in ("heb_mod", "heb_scg"):
            W, P, K = D[(lv, e)]
            x = defaultdict(set)
            for p in P:
                g = fc[e].get(W[p["t"] - 1]["clause"], "")
                if g:
                    x[g].update(E(p["who"]))
            m[e] = x
        shared[lv] = {g: m["heb_mod"][g] & m["heb_scg"][g] for g in set(m["heb_mod"]) & set(m["heb_scg"])}
    exc = {lv: sorted(g for g in shared["l0"] if not shared["l0"][g] <= shared[lv].get(g, set())) for lv in shared}
    R.info("measurement 2: participants as a pair, shared(l0) within shared(L); exceptions listed",
           "; ".join(f"{lv}: {len(shared['l0'])} Greek clauses, {len(v)} exceptions {v[:10]}" for lv, v in exc.items()))
    # measurement 5
    refs = pqr(B / "measures" / "referents.parquet")
    mine5 = []
    for (lv, tx), (W, P, K) in D.items():
        dp = {(p["t"], p["n"]): p for p in P}
        rch = defaultdict(list)
        for k in K:
            rch[(k["other"], k["s"], k["s_n"])].append((dp[(k["t"], k["n"])], k["how"]))
        nm = defaultdict(set)
        for o in byLT[(lv, tx)]:
            if o["state"] == "applied" and o["switch"] in ("r", "a"):
                nm[(o["src_t"], o["src_n"])] |= set(E(o["ent"]))
        for pn, P_ in SC[tx].parts.items():
            scope = {t for p_, t in SC[tx].order if p_ == pn}
            for r in P_.wa:
                if r["t"] not in scope or r["state"] != "participant":
                    continue
                q = P_.pp[(r["t"], r["n"])]
                es = set(E(q["who"]))
                fs = {"noun": "noun", "pronoun": "pronoun", "suffix": "suffix", "verb_zero": "ending"}[r["head_kind"]]
                hits = [d for d, how in rch.get((pn, r["t"], r["n"]), ()) if how in ("copy", "replace")]
                ins = [d for d, how in rch.get((pn, r["t"], r["n"]), ())
                       if how == "insert" and d["who_basis"] == "inserted" and set(E(d["who"])) & es]
                if es and es <= nm.get((r["t"], r["n"]), set()):
                    fd = "name"
                elif fs == "noun" and any(d["kind"] == "stem" and d["class"] == "noun" and es <= set(E(d["who"])) for d in hits):
                    fd = "noun"
                elif any(es <= set(E(d["who"])) for d in hits):
                    fd = fs
                else:
                    fd = "lost"
                got = {e for d in hits + ins for e in E(d["who"])}
                mine5.append((lv, tx, r["t"], r["n"], " ".join(sorted(es)), fs, fd, got == es))
    have5 = [(r["level"], r["text"], r["src_t"], r["src_n"], r["ent"], r["form_src"], r["form_draft"], r["right"])
             for r in refs]
    R.check("measurement 5 (referents.parquet) equals 8.5 recomputed", sorted(have5) == sorted(mine5),
            f"{len(have5)} rows, {len(mine5)} recomputed")
    lostw = [(x[0], x[1], x[2], x[3]) for x in mine5 if x[6] == "lost"]
    wrong = [(x[0], x[1], x[2], x[3]) for x in mine5 if not x[7]]
    R.info("measurement 5: lost and wrong places, each listed (level, text, t, n)",
           f"lost {len(lostw)}: {lostw[:40]}; wrong {len(wrong)}: {wrong[:40]}")
    agg = defaultdict(Counter)
    for x in mine5:
        for e in x[4].split():
            a_ = agg[(x[0], x[1], e)]
            a_["places"] += 1
            a_[x[6]] += 1
            a_["wrong"] += 0 if x[7] else 1
    be = tsv(B / "measures" / "referents_by_ent.tsv")
    cols = ("places", "name", "noun", "pronoun", "suffix", "ending", "lost", "wrong")
    hb = {(r["level"], r["text"], r["ent"]): tuple(int(r[c]) for c in cols) for r in be}
    mb = {k: tuple(v[c] for c in cols) for k, v in agg.items()}
    R.check("referents_by_ent.tsv equals 8.5 recomputed", hb == mb, f"{len(hb)} rows, {len(mb)} recomputed")


# ------------------------------------------------------------------ the pack

def pack(R, B, cats, reach_rows, rebuild_names=None):
    R.section("stage 43: the pack (section 9)")
    pk = B / "pack"
    want = []
    for sub in ("lines", "texts", "measures"):
        want += sorted(str(p.relative_to(B)) for p in (B / sub).rglob("*") if p.is_file())
    want += ["ops.parquet", "changed_verses.tsv", "near/pairs.parquet", "near/rend_langs.parquet",
             "near/distance.parquet", "words/levels.tsv", "words/sense_levels.tsv", "words/explanations.parquet",
             "words/vocabulary.tsv", "anatomy.parquet", "sources.json"]
    miss = [f for f in want if not (pk / f).exists() or h256(pk / f) != h256(B / f)]
    terms_ok = (pk / "terms.tsv").exists() and h256(pk / "terms.tsv") == h256(I1 / "hbo" / "terms.tsv")
    R.check("pack: every file of section 9 present and equal (sha256) to the build's; terms.tsv equal to i1's",
            not miss and terms_ok and (pk / "README.md").exists(), f"{len(want)} files; differ/missing {miss[:4]}; terms {terms_ok}")
    files = sorted(str(p.relative_to(pk)) for p in pk.rglob("*") if p.is_file())
    sums = {}
    if (pk / "SHA256SUMS").exists():
        for line in open(pk / "SHA256SUMS", encoding="utf-8"):
            h, n = line.rstrip("\n").split("  ", 1)
            sums[n] = h
    sums_ok = set(sums) == set(files) - {"SHA256SUMS"} and all(h256(pk / n) == h for n, h in sums.items())
    R.check("pack: SHA256SUMS names every file but itself, each hash right", sums_ok, f"{len(sums)} entries, {len(files)} files")
    rd = open(pk / "README.md", encoding="utf-8").read() if (pk / "README.md").exists() else ""
    unnamed = [f for f in files if f"`{f}`" not in rd]
    nolic = [f for f in files if not re.search(r"^- `" + re.escape(f) + r"`: .*(licence|not on record).*$", rd, re.M)]
    gen = rd.split("### Genesis apart", 1)[1].split("\n## ", 1)[0] if "### Genesis apart" in rd else ""
    gr = set(re.findall(r"^\| `([^`]+)` \| `([^`]*)` \| `([^`]*)` \| `([^`]*)` \| `([^`]*)` \| (\d+) \|$", gen, re.M))
    want_g = {(r["level"], r["switch"], r["setting"], r["state"], r["reason"], r["places"]) for r in reach_rows
              if r["scope"] == "genesis" and r["text"] == "hbo"}
    order = [s for s in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6.", "## 7.", "## 8.", "## 9.")]
    pos = [rd.find(s) for s in order]
    R.check("pack README: names every file, a licence or \"not on record\" on each file's line, the word scoring_closed, "
            "sections 1 to 9 in order, a Genesis section equal to reach.tsv",
            not unnamed and not nolic and "scoring_closed" in rd and all(p >= 0 for p in pos) and pos == sorted(pos)
            and gr == want_g and bool(want_g),
            f"unnamed {unnamed[:3]}; no licence {nolic[:3]}; Genesis rows {len(gr)} of {len(want_g)}")
    # no Greek script, no English value, no closed path
    vocab = set()
    for vals in cats.values():
        for v in vals:
            vocab.update(LATIN.findall(str(v)))
    import tomllib

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                vocab.update(LATIN.findall(str(k)))
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        else:
            vocab.update(LATIN.findall(str(x)))

    for cf in sorted(I1.glob("*/categories.toml")):   # the codes of i1 that the copied pieces carry
        walk(tomllib.load(open(cf, "rb")))
    for n in ("hbo", "heb_mod", "heb_scg"):            # book codes are keys
        for b in set(pq.read_table(I1 / n / "words.parquet", columns=["book"]).column("book").to_pylist()):
            vocab.update(LATIN.findall(b))
    for r in tsv(I1 / "hbo" / "terms.tsv"):            # the term table's own code columns
        for c in ("category", "code", "from_hbo", "from_grc", "checked"):
            vocab.update(LATIN.findall(r.get(c) or ""))
    vocab |= {"true", "false", "null", "kinds", "one_word", "sources", "domain", "via", "languages", "rank_a", "rank_b",
              "lex", "grp", "syn", "phrase_only", "heb_mod", "heb_scg", "hbo", "arc", "grc", "lexeme", "rule", "text"}
    greek, eng, closed_ = Counter(), Counter(), []
    exempt_prose = {"README.md", "sources.json", "SHA256SUMS"}
    for f in files:
        p = pk / f
        raw = p.read_bytes()
        texts_ = [raw.decode("utf-8", "ignore")] if not f.endswith(".parquet") else [
            v for c in pq.read_table(p).columns if str(c.type) == "string" for v in c.to_pylist() if v]
        for x in texts_:
            for m in CLOSED_PATH.finditer(x):
                closed_.append((f, m.group(0)[:60]))
        if f in exempt_prose:
            continue
        if f.endswith(".parquet"):
            t = pq.read_table(p)
            cols = {c: t.column(c).to_pylist() for c in t.column_names if str(t.schema.field(c).type) == "string"}
        else:
            rows = tsv(p)
            cols = defaultdict(list)
            for r in rows:
                for c, v in r.items():
                    cols[c].append(v)
        for c, vals in cols.items():
            for v in vals:
                if not v:
                    continue
                if GREEK.search(v):
                    allowed = (f.endswith("near/pairs.parquet") and c == "evidence") or (f == "terms.tsv" and c in ("grc", "source_grc"))
                    greek[(f.split("/")[0] if "/" in f else f, c, "exempt" if allowed else "BAD")] += 1
                s = re.sub(r"\((I|II|III|IV|V)\)", " ", v)
                for rx in KEYLIKE:
                    s = rx.sub(" ", s)
                if f == "terms.tsv" and c in ("named_by",):
                    continue
                for wd in LATIN.findall(s):
                    if wd not in vocab:
                        eng[(f.split("/")[0], c, wd)] += 1
    badg = {k: v for k, v in greek.items() if k[2] == "BAD"}
    R.check("pack: no value in Greek script outside the two places the specification puts it (near/pairs evidence.via of "
            "nt2 rows, 5.1; terms.tsv's grc column, 9)", not badg,
            f"bad {sorted(badg.items())[:4]}; exempt by name {sorted((k, v) for k, v in greek.items() if k[2] == 'exempt')}")
    R.check("pack: no English value (every Latin word of a table is a declared code or a key; README, sources.json and "
            "SHA256SUMS are prose or records)", not eng, f"{sum(eng.values())} {sorted(eng.items())[:6]}")
    R.check("pack: no path naming HEBM95, TBTA or BHSA", not closed_, f"{closed_[:4]}")


# ------------------------------------------------------------------ columns, codes, the sample, the rebuild

SPEC_COLS = {
    "words.parquet": ["t", "book", "chapter", "verse", "w", "text", "after", "sentence", "clause", "op"],
    "pieces.parquet": ["t", "n", "text", "kind", "lexeme", "class", "marks", "who", "who_basis", "op"],
    "links.parquet": ["t", "n", "s", "agree", "agree_model", "other", "how", "basis", "s_n"],
    "ops.parquet": ["op", "level", "text", "switch", "setting", "key", "scoring_closed", "src_t", "src_n", "added_clause",
                    "added_role", "state", "reason", "detail", "rule", "before", "after", "lexeme_before",
                    "lexeme_after", "ent", "tier", "chosen_by", "routes_all", "grade", "form_rule", "draft_t"],
    "lines": ["key", "text", "level", "form", "scoring_closed", "changed", "line"],
    "changed_verses.tsv": ["level", "text", "key", "scoring_closed", "switches", "ops"],
    "measures/referents.parquet": ["level", "text", "key", "scoring_closed", "src_t", "src_n", "ent", "person",
                                   "form_src", "form_draft", "right"],
    "anatomy.parquet": ["text", "key", "t", "n", "scoring_closed", "piece_text", "kind", "class", "lexeme", "level",
                        "level_kind", "band", "sense", "sense_level", "domain", "ref_status", "ref_form", "who",
                        "who_basis", "layout", "line_kind", "in_quote", "changed_in", "ops"],
}


def meta(R, B, cats43, ops):
    R.section("stage 43: columns and codes")
    bad = []
    for f, want in SPEC_COLS.items():
        if f in ("words.parquet", "pieces.parquet", "links.parquet"):
            have = pq.ParquetFile(B / "texts" / "v2" / "hbo" / f).schema_arrow.names
        elif f == "lines":
            have = list(tsv(B / "lines" / "v2" / "hbo.cons.tsv")[0].keys())
        elif f.endswith(".parquet"):
            have = pq.ParquetFile(B / f).schema_arrow.names
        else:
            have = list(tsv(B / f)[0].keys())
        if have != want:
            bad.append((f, have))
    R.check("the columns of the stage-43 tables are those SPEC-levels 7 and 8 name, in order", not bad, f"{bad[:2]}")
    colmd = open(B / "COLUMNS.md", encoding="utf-8").read()
    sec = colmd.split("## Stage 43", 1)[1] if "## Stage 43" in colmd else ""
    nocol = []
    for f in ("words.parquet", "pieces.parquet", "links.parquet", "lexemes.tsv"):
        part = sec.split(f"### `texts/<level>/<text>/{f}`", 1)
        if len(part) < 2:
            nocol.append(f)
    for f in ("ops.parquet", "changed_verses.tsv", "anatomy.parquet", "measures/kept.parquet", "measures/pair.parquet",
              "measures/reach.tsv", "measures/referents.parquet", "measures/referents_by_ent.tsv"):
        part = sec.split(f"### `{f}`", 1)
        if len(part) < 2:
            nocol.append(f)
            continue
        body = part[1].split("\n### ", 1)[0]
        if f.endswith(".parquet"):
            cs = pq.ParquetFile(B / f).schema_arrow.names
        else:
            cs = list(tsv(B / f)[0].keys())
        nocol += [f"{f}.{c}" for c in cs if not re.search(r"^\| `" + re.escape(c) + r"` \| \S", body, re.M)]
    R.check("COLUMNS.md lists every table and column of stage 43 with a basis", not nocol, f"{nocol[:5]}")
    und = Counter()

    def need(cat, v):
        if v not in cats43.get(cat, []):
            und[(cat, v)] += 1

    for o in ops:
        for c in ("level", "text", "switch", "setting", "state", "reason", "rule", "tier", "grade", "form_rule",
                  "added_role"):
            need(f"ops.{c}", o[c])
        for x in json.loads(o["chosen_by"]):
            need("ops.chosen_by", x)
        if o["switch"] == "v":
            for k in o["_detail"]:
                need("ops.detail.keys", k)
    for lv, texts in LEVELS.items():
        for tx in texts:
            for r in pqr(B / "texts" / lv / tx / "links.parquet", ["other", "how", "basis"]):
                need("links.other", r["other"]), need("links.how", r["how"]), need("links.basis", r["basis"])
            for r in pqr(B / "texts" / lv / tx / "pieces.parquet", ["who_basis"]):
                need("pieces.who_basis", r["who_basis"])
    for r in pqr(B / "measures" / "pair.parquet", ["state_l0", "state_mod", "state_scg", "state_both"]):
        for v in r.values():
            need("pair.state", v)
    for r in tsv(B / "measures" / "reach.tsv"):
        need("reach.scope", r["scope"])
    for r in pqr(B / "measures" / "referents.parquet", ["form_src", "form_draft"]):
        need("referents.form_src", r["form_src"]), need("referents.form_draft", r["form_draft"])
    for r in pqr(B / "anatomy.parquet", ["layout"]):
        need("anatomy.layout", r["layout"])
    R.check("every coded value of the stage-43 tables declared in categories.toml [codes43]", not und,
            f"{sum(und.values())} {sorted(und.items())[:5]}")


def sample(R, B, path, cv):
    R.section("sample-43.md")
    txt = open(path, encoding="utf-8").read() if Path(path).exists() else ""
    ok, det = True, []
    for tx in TEXTS:
        lv = "v2_r_a" if tx == "hbo" else "v2_r"
        rows = [r for r in cv if r["level"] == lv and r["text"] == tx]
        k = max(1, len(rows) // 20)
        want = [r["key"] for r in rows[::k][:20]]
        part = txt.split(f"## {tx} (", 1)[1].split("\n## ", 1)[0] if f"## {tx} (" in txt else ""
        have = re.findall(r"^### (.+)$", part, re.M)
        lines = {lev: {r["key"]: r["line"] for r in tsv(B / "lines" / lev / f"{tx}.point.tsv")}
                 for lev, ts in LEVELS.items() if tx in ts}
        body_ok = all(f"- `{lev}`" in part and lines[lev][key] in part for key in want for lev in lines)
        ok &= have == want and len(want) == 20 and body_ok
        det.append(f"{tx}: {len(have)} verses, lines {body_ok}")
    R.check("sample-43.md holds 20 changed verses per text by the rule, each with the line of every level", ok,
            ", ".join(det))


def rebuild(R, root, build, py, sample42, sample43):
    """The whole build again into <build>b from nothing; every file's sha256 equal."""
    import os
    import shutil
    import subprocess
    import time
    R.section("rebuild into pilot-1b from nothing")
    B = root / build
    B2 = root / (build + "b")
    if B2.exists():
        trash = root / f"trash-{time.strftime('%Y-%m-%d')}" / f"{build}b-{int(time.time())}"
        trash.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(B2), str(trash))
    (B2 / "cache").mkdir(parents=True)
    s42, s43 = B2 / "cache" / "sample-42.md", B2 / "cache" / "sample-43.md"
    codes = []
    for st, smp in ((42, s42), (43, s43)):
        res = subprocess.run([str(py), "-I", str(REPO / "shoresh" / "macula" / "build_levels.py"), "--build", build + "b",
                              "--stage", str(st), "--root", str(root), "--sample", str(smp)], capture_output=True, text=True)
        codes.append(res.returncode)
        if res.returncode:
            R.out(res.stderr[-2000:])
    names = sorted(str(p.relative_to(B)) for p in B.rglob("*") if p.is_file() and p.name not in ("VALIDATION.md",)
                   and "cache" not in p.relative_to(B).parts)
    names2 = sorted(str(p.relative_to(B2)) for p in B2.rglob("*") if p.is_file() and p.name not in ("VALIDATION.md",)
                    and "cache" not in p.relative_to(B2).parts)
    diff = [f for f in names if f in names2 and h256(B / f) != h256(B2 / f) and f != "build.json"]
    # build.json names its build; compare it with the build's name taken out
    bj = [json.load(open(x / "build.json", encoding="utf-8")) for x in (B, B2)]
    for x in bj:   # the build's own name stands in `build` and in the command line `entry`
        x.pop("build", None)
        x["entry"] = x.get("entry", "").replace(f"--build {build}b ", "--build NAME ").replace(f"--build {build} ", "--build NAME ")
    bj_same = bj[0] == bj[1]
    smp_same = h256(s42) == h256(sample42) and h256(s43) == h256(sample43)
    R.check("the whole build rebuilt into pilot-1b from nothing (stages 42 and 43, an empty cache/): every file's sha256 "
            "equal, and the samples", codes == [0, 0] and not diff and names == names2 and bj_same and smp_same,
            f"exit {codes}; {len(names)} files, {len(diff)} differ {diff[:3]}; only one side "
            f"{sorted(set(names) ^ set(names2))[:3]}; build.json same {bj_same}; samples same {smp_same}; in {B2}")
