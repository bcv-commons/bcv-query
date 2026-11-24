"""SPEC 1.5 (g builds, stage 35): the rules of version 1.5 that stage 16 applies after the 1.3 hooks.

build_examples.py --build g1 --stage 35 sets examples_common.V15 and runs the builders of 1.4 (stage 28, 29, then
examples_v14). The 1.5 rules sit in the builder that writes the column: D9 (connective edge, Greek mood, Greek verbless
time) in examples_values11, D17 in examples_v13.hook16, D16 and D19 in examples_v13m.hook28, D23 and D25 to D28 in
examples_v14, and here (called from examples_people11 after hook28):
- D12c (1.5): the causer (`s` part with frame label AA under a causative stem, no D12 role) takes `actor`;
- D18 (1.5): the drops, kind and form, step W (`who`, `who_reason`).
"""
import collections as C
import json

import examples_common as X

CAUS = {"hiphil", "haphel", "aphel", "shaphel"}
IMPERS = {"γίνομαι", "εἰμί", "הָיָה", "הֲוָה"}


def _nfc(s):
    import unicodedata
    return unicodedata.normalize("NFC", s or "")


def hook35(gl, greek, T, V, terms, whos, added, lemma_of, cnt, ex, counts):
    """Changes T (constituents sem_role, sem_role_basis) and the added rows (per lang) in place; returns {lang: rows}."""
    IMP = {_nfc(x) for x in IMPERS}
    stem = {}                                   # word t -> (lg, piece index)
    who_of = {}                                 # (t, n) -> strict who (set)
    for lg in gl:
        P = T[lg]["P"]
        w = whos[lg][0]
        for i, (t, n, k) in enumerate(zip(P["t"], P["n"], P["kind"])):
            if k == "stem":
                stem[t] = (lg, i)
            who_of[(t, n)] = set(w[i].split())
    smarks = {t: json.loads(T[lg]["P"]["marks"][i]) for t, (lg, i) in stem.items()}
    crow = {k: (lg, j) for lg in gl for j, k in enumerate(T[lg]["K"]["clause"])}
    deps = C.defaultdict(list)
    for lg in gl:
        for t, h in zip(T[lg]["W"]["t"], T[lg]["W"]["head"]):
            deps[h].append(t)

    # ---- D12c (1.5): the causer ------------------------------------------------------------------------------------
    for lg in gl:
        if greek:
            break
        N = T[lg]["N"]
        actor = terms[lg][("sem_role", "actor")]
        for j, (k, o, role, sr, fr) in enumerate(zip(N["clause"], N["ord"], N["role"], N["sem_role"], N["frame_role"])):
            if role != "s" or "AA" not in (fr or "").split():
                continue
            cl, cj = crow[k]
            pred = T[cl]["K"]["pred"][cj]
            if not pred or smarks.get(pred, {}).get("stem") not in CAUS:
                continue
            if sr:
                cnt[f"{lg} 1.5 D12c causer parts that keep their D12 role"] += 1
                continue
            N["sem_role"][j], N["sem_role_basis"][j] = actor, "derived"
            V["sem"][(k, o)], V["semb"][(k, o)] = actor, "derived"
            V["sem_use"][lg]["actor"] += 1
            V["semb_use"][lg][("derived", "D12c causer")] += 1
            cnt[f"{lg} 1.5 D12c causer parts given actor"] += 1
            ex[f"{lg} 1.5 D12c causer parts given actor"].append(f"{k} {o}")

    # ---- D18 (1.5) ----------------------------------------------------------------------------------------------
    out = {}
    for lg in gl:
        tl = terms[lg]
        code_of = {tl[("added_kind", c)]: c for c in ("in_verb", "elsewhere", "unsaid", "possessor")}
        N = T[lg]["N"]
        fr = C.defaultdict(set)
        for k, f in zip(N["clause"], N["frame_role"]):
            fr[k].update((f or "").split())
        kept = []
        for a in added[lg]:
            v = a["verb"]
            m = smarks.get(v, {})
            sp = stem.get(v)
            lem = _nfc(lemma_of.get(T[sp[0]]["P"]["lexeme"][sp[1]], "")) if sp else ""
            place = f"{a['clause']} {v} {a['role']}"
            if a["role"] != "poss" and a["role"] in fr[a["clause"]]:
                cnt[f"{lg} 1.5 D18 drop (a): the role is a frame label of a part of the clause"] += 1
                ex[f"{lg} 1.5 D18 drop (a)"].append(place)
                continue
            if greek and m.get("mood") == "ptcp" and any(
                    stem.get(d) and T[stem[d][0]]["P"]["class"][stem[d][1]] == "det" for d in deps[v]):
                own = "A1" if m.get("voice") == "pass" else "A0"
                if a["role"] == own:
                    cnt[f"{lg} 1.5 D18 drop (b): an articular participle is its own {own}"] += 1
                    ex[f"{lg} 1.5 D18 drop (b)"].append(place)
                    continue
            if (a["role"] == "A0" and code_of[a["kind"]] == "unsaid" and lem in IMP and
                    (("person" not in m) or (m.get("person") == "3" and m.get("number") == "sg"))):
                cnt[f"{lg} 1.5 D18 drop (c): unsaid A0 of an impersonal verb, {lem}"] += 1
                ex[f"{lg} 1.5 D18 drop (c)"].append(place)
                continue
            kept.append(a)
        # (d) one row per key: the antecedent nearest the verb (tie: the earlier); no antecedent last
        by_key = C.defaultdict(list)
        for a in kept:
            by_key[(a["clause"], a["verb"], a["role"])].append(a)

        def dist(a):
            if not a["antecedent"]:
                return (1, 0, 0)
            t, n = map(int, a["antecedent"].split("."))
            return (0, abs(t - a["verb"]), t, n)
        rows = []
        for key in sorted(by_key, key=lambda k: (k[1], k[2], k[0])):
            rs = by_key[key]
            if len(rs) > 1:
                rs = sorted(rs, key=dist)
                cnt[f"{lg} 1.5 D18 drop (d): a second row on one key"] += len(rs) - 1
                ex[f"{lg} 1.5 D18 drop (d)"].extend(f"{key[0]} {key[1]} {key[2]} {x['antecedent']}" for x in rs[1:])
            rows.append(rs[0])
        # step 2: kind and form; step W: who
        v16 = getattr(X, "V16", False)
        v18 = getattr(X, "V18", False)      # SPEC 1.8: M1 (passive subjects), M2 (the larger set's members)
        if v18:
            import examples_v18 as V18M
        aa_row = {(a["clause"], a["verb"]) for a in rows if a["role"] == "AA"}     # SPEC 1.6 4.11: the frame's AA
        a0aa_verb = {a["verb"] for a in rows if a["role"] in ("A0", "AA")}         # SPEC 1.8 4.11 (M1)
        for a in rows:
            m = smarks.get(a["verb"], {})
            caus = m.get("stem") in CAUS
            if v16:     # SPEC 1.6 4.11 (R1): under a causative stem AA only where the frame has an AA, else A0
                has_aa = (a["clause"], a["verb"]) in aa_row or "AA" in fr[a["clause"]]
                subj = a["role"] == (("AA" if has_aa else "A0") if caus else "A0")
            else:
                subj = (a["role"] == "AA" and caus) or (a["role"] == "A0" and not caus)
            if (v18 and not subj and a["role"] == "A1" and m.get("person") and V18M.is_passive(lg, m)
                    and a["verb"] not in a0aa_verb and not ({"A0", "AA"} & fr[a["clause"]])):
                subj = True     # SPEC 1.8 4.11 (M1): the A1 row of a finite passive verb with no A0/AA is its subject
                k18 = (m.get("voice") if lg == "grc" else m.get("stem")) or ""
                cnt[f"{lg} 1.8 M1 passive subject rows, {k18}"] += 1
                ex[f"{lg} 1.8 M1 passive subject rows (clause verb role)"].append(f"{a['clause']} {a['verb']} A1 {k18}")
            old = code_of[a["kind"]]
            if a["role"] == "poss":
                kind, form = old, "none"
            elif subj and "person" in m:
                kind, form = "in_verb", "ending"
            elif v16:   # SPEC 1.6 D18 step 2 (ii) (R5): every other row's kind from `where`
                kind, form = ("unsaid" if a["where"] == "unexpressed" else "elsewhere"), "none"
            elif a["role"] == "A0" and caus:
                kind, form = ("unsaid" if a["where"] == "unexpressed" else "elsewhere"), "none"
            else:
                kind, form = old, "none"
            if v16 and form == "ending":     # SPEC 1.6 D18 step 2 (i) (R2): the ending's person, number, gender
                for f in ("person", "number", "gender"):
                    mine = m.get(f) or ""
                    if a[f] != mine:
                        cnt[f"{lg} 1.6 D18 ending rows whose dataset {f} " + ("is empty" if not a[f] else "differs")] += 1
                    a[f] = mine
                cnt[f"{lg} 1.6 D18 ending rows"] += 1
            if kind != old:
                cnt[f"{lg} 1.5 D18 kind {old} -> {kind}, role {a['role']}"] += 1
            a["kind"], a["form"] = tl[("added_kind", kind)], form
            vs = set()
            if subj and a["verb"] in stem:
                sl, si = stem[a["verb"]]
                vs = who_of[(a["verb"], T[sl]["P"]["n"][si])]
            ns = set()
            if a["antecedent"]:
                t, n = map(int, a["antecedent"].split("."))
                ns = who_of.get((t, n), set())
            if a["role"] == "poss":
                who, why = "", "guess"
            elif vs and ns and v16:     # SPEC 1.6 D18 step W: agreement on a set
                if vs <= ns or ns <= vs:
                    small, large = (vs, ns) if vs <= ns else (ns, vs)
                    if v18 and m.get("number") != "sg" and large != small:
                        # SPEC 1.8 D18 step W (M2): the larger set adds only types of the smaller, or person, group
                        large, out18 = V18M.larger_set(small, large)
                        for e in sorted(out18):
                            cnt[f"{lg} 1.8 M2 entities left out, type {V18M.etype(e)}"] += 1
                            ex[f"{lg} 1.8 M2 entities left out (clause verb role entity)"].append(
                                f"{a['clause']} {a['verb']} {a['role']} {e}")
                        if out18:
                            cnt[f"{lg} 1.8 M2 rows that lose members"] += 1
                    who = " ".join(sorted(small if m.get("number") == "sg" else large))
                    why = "verb_and_antecedent"
                    if vs != ns:
                        cnt[f"{lg} 1.6 D18 step W " + ("N inside V" if ns < vs else "V inside N") + ", verb number "
                            + ("sg" if m.get("number") == "sg" else m.get("number") or "none")] += 1
                elif vs & ns:
                    who, why = " ".join(sorted(vs & ns)), "verb_and_antecedent"
                    cnt[f"{lg} 1.6 D18 step W partial overlap"] += 1
                else:
                    who, why = "", "disagree"
            elif vs and ns:
                i = vs & ns
                who, why = (" ".join(sorted(i)), "verb_and_antecedent") if i else ("", "disagree")
            elif vs:
                who, why = " ".join(sorted(vs)), "verb"
            elif ns:
                who, why = " ".join(sorted(ns)), "antecedent"
            else:
                who, why = "", ("no_antecedent" if not a["antecedent"] else "antecedent_no_participant")
            a["who"], a["who_reason"] = who, why
            cnt[f"{lg} 1.5 D18 who_reason {why}"] += 1
        out[lg] = rows
        cnt[f"{lg} 1.5 added rows"] = len(rows)
    return out
