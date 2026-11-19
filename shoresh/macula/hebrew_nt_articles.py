"""Greek article links in the Hebrew NTs by rule (S1b, settled 2026-11-17: internal-docs/clause-structure-work/s1b-figures-2026-11-17.md).

    from macula import hebrew_nt_articles as A
    A.links(edition)      # -> {greek article id: {"parts": [(i, part)], "status": ..., "by": "rule" | "aligner"}}
    python -m macula.hebrew_nt_articles --check   # the rule on S1a's sealed sample: must give the settled figures

The rule (R4): the article's head is the first content word after it inside its MACULA Greek phrase (up to three phrases up);
the head's Hebrew word is its reviewed link (hebrew-nt review records v0.1.1: the decision, else the published link). Then
  the head word's article part                                   status primary
  else the head word's pronoun suffix part (אָבִי: the suffix)      status implied
  else, when the next Hebrew word is definite (article or suffix:
  a construct chain), that word's article, else its suffix part    status implied
  else none                                                      status not_rendered
An article whose head has no Hebrew word keeps the aligner's link, a whole word resolved to its article part (`by` aligner).
Scored on the sealed sample (200 articles per edition, blind judges): 0.805 Salkinson, 0.835 Delitzsch (the aligner: 0.440,
0.455). The figure is optimistic: the rule's last revision was shaped on that sample (see the figures note).
"""
from __future__ import annotations

import argparse
import collections
import functools
import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TREES = HERE / "trees-macula.db"
ANALYSIS = HERE / "data" / "bridge-corpus" / "inputs" / "hebrew-nt-analysis@v0.2"
RECORDS = ROOT / "internal-docs" / "hebrew-nt-release" / "review-v0.1.1" / "records"
LINKS = HERE / "data" / "hebrew-nt-bridge"
CONTENT = {"noun", "adj", "verb", "num", "pron"}
HCONTENT = {"noun", "adj", "verb", "num"}


@functools.lru_cache(maxsize=1)
def _greek():
    tr = sqlite3.connect(f"file:{TREES}?mode=ro", uri=True)
    W, SEQ = {}, {}
    for seq, key, cls, par, book, ch, vs in tr.execute(
            "select seq, key, class, parent, book, chapter, verse from words where corpus='grc'"):
        W[key] = (seq, cls, par, (book, ch, vs))
        SEQ[seq] = (key, cls)
    span = {i: (lo, hi) for i, lo, hi in tr.execute("select id, lo, hi from nodes where corpus='grc'")}
    parent = dict(tr.execute("select id, parent from nodes where corpus='grc'"))
    return W, SEQ, span, parent


def head(key: str) -> str | None:
    W, SEQ, span, parent = _greek()
    seq, cls, par, _ = W[key]
    p = par
    for _ in range(3):
        lo, hi = span.get(p, (seq, seq))
        for s in range(seq + 1, hi + 1):
            k, c = SEQ.get(s, (None, None))
            if c in CONTENT:
                return k
        p = parent.get(p)
    return None


def _hebrew(ed: str):
    import pyarrow.parquet as pq
    H = collections.defaultdict(dict)
    for r in pq.read_table(ANALYSIS / ed / "words.parquet", columns=["book", "chapter", "verse", "i", "part", "class"]).to_pylist():
        H[(r["book"], r["chapter"], r["verse"])].setdefault(r["i"], []).append((r["part"], r["class"]))
    return H


def _records(ed: str) -> dict:
    out = {}
    for line in (RECORDS / f"{ed}.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        out[r["gid"]] = r
    return out


def _head_word(rec: dict | None) -> int | None:
    """The head's Hebrew word index from its review record (as s1b.py)."""
    if not rec:
        return None
    af = rec["after"]
    v = af.get("status") or af.get("verdict")
    lk = af.get("link") if v in ("kept", "changed", "added", "right") else af.get("words")
    if v == "wrong" and not rec["before"]["link"] and af.get("words"):
        lk = af["words"]
    if not lk:
        return None
    x = lk[0]
    return x[0] if isinstance(x, list) else int(str(x).split(".")[0])


def rule(verse: dict, hw: int) -> tuple[list[tuple[int, int]], str]:
    def parts(w, cls):
        return [(w, p) for p, c in sorted(verse.get(w, [])) if c in cls]
    art = parts(hw, {"art"})
    if art:
        return art[:1], "primary"
    suf = [x for x in parts(hw, {"pron"}) if x[1] > 0]
    if suf:
        return suf[-1:], "implied"
    nxt = parts(hw + 1, {"art"}) or [x for x in parts(hw + 1, {"pron"}) if x[1] > 0]
    if nxt:
        return nxt[:1], "implied"
    return [], "not_rendered"


def links(ed: str, aligner: dict | None = None, hverse: dict | None = None) -> dict:
    """Every Greek article of the NT: its Hebrew parts by rule, else the aligner's (resolved). `aligner`: greek id -> [(book,
    chapter, verse, i, part)] from links.parquet (read when not given); `hverse`: greek id -> the Hebrew verse its link lies in."""
    import pyarrow.parquet as pq
    W, *_ = _greek()
    H = _hebrew(ed)
    rec = _records(ed)
    if aligner is None:
        aligner = collections.defaultdict(list)
        for r in pq.read_table(LINKS / ed / "links.parquet", columns=["greek_id", "book", "chapter", "verse", "i", "part"]).to_pylist():
            aligner[r["greek_id"]].append((r["book"], r["chapter"], r["verse"], r["i"], r["part"]))
    out = {}
    for key, (seq, cls, par, ref) in W.items():
        if cls != "det":
            continue
        gid = "n" + key
        hk = head(key)
        hw = _head_word(rec.get("n" + hk)) if hk else None
        own = aligner.get(gid, [])
        hl = aligner.get("n" + hk, []) if hk else []
        hv = (hverse or {}).get(gid) or (hl[0][:3] if hl else (own[0][:3] if own else ref))
        if hw is not None and tuple(hv) in H:
            ps, status = rule(H[tuple(hv)], hw)
            out[gid] = {"verse": tuple(hv), "parts": ps, "status": status, "by": "rule"}
        else:
            res = []
            for b, c, v, i, p in own:
                arts = [(i, q) for q, k in sorted(H.get((b, c, v), {}).get(i, [])) if k == "art"]
                res.append(arts[0] if arts else (i, p))
            v0 = own[0][:3] if own else ref
            out[gid] = {"verse": tuple(v0), "parts": sorted(set(res)), "status": "primary" if res else "not_rendered", "by": "aligner"}
    return out


def check() -> None:
    import csv
    W2 = ROOT / "internal-docs" / "clause-structure-work"
    for ed in ("heb_scg", "heb_mod"):
        items = [i for i in json.load(open(W2 / "s1-sealed-2026-11-17" / ed / "items.json"))["items"] if i["cls"] == "det"]
        judged = {}
        for half in (1, 2):
            for r in csv.DictReader(open(W2 / "s1b-judge-2026-11-17" / f"{ed}-{half}.tsv", encoding="utf-8"), delimiter="\t"):
                judged[r["item"]] = r
        hverse = {i["gid"]: tuple(i["hebrew_verse"]) for i in items}
        aligner = {i["gid"]: [(*i["hebrew_verse"], int(x.split(".")[0]), int(x.split(".")[1]) if "." in x else 0) for x in i["link"]]
                   for i in items}
        L = links(ed, aligner=collections.defaultdict(list, aligner), hverse=hverse)
        right = n = 0
        by = collections.Counter()
        for i in items:
            j = judged[i["item"]]["rendering"].strip()
            gold = set() if j in ("-", "") else {x.strip() for x in j.split(",")}
            got = {f"{a}.{b}" for a, b in L[i["gid"]]["parts"]}
            right += got == gold
            n += 1
            by[L[i["gid"]]["by"]] += 1
        print(ed, f"{right}/{n} = {right / n:.3f}", dict(by))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    if ap.parse_args().check:
        check()
