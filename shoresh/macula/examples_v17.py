"""Stage 49 (SPEC 1.7): the two Hebrew New Testaments as descriptions of their own, `<build>/heb_mod/`, `heb_scg/`.

    build_examples.py --build i1 --stage 49

1. Section 13: copies `hbo`, `arc`, `grc`, `other/`, `lexicon/` from `h1` into the build, file by file, and checks
   every sha256 against `h1` (`VALIDATION.md` included: it is the file of `h1`). The 1.6 builders' scratch that the
   1.6 validator reads (`cache/morphid.parquet`, `cache/speech-*`, `cache/stage*-counts.json`) is copied too.
2. 4.15, D29 to D44: every table of the two edition folders, from the build's own `grc` tables (Greek is read from
   nowhere else), `other/<edition>/`, `hebrew-nt-analysis` v0.2 (`form`, `person`), the build's `hbo`, `arc` pieces
   (the D36 lookup) and `lexicon/lexemes.tsv`. The statement tables and the small files: `examples_v17doc.py`.

Readings where the specification leaves a choice (each is in the report of stage 49, "For the specification"):
- D30 `pred`: the Hebrew words linked to the Greek `pred` are taken only where they stand in the clause or below it
  (else 0, counted), so that `pred` lies inside the clause's span.
- D35: a `pron` part is a suffix when any part before it in the word is of a class other than cj, art, rel.
- D37 (c): the edge is read over the clause's own words in text order; a connective goes to `marks_model` where a
  part collected or the part that ends the edge is `model`; a negator where its own part is `model`.
- D38: `head` is the word linked to the Greek head only (a D34 b suffix is not a link), so `ref_form` `suffix` is
  never written; the parts whose Greek head was carried to a suffix are counted.
- D39: `clause` is the clause in which the Hebrew verb stands (`words.clause`); where it is not the carried clause of
  the Greek row's clause, counted.
- D40: a piece that is both a noun or pronoun head and a `verb_zero` head takes the first kind (one row per piece).
- D42: `state_model` is written on stem pieces only (the links stand on stem pieces).
- D44: the account of a carried column on the Greek side is written under the table name `grc/<table>`.
"""
import collections as C
import hashlib
import json
import os
import shutil
import sys
import time
import unicodedata

import pyarrow as pa
import pyarrow.parquet as pq

import examples_common as X

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ANA = os.path.join(ROOT, "internal-docs/hebrew-nt-analysis-release/v0.2")
TERMS = os.path.join(ROOT, "internal-docs/source-examples-spec/terms.tsv")
ENTITIES = os.path.join(HERE, "data/entities/entities.tsv")
EDS = ("heb_mod", "heb_scg")
COPIED = ("hbo", "arc", "grc", "other", "lexicon")
CACHE_COPIED = ("morphid.parquet", "speech-grc", "speech-hbo", "speech-hbo-review")
OPENER = {"cj", "rel", "prep", "om", "art"}
NOT_HOST = {"cj", "art", "rel"}
WHO_CLASSES = {"noun", "verb", "adj", "pron", "num"}
CONTENT = {"noun", "verb", "adj", "adv"}
NEG_HBO = {"לֹא", "אַיִן", "אַל", "בֵּלֶת", "בַּל"}
NEG_ARC = {"לָא"}
CARRIED_TERMS = ("relation", "time", "aspect", "line_kind", "mood")
CARRIED_CODES = ("force", "polarity")
NOT_CARRIED_KEYS = ("kind", "voice", "transitivity", "subject_form", "subject_switch", "fronted", "neg_scope")
ABS = {"past", "present", "future", "timeless", "irrealis"}
REFFORM = {"noun": "noun", "pron": "pronoun", "adj": "adjective", "num": "number"}
SHARE = 0.9


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def files_under(d):
    out = []
    for root, _dirs, fs in os.walk(d):
        for f in fs:
            out.append(os.path.relpath(os.path.join(root, f), d))
    return sorted(out)


# ---- 1. the copied folders -------------------------------------------------------------------------------------------

def copy_folders(outdir, src, cnt):
    """Section 13: every file of the five folders of h1, byte for byte, sha256 checked."""
    n = 0
    shas = {}
    for sub in COPIED:
        a = os.path.join(src, sub)
        for rel in files_under(a):
            p, q = os.path.join(a, rel), os.path.join(outdir, sub, rel)
            os.makedirs(os.path.dirname(q), exist_ok=True)
            shutil.copyfile(p, q)
            s1, s2 = sha(p), sha(q)
            if s1 != s2:
                raise SystemExit(f"copy of {sub}/{rel}: sha256 differs")
            shas[f"{sub}/{rel}"] = s1
            n += 1
    cdir = os.path.join(outdir, "cache")
    os.makedirs(cdir, exist_ok=True)
    for name in sorted(os.listdir(os.path.join(src, "cache"))):
        p = os.path.join(src, "cache", name)
        if name in CACHE_COPIED or (name.startswith("stage") and name.endswith("-counts.json")):
            if os.path.isdir(p):
                if not os.path.exists(os.path.join(cdir, name)):
                    shutil.copytree(p, os.path.join(cdir, name))
            else:
                shutil.copyfile(p, os.path.join(cdir, name))
    cnt["section 13: files copied from h1, sha256 equal"] = n
    return shas


# ---- reading ---------------------------------------------------------------------------------------------------------

def rd(path, cols=None):
    return pq.read_table(path, columns=cols).to_pylist()


def tsv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        lines = fh.read().split("\n")
    head = lines[0].split("\t")
    return [dict(zip(head, ln.split("\t"))) for ln in lines[1:] if ln]


class Greek:
    """The build's own grc tables (read once)."""

    def __init__(self, outdir):
        d = os.path.join(outdir, "grc")
        self.words = rd(os.path.join(d, "words.parquet"))
        self.pieces = rd(os.path.join(d, "pieces.parquet"), ["t", "class", "lexeme", "who", "who_basis"])
        self.clauses = rd(os.path.join(d, "clauses.parquet"))
        self.cons = rd(os.path.join(d, "constituents.parquet"))
        self.added = rd(os.path.join(d, "added.parquet"))
        self.acc = {r["t"]: r for r in rd(os.path.join(d, "who_account.parquet"))}
        self.passages = rd(os.path.join(d, "passages.parquet"))
        self.links = rd(os.path.join(d, "links.parquet"))
        self.facts = rd(os.path.join(d, "facts.parquet"))
        self.relmap = tsv(os.path.join(d, "relmap.tsv"))
        self.w = {r["t"]: r for r in self.words}
        self.p = {r["t"]: r for r in self.pieces}
        self.c = {r["clause"]: r for r in self.clauses}
        self.corder = {r["clause"]: i for i, r in enumerate(self.clauses)}
        self.chain = {}
        for r in self.clauses:
            k, ch = r["clause"], []
            while k:
                ch.append(k)
                k = self.c[k]["parent"]
            self.chain[r["clause"]] = ch            # innermost first
        self.chainset = {k: set(v) for k, v in self.chain.items()}
        self.depth = {k: len(v) for k, v in self.chain.items()}
        self.verse_first = {}
        for r in self.words:
            self.verse_first.setdefault((r["book"], r["chapter"], r["verse"]), r["t"])
        self.deps = C.defaultdict(list)
        for r in self.words:
            if r["head"]:
                self.deps[r["head"]].append(r["t"])

    def lca(self, cs):
        cs = list(cs)
        common = set(self.chain[cs[0]])
        for c in cs[1:]:
            common &= self.chainset[c]
        return max(common, key=lambda x: self.depth[x]) if common else ""

    def in_clause(self, t, c):
        k = self.w[t]["clause"]
        return bool(k) and c in self.chainset[k]


def read_terms():
    rows = tsv(TERMS)
    to_code, to_hbo = {}, {}
    for r in rows:
        if r["grc"]:
            to_code[(r["category"], r["grc"])] = r["code"]
        to_hbo[(r["category"], r["code"])] = r["hbo"]
    return to_code, to_hbo


def catch_all_keys():
    out = set()
    for r in tsv(ENTITIES):
        acai = r["entity"]
        typ, rest = acai.split(":", 1)
        if rest.startswith("Generic") or rest in ("Messenger", "Messengers"):
            out.add(f"{typ}:e{hashlib.sha1(acai.encode('utf-8')).hexdigest()[:10]}")
    return out


# ---- D36: the Tanakh form lookup -------------------------------------------------------------------------------------

def norm_scg(s):
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if 0x05B0 <= ord(ch) <= 0x05EA or 0xFB1D <= ord(ch) <= 0xFB4F)
    return unicodedata.normalize("NFC", s)


def norm_mod(s):
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if 0x05D0 <= ord(ch) <= 0x05EA or 0xFB1D <= ord(ch) <= 0xFB4F)
    return unicodedata.normalize("NFC", s)


NORM = {"heb_scg": norm_scg, "heb_mod": norm_mod}
D36_CATS = ("stem", "person", "number", "gender", "state")


class Lookup:
    """D36 (b): Tanakh words (hbo, arc) by (form, lexeme keys in order); Tanakh pieces by (form, class, lexeme)."""

    def __init__(self, outdir, ed):
        f = NORM[ed]
        self.word = C.defaultdict(list)
        self.piece = C.defaultdict(list)
        for lg in ("hbo", "arc"):
            W = {r["t"]: r["text"] for r in rd(os.path.join(outdir, lg, "words.parquet"), ["t", "text"])}
            per = C.defaultdict(list)
            for r in rd(os.path.join(outdir, lg, "pieces.parquet"), ["t", "n", "text", "lexeme", "class", "marks"]):
                m = json.loads(r["marks"])
                per[r["t"]].append((r["n"], r["lexeme"], m))
                self.piece[(f(r["text"]), r["class"], r["lexeme"])].append(m)
            for t, ps in per.items():
                ps.sort(key=lambda x: x[0])
                self.word[(f(W[t]), tuple(x[1] for x in ps))].append([x[2] for x in ps])
        self.f = f
        self.memo = {}
        self.wvote = {}
        self.pvote = {}

    @staticmethod
    def vote(marks_list, cat):
        n = len(marks_list)
        vals = C.Counter(m.get(cat) for m in marks_list)
        best = [(k, v) for k, v in vals.items() if k is not None]
        if not best or not n:
            return None
        k, v = min(best, key=lambda kv: (-kv[1], kv[0]))
        return k if v >= SHARE * n else None

    def marks(self, word_text, parts):
        """-> per part (dict of category -> value, how) with how 'word', 'part' or ''."""
        mk = (word_text, tuple((p["text"], p["class"], p["lexeme"]) for p in parts))
        if mk not in self.memo:
            self.memo[mk] = self._marks(word_text, parts)
        return self.memo[mk]

    def _votes(self, lst):
        got = {}
        for cat in D36_CATS:
            v = self.vote(lst, cat)
            if v is not None:
                got[cat] = v
        return got

    def _marks(self, word_text, parts):
        key = (self.f(word_text), tuple(p["lexeme"] for p in parts))
        out = []
        if key in self.word:
            if key not in self.wvote:
                ws = self.word[key]
                self.wvote[key] = [self._votes([w[i] for w in ws]) for i in range(len(parts))]
            for got in self.wvote[key]:
                out.append((got, "word" if got else ""))
            return out
        for p in parts:
            pk = (self.f(p["text"]), p["class"], p["lexeme"])
            if pk not in self.pvote:
                lst = self.piece.get(pk)
                self.pvote[pk] = self._votes(lst) if lst else {}
            got = self.pvote[pk]
            out.append((got, "part" if got else ""))
        return out


# ---- the edition: D29 to D42 -----------------------------------------------------------------------------------------

class Edition:
    def __init__(self, outdir, ed, G, to_code, to_hbo, catch, cnt, ex):
        self.ed, self.G, self.cnt, self.ex = ed, G, cnt, ex
        self.to_code, self.to_hbo, self.catch = to_code, to_hbo, catch
        c = C.Counter()
        self.c = c
        o = os.path.join(outdir, "other", ed)
        ow = rd(os.path.join(o, "words.parquet"))
        op = rd(os.path.join(o, "parts.parquet"))
        ana = {}
        for r in rd(os.path.join(ANA, ed, "words.parquet"), ["book", "chapter", "verse", "i", "part", "form", "person"]):
            ana[(r["book"], r["chapter"], r["verse"], r["i"], r["part"])] = (r["form"], r["person"])
        # D29 words
        self.words = []
        left = []
        for r in ow:
            if not r["text"]:
                left.append(f"s={r['s']} {r['id']} analysis={'null' if r['analysis'] is None else 'given'}")
                continue
            self.words.append(r)
        ex[f"{ed} D29 tokens without text (not rows of words)"] = left
        c["D29 words"] = len(self.words)
        self.wby = {r["s"]: r for r in self.words}
        self.ts = [r["s"] for r in self.words]
        self.pos = {t: i for i, t in enumerate(self.ts)}
        parts = C.defaultdict(list)
        for r in op:
            parts[r["s"]].append(r)
        self.parts = {}
        for t in self.ts:
            ps = sorted(parts.get(t, []), key=lambda r: r["p"])
            w = self.wby[t]
            for n, r in enumerate(ps, 1):
                r["n"] = n
                fp = ana.get((w["book"], w["chapter"], w["verse"], w["w"], r["p"]))
                r["form"], r["aperson"] = fp if fp else (None, None)
            self.parts[t] = ps
        orphan = sorted(set(parts) - set(self.wby))
        c["D29 parts"] = sum(len(v) for v in self.parts.values())
        c["D29 parts of tokens without text (left out)"] = sum(len(parts[s]) for s in orphan)
        c["D29 words without parts"] = sum(1 for t in self.ts if not self.parts[t])
        # D35 kind
        self.stem = {}
        alt = 0
        for t in self.ts:
            ps = self.parts[t]
            sfx = []
            for i, p in enumerate(ps):
                s1 = p["class"] == "pron" and any(q["class"] not in NOT_HOST for q in ps[:i])
                s2 = p["class"] == "pron" and i > 0 and ps[i - 1]["class"] not in NOT_HOST
                alt += s1 != s2
                sfx.append(s1)
            si = max((i for i in range(len(ps)) if not sfx[i]), default=None)
            for i, p in enumerate(ps):
                p["kind"] = "stem" if i == si else ("prefix" if si is not None and i < si else "suffix")
            if si is None:
                raise SystemExit(f"{ed}: word {t} has no stem by D35")
            self.stem[t] = ps[si]
        c["D35 words where 'a part before' and 'the part just before' differ"] = alt
        # links
        self.g2h, self.h2g, self.mlinks = C.defaultdict(set), C.defaultdict(set), C.defaultdict(set)
        self.linkrows = []
        lost = 0
        for r in G.links:
            if r["other"] != ed:
                continue
            if r["s"] not in self.wby:
                lost += 1
                continue
            self.linkrows.append(r)
            if r["basis"] == "linked":
                self.g2h[r["t"]].add(r["s"])
                self.h2g[r["s"]].add(r["t"])
            else:
                self.mlinks[r["s"]].add(r["t"])
        c["D42 grc link rows to a token without text (no row)"] = lost
        self.one = {}
        for s, gs in self.h2g.items():
            if len(gs) == 1:
                g = next(iter(gs))
                if len(self.g2h[g]) == 1:
                    self.one[s] = g
        self.g_one = {g: s for s, g in self.one.items()}
        c["D29 words with a strict link"] = len(self.h2g)
        c["D29 one-to-one words"] = len(self.one)

    def lfirst(self, g, verb_first=False, within=None):
        hs = sorted(self.g2h.get(g, ()))
        if within is not None:
            hs = [h for h in hs if h in within]
        if not hs:
            return None
        if verb_first:
            v = [h for h in hs if self.stem[h]["class"] == "verb"]
            if v:
                return v[0]
        return hs[0]

    # D30, D31 -----------------------------------------------------------------------------------------------------
    def place(self):
        G, c = self.G, self.c
        place, case = {}, {}
        for t in self.ts:
            gs = self.h2g.get(t)
            if not gs:
                continue
            cs = {G.w[g]["clause"] for g in gs if G.w[g]["clause"]}
            if not cs:
                c["D30 (d) linked, no Greek clause"] += 1
                continue
            if len(cs) == 1:
                place[t], case[t] = next(iter(cs)), "D30a"
                continue
            deep = max(cs, key=lambda x: (G.depth[x], -G.corder[x]))
            if all(k in G.chainset[deep] for k in cs):
                place[t], case[t] = deep, "D30b"
                continue
            k = G.lca(cs)
            if k:
                place[t], case[t] = k, "D30c"
            else:
                c["D30 (d) linked, no common clause"] += 1
        self.p30 = dict(place)
        byverse = C.defaultdict(list)
        for t in self.ts:
            w = self.wby[t]
            byverse[(w["book"], w["chapter"], w["verse"])].append(t)
        self.byverse = byverse
        unplaced = []
        self.PQ = {}
        for v, ss in byverse.items():
            placed = [x for x in ss if x in self.p30]
            for t in ss:
                if t in self.p30:
                    continue
                prev = max((x for x in placed if x < t), default=None)
                nxt = min((x for x in placed if x > t), default=None)
                self.PQ[t] = (prev, nxt)
                if prev is None and nxt is None:
                    case[t] = "N4"
                    unplaced.append(t)
                    continue
                if prev is None or nxt is None:
                    place[t], case[t] = self.p30[prev if prev is not None else nxt], "N3"
                    continue
                a, b = self.p30[prev], self.p30[nxt]
                if a == b:
                    place[t], case[t] = a, "N1"
                    continue
                run = [x for x in ss if prev < x < nxt]
                fo = next((x for x in run if self.parts[x] and self.parts[x][0]["class"] in OPENER), None)
                if fo is not None and t >= fo:
                    place[t], case[t] = b, "N2a"
                    continue
                k = G.lca([a, b])
                if k:
                    place[t], case[t] = k, "N2b"
                else:
                    place[t], case[t] = a, "N2c"
        self.place_, self.case = place, case
        for k in ("D30a", "D30b", "D30c", "N1", "N2a", "N2b", "N2c", "N3", "N4"):
            c[f"placement {k}"] = sum(1 for v in case.values() if v == k)
        c["placement words in a clause"] = len(place)
        self.ex[f"{self.ed} D31 N4 unplaced words"] = [f"{t} {self.ref(t)}" for t in unplaced]

    def ref(self, t):
        w = self.wby[t]
        return f"{w['book']} {w['chapter']}:{w['verse']}"

    def carried(self):
        G = self.G
        H = C.defaultdict(set)
        for t, k in self.place_.items():
            for a in G.chain[k]:
                H[a].add(t)
        self.H = H
        self.carried_set = set(H)
        rows = []
        base = {}
        for r in G.clauses:
            k = r["clause"]
            if k not in H:
                continue
            h = sorted(H[k])
            npieces = sum(len(self.parts[t]) for t in h)
            base[k] = f"cl:{h[0]}.1:{npieces}"
        seen = C.Counter()
        self.key = {}
        for r in G.clauses:
            k = r["clause"]
            if k in base:
                seen[base[k]] += 1
                self.key[k] = base[k] if seen[base[k]] == 1 else f"{base[k]}:{seen[base[k]]}"
        self.c["clauses carried"] = len(self.key)
        self.c["clauses empty (Greek clauses with no placed word)"] = len(G.clauses) - len(self.key)
        self.ex[f"{self.ed} D30 empty Greek clauses"] = [r["clause"] for r in G.clauses if r["clause"] not in self.key]
        self.ex[f"{self.ed} D30 equal keys (numbered)"] = [f"{g} -> {self.key[g]}" for g in self.key if self.key[g].count(":") == 3]

    def cparent(self, k):
        for a in self.G.chain[k][1:]:
            if a in self.key:
                return a
        return ""

    # D32, D33 -----------------------------------------------------------------------------------------------------
    def sentences(self):
        G = self.G
        sent = {}
        for t, k in self.place_.items():
            sent[t] = G.w[G.c[k]["first"]]["sentence"]
        miss = []
        for v, ss in self.byverse.items():
            for i, t in enumerate(ss):
                if t in sent:
                    continue
                prev = next((x for x in reversed(ss[:i]) if x in self.place_), None)
                nxt = next((x for x in ss[i + 1:] if x in self.place_), None)
                if prev is not None:
                    sent[t] = sent[prev]
                elif nxt is not None:
                    sent[t] = sent[nxt]
                elif v in G.verse_first:
                    sent[t] = G.w[G.verse_first[v]]["sentence"]
                    miss.append(f"{t} {self.ref(t)}")
                else:
                    sent[t] = None
                    miss.append(f"{t} {self.ref(t)} (no Greek verse)")
        self.sent = sent
        self.ex[f"{self.ed} D32 words with no placed word in their verse"] = miss
        vs = C.defaultdict(set)
        for t, s in sent.items():
            vs[(self.wby[t]["book"], self.wby[t]["chapter"], self.wby[t]["verse"])].add(s)
        self.c["D32 verses holding words of two or more Greek sentences (exact)"] = sum(1 for v in vs.values() if len(v) > 1)
        bys = C.defaultdict(list)
        for t, s in sent.items():
            if t in self.place_:
                bys[s].append(t)
        notrun = []
        for s, ts in bys.items():
            ps = sorted(self.pos[t] for t in ts)
            if ps[-1] - ps[0] + 1 != len(ps):
                notrun.append(str(s))
        self.c["D32 Greek sentences carried"] = len(bys)
        self.c["D32 Greek sentences whose Hebrew words are not one run"] = len(notrun)
        self.ex[f"{self.ed} D32 Greek sentences not one run of Hebrew words"] = sorted(notrun, key=int)

    def heads(self):
        G = self.G
        self.head = {}
        for t, g in self.one.items():
            h = G.w[g]["head"]
            if h == 0:
                self.head[t] = (0, "root")
                continue
            if h in self.g_one:
                self.head[t] = (self.g_one[h], "direct")
                continue
            a = h
            while a and a not in self.g_one:
                a = G.w[a]["head"]
            self.head[t] = (self.g_one[a], "ancestor") if a else (0, "root")
        for k in ("direct", "ancestor"):
            self.c[f"D33 {k}"] = sum(1 for v in self.head.values() if v[1] == k)
        self.c["D33 root, Greek root"] = sum(1 for t, v in self.head.items() if v[1] == "root" and G.w[self.one[t]]["head"] == 0)
        self.c["D33 root, no one-to-one ancestor"] = sum(1 for t, v in self.head.items() if v[1] == "root" and G.w[self.one[t]]["head"] != 0)
        self.c["D33 no head"] = len(self.ts) - len(self.head)

    # D34 ----------------------------------------------------------------------------------------------------------
    def who(self):
        G, c = self.G, self.c
        who = {}           # (t, n) -> (value, greek t, rule)
        for t in self.ts:
            gs = self.h2g.get(t)
            if not gs:
                continue
            vals = {G.p[g]["who"] for g in gs if G.p[g]["who"]}
            if not vals:
                continue
            if len(vals) > 1:
                c["D34a not carried: two or more values"] += 1
                self.ex.setdefault(f"{self.ed} D34a two or more values", []).append(f"{t} {self.ref(t)}")
                continue
            st = self.stem[t]
            if st["class"] not in WHO_CLASSES:
                c[f"D34a not carried: stem class {st['class'] or '-'}"] += 1
                continue
            v = vals.pop()
            g = min(x for x in gs if G.p[x]["who"] == v)
            who[(t, st["n"])] = (v, g, "a")
            c["D34a words receiving a value"] += 1
            c[f"D34a on {st['basis']} words"] += 1
        # (b)
        gpron = [g for g, r in G.p.items() if r["class"] == "pron" and r["who"] and g not in self.g2h]
        c["D34 Greek pron with who and no strict link"] = len(gpron)
        bydep = C.defaultdict(list)
        for g in gpron:
            h = G.w[g]["head"]
            if h:
                bydep[h].append(g)
        taken_b = set()
        self.b_of = {}
        for h, gl in sorted(bydep.items()):
            if h not in self.g2h:
                c["D34b Greek head not linked"] += len(gl)
                continue
            sfx = [(t, p["n"]) for t in sorted(self.g2h[h]) for p in self.parts[t] if p["kind"] == "suffix" and p["class"] == "pron"]
            if len(gl) == 1 and len(sfx) == 1 and sfx[0] not in who:
                g = gl[0]
                who[sfx[0]] = (G.p[g]["who"], g, "b")
                taken_b.add(g)
                self.b_of[g] = sfx[0]
                c["D34b carried"] += 1
            elif len(gl) > 1 or len(sfx) > 1:
                c["D34b several candidates"] += len(gl)
            else:
                c["D34b no host suffix"] += len(gl)
        # (c)
        gbyc = C.defaultdict(list)
        for g in gpron:
            if g in taken_b or not G.w[g]["clause"]:
                continue
            gbyc[G.w[g]["clause"]].append(g)
        hbyc = C.defaultdict(list)
        for t, k in self.place_.items():
            for p in self.parts[t]:
                if p["class"] == "pron" and (t, p["n"]) not in who:
                    hbyc[k].append((t, p["n"]))
        self.c_of = {}
        for k in sorted(set(gbyc) | set(hbyc), key=lambda x: G.corder[x]):
            a, b = gbyc.get(k, []), hbyc.get(k, [])
            if k in self.key and len(a) == 1 and len(b) == 1:
                who[b[0]] = (G.p[a[0]]["who"], a[0], "c")
                self.c_of[a[0]] = b[0]
                c["D34c carried (clauses, exact)"] += 1
        self.whov = who
        for r in ("a", "b", "c"):
            c[f"D34 pieces with who by ({r})"] = sum(1 for v in who.values() if v[2] == r)

    # tables -------------------------------------------------------------------------------------------------------
    def term(self, cat, grc_term):
        code = self.to_code.get((cat, grc_term))
        if code is None:
            raise SystemExit(f"{self.ed}: Greek term {grc_term!r} of {cat} has no code in terms.tsv")
        h = self.to_hbo.get((cat, code))
        if not h:
            raise SystemExit(f"{self.ed}: code {cat}/{code} has no hbo term")
        return h, code


def d16(own):
    """own: key -> (time code or None, parent key, greek has time_abs). -> key -> (time_abs code or None, reason)."""
    memo = {}

    def up(k):
        p = own[k][1]
        while p and own[p][0] is None:
            p = own[p][1]
        return p

    def res(k):
        if k in memo:
            return memo[k]
        code = own[k][0]
        if code is None:
            memo[k] = (None, "no time")
            if own[k][2]:          # 1.5: a verbless Greek clause takes its nearest timed ancestor's time_abs
                p = up(k)
                memo[k] = (res(p)[0], "verbless") if p else (None, "verbless, no ancestor")
            return memo[k]
        if code in ABS:
            memo[k] = (code, "")
            return memo[k]
        p = up(k)
        if not p:
            memo[k] = (None, "no ancestor")
            return memo[k]
        P = res(p)[0]
        if P is None:
            memo[k] = (None, "ancestor unresolved")
        elif code == "simultaneous":
            memo[k] = (None, "simultaneous under irrealis") if P == "irrealis" else (P, "")
        elif code == "anterior":
            memo[k] = ("past", "") if P in ("past", "present") else (None, f"anterior under {P}")
        elif code == "posterior":
            memo[k] = ("future", "") if P in ("present", "future") else (None, f"posterior under {P}")
        else:
            memo[k] = (None, f"unknown time {code}")
        return memo[k]
    import sys
    sys.setrecursionlimit(100000)
    return {k: res(k) for k in own}


S_, I_, B_ = pa.string(), pa.int64(), pa.bool_()


def schema_of(outdir, table, extra):
    s = pq.read_schema(os.path.join(outdir, "grc", f"{table}.parquet"))
    return pa.schema([pa.field(f.name, f.type) for f in s] + [pa.field(n, t) for n, t in extra])


def empty_of(t):
    return "" if t == S_ else None


def tick(label, t0=[None]):
    now = time.time()
    if t0[0] is not None:
        print(f"  {label}: {now - t0[0]:.0f} s", file=sys.stderr, flush=True)
    t0[0] = now


def build_edition(outdir, ed, G, to_code, to_hbo, catch, cnt, ex):
    tick("start")
    E = Edition(outdir, ed, G, to_code, to_hbo, catch, cnt, ex)
    E.place()
    E.carried()
    E.sentences()
    E.heads()
    E.who()
    tick(f"{ed} D29-D34")
    c = E.c
    d = os.path.join(outdir, ed)
    os.makedirs(d, exist_ok=True)
    L = Lookup(outdir, ed)
    tick(f"{ed} lookup index")
    # ---- pieces: marks (D36) -------------------------------------------------------------------------------------
    for t in E.ts:
        w = E.wby[t]
        got = L.marks(w["text"], E.parts[t])
        for p, (m, how) in zip(E.parts[t], got):
            marks = {}
            if p["class"] == "verb" and p["form"]:
                marks["type"] = X.c0(p["form"])
                c[f"D36a type {p['basis']}"] += 1
            ap = {"first": "1", "second": "2", "third": "3"}.get(p["aperson"] or "")
            if p["class"] == "verb" and ap:
                marks["person"] = ap
                c[f"D36a person {p['basis']}"] += 1
            for cat in D36_CATS:
                if cat in m:
                    if cat == "person" and "person" in marks:
                        if m[cat] != marks["person"]:
                            c[f"D36 person of (a) kept where (b) differs, {p['basis']}"] += 1
                        continue
                    marks[cat] = m[cat]
                    c[f"D36b {cat} {how} {p['basis']}"] += 1
            p["marks"] = marks
    tick(f"{ed} D36")
    # ---- words ---------------------------------------------------------------------------------------------------
    ws = schema_of(outdir, "words", [("clause_basis", S_), ("from_t", I_)])
    W = {f.name: [] for f in ws}
    for t in E.ts:
        w = E.wby[t]
        k = E.place_.get(t)
        hd = E.head.get(t)
        g = E.one.get(t)
        row = {"t": t, "id": w["id"], "book": w["book"], "chapter": w["chapter"], "verse": w["verse"], "w": w["w"] + 1,
               "text": w["text"], "after": "", "sentence": E.sent.get(t), "clause": E.key[k] if k else "",
               "head": hd[0] if hd else None, "head_basis": hd[1] if hd else "",
               "rel": G.w[g]["rel"] if hd else "", "rel_shared": G.w[g]["rel_shared"] if hd else "",
               "clause_basis": ("linked" if E.case[t].startswith("D30") else "derived") if k else "",
               "from_t": g}
        for f in ws:
            W[f.name].append(row[f.name])
    X.write_parquet(os.path.join(d, "words.parquet"), W, ws)
    # ---- pieces --------------------------------------------------------------------------------------------------
    ps = schema_of(outdir, "pieces", [("basis", S_), ("who_from", I_)])
    P = {f.name: [] for f in ps}
    for t in E.ts:
        hd = E.head.get(t)
        for p in E.parts[t]:
            stem = p["kind"] == "stem"
            wv = E.whov.get((t, p["n"]))
            if stem and hd:
                ht, hn = (0, 0) if hd[0] == 0 else (hd[0], E.stem[hd[0]]["n"])
            else:
                ht = hn = None
            marks = X.jdump(p["marks"])
            row = {"t": t, "n": p["n"], "pid": "", "text": p["text"], "kind": p["kind"], "lexeme": p["lexeme"],
                   "class": p["class"], "marks": marks, "fused": "", "head_t": ht, "head_n": hn,
                   "head_basis": hd[1] if stem and hd else "", "rel": G.w[E.one[t]]["rel"] if stem and hd else "",
                   "who": wv[0] if wv else "", "who_basis": ("model" if p["basis"] == "model" else "linked") if wv else "",
                   "sense": "", "domain": "", "shared": shared_piece(p), "concept": "", "concept_by": "",
                   "clusivity": "", "clusivity_basis": "", "noun_rel": "", "noun_head_t": None, "noun_head_n": None,
                   "basis": p["basis"], "who_from": wv[1] if wv else None}
            for f in ps:
                P[f.name].append(row[f.name])
    X.write_parquet(os.path.join(d, "pieces.parquet"), P, ps)
    c["pieces rows"] = len(P["t"])
    tick(f"{ed} words, pieces")
    # ---- clauses (D30, D37) --------------------------------------------------------------------------------------
    own = {}
    for k in E.key:
        gm = json.loads(G.c[k]["marks"])
        tm = gm.get("time")
        own[k] = (to_code[("time", tm)] if tm else None, E.cparent(k), "time_abs" in gm)
    ta = d16(own)
    cs = schema_of(outdir, "clauses", [("from_clause", S_)])
    K = {f.name: [] for f in cs}
    ownwords = C.defaultdict(list)
    for t, k in E.place_.items():
        ownwords[k].append(t)
    E.ownwords = ownwords
    E.pred = {}
    E.cmarks = {}
    for r in G.clauses:
        k = r["clause"]
        if k not in E.key:
            continue
        h = sorted(E.H[k])
        first, last = h[0], h[-1]
        gaps = E.pos[last] - E.pos[first] + 1 != len(h)
        par = E.cparent(k)
        depth = sum(1 for a in G.chain[k][1:] if a in E.key)
        pred = 0
        if r["pred"]:
            x = E.lfirst(r["pred"], verb_first=True, within=E.H[k])
            if x is None and E.g2h.get(r["pred"]):
                c["D30 pred linked outside the clause (0)"] += 1
            pred = x or 0
        E.pred[k] = pred
        gm = json.loads(r["marks"])
        m, mm = {}, {}
        for cat in CARRIED_TERMS:
            if cat in gm:
                m[cat] = E.term(cat, gm[cat])[0]
        for cat in CARRIED_CODES:
            if cat in gm:
                m[cat] = gm[cat]
        tv, why = ta[k]
        if tv is not None:
            m["time_abs"] = to_hbo[("time", tv)]
        gta = to_code[("time", gm["time_abs"])] if "time_abs" in gm else None
        if gta != tv:
            c[f"D37b time_abs differs from Greek: {why or 'resolved'}"] += 1
        if tv is None and own[k][0] is not None:
            c[f"D16 empty time_abs: {why}"] += 1
        # (c) own: connective, negator
        conn, cmodel = [], False
        for t in sorted(ownwords.get(k, [])):
            stop = False
            for p in E.parts[t]:
                if p["class"] in ("cj", "rel"):
                    conn.append(p["lexeme"])
                    cmodel |= p["basis"] == "model"
                else:
                    cmodel |= p["basis"] == "model" and bool(conn)
                    stop = True
                    break
            if stop:
                break
        if conn:
            (mm if cmodel else m)["connective"] = conn
            c[f"D37c connective {'model' if cmodel else 'derived'}"] += 1
        neg = None
        for t in sorted(ownwords.get(k, [])):
            for p in E.parts[t]:
                lx = p["lexeme"]
                parts_ = lx.split(":")
                if len(parts_) >= 3 and ((parts_[1] == "hbo" and parts_[2] in NEG_HBO) or (parts_[1] == "arc" and parts_[2] in NEG_ARC)):
                    neg = p
                    break
            if neg:
                break
        if neg:
            (mm if neg["basis"] == "model" else m)["negator"] = neg["lexeme"]
            c[f"D37c negator {neg['basis']}"] += 1
        E.cmarks[k] = (m, mm)
        sh = {}
        if "polarity" in m:
            sh = POLARITY_SHARED.get(m["polarity"], {})
        row = {"clause": E.key[k], "book": E.wby[first]["book"], "chapter": E.wby[first]["chapter"],
               "verse": E.wby[first]["verse"], "first": first, "last": last, "gaps": gaps,
               "words": len(ownwords.get(k, [])), "parent": E.key[par] if par else "", "depth": depth,
               "via": "", "rule": "", "pattern": "", "role": r["role"], "role_wrapped": "", "pred": pred,
               "pred_kind": r["pred_kind"] if pred else "none", "marks": X.jdump(m), "shared": X.jdump(sh),
               "quote": r["quote"], "speaker": r["speaker"], "addressee": r["addressee"],
               "speech_basis": "linked" if r["quote"] else "", "line": "",
               "quote_model": r["quote_model"], "speaker_model": r["speaker_model"],
               "addressee_model": r["addressee_model"], "subject_model": "",
               "marks_model": X.jdump(mm) if mm else None, "from_clause": k}
        for f in cs:
            K[f.name].append(row[f.name])
    X.write_parquet(os.path.join(d, "clauses.parquet"), K, cs)
    c["clauses with gaps"] = sum(K["gaps"])
    c["clauses one unbroken run"] = len(K["gaps"]) - sum(K["gaps"])
    E.ex[f"{ed} D30 carried clauses with gaps"] = [k for k, g in zip(K["clause"], K["gaps"]) if g]
    # ---- constituents (D38) --------------------------------------------------------------------------------------
    ks = schema_of(outdir, "constituents", [("from_ord", I_), ("own_basis", S_)])
    KS = {f.name: [] for f in ks}
    ordn = C.Counter()
    E.p_heads = set()
    E.cons_rows = []
    for r in G.cons:
        k = r["clause"]
        if k not in E.key:
            c["D38 not carried: clause empty"] += 1
            continue
        gws = [g for g in range(r["first"], r["last"] + 1) if g in G.w and G.in_clause(g, k)]
        hs = set()
        for g in gws:
            hs |= E.g2h.get(g, set())
        if not hs:
            c[f"D38 not carried: no linked word, role {r['role']}"] += 1
            continue
        f0 = min(hs)
        i0 = E.pos[f0]
        if i0 > 0:
            prevt = E.ts[i0 - 1]
            if prevt not in E.p30 and E.place_.get(prevt) == E.place_.get(f0) and E.place_.get(prevt) and \
                    E.parts[prevt] and E.parts[prevt][0]["class"] in OPENER:
                hs.add(prevt)
                c["D38 opener added before the span"] += 1
        hl = sorted(hs)
        head = E.lfirst(r["head"]) if r["head"] else None
        if r["head"] and len(E.g2h.get(r["head"], ())) > 1:
            c["D38 head linked to two or more words (first taken)"] += 1
        if head is None:
            c["D38 head not linked"] += 1
            if r["head"] in E.b_of:
                c["D38 Greek head carried to a suffix by D34b (head null, ref_form empty)"] += 1
        ordn[k] += 1
        sp = E.stem[head] if head else None
        cls = sp["class"] if sp else ""
        obasis = "model" if sp and sp["basis"] == "model" else "derived"
        prep = ""
        if r["role"] == "pp" or r["class"] == "pp":
            for t in hl:
                q = next((p for p in E.parts[t] if p["class"] == "prep"), None)
                if q:
                    prep = q["lexeme"]
                    if q["basis"] == "model":
                        obasis = "model"
                    break
        sem = E.term("sem_role", r["sem_role"])[0] if r["sem_role"] else ""
        rs = E.term("ref_status", r["ref_status"])[0] if r["ref_status"] else ""
        rf = ""
        if rs and head:
            rf = REFFORM.get(cls, "")
            if not rf:
                c[f"D38 ref_form empty: stem class {cls or '-'}"] += 1
        if r["role"] == "p" and head:
            E.p_heads.add(head)
        row = {"clause": E.key[k], "ord": ordn[k], "role": r["role"], "head": head, "first": hl[0], "last": hl[-1],
               "class": cls, "frame_role": "", "sem_role": sem, "sem_role_basis": "linked" if sem else "",
               "prep": prep, "ref_status": rs, "ref_form": rf, "from_ord": r["ord"], "own_basis": obasis}
        E.cons_rows.append(row)
        for f in ks:
            KS[f.name].append(row[f.name])
        if E.pos[hl[-1]] - E.pos[hl[0]] + 1 != len(hl):
            c["D38 spans with gaps"] += 1
    X.write_parquet(os.path.join(d, "constituents.parquet"), KS, ks)
    c["constituents rows"] = len(KS["clause"])
    tick(f"{ed} clauses, constituents")
    # ---- added (D39) ---------------------------------------------------------------------------------------------
    as_ = schema_of(outdir, "added", [("from_clause", S_), ("from_t", I_), ("own_basis", S_)])
    A = {f.name: [] for f in as_}
    seen = set()
    E.added_rows = []
    for r in G.added:
        v = E.lfirst(r["verb"], verb_first=True)
        if v is None:
            c["D39 not carried: verb not linked"] += 1
            continue
        k = E.place_.get(v)
        if not k:
            c["D39 not carried: verb unplaced"] += 1
            continue
        if r["clause"] not in E.key:
            c["D39 Greek row's clause empty (row kept on the verb's clause)"] += 1
        elif E.key[r["clause"]] != E.key[k]:
            c["D39 verb's clause is not the carried clause of the Greek row's clause"] += 1
        key = (E.key[k], v, r["role"])
        if key in seen:
            c["D39 not carried: key already taken"] += 1
            continue
        seen.add(key)
        sp = E.stem[v]
        if r["role"] == "A0" and "person" in sp["marks"]:
            kind, form = "in_verb", "ending"
            pe, nu, ge = sp["marks"].get("person", ""), sp["marks"].get("number", ""), sp["marks"].get("gender", "")
        else:
            form = "none"
            kind = "possessor" if r["role"] == "poss" else "unsaid" if r["where"] == "unexpressed" else "elsewhere"
            pe, nu, ge = r["person"], r["number"], r["gender"]
        c[f"D39 kind {kind}"] += 1
        ant = ""
        if r["antecedent"]:
            at = E.lfirst(int(r["antecedent"].split(".")[0]))
            if at is not None:
                ant = f"{at}.{E.stem[at]['n']}"
                c["D39 antecedent linked"] += 1
            else:
                c["D39 antecedent not linked"] += 1
        else:
            c["D39 antecedent none"] += 1
        pron = any(p["class"] == "pron" for t in E.ownwords.get(k, []) for p in E.parts[t])
        if pron:
            c["D39 pronoun in clause (exact)"] += 1
        row = {"clause": E.key[k], "verb": v, "role": r["role"], "kind": to_hbo[("added_kind", kind)],
               "where": r["where"], "form": form, "person": pe, "number": nu, "gender": ge, "antecedent": ant,
               "who": r["who"], "who_reason": r["who_reason"], "from_clause": r["clause"], "from_t": r["verb"],
               "own_basis": sp["basis"]}
        row["_pron"] = pron
        E.added_rows.append(row)
        for f in as_:
            A[f.name].append(row[f.name])
    X.write_parquet(os.path.join(d, "added.parquet"), A, as_)
    c["added rows"] = len(A["clause"])
    # ---- who_account (D40) ---------------------------------------------------------------------------------------
    vz = {}
    keyrev = {v: k for k, v in E.key.items()}
    for row in E.added_rows:
        if row["form"] == "ending" and row["role"] == "A0":
            gk = keyrev[row["clause"]]
            pr = E.pred.get(gk)
            if pr:
                vz[(pr, E.stem[pr]["n"])] = G.c[gk]["pred"]
    wa = schema_of(outdir, "who_account", [("from_t", I_), ("basis", S_)])
    WA = {f.name: [] for f in wa}
    gpron_of = {}
    for g, tn in E.b_of.items():
        gpron_of[tn] = g
    for g, tn in E.c_of.items():
        gpron_of[tn] = g
    both = 0
    for t in E.ts:
        for p in E.parts[t]:
            tn = (t, p["n"])
            hk = None
            if p["kind"] == "stem" and p["class"] == "noun":
                hk = "noun"
            elif p["kind"] == "stem" and p["class"] == "pron":
                hk = "pronoun"
            elif p["kind"] == "suffix" and p["class"] == "pron":
                hk = "suffix"
            if tn in vz:
                if hk:
                    both += 1
                else:
                    hk = "verb_zero"
            if not hk:
                continue
            wv = E.whov.get(tn)
            g = None
            if hk in ("noun", "pronoun"):
                cand = [x for x in sorted(E.h2g.get(t, ())) if x in G.acc]
                if len(cand) > 1:
                    c["D40 stem with two or more Greek account rows (first taken)"] += 1
                g = cand[0] if cand else None
            elif hk == "suffix":
                g = gpron_of.get(tn)
                g = g if g in G.acc else None
            else:
                g = vz[tn] if vz[tn] in G.acc else None
            if wv and any(e not in catch for e in wv[0].split()):
                st, rs = "participant", ""
            elif wv:
                st, rs = "generic", ""
            elif t in E.p_heads and p["kind"] == "stem":
                st, rs = "not_referring", ""
            elif g is not None and G.acc[g]["state"] not in ("participant", "generic"):
                st, rs = G.acc[g]["state"], G.acc[g]["reason"]
            elif g is not None:
                st, rs = "unresolved", "not_carried"
            else:
                st, rs = "no_row", "not_linked"
            row = {"t": t, "n": p["n"], "head_kind": hk, "state": st, "reason": rs, "from_t": g,
                   "basis": "model" if p["basis"] == "model" else "derived"}
            for f in wa:
                WA[f.name].append(row[f.name])
            c[f"D40 {hk} {st}"] += 1
    c["D40 pieces both a noun/pronoun head and a verb_zero head (first kind)"] = both
    X.write_parquet(os.path.join(d, "who_account.parquet"), WA, wa)
    E.wa = WA
    # ---- passages (D41) ------------------------------------------------------------------------------------------
    pss = schema_of(outdir, "passages", [("from_passage", S_)])
    PS = {f.name: [] for f in pss}
    cfirst = sorted((K["first"][i], K["last"][i], K["clause"][i]) for i in range(len(K["clause"])))
    wclause = dict(zip(W["t"], W["clause"]))
    last_end = None
    for r in G.passages:
        hs = set()
        for g in range(r["first"], r["last"] + 1):
            hs |= E.g2h.get(g, set())
        if last_end is not None:
            moved = {h for h in hs if h <= last_end}
            if moved:
                c["D41 units moved to begin after the earlier's last"] += 1
                hs -= moved
        if not hs:
            c["D41 not carried"] += 1
            E.ex.setdefault(f"{ed} D41 units not carried", []).append(r["passage"])
            continue
        f, l = min(hs), max(hs)
        last_end = l if last_end is None else max(last_end, l)
        lines = None
        if r["lines"] is not None:
            lines = []
            for a, b in json.loads(r["lines"]):
                lh = {h for g in range(a, b + 1) for h in E.g2h.get(g, ()) if f <= h <= l}
                if lh:
                    lines.append([min(lh), max(lh)])
                else:
                    c["D41 lines with no linked word (left out)"] += 1
            lines = X.jdump(lines)
        inside = [x for x in cfirst if f <= x[0] <= l]
        row = {"passage": f"ps:nestle1904:{r['kind']}:{f}", "source": "nestle1904", "kind": r["kind"], "first": f,
               "last": l, "first_clause": wclause[f], "last_clause": wclause[l], "clauses": len(inside),
               "crossing": sum(1 for x in inside if x[1] > l), "lines": lines, "fact": r["fact"],
               "from_passage": r["passage"]}
        for fl in pss:
            PS[fl.name].append(row[fl.name])
    X.write_parquet(os.path.join(d, "passages.parquet"), PS, pss)
    c["passages carried"] = len(PS["passage"])
    tick(f"{ed} added, who_account, passages")
    # ---- links, link_account (D42) -------------------------------------------------------------------------------
    ls = pq.read_schema(os.path.join(outdir, "grc", "links.parquet"))
    LR = sorted(({"t": r["s"], "n": E.stem[r["s"]]["n"], "other": "grc", "s": r["t"], "how": r["how"],
                  "agree": r["agree"], "basis": r["basis"], "agree_model": r["agree_model"]} for r in E.linkrows),
                key=lambda x: (x["t"], x["n"], x["s"], x["basis"], x["how"]))
    X.write_parquet(os.path.join(d, "links.parquet"), {f.name: [x[f.name] for x in LR] for f in ls}, ls)
    c["links rows strict"] = sum(1 for x in LR if x["basis"] == "linked")
    c["links rows model"] = sum(1 for x in LR if x["basis"] == "model")
    linked_cls = C.Counter(E.stem[t]["class"] for t in E.h2g)
    all_cls = C.Counter(E.stem[t]["class"] for t in E.ts)
    las = pq.read_schema(os.path.join(outdir, "grc", "link_account.parquet"))
    LA = {f.name: [] for f in las}
    for t in E.ts:
        sc = E.stem[t]["class"]
        for p in E.parts[t]:
            sm = None
            if t in E.h2g:
                st, rs = ("linked", "") if p["kind"] == "stem" else ("word_linked", str(E.stem[t]["n"]))
            elif not linked_cls.get(sc):
                st, rs = "outside_alignment", sc
            elif linked_cls[sc] < 0.05 * all_cls[sc]:
                st, rs = "never_a_word", sc
            else:
                st, rs = "no_counterpart", ""
            if p["kind"] == "stem" and st != "linked" and t in E.mlinks:
                sm = "linked"
            for f, v in (("t", t), ("n", p["n"]), ("other", "grc"), ("state", st), ("reason", rs), ("state_model", sm)):
                LA[f].append(v)
            c[f"D42 link_account {st}"] += 1
    X.write_parquet(os.path.join(d, "link_account.parquet"), LA, las)
    tick(f"{ed} links")
    E.W, E.P, E.K, E.KS, E.A, E.PS, E.LR, E.LA = W, P, K, KS, A, PS, LR, LA
    cnt[f"D29-D42 {ed}"] = dict(sorted(c.items()))
    return E


POLARITY_SHARED = {"affirmative": {"Polarity": "Pos"}, "negative": {"Polarity": "Neg"}}


def shared_piece(p):
    return SHARED_FN(p)


SHARED_FN = None     # set by examples_v17doc (the hbo map.tsv)


def build(outdir, src, counts):
    import examples_v17doc as DOC
    ex = C.defaultdict(list)
    tick("copy")
    shas = copy_folders(outdir, src, counts)
    tick("copied")
    G = Greek(outdir)
    to_code, to_hbo = read_terms()
    catch = catch_all_keys()
    global SHARED_FN
    SHARED_FN = DOC.shared_fn(outdir)
    eds = {}
    for ed in EDS:
        eds[ed] = build_edition(outdir, ed, G, to_code, to_hbo, catch, counts, ex)
    DOC.build_rest(outdir, eds, G, to_code, to_hbo, catch, shas, counts, ex)
    return ex
