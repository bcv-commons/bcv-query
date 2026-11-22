"""SPEC 1.3 (stage 27, e builds): the new columns and tables of CHANGES-1.3.md.

- setup(stage): the 1.3 column lists and the clause category `mood` (D9), set before the sub-stages run.
- terms(outdir, langs, counts): stage 14 of an e build. terms.tsv is read from the master (stage 26 wrote it) and
  checked, never written: its 82 rows of 1.2 must be what the 1.2 rules give, the 30 new rows are checked for form.
  terms-notes.md = the 1.2 notes, the 1.3 reference codes added to the list at the head, and the sections of
  terms-notes-1.3-rows.md appended unchanged.
- more_data(greek): the clause keys of reference-status and implicit-args, joined by stage 16's D9 (one row per key).
- hook16(...): inside stage 16, after D9 and D10: D9m (marks_model), D17 (ref_status, ref_form), D20 (noun_rel,
  noun_head_t, noun_head_n), D21 (clusivity, clusivity_basis), D18 (added.parquet; its `who` participants).
- close(outdir, langs, counts): the last sub-stage: passages.parquet (D22), the 1.3 part of categories.toml, the
  map.tsv rows of the new codes, the 1.3 sources in sources.json.
"""
import collections as C
import csv
import glob
import hashlib
import json
import os
import re
import unicodedata

import pyarrow as pa
import pyarrow.parquet as pq

import examples_common as X

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
D = os.path.join(HERE, "data")
SPEC = os.path.join(REPO, "internal-docs", "source-examples-spec")
MASTER = os.path.join(SPEC, "terms.tsv")
ROWS13 = os.path.join(SPEC, "terms-notes-1.3-rows.md")
NP = os.path.join(D, "reference-status", "np.tsv")
IA = os.path.join(D, "implicit-args", "args.tsv")
WE = os.path.join(D, "we-layer", "words.tsv")
WE_VOTES = os.path.join(D, "we-votes", "verses.tsv")
NR = os.path.join(D, "noun-relations", "pairs.tsv")
PF = os.path.join(D, "bridge-corpus", "inputs", "passage-facts@v0.1")
MARKER = "# ---- the 1.3 part (build_examples.py --stage 27) ----"
NEW_CATS = ("ref_status", "noun_rel", "clusivity", "mood", "added_kind")
TERM_COLS = ["category", "code", "hbo", "grc", "from_hbo", "from_grc", "source_hbo", "source_grc", "named_by", "checked"]
REF_FORM = {"noun": "noun", "pron": "pronoun", "adj": "adjective", "num": "number"}
NUMBER = {"s": "sg", "p": "pl", "d": "du"}
D9M_MOODS = ("irrealis", "declarative")
SECTION_KIND = {"sc.pe": "petuchah", "sc.sa": "setumah"}
LAYOUT_KIND = {"fm.ms.song": ("mam", "song"), "fm.ms.lines": ("mam", "lines"), "fm.ed.lines": ("nestle1904", "ed_lines"),
               "fm.ed.block": ("nestle1904", "ed_block"), "fm.ed.qlines": ("nestle1904", "ed_qlines")}
PIECE_COLS_13 = [("clusivity", pa.string()), ("clusivity_basis", pa.string()), ("noun_rel", pa.string()),
                 ("noun_head_t", pa.int64()), ("noun_head_n", pa.int64())]
CLAUSE_COLS_13 = [("marks_model", pa.string())]
CONST_COLS_13 = [("ref_status", pa.string()), ("ref_form", pa.string())]
ADDED_COLS = [("clause", pa.string()), ("verb", pa.int64()), ("role", pa.string()), ("kind", pa.string()),
              ("where", pa.string()), ("form", pa.string()), ("person", pa.string()), ("number", pa.string()),
              ("gender", pa.string()), ("antecedent", pa.string()), ("who", pa.string())]
PASSAGE_COLS = [("passage", pa.string()), ("source", pa.string()), ("kind", pa.string()), ("first", pa.int64()),
                ("last", pa.int64()), ("first_clause", pa.string()), ("last_clause", pa.string()),
                ("clauses", pa.int64()), ("crossing", pa.int64()), ("lines", pa.string()), ("fact", pa.string())]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def read_tsv(path, col=None, val=None):
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))
    return rows if col is None else [r for r in rows if r[col] == val]


def nfc(s):
    return unicodedata.normalize("NFC", s)


# ---- setup -------------------------------------------------------------------------------------------------------

def setup(stage):
    """Called by build_examples.py for an e build before each sub-stage. From stage 16 on the tables carry the 1.3
    columns; the clause category `mood` (SPEC 8) is a D9 category from the start (stage 16 makes the marks)."""
    import examples_values as EV
    import examples_values11 as V11
    import examples_shared11 as S11
    import examples_core
    import examples_clauses as EC
    X.V12 = True
    X.V13 = True
    if not any(c[0] == "mood" for c in EV.CATS):
        EV.CATS.append(("mood", "clause-extras", "mood", "reading"))
    if "mood" not in V11.MEANING:
        V11.MEANING = V11.MEANING + ("mood",)
        S11.MEANING = S11.MEANING + ("mood",)
    if "time_abs" not in S11.MEANING:      # SPEC 1.3 D16 (stage 28): a meaning key of clauses.marks, terms of time
        S11.MEANING = S11.MEANING + ("time_abs",)
    if stage >= "16":
        for lst, extra in ((examples_core.PIECE_COLS_11, PIECE_COLS_13), (EC.CLAUSE_COLS_11, CLAUSE_COLS_13),
                           (EC.CONST_COLS_11, CONST_COLS_13)):
            if lst[-1][0] != extra[-1][0]:
                lst.extend(extra)


# ---- terms (stage 14 of an e build) --------------------------------------------------------------------------------

def _script_ok(term, greek):
    for ch in term:
        if ch == " ":
            continue
        cp = ord(ch)
        if greek and not (0x0370 <= cp <= 0x03FF or 0x1F00 <= cp <= 0x1FFF or 0x0300 <= cp <= 0x036F):
            return False
        if not greek and not (0x0590 <= cp <= 0x05FF or 0xFB1D <= cp <= 0xFB4F):
            return False
    return True


def notes13(notes12):
    """The 1.2 notes, the 1.3 reference codes in the list at the head (sorted with the others), the 1.3 rows appended."""
    with open(ROWS13, encoding="utf-8") as fh:
        rows13 = fh.read()
    refs13 = re.search(r"\n## Reference codes\n\n(.*?)\n\n## ", rows13, re.S).group(1).split("\n")
    body13 = rows13.split("\n## The rows\n", 1)[1].lstrip("\n")
    head, rest = notes12.split("\n## Reference codes\n\n", 1)
    refs12, after = rest.split("\n\n", 1)
    refs = sorted(refs12.split("\n") + refs13)
    if len(set(r.split("`")[1] for r in refs)) != len(refs):
        raise SystemExit("stage 27: a 1.3 reference code is already in the 1.2 notes")
    return (head + "\n## Reference codes\n\n" + "\n".join(refs) + "\n\n" + after.rstrip("\n") + "\n\n"
            + "## The rows new in version 1.3\n\n" + "(Appended unchanged from `terms-notes-1.3-rows.md`, stage 26.)\n\n"
            + body13.rstrip("\n") + "\n")


def terms(outdir, langs, counts):
    import shutil
    import examples_terms12 as T12
    ex = C.defaultdict(list)
    rows, notes = T12.make_rows(counts, ex)
    with open(MASTER, encoding="utf-8", newline="") as fh:
        master = fh.read()
    want12 = [ln.rsplit("\t", 1)[0] for ln in T12.render(rows).rstrip("\n").split("\n")]
    have = master.rstrip("\n").split("\n")
    if [ln.rsplit("\t", 1)[0] for ln in have[:len(want12)]] != want12:
        raise SystemExit("stage 27: the 82 rows of 1.2 in the master terms.tsv differ from what the 1.2 rules give")
    hdr = have[0].split("\t")
    if hdr != TERM_COLS:
        raise SystemExit(f"stage 27: terms.tsv columns {hdr}")
    new = [dict(zip(hdr, ln.split("\t"))) for ln in have[len(want12):]]
    seen = C.defaultdict(set)
    for r in [dict(zip(hdr, ln.split("\t"))) for ln in have[1:]]:
        if len(r) != 10 or r["checked"]:
            raise SystemExit(f"stage 27: terms.tsv row {r}")
        for lg in ("hbo", "grc"):
            if r[lg]:
                if (r["category"], r[lg]) in seen[lg]:
                    raise SystemExit(f"stage 27: two codes of {r['category']} share the {lg} term {r[lg]}")
                seen[lg].add((r["category"], r[lg]))
    for r in new:
        if r["category"] not in NEW_CATS:
            raise SystemExit(f"stage 27: a new terms.tsv row of category {r['category']}")
        for lg in ("hbo", "grc"):
            if r[lg] and (not _script_ok(r[lg], lg == "grc") or nfc(r[lg]) != r[lg]):
                raise SystemExit(f"stage 27: term {r[lg]!r} not in the {lg} script or not NFC")
            if not r[lg] and (r[f"from_{lg}"] or r[f"source_{lg}"]):
                raise SystemExit(f"stage 27: empty {lg} term with a from or source cell: {r}")
            if r[lg] and r[f"from_{lg}"] not in ("tradition", "coined"):
                raise SystemExit(f"stage 27: a 1.3 term must be tradition or coined: {r}")
    with open(T12.NOTES, encoding="utf-8", newline="") as fh:
        notes12 = fh.read()
    if notes12 != T12.render_notes(rows, notes):
        raise SystemExit("stage 27: the master terms-notes.md (1.2) differs from what the 1.2 rules give")
    text = notes13(notes12)
    for lg in langs:
        os.makedirs(os.path.join(outdir, lg), exist_ok=True)
        shutil.copyfile(MASTER, os.path.join(outdir, lg, "terms.tsv"))
        X.write_text(os.path.join(outdir, lg, "terms-notes.md"), text)
    counts["terms rows"] = len(have) - 1
    counts["terms rows of 1.2 (checked against the 1.2 rules)"] = len(want12) - 1
    counts["terms rows new in 1.3"] = len(new)
    counts["terms rows by category"] = dict(C.Counter(ln.split("\t")[0] for ln in have[1:]))
    counts["terms empty cells (1.3)"] = [f"{r['category']} {r['code']} {lg}" for r in new for lg in ("hbo", "grc")
                                         if not r[lg]]
    return ex


# ---- stage 16: the joins ------------------------------------------------------------------------------------------

def more_data(greek):
    corpus = "grc" if greek else "hbo"
    keys = sorted({r["clause_key"] for p in (NP, IA) for r in read_tsv(p, "corpus", corpus)})
    return {"v13-clause-keys": [{"clause_key": k} for k in keys]}


def _term(terms, lg, cat, code):
    t = terms[lg].get((cat, code))
    if not t:
        raise SystemExit(f"stage 27: {lg} {cat} code {code!r} has no term in terms.tsv (a meaning value of a "
                         "language whose cell is empty fails the build, SPEC 4.10)")
    return t


def hook16(gl, greek, T, V, E, terms, cnt, ex, counts, pins):
    """Fills the 1.3 columns in T (pieces, clauses, constituents); returns {lang: added rows} and
    {lang: set of ent keys of added.who}."""
    import examples_people as EP
    tag = "grc" if greek else "tan"
    corpus = "grc" if greek else "hbo"
    pre = "n" if greek else "o"
    for p in (NP, IA, WE, WE_VOTES, NR):
        pins[os.path.relpath(p, HERE)] = sha256(p)
    piece = {}                                   # pid -> (lg, i, t, n, kind, class)
    for lg in gl:
        P = T[lg]["P"]
        for i, (pid, t, n, k, c) in enumerate(zip(P["pid"], P["t"], P["n"], P["kind"], P["class"])):
            piece[pid] = (lg, i, t, n, k, c)
    crow = {k: (lg, j) for lg in gl for j, k in enumerate(T[lg]["K"]["clause"])}
    ck2cl = {r["clause_key"]: k for k, r in V["rows_of"][("main", "v13-clause-keys")].items()}
    cnt[f"{tag} 1.3 D9 clause keys of reference-status and implicit-args that join a clause"] = len(ck2cl)

    # ---- D9m: Hebrew time, aspect (and mood) read off the Septuagint's parse go to marks_model ----------------------
    for lg in gl:
        K = T[lg]["K"]
        K["marks_model"] = [None] * len(K["clause"])
    if not greek:
        ta = V["rows_of"][("main", "time-aspect")]
        ce = V["rows_of"][("main", "clause-extras")]
        for k, r in ta.items():
            if "lxx" not in r["basis"]:
                continue
            lg, j = crow[k]
            K = T[lg]["K"]
            m = json.loads(K["marks"][j])
            mm = {}
            for cat in ("time", "aspect"):
                if cat in m:
                    mm[cat] = m.pop(cat)
                else:
                    cnt[f"{lg} 1.3 D9m rows with lxx in the basis and no {cat} value"] += 1
            er = ce.get(k)
            if er is not None and X.c0(er["mood"] or "x") in D9M_MOODS and "mood" in m:
                mm["mood"] = m.pop("mood")
            cnt[f"{lg} 1.3 D9m clauses with marks_model"] += 1
            for cat, v in mm.items():
                cnt[f"{lg} 1.3 D9m {cat} moved to marks_model"] += 1
                # the categories.toml counts of stage 16 count the strict marks: take the moved value out
                for c_, n_ in list(V["use"][(lg, cat)].items()):
                    if _term(terms, lg, cat, c_) == v:
                        V["use"][(lg, cat)][c_] -= 1
                        if V["use"][(lg, cat)][c_] == 0:
                            del V["use"][(lg, cat)][c_]
                        break
                counts.setdefault(f"{lg} 1.3 D9m values by category", C.Counter())[f"{cat} {v}"] += 1
            K["marks"][j] = X.jdump(m)
            K["marks_model"][j] = X.jdump(mm) if mm else None
            ex[f"{lg} D9m clauses whose time, aspect (mood) went to marks_model"].append(f"{k} {r['basis']}")
        for lg in gl:
            c_ = counts.get(f"{lg} 1.3 D9m values by category")
            if c_ is not None:
                counts[f"{lg} 1.3 D9m values by category"] = dict(sorted(c_.items()))

    # ---- D17: reference status on the constituent -------------------------------------------------------------------
    cons_of = C.defaultdict(list)
    for lg in gl:
        N = T[lg]["N"]
        N["ref_status"] = [""] * len(N["clause"])
        N["ref_form"] = [""] * len(N["clause"])
        for j, k in enumerate(N["clause"]):
            cons_of[k].append((lg, j))
    on_cons = C.defaultdict(list)
    for r in read_tsv(NP, "corpus", corpus):
        pid = pre + r["head"]
        if pid not in piece:
            cnt[f"{tag} 1.3 D17 rows whose head is no piece"] += 1
            ex[f"{tag} D17 rows whose head is no piece"].append(f"{r['clause_key']} {r['head']}")
            continue
        plg, _i, t, n, _k, _c = piece[pid]
        k = ck2cl.get(r["clause_key"])
        if k is None:
            cnt[f"{plg} 1.3 D17 rows not joined: clause not joined (D9)"] += 1
            continue
        hits = [(lg, j) for lg, j in cons_of.get(k, []) if T[lg]["N"]["first"][j] <= t <= T[lg]["N"]["last"][j]]
        if not hits:
            cnt[f"{plg} 1.3 D17 rows not joined: head word in no constituent of the clause"] += 1
            ex[f"{plg} D17 rows whose head word is in no constituent of the clause"].append(f"{k} {pid}")
            continue
        if len(hits) > 1:
            cnt[f"{plg} 1.3 D17 rows whose head word lies in two or more constituent spans"] += 1
            if getattr(X, "V15", False):     # SPEC 1.5 D17 (A5): not the `v` part; then the part headed by the word
                nv = [h for h in hits if T[h[0]]["N"]["role"][h[1]] != "v"]
                if nv and len(nv) < len(hits):
                    cnt[f"{plg} 1.5 D17 rows that a `v` part shared with another part (the other takes it)"] += 1
                hits = nv or hits
            best = [h for h in hits if T[h[0]]["N"]["head"][h[1]] == t]
            hits = best or hits
        lg, j = hits[0]
        exact = T[lg]["N"]["head"][j] == t
        cnt[f"{plg} 1.3 D17 rows joined: head word {'is' if exact else 'is not'} the constituent's head"] += 1
        on_cons[(lg, j)].append((not exact, t, n, pid, r))
    for (lg, j), rs in list(on_cons.items()):
        if getattr(X, "V15", False) and T[lg]["N"]["role"][j] == "p":     # SPEC 1.5 D17 (A7)
            keep = [x for x in rs if piece[x[3]][4] == "suffix" or piece[x[3]][5] == "pron"]
            for x in rs:
                if x not in keep:
                    cnt[f"{lg} 1.5 D17 rows left out: a `p` part whose head piece is no suffix or pronoun"] += 1
                    ex[f"{lg} 1.5 D17 rows left out on a p part"].append(f"{T[lg]['N']['clause'][j]} {x[3]}")
            if not keep:
                del on_cons[(lg, j)]
                continue
            rs[:] = keep
    for (lg, j), rs in on_cons.items():
        rs.sort(key=lambda x: (x[0], x[1], x[2]))
        if len(rs) > 1:
            cnt[f"{lg} 1.3 D17 constituents with two or more rows (the first taken)"] += 1
            cnt[f"{lg} 1.3 D17 rows not taken: another row on the same constituent"] += len(rs) - 1
            ex[f"{lg} D17 constituents with two or more rows"].append(
                f"{T[lg]['N']['clause'][j]} {T[lg]['N']['ord'][j]} " + " ".join(x[3] for x in rs))
        _nx, _t, _n, pid, r = rs[0]
        code = X.c0(r["status"])
        T[lg]["N"]["ref_status"][j] = _term(terms, lg, "ref_status", code)
        _l, _i, _t2, _n2, kind, cls = piece[pid]
        form = "suffix" if kind == "suffix" else REF_FORM.get(cls, "")
        if not form:
            cnt[f"{lg} 1.3 D17 ref_form empty: head piece of class {cls}"] += 1
            ex[f"{lg} D17 ref_form empty (class of the head piece)"].append(f"{pid} {cls}")
        T[lg]["N"]["ref_form"][j] = form
        cnt[f"{lg} 1.3 D17 constituents with ref_status"] += 1
        counts.setdefault(f"{lg} 1.3 ref_status", C.Counter())[code] += 1
        counts.setdefault(f"{lg} 1.3 ref_form", C.Counter())[form or "(empty)"] += 1

    # ---- D20, D21: pieces ----------------------------------------------------------------------------------------
    for lg in gl:
        P = T[lg]["P"]
        n_ = len(P["pid"])
        P["clusivity"], P["clusivity_basis"] = [""] * n_, [""] * n_
        P["noun_rel"], P["noun_head_t"], P["noun_head_n"] = [""] * n_, [None] * n_, [None] * n_
    for r in read_tsv(WE, "lang", corpus):
        pid = pre + r["key"]
        if pid not in piece:
            raise SystemExit(f"stage 27: inclusive-we row {r['key']} is no piece (D21 expects every row on a piece)")
        lg, i = piece[pid][:2]
        v, b = r["value"], r["basis"]
        cnt[f"{lg} 1.3 D21 inclusive-we rows"] += 1
        if v in ("split", "unknown"):
            cnt[f"{lg} 1.3 D21 empty: value {v}"] += 1
            continue
        code = {"i": "inclusive", "e": "exclusive"}.get(v)
        if code is None:
            raise SystemExit(f"stage 27: inclusive-we value {v!r}")
        if b == "votes":
            basis = "linked"
        elif "rule:" in b:
            basis = "derived"
        else:
            raise SystemExit(f"stage 27: inclusive-we basis {b!r} not named by D21")
        T[lg]["P"]["clusivity"][i] = _term(terms, lg, "clusivity", code)
        T[lg]["P"]["clusivity_basis"][i] = basis
        cnt[f"{lg} 1.3 D21 clusivity {basis}"] += 1
        counts.setdefault(f"{lg} 1.3 clusivity", C.Counter())[f"{code} {basis} ({b})"] += 1
    seen_dep = set()
    for r in read_tsv(NR, "corpus", corpus):
        h, d = pre + r["head"], pre + r["dependent"]
        if h not in piece or d not in piece:
            raise SystemExit(f"stage 27: noun-relations pair {r['head']} {r['dependent']} names no piece")
        if d in seen_dep:
            raise SystemExit(f"stage 27: noun-relations dependent {d} has two rows")
        seen_dep.add(d)
        lg, i = piece[d][:2]
        hl, hi, ht, hn = piece[h][:4]
        P = T[lg]["P"]
        P["noun_head_t"][i], P["noun_head_n"][i] = ht, hn
        rel = X.c0(r["relation"])
        same = (P["head_t"][i], P["head_n"][i]) == (ht, hn)
        where = "the dependent's own head" if same else ("another piece of the same word" if ht == P["t"][i]
                                                         else "elsewhere")
        cnt[f"{lg} 1.3 D20 pairs whose head is {where}"] += 1
        counts.setdefault(f"{lg} 1.3 D20 pairs by form and head", C.Counter())[f"{r['form']} {where}"] += 1
        if rel == "other":
            cnt[f"{lg} 1.3 D20 noun_rel empty: other"] += 1
            continue
        P["noun_rel"][i] = _term(terms, lg, "noun_rel", rel)
        counts.setdefault(f"{lg} 1.3 noun_rel", C.Counter())[rel] += 1

    # ---- D18: added.parquet -----------------------------------------------------------------------------------------
    added = {lg: [] for lg in gl}
    who_ents = {lg: set() for lg in gl}
    for r in read_tsv(IA, "corpus", corpus):
        k = ck2cl.get(r["clause_key"])
        # SPEC 4.11: `verb` is the verb word, for `poss` the noun word (the dataset's `antecedent` of a POSS row is
        # the noun itself; its `verb` is the clause's verb). Stage 30 mend: 1.3's first build wrote the clause's verb.
        vp = pre + (r["antecedent"] if r["role"] == "POSS" else r["verb"])
        if k is None:
            cnt[f"{tag} 1.3 D18 rows not joined: clause not joined (D9)"] += 1
            continue
        lg = crow[k][0]
        if vp not in piece:
            cnt[f"{lg} 1.3 D18 rows left out: the verb is no piece"] += 1
            ex[f"{lg} D18 rows whose verb is no piece"].append(f"{k} {r['verb']} {r['role']}")
            continue
        vl, _i, vt, _vn, _vk, _vc = piece[vp]
        if vl != lg:
            cnt[f"{lg} 1.3 D18 rows whose verb piece is in the other Tanakh table"] += 1
        role = "poss" if r["role"] == "POSS" else r["role"]
        kind = ("possessor" if r["role"] == "POSS" else "in_verb" if r["in_verb"] == "1" else
                "unsaid" if r["where"] == "unexpressed" else "elsewhere")
        ant = ""
        if r["antecedent"]:
            ap = pre + r["antecedent"]
            if kind == "unsaid":
                cnt[f"{lg} 1.3 D18 unsaid rows with an antecedent in the dataset (left empty)"] += 1
            elif ap in piece:
                ant = f"{piece[ap][2]}.{piece[ap][3]}"
            else:
                cnt[f"{lg} 1.3 D18 antecedent that is no piece (left empty)"] += 1
                ex[f"{lg} D18 antecedent that is no piece"].append(f"{k} {r['verb']} {r['role']} {r['antecedent']}")
        who = ""
        ref = r["referent"]
        if ref and not ref.startswith("lemma:") and ref != "unresolved":
            e = E.ent(ref, f"{lg} 1.3 D18 referent")
            if e:
                who = e
                who_ents[lg].add(e)
        cnt[f"{lg} 1.3 D18 rows, kind {kind}"] += 1
        cnt[f"{lg} 1.3 D18 rows with who"] += bool(who)
        added[lg].append((vt, role, k, kind, X.c0(r["where"]), "ending" if r["in_verb"] == "1" else "none",
                          r["person"], NUMBER.get(r["number"], r["number"]), r["gender"], ant, who))
    for lg in gl:
        rows = sorted(added[lg])
        keys = C.Counter((x[2], x[0], x[1]) for x in rows)
        cnt[f"{lg} 1.3 D18 keys (clause, verb, role) with two or more rows"] = sum(1 for v in keys.values() if v > 1)
        added[lg] = [dict(clause=x[2], verb=x[0], role=x[1], kind=_term(terms, lg, "added_kind", x[3]), where=x[4],
                          form=x[5], person=x[6], number=x[7], gender=x[8], antecedent=x[9], who=x[10]) for x in rows]
        cnt[f"{lg} 1.3 added rows"] = len(rows)
    for key in list(counts):
        if key.endswith(("1.3 ref_status", "1.3 ref_form", "1.3 clusivity", "1.3 noun_rel", "pairs by form and head")):
            counts[key] = dict(sorted(counts[key].items()))
    return added, who_ents


def write_added(d, rows):
    cols = ADDED_COLS + ([("who_reason", pa.string())] if getattr(X, "V15", False) else [])    # SPEC 1.5 4.11
    X.write_parquet(os.path.join(d, "added.parquet"), {c: [r[c] for r in rows] for c, _t in cols}, pa.schema(cols))


# ---- close: passages, categories, map, sources --------------------------------------------------------------------

def _read(path, cols=None):
    return pq.read_table(path, columns=cols).to_pydict()


def passages(outdir, cnt, ex):
    """D22 -> {lang: rows}."""
    W, Kc = {}, {}
    for lg in ("hbo", "arc", "grc"):
        W[lg] = _read(os.path.join(outdir, lg, "words.parquet"), ["t", "id", "book", "clause"])
        Kc[lg] = _read(os.path.join(outdir, lg, "clauses.parquet"), ["clause", "first", "last"])
    P = {lg: _read(os.path.join(outdir, lg, "pieces.parquet"), ["t"]) for lg in ("hbo", "arc")}
    npieces = C.Counter()
    for lg in ("hbo", "arc"):
        for t in P[lg]["t"]:
            npieces[(t, lg)] += 1
    t_of, clause_of, book_of = {}, {}, {}
    for lg in W:                 # t numbers of the Tanakh and of the New Testament overlap: keyed by (greek, t)
        for t, i, b, c in zip(W[lg]["t"], W[lg]["id"], W[lg]["book"], W[lg]["clause"]):
            t_of[i] = t
            clause_of[(lg == "grc", t)] = c
            book_of[(lg == "grc", t)] = b
    firsts = {"tan": sorted((f, l) for lg in ("hbo", "arc") for f, l in zip(Kc[lg]["first"], Kc[lg]["last"])),
              "grc": sorted(zip(Kc["grc"]["first"], Kc["grc"]["last"]))}
    import bisect
    ff = {g: [x[0] for x in v] for g, v in firsts.items()}
    words_of_book = C.defaultdict(list)
    for lg in ("hbo", "arc"):
        for t, b in zip(W[lg]["t"], W[lg]["book"]):
            words_of_book[b].append(t)
    for b in words_of_book:
        words_of_book[b].sort()

    def wt(key, greek):
        wid = ("n" + key) if greek else ("o" + key[:11])
        t = t_of.get(wid)
        if t is None:
            raise SystemExit(f"stage 27: passage-facts word {key} is no word of the build (D22)")
        return t

    def unit(source, kind, first, last, lines, fact, greek):
        g = "grc" if greek else "tan"
        lo, hi = bisect.bisect_left(ff[g], first), bisect.bisect_right(ff[g], last)
        inside = firsts[g][lo:hi]
        crossing = sum(1 for f, l in inside if l > last)
        if greek:
            lg = "grc"
        else:
            nh = sum(npieces[(t, "hbo")] for t in range(first, last + 1))
            na = sum(npieces[(t, "arc")] for t in range(first, last + 1))
            lg = "arc" if na > nh else "hbo"
            if na and nh:
                cnt[f"tan 1.3 D22 units with pieces of both languages (in {lg})"] += 1
        if crossing:
            ex[f"{lg} D22 units with clauses that begin in them and end after them"].append(
                f"ps:{source}:{kind}:{first} {crossing}")
        return lg, dict(passage=f"ps:{source}:{kind}:{first}", source=source, kind=kind, first=first, last=last,
                        first_clause=clause_of[(greek, first)], last_clause=clause_of[(greek, last)], clauses=len(inside),
                        crossing=crossing, lines=lines, fact=fact)

    facts = []
    files = sorted(glob.glob(os.path.join(PF, "data", "*.jsonl")))
    for f in files:                      # file order (book code), then line order: the first fact keeps a repeated unit
        with open(f, encoding="utf-8") as fh:
            for ln in fh:
                r = json.loads(ln)
                if r["kind"] == "section" or (r["kind"] == "form" and r["value"] in LAYOUT_KIND):
                    facts.append(r)
                elif r["kind"] == "form":
                    cnt[f"1.3 D22 form facts not taken: {r['value']} {','.join(r['src'])}"] += 1
    out = C.defaultdict(list)
    marks = C.defaultdict(list)            # (source, book) -> [(t, kind, id)]
    seen_layout = {}
    for r in facts:
        greek = len(r["first"]) == 11
        if r["kind"] == "section":
            src = ",".join(r["src"])
            if src not in ("oshb", "mam") or r["value"] not in SECTION_KIND or greek:
                raise SystemExit(f"stage 27: section fact {r['id']} {src} {r['value']}")
            t = wt(r["after"], False)
            marks[(src, book_of[(False, t)])].append((t, r["after"], SECTION_KIND[r["value"]], r["id"]))
        else:
            source, kind = LAYOUT_KIND[r["value"]]
            first, last = wt(r["first"], greek), wt(r["last"], greek)
            lines = X.jdump([[wt(a, greek), wt(b, greek)] for a, b in r.get("lines", [])]) if r.get("lines") else None
            lg, u = unit(source, kind, first, last, lines, r["id"], greek)
            prev = seen_layout.get(u["passage"])
            if prev is not None:       # the source gives the same unit twice (same kind, first, last, lines): one unit
                if (prev["last"], prev["lines"]) != (last, lines):
                    raise SystemExit(f"stage 27: two {kind} facts with one first word and different spans: {r['id']}")
                cnt[f"{lg} 1.3 D22 layout facts that repeat a unit of the same kind and span (no unit; listed)"] += 1
                ex[f"{lg} D22 layout fact repeating a unit (no unit)"].append(f"{r['id']} = {prev['fact']}")
                continue
            seen_layout[u["passage"]] = u
            out[lg].append(u)
            cnt[f"{lg} 1.3 D22 units {source} {kind}"] += 1
    for (src, book), ms in sorted(marks.items()):
        ms.sort()
        words = words_of_book[book]
        start = words[0]
        last_t = None
        for t, _after, kind, fid in ms:
            if t == last_t:       # a second mark of the source on the same word (after another piece): no unit
                cnt[f"tan 1.3 D22 {src} marks on a word that already closes a unit (no unit; listed)"] += 1
                ex[f"tan D22 {src} second mark on one word (no unit)"].append(f"{book} {fid} {kind} t {t}")
                continue
            last_t = t
            if t < start:
                raise SystemExit(f"stage 27: {src} marks out of order in {book}: {fid}")
            lg, u = unit(src, kind, start, t, None, fid, False)
            out[lg].append(u)
            cnt[f"{lg} 1.3 D22 units {src} {kind}"] += 1
            nxt = bisect.bisect_right(words, t)
            start = words[nxt] if nxt < len(words) else None
            if start is None:
                break
        if start is not None:
            lg, u = unit(src, "book_end", start, words[-1], None, "", False)
            out[lg].append(u)
            cnt[f"{lg} 1.3 D22 units {src} book_end"] += 1
    for lg in out:
        out[lg].sort(key=lambda u: (u["source"], u["first"], u["kind"]))
    return out, files


def _vals(counter, term_of=None):
    out = []
    for code, n in sorted(counter.items()):
        t = f", term = {X.toml_str(term_of(code))}" if term_of else ""
        out.append(f"  {{ code = {X.toml_str(code)}{t}, count = {n} }},")
    return out


def cat_part(lang, tabs, terms_lg, pins, pfiles):
    """The 1.3 part of categories.toml: every new coded column and meaning category, with codes, terms, counts."""
    P, K, N, A, S = tabs["P"], tabs["K"], tabs["N"], tabs["A"], tabs["S"]
    code_of = {cat: {t: c for (cc, c), t in terms_lg.items() if cc == cat} for cat in NEW_CATS + ("time", "aspect")}
    code_of["time_abs"] = code_of["time"]             # D16: time_abs takes the terms of time
    L = [MARKER, "# SPEC 1.3 (stage 27): the new columns and tables. `count` = rows with the value; a meaning value",
         "# is a term of terms.tsv, declared with its code.", ""]

    def sec(name, basis, source, counter, meaning=None, extra=()):
        nonlocal L
        L += [f"[{name}]", f"basis = {X.toml_str(basis)}", f"source = {X.toml_str(source)}", *extra]
        if meaning:
            L.append('meaning = "terms.tsv"')
            L += ["values = ["] + [f"  {{ code = {X.toml_str(code_of[meaning][t])}, term = {X.toml_str(t)}, count = {n} }},"
                                   for t, n in sorted(counter.items(), key=lambda kv: code_of[meaning][kv[0]])] + ["]", ""]
        else:
            L += ["values = ["] + _vals(counter) + ["]", ""]

    def dsx(path):
        return (f"dataset_file = {X.toml_str(os.path.relpath(path, HERE))}", f"sha256 = {X.toml_str(pins[os.path.relpath(path, HERE)])}")
    cl = C.Counter(v for v in P["clusivity"] if v)
    if cl:
        sec("pieces.clusivity", "linked, derived (clusivity_basis)", "rule D21 from inclusive-we words.tsv value",
            cl, "clusivity", dsx(WE) + ('dataset_column = "value"', 'form_or_reading = "reading"'))
        sec("pieces.clusivity_basis", "derived", "rule D21: inclusive-we basis votes -> linked; a rule (rule:..., "
            "votes+rule:..., rule:...,votes_split) -> derived", C.Counter(v for v in P["clusivity_basis"] if v))
    nr = C.Counter(v for v in P["noun_rel"] if v)
    if nr:
        sec("pieces.noun_rel", "derived", "rule D20 from noun-relations pairs.tsv relation (other -> empty)", nr,
            "noun_rel", dsx(NR) + ('dataset_column = "relation"', 'form_or_reading = "reading"'))
    L += ["[pieces.noun_head_t]", 'basis = "derived"', 'source = "rule D20: the t of the pair\'s head piece"',
          f"pattern = \"a t of pieces.parquet\"", f"count = {sum(1 for v in P['noun_head_t'] if v is not None)}", ""]
    # clauses.mood is declared by stage 16's clause part (a D9 category, SPEC 8)
    mm = C.Counter((cat, v) for m in K["marks_model"] if m for cat, v in json.loads(m).items())
    if True:          # declared in every language (grc: no value, null on every clause)
        L += ["[clauses.marks_model]", 'basis = "model"', 'human_check = "no human check"',
              f"filled = {'true' if mm else 'false'}", 'model = "M7: GLAUx automatic parse of the Septuagint verb '
              '(lxx_tense, lxx_mood of clause-columns), read by the time-aspect dataset"',
              'dataset = "time-aspect (rows whose basis contains lxx); clause-extras mood (irrealis, declarative)"',
              'models = ["GLAUx automatic annotation (lemma, class, parse)"]', 'version = "not recorded"',
              'run = "spine releases lxx-glaux-2026-10-10, lxx-glaux-dan-theodotion-2026-11-14"',
              'source = "rule D9m"', 'form_or_reading = "reading"', 'meaning = "terms.tsv"', "values = ["]
        for (cat, v), n in sorted(mm.items(), key=lambda kv: (kv[0][0], code_of[kv[0][0]][kv[0][1]])):
            L.append(f"  {{ category = {X.toml_str(cat)}, code = {X.toml_str(code_of[cat][v])}, term = {X.toml_str(v)}, "
                     f"count = {n} }},")
        L += ["]", ""]
    rs = C.Counter(v for v in N["ref_status"] if v)
    if rs:
        sec("constituents.ref_status", "derived", "rule D17 from reference-status np.tsv status", rs, "ref_status",
            dsx(NP) + ('dataset_column = "status"', 'form_or_reading = "reading"'))
        sec("constituents.ref_form", "derived", "rule D17: the head piece's kind (suffix) or class (noun, pron, adj, num)",
            C.Counter(v for v in N["ref_form"] if v), extra=('form_or_reading = "form"',))
    if A["clause"]:
        src = "rule D18 from implicit-args args.tsv"
        sec("added.role", "given", src + " role (POSS -> poss); the frame labels as MACULA writes them", C.Counter(A["role"]),
            extra=dsx(IA) + ('dataset_column = "role"',))
        if getattr(X, "V16", False):     # SPEC 1.6 D18 step 2 (R1, R5)
            sec("added.kind", "derived", src + " (1.6): POSS -> possessor; a subject row (4.11 of 1.6: under a causative "
                "stem AA where the frame has an AA, else A0; under any other stem A0) whose verb's stem piece has a "
                "person -> in_verb; every other row: where unexpressed -> unsaid, else elsewhere (the dataset's in_verb "
                "is not read)", C.Counter(A["kind"]), "added_kind", ('form_or_reading = "reading"',))
        elif getattr(X, "V15", False):     # SPEC 1.5 D18 step 2
            sec("added.kind", "derived", src + " (1.5): POSS -> possessor; a subject row whose verb's stem piece has a "
                "person -> in_verb; the A0 row under a causative stem: where unexpressed -> unsaid, else elsewhere; "
                "every other row as 1.3 (in_verb 1 -> in_verb; where unexpressed -> unsaid; else elsewhere)",
                C.Counter(A["kind"]), "added_kind", ('form_or_reading = "reading"',))
        else:
            sec("added.kind", "derived", src + ": POSS -> possessor; in_verb 1 -> in_verb; where unexpressed -> unsaid; "
                "else elsewhere", C.Counter(A["kind"]), "added_kind", ('form_or_reading = "reading"',))
        sec("added.where", "given", src + " where (C0)", C.Counter(A["where"]), extra=('dataset_column = "where"',))
        if getattr(X, "V16", False):
            sec("added.form", "derived", src + " (1.6): ending on a subject row (4.11 of 1.6) whose verb's stem piece "
                "has a person, else none", C.Counter(A["form"]), extra=('form_or_reading = "form"',))
            sec("added.who_reason", "derived", "rule D18 step W (1.6): how `who` was found from the text's own pieces "
                "(pieces.who), or why it is empty; the two readings agree where one set holds the other (a singular "
                "verb takes the smaller set, any other the larger), overlap gives the common entities, none shared "
                "gives disagree (listed as SE5 in source_errors.tsv)", C.Counter(A["who_reason"]),
                extra=('form_or_reading = "form"',))
        elif getattr(X, "V15", False):
            sec("added.form", "derived", src + " (1.5): ending on a subject row whose verb's stem piece has a person, "
                "else none", C.Counter(A["form"]), extra=('form_or_reading = "form"',))
            sec("added.who_reason", "derived", "rule D18 step W (1.5): how `who` was found from the text's own pieces "
                "(pieces.who), or why it is empty", C.Counter(A["who_reason"]), extra=('form_or_reading = "form"',))
        else:
            sec("added.form", "derived", src + ": in_verb 1 -> ending, else none", C.Counter(A["form"]),
                extra=('form_or_reading = "form"',))
        e16 = (" (1.6) on rows of form ending: the verb's stem piece's marks, empty where it has none; on every other "
               "row:") if getattr(X, "V16", False) else ""
        sec("added.person", "derived", src + e16 + " person (the codes of 4.10); for poss the dataset's guess from the clause's "
            "subject", C.Counter(v for v in A["person"] if v))
        sec("added.number", "derived", src + e16 + " number: s -> sg, p -> pl, d -> du; for poss the dataset's guess from "
            "the clause's subject", C.Counter(v for v in A["number"] if v))
        sec("added.gender", "derived", src + e16 + " gender (the codes of 4.10); for poss the dataset's guess from the "
            "clause's subject", C.Counter(v for v in A["gender"] if v))
    if S["passage"]:
        pf = os.path.join(PF, "PIN.json")
        L += ["[passages.source]", 'basis = "given"', 'source = "passage-facts v0.1 src (D22)"',
              f"dataset_file = {X.toml_str(os.path.relpath(PF, HERE))}", f"pin_sha256 = {X.toml_str(sha256(pf))}",
              f"sha256_of_files = {X.toml_str(hashlib.sha256(''.join(sha256(f) for f in pfiles).encode()).hexdigest())}",
              "values = ["] + _vals(C.Counter(S["source"])) + ["]", ""]
        sec("passages.kind", "given", "passage-facts v0.1: sc.pe -> petuchah, sc.sa -> setumah, the rest of a book -> "
            "book_end; fm.ms.song -> song, fm.ms.lines -> lines, fm.ed.lines -> ed_lines, fm.ed.block -> ed_block, "
            "fm.ed.qlines -> ed_qlines", C.Counter(S["kind"]), extra=('form_or_reading = "form"',))
    return "\n".join(L).rstrip("\n") + "\n"


MAP13 = {("pieces", "clusivity"): "reading", ("pieces", "noun_rel"): "reading", ("clauses", "mood"): "reading",
         ("constituents", "ref_status"): "reading", ("added", "kind"): "reading",
         ("constituents", "ref_form"): "realisation_not_a_feature", ("added", "form"): "realisation_not_a_feature"}


def close(outdir, langs, counts):
    import examples_values11 as V11
    ex = C.defaultdict(list)
    cnt = C.Counter()
    units, pfiles = passages(outdir, cnt, ex)
    for lg in langs:
        d = os.path.join(outdir, lg)
        X.write_parquet(os.path.join(d, "passages.parquet"), {c: [u[c] for u in units.get(lg, [])] for c, _t in PASSAGE_COLS},
                        pa.schema(PASSAGE_COLS))
        tabs = dict(P=_read(os.path.join(d, "pieces.parquet"), ["clusivity", "clusivity_basis", "noun_rel", "noun_head_t"]),
                    K=_read(os.path.join(d, "clauses.parquet"), ["marks", "marks_model"]),
                    N=_read(os.path.join(d, "constituents.parquet"), ["ref_status", "ref_form"]),
                    A=_read(os.path.join(d, "added.parquet")),
                    S=_read(os.path.join(d, "passages.parquet"), ["passage", "source", "kind"]))
        terms_lg = V11.read_terms(outdir, lg)
        pins = {os.path.relpath(p, HERE): sha256(p) for p in (NP, IA, WE, WE_VOTES, NR)}
        path = os.path.join(d, "categories.toml")
        with open(path, encoding="utf-8") as fh:
            text = fh.read().split(MARKER)[0].rstrip("\n") + "\n\n"
        X.write_text(path, text + cat_part(lg, tabs, terms_lg, pins, pfiles))
        # map.tsv: the new codes (SPEC 13: meaning categories -> none, reading; ref_form, added.form -> their own reason)
        mp = os.path.join(d, "map.tsv")
        with open(mp, encoding="utf-8", newline="") as fh:
            rows = [ln.rstrip("\n").split("\t") for ln in fh]
        hdr, body = rows[0], [r for r in rows[1:] if (r[0], r[1]) not in MAP13]
        inv = {cat: {t: c for (cc, c), t in terms_lg.items() if cc == cat} for cat in NEW_CATS}
        new = C.Counter()
        for v in tabs["P"]["clusivity"]:
            if v:
                new[("pieces", "clusivity", inv["clusivity"][v])] += 1
        for v in tabs["P"]["noun_rel"]:
            if v:
                new[("pieces", "noun_rel", inv["noun_rel"][v])] += 1
        for m in tabs["K"]["marks"]:
            v = json.loads(m).get("mood")
            if v:
                new[("clauses", "mood", inv["mood"][v])] += 1
        for v, f in zip(tabs["N"]["ref_status"], tabs["N"]["ref_form"]):
            if v:
                new[("constituents", "ref_status", inv["ref_status"][v])] += 1
            if f:
                new[("constituents", "ref_form", f)] += 1
        for v, f in zip(tabs["A"]["kind"], tabs["A"]["form"]):
            new[("added", "kind", inv["added_kind"][v])] += 1
            new[("added", "form", f)] += 1
        body += [[a, b, c, "none", "", MAP13[(a, b)], str(n)] for (a, b, c), n in sorted(new.items())]
        body.sort(key=lambda r: (r[0], r[1], r[2], r[3], r[4]))
        X.write_tsv(mp, hdr, body)
        cnt[f"{lg} 1.3 map.tsv rows added"] = len(new)
        # stage 29: categories.toml [map.reason] declares the reasons of the final map.tsv, the 1.3 rows among them
        # (the no-English check (a) found `realisation_not_a_feature` undeclared and the count of `reading` stale)
        with open(path, encoding="utf-8") as fh:
            ctext = fh.read()
        rc = C.Counter(r[5] for r in body if r[3] == "none")
        i = ctext.index("[map.reason]\n")
        j = ctext.index("values = [\n", i)
        k = ctext.index("]\n", j) + 2
        vals = "values = [\n" + "".join(f'  {{ code = "{c}", count = {n} }},\n' for c, n in sorted(rc.items())) + "]\n"
        src_old = ctext[i:j]
        src_new = src_old.replace("unknown_value, lexeme_value\"", "unknown_value, lexeme_value; reading (meaning "
                                  "categories and readings, SPEC 1.2 and 1.3); realisation_not_a_feature (ref_form, "
                                  "added.form, SPEC 1.3)\"")
        X.write_text(path, ctext[:i] + src_new + vals + ctext[k:])
        # sources.json: the 1.3 sources (stage 29 writes the whole file anew)
        sj = os.path.join(d, "sources.json")
        with open(sj, encoding="utf-8") as fh:
            doc = json.load(fh)
        doc["v13"] = {
            "stage": "27",
            "reference-status": dict(file=os.path.relpath(NP, HERE), sha256=pins[os.path.relpath(NP, HERE)], basis="derived",
                                     build="local build 4ee0442; release v0.2 7612f663", model="none named"),
            "implicit-args": dict(file=os.path.relpath(IA, HERE), sha256=pins[os.path.relpath(IA, HERE)], basis="derived",
                                  build="local build cd2c348; not released", model="none named"),
            "inclusive-we": dict(files={os.path.relpath(WE, HERE): pins[os.path.relpath(WE, HERE)],
                                        os.path.relpath(WE_VOTES, HERE): pins[os.path.relpath(WE_VOTES, HERE)]},
                                 basis="linked (votes), derived (rules)", build="local build fc06571; release v0.1 d2d67cf4",
                                 model="none named"),
            "noun-relations": dict(file=os.path.relpath(NR, HERE), sha256=pins[os.path.relpath(NR, HERE)], basis="derived",
                                   build="local build 75dc6e1; release v0.1", model="none named"),
            "passage-facts": dict(folder=os.path.relpath(PF, HERE), pin_sha256=sha256(os.path.join(PF, "PIN.json")),
                                  files={os.path.relpath(f, HERE): sha256(f) for f in pfiles}, basis="given",
                                  release="v0.1, Hugging Face commit bbb9b2e3",
                                  licence="CC BY-SA 4.0 (MAM); OSHB CC BY 4.0; Nestle 1904 public domain"),
            "marks_model": dict(basis="model", model="M7: GLAUx's automatic parse of the Septuagint verb, read by the "
                                "time-aspect dataset (lxx_tense, lxx_mood of clause-columns)", models=[
                                    "GLAUx automatic annotation"], version="not recorded",
                                run="spine releases lxx-glaux-2026-10-10, lxx-glaux-dan-theodotion-2026-11-14",
                                human_check="no human check"),
        }
        doc.setdefault("model", {})["time-aspect-lxx-parse"] = doc["v13"]["marks_model"]
        X.write_text(sj, json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        counts[f"{lg} passages"] = len(units.get(lg, []))
    for k in sorted(cnt):
        counts[k] = cnt[k]
    return ex
