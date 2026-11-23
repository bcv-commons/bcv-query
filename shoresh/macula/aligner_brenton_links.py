"""The lexeme-aligner's Hebrew part -> Brenton word links as a plain table (step B of the id standard, option (a)).

Runs with the aligner's own Python, from the aligner's folder, reading its files only:

    cd lexeme-aligner && ALIGNER_SPINE_DB=pipeline/lexeme-spine-macula-parts-v1.1.db \
        .venv/bin/python -I ../bcv-query/shoresh/macula/aligner_brenton_links.py \
        --run pipeline/work/brenton/align-parts --usj pipeline/work/brenton/usj \
        --positions ../bcv-query/internal-docs/aligner-tables/v0.1/grc_bre/positions.tsv --out DIR

For every link in the run's per-method files (align_<method>_grc_bre_<BOOK>.jsonl): the Hebrew unit (h_idx) is turned into
its word-parts v1.1 part id through the parts spine, and the Brenton tokens (t_idx, the tokenizer's positions in the
target block the aligner paired with that Hebrew verse) into our `bre:` word ids through our positions table (aligner
tables v0.1, the aligner's numbering). A target block can pool several Brenton verses (a range); positions then run on
across them. Every token is checked against the table's token; a mismatch is counted, not linked.

Writes DIR/links.parquet (hebrew_part_id, bre_word_id, method, score, content, ref) and DIR/report.json.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import sqlite3
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from lexeme_aligner.compact_align import ALL_BOOKS
from lexeme_aligner.hebrew_source import HebrewSource
from lexeme_aligner.refs import encode
from lexeme_aligner.run_pilot import build_corpus
from lexeme_aligner.versification import remapper

METHODS = ("eflomal", "gloss", "gapfill", "spanext", "residual")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--usj", type=Path, required=True)
    ap.add_argument("--positions", type=Path, required=True)
    ap.add_argument("--spine", type=Path, default=Path("pipeline/lexeme-spine-macula-parts-v1.1.db"))
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=False)
    pos = collections.defaultdict(list)                      # (book, chapter, verse) -> [(token, bre id)] in position order
    with open(a.positions, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            pos[(r["book"], int(r["chapter"]), int(r["verse"]))].append((int(r["position"]), r["token"], r["bre_word_id"]))
    for k in pos:
        pos[k].sort()
    db = sqlite3.connect(f"file:{a.spine.resolve()}?mode=ro", uri=True)
    part_of = dict(db.execute("select key, part_id from spine_words where part_id is not null"))
    usj = a.usj.resolve()
    books = [b for b in ALL_BOOKS[:39] if any(a.run.glob(f"align_*_grc_bre_{b}.jsonl"))]
    rec = {}
    for r in build_corpus(books, usj, HebrewSource(), remap=remapper("grc_bre", str(usj))):
        rec[encode(r.book, r.ch, r.v)] = r
    st = collections.Counter()
    rows = []
    for m in METHODS:
        for f in sorted(a.run.glob(f"align_{m}_grc_bre_*.jsonl")):
            for line in open(f, encoding="utf-8"):
                j = json.loads(line)
                r = rec.get(j["ref"])
                if r is None:
                    st["record without a verse"] += len(j["pairs"]); continue
                if not r.tref or not r.toks:
                    st["no target text"] += len(j["pairs"]); continue
                tch, vs = r.tref
                block = []                                    # the target block: verses vs, vs+1, ... until it is consumed
                v = vs
                while len(block) < len(r.toks) and (r.book, tch, v) in pos:
                    block += pos[(r.book, tch, v)]; v += 1
                heb = {t.idx: t for t in r.heb}
                for p in j["pairs"]:
                    t = heb.get(p["h_idx"])
                    pid = part_of.get((t.keys or [None])[0]) if t else None
                    if not pid:
                        st["no part id"] += 1; continue
                    for ti in p["t_idx"]:
                        if ti >= len(block) or ti >= len(r.toks) or block[ti][1] != r.toks[ti]:
                            st["token mismatch"] += 1; continue
                        rows.append({"hebrew_part_id": f"wlc:{pid}", "bre_word_id": block[ti][2], "method": m,
                                     "score": p.get("score"), "content": bool(p.get("content")),
                                     "ref": f"{r.book} {r.ch}:{r.v}"})
                        st[f"links {m}"] += 1
    pq.write_table(pa.Table.from_pylist(rows), a.out / "links.parquet")
    (a.out / "report.json").write_text(json.dumps({"run": str(a.run), "books": books, **dict(st)}, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(dict(st), ensure_ascii=False))


if __name__ == "__main__":
    main()
