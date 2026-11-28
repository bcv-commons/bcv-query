"""Probe sets for the Hebrew New Testaments, in a compact form: places and named changes, no Hebrew spelled out
(grammar probes, pieces 2 to 4; plan: internal-docs/grammar-probes-plan-2026-11-27.md, section 13).

A probe is a place in the text and one named change. Nothing here holds Hebrew text: a clause is its id, a word its
id, a word part `<word id>.<part>` (the part counted from 1, as in the scheme's `antecedent`), and a replacement is a
pointer to a real word of the same edition that has the wanted form (a donor). The text is made from the pinned
tables when it is needed (`show`, or resolve() from code); every clause carries a short hash of its text, so a
table read against another version of the text is caught.

  cd shoresh && .venv/bin/python -I macula/probe_sets.py pairs    [--editions heb_scg heb_mod]
  cd shoresh && .venv/bin/python -I macula/probe_sets.py changes  [--editions ...] [--no-read-back]
  cd shoresh && .venv/bin/python -I macula/probe_sets.py show ID [ID ...] [--plain]     # a pair, a probe or a clause

Output macula/data/probe-sets/<edition>/ (git-ignored):
  pairs.parquet    two real clauses that differ in one thing (macula/probe_diff.py names it): pair, a, b (clause ids),
                   carrier (clause | verse), dimension, from, to, a_at, b_at (the parts that differ), with (what goes
                   with the change), marks_differ (clause marks read differently beside it), bearer, found_by, from_kind, to_kind (a swapped word's kind), moves (research's
                   feature numbers), sure, known_words (every word is a form the Tanakh has), plain_differs, a_check, b_check
  changes.parquet  the catalogue of default changes (macula/probe_changes.toml) with what the build found for each
  probes.parquet   a place with one change made by code: probe, change, clause, dimension, from, to, moves, the edits
                   (edit_op put | add | drop | move; edit_at the place's word; edit_from the donor word), sure, default
                   (the chosen spread), known_words, plain_differs, made_one (the difference function reads one change), check (the place), made_check (the changed clause), and the
                   read-back of the layer model on the changed clause (read_moved, read_role, read_ok)
  clauses.parquet  every clause named above: clause, book, chapter, verse, first, last (word ids), words, check,
                   check_plain, sure, same_text, and the labels a probe may need (frame, hearer_kind, hearer_number, we)
  CHECKS.json      counts, and what the caps left out
and macula/data/probe-sets/PIN.json: the tables the ids and hashes are read against.

Read: the clause scheme's New Testament tables, hebrew-nt-analysis's words, features and tree, the probe labels
(macula/probe_labels.py). Not read: any translation, BHSA, TBTA.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
import tomllib
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyarrow as pa
import pyarrow.parquet as pq

from macula import probe_diff as PD
from macula.clause_tagger import unpointed

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = DATA / "probe-sets"
LABELS = DATA / "probe-labels"
EDITIONS = ("heb_scg", "heb_mod")
CONTENT = ("noun", "verb", "adj", "adv", "num")
PER_FORM_GROUP, PER_SWAP_GROUP, PER_SMALL_GROUP = 6, 5, 4            # clauses taken per group of candidates
CONTEXT = {"hearer_kind": [15], "we": [4], "plural_size": [5]}       # dimensions of the context, with research's features
CHANGES = HERE / "probe_changes.toml"
FEAT = ("type", "stem", "person", "number", "gender", "state", "definite")
SOFT = {"gender": ("", "c", "b"), "person": ("", "x"), "state": ("",)}    # values that go with any other value
MIN_SURE, DEFAULT_SURE, PER_CHANGE = 0.8, 0.9, 30                    # a place's sureness; the default spread per change
NEGATOR, AND = "3808", "2050b"
CONSECUTIVE = ("wayyiqtol", "weqatal")                               # written with the conjunction, first in their clause
CJ_DIMS = ("connective", "swap_cj", "added_cj")
NOT_HEADS = ("3605",)                                                # `כֹּל אֲשֶׁר`: not a noun to swap or to count
NOUN_MIN, NOUN_SHARE = 3, 0.6                                        # a donor noun: the kind in 3 places and 6 of 10
NOT_READ = ("line_kind", "subject_switch", "relation", "transitivity", "head_role", "continues")


def check(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def plain(text):
    return " ".join(unpointed(w) or w for w in text.split(" "))


def part_id(S, key):
    return f"{S.word[key[0]]['id']}.{key[1] + 1}"


def write(path, rows, schema):
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({c: pa.array([r.get(c) for r in rows], type=t) for c, t in schema}), path)


STR, LST, F64, BOOL, I32 = pa.string(), pa.list_(pa.string()), pa.float64(), pa.bool_(), pa.int32()
PAIRS = [("pair", STR), ("edition", STR), ("a", STR), ("b", STR), ("carrier", STR), ("dimension", STR), ("from", STR),
         ("to", STR), ("a_at", LST), ("b_at", LST), ("with", LST), ("marks_differ", LST), ("bearer", STR), ("found_by", STR), ("from_kind", STR),
         ("to_kind", STR), ("moves", pa.list_(I32)), ("sure", F64), ("known_words", BOOL), ("plain_differs", BOOL), ("a_check", STR),
         ("b_check", STR)]
CLAUSES = [("clause", STR), ("edition", STR), ("book", STR), ("chapter", I32), ("verse", I32), ("first", STR), ("last", STR),
           ("words", I32), ("check", STR), ("check_plain", STR), ("sure", F64), ("same_text", I32), ("frame", STR),
           ("hearer_kind", STR), ("hearer_number", STR), ("we", STR)]


# ---------------------------------------------------------------- an edition with its labels
class Edition:
    def __init__(self, ed):
        self.ed = ed
        self.S = S = PD.NT(ed)
        self.D = PD.dimensions()
        self.recs = [r for r in PD.short_clauses(S)
                     if all(s["lexeme"] for s in r["slots"] if s["cls"] in CONTENT and s["kind"] == "stem")]
        self.by_clause = {r["clause"]: r for r in self.recs}
        self.same = collections.Counter(r["text"] for r in self.recs)
        self.frame = {r["clause"]: r for r in pq.read_table(LABELS / ed / "frames.parquet").to_pylist()}
        key = lambda r: (S.at.get((r["book"], r["chapter"], r["verse"], r["i"])), r["part"])  # noqa: E731
        self.kind = {key(r): r["kind"] for r in pq.read_table(LABELS / ed / "kinds.parquet").to_pylist() if r["kind"]}
        self.we_part = {key(r): r["value"] for r in pq.read_table(LABELS / ed / "we.parquet").to_pylist()}
        self.size_part = {key(r): r["size"] for r in pq.read_table(LABELS / ed / "plural_size.parquet").to_pylist()}

    def we(self, r):
        """the clause's inclusive-we value where its first person plural parts have one (i or e)"""
        v = {self.we_part[s["key"]] for s in r["slots"] if s["key"] in self.we_part}
        return next(iter(v)) if len(v) == 1 and v <= {"i", "e"} else None

    def size(self, r):
        v = {self.size_part[s["key"]] for s in r["slots"] if s["key"] in self.size_part}
        return next(iter(v)) if len(v) == 1 else None

    def clause_row(self, cid, r=None):
        S = self.S
        r = r or self.by_clause.get(cid) or S.record(cid)
        c, f = S.clauses[cid], self.frame.get(cid, {})
        return {"clause": cid, "edition": self.ed, "book": c["book"], "chapter": c["chapter"], "verse": c["verse"],
                "first": S.word[r["ts"][0]]["id"], "last": S.word[r["ts"][-1]]["id"], "words": r["words"],
                "check": check(r["text"]), "check_plain": check(plain(r["text"])), "sure": r["sure"],
                "same_text": self.same.get(r["text"], 1), "frame": f.get("frame"), "hearer_kind": f.get("hearer_kind"),
                "hearer_number": f.get("hearer_number"), "we": self.we(r)}


def known(r):
    """every word of the clause is a form the Tanakh has (its lexeme and form are that form's, not a model's guess)"""
    return all(s.get("known", True) for s in r["slots"] if s["cls"] in CONTENT + ("pron",))


def signature(slots):
    return tuple((s["cls"], s["lexeme"]) + tuple(s[f] for f in PD.FEATURES[1:]) for s in slots)


# ---------------------------------------------------------------- pairs the text holds
def candidates(E, n):
    """pairs of short clauses worth comparing, with how they were found. A clause text counts once (its surest
    place); the caps per group are counted in `n`."""
    S = E.S
    best = {}
    for r in sorted(E.recs, key=lambda r: (-r["sure"], r["ts"][0])):
        best.setdefault(r["text"], r)
    recs = sorted(best.values(), key=lambda r: r["ts"][0])
    n["short clauses"], n["different texts"] = len(E.recs), len(recs)
    seen = set()

    def give(a, b, how):
        k = (min(a["clause"], b["clause"]), max(a["clause"], b["clause"]))
        if a["clause"] != b["clause"] and k not in seen:
            seen.add(k)
            return (a, b, how) if a["ts"][0] < b["ts"][0] else (b, a, how)

    def within(groups, cap, how, spread=None):
        for rs in groups:
            rs = sorted(rs, key=lambda r: (-r["sure"], r["ts"][0]))
            if spread:                                               # one per kind first, then the rest
                first, rest, got = [], [], set()
                for r, k in zip(rs, spread(rs)):
                    (first if k not in got else rest).append(r)
                    got.add(k)
                rs = first + rest
            n[f"{how}: groups"] += len(rs) > 1
            n[f"{how}: clauses left out by the cap of {cap}"] += max(0, len(rs) - cap)
            rs = rs[:cap]
            for i in range(len(rs)):
                for j in range(i + 1, len(rs)):
                    p = give(rs[i], rs[j], how)
                    if p:
                        yield p

    # the same words in another form
    g = collections.defaultdict(list)
    for r in recs:
        g[tuple((s["cls"], s["lexeme"]) for s in r["slots"])].append(r)
    yield from within(g.values(), PER_FORM_GROUP, "same_words")
    # one word swapped
    g = collections.defaultdict(dict)
    at = {}
    for r in recs:
        for i, (key, mine) in enumerate(PD.swap_keys(r)):
            if mine and mine not in g[key]:
                g[key][mine] = r
                at[(key, r["clause"])] = next(s["key"] for s in r["slots"] if s["lexeme"] == mine and s["kind"] == "stem")
    for key, forms in g.items():
        yield from within([list(forms.values())], PER_SWAP_GROUP, "swap",
                          spread=lambda rs, key=key: [E.kind.get(at[(key, r["clause"])]) for r in rs])
    # one small word more
    g = collections.defaultdict(dict)
    for r in recs:
        for key, mine in PD.small_keys(r):
            g[key].setdefault(mine, r)
    yield from within([list(f.values()) for f in g.values()], PER_SMALL_GROUP, "small_word")
    # one constituent more
    full = {}
    for r in recs:
        full.setdefault(signature(r["slots"]), r)
    for r in recs:
        for k in S.cons[r["clause"]]:
            if k["role"] in ("v", "p") or k["first"] not in S.t_of:
                continue
            lo, hi = S.t_of[k["first"]], S.t_of[k["last"]]
            rest = [s for s in r["slots"] if not lo <= s["key"][0] <= hi]
            other = full.get(signature(rest)) if rest else None
            if other is not None:
                p = give(other, r, "constituent")
                if p:
                    yield p


def pair_sure(E, a, b, dim):
    marks = E.D["dimensions"].get(dim, {}).get("marks", [])
    return round(min([a["sure"], b["sure"]] + [r["mark_p"][m] for r in (a, b) for m in marks if m in r["mark_p"]]), 3)


def pairs(E):
    S, n, rows = E.S, collections.Counter(), []
    dims = collections.Counter()
    moves = E.D.get("moves", {})
    for a, b, how in candidates(E, n):
        x = PD.diff(a, b, E.D)
        n["compared"] += 1
        if x["same_parts"] or not x["dimensions"]:
            n["compared: no difference in the parts"] += 1
            continue
        # one change in the words. Clause marks that differ beside it (the reading of the time, the order's name) are
        # listed, not counted: the Hebrew differs in one thing
        form = [d for d in x["dimensions"] if d["slots"]]
        beside = [d for d in x["dimensions"] if not d["slots"]]
        if len(form) != 1 or any(r["what"] != "mark" for r in x["rest"]):
            n[f"compared: {min(len(form), 3)} changes in the words" + (" and a rest" if x["rest"] else "")] += 1
            continue
        d = form[0]
        ty = next((w for w in [d] + d["with"] if w.get("name") == "type"), None)
        if d["dimension"] == "time" and ty:                          # a change of tense is named by the two forms
            beside = beside + [{"dimension": "time_read", "from": d["from"], "to": d["to"]}]
            d = {**d, "from": ty["from"], "to": ty["to"]}
        differ = [f"{m['dimension']}:{m['from'] or ''}>{m['to'] or ''}" for m in beside] + \
                 [f"{r['name']}:{r['from'] or ''}>{r['to'] or ''}" for r in x["rest"] + x["quiet"]]
        ia, ib = [i for i, _ in d["slots"] if i is not None], [j for _, j in d["slots"] if j is not None]
        row = {"edition": E.ed, "a": a["clause"], "b": b["clause"], "carrier": "clause", "dimension": d["dimension"],
               "from": d["from"] or "", "to": d["to"] or "", "a_at": [part_id(S, a["slots"][i]["key"]) for i in ia],
               "b_at": [part_id(S, b["slots"][j]["key"]) for j in ib],
               "with": [f"{w['name']}:{w['from'] or ''}>{w['to'] or ''}" for w in d["with"]],
               "marks_differ": differ, "bearer": d.get("bearer") or "", "found_by": how, "moves": moves.get(d["dimension"], []),
               "sure": pair_sure(E, a, b, d["dimension"]), "known_words": known(a) and known(b),
               "plain_differs": plain(a["text"]) != plain(b["text"]),
               "a_check": check(a["text"]), "b_check": check(b["text"])}
        if d["dimension"].startswith("swap_") and ia and ib:
            row["from_kind"], row["to_kind"] = E.kind.get(a["slots"][ia[0]]["key"]), E.kind.get(b["slots"][ib[0]]["key"])
        rows.append(row)
        dims[d["dimension"]] += 1
    # the same words said in another setting: the hearer's kind, an inclusive or exclusive "we", how many a plural covers
    g = collections.defaultdict(list)
    for r in E.recs:
        g[signature(r["slots"])].append(r)
    for rs in g.values():
        if len(rs) < 2:
            continue
        for dim, value in (("hearer_kind", lambda r: (E.frame.get(r["clause"]) or {}).get("hearer_kind")),
                           ("we", E.we), ("plural_size", E.size)):
            by = {}
            for r in sorted(rs, key=lambda r: (-r["sure"], r["ts"][0])):
                v = value(r)
                if v:
                    by.setdefault(v, r)
            vs = sorted(by)
            for i in range(len(vs)):
                for j in range(i + 1, len(vs)):
                    a, b = by[vs[i]], by[vs[j]]
                    rows.append({"edition": E.ed, "a": a["clause"], "b": b["clause"], "carrier": "verse", "dimension": dim,
                                 "from": vs[i], "to": vs[j], "a_at": [], "b_at": [], "with": [], "marks_differ": [], "bearer": "",
                                 "found_by": "same_words_other_setting", "moves": CONTEXT[dim],
                                 "sure": round(min(a["sure"], b["sure"]), 3), "known_words": known(a) and known(b),
                                 "plain_differs": False,
                                 "a_check": check(a["text"]), "b_check": check(b["text"])})
                    dims[dim] += 1
    rows.sort(key=lambda r: (r["dimension"], S.t_of[E.clause_row(r["a"])["first"]], r["b"]))
    for i, r in enumerate(rows, 1):
        r["pair"] = f"pp:{E.ed}:{i:06d}"
    n["pairs"] = len(rows)
    n["pairs with no clause mark differing beside the change"] = sum(1 for r in rows if not r["marks_differ"])
    n["pairs whose unpointed texts are the same"] = sum(1 for r in rows if r["carrier"] == "clause" and not r["plain_differs"])
    n["pairs whose words are all forms the Tanakh has"] = sum(1 for r in rows if r["known_words"])
    for t in (0.8, 0.9):
        n[f"pairs of sureness {t} and more"] = sum(1 for r in rows if r["sure"] >= t)
        n[f"pairs of sureness {t} and more, all words known"] = sum(1 for r in rows if r["sure"] >= t and r["known_words"])
    return rows, {"counts": dict(n), "dimensions": dict(dims.most_common())}


# ---------------------------------------------------------------- changes made by code, with real words only
def bare(parts):
    """a word's parts without the article (it may be written in the preposition, or be no part at all)"""
    return [p for p in parts if p["cls"] != "art"]


def shape(parts):
    """what a donor must share with the word it replaces: the parts' classes and lexemes (a suffix is any pronoun)"""
    return tuple((p["cls"], "*" if p["cls"] == "pron" and p["kind"] == "suffix" else PD.strong(p["lexeme"])) for p in bare(parts))


def stem_at(parts):
    return next((i for i, p in enumerate(bare(parts)) if p["kind"] == "stem"), None)


class Donors:
    """the edition's words by shape and form"""

    def __init__(self, E):
        self.E, S = E, E.S
        self.forms = collections.defaultdict(lambda: collections.defaultdict(list))     # shape -> forms -> [t]
        self.nouns = collections.defaultdict(list)                   # (shape with the noun open, form without gender) -> [t]
        self.alone = collections.defaultdict(list)                   # a word of one part: (class, Strong) -> [t]
        self.pron = collections.defaultdict(list)                    # a pronoun alone: (person, number, gender) -> [t]
        last = {}
        for t, w in S.word.items():
            last[(w["book"], w["chapter"], w["verse"])] = t
        self.last = set(last.values())
        self.noun_count = collections.Counter()                      # (kind, Strong) -> places
        self.noun_places = collections.Counter()                     # Strong -> places with a kind
        for t, parts in S.parts.items():
            ps = bare(parts)
            if not ps or not all(p["known"] for p in ps):            # a donor is a form the Tanakh has
                continue
            sh, sig = shape(parts), tuple(tuple(p[f] for f in FEAT) for p in ps)
            self.forms[sh][sig].append(t)
            k = stem_at(parts)
            if len(ps) == 1:
                self.alone[sh[0]].append(t)
                if ps[0]["cls"] == "pron" and ps[0]["type"] == "personal" and ps[0]["person"]:
                    self.pron[(ps[0]["person"], ps[0]["number"], ps[0]["gender"])].append(t)
            if k is not None and ps[k]["cls"] == "noun" and ps[k]["type"] == "common" and ps[k]["lexeme"]:
                kind = E.kind.get(ps[k]["key"])
                if kind:
                    self.noun_count[(kind, PD.strong(ps[k]["lexeme"]))] += 1
                    self.noun_places[PD.strong(ps[k]["lexeme"])] += 1
                    self.nouns[self.noun_key(parts, k)].append((t, kind, PD.strong(ps[k]["lexeme"]), ps[k]["gender"]))

    @staticmethod
    def noun_key(parts, k):
        ps, sh = bare(parts), shape(parts)
        sig = tuple(tuple("" if (i == k and f == "gender") else p[f] for f in FEAT) for i, p in enumerate(ps))
        return sh[:k] + (("noun", "*"),) + sh[k + 1:], sig

    def best(self, ts, t0):
        """of the words that fit, one that stands as the place's word does: at a verse's end or not, in its book"""
        w0 = self.E.S.word[t0]
        return min(ts, key=lambda t: ((t in self.last) != (t0 in self.last), self.E.S.word[t]["book"] != w0["book"], abs(t - t0)))

    def form(self, t0, k, to, free=(), cj=0):
        """a word of the same shape whose part `k` has the values `to`, all else as in word `t0`. `cj`: the donor
        has the conjunction before it that the word has not (1), or has not the one the word has (-1)"""
        ps0, sh = bare(self.E.S.parts[t0]), shape(self.E.S.parts[t0])
        if cj == 1:
            sh = (("cj", AND),) + sh
        elif cj == -1:
            ps0, sh, k = ps0[1:], sh[1:], k - 1
        fit = []
        for sig, ts in self.forms[sh].items():
            ok = True
            for j, (p0, fs) in enumerate(zip(ps0, sig[cj == 1:])):
                for name, b in zip(FEAT, fs):
                    a = p0[name]
                    if j == k and name in to:
                        ok = b == to[name]
                    elif a != b and not (j == k and name in free) and not (name in SOFT and (a in SOFT[name] or b in SOFT[name])):
                        ok = False
                    if not ok:
                        break
                if not ok:
                    break
            if ok:
                fit += [t for t in ts if t != t0]
        return self.best(fit, t0) if fit else None

    def steady(self, kind, lex):
        """the noun has this kind in most of its places (a kind is read off the Greek word at one place, and is wrong
        at times: a donor must be a noun that is of the kind as a word)"""
        return self.noun_count[(kind, lex)] >= NOUN_MIN and self.noun_count[(kind, lex)] >= NOUN_SHARE * self.noun_places[lex]

    def noun(self, t0, k, kind, keep_gender, turn, strict=False):
        """a noun of that kind in the same form; among the kind's five commonest that fit, the one `turn` picks.
        `strict`: the very gender of the word, masculine or feminine (where something agrees with the noun)"""
        g0 = bare(self.E.S.parts[t0])[k]["gender"]
        own = PD.strong(bare(self.E.S.parts[t0])[k]["lexeme"])
        by = collections.defaultdict(list)
        for t, kd, lex, g in self.nouns.get(self.noun_key(self.E.S.parts[t0], k), ()):
            if strict and not (g == g0 and g in ("m", "f")):
                continue
            if kd == kind and lex != own and self.steady(kind, lex) and (not keep_gender or g == g0 or g in SOFT["gender"] or g0 in SOFT["gender"]):
                by[lex].append(t)
        if not by:
            return None
        top = sorted(by, key=lambda x: (-self.noun_count[(kind, x)], x))[:5]
        return self.best(by[top[turn % len(top)]], t0)


def families():
    fam = tomllib.loads(CHANGES.read_text(encoding="utf-8"))["family"]
    for name, f in fam.items():
        f["name"] = name
        f["slot"] = [f["slot"]] if isinstance(f.get("slot"), str) else f.get("slot", [])
    return fam


def span_of(S, cid, t):
    """the constituent the word heads, or stands in: (role, first, last)"""
    inside = None
    for k in S.cons[cid]:
        if k["head"] not in S.t_of or k["role"] == "v":
            continue
        lo, hi = S.t_of[k["first"]], S.t_of[k["last"]]
        if S.t_of[k["head"]] == t:
            return k["role"], lo, hi
        if lo <= t <= hi:
            inside = (k["role"], lo, hi)
    return inside


def made_text(S, ts, edits):
    """the clause's words after the edits: [(text, the word it comes from)]"""
    seq = [(t, t) for t in ts]                                       # (place in the clause, the word standing there)
    for op, at, frm in edits:
        i = next(i for i, (a, _) in enumerate(seq) if a == at)
        if op == "put":
            seq[i] = (at, frm)
        elif op == "drop":
            del seq[i]
        elif op in ("add_before", "add_after"):
            seq.insert(i + (op == "add_after"), (None, frm))
        elif op == "move_before":
            x = seq.pop(i)
            seq.insert(next(j for j, (a, _) in enumerate(seq) if a == frm), x)
    return seq


def probes_of(E, n):
    """every place with every change of the catalogue it can take, a donor found"""
    S, DN, fam = E.S, Donors(E), families()
    out = []
    for r in E.recs:
        if r["sure"] < MIN_SURE:
            continue
        cid, ts = r["clause"], r["ts"]
        verb = next((s for s in r["slots"] if s["bearer"] == "verb" and s["kind"] == "stem"), None)
        finite = verb is not None and verb["type"] in PD.FINITE
        first_cons = {S.t_of[k["first"]] for k in S.cons[cid] if k["first"] in S.t_of}

        def one_word(t):
            sp = span_of(S, cid, t)
            return sp is not None and sum(1 for x in r["slots"] if sp[1] <= x["key"][0] <= sp[2] and x["kind"] == "stem"
                                          and x["cls"] in CONTENT + ("pron",)) == 1

        def give(f, change, frm, to, at, edits, check_dim=True, note=""):
            sure = min([r["sure"]] + [r["mark_p"][m] for m in f.get("place", {}) if m in r["mark_p"]])
            seq = made_text(S, ts, edits)
            text = " ".join(S.word[w]["text"] for _, w in seq)
            row = {"edition": E.ed, "family": f["name"], "change": change, "clause": cid, "dimension": f["dimension"],
                   "from": frm or "", "to": to or "", "moves": f.get("moves", []), "at": part_id(S, at) if at else None,
                   "edit_op": [e[0] for e in edits], "edit_at": [S.word[e[1]]["id"] for e in edits],
                   "edit_from": [S.word[e[2]]["id"] if e[2] else None for e in edits], "sure": round(sure, 3),
                   "known_words": known(r), "plain_differs": plain(text) != plain(r["text"]), "check": check(r["text"]),
                   "made_check": check(text), "with": [note] if note else [],
                   "_edits": edits, "_text": text, "_lex": PD.strong(next((s["lexeme"] for s in r["slots"] if at and s["key"] == at), ""))}
            if check_dim and all(e[0] == "put" for e in edits):      # the difference function reads the made clause
                words = {}
                for _, t0, d in edits:
                    mine, theirs, lead = bare(S.parts[t0]), bare(S.parts[d]), []
                    if len(theirs) == len(mine) + 1 and theirs[0]["cls"] == "cj":     # the conjunction comes with the form
                        lead, theirs = [dict(theirs[0], key=(t0, 80), head=None)], theirs[1:]
                    elif len(mine) == len(theirs) + 1 and mine[0]["cls"] == "cj":     # or goes with it
                        mine = mine[1:]
                    words[t0] = [{**x, **{k: y[k] for k in ("text", "lexeme") + FEAT}} for x, y in zip(mine, theirs)]
                    arts = [dict(p, key=(t0, 90 + i), head=None) for i, p in enumerate(S.parts[d]) if p["cls"] == "art"]
                    words[t0] = arts + words[t0] if arts and words[t0] and words[t0][0]["cls"] == "noun" else \
                        words[t0][:1] + arts + words[t0][1:] if arts else words[t0]
                    words[t0] = lead + words[t0]
                x = PD.diff(r, S.record(cid, words=words, text=text), E.D)
                form = [d["dimension"] for d in x["dimensions"] if d["slots"] and not (note and d["dimension"] in CJ_DIMS)]
                if note:
                    n[f"{f['name']}: with the conjunction, read as " + "+".join(d["dimension"] for d in x["dimensions"] if d["slots"])
                      + (" and a rest" if x["rest"] else "")] += 1
                if f["dimension"] == "time" and form == ["finiteness"]:     # to or from a participle: the scheme's own name
                    row["dimension"], row["moves"] = "finiteness", sorted(set(row["moves"]) | {16})
                row["made_one"] = form == [row["dimension"]] and not x["rest"]
                n[f"{f['name']}: the made clause differs in " + ("this one thing" if row["made_one"] else "something else")] += 1
            out.append(row)

        for f in fam.values():
            if any(r["marks"].get(m) not in ok for m, ok in f.get("place", {}).items()):
                continue
            if "finite" in f.get("needs", ()) and not finite:
                continue
            how = f["how"]
            if how in ("form", "swap"):
                for s in r["slots"]:
                    t = s["key"][0]
                    if s["bearer"] not in f["slot"] or s["kind"] != f.get("part", "stem") or (f.get("classes") or [s["cls"]]).count(s["cls"]) == 0:
                        continue
                    if "one_word" in f.get("needs", ()) and not one_word(t):
                        continue
                    ps = bare(S.parts[t])
                    k = next((i for i, p in enumerate(ps) if p["key"] == s["key"]), None)
                    if k is None or not all(p["known"] for p in ps):
                        continue
                    if how == "swap":
                        if s["cls"] != "noun" or s["type"] != "common":
                            continue
                        own = E.kind.get(s["key"])
                        n[f"{f['name']}: places"] += 1
                        for kind in f["to_kinds"]:
                            if kind == own:
                                continue
                            d = DN.noun(t, k, kind, f.get("keep_gender", False), t)
                            if d is None:
                                n[f"{f['name']}: no donor"] += 1
                                continue
                            give(f, f"{f['name']}:>{kind}", own, kind, s["key"], [("put", t, d)])
                        continue
                    for v2 in f["values"]:
                        v1 = s[f["feature"]]
                        if v1 == v2 or v1 not in f["values"]:
                            continue
                        change = f"{f['name']}:{v1 or '-'}>{v2 or '-'}"
                        to = {f["feature"]: v2}
                        if f["feature"] == "type":                   # a form without a person meets one that has it
                            said = next((x for x in r["slots"] if x["bearer"] == "subject" and x["kind"] == "stem"), None)
                            if v2 == "imperative" and s["person"] != "2":
                                continue
                            if v1 == "imperative":
                                to["person"] = "2"
                            elif not s["person"] and v2 in PD.FINITE:    # from a participle: the subject said gives the person
                                if said is None:
                                    continue
                                to["person"] = said["person"] if said["cls"] == "pron" and said["person"] else "3"
                        n[f"{f['name']}: places"] += 1
                        d, note = DN.form(t, k, to, tuple(f.get("free", ()))), ""
                        if d is None and f["feature"] == "type":     # `וַיֹּאמֶר`, `וְאָמַר`: the conjunction is part of the form
                            if v2 in CONSECUTIVE and ps[0]["cls"] != "cj" and k == 0 and ts[0] == t:
                                d, note = DN.form(t, k, to, tuple(f.get("free", ())), cj=1), "conjunction:added"
                            elif v1 in CONSECUTIVE and ps[0]["cls"] == "cj" and k == 1:
                                d, note = DN.form(t, k, to, tuple(f.get("free", ())), cj=-1), "conjunction:dropped"
                        edits = [("put", t, d)]
                        for b in f.get("agree", ()):                 # what agrees takes the new value too
                            for a in r["slots"]:
                                if a["bearer"] == b and a["kind"] == "stem" and d is not None and a["known"]:
                                    ka = next(i for i, p in enumerate(bare(S.parts[a["key"][0]])) if p["key"] == a["key"])
                                    da = DN.form(a["key"][0], ka, {f["feature"]: v2}, ("gender",)) if a[f["feature"]] == v1 else None
                                    d = d if da is not None else None
                                    edits.append(("put", a["key"][0], da))
                        if d is None:
                            n[f"{f['name']}: no donor"] += 1
                            continue
                        give(f, change, v1, v2, s["key"], edits, note=note)
            elif how == "drop_negator":
                for t in ts:
                    if shape(S.parts[t]) == (("adv", NEGATOR),) and verb is not None and t + 1 == verb["key"][0]:
                        give(f, "drop_negator", "negative", "affirmative", (t, S.parts[t][0]["key"][1]), [("drop", t, None)])
            elif how == "add_negator":
                if verb is not None and verb["type"] in ("qatal", "yiqtol") and bare(S.parts[verb["key"][0]])[0]["key"] == verb["key"]:
                    d = DN.best(DN.alone[("adv", NEGATOR)], verb["key"][0])
                    give(f, "add_negator", "affirmative", "negative", verb["key"], [("add_before", verb["key"][0], d)])
            elif how in ("drop_subject", "move_subject"):
                subj = [k for k in S.cons[cid] if k["role"] == "s" and k["head"] in S.t_of and k["first"] == k["last"]]
                if len(subj) != 1 or verb is None:
                    continue
                t, tv = S.t_of[subj[0]["head"]], verb["key"][0]
                free_word = lambda x: not any(p["cls"] in ("cj", "rel", "prep") for p in S.parts[x])  # noqa: E731
                if how == "drop_subject" and free_word(t) and t in ts:
                    give(f, f"drop_subject:{r['marks']['subject_form']}", r["marks"]["subject_form"], "zero", (t, bare(S.parts[t])[0]["key"][1]),
                         [("drop", t, None)])
                elif how == "move_subject" and abs(t - tv) == 1 and free_word(t) and free_word(tv) and t in ts and tv in ts \
                        and verb["type"] in ("qatal", "yiqtol", "participle_active"):
                    a, b = (t, tv) if t > tv else (tv, t)            # the later word goes before the earlier
                    give(f, "move_subject:" + ("sv>vs" if t < tv else "vs>sv"), "s-v" if t < tv else "v-s", "v-s" if t < tv else "s-v",
                         (t, bare(S.parts[t])[0]["key"][1]), [("move_before", a, b)])
            elif how == "add_pronoun":
                if verb is None or not verb["person"] or verb["person"] == "x":
                    continue
                want = (verb["person"], verb["number"], verb["gender"])
                ts2 = DN.pron.get(want) or [t for g in ("m", "c") for t in DN.pron.get(want[:2] + (g,), ())
                                            if verb["gender"] in SOFT["gender"] or g == "c"]
                if ts2:
                    give(f, f"add_pronoun:{verb['person']}{verb['number']}", "zero", "pronoun", verb["key"],
                         [("add_after", verb["key"][0], DN.best(ts2, verb["key"][0]))])
    return out


def unit_probes(E, DN, n):
    """probes on a relative unit (labels: relatives.parquet): the carrier is the clause above followed by the relative
    clause. The noun swapped for a noun of another kind, the noun's number changed with what agrees inside the
    relative clause, the relative clause dropped."""
    S, fam = E.S, families()
    path = LABELS / E.ed / "relatives.parquet"
    out = []
    if not path.exists() or "rel_head_swap" not in fam:
        return out
    for u in pq.read_table(path).to_pylist():
        A, R = u["above_clause"], u["rel_clause"]
        if not u["short"] or u["sure"] < MIN_SURE or u["rel_also"] or u["rel_role"] == "other":
            continue
        n["units: short, sure, one reading"] += 1
        ra, rr = E.by_clause.get(A), E.by_clause.get(R)
        if ra is None or rr is None:
            n["units: a clause is not among the short clauses with known lexemes"] += 1
            continue
        ts_a, ts_r = ra["ts"], rr["ts"]
        wa, wr = S.word[ts_a[0]], S.word[ts_r[-1]]
        if ts_r[0] != ts_a[-1] + 1 or (wa["book"], wa["chapter"], wa["verse"]) != (wr["book"], wr["chapter"], wr["verse"]):
            n["units: the relative clause does not follow the clause above in its verse"] += 1
            continue
        wid, part = u["head"].rsplit(".", 1)
        ht = S.t_of[wid]
        ps = bare(S.parts[ht])
        k = next((i for i, p in enumerate(ps) if p["key"] == (ht, int(part) - 1)), None)
        sp = span_of(S, A, ht)
        alone = sp is not None and sum(1 for x in ra["slots"] if sp[1] <= x["key"][0] <= sp[2] and x["kind"] == "stem"
                                       and x["cls"] in CONTENT + ("pron",)) == 1
        if k is None or not alone or not all(p["known"] for p in ps) or ps[k]["cls"] != "noun" or ps[k]["type"] != "common" \
                or PD.strong(ps[k]["lexeme"]).lstrip("0") in NOT_HEADS:
            n["units: the noun is not one known common noun alone in its constituent"] += 1
            continue
        n["units: places"] += 1
        ts, text = ts_a + ts_r, ra["text"] + " " + rr["text"]
        sure, role = min(u["sure"], ra["sure"], rr["sure"]), u["rel_role"]

        def give(f, change, frm, to, edits, note=""):
            made = " ".join(S.word[w]["text"] for _, w in made_text(S, ts, edits))
            out.append({"edition": E.ed, "family": f["name"], "change": change, "clause": R, "clause_above": A, "dimension": f["dimension"],
                        "from": frm or "", "to": to or "", "moves": f.get("moves", []), "at": u["head"],
                        "edit_op": [e[0] for e in edits], "edit_at": [S.word[e[1]]["id"] for e in edits],
                        "edit_from": [S.word[e[2]]["id"] if e[2] else None for e in edits], "sure": round(sure, 3),
                        "known_words": known(ra) and known(rr), "plain_differs": plain(made) != plain(text), "check": check(text),
                        "made_check": check(made), "with": [note] if note else [], "made_one": None,
                        "_edits": edits, "_text": made, "_lex": PD.strong(ps[k]["lexeme"])})

        f = fam["rel_head_swap"]
        own = E.kind.get(ps[k]["key"])
        for kind in f["to_kinds"]:
            if kind != own:
                d = DN.noun(ht, k, kind, True, ht, strict=True)
                if d is None:
                    n["rel_head_swap: no donor"] += 1
                else:
                    give(f, f"rel_head_swap:{role}:>{kind}", own, kind, [("put", ht, d)])
        f = fam["rel_head_number"]
        v1 = ps[k]["number"]
        v2 = {"sg": "pl", "pl": "sg"}.get(v1)
        above_agrees = u["head_role"] in ("s", "p") or S.clauses[A]["pred_kind"] != "v"    # `הוּא הַדָּבָר`: the pronoun agrees
        if v2 and not above_agrees:
            edits, note = [("put", ht, DN.form(ht, k, {"number": v2}))], ""
            inner = None                                             # the part of the relative clause that agrees with the noun
            if role == "s":
                verbs = [x for x in rr["slots"] if x["cls"] in ("verb", "adj") and x["kind"] == "stem"]
                others = [x for x in rr["slots"] if x["cls"] == "pron" and x["number"] in (v1, "")]
                if not verbs and not others:
                    inner = False                                    # `אֲשֶׁר בַּשָּׁמַיִם`: nothing agrees
                elif len(verbs) == 1 and verbs[0]["number"] == v1 and not others and u["rel_role_basis"] != "nominal":
                    inner, note = verbs[0]["key"], "agrees:verb"
            elif u["rel_resumed"]:
                w2, p2 = u["rel_resumed"].rsplit(".", 1)
                same = [x for x in rr["slots"] if x["cls"] == "pron" and x["person"] == "3" and x["number"] == v1]
                if len(same) == 1:                                   # `אֲשֶׁר לִבּוֹ נָכוֹן עִמּוֹ`: which one is the noun's
                    inner, note = (S.t_of[w2], int(p2) - 1), "agrees:pronoun"
            else:
                inner = False                                        # a gap: nothing takes the noun up
            if inner:
                ki = next((i for i, x in enumerate(bare(S.parts[inner[0]])) if x["key"] == inner), None)
                ok = ki is not None and all(x["known"] for x in bare(S.parts[inner[0]]))
                g0, d2 = ps[k]["gender"], None                       # what agrees keeps the noun's gender
                for g in ((g0,) if g0 in ("m", "f") else ()) + ("c", "b", ""):
                    d2 = d2 or (DN.form(inner[0], ki, {"number": v2, "gender": g}) if ok else None)
                edits.append(("put", inner[0], d2 if g0 in ("m", "f") else None))
            if inner is None or any(e[2] is None for e in edits):
                n["rel_head_number: no donor, or what agrees could not be told"] += 1
            else:
                give(f, f"rel_head_number:{role}:{v1}>{v2}", v1, v2, edits, note)
        f = fam["rel_drop"]
        give(f, f"rel_drop:{role}", "relative", "", [("drop", t, None) for t in ts_r])
    return out


def choose(rows):
    """the default spread per change: sure places whose made clause reads as meant and differs without points, one
    per word first"""
    by = collections.defaultdict(list)
    for r in rows:
        r["default"] = False
        if r["sure"] >= DEFAULT_SURE and r.get("made_one") is not False and r["plain_differs"] and r["known_words"]:
            by[r["change"]].append(r)
    for change, rs in by.items():
        rs.sort(key=lambda r: (-r["sure"], r["clause"]))
        seen, taken = collections.Counter(), 0
        for turn in range(PER_CHANGE):
            for r in rs:
                if taken < PER_CHANGE and not r["default"] and seen[r["_lex"]] == turn:
                    r["default"], taken = True, taken + 1
                    seen[r["_lex"]] += 1
            if taken >= PER_CHANGE:
                break


def read_back(E, rows, n):
    """the layer model reads each default probe's verse with the change made: which clause marks it reads differently,
    and whether a replaced word keeps its place in the tree"""
    from macula import clause_scheme as CS, hebrew_nt_clauses as N
    S, fam = E.S, families()
    L = CS.layers()
    pl = N.plain_of(E.ed)
    model, bat, device, _ = L.load_model(pl)
    verses = {v["key"]: v for v in L.nt_verses(E.ed, pl)}
    where = {}                                                       # word -> (verse key, its place among the verse's words)
    for vk, v in verses.items():
        for j, i in enumerate(v["word_i"]):
            where[S.at.get(vk + (i,))] = (vk, j)
    todo, jobs = [], []
    for r in rows:
        if not r["default"] or fam[r["family"]].get("read") is False:
            continue
        c = S.clauses[r["clause"]]
        vk = (c["book"], c["chapter"], c["verse"])
        v = verses[vk]
        seg = S.segs[r["clause"]][0]["seg"]
        ci = next((j for j, cl in enumerate(v["clauses"]) if cl["seg"] == seg), None)
        if ci is None or any(t not in where for e in r["_edits"] for t in e[1:] if t) or any(vk + (i,) not in S.at for i in v["word_i"]):
            n["read-back: verse not found"] += 1
            continue
        all_ts = [S.at[vk + (i,)] for i in v["word_i"]]
        seq = made_text(S, all_ts, r["_edits"])
        words = [verses[where[w][0]]["words"][where[w][1]] for _, w in seq]
        old = {a: j for j, (a, _) in enumerate(seq) if a is not None}
        new_i = [old.get(t) for t in all_ts]                         # an old word's new place
        cls = []
        for j, cl in enumerate(v["clauses"]):
            ws = [new_i[x] for x in cl["words"] if x < len(new_i) and new_i[x] is not None]
            if j == ci:
                ws += [k for k, (a, _) in enumerate(seq) if a is None]
            cls.append({"words": sorted(ws), "seg": cl["seg"]})
        put = next((e for e in r["_edits"] if e[0] == "put"), None)
        piece = None
        if put:
            wi = where[put[1]][1]
            piece = (sum(len(w["pieces"]) for w in v["words"][:wi]), sum(len(w["pieces"]) for w in words[:wi]),
                     len(v["words"][wi]["pieces"]), len(words[wi]["pieces"]))
        jobs.append((r, vk, ci, piece, len(todo)))
        todo.append({"key": vk, "words": words, "clauses": cls})
    keys = sorted({j[1] for j in jobs})
    base = dict(zip(keys, L.predict(model, bat, [verses[k] for k in keys], device)))
    res = L.predict(model, bat, todo, device)
    spec = E.D["dimensions"]
    for r, vk, ci, piece, k in jobs:
        a, b = base[vk]["clauses"][ci], res[k]["clauses"][ci] if ci < len(res[k]["clauses"]) else None
        if a is None or b is None:
            n["read-back: clause not read"] += 1
            continue
        f = fam[r["family"]]
        moved = [m for m in a if m not in NOT_READ and a[m][0] != b[m][0]]
        allowed = set(f.get("may", ())) | set(f.get("must", ())) | set(spec.get(f["dimension"], {}).get("marks", ())) | \
            set(spec.get(f["dimension"], {}).get("also", ()))
        role = None
        if piece and piece[2] == piece[3]:                           # the replaced word's parts keep their relations
            role = all(base[vk]["pieces"][piece[0] + q]["rel"] == res[k]["pieces"][piece[1] + q]["rel"] for q in range(piece[2]))
        r["read_moved"], r["read_role"] = moved, role
        r["read_ok"] = set(moved) <= allowed and set(f.get("must", ())) <= set(moved) and role is not False
        n["read-back: read"] += 1
        n["read-back: as meant"] += r["read_ok"]
        n[f"read-back {r['family']}: " + ("as meant" if r["read_ok"] else "not as meant")] += 1


PROBES = [("probe", STR), ("edition", STR), ("family", STR), ("change", STR), ("clause", STR), ("clause_above", STR), ("dimension", STR), ("from", STR),
          ("to", STR), ("moves", pa.list_(I32)), ("at", STR), ("edit_op", LST), ("edit_at", LST), ("edit_from", LST),
          ("sure", F64), ("default", BOOL), ("known_words", BOOL), ("plain_differs", BOOL), ("made_one", BOOL), ("check", STR), ("made_check", STR), ("with", LST),
          ("read_moved", LST), ("read_role", BOOL), ("read_ok", BOOL)]
CHANGE_COLS = [("change", STR), ("family", STR), ("dimension", STR), ("how", STR), ("moves", pa.list_(I32)), ("probes", I32),
               ("sure_probes", I32), ("default_probes", I32), ("read_as_meant", I32), ("words", I32)]


def build_changes(editions, read):
    for ed in editions:
        E = Edition(ed)
        n = collections.Counter()
        rows = probes_of(E, n)
        rows += unit_probes(E, Donors(E), n)
        for r in rows:
            r.setdefault("clause_above", None)
        choose(rows)
        if read:
            read_back(E, rows, n)
        rows.sort(key=lambda r: (r["change"], r["clause"], r["edit_from"][0] or ""))
        for i, r in enumerate(rows, 1):
            r["probe"] = f"pr:{ed}:{i:06d}"
        write(OUT / ed / "probes.parquet", rows, PROBES)
        fam = families()
        cat = []
        for change in sorted({r["change"] for r in rows}):
            rs = [r for r in rows if r["change"] == change]
            f = fam[rs[0]["family"]]
            cat.append({"change": change, "family": f["name"], "dimension": f["dimension"], "how": f["how"], "moves": f.get("moves", []),
                        "probes": len(rs), "sure_probes": sum(1 for r in rs if r["sure"] >= DEFAULT_SURE),
                        "default_probes": sum(1 for r in rs if r["default"]),
                        "read_as_meant": sum(1 for r in rs if r.get("read_ok")), "words": len({r["_lex"] for r in rs})})
        write(OUT / ed / "changes.parquet", cat, CHANGE_COLS)
        named = {r["clause"] for r in rows} | {r["clause_above"] for r in rows if r["clause_above"]}
        old = pq.read_table(OUT / ed / "pairs.parquet", columns=["a", "b"]).to_pylist() if (OUT / ed / "pairs.parquet").exists() else []
        named |= {c for r in old for c in (r["a"], r["b"])}
        write(OUT / ed / "clauses.parquet", [E.clause_row(c) for c in sorted(named)], CLAUSES)
        n["probes"], n["default probes"], n["changes"] = len(rows), sum(1 for r in rows if r["default"]), len(cat)
        n["probes whose unpointed text is the place's"] = sum(1 for r in rows if not r["plain_differs"])
        path = OUT / ed / "CHECKS.json"
        checks = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        checks["changes"] = {"counts": dict(sorted(n.items())),
                             "per change": {c["change"]: [c["probes"], c["sure_probes"], c["default_probes"], c["read_as_meant"]] for c in cat}}
        path.write_text(json.dumps(checks, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(ed, json.dumps(checks["changes"]["counts"], ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- reading a table back as text
def resolve(E, cid, form="pointed"):
    """a clause's text from the pinned tables: pointed, plain (no points) or parts (parts joined by ·)"""
    S = E.S
    ts = S.words_of(cid)
    if form == "parts":
        return " ".join("·".join(p["text"] for p in S.parts[t]) for t in ts)
    text = " ".join(S.word[t]["text"] for t in ts)
    return plain(text) if form == "plain" else text


def show(ids, form):
    eds = {}
    for x in ids:
        ed = x.split(":")[1]
        E = eds.get(ed) or eds.setdefault(ed, Edition(ed))
        if x.startswith("cl:"):
            print(x, "|", resolve(E, x, form))
        elif x.startswith("pp:"):
            r = next(r for r in pq.read_table(OUT / ed / "pairs.parquet").to_pylist() if r["pair"] == x)
            for k in ("a", "b"):
                ok = check(resolve(E, r[k])) == r[k + "_check"]
                print(f"{x} {k} {r[k]} | {resolve(E, r[k], form)}" + ("" if ok else "   HASH DIFFERS"))
            print(f"    {r['dimension']}: {r['from'] or '∅'} → {r['to'] or '∅'}; at {r['a_at']} / {r['b_at']}; with {r['with']}; "
                  f"moves {r['moves']}; sure {r['sure']}")
        elif x.startswith("pr:"):
            r = next(r for r in pq.read_table(OUT / ed / "probes.parquet").to_pylist() if r["probe"] == x)
            S = E.S
            edits = [(op, S.t_of[at], S.t_of[frm] if frm else None) for op, at, frm in zip(r["edit_op"], r["edit_at"], r["edit_from"])]
            ts = (S.words_of(r["clause_above"]) if r.get("clause_above") else []) + S.words_of(r["clause"])
            made = " ".join(S.word[w]["text"] for _, w in made_text(S, ts, edits))
            place = " ".join(S.word[t]["text"] for t in ts)
            ok = check(place) == r["check"] and check(made) == r["made_check"]
            print(f"{x} {r['clause']} | {plain(place) if form == 'plain' else place}  →  {plain(made) if form == 'plain' else made}" + ("" if ok else "   HASH DIFFERS"))
            print(f"    {r['change']} ({r['dimension']}: {r['from'] or '∅'} → {r['to'] or '∅'}); edits {list(zip(r['edit_op'], r['edit_at'], r['edit_from']))}; "
                  f"moves {r['moves']}; sure {r['sure']}; default {r['default']}; read back {r['read_ok']} {r['read_moved']}")
        else:
            raise SystemExit(f"{x}: not a clause, pair or probe id")


# ---------------------------------------------------------------- commands
def build_pairs(editions):
    from macula.build_text_ids import NUMBER
    pin = {"analysis": "hebrew-nt-analysis v0.8 tables (words, features, tree)", "scheme": "clause scheme 0.3",
           "books": {b: n for b, n in NUMBER.items() if 40 <= n <= 66}, "sha256": {}}
    for ed in editions:
        E = Edition(ed)
        rows, checks = pairs(E)
        write(OUT / ed / "pairs.parquet", rows, PAIRS)
        named = {c for r in rows for c in (r["a"], r["b"])}            # with the clauses the made probes name, as they stand
        if (OUT / ed / "probes.parquet").exists():
            for col in set(("clause", "clause_above")) & set(pq.read_schema(OUT / ed / "probes.parquet").names):
                named |= {c for c in pq.read_table(OUT / ed / "probes.parquet", columns=[col]).column(col).to_pylist() if c}
        write(OUT / ed / "clauses.parquet", [E.clause_row(c) for c in sorted(named)], CLAUSES)
        path = OUT / ed / "CHECKS.json"
        both = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        both["pairs"] = checks
        path.write_text(json.dumps(both, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        from macula import hebrew_nt_clauses as N
        pin["sha256"][ed] = {"words.parquet": hashlib.sha256((N.ANALYSIS / ed / "words.parquet").read_bytes()).hexdigest()}
        print(ed, json.dumps(checks, ensure_ascii=False, indent=1))
    (OUT / "PIN.json").write_text(json.dumps(pin, indent=1) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pairs")
    p.add_argument("--editions", nargs="+", default=list(EDITIONS))
    p = sub.add_parser("changes")
    p.add_argument("--editions", nargs="+", default=list(EDITIONS))
    p.add_argument("--no-read-back", action="store_true")
    p = sub.add_parser("show")
    p.add_argument("ids", nargs="+")
    p.add_argument("--plain", action="store_true")
    p.add_argument("--parts", action="store_true")
    a = ap.parse_args()
    if a.cmd == "pairs":
        build_pairs(a.editions)
    elif a.cmd == "changes":
        build_changes(a.editions, not a.no_read_back)
    else:
        show(a.ids, "plain" if a.plain else "parts" if a.parts else "pointed")


if __name__ == "__main__":
    main()
