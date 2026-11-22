"""Stage 43 of the Hebrew levels: the texts of the pilot, rules AF and NF, and switches V, R, A (SPEC-levels 6, 7).

Reads build i1 (the source parts) and the stage-42 tables of the levels build. Writes nothing itself; the stage
module (levels_stage43.py) writes the tables. Every function is deterministic (sorted inputs, explicit ties).
"""
import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict

import pyarrow.parquet as pq

from levels_common import I1, CONTENT

PILOT_BOOKS = ("GEN", "RUT", "JON")
TEXTS = ("hbo", "heb_mod", "heb_scg")
LEVELS = {  # SPEC-levels 6.1: level -> switches in order, texts
    "l0": ((), TEXTS),
    "v2": (("v",), TEXTS),
    "r": (("r_amb",), TEXTS),
    "rall": (("r_all",), TEXTS),
    "a": (("a",), ("hbo",)),
    "v2_r": (("v", "r_amb"), TEXTS),
    "v2_r_a": (("v", "r_amb", "a"), ("hbo",)),
}
LEVEL_ORDER = ("l0", "v2", "r", "rall", "a", "v2_r", "v2_r_a")
K = 2
MARK_KEYS = ("type", "stem", "person", "gender", "number", "state")
FINITE = ("qatal", "wayyiqtol", "yiqtol", "weqatal", "imperative", "jussive", "cohortative")
INFINITIVE = ("infinitive_construct", "infinitive_absolute")
PARTICIPLE = ("participle_active", "participle_passive")
CAUSATIVE = ("hiphil", "haphel", "aphel", "shaphel")
SENSE_RX = re.compile(r"\d{15}")
CLOSED_WHOLE = ("RUT", "JON")
CLOSED_CHAPTERS = {("GEN", 22), ("LUK", 1), ("LUK", 2), ("LUK", 15), ("PHP", 3), ("ACT", 1), ("MAT", 21)}


def scoring_closed(book, chapter):
    """SPEC-levels 7.4."""
    return book in CLOSED_WHOLE or (book, chapter) in CLOSED_CHAPTERS


def vkey(book, chapter, verse):
    return f"{book} {chapter}:{verse}"


def nfc(s):
    return unicodedata.normalize("NFC", s)


def strip_marks(s):
    """Every combining mark dropped (heb_mod takes Tanakh forms so, 6.5 step 3)."""
    return "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")


def gmatch(a, b):
    return a == b or (a in ("c", "b") and b in ("m", "f", "c", "b")) or (b in ("c", "b") and a in ("m", "f", "c", "b"))


def marks_agree(want, have):
    """want: the marks to keep; have: the attested piece's marks. c/b gender matches m or f (6.5)."""
    for k, v in want.items():
        hv = have.get(k)
        if hv is None or hv == "":
            return False
        if k == "gender":
            if not gmatch(v, hv):
                return False
        elif v != hv:
            return False
    return True


def single_sense(s):
    return s if s and SENSE_RX.fullmatch(s) else ""


def ents(who):
    return [e for e in (who or "").split() if e]


# ------------------------------------------------------------------ reading i1

def read_tsv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


COLS = {
    "words": ["t", "id", "book", "chapter", "verse", "w", "text", "after", "sentence", "clause"],
    "pieces": ["t", "n", "text", "kind", "lexeme", "class", "marks", "fused", "who", "who_basis", "sense", "domain",
               "basis"],
}


def _rows(part, name):
    path = I1 / part / f"{name}.parquet"
    cols = COLS.get(name)
    if cols:
        have = pq.ParquetFile(path).schema_arrow.names
        cols = [c for c in cols if c in have]
    return pq.read_table(path, columns=cols).to_pylist()


class Part:
    """One source part of i1, whole (the scope is chosen by the text)."""

    def __init__(self, name):
        self.name = name
        self.words = {r["t"]: r for r in _rows(name, "words")}
        self.pieces = defaultdict(list)
        for p in _rows(name, "pieces"):
            p["m"] = json.loads(p["marks"]) if p["marks"] else {}
            p.setdefault("basis", "")
            self.pieces[p["t"]].append(p)
        for t in self.pieces:
            self.pieces[t].sort(key=lambda p: p["n"])
        self.clauses = {}
        order = []
        for i, c in enumerate(_rows(name, "clauses")):
            c["m"] = json.loads(c["marks"]) if c["marks"] else {}
            self.clauses[c["clause"]] = c
            order.append((c["first"], i, c["clause"]))
        order.sort()
        self.clause_order = [c for _, _, c in order]
        self.clause_rank = {c: i for i, c in enumerate(self.clause_order)}
        self.constituents = defaultdict(list)
        for c in _rows(name, "constituents"):
            self.constituents[c["clause"]].append(c)
        self.who_account = _rows(name, "who_account")
        for r in self.who_account:
            r.setdefault("basis", "")
        self.added = _rows(name, "added") if (I1 / name / "added.parquet").exists() else []
        self.passages = _rows(name, "passages")
        self.participants = {r["ent"]: r for r in read_tsv(I1 / name / "participants.tsv")}
        self.words_by_clause = defaultdict(list)
        self.verse_index = defaultdict(list)
        for t, w in self.words.items():
            self.verse_index[vkey(w["book"], w["chapter"], w["verse"])].append(t)
            if w["clause"]:
                self.words_by_clause[w["clause"]].append(t)
        for c in self.words_by_clause:
            self.words_by_clause[c].sort()

    def stem(self, t):
        for p in self.pieces[t]:
            if p["kind"] == "stem":
                return p
        return None


def strict_piece(p):
    return p.get("basis", "") != "model"


def strict_who(p):
    return strict_piece(p) and p["who_basis"] != "model" and bool(p["who"])


class Text:
    """A text of the pilot (SPEC-levels 3.2): its source words in text order, and its parts."""

    def __init__(self, code, parts):
        self.code = code
        if code == "hbo":
            self.parts = {"hbo": parts["hbo"], "arc": parts["arc"]}
            ws = [(w["id"], pn, t) for pn in ("hbo", "arc") for t, w in self.parts[pn].words.items()
                  if w["book"] in PILOT_BOOKS]
            ws.sort()
            self.order = [(pn, t) for _, pn, t in ws]
            assert not set(parts["hbo"].words) & set(parts["arc"].words), "hbo and arc t overlap"
        else:
            self.parts = {code: parts[code]}
            self.order = [(code, t) for t in sorted(parts[code].words)]
        self.part_of = {t: pn for pn, t in self.order}
        self.scope = set(self.part_of)

    def word(self, t):
        return self.parts[self.part_of[t]].words[t]

    def pieces(self, t):
        return self.parts[self.part_of[t]].pieces[t]

    def part(self, t):
        return self.parts[self.part_of[t]]

    def key(self, t):
        w = self.word(t)
        return vkey(w["book"], w["chapter"], w["verse"])

    def closed(self, t):
        w = self.word(t)
        return scoring_closed(w["book"], w["chapter"])


# ------------------------------------------------------------------ rule AF (6.5)

class FormSource:
    """The attested words of one or more parts, indexed by stem lexeme."""

    def __init__(self, parts, strict_only=False, strip=False):
        self.by_lex = defaultdict(list)
        self.after = defaultdict(Counter)
        self.strip = strip
        for part in parts:
            for t in sorted(part.words):
                ps = part.pieces[t]
                if strict_only and not all(strict_piece(p) for p in ps):
                    continue
                st = [p for p in ps if p["kind"] == "stem"]
                if len(st) != 1:
                    continue
                s = st[0]
                pre = [p for p in ps if p["kind"] == "prefix"]
                suf = [p for p in ps if p["kind"] == "suffix"]
                text = part.words[t]["text"]
                if strip:
                    text = strip_marks(text)
                e = {
                    "pre_lex": tuple(p["lexeme"] for p in pre),
                    "marks": s["m"],
                    "suf": tuple((p["m"].get("person", ""), p["m"].get("gender", ""), p["m"].get("number", ""))
                                 for p in suf),
                    "text": nfc(text),
                    "pieces": [self._pc(p) for p in ps],
                    "pre_n": len(pre),
                    "fused": any(p["fused"] for p in ps),
                }
                e["tail"] = nfc("".join(p["text"] for p in e["pieces"][e["pre_n"]:]))
                self.by_lex[s["lexeme"]].append(e)
                self.after[(s["lexeme"], e["text"])][part.words[t]["after"]] += 1

    def _pc(self, p):
        return {"text": strip_marks(p["text"]) if self.strip else p["text"], "kind": p["kind"],
                "lexeme": p["lexeme"], "class": p["class"], "marks": p["marks"], "m": p["m"]}

    def find(self, lexeme, want, suf, pre_lex, step):
        """step 'whole' or 'joined'. Returns (text or tail, entry) or None."""
        cnt, rep = Counter(), {}
        for e in self.by_lex.get(lexeme, ()):
            if e["suf"] != suf or not marks_agree(want, e["marks"]):
                continue
            if step == "whole":
                if e["pre_lex"] != pre_lex:
                    continue
                k = e["text"]
            else:
                k = e["tail"]
            cnt[k] += 1
            rep.setdefault(k, e)
        if not cnt:
            return None
        k = min(cnt, key=lambda x: (-cnt[x], x))
        return k, rep[k]


class Forms:
    """The form sources per text (6.5): hbo the whole Tanakh; an edition its own strict words, then the Tanakh."""

    def __init__(self, parts):
        tan = [parts["hbo"], parts["arc"]]
        self.tanakh = FormSource(tan)
        self.chain = {"hbo": [(self.tanakh, "whole", "joined")]}
        self.chain["heb_mod"] = [(FormSource([parts["heb_mod"]], strict_only=True), "whole", "joined"),
                                 (FormSource(tan, strip=True), "whole_tanakh", "joined_tanakh")]
        self.chain["heb_scg"] = [(FormSource([parts["heb_scg"]], strict_only=True), "whole", "joined"),
                                 (self.tanakh, "whole_tanakh", "joined_tanakh")]

    def af(self, text, lexeme, want, suf, pre_pieces, fused):
        """Rule AF. pre_pieces: the source word's prefix pieces (copied as they stand under `joined`).
        Returns (form_rule, pieces) or None; pieces are dicts with text, kind, lexeme, class, marks, m, and 'role'
        ('pre' for a prefix of the form, 'stem', 'suf')."""
        pre_lex = tuple(p["lexeme"] for p in pre_pieces)
        for src, r_whole, r_joined in self.chain[text]:
            hit = src.find(lexeme, want, suf, pre_lex, "whole")
            if hit:
                e = hit[1]
                return r_whole, [dict(p, role=("pre" if i < e["pre_n"] else "stem" if p["kind"] == "stem" else "suf"))
                                 for i, p in enumerate(e["pieces"])]
            if fused:
                continue
            hit = src.find(lexeme, want, suf, pre_lex, "joined")
            if hit:
                e = hit[1]
                pre = [{"text": p["text"], "kind": p["kind"], "lexeme": p["lexeme"], "class": p["class"],
                        "marks": p["marks"], "m": p["m"], "role": "pre", "src": (p["t"], p["n"])} for p in pre_pieces]
                tail = [dict(p, role=("stem" if p["kind"] == "stem" else "suf")) for p in e["pieces"][e["pre_n"]:]]
                return r_joined, pre + tail
        return None

    def free_after(self, text, lexeme, form_text):
        """The commonest `after` of an attested free form (7.2): maqaf or a space."""
        for src, _, _ in self.chain[text]:
            c = src.after.get((lexeme, nfc(form_text)))
            if c:
                a = min(c, key=lambda x: (-c[x], x))
                return "־" if a == "־" else " "
        return " "


# ------------------------------------------------------------------ rule NF (6.6)

class Names:
    def __init__(self, parts):
        self.idx = {}
        for name, part in parts.items():
            idx = defaultdict(list)
            for t in sorted(part.words):
                ps = part.pieces[t]
                st = [p for p in ps if p["kind"] == "stem"]
                if len(st) != 1 or st[0]["class"] != "noun" or not strict_who(st[0]):
                    continue
                s = st[0]
                if s["m"].get("state", "abs") not in ("abs", ""):
                    continue
                if any(p["kind"] == "suffix" for p in ps) or any(p["fused"] for p in ps):
                    continue
                art = [p for p in ps if p["kind"] == "prefix" and p["class"] == "art"]
                pcs = art[-1:] + [s]
                ntext = "".join(p["text"] for p in pcs)
                proper = s["m"].get("type") == "proper"
                for e in ents(s["who"]):
                    idx[e].append((proper, ntext, t, pcs))
            self.idx[name] = idx

    def nf(self, ent, chain):
        """chain: the part names in order. Returns dict(text, pieces, definite) or None."""
        for name in chain:
            rows = self.idx.get(name, {}).get(ent)
            if not rows:
                continue
            for proper in (True, False):
                rs = [r for r in rows if r[0] == proper]
                if not rs:
                    continue
                cnt, first = Counter(), {}
                for r in rs:
                    cnt[r[1]] += 1
                    first.setdefault(r[1], r)
                best = min(cnt, key=lambda x: (-cnt[x], first[x][2]))
                r = first[best]
                pcs = [{"text": p["text"], "kind": p["kind"], "lexeme": p["lexeme"], "class": p["class"],
                        "marks": p["marks"], "m": p["m"]} for p in r[3]]
                return {"text": best, "pieces": pcs, "definite": proper or len(pcs) > 1, "proper": proper}
        return None


def nf_chain(text, part_name):
    if text == "hbo":
        return ("arc", "hbo") if part_name == "arc" else ("hbo",)
    return (text,)


# ------------------------------------------------------------------ the draft under construction

class Draft:
    """Source words in text order; each may be replaced by new words (`body`) and followed by inserted words."""

    def __init__(self, T):
        self.T = T
        self.body = {}             # src t -> [word]; word = {"pieces": [...], "op": tmp, "after": preset or None}
        self.ins = defaultdict(list)   # src t -> [(slot, seq, word)]
        self.writer = {}           # src t -> (switch, tmp) of the op that wrote the body
        self.cur_stem = {}         # src t -> the stem piece now standing (after V)
        self.seq = 0

    def insert(self, t, slot, word):
        self.seq += 1
        self.ins[t].append((slot, self.seq, word))


def src_piece_dict(p, part, how="copy"):
    return {"text": p["text"], "kind": p["kind"], "lexeme": p["lexeme"], "class": p["class"], "marks": p["marks"],
            "m": p["m"], "who": p["who"], "who_basis": p["who_basis"],
            "links": [(part, p["t"], p["n"], how)]}


def new_piece(p, who, who_basis, links):
    return {"text": p["text"], "kind": p["kind"], "lexeme": p["lexeme"], "class": p["class"], "marks": p["marks"],
            "m": p["m"], "who": who, "who_basis": who_basis, "links": links}


def name_pieces(nf, ent, links):
    return [new_piece(p, ent, "inserted", list(links)) for p in nf["pieces"]]


class Ctx:
    """What the switches read: the text, its parts, forms, names, the stage-42 tables."""

    def __init__(self, T, forms, names, W):
        self.T, self.forms, self.names, self.W = T, forms, names, W
        self.catch_all = set()
        for part in T.parts.values():
            by = {}
            for p_list in part.pieces.values():
                for p in p_list:
                    by[(p["t"], p["n"])] = p
            for r in part.who_account:
                if r["state"] == "generic":
                    p = by.get((r["t"], r["n"]))
                    if p is not None:
                        es = ents(p["who"])
                        if len(es) == 1:
                            self.catch_all.add(es[0])
            part._by = by


# ------------------------------------------------------------------ the stage-42 tables a switch reads

class Words42:
    def __init__(self, build):
        self.lev = {r["lexeme"]: r for r in read_tsv(build / "words" / "levels.tsv")}
        ex = pq.read_table(build / "words" / "explanations.parquet").to_pylist()
        self.lex_one = defaultdict(list)     # X -> [(Y, x_key)]
        self.phrase = Counter()              # X -> multi-word meaning statements
        for r in ex:
            if r["kind"] != "meaning" or r["x_state"] != "resolved" or not r["x_lexeme"]:
                continue
            yc = json.loads(r["y_content"])
            if r["one_word"] and len(yc) == 1:
                self.lex_one[r["x_lexeme"]].append((yc[0], r["x_key"]))
            else:
                self.phrase[r["x_lexeme"]] += 1
        self.group_head, self.senses_out = {}, {}
        g = pq.read_table(I1 / "lexicon" / "groups.parquet").to_pylist()
        heads = {r["group"]: r["lexeme"] for r in g if r["head"] and r["basis"] == "derived"}
        for r in g:
            if r["basis"] != "derived" or r["head"] or r["group"] not in heads:
                continue
            self.group_head[r["lexeme"]] = heads[r["group"]]
            self.senses_out[r["lexeme"]] = set(json.loads(r["senses_out"] or "[]"))
        self.groups = defaultdict(set)
        for r in g:
            if r["basis"] == "derived":
                self.groups[r["lexeme"]].add(r["group"])
        self.dist = {(r["a"], r["b"]): r for r in pq.read_table(build / "near" / "distance.parquet").to_pylist()}
        self.routes_all = defaultdict(set)
        indep = defaultdict(set)
        for r in pq.read_table(build / "near" / "pairs.parquet").to_pylist():
            ab = (r["a"], r["b"])
            self.routes_all[ab].add(r["route"])
            if r["basis"] == "model":
                continue
            if r["route"] == "lex" and r["meaning"]:
                indep[ab].add("lex")
            elif r["route"] in ("nt2", "rend"):
                indep[ab].add(r["route"])
        self.syn = defaultdict(list)          # X -> [(Y, chosen_by)]
        for ab, d in self.dist.items():
            if d["grade_strict"] == "d3" and len(indep.get(ab, ())) >= 2:
                cb = json.loads(d["routes_strict"])
                self.syn[ab[0]].append((ab[1], cb))
                self.syn[ab[1]].append((ab[0], cb))

    def level(self, lx):
        r = self.lev.get(lx)
        return int(r["level"]) if r and r["level"] != "" else None

    def grade(self, a, b):
        if a == b:
            return "d0"
        k = (a, b) if a < b else (b, a)
        d = self.dist.get(k)
        return d["grade"] if d else "d6"

    def ok_candidate(self, x, y):
        rx, ry = self.lev.get(x), self.lev.get(y)
        lv = self.level(y)
        return (y != x and ry is not None and lv is not None and lv <= K and ry["class"] == rx["class"]
                and ry["lang"] == rx["lang"])


# ------------------------------------------------------------------ switch V (6.2)

def tanakh_senses_at(T, ctx_parts, x, key):
    out = set()
    for part in ctx_parts:
        for t in part.verse_index.get(key, ()):
            for p in part.pieces[t]:
                if p["kind"] == "stem" and p["lexeme"] == x and single_sense(p["sense"]):
                    out.add(p["sense"])
    return out


def v_places(ctx):
    T, W = ctx.T, ctx.W
    out = []
    for pn, t in T.order:
        for p in T.parts[pn].pieces[t]:
            if p["kind"] != "stem" or p["class"] not in CONTENT or not strict_piece(p):
                continue
            r = W.lev.get(p["lexeme"])
            if not r or r["state"] in ("name", "function") or r["kind"] not in ("explained", "unexplained"):
                continue
            lv = W.level(p["lexeme"])
            if lv is not None and lv > K:
                out.append((pn, t, p))
    return out


def v_candidates(ctx, pn, t, p, sense_at):
    """The tiers of 6.2 in order. Returns [(tier, Y, chosen_by)], detail."""
    T, W = ctx.T, ctx.W
    x = p["lexeme"]
    tanakh = T.code == "hbo"
    ps = single_sense(p["sense"]) if tanakh else ""
    one_sense = W.lev[x]["senses"] == "1"
    tiers, detail = [], {}
    lex = set()
    for y, xk in W.lex_one.get(x, ()):
        if not W.ok_candidate(x, y):
            continue
        cover = one_sense
        if tanakh and not cover:
            if xk == T.key(t):
                cover = True
            elif ps and ps in sense_at(x, xk):
                cover = True
        if cover:
            lex.add(y)
    detail["lex"] = len(lex)
    for y in sorted(lex, key=lambda y: (-int(W.lev[y]["count"]), y)):
        tiers.append(("lex", y, ["lex"]))
    grp = []
    h = W.group_head.get(x)
    if h and W.ok_candidate(x, h) and not (ps and ps in W.senses_out.get(x, set())):
        grp.append(h)
    detail["grp"] = len(grp)
    for y in grp:
        tiers.append(("grp", y, ["grp", "lxx"]))
    syn = {}
    for y, cb in W.syn.get(x, ()):
        if W.ok_candidate(x, y):
            syn[y] = cb
    detail["syn"] = len(syn)
    for y in sorted(syn, key=lambda y: (-int(W.lev[y]["count"]), y)):
        tiers.append(("syn", y, syn[y]))
    if W.phrase.get(x):
        detail["phrase_only"] = W.phrase[x]
    return tiers, detail


def word_parts(ps):
    pre = [p for p in ps if p["kind"] == "prefix"]
    suf = [p for p in ps if p["kind"] == "suffix"]
    st = [p for p in ps if p["kind"] == "stem"][0]
    return pre, st, suf


def suf_sig(suf):
    return tuple((p["m"].get("person", ""), p["m"].get("gender", ""), p["m"].get("number", "")) for p in suf)


def build_word_from_af(pn, ps, af_pieces, stem_who, stem_basis):
    """The pieces of a word written by AF over a source word: prefixes and suffixes keep the source's who and link
    to themselves (copy); the stem links to the source stem (replace)."""
    pre, st, suf = word_parts(ps)
    out, ip, isuf = [], 0, 0
    for q in af_pieces:
        if q["role"] == "pre":
            s = pre[ip] if ip < len(pre) else None
            ip += 1
            out.append({"text": q["text"], "kind": "prefix", "lexeme": s["lexeme"] if s else q["lexeme"],
                        "class": s["class"] if s else q["class"], "marks": s["marks"] if s else q["marks"],
                        "m": s["m"] if s else q["m"], "who": s["who"] if s else "", "who_basis": s["who_basis"] if s else "",
                        "links": [(pn, s["t"], s["n"], "copy")] if s else [(pn, st["t"], st["n"], "replace")]})
        elif q["role"] == "stem":
            out.append(new_piece(q, stem_who, stem_basis, [(pn, st["t"], st["n"], "replace")]))
        else:
            s = suf[isuf] if isuf < len(suf) else None
            isuf += 1
            out.append({"text": q["text"], "kind": "suffix", "lexeme": s["lexeme"] if s else q["lexeme"],
                        "class": s["class"] if s else q["class"], "marks": s["marks"] if s else q["marks"],
                        "m": s["m"] if s else q["m"], "who": s["who"] if s else "", "who_basis": s["who_basis"] if s else "",
                        "links": [(pn, s["t"], s["n"], "copy")] if s else [(pn, st["t"], st["n"], "replace")]})
    return out


def switch_v(ctx, D, ops, level):
    T, W = ctx.T, ctx.W
    cache = {}

    def sense_at(x, key):
        if (x, key) not in cache:
            cache[(x, key)] = tanakh_senses_at(T, [T.parts["hbo"], T.parts["arc"]] if "hbo" in T.parts else [], x, key) \
                if T.code == "hbo" else set()
        return cache[(x, key)]

    for pn, t, p in v_places(ctx):
        ps = T.parts[pn].pieces[t]
        op = base_op(T, level, "v", "k2", t, p["n"])
        op["lexeme_before"] = p["lexeme"]
        op["before"] = T.word(t)["text"]
        tiers, detail = v_candidates(ctx, pn, t, p, sense_at)
        op["detail"] = detail
        fused = any(q["fused"] for q in ps)
        if not tiers:
            op["reason"] = "no_candidate"
            ops.append(op)
            continue
        want = {k: p["m"][k] for k in MARK_KEYS if p["m"].get(k)}
        pre, st, suf = word_parts(ps)
        hit = None
        for tier, y, cb in tiers:
            r = ctx.forms.af(T.code, y, want, suf_sig(suf), pre, fused)
            if r:
                hit = (tier, y, cb, r)
                break
        if not hit:
            op["reason"] = "fused_article" if fused else "no_form"
            ops.append(op)
            continue
        tier, y, cb, (rule, pcs) = hit
        new = build_word_from_af(pn, ps, pcs, p["who"], p["who_basis"])
        op.update(state="applied", rule="v_" + tier, tier=tier, chosen_by=cb, lexeme_after=y,
                  routes_all=sorted(W.routes_all.get((min(p["lexeme"], y), max(p["lexeme"], y)), ())),
                  grade=W.grade(p["lexeme"], y), form_rule=rule)
        word = {"pieces": new, "op": len(ops), "after": None}
        D.body[t] = [word]
        D.writer[t] = ("v", len(ops))
        D.cur_stem[t] = [q for q in new if q["kind"] == "stem"][0]
        op["_words"] = [word]
        ops.append(op)


def base_op(T, level, switch, setting, t, n):
    w = T.word(t)
    return {"level": level, "text": T.code, "switch": switch, "setting": setting,
            "key": vkey(w["book"], w["chapter"], w["verse"]), "scoring_closed": scoring_closed(w["book"], w["chapter"]),
            "src_t": t, "src_n": n, "added_clause": "", "added_role": "", "state": "not_applied", "reason": "",
            "detail": {}, "rule": "", "before": "", "after": "", "lexeme_before": "", "lexeme_after": "", "ent": "",
            "tier": "", "chosen_by": None, "routes_all": None, "grade": "", "form_rule": "", "_words": []}


# ------------------------------------------------------------------ switch R (6.3)

def r_places(ctx):
    T = ctx.T
    out = []
    for pn, part in T.parts.items():
        for r in part.who_account:
            if r["t"] not in T.scope or r["head_kind"] not in ("pronoun", "suffix", "verb_zero"):
                continue
            if r["state"] != "participant":
                continue
            p = part._by.get((r["t"], r["n"]))
            if p is None or p["m"].get("person") != "3":
                continue
            out.append((pn, r, p))
    out.sort(key=lambda x: (x[1]["t"], x[1]["n"]))
    return out


def head_gn(p):
    return p["m"].get("gender", ""), p["m"].get("number", "")


def gn_agree(hg, hn, g, n):
    okg = (not hg) or gmatch(hg, g)
    okn = (not hn) or hn == n
    return okg and okn


def window_candidates(ctx, pn, t, p, head_ents):
    part = ctx.T.parts[pn]
    cl = part.words[t]["clause"]
    if not cl or cl not in part.clause_rank:
        return []
    i = part.clause_rank[cl]
    win = part.clause_order[max(0, i - 2): i + 1]
    hg, hn = head_gn(p)
    cands = set()
    for c in win:
        for wt in part.words_by_clause.get(c, ()):
            for q in part.pieces[wt]:
                if q["kind"] != "stem" or q["class"] != "noun" or not strict_who(q):
                    continue
                g, n = q["m"].get("gender", ""), q["m"].get("number", "")
                if not g or not n or not gn_agree(hg, hn, g, n):
                    continue
                for e in ents(q["who"]):
                    if e not in head_ents:
                        cands.add(e)
    return sorted(cands)


def named_in_clause(ctx, pn, t, ent):
    part = ctx.T.parts[pn]
    cl = part.words[t]["clause"]
    if not cl:
        return False
    for wt in part.words_by_clause.get(cl, ()):
        for q in part.pieces[wt]:
            if q["kind"] == "stem" and q["class"] == "noun" and strict_who(q) and ent in ents(q["who"]):
                return True
    return False


def r_rule(ctx, D, pn, r, p):
    """The host rule of 6.3, or a host reason."""
    if r["head_kind"] == "verb_zero":
        return "r_subject"
    if r["head_kind"] == "pronoun":
        return "r_pronoun"
    t = r["t"]
    st = D.cur_stem.get(t) or ctx.T.parts[pn].stem(t)
    c = st["class"]
    if c in ("prep", "om"):
        return "r_prep"
    if c == "noun":
        return "r_construct"
    if c == "verb":
        ty = st["m"].get("type", "")
        if ty in FINITE:
            return "r_object"
        if ty in INFINITIVE:
            return "host_infinitive"
        if ty in PARTICIPLE:
            return "host_participle"
    return "host_other"


def om_lexeme(forms):
    cnt = Counter()
    for lx, es in forms.tanakh.by_lex.items():
        for e in es:
            if e["pieces"][e["pre_n"]]["class"] == "om":
                cnt[lx] += 1
    return min(cnt, key=lambda x: (-cnt[x], x))


def free_form(ctx, lexeme, pre_pieces):
    """The free form of a preposition or object marker for r_prep_free (6.3): AF with no suffix. Stage 44: a `joined`
    form counts only where its stem text stands in the form source as a bare word of the lexeme (no prefix, no suffix).
    Without this, the stem piece of one bound word (בְּשֶׁל, JON 1:7) gave ל a "free form" ל, and R wrote a lone
    ל before the name (432 ops); 6.3 names ל, ב, כ as prepositions with no free form (r_prep_bound)."""
    hit = ctx.forms.af(ctx.T.code, lexeme, {}, (), pre_pieces, any(q.get("fused") for q in pre_pieces))
    if hit is None or not hit[0].startswith("joined"):
        return hit
    tail = strip_marks(nfc("".join(q["text"] for q in hit[1] if q["role"] != "pre")))
    for src, _, _ in ctx.forms.chain[ctx.T.code]:
        if any(e["pre_n"] == 0 and e["suf"] == () and strip_marks(e["text"]) == tail
               for e in src.by_lex.get(lexeme, ())):
            return hit
    return None


def word_text(pieces):
    return "".join(q["text"] for q in pieces)


def switch_r(ctx, D, ops, level, setting, om_lx):
    T = ctx.T
    for pn, r, p in r_places(ctx):
        t = r["t"]
        part = T.parts[pn]
        op = base_op(T, level, "r", setting, t, r["n"])
        op["before"] = T.word(t)["text"]
        es = ents(p["who"])
        op["ent"] = " ".join(es)
        hk = r["head_kind"]
        model = r.get("basis") == "model" or not strict_piece(p) or p["who_basis"] == "model"
        stp = part.stem(t)
        if hk == "suffix" and stp is not None and not strict_piece(stp):
            model = True
        cands = window_candidates(ctx, pn, t, p, set(es)) if not model else []
        op["detail"] = cands
        reason = ""
        if model:
            reason = "model_input"
        elif len(es) != 1:
            reason = "several_referents"
        elif es[0] in ctx.catch_all:
            reason = "catch_all"
        elif named_in_clause(ctx, pn, t, es[0]):
            reason = "named_in_clause"
        elif setting == "amb" and not cands:
            reason = "not_ambiguous"
        nf = None
        rule = ""
        if not reason:
            nf = ctx.names.nf(es[0], nf_chain(T.code, pn))
            rule = r_rule(ctx, D, pn, r, p)
            if nf is None:
                reason = "no_name_form"
            elif rule == "r_object" and not nf["definite"]:
                reason = "indefinite"
            elif rule.startswith("host_"):
                reason = rule
        if reason:
            op["reason"] = reason
            ops.append(op)
            continue
        ent = es[0]
        tmp = len(ops)
        ps = part.pieces[t]
        cur = D.body[t][0]["pieces"] if t in D.body else None
        host_pieces = cur if cur is not None else [src_piece_dict(q, pn) for q in ps]
        pre = [q for q in host_pieces if q["kind"] == "prefix"]
        written, form_rule = [], "nf"
        head_link = (pn, r["t"], r["n"])
        if rule == "r_subject":
            w = {"pieces": name_pieces(nf, ent, [head_link + ("insert",)]), "op": tmp, "after": None}
            D.insert(t, 0, w)
            written = [w]
        elif rule == "r_pronoun":
            new = [dict(q) for q in pre] + name_pieces(nf, ent, [head_link + ("replace",)])
            w = {"pieces": new, "op": tmp, "after": None}
            D.body[t] = [w]
            D.writer[t] = ("r", tmp)
            written = [w]
        elif rule == "r_prep":
            st = D.cur_stem.get(t) or part.stem(t)
            spre = [q for q in ps if q["kind"] == "prefix"]
            ff = free_form(ctx, st["lexeme"], spre)
            if ff:
                rule = "r_prep_free"
                form_rule = ff[0]
                fw_pieces = build_word_from_af(pn, ps, ff[1], st["who"], st["who_basis"])
                fw_pieces = [q for q in fw_pieces if q["kind"] != "suffix"]
                fw = {"pieces": fw_pieces, "op": tmp,
                      "after": T.code == "hbo" and ctx.forms.free_after(T.code, st["lexeme"], word_text(ff[1])) or None}
                nw = {"pieces": name_pieces(nf, ent, [head_link + ("replace",)]), "op": tmp, "after": None}
                D.body[t] = [fw, nw]
                D.writer[t] = ("r", tmp)
                written = [fw, nw]
            elif st["class"] == "prep":
                rule = "r_prep_bound"
                got = bound_form(ctx, pn, ps, st, nf, ent, head_link, tmp)
                if got is None:
                    op["reason"] = "form_unattested"
                    ops.append(op)
                    continue
                form_rule, w = got
                D.body[t] = [w]
                D.writer[t] = ("r", tmp)
                written = [w]
            else:
                op["reason"] = "form_unattested"
                ops.append(op)
                continue
        elif rule == "r_construct":
            st = D.cur_stem.get(t) or part.stem(t)
            want = {"state": "cstr"}
            for k in ("number", "gender"):
                if st["m"].get(k):
                    want[k] = st["m"][k]
            spre = [q for q in ps if q["kind"] == "prefix"]
            hit = ctx.forms.af(T.code, st["lexeme"], want, (), spre, any(q["fused"] for q in ps))
            if not hit:
                op["reason"] = "form_unattested"
                ops.append(op)
                continue
            form_rule = hit[0]
            cw = build_word_from_af(pn, ps, hit[1], st["who"], st["who_basis"])
            cw = [q for q in cw if q["kind"] != "suffix"]
            if t in D.body:   # V replaced the host (6.9): the construct form is of the lexeme V wrote
                op["_over_v"] = True
            w1 = {"pieces": cw, "op": tmp, "after": None}
            nw = {"pieces": name_pieces(nf, ent, [head_link + ("replace",)]), "op": tmp, "after": None}
            D.body[t] = [w1, nw]
            D.writer[t] = ("r", tmp)
            written = [w1, nw]
        elif rule == "r_object":
            ff = ctx.forms.af(T.code, om_lx, {}, (), [], False)
            if not ff:
                op["reason"] = "form_unattested"
                ops.append(op)
                continue
            form_rule = ff[0]
            omp = [new_piece(q, "", "", [head_link + ("insert",)]) for q in ff[1] if q["role"] == "stem"]
            ow = {"pieces": omp, "op": tmp,
                  "after": "־" if T.code == "hbo" else None}
            nw = {"pieces": name_pieces(nf, ent, [head_link + ("insert",)]), "op": tmp, "after": None}
            D.insert(t, 1, ow)
            D.insert(t, 1, nw)
            written = [ow, nw]
        op.update(state="applied", rule=rule, form_rule=form_rule)
        op["_words"] = written
        ops.append(op)


def bound_form(ctx, pn, ps, st, nf, ent, head_link, tmp):
    """r_prep_bound: an attested whole word = host prefixes + the preposition as a prefix + NF's pieces."""
    T = ctx.T
    hpre = [q for q in ps if q["kind"] == "prefix"]
    base_pre = tuple(q["lexeme"] for q in hpre) + (st["lexeme"],)
    want_pre = base_pre + tuple(q["lexeme"] for q in nf["pieces"][:-1])
    has_art = len(nf["pieces"]) > 1
    nst = nf["pieces"][-1]
    for src, r_whole, _ in ctx.forms.chain[T.code]:
        cnt, rep = Counter(), {}
        for e in src.by_lex.get(nst["lexeme"], ()):
            if e["suf"] != ():
                continue
            # the article of NF stands as its own piece, or is fused into the preposition (לַ, בַּ, כַּ)
            if not ((e["pre_lex"] == want_pre and not e["fused"])
                    or (has_art and e["fused"] and e["pre_lex"] == base_pre)):
                continue
            if e["marks"].get("state", "abs") not in ("abs", ""):
                continue
            cnt[e["text"]] += 1
            rep.setdefault(e["text"], e)
        if cnt:
            k = min(cnt, key=lambda x: (-cnt[x], x))
            e = rep[k]
            out = []
            for i, q in enumerate(e["pieces"]):
                if i < len(hpre):
                    s = hpre[i]
                    out.append({"text": q["text"], "kind": "prefix", "lexeme": s["lexeme"], "class": s["class"],
                                "marks": s["marks"], "m": s["m"], "who": s["who"], "who_basis": s["who_basis"],
                                "links": [(pn, s["t"], s["n"], "copy")]})
                elif i == len(hpre):
                    out.append(new_piece(q, st["who"], st["who_basis"], [(pn, st["t"], st["n"], "replace")]))
                else:
                    out.append(new_piece(q, ent, "inserted", [head_link + ("replace",)]))
            return r_whole, {"pieces": out, "op": tmp, "after": None}
    if nf["proper"] and len(nf["pieces"]) == 1:
        ptxt = commonest_prefix(ctx, st["lexeme"])
        if ptxt is None:
            return None
        out = [{"text": s["text"], "kind": "prefix", "lexeme": s["lexeme"], "class": s["class"], "marks": s["marks"],
                "m": s["m"], "who": s["who"], "who_basis": s["who_basis"], "links": [(pn, s["t"], s["n"], "copy")]}
               for s in hpre]
        out.append({"text": ptxt, "kind": "prefix", "lexeme": st["lexeme"], "class": st["class"], "marks": "{}", "m": {},
                    "who": st["who"], "who_basis": st["who_basis"], "links": [(pn, st["t"], st["n"], "replace")]})
        out += name_pieces(nf, ent, [head_link + ("replace",)])
        return "joined", {"pieces": out, "op": tmp, "after": None}
    return None


_PREFIX_CACHE = {}


def commonest_prefix(ctx, lexeme):
    key = (ctx.T.code, lexeme)
    if key not in _PREFIX_CACHE:
        cnt = Counter()
        parts = list(ctx.T.parts.values()) if ctx.T.code != "hbo" else [ctx.T.parts["hbo"], ctx.T.parts["arc"]]
        for part in parts:
            for t in sorted(part.pieces):
                for q in part.pieces[t]:
                    if q["kind"] == "prefix" and q["lexeme"] == lexeme and strict_piece(q):
                        cnt[q["text"]] += 1
        _PREFIX_CACHE[key] = min(cnt, key=lambda x: (-cnt[x], x)) if cnt else None
    return _PREFIX_CACHE[key]


# ------------------------------------------------------------------ switch A (6.4)

def added_code(terms):
    return {r["hbo"]: r["code"] for r in terms if r["category"] == "added_kind"}


def a_places(ctx, kind_code):
    T = ctx.T
    out = []
    for pn, part in T.parts.items():
        for i, r in enumerate(part.added):
            if r["verb"] not in T.scope:
                continue
            if kind_code.get(r["kind"]) in ("in_verb", "elsewhere"):
                out.append((pn, i, r))
    out.sort(key=lambda x: (x[2]["verb"], x[2]["role"], x[2]["clause"]))
    return out


def switch_a(ctx, D, ops, level, kind_code, om_lx, r_subjects):
    T = ctx.T
    for pn, _, r in a_places(ctx, kind_code):
        part = T.parts[pn]
        st = part.stem(r["verb"])
        op = base_op(T, level, "a", "", r["verb"], st["n"])
        op["added_clause"], op["added_role"] = r["clause"], r["role"]
        op["before"] = T.word(r["verb"])["text"]
        es = ents(r["who"])
        op["ent"] = " ".join(es)
        subj = r["role"] == part._subj_role[(r["verb"], r["clause"])]
        reason = ""
        if r.get("own_basis") == "model":
            reason = "model_input"
        elif not es:
            reason = "no_who"
        elif len(es) > 1:
            reason = "several_referents"
        elif r["person"] in ("1", "2"):
            reason = "person_1_2"
        elif said_in_clause(part, r, es):
            reason = "said_in_clause"
        elif subj and r["verb"] in r_subjects:
            reason = "taken_by_r"
        elif not subj and r["role"] != "A1":
            reason = "role_other"
        nf = None
        if not reason:
            nf = ctx.names.nf(es[0], nf_chain(T.code, pn))
            if nf is None:
                reason = "no_name_form"
            elif not subj and not nf["definite"]:
                reason = "indefinite"
        ff = None
        if not reason and not subj:
            ff = ctx.forms.af(T.code, om_lx, {}, (), [], False)
            if not ff:
                reason = "form_unattested"
        if reason:
            op["reason"] = reason
            ops.append(op)
            continue
        tmp = len(ops)
        link = (pn, st["t"], st["n"], "insert")
        nw = {"pieces": name_pieces(nf, es[0], [link]), "op": tmp, "after": None}
        if subj:
            D.insert(r["verb"], 0, nw)
            written, rule, form_rule = [nw], "a_subject", "nf"
        else:
            omp = [new_piece(q, "", "", [link]) for q in ff[1] if q["role"] == "stem"]
            ow = {"pieces": omp, "op": tmp, "after": "־" if T.code == "hbo" else None}
            D.insert(r["verb"], 1, ow)
            D.insert(r["verb"], 1, nw)
            written, rule, form_rule = [ow, nw], "a_object", ff[0]
        op.update(state="applied", rule=rule, form_rule=form_rule)
        op["_words"] = written
        ops.append(op)


def said_in_clause(part, r, es):
    for wt in part.words_by_clause.get(r["clause"], ()):
        if wt == r["verb"]:
            continue
        for q in part.pieces[wt]:
            if set(ents(q["who"])) & set(es):
                return True
    return False


def prepare_a(T):
    """The subject role of every (verb, clause) of `added` (SPEC.md 4.11)."""
    for part in T.parts.values():
        aa = {(r["verb"], r["clause"]) for r in part.added if r["role"] == "AA"}
        part._subj_role = {}
        for r in part.added:
            k = (r["verb"], r["clause"])
            if k in part._subj_role:
                continue
            st = part.stem(r["verb"])
            stem = st["m"].get("stem", "") if st else ""
            has_aa = k in aa or any("AA" in re.split(r"[^A-Za-z0-9]+", c["frame_role"] or "")
                                    for c in part.constituents.get(r["clause"], ()))
            part._subj_role[k] = "AA" if (stem in CAUSATIVE and has_aa) else "A0"


# ------------------------------------------------------------------ assembling a level

def run_level(ctx, level, kind_code, om_lx):
    """Returns (draft words in order, ops) for one (level, text)."""
    T = ctx.T
    D = Draft(T)
    ops = []
    switches = LEVELS[level][0]
    for sw in switches:
        if sw == "v":
            switch_v(ctx, D, ops, level)
        elif sw.startswith("r_"):
            switch_r(ctx, D, ops, level, sw[2:], om_lx)
        elif sw == "a":
            r_subj = {o["src_t"] for o in ops if o["switch"] == "r" and o["rule"] == "r_subject"}
            switch_a(ctx, D, ops, level, kind_code, om_lx, r_subj)
    words = assemble(T, D)
    return words, ops


def assemble(T, D):
    out = []
    for pn, t in T.order:
        w = T.parts[pn].words[t]
        if t in D.body:
            body = D.body[t]
        else:
            body = [{"pieces": [src_piece_dict(q, pn) for q in T.parts[pn].pieces[t]], "op": None, "after": None,
                     "copy": True}]
        ins = [x[2] for x in sorted(D.ins.get(t, ()), key=lambda x: (x[0], x[1]))]
        seq = body + ins
        for i, dw in enumerate(seq):
            last = i == len(seq) - 1
            if T.code != "hbo":
                after = ""
            elif last:
                after = w["after"]
            else:
                after = dw["after"] or " "
            text = w["text"] if dw.get("copy") else word_text(dw["pieces"])
            out.append({"src": w, "part": pn, "text": text, "after": after, "pieces": dw["pieces"], "op": dw["op"],
                        "obj": dw})
    return out
