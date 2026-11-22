"""Stage 16, clause part (SPEC 1.1, build c1): `clauses.marks` (D9, section 8, with the terms of terms.tsv), `line`
(D11), `constituents.sem_role` and `sem_role_basis` (D12), and the clause part of categories.toml.

The 1.0 module examples_values.py is left as it was (build b1 must rebuild to the same bytes); its readers of the
layouts, the tree store and the datasets are reused. What 1.1 changes, rule by rule:
- the meaning categories (relation, time, aspect, line_kind) and the semantic roles are carried, as terms (U1);
- Greek join C2: `connective` goes to the outermost clause of the segment, every other category to the outermost
  clause of the segment that has a `pred`, else to the outermost;
- connective items C3: the clause's own pieces; else the pieces directly before its first piece that lie in no clause
  or in the parent clause (the run of such pieces that ends at the clause's first piece);
- negator `bilti` -> בֵּלֶת (C4); lemmas compared under NFC (C5);
- `fronted`: `none` where the dataset's value is empty (C6);
- Hebrew `voice`: `passive` also where the predicate's stem piece has `type` participle_passive (C12);
- D12 (C11): the row whose head is the constituent's head piece (two such: the one with the constituent's words);
  where none, the row whose words are the constituent's words. `sem_role_basis` `linked` for role_basis lxx_nt,
  lxx_nt_domain, hebrew_domain, `derived` for frame, frame_passive, hebrew_prep, ln, ln_speech, ln+speech. The bases
  SPEC 4.4 / D12 do not name and that rest on the Septuagint by their name (lxx_dative, lxx_nt_domain+speech,
  hebrew_domain+speech) are not filled: the specification gives them no basis (stage 16 report).
"""
import collections as C
import csv
import json
import os

import pyarrow.parquet as pq

import examples_clauses as EC
import examples_common as X
import examples_src as S
import examples_values as EV

CATS = EV.CATS
MEANING = ("relation", "time", "aspect", "line_kind")
NEG_LEMMA = dict(EV.NEG_LEMMA, bilti="בֵּלֶת")
SEM_LINKED = ("lxx_nt", "lxx_nt_domain", "hebrew_domain")
SEM_DERIVED = ("frame", "frame_passive", "hebrew_prep", "ln", "ln_speech", "ln+speech")
MARKER = "# ---- the clause part (build_examples.py --stage 16) ----"


def read_terms(outdir, lang):
    """(category, code) -> term of the language (arc reads the hbo column)."""
    col = "grc" if lang == "grc" else "hbo"
    with open(os.path.join(outdir, lang, "terms.tsv"), encoding="utf-8", newline="") as fh:
        return {(r["category"], r["code"]): r[col] for r in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)}


def term_of(terms, lang, cat, code):
    t = terms[lang].get((cat, code))
    if not t:
        raise SystemExit(f"stage 16: no term for {lang} {cat} {code} in terms.tsv")
    return t


def edge_setup(gl, T, order, own, pids_of, tpos, rows_of, plex, lemma, greek, cnt, extra, tag):
    """SPEC 1.2 D9: the words of every clause in text order, each word's own pieces, and (Greek) the postpositive
    lexemes, counted from the connectives rows joined to clauses: a lexeme is postpositive when more than half of its
    places, counted at its first piece inside the clause's span, stand at the clause's second word."""
    pid_t = {pid: t for lg in gl for pid, t in zip(T[lg]["P"]["pid"], T[lg]["P"]["t"])}
    cwords = {}
    for key, *_ in order:
        ws = []
        for p in sorted(pids_of[key], key=tpos.get):
            if not ws or ws[-1] != pid_t[p]:
                ws.append(pid_t[p])
        cwords[key] = ws
    own_by_word = {key: C.defaultdict(list) for key in cwords}
    for key, lst in own.items():
        for p, lx, lm in lst:
            own_by_word[key][pid_t[p]].append((p, lx, lm))
    post = set()
    if greek:
        tot, second = C.Counter(), C.Counter()
        for key, r in rows_of[("conn", "connectives")].items():
            ws = cwords[key]
            span = sorted(pids_of[key], key=tpos.get)
            for it in (r["conn"] or "").split():
                hit = next((p for p in span if EV.nfc(lemma[plex[p]]) == EV.nfc(it)), None)
                if hit is None:
                    continue
                tot[plex[hit]] += 1
                second[plex[hit]] += len(ws) > 1 and pid_t[hit] == ws[1]
        post = {lx for lx, n in tot.items() if second[lx] * 2 > n}
        extra["grc D9 postpositive lexemes (places at the clause's second word / places)"] = {
            lx: f"{second[lx]}/{tot[lx]}" for lx in sorted(post)}
        extra["grc D9 connective lexemes not postpositive, with 20 places or more (second word / places)"] = {
            lx: f"{second[lx]}/{tot[lx]}" for lx in sorted(tot) if lx not in post and tot[lx] >= 20}
        cnt["grc D9 postpositive lexemes"] = len(post)
    return dict(pid_t=pid_t, cwords=cwords, own_by_word=own_by_word, post=post, greek=greek, own=own, plex=plex,
                lemma=lemma)


def edge_match(E, key, items, lg, before_run, match_p, cnt, ex, left_items, src_val):
    """SPEC 1.2 D9: each listed item takes the first free piece with its lemma among the clause's edge: the own pieces
    of its first word; then each next word, as long as every word before it gave an item; in Greek the second word
    where its lexeme is postpositive; then the run before. -> the lexeme keys, in the items' order."""
    ws, obw = E["cwords"][key], E["own_by_word"][key]
    res = [None] * len(items)
    where = [None] * len(items)
    taken = set()

    def assign(pool, tag):
        gave = False
        for i, it in enumerate(items):
            if res[i] is not None:
                continue
            free = [x for x in pool if x[0] not in taken]
            hit = match_p([it], free)[0]
            if hit is not None:
                res[i], where[i] = hit, tag
                taken.add(hit[0])
                gave = True
        return gave
    v15 = E.get("v15")
    k = 0
    while k < len(ws):
        g0 = False
        if k == 0 and v15 is not None:      # SPEC 1.5 D9 (1): the first word's pieces before the clause's first piece
            g0 = assign([(p, E["plex"][p], E["lemma"][E["plex"][p]]) for p in v15["pre_first"](key)],
                        "1.5 (1) the first word's pieces before the clause")
        g1 = assign(obw.get(ws[k], []), "first word" if k == 0 else "a next word of the leading run")
        if not (g0 or g1):
            break
        k += 1
    if E["greek"] and len(ws) > 1 and k < 2:
        assign([x for x in obw.get(ws[1], []) if x[1] in E["post"]], "the second word (postpositive)")
        if v15 is not None:                  # SPEC 1.5 D9 (3): a postpositive in a gap right after the first word
            assign([(p, E["plex"][p], E["lemma"][E["plex"][p]]) for p in v15["gap"](key)
                    if E["plex"][p] in E["post"]], "1.5 (3) a postpositive in the gap after the first word")
    if any(r is None for r in res):
        if v15 is not None:                  # SPEC 1.5 D9 (2): the run before may run through ancestor clauses
            run = v15["run_before"](key)
            old = set(before_run(key))
            assign([(p, E["plex"][p], E["lemma"][E["plex"][p]]) for p in run if p in old], "the run before")
            assign([(p, E["plex"][p], E["lemma"][E["plex"][p]]) for p in run if p not in old],
                   "1.5 (2) the run before, through an ancestor clause")
        else:
            assign([(p, E["plex"][p], E["lemma"][E["plex"][p]]) for p in before_run(key)], "the run before")
    keys = []
    for it, hit, w in zip(items, res, where):
        if hit is None:
            cnt[f"{lg} connective: items left out (not at the clause's edge)"] += 1
            left_items[lg][it] += 1
            ex[f"{lg} connective: items left out (not at the clause's edge)"].append(f"{key} {it}")
            if any(EV.nfc(lm) == EV.nfc(it) for _p, _x, lm in E["own"][key]):
                cnt[f"{lg} connective: items left out that stand among the clause's own pieces (1.1 took them)"] += 1
            continue
        cnt[f"{lg} connective: items matched at {w}"] += 1
        if w.startswith("1.5"):
            ex[f"{lg} 1.5 D9 connective items brought back"].append(f"{key} {it} {w[:7]}")
        keys.append(hit[1])
        src_val.setdefault((lg, "connective", hit[1]), set()).add(it)
    return keys


QMARKS = (";", "\u037e")


def v15_edge(key_list, pids_of, tpos, tord, inner, parent_of, pid_t, cwords):
    """SPEC 1.5 D9: the three widenings of the connective edge, as functions of the clause key."""
    def first_pos(key):
        return min(tpos[p] for p in pids_of[key])

    def ancestors(key):
        out, p = set(), parent_of.get(key) or None
        while p:
            out.add(p)
            p = parent_of.get(p) or None
        return out

    def pre_first(key):
        f = first_pos(key)
        t0 = pid_t[tord[f][2]]
        out, j = [], f - 1
        while j >= 0 and pid_t[tord[j][2]] == t0:
            out.append(tord[j][2])
            j -= 1
        return out[::-1]

    def run_before(key):
        anc = ancestors(key)
        run, j = [], first_pos(key) - 1
        while j >= 0:
            p = tord[j][2]
            if inner.get(p) is not None and inner.get(p) not in anc:
                break
            run.append(p)
            j -= 1
        return run[::-1]

    def gap(key):
        ws = cwords[key]
        if len(ws) < 2:
            return []
        span = set(pids_of[key])
        lo = max(tpos[p] for p in pids_of[key] if pid_t[p] == ws[0])
        hi = min(tpos[p] for p in pids_of[key] if pid_t[p] == ws[1])
        return [tord[j][2] for j in range(lo + 1, hi) if tord[j][2] not in span]
    return dict(pre_first=pre_first, run_before=run_before, gap=gap)


def v15_clause(m, key, lg, rows_of, own, ptype, kv, after_of, terms, use, cnt, ex, verbless):
    """SPEC 1.5 D9, Greek: the interrogative mood (A11) and the verbless time (A6)."""
    inter = term_of(terms, lg, "mood", "interrogative")
    if m.get("mood") == inter:
        has_word = any(ptype.get(p) == "interrogative" for p, _x, _l in own[key])
        qm = any(q in (after_of.get(kv(key, "last")) or "") for q in QMARKS)
        if has_word or qm:
            cnt[f"{lg} 1.5 D9 mood interrogative kept: {'own interrogative word' if has_word else 'question mark'}"] += 1
        else:
            if m.get("relation") == term_of(terms, lg, "relation", "conditional"):
                code = "conditional"
            elif m.get("time") == term_of(terms, lg, "time", "irrealis"):
                code = "irrealis"
            else:
                code = "declarative"
            m["mood"] = term_of(terms, lg, "mood", code)
            use[(lg, "mood")]["interrogative"] -= 1
            use[(lg, "mood")][code] += 1
            cnt[f"{lg} 1.5 D9 mood interrogative -> {code}"] += 1
            ex[f"{lg} 1.5 D9 mood interrogative moved"].append(f"{key} {code}")
    r = rows_of[("main", "time-aspect")].get(key)
    if r is not None and r["basis"] == "grc:verbless":
        verbless.add(key)
        for cat in ("time", "aspect"):
            v = m.pop(cat, None)
            if v is None:
                continue
            for c_ in list(use[(lg, cat)]):
                if term_of(terms, lg, cat, c_) == v:
                    use[(lg, cat)][c_] -= 1
                    if use[(lg, cat)][c_] == 0:
                        del use[(lg, cat)][c_]
                    break
            cnt[f"{lg} 1.5 D9 verbless: {cat} taken out ({r[cat]})"] += 1
        cnt[f"{lg} 1.5 D9 verbless clauses (time-aspect basis grc:verbless)"] += 1


def compute(outdir, gl, greek, cnt, ex, pins, extra, terms, more=None):
    """`more`: further datasets (name -> rows with `clause_key`) joined to clauses as D9 joins (stage 17: D15m)."""
    tag = "grc" if greek else "tan"
    T = {}
    for lang in gl:
        d = os.path.join(outdir, lang)
        T[lang] = dict(W=pq.read_table(os.path.join(d, "words.parquet")).to_pydict(),
                       P=pq.read_table(os.path.join(d, "pieces.parquet")).to_pydict(),
                       K=pq.read_table(os.path.join(d, "clauses.parquet")).to_pydict(),
                       N=pq.read_table(os.path.join(d, "constituents.parquet")).to_pydict())
    bym = None
    if not greek:
        m = pq.read_table(os.path.join(outdir, "cache", "morphid.parquet")).to_pydict()
        bym = C.defaultdict(list)
        for mid, pid in zip(m["morphid"], m["pid"]):
            bym[mid].append(pid)
    keep = {}
    files = S.grc_lowfat_files() if greek else S.heb_lowfat_files()
    out, _w = EC.compute({lg: (T[lg]["W"], T[lg]["P"]) for lg in gl}, files, greek, bym, C.Counter(),
                         C.defaultdict(list), keep=keep, v11=True)
    for lg in gl:
        if [r["clause"] for r in out[lg][0]] != T[lg]["K"]["clause"]:
            raise SystemExit(f"stage 16: the {lg} clauses of stage 15 differ from the recomputed ones; rerun 15")
        if [r["pred"] for r in out[lg][0]] != T[lg]["K"]["pred"]:
            raise SystemExit(f"stage 16: the {lg} pred of stage 15 differs from the recomputed one; rerun 15")
    order = keep["clauses"]
    doc_ix = {k[0]: i for i, k in enumerate(order)}
    depth = {k[0]: k[3] for k in order}

    lemma = {}
    for lg in gl:
        with open(os.path.join(outdir, lg, "lexemes.tsv"), encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
                lemma[r["lexeme"]] = r["lemma"]
    plex, ptype, sent_of = {}, {}, {}
    for lg in gl:
        P = T[lg]["P"]
        wsent = dict(zip(T[lg]["W"]["t"], T[lg]["W"]["sentence"]))
        for pid, lx, mk, t in zip(P["pid"], P["lexeme"], P["marks"], P["t"]):
            plex[pid] = lx
            ptype[pid] = json.loads(mk).get("type")
            sent_of[pid] = wsent[t]
    inner = {}
    for key, rule, lang, dp, pids in order:
        for p in pids:
            if p not in inner or depth[inner[p]] < dp:
                inner[p] = key
    tord = sorted((T[lg]["P"]["t"][i], T[lg]["P"]["n"][i], pid) for lg in gl for i, pid in enumerate(T[lg]["P"]["pid"]))
    tpos = {x[2]: i for i, x in enumerate(tord)}
    own = {key: sorted(((p, plex[p], lemma[plex[p]]) for p in pids if inner[p] == key), key=lambda x: tpos[x[0]])
           for key, _r, _l, _d, pids in order}
    crow = {}
    for lg in gl:
        for j, k in enumerate(T[lg]["K"]["clause"]):
            crow[k] = (lg, j)
    parent_of = {k: p for lg in gl for k, p in zip(T[lg]["K"]["clause"], T[lg]["K"]["parent"])}
    wid, stem = {}, {}
    for lg in gl:
        for t, i in zip(T[lg]["W"]["t"], T[lg]["W"]["id"]):
            wid[t] = i
        for t, pid, kind in zip(T[lg]["P"]["t"], T[lg]["P"]["pid"], T[lg]["P"]["kind"]):
            if kind == "stem":
                stem[t] = pid

    def kv(key, col):
        lg, j = crow[key]
        return T[lg]["K"][col][j]

    def anchor(key):
        pred = kv(key, "pred")
        if greek:
            return wid[pred if pred else kv(key, "first")][1:]
        return stem[pred][1:] if pred else key.split(":")[1][1:]

    # ---- the layout, D11 --------------------------------------------------------------------------------------------
    segs, lay_sha, nfiles = EV.grc_layout() if greek else EV.heb_layout()
    pins[f"{tag} layout"] = dict(path=os.path.relpath(EV.GRC_LAYOUT if greek else EV.HEB_LAYOUT, S.HERE),
                                 files=nfiles, sha256_of_files=lay_sha, segments=len(segs))
    seg_of = {}
    for si, s in enumerate(segs):
        for w in s["words"]:
            if w in seg_of:
                raise SystemExit(f"stage 16: layout word {w} in two segments")
            seg_of[w] = si
    line = {}
    for key, *_ in order:
        si = seg_of.get(anchor(key))
        line[key] = "" if si is None else segs[si]["line"]
        cnt[f"{crow[key][0]} D11 clauses {'with' if si is not None else 'without'} a line"] += 1

    # ---- D9: dataset rows -> clauses (per category: Greek C2) -----------------------------------------------------
    corpus = "grc" if greek else "hbo"
    data = {"clause-columns": pq.read_table(os.path.join(EV.D, EV.FILES[(corpus, "clause-columns")])).to_pylist()}
    for ds in ("clause-extras", "connectives", "time-aspect"):
        data[ds] = EV.read_tsv(os.path.join(EV.D, EV.FILES[("*", ds)]), corpus)
    for ds in ("clause-columns", "clause-extras", "connectives", "time-aspect", "arg-roles"):
        f = EV.FILES[(corpus, ds)] if (corpus, ds) in EV.FILES else EV.FILES[("*", ds)]
        pins[f"{tag} {ds}"] = dict(file=f"data/{f}", sha256=S.sha256(os.path.join(EV.D, f)))
    if more:
        data.update(more)
    rows_of = {}          # (join, dataset) -> clause key -> row; join "conn" or "main" (Hebrew: one join)
    no_row = {}
    if not greek:
        tr = EV.tree_ranks()
        pins["tan trees-macula.db"] = dict(file="trees-macula.db", sha256=S.sha256(EV.TREES), cl_rows=len(tr))
        if len(tr) != len(order):
            raise SystemExit(f"stage 16: {len(tr)} tree-store clauses, {len(order)} lowfat clauses")
        rank_of = {tid: r for r, (tid, _rule) in enumerate(tr)}
        bad_rank = {r for r, (tid, rule) in enumerate(tr) if (rule or "") != order[r][1]}
        cnt["tan D9 ranks whose tree-store rule differs from the lowfat rule"] = len(bad_rank)
        key2cl = C.defaultdict(set)
        for s in segs:
            key2cl[s["clause_key"]].add(s["clause"])
        lay_rank = {rank_of[s["clause"]] for s in segs if s["clause"] in rank_of}
        for ds, rows in data.items():
            got = {}
            for r in rows:
                ids = key2cl.get(r["clause_key"])
                if not ids:
                    why = "clause_key not in the layout"
                elif len(ids) > 1:
                    why = "clause_key names two or more layout clauses"
                elif rank_of.get(next(iter(ids))) is None:
                    why = "layout clause id is not a cl row of the tree store"
                elif rank_of[next(iter(ids))] in bad_rank:
                    why = "the rule differs at this rank"
                elif order[rank_of[next(iter(ids))]][0] in got:
                    why = "a second row for the same clause"
                else:
                    got[order[rank_of[next(iter(ids))]][0]] = r
                    cnt[f"tan D9 {ds} rows joined"] += 1
                    continue
                cnt[f"tan D9 {ds} rows that found no clause: {why}"] += 1
                ex[f"tan D9 {ds} rows that found no clause"].append(f"{r['clause_key']} {why}")
            rows_of[("conn", ds)] = rows_of[("main", ds)] = got
        for r, (key, *_x) in enumerate(order):
            why = ("the layout has a segment for it, the dataset no row" if r in lay_rank else
                   "the layout gives it no segment of its own")
            no_row[("conn", key)] = no_row[("main", key)] = why
    else:
        first2seg = {s["first"]: si for si, s in enumerate(segs)}
        cand = C.defaultdict(list)
        for key, *_ in order:
            si = seg_of.get(anchor(key))
            if si is not None:
                cand[si].append(key)
        chosen = {"conn": {}, "main": {}}
        for si, keys in cand.items():
            outer = min(keys, key=lambda k: (depth[k], doc_ix[k]))
            chosen["conn"][si] = outer
            withp = [k for k in keys if kv(k, "pred")]
            chosen["main"][si] = min(withp, key=lambda k: (depth[k], doc_ix[k])) if withp else outer
            ties = [k for k in keys if depth[k] == depth[outer]]
            if len(ties) > 1:
                cnt["grc D9 segments with two or more outermost candidates (first in document order)"] += 1
                ex["grc D9 segments with two or more outermost candidates"].append(f"{segs[si]['line']} {' '.join(ties)}")
            if chosen["main"][si] != outer:
                cnt["grc D9 C2: segments whose non-connective categories go to another clause than connective"] += 1
            if not withp:
                cnt["grc D9 C2: segments with no candidate that has a pred (the outermost takes all)"] += 1
        cnt["grc D9 segments with a clause"] = len(cand)
        cnt["grc D9 segments without a clause"] = len(segs) - len(cand)
        for join in ("conn", "main"):
            taken = set(chosen[join].values())
            for ds, rows in data.items():
                got = {}
                for r in rows:
                    si = first2seg.get(r["clause_key"])
                    if si is None:
                        why = "clause_key is not the first word of a segment"
                    elif si not in chosen[join]:
                        why = "no clause has its predicate (or first) word in the segment"
                    else:
                        got[chosen[join][si]] = r
                        cnt[f"grc D9 {join} {ds} rows joined"] += 1
                        continue
                    cnt[f"grc D9 {join} {ds} rows that found no clause: {why}"] += 1
                    ex[f"grc D9 {join} {ds} rows that found no clause"].append(f"{r['clause_key']} {why}")
                rows_of[(join, ds)] = got
            for key, *_ in order:
                si = seg_of.get(anchor(key))
                no_row[(join, key)] = ("its predicate (or first) word is in no segment" if si is None else
                                       "another clause of its segment took the segment" if key not in taken else
                                       "its segment has no dataset row")

    # ---- marks --------------------------------------------------------------------------------------------------------
    match = EV.lemma_matcher(cnt, tag)

    def match_p(items, pool):
        """As the matcher, but gives (pid, lexeme) or None per item (exact lemma first, else equal under NFC)."""
        taken, res = set(), []
        for it in items:
            hit = next(((p, x) for p, x, lm in pool if p not in taken and lm == it), None)
            if hit is None:
                hit = next(((p, x) for p, x, lm in pool if p not in taken and EV.nfc(lm) == EV.nfc(it)), None)
                if hit is not None:
                    cnt[f"{tag} matched only as canonically equal text (NFC)"] += 1
            if hit is not None:
                taken.add(hit[0])
            res.append(hit)
        return res

    def before_run(key):
        """C3: the pieces directly before the clause's first piece that lie in no clause or in the parent clause."""
        first = min(tpos[p] for p in pids_of[key])
        par = parent_of.get(key) or None
        run = []
        j = first - 1
        while j >= 0:
            p = tord[j][2]
            if inner.get(p) not in (None, par):
                break
            run.append(p)
            j -= 1
        return run[::-1]

    pids_of = {k[0]: k[4] for k in order}
    if X.V12:
        E12 = edge_setup(gl, T, order, own, pids_of, tpos, rows_of, plex, lemma, greek, cnt, extra, tag)
    if getattr(X, "V15", False):
        E12["v15"] = v15_edge(key_list=[k[0] for k in order], pids_of=pids_of, tpos=tpos, tord=tord, inner=inner,
                              parent_of=parent_of, pid_t=E12["pid_t"], cwords=E12["cwords"])
    marks, use, src_val = {}, C.defaultdict(C.Counter), {}
    verbless = set()
    after_of = {t: a for lg in gl for t, a in zip(T[lg]["W"]["t"], T[lg]["W"]["after"])} if greek else {}
    taken_by = C.defaultdict(list)
    no_row_rules = C.defaultdict(C.Counter)
    left_items = C.defaultdict(C.Counter)
    voice_c12 = C.Counter()
    for key, rule, lang_, dp, pids in order:
        m = {}
        lg = crow[key][0]
        any_row = False
        for cat, ds, col, _fr in CATS:
            join = "conn" if cat == "connective" else "main"
            r = rows_of[(join, ds)].get(key)
            if r is None:
                cnt[f"{lg} {cat}: clauses without a dataset row, {no_row[(join, key)]}"] += 1
                continue
            any_row = True
            raw = r[col]
            if cat == "negator":
                if not raw:
                    continue
                lem = NEG_LEMMA.get(raw)
                if lem is None:
                    raise SystemExit(f"stage 16: negator value {raw!r} not in SPEC 8")
                if X.V12:     # SPEC 1.2 D9: own pieces in text order, then the run before
                    hit = match_p([lem], own[key] + [(p, plex[p], lemma[plex[p]]) for p in before_run(key)])[0]
                    got = None if hit is None else hit[1]
                    if hit is not None and inner.get(hit[0]) != key:
                        cnt[f"{lg} negator: found in the run before the clause (1.2)"] += 1
                        ex[f"{lg} negator: found in the run before the clause (1.2)"].append(f"{key} {raw}")
                else:
                    got = match([lem], own[key])[0]
                if got is None:
                    cnt[f"{lg} negator: no own piece with the lemma (left out), {raw}"] += 1
                    ex[f"{lg} negator: no own piece with the lemma"].append(f"{key} {raw}")
                    continue
                m[cat] = got
                src_val.setdefault((lg, cat, got), set()).add(raw)
                use[(lg, cat)][got] += 1
                continue
            if cat == "connective":
                items = (raw or "").split()
                if not items:
                    continue
                if X.V12:
                    keys = edge_match(E12, key, items, lg, before_run, match_p, cnt, ex, left_items, src_val)
                    for g in set(keys):
                        use[(lg, cat)][g] += 1
                    if keys:
                        m[cat] = keys
                    continue
                got_own = match(items, own[key])
                rest = [it for it, g in zip(items, got_own) if g is None]
                before = [(p, plex[p], lemma[plex[p]]) for p in before_run(key)] if rest else []
                got_bp = match_p(rest, before)
                for hit in got_bp:
                    if hit is not None:
                        taken_by[hit[0]].append(key)
                got_before = iter(None if h is None else h[1] for h in got_bp)
                keys = []
                for it, g in zip(items, got_own):
                    if g is not None:
                        keys.append(g)
                        cnt[f"{lg} connective: items matched to an own piece"] += 1
                        src_val.setdefault((lg, cat, g), set()).add(it)
                        continue
                    g2 = next(got_before)
                    if g2 is None:
                        cnt[f"{lg} connective: items left out (no own piece, none directly before)"] += 1
                        left_items[lg][it] += 1
                        ex[f"{lg} connective: items left out"].append(f"{key} {it}")
                        continue
                    keys.append(g2)
                    cnt[f"{lg} connective: items matched to a piece directly before the clause"] += 1
                    src_val.setdefault((lg, cat, g2), set()).add(it)
                for g in set(keys):
                    use[(lg, cat)][g] += 1
                if keys:
                    m[cat] = keys
                continue
            if cat == "fronted" and (raw is None or raw == ""):
                code, sv = "none", ""
                cnt[f"{lg} fronted: none, the dataset's empty value ({raw!r})"] += 1
            else:
                code, sv = EV.value_code(cat, raw, r if ds == "clause-columns" else None, cnt, lg)
            if cat == "voice" and not greek:
                pred = kv(key, "pred")
                if pred and ptype.get(stem[pred]) == "participle_passive":
                    voice_c12[(lg, code)] += 1
                    if code != "passive":
                        cnt[f"{lg} voice C12: passive participle predicate, dataset value {code} -> passive"] += 1
                        ex[f"{lg} voice C12: set to passive (clause dataset value)"].append(f"{key} {code}")
                        code, sv = "passive", "passive"
            if code is None:
                cnt[f"{lg} {cat}: dataset row without a value ({raw!r})"] += 1
                continue
            src_val.setdefault((lg, cat, code), set()).add(sv)
            use[(lg, cat)][code] += 1
            m[cat] = term_of(terms, lg, cat, code) if cat in MEANING else code
        if getattr(X, "V15", False) and greek:
            v15_clause(m, key, lg, rows_of, own, ptype, kv, after_of, terms, use, cnt, ex, verbless)
        if not any_row:
            cnt[f"{lg} clauses without any dataset row"] += 1
            no_row_rules[lg][rule] += 1
        if "kind" in m and m["kind"] == "vc" and kv(key, "pred_kind") == "none":
            ex[f"{lg} kind: vc with pred_kind none (AUDIT 3)"].append(key)
        marks[key] = X.jdump(m)
    cnt[f"{tag} connective: pieces directly before a clause taken by two or more clauses (diagnostic)"] = sum(
        1 for v in taken_by.values() if len(v) > 1)
    cnt[f"{tag} connective: pieces directly before a clause taken from another sentence (diagnostic)"] = sum(
        1 for p, ks in taken_by.items() for k in ks if sent_of[p] != sent_of[min(pids_of[k], key=tpos.get)])
    for lg in gl:
        extra[f"{lg} clauses without any dataset row, by rule (top 25)"] = dict(no_row_rules[lg].most_common(25))
        extra[f"{lg} connective: items left out, by item"] = dict(left_items[lg].most_common())
        extra[f"{lg} voice C12: passive participle predicates by dataset value"] = {
            str(c): n for (l_, c), n in sorted(voice_c12.items(), key=str) if l_ == lg}

    # ---- D12 --------------------------------------------------------------------------------------------------------
    role_of = {(k, o): rl for lg in gl for k, o, rl in zip(T[lg]["N"]["clause"], T[lg]["N"]["ord"], T[lg]["N"]["role"])}
    roles = EV.read_tsv(os.path.join(EV.D, EV.FILES[("*", "arg-roles")]), corpus)
    by_head, by_words = C.defaultdict(list), C.defaultdict(list)
    for i, r in enumerate(roles):
        if r["head"]:
            by_head[r["head"]].append(i)
        else:
            cnt[f"{tag} D12 arg-roles rows without a head"] += 1
        by_words[tuple(sorted(r["words"].split()))].append(i)
    sem, semb, sem_use, semb_use = {}, {}, C.defaultdict(C.Counter), C.defaultdict(C.Counter)
    used = C.Counter()
    for (key, o), (hp, pids) in sorted(keep["const"].items(), key=lambda x: (doc_ix[x[0][0]], x[0][1])):
        lg = crow[key][0]
        words = tuple(sorted(p[1:] for p in pids))
        cand = by_head.get(hp[1:], [])
        how = "head"
        if len(cand) > 1:
            cand = [i for i in cand if tuple(sorted(roles[i]["words"].split())) == words]
            how = "head and words"
        if not by_head.get(hp[1:]):
            cand = by_words.get(words, [])
            how = "words"
        sem[(key, o)] = semb[(key, o)] = ""
        if len(cand) != 1:
            why = "no row" if not cand else "two or more rows"
            cnt[f"{lg} D12 constituents without a row ({how}: {why})"] += 1
            cnt[f"{lg} D12 constituents without a row, role {role_of[(key, o)]}"] += 1
            continue
        i = cand[0]
        used[i] += 1
        r = roles[i]
        val, basis = r["role"], r["role_basis"]
        cnt[f"{lg} D12 constituents with a row, found by {how}"] += 1
        if val in ("", "-"):
            cnt[f"{lg} D12 row with no role ({val!r})"] += 1
            continue
        if X.V12:     # SPEC 1.2 D12: lxx_* or hebrew_domain, each with or without +speech -> linked; all others derived
            core = basis[:-len("+speech")] if basis.endswith("+speech") else basis
            b = "linked" if core.startswith("lxx_") or core == "hebrew_domain" else "derived"
        elif basis in SEM_LINKED:
            b = "linked"
        elif basis in SEM_DERIVED:
            b = "derived"
        else:
            cnt[f"{lg} D12 role not filled: role_basis {basis} has no basis in SPEC 4.4 / D12"] += 1
            ex[f"{lg} D12 role not filled: role_basis not named by the specification"].append(f"{key} {o} {basis} {val}")
            continue
        code = X.c0(val)
        sem[(key, o)] = term_of(terms, lg, "sem_role", code)
        semb[(key, o)] = b
        sem_use[lg][code] += 1
        semb_use[lg][(b, basis)] += 1
        src_val.setdefault((lg, "sem_role", code), set()).add(val)
        cnt[f"{lg} D12 sem_role filled, role_basis {basis} -> {b}"] += 1
    cnt[f"{tag} D12 arg-roles rows taken by two or more constituents"] = sum(1 for v in used.values() if v > 1)
    cnt[f"{tag} D12 arg-roles rows with a role taken by no constituent"] = sum(
        1 for i, r in enumerate(roles) if i not in used and r["role"] not in ("", "-"))
    return dict(T=T, order=order, marks=marks, line=line, sem=sem, semb=semb, use=use, sem_use=sem_use,
                semb_use=semb_use, src_val=src_val, rows_of=rows_of, no_row=no_row, verbless=verbless)


def clause_part(lang, V, pins, tag, terms):
    use, src_val = V["use"], V["src_val"]
    out = [MARKER, "# SPEC 1.1: the clause categories of section 8 (rule D9) in clauses.marks, the semantic roles (D12),",
           "# and the coded columns stage 16 fills. `count` = clauses (constituents, pieces, participants) with the code;",
           "# `rule`: C0, `lexeme` (D9's lexeme key), `C12`, `C6`; `term`: the term of terms.tsv a meaning code stands as.",
           f"# Layout {pins[tag + ' layout']['path']} (sha256 of its files {pins[tag + ' layout']['sha256_of_files']})"
           + (f"; trees-macula.db ({pins['tan trees-macula.db']['sha256']})." if tag == "tan" else "."), ""]
    for cat, ds, col, fr in CATS:
        if not use[(lang, cat)]:
            continue
        if fr is None:
            fr = "form" if lang == "grc" else "reading"
        if cat == "subject_switch":
            fr = "form"
        f = pins[f"{tag} {ds}"]
        out += [f"[clauses.{cat}]", 'column = "marks"', 'basis = "derived"',
                f"source = {X.toml_str('rule D9 from our dataset ' + ds)}", f"dataset = {X.toml_str(ds)}",
                f"file = {X.toml_str(f['file'])}", f"dataset_column = {X.toml_str(col)}",
                f"sha256 = {X.toml_str(f['sha256'])}", f"form_or_reading = {X.toml_str(fr)}"]
        if cat in MEANING:
            out.append('meaning = "terms.tsv"')
        out.append("values = [")
        for code in sorted(use[(lang, cat)]):
            vals = sorted(src_val[(lang, cat, code)])
            if cat in ("negator", "connective"):
                rule, value = "lexeme", " ".join(vals)
            else:
                if len(vals) > 1 and not (cat == "voice" and code == "passive"):
                    raise SystemExit(f"two source values give one code: {lang} {cat} {vals} -> {code}")
                value = vals[0]
                rule = "C6" if (cat == "fronted" and code == "none") else "C0"
                if cat == "voice" and code == "passive" and lang != "grc":
                    rule, value = "C0, C12", "passive"
            t = f", term = {X.toml_str(term_of(terms, lang, cat, code))}" if cat in MEANING else ""
            out.append(f"  {{ code = {X.toml_str(code)}, value = {X.toml_str(value)}, rule = {X.toml_str(rule)}{t}, "
                       f"count = {use[(lang, cat)][code]} }},")
        out += ["]", ""]
    if V["sem_use"][lang]:
        f = pins[f"{tag} arg-roles"]
        out += ["[constituents.sem_role]", 'column = "sem_role"', 'basis = "derived, linked (sem_role_basis)"',
                'source = "rule D12 from our dataset arg-roles"', 'dataset = "arg-roles"',
                f"file = {X.toml_str(f['file'])}", 'dataset_column = "role"', f"sha256 = {X.toml_str(f['sha256'])}",
                'form_or_reading = "reading"', 'meaning = "terms.tsv"', "values = ["]
        for code in sorted(V["sem_use"][lang]):
            out.append(f"  {{ code = {X.toml_str(code)}, value = {X.toml_str(sorted(src_val[(lang, 'sem_role', code)])[0])}, "
                       f"rule = \"C0\", term = {X.toml_str(term_of(terms, lang, 'sem_role', code))}, "
                       f"count = {V['sem_use'][lang][code]} }},")
        out += ["]", "", "[constituents.sem_role_basis]", 'column = "sem_role_basis"', 'basis = "derived"',
                'source = "rule D12: arg-roles role_basis lxx_nt, lxx_nt_domain, hebrew_domain -> linked; frame, '
                'frame_passive, hebrew_prep, ln, ln_speech, ln+speech -> derived"', "values = ["]
        by = C.defaultdict(lambda: [C.Counter()])
        for (b, basis), n in V["semb_use"][lang].items():
            by[b][0][basis] += n
        for b in sorted(by):
            srcs = " ".join(sorted(k for k, v in by[b][0].items() if v > 0))   # 1.3 D12c: a moved row counts -1
            out.append(f"  {{ code = {X.toml_str(b)}, value = {X.toml_str('role_basis ' + srcs)}, rule = \"D12\", "
                       f"count = {sum(by[b][0].values())} }},")
        out += ["]", ""]
    return "\n".join(out)
