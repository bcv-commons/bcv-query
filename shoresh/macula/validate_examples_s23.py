"""Stage 23 checks of the source examples (SPEC 1.2, sections 10 and 13), for d builds.

Imports nothing from the builders and reads nothing from a build's cache/. Called by validate_examples.py:
  terms12(R, build)       the terms condition of SPEC 10 (ten columns, checked empty, rule T recomputed with the pair,
                          no preposition word in a sem_role term, reference codes and rule T cells in terms-notes.md)
  lxx12(...)              the links condition for the Septuagint (two passes, bridge accounting, agree_model), called
                          from validate_examples_s19.py with what that module has read
  stage23(R, build)       participants (no name הַ, no model who), and every column SPEC 13 calls unchanged against c1
"""
import collections as C
import csv
import json
import os
import re
import unicodedata as U

import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(HERE, "data")
SPEC = os.path.join(REPO, "internal-docs", "source-examples-spec")
BRIDGE = os.path.join(REPO, "internal-docs/hebrew-greek-cf-release/v0.2/bridges/lxx.parquet")
TERM_COLS = ["category", "code", "hbo", "grc", "from_hbo", "from_grc", "source_hbo", "source_grc", "named_by", "checked"]
STRICT_HOW = {"sure", "order", "neighbours", "form_near", "verse_form"}
MODEL_HOW = {"number", "lemma", "verse_lemma", "verse_number"}
nfc = lambda s: U.normalize("NFC", s)  # noqa: E731
LEX_RE = re.compile(r"^lex:(hbo|arc|grc):\S.*$")
REF_RE = re.compile(r"^ref:[a-z0-9]+(_[a-z0-9]+)*$")


V13 = False   # SPEC 1.3 (e builds): set by validate_examples.py
V18 = False   # SPEC 1.8 (j builds): set by validate_examples.py (D13a form_near, M4)


def tsv(path):
    csv.field_size_limit(1 << 30)
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))


def table(path, columns=None):
    return pq.read_table(path, columns=columns).to_pylist()


def c0(v):
    return re.sub(r"[^a-z0-9]+", "_", v.lower()).strip("_")


def script(s, greek):
    for ch in s:
        if ch in " ͏᾽’ʼ'":
            continue
        n = U.name(ch, "")
        if U.category(ch).startswith("M"):
            continue
        if greek and "GREEK" not in n:
            return False
        if not greek and "HEBREW" not in n:
            return False
    return bool(s.strip())


def heb_norm(s):
    return nfc("".join(ch for ch in s if not ("֑" <= ch <= "֯" or ch in "ֽׅׄ")))


# ---- terms ----------------------------------------------------------------------------------------------------------

def _rule_t(build):
    """Rule T (SPEC 4.10), written apart from the builder: -> {(cat, code, lg): (kind, item(s), rows, total)},
    {(cat, code, lg): (commonest item, rows)}."""
    b1 = os.path.join(os.path.dirname(os.path.normpath(build)), "b1")
    arcv = {(r["book"], r["chapter"], r["verse"]) for r in table(os.path.join(b1, "arc", "words.parquet"),
                                                                  ["book", "chapter", "verse"])}
    vkey = {}
    for r in table(os.path.join(DATA, "clause-columns", "hebrew.parquet"), ["clause_key", "ref"]):
        book, cv = r["ref"].split(" ", 1)
        c, v = cv.split(".")[0].split(":")
        vkey[r["clause_key"]] = (book, int(c), int(v))
    out, common = {}, {}
    for cat, path, vcol, icol in (("relation", "connectives/clauses.tsv", "relation", "conn"),
                                  ("sem_role", "arg-roles/roles.tsv", "role", "prep_lemma")):
        one = {lg: C.Counter() for lg in ("hbo", "grc")}
        two = {lg: C.Counter() for lg in ("hbo", "grc")}
        tot = {lg: C.Counter() for lg in ("hbo", "grc")}
        for r in tsv(os.path.join(DATA, path)):
            lg, val = r["corpus"], r[vcol]
            if val in ("", "-") or lg not in one:
                continue
            if lg == "hbo" and (r["clause_key"] not in vkey or vkey[r["clause_key"]] in arcv):
                continue
            code = c0(val)
            tot[lg][code] += 1
            items = [nfc(x) for x in r[icol].split()]
            for it in set(items):
                one[lg][(code, it)] += 1
            seen = set()
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    if items[i] != items[j] and frozenset((items[i], items[j])) not in seen:
                        seen.add(frozenset((items[i], items[j])))
                        two[lg][(code, (items[i], items[j]))] += 1
        for lg in one:
            home = {}
            per = C.defaultdict(dict)
            for (code, it), n in one[lg].items():
                per[it][code] = n
            for it, cc in per.items():
                top = sorted(cc.items(), key=lambda x: -x[1])
                if len(top) == 1 or top[0][1] > top[1][1]:
                    home[it] = top[0][0]
            for code in tot[lg]:
                ok = [(n, it) for (c, it), n in one[lg].items() if c == code and home.get(it) == code
                      and n >= 0.05 * tot[lg][code]]
                allc = sorted(((n, it) for (c, it), n in one[lg].items() if c == code), key=lambda x: (-x[0], x[1]))
                if allc:
                    common[(cat, code, lg)] = (allc[0][1], allc[0][0])
                if ok:
                    n, it = sorted(ok, key=lambda x: (-x[0], x[1]))[0]
                    out[(cat, code, lg)] = ("single", (it,), n, tot[lg][code])
                    continue
                if cat != "relation":
                    continue
                sets = C.defaultdict(C.Counter)
                for (c, k), n in two[lg].items():
                    sets[frozenset(k)][c] += n
                best = None
                for fs, cc in sets.items():
                    top = sorted(cc.items(), key=lambda x: -x[1])
                    if top[0][0] != code or (len(top) > 1 and top[0][1] == top[1][1]):
                        continue
                    if cc[code] >= 0.90 * tot[lg][code]:
                        orders = sorted(((n, k) for (c, k), n in two[lg].items() if c == code and frozenset(k) == fs),
                                        key=lambda x: (-x[0], x[1]))
                        cand = (-cc[code], orders[0][1])
                        best = cand if best is None or cand < best else best
                if best:
                    out[(cat, code, lg)] = ("pair", best[1], -best[0], tot[lg][code])
    return out, common


def _key_of(build, lg, item, cat):
    """The b1 lexeme key of an item (SPEC 4.10)."""
    b1 = os.path.join(os.path.dirname(os.path.normpath(build)), "b1")
    if (lg, "lex") not in _KEYS:
        lex = tsv(os.path.join(b1, lg, "lexemes.tsv"))
        used = C.Counter(k for m in table(os.path.join(b1, lg, "clauses.parquet"), ["marks"])
                         for k in json.loads(m["marks"]).get("connective", []))
        _KEYS[(lg, "lex")] = (lex, used)
    lex, used = _KEYS[(lg, "lex")]
    rows = [r for r in lex if nfc(r["lemma"]) == item]
    if not rows:
        return None, None
    if cat == "relation":
        rows.sort(key=lambda r: (-used[r["lexeme"]], -int(r["count"]), r["lexeme"]))
    else:
        rows.sort(key=lambda r: (r["class"] != "prep", -int(r["count"]), r["lexeme"]))
    return rows[0]["lexeme"], rows[0]["lemma"]


_KEYS = {}


def terms12(R, build):
    R.section("terms (SPEC 1.2, 4.10)")
    with open(os.path.join(SPEC, "terms.tsv"), encoding="utf-8") as fh:
        master = fh.read()
    with open(os.path.join(SPEC, "terms-notes.md"), encoding="utf-8") as fh:
        notes = fh.read()
    if V13:      # SPEC 1.3: the build's notes are the 1.2 notes with the 1.3 rows appended (stage 27 checks how)
        with open(os.path.join(build, "hbo", "terms-notes.md"), encoding="utf-8") as fh:
            notes = fh.read()
    for lang in ("hbo", "arc", "grc"):
        d = os.path.join(build, lang)
        R.check(f"{lang} terms.tsv: a byte copy of the master", open(os.path.join(d, "terms.tsv"), encoding="utf-8").read() == master)
        R.check(f"{lang} terms-notes.md: a byte copy of the master", os.path.exists(os.path.join(d, "terms-notes.md")) and
                open(os.path.join(d, "terms-notes.md"), encoding="utf-8").read() == notes)
    rows = tsv(os.path.join(SPEC, "terms.tsv"))
    R.check("terms.tsv: the ten columns of SPEC 4.10", master.split("\n", 1)[0].split("\t") == TERM_COLS, len(rows))
    R.check("terms.tsv: checked empty on every row (U4)", all(r["checked"] == "" for r in rows), f"{len(rows)} rows")
    bad = []
    for r in rows:
        for lg in ("hbo", "grc"):
            if V13 and not r[lg] and not r[f"from_{lg}"] and not r[f"source_{lg}"]:
                continue     # SPEC 1.3 4.10: a cell may be empty where the code occurs in no table of the language
            if not script(r[lg], lg == "grc"):
                bad.append(f"{r['code']} {lg} term")
            if r[f"from_{lg}"] not in ("text", "tradition", "coined"):
                bad.append(f"{r['code']} from_{lg}")
            s = r[f"source_{lg}"]
            okj = False
            if s.startswith("["):
                try:
                    okj = all(LEX_RE.match(x) for x in json.loads(s))
                except ValueError:
                    okj = False
            if not (s == "" or LEX_RE.match(s) or REF_RE.match(s) or okj):
                bad.append(f"{r['code']} source_{lg} {s!r}")
            if r[f"from_{lg}"] == "tradition" and not REF_RE.match(s):
                bad.append(f"{r['code']} tradition source is no reference code")
            if r[f"from_{lg}"] == "text" and not (LEX_RE.match(s) or okj):
                bad.append(f"{r['code']} text source is no lexeme key")
            if r[f"from_{lg}"] == "coined" and s and r["category"] != "sem_role":
                bad.append(f"{r['code']} coined source outside sem_role")
        if not re.fullmatch(r"[a-z0-9_]+", r["code"]) or not re.fullmatch(r"[a-z_]+", r["category"]) \
                or not re.fullmatch(r"[a-z0-9-]+", r["named_by"]):
            bad.append(f"{r['code']} code, category or named_by")
    R.check("terms.tsv: no English in any column (terms in the script; from, source, named_by, category, code are "
            "codes or keys)", not bad, f"{len(bad)} {bad[:5]}")
    dup = []
    for cat in {r["category"] for r in rows}:
        for lg in ("hbo", "grc"):
            cc = C.Counter(nfc(r[lg]) for r in rows if r["category"] == cat)
            dup += [f"{cat} {lg} {t}" for t, n in cc.items() if n > 1]
    R.check("terms.tsv: no two codes of one category share a term in a language", not dup, dup)
    tw = C.Counter(nfc(r[lg]) for r in rows for lg in ("hbo", "grc"))
    cats = C.defaultdict(set)
    for r in rows:
        for lg in ("hbo", "grc"):
            cats[nfc(r[lg])].add(r["category"])
    R.info("terms in two categories (allowed, A4)", sorted(t for t, c in cats.items() if len(c) > 1))
    # rule T recomputed
    rt, common = _rule_t(build)
    wrong = []
    by = {(r["category"], r["code"]): r for r in rows}
    for (cat, code, lg), (kind, items, n, tot) in sorted(rt.items()):
        r = by.get((cat, code))
        if r is None:
            wrong.append(f"{cat} {code} no row")
            continue
        keys = [_key_of(build, lg, it, cat) for it in items]
        if any(k[0] is None for k in keys):
            continue
        src = keys[0][0] if kind == "single" else json.dumps([k[0] for k in keys], ensure_ascii=False,
                                                            separators=(",", ":"))
        if cat == "relation":
            if (r[lg], r[f"from_{lg}"], r[f"source_{lg}"]) != (" ".join(k[1] for k in keys), "text", src):
                wrong.append(f"{lg} {cat} {code}: {r[lg]} {r['source_' + lg]} != {src}")
        elif r[f"source_{lg}"] != src or r[f"from_{lg}"] == "text":
            wrong.append(f"{lg} sem_role {code}: source {r['source_' + lg]} != {src}")
    for r in rows:
        for lg in ("hbo", "grc"):
            if r[f"from_{lg}"] == "text" and r["category"] == "relation" and (r["category"], r["code"], lg) not in rt:
                wrong.append(f"{lg} {r['code']}: text term without rule T's item")
            if r["category"] == "sem_role" and r[f"source_{lg}"] and ("sem_role", r["code"], lg) not in rt:
                wrong.append(f"{lg} {r['code']}: sem_role source without rule T's item")
    R.check("terms.tsv: every text term and every sem_role source is rule T's item, recomputed (pair rule included)",
            not wrong, f"{len(rt)} cells; {wrong[:5]}")
    R.info("rule T pairs", {f"{lg} {code}": " ".join(items) for (cat, code, lg), (k, items, n, t) in rt.items()
                            if k == "pair"})
    # no preposition word in a sem_role term
    badp = []
    for lang in ("hbo", "arc", "grc"):
        d = os.path.join(build, lang)
        tl = "grc" if lang == "grc" else "hbo"
        preps = {r["prep"] for r in table(os.path.join(d, "constituents.parquet"), ["prep"]) if r["prep"]}
        lem = {r["lexeme"]: nfc(r["lemma"]) for r in tsv(os.path.join(d, "lexemes.tsv"))}
        plem = {lem[k] for k in preps}
        tw_ = {p["t"] for p in table(os.path.join(d, "pieces.parquet"), ["t", "lexeme"]) if p["lexeme"] in preps}
        f = heb_norm if tl == "hbo" else (lambda s: nfc(re.sub(r"[^\w᾽’]", "", s)).lower())
        forms = {f(w["text"]) for w in table(os.path.join(d, "words.parquet"), ["t", "text"]) if w["t"] in tw_}
        for r in rows:
            if r["category"] != "sem_role":
                continue
            for x in r[tl].split():
                if nfc(x) in plem or f(x) in forms:
                    badp.append(f"{lang} {r['code']} {x}")
    R.check("terms.tsv: no sem_role term holds a word that is a preposition's lemma or the form of a word holding a "
            "preposition of constituents.prep (recomputed per language)", not badp, badp)
    # terms-notes.md
    refs = {r[f"source_{lg}"] for r in rows for lg in ("hbo", "grc") if r[f"source_{lg}"].startswith("ref:")}
    unres = [x for x in sorted(refs) if f"- `{x}` (" not in notes]
    R.check("terms-notes.md: every reference code resolved", not unres, f"{len(refs)} codes; {unres}")
    differ = [(cat, code, lg) for (cat, code, lg), (kind, items, n, t) in rt.items()
              if kind == "single" and (cat, code, lg) in common and common[(cat, code, lg)][0] != items[0]]
    miss = [x for x in differ if f"- {x[2]} `{x[0]}` `{x[1]}`: " not in notes]
    R.check("terms-notes.md: every cell where rule T's item is not the commonest marker is listed", not miss,
            f"{len(differ)} cells ({sum(1 for x in differ if x[2] == 'hbo')} hbo, "
            f"{sum(1 for x in differ if x[2] == 'grc')} grc); missing {miss}")
    R.info("terms-notes.md: cells where rule T's item is not the commonest marker",
           [f"{lg} {cat} {code}: {rt[(cat, code, lg)][1][0]} / {common[(cat, code, lg)][0]}"
            for cat, code, lg in sorted(differ)])
    # every meaning value that occurs has a term
    for lang in ("hbo", "arc", "grc"):
        d = os.path.join(build, lang)
        tl = "grc" if lang == "grc" else "hbo"
        have = {(r["category"], nfc(r[tl])) for r in rows}
        miss = set()
        for m in table(os.path.join(d, "clauses.parquet"), ["marks"]):
            for cat, v in json.loads(m["marks"]).items():
                if cat in ("relation", "time", "aspect", "line_kind") and (cat, nfc(v)) not in have:
                    miss.add((cat, v))
        for r in table(os.path.join(d, "constituents.parquet"), ["sem_role"]):
            if r["sem_role"] and ("sem_role", nfc(r["sem_role"])) not in have:
                miss.add(("sem_role", r["sem_role"]))
        for r in tsv(os.path.join(d, "participants.tsv")):
            if ("ent_type", nfc(r["type"])) not in have:
                miss.add(("ent_type", r["type"]))
        R.check(f"{lang} terms: every meaning value in the tables is a term of terms.tsv", not miss, sorted(miss)[:5])


# ---- the Septuagint links (called from validate_examples_s19.py) ----------------------------------------------------

def lxx12(R, build, T, O, links, named, pl, verse_words, vid, hv_of, pid_tn, s_of):
    R.section("links: the Septuagint under SPEC 1.2 D13a (two passes)")
    from validate_examples_s19 import plain, one_edit, FILLERS
    L = [r for lg in ("hbo", "arc") for r in T[lg]["L"]]
    bad_how = [r for r in L if not ((r["how"] in STRICT_HOW and r["basis"] == "linked") or
                                    (r["how"] in MODEL_HOW and r["basis"] == "model"))]
    R.check("lxx links: basis linked for sure, order, neighbours, form_near, verse_form; model for number, lemma, "
            "verse_lemma, verse_number (no other how)", not bad_how, f"{len(bad_how)} wrong of {len(L):,}")
    strict = C.defaultdict(set)
    for r in L:
        if r["basis"] == "linked":
            strict[(r["t"], r["n"])].add(r["s"])
    on_strict = [r for r in L if r["basis"] == "model" and (r["t"], r["n"]) in strict]
    R.check("lxx links: no Septuagint model link stands on a piece that has a strict Septuagint link", not on_strict,
            len(on_strict))
    # the bridge's rows
    br = []
    for r in table(BRIDGE):
        b, cv, i = r["lxx_key"].split(" ")[1:]
        c, v = map(int, cv.split(":"))
        br.append(pid_tn["o" + r["hebrew_mid"]] + (s_of[(b, c, v, int(i))], r["how"]))
    rowset = C.Counter((r["t"], r["n"], r["s"], r["how"]) for r in L if r["how"] in {"sure", "order", "neighbours", "number"})
    as_row = agree = displaced = 0
    want_agree = set()
    rest = []
    for t, n, s, how in br:
        if rowset[(t, n, s, how)] > 0:
            as_row += 1
        elif how == "number" and s in strict.get((t, n), ()):
            agree += 1
            want_agree.add((t, n, s))
        elif how == "number" and (t, n) in strict:
            displaced += 1
        else:
            rest.append((t, n, s, how))
    R.check("lxx links: each of the bridge's rows is a links row with its how, or agrees with a strict row of its piece, "
            "or is displaced; the three add up to 345,461", not rest and as_row + agree + displaced == len(br) == 345461
            and sum(rowset.values()) == as_row,
            f"rows {as_row:,} + agreeing {agree:,} + displaced {displaced:,} = {as_row + agree + displaced:,}; "
            f"unaccounted {len(rest)}")
    numset = {(t, n, s) for t, n, s, how in br if how == "number"}
    bad_am = [r for r in L if r["basis"] == "linked" and r["agree_model"] != (1 if (r["t"], r["n"], r["s"]) in numset else 0)]
    R.check("lxx links: agree_model 1 on a strict row exactly where a bridge number link of the piece names the same "
            "word, else 0 (recomputed)", not bad_am, f"{len(bad_am)} differ; 1 on {len(want_agree):,} rows")
    # the strict pass, form_near recomputed (own verses from the strict bridge links only)
    pieces = sorted((p["t"], p["n"], p["pid"]) for lg in ("hbo", "arc") for p in T[lg]["P"])
    bstrict = C.defaultdict(set)
    own = C.defaultdict(set)
    held = set()
    for t, n, s, how in br:
        if how in {"sure", "order", "neighbours"}:
            bstrict[(t, n)].add(s)
            own[hv_of[t]].add(vid[s])
            held.add(s)
    exp_fn = {}
    for t, n, pid in pieces:
        if (t, n) in bstrict:
            continue
        g = named.get(pid)
        if not g or g in FILLERS:
            continue
        f = plain(g)
        if len(f) < 5:
            continue
        free = [s for k in sorted(own[hv_of[t]]) for s in verse_words[k] if s not in held and
                (one_edit(pl[s], f) or (V18 and pl[s] == f))]     # SPEC 1.8 D13a (M4): an equal form or one edit
        if len(free) == 1:
            exp_fn[(t, n)] = free[0]
            held.add(free[0])
    got_fn = {(r["t"], r["n"]): r["s"] for r in L if r["how"] == "form_near"}
    R.check("lxx form_near (strict pass, no number guard): the links equal the rule recomputed over the strict bridge "
            "links", got_fn == exp_fn, f"{len(got_fn):,} links, recomputed {len(exp_fn):,}, "
            f"differ {len(set(got_fn.items()) ^ set(exp_fn.items()))}")
    vf = [r for r in L if r["how"] == "verse_form"]
    pid_of = {(t, n): pid for t, n, pid in pieces}
    held_by = C.Counter(r["s"] for r in L if r["basis"] == "linked")
    bad_vf = [r for r in vf if pl[r["s"]] != plain(named.get(pid_of[(r["t"], r["n"])])) or held_by[r["s"]] > 1]
    R.check("lxx verse_form: every link's word has the named form and no other strict link holds it", not bad_vf,
            f"{len(vf):,} links; {len(bad_vf)} wrong")
    bad_fn = [r for r in L if r["how"] == "form_near" and held_by[r["s"]] > 1]
    R.check("lxx form_near: no other strict link holds its word", not bad_fn, len(bad_fn))
    mrule = [r for r in L if r["how"] in {"lemma", "verse_lemma", "verse_number"}]
    allheld = C.Counter(r["s"] for r in L)
    bad_m = [r for r in mrule if allheld[r["s"]] > 1]
    R.check("lxx lemma, verse_lemma, verse_number: each takes a word no other link (strict or model) holds", not bad_m,
            f"{len(mrule):,} links; {len(bad_m)} wrong")
    shared = sum(1 for r in L if r["how"] == "number" and r["basis"] == "model" and held_by[r["s"]] > 0)
    R.info("lxx bridge number rows on a Septuagint word a strict link of another piece holds (counted, SPEC D13a)", shared)
    R.info("lxx links by how and basis (1.2)", dict(sorted(C.Counter(f"{r['how']} {r['basis']}" for r in L).items())))


# ---- participants and the unchanged columns -------------------------------------------------------------------------

def _cmp(R, name, a, b, key, cols, info_only=False):
    ia = {key(r): r for r in a}
    ib = {key(r): r for r in b}
    keys_ok = set(ia) == set(ib)
    d = C.Counter()
    for k in set(ia) & set(ib):
        for c in cols:
            if ia[k].get(c) != ib[k].get(c):
                d[c] += 1
    msg = f"{len(ia):,} rows; keys only in d1 {len(set(ia) - set(ib))}, only in c1 {len(set(ib) - set(ia))}; " \
          f"differ {dict(d)}"
    if info_only:
        R.info(name, msg)
    else:
        R.check(name, keys_ok and not d, msg)
    return d


def stage23(R, build):
    c1 = os.path.join(os.path.dirname(os.path.normpath(build)), "c1")
    R.section("participants (SPEC 1.2)")
    for lang in ("hbo", "arc", "grc"):
        d = os.path.join(build, lang)
        P = table(os.path.join(d, "pieces.parquet"), ["who_basis"])
        prow = tsv(os.path.join(d, "participants.tsv"))
        R.check(f"{lang} participants: no name is הַ (D7n)", not [r for r in prow if nfc(r["name"]) == nfc("הַ")])
        R.check(f"{lang} pieces: no who_basis is model; participants: every words_model is 0 (section 9)",
                not [p for p in P if p["who_basis"] == "model"] and all(r["words_model"] in ("0", "") for r in prow),
                f"{len(prow):,} participants")
        cn = {r["ent"]: r for r in tsv(os.path.join(c1, lang, "participants.tsv"))}
        renamed = [f"{e}: {cn[e]['name']} -> {r['name']} ({r['name_basis']})" for e, r in
                   ((r["ent"], r) for r in prow) if e in cn and nfc(cn[e]["name"]) == nfc("הַ")]
        if lang != "grc":
            R.info(f"{lang} participants c1 named הַ, now", renamed)
    R.section("unchanged against c1 (SPEC 13)")
    for lang in ("hbo", "arc", "grc"):
        d, e = os.path.join(build, lang), os.path.join(c1, lang)
        rd = lambda name, cols=None: table(os.path.join(d, name), cols)  # noqa: E731
        re_ = lambda name, cols=None: table(os.path.join(e, name), cols)  # noqa: E731
        W, W1 = rd("words.parquet"), re_("words.parquet")
        cols = [c for c in W[0] if c != "rel_shared" or lang == "grc"]
        _cmp(R, f"{lang} unchanged: words, every column{' but rel_shared' if lang != 'grc' else ''}", W, W1,
             lambda r: r["t"], cols)
        if lang != "grc":
            ch = C.Counter((b["rel_shared"], a["rel_shared"], a["rel"]) for a, b in zip(W, W1)
                           if a["t"] == b["t"] and a["rel_shared"] != b["rel_shared"])
            R.info(f"{lang} changed: words.rel_shared (c1 -> d1, label)", {" ".join(k): v for k, v in sorted(ch.items())})
        P, P1 = rd("pieces.parquet"), re_("pieces.parquet")
        _cmp(R, f"{lang} unchanged: pieces, every column", P, P1, lambda r: (r["t"], r["n"]), list(P[0]))
        K, K1 = rd("clauses.parquet"), re_("clauses.parquet")
        changed = {"marks"} | ({"addressee", "quote_model", "speaker_model", "addressee_model"} if lang == "grc" else set())
        _cmp(R, f"{lang} unchanged: clauses, every column but {', '.join(sorted(changed))}", K, K1,
             lambda r: r["clause"], [c for c in K[0] if c not in changed])
        tl = "grc" if lang == "grc" else "hbo"
        code_of = {(r["category"], nfc(r[tl])): r["code"] for r in tsv(os.path.join(d, "terms.tsv"))}
        code1 = {(r["category"], nfc(r[tl])): r["code"] for r in tsv(os.path.join(e, "terms.tsv"))}
        km, kc = C.Counter(), C.Counter()
        i1 = {r["clause"]: r for r in K1}
        for r in K:
            a, b = json.loads(r["marks"]), json.loads(i1[r["clause"]]["marks"])
            for cat in set(a) | set(b):
                if cat in ("connective", "negator"):
                    kc[cat] += a.get(cat) != b.get(cat)
                elif cat == "relation":
                    km[cat] += code_of.get((cat, nfc(a.get(cat, "")))) != code1.get((cat, nfc(b.get(cat, ""))))
                else:
                    km[cat] += a.get(cat) != b.get(cat)
        R.check(f"{lang} unchanged: clauses.marks, every key but connective and negator (relation by code)",
                sum(km.values()) == 0, dict(km))
        R.info(f"{lang} changed: clauses.marks connective / negator (clauses whose value differs from c1)", dict(kc))
        if lang == "grc":
            ad = sum(1 for r in K if r["addressee"] != i1[r["clause"]]["addressee"])
            R.info("grc changed: clauses.addressee (clauses whose value differs from c1)", ad)
        N, N1 = rd("constituents.parquet"), re_("constituents.parquet")
        _cmp(R, f"{lang} unchanged: constituents, every column but sem_role, sem_role_basis", N, N1,
             lambda r: (r["clause"], r["ord"]), [c for c in N[0] if c not in ("sem_role", "sem_role_basis")])
        sc = {"sem_role", "sem_role_basis"}
        cs = {r["category"]: 0 for r in []}
        n1 = {(r["clause"], r["ord"]): r for r in N1}
        bad = C.Counter()
        for r in N:
            o = n1[(r["clause"], r["ord"])]
            if o["sem_role"]:
                bad["sem_role code"] += code_of.get(("sem_role", nfc(r["sem_role"]))) != code1.get(("sem_role", nfc(o["sem_role"])))
                bad["sem_role_basis"] += r["sem_role_basis"] != o["sem_role_basis"]
            elif r["sem_role"]:
                bad["newly filled"] += 1
                cs[r["sem_role_basis"]] = cs.get(r["sem_role_basis"], 0) + 1
        R.check(f"{lang} unchanged: constituents.sem_role by code, and sem_role_basis, on every row c1 fills",
                bad["sem_role code"] == 0 and bad["sem_role_basis"] == 0, dict(bad))
        R.info(f"{lang} changed: constituents newly filled (c1 empty), by sem_role_basis", cs)
        R.check(f"{lang} unchanged: lexemes.tsv", open(os.path.join(d, "lexemes.tsv"), "rb").read() ==
                open(os.path.join(e, "lexemes.tsv"), "rb").read())
        pr, pr1 = tsv(os.path.join(d, "participants.tsv")), tsv(os.path.join(e, "participants.tsv"))
        ha = {r["ent"] for r in pr1 if nfc(r["name"]) == nfc("הַ")}
        i_ = {r["ent"]: r for r in pr}
        dd = C.Counter()
        for r in pr1:
            x = i_.get(r["ent"])
            if x is None:
                dd["c1 row missing"] += 1
                continue
            for c in r:
                if c in ("name", "name_basis") and r["ent"] in ha:
                    continue
                if c == "ent_basis" and lang == "grc":
                    continue
                dd[c] += x[c] != r[c]
        dd = {k: v for k, v in dd.items() if v}
        new = sorted(set(i_) - {r["ent"] for r in pr1})
        R.check(f"{lang} unchanged: participants.tsv, every row of c1 but name, name_basis of those named הַ"
                + (" (and ent_basis in grc)" if lang == "grc" else ""), not dd and (lang == "grc" or not new),
                f"{dd}; rows added {len(new)}")
        for name in ("forms", "paradigms", "markers", "constructions", "orders", "agreement", "frames", "pairs",
                     "exceptions"):
            a, b = rd(f"{name}.parquet"), re_(f"{name}.parquet")
            R.check(f"{lang} unchanged: {name}.parquet, every row and column", a == b, f"{len(a):,} rows")
        cl, cl1 = rd("clause_links.parquet"), re_("clause_links.parquet")
        R.info(f"{lang} changed: clause_links rows d1 / c1", f"{len(cl):,} / {len(cl1):,}")
        F, F1 = rd("facts.parquet"), re_("facts.parquet")
        keep = lambda r: not (lang != "grc" and r["relation"] == "rendered_by" and str(r["object"]).startswith("lxx:"))  # noqa: E731
        fa, fb = sorted(map(lambda r: tuple(map(str, r.values())), filter(keep, F))), \
            sorted(map(lambda r: tuple(map(str, r.values())), filter(keep, F1)))
        R.check(f"{lang} unchanged: facts, every row but the Septuagint rendered_by rows", fa == fb, f"{len(fa):,} rows")
        Ld, L1 = rd("links.parquet"), re_("links.parquet")
        A, A1 = rd("link_account.parquet"), re_("link_account.parquet")
        if lang == "grc":
            R.check("grc unchanged: links.parquet, every row and column", Ld == L1, f"{len(Ld):,}")
            R.check("grc unchanged: link_account.parquet, every row and column", A == A1, f"{len(A):,}")
        else:
            sel = lambda Ls: sorted((r["t"], r["n"], r["other"], r["s"], r["how"], r["agree"], r["basis"])  # noqa: E731
                                    for r in Ls if r["how"] in ("sure", "order", "neighbours"))
            R.check(f"{lang} unchanged: links t, n, other, s, how, agree, basis of every bridge strict row",
                    sel(Ld) == sel(L1), f"{len(sel(Ld)):,}")
            hb = lambda Ls: dict(sorted(C.Counter(f"{r['how']} {r['basis']}" for r in Ls).items()))  # noqa: E731
            R.info(f"{lang} changed: links by how and basis, c1 -> d1", f"{hb(L1)} -> {hb(Ld)}")
            st = C.Counter((a["state"], b["state"]) for a, b in zip(A1, A) if a["state"] != b["state"])
            R.info(f"{lang} changed: link_account.state c1 -> d1", {f"{a} -> {b}": v for (a, b), v in sorted(st.items())})
            sm = sum(1 for a, b in zip(A1, A) if a["state_model"] != b["state_model"])
            R.info(f"{lang} changed: link_account.state_model rows", sm)
        se, se1 = tsv(os.path.join(d, "source_errors.tsv")), tsv(os.path.join(e, "source_errors.tsv"))
        R.check(f"{lang} unchanged: source_errors.tsv SE1, SE2 rows",
                [r for r in se if r["rule"] in ("SE1", "SE2")] == se1, f"{len(se1)} rows")
        R.info(f"{lang} source_errors.tsv rows by rule", dict(C.Counter(r["rule"] for r in se)))
        pf, pf1 = tsv(os.path.join(d, "profile.tsv")), tsv(os.path.join(e, "profile.tsv"))
        R.info(f"{lang} profile.tsv rows that differ from c1 (expected none)",
               [f"{a.get('id', '')}" for a, b in zip(pf, pf1) if a != b] + ([] if len(pf) == len(pf1) else ["row count"]))
    for ed in ("lxx", "heb_scg", "heb_mod"):
        a, b = table(os.path.join(build, "other", ed, "words.parquet")), table(os.path.join(c1, "other", ed, "words.parquet"))
        R.check(f"other/{ed}: unchanged, every column", a == b, f"{len(a):,}")
    # terms.tsv cells 1.2 does not name
    t, t1 = tsv(os.path.join(SPEC, "terms.tsv")), tsv(os.path.join(c1, "hbo", "terms.tsv"))
    p7 = {("hbo", c) for c in ("addressee", "accompaniment", "agent", "content", "goal", "location", "opposition",
                               "reason_participant", "recipient", "source", "standard", "time", "viewpoint")} | \
         {("grc", c) for c in ("accompaniment", "addressee", "agent", "beneficiary", "content", "distribution", "goal",
                               "location", "reason_participant", "separation", "source", "source_event", "standard",
                               "time", "viewpoint")}
    i1 = {(r["category"], r["code"]): r for r in t1}
    bad, named = [], 0
    for r in t:
        o = i1.get((r["category"], r["code"]))
        if o is None:
            bad.append(f"{r['code']} new row")
            continue
        if (r["named_by"], r["checked"]) != (o["named_by"], o["checked"]):
            bad.append(f"{r['code']} named_by/checked")
        for lg in ("hbo", "grc"):
            if (r["category"] == "sem_role" and (lg, r["code"]) in p7) or (r["category"], r["code"], lg) in \
                    {("relation", "adversative", "hbo"), ("aspect", "imperfective", "grc")} or o[f"from_{lg}"] == "tradition":
                named += 1
                continue
            cols = (lg, f"from_{lg}") if r["category"] == "sem_role" and o[f"from_{lg}"] == "text" else \
                (lg, f"from_{lg}", f"source_{lg}")
            if r["category"] == "sem_role":
                cols = (lg, f"from_{lg}")
            if any(r[c] != o[c] for c in cols):
                bad.append(f"{lg} {r['category']} {r['code']}")
    R.check("terms.tsv: unchanged against c1 in every cell 1.2 does not name (term, from, source; sem_role: term, from; "
            "named_by, checked)", not bad and len(t) == len(t1), f"{len(t)} rows; {named} cells named by 1.2; {bad[:8]}")
