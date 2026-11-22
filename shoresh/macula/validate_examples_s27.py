"""Stage 27 checks (SPEC 1.3, section 10: new columns (the parts of 27), model in marks, added, passages, terms 1.3,
unchanged against d1). Imports nothing from the builders: every join and every value is recomputed here from the
datasets on disk and the build's own G columns.

    stage27(R, build, d1=None)      called by validate_examples.py --build e1 --upto 27
"""
import bisect
import collections as C
import csv
import glob
import hashlib
import json
import os
import re
import tomllib
import unicodedata

import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
D = os.path.join(HERE, "data")
SPEC = os.path.join(REPO, "internal-docs", "source-examples-spec")
LANGS = ("hbo", "arc", "grc")
MARKER = "# ---- the 1.3 part (build_examples.py --stage 27) ----"
NEWCATS = ("ref_status", "noun_rel", "clusivity", "mood", "added_kind")
TYPES = ("person", "place", "group", "deity", "realia", "flora", "fauna")

V14 = False   # an f build (SPEC 1.4): set by validate_examples.py
V16 = False          # an h build (SPEC 1.6): set by validate_examples.py
V15 = False   # a g build (SPEC 1.5): D17 (A5, A7) and D18 of 1.5, recomputed by validate_examples_s35


def tsv(path, col=None, val=None):
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader((ln for ln in fh if not ln.startswith("#")), delimiter="\t", quoting=csv.QUOTE_NONE))
    return rows if col is None else [r for r in rows if r[col] == val]


def tab(build, lg, name, cols=None):
    return pq.read_table(os.path.join(build, lg, f"{name}.parquet"), columns=cols).to_pydict()


def c0(v):
    return re.sub(r"[^a-z0-9]+", "_", v.lower()).strip("_")


def jd(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def script_ok(s, greek):
    for ch in s:
        cp = ord(ch)
        if ch == " ":
            continue
        if greek and not (0x0370 <= cp <= 0x03FF or 0x1F00 <= cp <= 0x1FFF or 0x0300 <= cp <= 0x036F):
            return False
        if not greek and not (0x0590 <= cp <= 0x05FF or 0xFB1D <= cp <= 0xFB4F):
            return False
    return True


class Load:
    """The build's tables, read once."""

    def __init__(self, build):
        self.build = build
        self.P, self.W, self.K, self.N, self.A, self.S, self.part = {}, {}, {}, {}, {}, {}, {}
        for lg in LANGS:
            self.P[lg] = tab(build, lg, "pieces")
            self.W[lg] = tab(build, lg, "words", ["t", "id", "book", "clause"])
            self.K[lg] = tab(build, lg, "clauses")
            self.N[lg] = tab(build, lg, "constituents")
            self.A[lg] = tab(build, lg, "added") if os.path.exists(os.path.join(build, lg, "added.parquet")) else None
            self.S[lg] = tab(build, lg, "passages") if os.path.exists(os.path.join(build, lg, "passages.parquet")) else None
            self.part[lg] = tsv(os.path.join(build, lg, "participants.tsv"))
        self.terms = {lg: {(r["category"], r["code"]): r["grc" if lg == "grc" else "hbo"]
                           for r in tsv(os.path.join(build, lg, "terms.tsv"))} for lg in LANGS}
        self.piece = {}
        for lg in LANGS:
            P = self.P[lg]
            for i, (pid, t, n, k, c) in enumerate(zip(P["pid"], P["t"], P["n"], P["kind"], P["class"])):
                self.piece[pid] = (lg, i, t, n, k, c)
        self.crow = {k: (lg, j) for lg in LANGS for j, k in enumerate(self.K[lg]["clause"])}
        self.wid = {t: i for lg in LANGS for t, i in zip(self.W[lg]["t"], self.W[lg]["id"])}

    def kv(self, k, col):
        lg, j = self.crow[k]
        return self.K[lg][col][j]


# ---- D9: the validator's own join (validate_examples_s16.values, with the clause keys of the 1.3 datasets as an
# extra dataset of one row per key); saved to the scratch folder so that the tamper test can reuse it --------------

def v13_keys(corpus):
    keys = set()
    for p in (os.path.join(D, "reference-status", "np.tsv"), os.path.join(D, "implicit-args", "args.tsv")):
        keys |= {r["clause_key"] for r in tsv(p, "corpus", corpus)}
    return [{"clause_key": k} for k in sorted(keys)]


def d9_from_stash(STASH):
    out = {}
    for gname, corpus in (("hbo+arc", "hbo"), ("grc", "grc")):
        ro = STASH[f"s16 rows_of {gname}"]
        out[corpus] = {"ck": {r["clause_key"]: k for k, r in ro[("main", "v13-clause-keys")].items()},
                       "ta": {r["clause_key"]: k for k, r in ro[("main", "time-aspect")].items()}}
    return out


def join_keys(M, corpus, keys, what="ck"):
    out, why = {}, C.Counter()
    for ck in sorted(set(keys)):
        k = M[corpus][what].get(ck)
        if k is None:
            why["no clause (D9)"] += 1
        else:
            out[ck] = k
    return out, why


# ---- the checks ----------------------------------------------------------------------------------------------------

def stage27(R, build, d1=None, quick=False, STASH=None, maps=None):
    """maps: the D9 maps (d9_from_stash); from STASH when the whole validator runs."""
    d1 = d1 or os.path.join(os.path.dirname(os.path.normpath(build)), "d1")
    L = Load(build)
    M = maps or d9_from_stash(STASH)
    R.info("D9 clause keys of reference-status and implicit-args joined (validator's own join)",
           {c: len(M[c]["ck"]) for c in M})
    cats = {}
    for lg in LANGS:
        with open(os.path.join(build, lg, "categories.toml"), encoding="utf-8") as fh:
            text = fh.read()
        cats[lg] = tomllib.loads(text)
        R.check(f"{lg} categories.toml: has the 1.3 part", MARKER in text)
    E = {r["entity"]: r for r in tsv(os.path.join(D, "entities", "entities.tsv"))}

    def ent(acai):
        r = E.get(acai)
        if r is None or r["type"] not in TYPES:
            return ""
        return f"{r['type']}:e{hashlib.sha1(acai.encode('utf-8')).hexdigest()[:10]}"
    groups = (("hbo", ("hbo", "arc")), ("grc", ("grc",)))

    def term(lg, cat, code):
        return L.terms[lg].get((cat, code), f"NO TERM {cat} {code}")

    # ---- terms 1.3 ---------------------------------------------------------------------------------------------------
    R.section("terms 1.3 (SPEC 4.10)")
    master = open(os.path.join(SPEC, "terms.tsv"), encoding="utf-8").read()
    rows = tsv(os.path.join(SPEC, "terms.tsv"))
    for lg in LANGS:
        R.check(f"{lg} terms.tsv: a byte copy of the master", open(os.path.join(build, lg, "terms.tsv"), encoding="utf-8").read() == master)
    d1t = open(os.path.join(d1, "hbo", "terms.tsv"), encoding="utf-8").read().rstrip("\n").split("\n")
    R.check("terms.tsv: the 82 rows of 1.2 equal d1's, every column", master.split("\n")[:len(d1t)] == d1t, len(d1t) - 1)
    new = rows[len(d1t) - 1:]
    R.check("terms.tsv: 30 rows added, of the five new categories", len(new) == 30 and
            {r["category"] for r in new} == set(NEWCATS), dict(C.Counter(r["category"] for r in new)))
    R.check("terms.tsv: the new rows are tradition or coined, NFC, in the language's script; an empty term has empty "
            "from and source", all((not r[lg] and not r[f"from_{lg}"] and not r[f"source_{lg}"]) or
                                   (r[f"from_{lg}"] in ("tradition", "coined") and script_ok(r[lg], lg == "grc")
                                    and unicodedata.normalize("NFC", r[lg]) == r[lg]) for r in new for lg in ("hbo", "grc")))
    dup = C.Counter((r["category"], lg, r[lg]) for r in rows for lg in ("hbo", "grc") if r[lg])
    R.check("terms.tsv: no two codes of a category share a term in a language", max(dup.values()) == 1)
    notes = open(os.path.join(build, "hbo", "terms-notes.md"), encoding="utf-8").read()
    rows13 = open(os.path.join(SPEC, "terms-notes-1.3-rows.md"), encoding="utf-8").read()
    body13 = rows13.split("\n## The rows\n", 1)[1].strip("\n")
    refs13 = re.findall(r"^- `(ref:[a-z0-9_]+)`", rows13, re.M)
    head = notes.split("\n## ", 2)[1]
    R.check("terms-notes.md: the 1.3 rows appended unchanged, the 1.3 reference codes in the list at the head, "
            "and every reference code of terms.tsv resolved there",
            notes.rstrip("\n").endswith(body13) and all(f"`{c}`" in head for c in refs13) and
            all(f"`{r[f'source_{lg}']}`" in head for r in rows for lg in ("hbo", "grc") if r[f"source_{lg}"].startswith("ref:")),
            f"{len(refs13)} codes")
    d1n = open(os.path.join(d1, "hbo", "terms-notes.md"), encoding="utf-8").read()
    R.check("terms-notes.md: every line of d1's notes is kept, in order",
            all(x in set(notes.split("\n")) for x in d1n.split("\n")))
    for lg in LANGS:
        R.check(f"{lg} terms-notes.md: the same in every language folder",
                open(os.path.join(build, lg, "terms-notes.md"), encoding="utf-8").read() == notes)

    # ---- model in marks (D9m) and mood --------------------------------------------------------------------------------
    R.section("model in marks (D9m) and mood (SPEC 8)")
    TA = tsv(os.path.join(D, "time-aspect", "clauses.tsv"), "corpus", "hbo")
    CE = {r["clause_key"]: r for r in tsv(os.path.join(D, "clause-extras", "clauses.tsv"), "corpus", "hbo")}
    tamap, why = join_keys(M, "hbo", [r["clause_key"] for r in TA], "ta")
    want = {}
    for r in TA:
        k = tamap.get(r["clause_key"])
        if k is None or "lxx" not in r["basis"]:
            continue
        lg = L.crow[k][0]
        m = {}
        for cat in ("time", "aspect"):
            if r[cat]:
                m[cat] = term(lg, cat, c0(r[cat]))
        mo = CE.get(r["clause_key"], {}).get("mood", "")
        if mo and c0(mo) in ("irrealis", "declarative"):
            m["mood"] = term(lg, "mood", c0(mo))
        want[k] = jd(m) if m else None
    lxx_rows = sum(1 for r in TA if "lxx" in r["basis"])
    R.info("tan D9m time-aspect rows with lxx in the basis; joined", f"{lxx_rows:,}; {sum(1 for _ in want):,} "
           f"(hbo {sum(1 for k in want if L.crow[k][0] == 'hbo'):,}, arc {sum(1 for k in want if L.crow[k][0] == 'arc'):,}; "
           "SPEC expects 3,446; 3,388 / 46)")
    for lg in LANGS:
        K = L.K[lg]
        bad = both = 0
        for k, mk, mm in zip(K["clause"], K["marks"], K["marks_model"]):
            exp = None if lg == "grc" else want.get(k)
            if mm:            # time_abs (D16) is stage 28's
                z = json.loads(mm)
                z.pop("time_abs", None)
                mm_ = jd(z) if z else None
            else:
                mm_ = mm
            bad += mm_ != exp
            if mm:
                both += bool(set(json.loads(mm)) & set(json.loads(mk)))
        R.check(f"{lg} clauses.marks_model: equals D9m recomputed on every clause (null elsewhere{', every Greek clause' if lg == 'grc' else ''})",
                bad == 0, f"{bad} differ; {sum(1 for x in K['marks_model'] if x):,} filled")
        R.check(f"{lg} clauses: no key both in marks and in marks_model", both == 0, both)
        mood = C.Counter(json.loads(m).get("mood") for m in K["marks"])
        mood.pop(None, None)
        inv = {v: c for (cat, c), v in L.terms[lg].items() if cat == "mood"}
        R.check(f"{lg} clauses.marks.mood: every value a term of category mood", all(v in inv for v in mood), dict(mood))
        R.info(f"{lg} clauses with marks.mood (strict) / in marks_model", f"{sum(mood.values()):,} / "
               f"{sum(1 for m in K['marks_model'] if m and 'mood' in json.loads(m)):,}")

    # ---- D17 ----------------------------------------------------------------------------------------------------------
    R.section("constituents.ref_status, ref_form (D17)")
    for corpus, gl in groups:
        pre = "n" if corpus == "grc" else "o"
        NP = tsv(os.path.join(D, "reference-status", "np.tsv"), "corpus", corpus)
        ckm, why = join_keys(M, corpus, [r["clause_key"] for r in NP])
        cons = C.defaultdict(list)
        for lg in gl:
            for j, k in enumerate(L.N[lg]["clause"]):
                cons[k].append((lg, j))
        st, on = C.Counter(), C.defaultdict(list)
        for r in NP:
            pid = pre + r["head"]
            if pid not in L.piece:
                st[(corpus, "head piece not in the build")] += 1
                continue
            plg, _i, t, n, kind, cls = L.piece[pid]
            k = ckm.get(r["clause_key"])
            if k is None:
                st[(plg, "clause not joined")] += 1
                continue
            hits = [(lg, j) for lg, j in cons.get(k, []) if L.N[lg]["first"][j] <= t <= L.N[lg]["last"][j]]
            if not hits:
                st[(plg, "head word in no constituent of the clause")] += 1
                continue
            if V15 and len(hits) > 1:      # SPEC 1.5 D17 (A5): not the `v` part where another part shares the span
                hits = [h for h in hits if L.N[h[0]]["role"][h[1]] != "v"] or hits
            ex_ = [h for h in hits if L.N[h[0]]["head"][h[1]] == t]
            h = (ex_ or hits)[0]
            st[(plg, "head word is the constituent's head" if ex_ else "head word inside the span only")] += 1
            on[h].append((not ex_, t, n, kind, cls, r["status"]))
        exp = {}
        two = C.Counter()
        p_left = C.Counter()
        if V15:      # SPEC 1.5 D17 (A7): a `p` part takes a row only where its head piece is a suffix or a pronoun
            for h in list(on):
                if L.N[h[0]]["role"][h[1]] == "p":
                    keep = [x for x in on[h] if x[3] == "suffix" or x[4] == "pron"]
                    p_left[h[0]] += len(on[h]) - len(keep)
                    if keep:
                        on[h] = keep
                    else:
                        del on[h]
            for lg in gl:
                R.info(f"{lg} 1.5 D17 rows left out on a `p` part (head no suffix, no pronoun), recomputed", p_left[lg])
        for h, rs in on.items():
            rs.sort()
            two[h[0]] += len(rs) > 1
            _x, _t, _n, kind, cls, status = rs[0]
            form = "suffix" if kind == "suffix" else {"noun": "noun", "pron": "pronoun", "adj": "adjective",
                                                       "num": "number"}.get(cls, "")
            exp[h] = (term(h[0], "ref_status", c0(status)), form)
        for lg in gl:
            N = L.N[lg]
            bad = sum(1 for j in range(len(N["clause"])) if (N["ref_status"][j], N["ref_form"][j]) != exp.get((lg, j), ("", "")))
            R.check(f"{lg} constituents.ref_status, ref_form: equal D17 recomputed on every constituent", bad == 0,
                    f"{bad} differ; {sum(1 for v in N['ref_status'] if v):,} filled of {len(N['clause']):,}")
            R.info(f"{lg} D17 reference-status rows by join", {b: v for (a, b), v in sorted(st.items()) if a == lg})
            R.info(f"{lg} D17 constituents with two or more rows (the first taken)", two[lg])
            R.check(f"{lg} constituents.ref_status: every value a term of ref_status; ref_form a declared code",
                    set(v for v in N["ref_status"] if v) <= {t for (c, _k), t in L.terms[lg].items() if c == "ref_status"}
                    and set(v for v in N["ref_form"] if v) <= {"noun", "pronoun", "suffix", "adjective", "number"})
            R.info(f"{lg} D17 ref_status filled, ref_form empty (head class outside the five)",
                   sum(1 for a, b in zip(N["ref_status"], N["ref_form"]) if a and not b))
        R.info(f"{corpus} D17 rows: clause keys not joined, by reason", dict(why))
        R.info(f"{corpus} D17 rows whose head is no piece", st.get((corpus, "head piece not in the build"), 0))

    # ---- D21, D20 -----------------------------------------------------------------------------------------------------
    R.section("pieces.clusivity, clusivity_basis (D21); noun_rel, noun_head_t, noun_head_n (D20)")
    for corpus, gl in groups:
        pre = "n" if corpus == "grc" else "o"
        expc, onpiece = {}, 0
        for r in tsv(os.path.join(D, "we-layer", "words.tsv"), "lang", corpus):
            pid = pre + r["key"]
            onpiece += pid in L.piece
            if pid not in L.piece or r["value"] not in ("i", "e"):
                continue
            lg = L.piece[pid][0]
            b = "linked" if r["basis"] == "votes" else "derived" if "rule:" in r["basis"] else "?"
            expc[pid] = (term(lg, "clusivity", {"i": "inclusive", "e": "exclusive"}[r["value"]]), b)
        rows_we = {pre + r["key"] for r in tsv(os.path.join(D, "we-layer", "words.tsv"), "lang", corpus)}
        R.check(f"{corpus} D21: every inclusive-we row is on a piece", onpiece == len(rows_we), f"{onpiece:,} rows")
        NR = tsv(os.path.join(D, "noun-relations", "pairs.tsv"), "corpus", corpus)
        expn, where = {}, C.Counter()
        for r in NR:
            h, dpid = pre + r["head"], pre + r["dependent"]
            if h not in L.piece or dpid not in L.piece:
                where["a piece not in the build"] += 1
                continue
            lg = L.piece[dpid][0]
            rel = c0(r["relation"])
            expn[dpid] = ("" if rel == "other" else term(lg, "noun_rel", rel), L.piece[h][2], L.piece[h][3])
            i = L.piece[dpid][1]
            P = L.P[lg]
            w = ("own head" if (P["head_t"][i], P["head_n"][i]) == (L.piece[h][2], L.piece[h][3]) else
                 "same word, another piece" if L.piece[h][2] == P["t"][i] else "elsewhere")
            where[f"{lg} {w}"] += 1
        R.check(f"{corpus} D20: no dependent with two rows; every head piece exists",
                len(expn) == len(NR) and where.get("a piece not in the build", 0) == 0, f"{len(NR):,} pairs")
        R.info(f"{corpus} D20 pairs by where the head is (SPEC: hbo 35,737 / 6,832 / 12,112; arc 614 / 6 / 76; grc 5,048 / 0 / 1,207)",
               dict(sorted(where.items())))
        for lg in gl:
            P = L.P[lg]
            badc = badn = fp = fpn = 0
            for pid, c, cb, nr_, ht, hn, mk in zip(P["pid"], P["clusivity"], P["clusivity_basis"], P["noun_rel"],
                                                   P["noun_head_t"], P["noun_head_n"], P["marks"]):
                badc += (c, cb) != expc.get(pid, ("", ""))
                e = expn.get(pid)
                badn += (nr_, ht, hn) != (e if e else ("", None, None))
                m = json.loads(mk)
                if m.get("person") == "1" and m.get("number") == "pl":
                    fp += 1
                    fpn += pid not in rows_we
            R.check(f"{lg} pieces.clusivity, clusivity_basis: equal D21 recomputed on every piece", badc == 0,
                    f"{badc} differ; filled {sum(1 for v in P['clusivity'] if v):,}, by basis "
                    f"{dict(C.Counter(v for v in P['clusivity_basis'] if v))}")
            R.check(f"{lg} D21: every first-person plural piece (by marks) has an inclusive-we row", fpn == 0,
                    f"{fp - fpn:,} of {fp:,}")
            R.check(f"{lg} pieces.noun_rel, noun_head_t, noun_head_n: equal D20 recomputed on every piece", badn == 0,
                    f"{badn} differ; pairs {sum(1 for v in P['noun_head_t'] if v is not None):,}, noun_rel filled "
                    f"{sum(1 for v in P['noun_rel'] if v):,}")
            vals = {t for (c, _k), t in L.terms[lg].items() if c in ("clusivity", "noun_rel")}
            R.check(f"{lg} pieces.clusivity, noun_rel: every value a term of its category",
                    all(v in vals for v in P["clusivity"] + P["noun_rel"] if v))

    # ---- D18 ----------------------------------------------------------------------------------------------------------
    R.section("added.parquet (D18)")
    partset = {lg: {r["ent"] for r in L.part[lg]} for lg in LANGS}
    for corpus, gl in groups:
        pre = "n" if corpus == "grc" else "o"
        IA = tsv(os.path.join(D, "implicit-args", "args.tsv"), "corpus", corpus)
        ckm, why = join_keys(M, corpus, [r["clause_key"] for r in IA])
        exp = {lg: [] for lg in gl}
        st = C.Counter()
        for r in IA:
            k = ckm.get(r["clause_key"])
            if k is None:
                st[f"{corpus} clause not joined"] += 1
                continue
            lg = L.crow[k][0]
            vp = pre + (r["antecedent"] if r["role"] == "POSS" else r["verb"])   # SPEC 4.11: for poss, the noun word
            if vp not in L.piece:
                st[f"{lg} verb is no piece (left out)"] += 1
                continue
            kind = ("possessor" if r["role"] == "POSS" else "in_verb" if r["in_verb"] == "1" else
                    "unsaid" if r["where"] == "unexpressed" else "elsewhere")
            ap = pre + r["antecedent"] if r["antecedent"] else None
            ant = f"{L.piece[ap][2]}.{L.piece[ap][3]}" if ap in L.piece and kind != "unsaid" else ""
            who = ent(r["referent"]) if r["referent"] and not r["referent"].startswith("lemma:") else ""
            exp[lg].append((L.piece[vp][2], "poss" if r["role"] == "POSS" else r["role"], k,
                            term(lg, "added_kind", kind), c0(r["where"]), "ending" if r["in_verb"] == "1" else "none",
                            r["person"], {"s": "sg", "p": "pl", "d": "du"}.get(r["number"], r["number"]), r["gender"],
                            ant, who))
            st[f"{lg} joined"] += 1
        R.info(f"{corpus} D18 implicit-args rows: {len(IA):,}; by join (SPEC: joined 48,628 / 679 / 19,736; not joined "
               "212 / 42; verb no piece 237 / 3 / 103)", dict(sorted(st.items())))
        R.info(f"{corpus} D18 clause keys not joined, by reason", dict(why))
        if V15:      # SPEC 1.5 D18: drops, kind and form, step W (validate_examples_s35, apart from the builder)
            import validate_examples_s35 as S35
            exp = S35.d18(R, build, gl, exp, term)
        for lg in gl:
            A = L.A[lg]
            if A is None:
                R.check(f"{lg} added.parquet exists", False)
                continue
            have = list(zip(A["verb"], A["role"], A["clause"], A["kind"], A["where"], A["form"], A["person"],
                            A["number"], A["gender"], A["antecedent"], A["who"],
                            *((A["who_reason"],) if V15 else ())))
            R.check(f"{lg} added.parquet: every row recomputed by D18, in order (verb, role, clause)",
                    have == sorted(exp[lg]), f"{len(have):,} rows, recomputed {len(exp[lg]):,}")
            R.check(f"{lg} added.parquet: the columns of SPEC 4.11",
                    list(A) == ["clause", "verb", "role", "kind", "where", "form", "person", "number", "gender",
                                "antecedent", "who"] + (["who_reason"] if V15 else []))
            span = {k: (f, l_) for k, f, l_ in zip(L.K[lg]["clause"], L.K[lg]["first"], L.K[lg]["last"])}
            out_span = [f"{k} {v}" for k, v in zip(A["clause"], A["verb"]) if not (span[k][0] <= v <= span[k][1])]
            R.check(f"{lg} added: every clause exists", all(k in span for k in A["clause"]))
            R.info(f"{lg} added: rows whose verb word lies outside the clause's span (listed)", f"{len(out_span)}: {out_span[:5]}")
            tnset = {(v[2], v[3]) for v in L.piece.values()}
            R.check(f"{lg} added: every antecedent place exists",
                    all(tuple(map(int, a.split("."))) in tnset for a in A["antecedent"] if a))
            R.check(f"{lg} added: every who is in participants.tsv", all(x in partset[lg] for w in A["who"] if w for x in w.split()),
                    f"{sum(1 for w in A['who'] if w):,} with who")
            R.check(f"{lg} added: kind a term of added_kind; role, where, form, person, number, gender declared codes",
                    set(A["kind"]) <= {t for (c, _k), t in L.terms[lg].items() if c == "added_kind"}
                    and set(A["role"]) <= {"A0", "A1", "A2", "AA", "AA2", "poss"} and set(A["form"]) <= {"ending", "none"}
                    and set(A["where"]) <= {"earlier_clause", "later_clause", "mixed", "unexpressed", "no_clause", "none"}
                    and set(A["person"]) <= {"", "1", "2", "3"} and set(A["number"]) <= {"", "sg", "pl", "du"}
                    and set(A["gender"]) <= {"", "m", "f", "c", "n"})
            R.info(f"{lg} added rows by kind", dict(C.Counter(A["kind"])))

    # ---- D22 ----------------------------------------------------------------------------------------------------------
    R.section("passages.parquet (D22)")
    t_of, book_of, clause_of = {}, {}, {}
    for lg in LANGS:            # the Tanakh's t and the New Testament's t overlap: keyed by (greek, t)
        for t, i, b, c in zip(L.W[lg]["t"], L.W[lg]["id"], L.W[lg]["book"], L.W[lg]["clause"]):
            t_of[i], book_of[(lg == "grc", t)], clause_of[(lg == "grc", t)] = t, b, c
    pcount = C.Counter((v[2], v[0]) for v in L.piece.values() if v[0] != "grc")
    bw = C.defaultdict(list)
    for lg in ("hbo", "arc"):
        for t, b in zip(L.W[lg]["t"], L.W[lg]["book"]):
            bw[b].append(t)
    for b in bw:
        bw[b].sort()
    cf = {"tan": sorted((f, l_) for lg in ("hbo", "arc") for f, l_ in zip(L.K[lg]["first"], L.K[lg]["last"])),
          "grc": sorted(zip(L.K["grc"]["first"], L.K["grc"]["last"]))}
    cff = {g: [x[0] for x in v] for g, v in cf.items()}

    def W_(key, greek):
        return t_of[("n" + key) if greek else ("o" + key[:11])]

    def mk(source, kind, a, b, lines, fact, greek):
        g = "grc" if greek else "tan"
        ins = cf[g][bisect.bisect_left(cff[g], a):bisect.bisect_right(cff[g], b)]
        if greek:
            lg = "grc"
        else:
            nh = sum(pcount[(t, "hbo")] for t in range(a, b + 1))
            na = sum(pcount[(t, "arc")] for t in range(a, b + 1))
            lg = "arc" if na > nh else "hbo"
        return lg, (f"ps:{source}:{kind}:{a}", source, kind, a, b, clause_of[(greek, a)], clause_of[(greek, b)], len(ins),
                    sum(1 for _f, l_ in ins if l_ > b), lines, fact)
    exp = C.defaultdict(list)
    marks = C.defaultdict(list)
    LK = {"fm.ms.song": ("mam", "song"), "fm.ms.lines": ("mam", "lines"), "fm.ed.lines": ("nestle1904", "ed_lines"),
          "fm.ed.block": ("nestle1904", "ed_block"), "fm.ed.qlines": ("nestle1904", "ed_qlines")}
    nfacts = C.Counter()
    seenl = set()
    for f in sorted(glob.glob(os.path.join(D, "bridge-corpus", "inputs", "passage-facts@v0.1", "data", "*.jsonl"))):
        with open(f, encoding="utf-8") as fh:
            for ln in fh:
                r = json.loads(ln)
                if r["kind"] == "section":
                    nfacts[f"section {r['value']} {','.join(r['src'])}"] += 1
                    t = W_(r["after"], False)
                    marks[(r["src"][0], book_of[(False, t)])].append((t, r["after"], {"sc.pe": "petuchah", "sc.sa": "setumah"}[r["value"]], r["id"]))
                elif r["kind"] == "form" and r["value"] in LK:
                    nfacts[f"form {r['value']}"] += 1
                    g = len(r["first"]) == 11
                    lines = jd([[W_(a, g), W_(b, g)] for a, b in r["lines"]]) if r.get("lines") else None
                    lg, u = mk(*LK[r["value"]], W_(r["first"], g), W_(r["last"], g), lines, r["id"], g)
                    if u[0] in seenl:
                        nfacts["form repeating a unit of the same kind and span (no unit)"] += 1
                        continue
                    seenl.add(u[0])
                    exp[lg].append(u)
                elif r["kind"] == "form":
                    nfacts[f"form not taken {r['value']}"] += 1
    second = C.Counter()
    for (src, b), ms in sorted(marks.items()):
        ms.sort()
        start = bw[b][0]
        prev = None
        for t, _a, kind, fid in ms:
            if t == prev:
                second[src] += 1
                continue
            prev = t
            lg, u = mk(src, kind, start, t, None, fid, False)
            exp[lg].append(u)
            j = bisect.bisect_right(bw[b], t)
            start = bw[b][j] if j < len(bw[b]) else None
        if start is not None:
            lg, u = mk(src, "book_end", start, bw[b][-1], None, "", False)
            exp[lg].append(u)
    R.info("passages: section marks on a word that already closes a unit of the same source (no unit)", dict(second))
    R.info("passage-facts v0.1 facts read (SPEC: OSHB 1,181 + 1,981, MAM 1,545 + 1,973; layouts 8, 225, 14, 15, 93; "
           "1,018 fm.tr.poetry not taken)", dict(sorted(nfacts.items())))
    allu = []
    for lg in LANGS:
        S = L.S[lg]
        if S is None:
            R.check(f"{lg} passages.parquet exists", False)
            continue
        cols = ["passage", "source", "kind", "first", "last", "first_clause", "last_clause", "clauses", "crossing",
                "lines", "fact"]
        have = list(zip(*[S[c] for c in cols])) if S["passage"] else []
        want_ = sorted(exp[lg], key=lambda u: (u[1], u[3], u[2]))
        R.check(f"{lg} passages.parquet: every unit recomputed by D22, in order (source, first, kind)", have == want_,
                f"{len(have):,} units, recomputed {len(want_):,}; by kind {dict(C.Counter(S['kind']))}")
        R.check(f"{lg} passages: columns of SPEC 4.13; keys unique; first <= last", list(S) == cols and
                len(set(S["passage"])) == len(S["passage"]) and all(a <= b for a, b in zip(S["first"], S["last"])))
        R.info(f"{lg} passages: units with clauses that begin in them and end after them; such clauses",
               f"{sum(1 for c in S['crossing'] if c):,}; {sum(S['crossing']):,}")
        allu += [(s, k, a, b) for s, k, a, b in zip(S["source"], S["kind"], S["first"], S["last"])]
    fam = C.defaultdict(list)
    for s, k, a, b in allu:
        fam[(s, "section" if k in ("petuchah", "setumah", "book_end") else k)].append((a, b))
    fam2 = C.defaultdict(list)
    for s, k, a, b in allu:
        if k not in ("petuchah", "setumah", "book_end"):
            fam2[s].append((a, b, k))
    for key, us in sorted(fam.items()):
        us.sort()
        ov = sum(1 for x, y in zip(us, us[1:]) if y[0] <= x[1])
        R.check(f"passages {key[0]} {key[1]}: units do not overlap", ov == 0, f"{len(us):,} units, {ov} overlaps")
    for s, us in sorted(fam2.items()):
        us.sort()
        ov = [f"{x[2]} {x[0]}-{x[1]} / {y[2]} {y[0]}-{y[1]}" for x, y in zip(us, us[1:]) if y[0] <= x[1]]
        R.info(f"passages {s}: layouts of different kinds that overlap (SPEC 10 asks none per source; listed)",
               f"{len(ov)}: {ov[:3]}")
    for src in ("oshb", "mam"):
        cover = C.defaultdict(set)
        for s, k, a, b in allu:
            if s == src and k in ("petuchah", "setumah", "book_end"):
                cover[book_of[(False, a)]].update(range(a, b + 1))
        miss = sum(1 for b, ts in cover.items() for t in bw[b] if t not in ts)
        R.check(f"passages {src}: the sections cover every word of each book they mark", miss == 0,
                f"{len(cover)} books, {miss} words missing")

    # ---- the declarations of the 1.3 part ---------------------------------------------------------------------------
    R.section("the 1.3 codes and terms declared (categories.toml, map.tsv)")
    for lg in LANGS:
        ct = cats[lg]
        P, K, N, A, S = L.P[lg], L.K[lg], L.N[lg], L.A[lg], L.S[lg]
        mm = C.Counter((c, v) for m in K["marks_model"] if m for c, v in json.loads(m).items())
        checks = [("pieces", "clusivity", C.Counter(v for v in P["clusivity"] if v), "term"),
                  ("pieces", "clusivity_basis", C.Counter(v for v in P["clusivity_basis"] if v), "code"),
                  ("pieces", "noun_rel", C.Counter(v for v in P["noun_rel"] if v), "term"),
                  ("constituents", "ref_status", C.Counter(v for v in N["ref_status"] if v), "term"),
                  ("constituents", "ref_form", C.Counter(v for v in N["ref_form"] if v), "code"),
                  ("added", "kind", C.Counter(A["kind"]), "term"), ("added", "role", C.Counter(A["role"]), "code"),
                  ("added", "where", C.Counter(A["where"]), "code"), ("added", "form", C.Counter(A["form"]), "code"),
                  ("added", "person", C.Counter(v for v in A["person"] if v), "code"),
                  ("added", "number", C.Counter(v for v in A["number"] if v), "code"),
                  ("added", "gender", C.Counter(v for v in A["gender"] if v), "code"),
                  ("passages", "source", C.Counter(S["source"]), "code"), ("passages", "kind", C.Counter(S["kind"]), "code")]
        catof = {"clusivity": "clusivity", "noun_rel": "noun_rel", "ref_status": "ref_status", "kind": "added_kind"}
        for tb, col, use, by in checks:
            sec = ct.get(tb, {}).get(col)
            if not use:
                R.check(f"{lg} categories.toml: no [{tb}.{col}] where no row has a value", sec is None)
                continue
            decl = {v[by]: v["count"] for v in (sec or {}).get("values", [])}
            ok = decl == dict(use)
            if by == "term":
                ok = ok and all(L.terms[lg].get((catof[col], v["code"])) == v["term"] for v in sec["values"])
            R.check(f"{lg} categories.toml {tb}.{col}: every value declared{' with its code (terms.tsv)' if by == 'term' else ''} "
                    "and count", ok, f"{len(use)} values")
        sec = ct.get("clauses", {}).get("marks_model", {})
        ok = sec.get("basis") == "model" and sec.get("human_check") == "no human check" and sec.get("models") and \
            {(v["category"], v["term"]): v["count"] for v in sec.get("values", [])} == dict(mm) and \
            all(L.terms[lg].get(("time" if v["category"] == "time_abs" else v["category"], v["code"])) == v["term"]
                for v in sec.get("values", []))
        R.check(f"{lg} categories.toml clauses.marks_model: basis model, model named, no human check, every value "
                "declared with its code and count", bool(ok), f"{sum(mm.values()):,} values")
        sj = json.load(open(os.path.join(build, lg, "sources.json"), encoding="utf-8"))
        R.check(f"{lg} sources.json: the 1.3 sources pinned (sha256 equal to the files on disk) and marks_model's model",
                all(sj.get("v13", {}).get(n, {}).get("sha256") == sha(os.path.join(HERE, sj["v13"][n]["file"]))
                    for n in ("reference-status", "implicit-args", "noun-relations")) and
                all(sha(os.path.join(HERE, f)) == h for f, h in sj.get("v13", {}).get("inclusive-we", {}).get("files", {}).items())
                and "time-aspect-lxx-parse" in sj.get("model", {}))
        rows = [r for r in tsv(os.path.join(build, lg, "map.tsv"))]
        mp = {(r["table"], r["category"], r["code"]): r for r in rows}
        need = [("pieces", "clusivity", c) for (cat, c), t in L.terms[lg].items() if cat == "clusivity" and t in use_terms(P["clusivity"])]
        need += [("pieces", "noun_rel", c) for (cat, c), t in L.terms[lg].items() if cat == "noun_rel" and t in use_terms(P["noun_rel"])]
        need += [("constituents", "ref_status", c) for (cat, c), t in L.terms[lg].items() if cat == "ref_status" and t in use_terms(N["ref_status"])]
        need += [("clauses", "mood", c) for (cat, c), t in L.terms[lg].items() if cat == "mood" and t in
                 {json.loads(m).get("mood") for m in K["marks"]}]
        need += [("constituents", "ref_form", c) for c in set(N["ref_form"]) if c]
        need += [("added", "form", c) for c in set(A["form"])]
        R.check(f"{lg} map.tsv: every new code maps to none (meaning: reading; ref_form, added.form: a reason of their own)",
                all(k in mp and mp[k]["feature"] == "none" and mp[k]["reason"] ==
                    ("realisation_not_a_feature" if k[1] in ("ref_form", "form") else "reading") for k in need),
                f"{len(need)} codes")

    # ---- strict view of the new parts -------------------------------------------------------------------------------
    R.section("strict view of the 1.3 parts (SPEC 2.3)")
    for lg in LANGS:
        R.check(f"{lg} strict: no new strict column holds the basis model (clusivity_basis linked or derived only)",
                set(v for v in L.P[lg]["clusivity_basis"] if v) <= {"linked", "derived"})
    if quick:
        return
    unchanged(R, build, d1, L, want)


def use_terms(col):
    return {v for v in col if v}


# ---- unchanged against d1 (SPEC 13) ------------------------------------------------------------------------------------

def unchanged(R, build, d1, L, d9m):
    R.section("unchanged against d1 (SPEC 13)")
    for lg in LANGS:
        for name, key in (("words", None), ("pieces", None), ("constituents", None), ("clauses", None)):
            a = tab(build, lg, name)
            b = tab(d1, lg, name)
            n = len(next(iter(b.values())))
            R.check(f"{lg} {name}: as many rows as d1 (no added argument is a row)", len(next(iter(a.values()))) == n, f"{n:,}")
            cols = [c for c in b if not (name == "clauses" and c == "marks")
                    and not (name == "pieces" and c in ("who", "who_basis"))           # D7r: stage 28
                    and not (name == "constituents" and c in ("sem_role", "sem_role_basis"))]   # D12c: stage 28
            diff = {c: sum(1 for x, y in zip(a[c], b[c]) if x != y) for c in cols if c in a}
            miss = [c for c in cols if c not in a]
            R.check(f"{lg} unchanged: {name}, every column of d1{({'clauses': ' but marks', 'pieces': ' but who, who_basis (D7r, stage 28)', 'constituents': ' but sem_role, sem_role_basis (D12c, stage 28)'}).get(name, '')}, row by row",
                    not miss and not any(diff.values()), {c: v for c, v in diff.items() if v} or f"{len(cols)} columns")
            if name == "clauses":
                bad, moved, mood = 0, 0, 0
                for k, ma, mb, mm in zip(a["clause"], a["marks"], b["marks"], a["marks_model"]):
                    x, y = json.loads(ma), json.loads(mb)
                    mood += "mood" in x
                    x.pop("mood", None)
                    x.pop("time_abs", None)          # D16: stage 28
                    if V15:      # SPEC 1.5: the connective edge (D9); Greek mood and verbless time; stage 35 checks
                        for c in ("connective",) + (("mood", "time", "aspect") if lg == "grc" else ()):
                            x.pop(c, None)
                            y = dict(y)
                            y.pop(c, None)
                    if mm:
                        z = json.loads(mm)
                        moved += 1
                        for c in ("time", "aspect"):
                            if c in z:
                                x[c] = z[c]
                    bad += x != y
                R.check(f"{lg} unchanged: clauses.marks equals d1 but for the new key mood and the D9m moves",
                        bad == 0, f"{bad} differ; changed rows: D9m {moved:,}, mood added {mood:,}")
        pa_ = {r["ent"]: r for r in L.part[lg]}
        pb_ = {r["ent"]: r for r in tsv(os.path.join(d1, lg, "participants.tsv"))}
        # stage 28 changes words (D7r) and the catch-all names (D7n): those are checked by stage 28
        dif = sum(1 for e, r in pb_.items() if e not in pa_ or any(pa_[e][c] != r[c] for c in ("ent", "type", "sex", "ent_basis")))
        aw = {w for w in L.A[lg]["who"] if w} | {w for w, b in zip(L.P[lg]["who"], L.P[lg]["who_basis"]) if b == "reference"}
        newrows = set(pa_) - set(pb_)
        R.check(f"{lg} unchanged: participants.tsv, every row of d1 (ent, type, sex, ent_basis; name and words: stage 28)",
                dif == 0, f"{dif} differ of {len(pb_):,}")
        R.check(f"{lg} participants.tsv: the new rows are entities of added.who or of D7r, ent_basis given",
                newrows <= aw and all(pa_[e]["ent_basis"] == "given" for e in newrows),
                f"{len(newrows):,} new rows")
        fa = pq.read_table(os.path.join(build, lg, "facts.parquet")).to_pylist()
        fb = pq.read_table(os.path.join(d1, lg, "facts.parquet")).to_pylist()
        if V14:   # SPEC 1.4 D24a changes the equivalent_of rows; stage 32 checks them against e1
            fa = [r for r in fa if r["relation"] != "equivalent_of"]
            fb = [r for r in fb if r["relation"] != "equivalent_of"]
        sa = {jd(r) for r in fa}
        sb = {jd(x) for x in fb}
        newf = [r for r in fa if jd(r) not in sb]
        R.check(f"{lg} unchanged: facts.parquet, every row of d1; new rows are kin rows with a new participant"
                + (" (equivalent_of aside: SPEC 1.4, stage 32)" if V14 else ""),
                all(jd(r) in sa for r in fb) and all(r["relation"] in ("father", "mother", "offspring", "sibling",
                                                                      "partner", "tribe", "group_origin")
                                                     and (r["subject"] in newrows or r["object"] in newrows) for r in newf),
                f"{len(newf):,} new kin rows")
        for f in ("lexemes.tsv", "source_errors.tsv", "relmap.tsv", "forms.parquet", "paradigms.parquet",
                  "markers.parquet", "constructions.parquet", "orders.parquet", "agreement.parquet", "frames.parquet",
                  "pairs.parquet", "clause_links.parquet", "exceptions.parquet", "links.parquet", "link_account.parquet"):
            pa1, pb1 = os.path.join(build, lg, f), os.path.join(d1, lg, f)
            if not os.path.exists(pb1):
                continue
            if f.endswith(".parquet"):
                same = pq.read_table(pa1).to_pydict() == pq.read_table(pb1).to_pydict()
            elif V16 and f == "source_errors.tsv":     # SPEC 1.6: SE5 rows added (stage 38); SE1 to SE4 as d1
                with open(pa1, encoding="utf-8") as fa, open(pb1, encoding="utf-8") as fb:
                    same = [x for x in fa if not x.startswith("SE5\t")] == list(fb)
            else:
                same = sha(pa1) == sha(pb1)
            if V15 and f == "clause_links.parquet":     # SPEC 1.5: follows marks.connective (stage 18, stage 35)
                R.info(f"{lg} clause_links.parquet against d1", "follows the 1.5 connective edge; stage 35 counts it")
                continue
            R.check(f"{lg} unchanged: {f} equals d1", same)
        pf = tsv(os.path.join(build, lg, "profile.tsv"))
        pg = tsv(os.path.join(d1, lg, "profile.tsv"))
        R.info(f"{lg} profile.tsv rows that differ from d1 (expected none)", sum(1 for x, y in zip(pf, pg) if x != y)
               + abs(len(pf) - len(pg)))
        ma = {(r["table"], r["category"], r["code"], r["feature"], r["value"]): r for r in tsv(os.path.join(build, lg, "map.tsv"))}
        mb = {(r["table"], r["category"], r["code"], r["feature"], r["value"]): r for r in tsv(os.path.join(d1, lg, "map.tsv"))}
        R.check(f"{lg} map.tsv: every row of d1 kept but the counts of time, aspect (D9m)",
                all((k in ma or (V15 and k[1] in ("time", "aspect", "mood", "connective"))) and
                    (k not in ma or ma[k] == r or k[1] in ("time", "aspect") or
                                 (V15 and {c: v for c, v in ma[k].items() if c != "count"} ==
                                  {c: v for c, v in r.items() if c != "count"})) for k, r in mb.items()),
                f"{len(set(ma) - set(mb))} rows added")
    for ed in sorted(os.listdir(os.path.join(d1, "other"))):
        a = pq.read_table(os.path.join(build, "other", ed, "words.parquet")).to_pydict()
        b = pq.read_table(os.path.join(d1, "other", ed, "words.parquet")).to_pydict()
        R.check(f"other/{ed}/words.parquet: equals d1", a == b)


if __name__ == "__main__":
    # stage 27 alone, with the D9 maps a whole run of the validator saved (for checking and the tamper test)
    import sys
    sys.path.append(HERE)
    import validate_examples as VE
    build = os.path.join(HERE, "data", "source-examples", sys.argv[1] if len(sys.argv) > 1 else "e1")
    maps = json.load(open(os.path.join("/tmp/claude-1000/source-examples", "s27-validate-e1", "d9-maps.json"),
                          encoding="utf-8"))
    R = VE.Report()
    stage27(R, build, maps=maps)
    print(f"== {R.passes} PASS, {R.skips} SKIP, {R.fails} FAIL")
    sys.exit(1 if R.fails else 0)
