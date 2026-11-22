"""SPEC 1.5 (g builds): D23 (H0, H1, H2, K6) and D25 to D26 of 1.5 (L1 to L11), called by examples_v14 when
examples_common.V15 is set. Every rule is the text of SPEC.md 6, "D23 in 1.5" and "D25 and D26 in 1.5"."""
import collections as C
import json
import os
import re
import unicodedata as U

import pyarrow as pa
import pyarrow.parquet as pq

FUNC_CLASSES = ("det", "pron", "conj", "prep", "ptcl")
UNDER = set()          # the strict members joined under the floor (D25 1.5 step 2), for SAMPLE.md (D28)
H_SHARE = 0.1
UBS_GATE = 3


def cons(s):
    """The consonants of a text: the letters U+05D0-U+05EA, nothing else."""
    return "".join(ch for ch in U.normalize("NFD", s or "") if "א" <= ch <= "ת")


def tanakh_forms(outdir):
    """consonantal form -> lexeme -> Tanakh stem pieces (hbo and arc)."""
    f = C.defaultdict(C.Counter)
    for lang in ("hbo", "arc"):
        for r in pq.read_table(os.path.join(outdir, lang, "pieces.parquet"), columns=["text", "lexeme", "kind"]).to_pylist():
            if r["kind"] == "stem":
                f[cons(r["text"])][r["lexeme"]] += 1
    return f


def keys15(outdir, parts, cnt, ex):
    """D23 in 1.5: unpointed homographs in heb_mod (H0, H1, H2), then K6 in both editions. Changes parts in place."""
    forms = tanakh_forms(outdir)
    links = C.defaultdict(set)              # heb_mod s -> Greek t (strict)
    scg_of_t = C.defaultdict(set)           # Greek t -> heb_scg s (strict)
    for r in pq.read_table(os.path.join(outdir, "grc", "links.parquet"), columns=["t", "other", "s", "basis"]).to_pylist():
        if r["basis"] != "linked":
            continue
        if r["other"] == "heb_mod":
            links[r["s"]].add(r["t"])
        elif r["other"] == "heb_scg":
            scg_of_t[r["t"]].add(r["s"])
    scg_by_s = C.defaultdict(list)
    for r in parts["heb_scg"]:
        scg_by_s[r["s"]].append(r["lexeme"])
    c = C.Counter()
    moves = C.Counter()
    for r in parts["heb_mod"]:
        if r["basis"] != "derived" or not r["lexeme"].startswith("lex:"):
            continue
        lx = forms.get(cons(r["text"]))
        if not lx or len(lx) < 2 or r["lexeme"] not in lx:
            continue
        tot = sum(lx.values())
        second = sorted(lx.values(), reverse=True)[1]
        if second < H_SHARE * tot:
            c["homograph forms under the 0.1 bound (not exposed)"] += 1
            continue
        c["exposed"] += 1
        found = {k for t in links.get(r["s"], ()) for s2 in scg_of_t.get(t, ()) for k in scg_by_s.get(s2, ()) if k in lx}
        if len(found) == 1:
            k = found.pop()
            if k == r["lexeme"]:
                r["key_rule"] = "H1"
            else:
                moves[(r["lexeme"], k)] += 1
                ex["heb_mod D23 H2 parts (s p old new)"].append(f"{r['s']} {r['p']} {r['lexeme']} {k}")
                r["lexeme"], r["key_rule"] = k, "H2"
        else:
            r["key_rule"], r["basis"] = "H0", "model"
            c["H0: Salkinson's parts give " + ("none" if not found else "two or more") + " of the form's lexemes"] += 1
        c[r["key_rule"]] += 1
    cnt["D23 1.5 heb_mod homographs"] = dict(sorted(c.items()))
    cnt["D23 1.5 heb_mod H2 moves (top 25)"] = {f"{a} -> {b}": n for (a, b), n in
                                                 sorted(moves.items(), key=lambda x: (-x[1], x[0]))[:25]}
    for ed in ("heb_mod", "heb_scg"):
        c6 = C.Counter()
        for r in parts[ed]:
            if r["key_rule"] not in ("K0", "K5"):
                continue
            lx = forms.get(cons(r["text"]))
            if lx and len(lx) == 1:
                c6[f"K6 from {r['key_rule']}, basis was {r['basis']}"] += 1
                r["lexeme"], r["key_rule"], r["basis"] = next(iter(lx)), "K6", "model"
        cnt[f"D23 1.5 {ed} K6"] = dict(sorted(c6.items()))


def function_numbers(outdir, V):
    """D25 1.5 step 1: Greek numbers whose commonest MACULA Greek class (by count; tie: the smaller code) is a function
    class."""
    g = C.defaultdict(C.Counter)
    for r in V.tsv(os.path.join(outdir, "grc", "lexemes.tsv")):
        for s in (r["strong"] or "").split():
            if re.fullmatch(r"[0-9]+", s):
                g[V.digits(s)][r["class"]] += int(r["count"])
    return {n for n, c in g.items() if sorted(c.items(), key=lambda x: (-x[1], x[0]))[0][0] in FUNC_CLASSES}


def list_evidence(outdir, V, lex, cnt, ex):
    """(Aramaic lexeme, Hebrew key) -> evidence -> list rows (as D24a resolves the Hebrew side)."""
    A = {r["pid"]: r["lexeme"] for r in pq.read_table(os.path.join(outdir, "arc", "pieces.parquet"),
                                                     columns=["pid", "lexeme"]).to_pylist()}
    exact, dg = V.resolve_equiv(lex, C.Counter(), C.defaultdict(list))
    ev = C.defaultdict(C.Counter)
    for r in pq.read_table(V.EQUIV).to_pylist():
        ax = A.get("o" + r["key"])
        if not ax or not (r["hebrew_strong"] and r["hebrew_lemma"]):
            continue
        k = (V.nfc(r["hebrew_lemma"]), r["hebrew_strong"].lstrip("0"))
        hx = exact[k][0] if len(exact.get(k, [])) == 1 else (
            dg[k][0] if not exact.get(k) and len(dg.get(k, [])) == 1 else None)
        if hx:
            ev[(ax, hx)][r["evidence"]] += 1
    return ev


def make_groups15(V, prof, elig, lex, sizes, picks, ev, dom, prefix, cnt_key, cnt, pairs=None):
    """D25 and D26 of 1.5 (steps 2 to 4). -> groups, member_of, anchors, weak (as examples_v14.make_groups).
    With `pairs` (SPEC 1.6, examples_common.V16): step 2b between step 2 and D26; its record goes to STEP2B[prefix]."""
    def size(k):
        return V.size_of(lex, sizes, k)

    def head(mem):
        heb = [m for m in mem if lex[m]["lang"] == "hbo"]
        return sorted(heb or mem, key=lambda k: (-size(k), k))[0]
    anchors = {}
    for lx in sorted(elig):
        g, share = V.anchor_of(prof.get(lx, C.Counter()))
        if g is not None:
            anchors[lx] = (g, share)
    cand = C.defaultdict(list)
    for lx, (g, _) in anchors.items():
        cand[(g, lex[lx]["class"])].append(lx)
    groups, member_of, weak, under = {}, {}, [], {}
    gate, allg_of = {}, {}
    c = C.Counter()
    for (g, cl), ls in sorted(cand.items()):
        if len(ls) < 2:
            continue
        allg = sum(prof[lx][g] for lx in ls)
        pend = []
        strong = [lx for lx in ls if prof[lx][g] >= V.MIN_MEMBER * allg]
        rest = [lx for lx in ls if lx not in strong]
        rare = []
        if strong:
            h0 = head(strong)
            for lx in rest:
                d = V.ubs_depth(dom.get(lx), dom.get(h0))
                ok = lex[lx]["lang"] == "arc" or (d or 0) >= UBS_GATE
                c["candidates under the floor"] += 1
                c[f"candidates under the floor, {'joined' if ok else 'not joined'}"] += 1
                if ok:
                    rare.append(lx)
                else:
                    pend.append(lx)
        mem = strong + rare
        if len(mem) >= 2:
            allg_of[f"{prefix}:{head(mem)}"] = (g, allg)
            gate.update({lx: (V.gkey(g), cl) for lx in pend})     # kept out by the UBS gate beside a group (D27 1.6)
            weak += [lx for lx in ls if lx not in mem]
            key = f"{prefix}:{head(mem)}"
            groups[key] = {"anchor": V.gkey(g), "members": {
                lx: ("anchor", prof[lx][g], sum(prof[lx].values()) - prof[lx][g]) for lx in mem}}
            for lx in mem:
                member_of[lx] = key
            for lx in rare:
                under[lx] = key
        else:
            weak += [lx for lx in ls if lx not in mem]
    if pairs is not None:     # SPEC 1.6 D25 step 2b
        step2b(V, groups, member_of, under, allg_of, gate, lex, dom, prof, pairs, prefix, c)
        # a group left with its head alone stays only for D26 to join an Aramaic word to it; else it dissolves below
    joins = C.defaultdict(list)
    for ax in sorted(picks):
        if ax not in elig or ax in member_of or lex[ax]["lang"] != "arc":
            continue
        pieces = int(lex[ax]["count"])
        per = C.Counter(hx for hx, b, _, _ in picks[ax] if hx and b == "derived" and hx in elig)
        top = [hx for hx, n in per.items() if n * 2 >= pieces]
        if len(top) > 1:
            c["D26 arc lexemes with two Hebrew picks at half (not joined)"] += 1
            continue
        if not top:
            continue
        hx = top[0]
        if lex[hx]["class"] != lex[ax]["class"]:
            c["D26 refused: the pick's class differs"] += 1
            continue
        cog = ev[(ax, hx)]["cognate_meaning"]
        if per[hx] < 2 and not cog:
            c["D26 refused: one piece and no cognate row"] += 1
            continue
        jb = "aramaic_cognate" if cog * 2 >= per[hx] else "aramaic_list"
        other = sum(1 for h, b, _, _ in picks[ax] if h != hx and b != "model")
        joins[hx].append((ax, per[hx], other, jb))
    for hx in sorted(joins):
        if hx in member_of:
            key = member_of[hx]
            for ax, n, o, jb in joins[hx]:
                groups[key]["members"][ax] = (jb, n, o)
                member_of[ax] = key
            c["D26 arc lexemes joined to a group of D25"] += len(joins[hx])
        else:
            jb0 = joins[hx][0][3]
            mem = {hx: (jb0, sum(n for _, n, _, _ in joins[hx]), 0)}
            for ax, n, o, jb in joins[hx]:
                mem[ax] = (jb, n, o)
            key = f"{prefix}:{head(list(mem))}"
            if key in groups:
                raise SystemExit(f"D26 (1.5): group key {key} twice")
            groups[key] = {"anchor": "", "members": mem}
            for lx in mem:
                member_of[lx] = key
            c["D26 groups formed"] += 1
    if pairs is not None:     # SPEC 1.6 D25 step 2b: a group left with its head alone (after D26) dissolves
        dis = STEP2B[prefix]["dissolved"]
        for key in list(dis):
            if key in groups and len(groups[key]["members"]) < 2:
                for lx in groups[key]["members"]:
                    member_of.pop(lx, None)
                del groups[key]
                c["1.6 step 2b groups dissolved (head alone after D26)"] += 1
            else:
                c["1.6 step 2b groups left with the head alone that D26 keeps (an Aramaic word joins the head)"] += 1
                del dis[key]
    # the head may change when D26 adds a member: rename by the head of all members
    renamed = {}
    for key, g in groups.items():
        nk = f"{prefix}:{head(list(g['members']))}"
        if nk in renamed:
            raise SystemExit(f"D25 (1.5): group key {nk} twice")
        renamed[nk] = g
    member_of = {lx: k for k, g in renamed.items() for lx in g["members"]}
    under = {lx: member_of[lx] for lx in under}
    sizes_c = C.Counter(len(v["members"]) for v in renamed.values())
    cnt[cnt_key] = {"anchored lexemes": len(anchors), "groups": len(renamed),
                    "members": sum(len(v["members"]) for v in renamed.values()),
                    "groups by size": {str(k): v for k, v in sorted(sizes_c.items())},
                    "joined_by": dict(sorted(C.Counter(m[0] for v in renamed.values() for m in v["members"].values()).items())),
                    "groups with an arc member": sum(1 for v in renamed.values() if any(lex[m]["lang"] == "arc" for m in v["members"])),
                    "groups with an arc head": sum(1 for k in renamed if lex[k.split(":", 1)[1]]["lang"] == "arc"),
                    "groups of two classes": sum(1 for v in renamed.values() if len({lex[m]["class"] for m in v["members"]}) > 1),
                    "anchored candidates out of every group (written alone)": len(weak), **dict(sorted(c.items()))}
    return renamed, member_of, anchors, set(weak), under


STEP2B = {}    # SPEC 1.6: prefix -> {"out": {lexeme: record}, "dissolved": {group: head}, "kept_out": {lexeme: (g, class)}}


def step2b(V, groups, member_of, under, allg_of, gate, lex, dom, prof, pairs, prefix, c):
    """SPEC 1.6 D25 step 2b: a weak join (an hbo member, not the head, joined by anchor, under the floor or with a
    ubs_depth to the head under 3) stays only where a second route confirms it: a pairs row with another member of
    the group that is sept_number with a number in `via` other than the anchor, nt_editions of basis linked (D25m:
    linked or model), or the other member in its same_strong. aramaic_list rows confirm nothing; arc members are no
    weak joins. A group left with its head alone dissolves. Changes groups, member_of, under in place."""
    nt_ok = ("linked",) if prefix == "cg" else ("linked", "model")
    pair = C.defaultdict(list)
    for p in pairs:
        pair[frozenset((p["a"], p["b"]))].append(p)
    out, dissolved = {}, {}
    for key in sorted(groups):
        g = groups[key]
        h = key.split(":", 1)[1]
        anchor = g["anchor"]
        mem = list(g["members"])
        gnum, allg = allg_of[key]
        leave = []
        for lx in sorted(mem):
            if lx == h or lex[lx]["lang"] != "hbo" or g["members"][lx][0] != "anchor":
                continue
            d = V.ubs_depth(dom.get(lx), dom.get(h))
            is_under = lx in under
            loose = d is not None and d < UBS_GATE
            if not (is_under or loose):
                continue
            routes, lacks = set(), []
            for o in mem:
                if o == lx:
                    continue
                if lex[o]["lang"] == lex[lx]["lang"] and V.digits(lex[o]["strong"]) == V.digits(lex[lx]["strong"]):
                    routes.add("same_strong")
                for p in pair.get(frozenset((lx, o)), []):
                    if p["evidence"] == "sept_number" and [x for x in json.loads(p["via"]) if x != anchor]:
                        routes.add("sept_number")
                    if p["evidence"] == "nt_editions" and p["basis"] in nt_ok:
                        routes.add("nt_editions")
            why = "under the floor" if is_under else "ubs_depth under 3"
            c[f"1.6 step 2b weak joins, {why}, {'confirmed' if routes else 'leave'}"] += 1
            for r in sorted(routes):
                c[f"1.6 step 2b confirmed by {r}"] += 1
            if not routes:
                leave.append(lx)
                out[lx] = {"group": key, "head": h, "ubs_depth": d, "why": why, "anchor": anchor,
                           "share": prof[lx][gnum] / allg if allg else 0.0,
                           "lacks": "sept_number with another number, nt_editions " + "/".join(nt_ok) + ", same_strong"}
        for lx in leave:
            del g["members"][lx]
            del member_of[lx]
            under.pop(lx, None)
        if leave:
            c["1.6 step 2b groups that lose a member"] += 1
        if len(g["members"]) < 2:      # left with its head alone: dissolves after D26 unless D26 joins a word to it
            dissolved[key] = (h, anchor, lex[h]["class"])
    kept = {lx: v for lx, v in gate.items() if lx not in member_of}
    for lx, r in out.items():
        kept[lx] = (r["anchor"], lex[lx]["class"])
    STEP2B[prefix] = {"out": out, "dissolved": dissolved, "kept_out": kept}
    c["1.6 step 2b members out"] = len(out)


def senses_profile(outdir, sp):
    """lexeme -> UBS sense -> Greek number -> Septuagint places (pieces with one sense code)."""
    sense = {}
    for lang in ("hbo", "arc"):
        for r in pq.read_table(os.path.join(outdir, lang, "pieces.parquet"), columns=["t", "n", "sense"]).to_pylist():
            if r["sense"] and " " not in r["sense"]:
                sense[(r["t"], r["n"])] = r["sense"]
    ps = C.defaultdict(lambda: C.defaultdict(C.Counter))
    for lx, g, t, n in sp:
        s = sense.get((t, n))
        if s:
            ps[lx][s][g] += 1
    return ps


def senses_out(V, lx, anchor, ps):
    """`groups.senses_out` (4.14): json list, or None."""
    if not anchor or lx not in ps:
        return None
    g = anchor.split(":", 1)[1]
    counted, out = False, []
    for s, prof in sorted(ps[lx].items()):
        if sum(prof.values()) < V.MIN_PLACES:
            continue
        counted = True
        a, _ = V.anchor_of(prof)
        if a != g:
            out.append(s)
    return json.dumps(sorted(out), ensure_ascii=False) if counted else None


GROUPS15 = [("group", pa.string()), ("lexeme", pa.string()), ("head", pa.bool_()), ("anchor", pa.string()),
            ("joined_by", pa.string()), ("members", pa.int64()), ("count", pa.int64()), ("against", pa.int64()),
            ("same_strong", pa.string()), ("ubs_depth", pa.int64()), ("senses_out", pa.string()), ("basis", pa.string())]
