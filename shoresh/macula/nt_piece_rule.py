"""Piece grain inside a Greek word <-> Hebrew part pair (for the lexeme-aligner; deterministic, no model).

    cd shoresh && .venv/bin/python -m macula.nt_piece_rule --join internal-docs/nt-tree-join/v0.1 \
        --tables internal-docs/aligner-tables/v0.2 --greek-parts WORD_PARTS/greek/parts.tsv --out DIR

The aligner's level-2 links often give a Greek part every piece of the Hebrew word it renders (ROM 9:9 ἐλεύσ -> א + שוב).
This picks the piece by grammar, where one Greek word alone links a Hebrew level-1 part that has two or more pieces:
  rule:piece_stem      a Greek stem -> the Hebrew stem piece (or the fused piece)
  rule:piece_person    a Greek verb ending with person -> the Hebrew pieces whose features carry the same person
                       (a prefix, an ending, or both: יִּ...וּ); a different person in the Hebrew: no row
  rule:piece_number    a Greek case ending (noun, adjective, participle) in the plural or dual -> a Hebrew ending in the
                       plural or dual; otherwise -> the stem piece
  rule:piece_none      an augment or reduplication -> no Hebrew piece (hebrew_piece_id empty)
Other Greek parts (preverb, particle, fused) get no row: the aligner's link stays.

With --carry, the join's links (made on an older table version) are first moved through the tables' piece map.
Reads the tree join's part_links (the aligner's v02 cells with the paired Hebrew verse resolved) and parts, the tables'
level-2 features, and word-parts' Greek kinds and features. Writes DIR/piece_rule.parquet (edition, greek_part_id,
hebrew_part_id, hebrew_piece_id, basis, table_version) and DIR/report.json. The rows replace the aligner's links for that
(Greek part, Hebrew level-1 part); where there is no row, its links stay.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def heb_person(f: str) -> str:
    return f[3] if f[:1] == "V" and len(f) >= 6 and f[3] in "123" else ""


def heb_number(f: str) -> str:
    if f[:1] in ("N", "A") and len(f) >= 5:
        return f[3]
    if f[:1] == "V" and len(f) >= 6 and f[2] in "rs":       # participle: V stem r/s gender number state
        return f[4]
    return ""


def grc_person(f: str) -> str:
    seg = f.split("-")
    return seg[2][0] if f.startswith("V-") and len(seg) >= 3 and seg[2][:1] in "123" else ""


def grc_number(f: str) -> str:
    seg = f.split("-")
    if f[:1] in ("N", "A", "R", "D", "T") and len(seg) >= 2 and len(seg[1]) >= 2:
        return seg[1][1]                                     # N-NPM: case, number, gender
    if f.startswith("V-") and len(seg) >= 3 and seg[2][:1] in "NGDAV" and len(seg[2]) >= 2:
        return seg[2][1]                                     # participle V-PAP-NPM
    return ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--join", type=Path, required=True)
    ap.add_argument("--tables", type=Path, required=True)
    ap.add_argument("--greek-parts", type=Path, required=True)
    ap.add_argument("--carry", action="store_true", help="the join's links are on an older table version: carry their piece "
                    "ids over through <tables>/<edition>/piece_map_<old>.parquet (every new piece sharing letters)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=False)
    version = json.loads((a.tables / "heb_scg" / "_split.json").read_text())["table_version"]
    gk = {}
    with open(a.greek_parts, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            gk[r["part_id"]] = (r["kind"], r["features"] or "", r["word_id"])
    rows, st, sample = [], collections.Counter(), []
    for ed in ("heb_scg", "heb_mod"):
        piece = {}                                           # part2_id -> (part_id, kind, features, text)
        pieces_of = collections.defaultdict(list)
        for r in pq.read_table(a.tables / ed / "words.parquet").to_pylist():
            if r["part2_id"]:
                piece[r["part2_id"]] = (r["part_id"], r["level2_kind"], r["level2_features"] or "", r["text"])
                pieces_of[r["part_id"]].append(r["part2_id"])
        links = pq.read_table(a.join / "by" / "part_links.parquet", filters=[("edition", "=", ed)]).to_pylist()
        if a.carry:
            cm = collections.defaultdict(list)
            for f in sorted((a.tables / ed).glob("piece_map_*.parquet")):
                for r in pq.read_table(f).to_pylist():
                    cm[r["old_part2_id"]].append(r["new_part2_id"])
            links = [{**l, "hebrew_piece_id": n} for l in links for n in (cm.get(l["hebrew_piece_id"]) or [l["hebrew_piece_id"]])]
            st[f"{ed}: links carried over through the piece map"] = sum(1 for l in links if l["hebrew_piece_id"] in
                                                                        {n for v in cm.values() for n in v})
        to_part = collections.defaultdict(lambda: collections.defaultdict(set))   # hebrew level-1 part -> greek part -> pieces
        for l in links:
            h = l["hebrew_piece_id"]
            if h and h in piece and l["greek_part_id"].isdigit():
                to_part[piece[h][0]][l["greek_part_id"]].add(h)
        for hp, G in to_part.items():
            ps = pieces_of[hp]
            if len(ps) < 2:
                continue
            words = {gk.get(g, ("", "", ""))[2] for g in G}
            if len(words) != 1 or "" in words:
                st[f"{ed}: Hebrew part linked from several Greek words (no row)"] += 1
                continue
            st[f"{ed}: pairs considered"] += 1
            stems = [p for p in ps if piece[p][1] in ("stem", "fused")]
            for g in sorted(G):
                kind, f, _ = gk[g]
                choice, basis = None, ""
                if kind == "stem" and len(stems) == 1:
                    choice, basis = stems, "rule:piece_stem"
                elif kind in ("augment", "reduplication"):
                    choice, basis = [""], "rule:piece_none"
                elif kind == "ending" and grc_person(f):
                    pr = [p for p in ps if heb_person(piece[p][2])]
                    same = [p for p in pr if heb_person(piece[p][2]) == grc_person(f)]
                    if same and len(same) == len(pr):
                        choice, basis = same, "rule:piece_person"
                    else:
                        st[f"{ed}: person differs or none (no row)"] += 1
                elif kind == "ending" and grc_number(f):
                    many = [p for p in ps if piece[p][1] == "ending" and heb_number(piece[p][2]) in ("p", "d")]
                    if grc_number(f) in ("P", "D") and len(many) == 1:
                        choice, basis = many, "rule:piece_number"
                    elif len(stems) == 1:
                        choice, basis = stems, "rule:piece_number"
                if choice is None:
                    continue
                if set(c for c in choice if c) == G[g] and basis != "rule:piece_none":
                    st[f"{ed}: {basis} already so"] += 1
                    continue
                st[f"{ed}: {basis}"] += 1
                for c in choice:
                    rows.append({"edition": ed, "greek_part_id": g, "hebrew_part_id": hp, "hebrew_piece_id": c, "basis": basis,
                                 "table_version": version})
                if len(sample) < 4000:
                    sample.append((ed, g, hp, sorted(G[g]), choice, basis))
    pq.write_table(pa.Table.from_pylist(rows), a.out / "piece_rule.parquet")
    rep = {"join": str(a.join), "tables": str(a.tables), "table_version": version, "rows": len(rows), **dict(sorted(st.items()))}
    (a.out / "report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(rep, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
