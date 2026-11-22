"""SPEC 1.3 (stage 28, e builds): the three mends and the account of who is meant.

- hook28(...): inside stage 16, after D9, D9m (examples_v13.hook16), D10 and D7, before participants:
  D12c (the caused party of a causative verb: `o`, `o2` read as actor -> undergoer), D16 (`marks.time_abs`, and in
  `marks_model` where it reads a model time), D7r (`who` by reference: reference-status rows of basis `ref`, and the
  `A0` `in_verb` row of implicit-args on the predicate of a clause with a zero subject), D19 (who_account rows).
- catch_all(acai): the 34 catch-all entities of SPEC 4.5 (D7n gives them no name).
- cat16(...): the categories.toml sections of stage 16 for clauses.time_abs and who_account.
"""
import collections as C
import csv
import json
import os

import pyarrow as pa

import examples_common as X

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "data")
NP = os.path.join(D, "reference-status", "np.tsv")
IA = os.path.join(D, "implicit-args", "args.tsv")
CAUS = {"hbo": {"hiphil"}, "arc": {"haphel", "aphel", "shaphel"}, "grc": set()}
NO_WHO = {"hbo": {"cj", "prep", "art"}, "arc": {"cj", "prep", "art"}, "grc": {"conj", "prep", "det"}}
ABS = ("past", "present", "future", "timeless", "irrealis")
REL = ("anterior", "simultaneous", "posterior")
STATES = ("participant", "generic", "not_referring", "entity_not_taken", "no_entity", "unresolved", "no_row")
HEAD_KINDS = ("noun", "pronoun", "suffix", "verb_zero")
WA_COLS = [("t", pa.int64()), ("n", pa.int64()), ("head_kind", pa.string()), ("state", pa.string()),
           ("reason", pa.string())]


def read_tsv(path, col=None, val=None):
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))
    return rows if col is None else [r for r in rows if r[col] == val]


def catch_all(acai):
    rest = acai.split(":", 1)[1] if ":" in acai else acai
    return rest.startswith("Generic") or rest in ("Messenger", "Messengers")


def is_entity_id(ref):
    # reference-status writes an unresolved reference `unresolved` or `unresolved:<word>`
    return bool(ref) and not ref.startswith("unresolved") and not ref.startswith("lemma:")


def d16(own):
    """own: clause -> (time code or None, model flag, parent). -> clause -> (time_abs code or None, reason, model)."""
    memo = {}

    def resolve(k):
        if k in memo:
            return memo[k]
        code, model, parent = own[k]
        if code in ABS:
            memo[k] = (code, "", model)
            return memo[k]
        p = parent
        while p and own[p][0] is None:
            p = own[p][2]
        if not p:
            memo[k] = (None, "no ancestor", model)
            return memo[k]
        pv, _pr, pm = resolve(p)
        m = model or pm
        if pv is None:
            out = (None, "ancestor unresolved", m)
        elif code == "simultaneous":
            out = (None, "simultaneous under irrealis", m) if pv == "irrealis" else (pv, "", m)
        elif code == "anterior":
            out = ("past", "", m) if pv in ("past", "present") else (None, f"anterior under {pv}", m)
        elif code == "posterior":
            out = ("future", "", m) if pv in ("present", "future") else (None, f"posterior under {pv}", m)
        else:
            raise SystemExit(f"stage 28: time code {code!r} not named by D16")
        memo[k] = out
        return out
    return {k: resolve(k) for k, v in own.items() if v[0] is not None}


def hook28(gl, greek, T, V, E, terms, whos, rows, cnt, ex, counts):
    """Changes T (clauses marks, marks_model; constituents sem_role, sem_role_basis) and whos in place; returns
    {lang: who_account rows}."""
    tag = "grc" if greek else "tan"
    corpus = "grc" if greek else "hbo"
    pre = "n" if greek else "o"
    crow = {k: (lg, j) for lg in gl for j, k in enumerate(T[lg]["K"]["clause"])}
    stem_of = {}                        # word t -> (lg, piece index) of its stem piece
    for lg in gl:
        P = T[lg]["P"]
        for i, (t, k) in enumerate(zip(P["t"], P["kind"])):
            if k == "stem":
                stem_of[t] = (lg, i)

    # ---- D12c ----------------------------------------------------------------------------------------------------
    for lg in gl:
        if greek:
            break
        N = T[lg]["N"]
        actor = terms[lg][("sem_role", "actor")]
        und = terms[lg][("sem_role", "undergoer")]
        for j, (k, o, role, sr, sb, fr) in enumerate(zip(N["clause"], N["ord"], N["role"], N["sem_role"],
                                                         N["sem_role_basis"], N["frame_role"])):
            if role not in ("o", "o2") or sr != actor:
                continue
            cl, cj = crow[k]
            pred = T[cl]["K"]["pred"][cj]
            sp = stem_of.get(pred)
            m = json.loads(T[sp[0]]["P"]["marks"][sp[1]]) if sp else {}
            stem = m.get("stem", "")
            if sp and stem in CAUS[sp[0]]:
                N["sem_role"][j] = und
                N["sem_role_basis"][j] = "derived"
                V["sem"][(k, o)] = und
                V["semb"][(k, o)] = "derived"
                V["sem_use"][lg]["actor"] -= 1
                V["sem_use"][lg]["undergoer"] += 1
                V["semb_use"][lg][(sb, "D12c moved")] -= 1
                V["semb_use"][lg][("derived", "D12c")] += 1
                cnt[f"{lg} 1.3 D12c parts moved actor -> undergoer"] += 1
                counts.setdefault(f"{lg} 1.3 D12c moved by stem, verb form, frame label", C.Counter())[
                    f"{stem} {m.get('type', '')} {fr or '(none)'}"] += 1
                ex[f"{lg} D12c parts moved actor -> undergoer"].append(f"{k} {o} {role} {stem}")
            else:
                cnt[f"{lg} 1.3 D12c objects read as actor under a non-causative stem (not touched)"] += 1
                ex[f"{lg} D12c objects read as actor, not touched (stem)"].append(f"{k} {o} {role} {stem or '(none)'}")
        if f"{lg} 1.3 D12c moved by stem, verb form, frame label" in counts:
            counts[f"{lg} 1.3 D12c moved by stem, verb form, frame label"] = dict(sorted(
                counts[f"{lg} 1.3 D12c moved by stem, verb form, frame label"].items()))

    # ---- D16 -----------------------------------------------------------------------------------------------------
    own = {}
    code_of = {lg: {terms[lg][k]: k[1] for k in terms[lg] if k[0] == "time"} for lg in gl}
    for lg in gl:
        K = T[lg]["K"]
        for k, mk, mm, par in zip(K["clause"], K["marks"], K["marks_model"], K["parent"]):
            m = json.loads(mk)
            model = False
            v = m.get("time")
            if v is None and mm:
                v = json.loads(mm).get("time")
                model = v is not None
            own[k] = (code_of[lg][v] if v is not None else None, model, par or "")
    res = d16(own)
    if getattr(X, "V15", False) and greek:     # SPEC 1.5 D9, D16 (A6): a verbless clause takes its ancestor's time_abs
        for k in sorted(V["verbless"]):
            p = own[k][2]
            while p and own[p][0] is None:
                p = own[p][2]
            if not p:
                res[k] = (None, "verbless, no ancestor", False)
            else:
                pv, _pw, pm = res.get(p, (None, "", own[p][1]))
                res[k] = (pv, "" if pv is not None else "verbless, ancestor unresolved", pm)
            cnt[f"{crow[k][0]} 1.5 D16 verbless clauses: time_abs {'from an ancestor' if res[k][0] else res[k][1]}"] += 1
    for k, (v, why, model) in res.items():
        lg, j = crow[k]
        K = T[lg]["K"]
        rel = own[k][0] in REL
        if v is None:
            cnt[f"{lg} 1.3 D16 time_abs empty: {why}"] += 1
            continue
        term = terms[lg][("time", v)]
        if model:
            mm = json.loads(K["marks_model"][j]) if K["marks_model"][j] else {}
            mm["time_abs"] = term
            K["marks_model"][j] = X.jdump(mm)
            cnt[f"{lg} 1.3 D16 time_abs in marks_model (reads a model time)"] += 1
            if not own[k][1]:
                cnt[f"{lg} 1.3 D16 time_abs in marks_model on a clause whose own time is strict"] += 1
        else:
            m = json.loads(K["marks"][j])
            m["time_abs"] = term
            K["marks"][j] = X.jdump(m)
            cnt[f"{lg} 1.3 D16 time_abs in marks"] += 1
        if rel:
            cnt[f"{lg} 1.3 D16 relative times resolved"] += 1
            counts.setdefault(f"{lg} 1.3 D16 relative -> absolute", C.Counter())[f"{own[k][0]} -> {v}"] += 1
    for k, (c, _m, _p) in own.items():
        if c in REL:
            cnt[f"{crow[k][0]} 1.3 D16 relative times"] += 1
    for lg in gl:
        key = f"{lg} 1.3 D16 relative -> absolute"
        if key in counts:
            counts[key] = dict(sorted(counts[key].items()))

    # ---- D7r -----------------------------------------------------------------------------------------------------
    np_of = {pre + r["head"]: r for r in read_tsv(NP, "corpus", corpus)}
    ia_of = {pre + r["verb"]: r for r in read_tsv(IA, "corpus", corpus) if r["role"] == "A0" and r["in_verb"] == "1"}
    zero_pred = {}                      # stem piece pid of the predicate of a clause with pred_kind v, subject zero
    for lg in gl:
        K = T[lg]["K"]
        for k, pred, pk, mk in zip(K["clause"], K["pred"], K["pred_kind"], K["marks"]):
            if pk == "v" and pred and json.loads(mk).get("subject_form") == "zero":
                sp = stem_of.get(pred)
                if sp:
                    zero_pred[T[sp[0]]["P"]["pid"][sp[1]]] = k
    for lg in gl:
        P = T[lg]["P"]
        who, basis = whos[lg]
        for i, (pid, cl, kind) in enumerate(zip(P["pid"], P["class"], P["kind"])):
            if who[i]:
                continue
            got, step = None, None
            r = np_of.get(pid)
            if r is not None and r["basis"] == "ref" and is_entity_id(r["referent"]):
                got = E.ent(r["referent"], f"{lg} 1.3 D7r (a) referent")
                step = "a"
            if got is None and pid in zero_pred:
                r2 = ia_of.get(pid)
                if r2 is not None and is_entity_id(r2["referent"]):
                    got = E.ent(r2["referent"], f"{lg} 1.3 D7r (b) referent")
                    step = "b"
                    if got and any(got in rows.get((pid, kd), ()) for kd in ("explicit", "pronominal", "subject")):
                        cnt[f"{lg} 1.3 D7r (b) referents that ACAI's entity_words also gives the verb piece"] += 1
            if got is None:
                continue
            if cl in NO_WHO[lg] and not (lg == "grc" and cl == "det"):
                cnt[f"{lg} 1.3 D7r left empty: class {cl}"] += 1
                ex[f"{lg} D7r left empty on a function-word piece"].append(pid)
                continue
            who[i], basis[i] = got, "reference"
            hk = ("suffix" if kind == "suffix" else "verb" if step == "b" else cl)
            cnt[f"{lg} 1.3 D7r pieces filled, step ({step}), {hk}"] += 1
            ex[f"{lg} D7r pieces filled (pid step)"].append(f"{pid} {step}")

    # ---- D19 -----------------------------------------------------------------------------------------------------
    p_heads = set()
    for lg in gl:
        N = T[lg]["N"]
        p_heads |= {h for h, role in zip(N["head"], N["role"]) if role == "p"}
    rel_of = {t: r for lg in gl for t, r in zip(T[lg]["W"]["t"], T[lg]["W"]["rel"])}
    out = {}
    for lg in gl:
        P = T[lg]["P"]
        who = whos[lg][0]
        acc = []
        for i, (pid, t, n, kind, cl) in enumerate(zip(P["pid"], P["t"], P["n"], P["kind"], P["class"])):
            hk = None
            if kind == "stem" and cl == "noun":
                hk = "noun"
            elif kind == "stem" and cl == "pron":
                hk = "pronoun"
            elif kind == "suffix" and cl == "pron":
                hk = "suffix"
            if pid in zero_pred:
                if hk is not None:
                    cnt[f"{lg} 1.3 D19 heads both {hk} and verb_zero (taken as {hk})"] += 1
                else:
                    hk = "verb_zero"
            if hk is None:
                continue
            es = who[i].split()
            r = (ia_of if hk == "verb_zero" else np_of).get(pid)
            reason = ""
            if es and any(not catch_all(E.acai_of[e]) for e in es):
                st = "participant"
            elif es:
                st = "generic"
            elif t in p_heads:
                st = "not_referring"
            elif r is None:
                st, reason = "no_row", rel_of.get(t, "")
            elif is_entity_id(r["referent"]):
                er = E.rows.get(r["referent"])
                st, reason = "entity_not_taken", (er["type"] if er else r["referent"].split(":", 1)[0])
                if er is None:
                    cnt[f"{lg} 1.3 D19 entity_not_taken: id not in entities.tsv (reason from the id's type)"] += 1
            elif r["referent"].startswith("lemma:"):
                st, reason = "no_entity", (r.get("status", "") if hk != "verb_zero" else
                                           X.c0(r["where"]) if getattr(X, "V15", False) and r["where"] else "")
            else:
                st = "unresolved"
            acc.append((t, n, hk, st, reason))
            counts.setdefault(f"{lg} 1.3 D19 who_account by head kind and state", C.Counter())[f"{hk} {st}"] += 1
            if st in ("entity_not_taken", "no_entity"):
                counts.setdefault(f"{lg} 1.3 D19 reasons of {st}", C.Counter())[f"{hk} {reason or '(empty)'}"] += 1
        out[lg] = sorted(acc)
        cnt[f"{lg} 1.3 who_account rows"] = len(acc)
        for key in list(counts):
            if key.startswith(f"{lg} 1.3 D19"):
                counts[key] = dict(sorted(counts[key].items()))
    cnt[f"{tag} 1.3 D19 zero-subject predicates (pred_kind v)"] = len(zero_pred)
    return out


def write_account(d, rows):
    cols = [c for c, _t in WA_COLS]
    X.write_parquet(os.path.join(d, "who_account.parquet"), {c: [r[i] for r in rows] for i, c in enumerate(cols)},
                    pa.schema(WA_COLS))


def cat16(lang, K, wa, terms_lg):
    """The categories.toml sections of stage 16 for clauses.time_abs (terms of category time) and who_account."""
    code_of = {terms_lg[k]: k[1] for k in terms_lg if k[0] == "time"}
    use = C.Counter(json.loads(m).get("time_abs") for m in K["marks"])
    use.pop(None, None)
    L = ["[clauses.time_abs]", 'column = "marks"', 'basis = "derived"',
         'source = "rule D16: the clause\'s time, a relative one read through the nearest ancestor clause with a time"',
         'form_or_reading = "reading"', 'meaning = "terms.tsv"', 'terms_of = "time"', "values = ["]
    for t, n in sorted(use.items(), key=lambda kv: code_of[kv[0]]):
        L.append(f"  {{ code = {X.toml_str(code_of[t])}, value = {X.toml_str(code_of[t])}, rule = \"D16\", "
                 f"term = {X.toml_str(t)}, count = {n} }},")
    L += ["]", ""]
    desc = {"noun": "a stem piece of class noun", "pronoun": "a stem piece of class pron",
            "suffix": "a suffix piece of class pron",
            "verb_zero": "the stem piece of the predicate of a clause with pred_kind v and subject_form zero"}
    hk = C.Counter(r[2] for r in wa)
    L += ["[who_account.head_kind]", 'column = "head_kind"', 'basis = "derived"', 'source = "rule D19"', "values = ["]
    L += [f"  {{ code = {X.toml_str(c)}, value = {X.toml_str(desc[c])}, rule = \"D19\", count = {hk[c]} }},"
          for c in HEAD_KINDS if hk[c]]
    L += ["]", ""]
    sdesc = {"participant": "who holds an entity that is not a catch-all", "generic": "who holds only catch-all entities",
             "not_referring": "the head's word heads a constituent of role p",
             "entity_not_taken": "the reference row names an ACAI entity D7 and D7r do not take",
             "no_entity": "the reference row's referent is a lemma, no entity",
             "unresolved": "the reference row says unresolved or names no referent",
             "no_row": "no reference row has this head"}
    sc = C.Counter(r[3] for r in wa)
    L += ["[who_account.state]", 'column = "state"', 'basis = "derived"', 'source = "rule D19 (the first that holds)"',
          "values = ["]
    L += [f"  {{ code = {X.toml_str(c)}, value = {X.toml_str(sdesc[c])}, rule = \"D19\", count = {sc[c]} }},"
          for c in STATES if sc[c]]
    L += ["]", ""]
    rc = C.Counter((r[3], r[4]) for r in wa if r[4])
    L += ["[who_account.reason]", 'column = "reason"', 'basis = "derived"',
          'source = "rule D19: entity_not_taken: the ACAI type of the entity; no_entity: the reference-status status; '
          'no_row: the word\'s rel (a label of words.rel)"',
          'pattern = "an ACAI type, a reference-status status code, or a rel label"', f"count = {sum(rc.values())}",
          "values = ["]
    L += [f"  {{ state = {X.toml_str(s)}, code = {X.toml_str(c)}, count = {n} }}," for (s, c), n in sorted(rc.items())
          if s != "no_row"]
    L += ["]", ""]
    return "\n".join(L)
