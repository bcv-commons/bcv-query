"""Tamper test of stage 28: six scratch copies of e1, each with one value changed in one table: three tables new in
1.3 (added, who_account, passages) and three of 1.2 that stage 28 changes (pieces.who, clauses.marks time_abs,
constituents.sem_role). Each copy must fail the checks of stages 27 and 28. Uses the D9 maps the validator saved
(validate_examples.py --build e1 --upto 28 writes them).

    shoresh/.venv/bin/python -I shoresh/macula/validate_examples_tamper28.py
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
import validate_examples_s28 as S28  # noqa: E402

ROOT = os.path.join(HERE, "data", "source-examples")
E1, D1 = os.path.join(ROOT, "e1"), os.path.join(ROOT, "d1")
MAPS = os.path.join("/tmp/claude-1000/source-examples", "s27-validate-e1", "d9-maps.json")


def change(path, col, pick, new):
    t = pq.read_table(path)
    d = t.to_pydict()
    i = next(j for j in range(len(d[col])) if pick(d, j))
    old = d[col][i]
    d[col][i] = new(old, d)
    pq.write_table(pa.Table.from_pydict(d, schema=t.schema), path)
    return i, old, d[col][i]


def other_term(m):
    x = json.loads(m)
    x["time_abs"] = "עָתִיד" if x["time_abs"] != "עָתִיד" else "עָבָר"
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


CASES = [   # (name, lang, file, column, pick(d, j), new(old, d))
    ("hbo added.parquet (new in 1.3): who of the first row with one", "hbo", "added.parquet", "who",
     lambda d, j: bool(d["who"][j]), lambda v, d: ""),
    ("hbo who_account.parquet (new in 1.3): state of the first no_row head", "hbo", "who_account.parquet", "state",
     lambda d, j: d["state"][j] == "no_row", lambda v, d: "unresolved"),
    ("hbo passages.parquet (new in 1.3): kind of the first petuchah unit", "hbo", "passages.parquet", "kind",
     lambda d, j: d["kind"][j] == "petuchah", lambda v, d: "setumah"),
    ("grc pieces.who: the first piece filled by D7r gets another participant", "grc", "pieces.parquet", "who",
     lambda d, j: d["who_basis"][j] == "reference",
     lambda v, d: next(w for w in d["who"] if w and w != v and " " not in w)),
    ("hbo clauses.marks: time_abs of the first clause with one", "hbo", "clauses.parquet", "marks",
     lambda d, j: "time_abs" in json.loads(d["marks"][j]), lambda v, d: other_term(v)),
    ("hbo constituents.sem_role: the first object moved by D12c back to actor", "hbo", "constituents.parquet",
     "sem_role", lambda d, j: d["role"][j] == "o" and d["sem_role"][j] == "נִפְעָל" and d["frame_role"][j] == "A0"
     and d["sem_role_basis"][j] == "derived", lambda v, d: "פּוֹעֵל"),
]


def main():
    maps = json.load(open(MAPS, encoding="utf-8"))
    stamp = time.strftime("%H%M%S")
    bad = 0
    for n, (name, lg, f, col, pick, new) in enumerate(CASES, 1):
        dst = os.path.join(ROOT, f"e1-tamper28-{stamp}-{n}")      # beside e1 (scratch), as the copies of stage 27
        for sub in ("hbo", "arc", "grc", "other"):
            shutil.copytree(os.path.join(E1, sub), os.path.join(dst, sub))
        i, old, val = change(os.path.join(dst, lg, f), col, pick, new)
        R = VE.Report()
        del VE.S10_STAGE_LINES[:]
        S27.stage27(R, dst, d1=D1, quick=True, maps=maps)
        S28.stage28(R, dst, d1=D1)
        fails = [ln for _st, ln in VE.S10_STAGE_LINES if ln.startswith("FAIL")]
        print(f"== tamper {n}: {name}: row {i}: {old!r} -> {val!r}: {R.fails} FAIL")
        for ln in fails[:5]:
            print("   ", ln[:220])
        bad += R.fails == 0
    print(f"== {len(CASES) - bad} of {len(CASES)} tampered copies fail the checks, as they must")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
