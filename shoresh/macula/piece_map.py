"""Old -> new level-2 piece ids between two aligner-table versions (for carrying links over without a new refine).

    cd shoresh && .venv/bin/python -m macula.piece_map --old internal-docs/aligner-tables/v0.2 \
        --new internal-docs/aligner-tables/v0.3 [--editions heb_scg,heb_mod]

Writes <new>/<edition>/piece_map_<old version>.parquet: for every level-1 part whose pieces differ, each old piece -> new
piece pair that shares letters (old_part2_id, old_text, new_part2_id, new_text, shared_chars); parts whose pieces are the
same keep their ids and are not listed. A piece without an id on one side (a drop fault) is skipped. Prints the counts
and appends the files' sha256 to <new>/SHA256SUMS.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def spans(p: Path) -> dict:
    d = collections.defaultdict(list)
    for r in pq.read_table(p, columns=["part_id", "part2_id", "text"]).to_pylist():
        d[r["part_id"]].append(r)
    out = {}
    for pid, rs in d.items():
        o, out[pid] = 0, []
        for r in rs:
            out[pid].append((r["part2_id"], o, o + len(r["text"]), r["text"]))
            o += len(r["text"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old", type=Path, required=True)
    ap.add_argument("--new", type=Path, required=True)
    ap.add_argument("--editions", default="heb_scg,heb_mod")
    a = ap.parse_args()
    old_v = a.old.name
    rep, sums = {}, []
    for ed in a.editions.split(","):
        A, B = spans(a.old / ed / "words.parquet"), spans(a.new / ed / "words.parquet")
        if A.keys() != B.keys():
            raise SystemExit(f"{ed}: the level-1 parts differ between {a.old} and {a.new}; a piece map is not enough")
        rows, st = [], collections.Counter()
        for pid in A:
            if [(x[0], x[3]) for x in A[pid]] == [(x[0], x[3]) for x in B[pid]]:
                st["level-1 parts unchanged"] += 1
                continue
            st["level-1 parts changed"] += 1
            for i, s, e, t in A[pid]:
                for j, s2, e2, t2 in B[pid]:
                    ov = min(e, e2) - max(s, s2)
                    if ov > 0 and i and j:
                        rows.append({"old_part2_id": i, "old_text": t, "new_part2_id": j, "new_text": t2, "shared_chars": ov})
                        st["map rows"] += 1
        f = a.new / ed / f"piece_map_{old_v}.parquet"
        pq.write_table(pa.Table.from_pylist(rows), f)
        sums.append(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {ed}/{f.name}\n")
        rep[ed] = dict(st)
    with open(a.new / "SHA256SUMS", "a") as fh:
        fh.writelines(sums)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
