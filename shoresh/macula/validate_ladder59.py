"""Stage 59 checks of the Hebrew ladder validator (SPEC-ladder 6.6): pilot-2 of the level switches.

Called by validate_ladder.py --upto 59. Imports nothing from the builders: every rule is recomputed here with its own
code from k1, the gloss bank and the pilot-2 tables.
"""
import csv
import json
import random
import re
import subprocess
import sys
import unicodedata as ud
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

MAC = Path(__file__).resolve().parent
DATA = MAC / "data"
K1 = DATA / "source-examples" / "k1"
I1 = DATA / "source-examples" / "i1"
GLOSS = DATA / "hebrew-ladder" / "pilot-1" / "banks" / "gloss.parquet"
P1 = DATA / "hebrew-levels" / "pilot-1"
SEED = "ladder-2026-11-24"
LEVELS = {"l0": ("hbo", "heb_mod", "heb_scg"), "r": ("hbo", "heb_mod", "heb_scg"), "zr_r": ("hbo",), "z_r_a": ("hbo",)}
SW = {"l0": "", "r": "r", "zr_r": "vr", "z_r_a": "vra"}
FINITE = {"qatal", "wayyiqtol", "yiqtol", "weqatal", "imperative", "jussive", "cohortative"}
INF = {"infinitive_construct", "infinitive_absolute"}
PART = {"participle_active", "participle_passive"}
KINDS4 = ("person:", "group:", "deity:", "fauna:")
CAUS = {"hiphil", "haphel", "aphel", "shaphel"}
PASSIVE = {"niphal", "pual", "hophal"}
# the rule mends of 2026-11-25 (OPEN-ladder F.1), recomputed here with the validator's own code
REL_VERB = ("NpRelp", "Relp", "NpCL")
NOT_ACTIVE = {"niphal", "pual", "hophal", "qal_passive", "hithpael", "hithpolel", "hithpalpel", "nithpael", "pulal",
              "polal", "poal", "polpal"}
MAJESTY = {"0430", "0136", "0113", "1167"}
DIVINE = {"3068", "0430", "0410"}
V_COMMON = 100
EXPECT = {"hbo": (1248, 13537), "heb_mod": (677, 8892), "heb_scg": (678, 9397)}
KEEP = set(range(0x05B0, 0x05BD)) | {0x05C1, 0x05C2, 0x05C7}
LATIN = re.compile(r"[A-Za-z]")


def where(book, ch):
    if book in ("JON", "RUT", "MRK"): return book
    if book == "PSA" and 1 <= ch <= 41: return "PSA1-41"
    if book == "ISA" and 40 <= ch <= 55: return "ISA40-55"
    if book == "GEN" and 22 <= ch <= 25: return "GEN22-25"
    return None


def closed(book, ch):
    return book in ("RUT", "JON") or (book, ch) in {("GEN", 22), ("LUK", 1), ("LUK", 2), ("LUK", 15), ("PHP", 3), ("ACT", 1), ("MAT", 21)}


def ents(s):
    return (s or "").split()


def g_ok(a, b):
    if not a or not b: return not a
    return a == b or "c" in (a, b) or "b" in (a, b)


def letters_cons(s):
    return "".join(c for c in ud.normalize("NFD", s or "") if "א" <= c <= "ת")


def fin(s):
    return letters_cons(s).translate(str.maketrans("ךםןףץ", "כמנפצ"))


def own_point(s):
    out = []
    for ch in ud.normalize("NFD", s or ""):
        if "א" <= ch <= "ת" or ord(ch) in KEEP: out.append(ch)
        elif ud.category(ch) == "Mn": pass
        else: out.append(" ")
    return " ".join("".join(out).split())


def line_form(raw, form):
    out = []
    for ch in ud.normalize("NFD", raw):
        if "א" <= ch <= "ת": out.append(ch)
        elif form == "point" and ord(ch) in KEEP: out.append(ch)
        elif ud.category(ch) == "Mn": pass
        else: out.append(" ")
    return " ".join("".join(out).split())


def tsv(p):
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


class Src:
    """One k1 part as the checks read it."""

    def __init__(self, name):
        self.name = name
        self.w = {r["t"]: r for r in pq.read_table(K1 / name / "words.parquet", columns=[
            "t", "id", "book", "chapter", "verse", "w", "text", "after", "clause", "head", "rel"]).to_pylist()}
        for r in self.w.values():
            r["rel0"] = (r["rel"] or "").split(":")[0]
        self.vw = defaultdict(list)
        for t in sorted(self.w):
            r = self.w[t]; self.vw[(r["book"], r["chapter"], r["verse"])].append(t)
        have = pq.ParquetFile(K1 / name / "pieces.parquet").schema_arrow.names
        cols = [c for c in ("t", "n", "text", "kind", "lexeme", "class", "marks", "fused", "who", "who_basis", "basis") if c in have]
        self.p = defaultdict(list)
        self.pk = {}
        for r in pq.read_table(K1 / name / "pieces.parquet", columns=cols).to_pylist():
            r["m"] = json.loads(r["marks"] or "{}")
            r["basis"] = r.get("basis") or "given"
            self.p[r["t"]].append(r)
            self.pk[(r["t"], r["n"])] = r
        cl = pq.read_table(K1 / name / "clauses.parquet", columns=["clause", "first"]).to_pylist()
        order = sorted((c["first"], i, c["clause"]) for i, c in enumerate(cl))
        self.corder = [x[2] for x in order]
        self.crank = {c: i for i, c in enumerate(self.corder)}
        self.byclause = defaultdict(list)
        for t in sorted(self.w):
            if self.w[t]["clause"]: self.byclause[self.w[t]["clause"]].append(t)
        self.wa = pq.read_table(K1 / name / "who_account.parquet").to_pylist()
        self.added = pq.read_table(K1 / name / "added.parquet").to_pylist()
        self.cons = defaultdict(list)
        for r in pq.read_table(K1 / name / "constituents.parquet", columns=["clause", "frame_role"]).to_pylist():
            self.cons[r["clause"]].append(r)
        lastw = defaultdict(int)
        for r in self.w.values():
            k = (r["book"], r["chapter"], r["verse"]); lastw[k] = max(lastw[k], r["w"])
        self.lastw = lastw

    def stem(self, t):
        for q in self.p[t]:
            if q["kind"] == "stem": return q
        return None


def strict(q):
    return q["basis"] != "model" and q["who_basis"] != "model" and bool(q["who"])


class Mentions:
    """records (t, book, chapter, text, definite, number, head lexeme, head text, words)"""

    def __init__(self, S, name_lex):
        self.by = defaultdict(list)
        self.chain = defaultdict(list)          # NF2-CHAIN (OPEN-ladder 4): construct head + proper name
        ts = sorted(S.w)
        pausal = lambda w: w["w"] == S.lastw[(w["book"], w["chapter"], w["verse"])] or "֑" in w["text"]
        prop = lambda s: s["m"].get("type") == "proper" or (not s["m"].get("type") and s["lexeme"] in name_lex)
        for i, t in enumerate(ts):
            w = S.w[t]; ps = S.p[t]
            st = [q for q in ps if q["kind"] == "stem"]
            if len(st) != 1: continue
            s = st[0]
            if s["class"] != "noun" or not strict(s): continue
            if any(q["kind"] == "suffix" for q in ps) or any(q["fused"] for q in ps): continue
            if s["m"].get("state", "") == "cstr":
                if any(q["kind"] == "prefix" for q in ps) or i + 1 >= len(ts): continue
                w2 = S.w[ts[i + 1]]; ps2 = S.p[ts[i + 1]]
                if (w2["book"], w2["chapter"], w2["verse"]) != (w["book"], w["chapter"], w["verse"]) or pausal(w2): continue
                if len(ps2) != 1 or ps2[0]["kind"] != "stem" or ps2[0]["class"] != "noun" or ps2[0]["fused"]: continue
                if ps2[0]["m"].get("state", "") not in ("", "abs") or not prop(ps2[0]): continue
                for e in ents(s["who"]):
                    self.chain[e].append((t, w["book"], w["chapter"], s["text"] + ps2[0]["text"], True,
                                          s["m"].get("number", ""), s["lexeme"], s["text"], 2))
                continue
            if s["m"].get("state", "") not in ("", "abs"): continue
            if pausal(w): continue
            art = [q for q in ps if q["kind"] == "prefix" and q["class"] == "art"][-1:]
            text = "".join(q["text"] for q in art + [s])
            proper = prop(s)
            for e in ents(s["who"]):
                self.by[e].append((t, w["book"], w["chapter"], text, proper or bool(art), s["m"].get("number", ""),
                                   s["lexeme"], s["text"], 1))

    def nearest(self, ent, t, book, ch):
        same = other = None
        for r in self.by.get(ent, ()):
            if r[0] >= t: break
            if r[1] == book:
                if r[2] == ch: same = r
                elif book != "PSA": other = r
        if same is None:
            c = None
            for r in self.chain.get(ent, ()):
                if r[0] >= t: break
                if r[1] == book and r[2] == ch: c = r
            if c is not None: return c, "nf_chain"
        return (same, "nf_chapter") if same else (other, "nf_book") if other else (None, "")


def strong_of(lexeme):
    return (lexeme or "").rsplit(":", 1)[-1]


def num_bad(num, m, e):
    """NUM both ways (OPEN-ladder 3, 4)"""
    if num == "pl" and e.startswith("person:") and m[5] != "pl": return True
    return num == "sg" and m[5] == "pl" and strong_of(m[6]) not in MAJESTY


def antecedent(S, t):
    """REL: the antecedent word of the relative clause verb t (coordinated relatives followed back)"""
    if not S.w[t]["rel0"].startswith(REL_VERB): return None
    seen, h = set(), S.w[t]["head"]
    while h and h not in seen and h in S.w:
        seen.add(h); st = S.stem(h)
        if st is not None and st["class"] == "verb" and S.w[h]["rel0"].startswith(REL_VERB):
            h = S.w[h]["head"]; continue
        return h
    return None


def rel_same(S, t, e):
    h = antecedent(S, t)
    if h is None: return False
    ws = {h}
    if S.w[h]["rel0"] == "Np-Appos" and S.w[h]["head"]: ws.add(S.w[h]["head"])
    w = S.w[h]
    for x in S.vw[(w["book"], w["chapter"], w["verse"])]:
        if S.w[x]["rel0"] == "Np-Appos" and S.w[x]["head"] in ws: ws.add(x)
    return any(e in ents(q["who"]) for x in ws for q in S.p[x] if q["kind"] == "stem")


def just_before(S, t, e):
    w = S.w[t]; vs = S.vw[(w["book"], w["chapter"], w["verse"])]; i = vs.index(t)
    if i == 0 or S.w[vs[i - 1]]["clause"] == w["clause"]: return False
    st = S.stem(vs[i - 1])
    return st is not None and st["class"] == "noun" and e in ents(st["who"])


class Check59:
    def __init__(self, d, cond, say):
        self.d, self.cond, self.say = Path(d), cond, say

    # ---------------------------------------------------------------- loading
    def load(self):
        d = self.d
        self.S = {n: Src(n) for n in ("hbo", "arc", "heb_mod", "heb_scg")}
        self.lex = {r["lexeme"]: r for r in tsv(K1 / "lexicon" / "lexemes.tsv")}
        name_lex = {k for k, r in self.lex.items() if r["state"] == "name"}
        self.M = {n: Mentions(self.S[n], name_lex) for n in ("hbo", "heb_mod", "heb_scg")}
        self.name_lex = name_lex
        self.ops = pq.read_table(d / "ops.parquet").to_pylist()
        self.texts = {}
        for lv, txs in LEVELS.items():
            for tx in txs:
                base = d / "texts" / lv / tx
                self.texts[(lv, tx)] = (pq.read_table(base / "words.parquet").to_pylist(),
                                        pq.read_table(base / "pieces.parquet").to_pylist(),
                                        pq.read_table(base / "links.parquet").to_pylist())
        self.scope = {}
        for tx in ("hbo", "heb_mod", "heb_scg"):
            S = self.S[tx]
            if tx == "hbo":
                order = sorted((S.w[t]["id"], t) for t in S.w if where(S.w[t]["book"], S.w[t]["chapter"]) and S.w[t]["book"] != "MRK")
                self.scope[tx] = [t for _, t in order]
            else:
                self.scope[tx] = sorted(t for t in S.w if S.w[t]["book"] == "MRK")
        self.arc_in_scope = sum(1 for r in self.S["arc"].w.values() if where(r["book"], r["chapter"]))
        self.gloss = pq.read_table(GLOSS).to_pylist()
        terms = tsv(K1 / "hbo" / "terms.tsv")
        self.added_kind = {r["hbo"]: r["code"] for r in terms if r["category"] == "added_kind"}
        self.greek = {r["t"]: r for r in pq.read_table(K1 / "grc" / "pieces.parquet", columns=[
            "t", "kind", "class", "marks", "who", "who_basis"]).to_pylist() if r["kind"] == "stem"}
        self.glink = {}
        for e in ("heb_mod", "heb_scg"):
            m = defaultdict(set)
            for r in pq.read_table(K1 / e / "links.parquet").to_pylist():
                if r["other"] == "grc" and r["basis"] == "linked" and (r["agree"] or 0) >= 1: m[r["t"]].add(r["s"])
            self.glink[e] = m
        self.bj = json.loads((d / "build.json").read_text(encoding="utf-8"))

    # ---------------------------------------------------------------- the run
    def run(self, rebuild=True):
        say, cond = self.say, self.cond
        say("\n# Stage 59: pilot-2 of the switches (hebrew-levels/" + self.d.name + ")\n")
        need = ["build.json", "sources.json", "categories.toml", "COLUMNS.md", "README.md", "ops.parquet",
                "changed_verses.tsv", "sealed/switch_sample.tsv"]
        for lv, txs in LEVELS.items():
            for tx in txs:
                need += [f"texts/{lv}/{tx}/{f}" for f in ("words.parquet", "pieces.parquet", "links.parquet", "lexemes.tsv")]
                need += [f"lines/{lv}/{tx}.{f}.tsv" for f in ("cons", "point")]
        miss = [f for f in need if not (self.d / f).is_file()]
        cond("59 every file of SPEC-ladder 6.1 / SPEC-levels 7 present", not miss, f"{len(need)} files; missing {miss[:5]}")
        if miss: return
        self.load()
        self.files_and_inputs()
        self.texts_check()
        self.candidates_and_reasons()
        self.invariants()
        self.lines_check()
        self.counts_print()
        self.compare()
        self.sealed()
        self.latin()
        self.extras()
        if rebuild: self.rebuild()
        else: cond("59 rebuild gives the same sha256", None, "skipped (--no-rebuild)")

    def files_and_inputs(self):
        import hashlib
        def sha(p):
            h = hashlib.sha256(); h.update(Path(p).read_bytes()); return h.hexdigest()
        src = json.loads((self.d / "sources.json").read_text(encoding="utf-8"))
        root = MAC.parent.parent
        bad = [k for k, v in src["inputs"].items() if sha(root / k) != v]
        self.cond("59 sources.json: every input's sha256 equals the file", not bad, f"{len(src['inputs'])} inputs; differ {bad[:4]}")
        bad = [k for k, v in self.bj["files"].items() if not (self.d / k).is_file() or sha(self.d / k) != v]
        self.cond("59 build.json: every file's sha256 equals the file", not bad, f"{len(self.bj['files'])} files; differ {bad[:4]}")

    # ---------------------------------------------------------------- texts
    def texts_check(self):
        cond = self.cond
        cond("59 no Aramaic word in the Tanakh scope (SPEC-ladder 3.2)", self.arc_in_scope == 0, f"{self.arc_in_scope}")
        ops_by = {o["op"]: o for o in self.ops}
        bad_l0, bad_scope, bad_copy, bad_op, bad_draft, unlinked, unreached, bad_basis, keys_bad = [], [], [], [], [], [], [], [], []
        model_ct = {}
        for (lv, tx), (W, P, K) in sorted(self.texts.items()):
            S = self.S[tx]
            sc = self.scope[tx]
            verses = {(S.w[t]["book"], S.w[t]["chapter"], S.w[t]["verse"]) for t in sc}
            if (len(verses), len(sc)) != EXPECT[tx]: bad_scope.append((tx, len(verses), len(sc)))
            if lv == "l0":
                a = [(w["text"], w["after"] if tx == "hbo" else "") for w in W]
                b = [(S.w[t]["text"], S.w[t]["after"] if tx == "hbo" else "") for t in sc]
                if a != b or any(w["op"] for w in W): bad_l0.append(tx)
            vk = sorted({(w["book"], w["chapter"], w["verse"]) for w in W})
            if vk != sorted(verses): keys_bad.append((lv, tx))
            pw = defaultdict(list)
            for p in P: pw[p["t"]].append(p)
            lk = defaultdict(list)
            for k in K: lk[(k["t"], k["n"])].append(k)
            for w in W:
                if not w["op"]:
                    ls = [k for p in pw[w["t"]] for k in lk[(p["t"], p["n"])]]
                    if not ls or any(k["how"] != "copy" for k in ls) or len({k["s"] for k in ls}) != 1 \
                            or S.w[ls[0]["s"]]["text"] != w["text"]:
                        bad_copy.append((lv, tx, w["t"]))
                else:
                    o = ops_by.get(w["op"])
                    if o is None or o["state"] != "applied" or o["level"] != lv or o["text"] != tx \
                            or w["t"] not in json.loads(o["draft_t"]):
                        bad_op.append((lv, tx, w["t"]))
            wop = {w["t"]: w["op"] for w in W}
            for o in self.ops:
                if o["level"] == lv and o["text"] == tx and o["state"] == "applied":
                    dts = json.loads(o["draft_t"])
                    if not dts or any(wop.get(t) != o["op"] for t in dts): bad_draft.append(o["op"])
            for p in P:
                if not lk[(p["t"], p["n"])]: unlinked.append((lv, tx, p["t"], p["n"]))
                want = "derived" if p["op"] else None
                if want is None:
                    ls = lk[(p["t"], p["n"])]
                    want = self.S[ls[0]["other"]].pk[(ls[0]["s"], ls[0]["s_n"])]["basis"] if ls else "?"
                if p["basis"] != want: bad_basis.append((lv, tx, p["t"], p["n"], p["basis"], want))
            model_ct[f"{lv}/{tx}"] = sum(1 for p in P if p["basis"] == "model")
            reached = {(k["other"], k["s"], k["s_n"]) for k in K}
            for t in sc:
                for q in S.p[t]:
                    if (tx if tx != "hbo" else "hbo", t, q["n"]) not in reached: unreached.append((lv, tx, t, q["n"]))
        cond("59 scope: verses and words per part as SPEC-ladder 1 (hbo 1,248 / 13,537; heb_mod 677 / 8,892; heb_scg 678 / 9,397)",
             not bad_scope, f"{bad_scope[:3]}")
        cond("59 l0 equals k1 word for word (text and after, in order), no op", not bad_l0, f"differ {bad_l0}")
        cond("59 verse keys of every level equal the source's", not keys_bad, f"{keys_bad[:3]}")
        cond("59 every copied draft word links by copy to one source word of the same text", not bad_copy,
             f"{len(bad_copy)} bad {bad_copy[:3]}")
        cond("59 every written draft word traces to one applied op of its level and text", not bad_op, f"{len(bad_op)} bad {bad_op[:3]}")
        cond("59 every applied op's draft_t exist and carry the op", not bad_draft, f"{len(bad_draft)} bad {bad_draft[:3]}")
        cond("59 every draft piece has a link", not unlinked, f"{len(unlinked)} {unlinked[:3]}")
        cond("59 every source piece of the scope is reached at every level", not unreached, f"{len(unreached)} {unreached[:3]}")
        cond("59 pieces carry basis: a copied piece its source's (given for k1/hbo), a written piece derived",
             not bad_basis, f"{len(bad_basis)} bad {bad_basis[:3]}")
        self.say(f"    model pieces in the level texts (basis model): {json.dumps(model_ct)}")
        self.model_ct = model_ct

    # ---------------------------------------------------------------- places and reasons
    def catch_all(self, S):
        out = set()
        for r in S.wa:
            if r["state"] == "generic":
                q = S.pk.get((r["t"], r["n"]))
                if q is not None and len(ents(q["who"])) == 1: out.add(ents(q["who"])[0])
        return out

    def window(self, S, t, head, head_ents):
        cl = S.w[t]["clause"]
        if not cl or cl not in S.crank: return []
        i = S.crank[cl]
        g, n = head["m"].get("gender", ""), head["m"].get("number", "")
        out = set()
        for c in S.corder[max(0, i - 2): i + 1]:
            for wt in S.byclause.get(c, ()):
                for q in S.p[wt]:
                    if q["kind"] != "stem" or q["class"] != "noun" or not strict(q): continue
                    qg, qn = q["m"].get("gender", ""), q["m"].get("number", "")
                    if not qg or not qn: continue
                    if g and not (g == qg or g in "cb" or qg in "cb"): continue
                    if n and n != qn: continue
                    out |= {e for e in ents(q["who"]) if e not in head_ents}
        return sorted(out)

    def greek_reason(self, tx, t, ent, head):
        gs = sorted(self.glink[tx].get(t, ()))
        if not gs: return "greek_unlinked"
        carry = [g for g in gs if g in self.greek and self.greek[g]["who_basis"] != "model" and ent in ents(self.greek[g]["who"])]
        if not carry: return "greek_who"
        for g in carry:
            gp = self.greek[g]
            if gp["class"] not in ("verb", "pron"): continue
            gm = json.loads(gp["marks"] or "{}")
            for k in ("person", "number"):
                if head["m"].get(k) and gm.get(k) and head["m"][k] != gm[k]: return "greek_person_number"
        return ""

    def verb_reason(self, st, ps=()):
        if st is None or st["class"] != "verb": return "host_other"
        if any(q["kind"] == "prefix" and q["class"] == "art" for q in ps): return "host_participle"   # FIN-ART (OPEN 5)
        ty = st["m"].get("type", "")
        return "" if ty in FINITE else "host_infinitive" if ty in INF else "host_participle" if ty in PART else "host_other"

    def r_reason(self, tx, lv, r, v_lex):
        """-> (reason or '' (= a host rule writes or AF fails), name record)"""
        S = self.S[tx]; t = r["t"]
        p = S.pk[(t, r["n"])]
        es = ents(p["who"])
        st = S.stem(t)
        if (r.get("basis") == "model" or p["basis"] == "model" or p["who_basis"] == "model"
                or (r["head_kind"] == "suffix" and st is not None and st["basis"] == "model")):
            return "model_input", None
        if len(es) != 1: return "several_referents", None
        e = es[0]
        if e in self.ca[tx]: return "catch_all", None
        hk = r["head_kind"]
        if hk == "verb_zero" and not e.startswith(KINDS4): return "ent_kind", None
        if hk == "pronoun" and any((q["kind"] == "prefix" and q["class"] == "art") or q["fused"] for q in S.p[t]):
            return "demonstrative", None
        cl = S.w[t]["clause"]
        if cl:
            for wt in S.byclause[cl]:
                for q in S.p[wt]:
                    if (wt, q["n"]) != (t, r["n"]) and q["kind"] == "stem" and q["class"] in ("noun", "pron") and strict(q) \
                            and e in ents(q["who"]):
                        return "named_in_clause", None
        if not self.window(S, t, p, set(es)): return "not_ambiguous", None
        if tx != "hbo":
            g = self.greek_reason(tx, t, e, p)
            if g: return g, None
        if hk == "verb_zero":
            x = self.verb_reason(st, S.p[t])
            if x: return x, None
            if rel_same(S, t, e): return "relative_head", None          # REL (OPEN 1)
            if just_before(S, t, e): return "name_just_before", None    # REL-ASYN (OPEN 1)
        elif hk == "suffix":
            c = st["class"] if st else ""
            if c in ("prep", "om"):
                if v_lex.get(t, st["lexeme"]) in self.l0854: return "form_ambiguous", None
            elif c == "noun":
                pass
            elif c == "verb":
                x = self.verb_reason(st)
                if x: return x, None
            else:
                return "host_other", None
        w = S.w[t]
        m, _ = self.M[tx].nearest(e, t, w["book"], w["chapter"])
        if m is None: return "no_earlier_name", None
        cl = S.w[t]["clause"]                                            # NIC-FORM (OPEN 6)
        if cl and any(q["kind"] == "stem" and q["class"] == "noun" and fin(q["text"]) == fin(m[7])
                      for wt in S.byclause[cl] if wt < t for q in S.p[wt]):
            return "named_in_clause", m
        if not m[4]: return "indefinite", m
        if num_bad(p["m"].get("number", ""), m, e): return "number_mismatch", m
        return "", m

    def subj_roles(self, S):
        aa = {(r["verb"], r["clause"]) for r in S.added if r["role"] == "AA"}
        out = {}
        for r in S.added:
            k = (r["verb"], r["clause"])
            if k in out: continue
            st = S.stem(r["verb"])
            causative = st is not None and st["m"].get("stem", "") in CAUS
            has = k in aa or any("AA" in re.split(r"[^A-Za-z0-9]+", c["frame_role"] or "") for c in S.cons.get(r["clause"], ()))
            out[k] = "AA" if causative and has else "A0"
        return out

    def a_reason(self, r, subj, r_subj):
        S = self.S["hbo"]
        es = ents(r["who"])
        if r.get("own_basis") == "model": return "model_input", None
        if not es: return "no_who", None
        if len(es) > 1: return "several_referents", None
        if r["person"] in ("1", "2"): return "person_1_2", None
        if subj and not es[0].startswith(KINDS4): return "ent_kind", None
        for wt in S.byclause.get(r["clause"], ()):
            if wt != r["verb"] and any(set(ents(q["who"])) & set(es) for q in S.p[wt]): return "said_in_clause", None
        if subj and r["verb"] in r_subj: return "taken_by_r", None
        if not subj and r["role"] != "A1": return "role_other", None
        v, e = r["verb"], es[0]
        st = S.stem(v)
        x = self.verb_reason(st, S.p[v])
        if x: return x, None
        if subj:
            if rel_same(S, v, e): return "relative_head", None                  # REL (OPEN 1)
            if just_before(S, v, e): return "name_just_before", None            # REL-ASYN (OPEN 1)
            if strong_of(st["lexeme"]) == "1961" and any(                       # A-HAYAH (OPEN 7)
                    any(q["kind"] == "prefix" and q["class"] == "prep" and fin(q["text"]) == "כ" for q in S.p[wt])
                    and any(q["kind"] == "stem" and q["class"] == "noun" for q in S.p[wt]) for wt in S.byclause.get(r["clause"], ())):
                return "measure_hayah", None
        else:                                                                   # A-OBJ (OPEN 2)
            if antecedent(S, v) is not None: return "in_relative", None
            if st["m"].get("stem", "") in NOT_ACTIVE: return "passive_stem", None
            sr = self.sr[(v, r["clause"])]
            if e in ents(st["who"]) or any(x["verb"] == v and x["clause"] == r["clause"] and x["role"] == sr and e in ents(x["who"])
                                           for x in S.added):
                return "object_is_subject", None
            w = S.w[v]
            if any(q["m"].get("person") in ("1", "2") and e in ents(q["who"]) for x in S.vw[(w["book"], w["chapter"], w["verse"])]
                   for q in S.p[x]):
                return "speech_person", None
        w = S.w[v]
        m, _ = self.M["hbo"].nearest(e, v, w["book"], w["chapter"])
        if m is None: return "no_earlier_name", None
        if not m[4]: return "indefinite", m
        num = st["m"].get("number", "") if subj else r["number"]
        if num_bad(num, m, e): return "number_mismatch", m
        return "", m

    def v_reason(self, g, setting, S):
        t, n = g["src_t"], g["src_n"]
        if t is None:
            t = json.loads(g["anchor_t"])[0]; n = S.stem(t)["n"] if S.stem(t) else 1
        p = S.pk[(t, n)]
        st = self.lex
        if p["basis"] == "model": return "model_input"
        if len((g["lemma"] or "").replace("־", " ").split()) > 1 or g["src_t"] is None: return "lemma_phrase"
        if g["kind"] != "gloss": return "kind_other"
        if g["core_words"] >= 2: return "core_phrase"
        if g["fit"] == "fits":
            a, b = st.get(g["fit_lexeme"], {}).get("strong"), st.get(g["src_lexeme"], {}).get("strong")
            if g["fit_lexeme"] == g["src_lexeme"] or (a and a == b): return "no_change"
        if g["fit"] in ("unattested", "form_other"): return g["fit"]
        if any(q["fused"] for q in S.p[t]): return "fused_article"
        if setting == "all" and (g["src_count"] or 0) >= V_COMMON: return "common"          # V-COUNT (OPEN 8)
        if setting == "all" and not (p["class"] == "verb" and p["m"].get("type", "") not in PART):  # V-FIX (OPEN 8)
            w = S.w[t]; vs = S.vw[(w["book"], w["chapter"], w["verse"])]; i = vs.index(t)
            if i + 1 < len(vs):
                nx = S.p[vs[i + 1]]; st2 = [q for q in nx if q["kind"] == "stem"]
                if st2 and strong_of(st2[0]["lexeme"]) in DIVINE and not any(q["kind"] == "prefix" for q in nx): return "fixed_phrase"
        if setting == "rare" and not g["rare"]: return "not_rare"
        return ""

    def candidates_and_reasons(self):
        cond, say = self.cond, self.say
        self.ca = {tx: self.catch_all(self.S[tx]) for tx in ("hbo", "heb_mod", "heb_scg")}
        self.l0854 = {k for k, r in self.lex.items() if r["strong"] == "0854" and r["class"] == "prep"}
        say(f"    lexeme of אֵת 'with' (DEF, 0854) in k1/lexicon: {sorted(self.l0854)} (the specification wrote lex:hbo:את:0854)")
        ops = defaultdict(list)
        for o in self.ops: ops[(o["level"], o["text"], o["switch"])].append(o)
        place_bad, reason_bad, self.names = [], [], {}
        for lv, txs in LEVELS.items():
            for tx in txs:
                S = self.S[tx]; sc = set(self.scope[tx])
                v_lex = {}
                # V
                if "v" in SW[lv]:
                    setting = "rare" if lv == "zr_r" else "all"
                    rows = [g for g in self.gloss if g["anchor_state"] == "anchored" and where(g["book"], g["chapter"])
                            and g["book"] != "MRK"]
                    vo = ops[(lv, tx, "v")]
                    want = []
                    for g in rows:
                        t = g["src_t"] if g["src_t"] is not None else json.loads(g["anchor_t"])[0]
                        if t in sc: want.append((g, t))
                    by_gloss = {json.loads(o["detail"])["gloss"]: o for o in vo}
                    if len(by_gloss) != len(vo) or sorted(by_gloss) != sorted(g["gloss"] for g, _ in want):
                        place_bad.append((lv, tx, "v", len(vo), len(want)))
                    for g, t in want:
                        o = by_gloss.get(g["gloss"])
                        if o is None: continue
                        mine = self.v_reason(g, setting, S)
                        if o["setting"] != setting or (mine and o["reason"] != mine) or (not mine and o["state"] != "applied"):
                            reason_bad.append((o["op"], o["reason"], mine))
                        if o["state"] == "applied": v_lex[o["src_t"]] = o["lexeme_after"]
                # R
                if "r" in SW[lv]:
                    places = sorted((r["t"], r["n"], r) for r in S.wa if r["t"] in sc and r["head_kind"] in ("pronoun", "suffix", "verb_zero")
                                    and r["state"] == "participant" and S.pk.get((r["t"], r["n"]), {"m": {}})["m"].get("person") == "3")
                    ro = ops[(lv, tx, "r")]
                    got = Counter((o["src_t"], o["src_n"]) for o in ro)
                    if sorted(got) != sorted((a, b) for a, b, _ in places) or any(v != 1 for v in got.values()):
                        place_bad.append((lv, tx, "r", len(ro), len(places)))
                    rk = {(o["src_t"], o["src_n"]): o for o in ro}
                    for a, b, r in places:
                        o = rk.get((a, b))
                        if o is None: continue
                        mine, m = self.r_reason(tx, lv, r, v_lex)
                        if o["setting"] != "amb" or (mine and o["reason"] != mine) or \
                                (not mine and not (o["state"] == "applied" or o["reason"] == "form_unattested"
                                                   or (o["reason"] == "name_chain_bound" and m is not None and m[8] == 2))):
                            reason_bad.append((o["op"], o["reason"], mine))
                        if o["state"] == "applied": self.names[o["op"]] = m
                # A
                if "a" in SW[lv]:
                    sr = self.subj_roles(S); self.sr = sr
                    rows = sorted((r["verb"], r["role"], r["clause"], i, r) for i, r in enumerate(S.added) if r["verb"] in sc
                                  and self.added_kind.get(r["kind"]) in ("in_verb", "elsewhere"))
                    ao = ops[(lv, tx, "a")]
                    ak = Counter((o["src_t"], o["added_role"], o["added_clause"]) for o in ao)
                    if sorted(ak) != sorted((a, b, c) for a, b, c, _, _ in rows) or any(v != 1 for v in ak.values()):
                        place_bad.append((lv, tx, "a", len(ao), len(rows)))
                    r_subj = {o["src_t"] for o in ops[(lv, tx, "r")] if o["rule"] == "r_subject"}
                    am = {(o["src_t"], o["added_role"], o["added_clause"]): o for o in ao}
                    for a, b, c, _, r in rows:
                        o = am.get((a, b, c))
                        if o is None: continue
                        mine, m = self.a_reason(r, r["role"] == sr[(r["verb"], r["clause"])], r_subj)
                        if (mine and o["reason"] != mine) or (not mine and not (o["state"] == "applied" or o["reason"] == "form_unattested")):
                            reason_bad.append((o["op"], o["reason"], mine))
                        if o["state"] == "applied": self.names[o["op"]] = m
        cond("59 every candidate place of V, R, A has exactly one op row (places recomputed)", not place_bad, f"{place_bad[:4]}")
        cond("59 every reason of V, R, A recomputed by the validator's own rules (6.2-6.5)", not reason_bad,
             f"{len(reason_bad)} differ {reason_bad[:5]}")

    # ---------------------------------------------------------------- the rules' invariants (6.6)
    def invariants(self):
        cond, say = self.cond, self.say
        dw, dp = {}, {}
        for (lv, tx), (W, P, K) in self.texts.items():
            for w in W: dw[(lv, tx, w["t"])] = w
            for p in P: dp.setdefault((lv, tx, p["t"]), []).append(p)
        bad = defaultdict(list)
        disagree = []
        gloss = {g["gloss"]: g for g in self.gloss}
        self.fused_art = []
        later = defaultdict(set)      # a word after which R or A inserted: its after moved to the inserted word (SPEC-levels 7.2)
        for o in self.ops:
            if o["state"] == "applied" and o["switch"] in ("r", "a"): later[(o["level"], o["text"])].add(o["src_t"])
        for o in self.ops:
            if o["state"] != "applied": continue
            lv, tx = o["level"], o["text"]
            S = self.S[tx]
            dts = json.loads(o["draft_t"])
            if o["switch"] in ("r", "a"):
                e = o["ent"]
                npcs = [p for t in dts for p in dp[(lv, tx, t)] if p["who_basis"] == "inserted"]
                if not npcs or npcs[-1]["class"] != "noun": bad["name"].append(o["op"]); continue
                if any(ents(p["who"]) != [e] for p in npcs): bad["ent"].append(o["op"])
                head_t = o["src_t"]
                w = S.w[head_t]
                m, tier = self.M[tx].nearest(e, head_t, w["book"], w["chapter"])
                ntext = fin("".join(p["text"] for p in npcs))
                fused_art = o["rule"] == "r_prep_bound" and m is not None and m[4] and fin(m[3])[1:] == ntext
                if m is None or (fin(m[3]) != ntext and not fused_art) or o["form_rule"] not in (tier, "whole", "joined",
                                                                                                             "whole_tanakh", "joined_tanakh"):
                    bad["NF2"].append(o["op"])
                nm0 = json.loads(npcs[-1]["marks"] or "{}")
                definite = any(p["class"] == "art" for p in npcs) or nm0.get("type") == "proper" or \
                    (not nm0.get("type") and npcs[-1]["lexeme"] in self.name_lex)
                if not definite and not fused_art: bad["DEF"].append(o["op"])
                if fused_art: self.fused_art.append(o["op"])
                nst = npcs[-1]["marks"] and json.loads(npcs[-1]["marks"]).get("number", "")
                head = S.pk[(o["src_t"], o["src_n"])]
                if o["switch"] == "r":
                    num = head["m"].get("number", "")
                else:
                    num = S.stem(o["src_t"])["m"].get("number", "") if o["rule"] == "a_subject" else \
                        next(r["number"] for r in S.added if r["verb"] == o["src_t"] and r["role"] == o["added_role"] and r["clause"] == o["added_clause"])
                if m is not None and num_bad(num, m, e): bad["NUM"].append(o["op"])
                if o["rule"] in ("r_subject", "a_subject", "a_object", "r_object"):
                    st = S.stem(o["src_t"])
                    if not (st and st["class"] == "verb" and st["m"].get("type") in FINITE) or \
                            any(q["kind"] == "prefix" and q["class"] == "art" for q in S.p[o["src_t"]]): bad["FIN"].append(o["op"])
                if o["rule"] in ("r_subject", "a_subject") and not e.startswith(KINDS4): bad["KIND"].append(o["op"])
                if o["rule"] == "r_pronoun" and any((q["kind"] == "prefix" and q["class"] == "art") or q["fused"] for q in S.p[o["src_t"]]):
                    bad["DEM"].append(o["op"])
                st = S.stem(o["src_t"])
                if o["rule"].startswith("r_prep") and st and st["lexeme"] in self.l0854: bad["0854"].append(o["op"])
                if o["rule"] == "r_object":
                    v = dp[(lv, tx, dts[0])]
                    if any(p["kind"] == "suffix" for p in v) or not any(p["kind"] == "stem" and p["class"] == "verb" for p in v) \
                            or len(dts) not in (3, 4) or not any(p["class"] == "om" for p in dp[(lv, tx, dts[1])]):
                        bad["OBJ"].append(o["op"])
                if o["rule"] == "r_construct":
                    if json.loads(dp[(lv, tx, dts[0])][-1]["marks"] or "{}").get("state") != "cstr" and \
                            not any(json.loads(p["marks"] or "{}").get("state") == "cstr" for p in dp[(lv, tx, dts[0])] if p["kind"] == "stem"):
                        bad["cstr"].append(o["op"])
                if tx != "hbo" and o["switch"] == "r" and self.greek_reason(tx, o["src_t"], e, head):
                    bad["GK"].append(o["op"])
                if o["rule"] in ("r_subject", "a_subject"):
                    hm = S.stem(o["src_t"])["m"]; nm = json.loads(npcs[-1]["marks"] or "{}")
                    if (hm.get("number") and nm.get("number") and hm["number"] != nm["number"]) or \
                            (hm.get("gender") and nm.get("gender") and not g_ok(hm["gender"], nm["gender"])):
                        disagree.append((o["op"], o["key"], hm.get("gender", ""), hm.get("number", ""), nm.get("gender", ""), nm.get("number", "")))
            elif o["switch"] == "v":
                g = gloss[json.loads(o["detail"])["gloss"]]
                if g["fit"] != "fits": bad["V_fits"].append(o["op"])
                if lv == "zr_r" and not g["rare"]: bad["V_rare"].append(o["op"])
                text = dw[(lv, tx, dts[0])]["text"]
                if len(dts) != 1 or ud.normalize("NFD", text) != ud.normalize("NFD", g["fit_form"]): bad["V_form"].append(o["op"])
                stp = [p for p in dp[(lv, tx, dts[0])] if p["kind"] == "stem"]
                src = S.pk[(o["src_t"], o["src_n"])]
                if not stp or stp[0]["lexeme"] != g["fit_lexeme"] or o["lexeme_after"] != g["fit_lexeme"]: bad["V_lexeme"].append(o["op"])
                else:
                    nm = json.loads(stp[0]["marks"] or "{}")
                    for k in ("type", "person", "gender", "number", "state"):
                        a = src["m"].get(k)
                        if a and not (nm.get(k) == a or (k == "gender" and g_ok(a, nm.get(k, "")) and nm.get(k))):
                            bad["V_marks"].append(o["op"]); break
                if dw[(lv, tx, dts[0])]["after"] != S.w[o["src_t"]]["after"] and o["src_t"] not in later[(lv, tx)]:
                    bad["V_after"].append(o["op"])
        names = {"name": "every applied R/A op wrote a name word", "ent": "every written name piece carries exactly the op's ent",
                 "NF2": "NF2: 0 written names other than the nearest earlier mention in the window (chapter, then book; Psalms the psalm)",
                 "DEF": "DEF: 0 indefinite names applied", "NUM": "NUM: 0 applied with a plural host and a person's name that is not plural, or a singular host and a plural name (not אֱלֹהִים-like)",
                 "FIN": "FIN: 0 subjects or objects applied after a non-finite host (a verb with the article counts as a participle)", "KIND": "KIND: 0 subjects applied for other kinds than person/group/deity/fauna",
                 "DEM": "DEM: 0 applied on a pronoun with the article", "0854": "0854: 0 applied on the preposition אֵת 'with'",
                 "OBJ": "OBJ: 0 applied r_object whose host keeps its suffix (verb, object marker, name follow)",
                 "cstr": "r_construct: the host's new form has state cstr", "GK": "GK: every applied edition R op passes 6.3",
                 "V_fits": "V: every applied op from a `fits` gloss row", "V_rare": "V: at zr_r every applied op from a `rare` row",
                 "V_form": "V: the written word is the row's fit_form", "V_lexeme": "V: the new stem's lexeme is fit_lexeme",
                 "V_marks": "V: the new stem's marks agree with the source stem's", "V_after": "V: the written word keeps the source word's after"}
        for k, txt in names.items():
            cond("59 " + txt, not bad[k], f"{len(bad[k])} exceptions {bad[k][:4]}")
        say(f"    r_prep_bound names whose article is fused into the preposition (NF2 and DEF read through it): {len(self.fused_art)} {self.fused_art}")
        say(f"    written subjects whose gender or number differ from the verb's (counted, applied, not hidden): {len(disagree)}")
        for x in disagree: say(f"      {x}")

    # ---------------------------------------------------------------- lines
    def lines_check(self):
        cond = self.cond
        cv = tsv(self.d / "changed_verses.tsv")
        changed = defaultdict(set)
        for r in cv: changed[(r["level"], r["text"])].add(r["key"])
        own = defaultdict(Counter)
        sw = defaultdict(set)
        for o in self.ops:
            if o["state"] == "applied":
                own[(o["level"], o["text"])][o["key"]] += 1; sw[(o["level"], o["text"], o["key"])].add(o["switch"])
        cv_bad = [r for r in cv if int(r["ops"]) != own[(r["level"], r["text"])][r["key"]]
                  or json.loads(r["switches"]) != sorted(sw[(r["level"], r["text"], r["key"])])]
        cv_bad += [k for k in own if set(own[k]) != changed[k]]
        cond("59 changed_verses.tsv recomputed from the ops", not cv_bad, f"{len(cv)} rows; differ {cv_bad[:3]}")
        bad, fmt, closed_bad = [], [], []
        for (lv, tx), (W, P, K) in self.texts.items():
            raw, order = defaultdict(list), []
            for w in W:
                k = f"{w['book']} {w['chapter']}:{w['verse']}"
                if k not in raw: order.append((k, w["book"], w["chapter"]))
                raw[k].append(w["text"] + w["after"] if tx == "hbo" else w["text"])
            for form in ("cons", "point"):
                rows = tsv(self.d / "lines" / lv / f"{tx}.{form}.tsv")
                if [r["key"] for r in rows] != [k for k, _, _ in order]: bad.append((lv, tx, form, "keys")); continue
                for r, (k, b, c) in zip(rows, order):
                    want = line_form("".join(raw[k]) if tx == "hbo" else " ".join(raw[k]), form)
                    if r["line"] != want: bad.append((lv, tx, form, k))
                    ok = r["line"] and r["line"] == r["line"].strip() and "  " not in r["line"] and \
                        all("א" <= ch <= "ת" or ch == " " or (form == "point" and ord(ch) in KEEP) for ch in r["line"]) and \
                        r["text"] == tx and r["level"] == lv and r["form"] == form and re.fullmatch(r"[1-3A-Z]{3} \d+:\d+", r["key"])
                    if not ok: fmt.append((lv, tx, form, k))
                    if r["scoring_closed"] != ("true" if closed(b, c) else "false") or \
                            r["changed"] != ("true" if k in changed[(lv, tx)] else "false"):
                        closed_bad.append((lv, tx, form, k))
                if tx == "heb_mod" and form == "point":
                    cons = tsv(self.d / "lines" / lv / f"{tx}.cons.tsv")
                    if [r["line"] for r in rows] != [r["line"] for r in cons]: bad.append((lv, tx, "point!=cons"))
        for o in self.ops:
            b, c = o["key"].split()[0], int(o["key"].split()[1].split(":")[0])
            if o["scoring_closed"] != closed(b, c): closed_bad.append(o["op"])
        cond("59 lines: rule IN recomputed on every level text (cons, point; heb_mod point = cons)", not bad, f"{len(bad)} {bad[:3]}")
        cond("59 lines: one row per verse, none empty, letters/points/space only, key BOOK ch:v", not fmt, f"{len(fmt)} {fmt[:3]}")
        cond("59 scoring_closed (Ruth, Jonah, GEN 22) and changed right on every line and op row", not closed_bad,
             f"{len(closed_bad)} {closed_bad[:3]}")

    # ---------------------------------------------------------------- counts
    def counts_print(self):
        say = self.say
        say("\n## Counts per level x part x switch x reason, portion by portion\n")
        c = Counter()
        for o in self.ops:
            b, ch = o["key"].split()[0], int(o["key"].split()[1].split(":")[0])
            c[(o["level"], o["text"], o["switch"], where(b, ch), o["state"], o["reason"] or o["rule"])] += 1
        say("| level | part | switch | portion | state | reason / rule | ops |\n|---|---|---|---|---|---|---|")
        for k in sorted(c): say("| " + " | ".join(map(str, k)) + f" | {c[k]} |")
        tot = Counter()
        for (lv, tx, s, p, st, rr), v in c.items(): tot[(lv, tx, s, st)] += v
        say("\nTotals:")
        for k in sorted(tot): say(f"    {'/'.join(k)}: {tot[k]}")

    # ---------------------------------------------------------------- pilot-1 against pilot-2
    def compare(self):
        say = self.say
        ids = {}
        for part in ("hbo", "heb_mod", "heb_scg"):
            a = {r["t"]: r["id"] for r in pq.read_table(I1 / part / "words.parquet", columns=["t", "id"]).to_pylist()}
            ids[part] = sum(1 for t, i in a.items() if self.S[part].w.get(t, {}).get("id") != i)
        self.cond("59 pilot-1 (i1) and pilot-2 (k1) name the same words by t (MACULA ids equal)", not any(ids.values()), json.dumps(ids))
        p1 = pq.read_table(P1 / "ops.parquet").to_pylist()
        shared = {"GEN22-25", "RUT", "JON", "MRK"}
        def sh(o):
            return where(o["key"].split()[0], int(o["key"].split()[1].split(":")[0])) in shared
        pairs = {"r": ("r", "r"), "a": ("v2_r_a", "z_r_a"), "v": ("v2", "z_r_a")}
        res = {}
        say("\n## Pilot-1 against pilot-2 over the shared places (GEN 22-25, RUT, JON, MRK)\n")
        say("| switch/part | pilot-1 applied | pilot-2 applied | kept | kept, other form | dropped | new |\n|---|---|---|---|---|---|---|")
        lines = []
        for sw, (l1, l2) in pairs.items():
            for tx in ("hbo", "heb_mod", "heb_scg"):
                if sw == "a" and tx != "hbo": continue
                l2x = "r" if (sw == "v" and tx != "hbo") else l2
                A = {(o["src_t"], o["src_n"], o["added_role"]): o for o in reversed(p1)
                     if o["level"] == l1 and o["text"] == tx and o["switch"] == sw and sh(o)}
                Bm = {(o["src_t"], o["src_n"], o["added_role"]): o for o in reversed(self.ops)
                      if o["level"] == l2x and o["text"] == tx and o["switch"] == sw and sh(o)}
                c, drop, new = Counter(), Counter(), Counter()
                for k, o in A.items():
                    if o["state"] != "applied": continue
                    c["p1_applied"] += 1
                    q = Bm.get(k)
                    if q is None: drop["no_place_in_pilot2"] += 1
                    elif q["state"] == "applied":
                        c["kept"] += 1
                        if q["after"] != o["after"]: c["kept_other_form"] += 1
                    else: drop[q["reason"]] += 1
                for k, q in Bm.items():
                    if q["state"] != "applied": continue
                    c["p2_applied"] += 1
                    o = A.get(k)
                    if o is None: new["no_place_in_pilot1"] += 1
                    elif o["state"] != "applied": new[o["reason"]] += 1
                c["dropped"], c["new"] = sum(drop.values()), sum(new.values())
                rules = Counter((A[k]["rule"], q["rule"]) for k, q in Bm.items() if q["state"] == "applied" and k in A
                                and A[k]["state"] == "applied")
                if sw == "r": lines.append(f"    {sw}/{tx} kept, pilot-1 rule -> pilot-2 rule: {dict(sorted(rules.items()))}")
                p1r = Counter(A[k]["rule"] for k in A if A[k]["state"] == "applied")
                if sw == "r": lines.append(f"    {sw}/{tx} pilot-1 applied by rule: {dict(sorted(p1r.items()))}")
                res[f"{sw}/{tx}"] = {"levels": [l1, l2x], "counts": dict(sorted(c.items())),
                                     "dropped_by_pilot2_reason": dict(sorted(drop.items())), "new_by_pilot1_reason": dict(sorted(new.items()))}
                say(f"| {sw}/{tx} | {c['p1_applied']} | {c['p2_applied']} | {c['kept']} | {c['kept_other_form']} | {c['dropped']} | {c['new']} |")
                lines.append(f"    {sw}/{tx} dropped by pilot-2's reason: {json.dumps(dict(sorted(drop.items())), ensure_ascii=False)}; "
                             f"new, by pilot-1's reason: {json.dumps(dict(sorted(new.items())), ensure_ascii=False)}")
        for x in lines: say(x)
        theirs = {k: v for k, v in self.bj["counts"]["compare_pilot1"].items() if not k.startswith("_")}
        self.cond("59 the comparison with pilot-1 recomputed equals build.json's", res == theirs,
                  "differ: " + str(sorted(k for k in set(res) | set(theirs) if res.get(k) != theirs.get(k))))

    # ---------------------------------------------------------------- the sealed sample
    def sealed(self):
        rows = tsv(self.d / "sealed" / "switch_sample.tsv")
        with open(self.d / "sealed" / "switch_sample.tsv", encoding="utf-8") as f:
            head = f.readline().rstrip("\n").split("\t")
        rng = random.Random(SEED)
        want = []
        for sw, lv, tx in (("r", "r", None), ("a", "z_r_a", "hbo"), ("v", "z_r_a", "hbo")):
            ids = sorted(o["op"] for o in self.ops if o["level"] == lv and o["switch"] == sw and o["state"] == "applied"
                         and (tx is None or o["text"] == tx))
            want += [(sw, lv, x) for x in (rng.sample(ids, 30) if len(ids) > 30 else ids)]
        got = [(r["switch"], r["level"], r["op"]) for r in rows]
        import hashlib
        h = hashlib.sha256((self.d / "sealed" / "switch_sample.tsv").read_bytes()).hexdigest()
        self.cond("59 sealed sample: 30 applied ops per switch (R, A, V) by seed ladder-2026-11-24, op ids only, sha256 in build.json",
                  got == want and head == ["switch", "level", "op"] and self.bj.get("sealed_switches") == h,
                  f"{Counter(r[0] for r in got)}; header {head}; sha {h[:12]}")

    # ---------------------------------------------------------------- Latin letters
    def latin(self):
        hits = []
        for (lv, tx), (W, P, K) in self.texts.items():
            hits += [(lv, tx, "words", w["t"]) for w in W if LATIN.search(w["text"])]
            hits += [(lv, tx, "pieces", p["t"]) for p in P if LATIN.search(p["text"])]
            hits += [(lv, tx, "lemma", r["lexeme"]) for r in tsv(self.d / "texts" / lv / tx / "lexemes.tsv") if LATIN.search(r["lemma"])]
        hits += [o["op"] for o in self.ops if LATIN.search(o["before"]) or LATIN.search(o["after"])]
        for p in sorted((self.d / "lines").rglob("*.tsv")):
            hits += [str(p) for r in tsv(p) if LATIN.search(r["line"])]
        self.cond("59 the Latin-letter check passes on every text column of pilot-2", not hits, f"{len(hits)} {hits[:3]}")

    # ---------------------------------------------------------------- counts for the report
    def extras(self):
        say = self.say
        say("\n## Counts for the report (no bar)\n")
        by_strong, by_cons = defaultdict(list), defaultdict(list)
        for k, r in self.lex.items():
            if r["lang"] in ("hbo", "arc") and r["strong"]:
                by_strong[(r["lang"], r["strong"].rstrip("abcdefgh"))].append(k)
            by_cons[(r["lang"], fin(r["lemma"]), r["class"])].append(k)
        ds = sum(1 for v in by_strong.values() if len(v) > 1)
        dc = sum(1 for v in by_cons.values() if len(v) > 1)
        say(f"    lexicon double keys: {ds} Strong numbers (base, letter suffix dropped) under several keys; "
            f"{dc} (lang, consonants, class) under several keys")
        vo = [o for o in self.ops if o["switch"] == "v"]
        g = {x["gloss"]: x for x in self.gloss}
        same_cons = [o["op"] for o in vo if o["level"] == "z_r_a" and o["state"] == "applied"
                     and fin(self.lex.get(o["lexeme_after"], {}).get("lemma", "")) == fin(self.lex.get(o["lexeme_before"], {}).get("lemma", ""))]
        nc = [o["op"] for o in vo if o["level"] == "z_r_a" and o["reason"] == "no_change"]
        say(f"    V at z_r_a: no_change {len(nc)} {nc}; applied with the same consonants of lemma under another key: {len(same_cons)} {same_cons}")
        S = self.S["hbo"]
        pas = [o["op"] for o in self.ops if o["level"] == "z_r_a" and o["switch"] == "a" and o["state"] == "applied"
               and S.stem(o["src_t"])["m"].get("stem") in PASSIVE]
        rel = []
        for o in self.ops:
            if o["level"] == "z_r_a" and o["switch"] == "a" and o["state"] == "applied" and o["rule"] == "a_object":
                if any(q["class"] == "rel" for wt in S.byclause.get(o["added_clause"], ()) for q in S.p[wt]): rel.append(o["op"])
        say(f"    OPEN item 11 by rule: A applied on a passive stem (niphal, pual, hophal) {len(pas)} {pas[:10]}; "
            f"A object applied in a clause with a relative word {len(rel)} {rel[:10]}; Tanakh quotations in Mark: no table marks them (not counted)")
        lexd = Counter()
        for o in self.ops:
            if o["state"] == "applied" and o["switch"] == "r" and o["text"] != "hbo" and o["level"] == "r":
                m = self.names.get(o["op"])
                st = self.S[o["text"]]
                if m is not None and not st.stem(m[0])["m"].get("type"): lexd[o["text"]] += 1
        say(f"    applied R in the editions whose name is a proper noun only by the lexicon's state `name` (DEF): {dict(lexd)}")

    # ---------------------------------------------------------------- rebuild
    def rebuild(self):
        import hashlib
        base = Path("/tmp/claude-1000/source-examples/ladder59")
        n = 1
        while (base / f"rebuild-{n}").exists(): n += 1
        out = base / f"rebuild-{n}"
        subprocess.run([sys.executable, "-I", str(MAC / "build_ladder.py"), "--build", "pilot-1", "--stage", "59", "--out", str(out)],
                       check=True, capture_output=True)
        def sums(d):
            return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest() for p in d.rglob("*")
                    if p.is_file() and p.name != "VALIDATION.md" and "cache" not in p.relative_to(d).parts}
        a, b = sums(out), sums(self.d)
        diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        self.cond("59 rebuild from nothing gives the same sha256 for every file", not diff, f"{len(b)} files; differ {diff[:5]} (scratch rebuild-{n})")
