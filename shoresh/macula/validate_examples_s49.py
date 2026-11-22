"""Stage 49 checks (SPEC 1.7, section 10 "new in 1.7"). Imports nothing from the builders; reads only the build's own
files (and h1 for the copied folders, the analysis release for D36 a, terms.tsv and entities.tsv).

run(R, build, compare=None): per edition every condition "new in 1.7", each recomputed here by code of its own:
copied folders, format, words and pieces (D29, D35, D36), clauses (D30, D31, D32 and the carried clauses), values
carried (every value against its grc row through its from_* key and terms.tsv; D16), own values (D37 c, D38, D39),
heads (D33), who (D34 a, b, c), added, who account, passages (D39 to D41), links (D42), files (D43, D44: lexemes,
participants, facts, the statement tables, carry_account, differ), the strict view, no Greek / no English, model
attribution, and the rebuild (compare). Every count of section 6 marked "about" is printed exactly.
"""
import collections as C
import hashlib
import json
import os
import re
import tomllib
import unicodedata

import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
H1 = os.path.join(HERE, "data/source-examples/h1")
TERMS = os.path.join(ROOT, "internal-docs/source-examples-spec/terms.tsv")
ANA = os.path.join(ROOT, "internal-docs/hebrew-nt-analysis-release/v0.2")
ENT = os.path.join(HERE, "data/entities/entities.tsv")
GLOSSED = os.path.join(ROOT, "internal-docs/source-examples-work/glossed-i1")
EDS = ("heb_mod", "heb_scg")
FOLDERS = ("hbo", "arc", "grc", "other", "lexicon")
FILES = {"words.parquet", "pieces.parquet", "clauses.parquet", "constituents.parquet", "added.parquet",
         "who_account.parquet", "passages.parquet", "links.parquet", "link_account.parquet", "lexemes.tsv",
         "participants.tsv", "facts.parquet", "forms.parquet", "paradigms.parquet", "markers.parquet",
         "constructions.parquet", "orders.parquet", "agreement.parquet", "frames.parquet", "pairs.parquet",
         "clause_links.parquet", "exceptions.parquet", "profile.tsv", "terms.tsv", "terms-notes.md", "map.tsv",
         "relmap.tsv", "source_errors.tsv", "categories.toml", "sources.json", "COLUMNS.md", "READ-FIRST.md",
         "VALIDATION.md", "carry_account.tsv", "differ.parquet"}
NEW = {"words": ["clause_basis", "from_t"], "pieces": ["basis", "who_from"], "clauses": ["from_clause"],
       "constituents": ["from_ord", "own_basis"], "added": ["from_clause", "from_t", "own_basis"],
       "who_account": ["from_t", "basis"], "passages": ["from_passage"], "links": [], "link_account": [],
       "facts": []}
EMPTY = {"pieces": ["pid", "fused", "sense", "domain", "concept", "concept_by", "clusivity", "clusivity_basis",
                    "noun_rel", "noun_head_t", "noun_head_n"],
         "clauses": ["via", "rule", "pattern", "role_wrapped", "line", "subject_model"],
         "constituents": ["frame_role"], "words": ["after"]}
OPENERS = ("cj", "rel", "prep", "om", "art")
NEGS = {"hbo": ("לֹא", "אַיִן", "אַל", "בֵּלֶת", "בַּל"), "arc": ("לָא",)}
MEANING = ("relation", "time", "aspect", "line_kind", "mood")
FORMKEYS = ("kind", "voice", "transitivity", "subject_form", "subject_switch", "fronted", "neg_scope")
WRITE = False
LINES = []


def H(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def T(path):
    return pq.read_table(path).to_pylist()


def TS(path):
    with open(path, encoding="utf-8", newline="") as fh:
        ls = fh.read().split("\n")
    hd = ls[0].split("\t")
    return [dict(zip(hd, x.split("\t"))) for x in ls[1:] if x]


def nul(v):
    return v is None or v == "" or v == "{}" or v == "[]"


def heb_ok(s):
    return all(0x0590 <= ord(c) <= 0x05FF or 0xFB1D <= ord(c) <= 0xFB4F or c in " ͏" for c in s)


GREEK = re.compile("[Ͱ-Ͽἀ-῿]")


def walk(d):
    out = []
    for r, _, fs in os.walk(d):
        out += [os.path.relpath(os.path.join(r, f), d) for f in fs]
    return sorted(out)


class G_:
    def __init__(self, b):
        d = os.path.join(b, "grc")
        self.W = {r["t"]: r for r in T(os.path.join(d, "words.parquet"))}
        self.P = {r["t"]: r for r in T(os.path.join(d, "pieces.parquet"))}
        self.Cl = T(os.path.join(d, "clauses.parquet"))
        self.C = {r["clause"]: r for r in self.Cl}
        self.order = {r["clause"]: i for i, r in enumerate(self.Cl)}
        self.K = T(os.path.join(d, "constituents.parquet"))
        self.Kd = {(r["clause"], r["ord"]): r for r in self.K}
        self.A = T(os.path.join(d, "added.parquet"))
        self.Ad = {(r["clause"], r["verb"], r["role"]): r for r in self.A}
        self.WA = {r["t"]: r for r in T(os.path.join(d, "who_account.parquet"))}
        self.PS = T(os.path.join(d, "passages.parquet"))
        self.PSd = {r["passage"]: r for r in self.PS}
        self.L = T(os.path.join(d, "links.parquet"))
        self.F = T(os.path.join(d, "facts.parquet"))
        self.anc = {}
        for k in self.C:
            a, x = [], self.C[k]["parent"]
            while x:
                a.append(x)
                x = self.C[x]["parent"]
            self.anc[k] = a
        self.vfirst = {}
        for t in sorted(self.W):
            r = self.W[t]
            self.vfirst.setdefault((r["book"], r["chapter"], r["verse"]), t)

    def up(self, k):            # k and its ancestors, innermost first
        return [k] + self.anc[k]

    def common(self, ks):
        s = None
        for k in ks:
            u = self.up(k)
            s = set(u) if s is None else s & set(u)
        if not s:
            return ""
        return max(s, key=lambda x: len(self.anc[x]))


def terms():
    rows = TS(TERMS)
    g2c = {(r["category"], r["grc"]): r["code"] for r in rows if r["grc"]}
    c2h = {(r["category"], r["code"]): r["hbo"] for r in rows}
    h2c = {(r["category"], r["hbo"]): r["code"] for r in rows if r["hbo"]}
    return g2c, c2h, h2c


def catch():
    s = set()
    for r in TS(ENT):
        ty, rest = r["entity"].split(":", 1)
        if rest.startswith("Generic") or rest in ("Messenger", "Messengers"):
            s.add(ty + ":e" + hashlib.sha1(r["entity"].encode()).hexdigest()[:10])
    return s


# ---- the independent recomputation of one edition --------------------------------------------------------------------

class Ed:
    def __init__(self, b, ed, G):
        self.b, self.ed, self.G = b, ed, G
        d = os.path.join(b, ed)
        self.d = d
        self.w = T(os.path.join(d, "words.parquet"))
        self.p = T(os.path.join(d, "pieces.parquet"))
        self.c = T(os.path.join(d, "clauses.parquet"))
        self.k = T(os.path.join(d, "constituents.parquet"))
        self.a = T(os.path.join(d, "added.parquet"))
        self.wa = T(os.path.join(d, "who_account.parquet"))
        self.ps = T(os.path.join(d, "passages.parquet"))
        self.l = T(os.path.join(d, "links.parquet"))
        self.la = T(os.path.join(d, "link_account.parquet"))
        self.W = {r["t"]: r for r in self.w}
        self.Pd = {(r["t"], r["n"]): r for r in self.p}
        self.parts_of = C.defaultdict(list)
        for r in self.p:
            self.parts_of[r["t"]].append(r)
        ow = T(os.path.join(b, "other", ed, "words.parquet"))
        self.ow = ow
        op = T(os.path.join(b, "other", ed, "parts.parquet"))
        self.op = C.defaultdict(list)
        for r in op:
            self.op[r["s"]].append(r)
        for v in self.op.values():
            v.sort(key=lambda r: r["p"])
        self.ts = sorted(r["s"] for r in ow if r["text"])
        self.ix = {t: i for i, t in enumerate(self.ts)}
        self.words = {r["s"]: r for r in ow if r["text"]}
        # strict links of this edition
        self.up_, self.down = C.defaultdict(set), C.defaultdict(set)
        self.model = C.defaultdict(set)
        for r in G.L:
            if r["other"] != ed or r["s"] not in self.words:
                continue
            if r["basis"] == "linked":
                self.up_[r["s"]].add(r["t"])
                self.down[r["t"]].add(r["s"])
            else:
                self.model[r["s"]].add(r["t"])
        self.o2o = {s: min(g) for s, g in self.up_.items() if len(g) == 1 and len(self.down[min(g)]) == 1}
        self.o2o_g = {g: s for s, g in self.o2o.items()}

    def stem_kind(self, t):
        ps = self.op[t]
        suf = [p["class"] == "pron" and any(q["class"] not in ("cj", "art", "rel") for q in ps[:i]) for i, p in enumerate(ps)]
        st = [i for i in range(len(ps)) if not suf[i]]
        s = st[-1] if st else None
        return ["stem" if i == s else ("prefix" if s is not None and i < s else "suffix") for i in range(len(ps))]

    def placement(self):
        G = self.G
        pl, how = {}, {}
        for t in self.ts:
            gs = self.up_.get(t)
            if not gs:
                continue
            cs = sorted({G.W[g]["clause"] for g in gs if G.W[g]["clause"]})
            if not cs:
                continue
            if len(cs) == 1:
                pl[t], how[t] = cs[0], "D30a"
                continue
            deep = max(cs, key=lambda z: len(G.anc[z]))
            if all(x in G.up(deep) for x in cs):
                pl[t], how[t] = deep, "D30b"
                continue
            k = G.common(cs)
            if k:
                pl[t], how[t] = k, "D30c"
        lk = dict(pl)
        bv = C.defaultdict(list)
        for t in self.ts:
            w = self.words[t]
            bv[(w["book"], w["chapter"], w["verse"])].append(t)
        self.bv = bv
        for v, ts in bv.items():
            got = [t for t in ts if t in lk]
            for t in ts:
                if t in lk:
                    continue
                P = [x for x in got if x < t]
                Q = [x for x in got if x > t]
                P, Q = (P[-1] if P else None), (Q[0] if Q else None)
                if P is None and Q is None:
                    how[t] = "N4"
                elif P is None or Q is None:
                    pl[t], how[t] = lk[P if P is not None else Q], "N3"
                elif lk[P] == lk[Q]:
                    pl[t], how[t] = lk[P], "N1"
                else:
                    between = [x for x in ts if P < x < Q]
                    op = [x for x in between if self.op[x] and self.op[x][0]["class"] in OPENERS]
                    if op and t >= op[0]:
                        pl[t], how[t] = lk[Q], "N2a"
                    else:
                        k = G.common([lk[P], lk[Q]])
                        pl[t], how[t] = (k, "N2b") if k else (lk[P], "N2c")
        self.pl, self.how, self.lk = pl, how, lk
        sub = C.defaultdict(set)
        for t, k in pl.items():
            for a in G.up(k):
                sub[a].add(t)
        self.sub = sub
        keys, seen = {}, C.Counter()
        for r in G.Cl:
            k = r["clause"]
            if k in sub:
                ts = sorted(sub[k])
                base = f"cl:{ts[0]}.1:{sum(len(self.op[t]) for t in ts)}"
                seen[base] += 1
                keys[k] = base + ("" if seen[base] == 1 else f":{seen[base]}")
        self.keys = keys

    def parent(self, k):
        return next((a for a in self.G.anc[k] if a in self.keys), "")


def d16v(own):
    """key -> (time code or None, parent, verbless flag) -> key -> code or None (validator's own D16)."""
    out = {}
    ABS = ("past", "present", "future", "timeless", "irrealis")

    def timed(k):
        p = own[k][1]
        while p and own[p][0] is None:
            p = own[p][1]
        return p
    order = sorted(own, key=lambda k: 0)
    for _ in range(64):
        changed = False
        for k in order:
            if k in out:
                continue
            code = own[k][0]
            if code is None:
                if not own[k][2]:
                    out[k] = None
                    changed = True
                    continue
                p = timed(k)
                if not p:
                    out[k] = None
                    changed = True
                elif p in out:
                    out[k] = out[p]
                    changed = True
                continue
            if code in ABS:
                out[k] = code
                changed = True
                continue
            p = timed(k)
            if not p:
                out[k] = None
                changed = True
                continue
            if p not in out:
                continue
            P = out[p]
            if P is None:
                v = None
            elif code == "simultaneous":
                v = None if P == "irrealis" else P
            elif code == "anterior":
                v = "past" if P in ("past", "present") else None
            else:
                v = "future" if P in ("present", "future") else None
            out[k] = v
            changed = True
        if not changed:
            break
    return out


def check_edition(R, b, ed, G, g2c, c2h, h2c, ca, about):
    E = Ed(b, ed, G)
    d = E.d
    # ---- format ------------------------------------------------------------------------------------------------
    have = set(os.listdir(d))
    have.add("VALIDATION.md")      # the validator's own file (written with --write-md after this check)
    R.check(f"{ed} format (1.7): the folder holds the files of 4.15 and no other (VALIDATION.md is the validator's)", have == FILES,
            f"missing {sorted(FILES - have)}, extra {sorted(have - FILES)}")
    bad = []
    for tb, new in NEW.items():
        g = pq.read_schema(os.path.join(b, "grc", f"{tb}.parquet"))
        e = pq.read_schema(os.path.join(d, f"{tb}.parquet"))
        want = [(f.name, str(f.type)) for f in g] + [(n, None) for n in new]
        got = [(f.name, str(f.type)) for f in e]
        if [x[0] for x in want] != [x[0] for x in got] or any(w[1] and w[1] != h[1] for w, h in zip(want, got)):
            bad.append(tb)
    R.check(f"{ed} format (1.7): every table has the grc columns in order (same types), then exactly the new columns",
            not bad, bad)
    tabs = {"words": E.w, "pieces": E.p, "clauses": E.c, "constituents": E.k}
    nonempty = [(tb, c) for tb, cs in EMPTY.items() for c in cs if any(not nul(r[c]) for r in tabs[tb])]
    R.check(f"{ed} format (1.7): every column 4.15 calls empty is empty on every row", not nonempty, nonempty)
    # ---- words, pieces -----------------------------------------------------------------------------------------
    R.check(f"{ed} words (1.7): one row per other/{ed} word with text, and no other", [r["t"] for r in E.w] == E.ts,
            f"{len(E.w):,} rows; left out {sum(1 for r in E.ow if not r['text'])} tokens without text")
    R.check(f"{ed} words (1.7): t, id unique", len({r["t"] for r in E.w}) == len(E.w) == len({r["id"] for r in E.w}))
    vv = {(r["book"], r["chapter"], r["verse"]) for r in E.ow if r["text"]}
    R.check(f"{ed} words (1.7): every verse of other/ present", vv == {(r["book"], r["chapter"], r["verse"]) for r in E.w}, len(vv))
    badw = [r["t"] for r in E.w if (r["id"], r["book"], r["chapter"], r["verse"], r["w"], r["text"]) !=
            (E.words[r["t"]]["id"], E.words[r["t"]]["book"], E.words[r["t"]]["chapter"], E.words[r["t"]]["verse"],
             E.words[r["t"]]["w"] + 1, E.words[r["t"]]["text"])]
    R.check(f"{ed} words (1.7): id, place, w (+1), text as other/", not badw, badw[:5])
    exp = [(t, i + 1, p) for t in E.ts for i, p in enumerate(E.op[t])]
    R.check(f"{ed} pieces (1.7): one row per parts.parquet row", [(r["t"], r["n"]) for r in E.p] == [(t, n) for t, n, _ in exp], len(E.p))
    bp = [(r["t"], r["n"]) for r, (t, n, p) in zip(E.p, exp) if (r["text"], r["lexeme"], r["class"], r["basis"]) !=
          (p["text"], p["lexeme"], p["class"], p["basis"])]
    R.check(f"{ed} pieces (1.7): text, lexeme, class, basis equal parts.parquet", not bp, bp[:5])
    sp = [t for t in E.ts if "".join(p["text"] for p in E.parts_of[t]) != E.words[t]["text"]]
    R.info(f"{ed} pieces (1.7): words whose parts do not spell the token (the letterless articles of D23 aside)", len(sp))
    R.check(f"{ed} pieces (1.7): the parts of a word spell its text, but where the analysis's parts differ from the "
            "token (listed)", all(E.words[t]["analysis"] for t in sp), sp[:5])
    kinds = {t: E.stem_kind(t) for t in E.ts}
    bk = [(r["t"], r["n"]) for r in E.p if kinds[r["t"]][r["n"] - 1] != r["kind"]]
    R.check(f"{ed} pieces (1.7): exactly one stem per word, kind recomputed by D35", not bk and
            all(k.count("stem") == 1 for k in kinds.values()), bk[:5])
    lexk = {r["lexeme"] for r in TS(os.path.join(d, "lexemes.tsv"))}
    lexi = {r["lexeme"] for r in TS(os.path.join(b, "lexicon", "lexemes.tsv"))}
    R.check(f"{ed} pieces (1.7): every lexeme in the edition's lexemes.tsv and in lexicon/lexemes.tsv",
            all(r["lexeme"] in lexk and r["lexeme"] in lexi for r in E.p))
    about["D35 referring heads (exact)"] = dict(C.Counter(
        f"{r['class']} {r['kind']}" for r in E.p if (r["kind"] == "stem" and r["class"] in ("noun", "pron")) or
        (r["kind"] == "suffix" and r["class"] == "pron")))
    marks_check(R, E, b, about)
    # ---- clauses -----------------------------------------------------------------------------------------------
    E.placement()
    hw = {r["t"]: r for r in E.w}
    cnt = C.Counter(E.how.values())
    R.info(f"{ed} clauses (1.7): placement by case, recomputed", dict(sorted(cnt.items())))
    badp = [t for t in E.ts if hw[t]["clause"] != (E.keys[E.pl[t]] if t in E.pl else "") or
            hw[t]["clause_basis"] != (("linked" if E.how[t].startswith("D30") else "derived") if t in E.pl else "")]
    R.check(f"{ed} clauses (1.7): words.clause and clause_basis recomputed by D30 and D31", not badp, badp[:5])
    ck = {r["from_clause"]: r for r in E.c}
    R.check(f"{ed} clauses (1.7): every grc clause with a placed word has exactly one row, and no other row",
            set(ck) == set(E.keys) and len(ck) == len(E.c), f"{len(E.c):,} rows; empty Greek clauses {len(G.Cl) - len(E.keys):,}")
    R.check(f"{ed} clauses (1.7): keys made by section 3, unique", all(ck[k]["clause"] == E.keys[k] for k in ck)
            and len({r["clause"] for r in E.c}) == len(E.c))
    R.check(f"{ed} clauses (1.7): every words.clause exists", {r["clause"] for r in E.w if r["clause"]} <= {r["clause"] for r in E.c})
    bc = []
    for r in E.c:
        k = r["from_clause"]
        s = sorted(E.sub[k])
        gaps = E.ix[s[-1]] - E.ix[s[0]] + 1 != len(s)
        par = E.parent(k)
        if (r["first"], r["last"], r["gaps"], r["parent"], r["depth"]) != (
                s[0], s[-1], gaps, E.keys[par] if par else "", sum(1 for a in G.anc[k] if a in E.keys)):
            bc.append(r["clause"])
    owncount = C.Counter(E.pl.values())
    bc += [r["clause"] for r in E.c if r["words"] != owncount[r["from_clause"]]]
    R.check(f"{ed} clauses (1.7): first, last, words, gaps, parent, depth recomputed", not bc, bc[:5])
    # parent tree per sentence
    sent = {}
    for t in E.ts:
        if t in E.pl:
            sent[t] = G.W[G.C[E.pl[t]]["first"]]["sentence"]
    for v, ts in E.bv.items():
        for i, t in enumerate(ts):
            if t in sent:
                continue
            pv = [x for x in ts[:i] if x in E.pl]
            nx = [x for x in ts[i + 1:] if x in E.pl]
            sent[t] = sent[pv[-1]] if pv else sent[nx[0]] if nx else (G.W[G.vfirst[v]]["sentence"] if v in G.vfirst else None)
    bs = [t for t in E.ts if hw[t]["sentence"] != sent[t]]
    R.check(f"{ed} clauses (1.7): sentence recomputed by D32", not bs, bs[:5])
    cr = {r["clause"]: r for r in E.c}
    loop = 0
    mixed = 0
    for r in E.c:
        seen, x = set(), r["clause"]
        while x:
            if x in seen:
                loop += 1
                break
            seen.add(x)
            x = cr[x]["parent"]
        if r["parent"] and G.W[G.C[cr[r["parent"]]["from_clause"]]["first"]]["sentence"] != G.W[G.C[r["from_clause"]]["first"]]["sentence"]:
            mixed += 1
    R.check(f"{ed} clauses (1.7): parent a tree per sentence (D32), no loop, ending at the top", loop == 0 and mixed == 0, f"loops {loop}, across sentences {mixed}")
    vs = C.defaultdict(set)
    for t, s in sent.items():
        w = E.words[t]
        vs[(w["book"], w["chapter"], w["verse"])].add(s)
    about["D32 verses holding words of two or more Greek sentences"] = sum(1 for x in vs.values() if len(x) > 1)
    badpred = [r["clause"] for r in E.c if r["pred"] and not (r["first"] <= r["pred"] <= r["last"])]
    R.check(f"{ed} clauses (1.7): pred, where not 0, a word inside the clause's span", not badpred, badpred[:5])
    R.info(f"{ed} clauses (1.7): with gaps / empty Greek clauses / unplaced words",
           f"{sum(r['gaps'] for r in E.c):,} / {len(G.Cl) - len(E.keys):,} / {sum(1 for t in E.ts if t not in E.pl):,}")
    # ---- values carried, own values ----------------------------------------------------------------------------
    pk = {}
    for t in E.ts:
        for p in E.parts_of[t]:
            pk[(t, p["n"])] = p
    own_t = {}
    for k in E.keys:
        gm = json.loads(G.C[k]["marks"])
        own_t[k] = (g2c[("time", gm["time"])] if "time" in gm else None, E.parent(k), "time_abs" in gm)
    ta = d16v(own_t)
    badv, badown, diff_ta, wrongkey, notterm = [], [], 0, 0, 0
    mterms = {(c, h) for (c, code), h in c2h.items()}
    ownw = C.defaultdict(list)
    for t, x in E.pl.items():
        ownw[x].append(t)
    for v in ownw.values():
        v.sort()
    for r in E.c:
        k = r["from_clause"]
        g = G.C[k]
        gm = json.loads(g["marks"])
        m = json.loads(r["marks"])
        mm = json.loads(r["marks_model"]) if r["marks_model"] else {}
        want = {}
        for cat in MEANING:
            if cat in gm:
                want[cat] = c2h[(cat, g2c[(cat, gm[cat])])]
        for cat in ("force", "polarity"):
            if cat in gm:
                want[cat] = gm[cat]
        if ta[k] is not None:
            want["time_abs"] = c2h[("time", ta[k])]
        if ta[k] != (g2c[("time", gm["time_abs"])] if "time_abs" in gm else None):
            diff_ta += 1
        got = {x: v for x, v in m.items() if x not in ("connective", "negator")}
        if got != want:
            badv.append(r["clause"])
        if any(x in m for x in FORMKEYS):
            wrongkey += 1
        for cat in MEANING + ("time_abs",):
            if cat in m and ("time" if cat == "time_abs" else cat, m[cat]) not in mterms:
                notterm += 1
        for col in ("role", "quote", "speaker", "addressee", "quote_model", "speaker_model", "addressee_model"):
            if r[col] != g[col]:
                badv.append(f"{r['clause']} {col}")
        if r["pred_kind"] != (g["pred_kind"] if r["pred"] else "none") or r["speech_basis"] != ("linked" if r["quote"] else ""):
            badv.append(f"{r['clause']} pred_kind/speech_basis")
        cands = sorted(t for t in E.down.get(g["pred"], ()) if t in E.sub[k]) if g["pred"] else []
        v = [t for t in cands if E.Pd[(t, kinds_stem(E, t))]["class"] == "verb"]
        if r["pred"] != ((v or cands or [0])[0]):
            badv.append(f"{r['clause']} pred")
        # own: connective, negator
        conn, cm = [], False
        for t in ownw[k]:
            stop = False
            for p in E.parts_of[t]:
                if p["class"] in ("cj", "rel"):
                    conn.append(p["lexeme"])
                    cm = cm or p["basis"] == "model"
                else:
                    cm = cm or (p["basis"] == "model" and bool(conn))
                    stop = True
                    break
            if stop:
                break
        neg = None
        for t in ownw[k]:
            for p in E.parts_of[t]:
                f = p["lexeme"].split(":")
                if len(f) > 2 and f[2] in NEGS.get(f[1], ()):
                    neg = p
                    break
            if neg:
                break
        wm, wmm = {}, {}
        if conn:
            (wmm if cm else wm)["connective"] = conn
        if neg:
            (wmm if neg["basis"] == "model" else wm)["negator"] = neg["lexeme"]
        if {x: v for x, v in m.items() if x in ("connective", "negator")} != wm or mm != wmm:
            badown.append(r["clause"])
        if set(m) & set(mm):
            badown.append(f"{r['clause']} key in marks and marks_model")
    R.check(f"{ed} values carried (1.7): every carried clause value equals its grc row's (terms through terms.tsv; "
            "relation, time, aspect, line_kind, mood, force, polarity, role, pred, pred_kind, quote, speaker, "
            "addressee, the three _model columns); time_abs by D16 over the carried tree", not badv, badv[:5])
    R.info(f"{ed} values carried (1.7): time_abs differing from the Greek clause's (D37 b)", diff_ta)
    R.check(f"{ed} values carried (1.7): no Greek form key of 4.15 in marks", wrongkey == 0, wrongkey)
    R.check(f"{ed} values carried (1.7): every meaning value an hbo term of its category", notterm == 0, notterm)
    R.check(f"{ed} own values (1.7): connective, negator recomputed by D37 c; a key read off a model part in "
            "marks_model only", not badown, badown[:5])
    E.who_calc()
    heads_check(R, E, hw)
    who_check(R, E, pk, ca, about)
    cons_check(R, E, g2c, c2h, pk)
    added_check(R, E, c2h, pk, about)
    account_check(R, E, pk, ca)
    pass_check(R, E)
    links_check(R, E)
    return E


def kinds_stem(E, t):
    return next(p["n"] for p in E.parts_of[t] if p["kind"] == "stem")


def _norm(ed, s):
    s = unicodedata.normalize("NFD", s)
    hi = 0x05EA
    lo = 0x05B0 if ed == "heb_scg" else 0x05D0
    return unicodedata.normalize("NFC", "".join(c for c in s if lo <= ord(c) <= hi or 0xFB1D <= ord(c) <= 0xFB4F))


def marks_check(R, E, b, about):
    ed = E.ed
    word, piece = C.defaultdict(list), C.defaultdict(list)
    for lg in ("hbo", "arc"):
        tx = {r["t"]: r["text"] for r in T(os.path.join(b, lg, "words.parquet"))}
        per = C.defaultdict(list)
        for r in T(os.path.join(b, lg, "pieces.parquet")):
            m = json.loads(r["marks"])
            per[r["t"]].append((r["n"], r["lexeme"], m))
            piece[(_norm(ed, r["text"]), r["class"], r["lexeme"])].append(m)
        for t, v in per.items():
            v.sort(key=lambda x: x[0])
            word[(_norm(ed, tx[t]), tuple(x[1] for x in v))].append([x[2] for x in v])
    ana = {}
    for r in T(os.path.join(ANA, ed, "words.parquet")):
        ana[(r["book"], r["chapter"], r["verse"], r["i"], r["part"])] = (r["form"], r["person"])
    memo = {}

    def vote(lst):
        out = {}
        for cat in ("stem", "person", "number", "gender", "state"):
            c = C.Counter(m[cat] for m in lst if cat in m)
            if c:
                v, n = max(sorted(c.items()), key=lambda x: x[1])
                if n >= 0.9 * len(lst):
                    out[cat] = v
        return out
    bad = []
    cnt = C.Counter()
    for t in E.ts:
        w = E.words[t]
        ps = E.parts_of[t]
        key = (_norm(ed, w["text"]), tuple(p["lexeme"] for p in ps))
        if key in word:
            if ("w",) + key not in memo:
                ws = word[key]
                memo[("w",) + key] = [vote([x[i] for x in ws]) for i in range(len(ps))]
            vs = [(v, "word") for v in memo[("w",) + key]]
        else:
            vs = []
            for p in ps:
                k2 = ("p", _norm(ed, p["text"]), p["class"], p["lexeme"])
                if k2 not in memo:
                    memo[k2] = vote(piece[k2[1:]]) if k2[1:] in piece else {}
                vs.append((memo[k2], "part"))
        op = E.op[t]
        for p, (v, how), o in zip(ps, vs, op):
            fo, pe = ana.get((w["book"], w["chapter"], w["verse"], w["w"], o["p"]), (None, None))
            want = dict(v)
            if p["class"] == "verb" and fo:
                want["type"] = re.sub(r"[^a-z0-9]+", "_", fo.lower()).strip("_")
                cnt[f"(a) type {p['basis']}"] += 1
            if p["class"] == "verb" and pe in ("first", "second", "third"):
                want["person"] = {"first": "1", "second": "2", "third": "3"}[pe]
                cnt[f"(a) person {p['basis']}"] += 1
            for cat in ("stem", "number", "gender", "state", "person"):
                if cat in v and (cat != "person" or want.get("person") == v[cat]):
                    cnt[f"(b) {cat} {how} {p['basis']}"] += 1
            if json.loads(p["marks"]) != want:
                bad.append((t, p["n"]))
    R.check(f"{ed} pieces (1.7): marks recomputed by D36 (the analysis part and the Tanakh lookup apart)", not bad, bad[:5])
    about["D36 marks by part, category and basis"] = dict(sorted(cnt.items()))


def _who_calc(E):
    G = E.G
    W = {}
    for t in E.ts:
        gs = E.up_.get(t, ())
        vals = sorted({G.P[g]["who"] for g in gs if G.P[g]["who"]})
        if len(vals) == 1:
            st = next(p for p in E.parts_of[t] if p["kind"] == "stem")
            if st["class"] in ("noun", "verb", "adj", "pron", "num"):
                W[(t, st["n"])] = (vals[0], "a")
    gp = sorted(g for g, r in G.P.items() if r["class"] == "pron" and r["who"] and g not in E.down)
    dep = C.defaultdict(list)
    for g in gp:
        if G.W[g]["head"]:
            dep[G.W[g]["head"]].append(g)
    B = set()
    E.bsuffix = {}
    for h in sorted(dep):
        if h not in E.down:
            continue
        sf = [(t, p["n"]) for t in sorted(E.down[h]) for p in E.parts_of[t] if p["kind"] == "suffix" and p["class"] == "pron"]
        if len(dep[h]) == 1 and len(sf) == 1 and sf[0] not in W:
            W[sf[0]] = (G.P[dep[h][0]]["who"], "b")
            B.add(dep[h][0])
            E.bsuffix[dep[h][0]] = sf[0]
    gc = C.defaultdict(list)
    for g in gp:
        if g not in B and G.W[g]["clause"]:
            gc[G.W[g]["clause"]].append(g)
    hc = C.defaultdict(list)
    for t, k in E.pl.items():
        for p in E.parts_of[t]:
            if p["class"] == "pron" and (t, p["n"]) not in W:
                hc[k].append((t, p["n"]))
    E.csuffix = {}
    for k in gc:
        if k in E.keys and len(gc[k]) == 1 and len(hc.get(k, [])) == 1:
            W[hc[k][0]] = (G.P[gc[k][0]]["who"], "c")
            E.csuffix[gc[k][0]] = hc[k][0]
    E.Wv = W


Ed.who_calc = _who_calc


def heads_check(R, E, hw):
    G = E.G
    bad, c = [], C.Counter()
    for t in E.ts:
        r = hw[t]
        if t not in E.o2o:
            if r["head"] is not None or r["from_t"] is not None:
                bad.append(t)
            continue
        g = E.o2o[t]
        h = G.W[g]["head"]
        if h == 0:
            want = (0, "root")
        else:
            x = h
            while x and x not in E.o2o_g:
                x = G.W[x]["head"]
            want = (E.o2o_g[x], "direct" if x == h else "ancestor") if x else (0, "root")
        c[want[1]] += 1
        if (r["head"], r["head_basis"], r["rel"], r["rel_shared"], r["from_t"]) != (want[0], want[1], G.W[g]["rel"], G.W[g]["rel_shared"], g):
            bad.append(t)
    R.check(f"{E.ed} heads (1.7): head filled exactly on the one-to-one words, each recomputed by D33", not bad,
            f"{len(E.o2o):,} one-to-one; {bad[:5]}")
    loops = 0
    for t in E.ts:
        seen, x = set(), t
        while x and hw[x]["head"]:
            if x in seen:
                loops += 1
                break
            seen.add(x)
            x = hw[x]["head"]
    R.check(f"{E.ed} heads (1.7): following heads ends at a root or a null head, no loop", loops == 0, loops)
    R.info(f"{E.ed} heads (1.7): direct, ancestor, root", dict(sorted(c.items())))
    badp = []
    for r in E.p:
        hr = hw[r["t"]]
        if r["kind"] == "stem" and hr["head"] is not None:
            want = (0, 0) if hr["head"] == 0 else (hr["head"], kinds_stem(E, hr["head"]))
            if (r["head_t"], r["head_n"], r["head_basis"], r["rel"]) != want + (hr["head_basis"], hr["rel"]):
                badp.append((r["t"], r["n"]))
        elif (r["head_t"], r["head_n"], r["head_basis"], r["rel"]) != (None, None, "", ""):
            badp.append((r["t"], r["n"]))
    R.check(f"{E.ed} heads (1.7): the stem piece takes the word's edge; no edge inside a word", not badp, badp[:5])


def who_check(R, E, pk, ca, about):
    G = E.G
    bad = []
    for r in E.p:
        k = (r["t"], r["n"])
        w = E.Wv.get(k)
        if (r["who"], r["who_basis"]) != ((w[0], "model" if r["basis"] == "model" else "linked") if w else ("", "")):
            bad.append(k)
        elif w and (r["who_from"] is None or G.P[r["who_from"]]["who"] != w[0]):
            bad.append(k)
        elif not w and r["who_from"] is not None:
            bad.append(k)
    c = C.Counter(v[1] for v in E.Wv.values())
    R.check(f"{E.ed} who (1.7): every who recomputed by D34 a, b, c in that order (who_from a Greek piece with that "
            "value)", not bad, f"{dict(sorted(c.items()))}; {bad[:5]}")
    about["D34 c pieces (exact)"] = c["c"]
    R.check(f"{E.ed} who (1.7): no who on a piece of class cj, prep, art, rel",
            not [r for r in E.p if r["who"] and r["class"] in ("cj", "prep", "art", "rel")])
    R.check(f"{E.ed} who (1.7): who_basis model exactly on the pieces of basis model that have a who",
            all((r["who_basis"] == "model") == (r["basis"] == "model") for r in E.p if r["who"]))
    pt = TS(os.path.join(E.d, "participants.tsv"))
    ents = set()
    for r in E.p:
        ents.update(r["who"].split())
    for r in E.c:
        for col in ("speaker", "addressee", "speaker_model", "addressee_model"):
            if r[col]:
                ents.update(r[col].split())
    for r in E.a:
        ents.update(r["who"].split())
    R.check(f"{E.ed} who (1.7): every ent of who, speaker, addressee, added.who and the M columns in participants.tsv, "
            "and no other row", {r["ent"] for r in pt} == ents, len(pt))
    R.check(f"{E.ed} who (1.7): every name in Hebrew script or empty; catch-all participants unnamed",
            all(heb_ok(r["name"]) for r in pt) and all(not r["name"] for r in pt if r["ent"] in ca),
            [r["name"] for r in pt if not heb_ok(r["name"])][:3])
    E.pt = pt


def cons_check(R, E, g2c, c2h, pk):
    G = E.G
    rows = []
    n = C.Counter()
    for r in G.K:
        k = r["clause"]
        if k not in E.keys:
            continue
        gw = [g for g in range(r["first"], r["last"] + 1) if g in G.W and G.W[g]["clause"] and k in G.up(G.W[g]["clause"])]
        hs = set().union(*[E.down.get(g, set()) for g in gw]) if gw else set()
        if not hs:
            continue
        f = min(hs)
        i = E.ix[f]
        if i:
            q = E.ts[i - 1]
            if q not in E.lk and q in E.pl and E.pl.get(q) == E.pl.get(f) and E.op[q] and E.op[q][0]["class"] in OPENERS:
                hs.add(q)
        n[k] += 1
        hl = sorted(hs)
        cand = sorted(E.down.get(r["head"], ())) if r["head"] else []
        hd = cand[0] if cand else None
        st = E.Pd[(hd, kinds_stem(E, hd))] if hd else None
        ob = "model" if st and st["basis"] == "model" else "derived"
        prep = ""
        if r["role"] == "pp" or r["class"] == "pp":
            for t in hl:
                q = [p for p in E.parts_of[t] if p["class"] == "prep"]
                if q:
                    prep = q[0]["lexeme"]
                    ob = "model" if q[0]["basis"] == "model" else ob
                    break
        rs = c2h[("ref_status", g2c[("ref_status", r["ref_status"])])] if r["ref_status"] else ""
        rf = {"noun": "noun", "pron": "pronoun", "adj": "adjective", "num": "number"}.get(st["class"] if st else "", "") if rs and hd else ""
        rows.append({"clause": E.keys[k], "ord": n[k], "role": r["role"], "head": hd, "first": hl[0], "last": hl[-1],
                     "class": st["class"] if st else "", "frame_role": "",
                     "sem_role": c2h[("sem_role", g2c[("sem_role", r["sem_role"])])] if r["sem_role"] else "",
                     "sem_role_basis": "linked" if r["sem_role"] else "", "prep": prep, "ref_status": rs, "ref_form": rf,
                     "from_ord": r["ord"], "own_basis": ob})
    bad = [i for i, (a, b) in enumerate(zip(E.k, rows)) if a != b]
    R.check(f"{E.ed} own values (1.7): constituents recomputed by D38 (span, head, class, prep, ref_form, own_basis; "
            "role, sem_role, ref_status carried by code)", len(E.k) == len(rows) and not bad,
            f"{len(E.k):,} rows, recomputed {len(rows):,}; {bad[:3]}")
    R.check(f"{E.ed} own values (1.7): ref_form filled only where ref_status is and head is not null",
            all(r["ref_status"] and r["head"] is not None for r in E.k if r["ref_form"]))
    R.info(f"{E.ed} constituents (1.7): rows", len(E.k))


def added_check(R, E, c2h, pk, about):
    G = E.G
    rows, seen, why = [], set(), C.Counter()
    for r in G.A:
        cand = sorted(E.down.get(r["verb"], ()))
        v = [t for t in cand if E.Pd[(t, kinds_stem(E, t))]["class"] == "verb"]
        verb = (v or cand or [None])[0]
        if verb is None:
            why["verb not linked"] += 1
            continue
        if verb not in E.pl:
            why["verb unplaced"] += 1
            continue
        key = (E.keys[E.pl[verb]], verb, r["role"])
        if key in seen:
            why["key taken"] += 1
            continue
        seen.add(key)
        st = E.Pd[(verb, kinds_stem(E, verb))]
        m = json.loads(st["marks"])
        if r["role"] == "A0" and "person" in m:
            kind, form, pe, nu, ge = "in_verb", "ending", m["person"], m.get("number", ""), m.get("gender", "")
        else:
            kind = "possessor" if r["role"] == "poss" else ("unsaid" if r["where"] == "unexpressed" else "elsewhere")
            form, pe, nu, ge = "none", r["person"], r["number"], r["gender"]
        ant = ""
        if r["antecedent"]:
            c = sorted(E.down.get(int(r["antecedent"].split(".")[0]), ()))
            if c:
                ant = f"{c[0]}.{kinds_stem(E, c[0])}"
        rows.append({"clause": key[0], "verb": verb, "role": r["role"], "kind": c2h[("added_kind", kind)],
                     "where": r["where"], "form": form, "person": pe, "number": nu, "gender": ge, "antecedent": ant,
                     "who": r["who"], "who_reason": r["who_reason"], "from_clause": r["clause"], "from_t": r["verb"],
                     "own_basis": st["basis"]})
    R.check(f"{E.ed} added (1.7): rows recomputed by D39 (the key unique; kind, form, person, number, gender on the "
            "Hebrew verb's stem piece; the rest carried)", rows == E.a and len({(r["clause"], r["verb"], r["role"]) for r in E.a}) == len(E.a),
            f"{len(E.a):,} rows; not carried {dict(why)}")
    ck = {r["clause"] for r in E.c}
    R.check(f"{E.ed} added (1.7): every clause, verb, antecedent exists in the edition",
            all(r["clause"] in ck and r["verb"] in E.W and (not r["antecedent"] or tuple(map(int, r["antecedent"].split("."))) in E.Pd) for r in E.a))
    own = C.defaultdict(list)
    for t, k in E.pl.items():
        own[E.keys[k]].append(t)
    about["D39 added rows whose clause holds an edition pronoun (exact)"] = sum(
        1 for r in E.a if any(p["class"] == "pron" for t in own[r["clause"]] for p in E.parts_of[t]))
    # who account
    G = E.G
    vz = {}
    kr = {v: k for k, v in E.keys.items()}
    cp = {r["clause"]: r["pred"] for r in E.c}
    for r in E.a:
        if r["form"] == "ending" and r["role"] == "A0" and cp[r["clause"]]:
            pr = cp[r["clause"]]
            vz[(pr, kinds_stem(E, pr))] = G.C[kr[r["clause"]]]["pred"]
    pheads = {r["head"] for r in E.k if r["role"] == "p" and r["head"]}
    gfor = {}
    for g, tn in list(E.bsuffix.items()) + list(E.csuffix.items()):
        gfor[tn] = g
    ca = CA
    want = []
    for r in E.p:
        tn = (r["t"], r["n"])
        hk = "noun" if r["kind"] == "stem" and r["class"] == "noun" else "pronoun" if r["kind"] == "stem" and r["class"] == "pron" \
            else "suffix" if r["kind"] == "suffix" and r["class"] == "pron" else None
        if hk is None and tn in vz:
            hk = "verb_zero"
        if not hk:
            continue
        if hk in ("noun", "pronoun"):
            g = next((x for x in sorted(E.up_.get(r["t"], ())) if x in G.WA), None)
        elif hk == "suffix":
            g = gfor.get(tn)
            g = g if g in G.WA else None
        else:
            g = vz[tn] if vz[tn] in G.WA else None
        if r["who"] and any(e not in ca for e in r["who"].split()):
            s = ("participant", "")
        elif r["who"]:
            s = ("generic", "")
        elif r["kind"] == "stem" and r["t"] in pheads:
            s = ("not_referring", "")
        elif g is not None and G.WA[g]["state"] not in ("participant", "generic"):
            s = (G.WA[g]["state"], G.WA[g]["reason"])
        elif g is not None:
            s = ("unresolved", "not_carried")
        else:
            s = ("no_row", "not_linked")
        want.append({"t": r["t"], "n": r["n"], "head_kind": hk, "state": s[0], "reason": s[1], "from_t": g,
                     "basis": "model" if r["basis"] == "model" else "derived"})
    R.check(f"{E.ed} who account (1.7): one row per referring head of D40 and none elsewhere, states recomputed, "
            "basis model exactly on model heads", want == E.wa, f"{len(E.wa):,} rows; " +
            str(dict(sorted(C.Counter(f"{r['head_kind']} {r['state']}" for r in E.wa).items()))))


def pass_check(R, E):
    G = E.G
    out, last = [], None
    wc = {r["t"]: r["clause"] for r in E.w}
    cl = sorted((r["first"], r["last"]) for r in E.c)
    for r in G.PS:
        hs = set()
        for g in range(r["first"], r["last"] + 1):
            hs |= E.down.get(g, set())
        if last is not None:
            hs = {h for h in hs if h > last}
        if not hs:
            continue
        f, l = min(hs), max(hs)
        last = l if last is None else max(last, l)
        lines = None
        if r["lines"] is not None:
            lines = []
            for a, b in json.loads(r["lines"]):
                x = {h for g in range(a, b + 1) for h in E.down.get(g, ()) if f <= h <= l}
                if x:
                    lines.append([min(x), max(x)])
            lines = json.dumps(lines, separators=(",", ":"))
        ins = [x for x in cl if f <= x[0] <= l]
        out.append({"passage": f"ps:nestle1904:{r['kind']}:{f}", "source": "nestle1904", "kind": r["kind"], "first": f,
                    "last": l, "first_clause": wc[f], "last_clause": wc[l], "clauses": len(ins),
                    "crossing": sum(1 for x in ins if x[1] > l), "lines": lines, "fact": r["fact"], "from_passage": r["passage"]})
    ov = sum(1 for a, b in zip(E.ps, E.ps[1:]) if b["first"] <= a["last"])
    R.check(f"{E.ed} passages (1.7): recomputed by D41, first <= last, no overlap within the source", out == E.ps and ov == 0
            and all(r["first"] <= r["last"] for r in E.ps), f"{len(E.ps)} of {len(G.PS)}; crossing clauses {sum(r['crossing'] for r in E.ps)}")


def links_check(R, E):
    G = E.G
    want = sorted(((r["s"], kinds_stem(E, r["s"]), "grc", r["t"], r["how"], r["agree"], r["basis"], r["agree_model"])
                   for r in G.L if r["other"] == E.ed and r["s"] in E.words), key=lambda x: (x[0], x[1], x[3], x[6], x[4]))
    got = [(r["t"], r["n"], r["other"], r["s"], r["how"], r["agree"], r["basis"], r["agree_model"]) for r in E.l]
    R.check(f"{E.ed} links (1.7): every grc link row of the edition is exactly one row on the stem piece of its word, "
            "and no other; every s a grc t; model rows model", want == got and all(r["s"] in G.W for r in E.l),
            f"{len(E.l):,} rows (model {sum(1 for r in E.l if r['basis'] == 'model'):,})")
    lc = C.Counter(E.Pd[(t, kinds_stem(E, t))]["class"] for t in E.up_)
    ac = C.Counter(E.Pd[(t, kinds_stem(E, t))]["class"] for t in E.ts)
    bad = 0
    for r in E.la:
        t = r["t"]
        sc = E.Pd[(t, kinds_stem(E, t))]["class"]
        if t in E.up_:
            s = ("linked", "") if E.Pd[(t, r["n"])]["kind"] == "stem" else ("word_linked", str(kinds_stem(E, t)))
        elif lc[sc] == 0:
            s = ("outside_alignment", sc)
        elif lc[sc] < 0.05 * ac[sc]:
            s = ("never_a_word", sc)
        else:
            s = ("no_counterpart", "")
        sm = "linked" if E.Pd[(t, r["n"])]["kind"] == "stem" and s[0] != "linked" and t in E.model else None
        bad += (r["state"], r["reason"], r["state_model"]) != s + (sm,)
    R.check(f"{E.ed} links (1.7): one strict link_account state per piece, recomputed by D42",
            bad == 0 and [(r["t"], r["n"]) for r in E.la] == [(r["t"], r["n"]) for r in E.p],
            str(dict(sorted(C.Counter(r["state"] for r in E.la).items()))))


# ---- D44 recomputed: the account ---------------------------------------------------------------------------------------

RULES = {   # (table, column) -> how a filled value is accounted: (state, basis or a row column, prefixed '@')
    ("words", "sentence"): ("carried", "linked"), ("words", "clause"): ("carried", "@clause_basis"),
    ("words", "head"): ("carried", "linked"), ("words", "head_basis"): ("carried", "derived"),
    ("words", "rel"): ("carried", "linked"), ("words", "rel_shared"): ("carried", "linked"),
    ("words", "from_t"): ("carried", "linked"),
    ("pieces", "head_t"): ("carried", "linked"), ("pieces", "head_n"): ("carried", "linked"),
    ("pieces", "head_basis"): ("carried", "linked"), ("pieces", "rel"): ("carried", "linked"),
    ("pieces", "who"): ("carried", "@who_basis"), ("pieces", "who_from"): ("carried", "linked"),
    ("clauses", "clause"): ("carried", "derived"), ("clauses", "first"): ("carried", "derived"),
    ("clauses", "last"): ("carried", "derived"), ("clauses", "gaps"): ("carried", "derived"),
    ("clauses", "words"): ("carried", "derived"), ("clauses", "shared"): ("own", "derived"),
    ("clauses", "marks_model"): ("own", "model"), ("clauses", "quote_model"): ("carried", "model"),
    ("clauses", "speaker_model"): ("carried", "model"), ("clauses", "addressee_model"): ("carried", "model"),
    ("constituents", "class"): ("own", "@own_basis"), ("constituents", "prep"): ("own", "@own_basis"),
    ("constituents", "ref_form"): ("own", "@own_basis"), ("constituents", "clause"): ("carried", "derived"),
    ("constituents", "ord"): ("carried", "derived"), ("constituents", "first"): ("carried", "derived"),
    ("constituents", "last"): ("carried", "derived"),
    ("added", "kind"): ("own", "@own_basis"), ("added", "form"): ("own", "@own_basis"),
    ("added", "clause"): ("carried", "derived"),
    ("passages", "passage"): ("own", "derived"), ("passages", "first_clause"): ("own", "derived"),
    ("passages", "last_clause"): ("own", "derived"), ("passages", "clauses"): ("own", "derived"),
    ("passages", "crossing"): ("own", "derived"),
}
DEFAULT = {"words": ("own", "given"), "pieces": ("own", "@basis"), "clauses": ("carried", "linked"),
           "constituents": ("carried", "linked"), "added": ("carried", "linked"), "who_account": ("own", "@basis"),
           "passages": ("carried", "linked"), "links": ("carried", "@basis"), "link_account": ("own", "derived")}
METAC = ("clause_basis", "who_basis", "speech_basis", "sem_role_basis", "own_basis", "basis")
GIV = {("pieces", "t"), ("pieces", "n"), ("pieces", "text"), ("clauses", "book"), ("clauses", "chapter"),
       ("clauses", "verse"), ("who_account", "t"), ("who_account", "n")}
SRCC = {("pieces", x) for x in EMPTY["pieces"]} | {("words", "after")} | {("clauses", x) for x in EMPTY["clauses"]} | \
    {("constituents", "frame_role")}


def reason_empty(tb, col, r):
    if tb == "words" and col in ("head", "head_basis", "rel", "rel_shared", "from_t"):
        return "not_one_to_one"
    if tb == "pieces" and col in ("head_t", "head_n", "head_basis", "rel"):
        return "not_stem" if r["kind"] != "stem" else "not_one_to_one"
    if tb == "words" and col in ("clause", "clause_basis", "sentence"):
        return "unplaced"
    if (tb, col) in (("constituents", "head"), ("added", "antecedent"), ("clauses", "pred")):
        return "not_linked"
    if (tb, col) == ("pieces", "class"):
        return "tagger_dash"
    return "none"


def one(tb, col, r):
    v = r[col]
    if (tb, col) in SRCC:
        return ("not_carried", "", "greek_only" if tb in ("clauses", "constituents") else "src")
    if nul(v) or (tb, col) == ("clauses", "pred") and not v:
        return ("not_carried", "", reason_empty(tb, col, r))
    if col in METAC:
        return ("own", "derived", "")
    if (tb, col) in GIV:
        return ("own", "given", "")
    if tb == "added" and col in ("person", "number", "gender"):
        return ("own", r["own_basis"], "") if r["form"] == "ending" else ("carried", "linked", "")
    if tb == "who_account" and col in ("state", "reason"):
        x = r["from_t"] is not None and r["state"] not in ("participant", "generic", "not_referring", "unresolved", "no_row")
        return ("carried", "linked", "") if x else ("own", r["basis"], "")
    if tb == "who_account" and col == "from_t":
        return ("carried", "linked", "")
    st, bs = RULES.get((tb, col), DEFAULT[tb])
    return (st, r[bs[1:]] if bs.startswith("@") else bs, "")


def account_check(R, E, pk, ca):
    G = E.G
    tabs = {"words": E.w, "pieces": E.p, "clauses": E.c, "constituents": E.k, "added": E.a, "who_account": E.wa,
            "passages": E.ps, "links": E.l, "link_account": E.la}
    acc = C.Counter()
    for tb, rows in tabs.items():
        for col in (rows[0].keys() if rows else []):
            for r in rows:
                if (tb, col) == ("clauses", "marks"):
                    m = json.loads(r[col])
                    for key in ("relation", "time", "aspect", "line_kind", "mood", "force", "polarity", "time_abs",
                                "connective", "negator") + FORMKEYS:
                        s = (("own", "derived", "") if key in ("connective", "negator") else ("carried", "derived" if key == "time_abs" else "linked", "")) \
                            if key in m else ("not_carried", "", "greek_form_key" if key in FORMKEYS else "none")
                        acc[(tb, "marks." + key) + s] += 1
                elif (tb, col) == ("pieces", "marks"):
                    m = json.loads(r[col])
                    for key in ("type", "stem", "person", "gender", "number", "state"):
                        acc[(tb, "marks." + key) + (("own", r["basis"], "") if key in m else ("not_carried", "", "none"))] += 1
                else:
                    acc[(tb, col) + one(tb, col, r)] += 1
    # the Greek side
    for r in G.Cl:
        k, on = r["clause"], r["clause"] in E.keys
        for key in json.loads(r["marks"]):
            if key not in ("connective", "negator"):
                acc[("grc/clauses", "marks." + key) + (("not_carried", "", "greek_form_key") if key in FORMKEYS else
                                                      ("carried", "linked", "") if on else ("not_carried", "", "empty_clause"))] += 1
        for col in ("role", "quote", "speaker", "addressee", "quote_model", "speaker_model", "addressee_model"):
            if not nul(r[col]):
                acc[("grc/clauses", col) + (("carried", "model" if col.endswith("model") else "linked", "") if on else ("not_carried", "", "empty_clause"))] += 1
        for col in ("via", "rule", "pattern", "role_wrapped", "line", "subject_model"):
            if not nul(r[col]):
                acc[("grc/clauses", col, "not_carried", "", "greek_only")] += 1
        acc[("grc/clauses", "clause") + (("carried", "derived", "") if on else ("not_carried", "", "empty_clause"))] += 1
    cpred = {r["from_clause"]: r["pred"] for r in E.c}
    for r in G.Cl:
        if r["pred"]:
            k = r["clause"]
            s = ("not_carried", "", "empty_clause") if k not in E.keys else (("carried", "linked", "") if cpred[k] else ("not_carried", "", "not_linked"))
            acc[("grc/clauses", "pred") + s] += 1
    for g in G.W:
        acc[("grc/words", "head") + (("carried", "linked", "") if g in E.o2o_g else ("not_carried", "", "not_linked" if g not in E.down else "not_one_to_one"))] += 1
    got = set()
    for r in E.p:
        if r["who_from"] is not None:
            got.add(r["who_from"])
            if E.Wv.get((r["t"], r["n"]), ("", ""))[1] == "a":
                got |= {x for x in E.up_[r["t"]] if G.P[x]["who"] == r["who"]}
    for g, p in G.P.items():
        if p["who"]:
            if g in got:
                s = ("carried", "linked", "")
            elif g in E.down:
                s = ("not_carried", "", "two_values" if any(len({G.P[x]["who"] for x in E.up_[t] if G.P[x]["who"]}) > 1 for t in E.down[g]) else "stem_class")
            else:
                s = ("not_carried", "", "no_host_suffix" if p["class"] == "pron" else "not_linked")
            acc[("grc/pieces", "who") + s] += 1
    kr = {v: k for k, v in E.keys.items()}
    took = {(kr[r["clause"]], r["from_ord"]): r for r in E.k}
    for r in G.K:
        x = took.get((r["clause"], r["ord"]))
        why = "empty_clause" if r["clause"] not in E.keys else "not_linked"
        for col in ("role", "sem_role", "ref_status", "head"):
            if nul(r[col]):
                continue
            ok = x is not None and (col != "head" or x["head"] is not None)
            acc[("grc/constituents", col) + (("carried", "linked", "") if ok else ("not_carried", "", why))] += 1
    tk = {(r["from_clause"], r["from_t"], r["role"]) for r in E.a}
    for r in G.A:
        on = (r["clause"], r["verb"], r["role"]) in tk
        c = sorted(E.down.get(r["verb"], ()))
        v = [t for t in c if E.Pd[(t, kinds_stem(E, t))]["class"] == "verb"]
        vb = (v or c or [None])[0]
        why = "not_linked" if not c else ("unplaced" if vb not in E.pl else "key_taken")
        for col in ("role", "where", "who", "who_reason", "antecedent"):
            if not nul(r[col]):
                acc[("grc/added", col) + (("carried", "linked", "") if on else ("not_carried", "", why))] += 1
    used = {r["from_t"] for r in E.wa if r["from_t"] is not None}
    for g in G.WA:
        acc[("grc/who_account", "state") + (("carried", "linked", "") if g in used else ("not_carried", "", "not_linked"))] += 1
    fp = {r["from_passage"] for r in E.ps}
    for r in G.PS:
        acc[("grc/passages", "passage") + (("carried", "linked", "") if r["passage"] in fp else ("not_carried", "", "not_linked"))] += 1
    acc = C.Counter({k: v for k, v in acc.items() if v})
    have = C.Counter()
    for r in TS(os.path.join(E.d, "carry_account.tsv")):
        have[(r["table"], r["column"], r["state"], r["basis"], r["reason"])] += int(r["count"])
    R.check(f"{E.ed} files (1.7): carry_account.tsv recomputed row by row by D44", acc == have,
            f"{len(have):,} rows; differ {len(set(acc.items()) ^ set(have.items()))}")
    sums = C.defaultdict(int)
    for k, n in have.items():
        sums[(k[0], k[1])] += n
    nrows = {tb: len(rows) for tb, rows in tabs.items()}
    gtot = {"grc/clauses": len(G.Cl), "grc/words": len(G.W), "grc/who_account": len(G.WA), "grc/passages": len(G.PS)}
    badsum = []
    for (tb, col), n in sums.items():
        if tb in nrows and n != nrows[tb]:
            badsum.append((tb, col, n))
        if tb in gtot and col in ("clause", "head", "state", "passage") and n != gtot[tb]:
            badsum.append((tb, col, n))
    miss = [(tb, col) for tb, rows in tabs.items() for col in (rows[0].keys() if rows else []) if
            (tb, col) not in sums and not (tb, col) in (("clauses", "marks"), ("pieces", "marks"))]
    gfrom = {"grc/clauses": {c: sum(1 for r in G.Cl if r[c]) for c in ("role", "quote", "speaker", "addressee", "pred")},
             "grc/constituents": {c: sum(1 for r in G.K if not nul(r[c])) for c in ("role", "sem_role", "ref_status", "head")},
             "grc/added": {c: sum(1 for r in G.A if not nul(r[c])) for c in ("role", "where", "who", "who_reason", "antecedent")},
             "grc/pieces": {"who": sum(1 for p in G.P.values() if p["who"])}}
    for tb, cs in gfrom.items():
        for c, n in cs.items():
            if sums.get((tb, c), 0) != n:
                badsum.append((tb, c, sums.get((tb, c), 0), n))
    R.check(f"{E.ed} files (1.7): for every table and column the account adds up to the table's rows, and on the Greek "
            "side to the Greek rows the column could be carried from", not badsum and not miss, (badsum[:3], miss[:3]))


# ---- D43 files, statements, strict view --------------------------------------------------------------------------------

def files_check(R, E, lexicon, ca, c2h):
    ed, G = E.ed, E.G
    form = (lambda s: unicodedata.normalize("NFC", "".join(c for c in s if ord(c) not in set(range(0x0591, 0x05B0)) | {0x05BD, 0x05C4, 0x05C5}))) \
        if ed == "heb_scg" else (lambda s: unicodedata.normalize("NFC", s))
    per = C.defaultdict(list)
    for r in E.p:
        per[r["lexeme"]].append(r)
    want = []
    for lx in sorted(per):
        ps = per[lx]
        dv = [p for p in ps if p["basis"] == "derived"] or ps
        cc = C.Counter(p["class"] for p in dv)
        top = max(cc.values())
        f0 = min((p["t"], p["n"]) for p in dv)
        L = lexicon.get(lx, {})
        want.append({"lexeme": lx, "lemma": L.get("lemma", ""), "strong": L.get("strong", ""),
                     "class": min(k for k, v in cc.items() if v == top),
                     "count": str(sum(1 for p in ps if p["basis"] == "derived")),
                     "forms": str(len({form(p["text"]) for p in dv})), "books": str(len({E.W[p["t"]]["book"] for p in dv})),
                     "senses": "", "domains": "", "first": f"{f0[0]}.{f0[1]}",
                     "count_model": str(sum(1 for p in ps if p["basis"] == "model"))})
    lx = TS(os.path.join(E.d, "lexemes.tsv"))
    R.check(f"{ed} files (1.7): lexemes.tsv recomputed by D43", lx == want, len(lx))
    # participants
    sw, mw, nm = C.defaultdict(set), C.defaultdict(set), C.defaultdict(C.Counter)
    op = {(t, i + 1): p for t in E.ts for i, p in enumerate(E.op[t])}
    for r in E.p:
        for e in r["who"].split():
            (mw if r["basis"] == "model" else sw)[e].add(r["t"])
            if r["basis"] != "model" and r["kind"] == "stem" and r["class"] in ("noun", "adj"):
                l = unicodedata.normalize("NFC", op[(r["t"], r["n"])]["lemma"] or "")
                if l and l != "הַ":
                    nm[e][l] += 1
    gp = {r["ent"]: r for r in TS(os.path.join(E.b, "grc", "participants.tsv"))}
    strict_e = set(sw) | {e for r in E.c for c in ("speaker", "addressee") for e in r[c].split()} | {e for r in E.a for e in r["who"].split()}
    wp = []
    for e in sorted({r["ent"] for r in E.pt}):
        n = ""
        if e not in ca and nm.get(e):
            top = max(nm[e].values())
            n = min(k for k, v in nm[e].items() if v == top)
        wp.append({"ent": e, "type": c2h[("ent_type", e.split(":")[0])], "name": n, "name_basis": "derived" if n else "",
                   "sex": gp[e]["sex"], "words": str(len(sw.get(e, ()))), "words_model": str(len(mw.get(e, ()))),
                   "ent_basis": "given" if e in strict_e else "model"})
    R.check(f"{ed} files (1.7): participants.tsv recomputed by D43 (type the hbo term, name from the edition's own "
            "stem pieces)", wp == E.pt, len(wp))
    # facts
    fa = T(os.path.join(E.d, "facts.parquet"))
    hc = C.Counter((r["lexeme"], r["basis"], r["class"]) for r in E.p)
    tot = C.Counter((r["lexeme"], r["basis"]) for r in E.p)
    wf = [("has_class", a, cl, b, n, n / tot[(a, b)]) for (a, b, cl), n in sorted(hc.items(), key=lambda x: (x[0][0], x[0][1], x[0][2]))]
    given = {r["ent"] for r in E.pt if r["ent_basis"] == "given"}
    kin = [r for r in G.F if r["relation"] in ("father", "mother", "offspring", "sibling", "partner", "tribe", "group_origin")
           and r["subject"] in given and r["object"] in given]
    rn, lt = C.Counter(), C.Counter()
    for t in E.ts:
        st = E.Pd[(t, kinds_stem(E, t))]
        for g in E.up_.get(t, ()):
            rn[(st["lexeme"], G.P[g]["lexeme"], "model" if st["basis"] == "model" else "linked")] += 1
            lt[st["lexeme"]] += 1
    got_hc = [(r["relation"], r["subject"], r["object"], r["kind"], r["count"], r["share"]) for r in fa if r["relation"] == "has_class"]
    got_rn = sorted((r["subject"], r["object"], r["kind"], r["count"], r["share"]) for r in fa if r["relation"] == "renders")
    got_kin = [r for r in fa if r["relation"] not in ("has_class", "renders")]
    ok = got_hc == wf and got_rn == sorted((a, b, k, n, n / lt[a]) for (a, b, k), n in rn.items()) and got_kin == kin
    R.check(f"{ed} files (1.7): facts.parquet recomputed by D43 (has_class, kin between given participants, renders)",
            ok, f"{len(fa):,} rows: has_class {len(got_hc):,}, kin {len(got_kin):,}, renders {len(got_rn):,}")
    for f in ("terms.tsv", "terms-notes.md"):
        R.check(f"{ed} files (1.7): {f} equals the master", H(os.path.join(E.d, f)) == H(os.path.join(E.b, "hbo", f)) and
                (f != "terms.tsv" or H(os.path.join(E.d, f)) == H(TERMS)))
    # differ: recomputed in run(); statements over the strict view
    statements_check(R, E, lx, form)


def strict_view(E):
    """4.15: model pieces lose kind, lexeme, class, marks, shared; values whose _basis is model are emptied; model rows go."""
    P = []
    for r in E.p:
        x = dict(r)
        if r["basis"] == "model":
            for c in ("kind", "lexeme", "class", "marks", "shared"):
                x[c] = ""
        if r["who_basis"] == "model":
            x["who"] = x["who_basis"] = ""
            x["who_from"] = None
        P.append(x)
    K = []
    for r in E.k:
        x = dict(r)
        if r["own_basis"] == "model":
            x["class"] = x["prep"] = x["ref_form"] = ""
        K.append(x)
    A = []
    for r in E.a:
        x = dict(r)
        if r["own_basis"] == "model":
            for c in ("kind", "form"):
                x[c] = ""
            if r["form"] == "ending":
                x["person"] = x["number"] = x["gender"] = ""
        A.append(x)
    Cl = [dict(r, marks_model=None, quote_model=None, speaker_model=None, addressee_model=None) for r in E.c]
    WA = [r for r in E.wa if r["basis"] != "model"]
    L = [r for r in E.l if r["basis"] != "model"]
    return {"pieces": P, "constituents": K, "added": A, "clauses": Cl, "who_account": WA, "links": L}


def statements_check(R, E, lexrows, form):
    S = strict_view(E)
    model_left = sum(1 for r in S["pieces"] if r["basis"] == "model" and (r["lexeme"] or r["marks"] or r["who"])) + \
        sum(1 for r in S["constituents"] if r["own_basis"] == "model" and (r["class"] or r["prep"] or r["ref_form"])) + \
        sum(1 for r in S["who_account"] if r["basis"] == "model") + sum(1 for r in S["links"] if r["basis"] == "model")
    R.check(f"{E.ed} strict view (1.7): built from the edition's own files, it holds no value of basis model", model_left == 0, model_left)
    same = all(a == b for a, b in zip(S["pieces"], E.p) if a["basis"] != "model" and a["who_basis"] != "model")
    R.check(f"{E.ed} strict view (1.7): equal value by value to the strict columns and rows", same)
    st = {(r["t"], r["n"]): r for r in S["pieces"] if r["basis"] != "model"}
    stem = {t: r for (t, n), r in st.items() if r["kind"] == "stem"}
    hw = {r["t"]: r for r in E.w}
    W = {}
    fg, pg = C.defaultdict(list), C.defaultdict(list)
    for (t, n), r in sorted(st.items()):
        fg[(r["lexeme"], r["marks"], form(r["text"]))].append(f"{t}.{n}")
        pg[(r["class"], r["marks"])].append((f"{t}.{n}", r["lexeme"], form(r["text"])))
    W["forms"] = [(k[0], k[1], k[2], len(v), 0, " ".join(v[:3])) for k, v in sorted(fg.items())]
    W["paradigms"] = [(k[0], k[1], len({x[1] for x in v}), len({x[2] for x in v}), len(v), 0, " ".join(x[0] for x in v[:3]))
                      for k, v in sorted(pg.items())]
    lc = {r["lexeme"]: r["class"] for r in lexrows if int(r["count"])}
    ncl = C.Counter(lc.values())
    mk = C.defaultdict(list)
    for (t, n), r in sorted(st.items()):
        if r["kind"] != "stem" and t in stem:
            m = json.loads(r["marks"])
            key = r["lexeme"]
            if r["kind"] == "suffix" and r["class"] == "pron" and all(c in m for c in ("person", "gender", "number")):
                key = f"sfx:hbo:{m['person']}.{m['gender']}.{m['number']}"
            mk[(key, r["kind"])].append(((t, n), json.loads(stem[t]["marks"])))
        if r["kind"] == "stem" and r["lexeme"] in lc and ncl[lc[r["lexeme"]]] <= 40:
            h = hw[t]["head"]
            if h and h in stem:
                mk[(r["lexeme"], "word")].append(((t, n), json.loads(stem[h]["marks"])))
    mr = []
    for (m, kind), its in mk.items():
        cats = C.defaultdict(list)
        for o, mm in its:
            for c, v in mm.items():
                cats[c].append((o, v))
        for c, xs in cats.items():
            vc = C.Counter(v for _, v in xs)
            v, n = sorted(vc.items(), key=lambda kv: (-kv[1], kv[0]))[0]
            if len(xs) >= 20 and n >= 0.95 * len(xs):
                pro = sorted(o for o, x in xs if x == v)
                mr.append((m, kind, c, v, n, len(xs) - n, " ".join(f"{a}.{b}" for a, b in pro[:3])))
    W["markers"] = sorted(mr)
    og, ag, pr = C.defaultdict(lambda: [0, 0, []]), C.defaultdict(lambda: [0, 0, 0, []]), C.defaultdict(list)
    for t in E.ts:
        h = hw[t]["head"]
        if not h or t not in stem or h not in stem:
            continue
        rel = hw[t]["rel"]
        dm, hm = json.loads(stem[t]["marks"]), json.loads(stem[h]["marks"])
        g = og[(rel, stem[h]["class"], stem[t]["class"])]
        g[0 if t < h else 1] += 1
        g[2].append((0 if t < h else 1, t))
        for cat in ("gender", "number", "person", "case", "state"):
            a, b = dm.get(cat), hm.get(cat)
            if a is None and b is None:
                continue
            x = ag[(rel, cat)]
            if a is None or b is None or a != b and (a in ("c", "b", "x") or b in ("c", "b", "x")):
                x[2] += 1
            elif a == b:
                x[0] += 1
                x[3].append(t)
            else:
                x[1] += 1
        pr[(stem[h]["lexeme"], rel, stem[t]["lexeme"])].append(t)
    W["orders"] = [(k[0], k[1], k[2], v[0], v[1], max(v[0], v[1]), min(v[0], v[1]),
                    " ".join(str(t) for t in sorted(t for s, t in v[2] if s == (0 if v[0] >= v[1] else 1))[:3]))
                   for k, v in sorted(og.items())]
    W["agreement"] = [(k[0], k[1], v[0], v[1], v[2], v[0], v[1], " ".join(str(t) for t in sorted(v[3])[:3]))
                      for k, v in sorted(ag.items()) if v[0] + v[1]]
    W["pairs"] = [(k[0], k[1], k[2], len(v), 0, " ".join(str(t) for t in sorted(v)[:3])) for k, v in sorted(pr.items()) if len(v) >= 2]
    cons = C.defaultdict(list)
    for r in S["constituents"]:
        cons[r["clause"]].append(r)
    fr = C.defaultdict(list)
    for i, r in enumerate(S["clauses"]):
        p = r["pred"]
        if r["pred_kind"] != "v" or not p or p not in stem:
            continue
        cs = sorted(cons.get(r["clause"], []), key=lambda x: x["ord"])
        v = [x for x in cs if x["role"] == "v" and x["head"] == p]
        roles = sorted((f"pp:{x['prep']}" if x["prep"] else "pp") if x["role"] == "pp" else x["role"] for x in cs if not v or x is not v[0])
        m = json.loads(stem[p]["marks"])
        fr[(stem[p]["lexeme"], m.get("stem", ""), " ".join(roles))].append(((r["first"], i), r["clause"]))
    W["frames"] = [(k[0], k[1], k[2], len(v), 0, " ".join(c for _, c in sorted(v)[:3])) for k, v in sorted(fr.items())]
    cols = {"forms": ("lexeme", "marks", "form", "count", "against", "places"),
            "paradigms": ("class", "marks", "lexemes", "forms", "count", "against", "places"),
            "markers": ("marker", "kind", "category", "value", "count", "against", "places"),
            "orders": ("rel", "head_class", "dep_class", "before", "after", "count", "against", "places"),
            "agreement": ("rel", "category", "agree", "differ", "n_a", "count", "against", "places"),
            "pairs": ("head", "rel", "dep", "count", "against", "places"),
            "frames": ("lexeme", "stem", "frame", "count", "against", "places")}
    bad = []
    tot_against = 0
    for name, cl in cols.items():
        got = T(os.path.join(E.d, f"{name}.parquet"))
        g2 = sorted(tuple(r[c] for c in cl) for r in got) if name == "markers" else [tuple(r[c] for c in cl) for r in got]
        ids = [r["id"] for r in got] == [f"{name}:{i}" for i in range(1, len(got) + 1)]
        if g2 != W[name] or not ids:
            bad.append(name)
        tot_against += sum(r["against"] for r in got)
    for name in ("constructions", "clause_links"):
        if pq.read_metadata(os.path.join(E.d, f"{name}.parquet")).num_rows:
            bad.append(name)
    exc = pq.read_metadata(os.path.join(E.d, "exceptions.parquet")).num_rows
    R.check(f"{E.ed} strict view (1.7): every statement table equals the one recomputed on the strict view "
            "(constructions, clause_links: no row)", not bad, bad)
    R.check(f"{E.ed} files (1.7): exceptions.parquet = the sum of against", exc == tot_against, f"{exc:,}")
    prof = TS(os.path.join(E.d, "profile.tsv"))
    sid = set()
    for name in cols:
        sid |= {r["id"] for r in T(os.path.join(E.d, f"{name}.parquet"))}
    okp = len(prof) == 195 and all(all(x in sid for x in r["statement"].split()) or r["statement"].startswith("categories.toml") for r in prof if r["value"] != "?")
    R.check(f"{E.ed} files (1.7): profile.tsv has the 195 rows, every answer's evidence a statement of the strict tables "
            "(the rules of 4.10 are examples_shared11's, read by stage 20's check)", okp,
            sum(1 for r in prof if r["value"] != "?"))


def differ_check(R, eds):
    sets = {}
    for ed, E in eds.items():
        d = {}
        for g, ss in E.down.items():
            x = {}
            for s in ss:
                l = {p["lexeme"] for p in E.parts_of[s] if p["class"] in ("noun", "verb", "adj", "adv")}
                if l:
                    x[s] = l
            if x:
                d[g] = x
        sets[ed] = d
    want = {ed: [] for ed in eds}
    for g in sorted(set(sets["heb_mod"]) & set(sets["heb_scg"])):
        a, b = sets["heb_mod"][g], sets["heb_scg"][g]
        A, B = set().union(*a.values()), set().union(*b.values())
        if A == B:
            continue
        st = "overlap" if A & B else "disjoint"
        for ed, me, ot, oe in (("heb_mod", a, b, "heb_scg"), ("heb_scg", b, a, "heb_mod")):
            for s in sorted(me):
                for o in sorted(ot):
                    m = any(p["basis"] == "model" for p in eds[ed].parts_of[s]) or any(p["basis"] == "model" for p in eds[oe].parts_of[o])
                    want[ed].append({"from_t": g, "t": s, "lexemes": json.dumps(sorted(me[s]), ensure_ascii=False, separators=(",", ":")),
                                     "other": oe, "other_t": o,
                                     "other_lexemes": json.dumps(sorted(ot[o]), ensure_ascii=False, separators=(",", ":")),
                                     "state": st, "basis": "model" if m else "derived"})
    got = {ed: T(os.path.join(E.d, "differ.parquet")) for ed, E in eds.items()}
    R.check("tan differ (1.7): differ.parquet recomputed by D44 in both editions, the same Greek pieces in both files",
            all(got[e] == want[e] for e in eds) and {r["from_t"] for r in got["heb_mod"]} == {r["from_t"] for r in got["heb_scg"]},
            ", ".join(f"{e} {len(got[e]):,} rows" for e in eds))
    c = C.Counter((r["state"], r["basis"]) for r in got["heb_mod"])
    R.info("tan differ (1.7): heb_mod rows by state and basis", {f"{a} {b}": n for (a, b), n in sorted(c.items())})


def script_check(R, b, ed):
    d = os.path.join(b, ed)
    greek, where = 0, []
    for f in sorted(os.listdir(d)):
        p = os.path.join(d, f)
        if f in ("terms.tsv", "terms-notes.md"):
            continue          # D43: the master, copied unchanged (its grc column holds the Greek terms)
        if f.endswith(".parquet"):
            rows = T(p)
            for r in rows:
                for c, v in r.items():
                    if isinstance(v, str) and GREEK.search(v):
                        if f == "facts.parquet" and c == "object" and r["relation"] == "renders":
                            continue
                        greek += 1
                        if len(where) < 5:
                            where.append(f"{f}:{c}")
        elif f.endswith(".tsv"):
            for r in TS(p):
                for c, v in r.items():
                    if GREEK.search(v or ""):
                        greek += 1
                        if len(where) < 5:
                            where.append(f"{f}:{c}")
    R.check(f"{ed} no Greek (1.7): no string value in an edition table is in Greek script (renders objects aside)",
            greek == 0, f"{greek} {where}")
    gv = gloss_vocab()
    cat = tomllib.load(open(os.path.join(d, "categories.toml"), "rb"))
    declared = set()

    def walkc(x):
        if isinstance(x, dict):
            if "code" in x:
                declared.add(str(x["code"]))
            for v in x.values():
                walkc(v)
        elif isinstance(x, list):
            for v in x:
                walkc(v)
    walkc(cat)
    eng = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".parquet") and f != "facts.parquet":
            for r in T(os.path.join(d, f)):
                for c, v in r.items():
                    if isinstance(v, str) and v in gv and v not in declared:
                        eng.append(f"{f}:{c}={v}")
    hebcols = [(r["text"], r["t"]) for r in T(os.path.join(d, "words.parquet"))]
    nonheb = [t for x, t in hebcols if not heb_ok(re.sub(r"[־׀׃׳״.,;:!?'\"()\-\[\]]", "", x))]
    R.check(f"{ed} no English (1.7): no string value equals a word of the gloss vocabulary unless a declared code; "
            "every text in Hebrew script or punctuation", not eng and not nonheb, (eng[:5], nonheb[:5]))


_GV = None


def gloss_vocab():
    global _GV
    if _GV is None:
        import validate_examples as V
        _GV = set(V._s10_gloss_vocab()[0])
    return _GV


def attribution_check(R, b, ed):
    d = os.path.join(b, ed)
    s = json.load(open(os.path.join(d, "sources.json"), encoding="utf-8"))
    cat = open(os.path.join(d, "categories.toml"), encoding="utf-8").read()
    m = s.get("model", {})
    ok = "hebrew-nt-analysis" in m and "M6" in m["hebrew-nt-analysis"].get("basis", "") and "[model.M6]" in cat and \
        any("reviewed" in k for k in m) and "[model.M4]" in cat
    if ed == "heb_scg":
        ok = ok and any("bridge" in k for k in m) and "[model.M5]" in cat
    R.check(f"{ed} model attribution (1.7): M6 named in sources.json and categories.toml for every model basis; M4 for "
            "the carried speech M columns" + ("; M5 for the model link rows" if ed == "heb_scg" else ""), ok)


CA = set()


def run(R, build, compare=None):
    global CA
    R.section("the copied folders (1.7)")
    bad, n = [], 0
    for sub in FOLDERS:
        for rel in walk(os.path.join(build, sub)):
            if rel.endswith("VALIDATION.md"):
                continue
            n += 1
            p, q = os.path.join(build, sub, rel), os.path.join(H1, sub, rel)
            if not os.path.exists(q) or H(p) != H(q):
                bad.append(f"{sub}/{rel}")
        miss = [rel for rel in walk(os.path.join(H1, sub)) if not os.path.exists(os.path.join(build, sub, rel))]
        bad += [f"{sub}/{x} (missing)" for x in miss]
    R.check("tan the copied folders (1.7): every file of hbo, arc, grc, other, lexicon has the sha256 of h1's "
            "(VALIDATION.md aside)", not bad, f"{n} files; {bad[:5]}")
    G = G_(build)
    g2c, c2h, h2c = terms()
    CA = catch()
    lexicon = {r["lexeme"]: r for r in TS(os.path.join(build, "lexicon", "lexemes.tsv"))}
    eds = {}
    about = {}
    for ed in EDS:
        R.section(f"{ed} (1.7)")
        ab = {}
        E = check_edition(R, build, ed, G, g2c, c2h, h2c, CA, ab)
        files_check(R, E, lexicon, CA, c2h)
        script_check(R, build, ed)
        attribution_check(R, build, ed)
        eds[ed] = E
        for k, v in ab.items():
            R.info(f"{ed} about, counted exactly: {k}", v)
    differ_check(R, eds)
    if compare:
        R.section("rebuild (1.7)")
        other = os.path.join(os.path.dirname(os.path.normpath(build)), compare) if not os.path.isabs(compare) else compare
        for sub in FOLDERS + EDS:
            a, b2 = os.path.join(build, sub), os.path.join(other, sub)
            fs = [f for f in walk(a) if not f.endswith("VALIDATION.md")]
            diff = [f for f in fs if not os.path.exists(os.path.join(b2, f)) or H(os.path.join(a, f)) != H(os.path.join(b2, f))]
            extra = [f for f in walk(b2) if not f.endswith("VALIDATION.md") and f not in fs] if os.path.exists(b2) else ["(missing)"]
            R.check(f"tan rebuild (1.7): every file of {os.path.basename(build)}/{sub} has the same sha256 in {compare}",
                    not diff and not extra, f"{len(fs)} files; differ {diff[:3]} {extra[:3]}")
        gb = os.path.join(other, "cache", "glossed")
        fs = sorted(os.listdir(GLOSSED)) if os.path.isdir(GLOSSED) else []
        diff = [f for f in fs if not os.path.exists(os.path.join(gb, f)) or H(os.path.join(GLOSSED, f)) != H(os.path.join(gb, f))]
        R.check(f"tan rebuild (1.7): the {len(fs)} sheets of glossed-i1/ equal {compare}/cache/glossed/", fs and not diff, diff)
