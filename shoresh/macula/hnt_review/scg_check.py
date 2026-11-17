#!/usr/bin/env python3
"""Blind hand check of the heb_scg alignment against the lexeme bridge (scg_bridge_probe.py's signal). Content Greek words (noun,
verb, adj) whose Greek lexeme the bridge knows, in four groups:
  E+  edited / edited-wide links that agree with the bridge      E-  the same, disagreeing
  K-  kept links that disagree with the bridge                    N+  `none` words with an unlinked bridge rendering in the verse
Round 2 (--round 2, the groups the first round did not cover): K+ kept links that agree with the bridge, N- `none` words with no
bridge rendering in the verse, U content words of any class whose Greek lexeme the bridge does not know; verses of round 1 are
skipped. `sample` draws N per group at random (seed 7, one item per verse), shuffles them and writes items.md WITHOUT the group (key.json
holds it); the judge writes judgments.tsv (id, link: right|partial|wrong, rendering: the right Hebrew token(s) or -, note);
`cands` writes, per item, the bridge's renderings present in the verse (for the second question: is the bridge's candidate the
right one?), only after the judgments; `score` unblinds. Strict = right; lenient = right + partial (the rendering is among the
linked words, with others). Output under $MAKE_TANAKH_PRIVATE/rules/bridge/scg_check/
(SCG_EDITION=heb_mod: Delitzsch, under bridge/hebmod/check/).
    . ./env.sh; ~/sil-study/.venv/bin/python lab/bridge/scg_check.py sample|cands|score [--n 40] [--round 2]"""
import argparse, collections, glob, json, math, os, random, re, sqlite3
import pandas as pd

P = os.path.join(os.environ["MAKE_TANAKH_PRIVATE"], "rules"); W = os.environ["MAKE_TANAKH_WORK"]
# SCG_EDITION picks the Hebrew NT (default heb_scg): its parts analysis, its alignments-by-id files, the output folder
ED = os.environ.get("SCG_EDITION", "heb_scg")
EDITIONS = {"heb_scg": dict(name="Salkinson-Ginsburg", words=f"{W}/download/hebrew-nt-analysis/heb_scg/words.parquet",
                            dl=f"{P}/data/hebnt/dl", out=os.path.join(P, "bridge", "scg_check")),
            "heb_mod": dict(name="Delitzsch", words=f"{P}/bridge/hebmod/tagger/export/heb_mod/words.parquet",
                            dl=f"{P}/data/hebmod/by-id", out=os.path.join(P, "bridge", "hebmod", "check"))}
E = EDITIONS[ED]; OUT = E["out"]
num = lambda s: int(re.match(r"\d+", str(s)).group()) if s and re.match(r"\d+", str(s)) else None


def load():
    B = json.load(open(f"{P}/bridge/strong_bridge_bq.json"))["g2h"]
    G = {}
    for k, b, c, v, text, lemma, strong, cls in sqlite3.connect(f"{W}/orig/grc.sqlite").execute(
            "select key, book, ch, v, text, lemma, strong, class from tokens order by key"):
        G["n" + k] = dict(book=b, ch=c, v=v, text=text, lemma=lemma, strong=num(strong), cls=cls)
    w = pd.read_parquet(E["words"],
                        columns=["book", "chapter", "verse", "i", "part", "word", "text", "strong", "class"])
    H = collections.defaultdict(dict)
    for b, c, v, i, p, word, text, s, cls in w.itertuples(index=False):
        if cls != "verse-number":                                      # a verse number written as a word (Salkinson) is no word
            H[(b, c, v)][(i, p)] = dict(word=word, text=text, strong=num(s), cls=cls)
    return B, G, H


def verses():
    for f in sorted(glob.glob(f"{E['dl']}/*.json")):
        book = os.path.basename(f)[:3]
        for cv, e in json.load(open(f)).items():
            if re.fullmatch(r"\d+:\d+", cv):
                c, v = map(int, cv.split(":")); yield book, c, v, e


def keys_of(pos, hv):
    out = []
    for x in pos:
        t, _, p = str(x).partition(".")
        out += [(int(t), int(p))] if p else sorted(k for k in hv if k[0] == int(t))
    return out


def groups(B, G, H):
    out = collections.defaultdict(list)
    for book, c, v, e in verses():
        hv = H.get((book, c, v), {}); linked = set()
        for pos, gids, cls in e["links"]:
            linked |= set(keys_of(pos, hv))
        gk = {}                                                       # Greek id -> verse key
        for pos, gids, cls in e["links"]:
            ks = keys_of(pos, hv); hs = {hv[k]["strong"] for k in ks if k in hv} - {None}
            for g in gids:
                gw = G.get(g)
                if not gw or gw["cls"] not in ("noun", "verb", "adj") or gw["strong"] is None:
                    continue
                cand = {h for h, *_ in B.get(str(gw["strong"]), [])}
                if not cand:
                    out["U"].append(dict(book=book, ch=c, v=v, g=g, gids=gids, link=[list(k) for k in ks], cls=cls)); continue
                agree = bool(hs & cand)
                grp = ("E+" if agree else "E-") if cls in ("edited", "edited-wide") else (("K+" if agree else "K-") if cls == "kept" else None)
                if grp:
                    out[grp].append(dict(book=book, ch=c, v=v, g=g, gids=gids, link=[list(k) for k in ks], cls=cls))
        for g in e.get("none", []):
            gw = G.get(g)
            if gw and gw["cls"] in ("noun", "verb", "adj") and gw["strong"] is not None:
                cand = {h for h, *_ in B.get(str(gw["strong"]), [])}
                it = dict(book=book, ch=c, v=v, g=g, gids=[g], link=[], cls="none")
                if not cand:
                    out["U"].append(it)
                elif any(hv[k]["strong"] in cand for k in hv if k not in linked and hv[k]["strong"]):
                    out["N+"].append(it)
                else:
                    out["N-"].append(it)
    return out


def sample(a):
    B, G, H = load(); gr = groups(B, G, H); rnd = random.Random(7 + a.round)
    out = OUT if a.round == 1 else os.path.join(OUT, f"round{a.round}")
    byv = collections.defaultdict(list)
    for k, x in G.items():
        byv[(x["book"], x["ch"], x["v"])].append((k, x))
    items, seen = [], set()
    if a.round > 1:
        seen = {(x["book"], x["ch"], x["v"]) for x in json.load(open(os.path.join(OUT, "key.json"))).values()}
    for grp in (("E+", "E-", "K-", "N+") if a.round == 1 else ("K+", "N-", "U")):
        pool = gr[grp][:]; rnd.shuffle(pool); n = 0
        for it in pool:
            vk = (it["book"], it["ch"], it["v"])
            if vk in seen:
                continue
            seen.add(vk); it["group"] = grp; items.append(it); n += 1
            if n == a.n:
                break
        print(grp, len(gr[grp]), "->", n)
    rnd.shuffle(items)
    os.makedirs(out, exist_ok=True); md = []; key = {}
    for i, it in enumerate(items, 1):
        iid = f"q{i:03d}"; key[iid] = it
        vk = (it["book"], it["ch"], it["v"]); hv = H[vk]; gw = G[it["g"]]
        greek = " ".join(f"[{x['text']}]" if k in it["gids"] else x["text"] for k, x in byv[vk])
        toks = collections.OrderedDict()
        for (t, p), x in sorted(hv.items()):
            toks.setdefault(t, x["word"])
        heb = " ".join(f"{t}:{w}" for t, w in toks.items())
        link = sorted({t for t, p in map(tuple, it["link"])})
        parts = ", ".join(f"{t}.{p} {hv[(t, p)]['text']}" for t, p in map(tuple, it["link"]) if (t, p) in hv) or "(none: no link)"
        md += [f"## {iid}  {it['book']} {it['ch']}:{it['v']}", f"Greek word: **{gw['text']}** (lemma {gw['lemma']}, {gw['cls']})",
               f"Greek: {greek}", f"Hebrew: {heb}", f"Linked: tokens {link or '-'}; parts: {parts}", ""]
    open(os.path.join(out, "items.md"), "w", encoding="utf-8").write("\n".join(md))
    json.dump(key, open(os.path.join(out, "key.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(len(items), "items ->", out)


def judgments(d=OUT):
    out = {}
    for l in open(os.path.join(d, "judgments.tsv"), encoding="utf-8"):
        if l.strip() and not l.startswith("#"):
            f = l.rstrip("\n").split("\t"); out[f[0]] = f
    return out


def cands(a):
    B, G, H = load(); key = json.load(open(os.path.join(OUT, "key.json"))); md = []
    for iid, it in key.items():
        hv = H[(it["book"], it["ch"], it["v"])]; gw = G[it["g"]]
        cand = {h for h, *_ in B.get(str(gw["strong"]), [])}
        cs = sorted({t for (t, p), x in hv.items() if x["strong"] in cand})
        md.append(f"{iid}\t{it['book']} {it['ch']}:{it['v']}\t{gw['text']}\tbridge renderings in the verse: " +
                  (", ".join(f"{t}:{hv[(t, 0)]['word'] if (t, 0) in hv else '?'}" for t in cs) or "-"))
    open(os.path.join(OUT, "cands.tsv"), "w", encoding="utf-8").write("\n".join(md) + "\n"); print("cands.tsv written")


def ci(k, n):
    """Wilson 95% interval"""
    if not n:
        return "-"
    p = k / n; z = 1.96; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return f"{p:.0%} [{c - h:.0%}, {c + h:.0%}]"


def score(a):
    d = OUT if a.round == 1 else os.path.join(OUT, f"round{a.round}")
    key = json.load(open(os.path.join(d, "key.json"))); J = judgments(d); st = collections.defaultdict(collections.Counter)
    for iid, it in key.items():
        if iid not in J:
            continue
        j = J[iid]; g = it["group"]; st[g]["n"] += 1; st[g][j[1]] += 1
        if len(j) > 4 and j[4] in ("yes", "no", "-"):
            st[g]["cand " + j[4]] += 1
    print("| group | n | right | right + partial | wrong | bridge candidate right (of judged) |\n|---|---|---|---|---|---|")
    for g in ("E+", "E-", "K-", "N+", "K+", "N-", "U"):
        s = st[g]; n = s["n"]
        if not n:
            continue
        print(f"| {g} | {n} | {ci(s['right'], n)} | {ci(s['right'] + s['partial'], n)} | {s['wrong']} | {s['cand yes']}/{s['cand yes'] + s['cand no']} |")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["sample", "cands", "score"]); ap.add_argument("--n", type=int, default=40); ap.add_argument("--round", type=int, default=1)
    a = ap.parse_args(); {"sample": sample, "cands": cands, "score": score}[a.cmd](a)
