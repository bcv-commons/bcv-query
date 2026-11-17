#!/usr/bin/env python3
"""Cross-check of the heb_scg alignment (alignments-by-id v1.1 n1904/h/heb/heb_scg, local copy data/hebnt/dl) against the lexeme
bridge (bridge/strong_bridge_bq.json: bcv-query tiers + ours): per link class, the share of content Greek words (noun, verb, adj)
whose linked Hebrew words include a bridge rendering of the Greek lexeme; for `none`, whether an unlinked Hebrew word of the
verse is one (a candidate missed link). No cost, nothing sent.
    . ./env.sh; ~/sil-study/.venv/bin/python lab/bridge/scg_bridge_probe.py"""
import collections, glob, json, os, re, sqlite3
import pandas as pd
P = os.path.join(os.environ["MAKE_TANAKH_PRIVATE"], "rules"); W = os.environ["MAKE_TANAKH_WORK"]
num = lambda s: int(re.match(r"\d+", str(s)).group()) if s and re.match(r"\d+", str(s)) else None
B = json.load(open(f"{P}/bridge/strong_bridge_bq.json"))["g2h"]
G = {}
for k, strong, cls in sqlite3.connect(f"{W}/orig/grc.sqlite").execute("select key, strong, class from tokens"):
    G["n" + k] = (num(strong), cls)
w = pd.read_parquet(f"{W}/download/hebrew-nt-analysis/heb_scg/words.parquet", columns=["book", "chapter", "verse", "i", "part", "strong"])
H = collections.defaultdict(dict)
for b, c, v, i, p, s in w.itertuples(index=False):
    H[(b, c, v)][(i, p)] = num(s)
st = collections.Counter()
for f in glob.glob(f"{P}/data/hebnt/dl/*.json"):
    book = os.path.basename(f)[:3]
    for cv, e in json.load(open(f)).items():
        if not re.fullmatch(r"\d+:\d+", cv):
            continue
        c, v = map(int, cv.split(":")); hv = H.get((book, c, v), {})
        linked = set()
        for pos, gids, cls in e["links"]:
            hs = set()
            for x in pos:
                t, _, p = str(x).partition(".")
                keys = [(int(t), int(p))] if p else [k for k in hv if k[0] == int(t)]
                linked |= set(keys); hs |= {hv.get(k) for k in keys} - {None}
            for g in gids:
                gs, gc = G.get(g, (None, None))
                if gc not in ("noun", "verb", "adj") or gs is None:
                    continue
                cand = {h for h, *_ in B.get(str(gs), [])}
                st[(cls, "content")] += 1
                if cand:
                    st[(cls, "bridged")] += 1; st[(cls, "agree")] += bool(hs & cand)
        for g in e.get("none", []):
            gs, gc = G.get(g, (None, None))
            if gc in ("noun", "verb", "adj") and gs is not None:
                cand = {h for h, *_ in B.get(str(gs), [])}
                st[("none", "content")] += 1
                if cand:
                    st[("none", "bridged")] += 1
                    st[("none", "agree")] += any(hv[k] in cand for k in hv if k not in linked and hv[k])
print("| class | content Greek words | bridge knows the word | agree with the bridge | hand check (lexeme-aligner) |")
print("|---|---|---|---|---|")
HC = {"kept": "25/25", "inside": "21/25", "part": "21/25", "edited": "25/39", "edited-wide": "17/36", "none": "19/25 right"}
for cls in ("kept", "inside", "part", "edited", "edited-wide", "none"):
    n, b, a = st[(cls, "content")], st[(cls, "bridged")], st[(cls, "agree")]
    if n:
        print(f"| {cls} | {n:,} | {b / n:.1%} | {a / b:.1%} | {HC[cls]} |" if b else f"| {cls} | {n:,} | 0 | - | {HC[cls]} |")
print("(none: 'agree' = an unlinked Hebrew word in the verse is a bridge rendering of it, i.e. a candidate missed link)")
