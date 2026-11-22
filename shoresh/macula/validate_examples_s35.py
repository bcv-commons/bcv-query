"""Stage 35 checks (SPEC 1.5, section 10 "new in 1.5", section 13 against f1, the sample of mends). Imports no builder.

- d18(...): D18 of 1.5 recomputed from the rows of 1.3's rule (validate_examples_s27) and the build's pieces, words and
  constituents: the drops (a) to (d), kind and form, step W (`who`, `who_reason`).
- stage35(...): unchanged against f1 (section 13), the moves against f1 counted per mend, the 1.5 conditions that no
  earlier stage's check holds, and glossed-g1/mends-sample.md.
"""
import collections as C
import json
import os
import unicodedata as U

import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CAUS = {"hiphil", "haphel", "aphel", "shaphel"}
IMPERS = {U.normalize("NFC", x) for x in ("γίνομαι", "εἰμί", "הָיָה", "הֲוָה")}
LANGS = ("hbo", "arc", "grc")


def nfc(s):
    return U.normalize("NFC", s or "")


def _tsv(path):
    with open(path, encoding="utf-8") as fh:
        head = fh.readline().rstrip("\n").split("\t")
        return [dict(zip(head, ln.rstrip("\n").split("\t"))) for ln in fh]


def d18(R, build, gl, exp, term, piece_langs=None):
    """exp: {lang: [(verb t, role, clause, kind term, where, form, person, number, gender, antecedent, who)]} by 1.3's
    rule -> the rows of 1.5, with who_reason appended."""
    stem, who = {}, {}
    lemma = {}
    for lg in (piece_langs or gl):
        P = pq.read_table(os.path.join(build, lg, "pieces.parquet"),
                          columns=["t", "n", "kind", "class", "marks", "lexeme", "who"]).to_pylist()
        for r in P:
            who[(r["t"], r["n"])] = set((r["who"] or "").split())
            if r["kind"] == "stem":
                stem[r["t"]] = r
        for r in _tsv(os.path.join(build, lg, "lexemes.tsv")):
            lemma[r["lexeme"]] = nfc(r["lemma"])
    deps = C.defaultdict(list)
    for lg in (piece_langs or gl):
        W = pq.read_table(os.path.join(build, lg, "words.parquet"), columns=["t", "head"]).to_pydict()
        for t, h in zip(W["t"], W["head"]):
            deps[h].append(t)
    out = {}
    for lg in gl:
        N = pq.read_table(os.path.join(build, lg, "constituents.parquet"), columns=["clause", "frame_role"]).to_pydict()
        labels = C.defaultdict(set)
        for k, f in zip(N["clause"], N["frame_role"]):
            labels[k] |= set((f or "").split())
        code = {term(lg, "added_kind", c): c for c in ("in_verb", "elsewhere", "unsaid", "possessor")}
        drops = C.Counter()
        kept = []
        for x in exp[lg]:
            v, role, k, kind = x[0], x[1], x[2], code[x[3]]
            m = json.loads(stem[v]["marks"]) if v in stem else {}
            if role != "poss" and role in labels[k]:
                drops["(a) the role is a frame label of a part of its clause"] += 1
                continue
            if lg == "grc" and m.get("mood") == "ptcp" and any(stem.get(d, {}).get("class") == "det" for d in deps[v]) \
                    and role == ("A1" if m.get("voice") == "pass" else "A0"):
                drops["(b) Greek articular participle, its own role"] += 1
                continue
            lem = lemma.get(stem[v]["lexeme"], "") if v in stem else ""
            if role == "A0" and kind == "unsaid" and lem in IMPERS and (
                    "person" not in m or (m.get("person") == "3" and m.get("number") == "sg")):
                drops[f"(c) unsaid A0 of an impersonal verb {lem}"] += 1
                continue
            kept.append(x)
        keys = C.defaultdict(list)
        for x in kept:
            keys[(x[2], x[0], x[1])].append(x)
        rows = []
        for key, xs in keys.items():
            def near(x):
                if not x[9]:
                    return (1,)
                t, n = map(int, x[9].split("."))
                return (0, abs(t - x[0]), t, n)
            xs = sorted(xs, key=near)
            drops["(d) a second row on one key"] += len(xs) - 1
            rows.append(xs[0])
        moved = C.Counter()
        res = []
        if V16:      # SPEC 1.6 4.11: the frame's AA (a row after the drops, or a part whose frame_role holds AA)
            aa_row = {(x[2], x[0]) for x in rows if x[1] == "AA"}
            aa_part = set()
            for lg_ in (piece_langs or gl):
                for k_, f_ in zip(*pq.read_table(os.path.join(build, lg_, "constituents.parquet"),
                                                 columns=["clause", "frame_role"]).to_pydict().values()):
                    if "AA" in (f_ or "").split():
                        aa_part.add(k_)
        for x in rows:
            v, role, k, kind = x[0], x[1], x[2], code[x[3]]
            m = json.loads(stem[v]["marks"]) if v in stem else {}
            caus = m.get("stem") in CAUS
            subj = role == ("AA" if caus else "A0")
            if V16:
                subj = role == (("AA" if ((k, v) in aa_row or k in aa_part) else "A0") if caus else "A0")
            form = "none"
            if role != "poss" and subj and "person" in m:
                new, form = "in_verb", "ending"
            elif V16 and role != "poss":     # SPEC 1.6 D18 step 2 (ii)
                new = "unsaid" if x[4] == "unexpressed" else "elsewhere"
            elif role == "A0" and caus:
                new = "unsaid" if x[4] == "unexpressed" else "elsewhere"
            else:
                new = kind
            moved[f"{kind} -> {new}"] += kind != new
            V_ = who[(v, stem[v]["n"])] if subj and v in stem and role != "poss" else set()
            N_ = who.get(tuple(map(int, x[9].split("."))), set()) if x[9] else set()
            if role == "poss":
                w, why = "", "guess"
            elif V_ and N_ and V16 and (V_ <= N_ or N_ <= V_):     # SPEC 1.6 step W: one set holds the other
                sm, lg_set = (V_, N_) if V_ <= N_ else (N_, V_)
                w, why = " ".join(sorted(sm if m.get("number") == "sg" else lg_set)), "verb_and_antecedent"
            elif V_ and N_:
                w = " ".join(sorted(V_ & N_))
                why = "verb_and_antecedent" if w else "disagree"
            elif V_:
                w, why = " ".join(sorted(V_)), "verb"
            elif N_:
                w, why = " ".join(sorted(N_)), "antecedent"
            else:
                w, why = "", "antecedent_no_participant" if x[9] else "no_antecedent"
            png = (x[6], x[7], x[8])
            if V16 and form == "ending":      # SPEC 1.6 D18 step 2 (i): the ending's person, number, gender
                png = tuple(m.get(f) or "" for f in ("person", "number", "gender"))
            res.append((v, role, k, term(lg, "added_kind", new), x[4], form) + png + (x[9], w, why))
        out[lg] = res
        R.info(f"{lg} 1.5 D18 drops, recomputed", dict(sorted(drops.items())))
        R.info(f"{lg} 1.5 D18 kind moves, recomputed", {k_: n for k_, n in sorted(moved.items()) if n})
        R.info(f"{lg} 1.5 D18 who_reason, recomputed", dict(sorted(C.Counter(r[11] for r in res).items())))
        R.check(f"{lg} added (1.5): no poss row has a who", all(not r[10] for r in res if r[1] == "poss"))
    return out


VERBLESS = set()       # Greek clauses whose time-aspect row has basis grc:verbless (filled by stage 16's check, D9)


def verbless_time_abs(R, build, res, own):
    """SPEC 1.5 D16: a verbless Greek clause takes the time_abs of its nearest ancestor with a time (not verbless)."""
    K = pq.read_table(os.path.join(build, "grc", "clauses.parquet"), columns=["clause", "parent"]).to_pydict()
    parent = dict(zip(K["clause"], K["parent"]))
    res = dict(res)
    c = C.Counter()
    if not VERBLESS:
        R.check("grc 1.5 D16: the verbless clauses are known (stage 16's check ran in this run)", False)
    for k in sorted(VERBLESS):
        up = parent.get(k)
        while up and up not in own:
            up = parent.get(up)
        if not up:
            res[k] = ("grc", "", "verbless, no ancestor", False)
        else:
            _l, v, _r, m = res[up]
            res[k] = ("grc", v, "" if v else "verbless, ancestor unresolved", m)
        c["from an ancestor" if res[k][1] else res[k][2]] += 1
    R.info("grc 1.5 D16 verbless clauses, recomputed", dict(sorted(c.items())))
    return res


def causer_rows(R, build, lg, N1):
    """SPEC 1.5 D12c (A3): (clause, ord) of the `s` parts with frame label AA in a clause whose pred's stem piece has a
    causative stem and whose 1.4 role (N1, the earlier build's sem_role) is empty."""
    N = pq.read_table(os.path.join(build, lg, "constituents.parquet"),
                      columns=["clause", "ord", "role", "frame_role"]).to_pydict()
    K = pq.read_table(os.path.join(build, lg, "clauses.parquet"), columns=["clause", "pred"]).to_pydict()
    pred = dict(zip(K["clause"], K["pred"]))
    stem = {}
    for l2 in (("hbo", "arc") if lg != "grc" else ("grc",)):
        P = pq.read_table(os.path.join(build, l2, "pieces.parquet"), columns=["t", "kind", "marks"]).to_pydict()
        stem.update({t: json.loads(m).get("stem") for t, k, m in zip(P["t"], P["kind"], P["marks"]) if k == "stem"})
    old = {(k, o): s for k, o, s in zip(N1["clause"], N1["ord"], N1["sem_role"])}
    out = set()
    kept = 0
    for k, o, r, f in zip(N["clause"], N["ord"], N["role"], N["frame_role"]):
        if r == "s" and "AA" in (f or "").split() and stem.get(pred.get(k)) in CAUS:
            if old.get((k, o)):
                kept += 1
            else:
                out.add((k, o))
    R.info(f"{lg} 1.5 D12c causer parts, recomputed: given actor / keep their D12 role", f"{len(out):,} / {kept}")
    return out


# ---- D23 and D25, D26 of 1.5, recomputed (called by validate_examples_s32 on a g build) ---------------------------

FUNC = ("det", "pron", "conj", "prep", "ptcl")


def cons(s):
    return "".join(ch for ch in U.normalize("NFD", s or "") if "א" <= ch <= "ת")


def forms(build):
    f = C.defaultdict(C.Counter)
    for lg in ("hbo", "arc"):
        P = pq.read_table(os.path.join(build, lg, "pieces.parquet"), columns=["text", "lexeme", "kind"]).to_pydict()
        for x, lx, k in zip(P["text"], P["lexeme"], P["kind"]):
            if k == "stem":
                f[cons(x)][lx] += 1
    return f


def keys15(R, build, want):
    """want: {edition: [(s, p, text, class, lemma, strong, lexeme, key_rule, basis)]} by 1.4's D23 -> 1.5's."""
    F = forms(build)
    L = pq.read_table(os.path.join(build, "grc", "links.parquet"), columns=["t", "other", "s", "basis"]).to_pydict()
    mod_t, scg_s = C.defaultdict(set), C.defaultdict(set)
    for t, o, s, b in zip(L["t"], L["other"], L["s"], L["basis"]):
        if b == "linked" and o == "heb_mod":
            mod_t[s].add(t)
        elif b == "linked" and o == "heb_scg":
            scg_s[t].add(s)
    scg = C.defaultdict(set)
    for r in want["heb_scg"]:
        scg[r[0]].add(r[6])
    out = {}
    c = C.Counter()
    rows = []
    for r in want["heb_mod"]:
        r = list(r)
        lx = F.get(cons(r[2]), {})
        if r[8] == "derived" and r[6].startswith("lex:") and len(lx) >= 2 and r[6] in lx and \
                sorted(lx.values())[-2] >= 0.1 * sum(lx.values()):
            got = {k for t in mod_t.get(r[0], ()) for s2 in scg_s.get(t, ()) for k in scg.get(s2, ()) if k in lx}
            if len(got) == 1:
                k = next(iter(got))
                r[7] = "H1" if k == r[6] else "H2"
                r[6] = k
            else:
                r[7], r[8] = "H0", "model"
            c[r[7]] += 1
        rows.append(r)
    out["heb_mod"] = rows
    out["heb_scg"] = [list(r) for r in want["heb_scg"]]
    for ed in out:
        for r in out[ed]:
            if r[7] in ("K0", "K5"):
                lx = F.get(cons(r[2]), {})
                if len(lx) == 1:
                    r[6], r[7], r[8] = next(iter(lx)), "K6", "model"
                    c[f"{ed} K6"] += 1
        out[ed] = [tuple(r) for r in out[ed]]
    R.info("tan 1.5 D23 recomputed: heb_mod H0, H1, H2; K6 per edition (SPEC from f1: H1 8,095, H2 205, H0 7,078; "
           "K6 heb_mod 1,055, heb_scg 1,494)", dict(sorted(c.items())))
    return out


def function_numbers(build):
    g = C.defaultdict(C.Counter)
    for r in _tsv(os.path.join(build, "grc", "lexemes.tsv")):
        for s in (r["strong"] or "").split():
            if s.isdigit():
                g[s.lstrip("0") or "0"][r["class"]] += int(r["count"])
    return {n for n, c in g.items() if sorted(c.items(), key=lambda x: (-x[1], x[0]))[0][0] in FUNC}


GATE16 = {}     # SPEC 1.6 D27: prefix -> the lexemes the UBS gate keeps out beside a group (set by groups15)


def groups15(lex, elig, prof, lst, ev, size, dom_depth, prefix, step2b=None):
    """D25 steps 2 to 4 and D26 of 1.5 over a profile -> groups {key: (anchor, {lexeme: (joined_by, count, against)})},
    member, anchor, under (members joined under the floor), weak (anchored, in no group)."""
    def head(ms):
        h = [m for m in ms if lex[m]["lang"] == "hbo"] or list(ms)
        return min(h, key=lambda x: (-size(x), x))
    anchor = {}
    for lx in elig:
        c = prof.get(lx)
        if not c or sum(c.values()) < 5:
            continue
        top = max(c.values())
        g = min((g for g, n in c.items() if n == top), key=int)
        if top / sum(c.values()) >= 0.5:
            anchor[lx] = (g, top / sum(c.values()))
    cands = C.defaultdict(list)
    for lx, (g, _) in anchor.items():
        cands[(g, lex[lx]["class"])].append(lx)
    groups, under, weak, gate = {}, set(), set(), set()
    for (g, cl), ls in cands.items():
        tot = sum(prof[x][g] for x in ls)
        mem = [x for x in ls if prof[x][g] >= 0.05 * tot]
        low = []
        if mem:
            h0 = head(mem)
            low = [x for x in ls if x not in mem and (lex[x]["lang"] == "arc" or (dom_depth(x, h0) or 0) >= 3)]
        allm = mem + low
        if len(allm) < 2:
            if len(ls) >= 2:
                weak |= set(ls) - set(allm)
            continue
        weak |= set(ls) - set(allm)
        gate |= set(ls) - set(allm)
        under |= set(low)
        groups[g + "|" + cl] = ("g:" + g, {x: ("anchor", prof[x][g], sum(prof[x].values()) - prof[x][g]) for x in allm})
    GATE16[prefix] = gate
    pending = set()
    if step2b is not None:     # SPEC 1.6 D25 step 2b, between step 2 and D26 (the head chosen before it)
        pending = step2b(groups, under, head)
    member = {x: k for k, v in groups.items() for x in v[1]}
    join = C.defaultdict(list)
    for ax, L in sorted(lst.items()):
        if ax not in elig or ax in member or lex[ax]["lang"] != "arc":
            continue
        per = C.Counter(h for h, b, _, _ in L if h and b == "derived" and h in elig)
        hits = [h for h, n in per.items() if 2 * n >= int(lex[ax]["count"])]
        if len(hits) != 1:
            continue
        h = hits[0]
        cg = ev[(ax, h)]["cognate_meaning"]
        if lex[h]["class"] != lex[ax]["class"] or (per[h] < 2 and not cg):
            continue
        jb = "aramaic_cognate" if 2 * cg >= per[h] else "aramaic_list"
        join[h].append((ax, per[h], sum(1 for hh, bb, _, _ in L if hh != h and bb != "model"), jb))
    for h, js in sorted(join.items()):
        if h in member:
            for ax, n, o, jb in js:
                groups[member[h]][1][ax] = (jb, n, o)
                member[ax] = member[h]
        else:
            mem = {h: (js[0][3], sum(x[1] for x in js), 0)}
            mem.update({ax: (jb, n, o) for ax, n, o, jb in js})
            groups["|" + h] = ("", mem)
            for x in mem:
                member[x] = "|" + h
    for k in pending:          # SPEC 1.6: a group left with its head alone dissolves unless D26 joined a word to it
        if len(groups[k][1]) < 2:
            del groups[k]
    named = {f"{prefix}:{head(v[1])}": v for v in groups.values()}
    member = {x: k for k, v in named.items() for x in v[1]}
    return named, member, anchor, under, weak


_SENSE = {}


def senses_out(build, sp, lx, anchor):
    """`groups.senses_out` (SPEC 1.5 4.14): the member's UBS senses (pieces with one sense code) with 5 places or more
    whose own anchor (5 places, half) is not the group's number; json, or None."""
    if build not in _SENSE:
        sense = {}
        for lg in ("hbo", "arc"):
            P = pq.read_table(os.path.join(build, lg, "pieces.parquet"), columns=["t", "n", "sense"]).to_pydict()
            for t, n, s in zip(P["t"], P["n"], P["sense"]):
                if s and " " not in s:
                    sense[(t, n)] = s
        _SENSE[build] = (sense, {})
    sense, cache = _SENSE[build]
    key = id(sp)
    if key not in cache:
        ps = C.defaultdict(lambda: C.defaultdict(C.Counter))
        for x, g, t, n in sp:
            s = sense.get((t, n))
            if s:
                ps[x][s][g] += 1
        cache.clear()
        cache[key] = ps
    ps = cache[key]
    if not anchor or lx not in ps:
        return None
    g0 = anchor.split(":", 1)[1]
    seen, out = False, []
    for s, prof in ps[lx].items():
        tot = sum(prof.values())
        if tot < 5:
            continue
        seen = True
        top = max(prof.values())
        a = min((g for g, n in prof.items() if n == top), key=int) if top / tot >= 0.5 else None
        if a != g0:
            out.append(s)
    return json.dumps(sorted(out), ensure_ascii=False) if seen else None


# ---- stage 35: unchanged against f1, the moves, the 1.5 conditions, the sample of mends ----------------------------

SAME_FILES = ("words.parquet", "pieces.parquet", "lexemes.tsv", "passages.parquet", "exceptions.parquet",
              "source_errors.tsv", "terms.tsv", "terms-notes.md", "relmap.tsv", "profile.tsv",
              "links.parquet", "link_account.parquet", "agreement.parquet",
              "constructions.parquet", "forms.parquet", "frames.parquet", "markers.parquet", "orders.parquet",
              "pairs.parquet", "paradigms.parquet")
SAMPLE = os.path.join(ROOT, "internal-docs/source-examples-work/glossed-g1/mends-sample.md")
WRITE = False          # set by validate_examples.py --write-md
V16 = False            # an h build (SPEC 1.6): the 1.5 conditions read against g1; stage 38 checks what 1.6 changes


def _sha(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _rows(path, cols=None):
    return pq.read_table(path, columns=cols).to_pylist()


def pick(items, n=20, first=5):
    """The fixed rule of the sample: the first 5 in text order, then every k-th, 20 in all."""
    if len(items) <= n:
        return list(items)
    rest = items[first:]
    k = max(1, len(rest) // (n - first))
    return list(items[:first]) + rest[::k][:n - first]


def stage35(R, build, f1=None):
    f1 = f1 or os.path.join(os.path.dirname(os.path.normpath(build)), "f1")
    md = ["# Sample of the mends of version 1.5: build g1 against f1", "",
          "Written by `validate_examples.py --build g1 --upto 35 --write-md` (`validate_examples_s35.py`). For every mend "
          "of SPEC 1.5 and every language: what moved against `f1`, counted, and a sample by a fixed rule: the changed "
          "rows in text order, the first 5, then every k-th (k = (n - 5) // 15), 20 in all. Each line: the place, the "
          "words of the text, the value in `f1` and in `g1`. Nothing here is a gloss.", ""]
    words, text_of = {}, {}
    for lg in LANGS:
        W = pq.read_table(os.path.join(build, lg, "words.parquet"), columns=["t", "book", "chapter", "verse", "text"]).to_pydict()
        for t, b, c, v, x in zip(W["t"], W["book"], W["chapter"], W["verse"], W["text"]):
            words[(lg, t)] = (b, c, v)
            text_of[(lg, t)] = x

    def ref(t, lg):
        b, c, v = words.get((lg, t), ("?", 0, 0))
        return f"{b} {c}:{v}"

    def span(a, b, lg, cap=8):
        ws = [text_of[(lg, t)] for t in range(a, b + 1) if (lg, t) in text_of]
        return " ".join(ws[:cap]) + (" …" if len(ws) > cap else "")

    def section(title, lg, changed, counts):
        md.extend([f"## {title}: {lg}", "", "Moves against f1: " + (
            "; ".join(f"{k} {v:,}" for k, v in counts.items()) if counts else "none") + ".", ""])
        for line in pick(changed):
            md.append(f"- {line}")
        md.append("")

    # ---- unchanged files (section 13)
    R.section("unchanged against f1 (SPEC 1.5 section 13)")
    for lg in LANGS:
        same = [f for f in SAME_FILES if os.path.exists(os.path.join(f1, lg, f))
                and not (V16 and f == "source_errors.tsv")]     # SPEC 1.6: SE5 rows (stage 38)
        diff = [f for f in same if not os.path.exists(os.path.join(build, lg, f)) or
                _sha(os.path.join(build, lg, f)) != _sha(os.path.join(f1, lg, f))]
        R.check(f"{lg} unchanged: {len(same)} tables and files byte-equal to f1 (words, pieces, lexemes, passages, the "
                "statement tables but clause_links, exceptions, source_errors, terms, terms-notes, relmap, profile, links, "
                "link_account; map.tsv, facts, clause_links are checked as follow-on below)", not diff, diff)
        for f in ("words", "pieces"):
            pass
    for ed in ("heb_mod", "heb_scg"):
        same = [f for f in os.listdir(os.path.join(f1, "other", ed)) if f != "parts.parquet"]
        diff = [f for f in same if _sha(os.path.join(build, "other", ed, f)) != _sha(os.path.join(f1, "other", ed, f))]
        R.check(f"tan other/{ed}: every file but parts.parquet byte-equal to f1", not diff, diff)

    # ---- participants (4.5, D18 step W)
    for lg in LANGS:
        a = {r["ent"]: r for r in _tsv(os.path.join(f1, lg, "participants.tsv"))}
        b = {r["ent"]: r for r in _tsv(os.path.join(build, lg, "participants.tsv"))}
        gone = sorted(set(a) - set(b))
        A1 = _rows(os.path.join(f1, lg, "added.parquet"), ["who"])
        P1 = pq.read_table(os.path.join(f1, lg, "pieces.parquet"), columns=["who"]).to_pydict()["who"]
        K1 = pq.read_table(os.path.join(f1, lg, "clauses.parquet"), columns=["speaker", "addressee"]).to_pydict()
        other = {e for w in P1 for e in (w or "").split()} | set(K1["speaker"]) | set(K1["addressee"])
        only = {e for r in A1 for e in (r["who"] or "").split()} - other     # several entities since 1.5
        R.check(f"{lg} participants: the rows gone are exactly f1's participants that only added.who named; every other "
                "row equal to f1's", set(gone) == only and set(b) <= set(a) and all(b[e] == a[e] for e in b),
                f"{len(gone)} gone (SPEC from f1: hbo 32, arc 8, grc 8), {len(only)} only in added.who")
        Ag = _rows(os.path.join(build, lg, "added.parquet"), ["who"])
        named = {e for r in Ag for e in r["who"].split()}
        Pg = pq.read_table(os.path.join(build, lg, "pieces.parquet"), columns=["who"]).to_pydict()["who"]
        Kg = pq.read_table(os.path.join(build, lg, "clauses.parquet"), columns=["speaker", "addressee"]).to_pydict()
        else_ = {e for w in Pg for e in (w or "").split()} | set(Kg["speaker"]) | set(Kg["addressee"])
        R.check(f"{lg} participants (1.5): every ent occurs in a column other than added.who", set(b) <= else_,
                f"{len(set(b) - else_)} not")
        R.check(f"{lg} added.who (1.5): every entity is a participant named elsewhere", named <= else_,
                f"{len(named - else_)} not")
        section("participants.tsv rows gone (D18 step W)", lg, [f"{e} ({a[e]['name'] or '-'})" for e in gone],
                {"rows gone": len(gone)} if gone else {})
        # follow-on changes (not named in section 13; see the stage 35 report)
        fa = {json.dumps(r, sort_keys=True, ensure_ascii=False) for r in _rows(os.path.join(f1, lg, "facts.parquet"))}
        fbl = _rows(os.path.join(build, lg, "facts.parquet"))
        fb = {json.dumps(r, sort_keys=True, ensure_ascii=False) for r in fbl}
        lostf = [json.loads(x) for x in sorted(fa - fb)]
        R.check(f"{lg} facts (follow-on): every row equals f1's; the rows gone are kin rows with a side among the "
                "participants gone", fb <= fa and all(r["source"] == "acai" and (r["subject"] in gone or r["object"] in gone)
                                                      for r in lostf), f"{len(lostf)} kin rows gone")
        section("facts kin rows gone with their participant (follow-on)", lg,
                [f"{r['subject']} {r['relation']} {r['object']}" for r in lostf], {"kin rows gone": len(lostf)} if lostf else {})
        ma = {tuple(v for c_, v in r.items() if c_ != "count"): r["count"] for r in _tsv(os.path.join(f1, lg, "map.tsv"))}
        mb = {tuple(v for c_, v in r.items() if c_ != "count"): r["count"] for r in _tsv(os.path.join(build, lg, "map.tsv"))}
        newk, gonek = set(mb) - set(ma), set(ma) - set(mb)
        mended = {("added", "who_reason"), ("clauses", "connective"), ("clauses", "mood"), ("clauses", "time"),
                  ("clauses", "aspect"), ("clauses", "time_abs")}
        R.check(f"{lg} map.tsv (follow-on): every row of f1 kept but its count; rows come or go only for the codes of "
                "the mended columns (who_reason, connective, mood, time, aspect)",
                all((k[0], k[1]) in mended for k in newk | gonek),
                f"{sum(1 for k in ma if k in mb and mb[k] != ma[k])} counts moved, {len(newk)} rows added "
                f"{sorted(newk)[:3]}, {len(gonek)} gone {sorted(gonek)[:3]}")
        ca = _rows(os.path.join(f1, lg, "clause_links.parquet"))
        cb = _rows(os.path.join(build, lg, "clause_links.parquet"))
        ka = {(r["kind"], r["connective"], r["parent_kind"], r["role"]): r["count"] for r in ca}
        kb = {(r["kind"], r["connective"], r["parent_kind"], r["role"]): r["count"] for r in cb}
        mv = sorted(k for k in set(ka) | set(kb) if ka.get(k) != kb.get(k))
        R.info(f"{lg} clause_links (follow-on of marks.connective; recomputed by stage 18's check): rows f1 {len(ca)}, "
               f"g1 {len(cb)}; patterns whose count moved", len(mv))
        section("clause_links patterns (follow-on of the connective edge)", lg,
                [f"{k[0] or '-'} {k[1] or '-'} under {k[2] or '-'} {k[3] or ''}: f1 {ka.get(k, 0)}; g1 {kb.get(k, 0)}" for k in mv],
                {"patterns whose count moved": len(mv)} if mv else {})
    return md, words, text_of, ref, span, section


def moves(R, build, f1, ctx):
    md, words, text_of, ref, span, section = ctx
    terms = {}
    for lg in LANGS:
        for r in _tsv(os.path.join(build, lg, "terms.tsv")):
            terms[(lg, r["category"], r["code"])] = r["grc" if lg == "grc" else "hbo"]
    # ---- added (D18)
    R.section("added (D18 of 1.5) against f1")
    for lg in LANGS:
        a = {}
        for r in _rows(os.path.join(f1, lg, "added.parquet")):
            a.setdefault((r["clause"], r["verb"], r["role"]), r)
        b = {(r["clause"], r["verb"], r["role"]): r for r in _rows(os.path.join(build, lg, "added.parquet"))}
        R.check(f"{lg} added (1.5): (clause, verb, role) unique", len(b) == pq.read_metadata(
            os.path.join(build, lg, "added.parquet")).num_rows)
        same_c = ("where", "antecedent") if V16 else ("where", "person", "number", "gender", "antecedent")
        R.check(f"{lg} added (1.5): every row's key is a row of f1, and clause, verb, role, " + ", ".join(same_c) +
                " equal f1's", set(b) <= set(a) and all(all(b[k][c] == a[k][c] for c in same_c) for k in b))
        c = C.Counter()
        ch = {"drop": [], "kind": [], "who": []}
        for k in sorted(a, key=lambda k: (k[1], k[2], k[0])):
            x = a[k]
            line = f"{ref(k[1], lg)} {text_of.get((lg, k[1]), '')} {k[2]}"
            if k not in b:
                c["rows dropped"] += 1
                ch["drop"].append(f"{line}: f1 kind {x['kind']}, who {x['who'] or '-'}; g1 no row")
                continue
            y = b[k]
            if (x["kind"], x["form"]) != (y["kind"], y["form"]):
                c[f"kind/form moved"] += 1
                ch["kind"].append(f"{line}: f1 {x['kind']} / {x['form']}; g1 {y['kind']} / {y['form']}")
            if x["who"] != y["who"]:
                st = "emptied" if not y["who"] else "filled" if not x["who"] else "another"
                c[f"who {st}"] += 1
                ch["who"].append(f"{line}: f1 who {x['who'] or '-'}; g1 who {y['who'] or '-'} ({y['who_reason']})")
            else:
                c["who the same"] += 1
        R.info(f"{lg} added: moves against f1", dict(sorted(c.items())))
        section("D18 step 1, rows dropped", lg, ch["drop"], {k: v for k, v in c.items() if "dropped" in k})
        section("D18 step 2, kind and form", lg, ch["kind"], {k: v for k, v in c.items() if "kind" in k})
        section("D18 step W, who", lg, ch["who"], {k: v for k, v in sorted(c.items()) if k.startswith("who")})
        # D18 of 1.5 recomputed from f1's rows (1.3's rule, checked in f1) and this build's pieces
        f1rows = sorted((r["verb"], r["role"], r["clause"], r["kind"], r["where"], r["form"], r["person"], r["number"],
                         r["gender"], r["antecedent"], r["who"]) for r in _rows(os.path.join(f1, lg, "added.parquet")))
        want = d18(R, build, (lg,), {lg: f1rows}, lambda l_, cat, code: terms[(l_, cat, code)],
                   piece_langs=("grc",) if lg == "grc" else ("hbo", "arc"))[lg]
        have = sorted((r["verb"], r["role"], r["clause"], r["kind"], r["where"], r["form"], r["person"], r["number"],
                       r["gender"], r["antecedent"], r["who"], r["who_reason"]) for r in b.values())
        R.check(f"{lg} added (1.5): every row recomputed by D18's three steps from f1's rows (drops, kind and form, "
                "step W with who_reason)" + (" [steps 2 and W by the rules of 1.6]" if V16 else ""), have == sorted(want), f"{len(have):,} rows, recomputed {len(want):,}")
        poss = [r for r in b.values() if r["role"] == "poss" and r["who"]]
        R.check(f"{lg} added (1.5): no poss row has a who", not poss, len(poss))
    # ---- constituents (D12c causer, D17)
    R.section("constituents (D12c, D17 of 1.5) against f1")
    for lg in LANGS:
        cols = ["clause", "ord", "role", "first", "last", "head", "sem_role", "sem_role_basis", "ref_status", "ref_form"]
        A = pq.read_table(os.path.join(f1, lg, "constituents.parquet")).to_pydict()
        B = pq.read_table(os.path.join(build, lg, "constituents.parquet")).to_pydict()
        same_cols = [x for x in A if x not in ("sem_role", "sem_role_basis", "ref_status", "ref_form")]
        R.check(f"{lg} constituents unchanged: every column but sem_role, sem_role_basis, ref_status, ref_form equals f1, "
                "row by row", list(A) == list(B) and all(A[x] == B[x] for x in same_cols), same_cols)
        n = len(A["clause"])
        c = C.Counter()
        ch = {"sem": [], "ref": []}
        span_of = C.defaultdict(list)
        for j in range(n):
            span_of[B["clause"][j]].append(j)
        for j in range(n):
            line = f"{ref(B['head'][j], lg)} {span(B['first'][j], B['last'][j], lg)} [{B['role'][j]}]"
            if (A["sem_role"][j], A["sem_role_basis"][j]) != (B["sem_role"][j], B["sem_role_basis"][j]):
                ok = B["role"][j] == "s" and not A["sem_role"][j] and B["sem_role_basis"][j] == "derived"
                c["sem_role filled on a causer part" if ok else "sem_role moved otherwise"] += 1
                ch["sem"].append(f"{line}: f1 {A['sem_role'][j] or '-'}; g1 {B['sem_role'][j]}")
            if (A["ref_status"][j], A["ref_form"][j]) != (B["ref_status"][j], B["ref_form"][j]):
                kind = ("taken off a v part" if A["role"][j] == "v" and not B["ref_status"][j] else
                        "taken off a p part" if A["role"][j] == "p" and not B["ref_status"][j] else
                        "given to a part beside its v" if not A["ref_status"][j] else "changed")
                c[f"ref_status {kind}"] += 1
                ch["ref"].append(f"{line}: f1 {A['ref_status'][j] or '-'} {A['ref_form'][j] or ''}; "
                                 f"g1 {B['ref_status'][j] or '-'} {B['ref_form'][j] or ''}")
        R.check(f"{lg} constituents (1.5): sem_role moved only on causer parts (s, empty in f1, derived)",
                c["sem_role moved otherwise"] == 0, dict(c))
        bad_v = 0
        for k, js in span_of.items():
            for j in js:
                if B["role"][j] == "v" and B["ref_status"][j] and any(
                        B["role"][i] != "v" and (B["first"][i], B["last"][i]) == (B["first"][j], B["last"][j]) for i in js):
                    bad_v += 1
        R.check(f"{lg} constituents (1.5): no ref_status on a v part where a non-v part of the clause has its span",
                bad_v == 0, bad_v)
        bad_p = sum(1 for j in range(n) if B["role"][j] == "p" and B["ref_status"][j] and
                    B["ref_form"][j] not in ("suffix", "pronoun"))
        R.check(f"{lg} constituents (1.5): no ref_status on a p part unless ref_form is suffix or pronoun", bad_p == 0, bad_p)
        R.info(f"{lg} constituents: moves against f1", dict(sorted(c.items())))
        section("D12c the causer, sem_role", lg, ch["sem"], {k: v for k, v in c.items() if k.startswith("sem")})
        section("D17 reference status", lg, ch["ref"], {k: v for k, v in sorted(c.items()) if k.startswith("ref")})
    # ---- who_account (D19)
    R.section("who_account (D19 of 1.5) against f1")
    for lg in LANGS:
        A = pq.read_table(os.path.join(f1, lg, "who_account.parquet")).to_pydict()
        B = pq.read_table(os.path.join(build, lg, "who_account.parquet")).to_pydict()
        R.check(f"{lg} who_account unchanged: t, n, head_kind, state equal f1, row by row",
                all(A[x] == B[x] for x in ("t", "n", "head_kind", "state")))
        ch = []
        bad = miss = 0
        for j in range(len(A["t"])):
            if A["reason"][j] != B["reason"][j]:
                ok = B["head_kind"][j] == "verb_zero" and B["state"][j] == "no_entity" and not A["reason"][j]
                bad += not ok
                ch.append(f"{ref(B['t'][j], lg)} {text_of.get((lg, B['t'][j]), '')}: f1 -; g1 {B['reason'][j]}")
            if B["head_kind"][j] == "verb_zero" and B["state"][j] == "no_entity" and not B["reason"][j]:
                miss += 1
        R.check(f"{lg} who_account (1.5): reason changes only on verb_zero no_entity rows empty in f1", bad == 0, bad)
        R.check(f"{lg} who_account (1.5): every verb_zero no_entity row has a reason", miss == 0, miss)
        section("D19 reason of verb_zero", lg, ch, {"reasons filled": len(ch)} if ch else {})
    # ---- clauses (D9, D16)
    R.section("clauses (D9, D16 of 1.5) against f1")
    for lg in LANGS:
        A = pq.read_table(os.path.join(f1, lg, "clauses.parquet")).to_pydict()
        B = pq.read_table(os.path.join(build, lg, "clauses.parquet")).to_pydict()
        oth = [x for x in A if x not in ("marks", "marks_model")]
        R.check(f"{lg} clauses unchanged: every column but marks, marks_model equals f1, row by row",
                list(A) == list(B) and all(A[x] == B[x] for x in oth))
        allowed = {"connective"} | ({"mood", "time", "aspect", "time_abs"} if lg == "grc" else set())
        c = C.Counter()
        ch = C.defaultdict(list)
        bad = 0
        for j in range(len(A["clause"])):
            ma, mb = json.loads(A["marks"][j]), json.loads(B["marks"][j])
            if A["marks_model"][j] != B["marks_model"][j]:
                bad += 1
            line = f"{ref(B['first'][j], lg)} {span(B['first'][j], B['last'][j], lg)}"
            for key in sorted(set(ma) | set(mb)):
                if ma.get(key) != mb.get(key):
                    if key not in allowed:
                        bad += 1
                        continue
                    c[f"{key} moved"] += 1
                    ch[key].append(f"{line}: f1 {ma.get(key, '-')}; g1 {mb.get(key, '-')}")
        R.check(f"{lg} clauses (1.5): marks differ from f1 only in " + ", ".join(sorted(allowed)) +
                "; marks_model equal", bad == 0, bad)
        lost = sum(1 for ma, mb in zip(A["marks"], B["marks"])
                   if C.Counter(json.loads(ma).get("connective", [])) - C.Counter(json.loads(mb).get("connective", [])))
        R.check(f"{lg} clauses (1.5): the edge only widens: every connective of f1 stands in g1 on its clause",
                lost == 0, lost)
        R.info(f"{lg} clauses: moves against f1", dict(sorted(c.items())))
        for key in sorted(allowed):
            section(f"D9/D16 marks.{key}", lg, ch[key], {f"{key} moved": c[f'{key} moved']} if ch[key] else {})
        if lg == "grc":
            inter = terms[("grc", "mood", "interrogative")]
            P = pq.read_table(os.path.join(build, lg, "pieces.parquet"), columns=["t", "marks"]).to_pydict()
            W = pq.read_table(os.path.join(build, lg, "words.parquet"), columns=["t", "clause", "after"]).to_pydict()
            cl_of = dict(zip(W["t"], W["clause"]))
            after = dict(zip(W["t"], W["after"]))
            iw = {cl_of[t] for t, m in zip(P["t"], P["marks"]) if json.loads(m).get("type") == "interrogative"}
            badq = sum(1 for k, m, last in zip(B["clause"], B["marks"], B["last"]) if json.loads(m).get("mood") == inter
                       and k not in iw and not any(q in (after.get(last) or "") for q in (";", ";")))
            R.check("grc clauses (1.5): no interrogative mood without an own interrogative word or a final question mark",
                    badq == 0, badq)
            badt = sum(1 for k, m in zip(B["clause"], B["marks"]) if k in VERBLESS and ("time" in json.loads(m) or
                                                                                     "aspect" in json.loads(m)))
            if VERBLESS:
                R.check("grc clauses (1.5): no clause whose time-aspect row is grc:verbless has a time or an aspect",
                        badt == 0, f"{badt} of {len(VERBLESS):,}")
            else:
                R.skip("grc clauses (1.5): verbless clauses without time", "stage 16's check did not run (--only)")
    # ---- parts (D23)
    R.section("other/heb_*/parts.parquet (D23 of 1.5) against f1")
    for ed in ("heb_mod", "heb_scg"):
        A = pq.read_table(os.path.join(f1, "other", ed, "parts.parquet")).to_pydict()
        B = pq.read_table(os.path.join(build, "other", ed, "parts.parquet")).to_pydict()
        given = ("s", "p", "text", "class", "lemma", "strong")
        R.check(f"tan {ed} parts unchanged: s, p, text, class, lemma, strong equal f1, row by row",
                all(A[x] == B[x] for x in given))
        W = pq.read_table(os.path.join(build, "other", ed, "words.parquet"), columns=["s", "book", "chapter", "verse", "text"]).to_pydict()
        wd = {s: (b, c_, v, x) for s, b, c_, v, x in zip(W["s"], W["book"], W["chapter"], W["verse"], W["text"])}
        c, ch, bad = C.Counter(), [], 0
        for j in range(len(A["s"])):
            a = (A["lexeme"][j], A["key_rule"][j], A["basis"][j])
            b = (B["lexeme"][j], B["key_rule"][j], B["basis"][j])
            if a != b:
                rule = b[1]
                if rule not in ("H0", "H1", "H2", "K6") or (ed == "heb_scg" and rule != "K6"):
                    bad += 1
                c[f"{a[1]} -> {rule}" + (" (key moved)" if a[0] != b[0] else "") + (" (to model)" if a[2] != b[2] else "")] += 1
                w = wd.get(B["s"][j], ("?", 0, 0, ""))
                ch.append(f"{w[0]} {w[1]}:{w[2]} {w[3]} part {B['p'][j]} {B['text'][j]}: f1 {a[0]} {a[1]} {a[2]}; "
                          f"g1 {b[0]} {b[1]} {b[2]}")
        R.check(f"tan {ed} parts (1.5): lexeme, key_rule, basis differ from f1 only on H0, H1, H2 (heb_mod) and K6 parts",
                bad == 0, bad)
        R.info(f"tan {ed} parts: moves against f1", dict(sorted(c.items())))
        section(f"D23 keys ({ed})", "tan", ch, dict(sorted(c.items())))
    # ---- lexicon (D25 to D27)
    R.section("lexicon (D25 to D27 of 1.5) against f1")
    L1 = {r["lexeme"]: r for r in _tsv(os.path.join(f1, "lexicon", "lexemes.tsv"))}
    L2 = {r["lexeme"]: r for r in _tsv(os.path.join(build, "lexicon", "lexemes.tsv"))}
    R.check("tan lexicon/lexemes.tsv unchanged: lemma, strong, lang, class, tanakh equal f1 on every key of both; keys "
            "only lost by K6 and H2", all(all(L1[k][x] == L2[k][x] for x in ("lemma", "strong", "lang", "class", "tanakh"))
                                       for k in L2 if k in L1 and not k.startswith("ntx:")) and set(L2) <= set(L1),
            f"{len(L1):,} keys in f1, {len(L2):,} in g1; lost {len(set(L1) - set(L2)):,}; new {len(set(L2) - set(L1))}")
    st = C.Counter((L1[k]["state"], L2[k]["state"]) for k in L2 if k in L1 and L1[k]["state"] != L2[k]["state"])
    R.info("tan lexemes.tsv state moves against f1", {f"{a} -> {b}": n for (a, b), n in sorted(st.items())})
    G1 = C.defaultdict(set)
    G2 = C.defaultdict(set)
    rows2 = _rows(os.path.join(build, "lexicon", "groups.parquet"))
    for r in _rows(os.path.join(f1, "lexicon", "groups.parquet")):
        if r["basis"] == "derived":
            G1[r["group"]].add(r["lexeme"])
    for r in rows2:
        if r["basis"] == "derived":
            G2[r["group"]].add(r["lexeme"])
    m1 = {x: frozenset(v) for v in G1.values() for x in v}
    m2 = {x: frozenset(v) for v in G2.values() for x in v}
    c, ch = C.Counter(), []
    lem = {k: r["lemma"] for k, r in L1.items()}
    lem.update({k: r["lemma"] for k, r in L2.items()})
    for x in sorted(set(m1) | set(m2)):
        a, b = m1.get(x), m2.get(x)
        kind = ("joins" if a is None else "leaves" if b is None else "same members" if a == b else "other members")
        c[kind] += 1
        if kind != "same members":
            f = lambda s: " ".join(sorted(lem[y] for y in s)) if s else "-"  # noqa: E731
            ch.append(f"{lem[x]} ({x}): f1 [{f(a)}]; g1 [{f(b)}]")
    R.info("tan groups: strict members against f1", dict(sorted(c.items())))
    section("D25, D26 groups (strict members)", "tan", ch, dict(sorted(c.items())))
    fn = function_numbers(build)
    anc = [r for r in rows2 if r["anchor"] and r["anchor"].split(":")[1] in fn]
    R.check("tan groups (1.5): no group anchored on a function number", not anc, f"{len(fn)} function numbers, {len(anc)} rows")
    by = C.defaultdict(list)
    for r in rows2:
        by[r["group"]].append(r)
    mixed = [k for k, v in by.items() if len({L2[r["lexeme"]]["class"] for r in v}) > 1]
    R.check("tan groups (1.5): no group of two classes", not mixed, mixed[:5])
    arch = [k for k, v in by.items() if any(L2[r["lexeme"]]["lang"] == "hbo" for r in v) and
            any(r["head"] and L2[r["lexeme"]]["lang"] != "hbo" for r in v)]
    R.check("tan groups (1.5): the head is hbo wherever the group has an hbo member", not arch, arch[:5])
    loose = [(r["group"], r["lexeme"], r["ubs_depth"]) for r in rows2 if r["basis"] == "derived" and
             r["ubs_depth"] is not None and r["ubs_depth"] < 3]
    rf = open(os.path.join(build, "lexicon", "READ-FIRST.md"), encoding="utf-8").read()
    R.check("tan lexicon/READ-FIRST.md lists every loose member (ubs_depth under 3)",
            all(f"| {g} | {x} |" in rf for g, x, _ in loose), f"{len(loose)} loose members")
    R.info("tan groups: strict rows by joined_by", dict(sorted(C.Counter(r["joined_by"] for r in rows2 if r["basis"] == "derived").items())))


class Renamed:
    """SPEC 1.6: the 1.5 conditions on an h build, read against g1: the messages name g1 for f1 and h1 for g1."""

    def __init__(self, R):
        self.R = R

    def _m(self, msg):
        import re
        return re.sub(r"\bf1\b", "g1", re.sub(r"\bg1\b", "h1", msg)) if isinstance(msg, str) else msg

    def check(self, msg, *a, **k):
        return self.R.check(self._m(msg), *a, **k)

    def info(self, msg, *a, **k):
        return self.R.info(self._m(msg), *a, **k)

    def section(self, msg, *a, **k):
        return self.R.section(self._m(msg), *a, **k)

    def __getattr__(self, name):
        return getattr(self.R, name)


def run(R, build):
    if V16:      # SPEC 1.6 section 14: all of 1.5, read against g1 where they name f1; no 1.5 mends sample
        f1 = os.path.join(os.path.dirname(os.path.normpath(build)), "g1")
        R = Renamed(R)
        ctx = stage35(R, build, f1)
        moves(R, build, f1, ctx)
        R.info("sample of mends of 1.5: glossed-g1/mends-sample.md is g1's and is not rewritten (stage 38 writes "
               "glossed-h1/mends-sample.md)", "")
        return
    f1 = os.path.join(os.path.dirname(os.path.normpath(build)), "f1")
    ctx = stage35(R, build, f1)
    moves(R, build, f1, ctx)
    text = "\n".join(ctx[0]).rstrip("\n") + "\n"
    R.section("sample of mends")
    if WRITE:
        os.makedirs(os.path.dirname(SAMPLE), exist_ok=True)
        with open(SAMPLE, "w", encoding="utf-8") as fh:
            fh.write(text)
    have = open(SAMPLE, encoding="utf-8").read() if os.path.exists(SAMPLE) else None
    R.check("glossed-g1/mends-sample.md: equals the sample this check writes (every mend, its count, the fixed-rule "
            "sample)", have == text, f"{text.count(chr(10)):,} lines" if have == text else
            "missing or differs: run with --write-md")
