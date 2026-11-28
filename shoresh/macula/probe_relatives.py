"""Relative clauses as units for the grammar probes: the noun a relative clause hangs on, and what that noun is
inside the clause (grammar probes, the gap of the first probe sets: a relative clause shows its agreement only
together with its noun, so the carrier is two clauses).

  python -I macula/probe_relatives.py build [--editions heb_scg,heb_mod]   # data/probe-labels/<edition>/relatives.parquet
  python -I macula/probe_relatives.py measure [--plain]                     # the rules against the Tanakh

A unit: a clause that opens with a relative word (`אֲשֶׁר`, `שֶׁ`), the noun its head hangs on in the tree (relation
`NpRelp`), and the clause that noun stands in. Per unit, by rule:

  head          the noun (a word part id), its class, number, gender, definiteness, and what it is in the clause above
  rel_role      what the noun is inside the relative clause:
                  s     its subject: no subject is said and the unsaid subject's antecedent is the noun (where the
                        scheme's table `added` gives none: the verb agrees with the noun), or the clause has no verb
                  o     its object: a pronoun on the verb or on `אֵת` takes the noun up, or nothing does (a gap)
                  pp    after a preposition: `בּוֹ`, `אֵלָיו`
                  place taken up by `שָׁם`
                  adv   a day, a time or a place with nothing taking it up: `הַיּוֹם אֲשֶׁר בָּא`
                  poss  the owner: `אֲשֶׁר שְׁמוֹ`
                  other none of these could be read
  rel_role_basis  nominal | antecedent | agreement | resumed | gap | none
  rel_also      a second reading the text allows (`הָאִישׁ אֲשֶׁר שָׁלַח אֹתוֹ`: who sent him, or whom he sent)
  rel_resumed   the pronoun that takes the noun up (a word part id)
  subject_refers  where the clause's unsaid subject has an antecedent in the scheme's table `added`: is it the noun
  sure          the tree's sureness of the link (head times relation); 1 for the Tanakh's own tree

measure: (1) on the Tanakh's test chapters, the released tree model reading as it reads the New Testament, how often
the link of a relative clause to its noun is MACULA's; (2) on the whole Tanakh, on MACULA's tree, the rule's
"subject or not" against MACULA's own antecedent of the unsaid subject. No hand check.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from macula import clause_scheme as CS
from macula import hebrew_nt_clauses as N
from macula import probe_diff as PD

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "probe-labels"
EDITIONS = ("heb_scg", "heb_mod")
OBJECT_MARKER, THERE = "853", "8033"
PASSIVE = ("niphal", "pual", "hophal")                               # their subject is what an active verb has as object
TIME_PLACE = ("3117", "6256", "4725", "8141", "3915", "2165", "4150", "8160")   # a day, a time, a place: `הַיּוֹם אֲשֶׁר בָּא`
TO = ("3807a", "l")                                                  # `לְ`: `אֲשֶׁר חָצַב לוֹ` is mostly "for himself"
OBJECT_MIN, OBJECT_SHARE = 5, 0.1
NOT_A_NOUN = ("6310",)                                               # `כְּפִי אֲשֶׁר`, `לְפִי אֲשֶׁר`: a conjunction in two words
SOFT_GENDER = ("", "c", "b")
SHORT = 6


class View:
    """one side (the Tanakh, or an edition of the New Testament) in one shape: parts per word with tree and
    features, the clause of a word, the scheme's clauses, constituents and unsaid subjects"""

    def __init__(self, side):
        self.side = side
        folder = PD.SCHEME_OUT / ("tanakh" if side == "tanakh" else f"nt/{side}")
        self.parts, self.wid, self.link_p = {}, {}, {}
        if side == "tanakh":
            S = PD.Tanakh(folder)
            words = pq.read_table(CS.K1 / "hbo" / "words.parquet", columns=["t", "id"]).to_pylist()
            self.wid = {w["t"]: w["id"] for w in words}
            for t, ps in S.parts.items():
                out = []
                for p in sorted(ps, key=lambda p: p["n"]):
                    m = json.loads(p["marks"] or "{}")
                    out.append({"key": (t, p["n"]), "pid": f"{self.wid.get(t)}.{p['n']}", "cls": p["class"] or "", "kind": p["kind"],
                                "lexeme": p["lexeme"] or "", "rel": (p["rel"] or "").split(":")[0],
                                "head": (p["head_t"], p["head_n"]) if p["head_t"] else None,
                                **{f: m.get(f, "") for f in ("type", "stem", "person", "number", "gender", "state")}})
                self.parts[t] = out
            self.at = lambda s, w: S.at.get((s["book"], s["chapter"], s["verse"], w))
        else:
            S = PD.NT(side)
            self.wid = {t: w["id"] for t, w in S.word.items()}
            for t, ps in S.parts.items():
                self.parts[t] = [{**p, "pid": f"{self.wid[t]}.{p['key'][1] + 1}"} for p in ps]
            key = lambda r: (S.at.get((r["book"], r["chapter"], r["verse"], r["i"])), r["part"])  # noqa: E731
            for r in pq.read_table(N.LAYERS / side / "pieces.parquet", columns=["book", "chapter", "verse", "i", "part", "head_p", "rel_p"]).to_pylist():
                self.link_p[key(r)] = (r["head_p"] or 0.0) * (r["rel_p"] or 0.0)
            self.at = lambda s, w: S.at.get((s["book"], s["chapter"], s["verse"], w - 1))
        self.t_of = {i: t for t, i in self.wid.items()}
        self.part = {p["key"]: p for ps in self.parts.values() for p in ps}
        self.clauses, self.cons = S.clauses, S.cons
        self.words, self.clause_of, self.n_segs = {}, {}, {}
        for cid, segs in S.segs.items():
            ts = []
            for s in sorted(segs, key=lambda s: (s["chapter"], s["verse"], s["first_w"])):
                ts += [t for t in (self.at(s, w) for w in range(s["first_w"], s["last_w"] + 1)) if t is not None]
            self.words[cid], self.n_segs[cid] = ts, len(segs)
            for t in ts:
                self.clause_of[t] = cid
        self.added = collections.defaultdict(list)
        for a in pq.read_table(folder / "added.parquet").to_pylist():
            self.added[a["clause"]].append(a)

    def stem(self, t):
        return next((p for p in self.parts.get(t, ()) if p["kind"] == "stem"), None)


_OBJECTS = {}


def takes_object(verb):
    """does this verb take an object, by the Tanakh's clauses: its lexeme in its stem (the lexeme alone where the
    stem is not known) has an object in 1 clause of 10 or more. A verb seen fewer than 5 times: yes."""
    if not _OBJECTS:
        T = PD.Tanakh()
        for cid, c in T.clauses.items():
            t = T.t_of.get(c["pred"])
            st = next((p for p in T.parts.get(t, ()) if p["kind"] == "stem" and p["class"] == "verb"), None)
            if st is None:
                continue
            has = any(k["role"] in ("o", "o2") for k in T.cons[cid])
            lex = CS.strong(st["lexeme"]).lstrip("0")
            for key in ((lex, json.loads(st["marks"] or "{}").get("stem", "")), (lex, None)):
                a = _OBJECTS.setdefault(key, [0, 0])
                a[0] += 1
                a[1] += has
    lex = CS.strong(verb["lexeme"]).lstrip("0")
    n, o = _OBJECTS.get((lex, verb.get("stem"))) or _OBJECTS.get((lex, None)) or (0, 0)
    return n < OBJECT_MIN or o / n >= OBJECT_SHARE


def agrees(x, h, person=True):
    """x (a verb or a pronoun) can stand for the noun h: its number, its gender where both have one, the third person
    (a pronoun as the noun: its own person)"""
    number = h.get("number") or ("sg" if h.get("type") == "proper" else "")    # a name is written without a number
    if not x.get("number") or x["number"] != number:
        return False
    if x.get("gender") != h.get("gender") and x.get("gender") not in SOFT_GENDER and h.get("gender") not in SOFT_GENDER:
        return False
    return not person or not x.get("person") or x["person"] == (h.get("person") or "3")


def resumptions(V, cid, h):
    """the pronouns of the clause's own words that can take the noun up: [(role, part)]"""
    out = []
    for t in V.words[cid]:
        ps = V.parts.get(t, ())
        st = V.stem(t)
        for p in ps:
            if p["cls"] == "adv" and CS.strong(p["lexeme"]).lstrip("0") == THERE:
                out.append(("place", p))
            if p["cls"] != "pron" or p["key"] == h["key"] or not agrees(p, h) or not p.get("known", True):
                continue                                             # a pronoun cut off a word the Tanakh does not have is a guess
            if p["kind"] != "suffix":
                out.append(("s", p))
            elif st is not None and (st["cls"] == "om" or CS.strong(st["lexeme"]).lstrip("0").rstrip("abc") == OBJECT_MARKER or st["cls"] == "verb"):
                out.append(("o", p))
            elif st is not None and st["cls"] == "prep":
                out.append(("to" if CS.strong(st["lexeme"]).lstrip("0") in TO else "pp", p))
            elif st is not None and st["cls"] in ("noun", "adj"):
                out.append(("poss", p))
    return out


def role_of(V, cid, h, by_antecedent=True):
    """(rel_role, basis, also, resumed part) of the noun h inside the relative clause cid. Subject or not: where the
    clause's unsaid subject has an antecedent in the table `added`, that decides (the verb of `הַדָּבָר אֲשֶׁר דִּבֶּר`
    agrees with the noun and is not about it); else the verb's agreement with the noun."""
    c = V.clauses[cid]
    res = resumptions(V, cid, h)
    first = lambda *roles: next(((r, p) for want in roles for r, p in res if r == want), None)  # noqa: E731
    subj = None
    for k in V.cons[cid]:
        if k["role"] == "s" and k["head"] in V.t_of:
            st = V.stem(V.t_of[k["head"]])
            if st is not None and st["cls"] != "rel":
                subj = st
    said_object = any(k["role"] in ("o", "o2") for k in V.cons[cid])
    verb = V.stem(V.t_of[c["pred"]]) if c["pred_kind"] == "v" and c["pred"] in V.t_of else None
    if verb is not None and verb["cls"] != "verb":
        verb = None
    if verb is None:                                                 # the clause's verb where the scheme names none
        verb = next((p for t in V.words[cid] for p in V.parts.get(t, ()) if p["cls"] == "verb" and p["kind"] == "stem"
                     and p["type"] and not p["type"].startswith("infinitive")), None)
    own_pronoun = subj is not None and subj["cls"] == "pron" and agrees(subj, h)    # `אֲשֶׁר הוּא ...`: the noun again
    if verb is None:
        if own_pronoun:
            return "s", "nominal", "", subj
        r = first("poss", "pp", "to", "place", "o")
        if subj is None:                                             # `אֲשֶׁר בְּעֵינְךָ` is about the noun; `אֲשֶׁר אֵין בָּם` takes it up
            return (r[0].replace("to", "pp"), "resumed", "s", r[1]) if r and r[0] != "o" else ("s", "nominal", "", None)
        return (r[0], "resumed", "", r[1]) if r else ("other", "none", "", None)
    if verb["type"].startswith("infinitive"):
        return "other", "none", "", None
    passive = verb.get("stem") in PASSIVE or verb["type"] == "participle_passive"
    gap = not said_object and not passive and takes_object(verb)      # the verb can have the noun as its unsaid object
    when = CS.strong(h["lexeme"]).lstrip("0") in TIME_PLACE
    if subj is None or own_pronoun:
        agree = own_pronoun or agrees(verb, h, person=verb["type"] in PD.FINITE)
        sub = next((a for a in V.added[cid] if a["role"] == "s" and a["antecedent"]), None)
        if by_antecedent and sub is not None and not own_pronoun:
            is_s, basis = sub["antecedent"] == h["pid"], "antecedent"
            if not is_s and agree and not gap and not when and not first("o", "pp", "to", "place"):
                is_s, basis = True, "agreement"                      # nothing else the noun could be in the clause
        else:
            is_s, basis = agree and not when, "agreement"
        if is_s:
            r = first("o", "pp", "to", "place") if basis == "agreement" else None
            return "s", basis, r[0].replace("to", "pp") if r else "", subj if own_pronoun else None
    r = first("o", "pp", "place")
    if r:                                                            # `הַכֹּל אֲשֶׁר כָּתוּב עָלָיו`: all that is written of him, too
        open_s = subj is None and not when and agrees(verb, h, person=verb["type"] in PD.FINITE)
        return r[0], "resumed", "s" if open_s else "", r[1]
    if when:
        return "adv", "gap", "", None
    r = first("to")
    if r and not gap:
        return "pp", "resumed", "", r[1]
    if gap:
        return "o", "gap", "pp" if r else "", None
    r = first("poss")
    return (r[0], "resumed", "", r[1]) if r else ("other", "none", "", None)


def units(V, n, by_antecedent=True):
    """the relative units of a side: a clause opening with a relative word whose head hangs on a noun of another clause"""
    rows = []
    for cid in sorted(V.words):
        ts = V.words[cid]
        own = [p for t in ts for p in V.parts.get(t, ())]
        rel_word = next((p for p in own[:3] if p["cls"] == "rel"), None)
        if rel_word is None:
            continue
        n["clauses that open with a relative word"] += 1
        tops = [p for p in own if p["rel"] == "NpRelp" and p["head"] in V.part and V.clause_of.get(p["head"][0]) != cid]
        if not tops:
            n["  no noun in the tree (the clause is not hung on a noun, or on a word of its own)"] += 1
            continue
        top = tops[0]
        h = V.part[top["head"]]
        above = V.clause_of.get(h["key"][0])
        if above is None or h["cls"] not in ("noun", "pron", "adj", "num") or CS.strong(h["lexeme"]).lstrip("0") in NOT_A_NOUN:
            n["  the head is not a noun or pronoun, or stands in no clause"] += 1
            continue
        role, basis, also, resumed = role_of(V, cid, h, by_antecedent)
        role = "pp" if role == "to" else role
        ht = h["key"][0]
        head_role = next((k["role"] for k in V.cons[above] if k["head"] in V.t_of and k["first"] in V.t_of and k["last"] in V.t_of
                          and V.t_of[k["first"]] <= ht <= V.t_of[k["last"]]), "")
        sub = next((a for a in V.added[cid] if a["role"] == "s" and a["antecedent"]), None)
        rows.append({"rel_clause": cid, "above_clause": above, "head": h["pid"], "head_class": h["cls"], "head_number": h.get("number") or "",
                     "head_gender": h.get("gender") or "", "head_definite": h.get("definite") or "", "head_role": head_role,
                     "rel_word": rel_word["lexeme"], "rel_role": role, "rel_role_basis": basis, "rel_also": also,
                     "rel_resumed": resumed["pid"] if resumed else "",
                     "subject_refers": None if sub is None else sub["antecedent"] == h["pid"],
                     "sure": round(V.link_p.get(top["key"], 1.0), 4),
                     "words_rel": len(ts), "words_above": len(V.words[above]),
                     "short": len(ts) <= SHORT and len(V.words[above]) <= SHORT and V.n_segs[cid] == 1 and V.n_segs[above] == 1})
        n["units"] += 1
        n[f"  rel_role {role} ({basis})"] += 1
    return rows


COLS = [("unit", pa.string()), ("edition", pa.string()), ("rel_clause", pa.string()), ("above_clause", pa.string()), ("head", pa.string()),
        ("head_class", pa.string()), ("head_number", pa.string()), ("head_gender", pa.string()), ("head_definite", pa.string()),
        ("head_role", pa.string()), ("rel_word", pa.string()), ("rel_role", pa.string()), ("rel_role_basis", pa.string()),
        ("rel_also", pa.string()), ("rel_resumed", pa.string()), ("subject_refers", pa.bool_()), ("sure", pa.float64()),
        ("words_rel", pa.int32()), ("words_above", pa.int32()), ("short", pa.bool_())]


def build(editions):
    for ed in editions:
        V = View(ed)
        n = collections.Counter()
        rows = units(V, n)
        for i, r in enumerate(rows, 1):
            r["unit"], r["edition"] = f"ru:{ed}:{i:05d}", ed
        (OUT / ed).mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.table({c: pa.array([r[c] for r in rows], type=t) for c, t in COLS}), OUT / ed / "relatives.parquet")
        n["units, both clauses short"] = sum(1 for r in rows if r["short"])
        n["units, short and sure 0.9 and more"] = sum(1 for r in rows if r["short"] and r["sure"] >= 0.9)
        n["subject by the rule, the unsaid subject's antecedent is the noun"] = sum(1 for r in rows if r["rel_role"] == "s" and r["subject_refers"])
        n["subject by the rule, the antecedent is another word"] = sum(1 for r in rows if r["rel_role"] == "s" and r["subject_refers"] is False)
        print(ed, json.dumps(dict(n), ensure_ascii=False, indent=1))


def measure(plain):
    """(2) first, on MACULA's tree: the rule's subject-or-not against MACULA's antecedent of the unsaid subject;
    then (1) the link on the test chapters as the New Testament is read"""
    V = View("tanakh")
    n = collections.Counter()
    rows = units(V, n, by_antecedent=False)                          # the verb's agreement alone, to see what it is worth
    print("the Tanakh on MACULA's tree, subject by agreement alone:", json.dumps(dict(n), ensure_ascii=False, indent=1))
    c = collections.Counter()
    for r in rows:
        if r["subject_refers"] is not None:
            c[(r["rel_role"] == "s", r["subject_refers"])] += 1
    both, rule_only, ref_only, neither = c[(True, True)], c[(True, False)], c[(False, True)], c[(False, False)]
    print(f"units whose unsaid subject has MACULA's antecedent: {sum(c.values()):,}")
    print(f"  the rule says subject: {both + rule_only:,}, of these the antecedent is the noun {both:,} ({both / max(1, both + rule_only):.1%})")
    print(f"  the antecedent is the noun: {both + ref_only:,}, of these the rule says subject {both:,} ({both / max(1, both + ref_only):.1%})")
    print(f"  neither: {neither:,}")

    L = CS.layers()
    wd, sent, clauses, cons = CS.tanakh()
    meta = {p["key"]: p for parts in sent.values() for p in parts}
    by_ref = collections.defaultdict(list)
    for w in wd.values():
        by_ref[f"{w['book']} {w['chapter']}:{w['verse']}"].append(w)
    data = L.load("test", plain)
    trees = CS.released_trees(data, plain)
    T = (0.0, 0.5, 0.8, 0.9, 0.95)
    gold_n, found, said = 0, collections.Counter(), collections.Counter()
    for v, tr in zip(data, trees):
        ws = sorted(by_ref[v["ref"]], key=lambda w: w["w"])
        order = []
        for w in ws:
            order.extend(sorted(k for k in ((w["t"], i) for i in range(1, 12)) if k in meta))
        if len(order) != len(tr):
            continue
        gold = {k: meta[k]["head"] for k in order if meta[k]["rel"].startswith("NpRelp") and meta[k]["head"] in meta}
        gold_n += len(gold)
        for i, k in enumerate(order):
            head, rel, hp, rp = tr[i]
            if not (rel or "").startswith("NpRelp") or not 0 < head <= len(order):
                continue
            for t in T:
                if hp * rp >= t:
                    said[t] += 1
                    found[t] += gold.get(k) == order[head - 1]
    print(f"test chapters, the released tree model ({'without' if plain else 'with'} points): MACULA hangs {gold_n:,} clauses on a noun")
    for t in T:
        print(f"  sureness {t:.2f} and more: the model hangs {said[t]:,}, as MACULA {found[t]:,} "
              f"(right {found[t] / max(1, said[t]):.1%}, found {found[t] / max(1, gold_n):.1%})")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=("build", "measure"))
    ap.add_argument("--editions", default=",".join(EDITIONS))
    ap.add_argument("--plain", action="store_true")
    a = ap.parse_args()
    if a.command == "build":
        build(a.editions.split(","))
    else:
        measure(a.plain)


if __name__ == "__main__":
    main()
