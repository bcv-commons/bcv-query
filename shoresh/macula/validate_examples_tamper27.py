"""Tamper test of stage 27 (SPEC 14): a scratch copy of e1 with one value changed in each new table (added, passages)
and in new columns (pieces.clusivity, constituents.ref_status, clauses.marks_model); each copy must fail the stage-27
checks. Uses the D9 maps the validator saved (validate_examples.py --build e1 --upto 27 writes them).

    shoresh/.venv/bin/python -I shoresh/macula/validate_examples_tamper27.py
"""
import json
import os
import shutil
import sys
import time

import pyarrow as pa
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(HERE)
import validate_examples as VE  # noqa: E402
import validate_examples_s27 as S27  # noqa: E402

ROOT = os.path.join(HERE, "data", "source-examples")
E1, D1 = os.path.join(ROOT, "e1"), os.path.join(ROOT, "d1")
SCR = "/tmp/claude-1000/source-examples"
MAPS = os.path.join(SCR, "s27-validate-e1", "d9-maps.json")


def change(path, col, pick, new):
    t = pq.read_table(path)
    d = t.to_pydict()
    i = next(j for j, v in enumerate(d[col]) if pick(v))
    old = d[col][i]
    d[col][i] = new(old)
    pq.write_table(pa.Table.from_pydict(d, schema=t.schema), path)
    return i, old, d[col][i]


CASES = [
    ("hbo added.parquet: kind of the first in_verb row", "hbo", "added.parquet", "kind",
     lambda v: v == "כָּלוּל בַּפֹּעַל", lambda v: "לֹא נֶאֱמַר"),
    ("hbo passages.parquet: last of the first unit", "hbo", "passages.parquet", "last", lambda v: True, lambda v: v + 1),
    ("grc pieces.clusivity: first filled value", "grc", "pieces.parquet", "clusivity", lambda v: bool(v), lambda v: ""),
    ("hbo constituents.ref_status: first filled value", "hbo", "constituents.parquet", "ref_status", lambda v: bool(v),
     lambda v: "לֹא מְבֹרָר" if v != "לֹא מְבֹרָר" else "נִזְכָּר"),
    ("hbo clauses.marks_model: first filled value", "hbo", "clauses.parquet", "marks_model", lambda v: bool(v),
     lambda v: None),
]


def main():
    maps = json.load(open(MAPS, encoding="utf-8"))
    stamp = time.strftime("%H%M%S")
    bad = 0
    for n, (name, lg, f, col, pick, new) in enumerate(CASES, 1):
        dst = os.path.join(ROOT, f"e1-tamper27-{stamp}-{n}")      # beside e1, as the d1 tamper copies of stage 23
        for sub in ("hbo", "arc", "grc", "other"):
            shutil.copytree(os.path.join(E1, sub), os.path.join(dst, sub))
        i, old, val = change(os.path.join(dst, lg, f), col, pick, new)
        R = VE.Report()
        del VE.S10_STAGE_LINES[:]
        S27.stage27(R, dst, d1=D1, quick=True, maps=maps)
        fails = [ln for _st, ln in VE.S10_STAGE_LINES if ln.startswith("FAIL")]
        print(f"== tamper {n}: {name}: row {i}: {old!r} -> {val!r}: {R.fails} FAIL")
        for ln in fails[:5]:
            print("   ", ln[:200])
        bad += R.fails == 0
    print(f"== {len(CASES) - bad} of {len(CASES)} tampered copies fail the checks, as they must")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
