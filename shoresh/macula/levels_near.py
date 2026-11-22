"""Near-synonym routes N1 to N6 and the graded distance N7 (SPEC-levels 5.1, 5.2). Cut points: stage 40's (D-15)."""
import json
import pickle
from collections import Counter, defaultdict
from itertools import combinations

import numpy as np

from levels_common import DATA, is_content_lexeme, lexicon, part_lexemes, table
from levels_explain import explaining

UBS_MAX = 40            # a main domain held by more than 40 lexemes is left out
REND_MIN_OCC = 5        # aligned places a lexeme needs in a language
REND_SHARE = 0.3        # an owned rendering stands on at least this share of them
REND_BUCKET = 30        # a rendering owned by more lexemes than this in one language is left out
REND_LANGS = 10         # the route holds a pair in this many languages or more
VEC_K = 5               # mutual nearest neighbours
ROUTES = ("lex", "ubs", "nt2", "rend", "lxx", "vec")
INDEPENDENT = ("lex", "nt2", "rend", "lxx")   # lex only with meaning true
RENDER_PICKLE = DATA / "compact_renderings_80.pkl"
VEC_DIR = DATA / "vector-store"


def lang(lx):
    return lexicon()[lx]["lang"]


def ordered(a, b):
    return (a, b) if a < b else (b, a)


def route_lex(rows, dropped):
    acc = {}
    for r in explaining(rows):
        x = r["x_lexeme"]
        if not is_content_lexeme(x):
            continue
        for y in r["y_content"]:
            if y == x:
                continue
            if lang(x) != lang(y):
                dropped["lex_cross_lang"] += 1
                continue
            p = ordered(x, y)
            d = acc.setdefault(p, {"n": 0, "kinds": set(), "one": 0, "sources": set(), "meaning": False,
                                   "places": []})
            d["n"] += 1
            d["kinds"].add(r["kind"])
            d["sources"].add(r["source"])
            if r["one_word"]:
                d["one"] += 1
                if r["kind"] == "meaning":
                    d["meaning"] = True
            if r["x_key"] not in d["places"]:
                d["places"].append(r["x_key"])
    out = []
    for (a, b), d in acc.items():
        out.append({"a": a, "b": b, "route": "lex", "basis": "given", "count": d["n"],
                    "evidence": {"kinds": sorted(d["kinds"]), "one_word": d["one"], "sources": sorted(d["sources"])},
                    "meaning": d["meaning"], "engine": False, "places": "; ".join(d["places"][:3])})
    return out


def main_domains():
    """content lexeme -> its main UBS domain (most Tanakh pieces; tie: the smaller code)."""
    main = {}
    for part in ("hbo", "arc"):
        for lx, r in part_lexemes(part).items():
            if not is_content_lexeme(lx) or not r["domains"]:
                continue
            ds = [d.rsplit(":", 1) for d in r["domains"].split()]
            main[lx] = min(((-int(n), c) for c, n in ds))[1]
    return main


def route_ubs(dropped):
    main = main_domains()
    byd = defaultdict(list)
    for lx, d in main.items():
        byd[d].append(lx)
    out = []
    for d in sorted(byd):
        ls = sorted(byd[d])
        if len(ls) > UBS_MAX:
            dropped["ubs_domains_left_out"] += 1
            continue
        for a, b in combinations(ls, 2):
            if lang(a) != lang(b):
                dropped["ubs_cross_lang"] += 1
                continue
            out.append({"a": a, "b": b, "route": "ubs", "basis": "given", "count": 1, "evidence": {"domain": d},
                        "meaning": False, "engine": False, "places": ""})
    return out


def route_pairs(evidence, route, dropped):
    p = table("lexicon", "pairs", ("a", "b", "evidence", "basis", "via", "count", "places"))
    out = []
    for a, b, e, bs, via, n, pl in zip(p["a"], p["b"], p["evidence"], p["basis"], p["via"], p["count"], p["places"]):
        if e != evidence:
            continue
        if not (is_content_lexeme(a) and is_content_lexeme(b)):
            dropped[f"{route}_not_content"] += 1
            continue
        if lang(a) != lang(b):
            dropped[f"{route}_cross_lang"] += 1
            continue
        a2, b2 = ordered(a, b)
        out.append({"a": a2, "b": b2, "route": route, "basis": "given" if route == "lxx" else bs, "count": n,
                    "evidence": {"via": json.loads(via)}, "meaning": False, "engine": route == "lxx",
                    "places": pl})
    return out


def route_rend(dropped):
    """-> (pairs rows, rend_langs rows, info)."""
    d = pickle.load(open(RENDER_PICKLE, "rb"))
    pid2lex = {}
    for part in ("hbo", "arc"):
        pc = table(part, "pieces", ("pid", "lexeme"))
        for pid, lx in zip(pc["pid"], pc["lexeme"]):
            if pid and lx and is_content_lexeme(lx):
                pid2lex[pid[1:]] = lx
    occ = defaultdict(Counter)
    n_occ = Counter()
    for k in sorted(d["features"]):
        lx = pid2lex.get(k)
        if not lx:
            continue
        langs = set()
        for lg, r in d["features"][k]:
            occ[(lg, lx)][r] += 1
            langs.add(lg)
        for lg in langs:
            n_occ[(lg, lx)] += 1
    own = defaultdict(set)
    share = {}
    for (lg, lx), c in occ.items():
        n = n_occ[(lg, lx)]
        if n < REND_MIN_OCC:
            continue
        for r, m in c.items():
            if m >= REND_SHARE * n:
                own[(lg, r)].add(lx)
                share[(lg, r, lx)] = m / n
    per = defaultdict(dict)   # (a, b) -> lang -> (share_a, share_b)
    for (lg, r), ls in sorted(own.items()):
        if len(ls) > REND_BUCKET:
            dropped["rend_renderings_left_out"] += 1
            continue
        for a, b in combinations(sorted(ls), 2):
            if lang(a) != lang(b):
                dropped["rend_cross_lang_language_pairs"] += 1
                continue
            sa, sb = share[(lg, r, a)], share[(lg, r, b)]
            old = per[(a, b)].get(lg)
            cand = (min(sa, sb), sa + sb)
            if old is None or cand > (min(old), old[0] + old[1]):
                per[(a, b)][lg] = (sa, sb)
    rows, lrows = [], []
    code = lambda lg: lg[2:] if lg.startswith("x-") else lg  # noqa: E731
    below = 0
    for (a, b), m in sorted(per.items()):
        if len(m) < REND_LANGS:
            below += 1
            continue
        rows.append({"a": a, "b": b, "route": "rend", "basis": "linked", "count": len(m),
                     "evidence": {"languages": len(m)}, "meaning": False, "engine": False, "places": ""})
        for lg in sorted(m, key=code):
            lrows.append({"a": a, "b": b, "lang": code(lg), "edition": d["editions"][code(lg)],
                          "rendering_share_a": m[lg][0], "rendering_share_b": m[lg][1]})
    info = {"languages": sorted(d["languages"]), "editions": {k: d["editions"][k] for k in sorted(d["editions"])},
            "pairs_below_10_languages": below}
    return rows, lrows, info


def route_vec(dropped):
    meta = json.load(open(VEC_DIR / "lexemes.json", encoding="utf-8"))
    vec = np.load(VEC_DIR / "lexemes.npy")
    bystrong = defaultdict(list)
    for lx in sorted(lexicon()):
        r = lexicon()[lx]
        if not is_content_lexeme(lx) or r["lang"] != "hbo":
            continue
        s = "".join(ch for ch in r["strong"] if ch.isdigit())
        if s:
            bystrong[int(s)].append(lx)
    idx, keys = [], []
    for i, k in enumerate(meta["keys"]):
        if k.startswith("h") and k[1:].isdigit() and int(k[1:]) in bystrong:
            idx.append(i)
            keys.append(int(k[1:]))
    m = vec[idx].astype(np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
    sim = m @ m.T
    np.fill_diagonal(sim, -1)
    top = np.argsort(-sim, axis=1, kind="stable")[:, :VEC_K]
    rank = [{int(j): r + 1 for r, j in enumerate(t)} for t in top]
    out = []
    for i in range(len(idx)):
        for j, ri in rank[i].items():
            if i < j and i in rank[j]:
                la, lb = bystrong[keys[i]], bystrong[keys[j]]
                if len(la) > 1 or len(lb) > 1:
                    dropped["vec_strong_with_several_lexemes"] += 1
                a, b = la[0], lb[0]
                ra, rb = (ri, rank[j][i]) if a < b else (rank[j][i], ri)
                a, b = ordered(a, b)
                out.append({"a": a, "b": b, "route": "vec", "basis": "model", "count": 1,
                            "evidence": {"rank_a": ra, "rank_b": rb}, "meaning": False, "engine": False,
                            "places": ""})
    return out, {"hebrew_vectors_joined": len(idx)}


def strict_groups():
    g = table("lexicon", "groups", ("group", "lexeme", "basis"))
    by = defaultdict(list)
    for gr, lx, bs in zip(g["group"], g["lexeme"], g["basis"]):
        if bs == "derived":
            by[gr].append(lx)
    pairs = set()
    for gr in sorted(by):
        for a, b in combinations(sorted(by[gr]), 2):
            pairs.add((a, b))
    return pairs


def grade_of(rows_of_pair, group):
    """N7 over the given evidence rows of one pair -> (grade, k, routes)."""
    routes = sorted({r["route"] for r in rows_of_pair})
    ind = set()
    lex_false = False
    for r in rows_of_pair:
        if r["route"] == "lex":
            if r["meaning"]:
                ind.add("lex")
            else:
                lex_false = True
        elif r["route"] in ("nt2", "rend", "lxx"):
            ind.add(r["route"])
    k = len(ind)
    if group:
        g = "d2"
    elif k:
        g = "d3"
    elif "ubs" in routes or lex_false:
        g = "d4"
    elif routes == ["vec"]:
        g = "d5"
    else:
        g = "d6"
    return g, k, routes


def grade(by_pair, groups, a, b, without=()):
    """grade(a, b, without): the grade with the rows of the routes in `without` removed ('grp' drops d2)."""
    a, b = ordered(a, b)
    if a == b:
        return "d0"
    rows = [r for r in by_pair.get((a, b), []) if r["route"] not in without]
    return grade_of(rows, (a, b) in groups and "grp" not in without)[0]


def distance(pairs_rows, groups):
    by = defaultdict(list)
    for r in pairs_rows:
        by[(r["a"], r["b"])].append(r)
    out = []
    for p in sorted(set(by) | groups):
        rs = by.get(p, [])
        grp = p in groups
        g, k, routes = grade_of(rs, grp)
        gs, ks, rts = grade_of([r for r in rs if r["basis"] != "model"], grp)
        out.append({"a": p[0], "b": p[1], "grade": g, "k": k, "routes": routes, "grade_strict": gs,
                    "k_strict": ks, "routes_strict": rts, "group": grp})
    return out


def build(rows):
    dropped = Counter()
    pr = route_lex(rows, dropped)
    pr += route_ubs(dropped)
    pr += route_pairs("nt_editions", "nt2", dropped)
    rend, rlangs, rinfo = route_rend(dropped)
    pr += rend
    pr += route_pairs("sept_number", "lxx", dropped)
    vec, vinfo = route_vec(dropped)
    pr += vec
    pr.sort(key=lambda r: (r["route"], r["basis"], r["a"], r["b"]))
    rlangs.sort(key=lambda r: (r["a"], r["b"], r["lang"]))
    groups = strict_groups()
    dist = distance(pr, groups)
    return pr, rlangs, dist, {"dropped": dict(sorted(dropped.items())), "rend": rinfo, "vec": vinfo,
                              "group_pairs": len(groups)}
