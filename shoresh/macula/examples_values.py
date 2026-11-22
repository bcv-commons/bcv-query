"""Stage 05 (clause values) of the source-examples build, SPEC 1.0 sections 4.3 (`marks`, `line`), 4.4 (`sem_role`),
4.10 (the clause part of categories.toml), 8, D9, D11, D12.

Reads the stage-04 tables of hbo, arc, grc, the lowfat files again through examples_clauses.compute (for the clause
order, the pieces of every clause and constituent, and the constituents' head pieces), our clause layouts
(data/clause-layout, data/nt-clause-layout), the tree store trees-macula.db (the Hebrew layout's `clause` is a row id
there; its rank among the store's `cl` rows is the rank of the lowfat clause), and our datasets: clause-columns,
clause-extras, connectives, time-aspect, arg-roles. Writes clauses.parquet and constituents.parquet anew (only
`marks`, `line`, `sem_role` change) and categories.toml anew (the piece part as stage 02 wrote it, then the clause
part). Counts and exception lists go to cache/stage05-counts.json.

English values. The categories that the specification marks as readings (relation, time, aspect, line_kind) and the
semantic roles of arg-roles are English words that name a meaning (`purpose`, `past`, `location`). They are joined
and counted here but not carried (WITHHELD, SEM_ROLE_CODES); see the stage report, "For the specification". Form
categories keep their codes (C0).
"""
import collections as C
import csv
import glob
import hashlib
import json
import os
import sqlite3
import unicodedata

import pyarrow as pa
import pyarrow.parquet as pq

import examples_clauses as EC
import examples_common as X
import examples_src as S

D = os.path.join(S.HERE, "data")
TREES = os.path.join(S.HERE, "trees-macula.db")
HEB_LAYOUT = os.path.join(D, "clause-layout", "clauses")
GRC_LAYOUT = os.path.join(D, "nt-clause-layout", "clauses")
FILES = {
    ("hbo", "clause-columns"): "clause-columns/hebrew.parquet",
    ("grc", "clause-columns"): "clause-columns/greek-nt.parquet",
    ("*", "clause-extras"): "clause-extras/clauses.tsv",
    ("*", "connectives"): "connectives/clauses.tsv",
    ("*", "time-aspect"): "time-aspect/clauses.tsv",
    ("*", "arg-roles"): "arg-roles/roles.tsv",
}

# SPEC section 8, in its order: category, dataset, column, form or reading
CATS = [
    ("kind", "clause-columns", "kind", "form"),
    ("force", "clause-columns", "force", "form"),
    ("polarity", "clause-extras", "polarity", "form"),
    ("negator", "clause-columns", "neg", "form"),
    ("neg_scope", "clause-columns", "neg_scope", "form"),
    ("connective", "connectives", "conn", "form"),
    ("relation", "connectives", "relation", "reading"),
    ("time", "time-aspect", "time", "reading"),
    ("aspect", "time-aspect", "aspect", "reading"),
    ("line_kind", "time-aspect", "band", "reading"),
    ("voice", "clause-columns", "voice", None),          # Hebrew reading, Greek form (SPEC 8)
    ("transitivity", "clause-columns", "m_trans", "form"),
    ("subject_form", "clause-columns", "subj_form", "form"),
    ("subject_switch", "clause-columns", "subj_switch", "rests on MACULA's subject references"),
    ("fronted", "clause-columns", "front", "form"),
]
# readings whose values are English words naming a meaning: joined and counted, not carried
WITHHELD = ("relation", "time", "aspect", "line_kind")
# SPEC 8: the negator lemmas, as the specification writes them
NEG_LEMMA = {"lo": "לֹא", "en": "אַיִן", "al": "אַל", "bilti": "בִּלְתִּי", "bal": "בַּל", "la": "לָא",
             "ou": "οὐ", "me": "μή"}
# D12: role_basis values that rest on the Septuagint (a Greek preposition or case of the translation)
LXX_BASES = ("lxx_dative", "lxx_nt", "lxx_nt_domain", "lxx_nt_domain+speech")
# D12: arg-roles values that are codes, not English words; every other value is withheld (counted)
SEM_ROLE_CODES = ("A2",)
MARKER = "# ---- the clause part (build_examples.py --stage 05) ----"


def sha256(path):
    return S.sha256(path)


def files_sha(files, root):
    h = hashlib.sha256()
    for f in files:
        h.update(os.path.relpath(f, root).encode())
        h.update(sha256(f).encode())
    return h.hexdigest()


def read_tsv(path, corpus):
    with open(path, encoding="utf-8", newline="") as fh:
        return [r for r in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE) if r["corpus"] == corpus]


def nfc(s):
    return unicodedata.normalize("NFC", s)


def lemma_matcher(cnt, tag):
    """match(items, own) -> [lexeme or None]: each item takes the first own piece (text order) with that lemma not
    yet taken. Exact string first; where none, a canonically equal lemma (same text under NFC) is taken, counted."""
    def match(items, own):
        taken, out = set(), []
        for it in items:
            hit = None
            for pid, lex, lem in own:
                if pid not in taken and lem == it:
                    hit = (pid, lex)
                    break
            if hit is None:
                for pid, lex, lem in own:
                    if pid not in taken and nfc(lem) == nfc(it):
                        hit = (pid, lex)
                        cnt[f"{tag} matched only as canonically equal text (NFC)"] += 1
                        break
            if hit is None:
                out.append(None)
            else:
                taken.add(hit[0])
                out.append(hit[1])
        return out
    return match


def value_code(cat, raw, row_cc, cnt, tag):
    """(C0 code, source value) of one category's dataset value, or (None, None) where the dataset has none."""
    if cat == "transitivity":
        return (None, None) if raw is None else (X.c0(str(raw)), str(raw))
    if raw is None or raw == "":
        return None, None
    code = X.c0(str(raw))
    if cat == "force" and row_cc is not None and row_cc.get("interrog") is True and code == "declarative":
        cnt[f"{tag} force: declarative with interrog true, written interrogative"] += 1
        return "interrogative", "interrogative"
    return code, str(raw)


# ---- the layouts ------------------------------------------------------------------------------------------------

def heb_layout():
    files = sorted(glob.glob(os.path.join(HEB_LAYOUT, "*", "*.jsonl")))
    segs = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for ln in fh:
                r = json.loads(ln)
                segs.append(dict(line=f"{r['book']}.{r['chapter']}.{r['verse']}.{r['seg']}",
                                 clause_key=r["clause_key"], clause=r["clause"], rule=r["rule"], words=r["words"]))
    return segs, files_sha(files, HEB_LAYOUT), len(files)


def grc_layout():
    files = sorted(glob.glob(os.path.join(GRC_LAYOUT, "*", "*.jsonl")))
    segs = []
    for f in files:
        book, chap = os.path.basename(f)[:-len(".jsonl")].rsplit("_", 1)
        with open(f, encoding="utf-8") as fh:
            for ln in fh:
                r = json.loads(ln)
                segs.append(dict(line=f"{book}.{int(chap)}.{r['verse']}.{r['seg']}", first=r["first"],
                                 words=r["words"]))
    return segs, files_sha(files, GRC_LAYOUT), len(files)


def tree_ranks():
    """Row ids of the store's Hebrew `cl` nodes in id order (the rank), with their rule."""
    db = sqlite3.connect(f"file:{TREES}?mode=ro", uri=True)
    rows = db.execute("select id, rule from nodes where corpus='hbo' and cls='cl' order by id").fetchall()
    db.close()
    return rows


# ---- one text ---------------------------------------------------------------------------------------------------

def compute(outdir, gl, greek, cnt, ex, pins, extra):
    tag = "grc" if greek else "tan"
    tables = {}
    for lang in gl:
        d = os.path.join(outdir, lang)
        tables[lang] = dict(W=pq.read_table(os.path.join(d, "words.parquet")).to_pydict(),
                            P=pq.read_table(os.path.join(d, "pieces.parquet")).to_pydict(),
                            K=pq.read_table(os.path.join(d, "clauses.parquet")).to_pydict(),
                            N=pq.read_table(os.path.join(d, "constituents.parquet")).to_pydict())
        if not tables[lang]["K"]["clause"]:
            raise SystemExit(f"stage 05 needs stage 04's clauses ({lang})")
    # recompute stage 04's clause order and pieces (no table is written by this call)
    bym = None
    if not greek:
        m = pq.read_table(os.path.join(outdir, "cache", "morphid.parquet")).to_pydict()
        bym = C.defaultdict(list)
        for mid, pid in zip(m["morphid"], m["pid"]):
            bym[mid].append(pid)
    keep = {}
    files = S.grc_lowfat_files() if greek else S.heb_lowfat_files()
    out, _w = EC.compute({lg: (tables[lg]["W"], tables[lg]["P"]) for lg in gl}, files, greek, bym,
                         C.Counter(), C.defaultdict(list), keep=keep)
    for lg in gl:
        if [r["clause"] for r in out[lg][0]] != tables[lg]["K"]["clause"]:
            raise SystemExit(f"stage 05: the {lg} clauses of stage 04 differ from the recomputed ones; rerun stage 04")
    order = keep["clauses"]                         # (key, rule, lang, depth, pids) in document order
    doc_ix = {k[0]: i for i, k in enumerate(order)}
    depth = {k[0]: k[3] for k in order}

    # pieces: lexeme and lemma; innermost clause of every piece; the clause's own pieces in text order
    lemma = {}
    for lg in gl:
        with open(os.path.join(outdir, lg, "lexemes.tsv"), encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
                lemma[r["lexeme"]] = r["lemma"]
    plex = {}
    for lg in gl:
        P = tables[lg]["P"]
        for pid, lx in zip(P["pid"], P["lexeme"]):
            plex[pid] = lx
    inner = {}
    for key, rule, lang, dp, pids in order:
        for p in pids:
            if p not in inner or depth[inner[p]] < dp:
                inner[p] = key
    own = {key: [(p, plex[p], lemma[plex[p]]) for p in pids if inner[p] == key] for key, _r, _l, _d, pids in order}
    for lex_ in set(plex.values()):
        if lex_ not in lemma:
            raise SystemExit(f"stage 05: lexeme {lex_} not in lexemes.tsv")

    # clause rows by key; words by t
    crow = {}
    for lg in gl:
        K = tables[lg]["K"]
        for j, k in enumerate(K["clause"]):
            crow[k] = (lg, j)
    wid, stem = {}, {}
    for lg in gl:
        W = tables[lg]["W"]
        for t, i in zip(W["t"], W["id"]):
            wid[t] = i
        P = tables[lg]["P"]
        for t, pid, kind in zip(P["t"], P["pid"], P["kind"]):
            if kind == "stem":
                stem[t] = pid

    def anchor(key):
        """D11 / D9 Greek: the predicate word's stem piece (Hebrew) or word (Greek); where pred is 0, the clause's
        first piece (Hebrew) or first word (Greek). As a layout word key (without the o / n)."""
        lg, j = crow[key]
        K = tables[lg]["K"]
        pred = K["pred"][j]
        if greek:
            return wid[pred if pred else K["first"][j]][1:]
        if pred:
            return stem[pred][1:]
        return key.split(":")[1][1:]

    # ---- the layout: segments, D11 ------------------------------------------------------------------------------
    segs, lay_sha, nfiles = grc_layout() if greek else heb_layout()
    pins[f"{tag} layout"] = dict(path=os.path.relpath(GRC_LAYOUT if greek else HEB_LAYOUT, S.HERE), files=nfiles,
                                 sha256_of_files=lay_sha, segments=len(segs))
    seg_of = {}
    for si, s in enumerate(segs):
        for w in s["words"]:
            if w in seg_of:
                raise SystemExit(f"stage 05: layout word {w} in two segments")
            seg_of[w] = si
    if len({s["line"] for s in segs}) != len(segs):
        raise SystemExit("stage 05: layout line keys repeat")
    line = {}
    for key, *_ in order:
        a = anchor(key)
        si = seg_of.get(a)
        lg = crow[key][0]
        if si is None:
            line[key] = ""
            cnt[f"{lg} D11 clauses whose predicate (or first) piece is in no segment"] += 1
            ex[f"{lg} D11 clauses whose predicate (or first) piece is in no segment"].append(key)
        else:
            line[key] = segs[si]["line"]
            cnt[f"{lg} D11 clauses with a line"] += 1

    # ---- D9: dataset rows -> clauses ----------------------------------------------------------------------------
    corpus = "grc" if greek else "hbo"
    data = {}
    cc = pq.read_table(os.path.join(D, FILES[(corpus, "clause-columns")])).to_pylist()
    data["clause-columns"] = cc
    for ds in ("clause-extras", "connectives", "time-aspect"):
        data[ds] = read_tsv(os.path.join(D, FILES[("*", ds)]), corpus)
    for ds in ("clause-columns", "clause-extras", "connectives", "time-aspect", "arg-roles"):
        f = FILES[(corpus, ds)] if (corpus, ds) in FILES else FILES[("*", ds)]
        pins[f"{tag} {ds}"] = dict(file=f"data/{f}", sha256=sha256(os.path.join(D, f)))
    rows_of = {}   # dataset -> clause key -> row
    if not greek:
        tr = tree_ranks()
        pins["tan trees-macula.db"] = dict(file="trees-macula.db", sha256=sha256(TREES), cl_rows=len(tr))
        if len(tr) != len(order):
            raise SystemExit(f"stage 05: {len(tr)} tree-store clauses, {len(order)} lowfat clauses")
        rank_of = {tid: r for r, (tid, _rule) in enumerate(tr)}
        bad_rank = set()
        for r, (tid, rule) in enumerate(tr):
            if (rule or "") != order[r][1]:
                bad_rank.add(r)
                ex["tan D9 ranks whose tree-store rule differs from the lowfat rule"].append(
                    f"{r} {tid} {rule} {order[r][0]} {order[r][1]}")
        cnt["tan D9 ranks whose tree-store rule differs from the lowfat rule"] = len(bad_rank)
        key2cl = C.defaultdict(set)
        for s in segs:
            key2cl[s["clause_key"]].add(s["clause"])
        cnt["tan D9 layout clause_keys with two or more clause ids"] = sum(1 for v in key2cl.values() if len(v) > 1)
        lay_rank = {rank_of[s["clause"]] for s in segs if s["clause"] in rank_of}
        for ds, rows in data.items():
            got = {}
            for r in rows:
                ids = key2cl.get(r["clause_key"])
                if not ids:
                    why = "clause_key not in the layout"
                elif len(ids) > 1:
                    why = "clause_key names two or more layout clauses"
                else:
                    tid = next(iter(ids))
                    rk = rank_of.get(tid)
                    if rk is None:
                        why = "layout clause id is not a cl row of the tree store"
                    elif rk in bad_rank:
                        why = "the rule differs at this rank"
                    else:
                        key = order[rk][0]
                        if key in got:
                            why = "a second row for the same clause"
                        else:
                            got[key] = r
                            cnt[f"tan D9 {ds} rows joined"] += 1
                            continue
                cnt[f"tan D9 {ds} rows that found no clause: {why}"] += 1
                ex[f"tan D9 {ds} rows that found no clause"].append(f"{r['clause_key']} {why}")
            rows_of[ds] = got
        no_row_reason = {}
        for r, (key, rule, lang, dp, pids) in enumerate(order):
            no_row_reason[key] = ("the layout has a segment for it, the dataset no row" if r in lay_rank else
                                  "the layout gives it no segment of its own")
    else:
        first2seg = {s["first"]: si for si, s in enumerate(segs)}
        cand = C.defaultdict(list)
        for key, *_ in order:
            si = seg_of.get(anchor(key))
            if si is not None:
                cand[si].append(key)
        chosen = {}
        for si, keys in cand.items():
            m = min(depth[k] for k in keys)
            top = [k for k in keys if depth[k] == m]
            top.sort(key=doc_ix.get)
            chosen[si] = top[0]
            if len(top) > 1:
                cnt["grc D9 segments with two or more outermost candidate clauses (first in document order)"] += 1
                ex["grc D9 segments with two or more outermost candidate clauses"].append(
                    f"{segs[si]['line']} {' '.join(top)}")
            lg, j = crow[top[0]]
            if tables[lg]["K"]["pred"][j] == 0 and any(tables[crow[k][0]]["K"]["pred"][crow[k][1]] for k in keys):
                cnt["grc D9 segments given to a clause without pred while a clause with pred is a candidate"] += 1
        cnt["grc D9 segments with a clause"] = len(chosen)
        cnt["grc D9 segments without a clause"] = len(segs) - len(chosen)
        for si, s in enumerate(segs):
            if si not in chosen:
                ex["grc D9 segments without a clause"].append(s["line"])
        seg_chosen = set(chosen.values())
        for ds, rows in data.items():
            got = {}
            for r in rows:
                si = first2seg.get(r["clause_key"])
                if si is None:
                    why = "clause_key is not the first word of a segment"
                elif si not in chosen:
                    why = "no clause has its predicate (or first) word in the segment"
                else:
                    got[chosen[si]] = r
                    cnt[f"grc D9 {ds} rows joined"] += 1
                    continue
                cnt[f"grc D9 {ds} rows that found no clause: {why}"] += 1
                ex[f"grc D9 {ds} rows that found no clause"].append(f"{r['clause_key']} {why}")
            rows_of[ds] = got
        no_row_reason = {}
        for key, *_ in order:
            si = seg_of.get(anchor(key))
            if si is None:
                no_row_reason[key] = "its predicate (or first) word is in no segment"
            elif key not in seg_chosen:
                no_row_reason[key] = "a clause further out (or earlier) took its segment"
            else:
                no_row_reason[key] = "its segment has no dataset row"

    # ---- marks ----------------------------------------------------------------------------------------------------
    match = lemma_matcher(cnt, tag)
    diag = lemma_matcher(C.Counter(), tag)          # diagnostics only, not counted with the rule
    marks, use, src_val = {}, C.defaultdict(C.Counter), {}
    withheld_use = C.defaultdict(C.Counter)
    no_row_rules = C.defaultdict(C.Counter)
    left_items = C.defaultdict(C.Counter)
    tord = sorted(((tables[lg]["P"]["t"][i], tables[lg]["P"]["n"][i], pid) for lg in gl
                   for i, pid in enumerate(tables[lg]["P"]["pid"])))
    tpos = {x[2]: i for i, x in enumerate(tord)}

    def prev_of(pid, n):
        i = tpos[pid]
        return [tord[j][2] for j in range(max(0, i - n), i)][::-1]

    parent_of = {}
    for lg in gl:
        K = tables[lg]["K"]
        for k, p in zip(K["clause"], K["parent"]):
            parent_of[k] = p
    for key, rule, lang, dp, pids in order:
        m = {}
        lg = crow[key][0]
        any_row = False
        for cat, ds, col, _fr in CATS:
            r = rows_of[ds].get(key)
            if r is None:
                cnt[f"{lg} {cat}: clauses without a dataset row, {no_row_reason[key]}"] += 1
                continue
            any_row = True
            raw = r[col]
            if cat == "negator":
                if raw is None or raw == "":
                    continue
                lem = NEG_LEMMA.get(raw)
                if lem is None:
                    cnt[f"{lg} negator: dataset value not in the specification's list: {raw}"] += 1
                    continue
                got = match([lem], own[key])[0]
                if got is None:
                    cnt[f"{lg} negator: no own piece with the lemma (left out), {raw} {lem}"] += 1
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
                got = match(items, own[key])
                keys = [g for g in got if g is not None]
                for it, g in zip(items, got):
                    if g is None:
                        cnt[f"{lg} connective: items with no own piece of that lemma (left out)"] += 1
                        left_items[lg][it] += 1
                        ex[f"{lg} connective: items left out"].append(f"{key} {it}")
                        par = parent_of.get(key)
                        if par and diag([it], own[par])[0] is not None:
                            cnt[f"{lg} connective: left-out items whose lemma is among the parent clause's own "
                                "pieces (diagnostic)"] += 1
                        before = [(p, plex[p], lemma[plex[p]]) for p in prev_of(pids[0], 3) if p not in inner]
                        if diag([it], before)[0] is not None:
                            cnt[f"{lg} connective: left-out items whose lemma is a piece in no clause among the 3 "
                                "pieces before the clause (diagnostic)"] += 1
                    else:
                        src_val.setdefault((lg, cat, g), set()).add(it)
                        cnt[f"{lg} connective: items matched"] += 1
                for g in set(keys):
                    use[(lg, cat)][g] += 1
                if keys:
                    m[cat] = keys
                    cnt[f"{lg} connective: clauses with a list of {len(keys)}"] += 1
                continue
            code, sv = value_code(cat, raw, r if ds == "clause-columns" else None, cnt, lg)
            if code is None:
                cnt[f"{lg} {cat}: dataset row without a value ({raw!r})"] += 1
                continue
            if cat in WITHHELD:
                withheld_use[(lg, cat)][code] += 1
                continue
            m[cat] = code
            src_val.setdefault((lg, cat, code), set()).add(sv)
            use[(lg, cat)][code] += 1
        if not any_row:
            cnt[f"{lg} clauses without any dataset row"] += 1
            cnt[f"{lg} clauses without any dataset row, {no_row_reason[key]}"] += 1
            no_row_rules[lg][rule] += 1
        marks[key] = X.jdump(m)

    for lg in gl:
        extra[f"{lg} clauses without any dataset row, by rule (top 25)"] = dict(no_row_rules[lg].most_common(25))
        extra[f"{lg} connective: items left out, by item"] = dict(left_items[lg].most_common())

    # diagnostics of the Greek join (not used for any value): the outermost clause *with a predicate* instead
    if greek:
        def has_pred(k):
            lg_, j_ = crow[k]
            return tables[lg_]["K"]["pred"][j_] != 0
        alt = {}
        for si, keys in cand.items():
            pool = [k for k in keys if has_pred(k)] or keys
            alt[si] = min(pool, key=lambda k: (depth[k], doc_ix[k]))
        cnt["grc D9 (diagnostic) segments whose clause would differ under 'outermost clause with a pred'"] = sum(
            1 for si in chosen if alt[si] != chosen[si])
        for r in data["clause-columns"]:
            si = first2seg.get(r["clause_key"])
            if si in chosen and r["neg"]:
                lem = NEG_LEMMA[r["neg"]]
                cnt["grc D9 (diagnostic) negators found, the rule"] += diag([lem], own[chosen[si]])[0] is not None
                cnt["grc D9 (diagnostic) negators found, 'outermost clause with a pred'"] += \
                    diag([lem], own[alt[si]])[0] is not None
        for r in data["connectives"]:
            si = first2seg.get(r["clause_key"])
            if si in chosen and r["conn"]:
                items = r["conn"].split()
                cnt["grc D9 (diagnostic) connective items"] += len(items)
                cnt["grc D9 (diagnostic) connective items found, the rule"] += sum(
                    1 for g in diag(items, own[chosen[si]]) if g)
                cnt["grc D9 (diagnostic) connective items found, 'outermost clause with a pred'"] += sum(
                    1 for g in diag(items, own[alt[si]]) if g)

    # ---- D12: semantic roles --------------------------------------------------------------------------------------
    role_of, in_const, pclass_of = {}, {}, {}
    for (k_, o_), (hp_, pids_) in keep["const"].items():
        for p_ in pids_:
            # innermost constituent (the deepest clause's) wins
            if p_ not in in_const or depth[in_const[p_][0]] < depth[k_]:
                in_const[p_] = (k_, o_)
    for lg in gl:
        P = tables[lg]["P"]
        for pid, cl in zip(P["pid"], P["class"]):
            pclass_of[pid] = cl
    for lg in gl:
        N = tables[lg]["N"]
        for k, o, rl in zip(N["clause"], N["ord"], N["role"]):
            role_of[(k, o)] = rl
    roles = read_tsv(os.path.join(D, FILES[("*", "arg-roles")]), corpus)
    by_head = C.defaultdict(list)
    for i, r in enumerate(roles):
        if not r["head"]:
            cnt[f"{tag} D12 arg-roles rows without a head (found no constituent)"] += 1
            continue
        by_head[r["head"]].append(i)
    sem, sem_use = {}, C.defaultdict(C.Counter)
    used_rows = set()
    for (key, o), (hp, pids) in sorted(keep["const"].items(), key=lambda x: (doc_ix[x[0][0]], x[0][1])):
        lg = crow[key][0]
        cand = by_head.get(hp[1:], [])
        if len(cand) > 1:
            words = sorted(p[1:] for p in pids) if not greek else sorted(p[1:] for p in pids)
            cand = [i for i in cand if sorted(roles[i]["words"].split()) == words]
            cnt[f"{lg} D12 constituents whose head has two or more rows"] += 1
        if not cand:
            cnt[f"{lg} D12 constituents without an arg-roles row"] += 1
            cnt[f"{lg} D12 constituents without an arg-roles row, role {role_of[(key, o)]}"] += 1
            sem[(key, o)] = ""
            continue
        if len(cand) > 1:
            cnt[f"{lg} D12 constituents with two or more rows of the same words (none taken)"] += 1
            sem[(key, o)] = ""
            continue
        r = roles[cand[0]]
        used_rows.add(cand[0])
        val, basis = r["role"], r["role_basis"]
        cnt[f"{lg} D12 constituents with a row"] += 1
        if val in ("", "-"):
            cnt[f"{lg} D12 row with no role (empty)"] += 1
            sem[(key, o)] = ""
            continue
        if basis in LXX_BASES:
            cnt[f"{lg} D12 role not taken: rests on the Septuagint, basis {basis}"] += 1
            sem[(key, o)] = ""
            continue
        code = X.c0(val)
        if val not in SEM_ROLE_CODES:
            cnt[f"{lg} D12 role withheld (an English word), basis {basis}"] += 1
            withheld_use[(lg, "sem_role")][code] += 1
            sem[(key, o)] = ""
            continue
        sem[(key, o)] = code
        sem_use[lg][code] += 1
        src_val.setdefault((lg, "sem_role", code), set()).add(val)
    for i, r in enumerate(roles):
        if r["head"] and i not in used_rows:
            cnt[f"{tag} D12 arg-roles rows that found no constituent (head is no constituent's head piece)"] += 1
            cnt[f"{tag} D12 arg-roles rows that found no constituent, relation {r['relation']}"] += 1
            pfx = "n" if greek else "o"
            inside = in_const.get(pfx + r["head"])
            if inside is None:
                cnt[f"{tag} D12 arg-roles rows that found no constituent: head in no constituent"] += 1
            else:
                k_, o_ = inside
                hp_ = keep["const"][(k_, o_)][0]
                same_words = sorted(roles[i]["words"].split()) == sorted(
                    p[1:] for p in keep["const"][(k_, o_)][1])
                cnt[f"{tag} D12 arg-roles rows that found no constituent: head inside a constituent, not its head "
                    f"piece; same words {same_words}; that head piece's class {pclass_of.get(hp_)}"] += 1
            ex[f"{tag} D12 arg-roles rows that found no constituent"].append(f"{r['head']} {r['relation']}")
    return tables, order, marks, line, sem, use, sem_use, withheld_use, src_val


# ---- categories.toml: the clause part --------------------------------------------------------------------------

def clause_part(lang, tables_lang, use, sem_use, withheld_use, src_val, pins, tag):
    out = [MARKER, "# The clause categories of SPEC 1.0, section 8 (rule D9) and the semantic roles (D12).",
           "# `count` = clauses (constituents) of this table with the code. `rule`: C0, or",
           "# `lexeme` (the lexeme key of the clause's own piece with the listed lemma, D9). Datasets joined to",
           f"# the clauses through the layout {pins[tag + ' layout']['path']} (sha256 of its files "
           f"{pins[tag + ' layout']['sha256_of_files']})" + (
               f" and trees-macula.db ({pins['tan trees-macula.db']['sha256']})." if tag == "tan" else "."),
           "# Joined but not carried (English words naming a meaning; stage 05 report): "
           + ", ".join(f"{c} ({sum(withheld_use[(lang, c)].values())})" for c in WITHHELD + ("sem_role",)) + ".",
           ""]
    for cat, ds, col, fr in CATS:
        if cat in WITHHELD or not use[(lang, cat)]:
            continue
        if fr is None:
            fr = "form" if lang == "grc" else "reading"
        f = pins[f"{tag} {ds}"]
        out.append(f"[clauses.{cat}]")
        out.append('column = "marks"')
        out.append('basis = "derived"')
        out.append(f'source = {X.toml_str("rule D9 from our dataset " + ds)}')
        out.append(f"dataset = {X.toml_str(ds)}")
        out.append(f"file = {X.toml_str(f['file'])}")
        out.append(f"dataset_column = {X.toml_str(col)}")
        out.append(f"sha256 = {X.toml_str(f['sha256'])}")
        out.append(f"form_or_reading = {X.toml_str(fr)}")
        out.append("values = [")
        for code in sorted(use[(lang, cat)]):
            vals = sorted(src_val[(lang, cat, code)])
            rule = "lexeme" if cat in ("negator", "connective") else "C0"
            if len(vals) > 1:
                raise SystemExit(f"two source values give one code: {lang} {cat} {vals} -> {code}")
            out.append(f"  {{ code = {X.toml_str(code)}, value = {X.toml_str(vals[0])}, rule = {X.toml_str(rule)}, "
                       f"count = {use[(lang, cat)][code]} }},")
        out.append("]")
        out.append("")
    if sem_use[lang]:
        f = pins[f"{tag} arg-roles"]
        out.append("[constituents.sem_role]")
        out.append('column = "sem_role"')
        out.append('basis = "derived"')
        out.append('source = "rule D12 from our dataset arg-roles"')
        out.append('dataset = "arg-roles"')
        out.append(f"file = {X.toml_str(f['file'])}")
        out.append('dataset_column = "role"')
        out.append(f"sha256 = {X.toml_str(f['sha256'])}")
        out.append('form_or_reading = "reading"')
        out.append("values = [")
        for code in sorted(sem_use[lang]):
            out.append(f"  {{ code = {X.toml_str(code)}, value = {X.toml_str(sorted(src_val[(lang, 'sem_role', code)])[0])}, "
                       f'rule = "C0", count = {sem_use[lang][code]} }},')
        out.append("]")
        out.append("")
    return "\n".join(out)


def build(outdir, langs, counts):
    ex = C.defaultdict(list)
    cnt = C.Counter()
    pins = {}
    groups = []
    if {"hbo", "arc"} & set(langs):
        if not {"hbo", "arc"} <= set(langs):
            raise SystemExit("stage 05: hbo and arc are built together (one layout, one tree-store rank)")
        groups.append((("hbo", "arc"), False))
    if "grc" in langs:
        groups.append((("grc",), True))
    for gl, greek in groups:
        tag = "grc" if greek else "tan"
        tables, order, marks, line, sem, use, sem_use, withheld_use, src_val = compute(outdir, gl, greek, cnt, ex,
                                                                                        pins, counts)
        for lang in gl:
            T = tables[lang]
            K, N = T["K"], T["N"]
            K["marks"] = [marks[k] for k in K["clause"]]
            K["line"] = [line[k] for k in K["clause"]]
            N["sem_role"] = [sem.get((k, o), "") for k, o in zip(N["clause"], N["ord"])]
            d = os.path.join(outdir, lang)
            X.write_parquet(os.path.join(d, "clauses.parquet"), K, pa.schema(EC.CLAUSE_COLS))
            X.write_parquet(os.path.join(d, "constituents.parquet"), N, pa.schema(EC.CONST_COLS))
            path = os.path.join(d, "categories.toml")
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            piece_part = text.split(MARKER)[0].rstrip("\n") + "\n\n"
            X.write_text(path, piece_part + clause_part(lang, T, use, sem_use, withheld_use, src_val, pins, tag))
            n = len(K["clause"])
            parsed = [json.loads(v) for v in K["marks"]]
            cnt[f"{lang} clauses"] = n
            cnt[f"{lang} clauses with marks not empty"] = sum(1 for v in K["marks"] if v != "{}")
            cnt[f"{lang} clauses with a line"] = sum(1 for v in K["line"] if v)
            cnt[f"{lang} constituents"] = len(N["clause"])
            cnt[f"{lang} constituents with sem_role"] = sum(1 for v in N["sem_role"] if v)
            for cat, *_ in CATS:
                if cat in WITHHELD:
                    cnt[f"{lang} {cat}: clauses with a value (withheld, not carried)"] = \
                        sum(withheld_use[(lang, cat)].values())
                    counts[f"{lang} values withheld {cat}"] = dict(sorted(withheld_use[(lang, cat)].items()))
                else:
                    cnt[f"{lang} {cat}: clauses with a value"] = sum(1 for v in parsed if cat in v)
                    counts[f"{lang} values {cat}"] = dict(sorted(use[(lang, cat)].items()))
            counts[f"{lang} values withheld sem_role"] = dict(sorted(withheld_use[(lang, "sem_role")].items()))
            counts[f"{lang} values sem_role"] = dict(sorted(sem_use[lang].items()))
    counts["pins"] = pins
    for k in sorted(cnt):
        counts[k] = cnt[k]
    return ex
