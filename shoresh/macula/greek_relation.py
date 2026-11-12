"""A relation label per clause of the Greek NT layout, in the Hebrew layout's vocabulary, by rule; and one clause-shape vocabulary for
both layouts. Both were worked out and handed over by make-tanakh-research (2026-11-12, packets 04 and 06), and are ported here to
read bcv-query's own inputs: the layout rows, macula-spine.db, trees-macula.db, and MACULA Greek's adjunct types (CC BY 4.0, pinned).

    relations(rows)  -> {clause: (relation, basis, connective)}     rows: the Greek layout's rows in text order (one book or all)
    shapes(lang, rows) -> {clause id: shape}                          Hebrew id `clause_key`, Greek `clause`

Relation, in this order (`basis` names the rule that decided):
  speech        the first main clause of a quotation (`quotation`)
  subordinator  the clause's own first words: ἵνα / ὅπως purpose, διότι / ἐπεί causal, εἰ / ἐάν conditional, ὅτε / ὅταν / ἕως temporal,
                καθώς / ὥσπερ comparison, ὥστε consequence; ὅτι and ὡς are two-way and settled by MACULA's adjunct type, else by role.
                A subordinator printed on a pre-nuclear dependent that the tree hangs on the parent belongs to the parent (JHN 5:38)
  relative      a relative pronoun among the first two words
  role          object clause complement, subject clause subject, adverbial participle circumstantial, adverbial infinitive purpose,
                articular clause embedded; an adjunct type on the clause refines these
  connective    for a clause that hangs on nothing: γάρ causal, οὖν / διό consequence, ἀλλά / πλήν adversative, καί / δέ ...
                coordination, none asyndetic; lifted from its pre-nuclear dependent where the tree hangs it above (packet 01), or
                from a sibling adverbial clause before it in the same sentence (Acts 19:6)
Values outside the Hebrew vocabulary: comparison, subject, place, concession.

Shape: the roles of the clause's constituents in order, S subject, O object, V verb (the copula too), P predicate, A adjunct (ADV, PP,
IO; a run is one A), N a lone noun phrase, I interjection, + a coordination of clauses, ~ another clause complex; read from the
rule string where it is a role sequence or a one-constituent rule, else from the tree (the roles of the clause node's children).
"""
from __future__ import annotations

import collections
import functools
import json
import re
import sqlite3
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TREES, SPINE = HERE / "trees-macula.db", HERE / "macula-spine.db"
ADJUNCT_PIN = "27bf625776c645100ad97c10b5ef8228e68893ad"
ADJUNCT_URL = f"https://raw.githubusercontent.com/Clear-Bible/macula-greek/{ADJUNCT_PIN}/sources/Clear/adjunct-types/adjunct_type.json"
CACHE = HERE / ".cache" / "macula-greek" / ADJUNCT_PIN

SUB = {"ἵνα": "purpose", "ὅπως": "purpose", "διότι": "causal", "ἐπεί": "causal", "ἐπειδή": "causal", "εἰ": "conditional", "ἐάν": "conditional",
       "ὅτε": "temporal", "ὅταν": "temporal", "ἕως": "temporal", "πρίν": "temporal", "ἡνίκα": "temporal", "καθώς": "comparison", "ὥσπερ": "comparison",
       "καθάπερ": "comparison", "ὡσεί": "comparison", "ὥστε": "consequence", "ὅτι": "?hoti", "ὡς": "?hos", "ἄχρι": "temporal", "μέχρι": "temporal",
       "ἐπάν": "temporal", "ὁσάκις": "temporal", "καθότι": "causal", "ἐπειδήπερ": "causal", "εἴτε": "conditional", "κἄν": "conditional", "ἐάνπερ": "conditional",
       "εἴπερ": "conditional", "μήποτε": "purpose", "ὅπου": "relative", "ὅθεν": "relative", "οὗ": "relative"}
POST = ("δέ", "γάρ", "οὖν", "μέν", "τέ")
SENT = {"γάρ": "causal", "οὖν": "consequence", "διό": "consequence", "ἄρα": "consequence", "ἀλλά": "adversative", "πλήν": "adversative", "ὅθεν": "consequence",
        "καί": "coordination", "δέ": "coordination", "τέ": "coordination", "ἤ": "coordination", "οὐδέ": "coordination", "μηδέ": "coordination",
        "μέν": "coordination", "οὔτε": "coordination", "μήτε": "coordination"}
ADJ = {"Source": "causal", "Projection": "complement", "Condition": "conditional", "Goal": "purpose", "Manner": "comparison", "Time": "temporal",
       "Comparison": "comparison", "Result": "consequence", "Place": "place", "Concession": "concession"}
STRONG = ("causal", "consequence", "adversative")


@functools.lru_cache(maxsize=1)
def adjunct_types() -> dict[str, str]:
    p = CACHE / "adjunct_type.json"
    if not p.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(ADJUNCT_URL, timeout=120) as r:
            p.write_bytes(r.read())
    return {x["node_head"].lstrip("n"): x["field_type"] for x in json.loads(p.read_text(encoding="utf-8")) if x["node_category"] in ("conj", "CL")}


@functools.lru_cache(maxsize=1)
def _greek():
    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    tr = sqlite3.connect(f"file:{TREES}?mode=ro", uri=True)
    wt = dict(tr.execute("SELECT key, wtype FROM words WHERE corpus='grc' AND inserted=0"))
    T = {k: (lem, cls, mood, wt.get(k), case) for k, lem, cls, mood, case in
         sp.execute("SELECT key, lemma, class, mood, case_ FROM macula_words WHERE length(key)=11")}
    W = {k: (cl, role) for k, cl, role in tr.execute("SELECT key, cl, role FROM words WHERE corpus='grc' AND inserted=0")}
    N = dict(tr.execute("SELECT id, parent FROM nodes WHERE corpus='grc'"))
    return T, W, N


def relations(rows: list[dict]) -> dict[str, tuple]:
    T, W, N = _greek()
    adj = adjunct_types()
    C: dict = collections.OrderedDict()
    qstart, seenq, seenc = set(), set(), set()
    for i, r in enumerate(rows):
        if not r.get("clause"):
            continue
        if r.get("quotation") and r["quotation"] not in seenq:
            seenq.add(r["quotation"])
            if r["clause"] not in seenc:
                qstart.add(r["clause"])
        seenc.add(r["clause"])
        c = C.setdefault(r["clause"], {"words": [], "parent": r.get("parent"), "role": r.get("role"), "via": list(r.get("via") or []),
                                       "quotation": r.get("quotation"), "first": i, "sentence": r.get("sentence")})
        c["words"] += [str(k).lstrip("n") for k in r["words"]]

    def node(c):
        cnt = collections.Counter(W[k][0] for k in c["words"] if k in W and W[k][1]) or collections.Counter(W[k][0] for k in c["words"] if k in W)
        return cnt.most_common(1)[0][0] if cnt else None

    def at_or_above(a, b):
        n = 0
        while b is not None and n < 40:
            if a == b:
                return True
            b, n = N.get(b), n + 1
        return False
    for c in C.values():
        c["node"] = node(c)
    lifted, opens, sublift, subskip = {}, {}, {}, set()
    for cid, c in C.items():
        opens.setdefault(c["sentence"], cid)

    def root(cid):
        n = 0
        while C[cid]["parent"] in C and n < 40:
            cid, n = C[cid]["parent"], n + 1
        return cid
    for cid, c in C.items():
        c["sent"] = None
        par = C.get(c["parent"])
        k0 = c["words"][0] if c["words"] else None
        if par is not None and par["first"] > c["first"] and k0 in T and T[k0][0] in SUB and k0 in W and par["node"] is not None and c["node"] is not None \
                and W[k0][0] != c["node"] and at_or_above(W[k0][0], par["node"]):
            sublift[c["parent"]] = (T[k0][0], cid)
            subskip.add(cid)
        for j, k in enumerate(c["words"][:4]):
            t = T.get(k)
            if not t or t[0] not in SENT or (j > 0 and t[0] not in POST) or (j == 3 and t[0] not in POST):
                continue
            before = par is not None and par["first"] > c["first"]
            up = before and k in W and par["node"] is not None and at_or_above(W[k][0], par["node"])
            if not up and before and t[0] in POST and opens.get(c["sentence"]) == cid:
                up = "post"
            if up:
                tgt = root(cid) if up == "post" else c["parent"]
                if tgt not in lifted or SENT[t[0]] in STRONG:
                    lifted[tgt] = (t[0], cid)
            elif c["sent"] is None or SENT[t[0]] in STRONG:
                c["sent"] = t[0]
    q2 = set()
    for q in qstart:
        t, n = q, 0
        while C[t]["parent"] in C and C[C[t]["parent"]]["first"] > C[t]["first"] and n < 10:
            t, n = C[t]["parent"], n + 1
        q2.add(t)
    qstart = q2
    qpar = {str(C[q]["quotation"]).lstrip("n"): C[q]["parent"] for q in qstart}
    sibs = collections.defaultdict(list)
    for cid, c in C.items():
        if c["parent"]:
            sibs[(c["parent"], c["role"])].append(cid)
    out = {}
    for cid, c in C.items():
        toks = [T[k] for k in c["words"][:4] if k in T]
        a = next((adj[k] for k in c["words"][:3] if k in adj), None)
        moods = [t[2] for t in toks if t[1] == "verb"]
        rel = basis = conn = None
        sub = next((t[0] for t in toks[(1 if cid in subskip else 0):3] if t[0] in SUB and (c["parent"] or t[0] != "ὅθεν")), None)
        if sub is None and cid in sublift:
            sub = sublift[cid][0]
            if a is None:
                a = next((adj[k] for k in C[sublift[cid][1]]["words"][:1] if k in adj), None)
        if sub in ("ὡς", "ὡσεί") and a not in ADJ and not c["parent"]:
            sub = None
        if cid in qstart:
            rel, basis = "speech", "speech"
        elif c["quotation"] and c["parent"] and c["role"] == "o" and qpar.get(str(c["quotation"]).lstrip("n")) == c["parent"] and not sub:
            rel, basis, conn = (SENT[c["sent"]], "connective (inside a speech)", c["sent"]) if c["sent"] else ("asyndetic", "no connective (inside a speech)", None)
        elif sub:
            rel, basis, conn = SUB[sub], "subordinator", sub
            if sub in ("ἵνα", "ὅπως") and a == "Projection":
                rel, basis = "complement", "subordinator + adjunct type"
            if rel.startswith("?"):
                if a in ADJ:
                    rel, basis = ADJ[a], "subordinator + adjunct type"
                elif sub == "ὅτι":
                    rel, basis = ("complement" if c["role"] in ("o", "s", "p") else "causal"), "subordinator + role"
                else:
                    rel, basis = "comparison", "subordinator (default)"
        elif any(t[1] == "pron" and t[3] == "relative" for t in toks[:2]):
            rel, basis = "relative", "relative pronoun"
        elif c["parent"]:
            if a in ADJ:
                rel, basis = ADJ[a], "adjunct type"
            elif c["role"] in ("o", "s") and (c["sent"] or cid in lifted) and sibs[(c["parent"], c["role"])][0] != cid:
                conn = c["sent"] or lifted[cid][0]
                rel, basis = SENT[conn], "connective (after a clause of the same role)"
            elif c["role"] == "o":
                rel, basis = "complement", "role"
            elif c["role"] == "s":
                rel, basis = "subject", "role"
            elif c["role"] == "adv":
                rel, basis = ("circumstantial", "role + participle") if "participle" in moods else \
                    ("purpose", "role + infinitive") if "infinitive" in moods else (None, None)
            elif "DetCL" in c["via"]:
                rel, basis = "embedded", "articular"
            if rel is None and c["sent"]:
                rel, basis, conn = SENT[c["sent"]], "connective (inside a clause complex)", c["sent"]
            elif rel is None and c["role"] != "adv":
                allm = [T[k][2] for k in c["words"] if k in T and T[k][1] == "verb"]
                if allm and allm[0] == "participle":
                    pc = next((T[k][4] for k in c["words"] if k in T and T[k][1] == "verb"), None)
                    rel, basis = ("circumstantial", "participle without a role, nominative") if pc == "nominative" else \
                        ("embedded", "participle without a role (attributive)")
                elif allm and allm[0] == "infinitive":
                    rel, basis = "complement", "infinitive without a role"
                else:
                    rel, basis = "asyndetic", "no connective (inside a clause complex)"
        if rel is None and not c["parent"]:
            s = lifted.get(cid, (None, None))[0] if (cid in lifted and (c["sent"] is None or SENT[lifted[cid][0]] in STRONG)) else c["sent"]
            if s:
                rel, conn = SENT[s], s
                basis = "connective (on its pre-nuclear dependent)" if cid in lifted and s == lifted[cid][0] and s != c["sent"] else "connective"
            elif toks and all(t[4] == "vocative" for t in toks if t[1] in ("noun", "adj")) and any(t[4] == "vocative" for t in toks):
                rel, basis = "vocative", "case"
            else:
                rel, basis = "asyndetic", "no connective"
        out[cid] = [rel, basis, conn]
        vm = [T[k][2] for k in c["words"] if k in T and T[k][1] == "verb"]
        c["finite"] = any(m in ("indicative", "subjunctive", "imperative", "optative") for m in vm)
        c["ptc"] = bool(vm) and not c["finite"]
        c["sub"] = bool(sub)
    tops = collections.defaultdict(list)
    for cid, c in C.items():
        if not c["parent"]:
            tops[c["sentence"]].append(cid)
    for ts in tops.values():
        pend, pre = None, []
        for i, cid in enumerate(ts):
            c = C[cid]
            if (not c["finite"] or c["sub"]) and i + 1 < len(ts):
                pend = c["sent"] or lifted.get(cid, (None,))[0] or pend
                pre.append(cid)
                continue
            if pre and out[cid][1] == "no connective":
                if pend:
                    out[cid] = [SENT[pend], "connective (on its pre-nuclear clause, same sentence)", pend]
                for q in pre:
                    if out[q][1] in ("connective", "no connective", "connective (on its pre-nuclear dependent)") and C[q]["ptc"]:
                        out[q] = ["circumstantial", "participle before the main clause", None]
            if i and out[cid][1] == "no connective" and not c["finite"]:
                vm = [T[k][2] for k in c["words"] if k in T and T[k][1] == "verb"]
                if vm:
                    out[cid] = ["circumstantial" if vm[0] == "participle" else "complement", "non-finite clause after the main clause", None]
            pend, pre = None, []
    return {k: tuple(v) for k, v in out.items()}


# --- clause shapes -------------------------------------------------------------------------------------------------------------
ROLE = {"S": "S", "O": "O", "O2": "O", "V": "V", "VC": "V", "P": "P", "ADV": "A", "PP": "A", "IO": "A", "AUX": ""}
ONE = {"V2CL": "V", "P2CL": "P", "Np2CL": "N", "Intj2CL": "I", "PP2CL": "A", "ADV2CL": "A", "O2CL": "O", "O22CL": "O", "S2CL": "S", "ppCL": "A",
       "AdvpCL": "A", "AdjpCL": "P", "Relp2CL": "N"}
SEQ = re.compile(r"(S|O|O2|IO|V|VC|P|PP|ADV)(-(S|O|O2|IO|V|VC|P|PP|ADV))*$")


def fold(roles) -> str:
    out = []
    for r in roles:
        x = ROLE.get((r or "").upper(), "")
        if x and not (x == "A" and out and out[-1] == "A"):
            out.append(x)
    return "-".join(out)


def from_rule(rule):
    if not rule:
        return None
    if SEQ.match(rule):
        return fold(rule.split("-"))
    if rule in ONE:
        return ONE[rule]
    if re.search(r"aCL|andCL|Conj\dCL|EitherOr", rule):
        return "+"
    return None


@functools.lru_cache(maxsize=2)
def _tree(corpus: str):
    db = sqlite3.connect(f"file:{TREES}?mode=ro", uri=True)
    W = {k: (seq, role, parent, cl) for k, seq, role, parent, cl in
         db.execute("SELECT key, seq, role, parent, cl FROM words WHERE corpus=? AND inserted=0", (corpus,))}
    N = {i: (parent, role, rule, lo) for i, parent, role, rule, lo in db.execute("SELECT id, parent, role, rule, lo FROM nodes WHERE corpus=?", (corpus,))}
    kids = collections.defaultdict(list)
    for i, (parent, role, rule, lo) in N.items():
        if role:
            kids[parent].append((lo or 0, role))
    for k, (seq, role, parent, cl) in W.items():
        if role:
            kids[parent].append((seq, role))
    return W, N, kids


def shapes(lang: str, rows: list[dict]) -> dict[str, str]:
    key = "clause_key" if lang == "hbo" else "clause"
    clauses: dict = {}
    for r in rows:
        if r.get(key):
            clauses.setdefault(r[key], [r.get("rule"), r.get("kind"), []])[2].extend(str(k).lstrip("n") for k in r["words"])
    out = {}
    tree = None
    for cid, (rule, kind, words) in clauses.items():
        s = from_rule(rule)
        if s is None:
            tree = tree or _tree(lang)
            W, N, kids = tree
            ws = [W[k] for k in words if k in W]
            cls_ = collections.Counter(w[3] for w in ws if w[3] in N)
            roled = collections.Counter(w[3] for w in ws if w[1] and w[3] in N)
            if cls_:
                c = next((x for x, _ in cls_.most_common() if rule and N[x][2] == rule), None) or (roled or cls_).most_common(1)[0][0]
                s = fold([r for _, r in sorted(kids.get(c, []))]) or None
        if s is None:
            s = "~" if rule else ("V" if kind == "VC" else "")
        out[cid] = s
    return out
