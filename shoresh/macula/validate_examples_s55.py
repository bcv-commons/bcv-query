"""SPEC 1.9 (k builds, stage 55): the exit conditions new in 1.9 (section 10), on k1 against j1 (CHANGES-1.9.md).

Called by validate_examples.py --build k1 --upto 55 (as s52 is). It imports no builder: the rules of N1 to N6 are
written here again from the specification; the helpers of validate_examples_s52 (validator code) are reused.
- N1 edition endings, N2 the tie (moves against j1, by kind), N3 places beside a kept member, N4 `N` kept,
  N5 the Strong's table, N6 the wider reach, mends off (k0 = j1), against j1, rebuild (k1 = k2).
"""
import collections as C
import json
import os
import re
import unicodedata as U

import validate_examples_s52 as S

T, TSV, H = S.T, S.TSV, S.H
HERE = S.HERE
J1 = os.path.join(HERE, "data/source-examples/j1")
I1 = S.I1
OUT52 = os.path.join(J1, "cache", "stage52-outside")
LANGS, EDS = S.LANGS, S.EDS
STRONG_PIN = "3650d1d2"
# the figures of CHANGES-1.9 (counted over j1 by stage 54)
EXP = {
    "N1 differ": {"heb_mod": 56, "heb_scg": 47},
    "N2 form_near": {"hbo": 23720, "arc": 243}, "N2 verse_form": {"hbo": 4695, "arc": 9},
    "N2 pieces that move": {"hbo": 326, "arc": 6},
    "N2 moves": {"hbo": {"strict won (was model, same word)": 274, "strict won (was model, another word)": 27,
                         "strict won (was not placed)": 3, "strict lost (now model, another word)": 9,
                         "strict lost (now not placed)": 1, "strict on both, another word": 11,
                         "model only on both, another word": 1},
                 "arc": {"strict won (was model, same word)": 6}},
    "N3 kept": {"hbo": 10, "arc": 0, "grc": 0}, "N3 left out": {"hbo": 43, "arc": 0, "grc": 55},
    "N4 rows": {"hbo": 2, "arc": 0, "grc": 16}, "N4 editions": {"heb_mod": 16, "heb_scg": 15},
    "N5 rows": {"heb_mod": 552, "heb_scg": 632}, "N5 kept": {"heb_mod": 3, "heb_scg": 19},
    "SE5": {"hbo": 122, "grc": 138},
}
# a difference against CHANGES-1.9, listed (report 55): piece 169021.1 (hbo) has a model link verse_lemma to s=265310 in
# j1 and none in k1's links.parquet; count54_n2.py, which reads the pass's model links before they are written, counts
# it model -> model
DIFF_N2 = {"hbo": {"count script": "model only on both, another word", "table": "model gained or lost",
                   "piece": "t=169021 n=1: j1 verse_lemma s=265310 (model), k1 no link; link_account state_model linked -> none"}}
EXCLUDE = ("מגרש", "צידה", "יחי")       # SPEC D14 (1.9), written here again
FIN = str.maketrans("ךםןףץ", "כמנפצ")
COORD = re.compile(r"^(NpaNp|[0-9]+Np):[0-9]+$")
NOUNISH = ("noun", "name", "propn", "n")
DECL = ("sources.json", "categories.toml", "COLUMNS.md", "READ-FIRST.md", "VALIDATION.md")
STMT = ("forms", "paradigms", "markers", "constructions", "orders", "agreement", "frames", "pairs", "clause_links",
        "exceptions")


def cons(t):
    return "".join(x for x in U.normalize("NFD", t or "") if "א" <= x <= "ת").translate(FIN)


def key(a):
    return (a["clause"], a["verb"], a["role"])


def stem_marks(build, sub):
    return {p["t"]: (json.loads(p["marks"]) if p["marks"] else {})
            for p in T(os.path.join(build, sub, "pieces.parquet"), ["t", "kind", "marks"]) if p["kind"] == "stem"}


# ---- N1 ---------------------------------------------------------------------------------------------------------------

def n1(R, build):
    gm = stem_marks(build, "grc")
    for ed in EDS:
        R.section(f"{ed} edition endings (1.9, N1)")
        hm = stem_marks(build, ed)
        K = {key(a): a for a in T(os.path.join(build, ed, "added.parquet"))}
        J = {key(a): a for a in T(os.path.join(J1, ed, "added.parquet"))}

        def differs(a):
            h, g = hm.get(a["verb"], {}), gm.get(a["from_t"], {})
            hp = "" if h.get("person") == "x" else (h.get("person") or "")
            hn, gp, gn = h.get("number") or "", g.get("person") or "", g.get("number") or ""
            return bool(hp and hn and gp and gn and (hp, hn) != (gp, gn))
        bad = [k for k, a in K.items() if a["form"] == "ending" and a["role"] == "A1" and differs(a)]
        R.check(f"{ed} added (1.9, N1): every carried A1 subject row (D39 in 1.8) of form ending has Hebrew and Greek "
                "person and number equal wherever both are given", not bad, f"{len(bad)} {bad[:3]}")
        a0 = [k for k, a in K.items() if a["form"] == "ending" and a["role"] != "A1" and differs(a)]
        R.info(f"{ed} N1 (1.9): A0 rows of form ending whose endings differ, not reached (report 55, for the "
               "specification)", len(a0))
        S.line(ed, f"- N1 (1.9): A0 rows of form ending whose Hebrew and Greek endings differ, left as 1.8 writes them: "
                   f"{len(a0)}")
        moved = sorted(k for k in K if k in J and J[k]["form"] == "ending" and K[k]["form"] == "none")
        want = sorted(k for k in K if k in J and J[k]["form"] == "ending" and J[k]["role"] == "A1" and differs(J[k]))
        R.check(f"{ed} added (1.9, N1): the rows that go ending -> none are exactly j1's ending rows whose endings differ",
                moved == want, f"{len(moved)} / {len(want)}")
        # the difference listed (report 55): CHANGES-1.9 counts every row that is ending in j1 and not in i1; the rule
        # reaches the A1 rows only, so the A0 rows among them (the 8 heb_mod rows of N7) whose endings differ stay
        i1e = {(a["from_clause"], a["verb"], a["role"]) for a in T(os.path.join(I1, ed, "added.parquet"))
               if a["form"] == "ending"}
        a0new = sorted(k for k in K if k in J and J[k]["form"] == "ending" and J[k]["role"] != "A1" and differs(J[k])
                       and (J[k]["from_clause"], J[k]["verb"], J[k]["role"]) not in i1e)
        for k in a0new:
            R.info(f"{ed} N1 (1.9): listed, an A0 row new in 1.8 (N7) whose endings differ, left ending", " ".join(map(str, k)))
            S.line(ed, f"- N1 (1.9) listed: A0 row new in 1.8 whose endings differ, left ending: {' '.join(map(str, k))}")
        R.check(f"{ed} N1 (1.9): rows ending -> none {len(moved)} + listed A0 rows new in 1.8 {len(a0new)}, D39 (1.9) says "
                f"{EXP['N1 differ'][ed]}", len(moved) + len(a0new) == EXP["N1 differ"][ed], len(moved))
        nn = 0
        for r in TSV(os.path.join(build, ed, "carry_account.tsv")):
            if (r["table"], r["column"], r["state"], r["basis"], r["reason"]) == ("added", "form", "own", "derived",
                                                                                   "ending_not_greek"):
                nn += int(r["count"])
        R.check(f"{ed} carry_account (1.9, N1): ending_not_greek counts the rows made none", nn == len(moved), nn)
        badc = [k for k in moved if any(K[k][f] != J[k][f] for f in ("clause", "verb", "role", "where", "antecedent",
                                                                       "from_clause", "from_t", "own_basis"))]
        R.check(f"{ed} N1 (1.9): a row made none keeps its key, where, antecedent and from_ columns", not badc, len(badc))
        cols = C.Counter(f for k in K if k in J for f in K[k] if K[k][f] != J[k][f])
        S.line(ed, f"- N1 (1.9): rows ending -> none {len(moved)}; added columns that differ from j1 {dict(cols)}")
        R.info(f"{ed} added (1.9): columns that differ from j1 (N1, N4, N5)", dict(cols.most_common()))
        R.check(f"{ed} added (1.9): the same keys as j1", set(K) == set(J), f"{len(set(K) ^ set(J))}")
        wa = {b: C.Counter(json.dumps(r, sort_keys=True, default=str) for r in T(os.path.join(b, ed, "who_account.parquet")))
              for b in (J1, build)}
        gone, come = wa[J1] - wa[build], wa[build] - wa[J1]
        st = C.Counter(json.loads(x)["state"] for x in gone.elements())
        R.info(f"{ed} D40 (1.9): who_account rows (the verb_zero heads of D40 among them) j1 {sum(wa[J1].values()):,} -> "
               f"k1 {sum(wa[build].values()):,}", f"only in j1 {sum(gone.values())} by state {dict(st)}, only in k1 "
               f"{sum(come.values())}")
        S.line(ed, f"- D40 (1.9): who_account rows {sum(wa[J1].values()):,} -> {sum(wa[build].values()):,} (only in j1 "
                   f"{sum(gone.values())}, by state {dict(st)}; only in k1 {sum(come.values())})")


# ---- N2 ---------------------------------------------------------------------------------------------------------------

def n2(R, build):
    R.section("the form_near tie (1.9, N2)")
    for lg in ("hbo", "arc"):
        sets = {}
        for b in (J1, build):
            st, mo = C.defaultdict(set), C.defaultdict(set)
            for r in T(os.path.join(b, lg, "links.parquet")):
                if r["other"] != "lxx":
                    continue
                (st if r["basis"] == "linked" else mo)[(r["t"], r["n"])].add((r["s"], r["how"]))
            sets[b] = (st, mo)
        (sa, ma), (sb, mb) = sets[J1], sets[build]
        how = C.Counter(h for xs in sb.values() for _, h in xs)
        for h in ("form_near", "verse_form"):
            R.check(f"{lg} links (1.9, N2): strict {h} {how[h]:,}, D13a (1.9) says {EXP['N2 ' + h][lg]:,}",
                    how[h] == EXP["N2 " + h][lg], how[h])
        mv = C.Counter()
        npieces = 0
        for pid in set(sa) | set(sb) | set(ma) | set(mb):
            a1, b1, a2, b2 = sa.get(pid, set()), sb.get(pid, set()), ma.get(pid, set()), mb.get(pid, set())
            if (a1, a2) == (b1, b2):
                continue
            npieces += 1
            ws = lambda x: {s for s, _ in x}
            if not a1 and b1:
                mv["strict won " + ("(was model, same word)" if ws(a2) & ws(b1) else "(was model, another word)" if a2
                                    else "(was not placed)")] += 1
            elif a1 and not b1:
                mv["strict lost " + ("(now model, same word)" if ws(b2) & ws(a1) else "(now model, another word)" if b2
                                     else "(now not placed)")] += 1
            elif a1 and b1:
                mv["strict on both, " + ("another word" if ws(a1) != ws(b1) else "same word, another how")] += 1
            else:
                mv[("model only on both, " + ("another word" if ws(a2) != ws(b2) else "same")) if a2 and b2
                   else "model gained or lost"] += 1
        R.check(f"{lg} N2 (1.9): pieces whose link moves {npieces}, D13a (1.9) says {EXP['N2 pieces that move'][lg]}",
                npieces == EXP["N2 pieces that move"][lg], npieces)
        exp = dict(EXP["N2 moves"][lg])
        listed = DIFF_N2.get(lg)
        if listed and dict(mv) != exp:
            a_, b_ = listed["count script"], listed["table"]
            exp[a_] -= 1
            exp = {k: v for k, v in exp.items() if v}
            exp[b_] = exp.get(b_, 0) + 1
            R.info(f"{lg} N2 (1.9): a difference listed: one move counted as '{a_}' by count54_n2.py (the pass's own "
                   f"model links) is '{b_}' in links.parquet", listed["piece"])
        R.check(f"{lg} N2 (1.9): the moves by kind as D13a (1.9), the listed difference read", dict(mv) == exp, dict(mv))
        S.line(lg, f"- N2 (1.9): strict form_near {how['form_near']:,}, verse_form {how['verse_form']:,}; pieces that "
                   f"move {npieces}: {dict(mv)}")
        la = {}
        for b in (J1, build):
            la[b] = {(r["t"], r["n"]): (r["state"], r["reason"]) for r in T(os.path.join(b, lg, "link_account.parquet"))
                     if r["other"] == "lxx"}
        ch = C.Counter(f"{la[J1][k][0]} -> {la[build][k][0]}" for k in la[build] if k in la[J1] and la[J1][k] != la[build][k])
        R.info(f"{lg} link_account (1.9, N2): rows that change, by state", dict(ch))
        S.line(lg, f"- N2 (1.9): link_account rows that change, by state {dict(ch)}")


# ---- N3, N4 -----------------------------------------------------------------------------------------------------------

def coordinated(build, lg):
    W = {r["t"]: (r["book"], r["chapter"], r["verse"]) for r in T(os.path.join(build, lg, "words.parquet"),
                                                                    ["t", "book", "chapter", "verse"])}
    byv = C.defaultdict(list)
    for p in T(os.path.join(build, lg, "pieces.parquet"), ["t", "n", "who", "rel", "head_t", "head_n", "class"]):
        if p["who"] and p["class"] in NOUNISH:
            byv[W[p["t"]]].append(p)

    def test(verb, e, kept):
        ps = byv.get(W.get(verb), [])
        pe = [p for p in ps if e in p["who"].split() and COORD.match(str(p["rel"]))]
        pk = [q for q in ps if kept & set(q["who"].split())]
        return any(((p["head_t"], p["head_n"]) == (q["head_t"], q["head_n"]) and p["head_t"] is not None)
                   or (p["head_t"], p["head_n"]) == (q["t"], q["n"]) for p in pe for q in pk)
    return test


def n3n4(R, build):
    changed_grc = set()
    for lg in LANGS:
        R.section(f"{lg} places beside a kept member, N kept (1.9, N3, N4)")
        stem, who, fr, W = S.load_lang(build, lg)
        A = T(os.path.join(build, lg, "added.parquet"))
        Aj = {key(a): a for a in T(os.path.join(J1, lg, "added.parquet"))}
        Sr = S.subj_rows(lg, A, stem, fr, True)
        r18 = S.recompute_who(A, Sr, stem, who, True)
        test = coordinated(build, lg)
        r19, kept, left, n4 = {}, [], [], []
        for a in A:
            k = key(a)
            w, why, out, larger, small = r18[k]
            ws = set(w.split())
            if out:
                back = {e for e in out if S.etype(e) == "place" and test(a["verb"], e, ws)}
                kept += [(k, e) for e in sorted(back)]
                left += [(k, e) for e in sorted(out - back) if S.etype(e) == "place"]
                ws |= back
            s16, s18, _ = Sr.get(k, (False, False, ""))
            if why == "disagree" and s18 and not s16:
                ns = who.get(tuple(map(int, a["antecedent"].split("."))), set()) if a["antecedent"] else set()
                ws, why = set(ns), "antecedent_not_verb"
                n4.append(k)
            r19[k] = (" ".join(sorted(ws)), why)
        bad = [k for k, a in ((key(a), a) for a in A)
               if (a["who"], a["who_reason"]) != r19[k] and (a["who"], a["who_reason"]) != (Aj[k]["who"], Aj[k]["who_reason"])]
        moved19 = {k for k in r19 if r19[k] != (r18[k][0], r18[k][1])}
        chg = {k for k, a in ((key(a), a) for a in A) if (a["who"], a["who_reason"]) != (Aj[k]["who"], Aj[k]["who_reason"])}
        R.check(f"{lg} added (1.9, N3, N4): the rows whose who or who_reason differ from j1 are exactly the rows step W "
                "(1.9) moves against step W (1.8), and they hold the value of step W (1.9)",
                chg == moved19 and not bad, f"changed {len(chg)}, moved by the rule {len(moved19)}, wrong {len(bad)}")
        R.check(f"{lg} N3 (1.9): places kept {len(kept)}, D18 (1.9) says {EXP['N3 kept'][lg]}", len(kept) == EXP["N3 kept"][lg],
                len(kept))
        R.check(f"{lg} N3 (1.9): places still left out {len(left)}, D18 (1.9) says {EXP['N3 left out'][lg]}",
                len(left) == EXP["N3 left out"][lg], len(left))
        whok = {key(a): a["who"] for a in A}
        badn3 = [(k, e) for k, e in kept if e not in whok[k].split()]
        R.check(f"{lg} added (1.9, N3): every place the test keeps is in the row's who, none left out where it holds",
                not badn3, len(badn3))
        n4rows = [a for a in A if a["who_reason"] == "antecedent_not_verb"]
        badn4 = []
        for a in n4rows:
            s16, s18, _ = Sr[key(a)]
            sn, _m = stem.get(a["verb"], (None, {}))
            vs = who.get((a["verb"], sn), set())
            ns = who.get(tuple(map(int, a["antecedent"].split("."))), set()) if a["antecedent"] else set()
            if not (s18 and not s16 and vs and ns and not vs & ns and set(a["who"].split()) == ns):
                badn4.append(key(a))
        R.check(f"{lg} added (1.9, N4): every antecedent_not_verb row is an M1 row whose V and N share no member, who = N",
                not badn4, f"{len(n4rows)} rows, {len(badn4)} wrong")
        R.check(f"{lg} N4 (1.9): rows antecedent_not_verb {len(n4rows)}, D18 (1.9) says {EXP['N4 rows'][lg]}",
                len(n4rows) == EXP["N4 rows"][lg], len(n4rows))
        dis = [key(a) for a in A if a["who_reason"] == "disagree" and Sr.get(key(a), (1, 0, ""))[1] and not Sr[key(a)][0]]
        R.check(f"{lg} added (1.9, N4): no M1 row is disagree", not dis, len(dis))
        se = TSV(os.path.join(build, lg, "source_errors.tsv"))
        se5 = [r for r in se if r["rule"] == "SE5"]
        places = {r["place"] for r in se5}
        miss = []
        for a in A:
            if a["who_reason"] in ("disagree", "antecedent_not_verb") and a["role"] != "poss":
                sn, _m = stem.get(a["verb"], (None, {}))
                if f"{a['verb']}.{sn}" not in places and a["antecedent"] not in places:
                    miss.append(key(a))
        ndis = sum(1 for a in A if a["who_reason"] in ("disagree", "antecedent_not_verb"))
        R.check(f"{lg} source_errors (1.9, N4): SE5 holds the rows of both reasons (disagree, antecedent_not_verb)",
                not miss, f"{ndis} rows, {len(se5)} SE5 rows, {len(miss)} missing")
        if lg in EXP["SE5"]:
            R.check(f"{lg} source_errors (1.9): SE5 rows {len(se5)}, section 13 (1.9) says {EXP['SE5'][lg]}",
                    len(se5) == EXP["SE5"][lg], len(se5))
        for k, e in kept:
            S.line(lg, f"- N3 (1.9) place kept: {W[k[1]]} {k[0]} {k[1]} {k[2]} {e}")
        for k, e in left:
            S.line(lg, f"- N3 (1.9) place left out: {W[k[1]]} {k[0]} {k[1]} {k[2]} {e}")
        for k in n4:
            S.line(lg, f"- N4 (1.9) antecedent_not_verb: {W[k[1]]} {k[0]} {k[1]} {k[2]}")
        if lg == "grc":
            changed_grc = chg
    for ed in EDS:
        K = {key(a): a for a in T(os.path.join(build, ed, "added.parquet"))}
        J = {key(a): a for a in T(os.path.join(J1, ed, "added.parquet"))}
        n = sum(1 for k in K if k in J and K[k]["who_reason"] == "antecedent_not_verb" and K[k]["who"] != J[k]["who"])
        gk = {(a["from_clause"], a["from_t"], a["role"]) for a in K.values() if a["who_reason"] == "antecedent_not_verb"}
        R.check(f"{ed} N4 (1.9): edition rows that get back a who {n}, D18 (1.9) says {EXP['N4 editions'][ed]}",
                n == EXP["N4 editions"][ed], n)
        R.check(f"{ed} added (1.9, N4): every antecedent_not_verb row carries a Greek row N4 changed", gk <= changed_grc,
                len(gk - changed_grc))


# ---- N5 ---------------------------------------------------------------------------------------------------------------

def n5(R, build):
    R.section("the Strong's table (1.9, N5)")
    sh = H(S.STRONG)
    R.check(f"N5 (1.9): strong_fixes.tsv has the sha256 of section 5 (1.9) ({STRONG_PIN}…)", sh.startswith(STRONG_PIN), sh[:12])
    rows = TSV(S.STRONG)
    per = C.Counter(r["edition"] for r in rows)
    R.check("N5 (1.9): the table holds 1,184 rows (heb_mod 552, heb_scg 632)", dict(per) == EXP["N5 rows"], dict(per))
    ex = [r for r in rows if cons(r["text"]) in EXCLUDE]
    R.check("N5 (1.9): no row of the table has an EXCLUDE surface", not ex, len(ex))
    for ed in EDS:
        ana = T(os.path.join(S.ANA, ed, "words.parquet"))
        _fixed, used = S.apply_fixes(ed, ana)
        R.check(f"{ed} N5 (1.9): every one of the table's {per[ed]} rows applied to exactly one part",
                used["strong"] == per[ed], used["strong"])
        P = {(r["s"], r["p"]): r for r in T(os.path.join(build, "other", ed, "parts.parquet"))}
        Pi = {(r["s"], r["p"]): r for r in T(os.path.join(I1, "other", ed, "parts.parquet"))}
        Pj = {(r["s"], r["p"]): r for r in T(os.path.join(J1, "other", ed, "parts.parquet"))}
        R.check(f"{ed} N5 (1.9): parts.parquet rows {len(P):,} (j1 {len(Pj):,})", len(P) == len(Pj), len(P))
        exc = [k for k, r in P.items() if cons(r["text"]) in EXCLUDE and r["basis"] == "model"
               and k in Pj and Pj[k]["lexeme"] != r["lexeme"]]
        R.check(f"{ed} N5 (1.9): EXCLUDE parts given back their value {len(exc)}, D14 (1.9) says {EXP['N5 kept'][ed]}",
                len(exc) == EXP["N5 kept"][ed], len(exc))
        bad = [k for k in exc if any(P[k][f] != Pi[k][f] for f in ("lemma", "strong", "lexeme", "key_rule", "basis"))]
        R.check(f"{ed} N5 (1.9): the parts of an EXCLUDE surface equal i1's", not bad, f"{len(bad)} {bad[:3]}")
        other = [k for k in P if k in Pj and P[k] != Pj[k] and k not in set(exc)]
        R.check(f"{ed} N5 (1.9): no other part differs from j1", not other, f"{len(other)} {other[:3]}")
        S.line(ed, f"- N5 (1.9): parts given back the analysis's value {len(exc)}; other parts that differ from j1 "
                   f"{len(other)}")


# ---- N6 ---------------------------------------------------------------------------------------------------------------

def _rows(p):
    if p.endswith(".parquet"):
        return C.Counter(json.dumps(r, sort_keys=True, ensure_ascii=False, default=str) for r in T(p))
    with open(p, encoding="utf-8") as fh:
        return C.Counter(fh.read().split("\n"))


def n6(R, build):
    R.section("the wider reach (1.9, N6)")
    files = [("28.19", f"{lg}/facts.parquet") for lg in ("hbo", "arc")] + \
            [("28.16", f"{lg}/source_errors.tsv") for lg in LANGS] + [("28.13", f"{lg}/map.tsv") for lg in LANGS]
    raw = S.named_forms()
    lxx = {U.normalize("NFC", (r["text"] or "").lower()) for r in T(os.path.join(build, "other", "lxx", "words.parquet"), ["text"])}
    swapped = {g for g in raw.values() if g and g != g.translate(S.SWAP)}
    fixed = {g.translate(S.SWAP) for g in raw.values() if g}
    for step, rel in files:
        m = os.path.join(OUT52, step, rel)
        ref = m if os.path.exists(m) else os.path.join(J1, rel)
        a, b = _rows(ref), _rows(os.path.join(build, rel))
        only_ref, only_k = sum((a - b).values()), sum((b - a).values())
        if rel.endswith("facts.parquet"):
            rel_kinds = C.Counter(json.loads(x)["relation"] for x in (a - b) + (b - a))
            R.check(f"{rel} (1.9, N6): equal to stage 52's mended copy but rows of rendered_by (N2)",
                    set(rel_kinds) <= {"rendered_by"}, f"only in the copy {only_ref:,}, only in k1 {only_k:,}; {dict(rel_kinds)}")
            objs = {json.loads(x)["object"] for x in b if json.loads(x)["relation"] == "rendered_by"}
            sus = sorted(o for o in objs if o.startswith("lxx:form:") and o[9:] in swapped and o[9:] not in fixed)
            badf = sorted(o for o in objs if o.startswith("lxx:form:") and o[9:] not in lxx)
            R.check(f"{rel} (1.9, N6): no rendered_by object holds a form macula_greek() would change: every lxx:form "
                    "object is a word of the Septuagint text (other/lxx words, lower-cased, NFC), none a MACULA named form",
                    not badf, f"{len(objs):,} objects; such forms that the Septuagint text holds {len(sus)} {sus[:3]}; "
                    f"wrong {badf[:3]}")
            R.info(f"{rel} (1.9): rows {sum(b.values()):,}; j1 {sum(_rows(os.path.join(J1, rel)).values()):,}", "")
        elif rel.endswith("source_errors.tsv"):
            other = [x for x in (a - b) + (b - a) if not x.startswith("SE5\t")]
            R.check(f"{rel} (1.9, N6): equal to stage 52's mended copy but SE5 lines (N3, N4)", not other,
                    f"only in the copy {only_ref}, only in k1 {only_k}; {other[:2]}")
        else:
            R.check(f"{rel} (1.9, N6): equal to stage 52's mended copy (no 1.9 mend changes form or kind counts)",
                    a == b, f"only in the copy {only_ref}, only in k1 {only_k}")
        lg = rel.split("/")[0]
        S.line(lg, f"- N6 (1.9): `{rel}` against stage 52's mended copy: lines only in the copy {only_ref:,}, only in "
                   f"k1 {only_k:,}")


# ---- the reach, k0, rebuild ---------------------------------------------------------------------------------------------

def in_reach19(rel):
    parts = rel.split("/")
    f = parts[-1]
    if parts[0] in EDS:
        return "N1, N2, N3, N4, N5"
    if parts[0] == "cache" or f in DECL or f == "profile.tsv":
        return "all"
    if parts[0] == "lexicon":
        return "N2, N5"
    if parts[0] == "other":
        return "N5" if len(parts) == 3 and parts[1] in EDS and f in ("words.parquet", "parts.parquet") else ""
    if parts[0] in LANGS and len(parts) == 2:
        if f == "added.parquet" or f[:-8] in STMT:
            return "N3, N4"
        if f == "source_errors.tsv":
            return "N3, N4, N6"
        if f == "map.tsv":
            return "N6"
        if parts[0] in ("hbo", "arc") and f in ("links.parquet", "link_account.parquet"):
            return "N2"
        if parts[0] in ("hbo", "arc") and f == "facts.parquet":
            return "N2, N6"
    return ""


def against_j1(R, build):
    R.section("against j1 (1.9)")
    out_bad, inside, n_out = [], [], 0
    for sub in list(LANGS) + ["other", "lexicon"] + list(EDS):
        for f in sorted(set(S.walk(os.path.join(J1, sub))) | set(S.walk(os.path.join(build, sub)))):
            rel = f"{sub}/{f}"
            if rel.endswith("VALIDATION.md"):
                continue
            p, q = os.path.join(J1, rel), os.path.join(build, rel)
            mend = in_reach19(rel)
            if not mend:
                n_out += 1
                if not os.path.exists(p) or not os.path.exists(q) or H(p) != H(q):
                    out_bad.append(rel)
            elif os.path.exists(p) and os.path.exists(q) and H(p) != H(q):
                inside.append((rel, mend))
    R.check("against j1 (1.9): every data file outside the reach of section 13 (1.9) has the sha256 of j1's",
            not out_bad, f"{n_out} files; {out_bad[:5]}")
    R.info("against j1 (1.9): files inside the reach that differ from j1", len(inside))
    for rel, mend in inside:
        p, q = os.path.join(J1, rel), os.path.join(build, rel)
        if not rel.endswith((".parquet", ".tsv")):
            R.info(f"against j1 (1.9): {rel} ({mend}) differs (a declaration file)", "")
            continue
        n1_, n2_, cols, o1, o2 = S.diff_table(p, q)
        txt = ((f"rows differing by column {dict(cols.most_common())}; " if cols is not None else "")
               + f"rows only in j1 {o1:,}, only in k1 {o2:,}")
        R.info(f"against j1 (1.9): {rel} ({mend}) rows j1 {n1_:,} k1 {n2_:,}", txt)
        lg = rel.split("/")[0]
        if lg in LANGS or lg in EDS:
            S.line(lg, f"- against j1 (1.9): `{rel}` ({mend}): rows {n1_:,} -> {n2_:,}; {txt}")


def mends_off(R, build):
    R.section("mends off (1.9): k0 against j1")
    k0 = os.path.join(HERE, "data/source-examples/k0")      # beside j1 (also when the build checked is a scratch copy)
    if not os.path.isdir(k0):
        R.check("mends off (1.9): k0 exists", False, k0)
        return
    bad, decl, n = [], [], 0
    for sub in list(LANGS) + ["other", "lexicon"] + list(EDS):
        fa, fb = S.walk(os.path.join(J1, sub)), S.walk(os.path.join(k0, sub))
        for f in sorted(set(fa) | set(fb)):
            rel = f"{sub}/{f}"
            p, q = os.path.join(J1, rel), os.path.join(k0, rel)
            if f.split("/")[-1] in DECL:
                if not os.path.exists(p) or not os.path.exists(q) or H(p) != H(q):
                    decl.append(rel)
                continue
            n += 1
            if not os.path.exists(p) or not os.path.exists(q) or H(p) != H(q):
                bad.append(rel)
    R.check("mends off (1.9): every data file of j1 has the same sha256 in k0 (1.9 mends off, 1.8's on, the 1.8 "
            "Strong's table)", not bad and n > 0, f"{n} files; {bad[:5]}")
    R.info("mends off (1.9): declaration files that differ (they name the builder files and the SPEC's sha256)",
           f"{len(decl)}: {decl[:12]}")


def rebuild(R, build, compare):
    R.section("rebuild (1.9)")
    other = os.path.join(os.path.dirname(os.path.normpath(build)), compare) if not os.path.isabs(compare) else compare
    bad, n = [], 0
    for sub in list(LANGS) + ["other", "lexicon"] + list(EDS) + ["cache/glossed"]:
        a, b = os.path.join(build, sub), os.path.join(other, sub)
        fa = [f for f in S.walk(a) if not f.endswith("VALIDATION.md")]
        fb = [f for f in S.walk(b) if not f.endswith("VALIDATION.md")] if os.path.isdir(b) else []
        n += len(fa)
        bad += [f"{sub}/{f}" for f in sorted(set(fa) ^ set(fb))]
        bad += [f"{sub}/{f}" for f in fa if f in fb and H(os.path.join(a, f)) != H(os.path.join(b, f))]
    R.check(f"rebuild (1.9): every file of {os.path.basename(os.path.normpath(build))} has the same sha256 in "
            f"{os.path.basename(other)} (VALIDATION.md aside; cache/glossed included)", not bad and n > 0,
            f"{n} files; {bad[:5]}")


def held(R, names):
    R.section("held checks (1.9, N7)")
    R.info("held checks (1.9): the list names each by its full name, compared whole", f"{len(names)} names")


def run(R, build, compare=None, held_names=()):
    n1(R, build)
    n2(R, build)
    n3n4(R, build)
    n5(R, build)
    n6(R, build)
    held(R, held_names)
    mends_off(R, build)
    against_j1(R, build)
    if compare:
        rebuild(R, build, compare)


def write_md(build, lines_by_stage, upto, held_lines, held_names):
    """Appends the block "new in 1.9" to each VALIDATION.md that s52.write_md wrote: the stage 55 lines of the folder, the
    held checks of this run and the list of held names (N7)."""
    for lg in LANGS + EDS:
        p = os.path.join(build, lg, "VALIDATION.md")
        with open(p, encoding="utf-8") as fh:
            head = fh.read().rstrip("\n")
        L = [head, "", f"## New in 1.9 (stage 55; `validate_examples.py --build {os.path.basename(os.path.normpath(build))} "
             f"--upto {upto} --write-md`)", "",
             "(The block \"new in 1.8\" above was written by stage 52's code on this build; the lines \"against i1\" there "
             "compare with i1. Stage 55 compares with j1.)", ""]
        for st, ln in lines_by_stage:
            w = ln.split()
            if st == "55" and len(w) > 1 and (w[1] == lg or w[1].startswith(lg + "/")):
                L.append(f"    {ln}")
        L += ["", "### Held checks (1.9, N7): each by its full name, compared whole", ""]
        L += [f"    {ln}" for _st, ln in held_lines]
        L += ["", f"The list holds {len(held_names)} names (`shoresh/macula/validate_examples_held19.tsv`); a failed check "
              "not on it fails.", ""]
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("\n".join(L).rstrip("\n") + "\n")
