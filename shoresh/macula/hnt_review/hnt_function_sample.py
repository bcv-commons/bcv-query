#!/usr/bin/env python3
"""Function-word check of the Hebrew NT alignments (packet 32, item c; for bcv-query to run): a blind sample of Greek function
words per class and edition, shown with the Greek verse and the Hebrew verse split into parts, for a judge to decide by the rules
below WITHOUT the aligner's link; the link is revealed only in score.

  sample ED BYID_DIR WORDS_PARQUET OUT [--n 40] [--seed 32]
        ED = heb_scg | heb_mod; BYID_DIR = the edition's alignments-by-id files (<BOOK>_<hash>.json); WORDS_PARQUET = its
        hebrew-nt-analysis words.parquet; Greek from MACULA Greek (GREEK_TOKENS: a table key, book, ch, v, text, lemma, class,
        ord; default $MAKE_TANAKH_WORK/orig/grc.sqlite). Classes: det, prep, conj, pron, ptcl (one word per verse, n per class).
        Writes OUT/items.json (with the hidden link) and OUT/batch.md (without it), and OUT/judgments.tsv to fill:
        item, rendering ("t.p,t.p" | "-" = not rendered), verdict of the judge's own reading (sure | unsure), note
  score OUT    the judge's rendering vs the aligner's link per class: right (same parts), partial (overlap), wrong, and for "-":
               right if the aligner also left it unlinked

Rules (as docs/scg-review-design.md rules v2, for function words):
  - article: the Hebrew article part (ה) or the construct / definiteness it is absorbed into; "-" if Hebrew has no article there.
  - preposition: the Hebrew preposition part or word (ב ל כ מ, על, אל, ...) carrying the relation; a Greek case-only relation is
    not in this sample.
  - conjunction: ו and the Hebrew conjunction words (כי, אם, אשר as "that", גם, אבל ...); δέ / καί with no Hebrew word: "-".
  - pronoun: the suffix part or the independent pronoun; a verb's person ending is NOT the pronoun's rendering ("-") unless
    the Greek pronoun is the verb's subject and Hebrew writes no pronoun (then "-" too).
  - particle: the Hebrew word that carries it (negation לא / אל, הנה for ἰδού ...), else "-".
    . ./env.sh; ~/sil-study/.venv/bin/python -I lab/bridge/hnt_function_sample.py sample heb_mod DIR WORDS OUT"""
import argparse, collections, glob, json, os, random, re, sqlite3

CLASSES = ("det", "prep", "conj", "pron", "ptcl")


def greek():
    p = os.environ.get("GREEK_TOKENS") or os.path.join(os.environ["MAKE_TANAKH_WORK"], "orig", "grc.sqlite")
    g = sqlite3.connect("file:" + p + "?mode=ro", uri=True)
    T = {}; V = collections.defaultdict(list)
    for k, b, c, v, text, lemma, cls, o in g.execute("select key, book, ch, v, text, lemma, class, ord from tokens order by key"):
        T["n" + k] = dict(book=b, ch=c, v=v, text=text, lemma=lemma, cls=cls); V[(b, c, v)].append(("n" + k, text))
    return T, V


def hebrew(path):
    import pyarrow.parquet as pq
    H = collections.defaultdict(list)
    for r in pq.read_table(path, columns=["book", "chapter", "verse", "i", "part", "text", "class"]).to_pylist():
        if r["class"] != "verse-number":
            H[(r["book"], r["chapter"], r["verse"])].append((r["i"], r["part"], r["text"] or "∅", r["class"]))
    return {k: sorted(v) for k, v in H.items()}


def sample(a):
    T, V = greek(); H = hebrew(a.words); rng = random.Random(a.seed); items = []
    links = {}; where = {}
    for f in sorted(glob.glob(os.path.join(a.byid, "*.json"))):
        b = os.path.basename(f)[:3]
        for cv, e in json.load(open(f, encoding="utf-8")).items():
            if re.fullmatch(r"\d+:\d+", cv):
                c, v = map(int, cv.split(":"))
                for pos, gids, cls in e["links"]:
                    for g in gids:
                        links[g] = [str(x) for x in pos]; where[g] = (b, c, v)
    by = collections.defaultdict(dict)
    for g, t in T.items():
        if t["cls"] in CLASSES:
            k = (t["book"], t["ch"], t["v"])
            by[t["cls"]].setdefault(k, []).append(g)
    for cls in CLASSES:
        verses = sorted(by[cls]); rng.shuffle(verses)
        for k in verses:
            hk = tuple(where.get(by[cls][k][0], k))
            if hk not in H:
                continue
            g = rng.choice(by[cls][k]); items.append(dict(item=f"{cls}-{sum(i['cls'] == cls for i in items) + 1:02d}", cls=cls, gid=g,
                                                              greek_verse=k, hebrew_verse=hk, link=links.get(g, [])))
            if sum(i["cls"] == cls for i in items) >= a.n:
                break
    os.makedirs(a.out, exist_ok=True)
    json.dump(dict(edition=a.ed, seed=a.seed, n=a.n, items=items), open(os.path.join(a.out, "items.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    with open(os.path.join(a.out, "batch.md"), "w", encoding="utf-8") as f:
        f.write(f"# Function-word check, {a.ed} (blind: no link shown)\n\nRules: see the script's header.\n\n")
        for it in items:
            gk = it["greek_verse"]; hk = tuple(it["hebrew_verse"])
            gtxt = " ".join(f"[{w}]" if g == it["gid"] else w for g, w in V[tuple(gk)])
            htxt = " ".join(f"{i}.{p}:{t}" for i, p, t, _ in H[hk])
            f.write(f"## {it['item']} ({it['cls']}) {gk[0]} {gk[1]}:{gk[2]}\n\nGreek: {gtxt}\n\nHebrew ({hk[0]} {hk[1]}:{hk[2]}): {htxt}\n\n")
    with open(os.path.join(a.out, "judgments.tsv"), "w", encoding="utf-8") as f:
        f.write("item\trendering\tsure\tnote\n" + "".join(f"{it['item']}\t\t\t\n" for it in items))
    print(a.ed, collections.Counter(i["cls"] for i in items))


def score(a):
    D = json.load(open(os.path.join(a.out, "items.json"), encoding="utf-8")); I = {i["item"]: i for i in D["items"]}
    H = None; res = collections.defaultdict(collections.Counter)
    for row in list(open(os.path.join(a.out, "judgments.tsv"), encoding="utf-8"))[1:]:
        it, ren, *_ = (row.rstrip("\n").split("\t") + ["", ""])[:4]
        if not ren:
            continue
        i = I[it]; link = set(i["link"])
        # a link to a whole token counts for every part of it
        def norm(xs):
            return {x if "." in x else x + ".*" for x in xs}
        j = set() if ren == "-" else set(ren.split(","))
        if not j:
            v = "right" if not link else "wrong"
        else:
            L = norm(link); J = norm(j)
            same = L == J or ({x.split(".")[0] for x in L if x.endswith(".*")} >= {x.split(".")[0] for x in J} and all(x.endswith(".*") for x in L))
            ov = {x.split(".")[0] for x in L} & {x.split(".")[0] for x in J}
            v = "right" if same else "partial" if ov else "wrong"
        res[i["cls"]][v] += 1
    out = {c: dict(n) for c, n in res.items()}
    json.dump(out, open(os.path.join(a.out, "score.json"), "w"), indent=1); print(json.dumps(out, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("sample"); s.add_argument("ed"); s.add_argument("byid"); s.add_argument("words"); s.add_argument("out")
    s.add_argument("--n", type=int, default=40); s.add_argument("--seed", type=int, default=32)
    s2 = sp.add_parser("score"); s2.add_argument("out")
    a = ap.parse_args(); {"sample": sample, "score": score}[a.cmd](a)
