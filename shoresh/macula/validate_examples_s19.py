"""Stage 19 checks (SPEC 1.1, section 10: links; strict view (links, facts); unchanged; model attribution of M5-M7).
Called by validate_examples.py --build c1 --upto 19. Imports none of the examples_* builders and reads nothing from
the build's cache/. Its own readings:
- MACULA Hebrew lowfat `greek` per piece (the named Septuagint word), parsed here;
- GLAUx's store (plain forms, Strong's numbers) for the `form_near` guard: a `form_near` link is `model` exactly
  when more than one free word of the verse's own Septuagint verses is one edit from the named form (so the number
  guard chose); "free" = not linked by the bridge, by a `lemma` link, or by a `form_near` link of an earlier piece;
- the bridge's `lxx.parquet`, hebrew-nt-bridge v0.1's links, hebrew-nt-part-links 2026-11-19, hebrew-nt-analysis v0.2;
- `b1`'s links, accounts and other words (stage 08, validated there against the sources).
"""
import collections as C
import glob
import json
import multiprocessing as mp
import os
import re
import sqlite3
import tomllib
import unicodedata as U
import xml.etree.ElementTree as ET

import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
XID = "{http://www.w3.org/XML/1998/namespace}id"
HEB_LOWFAT = os.path.join(HERE, ".lowfat-src/WLC/lowfat")
BRIDGE = os.path.join(ROOT, "internal-docs/hebrew-greek-cf-release/v0.2/bridges/lxx.parquet")
GLAUX = os.path.join(ROOT, "shoresh/lxx/data/lxx-glaux.db")
NTB = os.path.join(ROOT, "internal-docs/hebrew-nt-bridge-release/v0.1")
PARTS = os.path.join(HERE, "data/hebrew-nt-part-links/2026-11-19")
ANA = os.path.join(ROOT, "internal-docs/hebrew-nt-analysis-release/v0.2")
EDS = ("heb_scg", "heb_mod")
FILLERS = {"’’", "^^^"}
MODEL_HOW = {"number", "lemma", "verse_lemma", "verse_number"}
REVIEW = {"kept", "inside", "part", "edited", "edited-wide"}
NT_CONTENT = {"noun", "verb", "adj"}
LINK_COLS = ["t", "n", "other", "s", "how", "agree", "basis", "agree_model"]
ACC_COLS = ["t", "n", "other", "state", "reason", "state_model"]
OTHER_COLS = ["s", "id", "book", "chapter", "verse", "w", "text", "lemma", "class"]
KIN = {"father", "mother", "offspring", "sibling", "partner", "tribe", "group_origin"}
HEB_DROP = set(range(0x0591, 0x05B0)) | {0x05BD, 0x05C4, 0x05C5}


V12 = False          # set by validate_examples.py for a d build (SPEC 1.2): the Septuagint checks of 1.2 are in
                     # validate_examples_s23.py; the 1.1 ones that compare with b1 or the number guard are left out

def c0(v):
    return re.sub(r"[^a-z0-9]+", "_", v.lower()).strip("_")


def plain(s):
    s = U.normalize("NFD", (s or "").lower())
    return "".join(ch for ch in s if not U.combining(ch)).replace("ς", "σ").strip(".,;·:!?'’\"")


def one_edit(a, b):
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    return any(b[:i] + b[i + 1:] == a for i in range(len(b)))


def norm_heb(t):
    return U.normalize("NFC", "".join(ch for ch in t if ord(ch) not in HEB_DROP))


def _greek_file(path):
    return [(w.get(XID), w.get("greek")) for w in ET.parse(path).getroot().iter("w")]


def rows(path, cols=None):
    return pq.read_table(path, columns=cols).to_pylist()


def stage19(R, build, src, STASH):
    b1 = os.path.join(os.path.dirname(os.path.normpath(build)), "b1")
    R.section("links (SPEC 4.9, D13, D13a, D13m, D14): other texts")
    # --- other texts, once per build ---
    R.check("other/: one folder per text at build level (lxx, heb_scg, heb_mod), none inside a language folder",
            sorted(os.listdir(os.path.join(build, "other"))) == ["heb_mod", "heb_scg", "lxx"]
            and not any(os.path.isdir(os.path.join(build, lg, "other")) for lg in ("hbo", "arc", "grc")))
    O = {}
    O["lxx"] = rows(os.path.join(build, "other", "lxx", "words.parquet"))
    R.check("other/lxx: columns as SPEC 4.9", list(O["lxx"][0]) == OTHER_COLS)
    R.check("other/lxx: every value equals b1's (row by row)",
            O["lxx"] == rows(os.path.join(b1, "hbo", "other", "lxx", "words.parquet")), f"{len(O['lxx']):,} rows")
    for ed in EDS:
        O[ed] = rows(os.path.join(build, "other", ed, "words.parquet"))
        R.check(f"other/{ed}: columns as SPEC 4.9 (with analysis, analysis_basis)",
                list(O[ed][0]) == OTHER_COLS + ["analysis", "analysis_basis"])
        old = rows(os.path.join(b1, "grc", "other", ed, "words.parquet"))
        R.check(f"other/{ed}: the columns of b1 equal b1's (row by row)",
                [{k: r[k] for k in OTHER_COLS} for r in O[ed]] == old, f"{len(old):,} rows")
        by = C.defaultdict(list)
        for r in rows(os.path.join(ANA, ed, "words.parquet"), ["book", "chapter", "verse", "i", "part", "token", "text",
                                                               "class", "lemma", "source"]):
            by[(r["book"], r["chapter"], r["verse"], r["i"])].append(r)
        bad, none_tok, basis = 0, 0, C.Counter()
        for r in O[ed]:
            ps = sorted(by.get((r["book"], r["chapter"], r["verse"], r["w"]), []), key=lambda x: x["part"])
            if not ps or not any("א" <= ch <= "ת" for ch in ps[0]["token"]):
                none_tok += bool(ps)
                want = (None, None)
            else:
                an = json.dumps([{"class": "" if x["class"] == "-" else c0(x["class"]), "lemma": x["lemma"],
                                  "text": x["text"]} for x in ps], sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False)
                want = (an, "derived" if {x["source"] for x in ps} == {"macula"} else "model")
            bad += (r["analysis"], r["analysis_basis"]) != want
            basis[r["analysis_basis"]] += 1
        R.check(f"other/{ed}: analysis and analysis_basis equal hebrew-nt-analysis v0.2 recomputed (D14)", bad == 0,
                f"{bad} differ; by basis {dict(sorted((str(k), v) for k, v in basis.items()))}; "
                f"no analysis (token without a Hebrew letter) {none_tok}")
        R.check(f"other/{ed}: lemma and class empty", all(r["lemma"] is None and r["class"] is None for r in O[ed]))
    s_exists = {k: {r["s"] for r in v} for k, v in O.items()}

    # --- the Septuagint ---
    R.section("links: the Septuagint (hbo, arc)")
    T = {}
    for lg in ("hbo", "arc"):
        d = os.path.join(build, lg)
        T[lg] = {"W": rows(os.path.join(d, "words.parquet"), ["t", "book", "chapter", "verse"]),
                 "P": rows(os.path.join(d, "pieces.parquet"), ["t", "n", "pid", "class", "lexeme"]),
                 "L": rows(os.path.join(d, "links.parquet")), "A": rows(os.path.join(d, "link_account.parquet")),
                 "L1": rows(os.path.join(b1, lg, "links.parquet")), "A1": rows(os.path.join(b1, lg, "link_account.parquet"))}
        R.check(f"{lg} links: columns as SPEC 4.9", list(T[lg]["L"][0]) == LINK_COLS)
        R.check(f"{lg} link_account: columns as SPEC 4.9", list(T[lg]["A"][0]) == ACC_COLS)
        key = lambda r: (r["t"], r["n"], r["other"], r["s"], r["how"])
        if not V12:
            R.check(f"{lg} links: (t, n, other, s, how) equal b1's rows, the strict links of stage 08 and its model-read rules",
                    sorted(map(key, T[lg]["L"])) == sorted(map(key, T[lg]["L1"])), f"{len(T[lg]['L']):,} rows")
        R.check(f"{lg} links: every s is a word of other/lxx", all(r["s"] in s_exists["lxx"] for r in T[lg]["L"]))
        if V12:
            R.check(f"{lg} links: agree_model 0 or 1 on linked rows, null on model rows (SPEC 1.2 D13a)",
                    all((r["agree_model"] in (0, 1)) if r["basis"] == "linked" else r["agree_model"] is None
                        for r in T[lg]["L"]))
        else:
            R.check(f"{lg} links: agree_model null (no model alignment of the Septuagint)",
                    all(r["agree_model"] is None for r in T[lg]["L"]))
        R.check(f"{lg} links: agree 1 on linked rows, 0 on model rows",
                all(r["agree"] == (1 if r["basis"] == "linked" else 0) for r in T[lg]["L"]))
    # the bridge's rows
    s_of = {(r["book"], r["chapter"], r["verse"], r["w"]): r["s"] for r in O["lxx"]}
    pid_tn = {p["pid"]: (p["t"], p["n"]) for lg in ("hbo", "arc") for p in T[lg]["P"]}
    br = set()
    for r in rows(BRIDGE):
        b, cv, i = r["lxx_key"].split(" ")[1:]
        c, v = map(int, cv.split(":"))
        br.add(pid_tn["o" + r["hebrew_mid"]] + (s_of[(b, c, v, int(i))], r["how"]))
    got = {(r["t"], r["n"], r["s"], r["how"]) for lg in ("hbo", "arc") for r in T[lg]["L"]
           if r["how"] in {"sure", "order", "neighbours", "number"}}
    if not V12:
        R.check("lxx links: the rows whose how comes from the bridge equal the bridge's rows", got == br and len(br) == 345461,
                f"{len(br):,}")
    # form_near: did the number guard choose? (independent recomputation of the free words)
    con = sqlite3.connect(f"file:{GLAUX}?mode=ro", uri=True)
    gid_plain = {str(g): plain(sf) for sf, g in con.execute("select surface, glaux_id from lxx_words where canonical = 1")}
    pl = {r["s"]: gid_plain[r["id"]] for r in O["lxx"]}
    vid, verse_words = {}, C.defaultdict(list)
    for r in O["lxx"]:
        k = (r["book"], r["chapter"], r["verse"])
        vid[r["s"]] = k
        verse_words[k].append(r["s"])
    with mp.get_context("fork").Pool(7) as pool:
        named = dict(x for f in pool.map(_greek_file, sorted(glob.glob(os.path.join(HEB_LOWFAT, "*-lowfat.xml"))),
                                         chunksize=8) for x in f)
    pieces = sorted((p["t"], p["n"], p["pid"], p["class"], lg) for lg in ("hbo", "arc") for p in T[lg]["P"])
    hv_of = {}
    for lg in ("hbo", "arc"):
        for w in T[lg]["W"]:
            hv_of[w["t"]] = (w["book"], w["chapter"], w["verse"])
    links = {}
    for lg in ("hbo", "arc"):
        for r in T[lg]["L"]:
            links.setdefault((r["t"], r["n"]), []).append(r)
    own = C.defaultdict(set)
    for (t, n), ls in links.items():
        for r in ls:
            if r["how"] in {"sure", "order", "neighbours", "number"}:
                own[hv_of[t]].add(vid[r["s"]])
    taken = {r["s"] for ls in links.values() for r in ls if r["how"] in {"sure", "order", "neighbours", "number", "lemma"}}
    decisive, fn = set(), 0
    for t, n, pid, cls, lg in pieces:
        for r in links.get((t, n), ()):
            if r["how"] != "form_near":
                continue
            fn += 1
            f = plain(named.get(pid))
            free = [s for k in sorted(own[hv_of[t]]) for s in verse_words[k] if s not in taken and one_edit(pl[s], f)]
            if r["s"] not in free:
                fn = -10**9
            if len(free) > 1:
                decisive.add((t, n))
            taken.add(r["s"])
    if not V12:
        R.check("lxx form_near: every link's word is free and one edit from the named form (recomputed)", fn >= 0,
                f"{max(fn, 0):,} links; the number guard chose in {len(decisive)}")
    bad = 0
    for (t, n), ls in links.items():
        for r in ls:
            want = "model" if r["how"] in MODEL_HOW or (r["how"] == "form_near" and (t, n) in decisive) else "linked"
            bad += r["basis"] != want
    if not V12:
        R.check("lxx links: basis model exactly where the rule reads a GLAUx lemma or its number (bridge number, lemma, "
                "verse_lemma, verse_number; form_near where the guard chose)", bad == 0, f"{bad} wrong")
    else:
        import validate_examples_s23
        validate_examples_s23.lxx12(R, build, T, O, links, named, pl, verse_words, vid, hv_of, pid_tn, s_of)
    R.info("lxx links by how and basis", dict(sorted(C.Counter(f"{r['how']} {r['basis']}" for ls in links.values()
                                                               for r in ls).items())))
    # D13 over strict links
    strict = {k for k, ls in links.items() if any(r["basis"] == "linked" for r in ls)}
    modelonly = {k for k in links if k not in strict}
    ca, cl = C.Counter(), C.Counter()
    for t, n, pid, cls, lg in pieces:
        ca[cls] += 1
        cl[cls] += (t, n) in strict
    naw = {c for c in ca if cl[c] / ca[c] < 0.05}
    R.info("lxx never_a_word classes over strict links", sorted(naw))
    for lg in ("hbo", "arc"):
        A = {(r["t"], r["n"]): r for r in T[lg]["A"]}
        P = [p for p in pieces if p[4] == lg]
        R.check(f"{lg} link_account: one row per piece, other lxx", len(A) == len(T[lg]["A"]) == len(P)
                and all(r["other"] == "lxx" for r in T[lg]["A"]))
        bad = 0
        for t, n, pid, cls, _ in P:
            g = named.get(pid)
            g = g if g and g not in FILLERS else None
            if (t, n) in strict:
                w = ("linked", "")
            elif cls in naw:
                w = ("never_a_word", cls)
            elif g:
                w = ("unplaced", g)
            else:
                w = ("no_counterpart", "")
            sm = "linked" if (t, n) in modelonly else None
            bad += (A[(t, n)]["state"], A[(t, n)]["reason"], A[(t, n)]["state_model"]) != w + (sm,)
        R.check(f"{lg} link_account: state and reason by D13 over strict links, state_model as SPEC 4.9 (recomputed)",
                bad == 0, f"{bad} differ; " + str(dict(sorted(C.Counter(r["state"] for r in T[lg]["A"]).items()))))
        A1 = {(r["t"], r["n"]): r for r in T[lg]["A1"]}
        ch = [k for k in A if (A[k]["state"], A[k]["reason"]) != (A1[k]["state"], A1[k]["reason"])]
        if not V12:
            R.check(f"{lg} unchanged: account rows differ from b1 only on pieces whose only link became model",
                    set(ch) == {k for k in modelonly if k in A}, f"{len(ch):,} changed")
    # --- the Hebrew New Testaments ---
    R.section("links: the Hebrew New Testaments (grc)")
    d = os.path.join(build, "grc")
    L = rows(os.path.join(d, "links.parquet"))
    A = rows(os.path.join(d, "link_account.parquet"))
    L1 = rows(os.path.join(b1, "grc", "links.parquet"))
    A1 = rows(os.path.join(b1, "grc", "link_account.parquet"))
    R.check("grc links: columns as SPEC 4.9", list(L[0]) == LINK_COLS)
    R.check("grc link_account: columns as SPEC 4.9", list(A[0]) == ACC_COLS)
    k6 = lambda r: (r["t"], r["n"], r["other"], r["s"], r["how"], r["agree"])
    R.check("grc unchanged: the linked rows equal b1's rows (t, n, other, s, how, agree)",
            sorted(k6(r) for r in L if r["basis"] == "linked") == sorted(map(k6, L1)), f"{len(L1):,}")
    R.check("grc unchanged: link_account t, n, other, state, reason equal b1's",
            [(r["t"], r["n"], r["other"], r["state"], r["reason"]) for r in A] == [tuple(r.values()) for r in A1])
    R.check("grc links: every s is a word of other/<text>", all(r["s"] in s_exists[r["other"]] for r in L))
    W = rows(os.path.join(d, "words.parquet"), ["t", "id"])
    t_of = {w["id"]: w["t"] for w in W}
    for ed in EDS:
        so = {(r["book"], r["chapter"], r["verse"], r["w"]): r["s"] for r in O[ed]}
        rev = C.defaultdict(set)
        for r in rows(os.path.join(NTB, "links", f"{ed}.parquet"), ["greek_id", "book", "chapter", "verse", "i", "link"]):
            if r["link"] in REVIEW:
                k = (t_of.get(r["greek_id"]), so.get((r["book"], r["chapter"], r["verse"], r["i"])))
                if None not in k:
                    rev[k].add(c0(r["link"]))
        part = set()
        for r in rows(os.path.join(PARTS, ed, "part_links.parquet"), ["book", "chapter", "verse", "i", "greek_id", "runs"]):
            if r["runs"] >= 3:
                k = (t_of.get(r["greek_id"]), so.get((r["book"], r["chapter"], r["verse"], r["i"])))
                if None not in k:
                    part.add(k)
        S = {(r["t"], r["s"]) for r in L if r["other"] == ed and r["basis"] == "linked"}
        want_m = sorted((t, 1, ed, s, "review_" + min(c), 0, "model", int(True) + int((t, s) in part))
                        for (t, s), c in rev.items() if (t, s) not in S)
        got_m = sorted(tuple(r.values()) for r in L if r["other"] == ed and r["basis"] == "model")
        R.check(f"{ed}: model rows equal the reviewed links of hebrew-nt-bridge v0.1 that no strict link has (D13m), "
                f"with how, agree 0, agree_model", got_m == want_m, f"{len(got_m):,}")
        bad = sum(1 for r in L if r["other"] == ed and r["basis"] == "linked"
                  and r["agree_model"] != int((r["t"], r["s"]) in rev) + int((r["t"], r["s"]) in part))
        R.check(f"{ed}: agree_model of the strict rows recomputed (reviewed + part links runs >= 3)", bad == 0,
                f"{bad} differ")
        conf = sum(1 for k in S if k in rev)
        rt = {t for t, _ in rev}
        R.info(f"{ed} strict links confirmed / contradicted / no opinion by a reviewed link; model rows added",
               f"{conf:,} / {sum(1 for k in S if k not in rev and k[0] in rt):,} / "
               f"{sum(1 for k in S if k[0] not in rt):,}; {len(want_m):,}")
        mt = {r[0] for r in want_m}
        bad = sum(1 for r in A if r["other"] == ed and
                  r["state_model"] != ("linked" if r["state"] != "linked" and r["t"] in mt else None))
        R.check(f"{ed}: link_account.state_model as SPEC 4.9 (recomputed)", bad == 0, f"{bad} differ")
    # --- facts rendered_by ---
    R.section("facts: rendered_by (4.8)")
    lxx = {r["s"]: r for r in O["lxx"]}
    for lg in ("hbo", "arc", "grc"):
        dd = os.path.join(build, lg)
        F = rows(os.path.join(dd, "facts.parquet"))
        P = rows(os.path.join(dd, "pieces.parquet"), ["t", "n", "lexeme"])
        lex = {(p["t"], p["n"]): p["lexeme"] for p in P}
        LL = T[lg]["L"] if lg != "grc" else L
        pair = C.Counter()
        for r in LL:
            if r["basis"] != "linked":
                continue
            objs = []
            if r["other"] == "lxx":
                w = lxx[r["s"]]
                if w["text"]:
                    objs.append((f"lxx:form:{U.normalize('NFC', w['text'].lower())}", "linked", "links.parquet", "hebrew-greek-cf"))
                if w["lemma"]:
                    objs.append((f"lxx:{w['lemma']}", "model", "links.parquet:glaux_lemma", "glaux"))
            else:
                continue                   # the Hebrew New Testaments: below
            for o, kind, m, s_ in objs:
                pair[(lex[(r["t"], r["n"])], r["other"], kind, o, m, s_)] += 1
        if lg == "grc":
            tx = {ed: {x["s"]: x["text"] for x in O[ed]} for ed in EDS}
            for r in LL:
                if r["basis"] == "linked" and tx[r["other"]][r["s"]]:
                    pair[(lex[(r["t"], r["n"])], r["other"], "linked", f"{r['other']}:form:{norm_heb(tx[r['other']][r['s']])}",
                          "links.parquet", "compact-alignments")] += 1
        tot = C.Counter()
        for (lx, o, kind, *_), v in pair.items():
            tot[(lx, o, kind)] += v
        want = sorted((lx, "rendered_by", ob, kind, m, s_, None, v, v / tot[(lx, o, kind)], "")
                      for (lx, o, kind, ob, m, s_), v in pair.items())
        got = sorted(tuple(r.values()) for r in F if r["relation"] == "rendered_by")
        R.check(f"{lg} facts: rendered_by equals the recount from the linked rows (form rows linked; GLAUx lemma rows model)",
                got == want, f"{len(got):,} rows; " + str(dict(C.Counter(g[3] for g in got))))
        R.check(f"{lg} facts: the other rows are kin rows only (stage 16; stage 20's has_class, in_domain, sense_of, "
                f"equivalent_of aside), sorted by (subject, relation, object)",
                all(r["relation"] in KIN for r in F if r["relation"] not in
                    ("rendered_by", "has_class", "in_domain", "sense_of", "equivalent_of"))
                and [(r["subject"], r["relation"], r["object"]) for r in F]
                == sorted((r["subject"], r["relation"], r["object"]) for r in F))
        if lg == "grc":
            R.check("grc unchanged: rendered_by rows equal b1's", got == sorted(
                tuple(r.values()) for r in rows(os.path.join(b1, "grc", "facts.parquet")) if r["relation"] == "rendered_by"))
    # --- strict view ---
    R.section("strict view (links, facts)")
    for lg in ("hbo", "arc", "grc"):
        dd = os.path.join(build, lg)
        LL = rows(os.path.join(dd, "links.parquet"))
        AA = rows(os.path.join(dd, "link_account.parquet"))
        F = rows(os.path.join(dd, "facts.parquet"))
        sl = [{k: v for k, v in r.items() if k != "agree_model"} for r in LL if r["basis"] != "model"]
        sa = [{k: v for k, v in r.items() if k != "state_model"} for r in AA]
        sf = [r for r in F if r["kind"] != "model"]
        R.check(f"{lg} strict view: no value of basis model in links, link_account, facts",
                all(r["basis"] == "linked" for r in sl) and all(r["kind"] != "model" for r in sf))
        R.check(f"{lg} strict view: the account closes over strict links (state linked exactly where a strict link is)",
                {(r["t"], r["n"], r["other"]) for r in sl} == {(r["t"], r["n"], r["other"]) for r in sa if r["state"] == "linked"}
                and len({(r["t"], r["n"], r["other"]) for r in sa}) == len(sa), f"{len(sa):,} rows")
        b1l = rows(os.path.join(b1, lg, "links.parquet"))
        keep = sorted(tuple(r.values()) for r in b1l if r["how"] not in MODEL_HOW)
        if not (V12 and lg != "grc"):
            R.check(f"{lg} strict view: links equal b1's rows whose rule reads no GLAUx lemma (unchanged)",
                    sorted((r["t"], r["n"], r["other"], r["s"], r["how"], r["agree"]) for r in sl) == keep, f"{len(keep):,}")
    # --- categories.toml, sources.json ---
    R.section("model attribution (links)")
    for lg in ("hbo", "arc", "grc"):
        dd = os.path.join(build, lg)
        with open(os.path.join(dd, "categories.toml"), "rb") as fh:
            cat = tomllib.load(fh)
        LL = rows(os.path.join(dd, "links.parquet"))
        AA = rows(os.path.join(dd, "link_account.parquet"))
        cv = lambda sec: {v["code"]: v["count"] for v in sec.get("values", [])}
        R.check(f"{lg} categories.toml links.how, links.basis, link_account.state, state_model: every code with its count",
                cv(cat["links"]["how"]) == dict(C.Counter(r["how"] for r in LL))
                and cv(cat["links"]["basis"]) == dict(C.Counter(r["basis"] for r in LL))
                and cv(cat["link_account"]["state"]) == dict(C.Counter(r["state"] for r in AA))
                and cv(cat["link_account"]["state_model"]) == dict(C.Counter(r["state_model"] for r in AA if r["state_model"])))
        secs = [cat["links"]["agree_model"], cat["link_account"]["state_model"], cat["facts"]["rendered_by"]]
        if lg == "grc":
            secs += [cat["other"][ed]["analysis_basis"] for ed in EDS]
        else:
            secs += [cat["other"]["lxx"]["class"], cat["other"]["lxx"]["lemma"]]
        named_ok = all((s.get("filled") is False) or (s.get("dataset") and s.get("version") and s.get("models")
                                                       and s.get("human_check") == "no human check") for s in secs[:2] + secs[3:])
        if lg != "grc":
            named_ok = named_ok and bool(secs[2].get("models"))
        R.check(f"{lg} categories.toml: every M column of the links names dataset, version, model(s), no human check",
                named_ok)
        with open(os.path.join(dd, "sources.json"), encoding="utf-8") as fh:
            sj = json.load(fh)
        keys = ["hebrew-nt-bridge", "hebrew-nt-part-links", "hebrew-nt-analysis"] if lg == "grc" else ["glaux"]
        R.check(f"{lg} sources.json: model entries {keys} with models, version, no human check",
                all(k in sj["model"] and sj["model"][k].get("models") and sj["model"][k].get("version")
                    and sj["model"][k].get("human_check") == "no human check" for k in keys))
