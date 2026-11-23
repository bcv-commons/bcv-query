"""Hebrew part -> Septuagint (GLAUx) part links through Brenton (step B of the id standard, option (a)). Local, unpublished.

    cd shoresh && .venv/bin/python -m macula.build_brenton_part_links --links DIR/links.parquet --join DIR --lxx-parts DIR --out DIR

The lexeme-aligner links Hebrew parts (word-parts v1.1) to Brenton WORDS (its CC BY layer; `aligner_brenton_links.py` makes
the table). Here each Brenton word is taken to its GLAUx word (our Brenton-GLAUx join) and, where the case is clear, down to
GLAUx's parts (lxx-parts):
  rule:one_greek_part    the GLAUx word has one part: every Hebrew part linked to the Brenton word goes to it
  rule:one_hebrew_part   one Hebrew part is linked to the Brenton word: it goes to every part of the GLAUx word
  open                   several on both sides: the link stays at word level (lxx_part_id empty); a later step decides
  no_glaux               the join gives no GLAUx word of the same or a variant form (link differs / none / a fault)
One row per (Hebrew part, Brenton word, GLAUx part); `methods` lists the aligner's methods that made the word link.

Licence: the table holds GLAUx's ids, so it is CC BY-SA 4.0, as GLAUx; the aligner's own layer stays CC BY.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def tsv(p):
    with open(p, encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--links", type=Path, required=True)
    ap.add_argument("--join", type=Path, required=True, help="the Brenton-GLAUx join folder (join.tsv)")
    ap.add_argument("--lxx-parts", type=Path, required=True, help="the lxx-parts folder (parts.tsv)")
    ap.add_argument("--methods", default="eflomal,gloss,gapfill,spanext,residual")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=False)
    keep = set(a.methods.split(","))
    join = {r["bre_word_id"]: r for r in tsv(a.join / "join.tsv")}
    gparts = collections.defaultdict(list)
    for r in tsv(a.lxx_parts / "parts.tsv"):
        gparts["lxx:" + r["word_id"]].append(("lxx:" + r["part_id"], r["kind"], r["text"]))
    heb = collections.defaultdict(lambda: collections.defaultdict(set))   # bre word -> hebrew part -> methods
    for r in pq.read_table(a.links).to_pylist():
        if r["method"] in keep:
            heb[r["bre_word_id"]][r["hebrew_part_id"]].add(r["method"])
    rows, st = [], collections.Counter()
    for w, H in heb.items():
        j = join.get(w, {})
        g = j.get("lxx_word_id") or ""
        P = gparts.get(g, []) if j.get("link") in ("same", "variant") else []
        if not P:
            basis = "no_glaux"
        elif len(P) == 1:
            basis = "rule:one_greek_part"
        elif len(H) == 1:
            basis = "rule:one_hebrew_part"
        else:
            basis = "open"
        st[f"brenton words: {basis}"] += 1
        for h, ms in sorted(H.items()):
            for p in (P if basis.startswith("rule") else [("", "", "")]):
                rows.append({"hebrew_part_id": h, "bre_word_id": w, "lxx_word_id": g if P else "", "lxx_part_id": p[0],
                             "lxx_part_kind": p[1], "basis": basis, "join_link": j.get("link", ""),
                             "methods": ",".join(sorted(ms))})
                st[f"rows: {basis}"] += 1
    pq.write_table(pa.Table.from_pylist(rows), a.out / "part_links.parquet")
    rep = {"links": str(a.links), "join": str(a.join), "lxx_parts": str(a.lxx_parts), "methods": sorted(keep),
           "licence": "CC BY-SA 4.0 (GLAUx ids)", **dict(sorted(st.items()))}
    (a.out / "report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(rep, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
