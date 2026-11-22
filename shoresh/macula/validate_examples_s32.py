"""Stage 32 of the validator: the exit conditions new in SPEC 1.4 (section 10), over an f build.

Called by `validate_examples.py --build f1 --upto 32` after every check of 1.3. Imports nothing from the builders:
D23 to D28 and D24a are recomputed here from the pinned sources and the build's 1.3 tables, and compared with
`other/heb_*/parts.parquet`, `lexicon/` and `arc/facts.parquet`. Also: the strict view of the new tables (recomputed
with every model row of the input left out), the unchanged columns against `e1` (section 13), model attribution, no
English, and with --compare the rebuild of `lexicon/` and the reader's sample.
"""
import collections as C
import csv
import difflib
import glob
import hashlib
import json
import multiprocessing as mp
import os
import re
import unicodedata as U
import xml.etree.ElementTree as ET

import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
EDS = ("heb_mod", "heb_scg")
ANA = {ed: os.path.join(ROOT, f"internal-docs/hebrew-nt-analysis-release/v0.2/{ed}/words.parquet") for ed in EDS}
ANA_SUMS = os.path.join(ROOT, "internal-docs/hebrew-nt-analysis-release/v0.2/SHA256SUMS")
GNUM = os.path.join(ROOT, "resources/lxx_bridge_tiers/greek_numbers.tsv")
GNUM_PIN = "ce0617b7b1a5ef39d32608a8610c50aa2a645de0797fc06181d68867a8bea082"
EQUIV = os.path.join(ROOT, "internal-docs/aramaic-hebrew-equivalents-release/v0.1.1/data/words.parquet")
EQUIV_PIN = "90f71ff81c4637fec8a3afe79efecce3c5b7b7732523fe3b587bbc1c87ce2b46"
LOWFAT = os.path.join(HERE, ".lowfat-src/WLC/lowfat")
XMLID = "{http://www.w3.org/XML/1998/namespace}id"
GLOSSED_F1 = os.path.join(ROOT, "internal-docs/source-examples-work/glossed-f1")

CONTENT = {"noun", "verb", "adj", "adv"}
FUNC = {"negative", "demonstrative", "interrogative", "affirmation", "indefinite", "exhortation", "interjection"}
BASIS_OF_EVIDENCE = {"cognate_meaning": "derived", "domain": "derived", "greek_word": "derived", "greek_verse": "model"}
STATE_CODES = ("member", "nt_only", "function", "name", "no_number", "few_places", "spread", "alone")
HEB = re.compile(r"^[\u0590-\u05FF\uFB1D-\uFB4F\u034F ]*$")


# ---- reading ------------------------------------------------------------------------------------------------------

def sha_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(1 << 22)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def read_tsv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        rows = fh.read().split("\n")
    head = rows[0].split("\t")
    return [dict(zip(head, r.split("\t"))) for r in rows[1:] if r != ""]


def rows_of(path, cols=None):
    return pq.read_table(path, columns=cols).to_pylist()


def norm(s):
    return U.normalize("NFC", s or "")


def numpart(s):
    """Strong's digits, letters dropped, leading zeros dropped ('' for none or 0)."""
    d = "".join(ch for ch in (s or "") if ch.isdigit())
    return str(int(d)) if d and int(d) else ""


def _gs_one(path):
    out = []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "w":
            g = el.get("greekstrong")
            if g:
                out.append((el.get(XMLID), g))
    return out


def lowfat_numbers():
    files = sorted(glob.glob(os.path.join(LOWFAT, "*-lowfat.xml")))
    with mp.get_context("fork").Pool(8) as pool:
        parts = pool.map(_gs_one, files, chunksize=8)
    d = {}
    for lst in parts:
        for xid, g in lst:
            d[xid] = g
    return d, len(files)


def jdump(v):
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


# ---- the recomputation ----------------------------------------------------------------------------------------------

class World:
    """Everything D23 to D27 needs, read once."""

    def __init__(self, build):
        self.build = build
        self.lex = {}
        for lang in ("hbo", "arc"):
            for r in read_tsv(os.path.join(build, lang, "lexemes.tsv")):
                r["lang"] = lang
                self.lex[r["lexeme"]] = r
        self.ana = {}
        for ed in EDS:
            by = C.defaultdict(list)
            for r in rows_of(ANA[ed]):
                by[(r["book"], r["chapter"], r["verse"], r["i"])].append(r)
            self.ana[ed] = by
        self.other = {ed: rows_of(os.path.join(build, "other", ed, "words.parquet"),
                                  ["s", "book", "chapter", "verse", "w", "text", "analysis", "analysis_basis"]) for ed in EDS}
        self.pieces = []
        for lang in ("hbo", "arc"):
            for r in rows_of(os.path.join(build, lang, "pieces.parquet"), ["t", "n", "pid", "lexeme", "kind", "marks"]):
                r["lang"] = lang
                self.pieces.append(r)
        self.gnum_rows = read_tsv(GNUM)
        self.lowfat, self.lowfat_files = lowfat_numbers()
        self.grc_piece_lex = {r["t"]: r["lexeme"] for r in rows_of(os.path.join(build, "grc", "pieces.parquet"), ["t", "lexeme"])}
        self.grc_strong = {r["lexeme"]: r["strong"] for r in read_tsv(os.path.join(build, "grc", "lexemes.tsv"))}
        self.links = rows_of(os.path.join(build, "grc", "links.parquet"), ["t", "other", "s", "basis"])
        self.equiv = rows_of(EQUIV)

    # D23
    def parts(self):
        lex = self.lex
        idx1 = C.defaultdict(set)
        idx3 = C.defaultdict(set)
        idx4 = C.defaultdict(set)
        for k, r in lex.items():
            idx1[(r["lang"], norm(r["lemma"]), r["strong"])].add(k)
            if r["lang"] == "hbo":
                idx3[(norm(r["lemma"]), numpart(r["strong"]))].add(k)
                idx4[numpart(r["strong"])].add(k)
        out, acct, multi = {}, {}, []
        for ed in EDS:
            rows, a = [], C.Counter()
            used = set()
            for w in self.other[ed]:
                key = (w["book"], w["chapter"], w["verse"], w["w"])
                if w["analysis"] is None:
                    a["English tokens (no analysis)"] += 1
                    used.add(key)
                    continue
                used.add(key)
                a["words joined"] += 1
                every = True
                for r in sorted(self.ana[ed][key], key=lambda r: r["part"]):
                    if r["text"] == "" or r["text"] is None:
                        a["letterless parts"] += 1
                        continue
                    lem = norm(r["lemma"])
                    st = r["strong"] or ""
                    rule, k = None, None
                    if r["lexeme"] is None or r["lexeme"] == "":
                        rule, k = "K0", "ntx:hbo:" + lem
                    else:
                        for rr, found in (("K1", idx1.get(("hbo", lem, st), set())), ("K2", idx1.get(("arc", lem, st), set())),
                                          ("K3", idx3.get((lem, numpart(st)), set())),
                                          ("K4", idx4.get(numpart(st), set()) if numpart(st) else set())):
                            if len(found) > 1:
                                multi.append((ed, w["s"], r["part"], rr))
                            if len(found) == 1:
                                rule, k = rr, min(found)
                                break
                        if rule is None:
                            rule, k = "K5", "ntx:hbo:" + lem
                    every = every and not k.startswith("ntx:")
                    cl = r["class"] if r["class"] not in (None, "-") else ""
                    rows.append((w["s"], int(r["part"]), r["text"], cl, r["lemma"] or "", st, k, rule, w["analysis_basis"]))
                    a[f"{rule} {w['analysis_basis']}"] += 1
                    if rule == "K0":
                        a[f"ntx K0 class {cl or '-'}"] += 1
                a[f"words with every part on a Tanakh key, {w['analysis_basis']}"] += every
                a[f"words {w['analysis_basis']}"] += 1
            for key, lst in self.ana[ed].items():
                if key in used:
                    continue
                if all(r["class"] == "verse-number" for r in lst):
                    a["verse-number tokens"] += 1
                else:
                    a["analysis words neither joined nor accounted for"] += 1
            out[ed] = sorted(rows)
            acct[ed] = a
        return out, acct, multi

    # D24 eligibility
    def eligible(self):
        ty, sty = C.defaultdict(C.Counter), C.defaultdict(C.Counter)
        for p in self.pieces:
            t = json.loads(p["marks"]).get("type", "")
            ty[p["lexeme"]][t] += 1
            if p["kind"] == "stem":
                sty[p["lexeme"]][t] += 1
        names, funcs = set(), set()
        for k in self.lex:
            c = ty[k]
            tot = sum(c.values())
            if tot and 2 * (c["proper"] + c["gentilic"]) > tot:
                names.add(k)
            if sty[k]:
                best = max(sty[k].values())
                if min(t for t, n in sty[k].items() if n == best) in FUNC:
                    funcs.add(k)
        elig = {k for k, r in self.lex.items() if r["class"] in CONTENT and k not in names and k not in funcs}
        return elig, names, funcs

    def d24n(self):
        m, stay = {}, set()
        for r in self.gnum_rows:
            if r["nt_strong"]:
                m[numpart(r["source_strong"])] = numpart(r["nt_strong"])
            else:
                stay.add(numpart(r["source_strong"]))
        return m, stay

    def sept(self, elig):
        m, stay = self.d24n()
        pl, moved, two, stayed = [], 0, [], 0
        for p in self.pieces:
            g = self.lowfat.get(p["pid"])
            if not g:
                continue
            if not g.isdigit():
                two.append(p["pid"])
                continue
            g = numpart(g)
            if m.get(g, g) != g:
                g = m[g]
                moved += 1
            elif g in stay:
                stayed += 1
            pl.append((p["lexeme"], g, p["t"], p["n"]))
        return pl, moved, two, stayed

    def nt(self, parts, elig, drop_model=False):
        pos = {ed: C.defaultdict(list) for ed in EDS}
        for ed in EDS:
            for row in parts[ed]:
                if drop_model and row[8] == "model":
                    continue
                pos[ed][row[0]].append(row)
        places, nosingle = [], 0
        per_t = C.defaultdict(lambda: {"heb_mod": set(), "heb_scg": set()})
        for l in self.links:
            if l["other"] not in EDS or l["basis"] != "linked":
                continue
            per_t[l["t"]][l["other"]].add(l["s"])
            st = self.grc_strong.get(self.grc_piece_lex[l["t"]], "")
            if not st.isdigit() or not numpart(st):
                nosingle += 1
                continue
            for row in pos[l["other"]].get(l["s"], []):
                if row[6] in elig:
                    places.append((row[6], numpart(st), row[8]))
        return places, per_t, pos, nosingle


def ubs(a, b, dom):
    if not dom.get(a) or not dom.get(b):
        return None
    best = 0
    for x in dom[a]:
        for y in dom[b]:
            n = 0
            for i in range(0, min(len(x), len(y)) - 2, 3):
                if x[i:i + 3] != y[i:i + 3]:
                    break
                n += 1
            best = max(best, n)
    return best


V16 = False   # an h build (SPEC 1.6): step 2b, kept_out (validate_examples_s38)
V15 = False   # a g build (SPEC 1.5): D23, D25, D26 of 1.5 (validate_examples_s35), set by validate_examples.py


def recompute(Wd, parts, drop_model=False):
    """All of D24 to D27 from the parts (as recomputed) and the World; drop_model = the strict view's input."""
    lex = Wd.lex
    elig, names, funcs = Wd.eligible()
    dom = {k: [d.split(":")[0] for d in r["domains"].split()] for k, r in lex.items()}
    sp, moved, two, stayed = Wd.sept(elig)
    ntp, per_t, pos, nosingle = Wd.nt(parts, elig, drop_model)
    if V15:      # SPEC 1.5 D25 step 1: a place on a function number is no place
        import validate_examples_s35 as S35
        fn = S35.function_numbers(Wd.build)
        sp = [x for x in sp if x[1] not in fn]
        ntp = [x for x in ntp if x[1] not in fn]
        num = lambda t: (Wd.grc_strong.get(Wd.grc_piece_lex.get(t), "") or "")  # noqa: E731
        per_t = {t: v for t, v in per_t.items() if not (num(t).isdigit() and (num(t).lstrip("0") or "0") in fn)}
        ev = C.defaultdict(C.Counter)
    pairs = []
    # sept_number
    cnt = C.defaultdict(C.Counter)
    where = C.defaultdict(list)
    for lx, g, t, n in sp:
        if lx in elig:
            cnt[lx][g] += 1
            where[(lx, g)].append((t, n))
    bynum = C.defaultdict(set)
    for lx, c in cnt.items():
        for g, n in c.items():
            if n >= 3:
                bynum[g].add(lx)
    share = C.defaultdict(set)
    for g, ls in bynum.items():
        for a in ls:
            for b in ls:
                if a < b:
                    share[(a, b)].add(g)
    for (a, b), gs in share.items():
        ca = sum(cnt[a][g] for g in gs)
        cb = sum(cnt[b][g] for g in gs)
        pl = sorted(where[(a, g)][i] for g in gs for i in range(len(where[(a, g)])))
        pl = sorted(pl + [p for g in gs for p in where[(b, g)]])[:3]
        pairs.append({"a": a, "b": b, "evidence": "sept_number", "basis": "given",
                      "via": jdump(["g:" + g for g in sorted(gs, key=int)]), "count": ca + cb,
                      "a_other": sum(cnt[a].values()) - ca, "b_other": sum(cnt[b].values()) - cb,
                      "ubs_depth": ubs(a, b, dom), "places": " ".join(f"{t}.{n}" for t, n in pl)})
    # nt_editions
    for basis in ("linked",) if drop_model else ("linked", "model"):
        found = C.Counter()
        vias = C.defaultdict(set)
        plc = C.defaultdict(list)
        views = []
        for t in sorted(per_t):
            S = {}
            carry = {}
            for ed in EDS:
                S[ed], carry[ed] = set(), C.defaultdict(list)
                for s in sorted(per_t[t][ed]):
                    for row in pos[ed].get(s, []):
                        if row[6] in elig and (basis == "model" or row[8] == "derived"):
                            S[ed].add(row[6])
                            carry[ed][row[6]].append(row)
            A, B = S["heb_mod"], S["heb_scg"]
            if not (A and B):
                continue
            views.append((A, B))
            if A & B:
                continue
            for x in A:
                for y in B:
                    m = any(r[8] == "model" for r in carry["heb_mod"][x] + carry["heb_scg"][y])
                    if (basis == "model") != m:
                        continue
                    k = tuple(sorted((x, y)))
                    found[k] += 1
                    vias[k].add(Wd.grc_piece_lex[t])
                    if len(plc[k]) < 3:
                        r1, r2 = min(carry["heb_mod"][x]), min(carry["heb_scg"][y])
                        plc[k].append(f"heb_mod:{r1[0]}.{r1[1]}+heb_scg:{r2[0]}.{r2[1]}")
        members = C.defaultdict(list)
        for k in found:
            members[k[0]].append(k)
            members[k[1]].append(k)
        against = C.Counter()
        for A, B in views:
            for x in A | B:
                for k in members.get(x, ()):
                    y = k[1] if x == k[0] else k[0]
                    if (x in A and y not in B) or (x in B and y not in A):
                        against[(k, x)] += 1
        for k, n in found.items():
            pairs.append({"a": k[0], "b": k[1], "evidence": "nt_editions", "basis": basis, "via": jdump(sorted(vias[k])),
                          "count": n, "a_other": against[(k, k[0])], "b_other": against[(k, k[1])],
                          "ubs_depth": ubs(k[0], k[1], dom), "places": " ".join(plc[k])})
    # aramaic_list
    hb_full, hb_dig = C.defaultdict(set), C.defaultdict(set)
    for k, r in lex.items():
        if r["lang"] == "hbo":
            hb_full[(norm(r["lemma"]), r["strong"].lstrip("0"))].add(k)
            hb_dig[(norm(r["lemma"]), "".join(ch for ch in r["strong"] if ch.isdigit()).lstrip("0"))].add(k)
    arcp = {p["pid"]: p for p in Wd.pieces if p["lang"] == "arc"}
    lst = C.defaultdict(list)
    unresolved, pickless = C.Counter(), C.Counter()
    for r in Wd.equiv:
        p = arcp.get("o" + r["key"])
        if p is None:
            continue
        hx, b = None, None
        if r["hebrew_strong"] and r["hebrew_lemma"]:
            kk = (norm(r["hebrew_lemma"]), r["hebrew_strong"].lstrip("0"))
            hit = hb_full.get(kk) or set()
            if not hit:
                hit = hb_dig.get(kk) or set()
            if len(hit) == 1:
                hx, b = min(hit), BASIS_OF_EVIDENCE[r["evidence"]]
                if V15:
                    ev[(p["lexeme"], hx)][r["evidence"]] += 1
            else:
                unresolved[p["lexeme"]] += 1
        else:
            pickless[p["lexeme"]] += 1
        if drop_model and b == "model":
            continue
        lst[p["lexeme"]].append((hx, b, p["t"], p["n"]))
    for ax, L in lst.items():
        grp = C.defaultdict(list)
        for hx, b, t, n in L:
            if hx:
                grp[(hx, b)].append((t, n))
        for (hx, b), pl in grp.items():
            if ax in elig and hx in elig:
                oth = sum(1 for h, bb, _, _ in L if h != hx and not (b == "derived" and bb == "model"))
                pairs.append({"a": ax, "b": hx, "evidence": "aramaic_list", "basis": b, "via": "[]", "count": len(pl),
                              "a_other": oth, "b_other": 0, "ubs_depth": ubs(ax, hx, dom),
                              "places": " ".join(f"{t}.{n}" for t, n in sorted(pl)[:3])})
    pairs.sort(key=lambda r: (r["evidence"], r["basis"], r["a"], r["b"]))
    # parts per key
    pc = C.Counter()
    for ed in EDS:
        for row in parts[ed]:
            if drop_model and row[8] == "model":
                continue
            pc[(ed, row[8], row[6])] += 1
    size = lambda k: int(lex[k]["count"]) + pc[("heb_mod", "derived", k)] + pc[("heb_scg", "derived", k)]  # noqa: E731

    pair16 = C.defaultdict(list)
    for p in pairs:
        pair16[frozenset((p["a"], p["b"]))].append(p)
    OUT16 = {}

    def step2b16(G, U, H, prefix):
        """SPEC 1.6 D25 step 2b on the validator's own step-2 groups; -> the keys left with the head alone."""
        nt_ok = ("linked",) if prefix == "cg" else ("linked", "model")
        pend, out = set(), {}
        for k, (anc, ms) in G.items():
            h = H(list(ms))
            leave = []
            for x in sorted(ms):
                if x == h or lex[x]["lang"] != "hbo":
                    continue
                d = ubs(x, h, dom)
                if not (x in U or (d is not None and d < 3)):
                    continue
                ok = False
                for o in ms:
                    if o == x:
                        continue
                    if lex[o]["lang"] == "hbo" and numpart(lex[o]["strong"]) == numpart(lex[x]["strong"]):
                        ok = True
                    for p in pair16.get(frozenset((x, o)), []):
                        if p["evidence"] == "sept_number" and [v for v in json.loads(p["via"]) if v != anc]:
                            ok = True
                        if p["evidence"] == "nt_editions" and p["basis"] in nt_ok:
                            ok = True
                if not ok:
                    leave.append(x)
            for x in leave:
                del ms[x]
                U.discard(x)
                out[x] = k
            if len(ms) < 2:
                pend.add(k)
        OUT16[prefix] = out
        return pend

    def run(with_model, prefix):
        if V15:
            prof = C.defaultdict(C.Counter)
            for lx, g, _, _ in sp:
                if lx in elig:
                    prof[lx][g] += 1
            for lx, g, b in ntp:
                if b == "derived" or with_model:
                    prof[lx][g] += 1
            groups, member, anchor, under, _w = S35.groups15(lex, elig, prof, lst, ev, size,
                                                             lambda a, b: ubs(a, b, dom), prefix,
                                                             step2b=(lambda G, U, H: step2b16(G, U, H, prefix))
                                                             if V16 else None)
            return groups, member, anchor, prof, under
        prof = C.defaultdict(C.Counter)
        for lx, g, _, _ in sp:
            if lx in elig:
                prof[lx][g] += 1
        for lx, g, b in ntp:
            if b == "derived" or with_model:
                prof[lx][g] += 1
        anchor = {}
        for lx in elig:
            c = prof.get(lx)
            if not c or sum(c.values()) < 5:
                continue
            top = max(c.values())
            g = min((g for g, n in c.items() if n == top), key=int)
            if top / sum(c.values()) >= 0.5:
                anchor[lx] = (g, top / sum(c.values()))
        cands = C.defaultdict(list)
        for lx, (g, _) in anchor.items():
            cands[(g, lex[lx]["class"])].append(lx)
        groups, member, under = {}, {}, set()
        for (g, cl), ls in cands.items():
            tot = sum(prof[x][g] for x in ls)
            mem = [x for x in ls if prof[x][g] >= 0.05 * tot]
            if len(mem) < 2:
                continue
            under |= set(ls) - set(mem)
            head = min(mem, key=lambda x: (-size(x), x))
            key = f"{prefix}:{head}"
            groups[key] = ("g:" + g, {x: ("anchor", prof[x][g], sum(prof[x].values()) - prof[x][g]) for x in mem})
            for x in mem:
                member[x] = key
        join = C.defaultdict(list)
        for ax, L in sorted(lst.items()):
            if ax not in elig or ax in member or lex[ax]["lang"] != "arc":
                continue
            per = C.Counter(h for h, b, _, _ in L if h and b == "derived" and h in elig)
            hits = [h for h, n in per.items() if 2 * n >= int(lex[ax]["count"])]
            if len(hits) == 1:
                h = hits[0]
                join[h].append((ax, per[h], sum(1 for hh, bb, _, _ in L if hh != h and bb != "model")))
        for h, js in join.items():
            if h in member:
                for ax, n, o in js:
                    groups[member[h]][1][ax] = ("aramaic_list", n, o)
                    member[ax] = member[h]
            else:
                mem = {h: ("aramaic_list", sum(n for _, n, _ in js), 0)}
                mem.update({ax: ("aramaic_list", n, o) for ax, n, o in js})
                key = f"{prefix}:" + min(mem, key=lambda x: (-size(x), x))
                groups[key] = ("", mem)
                for x in mem:
                    member[x] = key
        return groups, member, anchor, prof, under

    strict, smember, anchor, prof, under = run(False, "cg")
    if drop_model:
        mgroups, mmember, allm = {}, {}, set()
    else:
        mall, mm, _, _, _ = run(True, "cgm")
        sets = {frozenset(v[1]) for v in strict.values()}
        mgroups = {k: v for k, v in mall.items() if frozenset(v[1]) not in sets}
        mmember = {x: k for k, v in mgroups.items() for x in v[1]}
        allm = set(mm)
    grows = []
    for gs, basis in ((strict, "derived"), (mgroups, "model")):
        for key, (anc, mem) in gs.items():
            for x, (jb, n, o) in mem.items():
                ss = sorted(y for y in mem if y != x and lex[y]["lang"] == lex[x]["lang"] and numpart(lex[y]["strong"]) == numpart(lex[x]["strong"]))
                grows.append({"group": key, "lexeme": x, "head": key.split(":", 1)[1] == x, "anchor": anc, "joined_by": jb,
                              "members": len(mem), "count": n, "against": o, "same_strong": jdump(ss), "basis": basis})
                if V15:      # SPEC 1.5 4.14: ubs_depth to the head, senses_out
                    h = key.split(":", 1)[1]
                    grows[-1]["ubs_depth"] = None if h == x else ubs(x, h, dom)
                    grows[-1]["senses_out"] = S35.senses_out(Wd.build, sp, x, anc)
    grows.sort(key=lambda r: (r["group"], r["lexeme"]))
    # lexemes.tsv
    keys = {p["lexeme"] for p in Wd.pieces} | {row[6] for ed in EDS for row in parts[ed]
                                                 if not (drop_model and row[8] == "model")}
    ncls = C.defaultdict(C.Counter)
    for ed in EDS:
        for row in parts[ed]:
            if row[6].startswith("ntx:") and not (drop_model and row[8] == "model"):
                ncls[row[6]][row[3]] += 1
    lrows = {}
    for k in keys:
        if k.startswith("ntx:"):
            top = max(ncls[k].values())
            r = {"lexeme": k, "lemma": k[8:], "strong": "", "lang": "hbo", "class": min(c for c, n in ncls[k].items() if n == top),
                 "tanakh": "0"}
        else:
            x = lex[k]
            r = {"lexeme": k, "lemma": x["lemma"], "strong": x["strong"], "lang": x["lang"], "class": x["class"], "tanakh": x["count"]}
        r["heb_mod"], r["heb_scg"] = str(pc[("heb_mod", "derived", k)]), str(pc[("heb_scg", "derived", k)])
        r["heb_mod_model"], r["heb_scg_model"] = str(pc[("heb_mod", "model", k)]), str(pc[("heb_scg", "model", k)])
        pl = sum(prof[k].values()) if k in elig else None
        r["places"] = "" if pl is None else str(pl)
        r["anchor"] = "g:" + anchor[k][0] if k in anchor else ""
        r["anchor_share"] = f"{anchor[k][1]:.4f}" if k in anchor else ""
        r["group"] = smember.get(k, "")
        if k in smember:
            s = "member"
        elif k.startswith("ntx:"):
            s = "nt_only"
        elif lex[k]["class"] not in CONTENT or k in funcs:
            s = "function"
        elif k in names:
            s = "name"
        elif pl == 0:
            s = "no_number"
        elif pl < 5:
            s = "few_places"
        elif k not in anchor:
            s = "spread"
        elif V16 and (k in OUT16.get("cg", {}) or k in S35.GATE16.get("cg", set())):
            s = "kept_out"     # SPEC 1.6 D27
        else:
            s = "alone"
        r["state"] = s
        r["group_model"] = mmember[k] if k in mmember else ('""' if k in smember and k not in allm else "")
        lrows[k] = r
    extra = {"elig": elig, "names": names, "funcs": funcs, "moved": moved, "two": two, "stayed": stayed,
             "nosingle": nosingle, "under": under, "lists": lst, "unresolved": unresolved, "pickless": pickless,
             "anchor": anchor}
    if V15:
        extra["under15"] = under
    return pairs, grows, lrows, extra


# ---- D28 SAMPLE.md, written anew ------------------------------------------------------------------------------------

def sample_text(lrows, grows, pairs, under=None):
    G = C.defaultdict(list)
    for r in grows:
        G[r["group"]].append(r)
    strict = sorted(k for k in G if G[k][0]["basis"] == "derived")
    model = sorted(k for k in G if G[k][0]["basis"] == "model")
    tot = lambda k: sum(r["count"] for r in G[k])  # noqa: E731
    secs = [("top_places", sorted((k for k in strict if G[k][0]["anchor"]), key=lambda k: (-tot(k), k))[:20]),
            ("every_tenth", strict[9::10]),
            ("aramaic_list", sorted((k for k in strict if any(r["joined_by"] == "aramaic_list" for r in G[k])),
                                    key=lambda k: (-sum(r["count"] for r in G[k] if r["joined_by"] == "aramaic_list"
                                                        and r["lexeme"].startswith("lex:arc:")), k))[:10]),
            ("model_places", sorted(model, key=lambda k: (-tot(k), k))[:5])]
    if under is not None:      # SPEC 1.5 D28: the aramaic_cognate groups, the groups joined under the floor, the loose ones
        secs = secs[:3] + [
            ("aramaic_cognate", sorted((k for k in strict if any(r["joined_by"] == "aramaic_cognate" for r in G[k])),
                                       key=lambda k: (-sum(r["count"] for r in G[k] if r["joined_by"] == "aramaic_cognate"
                                                           and r["lexeme"].startswith("lex:arc:")), k))[:10]),
            ("under_floor", sorted(k for k in strict if any(r["lexeme"] in under for r in G[k]))),
            ("loose", sorted(k for k in strict if any(r["ubs_depth"] is not None and r["ubs_depth"] < 3 for r in G[k])))
        ] + secs[3:]
    P = C.defaultdict(list)
    for p in pairs:
        P[(p["a"], p["b"])].append(p)
    L = ["# lexicon/SAMPLE.md", "", "D28", ""]
    for code, ks in secs:
        L += [f"## {code} ({len(ks)})", ""]
        for k in ks:
            ms = sorted(G[k], key=lambda r: r["lexeme"])
            L += [f"### {k}", "", f"anchor `{ms[0]['anchor']}` · joined_by " + " ".join(sorted({r['joined_by'] for r in ms}))
                  + f" · basis {ms[0]['basis']}", "",
                  "| head | lemma | lang | tanakh | heb_mod | heb_scg | count | against | same_strong |"
                  + (" joined_by | ubs_depth | senses_out |" if under is not None else ""),
                  "|---|---|---|---|---|---|---|---|---|" + ("---|---|---|" if under is not None else "")]
            for r in ms:
                x = lrows[r["lexeme"]]
                tail = ""
                if under is not None:
                    so = r["senses_out"]
                    tail = (f" {r['joined_by']} | {'-' if r['ubs_depth'] is None else r['ubs_depth']} | "
                            f"{'-' if so is None else (' '.join(json.loads(so)) or '[]')} |")
                L.append(f"| {'*' if r['head'] else ''} | {x['lemma']} | {x['lang']} | {x['tanakh']} | {x['heb_mod']} | {x['heb_scg']} "
                         f"| {r['count']} | {r['against']} | {len(json.loads(r['same_strong']))} |" + tail)
            rows = []
            names = [r["lexeme"] for r in ms]
            for i, a in enumerate(names):
                for b in names[i + 1:]:
                    a2, b2 = min(a, b), max(a, b)
                    for p in P.get((a2, b2), []):
                        rows.append(f"| {lrows[a2]['lemma']} | {lrows[b2]['lemma']} | {p['evidence']} | {p['basis']} | {p['count']} "
                                    f"| {p['a_other']} | {p['b_other']} |")
            L += ["", "| a | b | evidence | basis | count | a_other | b_other |", "|---|---|---|---|---|---|---|"]
            L += sorted(rows) or ["| | | | | | | |"]
            L.append("")
    return "\n".join(L).rstrip("\n") + "\n"


# ---- the checks ---------------------------------------------------------------------------------------------------

def _diff_rows(want, got, key):
    w = {key(r): r for r in want}
    g = {key(r): r for r in got}
    missing = [k for k in w if k not in g]
    extra = [k for k in g if k not in w]
    differ = [k for k in w if k in g and w[k] != g[k]]
    return missing, extra, differ


def _categories(path):
    """{block name: set of codes} of a categories.toml (only the code = "..." entries), and the raw text."""
    blocks, cur = C.defaultdict(set), None
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    for ln in text.splitlines():
        m = re.match(r"^\[(.+)\]$", ln.strip())
        if m:
            cur = m.group(1)
            continue
        m = re.search(r'code = "([^"]*)"', ln)
        if m and cur:
            blocks[cur].add(m.group(1))
    return blocks, text


def stage32(R, build, compare=None, V=None):
    root = os.path.dirname(os.path.normpath(build))
    e1 = os.path.join(root, "e1")
    Lx = os.path.join(build, "lexicon")
    R.section("1.4 sources")
    sums = {}
    with open(ANA_SUMS, encoding="utf-8") as fh:
        for ln in fh:
            if ln.strip():
                h, f = ln.split(None, 1)
                sums[f.strip()] = h
    for ed in EDS:
        R.check(f"tan hebrew-nt-analysis v0.2 {ed}/words.parquet: sha256 as its SHA256SUMS", sha_of(ANA[ed]) == sums.get(f"{ed}/words.parquet"))
    R.check("tan greek_numbers.tsv: sha256 as pinned", sha_of(GNUM) == GNUM_PIN)
    R.check("tan aramaic-hebrew-equivalents v0.1.1 words.parquet: sha256 as pinned", sha_of(EQUIV) == EQUIV_PIN)
    Wd = World(build)
    hsrc = json.load(open(os.path.join(build, "hbo", "sources.json"), encoding="utf-8"))["sources"]["macula-hebrew"]["files"]
    bad = sum(1 for p in glob.glob(os.path.join(LOWFAT, "*-lowfat.xml"))
              if hsrc.get(os.path.relpath(p, ROOT), {}).get("sha256") != sha_of(p))
    R.check("tan the lowfat files read for greekstrong are those hbo/sources.json pins (sha256)", bad == 0 and Wd.lowfat_files == len(hsrc),
            f"{Wd.lowfat_files} files, {bad} differ")

    # ---- New Testament keys (D23)
    R.section("New Testament keys (D23)")
    want, acct, multi = Wd.parts()
    if V15:      # SPEC 1.5 D23: H0, H1, H2 (heb_mod), K6
        import validate_examples_s35 as S35
        want = S35.keys15(R, build, want)
    R.check("tan D23: no step found two or more keys", not multi, len(multi))
    for ed in EDS:
        got = [tuple(r[c] for c in ("s", "p", "text", "class", "lemma", "strong", "lexeme", "key_rule", "basis"))
               for r in rows_of(os.path.join(build, "other", ed, "parts.parquet"))]
        R.check(f"tan {ed} parts.parquet: sorted by (s, p), each once", got == sorted(got) and len({g[:2] for g in got}) == len(got), len(got))
        m, x, d = _diff_rows(want[ed], got, lambda r: r[:2])
        R.check(f"tan {ed} parts.parquet: one row per part of every joined word, no other row; key_rule, lexeme, basis and "
                f"the given columns recomputed by D23", not (m or x or d), f"{len(got):,} rows; missing {len(m)}, extra {len(x)}, differ {len(d)}: {(m + x + d)[:3]}")
        wb = {w["s"]: w["analysis_basis"] for w in Wd.other[ed]}
        R.check(f"tan {ed} parts.parquet: every basis equals its word's analysis_basis" + (
            " (1.5: or model on H0 and K6)" if V15 else ""),
            all(g[8] == wb[g[0]] or (V15 and g[7] in ("H0", "K6") and g[8] == "model") for g in got), len(got))
        known = set(Wd.lex)
        R.check(f"tan {ed} parts.parquet: every lex: key is a key of hbo/lexemes.tsv or arc/lexemes.tsv",
                all(g[6] in known for g in got if g[6].startswith("lex:")), sum(1 for g in got if g[6].startswith("lex:")))
        R.check(f"tan {ed} parts.parquet: every other key is ntx:hbo:<lemma NFC> on a K0 or K5 row",
                all(g[6] == "ntx:hbo:" + norm(g[4]) and g[7] in ("K0", "K5") for g in got if not g[6].startswith("lex:")),
                sum(1 for g in got if not g[6].startswith("lex:")))
        # spelling
        by = C.defaultdict(list)
        for g in got:
            by[g[0]].append(g)
        bad, n, src_bad = [], 0, []
        for w in Wd.other[ed]:
            if w["analysis"] is None:
                continue
            n += 1
            ana = sorted(Wd.ana[ed][(w["book"], w["chapter"], w["verse"], w["w"])], key=lambda r: r["part"])
            spelt = "".join(g[2] for g in sorted(by[w["s"]], key=lambda g: g[1]))
            full = "".join(r["text"] or "" for r in ana)
            if spelt != full:
                bad.append(w["s"])
            elif spelt != (ana[0]["word"] or ""):
                src_bad.append(f"s={w['s']} {w['book']} {w['chapter']}:{w['verse']} w={w['w']}: parts {spelt} | word {ana[0]['word']}")
        R.check(f"tan {ed} parts.parquet: the parts of each word, with the letterless articles, spell the analysis's word, "
                f"save the words whose own analysis parts do not (listed)", not bad, f"{n:,} words, {len(bad)} differ {bad[:5]}; "
                f"source exceptions {len(src_bad)}")
        R.info(f"tan {ed} source exceptions: words whose analysis parts (hebrew-nt-analysis v0.2) do not spell the word",
               f"{len(src_bad)}: {src_bad}")
        a = acct[ed]
        R.check(f"tan {ed}: every New Testament word keyed or accounted for (words of other/{ed} = joined + English tokens; "
                f"analysis words = those + verse-number tokens)",
                a["words joined"] + a["English tokens (no analysis)"] == len(Wd.other[ed])
                and a["analysis words neither joined nor accounted for"] == 0,
                f"other/{ed} {len(Wd.other[ed]):,} = joined {a['words joined']:,} + English {a['English tokens (no analysis)']}; "
                f"analysis {len(Wd.ana[ed]):,}; verse numbers {a['verse-number tokens']:,}; unaccounted {a['analysis words neither joined nor accounted for']}")
        R.info(f"tan {ed} parts by rule and basis", ", ".join(f"{k} {v:,}" for k, v in sorted(a.items()) if re.match(r"K\d ", k)))
        R.info(f"tan {ed} ntx (K0) parts by class", ", ".join(f"{k[13:]} {v:,}" for k, v in sorted(a.items()) if k.startswith("ntx K0 class")))
        R.info(f"tan {ed} distinct ntx keys", len({g[6] for g in got if g[6].startswith("ntx:")}))
        R.info(f"tan {ed} words with every part on a Tanakh key, by basis",
               ", ".join(f"{b} {a[f'words with every part on a Tanakh key, {b}']:,} of {a[f'words {b}']:,}" for b in ("derived", "model")))
        R.info(f"tan {ed} left out", f"letterless article parts {a['letterless parts']:,}; verse-number tokens {a['verse-number tokens']:,}; "
               f"English tokens {a['English tokens (no analysis)']}")

    # ---- lexicon, pairs, groups
    pairs, grows, lrows, ex = recompute(Wd, want)
    R.section("lexicon (D24, D24n, D25, D27)")
    R.info("tan D24 eligible lexemes", f"{len(ex['elig']):,} (names {len(ex['names']):,}; function words by type {len(ex['funcs'])})")
    R.info("tan D24n Septuagint pieces moved to the New Testament number", f"{ex['moved']:,}; under a listed number without nt_strong {ex['stayed']}")
    R.info("tan D24 pieces whose greekstrong holds two numbers (no place)", f"{len(ex['two'])}: {ex['two']}")
    R.info("tan D24 strict New Testament links whose Greek lexeme has no single number", ex["nosingle"])
    got = read_tsv(os.path.join(Lx, "lexemes.tsv"))
    with open(os.path.join(Lx, "lexemes.tsv"), encoding="utf-8") as fh:
        head = fh.readline().rstrip("\n").split("\t")
    R.check("tan lexicon/lexemes.tsv: the columns of SPEC 4.14 in order", head == ["lexeme", "lemma", "strong", "lang", "class", "tanakh",
            "heb_mod", "heb_scg", "heb_mod_model", "heb_scg_model", "places", "anchor", "anchor_share", "group", "state", "group_model"], head)
    keys = [r["lexeme"] for r in got]
    R.check("tan lexicon/lexemes.tsv: sorted by key, each once", keys == sorted(keys) and len(set(keys)) == len(keys), len(keys))
    R.check("tan lexicon/lexemes.tsv: one row per key of hbo and arc pieces and of the edition parts, and no other",
            set(keys) == set(lrows), f"{len(keys):,} rows, recount {len(lrows):,}")
    for col in ("tanakh", "heb_mod", "heb_scg", "heb_mod_model", "heb_scg_model", "lemma", "strong", "lang", "class"):
        d = [r["lexeme"] for r in got if r["lexeme"] in lrows and r[col] != lrows[r["lexeme"]][col]]
        R.check(f"tan lexicon/lexemes.tsv {col}: recomputed" + (" (equals the language's lexemes.tsv count)" if col == "tanakh" else ""),
                not d, f"{len(d)} differ {d[:3]}")
    for col in ("places", "anchor", "anchor_share", "group", "state", "group_model"):
        d = [r["lexeme"] for r in got if r["lexeme"] in lrows and r[col] != lrows[r["lexeme"]][col]]
        R.check(f"tan lexicon/lexemes.tsv {col}: recomputed by D24, D25, D26, D25m, D27", not d, f"{len(d)} differ {d[:3]}")
    R.check("tan lexicon/lexemes.tsv: every row has exactly one state of D27", all(r["state"] in STATE_CODES for r in got), len(got))
    big = [r for r in got if not r["lexeme"].startswith("ntx:") and int(r["tanakh"]) >= 5]
    R.check("tan lexicon: every Tanakh lexeme with 5 or more pieces is a member or has one of the other states",
            all(r["state"] in STATE_CODES for r in big), len(big))
    acc = C.Counter((r["lang"], r["state"]) for r in got)
    accb = C.Counter((r["lang"], r["state"]) for r in big)
    for lang in ("hbo", "arc"):
        R.info(f"tan lexicon account {lang} (every key)", ", ".join(f"{s} {acc[(lang, s)]:,}" for s in STATE_CODES))
        R.info(f"tan lexicon account {lang} (Tanakh lexemes with 5 or more pieces)", ", ".join(f"{s} {accb[(lang, s)]:,}" for s in STATE_CODES))
    R.info("tan D27: alone lexemes that are candidates under 0.05 of a group's anchor", len(ex["under"]))

    R.section("pairs (D24)")
    gp = rows_of(os.path.join(Lx, "pairs.parquet"))
    order = [(r["evidence"], r["basis"], r["a"], r["b"]) for r in gp]
    R.check("tan pairs.parquet: sorted by (evidence, basis, a, b), each once", order == sorted(order) and len(set(order)) == len(order), len(order))
    m, x, d = _diff_rows(pairs, gp, lambda r: (r["evidence"], r["basis"], r["a"], r["b"]))
    R.check("tan pairs.parquet: every row recomputed by D24 (count, a_other, b_other, via, ubs_depth, places), no row missing",
            not (m or x or d), f"{len(gp):,} rows; missing {len(m)}, extra {len(x)}, differ {len(d)}: {(m + x + d)[:3]}")
    R.check("tan pairs.parquet: every a, b eligible; a before b", all(r["a"] in ex["elig"] and r["b"] in ex["elig"] and r["a"] < r["b"] for r in gp), len(gp))
    okb = {"sept_number": {"given"}, "nt_editions": {"linked", "model"}, "aramaic_list": {"derived", "model"}}
    R.check("tan pairs.parquet: basis by its rule (sept_number given; nt_editions linked or model; aramaic_list derived or model)",
            all(r["basis"] in okb.get(r["evidence"], ()) for r in gp), len(gp))
    pc = C.Counter((r["evidence"], r["basis"]) for r in gp)
    R.info("tan pairs rows per evidence and basis", ", ".join(f"{e} {b} {n:,}" for (e, b), n in sorted(pc.items())))
    sept_pairs = {(r["a"], r["b"]) for r in gp if r["evidence"] == "sept_number"}
    for b in ("linked", "model"):
        nt3 = [r for r in gp if r["evidence"] == "nt_editions" and r["basis"] == b and r["count"] >= 3]
        R.info(f"tan nt_editions pairs ({b}) on 3 or more Greek pieces", f"{len(nt3):,}, of which also sharing a Septuagint number "
               f"{sum(1 for r in nt3 if (r['a'], r['b']) in sept_pairs):,}")

    R.section("groups (D25, D26, D25m)")
    gg = rows_of(os.path.join(Lx, "groups.parquet"))
    order = [(r["group"], r["lexeme"]) for r in gg]
    R.check("tan groups.parquet: sorted by (group, lexeme), each once", order == sorted(order) and len(set(order)) == len(order), len(gg))
    m, x, d = _diff_rows(grows, gg, lambda r: (r["group"], r["lexeme"]))
    R.check("tan groups.parquet: every group recomputed by D25, D26 and D25m (members, head, anchor, joined_by, count, against, "
            "same_strong, basis)", not (m or x or d), f"{len(gg):,} rows; missing {len(m)}, extra {len(x)}, differ {len(d)}: {(m + x + d)[:3]}")
    R.check("tan groups.parquet: every member eligible", all(r["lexeme"] in ex["elig"] for r in gg), len(gg))
    strict = [r for r in gg if r["basis"] == "derived"]
    sm = C.Counter(r["lexeme"] for r in strict)
    R.check("tan groups.parquet: no lexeme in two strict groups", max(sm.values() or [1]) == 1, len(sm))
    G = C.defaultdict(list)
    for r in gg:
        G[r["group"]].append(r)
    R.check("tan groups.parquet: one head per group, and the key names it", all(sum(r["head"] for r in v) == 1 and
            k.split(":", 1)[1] == next(r["lexeme"] for r in v if r["head"]) for k, v in G.items()), len(G))
    R.check("tan groups.parquet: members equals the group's rows; two or more", all(all(r["members"] == len(v) for r in v) and len(v) >= 2
            for v in G.values()), len(G))
    R.check("tan groups.parquet: key cg: on basis derived, cgm: on basis model", all(r["group"].startswith("cg:") == (r["basis"] == "derived")
            and r["group"].startswith(("cg:", "cgm:")) for r in gg), len(gg))
    lg = {r["lexeme"]: r["group"] for r in got}
    sg = {r["lexeme"]: r["group"] for r in strict}
    R.check("tan lexemes.group equals the strict group of each member and is empty on every other row",
            all(lg[k] == sg.get(k, "") for k in lg), len(lg))
    sk = [k for k in G if G[k][0]["basis"] == "derived"]
    mk = [k for k in G if G[k][0]["basis"] == "model"]
    R.info("tan strict groups", f"{len(sk)} ({sum(1 for k in sk if G[k][0]['anchor'])} by anchor, {sum(1 for k in sk if not G[k][0]['anchor'])} "
           f"formed by D26), members {sum(len(G[k]) for k in sk):,}; by size "
           + ", ".join(f"{s}: {n}" for s, n in sorted(C.Counter(len(G[k]) for k in sk).items())))
    R.info("tan strict groups by anchor (D25)", f"{sum(1 for k in sk if G[k][0]['anchor'])} groups, "
           f"{sum(sum(1 for r in G[k] if r['joined_by'] == 'anchor') for k in sk if G[k][0]['anchor'])} members joined by the anchor, by size "
           + ", ".join(f"{s}: {n}" for s, n in sorted(C.Counter(sum(1 for r in G[k] if r['joined_by'] == 'anchor') for k in sk if G[k][0]['anchor']).items())))
    R.info("tan strict groups with an Aramaic member", f"{sum(1 for k in sk if any(r['lexeme'].startswith('lex:arc:') for r in G[k]))}; "
           f"Aramaic members joined by the anchor {sum(1 for r in strict if r['lexeme'].startswith('lex:arc:') and r['joined_by'] == 'anchor')}, "
           f"by the list (D26) {sum(1 for r in strict if r['joined_by'] == 'aramaic_list' and r['lexeme'].startswith('lex:arc:'))}")
    R.info("tan strict groups holding a same_strong pair", sum(1 for k in sk if any(json.loads(r["same_strong"]) for r in G[k])))
    R.info("tan model groups (D25m) whose members differ from every strict group", f"{len(mk)}, members {sum(len(G[k]) for k in mk)}")
    lex = Wd.lex
    for size in sorted({len(G[k]) for k in sk}):
        ks = [k for k in sk if len(G[k]) == size]
        dom = lambda x, dep: {d.split(":")[0][:3 * dep] for d in lex[x]["domains"].split()}  # noqa: E731
        alld = [k for k in ks if all(lex[r["lexeme"]]["domains"] for r in G[k])]
        s1 = sum(1 for k in alld if set.intersection(*[dom(r["lexeme"], 1) for r in G[k]]))
        s3 = sum(1 for k in alld if set.intersection(*[dom(r["lexeme"], 3) for r in G[k]]))
        R.info(f"tan UBS check (not a gate), strict groups of {size}", f"{len(ks)}; every member with domains {len(alld)}: sharing a domain "
               f"at step 1 {s1}, at step 3 {s3}; with a member without domains {len(ks) - len(alld)}")

    R.section("Aramaic equivalents (D24a)")
    F = [r for r in rows_of(os.path.join(build, "arc", "facts.parquet")) if r["relation"] == "equivalent_of"]
    per = C.Counter(p["lexeme"] for p in Wd.pieces if p["lang"] == "arc")
    w = C.Counter()
    for ax, L in ex["lists"].items():
        for hx, b, _, _ in L:
            if hx:
                w[(ax, hx, b)] += 1
    gotf = {(r["subject"], r["object"], r["kind"]): r for r in F}
    bad = [k for k, n in w.items() if k not in gotf or gotf[k]["count"] != n or abs(gotf[k]["share"] - n / per[k[0]]) > 1e-12
           or gotf[k]["method"] != "words.parquet:hebrew_strong" or gotf[k]["source"] != "aramaic-hebrew-equivalents"]
    R.check("arc facts: every equivalent_of row recomputed by D24a (per Aramaic lexeme, Hebrew lexeme, kind; kind derived or model "
            "by the list row's evidence)", not bad and len(gotf) == len(w) == len(F), f"{len(F)} rows, recount {len(w)}, {len(bad)} differ {bad[:3]}")
    rows_per = C.Counter()
    arcp = {p["pid"]: p["lexeme"] for p in Wd.pieces if p["lang"] == "arc"}
    for r in Wd.equiv:
        if "o" + r["key"] in arcp:
            rows_per[arcp["o" + r["key"]]] += 1
    sums = C.Counter()
    for (ax, hx, b), n in w.items():
        sums[ax] += n
    bad = [ax for ax in rows_per if sums[ax] + ex["unresolved"][ax] + ex["pickless"][ax] != rows_per[ax]]
    R.check("arc facts: the pieces of all equivalent_of rows of an Aramaic lexeme plus its unresolved and pickless rows equal its list rows",
            not bad, f"{len(rows_per)} Aramaic lexemes, {len(bad)} differ")
    kc = C.Counter(r["kind"] for r in F)
    R.info("arc equivalent_of rows by kind", dict(sorted(kc.items())))
    R.info("arc equivalent_of pieces by kind", {k: sum(r["count"] for r in F if r["kind"] == k) for k in sorted(kc)})

    R.section("sample (D28)")
    with open(os.path.join(Lx, "SAMPLE.md"), encoding="utf-8") as fh:
        sample = fh.read()
    lr = {r["lexeme"]: r for r in got}
    mine = sample_text(lr, gg, gp, ex.get("under15")) if V15 else sample_text(lr, gg, gp)
    sample_full = sample
    if V16:     # SPEC 1.6 D28: the sections of 1.5 here; step2b_out and kept_out are checked by stage 38
        sample = sample.split("\n## step2b_out", 1)[0]
    R.check("tan lexicon/SAMPLE.md equals the one the validator writes by D28" + (" (the sections of 1.5)" if V16 else ""),
            sample == mine,
            f"{len(sample.splitlines())} lines" + ("" if sample == mine else f"; first difference: {next(iter(difflib.unified_diff(sample.splitlines(), mine.splitlines(), lineterm='', n=0)), '')}"))

    R.section("no English, model attribution (lexicon, parts)")
    cats, ctext = _categories(os.path.join(Lx, "categories.toml"))
    allow = set().union(*cats.values()) if cats else set()
    colnames = {"head", "lemma", "lang", "tanakh", "heb_mod", "heb_scg", "count", "against", "same_strong", "a", "b", "evidence",
                "basis", "a_other", "b_other", "anchor", "joined_by", "lexicon", "SAMPLE", "md", "D28", "top_places", "every_tenth",
                "aramaic_list", "model_places"} | ({"aramaic_cognate", "under_floor", "loose", "ubs_depth", "senses_out"} if V15 else set()) \
        | ({"step2b_out", "kept_out", "member", "head_lemma", "group", "share", "weak_by", "lacks", "state", "lexeme",
            "class", "dissolved_head", "sept_number", "nt_editions"} if V16 else set())
    s2 = re.sub(r"(?:cgm?|lex|ntx):\S+|g:\d+|`[^`]*`", " ", sample_full)
    latin = sorted({wd for wd in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", s2) if wd not in allow and wd not in colnames})
    R.check("tan lexicon/SAMPLE.md: no English (every Latin-script word is a column name, a declared code or a key)", not latin, latin[:10])
    coded = [("lexemes.state", [r["state"] for r in got]), ("lexemes.lang", [r["lang"] for r in got]),
             ("lexemes.class", [r["class"] for r in got]), ("pairs.evidence", [r["evidence"] for r in gp]),
             ("pairs.basis", [r["basis"] for r in gp]), ("groups.joined_by", [r["joined_by"] for r in gg]),
             ("groups.basis", [r["basis"] for r in gg])]
    pt = [r for ed in EDS for r in rows_of(os.path.join(build, "other", ed, "parts.parquet"))]
    coded += [("parts.key_rule", [r["key_rule"] for r in pt]), ("parts.basis", [r["basis"] for r in pt]), ("parts.class", [r["class"] for r in pt])]
    for blk, vals in coded:
        off = sorted({v for v in vals if v not in cats.get(blk, set())})
        R.check(f"tan no English (a): every value of {blk} is a code declared in lexicon/categories.toml", not off, f"{len(vals):,} values; off {off[:5]}")
    hebcols = [("lexemes.lemma", [r["lemma"] for r in got]), ("parts.text", [r["text"] for r in pt]), ("parts.lemma", [r["lemma"] for r in pt])]
    for nm, vals in hebcols:
        off = sorted({v for v in vals if not HEB.match(v or "")})
        R.check(f"tan no English (b): {nm} in Hebrew script or empty", not off, f"{len(vals):,} values; off {off[:5]}")
    keyok = re.compile(r"^(lex:(hbo|arc):\S.*|ntx:hbo:.*)$")
    R.check("tan no English: every key of lexemes, pairs, groups, parts is a lex: or ntx: key (Hebrew inside)",
            all(keyok.match(k) and HEB.match(k.split(":")[2]) for k in [r["lexeme"] for r in got]), len(got))
    vias = [v for r in gp for v in json.loads(r["via"])]
    R.check("tan pairs.via: only g:<number> or lex:grc: keys (evidence)", all(re.match(r"^(g:\d+|lex:grc:.+)$", v) for v in vias), len(vias))
    if V is not None and hasattr(V, "_s10_gloss_vocab"):
        vocab, _ = V._s10_gloss_vocab()
        vals = {v for r in got for k, v in r.items() if k not in ("tanakh", "heb_mod", "heb_scg", "heb_mod_model", "heb_scg_model", "places", "anchor_share")}
        vals |= {r[k] for r in gp for k in ("a", "b", "evidence", "basis", "places")} | {r[k] for r in gg for k in ("group", "lexeme", "anchor", "joined_by", "basis")}
        vals |= {r[k] for r in pt for k in ("text", "class", "lemma", "lexeme", "key_rule", "basis")}
        hits = sorted(v for v in vals if v and v.lower() in vocab and v not in allow)
        R.check("tan no English (c): no string value of the lexicon tables or parts equals a word of MACULA's gloss vocabulary "
                "unless a declared code", not hits, f"{len(vals):,} distinct values; {hits[:10]}")
    sj = json.load(open(os.path.join(Lx, "sources.json"), encoding="utf-8"))
    need = ("models", "version", "run", "human_check")
    R.check("tan model attribution: lexicon/sources.json names the tagger (M6) and GLAUx (M7) with version, models, run, no human check",
            all(all(sj["model"].get(k, {}).get(f) for f in need) for k in ("hebrew-nt-analysis", "glaux"))
            and all(sj["model"][k]["human_check"] == "no human check" for k in ("hebrew-nt-analysis", "glaux")), sorted(sj["model"]))
    blocks = re.split(r"\n(?=\[)", ctext)
    mb = {re.match(r"\[([^\]]+)\]", b).group(1): b for b in blocks if b.startswith("[")}
    need_m6 = ("lexemes.heb_mod_model", "lexemes.group_model", "pairs.nt_editions.model", "groups.model", "parts.basis")
    R.check("tan model attribution: lexicon/categories.toml names the tagger's dataset, version and model on every M column and model rows",
            all(k in mb and "hebrew-nt-analysis" in mb[k] and "models = [" in mb[k] and "version = " in mb[k] for k in need_m6), need_m6)
    R.check("tan model attribution: lexicon/categories.toml names GLAUx on the aramaic_list model rows",
            "pairs.aramaic_list.model" in mb and "GLAUx" in mb["pairs.aramaic_list.model"] and "models = [" in mb["pairs.aramaic_list.model"])
    ac, atext = _categories(os.path.join(build, "arc", "categories.toml"))
    R.check("arc model attribution: categories.toml [facts.equivalent_of] declares the kinds with their counts and names GLAUx (M7)",
            ac.get("facts.equivalent_of") == set(kc) and "GLAUx" in atext.split("[facts.equivalent_of]")[-1]
            and all(f"code = \"{k}\", value = \"{k}\", count = {n} " in atext.split("[facts.equivalent_of]")[-1] for k, n in kc.items()), dict(kc))
    asj = json.load(open(os.path.join(build, "arc", "sources.json"), encoding="utf-8"))
    R.check("arc model attribution: sources.json names facts equivalent_of with kind model under GLAUx; the list's basis is D24a's",
            any("equivalent_of" in c for c in asj["model"]["glaux"]["columns"])
            and "greek_verse" in asj["sources"]["aramaic-hebrew-equivalents"]["basis"], asj["sources"]["aramaic-hebrew-equivalents"]["basis"])

    R.section("strict view (lexicon, parts)")
    sp_, sg_, sl_, _ = recompute(Wd, {ed: [r for r in want[ed] if r[8] != "model"] for ed in EDS}, drop_model=True)
    m, x, d = _diff_rows(sp_, [r for r in gp if r["basis"] != "model"], lambda r: (r["evidence"], r["basis"], r["a"], r["b"]))
    R.check("tan strict view: pairs.parquet without its model rows equals D24 recomputed with every model part and model list row left out",
            not (m or x or d), f"missing {len(m)}, extra {len(x)}, differ {len(d)}")
    m, x, d = _diff_rows(sg_, [r for r in gg if r["basis"] != "model"], lambda r: (r["group"], r["lexeme"]))
    R.check("tan strict view: groups.parquet without its model rows equals D25, D26 recomputed from strict input only",
            not (m or x or d), f"missing {len(m)}, extra {len(x)}, differ {len(d)}")
    cols = ("tanakh", "heb_mod", "heb_scg", "places", "anchor", "anchor_share", "group", "state")
    d = [r["lexeme"] for r in got if r["lexeme"] in sl_ and any(r[c] != sl_[r["lexeme"]][c] for c in cols)]
    only_model = [r["lexeme"] for r in got if r["lexeme"] not in sl_]
    R.check("tan strict view: lexemes.tsv strict columns equal their recount from strict input only (rows of keys found only in "
            "model parts stand with their strict columns empty or 0)",
            not d and all(r["heb_mod"] == "0" and r["heb_scg"] == "0" and r["state"] == "nt_only" for r in got if r["lexeme"] in set(only_model)),
            f"{len(d)} differ; {len(only_model):,} keys only in model parts")
    R.check("tan strict view: no value of basis model in the strict rows of parts, pairs, groups",
            all(r["basis"] != "model" for r in pt if r["basis"] == "derived") and not any(r["basis"] == "model" for r in gp if r["evidence"] == "sept_number"),
            f"strict parts {sum(1 for r in pt if r['basis'] == 'derived'):,}, strict pairs {sum(1 for r in gp if r['basis'] != 'model'):,}, "
            f"strict group rows {len(strict):,}")

    # ---- unchanged against e1 (section 13)
    R.section("unchanged against e1 (SPEC 1.4 section 13)")
    if V15:
        R.info("tan unchanged against e1", "a g build is compared with f1 by stage 35 (SPEC 1.5 section 13)")
    elif not os.path.isdir(e1):
        R.skip("tan unchanged against e1", "e1 not present")
    else:
        unchanged_e1(R, build, e1)

    # ---- rebuild
    if compare:
        R.section(f"rebuild ({compare}): lexicon/ and the reader's sample")
        b2 = os.path.join(root, compare)
        fa = sorted(os.listdir(Lx))
        fb = sorted(os.listdir(os.path.join(b2, "lexicon"))) if os.path.isdir(os.path.join(b2, "lexicon")) else []
        diff = [f for f in set(fa) | set(fb) if f != "VALIDATION.md" and (f not in fa or f not in fb or
                sha_of(os.path.join(Lx, f)) != sha_of(os.path.join(b2, "lexicon", f)))]
        R.check(f"tan rebuild: every file of {os.path.basename(build)}/lexicon has the same sha256 in {compare} (VALIDATION.md aside)",
                not diff, f"{len([f for f in fa if f != 'VALIDATION.md'])} files, differ {sorted(diff)}")
        sa = os.path.join(GLOSSED_F1 if os.path.basename(build) == "f1" else GLOSSED_F1.replace("glossed-f1", "glossed-g1") if os.path.basename(build) == "g1" else GLOSSED_F1.replace("glossed-f1", "glossed-h1") if os.path.basename(build) in ("h1", "i1") else os.path.join(build, "cache", "reader-sample"), "equivalents-sample.md")
        sb = os.path.join(b2, "cache", "reader-sample", "equivalents-sample.md")
        R.check(f"tan rebuild: the reader's sample is the same in {compare}", os.path.exists(sa) and os.path.exists(sb) and sha_of(sa) == sha_of(sb))


def _pq_rows(path):
    t = pq.read_table(path)
    return t.schema, t.to_pylist()


def unchanged_e1(R, build, e1):
    for sub in ("hbo", "arc", "grc", "other"):
        a_dir, b_dir = os.path.join(e1, sub), os.path.join(build, sub)
        fa = {os.path.relpath(p, a_dir) for p in glob.glob(os.path.join(a_dir, "**", "*"), recursive=True) if os.path.isfile(p)}
        fb = {os.path.relpath(p, b_dir) for p in glob.glob(os.path.join(b_dir, "**", "*"), recursive=True) if os.path.isfile(p)}
        new = sorted(fb - fa)
        gone = sorted(fa - fb - {"VALIDATION.md"})
        allowed_new = {f"{ed}/parts.parquet" for ed in EDS} if sub == "other" else set()
        R.check(f"{'tan' if sub == 'other' else sub} unchanged: no file of e1/{sub} missing; new files only those of 1.4",
                not gone and set(new) <= allowed_new, f"new {new}, missing {gone}")
        same, differ = 0, []
        for f in sorted(fa & fb):
            if f == "VALIDATION.md":
                continue
            if sha_of(os.path.join(a_dir, f)) == sha_of(os.path.join(b_dir, f)):
                same += 1
            else:
                differ.append(f)
        allowed = {"sources.json", "COLUMNS.md"} | ({"facts.parquet", "categories.toml", "READ-FIRST.md"} if sub == "arc" else set())
        for f in ("COLUMNS.md", "READ-FIRST.md"):
            if f in differ:
                ta = open(os.path.join(a_dir, f), encoding="utf-8").read().splitlines()
                tb = open(os.path.join(b_dir, f), encoding="utf-8").read().splitlines()
                dl = [ln for ln in difflib.unified_diff(ta, tb, lineterm="", n=0) if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
                R.info(f"{sub} changed: {f} against e1 (the SPEC text it quotes, and the counts D24a moves)",
                       f"{sum(ln.startswith('-') for ln in dl)} lines out, {sum(ln.startswith('+') for ln in dl)} in: " + " || ".join(dl))
        R.check(f"{'tan' if sub == 'other' else sub} unchanged: every table and file of e1/{sub} has the same bytes in "
                f"{os.path.basename(build)}, but those section 13 lets change", set(differ) <= allowed,
                f"{same} same, differ {differ}")
        if sub == "arc" and "facts.parquet" in differ:
            sa, ra = _pq_rows(os.path.join(a_dir, "facts.parquet"))
            sb, rb = _pq_rows(os.path.join(b_dir, "facts.parquet"))
            ka = [r for r in ra if r["relation"] != "equivalent_of"]
            kb = [r for r in rb if r["relation"] != "equivalent_of"]
            R.check("arc unchanged: facts rows whose relation is not equivalent_of equal e1's, row by row; same schema",
                    ka == kb and sa == sb, f"{len(ka):,} rows")
            ea = [r for r in ra if r["relation"] == "equivalent_of"]
            eb = [r for r in rb if r["relation"] == "equivalent_of"]
            pa_, pb_ = C.Counter(), C.Counter()
            for r in ea:
                pa_[r["subject"]] += r["count"]
            for r in eb:
                pb_[r["subject"]] += r["count"]
            R.check("arc changed (D24a): equivalent_of rows before and after counted; the pieces per Aramaic lexeme equal in sum",
                    pa_ == pb_ and all(r["kind"] == "linked" for r in ea),
                    f"e1 {len(ea)} rows (kind {dict(C.Counter(r['kind'] for r in ea))}), {sum(pa_.values()):,} pieces; "
                    f"{os.path.basename(build)} {len(eb)} rows (kind {dict(sorted(C.Counter(r['kind'] for r in eb).items()))}), {sum(pb_.values()):,} pieces")
        if sub == "arc" and "categories.toml" in differ:
            ta = open(os.path.join(a_dir, "categories.toml"), encoding="utf-8").read().splitlines()
            tb = open(os.path.join(b_dir, "categories.toml"), encoding="utf-8").read().splitlines()
            dl = [ln for ln in difflib.unified_diff(ta, tb, lineterm="", n=0) if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
            removed = [ln for ln in dl if ln.startswith("-")]
            okrm = all(re.search(r'code = "(linked|derived|model|given|aramaic-hebrew-equivalents|equivalent_of|words\.parquet:hebrew_strong)"', ln) for ln in removed)
            R.check("arc changed: categories.toml differs from e1 only in the facts counts of kind, relation, source and the new "
                    "[facts.equivalent_of] block (and the method count)", okrm, f"{len(removed)} lines out, {len(dl) - len(removed)} in: {dl}")
        if "sources.json" in differ:
            ja = json.load(open(os.path.join(a_dir, "sources.json"), encoding="utf-8"))
            jb = json.load(open(os.path.join(b_dir, "sources.json"), encoding="utf-8"))
            paths = []

            def walk(x, y, p):
                if isinstance(x, dict) and isinstance(y, dict):
                    for k in sorted(set(x) | set(y)):
                        walk(x.get(k), y.get(k), p + [k])
                elif x != y:
                    paths.append("/".join(map(str, p)))
            walk(ja, jb, [])
            okp = all(p.startswith(("builder/", "specification/")) or p in ("sources/aramaic-hebrew-equivalents/basis", "model/glaux/columns")
                      for p in paths)
            R.check(f"{'tan' if sub == 'other' else sub} changed: sources.json differs from e1 only in the builder, the specification"
                    + (", the list's basis and GLAUx's columns (D24a)" if sub == "arc" else ""), okp,
                    f"{len(paths)} paths: " + ", ".join(sorted({'/'.join(p.split('/')[:2]) for p in paths})))


def write_md(build, lines):
    L = ["# VALIDATION: `lexicon/` and `other/heb_*/parts.parquet`", "",
         f"Written by `validate_examples.py --build {os.path.basename(os.path.normpath(build))} --upto 32 --write-md` (SPEC 1.4, "
         "section 10, the conditions new in 1.4). Every check of stage 32, with the count that met it.", ""]
    n = C.Counter(ln[:4] for _, ln in lines)
    L += [f"Result: {n['PASS']} PASS, {n['SKIP']} SKIP, {n['FAIL']} FAIL.", ""]
    for _, ln in lines:
        L.append(f"\n### {ln[3:]}\n" if ln.startswith("--") else f"- {ln}")
    with open(os.path.join(build, "lexicon", "VALIDATION.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L) + "\n")
