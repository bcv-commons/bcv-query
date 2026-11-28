"""What differs between two Hebrew clauses, in the clause scheme's names (grammar probes, piece 1).

A clause is read as a record: its clause marks, and its word parts in order (class, lexeme, form features, and what
the part bears in the clause: subject, object, possessor, ...). Two records are lined up part by part; the raw
differences are folded into dimensions by probe_dimensions.toml (a changed subject number with the verb that agrees
is one change, not two). The answer names the dimensions, each with from -> to and the parts it touches, and the
rest: raw differences that no dimension explains. A pair differs in one thing when it has one dimension and no rest.

  cd shoresh && .venv/bin/python -I macula/probe_diff.py tanakh-check          # the checks on the Tanakh
  cd shoresh && .venv/bin/python -I macula/probe_diff.py show <clause> <clause>

Records are built from the clause scheme's tables (macula/clause_scheme.py): the Tanakh's (class Tanakh) and the
Hebrew New Testaments' (class NT, on hebrew-nt-analysis's words, features and tree; its values in the Tanakh's codes).
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import tomllib
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyarrow.parquet as pq

from macula.clause_scheme import FINITE, K1, NEGATORS, SCHEME_OUT, part_kinds, strong

HERE = Path(__file__).resolve().parent
FEATURES = ("lexeme", "type", "stem", "person", "number", "gender", "state")
PNG = ("person", "number", "gender")
BEARER = {"s": "subject", "o": "object", "o2": "object2", "io": "object2", "pp": "pp", "adv": "adv", "p": "predicate",
          "v": "verb"}


def dimensions():
    d = tomllib.loads((HERE / "probe_dimensions.toml").read_text())
    scheme = SCHEME_OUT / "clause-scheme.toml"
    if scheme.exists():                                              # every mark named is a mark of the scheme
        cols = set(tomllib.loads(scheme.read_text())["tables"]["clauses"]["columns"])
        named = set(d["context_marks"]) | {m for x in d["dimensions"].values() for m in x.get("marks", [])}
        if named - cols:
            raise SystemExit(f"probe_dimensions.toml names marks the scheme does not have: {sorted(named - cols)}")
    return d


# ---------------------------------------------------------------- records
class Tanakh:
    """the Tanakh's clauses as records, from the scheme's tables and the word parts of k1/hbo"""

    def __init__(self, folder=None):
        folder = folder or SCHEME_OUT / "tanakh"
        self.clauses = {c["clause"]: c for c in pq.read_table(folder / "clauses.parquet").to_pylist()}
        self.segs = collections.defaultdict(list)
        for s in pq.read_table(folder / "segments.parquet").to_pylist():
            self.segs[s["clause"]].append(s)
        self.cons = collections.defaultdict(list)
        for c in pq.read_table(folder / "constituents.parquet").to_pylist():
            self.cons[c["clause"]].append(c)
        words = pq.read_table(K1 / "hbo" / "words.parquet", columns=["t", "id", "book", "chapter", "verse", "w"]).to_pylist()
        self.t_of = {w["id"]: w["t"] for w in words}
        self.at = {(w["book"], w["chapter"], w["verse"], w["w"]): w["t"] for w in words}
        self.parts = collections.defaultdict(list)
        for p in pq.read_table(K1 / "hbo" / "pieces.parquet", columns=["t", "n", "text", "kind", "class", "lexeme",
                                                                       "marks", "head_t", "head_n", "rel"]).to_pylist():
            self.parts[p["t"]].append(p)

    def record(self, cid):
        c = self.clauses[cid]
        ts = []
        for s in sorted(self.segs[cid], key=lambda s: s["first_w"]):
            ts += [self.at[(s["book"], s["chapter"], s["verse"], w)] for w in range(s["first_w"], s["last_w"] + 1)
                   if (s["book"], s["chapter"], s["verse"], w) in self.at]
        cons = [(BEARER.get(k["role"], k["role"]), self.t_of[k["head"]], self.t_of[k["first"]], self.t_of[k["last"]])
                for k in self.cons[cid]]
        pred = self.t_of.get(c["pred"])
        slots, pos = [], {}
        for t in ts:
            for p in sorted(self.parts[t], key=lambda p: p["n"]):
                m = json.loads(p["marks"] or "{}")
                pos[(p["t"], p["n"])] = len(slots)
                slots.append({"key": (p["t"], p["n"]), "text": p["text"], "cls": p["class"] or "", "kind": p["kind"],
                              "lexeme": p["lexeme"] or "", "rel": (p["rel"] or "").split(":")[0],
                              "head": (p["head_t"], p["head_n"]) if p["head_t"] else None,
                              **{f: m.get(f, "") for f in FEATURES[1:]}})
        for s in slots:
            s["head"] = pos.get(s["head"])
            s["bearer"] = self._bearer(s, slots, cons, pred)
            s["small"] = small_kind(s)
        marks = {k: (c[k] if not isinstance(c[k], list) else "+".join(c[k])) or "" for k in c
                 if not k.endswith(("_basis", "_p")) and k not in ("clause", "edition", "book", "chapter", "verse",
                                                                   "segments", "parent", "depth", "rule", "pred",
                                                                   "source_clause")}
        sure = min([c[k] for k in c if k.endswith("_p") and c[k] is not None] or [1.0])
        words, last = [], None
        for s in slots:
            if s["key"][0] != last:
                words.append("")
                last = s["key"][0]
            words[-1] += s["text"]
        return {"clause": cid, "marks": marks, "slots": slots, "text": " ".join(words), "words": len(words), "sure": sure}

    @staticmethod
    def _bearer(s, slots, cons, pred):
        """what the part bears in its clause: `verb`, `subject`, `object`, `pp`, ... for the head of a constituent
        and what agrees with it, `<role>_inner` for a part inside one, `possessor` for a suffix on a noun"""
        t = s["key"][0]
        head = slots[s["head"]] if s["head"] is not None else None
        if s["kind"] == "suffix" and s["cls"] == "pron":
            if s["rel"] in ("o", "o2", "s", "pp"):
                return BEARER[s["rel"]]
            if head is not None and head["cls"] in ("noun", "adj", "num") and head["key"][0] == t:
                return "possessor"
        if s["cls"] == "verb" and t == pred and s["kind"] == "stem":
            return "verb"
        for role, h, first, last in cons:
            if role == "verb":
                continue
            if t == h and s["kind"] == "stem":
                return role
            if first <= t <= last:
                if s["kind"] != "stem":
                    return role if s["cls"] == "pron" else ""        # a pronoun after its own preposition
                if head is not None and head["key"][0] == h and s["cls"] == "adj":
                    return role                                      # an adjective on the head agrees with it
                return role + "_inner"
        return ""


def small_kind(s):
    """the kind of a part whose presence in one clause only is a change of its own"""
    if strong(s["lexeme"]) in NEGATORS:
        return "negator"
    if s["type"] == "interrogative":
        return "question"
    if s["cls"] == "art":
        return "article"
    if s["cls"] == "om":
        return "object_marker"
    if s["cls"] in ("cj", "rel"):
        return "connective"
    if s["cls"] == "prep":
        return "preposition"
    if s["bearer"] == "possessor":
        return "possessor"
    b = s["bearer"].replace("_inner", "")
    return b if b in ("subject", "object", "pp", "adv") else ("object" if b == "object2" else "other")


# the New Testament tables' feature values in the Tanakh's codes
CODES = {"person": {"first": "1", "second": "2", "third": "3", "unknown: x": "x"},
         "number": {"singular": "sg", "plural": "pl", "dual": "du"},
         "gender": {"masculine": "m", "feminine": "f", "common": "c", "both": "b"},
         "state": {"absolute": "abs", "construct": "cstr", "determined": "det"}}


class NT:
    """a Hebrew New Testament's clauses as records, from the scheme's tables and hebrew-nt-analysis's word parts.
    A word has a running number `t` (the edition's order) and the id of the text standard (`scg:…`, `del:…`)."""

    def __init__(self, ed, folder=None):
        from macula import hebrew_nt_clauses as N
        self.ed = ed
        folder = folder or SCHEME_OUT / "nt" / ed
        self.clauses = {c["clause"]: c for c in pq.read_table(folder / "clauses.parquet").to_pylist()}
        self.segs = collections.defaultdict(list)
        for s in pq.read_table(folder / "segments.parquet").to_pylist():
            self.segs[s["clause"]].append(s)
        self.cons = collections.defaultdict(list)
        for c in pq.read_table(folder / "constituents.parquet").to_pylist():
            self.cons[c["clause"]].append(c)
        kinds = collections.defaultdict(collections.Counter)        # (class, Strong) -> the Tanakh's part types
        for p in pq.read_table(K1 / "hbo" / "pieces.parquet", columns=["class", "lexeme", "marks"]).to_pylist():
            t = json.loads(p["marks"] or "{}").get("type", "")
            if t and p["class"] != "verb":
                kinds[(p["class"], strong(p["lexeme"]))][t] += 1
        key = lambda r: (r["book"], r["chapter"], r["verse"], r["i"], r["part"])  # noqa: E731
        feat = {key(r): r for r in pq.read_table(N.FEATURES / ed / "features.parquet").to_pylist()}
        tree = {key(r): r for r in pq.read_table(N.LAYERS / ed / "pieces.parquet",
                                                 columns=["book", "chapter", "verse", "i", "part", "head_i", "head_part",
                                                          "rel"]).to_pylist()}
        by_word = collections.OrderedDict()
        for r in pq.read_table(N.ANALYSIS / ed / "words.parquet").to_pylist():
            if r["class"] != "verse-number" and (r["text"] or r["class"] == "art"):   # an article may be written in the preposition
                by_word.setdefault((r["book"], r["chapter"], r["verse"], r["i"]), []).append(r)
        self.at, self.t_of, self.word, self.parts = {}, {}, {}, {}
        for t, (wk, parts) in enumerate(by_word.items(), 1):
            self.at[wk] = t
            wid = f"{N.TEXTS[ed]}:{N.CS_BOOK[wk[0]]:02d}{wk[1]:03d}{wk[2]:03d}{wk[3] + 1:03d}"
            self.t_of[wid] = t
            self.word[t] = {"id": wid, "book": wk[0], "chapter": wk[1], "verse": wk[2], "i": wk[3], "text": parts[0]["word"]}
        for wk, parts in by_word.items():
            t = self.at[wk]
            parts.sort(key=lambda r: r["part"])
            out = []
            for p, kind in zip(parts, part_kinds([p["class"] or "" for p in parts])):
                f, tr = feat.get(key(p), {}), tree.get(key(p), {})
                cls = p["class"] or ""
                ty = (p["form"] or "").replace(" ", "_") if cls == "verb" else \
                    "proper" if f.get("definite") == "name" else \
                    (kinds[(cls, p["strong"] or "")].most_common(1) or [("common" if cls == "noun" else "", 0)])[0][0]
                head = self.at.get(wk[:3] + (tr.get("head_i"),)) if tr.get("head_i") is not None else None
                # a suffix is one word in many shapes: its person, number and gender tell them apart, not a lexeme
                lex = "hbo:suffix" if cls == "pron" and kind == "suffix" else p["lexeme"] or ""
                out.append({"key": (t, p["part"]), "text": p["text"], "cls": cls, "kind": kind, "lexeme": lex,
                            "rel": (tr.get("rel") or "").split(":")[0], "head": (head, tr.get("head_part")) if head else None,
                            "type": ty, "stem": f.get("stem") or "", "definite": f.get("definite") or "",
                            "known": p["source"] == "macula",        # the form stands in the Tanakh: its analysis is that form's

                            **{k: CODES[k].get(f.get(k) or "", "") for k in CODES}})
            self.parts[t] = out

    def words_of(self, cid):
        ts = []
        for s in sorted(self.segs[cid], key=lambda s: (s["chapter"], s["verse"], s["first_w"])):
            ts += [self.at[k] for k in ((s["book"], s["chapter"], s["verse"], w - 1) for w in range(s["first_w"], s["last_w"] + 1))
                   if k in self.at]
        return ts

    def record(self, cid, words=None, text=None):
        """the clause's record; `words` gives other parts for some of its words ({t: [parts]}, a changed clause)"""
        c = self.clauses[cid]
        ts = self.words_of(cid)
        cons = [(BEARER.get(k["role"], k["role"]), self.t_of[k["head"]], self.t_of[k["first"]], self.t_of[k["last"]])
                for k in self.cons[cid] if k["head"] in self.t_of]
        pred = self.t_of.get(c["pred"])
        slots, pos = [], {}
        for t in ts:
            for p in (words or {}).get(t, self.parts[t]):
                pos[p["key"]] = len(slots)
                slots.append(dict(p))
        for s in slots:
            s["head"] = pos.get(s["head"])
            s["bearer"] = Tanakh._bearer(s, slots, cons, pred)
            s["small"] = small_kind(s)
        skip = ("clause", "edition", "book", "chapter", "verse", "segments", "parent", "depth", "rule", "pred", "source_clause")
        marks = {k: (c[k] if not isinstance(c[k], list) else "+".join(c[k])) or "" for k in c
                 if not k.endswith(("_basis", "_p")) and k not in skip}
        mark_p = {k[:-2]: c[k] for k in c if k.endswith("_p") and c[k] is not None}
        sure = min([k["role_p"] for k in self.cons[cid] if k["role_p"] is not None] or [1.0])
        return {"clause": cid, "marks": marks, "mark_p": mark_p, "slots": slots, "unknown": ("stem",) + PNG + ("state",),
                "text": text or " ".join(self.word[t]["text"] for t in ts), "words": len(ts), "ts": ts, "sure": sure}


# ---------------------------------------------------------------- the difference
def line_up(a, b):
    """the cheapest line-up of two lists of parts: a part meets a part of its class (free with the same lexeme, 1
    with another), or stands alone (1). Returns [(i or None, j or None)] in order."""
    n, m = len(a), len(b)
    INF = 10 ** 6

    def meet(p, q):                                                  # `מִ` and `מִן` are one word in two shapes
        return p["cls"] == q["cls"] and (p["kind"] == q["kind"] or p["lexeme"] == q["lexeme"])

    cost = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        for j in range(m + 1):
            if i == 0 and j == 0:
                continue
            best = INF
            if i and j and meet(a[i - 1], b[j - 1]):
                best = cost[i - 1][j - 1] + (0 if a[i - 1]["lexeme"] == b[j - 1]["lexeme"] else 1)
            if i:
                best = min(best, cost[i - 1][j] + 1)
            if j:
                best = min(best, cost[i][j - 1] + 1)
            cost[i][j] = best
    out, i, j = [], n, m
    while i or j:
        if i and j and meet(a[i - 1], b[j - 1]) and \
                cost[i][j] == cost[i - 1][j - 1] + (0 if a[i - 1]["lexeme"] == b[j - 1]["lexeme"] else 1):
            out.append((i - 1, j - 1)); i -= 1; j -= 1
        elif i and (not j or cost[i][j] == cost[i - 1][j] + 1) and not (j and cost[i][j] == cost[i][j - 1] + 1 and i < j):
            out.append((i - 1, None)); i -= 1
        else:
            out.append((None, j - 1)); j -= 1
    return out[::-1]


def diff(a, b, D=None):
    """the dimensions in which clause record `b` differs from `a`, and the rest.
    {"dimensions": [{dimension, from, to, slots: [(i, j)], with: [raw differences folded in]}], "rest": [...],
     "quiet": [differences of quiet marks that no dimension took], "same_parts": bool, "one": bool, "sure": float}"""
    D = D or dimensions()
    spec = D["dimensions"]
    unknown = a.get("unknown") or b.get("unknown")                   # features whose empty value means "not known"
    raw = []                                                         # dicts: what (mark / feature / slot), name, from, to, i, j
    for k in sorted(set(a["marks"]) | set(b["marks"])):
        if k in D["context_marks"]:
            continue
        x, y = a["marks"].get(k, ""), b["marks"].get(k, "")
        if x != y:
            raw.append({"what": "mark", "name": k, "from": x, "to": y, "i": None, "j": None})
    for i, j in line_up(a["slots"], b["slots"]):
        if i is None or j is None:
            s = a["slots"][i] if j is None else b["slots"][j]
            raw.append({"what": "slot", "name": s["small"], "from": s["lexeme"] if j is None else "",
                        "to": "" if j is None else s["lexeme"], "i": i, "j": j, "cls": s["cls"], "bearer": s["bearer"]})
            continue
        p, q = a["slots"][i], b["slots"][j]
        for f in FEATURES:
            if p[f] != q[f]:
                if unknown and f in unknown and not (p[f] and q[f]) and p["type"] == q["type"]:
                    continue                                         # not given on one side: unknown, not another value
                raw.append({"what": "feature", "name": f, "from": p[f], "to": q[f], "i": i, "j": j, "cls": p["cls"],
                            "bearer": p["bearer"] if p["bearer"] == q["bearer"] else
                            "/".join(sorted({p["bearer"], q["bearer"]} - {""})), "small": p["small"]})
    dims, left = [], list(raw)

    def take(pred):
        got = [r for r in left if pred(r)]
        for r in got:
            left.remove(r)
        return got

    def add(name, core, frm=None, to=None):
        d = {"dimension": name, "from": core[0]["from"] if frm is None else frm, "to": core[0]["to"] if to is None else to,
             "slots": sorted({(r["i"], r["j"]) for r in core if r["what"] != "mark"}, key=lambda x: (x[0] or -1, x[1] or -1)),
             "with": core[1:]}
        dims.append(d)
        return d

    # 1. a word swap, with what follows from the new word (its own gender, the state it stands in)
    for r in take(lambda r: r["what"] == "feature" and r["name"] == "lexeme"):
        neg = r.get("small") == "negator"                            # `לֹא` for `אַל`: the command's form goes with it
        d = add("swap_negator" if neg else "swap_" + r["cls"], [r])
        d["with"] += take(lambda x: x["what"] == "feature" and (x["i"], x["j"]) == (r["i"], r["j"]) and x["name"] in ("gender", "type", "state"))
        if neg:
            d["with"] += take(lambda x: x["name"] in ("negator", "force", "mood", "type", "time", "time_abs", "aspect"))
        d["bearer"] = r["bearer"]
    # 1b. a verb that is finite in one clause and not in the other: what a finite verb alone has goes with it
    for r in take(lambda r: r["what"] == "feature" and r["name"] == "type" and r["cls"] == "verb"
                  and (r["from"] in FINITE) != (r["to"] in FINITE)):
        d = add("finiteness", [r])
        d["with"] += take(lambda x: x["what"] == "feature" and (x["i"], x["j"]) == (r["i"], r["j"]) and x["name"] in PNG + ("state",))
        d["with"] += take(lambda x: x["what"] == "mark" and x["name"] in spec["finiteness"]["also"])
    # 2. person, number and gender: one dimension per bearer and feature; what agrees is folded in
    for f in PNG:
        if f == "gender":                                            # `אָמַר` -> `אָמְרוּ`, `אָמַרְתִּי`: the form has no gender to keep
            for r in take(lambda r: r["what"] == "feature" and r["name"] == "gender" and {r["from"], r["to"]} & {"c", "b", ""}
                          and any((r["i"], r["j"]) in d["slots"] and d["dimension"].endswith(("_person", "_number")) for d in dims)):
                next(d for d in dims if (r["i"], r["j"]) in d["slots"] and d["dimension"].endswith(("_person", "_number")))["with"].append(r)
        own = [r for r in left if r["what"] == "feature" and r["name"] == f and r["cls"] not in D["agreeing_classes"]]
        groups = collections.OrderedDict()
        for r in own:
            groups.setdefault((r["bearer"], r["from"], r["to"]), []).append(r)
        for (bearer, x, y), rs in groups.items():
            for r in rs:
                left.remove(r)
            add(f"{bearer or 'other'}_{f}", rs)
        for r in take(lambda r: r["what"] == "feature" and r["name"] == f):      # verbs, adjectives, participles
            home = next((d for d in dims if d["dimension"] == f"subject_{f}" and (d["from"], d["to"]) == (r["from"], r["to"])), None) \
                or next((d for d in dims if d["dimension"].endswith("_" + f) and (d["from"], d["to"]) == (r["from"], r["to"])), None) \
                or next((d for d in dims if d["dimension"].startswith("swap_") and any(
                    w["name"] == f and (w["from"], w["to"]) == (r["from"], r["to"]) for w in d["with"])), None)
            if home is not None:
                home["with"].append(r)
                home["slots"] = sorted(set(home["slots"]) | {(r["i"], r["j"])})
            else:
                b_ = "subject" if r["bearer"] in ("verb", "predicate") else (r["bearer"] or "other")
                add(f"{b_}_{f}", [r])
    # 3. the dimensions of the table, in its order
    for name in D["order"]:
        sp = spec[name]
        core = take(lambda r: (r["what"] == "mark" and r["name"] in sp.get("marks", []) and r["name"] not in D.get("quiet_marks", []))
                    or (r["what"] == "slot" and r["name"] in sp.get("slots", []))
                    or (r["what"] == "feature" and r["name"] in sp.get("features", [])))
        if not core:
            continue
        first = next((r for r in core if r["what"] == "mark" and r["name"] == (sp.get("marks") or [""])[0]), core[0])
        core.remove(first)
        d = add(name, [first] + core)
        d["with"] += take(lambda r: r["name"] in sp.get("also", []) and r["what"] in ("mark", "feature", "slot"))
    # 4. state left over goes with its bearer
    for r in take(lambda r: r["what"] == "feature" and r["name"] == "state"):
        add(f"{r['bearer'] or 'other'}_state", [r])
    quiet = take(lambda r: r["what"] == "mark" and r["name"] in D.get("quiet_marks", []))
    same = not any(r["what"] != "mark" for r in raw)                 # the same parts with the same features
    return {"dimensions": dims, "rest": left, "quiet": quiet, "same_parts": same, "one": len(dims) == 1 and not left,
            "sure": min(a.get("sure", 1.0), b.get("sure", 1.0))}


def turned(r):
    """the answer for the pair read the other way"""
    def t(x):
        return {**x, "from": x["to"], "to": x["from"], "i": x["j"], "j": x["i"]}
    return {"dimensions": [{**d, "from": d["to"], "to": d["from"], "slots": sorted([(j, i) for i, j in d["slots"]], key=lambda x: (x[0] or -1, x[1] or -1)),
                            "with": [t(w) for w in d["with"]]} for d in r["dimensions"]],
            "rest": [t(x) for x in r["rest"]], "quiet": [t(x) for x in r["quiet"]], "same_parts": r["same_parts"],
            "one": r["one"], "sure": r["sure"]}


def brief(r):
    return "; ".join(f"{d['dimension']} {d['from'] or '∅'} → {d['to'] or '∅'}" + (f" (+{len(d['with'])})" if d["with"] else "")
                     for d in r["dimensions"]) + ("  REST " + ", ".join(f"{x['name']} {x['from'] or '∅'}→{x['to'] or '∅'}" for x in r["rest"]) if r["rest"] else "")


# ---------------------------------------------------------------- checks on the Tanakh
def no_accents(text):
    """the text without accents (the points stay)"""
    return "".join(ch for ch in text if not ("\u0591" <= ch <= "\u05af" or ch == "\u05bd"))


def short_clauses(src, lo=2, hi=6):
    """clause records of 2 to 6 words that are one segment with marks"""
    out = []
    for cid, c in src.clauses.items():
        if c["segments"] != 1 or not c["kind"]:
            continue
        s = src.segs[cid][0]
        if not lo <= s["last_w"] - s["first_w"] + 1 <= hi:
            continue
        out.append(src.record(cid))
    return out


def swap_keys(r):
    """the clause's sequence of parts with one noun, verb or adjective left open, with the word that stands there"""
    seq = [(s["cls"], s["lexeme"]) for s in r["slots"]]
    sig = tuple(tuple(s[f] for f in FEATURES[1:]) for s in r["slots"])
    for i, s in enumerate(r["slots"]):
        if s["kind"] == "stem" and s["cls"] in ("noun", "verb", "adj") and len(seq) > 1:
            yield (tuple(seq[:i] + [(s["cls"], "*")] + seq[i + 1:]), sig), s["lexeme"]


def small_keys(r):
    """the clause's sequence of parts without its small words (negator, article, question word, connective, object
    marker), with the small words it has"""
    SMALL = ("negator", "article", "question", "connective", "object_marker")
    rest = tuple((s["cls"], s["lexeme"]) + tuple(s[f] for f in FEATURES[1:]) for s in r["slots"] if s["small"] not in SMALL)
    if rest:
        yield rest, tuple((s["cls"], s["lexeme"]) for s in r["slots"] if s["small"] in SMALL)


def tanakh_check(show, per_group=4):
    D = dimensions()
    src = Tanakh()
    recs = short_clauses(src)
    n = collections.Counter()
    n["short clauses"] = len(recs)
    for r in recs[:3000]:                                            # a clause against itself gives nothing
        x = diff(r, r, D)
        n["self: not empty"] += bool(x["dimensions"] or x["rest"])
    groups = collections.defaultdict(list)
    for r in recs:
        groups[tuple((s["cls"], s["lexeme"]) for s in r["slots"])].append(r)
    dims, rests, ex = collections.Counter(), collections.Counter(), collections.defaultdict(list)
    same_marks = collections.Counter()
    for key, rs in groups.items():
        forms = collections.OrderedDict()
        for r in rs:
            forms.setdefault(no_accents(r["text"]), r)
        fs = list(forms.values())[:per_group]
        if len(fs) < 2:
            continue
        n["lexeme sequences with two forms or more"] += 1
        for i in range(len(fs)):
            for j in range(i + 1, len(fs)):
                x = diff(fs[i], fs[j], D)
                y = diff(fs[j], fs[i], D)
                n["pairs"] += 1
                n["turned round the same"] += brief(turned(x)) == brief(y)
                if x["same_parts"]:                                  # the same words read the same: only marks differ
                    n["same parts"] += 1
                    n["same parts, marks differ"] += bool(x["dimensions"] or x["rest"])
                    for d in x["dimensions"]:
                        same_marks[d["dimension"]] += 1
                    continue
                if not x["dimensions"] and not x["rest"]:
                    n["no difference found"] += 1
                    continue
                n["one dimension, no rest"] += x["one"]
                n["with a rest"] += bool(x["rest"])
                n[f"{min(len(x['dimensions']), 4)} dimensions"] += 1
                for d in x["dimensions"]:
                    dims[d["dimension"]] += 1
                    if x["one"] and len(ex[d["dimension"]]) < show:
                        ex[d["dimension"]].append(f"{fs[i]['text']}  |  {fs[j]['text']}   {brief(x)}")
                for r in x["rest"]:
                    rests[(r["what"], r["name"])] += 1
    print(json.dumps(n, ensure_ascii=False, indent=1))
    for title, keys in (("one word swapped", swap_keys), ("one small word more", small_keys)):
        g2 = collections.defaultdict(dict)
        for r in recs:
            for key, mine in keys(r):
                g2[key].setdefault(mine, r)
        m, d2, r2, e2 = collections.Counter(), collections.Counter(), collections.Counter(), collections.defaultdict(list)
        for key, forms in g2.items():
            fs = list(forms.values())[:3]
            if len(fs) < 2:
                continue
            m["groups"] += 1
            for i in range(len(fs)):
                for j in range(i + 1, len(fs)):
                    x = diff(fs[i], fs[j], D)
                    m["pairs"] += 1
                    m["one dimension, no rest"] += x["one"]
                    m["with a rest"] += bool(x["rest"])
                    for d in x["dimensions"]:
                        d2[d["dimension"]] += 1
                        if x["one"] and len(e2[d["dimension"]]) < show:
                            e2[d["dimension"]].append(f"{fs[i]['text']}  |  {fs[j]['text']}   {brief(x)}")
                    for r in x["rest"]:
                        r2[(r["what"], r["name"])] += 1
        print(f"=== {title}: {dict(m)}")
        print("    dimensions:", d2.most_common(14))
        print("    rest:", r2.most_common(8))
        for k, v in sorted(e2.items(), key=lambda kv: -d2[kv[0]])[:10]:
            for e in v:
                print(f"    {k}: {e}")
    print("=== the same lexemes, another form")
    print("dimensions:", dims.most_common())
    print("rest:", rests.most_common(12))
    print("same parts, marks differ:", same_marks.most_common())
    for k, v in sorted(ex.items(), key=lambda kv: -dims[kv[0]]):
        print(f"--- {k} ({dims[k]})")
        for e in v:
            print("   ", e)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("tanakh-check")
    p.add_argument("--show", type=int, default=3)
    p = sub.add_parser("show")
    p.add_argument("a")
    p.add_argument("b")
    a = ap.parse_args()
    if a.cmd == "tanakh-check":
        tanakh_check(a.show)
    else:
        src = Tanakh()
        x, y = src.record(a.a), src.record(a.b)
        r = diff(x, y)
        print(x["text"], "|", y["text"])
        print(json.dumps(r, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
