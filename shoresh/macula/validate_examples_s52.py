"""Stage 52 checks (SPEC 1.8, section 10 "new in 1.8"). Imports nothing from the builders. Reads the build's files, i1's
files for the comparison, the pinned fix tables, the hebrew-nt-analysis release, and MACULA Hebrew's lowfat files.

run(R, build, compare=None):
  M1  passive subjects: every added row of hbo, arc, grc recomputed by 4.11 (1.8) and D18 step 2; the new subject rows
      counted by stem or voice and by field against i1, beside the figures of 4.11 (1.8);
  M2  the larger set: every who recomputed by step W (1.8); every entity M2 leaves out listed; no who holds a member
      the larger set adds whose type is neither a type of the smaller set nor person nor group;
  M1, M2 in the editions: carried rows of changed grc rows (D39 in 1.8) counted by field; the verb_zero heads of D40;
  M3  the fix tables: sha256, every row applied once, every fixed part model in a model word, lemma, strong, lexeme
      from the table, the keys that move, the K2 landings, every other part equal to i1's;
  M4  the Septuagint form: every unplaced reason the fixed named form; the moves against i1 by kind;
  against i1: every file outside the reach of section 13 (1.8) byte-equal; every file inside it compared row by row;
  rebuild: the build named by --compare (j2) equal file by file (also checked by stage 49's part).
Lines for VALIDATION.md are kept in LINES (lang -> lines).
"""
import collections as C
import csv
import glob
import hashlib
import json
import multiprocessing as mp
import os
import unicodedata as U
import xml.etree.ElementTree as ET

import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
I1 = os.path.join(HERE, "data/source-examples/i1")
ANA = os.path.join(ROOT, "internal-docs/hebrew-nt-analysis-release/v0.2")
LEVEL1 = os.path.join(HERE, "text_faults/level1_fixes.tsv")
STRONG = os.path.join(HERE, "text_faults/strong_fixes.tsv")
PIN = {"level1_fixes.tsv": "2f42b3e9", "strong_fixes.tsv": "585a53c3"}     # SPEC section 5 (1.8)
LOWFAT = os.path.join(HERE, ".lowfat-src/WLC/lowfat")
XID = "{http://www.w3.org/XML/1998/namespace}id"
SWAP = str.maketrans("ξχΞΧ", "χξΧΞ")     # F0016, written here again (not imported)
LANGS = ("hbo", "arc", "grc")
EDS = ("heb_mod", "heb_scg")
CAUS = {"hiphil", "haphel", "aphel", "shaphel"}
PASSIVE = {"hbo": {"niphal", "pual", "hophal", "qal_passive", "pulal", "polal", "poal", "polpal"},
           "arc": {"peil", "hophal", "hithpeel", "hithpaal", "ithpeel", "ithpaal", "ithpoel"},
           "grc": {"pass", "midpass"}}
KEEP = {"person", "group"}
# the figures of SPEC 4.11 (1.8), D18 (1.8), D39 (1.8), D23 (1.8), D13a (1.8), counted over i1 by stage 51
EXP = {
    "M1 new subject rows": {"hbo": 952, "arc": 24, "grc": 743},
    "M1 by stem or voice": {"hbo": {"niphal": 739, "pual": 100, "hophal": 98, "qal_passive": 9, "polal": 4, "polpal": 2},
                            "arc": {"peil": 10, "hithpeel": 6, "hithpaal": 4, "hophal": 4},
                            "grc": {"pass": 735, "midpass": 8}},
    "M1 person or number changes": {"hbo": 491, "arc": 9, "grc": 438},
    "M1 person": {"hbo": 296, "arc": 5, "grc": 401}, "M1 number": {"hbo": 382, "arc": 6, "grc": 163},
    "M1 gender": {"hbo": 482, "arc": 6, "grc": 607}, "M1 who": {"hbo": 45, "arc": 1, "grc": 65},
    "M1 who_reason": {"hbo": 378, "arc": 6, "grc": 309},
    "M2 rows of 1.7 subject rows that lose members": {"hbo": 63, "arc": 0, "grc": 50},
    "M2 types left out": {"hbo": {"place": 46, "realia": 8, "fauna": 7, "deity": 1, "flora": 1}, "arc": {},
                          "grc": {"place": 49, "realia": 1}},
    "M2 more who changes on M1 rows": {"hbo": 1, "arc": 0, "grc": 6},
    "added rows that change (M1 + M2)": {"hbo": 1043, "arc": 24, "grc": 793},
    "ed carried rows of a changed grc row": {"heb_mod": 775, "heb_scg": 772},
    "ed of them M1": {"heb_mod": 727, "heb_scg": 725},
    "ed form": {"heb_mod": 538, "heb_scg": 530}, "ed person": {"heb_mod": 285, "heb_scg": 269},
    "ed number": {"heb_mod": 269, "heb_scg": 287}, "ed gender": {"heb_mod": 338, "heb_scg": 348},
    "ed who M1": {"heb_mod": 65, "heb_scg": 64}, "ed who M2": {"heb_mod": 48, "heb_scg": 47},
    "ed who_reason": {"heb_mod": 302, "heb_scg": 301},
    "M3 fixed parts": {"heb_mod": 574, "heb_scg": 651},
    "M3 K1->K1": {"heb_mod": 569, "heb_scg": 645}, "M3 K1->K2": {"heb_mod": 5, "heb_scg": 6},
    "M3 parts rows": {"heb_mod": 170028},
    "M3 keys go": ["6229.1", "17049.1", "28484.1", "28932.1", "30936.1", "31504.1", "41962.1", "48761.1", "51797.1",
                   "64461.1", "71777.1", "74217.1", "75270.1", "80437.1", "82044.1"],
    "M3 keys come": ["14138.1", "37873.1", "43589.1", "55630.1"],
    "M4 how": {"form_near": 23644, "verse_form": 4723, "number": 5094, "lemma": 841, "verse_lemma": 287, "verse_number": 96},
    "M4 moves": {"all": 3036, "newly placed": 1507, "newly placed strict": 873, "model->strict same word": 973,
                 "model->strict other word": 227, "strict->model same word": 272, "strict->model other word": 18,
                 "strict->strict other word": 10, "model->model": 24, "no longer placed": 5},
    "M4 unplaced reasons that change": {"hbo": 5947, "arc": 30},
}
LINES = C.defaultdict(list)       # lang -> lines for VALIDATION.md
DRIFT_OK = {}                     # set by run(): the artefact rows of step W (recomputed differently in i1 already)


def H(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def T(p, cols=None):
    return pq.read_table(p, columns=cols).to_pylist()


def TSV(p):
    csv.field_size_limit(1 << 30)
    with open(p, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))


def nfc(s):
    return U.normalize("NFC", s or "")


def etype(e):
    return e.split(":")[0]


def line(lang, s):
    LINES[lang].append(s)


# ---- M3: the fix tables, applied by code of its own -------------------------------------------------------------------

def apply_fixes(ed, rows):
    """hebrew-nt-analysis rows of `ed` with the two tables applied (level-1 first, then the Strong's numbers), written here
    from the tables' documented rule (D14 in 1.8), not imported. Returns (rows, {"level1": n, "strong": n})."""
    used = {"level1": 0, "strong": 0}
    if ed == "heb_mod":
        fix = {}
        for r in TSV(LEVEL1):
            b, cv = r["ref"].split()
            c, v = cv.split(":")
            fix[(b, int(c), int(v), int(r["position"]))] = r["to_cut"]
        by = C.OrderedDict()
        for r in rows:
            by.setdefault((r["book"], r["chapter"], r["verse"], r["i"]), []).append(r)
        out = []
        for k, ps in by.items():
            to = fix.get(k)
            if to is None:
                out += ps
                continue
            r0 = min(ps, key=lambda r: r["part"])
            if r0["token"] != "אתם":
                raise SystemExit(f"level1_fixes.tsv: {k} is not אתם")
            base = dict(r0, source="rule", form=None, person=None, role=None)
            if to == "whole":
                out.append(dict(base, part=0, text="אתם", **{"class": "pron"}, lemma="אַתֶּם", lexeme="hbo:0859a",
                                strong="0859a", role=r0.get("role")))
            else:
                prep = to == "split_prep"
                out.append(dict(base, part=0, text="את", **{"class": "prep" if prep else "om"}, lemma="אֵת",
                                lexeme="hbo:0854" if prep else "hbo:0853", strong="0854" if prep else "0853"))
                out.append(dict(base, part=1, text="ם", **{"class": "pron"}, lemma="הוּא", lexeme="hbo:2050c",
                                strong="2050c", p_split=None))
            used["level1"] += 1
        rows = out
    fx = {(r["book"], int(r["chapter"]), int(r["verse"]), int(r["i"]), int(r["part"])): r
          for r in TSV(STRONG) if r["edition"] == ed}
    out = []
    for r in rows:
        f = fx.get((r["book"], r["chapter"], r["verse"], r["i"], r["part"]))
        if f is None:
            out.append(r)
            continue
        if r["text"] != f["text"] or (r["strong"] or "") != f["from_strong"]:
            raise SystemExit(f"strong_fixes.tsv: {ed} {r['book']} {r['chapter']}:{r['verse']} {r['i']}.{r['part']} differs")
        out.append(dict(r, strong=f["to_strong"], lemma=f["to_lemma"], lexeme=f["to_lexeme"], source="rule"))
        used["strong"] += 1
    return out, used


# ---- M1, M2 over hbo, arc, grc ----------------------------------------------------------------------------------------

def load_lang(b, lg):
    d = os.path.join(b, lg)
    P = T(os.path.join(d, "pieces.parquet"), ["t", "n", "kind", "marks", "who"])
    stem = {p["t"]: (p["n"], json.loads(p["marks"]) if p["marks"] else {}) for p in P if p["kind"] == "stem"}
    who = {(p["t"], p["n"]): set((p["who"] or "").split()) for p in P}
    fr = C.defaultdict(set)
    for r in T(os.path.join(d, "constituents.parquet"), ["clause", "frame_role"]):
        fr[r["clause"]].update((r["frame_role"] or "").split())
    W = {w["t"]: f"{w['book']} {w['chapter']}:{w['verse']}" for w in
         T(os.path.join(d, "words.parquet"), ["t", "book", "chapter", "verse"])}
    return stem, who, fr, W


def subj_rows(lg, A, stem, fr, m1):
    """(clause, verb, role) -> (subject by 1.6, subject by 1.8 M1) for every row but poss."""
    aa_row = {(a["clause"], a["verb"]) for a in A if a["role"] == "AA"}
    a0aa = {a["verb"] for a in A if a["role"] in ("A0", "AA")}
    out = {}
    for a in A:
        if a["role"] == "poss":
            continue
        _, m = stem.get(a["verb"], (None, {}))
        caus = m.get("stem") in CAUS
        has_aa = (a["clause"], a["verb"]) in aa_row or "AA" in fr[a["clause"]]
        s16 = a["role"] == (("AA" if has_aa else "A0") if caus else "A0")
        k = (m.get("voice") if lg == "grc" else m.get("stem")) or ""
        s18 = s16 or (m1 and a["role"] == "A1" and bool(m.get("person")) and k in PASSIVE[lg]
                      and a["verb"] not in a0aa and not ({"A0", "AA"} & fr[a["clause"]]))
        out[(a["clause"], a["verb"], a["role"])] = (s16, s18, k)
    return out


def stepw(vs, ns, m, ant, m2):
    """-> (who set, reason, left out set, larger taken)"""
    if vs and ns:
        if vs <= ns or ns <= vs:
            small, large = (vs, ns) if vs <= ns else (ns, vs)
            if m.get("number") == "sg":
                return small, "verb_and_antecedent", set(), False
            out = set()
            if m2 and large != small:
                st = {etype(e) for e in small}
                out = {e for e in large - small if etype(e) not in st and etype(e) not in KEEP}
            return large - out, "verb_and_antecedent", out, large != small
        i = vs & ns
        return (i, "verb_and_antecedent", set(), False) if i else (set(), "disagree", set(), False)
    if vs:
        return vs, "verb", set(), False
    if ns:
        return ns, "antecedent", set(), False
    return set(), ("no_antecedent" if not ant else "antecedent_no_participant"), set(), False


def recompute_who(A, S, stem, who, m1m2):
    """(clause, verb, role) -> (who string, reason, left out, larger taken, small)"""
    out = {}
    for a in A:
        key = (a["clause"], a["verb"], a["role"])
        if a["role"] == "poss":
            out[key] = ("", "guess", set(), False, set())
            continue
        s16, s18, _ = S[key]
        subj = s18 if m1m2 else s16
        sn, m = stem.get(a["verb"], (None, {}))
        vs = who.get((a["verb"], sn), set()) if subj and sn is not None else set()
        ns = who.get(tuple(map(int, a["antecedent"].split("."))), set()) if a["antecedent"] else set()
        w, why, left, larger = stepw(vs, ns, m, a["antecedent"], m1m2)
        small = (vs if vs <= ns else ns) if vs and ns and (vs <= ns or ns <= vs) else set()
        out[key] = (" ".join(sorted(w)), why, left, larger, small)
    return out


def m1m2(R, build, about):
    kterm = {}
    grc_change = {}
    for lg in LANGS:
        R.section(f"{lg} passive subjects and the larger set (1.8, M1, M2)")
        stem, who, fr, W = load_lang(build, lg)
        A = T(os.path.join(build, lg, "added.parquet"))
        A1 = T(os.path.join(I1, lg, "added.parquet"))
        i1k = {(a["clause"], a["verb"], a["role"]): a for a in A1}
        jk = {(a["clause"], a["verb"], a["role"]): a for a in A}
        R.check(f"{lg} added (1.8): the same rows as i1 (keys), in the same order",
                [(a["clause"], a["verb"], a["role"]) for a in A] == [(a["clause"], a["verb"], a["role"]) for a in A1],
                f"{len(A):,} rows")
        S = subj_rows(lg, A, stem, fr, True)
        kt = C.Counter(a["kind"] for a in A1 if a["form"] == "ending")
        kterm[lg] = kt.most_common(1)[0][0]
        bad = []
        for a in A:
            key = (a["clause"], a["verb"], a["role"])
            if a["role"] == "poss":
                if a["form"] != "none":
                    bad.append(key)
                continue
            s16, s18, _ = S[key]
            _, m = stem.get(a["verb"], (None, {}))
            want_end = s18 and "person" in m
            if (a["form"] == "ending") != want_end or ((a["kind"] == kterm[lg]) != (a["form"] == "ending")):
                bad.append(key)
            elif want_end and any((a[f] or "") != (m.get(f) or "") for f in ("person", "number", "gender")):
                bad.append(key)
        R.check(f"{lg} added (1.8, M1): form ending exactly on the subject rows of 4.11 (1.8) whose verb's stem piece has "
                "a person; kind in_verb exactly on them; person, number, gender the stem piece's", not bad,
                f"{len(bad)} wrong {bad[:3]}")
        # new subject rows and their fields against i1
        new = [k for k, (s16, s18, _) in S.items() if s18 and not s16]
        by = C.Counter(S[k][2] for k in new)
        fc = C.Counter()
        pn = 0
        for k in new:
            a, o = jk[k], i1k[k]
            for f in ("kind", "form", "person", "number", "gender", "who", "who_reason"):
                fc[f] += (a[f] or "") != (o[f] or "")
            pn += (a["person"] or "") != (o["person"] or "") or (a["number"] or "") != (o["number"] or "")
        got = {"M1 new subject rows": len(new), "M1 person or number changes": pn, "M1 person": fc["person"],
               "M1 number": fc["number"], "M1 gender": fc["gender"], "M1 who": fc["who"], "M1 who_reason": fc["who_reason"]}
        for k, v in got.items():
            R.check(f"{lg} M1 (1.8): {k} {v:,}, 4.11 (1.8) says {EXP[k][lg]:,}", v == EXP[k][lg], f"{v:,}")
        R.check(f"{lg} M1 (1.8): new subject rows by stem or voice as 4.11 (1.8)", dict(by) == EXP["M1 by stem or voice"][lg],
                dict(by.most_common()))
        R.check(f"{lg} M1 (1.8): kind and form change on every new subject row", fc["kind"] == fc["form"] == len(new) or
                not new, f"kind {fc['kind']}, form {fc['form']}")
        line(lg, f"- M1 new subject rows {len(new):,} (by stem or voice {dict(by.most_common())}); fields changed against i1 "
                 f"{dict(fc)}")
        # step W recomputed (1.8), with the artefact rows of 1.7 (recompute != i1 in i1 itself) named
        st1, wh1, fr1, _ = load_lang(I1, lg)
        S1 = subj_rows(lg, A1, st1, fr1, False)
        R17 = recompute_who(A1, S1, st1, wh1, False)
        art = {k for k, v in R17.items() if (v[0], v[1]) != ((i1k[k]["who"] or ""), i1k[k]["who_reason"])}
        R18 = recompute_who(A, S, stem, who, True)
        diff = {k for k, v in R18.items() if (v[0], v[1]) != ((jk[k]["who"] or ""), jk[k]["who_reason"])}
        R.check(f"{lg} added (1.8, M2): every who and who_reason recomputed by step W (1.8); a difference only on a row "
                "where step W of 1.7 recomputed over i1 already differs from i1 (the builder reads its own who)",
                diff <= art, f"differ {len(diff)} (on i1's artefact rows {len(diff & art)}); i1 artefact rows {len(art)}: "
                f"{[f'{W.get(k[1])} {k[1]} {k[2]}' for k in sorted(art)][:4]}")
        # M2: left out, by type; and no forbidden member
        left = [(k, e) for k, v in R18.items() for e in sorted(v[2])]
        lost17 = set()
        types = C.Counter()
        m1more = 0
        for k, v in R18.items():
            if not v[2]:
                continue
            if S[k][0]:
                lost17.add(k)
                for t in {etype(e) for e in v[2]}:
                    types[t] += 1
            else:
                w17 = stepw(*_vsns(k, jk[k], S, stem, who), stem.get(k[1], (None, {}))[1], jk[k]["antecedent"], False)
                m1more += " ".join(sorted(w17[0])) != v[0]
        R.check(f"{lg} M2 (1.8): rows of 1.7's subject rows that lose members {len(lost17)}, D18 (1.8) says "
                f"{EXP['M2 rows of 1.7 subject rows that lose members'][lg]}",
                len(lost17) == EXP["M2 rows of 1.7 subject rows that lose members"][lg], len(lost17))
        R.check(f"{lg} M2 (1.8): types left out (rows per type) as D18 (1.8)", dict(types) == EXP["M2 types left out"][lg],
                dict(types.most_common()))
        R.check(f"{lg} M2 (1.8): who changes by M2 on M1's new rows {m1more}, D18 (1.8) says "
                f"{EXP['M2 more who changes on M1 rows'][lg]}", m1more == EXP["M2 more who changes on M1 rows"][lg], m1more)
        forb = []
        for a in A:
            k = (a["clause"], a["verb"], a["role"])
            v = R18[k]
            if not v[3]:
                continue
            st = {etype(e) for e in v[4]}
            for e in set((a["who"] or "").split()) - v[4]:
                if etype(e) not in st and etype(e) not in KEEP:
                    forb.append((k, e))
        R.check(f"{lg} added (1.8, M2): no who holds a member the larger set adds whose type is neither a type of the "
                "smaller set nor person nor group", not forb, f"{len(forb)} {forb[:3]}")
        R.info(f"{lg} M2 (1.8): entities left out (rows {len({k for k, _ in left})}, entities {len(left)})",
               "; ".join(f"{W.get(k[1])} verb {k[1]} {k[2]} {e} ({etype(e)})" for k, e in left[:12])
               + (" …" if len(left) > 12 else ""))
        line(lg, f"- M2 entities left out by step W (1.8): {len(left)} on {len({k for k, _ in left})} rows (row: verse, "
                 "verb t, role, entity, type):")
        for k, e in left:
            line(lg, f"  - {W.get(k[1])}, verb {k[1]}, {k[2]}, clause {k[0]}: `{e}` ({etype(e)})")
        ch = {k for k in jk if any((jk[k][f] or "") != (i1k[k][f] or "") for f in jk[k])}
        artc = sorted(art - ch)      # stage 51 counted these: its recompute of 1.7 differs from i1 there (not a change)
        R.check(f"{lg} added (1.8): rows that change against i1 {len(ch):,}; with the {len(artc)} rows where stage 51's "
                f"recompute differs from i1 (listed) {len(ch) + len(artc):,}, D18 (1.8) says "
                f"{EXP['added rows that change (M1 + M2)'][lg]:,}",
                len(ch) + len(artc) == EXP["added rows that change (M1 + M2)"][lg], len(ch))
        if artc:
            R.info(f"{lg} added (1.8): the rows stage 51 counted as changed that keep i1's value (step W of 1.7 recomputed "
                   "from the final pieces.who differs from the builder's own who there)",
                   "; ".join(f"{W.get(k[1])} verb {k[1]} {k[2]}" for k in artc))
            line(lg, f"- the {len(artc)} rows stage 51 counted as changed but that keep i1's value (its recompute read the "
                     "final pieces.who of the antecedent, the builder its own): " + "; ".join(
                         f"{W.get(k[1])} verb {k[1]} {k[2]}" for k in artc))
        other = [k for k in ch if not (S[k][1] and not S[k][0]) and k not in {x for x, _ in left}]
        R.check(f"{lg} added (1.8): every changed row is a new subject row of M1 or a row M2 changes", not other,
                f"{len(other)} {other[:3]}")
        about[f"{lg} M1 new subject rows"] = len(new)
        if lg == "grc":
            grc_change = {k: (S[k][1] and not S[k][0]) for k in ch}
    return grc_change


def _vsns(k, a, S, stem, who):
    sn, m = stem.get(a["verb"], (None, {}))
    vs = who.get((a["verb"], sn), set()) if S[k][1] and sn is not None else set()
    ns = who.get(tuple(map(int, a["antecedent"].split("."))), set()) if a["antecedent"] else set()
    return vs, ns


def editions_m1m2(R, build, grc_change):
    for ed in EDS:
        R.section(f"{ed} carried added rows (1.8, D39, M1, M2)")
        A = T(os.path.join(build, ed, "added.parquet"))
        A1 = T(os.path.join(I1, ed, "added.parquet"))
        # the clause keys of section 3 hold the clause's piece count, which M3's level-1 cuts change: map by row
        K, K1 = T(os.path.join(build, ed, "clauses.parquet"), ["clause", "first", "last"]), \
            T(os.path.join(I1, ed, "clauses.parquet"), ["clause", "first", "last"])
        lvt = set()
        if ed == "heb_mod":       # the edition words of the 19 level-1 tokens
            ids = {f"{ed} {r['ref']} {r['position']}" for r in TSV(LEVEL1)}
            lvt = {r["t"] for r in T(os.path.join(build, ed, "words.parquet"), ["t", "id"]) if r["id"] in ids}
        span = [(x, y) for x, y in zip(K, K1) if (x["first"], x["last"]) != (y["first"], y["last"])]
        near = lambda r: any(abs(r["first"] - t) <= 1 or abs(r["last"] - t) <= 1 for t in lvt)   # noqa: E731
        bad_span = [(x["clause"], y["clause"]) for x, y in span if not (near(x) or near(y))]
        cmap = {y["clause"]: x["clause"] for x, y in zip(K, K1)}
        moved = sorted(f"{y} -> {x}" for y, x in cmap.items() if x != y)
        R.check(f"{ed} clauses (1.8): the same clauses as i1, row by row; a span (first, last) moves only next to one of "
                "the 19 level-1 words (M3: a cut את + ם is an opener of D31); keys moved by M3 listed",
                len(K) == len(K1) and not bad_span, f"{len(K):,} clauses; spans moved {len(span)}, not next to a level-1 "
                f"word {len(bad_span)}; keys moved {len(moved)}: {moved[:4]}")
        k1 = {(cmap.get(a["clause"], a["clause"]), a["verb"], a["role"]): a for a in A1}
        R.check(f"{ed} added (1.8): the same keys as i1 (through the clause map)",
                [(a["clause"], a["verb"], a["role"]) for a in A] == list(k1), f"{len(A):,} rows")
        sm = {(r["t"], r["n"]): r["marks"] for r in T(os.path.join(build, ed, "pieces.parquet"), ["t", "n", "kind", "marks"])
              if r["kind"] == "stem"}
        sm1 = {(r["t"], r["n"]): r["marks"] for r in T(os.path.join(I1, ed, "pieces.parquet"), ["t", "n", "kind", "marks"])
               if r["kind"] == "stem"}
        vstem = {t: m for (t, n), m in sm.items()}
        vstem1 = {t: m for (t, n), m in sm1.items()}
        bs = {(r["t"]): r["basis"] for r in T(os.path.join(build, ed, "pieces.parquet"), ["t", "kind", "basis"]) if r["kind"] == "stem"}
        bs1 = {(r["t"]): r["basis"] for r in T(os.path.join(I1, ed, "pieces.parquet"), ["t", "kind", "basis"]) if r["kind"] == "stem"}
        c = C.Counter()
        other, m3rows = [], []
        for a in A:
            o = k1.get((a["clause"], a["verb"], a["role"]))
            g = (a["from_clause"], a["from_t"], a["role"])
            changed = o is not None and any((a[f] or "") != (o[f] or "") for f in a if f != "clause")
            if g in grc_change:
                c["carried rows of a changed grc row"] += 1
                m1 = grc_change[g]
                c["of them M1"] += m1
                for f in ("form", "who_reason"):
                    c[f] += (a[f] or "") != (o[f] or "")
                m1m = json.loads(vstem1.get(a["verb"]) or "{}")
                for f in ("person", "number", "gender"):
                    if (a[f] or "") != (o[f] or ""):
                        c[f + (" (ending rows)" if a["form"] == "ending" else " (rows of form none: the Greek row's new "
                                                                              "value carried)")] += 1
                    if a["form"] == "ending" and (m1m.get(f) or "") != (o[f] or ""):
                        c[f + " (ending rows, read with i1's stem marks as stage 51 did)"] += 1
                c["who M1" if m1 else "who M2"] += (a["who"] or "") != (o["who"] or "")
            elif changed:
                (m3rows if (vstem.get(a["verb"]), bs.get(a["verb"])) != (vstem1.get(a["verb"]), bs1.get(a["verb"]))
                 else other).append(a)
        R.info(f"{ed} D39 (1.8): person, number, gender changes on ending rows in j1 (with j1's stem marks, which M3 "
               "moves on a few verbs)", {k: v for k, v in c.items() if k.endswith("(ending rows)")})
        sfx = " (ending rows, read with i1's stem marks as stage 51 did)"
        for k, e in (("carried rows of a changed grc row", "ed carried rows of a changed grc row"),
                     ("of them M1", "ed of them M1"), ("form", "ed form"), ("person" + sfx, "ed person"),
                     ("number" + sfx, "ed number"), ("gender" + sfx, "ed gender"), ("who M1", "ed who M1"),
                     ("who M2", "ed who M2"), ("who_reason", "ed who_reason")):
            R.check(f"{ed} D39 (1.8): {k} {c[k]:,}, D39 (1.8) says {EXP[e][ed]:,}", c[k] == EXP[e][ed], c[k])
        R.info(f"{ed} D39 (1.8): person, number, gender changes on rows of form none (stage 51's count left them out: "
               "D39 carries the Greek row's person, number, gender there, and M1 changed them on grc)",
               {k: v for k, v in c.items() if "form none" in k})
        R.check(f"{ed} added (1.8): no row changes against i1 but those of a changed grc row, or of a verb whose stem "
                "marks or basis M3 moved (D36 over a fixed lexeme; a later D23 step)", not other,
                f"{len(other)} {[(a['clause'], a['verb'], a['role']) for a in other[:3]]}; M3 rows {len(m3rows)}")
        R.info(f"{ed} added (1.8): rows changed by M3 (the verb's stem marks moved by D36)",
               f"{len(m3rows)}: " + "; ".join(f"{a['clause']} {a['verb']} {a['role']}" for a in m3rows[:10]))
        line(ed, f"- added rows changed by M3 (the verb's stem marks moved): {len(m3rows)}; clause keys moved by M3: "
                 f"{len(moved)}: " + "; ".join(moved))
        line(ed, f"- D39 (1.8): carried rows of a changed grc row {c['carried rows of a changed grc row']:,}; fields {dict(c)}")
        wa = C.Counter(r["head_kind"] for r in T(os.path.join(build, ed, "who_account.parquet"), ["head_kind"]))
        wa1 = C.Counter(r["head_kind"] for r in T(os.path.join(I1, ed, "who_account.parquet"), ["head_kind"]))
        R.info(f"{ed} D40 (1.8): verb_zero heads j1 / i1 (M1 adds {wa['verb_zero'] - wa1['verb_zero']:,})",
               f"{wa['verb_zero']:,} / {wa1['verb_zero']:,}; all heads {sum(wa.values()):,} / {sum(wa1.values()):,}")
        line(ed, f"- D40 (1.8): verb_zero heads {wa['verb_zero']:,} (i1 {wa1['verb_zero']:,}; M1 adds "
                 f"{wa['verb_zero'] - wa1['verb_zero']:,})")


# ---- M3 ---------------------------------------------------------------------------------------------------------------

def m3(R, build):
    R.section("the fix tables (1.8, M3)")
    for p in (LEVEL1, STRONG):
        s = H(p)
        R.check(f"M3 (1.8): {os.path.basename(p)} has the sha256 of section 5 ({PIN[os.path.basename(p)]}…)",
                s.startswith(PIN[os.path.basename(p)]), s[:16])
    nlev = len(TSV(LEVEL1))
    nstr = C.Counter(r["edition"] for r in TSV(STRONG))
    R.check("M3 (1.8): the tables hold 19 tokens and 555 + 651 parts", nlev == 19 and nstr == {"heb_mod": 555, "heb_scg": 651},
            f"{nlev}; {dict(nstr)}")
    lex = {r["lexeme"] for r in TSV(os.path.join(build, "lexicon", "lexemes.tsv"))}
    for ed in EDS:
        raw = T(os.path.join(ANA, ed, "words.parquet"))
        fixed, used = apply_fixes(ed, raw)
        R.check(f"{ed} M3 (1.8): every row of each table applied to exactly one analysis row",
                used["strong"] == nstr[ed] and used["level1"] == (19 if ed == "heb_mod" else 0), used)
        P = T(os.path.join(build, "other", ed, "parts.parquet"))
        P1 = T(os.path.join(I1, "other", ed, "parts.parquet"))
        Wd = T(os.path.join(build, "other", ed, "words.parquet"))
        s_of = {(w["book"], w["chapter"], w["verse"], w["w"]): w for w in Wd}
        pk = {(r["s"], r["p"]): r for r in P}
        pk1 = {(r["s"], r["p"]): r for r in P1}
        R.check(f"{ed} M3 (1.8): parts.parquet rows {len(P):,}" + (f", D23 (1.8) says {EXP['M3 parts rows'][ed]:,}"
                if ed in EXP["M3 parts rows"] else f", i1 {len(P1):,}"),
                len(P) == EXP["M3 parts rows"].get(ed, len(P1)), len(P))
        frows = [r for r in fixed if r["source"] == "rule"]
        lv_words = set()
        if ed == "heb_mod":
            for r in TSV(LEVEL1):
                b, cv = r["ref"].split()
                c, v = cv.split(":")
                lv_words.add(s_of[(b, int(c), int(v), int(r["position"]))]["s"])
        bad_basis, bad_val, k2, rules = [], [], [], C.Counter()
        fixed_keys = set()
        for r in frows:
            w = s_of.get((r["book"], r["chapter"], r["verse"], r["i"]))
            if w is None or not r["text"]:
                continue
            key = (w["s"], r["part"])
            fixed_keys.add(key)
            p = pk.get(key)
            if p is None:
                bad_val.append((key, "missing"))
                continue
            if p["basis"] != "model" or w["analysis_basis"] != "model":
                bad_basis.append(key)
            lang = r["lexeme"].split(":")[0] if r["lexeme"] else ""
            k2ok = p["key_rule"] == "K2" and p["lexeme"].startswith("lex:arc:")     # D23 (1.8): kept, listed
            if (p["lemma"], p["strong"]) != (r["lemma"] or "", r["strong"] or "") or p["lexeme"] not in lex or \
                    not (p["lexeme"].startswith(f"lex:{lang}:") or k2ok) or not p["lexeme"].endswith(":" + (r["strong"] or "")):
                bad_val.append((key, p["lemma"], p["strong"], p["lexeme"]))
            o = pk1.get(key)
            rules[f"{o['key_rule'] if o else '-'} -> {p['key_rule']}"] += 1
            if p["lexeme"].startswith("lex:arc:"):
                k2.append(f"s={key[0]} p={key[1]} {p['text']} {p['lexeme']}")
        n_fixed = len(fixed_keys)
        n_count = used["strong"] + used["level1"]
        R.check(f"{ed} M3 (1.8): fixed parts {n_count:,} (the Strong's table's parts {used['strong']:,} + the level-1 "
                f"tokens {used['level1']}), D23 (1.8) says {EXP['M3 fixed parts'][ed]:,}",
                n_count == EXP["M3 fixed parts"][ed], f"parts with source rule {n_fixed:,}")
        R.check(f"{ed} M3 (1.8): every fixed part has basis model and lies in a word of analysis_basis model",
                not bad_basis, f"{len(bad_basis)} {bad_basis[:3]}")
        R.check(f"{ed} M3 (1.8): lemma and strong of every fixed part the table's; its lexeme a key of the table's "
                "language in lexicon/lexemes.tsv", not bad_val, f"{len(bad_val)} {bad_val[:3]}")
        ch_lex = sum(1 for k in fixed_keys if k in pk1 and pk1[k]["lexeme"] != pk[k]["lexeme"])
        R.check(f"{ed} M3 (1.8): the lexeme key changes on every fixed part present in i1",
                ch_lex == sum(1 for k in fixed_keys if k in pk1), f"{ch_lex}")
        R.info(f"{ed} M3 (1.8): key_rule i1 -> j1 on the fixed parts (D23 (1.8): K1->K1 {EXP['M3 K1->K1'][ed]}, "
               f"K1->K2 {EXP['M3 K1->K2'][ed]})", dict(sorted(rules.items())))
        R.info(f"{ed} M3 (1.8): K2 landings (an Aramaic Tanakh key, listed, kept as the table gives them)", f"{len(k2)}: {k2}")
        line(ed, f"- M3 fixed parts {n_fixed:,}; key_rule i1 -> j1 {dict(sorted(rules.items()))}; K2 landings {len(k2)}: "
                 + "; ".join(k2))
        gone = sorted(f"{s}.{p}" for (s, p) in set(pk1) - set(pk))
        come = sorted(f"{s}.{p}" for (s, p) in set(pk) - set(pk1))
        if ed == "heb_mod":
            R.check(f"{ed} M3 (1.8): the part keys that go and come are D23 (1.8)'s",
                    sorted(gone) == sorted(EXP["M3 keys go"]) and sorted(come) == sorted(EXP["M3 keys come"]),
                    f"go {len(gone)}, come {len(come)}")
            Pe = C.defaultdict(list)
            for r in T(os.path.join(build, ed, "pieces.parquet"), ["t", "n", "text"]):
                Pe[r["t"]].append((r["n"], r["text"]))
            Wt = {r["id"]: r["t"] for r in T(os.path.join(build, ed, "words.parquet"), ["t", "id"])}
            sid = {w["s"]: w["id"] for w in Wd}
            bad_e = []
            for s in sorted(lv_words):
                parts = sorted((r["p"], r["text"]) for r in P if r["s"] == s)
                t = Wt.get(sid[s])
                if t is None or [x[1] for x in sorted(Pe[t])] != [x[1] for x in parts] or \
                        [x[0] for x in sorted(Pe[t])] != list(range(1, len(parts) + 1)):
                    bad_e.append(s)
            R.check(f"{ed} M3 (1.8): the edition pieces (t, n) of the 19 level-1 words equal their parts", not bad_e,
                    f"{len(lv_words)} words; {bad_e[:3]}")
        else:
            R.check(f"{ed} M3 (1.8): no part key goes or comes", not gone and not come, f"{gone[:3]} {come[:3]}")
        lvk = {k for k in pk if k[0] in lv_words} | {k for k in pk1 if k[0] in lv_words}
        rest = [k for k in pk1 if k not in fixed_keys and k not in lvk and pk.get(k) != pk1[k]]
        later = {"K6", "H0", "H1", "H2"}
        bad_rest = [k for k in rest if not ({pk1[k]["key_rule"], pk.get(k, {}).get("key_rule")} & later)]
        R.check(f"{ed} M3 (1.8): every other part of parts.parquet equal to i1's, but parts a later D23 step (K6, H0 to H2) "
                "moves after the fixes (listed)", not bad_rest, f"{len(rest)} differ, {len(bad_rest)} not by a later step")
        if rest:
            desc = [f"s={k[0]} p={k[1]} {pk1[k]['key_rule']} {pk1[k]['basis']} {pk1[k]['lexeme']} -> "
                    f"{pk[k]['key_rule']} {pk[k]['basis']} {pk[k]['lexeme']}" for k in rest if k in pk]
            R.info(f"{ed} M3 (1.8): parts a later D23 step moves after the fixes", f"{len(rest)}: " + "; ".join(desc))
            line(ed, f"- M3: parts a later D23 step moves after the fixes ({len(rest)}): " + "; ".join(desc))
        # words.parquet: analysis of the fixed words only
        W1 = {w["s"]: w for w in T(os.path.join(I1, "other", ed, "words.parquet"))}
        fw = {k[0] for k in fixed_keys} | lv_words
        dw = [w["s"] for w in Wd if w != W1.get(w["s"])]
        R.check(f"{ed} M3 (1.8): other/{ed}/words.parquet differs from i1 only in the analysis of the fixed words",
                set(dw) <= fw and all({k for k in w if w[k] != W1[w["s"]][k]} <= {"analysis"} for w in Wd if w["s"] in set(dw)),
                f"{len(dw)} words differ; fixed words {len(fw)}")


# ---- M4 ---------------------------------------------------------------------------------------------------------------

def _gfile(path):
    return [(el.get(XID), el.get("greek")) for el in ET.parse(path).getroot().iter("w")]


def named_forms():
    files = sorted(glob.glob(os.path.join(LOWFAT, "*-lowfat.xml")))
    with mp.get_context("fork").Pool(8) as pool:
        return dict(x for f in pool.map(_gfile, files, chunksize=8) for x in f)


def m4(R, build):
    R.section("the Septuagint form (1.8, M4)")
    raw = named_forms()
    fixed = {k: (g.translate(SWAP) if g else g) for k, g in raw.items()}
    try:
        import text_faults
        same = all((text_faults.macula_greek(g) if g else g) == fixed[k] for k, g in raw.items())
        R.check("M4 (1.8): text_faults.macula_greek() reads every named form as ξ and χ swapped back", same,
                f"{sum(1 for g in raw.values() if g):,} named forms")
    except ImportError:
        R.skip("M4 (1.8): text_faults.macula_greek()", "module not found")
    nch = sum(1 for k in raw if raw[k] != fixed[k])
    R.info("M4 (1.8): named forms that change when read right (D13a (1.8): 19,876 of 373,897)",
           f"{nch:,} of {sum(1 for g in raw.values() if g):,}")
    moves = C.Counter()
    how = C.Counter()
    for lg in ("hbo", "arc"):
        pid = {(r["t"], r["n"]): r["pid"] for r in T(os.path.join(build, lg, "pieces.parquet"), ["t", "n", "pid"])}
        LA = T(os.path.join(build, lg, "link_account.parquet"))
        LA1 = T(os.path.join(I1, lg, "link_account.parquet"))
        up = [r for r in LA if r["other"] == "lxx" and r["state"] == "unplaced"]
        bad = [r for r in up if r["reason"] != fixed.get(pid[(r["t"], r["n"])])]
        R.check(f"{lg} link_account (1.8, M4): every unplaced reason is the fixed named form of its piece", not bad,
                f"{len(up):,} unplaced; {len(bad)} wrong {[(r['t'], r['n'], r['reason']) for r in bad[:2]]}")
        up1 = {(r["t"], r["n"]): r["reason"] for r in LA1 if r["other"] == "lxx" and r["state"] == "unplaced"}
        both = {(r["t"], r["n"]): r["reason"] for r in up}
        chg = sum(1 for k in both if k in up1 and both[k] != up1[k])
        R.info(f"{lg} M4 (1.8): unplaced in both builds whose reason changes (D13a (1.8) counted unplaced reasons holding "
               f"a swapped form: {EXP['M4 unplaced reasons that change'][lg]:,})", chg)
        L = T(os.path.join(build, lg, "links.parquet"))
        L1 = T(os.path.join(I1, lg, "links.parquet"))
        for r in L:
            if r["other"] == "lxx":
                how[r["how"]] += 1

        def per(rows):
            out = {}
            for r in rows:
                if r["other"] != "lxx":
                    continue
                k = (r["t"], r["n"])
                kind = "strict" if r["basis"] == "linked" else "model"
                cur = out.get(k)
                if cur is None or (kind == "model" and cur[0] == "strict" and False):
                    out[k] = (kind, r["s"], r["how"])
                elif kind == "strict" and cur[0] == "model":
                    out[k] = (kind, r["s"], r["how"])
            return out
        a, b = per(L1), per(L)
        for k in set(a) | set(b):
            x, y = a.get(k), b.get(k)
            if x == y:
                continue
            if x is None:
                moves["newly placed"] += 1
                moves["newly placed strict"] += y[0] == "strict"
            elif y is None:
                moves["no longer placed"] += 1
            elif x[0] == "model" and y[0] == "strict":
                moves["model->strict " + ("same word" if x[1] == y[1] else "other word")] += 1
            elif x[0] == "strict" and y[0] == "model":
                moves["strict->model " + ("same word" if x[1] == y[1] else "other word")] += 1
            elif x[0] == y[0] == "strict":
                moves["strict->strict " + ("other word" if x[1] != y[1] else "same word, other how")] += 1
            else:
                moves["model->model"] += 1
            moves["all"] += 1
        acc = C.Counter((r1["state"], r2["state"]) for r1, r2 in zip(LA1, LA) if (r1["t"], r1["n"]) == (r2["t"], r2["n"])
                        and r1["state"] != r2["state"])
        R.info(f"{lg} M4 (1.8): link_account state moves i1 -> j1", dict(acc.most_common()))
    for k, v in EXP["M4 how"].items():
        R.info(f"M4 (1.8): lxx links of how {k} j1 (D13a (1.8) says {v:,})", f"{how[k]:,}")
    for k, v in EXP["M4 moves"].items():
        R.info(f"M4 (1.8): pieces that move, {k} (D13a (1.8) says {v:,}; a piece's link read strict first)", f"{moves[k]:,}")
    R.info("M4 (1.8): pieces that move, other kinds", {k: v for k, v in moves.items() if k not in EXP["M4 moves"]})
    for lg in ("hbo", "arc"):
        line(lg, f"- M4 (1.8): lxx links by how {dict(sorted(how.items()))}; pieces that move against i1 (hbo + arc) "
                 f"{dict(sorted(moves.items()))}")
    return how, moves


# ---- against i1 -------------------------------------------------------------------------------------------------------

def in_reach(rel):
    parts = rel.split("/")
    if parts[0] in ("heb_mod", "heb_scg", "cache", "lexicon"):
        return "M1-M5" if parts[0] in EDS else ("M3" if parts[0] == "lexicon" else "all")
    f = parts[-1]
    if f in ("sources.json", "categories.toml", "COLUMNS.md", "READ-FIRST.md", "VALIDATION.md"):
        return "all"
    if parts[0] == "other":
        return "M3" if len(parts) == 3 and parts[1] in EDS and f in ("words.parquet", "parts.parquet") else ""
    if parts[0] in LANGS and len(parts) == 2:
        if f == "added.parquet" or f[:-8] in ("forms", "paradigms", "markers", "constructions", "orders", "agreement",
                                             "frames", "pairs", "clause_links", "exceptions"):
            return "M1, M2"
        if f == "profile.tsv":
            return "M1, M2, M4"
        if parts[0] in ("hbo", "arc") and f in ("links.parquet", "link_account.parquet"):
            return "M4"
    return ""


def walk(d):
    out = []
    for root, _ds, fs in os.walk(d):
        for f in fs:
            out.append(os.path.relpath(os.path.join(root, f), d))
    return sorted(out)


def diff_table(a, b):
    """-> (rows i1, rows j1, {column: rows differing} or None, rows only in i1, only in j1)"""
    if a.endswith(".parquet"):
        x, y = T(a), T(b)
    else:
        with open(a, encoding="utf-8") as fh:
            x = [{"line": s} for s in fh.read().split("\n")]
        with open(b, encoding="utf-8") as fh:
            y = [{"line": s} for s in fh.read().split("\n")]
    cols = None
    if len(x) == len(y) and (not x or list(x[0]) == list(y[0])):
        cols = C.Counter()
        for r, s in zip(x, y):
            for k in r:
                if r[k] != s[k]:
                    cols[k] += 1
    fx = C.Counter(json.dumps(r, sort_keys=True, ensure_ascii=False, default=str) for r in x)
    fy = C.Counter(json.dumps(r, sort_keys=True, ensure_ascii=False, default=str) for r in y)
    return len(x), len(y), cols, sum((fx - fy).values()), sum((fy - fx).values())


def against_i1(R, build):
    R.section("against i1 (1.8)")
    subs = list(LANGS) + ["other", "lexicon"] + list(EDS)
    out_bad, inside = [], []
    n_out = 0
    for sub in subs:
        a = os.path.join(I1, sub)
        files = sorted(set(walk(a)) | set(walk(os.path.join(build, sub))))
        for f in files:
            rel = f"{sub}/{f}"
            p, q = os.path.join(I1, rel), os.path.join(build, rel)
            if rel.endswith("VALIDATION.md"):
                continue
            mend = in_reach(rel)
            if not mend:
                n_out += 1
                if not os.path.exists(p) or not os.path.exists(q) or H(p) != H(q):
                    out_bad.append(rel)
            elif os.path.exists(p) and os.path.exists(q) and H(p) != H(q):
                inside.append((rel, mend))
    R.check("against i1 (1.8): every data file outside the reach of section 13 (1.8) has the sha256 of i1's",
            not out_bad, f"{n_out} files; {out_bad[:5]}")
    R.info("against i1 (1.8): files inside the reach that differ from i1", len(inside))
    for rel, mend in inside:
        p, q = os.path.join(I1, rel), os.path.join(build, rel)
        if not rel.endswith((".parquet", ".tsv")):
            R.info(f"against i1 (1.8): {rel} ({mend}) differs (a declaration file)", "")
            continue
        n1, n2, cols, only1, only2 = diff_table(p, q)
        R.info(f"against i1 (1.8): {rel} ({mend}) rows i1 {n1:,} j1 {n2:,}",
               (f"rows differing by column {dict(cols.most_common())}; " if cols is not None else "")
               + f"rows only in i1 {only1:,}, only in j1 {only2:,}")
        lg = rel.split("/")[0]
        if lg in LANGS or lg in EDS:
            line(lg, f"- against i1: `{rel}` ({mend}): rows {n1:,} -> {n2:,}"
                     + (f"; rows differing by column {dict(cols.most_common())}" if cols is not None else "")
                     + f"; rows only in i1 {only1:,}, only in j1 {only2:,}")
    return out_bad


def rebuild(R, build, compare):
    R.section("rebuild (1.8)")
    other = os.path.join(os.path.dirname(os.path.normpath(build)), compare) if not os.path.isabs(compare) else compare
    bad, n = [], 0
    for sub in list(LANGS) + ["other", "lexicon"] + list(EDS) + ["cache/glossed"]:
        a, b = os.path.join(build, sub), os.path.join(other, sub)
        fa = [f for f in walk(a) if not f.endswith("VALIDATION.md")]
        fb = [f for f in walk(b) if not f.endswith("VALIDATION.md")] if os.path.isdir(b) else []
        n += len(fa)
        bad += [f"{sub}/{f}" for f in sorted(set(fa) ^ set(fb))]
        bad += [f"{sub}/{f}" for f in fa if f in fb and H(os.path.join(a, f)) != H(os.path.join(b, f))]
    R.check(f"rebuild (1.8): every file of {os.path.basename(os.path.normpath(build))} has the same sha256 in {compare} "
            "(VALIDATION.md aside; the sheets of cache/glossed included)", not bad and n > 0, f"{n} files; {bad[:5]}")


def run(R, build, compare=None, parts=("m1m2", "m3", "m4", "i1")):
    about = {}
    if "m1m2" in parts:
        g = m1m2(R, build, about)
        editions_m1m2(R, build, g)
    if "m3" in parts:
        m3(R, build)
    if "m4" in parts:
        m4(R, build)
    if "i1" in parts:
        against_i1(R, build)
    if compare:
        rebuild(R, build, compare)


def write_md(build, lines_by_stage, upto):
    """VALIDATION.md of hbo, arc, grc: i1's file with a block "new in 1.8"; of the editions: the stage 49 file the caller
    wrote, with the same block appended."""
    for lg in LANGS + EDS:
        p = os.path.join(build, lg, "VALIDATION.md")
        if lg in LANGS:
            with open(os.path.join(I1, lg, "VALIDATION.md"), encoding="utf-8") as fh:
                head = fh.read().rstrip("\n")
            head += ("\n\n(The text above is i1's `VALIDATION.md`, kept: the 1.6 conditions, read on i1. The conditions of "
                     "1.6 and 1.7 read on this build stand in the validator's log; the block below is new in 1.8.)")
        else:
            with open(p, encoding="utf-8") as fh:
                head = fh.read().rstrip("\n")
        L = [head, "", f"## New in 1.8 (stage 52; `validate_examples.py --build {os.path.basename(os.path.normpath(build))} "
             f"--upto {upto} --write-md`)", ""]
        for st, ln in lines_by_stage:
            if st == "52" and (ln.split()[1:2] and (ln.split()[1] == lg or ln.split()[1].startswith(lg + " ")
                                                     or (lg in EDS and ln.split()[1] == "M3" and False))):
                L.append(f"    {ln}")
        L.append("")
        L += LINES.get(lg, [])
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("\n".join(L).rstrip("\n") + "\n")


def m1_keys(build):
    """(clause, verb) of the grc added rows that 4.11 (1.8) makes subject rows by M1 (recomputed here)."""
    stem, _who, fr, _W = load_lang(build, "grc")
    A = T(os.path.join(build, "grc", "added.parquet"))
    S = subj_rows("grc", A, stem, fr, True)
    return {(k[0], k[1]) for k, (s16, s18, _) in S.items() if s18 and not s16 and k[2] == "A1"}
