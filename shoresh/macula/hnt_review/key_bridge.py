#!/usr/bin/env python3
"""A Hebrew -> Greek lexeme bridge from the reviewed NT key alone: the two Hebrew NTs' reviewed links (heb_scg and Delitzsch,
scg_review.py layer -> corrections.jsonl, read by witness_agree.load), lexical marks only (phrase, free and not rendered left out),
Hebrew parts with a Strong's number. No English anywhere (the bridge's jev tier matches glosses). Per (Hebrew, Greek) pair the
reviewed words that link them, summed over the two witnesses; share = of the Hebrew lexeme's reviewed links. Written in
strong_bridge.json's format (h2g: hebrew -> [[greek, tier, count, share]]), tier `key`, so clause_index.py retrieve --bridge reads it.
    . ./env.sh; ~/sil-study/.venv/bin/python lab/bridge/key_bridge.py [--agree-only] [--with-bridge [--fallback]] [--out F]
bridge_engine.py and bridge_lexicon_eval.py read such a file with BRIDGE_FILE=F."""
import argparse, collections, json, os, sqlite3, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import witness_agree as WA  # noqa: E402

B = os.path.join(os.environ["MAKE_TANAKH_PRIVATE"], "rules", "bridge")
SPINE = os.path.join(os.environ["ALIGNER_DATA"], "lexeme-spine-macula.db")


def main(a):
    g = {"n" + k: s for k, lex, s in sqlite3.connect(SPINE).execute("select key, lexeme, strong from spine_words where lexeme like 'grc:%' and strong is not null")}
    eds = {ed: WA.load(ed) for ed in ("heb_scg", "heb_mod")}
    pair = collections.Counter(); n = collections.Counter()
    for ed, d in eds.items():
        other = eds["heb_mod" if ed == "heb_scg" else "heb_scg"]
        for gid, r in d.items():
            if r["how"] != "lexical" or gid not in g:
                continue
            hs = {x for x in r["lex"] if x.startswith("H")}
            if a.agree_only:
                hs &= other.get(gid, {}).get("lex", set())
            for h in hs:
                pair[(int(h[1:]), g[gid])] += 1; n["links"] += 1
    tot = collections.Counter()
    for (h, _), c in pair.items():
        tot[h] += c
    h2g = collections.defaultdict(list)
    for (h, gs), c in sorted(pair.items(), key=lambda x: -x[1]):
        if c >= a.min_count:
            h2g[str(h)].append([gs, "key", c, round(c / tot[h], 3)])
    if a.with_bridge:                                    # key + bridge: the bridge's tiers kept beside the key (coverage of the bridge)
        for h, v in json.load(open(os.path.join(B, "strong_bridge.json"), encoding="utf-8"))["h2g"].items():
            if not (a.fallback and h in h2g):
                h2g[h] += v
    out = os.path.join(B, a.out)
    json.dump({"h2g": h2g, "source": "reviewed NT key, heb_scg + heb_mod, lexical marks" + (", both witnesses agree" if a.agree_only else "") + ((", + strong_bridge.json where the key lacks the lexeme" if a.fallback else ", + strong_bridge.json") if a.with_bridge else "")},
              open(out, "w", encoding="utf-8"))
    print(dict(n), "Hebrew lexemes", len(h2g), "pairs", sum(len(v) for v in h2g.values()), "->", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--agree-only", action="store_true"); ap.add_argument("--min-count", type=int, default=2)
    ap.add_argument("--with-bridge", action="store_true")
    ap.add_argument("--fallback", action="store_true", help="with --with-bridge: the bridge only for Hebrew lexemes the key lacks")
    ap.add_argument("--out", default="strong_bridge_key.json"); main(ap.parse_args())
