"""Stage 40, item 6: near-synonym pairs per route (lex, ubs, nt2, rend, lxx, vec), overlap, reach by band, samples.

  shoresh/.venv/bin/python -I shoresh/macula/levels_feasibility_routes.py
    -> stdout, internal-docs/source-examples-work/levels/routes-counts.json, routes-sample.md
Needs explain-statements.jsonl (levels_feasibility_explain.py). Reads our own pickle compact_renderings_80.pkl and the
vector store's lexemes.npy / lexemes.json (both built by this project). About two minutes.
"""
import json
import pickle
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from levels_feasibility_common import (BAND_NAMES, DATA, OUT, SCRATCH, band, dump, lexicon, part_lexemes, table)  # noqa

ROUTES = ("lex", "ubs", "nt2", "rend", "lxx", "vec")
REND_MIN_OCC = 5        # a lexeme needs this many aligned occurrences in a language
REND_SHARE = 0.3        # a rendering is the lexeme's own in that language at this share of its occurrences
REND_BUCKET = 30        # a rendering own to more lexemes than this in one language is too general (dropped)
REND_LANGS = (5, 10, 20, 40)
VEC_K = 5               # mutual nearest neighbours among the Hebrew content lexemes


def content_lexemes():
    lx = lexicon()
    return {l for l, r in lx.items() if r["class"] in ("noun", "verb", "adj", "adv")
            and r["state"] not in ("name", "function")}


def pair(a, b):
    return (a, b) if a < b else (b, a)


def route_lex(content):
    out = defaultdict(set)
    for line in open(SCRATCH / "explain-statements.jsonl", encoding="utf-8"):
        r = json.loads(line)
        if r.get("state") != "statement" or not r.get("x") or not r["x"][0]:
            continue
        if r["kind"] not in ("meaning", "likeness", "derivation"):
            continue
        x = r["x"][0]
        single = len(r["y_content"]) == 1
        for y in r["y_content"]:
            if y != x and x in content and y in content:
                out[pair(x, y)].add(f"{r['source']}:{r['kind']}{':single' if single else ''}")
    return out


def route_ubs(content):
    """same main UBS lexical domain code (the code with most pieces in the lexeme's `domains`), both content."""
    main = {}
    for part in ("hbo", "arc"):
        for l, r in part_lexemes(part).items():
            if l in content and r["domains"]:
                ds = [d.rsplit(":", 1) for d in r["domains"].split()]
                ds = [(int(n), c) for c, n in ds]
                main[l] = max(ds)[1]
    byd = defaultdict(list)
    for l, d in main.items():
        byd[d].append(l)
    out = defaultdict(set)
    sizes = Counter()
    for d, ls in byd.items():
        sizes[min(len(ls), 50)] += 1
        if len(ls) > 40:          # a domain this wide says little about two of its words
            continue
        for a, b in combinations(sorted(ls), 2):
            out[pair(a, b)].add(f"ubs:{d}")
    return out, main, sizes


def route_lexicon(evidence, content):
    p = table("lexicon", "pairs", ("a", "b", "evidence", "basis", "count"))
    out = defaultdict(set)
    for a, b, e, bs, n in zip(p["a"], p["b"], p["evidence"], p["basis"], p["count"]):
        if e == evidence and a in content and b in content:
            out[pair(a, b)].add(f"{e}:{bs}")
    return out


def route_rend(content):
    d = pickle.load(open(DATA / "compact_renderings_80.pkl", "rb"))
    pc = table("hbo", "pieces", ("pid", "lexeme"))
    pid2lex = {p[1:]: l for p, l in zip(pc["pid"], pc["lexeme"]) if p and l in content}
    pa = table("arc", "pieces", ("pid", "lexeme"))
    pid2lex.update({p[1:]: l for p, l in zip(pa["pid"], pa["lexeme"]) if p and l in content})
    occ = defaultdict(Counter)       # (lang, lexeme) -> Counter(rendering)
    n_occ = Counter()
    joined = 0
    for k, feats in d["features"].items():
        l = pid2lex.get(k)
        if not l:
            continue
        joined += 1
        langs = set()
        for lang, r in feats:
            occ[(lang, l)][r] += 1
            langs.add(lang)
        for lang in langs:
            n_occ[(lang, l)] += 1
    own = defaultdict(set)           # (lang, rendering) -> lexemes
    for (lang, l), c in occ.items():
        n = n_occ[(lang, l)]
        if n < REND_MIN_OCC:
            continue
        for r, m in c.items():
            if m >= REND_SHARE * n:
                own[(lang, r)].add(l)
    out = defaultdict(set)           # pair -> languages (the per-edition evidence, kept)
    dropped = 0
    for (lang, r), ls in own.items():
        if len(ls) > REND_BUCKET:
            dropped += 1
            continue
        for a, b in combinations(sorted(ls), 2):
            out[pair(a, b)].add(lang)
    info = {"tokens_in_pickle": len(d["features"]), "tokens_joined_content": joined,
            "languages": len(d["languages"]), "editions": len(d["editions"]),
            "renderings_dropped_too_general": dropped}
    return out, info


def route_vec(content):
    meta = json.load(open(DATA / "vector-store" / "lexemes.json", encoding="utf-8"))
    vec = np.load(DATA / "vector-store" / "lexemes.npy")
    bystrong = defaultdict(list)
    for l in sorted(content):
        r = lexicon()[l]
        s = "".join(ch for ch in r["strong"] if ch.isdigit())
        if s and r["lang"] == "hbo":
            bystrong[int(s)].append(l)
    rows, keys = [], []
    for i, k in enumerate(meta["keys"]):
        if k.startswith("h") and k[1:].isdigit() and int(k[1:]) in bystrong:
            rows.append(i)
            keys.append(int(k[1:]))
    m = vec[rows].astype(np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
    sim = m @ m.T
    np.fill_diagonal(sim, -1)
    top = np.argsort(-sim, axis=1, kind="stable")[:, :VEC_K]
    tops = [set(t) for t in top]
    out = defaultdict(set)
    ambiguous_strong = 0
    for i, t in enumerate(tops):
        for j in t:
            if i < j and i in tops[j]:
                la, lb = bystrong[keys[i]], bystrong[keys[j]]
                if len(la) > 1 or len(lb) > 1:
                    ambiguous_strong += 1
                out[pair(la[0], lb[0])].add(f"vec:{sim[i, j]:.3f}")
    return out, {"hebrew_vectors_joined": len(rows), "strong_with_several_lexemes": ambiguous_strong}


def main():
    content = content_lexemes()
    lx = lexicon()
    routes, info = {}, {}
    routes["lex"] = route_lex(content)
    routes["ubs"], _, sizes = route_ubs(content)
    info["ubs_domain_sizes(capped_50)"] = dict(sorted(sizes.items()))
    routes["nt2"] = route_lexicon("nt_editions", content)
    routes["lxx"] = route_lexicon("sept_number", content)
    rend, info["rend"] = route_rend(content)
    routes["rend"] = rend
    routes["vec"], info["vec"] = route_vec(content)

    freq = {l: int(lx[l]["tanakh"] or 0) + int(lx[l]["heb_mod"] or 0) + int(lx[l]["heb_scg"] or 0) for l in content}
    counts = {"info": info, "routes": {}}
    for name in ROUTES:
        prs = routes[name]
        if name == "rend":
            levels = {f"langs>={k}": sum(1 for v in prs.values() if len(v) >= k) for k in REND_LANGS}
        else:
            levels = {}
        reach = Counter(band(freq[l]) for l in {x for p in prs for x in p})
        counts["routes"][name] = {"pairs": len(prs), "lexemes": len({x for p in prs for x in p}),
                                  "reach_by_band": {b: reach.get(b, 0) for b in BAND_NAMES}, **levels}
        if name == "lex":
            counts["routes"][name]["pairs_single_y"] = sum(1 for v in prs.values() if any(":single" in e for e in v))
            counts["routes"][name]["by_source"] = dict(Counter(e.split(":")[0] for v in prs.values() for e in v))
        if name == "nt2":
            counts["routes"][name]["pairs_with_linked"] = sum(1 for v in prs.values() if any("linked" in e for e in v))
    counts["content_lexemes_by_band"] = dict(Counter(band(freq[l]) for l in content if freq[l] > 0))
    # rend at the rule used for the overlap: at least 10 languages
    use = dict(routes)
    use["rend"] = {p: v for p, v in rend.items() if len(v) >= 10}
    ov = {}
    for a in ROUTES:
        ov[a] = {b: len(set(use[a]) & set(use[b])) for b in ROUTES}
    counts["overlap(rend>=10 langs)"] = ov
    allp = Counter()
    for a in ROUTES:
        for p in use[a]:
            allp[p] += 1
    counts["pairs_by_number_of_routes"] = dict(sorted(Counter(allp.values()).items()))
    no_lxx = Counter(sum(1 for a in ROUTES if a not in ("lxx", "vec") and p in use[a]) for p in allp)
    counts["pairs_by_routes_without_lxx_vec"] = dict(sorted(no_lxx.items()))
    # leave-one-language-out for rend: pairs that drop below 10 languages when one language is left out
    langs = Counter(l for v in use["rend"].values() for l in v)
    worst = max((sum(1 for v in use["rend"].values() if lang in v and len(v) == 10), lang) for lang in langs)
    counts["rend_leave_one_out_worst"] = {"language": worst[1], "pairs_lost": worst[0]}
    counts["rend_languages_used"] = len(langs)
    dump("routes-counts.json", counts)
    print(json.dumps(counts, ensure_ascii=False, indent=1))

    md = ["# Near-synonym routes: 30 pairs per route (fixed rule)", "",
          "Rule: the route's pairs sorted by (a, b) key; rows 0, k, 2k, ... with k = pairs // 30. `rend` is shown at",
          "10 or more languages. Columns: lemma a, lemma b, frequency (Tanakh + both editions) of each, the route's",
          "evidence, and the other routes the pair is in.", ""]
    for name in ROUTES:
        prs = sorted(use[name])
        k = max(1, len(prs) // 30)
        md += [f"## {name} ({len(prs)} pairs)", "", "| a | b | freq a | freq b | evidence | other routes |",
               "|---|---|---|---|---|---|"]
        for a, b in prs[::k][:30]:
            ev = sorted(use[name][(a, b)])
            evs = (f"{len(ev)} languages: " + " ".join(ev[:6]) + (" …" if len(ev) > 6 else "")) if name == "rend" \
                else " ".join(ev[:4])
            oth = " ".join(r for r in ROUTES if r != name and (a, b) in use[r]) or "—"
            md.append(f"| {lx[a]['lemma']} | {lx[b]['lemma']} | {freq[a]} | {freq[b]} | {evs} | {oth} |")
        md.append("")
    (OUT / "routes-sample.md").write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    main()
