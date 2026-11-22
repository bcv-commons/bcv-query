"""Stage 16 of the validator (SPEC 1.1, build c1): clause values, participants, speech (strict part), unchanged.

Called by validate_examples.py (`--upto 16`), after its stage 15 (which recomputes the clauses from the lowfat files
and leaves them in STASH). Imports nothing from the builders; it reads the datasets, the layouts, the tree store, our
entities and the speech layers itself, and builds the review-free speech layers into <build>/cache/validate16-speech-*
with validate_examples_speech.py.
"""
import collections as C
import csv
import glob
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tomllib
import unicodedata as U

import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(HERE, "data")
CATS = [("kind", "clause-columns", "kind"), ("force", "clause-columns", "force"),
        ("polarity", "clause-extras", "polarity"), ("negator", "clause-columns", "neg"),
        ("neg_scope", "clause-columns", "neg_scope"), ("connective", "connectives", "conn"),
        ("relation", "connectives", "relation"), ("time", "time-aspect", "time"),
        ("aspect", "time-aspect", "aspect"), ("line_kind", "time-aspect", "band"),
        ("voice", "clause-columns", "voice"), ("transitivity", "clause-columns", "m_trans"),
        ("subject_form", "clause-columns", "subj_form"), ("subject_switch", "clause-columns", "subj_switch"),
        ("fronted", "clause-columns", "front")]
MEANING = {"relation", "time", "aspect", "line_kind"}
V13 = False        # SPEC 1.3 (e builds): set by validate_examples.py; `mood` is a D9 category, marks_model holds D9m
SCRATCH = None     # e builds: the validator's own speech layers go here (validate_examples.py sets it)


def set13():
    global V13
    V13 = True
    if not any(c[0] == "mood" for c in CATS):
        CATS.append(("mood", "clause-extras", "mood"))
    MEANING.add("mood")
NEG = {"lo": "לֹא", "en": "אַיִן", "al": "אַל", "bilti": "בֵּלֶת", "bal": "בַּל", "la": "לָא", "ou": "οὐ", "me": "μή"}
SEM_LINKED = {"lxx_nt", "lxx_nt_domain", "hebrew_domain"}
SEM_DERIVED = {"frame", "frame_passive", "hebrew_prep", "ln", "ln_speech", "ln+speech"}
TYPES = ("person", "place", "group", "deity", "realia", "flora", "fauna")
KIN = {"father", "mother", "offspring", "sibling", "partner", "tribe", "group_origin"}
NO_WHO = {"hbo": {"cj", "prep", "art"}, "arc": {"cj", "prep", "art"}, "grc": {"conj", "prep", "det"}}
ENT_RE = re.compile(r"^(person|place|group|deity|realia|flora|fauna):e[0-9a-f]{10}$")
PART_COLS = ["ent", "type", "name", "name_basis", "sex", "words", "words_model", "ent_basis"]
FALLBACK = {"hbo": ("he:",), "arc": ("arc:", "he:"), "grc": ("el:",)}
nfc = lambda s: U.normalize("NFC", s)  # noqa: E731
V12 = False          # set by validate_examples.py for a d build (SPEC 1.2)
V16 = False          # an h build (SPEC 1.6): set by validate_examples.py
V15 = False          # set by validate_examples.py for a g build (SPEC 1.5: D9's edge, Greek mood, Greek verbless time)
QMARKS = (";", "\u037e")


def c0(v):
    return re.sub(r"[^a-z0-9]+", "_", v.lower()).strip("_")


def tsv(path, corpus=None):
    csv.field_size_limit(1 << 30)
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader((ln for ln in fh if not ln.startswith("#")), delimiter="\t", quoting=csv.QUOTE_NONE))
    return rows if corpus is None else [r for r in rows if r["corpus"] == corpus]


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def ekey(acai, t):
    return f"{t}:e{hashlib.sha1(acai.encode('utf-8')).hexdigest()[:10]}"


def script_ok(s, greek):
    """The language's script; a space between words; MACULA's Latin homograph marks ` (I)`, ` (II)` at the end are
    allowed by name (SPEC 10, no English; H7)."""
    s = re.sub(r" \((I|II|III|IV)\)$", "", s)
    for ch in s:
        o = ord(ch)
        if U.category(ch) == "Zs":
            continue
        if greek:
            if not (0x0370 <= o <= 0x03FF or 0x1F00 <= o <= 0x1FFF or U.category(ch).startswith("M")):
                return False
        elif not (0x0590 <= o <= 0x05FF or 0xFB1D <= o <= 0xFB4F or o == 0x034F):
            # U+034F COMBINING GRAPHEME JOINER: MACULA writes it inside Hebrew lemmas to keep the order of points
            return False
    return True


def terms_of(build, lang):
    col = "grc" if lang == "grc" else "hbo"
    return {(r["category"], r["code"]): r[col] for r in tsv(os.path.join(build, lang, "terms.tsv"))}


# ---- clause values ---------------------------------------------------------------------------------------------

UPTO = "16"     # set by validate_examples.stage16
EXTRA = {}      # corpus -> {dataset: rows}: further datasets joined as D9 joins (stage 17, D15m)


def values(R, build, STASH):
    out = {}
    for gname in ("hbo+arc", "grc"):
        st = STASH.get(gname)
        if st is None:
            R.check(f"{gname} stage 16 needs the clauses recomputed by stage 15 (run --upto 16 whole)", False)
            continue
        greek = gname == "grc"
        corpus = "grc" if greek else "hbo"
        allc, tabs, group, plex, stem = st["allc"], st["tabs"], st["group"], st["plex"], st["stem"]
        lemma, lexkeys, cats, terms = {}, set(), {}, {}
        for lang in group:
            for r in tsv(os.path.join(build, lang, "lexemes.tsv")):
                lemma[r["lexeme"]] = r["lemma"]
                lexkeys.add(r["lexeme"])
            with open(os.path.join(build, lang, "categories.toml"), "rb") as fh:
                cats[lang] = tomllib.load(fh)
            terms[lang] = terms_of(build, lang)
        K = {lg: pq.read_table(os.path.join(build, lg, "clauses.parquet")).to_pydict() for lg in group}
        N = {lg: pq.read_table(os.path.join(build, lg, "constituents.parquet")).to_pydict() for lg in group}
        P = {lg: pq.read_table(os.path.join(build, lg, "pieces.parquet"), columns=["t", "n", "pid", "marks"]).to_pydict()
             for lg in group}
        tab = {k: (lg, j) for lg in group for j, k in enumerate(K[lg]["clause"])}
        ok = all(c["key"] in tab for c in allc) and len(tab) == len(allc)
        R.check(f"{gname} clauses: the rows are the clauses stage 15's check recomputed", ok, f"{len(tab):,}")
        if not ok:
            continue
        for lg in group:
            for col in ("marks", "line"):
                R.check(f"{lg} clauses: {col} filled on every row (never null)", None not in K[lg][col])
            for col in ("sem_role", "sem_role_basis"):
                R.check(f"{lg} constituents: {col} filled on every row (never null)", None not in N[lg][col])
        kv = lambda key, col: K[tab[key][0]][col][tab[key][1]]  # noqa: E731
        ptype = {pid: json.loads(m).get("type") for lg in group for pid, m in zip(P[lg]["pid"], P[lg]["marks"])}
        tord = sorted((P[lg]["t"][i], P[lg]["n"][i], pid) for lg in group for i, pid in enumerate(P[lg]["pid"]))
        tpos = {x[2]: i for i, x in enumerate(tord)}
        inner = {}
        for i, c in enumerate(allc):
            for p in c["rows"]:
                if p not in inner or allc[inner[p]]["depth"] < c["depth"]:
                    inner[p] = i
        wid = {t: i for lg in group for t, i in zip(tabs[lg][0]["t"], tabs[lg][0]["id"])}
        ix_of = {c["key"]: i for i, c in enumerate(allc)}

        def anchor(c):
            pred = kv(c["key"], "pred")
            if greek:
                return wid[pred or kv(c["key"], "first")][1:]
            return stem[pred][1:] if pred else c["rows"][0][1:]

        segs = []
        if greek:
            for f in sorted(glob.glob(os.path.join(DATA, "nt-clause-layout/clauses/*/*.jsonl"))):
                b, ch = os.path.basename(f)[:-6].rsplit("_", 1)
                for ln in open(f, encoding="utf-8"):
                    r = json.loads(ln)
                    segs.append((f"{b}.{int(ch)}.{r['verse']}.{r['seg']}", r["words"], r["first"], None, None))
        else:
            for f in sorted(glob.glob(os.path.join(DATA, "clause-layout/clauses/*/*.jsonl"))):
                for ln in open(f, encoding="utf-8"):
                    r = json.loads(ln)
                    segs.append((f"{r['book']}.{r['chapter']}.{r['verse']}.{r['seg']}", r["words"], r["first"],
                                 r["clause_key"], r["clause"]))
        seg_of = {w: si for si, s in enumerate(segs) for w in s[1]}
        bad = sum(1 for c in allc if kv(c["key"], "line") != (segs[seg_of[anchor(c)]][0] if anchor(c) in seg_of else ""))
        R.check(f"{gname} clauses: line equals D11 recomputed", bad == 0, bad)
        # D9 joins
        data = {"clause-columns": pq.read_table(os.path.join(
            DATA, "clause-columns/greek-nt.parquet" if greek else "clause-columns/hebrew.parquet")).to_pylist()}
        for ds in ("clause-extras", "connectives", "time-aspect"):
            data[ds] = tsv(os.path.join(DATA, ds, "clauses.tsv"), corpus)
        data.update(EXTRA.get(corpus, {}))          # stage 17: D15m joins as D9 (set by validate_examples)
        rows_of = {}
        dkey = lambda k: (allc[ix_of[k]]["depth"], ix_of[k])  # noqa: E731
        if not greek:
            db = sqlite3.connect(f"file:{os.path.join(HERE, 'trees-macula.db')}?mode=ro", uri=True)
            tr = db.execute("select id, rule from nodes where corpus='hbo' and cls='cl' order by id").fetchall()
            db.close()
            rank_of = {tid: r for r, (tid, _x) in enumerate(tr)}
            k2c = C.defaultdict(set)
            for s in segs:
                k2c[s[3]].add(s[4])
            for ds, rows in data.items():
                got = {}
                for r in rows:
                    ids = k2c.get(r["clause_key"], set())
                    if len(ids) == 1 and next(iter(ids)) in rank_of:
                        got.setdefault(allc[rank_of[next(iter(ids))]]["key"], r)
                rows_of[("conn", ds)] = rows_of[("main", ds)] = got
                R.info(f"hbo+arc D9 {ds}: rows {len(rows):,}, joined {len(got):,}", f"found no clause {len(rows) - len(got):,}")
        else:
            first2 = {s[2]: si for si, s in enumerate(segs)}
            cand = C.defaultdict(list)
            for c in allc:
                if anchor(c) in seg_of:
                    cand[seg_of[anchor(c)]].append(c["key"])
            ch = {"conn": {si: min(ks, key=dkey) for si, ks in cand.items()},
                  "main": {si: min([k for k in ks if kv(k, "pred")] or ks, key=dkey) for si, ks in cand.items()}}
            R.info("grc D9 C2: segments whose non-connective categories go to another clause than connective",
                   sum(1 for si in ch["conn"] if ch["conn"][si] != ch["main"][si]))
            for join in ("conn", "main"):
                for ds, rows in data.items():
                    got = {}
                    for r in rows:
                        si = first2.get(r["clause_key"])
                        if si in ch[join]:
                            got[ch[join][si]] = r
                    rows_of[(join, ds)] = got
                    R.info(f"grc D9 ({join}) {ds}: rows {len(rows):,}, joined {len(got):,}",
                           f"found no clause {len(rows) - len(got):,}")

        STASH[f"s16 rows_of {gname}"] = rows_of

        def match(items, pool):
            taken, res = set(), []
            for it in items:
                hit = next(((p, x) for p, x, lm in pool if p not in taken and lm == it), None) or \
                    next(((p, x) for p, x, lm in pool if p not in taken and nfc(lm) == nfc(it)), None)
                if hit:
                    taken.add(hit[0])
                res.append(hit[1] if hit else None)
            return res

        def before(c):
            par = c["parent"]
            j = min(tpos[p] for p in c["rows"]) - 1
            run = []
            while j >= 0 and inner.get(tord[j][2]) in (None, par):
                run.append(tord[j][2])
                j -= 1
            return run[::-1]

        bad = C.Counter()
        moved15 = C.Counter()
        after_w = {}
        if V15 and greek:
            for lg in group:
                W_ = pq.read_table(os.path.join(build, lg, "words.parquet"), columns=["t", "after"]).to_pydict()
                after_w.update(zip(W_["t"], W_["after"]))
        use = {lg: C.defaultdict(C.Counter) for lg in group}
        vc_none = C.Counter()
        tof = {x[2]: x[0] for x in tord}
        post = set()
        edge_left, edge_at = C.Counter(), C.Counter()
        if V12 and greek:     # SPEC 1.2 D9: postpositive lexemes, counted from the joined connectives rows
            n_all, n_2 = C.Counter(), C.Counter()
            for i, c in enumerate(allc):
                r = rows_of[("conn", "connectives")].get(c["key"])
                if r is None:
                    continue
                span = sorted(c["rows"], key=tpos.get)
                ws = list(dict.fromkeys(tof[p] for p in span))
                for it in (r["conn"] or "").split():
                    p = next((q for q in span if nfc(lemma[plex[q]]) == nfc(it)), None)
                    if p is not None:
                        n_all[plex[p]] += 1
                        n_2[plex[p]] += len(ws) > 1 and tof[p] == ws[1]
            post = {x for x in n_all if 2 * n_2[x] > n_all[x]}
            R.info("grc D9 postpositive lexemes, recomputed (second word / places)",
                   {x: f"{n_2[x]}/{n_all[x]}" for x in sorted(post)})
            kai = [x for x in n_all if x.endswith(":καί")]
            R.info("grc D9 καί at the second word / places", {x: f"{n_2[x]}/{n_all[x]}" for x in kai})

        def anc_of(i):
            out, p = set(), allc[i]["parent"]
            while p is not None and p != "":
                out.add(p)
                p = allc[p]["parent"]
            return out

        def before15(i, c):
            """SPEC 1.5 D9 (2): the run before through every ancestor clause; stops at a piece of another clause."""
            anc = anc_of(i)
            j = min(tpos[p] for p in c["rows"]) - 1
            run = []
            while j >= 0 and (inner.get(tord[j][2]) is None or inner.get(tord[j][2]) in anc):
                run.append(tord[j][2])
                j -= 1
            return run[::-1]

        def edge(i, c, items):
            """SPEC 1.2 D9, written apart from the builder: the edge pools in order, an item to the first free piece."""
            span = sorted(c["rows"], key=tpos.get)
            ws = list(dict.fromkeys(tof[p] for p in span))
            ownw = C.defaultdict(list)
            for p in span:
                if inner[p] == i:
                    ownw[tof[p]].append((p, plex[p], lemma[plex[p]]))
            got, used = {}, set()

            def take(pool, where):
                any_ = False
                for j, it in enumerate(items):
                    if j in got:
                        continue
                    free = [x for x in pool if x[0] not in used]
                    hit = next((x for x in free if x[2] == it), None) or next(
                        (x for x in free if nfc(x[2]) == nfc(it)), None)
                    if hit:
                        got[j] = hit[1]
                        used.add(hit[0])
                        edge_at[(tab[c["key"]][0], where)] += 1
                        any_ = True
                return any_
            w = 0
            if not V15:
                while w < len(ws) and take(ownw.get(ws[w], []), "first word" if w == 0 else "leading run"):
                    w += 1
            else:       # SPEC 1.5 D9 (1): the first word's pieces before the clause's first piece open the edge
                f0 = tpos[span[0]]
                pre, j = [], f0 - 1
                while j >= 0 and tof[tord[j][2]] == ws[0]:
                    pre.append(tord[j][2])
                    j -= 1
                while w < len(ws):
                    a = take([(p, plex[p], lemma[plex[p]]) for p in pre[::-1]], "1.5 (1) first word before the clause") \
                        if w == 0 else False
                    b = take(ownw.get(ws[w], []), "first word" if w == 0 else "leading run")
                    if not (a or b):
                        break
                    w += 1
            if greek and (w == 0 if not V15 else w < 2) and len(ws) > 1:
                take([x for x in ownw.get(ws[1], []) if x[1] in post], "postpositive second word")
                if V15:    # SPEC 1.5 D9 (3): a postpositive in the gap of the clause right after its first word
                    lo = max(tpos[p] for p in span if tof[p] == ws[0])
                    hi = min(tpos[p] for p in span if tof[p] == ws[1])
                    sp_ = set(c["rows"])
                    take([(tord[j][2], plex[tord[j][2]], lemma[plex[tord[j][2]]]) for j in range(lo + 1, hi)
                          if tord[j][2] not in sp_ and plex[tord[j][2]] in post], "1.5 (3) postpositive in the gap")
            if len(got) < len(items):
                old = before(c)
                take([(p, plex[p], lemma[plex[p]]) for p in old], "run before")
                if V15 and len(got) < len(items):
                    olds = set(old)
                    take([(p, plex[p], lemma[plex[p]]) for p in before15(i, c) if p not in olds],
                         "1.5 (2) run before through an ancestor")
            for j, it in enumerate(items):
                if j not in got:
                    edge_left[(tab[c["key"]][0], it)] += 1
            return [got[j] for j in range(len(items)) if j in got]
        for i, c in enumerate(allc):
            own = [(p, plex[p], lemma[plex[p]]) for p in c["rows"] if inner[p] == i]
            exp = {}
            for cat, ds, col in CATS:
                r = rows_of[("conn" if cat == "connective" else "main", ds)].get(c["key"])
                if r is None:
                    continue
                v = r[col]
                if cat == "negator":
                    if v:
                        pool = own + ([(p, plex[p], lemma[plex[p]]) for p in before(c)] if V12 else [])
                        g = match([NEG[v]], pool)[0]
                        if g:
                            exp[cat] = g
                elif cat == "connective" and V12:
                    items = (v or "").split()
                    if items:
                        keys = edge(i, c, items)
                        if keys:
                            exp[cat] = keys
                elif cat == "connective":
                    items = (v or "").split()
                    if items:
                        g1 = match(items, own)
                        rest = [it for it, g in zip(items, g1) if g is None]
                        g2 = iter(match(rest, [(p, plex[p], lemma[plex[p]]) for p in before(c)]))
                        keys = [g if g is not None else next(g2) for g in g1]
                        keys = [k for k in keys if k]
                        if keys:
                            exp[cat] = keys
                elif cat == "transitivity":
                    if v is not None:
                        exp[cat] = c0(str(v))
                elif cat == "fronted" and v in (None, ""):
                    exp[cat] = "none"
                else:
                    code = None if v in (None, "") else c0(str(v))
                    if cat == "force" and code == "declarative" and r.get("interrog") is True:
                        code = "interrogative"
                    if cat == "voice" and not greek:
                        pred = kv(c["key"], "pred")
                        if pred and ptype.get(stem[pred]) == "participle_passive":
                            code = "passive"
                    if code is not None:
                        exp[cat] = terms[tab[c["key"]][0]].get((cat, code), f"NO TERM {code}") if cat in MEANING \
                            else code
            lg, j = tab[c["key"]]
            if V15 and greek:     # SPEC 1.5 D9: Greek interrogative mood (A11), verbless time (A6)
                tl = terms[lg]
                if exp.get("mood") == tl.get(("mood", "interrogative")):
                    word = any(ptype.get(p) == "interrogative" for p, _x, _l in own)
                    qm = any(q in (after_w.get(kv(c["key"], "last")) or "") for q in QMARKS)
                    if not (word or qm):
                        exp["mood"] = tl[("mood", "conditional" if exp.get("relation") == tl.get(("relation", "conditional"))
                                          else "irrealis" if exp.get("time") == tl.get(("time", "irrealis"))
                                          else "declarative")]
                        moved15["mood"] += 1
                ta = rows_of[("main", "time-aspect")].get(c["key"])
                if ta is not None and ta["basis"] == "grc:verbless":
                    moved15["verbless"] += 1
                    import validate_examples_s35 as S35
                    S35.VERBLESS.add(c["key"])
                    exp.pop("time", None)
                    exp.pop("aspect", None)
            raw = K[lg]["marks"][j]
            have = json.loads(raw)
            if V13:       # SPEC 1.3 D16: time_abs is checked by stage 28
                have.pop("time_abs", None)
            if V13 and K[lg].get("marks_model") is not None and K[lg]["marks_model"][j]:
                mmj = json.loads(K[lg]["marks_model"][j])
                mmj.pop("time_abs", None)
                merged = dict(have, **mmj)
                bad["marks"] += merged != exp or len(merged) != len(have) + len(mmj)
            else:
                bad["marks"] += have != exp
            bad["form"] += raw != json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            for cat, v in have.items():
                for x in (v if isinstance(v, list) else [v]):
                    if cat in ("negator", "connective") and x not in lexkeys:
                        bad["lexkeys"] += 1
                for x in (set(v) if isinstance(v, list) else [v]):
                    use[lg][cat][x] += 1
            if have.get("kind") == "vc" and kv(c["key"], "pred_kind") == "none":
                vc_none[lg] += 1
        if V15 and greek:
            R.info("grc 1.5 D9 recomputed: interrogative mood moved / verbless clauses (time, aspect taken out)",
                   f"{moved15['mood']:,} / {moved15['verbless']:,}")
        if V12:
            for lg in group:
                left = {it: n for (l_, it), n in sorted(edge_left.items(), key=lambda kv: -kv[1]) if l_ == lg}
                R.info(f"{lg} D9 connective items left out by the edge rule, recomputed: {sum(left.values()):,}; by lemma",
                       left)
                R.info(f"{lg} D9 connective items matched, by edge pool",
                       {w: n for (l_, w), n in sorted(edge_at.items()) if l_ == lg})
        R.check(f"{gname} clauses: marks equal D9 recomputed ({'1.2: the edge, postpositives, negator run before' if V12 else '1.1: C2, C3, C4, C6, C12'}, terms)", bad["marks"] == 0,
                bad["marks"])
        R.check(f"{gname} clauses: marks are JSON, keys sorted, no spaces", bad["form"] == 0, bad["form"])
        R.check(f"{gname} clauses: every lexeme key in negator, connective is in lexemes.tsv", bad["lexkeys"] == 0,
                bad["lexkeys"])
        for lg in group:
            cl = cats[lg].get("clauses", {})
            n = len(K[lg]["clause"])
            for cat, ds, col in CATS:
                sec = cl.get(cat)
                u = use[lg][cat]
                if not u:
                    R.check(f"{lg} categories.toml: no [clauses.{cat}] where no clause has it", sec is None)
                    continue
                if sec is None:
                    R.check(f"{lg} categories.toml: [clauses.{cat}] declared", False)
                    continue
                if cat in MEANING:
                    decl = {v["term"]: v["count"] for v in sec["values"]}
                    tok = all(terms[lg].get((cat, v["code"])) == v["term"] for v in sec["values"])
                    R.check(f"{lg} categories.toml clauses.{cat}: every term declared with its code (terms.tsv) and "
                            "count", decl == dict(u) and tok, f"{len(u)} terms")
                    R.check(f"{lg} clauses.{cat}: every term is in the language's script",
                            all(script_ok(t, lg == "grc") for t in u))
                else:
                    decl = {v["code"]: v["count"] for v in sec["values"]}
                    R.check(f"{lg} categories.toml clauses.{cat}: every value declared with its count",
                            decl == dict(u), f"{len(u)} codes")
                fok = sec.get("form_or_reading") in ("form", "reading") and sec.get("dataset") == ds and \
                    sec.get("dataset_column") == col and os.path.isfile(os.path.join(HERE, sec.get("file", "-")))
                R.check(f"{lg} categories.toml clauses.{cat}: dataset, column, form or reading, sha256 of the file",
                        fok and sha(os.path.join(HERE, sec["file"])) == sec.get("sha256"))
                R.info(f"{lg} {cat}: clauses with a value", f"{sum(u.values()) if cat != 'connective' else sum(1 for m in K[lg]['marks'] if 'connective' in json.loads(m)):,} of {n:,}")
            R.info(f"{lg} kind: clauses with kind vc and pred_kind none (AUDIT 3, listed in the build's counts)",
                   vc_none[lg])
        # D12
        roles = tsv(os.path.join(DATA, "arg-roles/roles.tsv"), corpus)
        byh, byw = C.defaultdict(list), C.defaultdict(list)
        for r in roles:
            if r["head"]:
                byh[r["head"]].append(r)
            byw[tuple(sorted(r["words"].split()))].append(r)
        exp_sem = {}
        for c in allc:
            for o, x in enumerate(c["cons"], 1):
                words = tuple(sorted(p[1:] for p in x["rows"]))
                cand = byh.get(x["hp"][1:], [])
                if len(cand) > 1:
                    cand = [r for r in cand if tuple(sorted(r["words"].split())) == words]
                if not byh.get(x["hp"][1:]):
                    cand = byw.get(words, [])
                e = ("", "")
                if len(cand) == 1 and cand[0]["role"] not in ("", "-"):
                    b = cand[0]["role_basis"]
                    t = terms[tab[c["key"]][0]].get(("sem_role", c0(cand[0]["role"])), "NO TERM")
                    if V12:     # SPEC 1.2 D12
                        core = b[:-7] if b.endswith("+speech") else b
                        e = (t, "linked") if core.startswith("lxx_") or core == "hebrew_domain" else (t, "derived")
                    else:
                        e = (t, "linked") if b in SEM_LINKED else (t, "derived") if b in SEM_DERIVED else ("", "")
                exp_sem[(c["key"], o)] = e
        if V13:       # SPEC 1.3 D12c: o, o2 read as actor under a causative stem -> undergoer, derived
            import validate_examples_s28 as S28
            for lg in group:
                act, und = terms[lg][("sem_role", "actor")], terms[lg][("sem_role", "undergoer")]
                for key in S28.d12c_moves(build, lg, act):
                    if exp_sem.get(key, ("",))[0] == act:
                        exp_sem[key] = (und, "derived")
        if V15:       # SPEC 1.5 D12c: the causer (s, AA, causative stem) takes actor where D12 gives none
            import validate_examples_s35 as S35
            for lg in group:
                keys = [k for k in exp_sem if tab[k[0]][0] == lg]
                n1 = {"clause": [k[0] for k in keys], "ord": [k[1] for k in keys],
                      "sem_role": [exp_sem[k][0] for k in keys]}
                for key in S35.causer_rows(R, build, lg, n1):
                    exp_sem[key] = (terms[lg][("sem_role", "actor")], "derived")
        for lg in group:
            got = {(k, o): (s, b) for k, o, s, b in zip(N[lg]["clause"], N[lg]["ord"], N[lg]["sem_role"],
                                                       N[lg]["sem_role_basis"])}
            d = sum(1 for k, v in got.items() if exp_sem.get(k) != v)
            R.check(f"{lg} constituents: sem_role, sem_role_basis equal D12 recomputed (C11, the bases of D12)",
                    d == 0 and len(got) == sum(1 for k in exp_sem if tab[k[0]][0] == lg), d)
            have = C.Counter(s for s, b in got.values() if s)
            sec = cats[lg].get("constituents", {}).get("sem_role")
            decl = {v["term"]: v["count"] for v in sec["values"]} if sec else {}
            tok = sec is not None and all(terms[lg].get(("sem_role", v["code"])) == v["term"] for v in sec["values"])
            R.check(f"{lg} categories.toml constituents.sem_role: every term declared with its code and count",
                    decl == dict(have) and tok, f"{len(have)} terms")
            hb = C.Counter(b for s, b in got.values() if b)
            secb = cats[lg].get("constituents", {}).get("sem_role_basis")
            declb = {v["code"]: v["count"] for v in secb["values"]} if secb else {}
            R.check(f"{lg} categories.toml constituents.sem_role_basis declared with counts", declb == dict(hb),
                    dict(hb))
            R.check(f"{lg} constituents: sem_role and sem_role_basis empty together",
                    all((s == "") == (b == "") for s, b in got.values()))
            R.info(f"{lg} constituents with sem_role", f"{sum(have.values()):,} of {len(got):,}; by basis {dict(hb)}")
        out[gname] = dict(tab=tab, K=K)
    return out


# ---- participants ---------------------------------------------------------------------------------------------

def participants(R, build, src):
    heb, grc_src, nodes = src
    ent_rows = {r["entity"]: r for r in tsv(os.path.join(DATA, "entities", "entities.tsv"))}

    def ent(a):
        r = ent_rows.get(a)
        return ekey(a, r["type"]) if r and r["type"] in TYPES else None

    rows, begins = C.defaultdict(set), C.defaultdict(set)
    with open(os.path.join(DATA, "entities", "entity_words.tsv"), encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
            if r["kind"] in ("explicit", "pronominal", "subject"):
                e = ent(r["entity"])
                if e:
                    pid = ("n" if len(r["word"]) == 11 else "o") + r["word"]
                    rows[(pid, r["kind"])].add(e)
                    if r["kind"] == "explicit" and r["instance"] == r["word"]:
                        begins[pid].add(e)
    morph = {mid: pid for pid, mid, _ in nodes}
    refs = {}
    for _, sents in heb:
        for ws, _ in sents:
            for w in ws:
                r = w[9] or w[10]
                if r:
                    refs[w[0]] = [morph.get(x) for x in r.split()]
    import xml.etree.ElementTree as ET
    for f in sorted(glob.glob(os.path.join(HERE, ".lowfat-src-grc", "*.xml"))):
        for w in ET.parse(f).getroot().iter("w"):
            r = w.get("referent") or w.get("subjref")
            if r:
                refs[w.get("{http://www.w3.org/XML/1998/namespace}id")] = r.split()
    T = {}
    for lang in ("hbo", "arc", "grc"):
        d = os.path.join(build, lang)
        T[lang] = dict(P=pq.read_table(os.path.join(d, "pieces.parquet"), columns=[
            "t", "n", "pid", "kind", "class", "lexeme", "marks", "who", "who_basis"]).to_pydict(),
            W=pq.read_table(os.path.join(d, "words.parquet"), columns=["t", "head"]).to_pydict(),
            K=pq.read_table(os.path.join(d, "clauses.parquet"), columns=["clause", "speaker", "addressee"]).to_pydict(),
            lemma={r["lexeme"]: r["lemma"] for r in tsv(os.path.join(d, "lexemes.tsv"))},
            terms=terms_of(build, lang))
    d7r = {}
    if V13:           # SPEC 1.3 D7r: where steps 1 to 4 give none
        import validate_examples_s28 as S28
        d7r = S28.d7r_candidates(build)
    base = {}
    for lang in T:
        P = T[lang]["P"]
        for pid, kind in zip(P["pid"], P["kind"]):
            for k in ("explicit", "pronominal", "subject"):
                es = rows.get((pid, k))
                if es and k == "explicit" and kind == "suffix":
                    es = begins.get(pid)
                if es:
                    base[pid] = (es, k)
                    break
    kin = tsv(os.path.join(DATA, "entities", "kinship.tsv"))
    acai_of = {ekey(a, r["type"]): a for a, r in ent_rows.items() if r["type"] in TYPES}
    god = {ekey(a, "deity") for a, r in ent_rows.items() if r["primary"] == "deity:Lord" and r["type"] == "deity"}
    for lang, D in T.items():
        P, greek = D["P"], lang == "grc"
        # the strict view (SPEC 2.3): a `who` of basis model (D7m, stage 17) is empty
        P["who"] = ["" if b == "model" else w for w, b in zip(P["who"], P["who_basis"])]
        P["who_basis"] = ["" if b == "model" else b for b in P["who_basis"]]
        bad = C.Counter()
        for pid, cl, who, wb in zip(P["pid"], P["class"], P["who"], P["who_basis"]):
            got = base.get(pid)
            if got is None and pid in refs:
                es = set()
                for tp in refs[pid]:
                    if tp in base:
                        es |= base[tp][0]
                if es:
                    got = (es, "chain")
            if got and cl in NO_WHO[lang] and got[1] != "explicit" and not (
                    greek and cl == "det" and got[1] in ("pronominal", "chain")):
                got = None
            if got is None and pid in d7r and not (cl in NO_WHO[lang] and not (greek and cl == "det")):
                got = ({d7r[pid][0]}, "reference")
            want = ("", "") if got is None else (" ".join(sorted(got[0])), got[1])
            bad["differ"] += (who, wb) != want
            bad["null"] += who is None or wb is None
            bad["key"] += bool(who) and (any(not ENT_RE.match(x) for x in who.split()) or
                                         who.split() != sorted(set(who.split())))
        R.check(f"{lang} pieces: who, who_basis never null", bad["null"] == 0, bad["null"])
        R.check(f"{lang} pieces: who, who_basis equal D7 recomputed (1.1: suffix step 1, Greek det)",
                bad["differ"] == 0, bad["differ"])
        R.check(f"{lang} pieces: every who is ent keys, sorted, each once", bad["key"] == 0, bad["key"])
        bas = C.Counter(v for v in P["who_basis"] if v)
        R.check(f"{lang} pieces: who_basis is a strict step (explicit, pronominal, subject, chain)",
                set(bas) <= {"explicit", "pronominal", "subject", "chain"} | ({"reference"} if V13 else set()), dict(bas))
        on = C.Counter((cl, b) for cl, b in zip(P["class"], P["who_basis"]) if b and cl in NO_WHO[lang])
        badon = sum(v for (cl, b), v in on.items() if b != "explicit" and not (greek and cl == "det" and
                                                                               b in ("pronominal", "chain")))
        R.check(f"{lang} pieces: no who on a conjunction, preposition, article piece unless explicit "
                "(Greek det: pronominal, chain too)", badon == 0, badon)
        R.info(f"{lang} who on such pieces (allowed)", dict(sorted(on.items())))
        # participants.tsv
        prow_all = tsv(os.path.join(build, lang, "participants.tsv"))
        # stage 17 adds rows of ent_basis `model`; the checks of stage 16 read the strict view (SPEC 2.3)
        prow = [r for r in prow_all if r.get("ent_basis") != "model"]
        if UPTO < "17":
            R.check(f"{lang} participants.tsv: no row of ent_basis model before stage 17", len(prow) == len(prow_all))
        R.check(f"{lang} participants.tsv: columns of SPEC 4.5", bool(prow) and list(prow[0]) == PART_COLS)
        have = {r["ent"]: r for r in prow}
        R.check(f"{lang} participants.tsv: every ent once, sorted", [r["ent"] for r in prow] == sorted(have))
        wordset, namec = C.defaultdict(set), C.defaultdict(C.Counter)
        for t, k, cl, lx, w, b in zip(P["t"], P["kind"], P["class"], P["lexeme"], P["who"], P["who_basis"]):
            for e in w.split():
                wordset[e].add(t)
                if b == "explicit" and k == "stem" and cl in ("noun", "adj") and not (
                        V12 and nfc(D["lemma"][lx]) == nfc("הַ")):         # SPEC 1.2 D7n
                    namec[e][nfc(D["lemma"][lx])] += 1
        sp = {x for x in D["K"]["speaker"] if x}
        ad = {x for x in D["K"]["addressee"] if x}
        allents = set(wordset) | sp | ad
        if V13:      # SPEC 1.3 4.5: and added.who
            aw = {e for x in pq.read_table(os.path.join(build, lang, "added.parquet"), columns=["who"]).column(0).to_pylist()
                  if x for e in x.split()}     # SPEC 1.5: several entities, separated by a space
            R.info(f"{lang} participants only through added.who (1.3)", len(aw - allents))
            allents |= aw
        R.check(f"{lang} participants: every ent in who, speaker, addressee{', added.who' if V13 else ''} is in participants.tsv, and no other",
                allents == set(have), f"{len(allents ^ set(have))} differ")
        code_of = {v: k[1] for k, v in D["terms"].items() if k[0] == "ent_type"}
        pb = C.Counter()
        for e, r in have.items():
            a = acai_of.get(e)
            if a is None:
                pb["no ACAI id"] += 1
                continue
            er = ent_rows[a]
            tail = a.partition(":")[2]
            if V13 and (tail.startswith("Generic") or tail in ("Messenger", "Messengers")):   # SPEC 1.3 D7n
                nm, nb = "", ""
            elif namec[e]:
                top = max(namec[e].values())
                nm, nb = min(x for x, v in namec[e].items() if v == top), "derived"
            else:
                lem = er["lemmas"].split(" | ")
                nm = next((x[len(p):] for p in FALLBACK[lang] for x in lem if x.startswith(p)), "")
                nb = "given" if nm else ""
            want = {"ent": e, "type": D["terms"].get(("ent_type", er["type"]), "NO TERM"), "name": nm,
                    "name_basis": nb, "sex": {"male": "m", "female": "f"}.get(er["gender"], ""),
                    "words": str(len(wordset.get(e, ()))), "words_model": "", "ent_basis": "given"}
            pb["differ"] += r != want
            pb["script"] += bool(r["name"]) and not script_ok(r["name"], greek)
            pb["type"] += code_of.get(r["type"]) != e.split(":")[0]
        R.check(f"{lang} participants.tsv: rows equal those recomputed (type term, name D7n, name_basis, sex, words; "
                "words_model empty, ent_basis given)", pb["differ"] + pb["no ACAI id"] == 0, dict(pb))
        R.check(f"{lang} participants.tsv: the type term stands for the key's type", pb["type"] == 0, pb["type"])
        R.check(f"{lang} participants.tsv: every name in the language's script (spaces allowed)", pb["script"] == 0,
                pb["script"])
        nbc = C.Counter(r["name_basis"] or "unnamed" for r in prow)
        R.info(f"{lang} participants: rows; named derived / given / unnamed", f"{len(prow):,}; {nbc['derived']:,} / "
               f"{nbc['given']:,} / {nbc['unnamed']:,}")
        with open(os.path.join(build, lang, "categories.toml"), "rb") as fh:
            cats = tomllib.load(fh)
        tc = C.Counter(r["type"] for r in prow_all)
        sec = cats.get("participants", {}).get("type", {})
        R.check(f"{lang} categories.toml participants.type: every term declared with its code and count",
                {v["term"]: v["count"] for v in sec.get("values", [])} == dict(tc) and
                all(D["terms"].get(("ent_type", v["code"])) == v["term"] for v in sec.get("values", [])))
        for tabn, col, vals in (("pieces", "who_basis", [v for v in P["who_basis"] if v]),
                                ("participants", "name_basis", [r["name_basis"] for r in prow_all if r["name_basis"]]),
                                ("participants", "ent_basis", [r["ent_basis"] for r in prow_all])):
            sec = cats.get(tabn, {}).get(col, {})
            R.check(f"{lang} categories.toml {tabn}.{col}: every code declared with its count",
                    {v["code"]: v["count"] for v in sec.get("values", [])} == dict(C.Counter(vals)))
        # kin
        F = pq.read_table(os.path.join(build, lang, "facts.parquet")).to_pydict()
        keep = [i for i, rel in enumerate(F["relation"]) if rel in KIN]
        got = [(F["subject"][i], F["relation"][i], F["object"][i]) for i in keep]
        want = sorted({(ent(r["entity"]), r["relation"], ent(r["other"])) for r in kin if r["relation"] in KIN
                       and ent(r["entity"]) in have and ent(r["other"]) in have})
        R.check(f"{lang} facts: kin rows equal kinship.tsv between participants (ent_basis given), sorted",
                got == want, f"{len(got):,} rows")
        R.check(f"{lang} facts: kin rows kind given, method kinship.tsv:relation, source acai, scores empty",
                all((F["kind"][i], F["method"][i], F["source"][i], F["confidence"][i], F["count"][i], F["share"][i],
                     F["tier"][i]) == ("given", "kinship.tsv:relation", "acai", None, None, None, "") for i in keep))
        R.info(f"{lang} facts kin rows by relation", dict(sorted(C.Counter(g[1] for g in got).items())))
        # source errors
        ty = {e: ent_rows[a]["type"] for e, a in acai_of.items()}
        stem_lemma = {t: nfc(D["lemma"][lx]) for t, k, lx in zip(P["t"], P["kind"], P["lexeme"]) if k == "stem"}
        W = D["W"]
        deps = C.defaultdict(set)
        for t, h in zip(W["t"], W["head"]):
            if h:
                deps[h].add(t)
        nxt = {W["t"][i]: W["t"][i + 1] for i in range(len(W["t"]) - 1)}
        exp = {"SE1": [], "SE2": []}
        for t, n, k, lx, who, wb, cl, mk in zip(P["t"], P["n"], P["kind"], P["lexeme"], P["who"], P["who_basis"],
                                                 P["class"], P["marks"]):
            if not who or wb != "explicit":
                continue
            es = who.split()
            if not greek and nfc(D["lemma"][lx]) in {nfc("אֱלֹהִים"), nfc("אֱלָהּ")} and god & set(es):
                if any(stem_lemma.get(x) in {nfc("אַחֵר"), nfc("נֵכָר")} for x in deps.get(t, ())) or (
                        json.loads(mk).get("state") == "cstr" and stem_lemma.get(nxt.get(t)) == nfc("נֵכָר")):
                    exp["SE1"].append((t, n, who))
            if k == "stem" and cl == "verb" and all(ty[e] in ("fauna", "flora", "realia") for e in es):
                exp["SE2"].append((t, n, who))
        want = [{"rule": r, "source": "acai", "place": f"{t}.{n}", "value": w, "count": str(len(exp[r]))}
                for r in ("SE1", "SE2") for t, n, w in sorted(exp[r])]
        if V12:   # SE3, SE4 (SPEC 7)
            se3 = sorted((t, n, cl) for t, n, k, lx, cl in zip(P["t"], P["n"], P["kind"], P["lexeme"], P["class"])
                         if not greek and k == "stem" and nfc(D["lemma"][lx]) == nfc("הַ") and cl != "art")
            pre = sum(1 for k, lx, cl in zip(P["kind"], P["lexeme"], P["class"])
                      if not greek and k != "stem" and nfc(D["lemma"][lx]) == nfc("הַ") and cl != "art")
            if not greek:
                R.info(f"{lang} SE3: prefix or suffix pieces of lemma הַ whose class is not art, not rows (for the specification)", pre)
            want += [{"rule": "SE3", "source": "macula", "place": f"{t}.{n}", "value": cl, "count": str(len(se3))}
                     for t, n, cl in se3]
            se4 = []
            if greek:
                Kc = pq.read_table(os.path.join(build, lang, "clauses.parquet"), columns=["clause", "first", "marks"]).to_pydict()
                rel = {r["code"]: r["grc"] for r in tsv(os.path.join(build, lang, "terms.tsv")) if r["category"] == "relation"}["relative"]
                for ck, f, mk in zip(Kc["clause"], Kc["first"], Kc["marks"]):
                    if json.loads(mk).get("relation") == rel and stem_lemma.get(f) == nfc("ὅς") and \
                            stem_lemma.get(f + 1) in {nfc("μέν"), nfc("δέ")} and stem_lemma.get(f + 2) not in {nfc("ἄν"), nfc("ἐάν")}:
                        se4.append(ck)
                want += [{"rule": "SE4", "source": "connectives", "place": ck, "value": rel, "count": str(len(se4))}
                         for ck in se4]
                R.info("grc SE4 (stage 21 counted 75, stage 22 69 with ἄν/ἐάν, 53 without)", len(se4))
            if not greek:
                R.info(f"{lang} SE3 pieces (c1: hbo 49)", f"{len(se3)}: by class {dict(C.Counter(x[2] for x in se3))}")
        got = tsv(os.path.join(build, lang, "source_errors.tsv"))
        if V16:      # SPEC 1.6: SE5 (the added rows of who_reason disagree) is recomputed by stage 38
            got = [r for r in got if r["rule"] != "SE5"]
        R.check(f"{lang} source_errors.tsv: rows equal the SE queries recomputed" + (" (SE1 to SE4; SE5 in stage 38)"
                                                                                   if V16 else ""), got == want,
                f"SE1 {len(exp['SE1'])}, SE2 {len(exp['SE2'])}")
    return T


# ---- speech -----------------------------------------------------------------------------------------------------

def speech(R, build, V):
    folders = {}
    for lang in ("hbo", "grc"):
        f = os.path.join(SCRATCH or os.path.join(build, "cache"), f"validate16-speech-{lang}")
        os.makedirs(f, exist_ok=True)
        log = f + ".log"
        with open(log, "w", encoding="utf-8") as fh:
            r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "validate_examples_speech.py"), lang, f],
                               stdout=fh, stderr=subprocess.STDOUT)
        R.check(f"{lang} speech: the validator built the review-free layer itself", r.returncode == 0, log)
        folders[lang] = f
    seg = {}
    for f in glob.glob(os.path.join(folders["hbo"], "segments", "*.tsv")):
        b = os.path.basename(f)[:-4]
        for r in tsv(f):
            seg[f"{b}.{r['chapter']}.{r['verse']}.{r['seg']}"] = r["quotation"]
    for f in glob.glob(os.path.join(DATA, "nt-clause-layout", "clauses", "*", "*.jsonl")):
        b, ch = os.path.basename(f)[:-6].rsplit("_", 1)
        for ln in open(f, encoding="utf-8"):
            r = json.loads(ln)
            seg[f"{b}.{int(ch)}.{r['verse']}.{r['seg']}"] = r["quotation"] or ""
    hq = {r["id"]: r for r in tsv(os.path.join(folders["hbo"], "quotations.tsv"))}
    gq = {r["id"]: r for r in tsv(os.path.join(folders["grc"], "quotations.tsv"))}
    pub = {r["id"]: r for r in tsv(os.path.join(DATA, "speaker-layer", "quotations.tsv"))}
    R.info("hbo speech: quotations review-free / reviewed (published layer)", f"{len(hq):,} / {len(pub):,}")
    R.info("hbo speech: only reviewed / only review-free / other speaker id / other span",
           f"{len(set(pub) - set(hq))} / {len(set(hq) - set(pub))} / "
           f"{sum(1 for q in hq if q in pub and pub[q]['speaker_id'] != hq[q]['speaker_id'])} / "
           f"{sum(1 for q in hq if q in pub and (pub[q]['first'], pub[q]['last']) != (hq[q]['first'], hq[q]['last']))}")
    lay_sid = {}
    for f in glob.glob(os.path.join(DATA, "nt-clause-layout", "clauses", "*", "*.jsonl")):
        for ln in open(f, encoding="utf-8"):
            r = json.loads(ln)
            if r["quotation"]:
                lay_sid[r["quotation"]] = r["speaker_id"] or ""
    R.info("grc speech: quotations whose speaker id differs between the published (reviewed) layout and the "
           "review-free recomputation", sum(1 for q, s in lay_sid.items() if gq.get(q, {}).get("speaker_id", "") != s))
    ent_rows = {r["entity"]: r for r in tsv(os.path.join(DATA, "entities", "entities.tsv"))}

    def ent(a):
        r = ent_rows.get(a)
        return ekey(a, r["type"]) if r and r["type"] in TYPES else None

    chars = {r["character"]: (ent(r["entity"]) if r["entity"] else None)
             for r in tsv(os.path.join(DATA, "entities", "characters.tsv"))}
    corr = {r["first"] for r in tsv(os.path.join(REPO, "resources", "speaker_layer", "corrections.tsv"))}
    addr = {}
    for r in tsv(os.path.join(DATA, "addressees", "quotations.tsv")):
        greek = r["corpus"] == "grc"
        q = (gq if greek else hq).get(r["quote"])
        if q is None or (r["first"] != (q["start"] if greek else q["first"]) and not (V12 and greek)) \
                or r["basis"] == "turn":       # SPEC 1.2 D10: a Greek row's first word is not compared
            continue
        if not greek and (r["quote"] not in pub or (pub[r["quote"]]["first"], pub[r["quote"]]["last"]) !=
                          (q["first"], q["last"])):
            continue
        a = r["addressee"]
        addr[(r["corpus"], r["quote"])] = None if not a or a.startswith("lemma:") else ent(a)
    for lang in ("hbo", "arc", "grc"):
        greek = lang == "grc"
        K = pq.read_table(os.path.join(build, lang, "clauses.parquet"), columns=[
            "clause", "line", "quote", "speaker", "addressee", "speech_basis"]).to_pydict()
        qs = gq if greek else hq
        bad = C.Counter()
        for ck, line, q, s, a, b in zip(K["clause"], K["line"], K["quote"], K["speaker"], K["addressee"],
                                        K["speech_basis"]):
            qq = seg.get(line, "")
            if qq and qq not in qs:
                bad["quotation not in the layer"] += 1
            if not qq or qq not in qs:
                want = ("", "", "", "")
            else:
                first = qs[qq]["start"] if greek else qs[qq]["first"]
                want = (f"q:{qq}", chars.get(qs[qq]["speaker_id"] or "") or "",
                        addr.get(("grc" if greek else "hbo", qq)) or "", "derived" if first in corr else "linked")
            bad["differ"] += (q, s, a, b) != want
            bad["null"] += None in (q, s, a, b)
        R.check(f"{lang} clauses: quote, speaker, addressee, speech_basis never null", bad["null"] == 0, bad["null"])
        R.check(f"{lang} clauses: quote, speaker, addressee, speech_basis equal D10 over the validator's own "
                "review-free layer", bad["differ"] + bad["quotation not in the layer"] == 0, dict(bad))
        R.info(f"{lang} clauses with quote / speaker / addressee / speech_basis derived",
               f"{sum(1 for v in K['quote'] if v):,} / {sum(1 for v in K['speaker'] if v):,} / "
               f"{sum(1 for v in K['addressee'] if v):,} / {sum(1 for v in K['speech_basis'] if v == 'derived'):,}")


# ---- unchanged ----------------------------------------------------------------------------------------------------

def unchanged(R, build):
    b1 = os.path.join(os.path.dirname(os.path.normpath(build)), "b1")
    if not os.path.isdir(b1):
        R.skip("stage 16 unchanged: equality with b1", "build b1 not present")
        return
    for lang in ("hbo", "arc", "grc"):
        A = pq.read_table(os.path.join(build, lang, "clauses.parquet")).to_pydict()
        B = pq.read_table(os.path.join(b1, lang, "clauses.parquet")).to_pydict()
        ib = {k: i for i, k in enumerate(B["clause"])}
        for c in ("quote", "speaker", "line"):
            d = sum(1 for i, k in enumerate(A["clause"]) if k not in ib or A[c][i] != B[c][ib[k]])
            R.check(f"{lang} unchanged: clauses.{c} equals b1 row by row", d == 0, d)
        for c in ("marks", "addressee"):
            R.info(f"{lang} changed against b1: clauses.{c}",
                   f"{sum(1 for i, k in enumerate(A['clause']) if k in ib and A[c][i] != B[c][ib[k]]):,} rows differ")
        pa_ = {r["ent"]: r for r in tsv(os.path.join(build, lang, "participants.tsv"))}
        pb_ = {r["ent"]: r for r in tsv(os.path.join(b1, lang, "participants.tsv"))}
        both = set(pa_) & set(pb_)
        d = sum(1 for e in both if pa_[e]["sex"] != pb_[e]["sex"])
        R.check(f"{lang} unchanged: participants.sex equals b1 for every ent in both builds", d == 0,
                f"{len(both):,} in both, {d} differ")
        R.info(f"{lang} participants: only in c1 / only in b1", f"{len(set(pa_) - set(pb_))} / {len(set(pb_) - set(pa_))}")
        A = pq.read_table(os.path.join(build, lang, "pieces.parquet"), columns=["who", "who_basis"]).to_pydict()
        B = pq.read_table(os.path.join(b1, lang, "pieces.parquet"), columns=["who", "who_basis"]).to_pydict()
        pairs = C.Counter((b, a) for a, b, wa, wb in zip(A["who_basis"], B["who_basis"], A["who"], B["who"])
                          if (a, wa) != (b, wb))
        R.info(f"{lang} changed against b1: pieces.who (b1 basis -> c1 basis)",
               ", ".join(f"{x!r}->{y!r} {n:,}" for (x, y), n in pairs.most_common(8)) or "0")


def stage16(R, build, src, STASH):
    R.section("clause values: marks (D9, terms), line (D11), sem_role (D12)")
    V = values(R, build, STASH)
    R.section("participants: who (D7), participants.tsv (D7n), kin facts, source_errors.tsv")
    participants(R, build, src)
    R.section("speech (strict part): the validator's own review-free layers (D10)")
    speech(R, build, V)
    R.section("unchanged: clauses.quote, speaker, line; participants.sex (SPEC 13)")
    unchanged(R, build)
