#!/usr/bin/env python3
"""Two witnesses of one Greek word: does Salkinson-Ginsburg (heb_scg) render it by the same Hebrew lexeme as Delitzsch (heb_mod)?
Reads each edition's reviewed layer (scg_review.py layer -> corrections.jsonl), its alignments-by-id files (to place each Greek id
in a verse) and its parts analysis (a lexeme per part). Per Greek word:
  agree    both link it, and their lexemes meet (Strong's number without its letter; a part without one by its text, points removed)
  differ   both link it, lexemes disjoint
  one      one links it, the other leaves it not rendered
  neither  both leave it not rendered
A link given by parts uses those parts; a link to whole words uses their content parts (noun, verb, adj, adv, num, ij, ptcl, x),
or all parts when a word has none (ל, יש, הוא). Counted by the mark (`how`) of each edition, and by who decided it.
    . ./env.sh; ~/sil-study/.venv/bin/python lab/bridge/witness_agree.py [--json OUT]"""
import argparse, collections, glob, json, os, re, unicodedata
import pyarrow.parquet as pq

P = os.environ["MAKE_TANAKH_PRIVATE"]; W = os.environ["MAKE_TANAKH_WORK"]; B = os.path.join(P, "rules", "bridge")
ED = {"heb_scg": (os.path.join(B, "scg_review"), os.path.join(P, "rules", "data", "hebnt", "dl"),
                  os.path.join(W, "download", "hebrew-nt-analysis", "heb_scg", "words.parquet")),
      "heb_mod": (os.path.join(B, "hebmod", "review"), os.path.join(P, "rules", "data", "hebmod", "by-id"),
                  os.path.join(B, "hebmod", "tagger", "export", "heb_mod", "words.parquet"))}
CONTENT = {"noun", "verb", "adj", "adv", "num", "ij", "ptcl", "x"}
POINTS = re.compile(r"[\u0591-\u05c7]")                                       # heb_scg is pointed, Delitzsch is not


def lex(r):
    s = re.sub(r"\D", "", r["strong"] or "")
    return "H" + s if s else "t:" + POINTS.sub("", unicodedata.normalize("NFD", r["text"] or ""))


def load(ed):
    rev, dl, words = ED[ed]
    parts = collections.defaultdict(list)
    for r in pq.read_table(words, columns=["book", "chapter", "verse", "i", "part", "text", "class", "strong"]).to_pylist():
        if r["class"] != "verse-number":
            parts[(r["book"], r["chapter"], r["verse"], r["i"])].append(r)
    where = {}
    for f in glob.glob(os.path.join(dl, "*.json")):
        b = os.path.basename(f)[:3]
        for cv, e in json.load(open(f, encoding="utf-8")).items():
            if ":" in cv:
                c, v = map(int, cv.split(":"))
                for g in [g for L in e["links"] for g in L[1]] + e["none"]:
                    where[g] = (b, c, v)
    out = {}
    for l in open(os.path.join(rev, "corrections.jsonl"), encoding="utf-8"):
        r = json.loads(l); a = r["after"]; b, c, v = where[r["gid"]]; L = set()
        if "link" in a:
            for t, p in a["link"]:
                L |= {lex(x) for x in parts[(b, c, v, t)] if x["part"] == p}
        for t in a.get("words") or []:
            ps = parts[(b, c, v, t)]
            L |= {lex(x) for x in ([x for x in ps if x["class"] in CONTENT] or ps)}
        out[r["gid"]] = {"lex": L, "how": r.get("how") or "not rendered", "by": r["decided_by"]}
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--json"); a = ap.parse_args()
    S, M = load("heb_scg"), load("heb_mod")
    both = sorted(set(S) & set(M)); st = collections.Counter(); by = collections.defaultdict(collections.Counter)
    res = {}
    for g in both:
        s, m = S[g], M[g]
        k = ("agree" if s["lex"] & m["lex"] else "differ") if s["lex"] and m["lex"] else ("one" if s["lex"] or m["lex"] else "neither")
        res[g] = k; st[k] += 1
        by["scg mark: " + s["how"]][k] += 1; by["mod mark: " + m["how"]][k] += 1
        by["both lexical" if s["how"] == m["how"] == "lexical" else "other"][k] += 1
        by["scg " + s["by"]][k] += 1; by["mod " + m["by"]][k] += 1
    print(f"Greek content words in both: {len(both)} (scg only {len(set(S) - set(M))}, mod only {len(set(M) - set(S))})")
    print("| | n | agree | differ | one | neither | agree of both linked |\n|---|---|---|---|---|---|---|")
    for name, c in [("all", st)] + sorted(by.items()):
        n = sum(c.values()); bl = c["agree"] + c["differ"]
        print(f"| {name} | {n} | {c['agree']} | {c['differ']} | {c['one']} | {c['neither']} | {c['agree'] / bl:.1%} |" if bl else f"| {name} | {n} | 0 | 0 | {c['one']} | {c['neither']} | - |")
    if a.json:
        json.dump(res, open(a.json, "w"), separators=(",", ":"))


if __name__ == "__main__":
    main()
