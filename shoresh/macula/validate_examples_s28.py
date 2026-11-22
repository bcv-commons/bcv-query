"""Stage 28 checks (SPEC 1.3, section 10): `marks.time_abs` (D16), the causative rule (D12c), `who` by reference
(D7r), the catch-all names (D7n), `who_account.parquet` (D19), and the changed columns against d1 (SPEC 13).
Imports nothing from the builders: every value is recomputed here from the datasets on disk and the build's own
G columns (and d1, whose `who` is the result of D7 steps 1 to 4, unchanged by section 13).

    stage28(R, build)                      called by validate_examples.py --build e1 --upto 28
    d7r_candidates(build), d12c_moves(...)  used by the stage-16 checks of an e build
    python -I validate_examples_s28.py [build]     stage 28 alone
"""
import collections as C
import csv
import hashlib
import json
import os
import tomllib

import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "data")
LANGS = ("hbo", "arc", "grc")
TYPES = ("person", "place", "group", "deity", "realia", "flora", "fauna")
CAUSATIVE = {"hbo": ("hiphil",), "arc": ("haphel", "aphel", "shaphel"), "grc": ()}
NO_WHO = {"hbo": ("cj", "prep", "art"), "arc": ("cj", "prep", "art"), "grc": ("conj", "prep", "det")}
STATES = ["participant", "generic", "not_referring", "entity_not_taken", "no_entity", "unresolved", "no_row"]
KINDS = ["noun", "pronoun", "suffix", "verb_zero"]
GROUPS = (("hbo", ("hbo", "arc")), ("grc", ("grc",)))
V16 = False          # an h build (SPEC 1.6): set by validate_examples.py
V15 = False   # a g build (SPEC 1.5): D16 for Greek verbless clauses, the causer (D12c), D19's verb_zero reason


def tsv(path, col=None, val=None):
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader((ln for ln in fh if not ln.startswith("#")), delimiter="\t", quoting=csv.QUOTE_NONE))
    return rows if col is None else [r for r in rows if r[col] == val]


def tab(build, lg, name, cols=None):
    return pq.read_table(os.path.join(build, lg, f"{name}.parquet"), columns=cols).to_pydict()


def jd(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Ents:
    def __init__(self):
        self.rows = {r["entity"]: r for r in tsv(os.path.join(D, "entities", "entities.tsv"))}
        self.key = {}
        self.acai = {}
        for a, r in self.rows.items():
            if r["type"] in TYPES:
                k = f"{r['type']}:e{hashlib.sha1(a.encode('utf-8')).hexdigest()[:10]}"
                self.key[a] = k
                self.acai[k] = a

    @staticmethod
    def catch_all(acai):
        tail = acai.partition(":")[2]
        return tail[:7] == "Generic" or tail == "Messenger" or tail == "Messengers"


def entity_ref(ref):
    return ref != "" and ref.split(":")[0] not in ("unresolved", "lemma")


def terms(build, lg):
    col = "grc" if lg == "grc" else "hbo"
    return {(r["category"], r["code"]): r[col] for r in tsv(os.path.join(build, lg, "terms.tsv"))}


# ---- helpers for the stage-16 checks ---------------------------------------------------------------------------------

def _zero_subject_preds(build, gl):
    """pid of the stem piece of the predicate of every clause with pred_kind v and subject_form zero."""
    stem = {}
    for lg in gl:
        P = tab(build, lg, "pieces", ["t", "pid", "kind"])
        for t, pid, k in zip(P["t"], P["pid"], P["kind"]):
            if k == "stem":
                stem[t] = pid
    out = set()
    for lg in gl:
        K = tab(build, lg, "clauses", ["pred", "pred_kind", "marks"])
        for pred, pk, mk in zip(K["pred"], K["pred_kind"], K["marks"]):
            if pk == "v" and pred in stem and json.loads(mk).get("subject_form") == "zero":
                out.add(stem[pred])
    return out


def d7r_candidates(build, E=None):
    """pid -> (ent, step): D7r's referent for a piece, (a) before (b); applied only where D7 steps 1 to 4 give none."""
    E = E or Ents()
    out = {}
    for corpus, gl in GROUPS:
        pre = "n" if corpus == "grc" else "o"
        zero = _zero_subject_preds(build, gl)
        for r in tsv(os.path.join(D, "implicit-args", "args.tsv"), "corpus", corpus):
            pid = pre + r["verb"]
            if r["role"] == "A0" and r["in_verb"] == "1" and pid in zero and r["referent"] in E.key:
                out[pid] = (E.key[r["referent"]], "b")
        for r in tsv(os.path.join(D, "reference-status", "np.tsv"), "corpus", corpus):
            if r["basis"] == "ref" and r["referent"] in E.key:
                out[pre + r["head"]] = (E.key[r["referent"]], "a")
    return out


def d12c_moves(build, lg, actor_term):
    """(clause, ord) of the constituents D12c moves, given the D12 role (the caller's recomputed sem_role)."""
    P = {}
    for l2 in (("hbo", "arc") if lg != "grc" else ("grc",)):
        X = tab(build, l2, "pieces", ["t", "kind", "marks"])
        for t, k, m in zip(X["t"], X["kind"], X["marks"]):
            if k == "stem":
                P[t] = (l2, json.loads(m).get("stem", ""))
    pred = {}
    for l2 in (("hbo", "arc") if lg != "grc" else ("grc",)):
        K = tab(build, l2, "clauses", ["clause", "pred"])
        pred.update(zip(K["clause"], K["pred"]))
    N = tab(build, lg, "constituents", ["clause", "ord", "role"])
    out = set()
    for k, o, role in zip(N["clause"], N["ord"], N["role"]):
        if role in ("o", "o2"):
            s = P.get(pred[k])
            if s and s[1] in CAUSATIVE[s[0]]:
                out.add((k, o))
    return out


# ---- D16, recomputed ---------------------------------------------------------------------------------------------------

def time_abs_all(build, gl, tm):
    """clause -> (lg, value code or '', reason, model?) for every clause with a time; tm: lg -> term -> code."""
    own, parent, where = {}, {}, {}
    for lg in gl:
        K = tab(build, lg, "clauses", ["clause", "parent", "marks", "marks_model"])
        for k, p, mk, mm in zip(K["clause"], K["parent"], K["marks"], K["marks_model"]):
            parent[k], where[k] = p, lg
            a = json.loads(mk).get("time")
            b = json.loads(mm).get("time") if mm else None
            if a is not None:
                own[k] = (tm[lg][a], False)
            elif b is not None:
                own[k] = (tm[lg][b], True)
    done = {}
    order = []
    for k in own:          # resolve top-down without recursion: collect each chain of relative times
        stack = [k]
        while stack:
            x = stack[-1]
            if x in done:
                stack.pop()
                continue
            code, model = own[x]
            if code in ("past", "present", "future", "timeless", "irrealis"):
                done[x] = (code, "", model)
                stack.pop()
                continue
            up = parent[x]
            while up and up not in own:
                up = parent[up]
            if not up:
                done[x] = ("", "no ancestor", model)
                stack.pop()
                continue
            if up not in done:
                stack.append(up)
                continue
            pv, _r, pm = done[up]
            m = model or pm
            table = {"simultaneous": {"past": "past", "present": "present", "future": "future", "timeless": "timeless"},
                     "anterior": {"past": "past", "present": "past"},
                     "posterior": {"present": "future", "future": "future"}}[code]
            if not pv:
                done[x] = ("", "ancestor unresolved", m)
            elif pv in table:
                done[x] = (table[pv], "", m)
            else:
                done[x] = ("", f"{code} under {pv}", m)
            stack.pop()
        order.append(k)
    return {k: (where[k],) + done[k] for k in own}, own


# ---- the checks ----------------------------------------------------------------------------------------------------

def stage28(R, build, d1=None):
    d1 = d1 or os.path.join(os.path.dirname(os.path.normpath(build)), "d1")
    E = Ents()
    T = {lg: terms(build, lg) for lg in LANGS}
    cats = {}
    for lg in LANGS:
        with open(os.path.join(build, lg, "categories.toml"), "rb") as fh:
            cats[lg] = tomllib.load(fh)

    # ---- D16 -----------------------------------------------------------------------------------------------------
    R.section("clauses.marks.time_abs (D16)")
    for corpus, gl in GROUPS:
        tm = {lg: {v: k[1] for k, v in T[lg].items() if k[0] == "time"} for lg in gl}
        res, own = time_abs_all(build, gl, tm)
        if V15 and corpus == "grc":      # SPEC 1.5 D9, D16 (A6): a verbless clause takes its ancestor's time_abs
            import validate_examples_s35 as S35
            res = S35.verbless_time_abs(R, build, res, own)
        for lg in gl:
            K = tab(build, lg, "clauses", ["clause", "marks", "marks_model"])
            bad = badm = 0
            why, resolved, rel = C.Counter(), C.Counter(), C.Counter()
            for k, mk, mm in zip(K["clause"], K["marks"], K["marks_model"]):
                a = json.loads(mk).get("time_abs")
                b = json.loads(mm).get("time_abs") if mm else None
                got = res.get(k)
                want_a = want_b = None
                if got:
                    _lg, v, reason, model = got
                    if v:
                        if model:
                            want_b = T[lg][("time", v)]
                        else:
                            want_a = T[lg][("time", v)]
                    else:
                        why[reason] += 1
                    if k in own and own[k][0] in ("anterior", "simultaneous", "posterior"):
                        rel[own[k][0]] += 1
                        if v:
                            resolved[f"{own[k][0]} -> {v}"] += 1
                bad += a != want_a
                badm += b != want_b
            R.check(f"{lg} clauses.marks.time_abs: equals D16 recomputed from time and parent on every clause (strict "
                    "times only)", bad == 0, f"{bad} differ; {sum(1 for m in K['marks'] if 'time_abs' in json.loads(m)):,} filled")
            R.check(f"{lg} clauses.marks_model.time_abs: equals D16 where it reads a marks_model time (D9m)", badm == 0,
                    f"{badm} differ; {sum(1 for m in K['marks_model'] if m and 'time_abs' in json.loads(m)):,} filled")
            R.info(f"{lg} D16 relative times, resolved (SPEC over d1, all times: hbo 6,994 of 13,654, arc 147 of 302, "
                   "grc 6,854 of 10,205)", f"{sum(resolved.values()):,} of {sum(rel.values()):,}: {dict(sorted(resolved.items()))}")
            R.info(f"{lg} D16 empty time_abs on a clause with a time, by reason", dict(why.most_common()))
            R.check(f"{lg} D16: every empty time_abs has a reason of SPEC D16",
                    set(why) <= ({"verbless, no ancestor", "verbless, ancestor unresolved"} if V15 else set()) | {"no ancestor", "ancestor unresolved", "anterior under future", "anterior under timeless",
                                 "anterior under irrealis", "posterior under past", "posterior under timeless",
                                 "posterior under irrealis", "simultaneous under irrealis"}, sorted(why))
            sec = cats[lg].get("clauses", {}).get("time_abs")
            use = C.Counter(json.loads(m).get("time_abs") for m in K["marks"])
            use.pop(None, None)
            ok = sec is not None and {v["term"]: v["count"] for v in sec["values"]} == dict(use) and \
                all(T[lg].get(("time", v["code"])) == v["term"] for v in sec["values"])
            R.check(f"{lg} categories.toml clauses.time_abs: every term declared with its code (category time) and count",
                    ok if use else sec is None or not sec.get("values"), f"{len(use)} terms")
            mm = C.Counter(v for m in K["marks_model"] if m for c, v in json.loads(m).items() if c == "time_abs")
            sm = cats[lg].get("clauses", {}).get("marks_model", {})
            decl = {v["term"]: v["count"] for v in sm.get("values", []) if v.get("category") == "time_abs"}
            R.check(f"{lg} categories.toml clauses.marks_model: the time_abs values declared with their counts",
                    decl == dict(mm), dict(mm))

    # ---- D12c ----------------------------------------------------------------------------------------------------
    R.section("constituents.sem_role: the caused party of a causative verb (D12c)")
    for lg in LANGS:
        N = tab(build, lg, "constituents", ["clause", "ord", "role", "sem_role", "sem_role_basis"])
        N1 = tab(d1, lg, "constituents", ["clause", "ord", "sem_role", "sem_role_basis"])
        actor, und = T[lg][("sem_role", "actor")], T[lg][("sem_role", "undergoer")]
        mv = d12c_moves(build, lg, actor)
        causer = set()
        if V15:      # SPEC 1.5 D12c (A3): the causer takes actor where D12 gave none
            import validate_examples_s35 as S35
            causer = S35.causer_rows(R, build, lg, N1)
        left = sum(1 for k, o, s in zip(N["clause"], N["ord"], N["sem_role"]) if (k, o) in mv and s == actor)
        R.check(f"{lg} D12c: no o or o2 under a causative stem is actor", left == 0, left)
        moved, other = [], 0
        for k, o, s, b, s1, b1 in zip(N["clause"], N["ord"], N["sem_role"], N["sem_role_basis"], N1["sem_role"],
                                      N1["sem_role_basis"]):
            if (s, b) != (s1, b1):
                if (k, o) in mv and s1 == actor and (s, b) == (und, "derived"):
                    moved.append((k, o))
                elif (k, o) in causer and (s, b) == (actor, "derived"):
                    pass
                else:
                    other += 1
        want = sum(1 for k, o, s1 in zip(N1["clause"], N1["ord"], N1["sem_role"]) if (k, o) in mv and s1 == actor)
        R.check(f"{lg} D12c: sem_role differs from d1 only on the D12c rows (actor -> undergoer, basis derived), and on "
                "every one of them", other == 0 and len(moved) == want,
                f"{len(moved):,} moved (SPEC expects hbo 5,977, arc 0, grc 0), {other} other changes")
        nc = sum(1 for k, o, r, s in zip(N["clause"], N["ord"], N["role"], N["sem_role"])
                 if r in ("o", "o2") and s == actor and (k, o) not in mv)
        R.info(f"{lg} D12c: objects read as actor under another stem (not touched; SPEC: hbo 15)", nc)
        if V15:
            got = sum(1 for k, o, s, b in zip(N["clause"], N["ord"], N["sem_role"], N["sem_role_basis"])
                      if (k, o) in causer and (s, b) == (actor, "derived"))
            R.check(f"{lg} 1.5 D12c: every causer part (s, AA, causative stem, no D12 role) is actor, derived",
                    got == len(causer), f"{got:,} of {len(causer):,} (SPEC from f1: hbo 1,571, arc 0)")

    # ---- D7r -----------------------------------------------------------------------------------------------------
    R.section("pieces.who by reference (D7r)")
    cand = d7r_candidates(build, E)
    newents = {lg: set() for lg in LANGS}
    for lg in LANGS:
        P = tab(build, lg, "pieces", ["pid", "kind", "class", "who", "who_basis"])
        P1 = tab(d1, lg, "pieces", ["pid", "who", "who_basis"])
        bad = other = 0
        by = C.Counter()
        for pid, k, cl, w, b, w1, b1 in zip(P["pid"], P["kind"], P["class"], P["who"], P["who_basis"], P1["who"],
                                            P1["who_basis"]):
            want = (w1, b1)
            if not w1 and pid in cand and not (cl in NO_WHO[lg] and not (lg == "grc" and cl == "det")):
                want = (cand[pid][0], "reference")
                by[f"({cand[pid][1]}) {'suffix' if k == 'suffix' else cl}"] += 1
            bad += (w, b) != want
            other += bool(w1) and (w, b) != (w1, b1)
            if b == "reference":
                newents[lg].add(w)
        R.check(f"{lg} pieces.who, who_basis: d1's values, and D7r recomputed where d1 has none (no filled value "
                "changes)", bad == 0 and other == 0, f"{bad} differ, {other} filled values changed; filled by D7r "
                f"{sum(by.values()):,}: {dict(sorted(by.items()))}")
        sec = cats[lg].get("pieces", {}).get("who_basis", {})
        R.check(f"{lg} categories.toml pieces.who_basis: reference declared with its count",
                {v["code"]: v["count"] for v in sec.get("values", [])}.get("reference", 0) ==
                sum(1 for b in P["who_basis"] if b == "reference"))

    # ---- participants: D7n catch-all, new rows -------------------------------------------------------------------
    R.section("participants.tsv (D7n catch-all names; rows of D7r)")
    for lg in LANGS:
        rows = tsv(os.path.join(build, lg, "participants.tsv"))
        ca = [r for r in rows if r["ent"] in E.acai and Ents.catch_all(E.acai[r["ent"]])]
        R.check(f"{lg} participants: every catch-all participant has an empty name and name_basis",
                all(not r["name"] and not r["name_basis"] for r in ca), f"{len(ca)} catch-all participants")
        r1 = {r["ent"]: r for r in tsv(os.path.join(d1, lg, "participants.tsv"))}
        aw = {w for w in tab(build, lg, "added", ["who"])["who"] if w}
        new = {r["ent"] for r in rows} - set(r1)
        R.check(f"{lg} participants: the rows not in d1 are entities of added.who or of D7r",
                new <= aw | newents[lg], f"{len(new)} new rows; of D7r only {len(new - aw)}")
        keep = all(r["ent"] in {x["ent"] for x in rows} for r in r1.values())
        if V15:      # SPEC 1.5 13: the participants only added.who named go (checked by stage 35 against f1)
            gone = [e for e in r1 if e not in {x["ent"] for x in rows}]
            R.info(f"{lg} 1.5 participants of d1 not in this build (only added.who named them; stage 35 checks)", len(gone))
            keep = True
        same = sum(1 for r in rows if r["ent"] in r1 and any(r[c] != r1[r["ent"]][c] for c in
                                                             ("type", "sex", "ent_basis", "words_model")))
        nm = sum(1 for r in rows if r["ent"] in r1 and (r["name"], r["name_basis"]) != (r1[r["ent"]]["name"],
                                                                                       r1[r["ent"]]["name_basis"])
                 and not Ents.catch_all(E.acai[r["ent"]]))
        R.check(f"{lg} unchanged: every d1 participant kept; type, sex, ent_basis equal; name, name_basis equal but "
                "for the catch-all entities", keep and same == 0 and nm == 0, f"{same} type/sex/basis, {nm} names differ")
        R.info(f"{lg} participants whose words changed against d1 (D7r)",
               sum(1 for r in rows if r["ent"] in r1 and r["words"] != r1[r["ent"]]["words"]))

    # ---- D19 -----------------------------------------------------------------------------------------------------
    R.section("who_account.parquet (D19)")
    table = {}
    for corpus, gl in GROUPS:
        pre = "n" if corpus == "grc" else "o"
        np_ = {pre + r["head"]: r for r in tsv(os.path.join(D, "reference-status", "np.tsv"), "corpus", corpus)}
        ia_ = {pre + r["verb"]: r for r in tsv(os.path.join(D, "implicit-args", "args.tsv"), "corpus", corpus)
               if r["role"] == "A0" and r["in_verb"] == "1"}
        zero = _zero_subject_preds(build, gl)
        phead = set()
        rel = {}
        for lg in gl:
            N = tab(build, lg, "constituents", ["head", "role"])
            phead |= {h for h, r in zip(N["head"], N["role"]) if r == "p"}
            W = tab(build, lg, "words", ["t", "rel"])
            rel.update(zip(W["t"], W["rel"]))
        for lg in gl:
            P = tab(build, lg, "pieces", ["t", "n", "pid", "kind", "class", "who"])
            want = []
            for t, n, pid, k, cl, w in zip(P["t"], P["n"], P["pid"], P["kind"], P["class"], P["who"]):
                hk = {("stem", "noun"): "noun", ("stem", "pron"): "pronoun", ("suffix", "pron"): "suffix"}.get((k, cl))
                if hk is None and pid in zero:
                    hk = "verb_zero"
                if hk is None:
                    continue
                es = w.split()
                ref = ia_.get(pid) if hk == "verb_zero" else np_.get(pid)
                if [e for e in es if not Ents.catch_all(E.acai[e])]:
                    s, why = "participant", ""
                elif es:
                    s, why = "generic", ""
                elif t in phead:
                    s, why = "not_referring", ""
                elif ref is None:
                    s, why = "no_row", rel[t]
                elif entity_ref(ref["referent"]):
                    s = "entity_not_taken"
                    why = E.rows[ref["referent"]]["type"] if ref["referent"] in E.rows else ref["referent"].split(":")[0]
                elif ref["referent"].startswith("lemma:"):
                    s, why = "no_entity", ref.get("status", "") if hk != "verb_zero" else (
                        "_".join(x for x in "".join(ch if ch.isalnum() else " " for ch in ref["where"].lower()).split())
                        if V15 and ref.get("where") else "")
                else:
                    s, why = "unresolved", ""
                want.append((t, n, hk, s, why))
            A = tab(build, lg, "who_account")
            have = list(zip(A["t"], A["n"], A["head_kind"], A["state"], A["reason"]))
            R.check(f"{lg} who_account.parquet: the columns of SPEC 4.12", list(A) == ["t", "n", "head_kind", "state", "reason"])
            R.check(f"{lg} who_account: every referring head has exactly one row, and no other piece has one",
                    sorted({(x[0], x[1]) for x in have}) == sorted((x[0], x[1]) for x in want) and
                    len(have) == len({(x[0], x[1]) for x in have}), f"{len(have):,} rows, {len(want):,} heads")
            R.check(f"{lg} who_account: every row recomputed by D19 (head_kind, state, reason), in order (t, n)",
                    have == sorted(want), f"{sum(1 for a, b in zip(have, sorted(want)) if a != b)} differ")
            whoset = {(t, n) for t, n, w in zip(P["t"], P["n"], P["who"])
                      if [e for e in w.split() if not Ents.catch_all(E.acai[e])]}
            heads = {(x[0], x[1]) for x in want}
            R.check(f"{lg} who_account: participant rows equal the referring heads with a non-catch-all who",
                    {(x[0], x[1]) for x in have if x[3] == "participant"} == whoset & heads)
            R.check(f"{lg} who_account: head_kind and state are codes of SPEC 4.12", set(A["head_kind"]) <= set(KINDS)
                    and set(A["state"]) <= set(STATES))
            for col in ("head_kind", "state"):
                sec = cats[lg].get("who_account", {}).get(col, {})
                R.check(f"{lg} categories.toml who_account.{col}: every code declared with its count",
                        {v["code"]: v["count"] for v in sec.get("values", [])} == dict(C.Counter(A[col])))
            table[lg] = C.Counter((x[2], x[3]) for x in have)
            R.info(f"{lg} who_account reasons of entity_not_taken",
                   dict(C.Counter(x[4] for x in have if x[3] == "entity_not_taken").most_common()))
            R.info(f"{lg} who_account reasons of no_entity",
                   dict(C.Counter(f"{x[2]} {x[4] or '(empty)'}" for x in have if x[3] == "no_entity").most_common()))
    for lg in LANGS:
        R.info(f"{lg} who_account: state by head kind ({', '.join(STATES)})",
               "; ".join(f"{hk} " + " / ".join(f"{table[lg][(hk, s)]:,}" for s in STATES) for hk in KINDS))
    return table


if __name__ == "__main__":
    import sys
    sys.path.append(HERE)
    import validate_examples as VE
    build = os.path.join(HERE, "data", "source-examples", sys.argv[1] if len(sys.argv) > 1 else "e1")
    R = VE.Report()
    stage28(R, build)
    print(f"== {R.passes} PASS, {R.skips} SKIP, {R.fails} FAIL")
    sys.exit(1 if R.fails else 0)
