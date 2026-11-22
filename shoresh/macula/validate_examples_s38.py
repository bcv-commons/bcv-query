"""Stage 38 checks (SPEC 1.6, section 10 "new in 1.6", section 13 against g1, the sample of mends). Imports no builder.

run(R, build): every condition "new in 1.6", recomputed here from the build's own tables and g1:
- added (1.6): the subject row of 4.11, D18 step 2 (kind, form, person/number/gender on ending rows) and step W (the
  set rule), the moves against g1 by step, role, kind and case;
- source errors (1.6): SE5 = the added rows of who_reason disagree; SE1 to SE4 equal g1's;
- groups (1.6): D25 step 2b from pairs.parquet and the members of step 2 (g1's anchor members), D27 kept_out, the
  moves against g1, the same for the cgm rows (D25m);
- reading sheets (1.6): every added row of glossed-h1/ shows who_reason and form;
- unchanged (1.6): section 13, h1 against g1;
- sample of mends (1.6): glossed-h1/mends-sample.md.
"""
import collections as C
import csv
import json
import os

import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LANGS = ("hbo", "arc", "grc")
CAUS = {"hiphil", "haphel", "aphel", "shaphel"}
GLOSSED = os.path.join(ROOT, "internal-docs/source-examples-work/glossed-h1")
SAMPLE = os.path.join(GLOSSED, "mends-sample.md")
WRITE = False          # set by validate_examples.py --write-md
FLOOR = 0.05           # SPEC D25: a member under 0.05 of the candidates' places at the anchor joined under the floor
GATE = 3               # SPEC D25 (L9): ubs_depth under 3 is loose
# files that 1.6 changes (section 13); every other file of a folder is byte-equal to g1's
CHANGED = {"lang": {"added.parquet", "source_errors.tsv", "categories.toml", "sources.json", "COLUMNS.md",
                    "READ-FIRST.md", "VALIDATION.md"},
           "lexicon": {"groups.parquet", "lexemes.tsv", "SAMPLE.md", "categories.toml", "sources.json", "COLUMNS.md",
                       "READ-FIRST.md", "VALIDATION.md"},
           "other": {"sources.json", "VALIDATION.md"}}
FOLLOW = {"map.tsv"}   # follow-on of a changed code's count (as in 1.5): checked row by row below


def _sha(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _rows(path, cols=None):
    return pq.read_table(path, columns=cols).to_pylist()


def _tsv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))


def pick(items, n=20, first=5):
    """The fixed rule of the sample: the first 5 in text order, then every k-th, 20 in all."""
    if len(items) <= n:
        return list(items)
    rest = items[first:]
    k = max(1, len(rest) // (n - first))
    return list(items[:first]) + rest[::k][:n - first]


def digits(s):
    return "".join(ch for ch in (s or "") if ch.isdigit()).lstrip("0")


class Ctx:
    """Words per language: a row's place is looked up in its own language's table (SPEC 10, 1.6), and a Tanakh row
    whose word stands in the other Tanakh table (counted) in that one."""

    def __init__(self, build):
        self.words, self.text = {}, {}
        for lg in LANGS:
            W = pq.read_table(os.path.join(build, lg, "words.parquet"), columns=["t", "book", "chapter", "verse", "text"]).to_pydict()
            for t, b, c, v, x in zip(W["t"], W["book"], W["chapter"], W["verse"], W["text"]):
                self.words[(lg, t)] = (b, c, v)
                self.text[(lg, t)] = x
        self.other_table = C.Counter()

    def own(self, t, lg):
        if (lg, t) in self.words:
            return lg
        if lg != "grc":
            o = "arc" if lg == "hbo" else "hbo"
            if (o, t) in self.words:
                self.other_table[lg] += 1
                return o
        return lg

    def place(self, t, lg):
        g = self.own(t, lg)
        b, c, v = self.words.get((g, t), ("?", 0, 0))
        return f"{b} {c}:{v} {self.text.get((g, t), '?')}"

    def piece_word(self, tn, lg):
        t = int(tn.split(".")[0])
        g = self.own(t, lg)
        return self.text.get((g, t), "?")


# ---- added (D18 of 1.6) ---------------------------------------------------------------------------------------------

def pieces_of(build, langs):
    stem, who = {}, {}
    for lg in langs:
        for p in _rows(os.path.join(build, lg, "pieces.parquet"), ["t", "n", "kind", "who", "marks"]):
            who[(p["t"], p["n"])] = p["who"] or ""
            if p["kind"] == "stem":
                stem[p["t"]] = (p["n"], json.loads(p["marks"]) if p["marks"] else {})
    return stem, who


def recompute_added(build, lg, rows, g1rows, terms):
    """D18 steps 2 and W of 1.6 over the rows (step 1 holds: the keys equal g1's). -> {key: expected row fields},
    {key: info for the moves}."""
    stem, who = pieces_of(build, ("grc",) if lg == "grc" else ("hbo", "arc"))
    N = _rows(os.path.join(build, lg, "constituents.parquet"), ["clause", "frame_role"])
    aa_part = {k["clause"] for k in N if "AA" in (k["frame_role"] or "").split()}
    aa_row = {(r["clause"], r["verb"]) for r in rows if r["role"] == "AA"}
    term = {c: terms[(lg, "added_kind", c)] for c in ("in_verb", "elsewhere", "unsaid", "possessor")}
    want, info = {}, {}
    for r in rows:
        k = (r["clause"], r["verb"], r["role"])
        g = g1rows[k]
        n, m = stem.get(r["verb"], (None, {}))
        caus = m.get("stem") in CAUS
        has_aa = (r["clause"], r["verb"]) in aa_row or r["clause"] in aa_part
        subj = r["role"] == (("AA" if has_aa else "A0") if caus else "A0")
        subj15 = r["role"] == ("AA" if caus else "A0")
        if r["role"] == "poss":
            kind, form = "possessor", "none"
        elif subj and m.get("person"):
            kind, form = "in_verb", "ending"
        else:
            kind, form = ("unsaid" if r["where"] == "unexpressed" else "elsewhere"), "none"
        if form == "ending":
            p_, n_, g_ = m.get("person") or "", m.get("number") or "", m.get("gender") or ""
        else:
            p_, n_, g_ = g["person"], g["number"], g["gender"]      # the dataset's values, as g1 wrote them
        V = set(who.get((r["verb"], n), "").split()) if subj and n is not None else set()
        Nn = set()
        if r["antecedent"]:
            at, an = map(int, r["antecedent"].split("."))
            Nn = set(who.get((at, an), "").split())
        case = ""
        if r["role"] == "poss":
            w, why = "", "guess"
        elif V and Nn:
            if V <= Nn or Nn <= V:
                small, large = (V, Nn) if V <= Nn else (Nn, V)
                sg = m.get("number") == "sg"
                w, why = " ".join(sorted(small if sg else large)), "verb_and_antecedent"
                case = ("equal" if V == Nn else ("N inside V" if Nn < V else "V inside N") + (", singular verb" if sg else
                        ", plural or numberless verb"))
            elif V & Nn:
                w, why, case = " ".join(sorted(V & Nn)), "verb_and_antecedent", "partial"
            else:
                w, why, case = "", "disagree", "none shared"
        elif V:
            w, why = " ".join(sorted(V)), "verb"
        elif Nn:
            w, why = " ".join(sorted(Nn)), "antecedent"
        else:
            w, why = "", ("no_antecedent" if not r["antecedent"] else "antecedent_no_participant")
        want[k] = {"kind": term[kind], "form": form, "person": p_, "number": n_, "gender": g_, "who": w, "who_reason": why}
        info[k] = {"subj": subj, "subj15": subj15, "caus": caus, "has_aa": has_aa, "stem_person": bool(m.get("person")),
                   "type": m.get("type") or m.get("mood") or "", "case": case, "V": V, "N": Nn, "marks": m}
    return want, info


def added16(R, build, g1, ctx, terms, md):
    R.section("added (D18 of 1.6) against g1")
    mv_all = {}
    for lg in LANGS:
        rows = _rows(os.path.join(build, lg, "added.parquet"))
        grows = {(r["clause"], r["verb"], r["role"]): r for r in _rows(os.path.join(g1, lg, "added.parquet"))}
        keys = [(r["clause"], r["verb"], r["role"]) for r in rows]
        R.check(f"{lg} added (1.6) unchanged: the same keys as g1 (no row dropped or added), and clause, verb, role, "
                "where, antecedent equal g1's", len(set(keys)) == len(keys) == len(grows) and set(keys) == set(grows)
                and all(grows[k]["where"] == r["where"] and grows[k]["antecedent"] == r["antecedent"]
                        for k, r in zip(keys, rows)), f"{len(rows):,} rows; g1 {len(grows):,}")
        want, info = recompute_added(build, lg, rows, grows, terms)
        bad = [k for k, r in zip(keys, rows) if any(r[f] != want[k][f] for f in want[k])]
        R.check(f"{lg} added (1.6): every row's kind, form, person, number, gender, who, who_reason recomputed by D18 "
                "steps 2 and W of 1.6 (the subject row of 4.11)", not bad,
                f"{len(rows):,} rows; differ {len(bad)}" + (f", e.g. {bad[:3]}" if bad else ""))
        inv = terms[(lg, "added_kind", "in_verb")]
        r_ = {k: r for k, r in zip(keys, rows)}
        x1 = [k for k in keys if (r_[k]["kind"] == inv) != (r_[k]["form"] == "ending")]
        R.check(f"{lg} added (1.6): kind in_verb exactly on the rows of form ending", not x1, len(x1))
        x2 = [k for k in keys if (r_[k]["form"] == "ending") != (info[k]["subj"] and info[k]["stem_person"])]
        R.check(f"{lg} added (1.6): form ending exactly on the subject rows whose stem piece has a person", not x2, len(x2))
        x3 = [k for k in keys if k[2] == "A0" and info[k]["caus"] and not info[k]["subj"] and not info[k]["has_aa"]]
        R.check(f"{lg} added (1.6): no A0 row under a causative stem is a non-subject row unless an AA row or part "
                "stands in its frame", not x3, len(x3))
        x4 = [k for k in keys if r_[k]["form"] == "ending" and any(
            r_[k][f] != (info[k]["marks"].get(f) or "") for f in ("person", "number", "gender"))]
        R.check(f"{lg} added (1.6): on every ending row person, number, gender equal the stem piece's marks", not x4, len(x4))
        # R2: the dataset's values (g1's on non-ending rows; the dataset wrote them there in 1.5 too) against the ending
        r2 = C.Counter()
        for k in keys:
            if r_[k]["form"] != "ending":
                continue
            r2["ending rows"] += 1
            d = False
            for f in ("person", "number", "gender"):
                ds, mine = grows[k][f], r_[k][f]     # g1 wrote the dataset's value on every row
                if ds != mine:
                    r2[f"{f} {'empty in the dataset' if not ds else 'differs' if mine else 'filled in the dataset, none on the stem piece'}"] += 1
                    d = True
            r2["rows with a field the dataset gives otherwise or not at all"] += d
        R.info(f"{lg} added (1.6) R2: ending rows against the dataset's person, number, gender (by field)", dict(sorted(r2.items())))
        # moves against g1, by step, role, kind, case
        mv = C.Counter()
        lists = C.defaultdict(list)
        for k in sorted(keys, key=lambda k: (k[1], k[2], k[0])):
            a, b, i = grows[k], r_[k], info[k]
            line = f"{ctx.place(k[1], lg)} {k[2]}"
            if i["subj"] and not i["subj15"]:
                mv[f"R1 new subject rows, role {k[2]}, stem person {'yes' if i['stem_person'] else 'no (' + i['type'] + ')'}"] += 1
                lists["R1"].append(f"{line}: g1 {a['kind']} / {a['form']}, who {a['who'] or '-'} ({a['who_reason']}); "
                                   f"h1 {b['kind']} / {b['form']}, who {b['who'] or '-'} ({b['who_reason']})")
            if (a["kind"], a["form"]) != (b["kind"], b["form"]):
                step = "R1" if i["subj"] and not i["subj15"] else "R5"
                mv[f"step 2 kind/form {a['kind']}/{a['form']} -> {b['kind']}/{b['form']}, role {k[2]} ({step})"] += 1
                if step == "R5":
                    lists["R5"].append(f"{line}: g1 {a['kind']} / {a['form']} (where {a['where']}); h1 {b['kind']} / {b['form']}")
            if b["form"] == "ending" and any(a[f] != b[f] for f in ("person", "number", "gender")):
                mv["step 2 R2 person/number/gender moved"] += 1
                lists["R2"].append(f"{line}: g1 {a['person'] or '-'}/{a['number'] or '-'}/{a['gender'] or '-'}; "
                                   f"h1 {b['person'] or '-'}/{b['number'] or '-'}/{b['gender'] or '-'}")
            if (a["who"], a["who_reason"]) != (b["who"], b["who_reason"]):
                cs = i["case"] or b["who_reason"]
                why = "R1 new subject row" if i["subj"] and not i["subj15"] else cs
                mv[f"step W who moved: {why}"] += 1
                if not (i["subj"] and not i["subj15"]):
                    lists["R3"].append(f"{line}: g1 who {a['who'] or '-'} ({a['who_reason']}); h1 who {b['who'] or '-'} "
                                       f"({b['who_reason']}); case {cs}")
            if i["subj"] and i["V"] and i["N"]:
                mv[f"step W subject rows with both readings: {i['case']}"] += 1
        mv["who_reason disagree (h1)"] = sum(1 for r in rows if r["who_reason"] == "disagree")
        mv["who_reason disagree (g1)"] = sum(1 for r in grows.values() if r["who_reason"] == "disagree")
        mv["rows of form ending (h1)"] = sum(1 for r in rows if r["form"] == "ending")
        R.info(f"{lg} added (1.6): moves against g1, by step, role, kind and case", dict(sorted(mv.items())))
        mv_all[lg] = (mv, lists)
    return mv_all


def se16(R, build, g1, ctx):
    R.section("source errors (SE5 of 1.6)")
    out = {}
    for lg in LANGS:
        A = _rows(os.path.join(build, lg, "added.parquet"))
        stem, who = pieces_of(build, ("grc",) if lg == "grc" else ("hbo", "arc"))
        want = []
        for a in A:
            if a["who_reason"] != "disagree":
                continue
            n = stem[a["verb"]][0]
            at, an = map(int, a["antecedent"].split("."))
            want.append((a["verb"], n, a["clause"], f"{who[(a['verb'], n)]} | {who[(at, an)]}"))
        want.sort()
        want = [("SE5", "acai", f"{t}.{n}", v, str(len(want))) for t, n, _k, v in want]
        have = [tuple(r.values()) for r in _tsv(os.path.join(build, lg, "source_errors.tsv"))]
        old = [tuple(r.values()) for r in _tsv(os.path.join(g1, lg, "source_errors.tsv"))]
        se5 = [r for r in have if r[0] == "SE5"]
        R.check(f"{lg} source_errors (1.6): the SE5 rows are exactly the added rows of who_reason disagree (place, value, "
                "count)", se5 == want, f"{len(se5)} rows, recomputed {len(want)}")
        R.check(f"{lg} source_errors unchanged: the rows of SE1 to SE4 equal g1's, in g1's order",
                [r for r in have if r[0] != "SE5"] == old, f"{len(old)} rows in g1")
        R.info(f"{lg} source_errors by rule", dict(sorted(C.Counter(r[0] for r in have).items())))
        out[lg] = se5
    return out


# ---- groups (D25 step 2b, D27 kept_out) ------------------------------------------------------------------------------

def groups16(R, build, g1):
    R.section("groups (D25 step 2b, D27 kept_out of 1.6) against g1")
    L = os.path.join(build, "lexicon")
    lex = {r["lexeme"]: r for r in _tsv(os.path.join(L, "lexemes.tsv"))}
    lex1 = {r["lexeme"]: r for r in _tsv(os.path.join(g1, "lexicon", "lexemes.tsv"))}
    pairs = C.defaultdict(list)
    for p in _rows(os.path.join(L, "pairs.parquet")):
        pairs[frozenset((p["a"], p["b"]))].append(p)
    G1 = C.defaultdict(list)
    for r in _rows(os.path.join(g1, "lexicon", "groups.parquet")):
        G1[(r["basis"], r["group"])].append(r)
    G2 = C.defaultdict(list)
    for r in _rows(os.path.join(L, "groups.parquet")):
        G2[(r["basis"], r["group"])].append(r)
    # the floor: the candidates' places at an anchor and class (lexemes.tsv places * anchor_share)
    at = C.Counter()
    for r in lex.values():
        if r["anchor"] and r["places"]:
            at[(r["anchor"], r["class"])] += round(int(r["places"]) * float(r["anchor_share"]))

    def at_anchor(x):
        r = lex[x]
        return round(int(r["places"]) * float(r["anchor_share"])) if r["anchor"] and r["places"] else 0

    def step2b(G, basis):
        """-> out {lexeme: (group, head, why)}, confirmed count by route, dissolved {group: head}."""
        nt_ok = ("linked",) if basis == "derived" else ("linked", "model")
        out, dis, c = {}, {}, C.Counter()
        for (b, key), ms in sorted(G.items()):
            if b != basis or not ms[0]["anchor"]:
                continue
            anc = [m for m in ms if m["joined_by"] == "anchor"]
            head = [m for m in ms if m["head"]][0]["lexeme"]
            aset = {m["lexeme"] for m in anc}
            tot = at[(ms[0]["anchor"], lex[head]["class"])] or 1
            leave = 0
            for m in anc:
                x = m["lexeme"]
                if m["head"] or lex[x]["lang"] != "hbo":
                    continue
                under = basis == "derived" and at_anchor(x) / tot < FLOOR
                loose = m["ubs_depth"] is not None and m["ubs_depth"] < GATE
                if not (under or loose):
                    continue
                routes = set()
                for o in aset - {x}:
                    if lex[o]["lang"] == "hbo" and digits(lex[o]["strong"]) == digits(lex[x]["strong"]):
                        routes.add("same_strong")
                    for p in pairs.get(frozenset((x, o)), []):
                        if p["evidence"] == "sept_number" and [v for v in json.loads(p["via"]) if v != ms[0]["anchor"]]:
                            routes.add("sept_number")
                        if p["evidence"] == "nt_editions" and p["basis"] in nt_ok:
                            routes.add("nt_editions")
                why = "under the floor" if under else "ubs_depth under 3"
                c[f"weak joins {why}, {'confirmed' if routes else 'leave'}"] += 1
                if not routes:
                    out[x] = (key, head, why)
                    leave += 1
            if len(anc) - leave < 2:     # left with its head alone; dissolves unless D26 joins a word to the head
                dis[key] = head
        return out, dis, c

    # strict: recompute from g1's step-2 members (the anchor members; the head chosen before step 2b)
    out, dis0, c = step2b(G1, "derived")
    keys2 = {k for (b, k) in G2 if b == "derived"}
    kept_by_d26 = [k for k in dis0 if k in keys2]
    bad26 = [k for k in kept_by_d26 if not all(r["joined_by"] != "anchor" or r["head"] for r in G2[("derived", k)])
             or [r["lexeme"] for r in G2[("derived", k)] if r["head"]] != [dis0[k]]]
    R.check("tan groups (1.6): a group left with its head alone stands in h1 only with the same head and D26 members "
            "(an Aramaic word joined to the head)", not bad26, f"{len(kept_by_d26)} kept by D26; bad {bad26[:5]}")
    dis = {k: h for k, h in dis0.items() if k not in keys2}
    R.info("tan step 2b recomputed from g1's anchor members and pairs.parquet (strict)", dict(sorted(c.items()), **{
        "members out": len(out), "groups that lose a member": len({v[0] for v in out.values()}),
        "groups dissolved": len(dis)}))
    m2 = {}
    for (b, key), ms in G2.items():
        if b == "derived":
            for m in ms:
                m2[m["lexeme"]] = (key, m["joined_by"])
    wrong_in = [x for x in out if x in m2 and m2[x][1] == "anchor"]
    R.check("tan groups (1.6): every member step 2b takes out is in no group by the anchor in h1", not wrong_in, wrong_in[:5])
    rejoin = sorted(x for x in out if x in m2)
    R.info("tan groups (1.6): Hebrew words step 2b took out that are members again by D26 (the pick of an Aramaic word)",
           f"{len(rejoin)}: " + "; ".join(f"{lex[x]['lemma']} {m2[x][0]} {m2[x][1]}" for x in rejoin))
    # every g1 anchor member that is not out stays, in a group with the same anchor and head
    stay_bad = []
    for (b, key), ms in G1.items():
        if b != "derived" or not ms[0]["anchor"] or key in dis:
            continue
        for m in ms:
            if m["joined_by"] == "anchor" and m["lexeme"] not in out and m2.get(m["lexeme"]) != (key, "anchor"):
                stay_bad.append(m["lexeme"])
    R.check("tan groups (1.6): every g1 anchor member that step 2b keeps stays in its group (the same key: the head does "
            "not move)", not stay_bad, stay_bad[:5])
    gone = [k for k in dis if ("derived", k) in G2 and any(r["joined_by"] == "anchor" for r in G2[("derived", k)])]
    R.check("tan groups (1.6): every group step 2b dissolves has no anchor member left in h1", not gone, gone[:5])
    # the rule on h1 itself: no weak hbo member without a second route; no group of one member
    out2, _d2, _c2 = step2b(G2, "derived")
    R.check("tan groups (1.6): no hbo member of h1 under the floor or with ubs_depth under 3 without a second route",
            not out2, list(out2)[:5])
    one = [k for k, ms in G2.items() if len(ms) < 2]
    R.check("tan groups (1.6): no group of one member (strict and cgm)", not one, one[:5])
    n_st = sum(1 for (b, _k) in G2 if b == "derived")
    n_mem = sum(len(ms) for (b, _k), ms in G2.items() if b == "derived")
    R.info("tan groups (1.6): strict groups and members in h1 (g1: 431 and 989)", f"{n_st} groups, {n_mem} members")
    R.info("tan groups (1.6): strict rows by joined_by", dict(sorted(C.Counter(
        r["joined_by"] for (b, _k), ms in G2.items() if b == "derived" for r in ms).items())))
    # D25m: the cgm rows of h1 hold no loose hbo member without a second route (the floor of D25m reads the model
    # places, which lexemes.tsv does not hold: under-floor joins of D25m are not recomputed here)
    outm, dism, cm = step2b(G2, "model")
    R.check("tan groups (1.6, D25m): no hbo member of a cgm group with ubs_depth under 3 without a second route", not outm,
            list(outm)[:5])
    gm1 = {k for (b, k) in G1 if b == "model"}
    gm2 = {k for (b, k) in G2 if b == "model"}
    mm1 = {(k, r["lexeme"]) for (b, k), ms in G1.items() if b == "model" for r in ms}
    mm2 = {(k, r["lexeme"]) for (b, k), ms in G2.items() if b == "model" for r in ms}
    R.info("tan groups (D25m) against g1", {"cgm groups g1": len(gm1), "cgm groups h1": len(gm2), "gone": len(gm1 - gm2),
                                           "new": len(gm2 - gm1), "member rows gone": len(mm1 - mm2),
                                           "member rows new": len(mm2 - mm1)})
    # the strict groups, member by member, against g1
    s1 = {m["lexeme"]: frozenset(x["lexeme"] for x in ms) for (b, _k), ms in G1.items() if b == "derived" for m in ms}
    s2 = {m["lexeme"]: frozenset(x["lexeme"] for x in ms) for (b, _k), ms in G2.items() if b == "derived" for m in ms}
    mc = C.Counter()
    for x in set(s1) | set(s2):
        a, b_ = s1.get(x), s2.get(x)
        mc["joins" if a is None else "leaves" if b_ is None else "same members" if a == b_ else "other members"] += 1
    R.info("tan groups: strict members against g1", dict(sorted(mc.items())))
    # D27 kept_out: g1's alone with a g1 strict group at their anchor and class (the UBS gate), and the members out
    ac1 = {(ms[0]["anchor"], lex1[[m for m in ms if m["head"]][0]["lexeme"]]["class"])
           for (b, _k), ms in G1.items() if b == "derived" and ms[0]["anchor"]}
    gate = {x for x, r in lex1.items() if r["state"] == "alone" and (r["anchor"], r["class"]) in ac1}
    want_k = {x for x in gate | set(out) if x not in m2}
    have_k = {x for x, r in lex.items() if r["state"] == "kept_out"}
    R.check("tan lexemes (1.6): state kept_out recomputed (g1's alone beside a strict group at their anchor and class, "
            "and the members step 2b takes out, unless a member again by D26)", want_k == have_k,
            f"{len(have_k)} kept_out (UBS gate {len(gate)}, step 2b {len(out)}, member again {len(set(out) & set(m2))}); "
            f"recomputed {len(want_k)}; differ {sorted(want_k ^ have_k)[:5]}")
    st = C.Counter((lex1[k]["state"], lex[k]["state"]) for k in lex if k in lex1 and lex1[k]["state"] != lex[k]["state"])
    R.info("tan lexemes.tsv state moves against g1", {f"{a} -> {b}": n for (a, b), n in sorted(st.items())})
    heads = [dis[k] for k in dis]
    hb = [h for h in heads if lex[h]["state"] not in ("alone", "member")]
    R.check("tan lexemes (1.6): the head of a dissolved group is alone (or a member again by D26)", not hb, hb[:5])
    allowed = {("member", "kept_out"), ("alone", "kept_out"), ("member", "alone"), ("alone", "member"), ("member", "member")}
    odd = [(a, b) for (a, b) in st if (a, b) not in allowed]
    R.check("tan lexemes (1.6): states move only member -> kept_out or alone, alone -> kept_out or member (D25 step 2b, "
            "D26, D27)", not odd, odd)
    gm_bad = [k for k in lex if k in lex1 and lex[k]["group_model"] != lex1[k]["group_model"]]
    R.info("tan lexemes (1.6): group_model moved against g1", f"{len(gm_bad)}: {gm_bad[:10]}")
    # SAMPLE.md: the two new sections, every member out and every kept_out lexeme
    sm = open(os.path.join(L, "SAMPLE.md"), encoding="utf-8").read()
    R.check("tan lexicon/SAMPLE.md (1.6): the sections step2b_out and kept_out list every member out and every kept_out "
            "lexeme", f"## step2b_out ({len(out)})" in sm and f"## kept_out ({len(have_k)})" in sm and
            all(f"| {x} | {lex[x]['lemma']} |" in sm for x in set(out) | have_k))
    rf = open(os.path.join(L, "READ-FIRST.md"), encoding="utf-8").read()
    R.check("tan lexicon/READ-FIRST.md (1.6) names the D26 join לֵילֵי / חֹדֶשׁ and the state kept_out",
            "לֵילֵי" in rf and "חֹדֶשׁ" in rf and "`kept_out`" in rf)
    return {"out": out, "dis": dis, "lex": lex, "lex1": lex1, "gate": gate, "kept": have_k, "m2": m2, "st": st}


# ---- unchanged against g1 (section 13) ------------------------------------------------------------------------------

def unchanged16(R, build, g1):
    R.section("unchanged against g1 (SPEC 1.6 section 13)")
    for sub, kind in [(lg, "lang") for lg in LANGS] + [("lexicon", "lexicon"), ("other/heb_mod", "other"),
                                                         ("other/heb_scg", "other")]:
        a, b = os.path.join(g1, sub), os.path.join(build, sub)
        fa = sorted(f for f in os.listdir(a) if os.path.isfile(os.path.join(a, f)))
        fb = sorted(f for f in os.listdir(b) if os.path.isfile(os.path.join(b, f)))
        same = [f for f in fa if f not in CHANGED[kind] and f not in FOLLOW]
        diff = [f for f in same if f not in fb or _sha(os.path.join(a, f)) != _sha(os.path.join(b, f))]
        names = sorted((set(fa) ^ set(fb)) - {"VALIDATION.md"})
        R.check(f"{sub} unchanged: {len(same)} files byte-equal to g1 (all but "
                f"{', '.join(sorted((CHANGED[kind] | FOLLOW) & set(fa)))}); the same file names", not diff and not names,
                f"differ {diff}; names {names}")
        if os.path.exists(os.path.join(a, "map.tsv")):     # follow-on: the counts of the added codes 1.6 moves
            ma, mb = _tsv(os.path.join(a, "map.tsv")), _tsv(os.path.join(b, "map.tsv"))
            key = lambda r: tuple(v for c_, v in r.items() if c_ != "count")  # noqa: E731
            moved = [(key(x), x["count"], y["count"]) for x, y in zip(ma, mb) if x != y]
            ok = len(ma) == len(mb) and all(key(x) == key(y) for x, y in zip(ma, mb)) and all(
                k[0] == "added" and k[1] in ("kind", "form") for k, _x, _y in moved)
            R.check(f"{sub} map.tsv (follow-on): every row equals g1's but the count of the codes of added.kind and "
                    "added.form, which follows D18 step 2 of 1.6", ok, "; ".join(f"{k[1]} {k[2]}: g1 {x}, h1 {y}"
                                                                          for k, x, y in moved))
    for lg in LANGS:
        A = {(r["clause"], r["verb"], r["role"]): r for r in _rows(os.path.join(g1, lg, "added.parquet"))}
        B = {(r["clause"], r["verb"], r["role"]): r for r in _rows(os.path.join(build, lg, "added.parquet"))}
        bad = [k for k in B if k not in A or any(A[k][c] != B[k][c] for c in ("where", "antecedent"))]
        pn = [k for k in B if k in A and B[k]["form"] != "ending" and any(A[k][c] != B[k][c] for c in ("person", "number", "gender"))]
        R.check(f"{lg} added unchanged: clause, verb, role, where, antecedent of every row equal g1's; person, number, "
                "gender equal g1's on every row not of form ending", not bad and not pn and set(A) == set(B),
                f"{len(B):,} rows; key or column differs {len(bad)}; p/n/g off an ending row {len(pn)}")
    L1 = {r["lexeme"]: r for r in _tsv(os.path.join(g1, "lexicon", "lexemes.tsv"))}
    L2 = {r["lexeme"]: r for r in _tsv(os.path.join(build, "lexicon", "lexemes.tsv"))}
    cols = [c for c in next(iter(L2.values())) if c not in ("group", "state", "group_model")]
    bad = [k for k in L2 if k not in L1 or any(L1[k][c] != L2[k][c] for c in cols)]
    R.check("tan lexicon/lexemes.tsv unchanged: every column but group, state, group_model equals g1, row by row; the "
            "same keys", not bad and set(L1) == set(L2), f"{len(L2):,} keys; differ {len(bad)}")
    G1 = {(r["group"], r["lexeme"]): r for r in _rows(os.path.join(g1, "lexicon", "groups.parquet"))}
    G2 = {(r["group"], r["lexeme"]): r for r in _rows(os.path.join(build, "lexicon", "groups.parquet"))}
    cols = [c for c in next(iter(G2.values())) if c not in ("members", "same_strong")]
    stay = [k for k in G2 if k in G1]
    bad = [k for k in stay if any(G1[k][c] != G2[k][c] for c in cols)]
    R.check("tan lexicon/groups.parquet unchanged: the rows of the members that stay equal g1's in every column but "
            "members and same_strong (of a changed group)", not bad, f"{len(stay)} rows stay; differ {len(bad)}; "
            f"rows only in g1 {len(set(G1) - set(G2))}; only in h1 {len(set(G2) - set(G1))}")
    ss = [k for k in stay if G1[k]["same_strong"] != G2[k]["same_strong"]]
    R.info("tan groups.parquet: same_strong moved on rows that stay (a member left the group)", len(ss))


# ---- reading sheets -------------------------------------------------------------------------------------------------

def sheets16(R):
    R.section("reading sheets (1.6)")
    fs = sorted(f for f in os.listdir(GLOSSED) if f.endswith(".md") and f not in ("mends-sample.md", "equivalents-sample.md"))
    rows = bad = 0
    for f in fs:
        hdr = None
        for ln in open(os.path.join(GLOSSED, f), encoding="utf-8"):
            if ln.startswith("| + | clause |"):
                hdr = [c.strip() for c in ln.strip().strip("|").split("|")]
                if "who_reason" not in hdr or "form" not in hdr:
                    bad += 1
            elif ln.startswith("| + |") and hdr:
                rows += 1
                cells = [c.strip() for c in ln.strip().strip("|").split("|")]
                if len(cells) != len(hdr) or not cells[hdr.index("who_reason")] or not cells[hdr.index("form")]:
                    bad += 1
    R.check(f"glossed-h1/: the {len(fs)} chapters show who_reason and form on every added row", len(fs) == 8 and rows > 0
            and not bad, f"{rows} added rows; without them {bad}")


# ---- run ------------------------------------------------------------------------------------------------------------

def run(R, build):
    g1 = os.path.join(os.path.dirname(os.path.normpath(build)), "g1")
    bname = os.path.basename(os.path.normpath(build))
    ctx = Ctx(build)
    terms = {}
    for lg in LANGS:
        for r in _tsv(os.path.join(build, lg, "terms.tsv")):
            terms[(lg, r["category"], r["code"])] = r["grc" if lg == "grc" else "hbo"]
    unchanged16(R, build, g1)
    mv = added16(R, build, g1, ctx, terms, None)
    se5 = se16(R, build, g1, ctx)
    gr = groups16(R, build, g1)
    sheets16(R)
    R.info("words looked up in the other Tanakh table (a row whose word stands there)", dict(ctx.other_table))
    # ---- the sample of mends
    md = [f"# Sample of the mends of version 1.6: build h1 against g1", "",
          "Written by `validate_examples.py --build h1 --upto 38 --write-md` (`validate_examples_s38.py`). For every mend "
          "of SPEC 1.6 (R1, R2, R3, R5, R7, R9, SE5) and every language: what moved against `g1`, counted, and a sample "
          "by a fixed rule: the changed rows in text order, the first 5, then every k-th (k = (n - 5) // 15), 20 in "
          "all. Each line: the place and the word of the row's own language (a Tanakh word that stands in the other "
          "Tanakh table is read there), the value in `g1` and in `h1`. Nothing here is a gloss.", ""]

    def section(title, lg, items, counts):
        md.extend([f"## {title}: {lg}", "", "Moved against g1: " + (
            "; ".join(f"{k} {v:,}" for k, v in counts.items()) if counts else "none") + f" ({len(items):,} rows).", ""])
        md.extend(f"- {x}" for x in pick(items))
        md.append("")
    for code, title in (("R1", "R1, the subject row under a causative stem without a causer (D18 step 2)"),
                        ("R2", "R2, person, number, gender of an ending row from the stem piece (D18 step 2)"),
                        ("R3", "R3, who on a set (D18 step W)"),
                        ("R5", "R5, in_verb only on ending rows; other kinds from where (D18 step 2)")):
        for lg in LANGS:
            m, lists = mv[lg]
            key = {"R1": "R1 new subject", "R2": "R2", "R3": "step W who moved", "R5": "(R5)"}[code]
            cs = {k: v for k, v in sorted(m.items()) if key in k and not (code == "R3" and "R1 new subject row" in k)}
            section(title, lg, lists[code], cs)
    for lg in LANGS:
        section("SE5, the two readings of who share no entity (source_errors.tsv)", lg,
                [f"{r[2]} {ctx.place(int(r[2].split('.')[0]), lg)}: g1 no row; h1 value {r[3]}" for r in se5[lg]],
                {"SE5 rows": len(se5[lg])})
    lex, lex1, out, dis = gr["lex"], gr["lex1"], gr["out"], gr["dis"]
    for lg in ("hbo", "arc"):
        items = [f"{lex[x]['lemma']} ({x}): g1 in {v[0]} (head {lex[v[1]]['lemma']}, {v[2]}); h1 "
                 + (f"{gr['m2'][x][0]} by {gr['m2'][x][1]}" if x in gr["m2"] else "in no group") + f", state {lex[x]['state']}"
                 for x, v in sorted(out.items()) if lex[x]["lang"] == lg]
        items += [f"group {k} (head {lex[h]['lemma']}): dissolved" for k, h in sorted(dis.items()) if lex[h]["lang"] == lg]
        section("R7, D25 step 2b: weak joins without a second route leave", lg, items,
                {"members out": sum(1 for x in out if lex[x]["lang"] == lg),
                 "groups dissolved": sum(1 for h in dis.values() if lex[h]["lang"] == lg)})
        mvd = sorted(k for k in lex if k in lex1 and lex1[k]["state"] != lex[k]["state"] and lex[k]["lang"] == lg)
        items = [f"{lex[k]['lemma']} ({k}, anchor {lex[k]['anchor'] or '-'}): g1 {lex1[k]['state']}; h1 {lex[k]['state']}"
                 for k in mvd]
        section("R9, D27 state kept_out (and alone for the heads of dissolved groups)", lg, items,
                {f"{a} -> {b}": sum(1 for k in mvd if (lex1[k]["state"], lex[k]["state"]) == (a, b))
                 for a, b in sorted({(lex1[k]["state"], lex[k]["state"]) for k in mvd})})
    text = "\n".join(md).rstrip("\n") + "\n"
    R.section("sample of mends (1.6)")
    if WRITE:
        os.makedirs(GLOSSED, exist_ok=True)
        with open(SAMPLE, "w", encoding="utf-8") as fh:
            fh.write(text)
    have = open(SAMPLE, encoding="utf-8").read() if os.path.exists(SAMPLE) else None
    R.check("glossed-h1/mends-sample.md: equals the sample this check writes (every mend of 1.6 per language, its count, "
            "the fixed-rule sample, words of the row's own language)", have == text and bname == "h1" or
            (bname != "h1" and have is not None), f"{text.count(chr(10)):,} lines" if have == text else
            "missing or differs: run with --write-md")
