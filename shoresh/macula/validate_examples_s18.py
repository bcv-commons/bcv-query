"""Stage 18 checks (SPEC 1.1, section 10: statements; unchanged).

Called by validate_examples.py --build c1 --upto 18. Imports none of the examples_* builders and reads nothing from
the build's cache/. It recomputes every statement table of SPEC 4.7 with the queries of section 7 from the word
tables, reading only strict columns (STRICT below), and compares row by row:
- it parses the MACULA node files itself (recursively over the XML) for `constructions`, with D2p's head index:
  `Head`, D2p(a) for a two-child conjunction node, D2p(d) at a Hebrew or Aramaic sentence node (the top node, Cat S,
  no Rule: its first CL child, else its first child), 0 for a compound;
- it reads MACULA's Greek `normalized` itself from the lowfat files (the normalised form);
- markers (E5): a suffix piece of class `pron` stands as `sfx:<lang>:<person>.<gender>.<number>` of its own marks;
- agreement (E8): codes that differ where one is `c`, `b` or `x` count as `n_a`;
- clause_links (C10): `connective` is `marks.connective` as a JSON array (keys sorted, no spaces), empty where absent;
- `exceptions.parquet` holds exactly the `against` places, every place exists (hbo and arc read together);
- the columns SPEC 13 calls unchanged equal b1's; what changed is counted.
"""
import collections as C
import csv
import glob
import json
import multiprocessing as mp
import os
import sys
import tomllib
import unicodedata as U
import xml.etree.ElementTree as ET

import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
XID = "{http://www.w3.org/XML/1998/namespace}id"
GRC_LOWFAT = os.path.join(HERE, ".lowfat-src-grc")
HEB_NODES = os.path.join(HERE, "data/macula-nodes/hebrew/WLC/nodes")
GRC_NODES = os.path.join(HERE, "data/macula-nodes/greek/Nestle1904/nodes")
TABLES = ("forms", "paradigms", "markers", "constructions", "orders", "agreement", "frames", "pairs", "clause_links")
GROUP = {"forms": ["lexeme", "marks", "form"], "paradigms": ["class", "marks"],
         "markers": ["marker", "kind", "category"], "constructions": ["level", "rule", "children"],
         "orders": ["rel", "head_class", "dep_class"], "agreement": ["rel", "category"],
         "frames": ["lexeme", "stem", "frame"], "pairs": ["head", "rel", "dep"],
         "clause_links": ["kind", "connective", "parent_kind", "role"]}
EXTRA = {"paradigms": ["lexemes", "forms"], "markers": ["value"], "constructions": ["head_at"],
         "orders": ["before", "after"], "agreement": ["agree", "differ", "n_a"]}
ATTEST = ("forms", "paradigms", "frames", "pairs", "clause_links")    # `against` 0 by section 7
# SPEC 4.7: columns beyond id, count, against, places
SPEC_COLS = {"forms": ["lexeme", "marks", "form"], "paradigms": ["class", "marks", "lexemes", "forms"],
             "markers": ["marker", "kind", "category", "value"],
             "constructions": ["level", "rule", "children", "head_at"],
             "orders": ["rel", "head_class", "dep_class", "before", "after"],
             "agreement": ["rel", "category", "agree", "differ", "n_a"], "frames": ["lexeme", "stem", "frame"],
             "pairs": ["head", "rel", "dep"], "clause_links": ["kind", "connective", "parent_kind", "role"]}
STRICT = {"words": ["t", "head", "rel"],
          "pieces": ["t", "n", "pid", "text", "kind", "lexeme", "class", "marks"],
          "clauses": ["clause", "first", "parent", "role", "role_wrapped", "pred", "pred_kind", "marks"],
          "constituents": ["clause", "ord", "role", "head", "prep"]}
HEB_DROP = set(range(0x0591, 0x05B0)) | {0x05BD, 0x05C4, 0x05C5}
NA_CODES = {"c", "b", "x"}
PLACE_MAP = {}    # pid -> ((t, n), lang); set before the node-file pool forks


def _norm_file(path):
    root = ET.parse(path).getroot()
    return [(w.get(XID), w.get("normalized")) for w in root.iter("w")]


def _nodes_file(path):
    """Branching nodes of one node file: (level, rule, children, head index, sentence node?, first place,
    aramaic row pieces, row pieces)."""
    sys.setrecursionlimit(50000)
    greek = "greek" in path
    out = []

    def leaf_pids(el):
        c = el.find("c")
        if c is not None:
            return [m.get(XID) for m in c.findall("m")]
        if greek:
            return [el.get(XID)]
        m = el.find("m")
        return [m.get(XID)] if m is not None else []

    def visit(el, top):
        kids = [k for k in el if k.tag == "Node"]
        if not kids:
            pids = leaf_pids(el)
            hits = [PLACE_MAP[p] for p in pids if p in PLACE_MAP]
            agg = (min(h[0] for h in hits) if hits else None, sum(1 for h in hits if h[1] == "arc"), len(hits))
            if el.find("c") is not None and len(pids) >= 2:
                out.append(("clause" if el.get("Cat") == "CL" else "phrase", "compound", "", 0, False) + agg)
            return agg
        res = [visit(k, False) for k in kids]
        mins = [r[0] for r in res if r[0] is not None]
        agg = (min(mins) if mins else None, sum(r[1] for r in res), sum(r[2] for r in res))
        if len(kids) >= 2:
            cats = [k.get("Cat") or "" for k in kids]
            hd, rule = el.get("Head"), el.get("Rule")
            sent = (not greek) and top and el.get("Cat") == "S" and rule is None
            if sent:
                h = cats.index("CL") if "CL" in cats else 0
            elif hd is not None:
                h = int(hd)
            elif len(kids) == 2 and sum(1 for c in cats if c in ("conj", "cj", "cjp")) == 1:
                h = 0 if cats[1] in ("conj", "cj", "cjp") else 1
            else:
                h = -1
            if rule is None:
                rule = "run" if hd is not None else ""
            out.append(("clause" if el.get("Cat") == "CL" else "phrase", rule, " ".join(c.lower() for c in cats), h,
                        sent) + agg)
        return agg

    for s in ET.parse(path).getroot().iter("Sentence"):
        for tree in s.findall("./Trees/Tree"):
            tops = [k for k in tree if k.tag == "Node"]
            for k in tops:
                visit(k, len(tops) == 1)
    return out


def _read(build, lang):
    d = os.path.join(build, lang)
    t = {n: pq.read_table(os.path.join(d, f"{n}.parquet"), columns=cols).to_pylist() for n, cols in STRICT.items()}
    with open(os.path.join(d, "lexemes.tsv"), encoding="utf-8", newline="") as fh:
        t["lexemes"] = list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))
    for n in TABLES + ("exceptions",):
        t["S:" + n] = pq.read_table(os.path.join(d, f"{n}.parquet")).to_pylist()
    return t


def _top(tally):
    return sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _expect(lang, t, stem, gnorm, cons, kinds):
    """table -> {group key: (extra values, for places, against places)}; places as (sort key, place)."""
    exp = {n: {} for n in TABLES}
    info = C.Counter()

    def pl(p):
        return ((p["t"], p["n"]), f'{p["t"]}.{p["n"]}')

    def norm(p):
        if lang == "grc":
            return U.normalize("NFC", gnorm[p["pid"]].lower())
        return U.normalize("NFC", "".join(ch for ch in p["text"] if ord(ch) not in HEB_DROP))

    forms, para = C.defaultdict(list), C.defaultdict(lambda: [[], set(), set()])
    for p in t["pieces"]:
        f = norm(p)
        forms[(p["lexeme"], p["marks"], f)].append(pl(p))
        g = para[(p["class"], p["marks"])]
        g[0].append(pl(p))
        g[1].add(p["lexeme"])
        g[2].add(f)
    exp["forms"] = {k: ((), v, []) for k, v in forms.items()}
    exp["paradigms"] = {k: ((len(v[1]), len(v[2])), v[0], []) for k, v in para.items()}

    # markers (E5, E6)
    per_class = C.Counter(r["class"] for r in t["lexemes"])
    small = {r["lexeme"] for r in t["lexemes"] if per_class[r["class"]] <= 40}
    head_of = {w["t"]: w["head"] for w in t["words"]}
    by = C.defaultdict(lambda: C.defaultdict(list))
    sfx_keys = set()
    for p in t["pieces"]:
        if p["kind"] in ("prefix", "suffix"):
            target, kind, marker = stem[p["t"]], p["kind"], p["lexeme"]
            if kind == "suffix" and p["class"] == "pron":
                own = json.loads(p["marks"])
                if {"person", "gender", "number"} <= set(own):
                    marker = "sfx:%s:%s.%s.%s" % (lang, own["person"], own["gender"], own["number"])
                    sfx_keys.add(marker)
                    info["pronoun suffix pieces as sfx keys"] += 1
                else:
                    info["pronoun suffix pieces lacking person/gender/number (lexeme key)"] += 1
        elif p["lexeme"] in small and head_of[p["t"]] != 0:
            target, kind, marker = stem[head_of[p["t"]]], "word", p["lexeme"]
        else:
            continue
        for cat, code in json.loads(target["marks"]).items():
            by[(marker, kind)][cat].append((code, pl(p)))
    info["distinct sfx keys"] = len(sfx_keys)
    info["sfx keys whose targets carry no category (no row possible)"] = len(
        sfx_keys - {m for m, _ in by if m.startswith("sfx:")})
    for (marker, kind), cats in by.items():
        for cat, items in cats.items():
            tally = C.Counter(c for c, _ in items)
            value = _top(tally)
            if len(items) >= 20 and tally[value] >= 0.95 * len(items):
                exp["markers"][(marker, kind, cat)] = ((value,), [x for c, x in items if c == value],
                                                       [x for c, x in items if c != value])

    # constructions
    grp = C.defaultdict(list)
    for level, rule, children, h, sent, place in cons:
        grp[(level, rule, children)].append((h, (place, f"{place[0]}.{place[1]}")))
    for k, items in grp.items():
        hat = _top(C.Counter(h for h, _ in items))
        exp["constructions"][k] = ((hat,), [x for h, x in items if h == hat], [x for h, x in items if h != hat])

    # word edges (E8 in agreement)
    side = C.defaultdict(lambda: ([], []))
    agr = C.defaultdict(lambda: [[], [], 0])
    prs = C.defaultdict(list)
    for w in t["words"]:
        if w["head"] == 0:
            continue
        d, h = stem[w["t"]], stem[w["head"]]
        x = ((w["t"], 0), str(w["t"]))
        side[(w["rel"], h["class"], d["class"])][0 if w["t"] < w["head"] else 1].append(x)
        dm, hm = json.loads(d["marks"]), json.loads(h["marks"])
        for cat in ("gender", "number", "person", "case", "state"):
            if cat in dm and cat in hm:
                if dm[cat] == hm[cat]:
                    agr[(w["rel"], cat)][0].append(x)
                elif dm[cat] in NA_CODES or hm[cat] in NA_CODES:
                    agr[(w["rel"], cat)][2] += 1
                    info["agreement edges n_a by E8"] += 1
                else:
                    agr[(w["rel"], cat)][1].append(x)
            elif cat in dm or cat in hm:
                agr[(w["rel"], cat)][2] += 1
        prs[(h["lexeme"], w["rel"], d["lexeme"])].append(x)
    for k, (b, a) in side.items():
        exp["orders"][k] = ((len(b), len(a)),) + ((b, a) if len(b) >= len(a) else (a, b))
    for k, (a, d, n) in agr.items():
        if a or d:
            exp["agreement"][k] = ((len(a), len(d), n), a, d)
    exp["pairs"] = {k: ((), v, []) for k, v in prs.items() if len(v) >= 2}

    # frames, clause_links
    corder = {c["clause"]: (c["first"], i) for i, c in enumerate(t["clauses"])}
    parts = C.defaultdict(list)
    for r in t["constituents"]:
        parts[r["clause"]].append(r)
    fr, cl = C.defaultdict(list), C.defaultdict(list)
    for c in t["clauses"]:
        x = (corder[c["clause"]], c["clause"])
        if c["pred_kind"] == "v":
            st = stem[c["pred"]]
            ps = sorted(parts[c["clause"]], key=lambda r: r["ord"])
            vs = [r for r in ps if r["role"] == "v" and r["head"] == c["pred"]]
            if not vs:
                info["frames: v clauses with no v part headed by pred"] += 1
            drop = vs[0]["ord"] if vs else None
            roles = sorted(("pp:" + r["prep"] if r["role"] == "pp" and r["prep"] else r["role"])
                           for r in ps if r["ord"] != drop)
            fr[(st["lexeme"], json.loads(st["marks"]).get("stem", ""), " ".join(roles))].append(x)
        m = json.loads(c["marks"])
        pk = kinds[c["parent"]] if c["parent"] else "top"
        conn = json.dumps(m["connective"], ensure_ascii=False, separators=(",", ":")) if "connective" in m else ""
        cl[(m.get("kind", ""), conn, pk, c["role"] or c["role_wrapped"])].append(x)
    exp["frames"] = {k: ((), v, []) for k, v in fr.items()}
    exp["clause_links"] = {k: ((), v, []) for k, v in cl.items()}
    return exp, info


def _model_columns(build):
    """(table, column) of every section of categories.toml whose basis is model, over the three languages."""
    out = set()
    for lang in ("hbo", "arc", "grc"):
        with open(os.path.join(build, lang, "categories.toml"), "rb") as fh:
            cats = tomllib.load(fh)
        for tab, cols in cats.items():
            if isinstance(cols, dict):
                for col, sec in cols.items():
                    if isinstance(sec, dict) and str(sec.get("basis", "")).lower() in ("model", "m"):
                        out.add((tab, col))
    return out


def statements(R, build):
    R.section("statements: the tables of SPEC 4.7, recomputed over the strict columns by the validator's own code")
    model_cols = _model_columns(build)
    read = {(tab, c) for tab, cols in STRICT.items() for c in cols}
    R.check("statements read no column whose basis is model (categories.toml)", not (read & model_cols),
            f"{len(model_cols)} model columns declared, read {sorted(read & model_cols)}")
    R.check("statements read none of the M columns of SPEC 4 (concept, concept_by, who, who_basis, ..._model)",
            not any(c in ("concept", "concept_by", "who", "who_basis") or c.endswith("_model") for _, c in read))
    for lang in ("hbo", "arc", "grc"):
        extra = sorted(os.path.basename(p) for p in glob.glob(os.path.join(build, lang, "*_model.parquet")))
        R.check(f"{lang} no statement table over an M column (SPEC 4.7: none in 1.1)", not extra, extra or 0)
    tabs = {lang: _read(build, lang) for lang in ("hbo", "arc", "grc")}
    stem = {"tan": {}, "grc": {}}
    kinds = {"tan": {}, "grc": {}}
    for lang, t in tabs.items():
        g = "grc" if lang == "grc" else "tan"
        for p in t["pieces"]:
            if p["kind"] == "stem":
                stem[g][p["t"]] = p
        for c in t["clauses"]:
            kinds[g][c["clause"]] = json.loads(c["marks"]).get("kind", "")
    with mp.get_context("fork").Pool(7) as pool:
        gnorm = dict(x for f in pool.map(_norm_file, sorted(glob.glob(os.path.join(GRC_LOWFAT, "*.xml")))) for x in f)
    cons = {"hbo": [], "arc": [], "grc": []}
    sent_groups = {"hbo": set(), "arc": set()}
    for g, files, langs in (("tan", sorted(glob.glob(os.path.join(HEB_NODES, "*.xml"))), ("hbo", "arc")),
                            ("grc", sorted(glob.glob(os.path.join(GRC_NODES, "*.xml"))), ("grc",))):
        PLACE_MAP.clear()
        for lang in langs:
            for p in tabs[lang]["pieces"]:
                PLACE_MAP[p["pid"]] = ((p["t"], p["n"]), lang)
        with mp.get_context("fork").Pool(7) as pool:
            res = pool.map(_nodes_file, files, chunksize=4)
        nosent = C.Counter()
        for f in res:
            for level, rule, children, h, sent, mn, na, nt in f:
                if mn is None:
                    nosent["no row piece"] += 1
                    continue
                lang = "grc" if g == "grc" else ("arc" if 2 * na > nt else "hbo")
                cons[lang].append((level, rule, children, h, sent, mn))
                if sent:
                    nosent["sentence nodes (D2p d)"] += 1
                    sent_groups[lang].add((level, rule, children))
        R.info(f"{g} branching nodes", dict(nosent) | {"rows": sum(len(cons[x]) for x in langs)})
    PLACE_MAP.clear()
    if sum(len(v) for v in cons.values()) == 0:
        R.skip("statements: constructions", "node files not present")
    STATE = {"sent_groups": sent_groups}
    for lang, t in tabs.items():
        g = "grc" if lang == "grc" else "tan"
        exp, info = _expect(lang, t, stem[g], gnorm, cons[lang], kinds[g])
        R.info(f"{lang} rules counted (E5, E8, frames)", dict(sorted(info.items())))
        both = ("hbo", "arc") if g == "tan" else ("grc",)
        pieces_at = {f'{p["t"]}.{p["n"]}' for x in both for p in tabs[x]["pieces"]}
        words_at = {str(w["t"]) for x in both for w in tabs[x]["words"]}
        clauses_at = {c["clause"] for x in both for c in tabs[x]["clauses"]}
        own_at = {f'{p["t"]}.{p["n"]}' for p in t["pieces"]} | {str(w["t"]) for w in t["words"]} \
            | {c["clause"] for c in t["clauses"]}
        exc_by = C.defaultdict(list)
        for r in t["S:exceptions"]:
            exc_by[r["statement"]].append(r["place"])
        total_against, bad_place, other_place = 0, 0, C.Counter()
        for name in TABLES:
            rows = t["S:" + name]
            cols = list(rows[0]) if rows else []
            want = ["id"] + SPEC_COLS[name] + ["count", "against", "places"]
            R.check(f"{lang} {name}: columns are id, those of SPEC 4.7, count, against, places",
                    sorted(cols) == sorted(want), ", ".join(cols))
            gc, xc = GROUP[name], EXTRA.get(name, [])
            keys = [tuple(r[c] for c in gc) for r in rows]
            R.check(f"{lang} {name}: ids run 1..n in the sort order of the grouping columns",
                    [r["id"] for r in rows] == [f"{name}:{i}" for i in range(1, len(rows) + 1)]
                    and keys == sorted(keys) and len(set(keys)) == len(keys), len(rows))
            e = exp[name]
            R.check(f"{lang} {name}: rows equal the recomputed groups", set(keys) == set(e),
                    f"{len(set(keys) ^ set(e))} differ of {len(e)}")
            bad = C.Counter()
            for r, k in zip(rows, keys):
                if k not in e:
                    continue
                ext, pro, con = e[k]
                bad["count"] += r["count"] != len(pro)
                bad["against"] += r["against"] != len(con)
                bad["extra"] += tuple(r[c] for c in xc) != tuple(ext)
                bad["places"] += r["places"] != " ".join(p for _, p in sorted(pro)[:3])
                bad["exc"] += sorted(exc_by.get(r["id"], [])) != sorted(p for _, p in con)
                total_against += r["against"]
            R.check(f"{lang} {name}: every count equals the recount", bad["count"] == 0, bad["count"])
            R.check(f"{lang} {name}: every against equals the recount", bad["against"] == 0, bad["against"])
            if xc:
                R.check(f"{lang} {name}: {', '.join(xc)} equal the recount", bad["extra"] == 0, bad["extra"])
            R.check(f"{lang} {name}: places are the first three in text order", bad["places"] == 0, bad["places"])
            R.check(f"{lang} {name}: the exceptions of each statement are its against places", bad["exc"] == 0,
                    bad["exc"])
            if name in ATTEST:
                R.check(f"{lang} {name}: against is 0 (section 7)", all(r["against"] == 0 for r in rows),
                        sum(1 for r in rows if r["against"]))
            at = clauses_at if name in ("frames", "clause_links") else (
                words_at if name in ("orders", "agreement", "pairs") else pieces_at)
            for r in rows:
                for p in r["places"].split() + exc_by.get(r["id"], []):
                    if p not in at:
                        bad_place += 1
                    elif p not in own_at:
                        other_place[name] += 1
        ids = {r["id"] for n in TABLES for r in t["S:" + n]}
        R.check(f"{lang} exceptions: rows equal the sum of all against", len(t["S:exceptions"]) == total_against,
                f"{len(t['S:exceptions']):,} rows, sum {total_against:,}")
        R.check(f"{lang} exceptions: every statement exists", all(r["statement"] in ids for r in t["S:exceptions"]),
                sum(1 for r in t["S:exceptions"] if r["statement"] not in ids))
        R.check(f"{lang} exceptions: no statement place listed twice",
                len({(r["statement"], r["place"]) for r in t["S:exceptions"]}) == len(t["S:exceptions"]))
        R.check(f"{lang} statements: every place exists" + (" (in hbo or arc)" if g == "tan" else ""),
                bad_place == 0, bad_place)
        R.info(f"{lang} statement places that lie in the other Tanakh table",
               {k: v for k, v in sorted(other_place.items()) if v})
        per_lex = C.defaultdict(set)
        for r in t["S:forms"]:
            per_lex[r["lexeme"]].add(r["form"])
        bad = sum(1 for r in t["lexemes"] if len(per_lex[r["lexeme"]]) != int(r["forms"]))
        R.check(f"{lang} forms: distinct forms per lexeme equal lexemes.tsv `forms`", bad == 0, bad)
        R.check(f"{lang} forms: count sums to the pieces", sum(r["count"] for r in t["S:forms"]) == len(t["pieces"]),
                f"{len(t['pieces']):,}")
        mk = [r["marker"] for r in t["S:markers"]]
        R.check(f"{lang} markers: every marker is a lexeme of lexemes.tsv or an sfx key of the language",
                all(m in per_lex or m.startswith(f"sfx:{lang}:") for m in mk), len(mk))
        R.info(f"{lang} statement rows", {n: len(t["S:" + n]) for n in TABLES})
        R.info(f"{lang} against (sum) by table", {n: sum(r["against"] for r in t["S:" + n]) for n in TABLES})
    return STATE


def _rows(build, lang, name):
    return pq.read_table(os.path.join(build, lang, f"{name}.parquet")).to_pylist()


def unchanged(R, build, b1, state):
    R.section("unchanged: the statement tables SPEC 13 keeps equal b1's (and what changed, counted)")
    if not os.path.isdir(b1):
        R.skip("unchanged: statement tables equal b1", "build b1 not present")
        return
    for lang in ("hbo", "arc", "grc"):
        for name in TABLES:
            A, B = _rows(build, lang, name), _rows(b1, lang, name)
            gc = GROUP[name]
            gb = ["lexeme" if c == "marker" else c for c in gc]
            ka = {tuple(r[c] for c in gc): r for r in A}
            kb = {tuple(r[c] for c in gb): r for r in B}
            cols = [c for c in (A[0] if A else {}) if c not in gc]
            if name in ("forms", "paradigms") or (name == "constructions" and lang == "grc") \
                    or (name == "frames" and lang != "grc"):
                same = A == B
                R.check(f"{lang} unchanged: {name} equals b1 row by row, every column", same,
                        f"{len(A):,} rows")
                continue
            if name == "constructions":
                sg = state["sent_groups"][lang]
                R.check(f"{lang} unchanged: constructions has the rows (ids, keys) of b1", set(ka) == set(kb)
                        and [r["id"] for r in A] == [kb[k]["id"] for k in ka if k in kb], f"{len(A):,} rows")
                free = ("head_at", "count", "against")
                bad = sum(1 for k, r in ka.items() if k in kb for c in cols
                          if r[c] != kb[k][c] and not (k in sg and c in free))
                R.check(f"{lang} unchanged: constructions equals b1 but for head_at, count, against of the rows "
                        "that hold sentence nodes", bad == 0, bad)
                moved = [k for k in sg if k in ka and k in kb and ka[k]["head_at"] != kb[k]["head_at"]]
                pl = [k for k in sg if k in ka and k in kb and ka[k]["places"] != kb[k]["places"]]
                R.info(f"{lang} constructions: rows that hold sentence nodes / head_at changed / places changed",
                       f"{len(sg):,} / {len(moved):,} / {len(pl):,}")
                continue
            common = set(ka) & set(kb)
            diff = C.Counter(c for k in common for c in cols if c != "id" and ka[k][c] != kb[k][c])
            R.info(f"{lang} changed against b1: {name}",
                   f"rows {len(B):,} -> {len(A):,}; keys only in b1 {len(set(kb) - set(ka)):,}, only in c1 "
                   f"{len(set(ka) - set(kb)):,}; of {len(common):,} common keys differ by column {dict(diff)}")
        ea, eb = _rows(build, lang, "exceptions"), _rows(b1, lang, "exceptions")
        R.info(f"{lang} changed against b1: exceptions", f"rows {len(eb):,} -> {len(ea):,}")


def stage18(R, build, src, STASH):
    b1 = os.path.join(os.path.dirname(os.path.normpath(build)), "b1")
    state = statements(R, build)
    unchanged(R, build, b1, state)
