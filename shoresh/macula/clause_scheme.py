"""One clause scheme for the Tanakh and the Hebrew New Testaments (request 41, rows 1-5): the clause tables derived
from what both sides have, a tree of word parts (a head and a relation per part) and the clause each word belongs to.

The Tanakh build (source-examples, k1/hbo) reads its clauses and constituents from MACULA's groups. The Hebrew New
Testaments have no such groups, only the tagger's tree. This module derives the same tables from the tree alone, and
is first run on the Tanakh's own tree, where the tables it must give back are known:

  cd shoresh && .venv/bin/python -I macula/clause_scheme.py tanakh-constituents     # the share reproduced, per role

A verse is handed over as a list of parts in text order, each a dict:
  key      a sortable key of the part (Tanakh: (t, n); New Testament: (i, part))
  word     the key of its word
  head     the key of the part it depends on, or None
  rel      the relation to its head (the clause roles `s`, `o`, `o2`, `io`, `pp`, `adv`, ... or a phrase relation)
  cls      the part's class
  vtype    a verb's form (`qatal`, `participle_active`, ...), else empty
  depth    the depth of its word's clause
  kind     `stem`, `prefix` or `suffix`
  lexeme   the part's lexeme key
  clause   the clause of its word
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
K1 = HERE / "data" / "source-examples" / "k1"
ROLES = ("s", "o", "o2", "io", "pp", "adv", "vc", "aux")           # relations that make a part the head of a constituent
PATTERN_ROLES = {"v", "s", "o", "o2", "io", "p", "pp", "adv", "vc", "aux"}


def pattern_roles(rule):
    """the roles of a clause rule in text order (`S-V-PP` -> s, v, pp); empty where the rule is no such list"""
    parts = (rule or "").split("-")
    if parts and all(p and p == p.upper() and p.lower() in PATTERN_ROLES for p in parts):
        return [p.lower() for p in parts]
    return []


def rule_roles(rule):
    """(known, roles): what a clause rule says of the clause's constituents. A role list (`S-V-PP`) names them in
    text order; `V2CL`, `P2CL`, `PP2CL`, ... name the one constituent; any other rule (`Np2CL`, `cjpCLx`, ...) is a
    clause without constituents. Unknown (`''`, `-`, `other`): the tree alone decides."""
    if not rule or rule in ("-", "other"):
        return False, []
    r = pattern_roles(rule)
    if r:
        return True, r
    if rule.endswith("2CL") and rule[:-3].lower() in PATTERN_ROLES and rule[:-3] == rule[:-3].upper():
        return True, [rule[:-3].lower()]
    return True, []


class Tree:
    """the parts of one sentence or verse with their head links"""

    def __init__(self, parts):
        self.parts = {p["key"]: p for p in parts}
        self.kids = collections.defaultdict(list)
        for p in parts:
            if p["head"] is not None and p["head"] in self.parts:
                self.kids[p["head"]].append(p["key"])
        self.of_word = collections.defaultdict(list)
        for p in parts:
            self.of_word[p["word"]].append(p["key"])

    def subtree(self, key, stop=()):
        """the part and everything under it, not going into the parts of `stop`, nor along the chain that joins
        the clauses of a sentence (`run:N`)"""
        out, todo = [], [key]
        seen = set()
        while todo:
            k = todo.pop()
            if k in seen:
                continue
            seen.add(k)
            out.append(k)
            todo.extend(c for c in self.kids.get(k, ()) if c not in stop and not self.parts[c]["rel"].startswith("run:"))
        return out

    def ancestors(self, key):
        seen = []
        k = self.parts[key]["head"]
        while k is not None and k in self.parts and k not in seen:
            seen.append(k)
            k = self.parts[k]["head"]
        return seen


def clause_tops(tree, own):
    """the parts of a clause that no other part of the clause stands above: the clause's head, in text order.
    `own`: the keys of the clause's own parts. Stems first; a prefix (a conjunction that points out of the clause)
    counts only where no stem does."""
    own = set(own)
    tops = [k for k in sorted(own) if not any(a in own for a in tree.ancestors(k))]
    full = [k for k in tops if tree.parts[k]["cls"] not in ("cj", "rel")]   # not the word that opens the clause
    stems = [k for k in full if tree.parts[k]["kind"] == "stem"]
    return stems or full or tops


def span_words(tree, keys):
    ws = sorted({tree.parts[k]["word"] for k in keys})
    return ws[0], ws[-1]


def derive(tree, own, rule="", depth=0, head_role=None):
    """the constituents of one clause from the tree. Returns (pred word or None, pred_kind, rows); a row is a dict
    role, head (word), first, last (words), cls, prep, part (the heading part's key), basis.
    `rule`: the clause rule where one is known; it names the role of a head that the tree leaves without one.
    `head_role`: that role given directly (the tagger's value; `none` for a clause without constituents), in the
    rule's place.
    `depth`: the clause's depth; a part's `depth` is its own clause's. A part of a deeper clause that hangs on this
    clause's head with a role is a constituent of this clause (a clause as subject, object or after a preposition);
    one of a shallower clause is not (there this clause holds the predicate of the clause around it)."""
    known, want = rule_roles(rule) if head_role is None else (True, [head_role] if head_role != "none" else [])
    tops = clause_tops(tree, own)
    if not tops or (known and not want):
        return None, "none", []
    own_set = set(own)
    deps, heads = [], []                                             # parts that carry a role; the clause's heads
    for t in tops:
        p = tree.parts[t]
        h = p["head"]
        if p["rel"] in ROLES and h is not None and h in tree.parts and tree.parts[h]["depth"] > depth:
            deps.append(t)                                           # the predicate stands in a clause inside this one
            if h not in heads:
                heads.append(h)
        else:
            heads.append(t)
    for t in heads:
        for c in sorted(tree.kids.get(t, ())):
            q = tree.parts[c]
            if q["rel"] in ROLES and c not in deps and (c in own_set or (t in own_set and q["depth"] > depth)):
                deps.append(c)
    dep_set = set(deps)

    def whole(sub):
        for k in list(sub):                                          # with the word's own prefixes and suffixes
            sub.extend(x for x in tree.of_word[tree.parts[k]["word"]] if x not in sub and x not in dep_set)
        return sub

    rows = []
    for c in deps:
        p = tree.parts[c]
        if p["kind"] != "stem" and tree.parts[p["head"]]["word"] == p["word"]:
            sub = [c]                                                # a suffix: the word itself
        else:
            sub = whole(tree.subtree(c, stop=dep_set - {c}))
        first, last = span_words(tree, sub)
        rows.append({"role": p["rel"], "head": p["word"], "first": first, "last": last, "part": c, "sub": sub,
                     "basis": "relation"})
    left = list(want)
    for r in rows:
        if r["role"] in left:
            left.remove(r["role"])
    pred, pred_kind = None, "none"
    for top in heads:
        tp = tree.parts[top]
        if head_role is not None:
            role = left[0] if left else ""
        elif known:
            role = "v" if "v" in left and tp["cls"] == "verb" else left[0] if len(left) == 1 else \
                "p" if "p" in left else left[0] if left else ""
        else:
            role = "v" if tp["cls"] == "verb" else ""
        if not role:
            continue
        if role in left:
            left.remove(role)
        w = tp["word"]
        if role == "v":
            sub = [top]
            for c in tree.kids.get(top, ()):                         # verbs joined into one predicate
                if tree.parts[c]["rel"].startswith("VPandVP") and tree.parts[c]["cls"] == "verb":
                    sub.extend(tree.subtree(c, stop=dep_set))
        else:
            away = {c for c in tree.kids.get(top, ())                # a conjunction or relative word on another word
                    if (tree.parts[c]["cls"] in ("cj", "rel") and tree.parts[c]["word"] != w)   # opens the clause;
                    or (c not in own_set and tree.parts[c]["depth"] <= depth)}   # a clause beside this one is no part
            sub = whole(tree.subtree(top, stop=dep_set | away))
        first, last = span_words(tree, sub)
        rows.append({"role": role, "head": w, "first": first, "last": last, "part": top, "sub": sub,
                     "basis": "rule" if known and role != "v" else "head"})
        if role in ("v", "p") and pred is None:
            pred, pred_kind = w, role
    for r in rows:
        r["cls"] = const_class(tree, r)
        r["prep"] = const_prep(tree, r)
    rows.sort(key=lambda r: (r["first"], r["role"] != "v", r["head"]))
    return pred, pred_kind, rows


def const_prep(tree, r):
    """the lexeme of the preposition that opens the constituent"""
    if r["role"] == "v":
        return ""
    ks = sorted(r["sub"])
    for k in ks:
        p = tree.parts[k]
        if p["cls"] == "prep":
            return p["lexeme"] or ""
        if p["cls"] not in ("cj", "art", "om"):
            break
    return ""


def const_class(tree, r):
    """the constituent's class, as MACULA names its group: `pp` after a preposition, `np` for a noun, pronoun or
    participle with anything beside it (an article, the object marker, a dependent), `cl` for a clause, else the
    head's own class"""
    p = tree.parts[r["part"]]
    parts = [tree.parts[k] for k in r["sub"]]
    words = {q["word"] for q in parts}
    if r["role"] == "v":
        return "vp" if len(words) > 1 or any(q["cls"] == "x" for q in (tree.parts[c] for c in tree.kids.get(r["part"], ()))) else "verb"
    if const_prep(tree, r):
        return "pp"
    more = [q for q in parts if q is not p and q["cls"] != "cj"]
    if p["cls"] == "verb":
        return "verb" if len(words) == 1 else "np" if p.get("vtype", "").startswith("participle") else "cl"
    if p["kind"] == "suffix" and not more:
        return "pron"
    if p["cls"] in ("noun", "pron"):
        return "np" if more else p["cls"]
    if p["cls"] in ("om", "art"):                                    # the object marker as head (`אֹתוֹ`); an article
        return "np"
    if more and len(words) > 1:
        return {"adj": "adjp", "adv": "advp", "num": "nump", "ij": "ijp"}.get(p["cls"], "np")
    return p["cls"] or ""


# ---------------------------------------------------------------- clause marks by rule
NEGATORS = {"3808", "0408", "0409", "0369", "1077", "3809", "1115"}   # the Strong numbers clause-columns reads as negators
FINITE = {"qatal", "wayyiqtol", "yiqtol", "weqatal", "imperative", "jussive", "cohortative"}
SKIP = {"cj", "rel", "ptcl", "ij", "art"}
FRONT = {"s", "o", "o2", "io", "pp", "adv", "p"}


def strong(lexeme):
    return (lexeme or "").rsplit(":", 1)[-1]


def clause_verb(tree, own):
    """the clause's verb as clause-columns takes it: the first finite verb among its words, else the first verb"""
    vs = [k for k in sorted(own) if tree.parts[k]["cls"] == "verb"]
    fin = [k for k in vs if tree.parts[k]["vtype"] in FINITE]
    return (fin or vs or [None])[0]


def marks_by_rule(tree, own, rows):
    """kind, pattern, fronted, subject_form, neg_scope and a first transitivity from the tree and the constituents
    (`rows` of derive); each as clause-columns defines it on MACULA's words"""
    own = sorted(own)
    verb = clause_verb(tree, own)
    vw = tree.parts[verb]["word"] if verb else None
    m = {"kind": "vc" if verb else "nc"}
    m["pattern"] = "-".join(r["role"].upper() for r in rows)
    def role_of(k):
        """the role a part stands in: that of the constituent around it; a preposition outside every constituent
        that governs the clause itself counts as `pp`, as clause-columns counts it on MACULA's words"""
        for r in rows:
            if r["role"] != "v" and (k in r["sub"] or k == r["part"]):
                return r["role"]
        pt = tree.parts[k]                                           # `לִהְיוֹת`, `כַּאֲשֶׁר צִוָּה`
        return "pp" if pt["cls"] == "prep" and ((pt["rel"] or "").startswith(("PrepCL", "PpRelp"))
                                                or pt["head"] == verb) else ""
    if not verb:
        m["fronted"] = "verbless"
    else:
        m["fronted"] = next((role_of(k) for k in own if k < verb and tree.parts[k]["cls"] not in SKIP | {"verb"}
                             and strong(tree.parts[k]["lexeme"]) not in NEGATORS and role_of(k) in FRONT), "none")
    subj = [k for k in own if tree.parts[k]["cls"] in ("noun", "pron", "adj", "num") and role_of(k) == "s"]
    if subj:
        m["subject_form"] = "noun" if any(tree.parts[k]["cls"] != "pron" for k in subj) else "pronoun"
    else:
        m["subject_form"] = "zero" if verb and tree.parts[verb]["vtype"] in FINITE else "none"
    m["neg_scope"] = "none"
    for i, k in enumerate(own):
        if strong(tree.parts[k]["lexeme"]) in NEGATORS:
            nxt = next((x for x in own[i + 1:] if tree.parts[x]["cls"] not in SKIP), None)
            m["neg_scope"] = "verb" if nxt is not None and (nxt == verb or tree.parts[nxt]["cls"] == "verb") else "constituent"
            break
    m["transitivity"] = "0" if not verb else "2" if any(r["role"] in ("o", "o2") for r in rows) else "1"
    return m


# ---------------------------------------------------------------- the Tanakh

def tanakh():
    """the Tanakh's parts per sentence, its clauses and its constituent table"""
    words = pq.read_table(K1 / "hbo" / "words.parquet", columns=["t", "id", "book", "chapter", "verse", "w", "text", "sentence",
                                                                 "clause"]).to_pylist()
    wd = {w["t"]: w for w in words}
    sent = collections.defaultdict(list)
    for p in pq.read_table(K1 / "hbo" / "pieces.parquet", columns=["t", "n", "kind", "class", "lexeme", "head_t",
                                                                   "head_n", "rel", "marks"]).to_pylist():
        w = wd.get(p["t"])
        if w is None:
            continue
        sent[(w["book"], w["sentence"])].append(
            {"key": (p["t"], p["n"]), "word": p["t"], "head": (p["head_t"], p["head_n"]) if p["head_t"] else None,
             "rel": p["rel"] or "", "cls": p["class"] or "", "kind": p["kind"], "lexeme": p["lexeme"] or "",
             "clause": w["clause"] or "", "vtype": json.loads(p["marks"] or "{}").get("type", "")})
    clauses = {c["clause"]: c for c in pq.read_table(K1 / "hbo" / "clauses.parquet").to_pylist()}
    for parts in sent.values():
        for p in parts:
            p["depth"] = clauses[p["clause"]]["depth"] if p["clause"] in clauses else 0
    cons = collections.defaultdict(list)
    for c in pq.read_table(K1 / "hbo" / "constituents.parquet").to_pylist():
        cons[c["clause"]].append(c)
    return wd, sent, clauses, cons


def layout_clauses(wd):
    """the Tanakh's clauses as the clause layout cuts them, the cut the New Testament tagger learned: per verse the
    segments (runs of words), joined into clauses by the layout's clause key. A segment holds the words of one k1
    clause, and often the conjunction or relative word that k1 counts to the clause around it.
    Returns {(book, chapter, verse): [segment]}; a segment is a dict seg, clause (the layout's key), parent, depth,
    kind, rule, words (k1 word numbers `t`)."""
    LAYOUT = HERE / "data" / "clause-layout" / "clauses"
    t_of = {w["id"][1:]: w["t"] for w in wd.values()}
    out = collections.defaultdict(list)
    for f in sorted(LAYOUT.glob("*/*.jsonl")):
        for line in f.open():
            r = json.loads(line)
            if r["language"] != "hbo":
                continue
            ts = sorted({t_of[k[:11]] for k in r["words"] if k[:11] in t_of})
            if ts:
                out[(r["book"], r["chapter"], r["verse"])].append(
                    {"seg": r["seg"], "clause": r["clause_key"], "parent": r["parent_key"], "depth": r["depth"],
                     "kind": r["kind"] or "", "rule": r["rule"] or "", "words": ts})
    for segs in out.values():
        segs.sort(key=lambda s: s["words"][0])
    return out


def join_segments(segs):
    """the clauses of a verse from its segments: [(first segment, [segments])], segments with one clause key joined"""
    by = collections.OrderedDict()
    for s in segs:
        by.setdefault(s["clause"], []).append(s)
    return [(v[0], v) for v in by.values()]


def tanakh_units(cut, n):
    """the Tanakh's clauses to derive from: (sentence key, own part keys, k1 clause id, rule, depth), with k1's own
    clauses (`k1`) or with the clause layout's segments joined (`layout`, the New Testament's cut)"""
    wd, sent, clauses, cons = tanakh()
    units = []
    if cut == "k1":
        for sk, parts in sent.items():
            own = collections.defaultdict(list)
            for p in parts:
                if p["clause"]:
                    own[p["clause"]].append(p["key"])
            for cid, keys in own.items():
                if cid in clauses:
                    units.append((sk, keys, cid, clauses[cid]["rule"], clauses[cid]["depth"], None))
    else:
        of_word = collections.defaultdict(list)
        for sk, parts in sent.items():
            for p in parts:
                of_word[p["word"]].append(p)
        lay = layout_clauses(wd)
        for vk, segs in lay.items():
            for s in segs:
                for t in s["words"]:
                    for p in of_word[t]:
                        p["depth"] = s["depth"]                      # the layout's depth, as the tagger gives it
        for vk, segs in lay.items():
            for first, group in join_segments(segs):
                ts = [t for s in group for t in s["words"]]
                maj = k1_clause_of(ts, wd, of_word)
                if not maj or maj not in clauses:
                    n["layout clauses without a k1 clause"] += 1
                    continue
                keys = [p["key"] for t in ts for p in of_word[t]]
                units.append(((vk[0], wd[ts[0]]["sentence"]), keys, maj, first["rule"], first["depth"], len(group)))
        seen = collections.Counter(u[2] for u in units)
        n["k1 clauses met"] = len(seen)
        n["k1 clauses met by two layout clauses"] = sum(1 for v in seen.values() if v > 1)
    return wd, sent, clauses, cons, units


def k1_clause_of(ts, wd, of_word):
    """the k1 clause a layout clause stands for: the clause of most of its words, the words that only open a clause
    (a conjunction, a relative word) left out"""
    maj = collections.Counter(wd[t]["clause"] for t in ts if wd[t]["clause"] and not all(
        p["cls"] in ("cj", "rel") for p in of_word[t])).most_common(1) or collections.Counter(
        wd[t]["clause"] for t in ts if wd[t]["clause"]).most_common(1)
    return maj[0][0] if maj else None


def tanakh_constituents(show, no_rule=False, cut="k1"):
    n = collections.Counter()
    per = collections.defaultdict(collections.Counter)
    miss = collections.defaultdict(list)
    wd, sent, clauses, cons, units = tanakh_units(cut, n)
    trees = {}
    for sk, keys, cid, rule, depth, nseg in units:
        if sk not in trees:
            trees[sk] = Tree(sent[sk])
        tree = trees[sk]
        keys = [k for k in keys if k in tree.parts]
        c = clauses[cid]
        if True:
            pred, pk, rows = derive(tree, keys, "" if no_rule else rule, depth)
            gold = cons.get(cid, [])
            n["clauses"] += 1
            n["rule as k1"] += rule == c["rule"]
            n["pred_kind right"] += pk == c["pred_kind"]
            n["pred right"] += (pred or 0) == (c["pred"] or 0)
            if (pred or 0) != (c["pred"] or 0) or pk != c["pred_kind"]:
                miss[f"pred {c['pred_kind']} -> {pk}"].append(cid)
            g = collections.Counter((r["role"], r["head"]) for r in gold)
            d = collections.Counter((r["role"], r["head"]) for r in rows)
            for k in g:
                per[k[0]]["gold"] += g[k]
                per[k[0]]["found"] += min(g[k], d.get(k, 0))
                if d.get(k, 0) < g[k]:
                    miss[f"missed {k[0]}"].append(cid)
            for k in d:
                per[k[0]]["derived"] += d[k]
                if g.get(k, 0) < d[k]:
                    miss[f"extra {k[0]}"].append(cid)
            gi = {}
            for r in gold:
                gi.setdefault((r["role"], r["head"]), r)
            for r in rows:
                gr = gi.get((r["role"], r["head"]))
                if gr is None:
                    continue
                per[r["role"]]["matched"] += 1
                per[r["role"]]["span"] += (r["first"], r["last"]) == (gr["first"], gr["last"])
                per[r["role"]]["class"] += r["cls"] == gr["class"]
                per[r["role"]]["prep"] += r["prep"] == (gr["prep"] or "")
                if (r["first"], r["last"]) != (gr["first"], gr["last"]):
                    miss[f"span {r['role']}"].append(cid)
                elif r["cls"] != gr["class"]:
                    miss[f"class {r['role']} {gr['class']} -> {r['cls']}"].append(cid)
            n["clauses all right"] += g == d
    print(json.dumps(n, ensure_ascii=False))
    tot = collections.Counter()
    for role, c in sorted(per.items(), key=lambda kv: -kv[1]["gold"]):
        tot.update(c)
        print(f"{role:4} gold {c['gold']:6} found {c['found']:6} ({c['found'] / max(c['gold'], 1):.3f}) derived {c['derived']:6} "
              f"(precision {c['found'] / max(c['derived'], 1):.3f})  of matched: span {c['span'] / max(c['matched'], 1):.3f} "
              f"class {c['class'] / max(c['matched'], 1):.3f} prep {c['prep'] / max(c['matched'], 1):.3f}")
    print(f"all  gold {tot['gold']} found {tot['found']} ({tot['found'] / tot['gold']:.4f}) derived {tot['derived']} "
          f"(precision {tot['found'] / tot['derived']:.4f}) span {tot['span'] / tot['matched']:.4f} "
          f"class {tot['class'] / tot['matched']:.4f} prep {tot['prep'] / tot['matched']:.4f}")
    for k, v in sorted(miss.items(), key=lambda kv: -len(kv[1]))[:show]:
        print(f"{len(v):6} {k}: {' '.join(v[:3])}")


def tanakh_marks(cut):
    """the rule-derived marks against the Tanakh's own, on the Tanakh's own tree"""
    n = collections.Counter()
    wd, sent, clauses, cons, units = tanakh_units(cut, n)
    trees = {}
    conf = collections.defaultdict(collections.Counter)
    for sk, keys, cid, rule, depth, nseg in units:
        if sk not in trees:
            trees[sk] = Tree(sent[sk])
        tree = trees[sk]
        keys = [k for k in keys if k in tree.parts]
        c = clauses[cid]
        gold = json.loads(c["marks"] or "{}")
        if not gold:
            continue
        rows = derive(tree, keys, rule, depth)[2]
        m = marks_by_rule(tree, keys, rows)
        gold["pattern"] = c["pattern"]
        n["clauses"] += 1
        for k, v in m.items():
            if k == "pattern" and not gold["pattern"]:
                continue
            n[k + " n"] += 1
            n[k] += v == gold.get(k)
            if v != gold.get(k):
                conf[k][(gold.get(k), v)] += 1
    for k in ("kind", "pattern", "fronted", "subject_form", "neg_scope", "transitivity"):
        print(f"{k:13} {n[k] / max(n[k + ' n'], 1):.4f} of {n[k + ' n']}   " +
              "; ".join(f"{g}->{v} {x}" for (g, v), x in conf[k].most_common(6)))


# ---------------------------------------------------------------- the tagger's new values
# The second tagger (hebrew_nt_layers) is trained once more with further values per segment, on the clause layout's
# segments (the cut the New Testament has). Its published values (tree, ten marks) stay those of the released
# model; from this one only the new values are read.
SCHEME_OUT = HERE / "data" / "clause-scheme"
NEW_MARKS = ("kind", "line_kind", "fronted", "subject_form", "transitivity", "neg_scope", "subject_switch",
             "head_role", "continues")


def layers():
    """hebrew_nt_layers set up for the scheme's values: its own folder, the ten marks and the new ones"""
    from macula import hebrew_nt_layers as L
    if L.OUT != SCHEME_OUT:
        L.OUT = SCHEME_OUT
        L.MARKS = tuple(L.MARKS) + NEW_MARKS
    return L


def continues_of(segs, j):
    """where the clause of segment j was begun: the nearest earlier segment of the verse with its clause key, in
    segments back (`-2`, `-3`, `-4+`), else `none`"""
    for i in range(j - 1, -1, -1):
        if segs[i]["clause"] == segs[j]["clause"]:
            return f"-{j - i}" if j - i < 4 else "-4+"
    return "none"


def join_candidate(depths, j):
    """the segment that segment j may carry on: the nearest earlier one of its depth with only deeper segments
    between them (a clause broken by a clause standing inside it), as steps back, or 0"""
    for i in range(j - 2, -1, -1):
        if not all(depths[k] > depths[j] for k in range(i + 1, j)):
            return 0
        if depths[i] == depths[j]:
            return j - i
    return 0


def joined(depths, said, unsure=0.8):
    """`continues` per segment from the depths and the tagger's value (value, sureness): a candidate by depth is
    joined where the tagger says so, or says `none` with less than `unsure`. On the Tanakh's test chapters this finds
    69 of 88 joins at 87% precision (the tagger alone 54 at 72%, the depth rule alone 79 at 18%)."""
    out = []
    for j in range(len(depths)):
        back = join_candidate(depths, j)
        v, p = said[j] if said[j] else ("none", 1.0)
        out.append((f"-{back}" if back < 4 else "-4+") if back and (v != "none" or p < unsure) else "none")
    return out


def scheme_prep():
    L = layers()
    wd, sent, clauses, cons = tanakh()
    of_word = collections.defaultdict(list)
    for parts in sent.values():
        for p in parts:
            of_word[p["word"]].append(p)
    lay = layout_clauses(wd)
    for segs in lay.values():
        for s in segs:
            for t in s["words"]:
                for p in of_word[t]:
                    p["depth"] = s["depth"]
    raw = collections.defaultdict(list)
    for p in pq.read_table(K1 / "hbo" / "pieces.parquet").to_pylist():
        raw[p["t"]].append(p)
    con_of = collections.defaultdict(dict)
    for cid, rows in cons.items():
        for c in rows:
            if c["head"]:
                con_of[c["head"]] = (c["sem_role"] or "-", c["ref_status"] or "-")
    verses = collections.OrderedDict()
    for w in wd.values():
        verses.setdefault((w["book"], w["chapter"], w["verse"]), []).append(w)
    trees = {}
    SCHEME_OUT.mkdir(parents=True, exist_ok=True)
    n = collections.Counter()
    with (SCHEME_OUT / "verses.jsonl").open("w") as f:
        for vk, ws in verses.items():
            ws.sort(key=lambda w: w["w"])
            idx, wi_of = {}, {}
            for wi, w in enumerate(ws):
                wi_of[w["t"]] = wi
                for p in sorted(raw[w["t"]], key=lambda p: p["n"]):
                    idx[(w["t"], p["n"])] = len(idx) + 1
            out_words = []
            for w in ws:
                ps = sorted(raw[w["t"]], key=lambda p: p["n"])
                hn = L.head_piece(ps, w["t"]) if ps else None
                sem, ref = con_of.get(w["t"], ("-", "-"))
                out_words.append({"text": L.pointed(w["text"]) or w["text"], "pieces": [
                    {"text": L.pointed(p["text"]) or p["text"], "class": p["class"] or "-",
                     "head": idx.get((p["head_t"], p["head_n"]), 0) if p["head_t"] else 0, "rel": p["rel"] or "-",
                     "sem_role": sem if p["n"] == hn else "-", "ref_status": ref if p["n"] == hn else "-",
                     "who_kind": (p["who"] or "").split(":")[0] or "-"} for p in ps]})
            segs = lay.get(vk, [])
            labels = {}
            for first, group in join_segments(segs):
                ts = [t for s in group for t in s["words"]]
                maj = collections.Counter(wd[t]["clause"] for t in ts if wd[t]["clause"] and not all(
                    p["cls"] in ("cj", "rel") for p in of_word[t])).most_common(1) or collections.Counter(
                    wd[t]["clause"] for t in ts if wd[t]["clause"]).most_common(1)
                c = clauses.get(maj[0][0]) if maj else None
                m = json.loads(c["marks"] or "{}") if c else {}
                marks = {k: L.mark_value(m, k) for k in L.MARKS if k not in ("head_role", "continues")}
                sk = (vk[0], wd[ts[0]]["sentence"])
                if sk not in trees:
                    trees[sk] = Tree(sent[sk])
                keys = [p["key"] for t in ts for p in of_word[t] if p["key"] in trees[sk].parts]
                rows = derive(trees[sk], keys, first["rule"], first["depth"])[2]
                head = next((r["role"] for r in rows if r["basis"] in ("head", "rule")), "none")
                marks["head_role"] = head
                n["head_role " + head] += 1
                for s in group:
                    labels[s["seg"]] = (marks, c["clause"] if c else "")
            cls = []
            for j, s in enumerate(segs):
                marks, cid = labels[s["seg"]]
                cont = continues_of(segs, j)
                n["continues " + cont] += 1
                cls.append({"words": [wi_of[t] for t in s["words"] if t in wi_of], "seg": s["seg"], "k1": cid,
                            "rule": s["rule"], "depth": s["depth"], "marks": {**marks, "continues": cont}})
            split = L.split_of(vk[0], vk[1])
            n[split] += 1
            f.write(json.dumps({"ref": f"{vk[0]} {vk[1]}:{vk[2]}", "split": split, "words": out_words, "clauses": cls},
                               ensure_ascii=False) + "\n")
    print(json.dumps(n, ensure_ascii=False))


def scheme_eval(plain, split):
    """on the Tanakh's test chapters: the constituents and marks derived from the tagger's own tree, the head's role
    from the clause layout's rule or from the tagger's `head_role`, the clauses joined by the layout's keys or by the
    tagger's `continues`; and each mark by rule against the tagger's own value for it"""
    L = layers()
    wd, sent, clauses, cons = tanakh()
    meta = {p["key"]: p for parts in sent.values() for p in parts}
    by_ref = collections.defaultdict(list)
    for w in wd.values():
        by_ref[f"{w['book']} {w['chapter']}:{w['verse']}"].append(w)
    model, bat, device, ck = L.load_model(plain)
    rows = L.load(split, plain)
    pred = L.predict(model, bat, rows, device)
    RULE_MARKS = ("kind", "fronted", "subject_form", "neg_scope", "transitivity")
    res = {}
    for tree_of in ("true", "tagger"):
        for join in ("layout", "tagger", "depth and tagger"):
            for head in ("rule", "tagger"):
                if tree_of == "true" and (join, head) != ("layout", "rule"):
                    continue
                n = collections.Counter()
                for v, pr in zip(rows, pred):
                    ws = sorted(by_ref[v["ref"]], key=lambda w: w["w"])
                    order = []
                    for w in ws:
                        order.extend(sorted(k for k in ((w["t"], i) for i in range(1, 12)) if k in meta))
                    if len(order) != len(pr["pieces"]):
                        n["verses skipped"] += 1
                        continue
                    seg_of = {}
                    for j, cl in enumerate(v["clauses"]):
                        for wi in cl["words"]:
                            seg_of[ws[wi]["t"]] = j
                    parts = []
                    for i, k in enumerate(order):
                        q = dict(meta[k])
                        if tree_of == "tagger":
                            h = pr["pieces"][i]["head"]
                            q["head"] = order[h - 1] if 0 < h <= len(order) and h - 1 != i else None
                            q["rel"] = pr["pieces"][i]["rel"] if pr["pieces"][i]["rel"] not in ("-", "other") else ""
                        elif q["head"] not in meta or meta[q["head"]]["word"] not in seg_of:
                            q["head"] = None
                        j = seg_of.get(k[0])
                        q["depth"] = v["clauses"][j]["depth"] if j is not None else 0
                        parts.append(q)
                    in_verse = {q["key"] for q in parts}
                    for q in parts:
                        if q["head"] not in in_verse:
                            q["head"] = None
                    tree = Tree(parts)
                    group = list(range(len(v["clauses"])))            # segment -> the first segment of its clause
                    both = joined([cl["depth"] for cl in v["clauses"]],
                                  [(pr["clauses"][j] or {}).get("continues") for j in range(len(v["clauses"]))])
                    for j, cl in enumerate(v["clauses"]):
                        c = cl["marks"]["continues"] if join == "layout" else both[j] if join == "depth and tagger" else (
                            pr["clauses"][j] or {}).get("continues", ("none",))[0]
                        if j and join != "layout":
                            n["continues n"] += 1
                            n["continues right"] += c == cl["marks"]["continues"]
                            n["continues gold joined"] += cl["marks"]["continues"] != "none"
                            n["continues said joined"] += c != "none"
                            n["continues joined right"] += c != "none" and c == cl["marks"]["continues"]
                        if c not in ("none", "-", "other"):
                            back = int(c.strip("-+"))
                            if j - back >= 0:
                                group[j] = group[j - back]
                    for j0 in sorted(set(group)):
                        segs = [j for j in range(len(group)) if group[j] == j0]
                        cl0 = v["clauses"][j0]
                        cid = cl0["k1"]
                        if cid not in clauses:
                            continue
                        own = [k for k in order if seg_of.get(k[0]) in segs]
                        said = pr["clauses"][j0] or {}
                        if head == "rule":
                            pd, pk, drows = derive(tree, own, cl0["rule"], cl0["depth"])
                        else:
                            pd, pk, drows = derive(tree, own, "", cl0["depth"], head_role=said.get("head_role", ("none",))[0])
                        c = clauses[cid]
                        gold = cons.get(cid, [])
                        g = collections.Counter((r["role"], r["head"]) for r in gold)
                        d = collections.Counter((r["role"], r["head"]) for r in drows)
                        gs = {(r["role"], r["head"]): (r["first"], r["last"]) for r in gold}
                        n["clauses"] += 1
                        n["gold"] += sum(g.values())
                        n["derived"] += sum(d.values())
                        n["found"] += sum(min(g[k], d.get(k, 0)) for k in g)
                        n["found with span"] += sum(1 for r in drows if gs.get((r["role"], r["head"])) == (r["first"], r["last"]))
                        n["pred_kind"] += pk == c["pred_kind"]
                        n["pred"] += (pd or 0) == (c["pred"] or 0)
                        n["clause all right"] += g == d
                        gm = cl0["marks"]
                        n["head_role tagger"] += said.get("head_role", ("",))[0] == gm["head_role"]
                        if gm["kind"] == "-":
                            continue
                        n["marked"] += 1
                        if c["pattern"]:
                            n["patterned"] += 1
                            n["pattern"] += "-".join(r["role"].upper() for r in drows) == c["pattern"]
                        rm = marks_by_rule(tree, own, drows)
                        for k in RULE_MARKS:
                            a, b = rm[k] == gm[k], said.get(k, ("",))[0] == gm[k]
                            n[k + " rule"] += a
                            n[k + " tagger"] += b
                            n[k + " either"] += a or b
                        for k in ("line_kind", "subject_switch"):
                            n[k + " tagger"] += said.get(k, ("",))[0] == gm[k]
                        tv = said.get("transitivity", ("",))[0]       # the tagger's, but 2 where an object is found
                        n["transitivity tagger, 2 with an object"] += ("2" if rm["transitivity"] == "2" else tv) == gm["transitivity"]
                r = {"clauses": n["clauses"], "constituents": n["gold"],
                     "found": round(n["found"] / max(n["gold"], 1), 4), "precision": round(n["found"] / max(n["derived"], 1), 4),
                     "found with span": round(n["found with span"] / max(n["gold"], 1), 4),
                     "clause all right": round(n["clause all right"] / max(n["clauses"], 1), 4),
                     "pred": round(n["pred"] / max(n["clauses"], 1), 4), "pred_kind": round(n["pred_kind"] / max(n["clauses"], 1), 4),
                     "pattern": round(n["pattern"] / max(n["patterned"], 1), 4),
                     "head_role tagger": round(n["head_role tagger"] / max(n["clauses"], 1), 4)}
                for k in RULE_MARKS:
                    for w in ("rule", "tagger", "either"):
                        r[f"{k} {w}"] = round(n[f"{k} {w}"] / max(n["marked"], 1), 4)
                for k in ("line_kind", "subject_switch"):
                    r[k + " tagger"] = round(n[k + " tagger"] / max(n["marked"], 1), 4)
                r["transitivity tagger, 2 with an object"] = round(n["transitivity tagger, 2 with an object"] / max(n["marked"], 1), 4)
                if join != "layout":
                    r["continues"] = {"segments": n["continues n"], "right": round(n["continues right"] / max(n["continues n"], 1), 4),
                                      "joined in truth": n["continues gold joined"], "said joined": n["continues said joined"],
                                      "joined right": n["continues joined right"]}
                res[f"tree {tree_of}, joined by {join}, head by {head}"] = r
    out = SCHEME_OUT / f"eval-{'unpointed' if plain else 'pointed'}-{split}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(res, ensure_ascii=False, indent=1))


def part_kinds(classes):
    """`prefix`, `stem` or `suffix` per part of a word from the parts' classes: a pronoun (or an ending `x`) after a
    part that can bear one is a suffix; the last part before that is the stem (right for 99.6% of the Tanakh's parts)"""
    k = len(classes) - 1
    while k > 0 and classes[k] in ("pron", "x") and classes[k - 1] not in ("cj", "art", "ptcl", "rel"):
        k -= 1
    return ["prefix"] * k + ["stem"] + ["suffix"] * (len(classes) - k - 1)


def released_trees(rows, plain):
    """the tree of the released second tagger (hebrew-nt-analysis's pieces.parquet) for verses in its input form: per
    verse a list of (head, rel, head_p, rel_p) per part, head counted from 1 over the verse's parts, 0 for none"""
    import torch
    from macula import hebrew_nt_layers as L
    keep = L.OUT, L.MARKS
    L.OUT, L.MARKS = L.HERE / "data" / "hebrew-nt-layers", tuple(k for k in L.MARKS if k not in NEW_MARKS)
    try:
        model, bat, device, ck = L.load_model(plain)
        pred = L.predict(model, bat, rows, device)
    finally:
        L.OUT, L.MARKS = keep
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return [[(q["head"], q["rel"], q["head_p"], q["rel_p"]) for q in pr["pieces"]] for pr in pred]


def clauses_of_verse(L, model, bat, device, verses, trees=None):
    """the scheme's clauses for verses as the New Testament has them: words with parts (text, class, lexeme), a verb
    form per word, and segments with a depth. `verses`: dicts words [{text, form, parts [{text, class, lexeme}]}],
    segments [{words [word numbers from 0], depth}]. Adds per verse `out`: a list of clauses, each a dict
    segments, own (word numbers), head_role, rows (the constituents), marks {name: (value, sureness, basis)}.
    `trees`: per verse the parts' (head, rel, head_p, rel_p) of another tagger (the released one, whose tree
    hebrew-nt-analysis publishes); without it the scheme model's own tree is read. `trees="released"` runs the
    released tagger here."""
    rows = [{"words": [{"text": w["text"], "pieces": [{"text": q["text"], "class": q["class"] or "-"} for q in w["parts"]]}
                       for w in v["words"]],
             "clauses": [{"words": list(sg["words"])} for sg in v["segments"]]} for v in verses]
    pred = L.predict(model, bat, rows, device)
    if isinstance(trees, str):
        trees = released_trees(rows, PLAIN[0])
    for vi, (v, pr) in enumerate(zip(verses, pred)):
        seg_of, parts, order = {}, [], []
        for j, sg in enumerate(v["segments"]):
            for wi in sg["words"]:
                seg_of[wi] = j
        for wi, w in enumerate(v["words"]):
            kinds = part_kinds([q["class"] for q in w["parts"]])
            for pi, q in enumerate(w["parts"]):
                order.append((wi, pi))
                j = seg_of.get(wi)
                parts.append({"key": (wi, pi), "word": wi, "cls": q["class"] or "", "kind": kinds[pi],
                              "lexeme": q.get("lexeme") or "", "clause": "",
                              "vtype": (w.get("form") or "").replace(" ", "_") if q["class"] == "verb" else "",
                              "depth": v["segments"][j]["depth"] if j is not None else 0})
        for i, q in enumerate(parts):
            h, rel, hp, rp = trees[vi][i] if trees is not None else (
                pr["pieces"][i]["head"], pr["pieces"][i]["rel"], pr["pieces"][i]["head_p"], pr["pieces"][i]["rel_p"])
            q["head"] = order[h - 1] if 0 < h <= len(order) and h - 1 != i else None
            q["rel"] = rel if rel not in ("-", "other", None) else ""
            q["head_p"], q["rel_p"] = hp, rp
        tree = Tree(parts)
        said = [pr["clauses"][j] or {} for j in range(len(v["segments"]))]
        cont = joined([sg["depth"] for sg in v["segments"]], [x.get("continues") for x in said])
        group = list(range(len(cont)))
        for j, c in enumerate(cont):
            if c != "none" and j - int(c.strip("-+")) >= 0:
                group[j] = group[j - int(c.strip("-+"))]
        out = []
        for j0 in sorted(set(group)):
            segs = [j for j in range(len(group)) if group[j] == j0]
            own = [k for k in order if seg_of.get(k[0]) in segs]
            hr = said[j0].get("head_role", ("none", 0.0))
            pd, pk, drows = derive(tree, own, "", v["segments"][j0]["depth"], head_role=hr[0])
            marks = {k: (x[0], x[1], "model") for k, x in said[j0].items() if k not in ("head_role", "continues")}
            for k, x in marks_by_rule(tree, own, drows).items():
                if k in RULE_FIRST:
                    marks[k] = (x, None, "derived")
            out.append({"segments": segs, "own": sorted({k[0] for k in own}), "head_role": hr, "pred": pd, "pred_kind": pk,
                        "rows": drows, "marks": marks, "continues": [cont[j] for j in segs],
                        "continues_p": [said[j].get("continues", ("none", None))[1] for j in segs]})
        v["out"] = out
        v["tree"] = tree
    return verses


# the marks a rule gives better than the tagger's own value on the Tanakh's test chapters (scheme-eval); the others
# (transitivity, line_kind, subject_switch) are the tagger's
RULE_FIRST = ("kind", "pattern", "fronted", "subject_form", "neg_scope")
PLAIN = [False]                                                      # whether the models read text without points


def e2e_verses(plain, tree="scheme"):
    """the Tanakh's test chapters read as the New Testament is read (see scheme_e2e): the verses with their `out` and
    `tree`, the Tanakh's words per verse, and its constituents per head word"""
    L = layers()
    wd, sent, clauses, cons = tanakh()
    by_ref = collections.defaultdict(list)
    for w in wd.values():
        by_ref[f"{w['book']} {w['chapter']}:{w['verse']}"].append(w)
    gold_of = collections.defaultdict(list)                          # head word t -> gold rows
    for cid, rows in cons.items():
        for r in rows:
            gold_of[r["head"]].append(r)
    name = "pred-test-model-dictabert-unpointed.jsonl" if plain else "pred-test-model-dictabert.jsonl"
    verses, n = [], collections.Counter()
    for line in (HERE / "data" / "clause-tagger" / name).open():
        v = json.loads(line)
        segs = []
        for wi, w in enumerate(v["words"]):
            if w["start"] or not segs:
                segs.append({"words": [], "depth": w["depth"]})
            segs[-1]["words"].append(wi)
        verses.append({"ref": v["ref"], "segments": segs, "words": [
            {"text": (L.unpointed if plain else L.pointed)(w["text"]) or w["text"], "form": w["form"],
             "parts": [{"text": q["text"], "class": q["class"], "lexeme": q.get("lexeme") or ""} for q in w["parts"]]}
            for w in v["words"]]})
    model, bat, device, ck = L.load_model(plain)
    PLAIN[0] = plain
    clauses_of_verse(L, model, bat, device, verses, trees="released" if tree == "released" else None)
    return verses, by_ref, gold_of


def scheme_e2e(plain, tree="scheme"):
    """the Tanakh's test chapters as the New Testament is read: the first tagger's own segments, depths, word parts
    and verb forms (its saved test predictions), then the tree, the joining and the constituents from them. Scored
    per verse against the Tanakh's constituents by role and head word."""
    verses, by_ref, gold_of = e2e_verses(plain, tree)
    n = collections.Counter()
    per = collections.defaultdict(collections.Counter)
    for v in verses:
        ws = sorted(by_ref[v["ref"]], key=lambda w: w["w"])
        if len(ws) != len(v["words"]):
            n["verses skipped (word count)"] += 1
            continue
        n["verses"] += 1
        wi_of = {w["t"]: i for i, w in enumerate(ws)}
        g = collections.Counter()
        gs = {}
        for w in ws:
            for r in gold_of.get(w["t"], ()):
                g[(r["role"], wi_of[w["t"]])] += 1
                gs[(r["role"], wi_of[w["t"]])] = (wi_of.get(r["first"]), wi_of.get(r["last"]))
        d = collections.Counter()
        ds = {}
        for c in v["out"]:
            n["clauses"] += 1
            for r in c["rows"]:
                d[(r["role"], r["head"])] += 1
                ds[(r["role"], r["head"])] = (r["first"], r["last"])
        for k in g:
            per[k[0]]["gold"] += g[k]
            per[k[0]]["found"] += min(g[k], d.get(k, 0))
            per[k[0]]["span"] += k in ds and ds[k] == gs[k]
        for k in d:
            per[k[0]]["derived"] += d[k]
    tot = collections.Counter()
    res = {"verses": n["verses"], "clauses": n["clauses"], "skipped": n["verses skipped (word count)"], "roles": {}}
    for role, c in sorted(per.items(), key=lambda kv: -kv[1]["gold"]):
        tot.update(c)
        res["roles"][role] = {"gold": c["gold"], "found": round(c["found"] / max(c["gold"], 1), 4),
                              "precision": round(c["found"] / max(c["derived"], 1), 4),
                              "found with span": round(c["span"] / max(c["gold"], 1), 4)}
    res["all"] = {"gold": tot["gold"], "derived": tot["derived"], "found": round(tot["found"] / tot["gold"], 4),
                  "precision": round(tot["found"] / tot["derived"], 4), "found with span": round(tot["span"] / tot["gold"], 4),
                  "constituents per clause": round(tot["derived"] / max(n["clauses"], 1), 2)}
    res["tree"] = tree
    (SCHEME_OUT / f"e2e-{'unpointed' if plain else 'pointed'}{'' if tree == 'scheme' else '-' + tree}-test.json").write_text(
        json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))


# ---------------------------------------------------------------- the scheme file and the Tanakh in its shape
SCHEME_VERSION = "0.4"
SCHEME_MARKS = ("kind", "force", "polarity", "mood", "time", "time_abs", "aspect", "relation", "voice", "negator",
                "connective", "line_kind", "fronted", "subject_form", "transitivity", "neg_scope", "subject_switch")
LEXEME_MARKS = {"negator": "string", "connective": "list"}           # lexeme keys, no closed value set
CONTENT = {"noun", "verb", "adj", "pron", "num"}                     # a stem of these classes is more than an opening word


def scheme_tables():
    """the scheme's tables and columns; value sets are named `<table>.<column>` and filled from categories.toml"""
    S, I, L = "string", "int", "list"
    marks = collections.OrderedDict()
    for k in SCHEME_MARKS:
        marks[k] = ({"type": LEXEME_MARKS[k], "kind": "lexeme", "prefix": "lex:", "basis": True} if k in LEXEME_MARKS
                    else {"type": S, "kind": "value", "values": "clauses." + k, "basis": True})
    tables = collections.OrderedDict([
        ("clauses", {"file": "clauses.parquet", "key": ["clause"], "columns": collections.OrderedDict([
            ("clause", {"type": S, "kind": "key"}), ("edition", {"type": S, "kind": "code", "required": True}),
            ("book", {"type": S, "kind": "code", "required": True}), ("chapter", {"type": I, "min": 1}),
            ("verse", {"type": I}), ("segments", {"type": I, "min": 1}),
            ("parent", {"type": S, "kind": "key", "basis": True}), ("depth", {"type": I}),
            ("rule", {"type": S, "kind": "code", "basis": True}), ("pattern", {"type": S, "kind": "code", "basis": True}),
            ("pred", {"type": S, "kind": "word"}),
            ("pred_kind", {"type": S, "kind": "value", "values": "clauses.pred_kind", "basis": True}),
            ("source_clause", {"type": S, "kind": "key"})] + list(marks.items()))}),
        ("segments", {"file": "segments.parquet", "key": ["clause", "seg"], "ordered": [["first_w", "last_w"]],
                      "columns": collections.OrderedDict([
            ("clause", {"type": S, "kind": "key"}), ("seg", {"type": I, "min": 1}),
            ("book", {"type": S, "kind": "code", "required": True}), ("chapter", {"type": I, "min": 1}),
            ("verse", {"type": I}), ("first_w", {"type": I, "min": 1}), ("last_w", {"type": I, "min": 1}),
            ("continues", {"type": I, "min": 1, "basis": True})])}),
        ("constituents", {"file": "constituents.parquet", "key": ["clause", "ord"], "columns": collections.OrderedDict([
            ("clause", {"type": S, "kind": "key"}), ("ord", {"type": I, "min": 1}),
            ("role", {"type": S, "kind": "value", "values": "constituents.role", "required": True, "basis": True}),
            ("head", {"type": S, "kind": "word", "required": True}), ("first", {"type": S, "kind": "word", "required": True}),
            ("last", {"type": S, "kind": "word", "required": True}),
            ("class", {"type": S, "kind": "value", "values": "constituents.class"}),
            ("prep", {"type": S, "kind": "lexeme", "prefix": "lex:"}), ("frame_role", {"type": S, "kind": "code", "basis": True}),
            ("sem_role", {"type": S, "kind": "value", "values": "constituents.sem_role", "basis": True}),
            ("ref_status", {"type": S, "kind": "value", "values": "constituents.ref_status", "basis": True}),
            ("ref_form", {"type": S, "kind": "value", "values": "constituents.ref_form"})])}),
        ("added", {"file": "added.parquet", "key": ["verb", "role", "frame_role", "kind"], "columns": collections.OrderedDict([
            ("clause", {"type": S, "kind": "key"}), ("verb", {"type": S, "kind": "word", "required": True}),
            ("role", {"type": S, "kind": "value", "values": "added.role"}),
            ("frame_role", {"type": S, "kind": "value", "values": "added.frame_role", "basis": True}),
            ("kind", {"type": S, "kind": "value", "values": "added.kind", "required": True}),
            ("where", {"type": S, "kind": "value", "values": "added.where"}),
            ("form", {"type": S, "kind": "value", "values": "added.form"}),
            ("person", {"type": S, "kind": "value", "values": "added.person"}),
            ("number", {"type": S, "kind": "value", "values": "added.number"}),
            ("gender", {"type": S, "kind": "value", "values": "added.gender"}),
            ("antecedent", {"type": S, "kind": "part"}), ("who", {"type": S, "kind": "key", "basis": True}),
            ("who_reason", {"type": S, "kind": "value", "values": "added.who_reason"})])}),
        # the source's clauses that are no clause of the scheme: the bridge to the source's own tree. Only an edition
        # with a source tree has it (the Tanakh: MACULA's clause elements, as the Tanakh build holds them)
        ("source_groups", {"file": "source_groups.parquet", "key": ["source_clause"], "editions": ["hbo"],
                           "columns": collections.OrderedDict([
            ("source_clause", {"type": S, "kind": "key"}), ("book", {"type": S, "kind": "code", "required": True}),
            ("kind", {"type": S, "kind": "value", "values": "source_groups.kind", "required": True}),
            ("rule", {"type": S, "kind": "code"}), ("parent", {"type": S, "kind": "key"}),
            ("holds", {"type": L, "kind": "key"}), ("words", {"type": L, "kind": "word"}),
            ("in_clauses", {"type": L, "kind": "key"})])}),
        # order statements: a relation between two words, by the classes of head and dependent, with how often the
        # dependent stands before and after its head; `count` is the commoner side, `against` the other, `places`
        # up to three dependents of the commoner side
        ("orders", {"file": "orders.parquet", "key": ["rel", "head_class", "dep_class"], "columns": collections.OrderedDict([
            ("id", {"type": S, "kind": "key", "required": True}), ("rel", {"type": S, "kind": "code"}),
            ("head_class", {"type": S, "kind": "code"}), ("dep_class", {"type": S, "kind": "code"}),
            ("before", {"type": I}), ("after", {"type": I}), ("count", {"type": I, "min": 1}), ("against", {"type": I}),
            ("places", {"type": L, "kind": "word"})])}),
        # a Hebrew New Testament only: from each clause carried from the Greek (the Tanakh build's tables of the
        # edition) to the clauses read from the Hebrew that share its words. For whoever holds the carried ids.
        ("clause_join", {"file": "clause_join.parquet", "key": ["carried_clause", "clause"], "editions": ["heb_scg", "heb_mod"],
                         "columns": collections.OrderedDict([
            ("carried_clause", {"type": S, "kind": "key"}), ("clause", {"type": S, "kind": "key"}),
            ("kind", {"type": S, "kind": "value", "values": "clause_join.kind", "required": True}),
            ("shared", {"type": I, "min": 1})])})])
    for t in tables.values():                                        # a key's columns are filled, but for the two
        for col in t["key"]:                                         # roles of an unsaid mention, of which one may wait
            if col not in ("role", "frame_role"):
                t["columns"][col]["required"] = True
    return tables


def _toml(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {_toml(x)}" for k, x in v.items()) + " }"
    return "[" + ", ".join(_toml(x) for x in v) + "]"


def scheme_file():
    """clause-scheme.toml from the tables above and the Tanakh build's categories.toml (codes, and the Hebrew terms
    where a category is named by terms)"""
    import tomllib
    cats = tomllib.loads((K1 / "hbo" / "categories.toml").read_text())
    tables = scheme_tables()
    FROM = {"added.frame_role": ("added", "role")}                   # the frame labels k1 holds in `added.role`
    OWN = {"added.role": ["s", "o", "poss"],                         # the grammatical role of an unsaid mention
           "source_groups.kind": ["group", "opener", "inside"],     # what a source clause outside the scheme is
           "clause_join.kind": ["same", "split", "merged", "partial"]}
    MORE = {"added.who_reason": ["linked", "speech", "model", "model_new"]}   # a New Testament referent's basis
    sets = collections.OrderedDict()
    for t in tables.values():
        for col, c in t["columns"].items():
            name = c.get("values")
            if not name or name in sets:
                continue
            if name in OWN:
                sets[name] = {"codes": OWN[name]}
                continue
            tn, cn = FROM.get(name, name.split("."))
            vals = cats[tn][cn]["values"]
            src = cats[tn][cn].get("source", "")
            if any("term" in v for v in vals):
                sets[name] = {"source": src, "terms": [{"code": v["code"], "term": v["term"]} for v in vals]}
            else:
                sets[name] = {"source": src, "codes": [v["code"] for v in vals] + MORE.get(name, [])}
    out = ["# clause-scheme.toml: the clause level of the Tanakh and of the Hebrew New Testaments in one form.",
           "# Written by macula/clause_scheme.py scheme-file from its table list and the Tanakh build's categories.toml.",
           "# A column with `basis = true` has `<column>_basis` (one of `bases`) and `<column>_p` (0..1 or empty) beside it.",
           "# Kinds: key (a row id), word (a word id of the edition), part (word id, a dot, the part's number),",
           "# lexeme (a lexeme key), value (one of the value set named in `values`), code (a code with no closed list).",
           "#",
           "# The cut. A clause of the scheme begins with the word that opens it (a conjunction, a relative word, a",
           "# preposition before a clause); the cut is derived, the clause layout's. Where an edition has a source tree",
           "# (the Tanakh: MACULA's clause elements), that tree stays the anchor: `clauses.source_clause` names the",
           "# source's clause a scheme clause stands for, and `source_groups` has one row for every source clause that",
           "# is no clause of the scheme: `group` (owns no word, holds other clauses: coordination and the like),",
           "# `opener` (owns only the opening word: `holds` is what that word governs, `in_clauses` where it sits here),",
           "# `inside` (a clause of the source that the scheme does not cut out: `in_clauses` is the clause around it).",
           "# `holds` lists the nearest scheme clauses beneath it, in text order; `parent` is the source's own parent.",
           "# A table with `editions` is there for those editions only.",
           "", f'scheme = "clause-scheme"', f'version = "{SCHEME_VERSION}"',
           'bases = ["given", "derived", "linked", "model"]', ""]
    for name, t in tables.items():
        out.append(f"[tables.{name}]")
        for k in ("file", "key", "ordered", "editions"):
            if k in t:
                out.append(f"{k} = {_toml(t[k])}")
        out.append("")
        out.append(f"[tables.{name}.columns]")
        for col, c in t["columns"].items():
            out.append(f"{col} = {_toml(c)}")
        out.append("")
    for a, b in (("segments.clause", "clauses.clause"), ("constituents.clause", "clauses.clause"),
                 ("added.clause", "clauses.clause"), ("clauses.parent", "clauses.clause"),
                 ("source_groups.holds", "clauses.clause"), ("source_groups.in_clauses", "clauses.clause"),
                 ("clause_join.clause", "clauses.clause"),
                 ("source_groups.parent", ["clauses.source_clause", "source_groups.source_clause"])):
        out += ["[[joins]]", f'from = "{a}"', f"to = {_toml(b)}", ""]
    out += ["# no source clause is both a clause of the scheme and a row of source_groups",
            "[[disjoint]]", 'a = "source_groups.source_clause"', 'b = "clauses.source_clause"', ""]
    for name, v in sets.items():
        out.append(f'[values."{name}"]')
        if v.get("source"):
            out.append(f"source = {_toml(v['source'])}")
        if "codes" in v:
            out.append(f"codes = {_toml(v['codes'])}")
        else:
            out.append("terms = [")
            out += [f"  {_toml(x)}," for x in v["terms"]]
            out.append("]")
        out.append("")
    SCHEME_OUT.mkdir(parents=True, exist_ok=True)
    (SCHEME_OUT / "clause-scheme.toml").write_text("\n".join(out))
    print(f"[clause_scheme] {SCHEME_OUT / 'clause-scheme.toml'}: {len(tables)} tables, {len(sets)} value sets")


def write_scheme_table(folder, name, rows):
    """rows (dicts) as the scheme's table: every column of the scheme, `_basis` and `_p` beside a column with a basis"""
    import pyarrow as pa
    t = scheme_tables()[name]
    T = {"string": pa.string(), "int": pa.int64(), "list": pa.list_(pa.string())}
    fields = []
    for col, c in t["columns"].items():
        fields.append((col, T[c["type"]]))
        if c.get("basis"):
            fields += [(col + "_basis", pa.string()), (col + "_p", pa.float64())]
    folder.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({n: pa.array([r.get(n) for r in rows], type=ty) for n, ty in fields}), folder / t["file"],
                   compression="zstd")
    return len(rows)


def tanakh_export():
    """the Tanakh in the scheme's shape: the clause layout's cut (the New Testament's), the values of k1/hbo, and
    `source_groups`, the bridge to MACULA's own clauses (every clause of k1/hbo is a scheme clause's source or a row
    there; the account is written to ACCOUNT.json and the export stops if it does not close)"""
    import tomllib
    cats = tomllib.loads((K1 / "hbo" / "categories.toml").read_text())
    basis_of = lambda t, c: cats.get(t, {}).get(c, {}).get("basis", "given")
    n = collections.Counter()
    wd, sent, clauses, cons = tanakh()
    of_word = collections.defaultdict(list)
    for parts in sent.values():
        for p in parts:
            of_word[p["word"]].append(p)
    lay = layout_clauses(wd)
    cid_of_seg, id_of_key, out_c, out_s, by_k1 = {}, {}, [], [], collections.defaultdict(list)
    groups = []
    for vk, segs in lay.items():
        for first, group in join_segments(segs):
            cid = f"cl:hbo:{vk[0]}.{vk[1]}.{vk[2]}.{first['seg']}"
            id_of_key[(vk[0], first["clause"])] = cid
            groups.append((vk, first, group, cid))
    word_clause = {}
    for vk, first, group, cid in groups:
        ts = [t for s in group for t in s["words"]]
        for t in ts:
            word_clause[t] = cid
        k1 = k1_clause_of(ts, wd, of_word)
        c = clauses.get(k1)
        m = json.loads(c["marks"] or "{}") if c else {}
        by_k1[k1].append((cid, set(ts)))
        row = {"clause": cid, "edition": "hbo", "book": vk[0], "chapter": vk[1], "verse": vk[2], "segments": len(group),
               "parent": id_of_key.get((vk[0], first["parent"])), "depth": first["depth"], "rule": first["rule"] or None,
               "pattern": (c["pattern"] or None) if c else None,
               "pred": wd[c["pred"]]["id"] if c and c["pred"] in wd else None,
               "pred_kind": c["pred_kind"] if c else None, "source_clause": k1}
        for k in ("parent", "rule"):
            if row[k]:
                row[k + "_basis"] = "given"
        if row["pattern"]:
            row["pattern_basis"] = basis_of("clauses", "pattern")
        if row["pred_kind"]:
            row["pred_kind_basis"] = basis_of("clauses", "pred_kind")
        for k in SCHEME_MARKS:
            v = m.get(k)
            if v is None or v == [] or v == "":
                continue
            row[k] = [str(x) for x in v] if LEXEME_MARKS.get(k) == "list" else str(v)
            row[k + "_basis"] = basis_of("clauses", k)
        out_c.append(row)
        seen = {}
        for s in group:
            ws = [wd[t]["w"] for t in s["words"]]
            if ws != list(range(ws[0], ws[-1] + 1)):
                n["segments with a gap"] += 1
            r = {"clause": cid, "seg": s["seg"], "book": vk[0], "chapter": vk[1], "verse": vk[2], "first_w": ws[0],
                 "last_w": ws[-1], "continues": seen.get("last")}
            if r["continues"]:
                r["continues_basis"] = "given"
            seen["last"] = s["seg"]
            out_s.append(r)
    out_k = []
    for k1, rows in cons.items():
        homes = by_k1.get(k1)
        if not homes:
            n["constituents of a clause the layout does not hold"] += len(rows)
            continue
        per = collections.defaultdict(list)
        for r in rows:
            home = next((cid for cid, ts in homes if r["head"] in ts), homes[0][0])
            per[home].append(r)
        for cid, rs in per.items():
            for i, r in enumerate(sorted(rs, key=lambda r: (r["ord"]))):
                if r["head"] not in wd or r["first"] not in wd or r["last"] not in wd:
                    n["constituents with a word outside the table"] += 1
                    continue
                o = {"clause": cid, "ord": i + 1, "role": r["role"], "role_basis": basis_of("constituents", "role"),
                     "head": wd[r["head"]]["id"], "first": wd[r["first"]]["id"], "last": wd[r["last"]]["id"],
                     "class": r["class"] or None, "prep": r["prep"] or None, "frame_role": r["frame_role"] or None,
                     "sem_role": r["sem_role"] or None, "sem_role_basis": r["sem_role_basis"] or None,
                     "ref_status": r["ref_status"] or None, "ref_form": r["ref_form"] or None}
                if o["ref_status"]:
                    o["ref_status_basis"] = basis_of("constituents", "ref_status")
                if o["frame_role"]:
                    o["frame_role_basis"] = "given"                  # MACULA's own label
                out_k.append(o)
    out_a = []
    IN_VERB = next(v["term"] for v in cats["added"]["kind"]["values"] if v["code"] == "in_verb")
    POSS = next(v["term"] for v in cats["added"]["kind"]["values"] if v["code"] == "possessor")
    aramaic = {r["t"]: r["id"] for r in pq.read_table(K1 / "arc" / "words.parquet", columns=["t", "id"]).to_pylist()}
    part_id = lambda x: f"{wd[int(x.split('.')[0])]['id'] if int(x.split('.')[0]) in wd else aramaic[int(x.split('.')[0])]}.{x.split('.')[1]}"
    for r in pq.read_table(K1 / "hbo" / "added.parquet").to_pylist():
        if r["verb"] not in wd:
            n["added rows with a verb outside the table"] += 1
            continue
        ant = " ".join(part_id(x) for x in (r["antecedent"] or "").split()) or None     # an Aramaic word (Genesis 31:47, Ezra 7) is not in this table
        n["antecedents that are an Aramaic word"] += sum(int(x.split(".")[0]) not in wd for x in (r["antecedent"] or "").split())
        o = {"clause": word_clause.get(r["verb"]), "verb": wd[r["verb"]]["id"],
             "role": "s" if r["kind"] == IN_VERB else "poss" if r["kind"] == POSS else None,
             "frame_role": r["role"] if r["role"] != "poss" else None, "kind": r["kind"], "where": r["where"] or None,
             "form": r["form"] or None, "person": r["person"] or None, "number": r["number"] or None,
             "gender": r["gender"] or None, "antecedent": ant, "who": r["who"] or None, "who_reason": r["who_reason"] or None}
        if o["who"]:
            o["who_basis"] = "derived"
        if o["frame_role"]:
            o["frame_role_basis"] = "given"
        n["added rows whose grammatical role waits"] += o["role"] is None
        out_a.append(o)
    # the bridge to MACULA's own clauses: every clause of the Tanakh build is a scheme clause's source, or a row here
    first_t = {cid: min(ts) for homes in by_k1.values() for cid, ts in homes}
    is_source = {k1: [cid for cid, _ in homes] for k1, homes in by_k1.items() if k1}
    kids, own = collections.defaultdict(list), collections.defaultdict(list)
    for c in clauses.values():
        if c["parent"]:
            kids[c["parent"]].append(c["clause"])
    for t in sorted(wd):
        if wd[t]["clause"]:
            own[wd[t]["clause"]].append(t)
    stem = {p["word"]: p["cls"] for parts in sent.values() for p in parts if p["kind"] == "stem"}
    out_g = []
    for k1, c in clauses.items():
        if k1 in is_source:
            continue
        holds, todo = set(), list(kids[k1])
        while todo:                                                  # the nearest scheme clauses beneath it
            x = todo.pop()
            if x in is_source:
                holds.update(is_source[x])
            else:
                todo.extend(kids[x])
        ts = own[k1]
        kind = "group" if not ts else "inside" if any(stem.get(t) in CONTENT for t in ts) else "opener"
        sits = sorted({word_clause[t] for t in ts if t in word_clause}, key=first_t.get)
        n[f"source_groups: {kind}"] += 1
        n[f"source_groups: {kind} holding {min(len(holds), 2)}{'+' if len(holds) > 1 else ''}"] += 1
        if ts and len(sits) != 1:
            n[f"source_groups: words in {len(sits)} scheme clauses"] += 1
        out_g.append({"source_clause": k1, "book": None, "kind": kind, "rule": c["rule"] or None,
                      "parent": c["parent"] or None, "holds": sorted(holds, key=first_t.get) or None,
                      "words": [wd[t]["id"] for t in ts] or None, "in_clauses": sits or None})
    book_of = {}
    for w in wd.values():
        if w["clause"]:
            book_of.setdefault(w["clause"], w["book"])
    for g in out_g:                                                  # the book: of its own word, else of what it holds
        g["book"] = book_of.get(g["source_clause"]) or (g["holds"][0].split(":")[2].split(".")[0] if g["holds"] else None)
    by_g = {g["source_clause"]: g for g in out_g}
    for g in out_g:
        x = g
        while not g["book"] and x and x["parent"]:                   # a group with nothing beneath: its parent's book
            p_ = x["parent"]
            g["book"] = book_of.get(p_) or (by_g[p_]["book"] if p_ in by_g else None) or (
                is_source[p_][0].split(":")[2].split(".")[0] if p_ in is_source else None)
            x = by_g.get(p_)
    account = {"source clauses": len(clauses), "a scheme clause's source": len(is_source), "in source_groups": len(out_g),
               "scheme clauses": len(out_c), "scheme clauses without a source clause": sum(1 for r in out_c if not r["source_clause"]),
               "source clauses that two or more scheme clauses stand for": sum(1 for v in is_source.values() if len(v) > 1),
               "words": len(wd), "words in a scheme clause": len(word_clause),
               "words in no scheme clause": len(wd) - len(word_clause),
               "words the source puts in no clause": sum(1 for w in wd.values() if not w["clause"])}
    if account["source clauses"] != account["a scheme clause's source"] + account["in source_groups"]:
        raise SystemExit(f"the account of source clauses does not close: {account}")
    out_o = [{**{k: r[k] for k in ("id", "rel", "head_class", "dep_class", "before", "after", "count", "against")},
              "places": [wd[int(t)]["id"] for t in (r["places"] or "").split() if int(t) in wd] or None}
             for r in pq.read_table(K1 / "hbo" / "orders.parquet").to_pylist()]
    folder = SCHEME_OUT / "tanakh"
    for name, rows in (("clauses", out_c), ("segments", out_s), ("constituents", out_k), ("added", out_a),
                       ("source_groups", out_g), ("orders", out_o)):
        n[name] = write_scheme_table(folder, name, rows)
    (folder / "ACCOUNT.json").write_text(json.dumps(account, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(n, ensure_ascii=False))
    print(json.dumps(account, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("tanakh-constituents")
    p.add_argument("--show", type=int, default=40)
    p.add_argument("--no-rule", action="store_true", help="the tree alone, without the clause rule")
    p.add_argument("--cut", choices=("k1", "layout"), default="k1",
                   help="whose clauses: k1's own, or the clause layout's segments joined (the New Testament's cut)")
    p = sub.add_parser("tanakh-marks")
    p.add_argument("--cut", choices=("k1", "layout"), default="layout")
    sub.add_parser("scheme-prep")
    sub.add_parser("scheme-file")
    sub.add_parser("tanakh-export")
    for name in ("scheme-train", "scheme-score", "scheme-eval", "scheme-e2e"):
        p = sub.add_parser(name)
        p.add_argument("--unpointed", action="store_true")
        p.add_argument("--epochs", type=int, default=3)
        p.add_argument("--batch", type=int, default=16)
        p.add_argument("--seed", type=int, default=1)
        p.add_argument("--split", default="test")
        p.add_argument("--tree", choices=("scheme", "released"), default="scheme",
                       help="scheme-e2e: whose tree the constituents are derived from")
    a = ap.parse_args()
    if a.cmd == "tanakh-constituents":
        tanakh_constituents(a.show, a.no_rule, a.cut)
    elif a.cmd == "tanakh-marks":
        tanakh_marks(a.cut)
    elif a.cmd == "scheme-prep":
        scheme_prep()
    elif a.cmd == "scheme-file":
        scheme_file()
    elif a.cmd == "tanakh-export":
        tanakh_export()
    elif a.cmd == "scheme-train":
        layers().train(a.epochs, a.batch, a.seed, a.unpointed)
    elif a.cmd == "scheme-e2e":
        scheme_e2e(a.unpointed, a.tree)
    elif a.cmd == "scheme-eval":
        scheme_eval(a.unpointed, a.split)
    elif a.cmd == "scheme-score":
        m = layers().score(a.split, a.unpointed)
        (SCHEME_OUT / f"score-{'unpointed' if a.unpointed else 'pointed'}-{a.split}.json").write_text(
            json.dumps({k: round(v, 4) for k, v in m.items()}, indent=1) + "\n")


if __name__ == "__main__":
    main()
