"""Check a build of clause tables against the clause scheme (clause-scheme.toml). Reads only the scheme file and the
tables; the same checks for the Tanakh and for each Hebrew New Testament.

  cd shoresh && .venv/bin/python -I macula/validate_scheme.py <scheme.toml> <folder of tables> [--out report.json]

Checked per table: the file is there; every column of the scheme is there with its type, and no column the scheme
does not name; required columns are filled and the key is unique; a coded column holds only values of its value set (a
list column: each member); a column with a basis has `<column>_basis` with an allowed basis wherever the value is
filled and `<column>_p` empty or between 0 and 1; numbers are not negative; each join finds its row (a list column:
each member; a join may name several columns to look in); two columns named `disjoint` share no value. A table with
`editions` must be there when `clauses.edition` holds one of them, and is not looked for otherwise.
Exit status 0 on PASS, 1 on FAIL.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import tomllib
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

TYPES = {"string": pa.types.is_string, "int": pa.types.is_integer, "float": pa.types.is_floating,
         "bool": pa.types.is_boolean, "list": lambda t: pa.types.is_list(t) and pa.types.is_string(t.value_type)}


def filled(v):
    return v is not None and v != "" and v != []


def validate(scheme_path, folder):
    scheme = tomllib.loads(Path(scheme_path).read_text())
    bases = set(scheme["bases"])
    sets = {k: set(v.get("codes", [])) | {t["term"] for t in v.get("terms", [])} for k, v in scheme.get("values", {}).items()}
    fails, counts, tables = [], collections.OrderedDict(), {}

    def fail(table, check, n, example=None):
        fails.append({"table": table, "check": check, "rows": n, "example": example})

    editions = set()
    first = next(iter(scheme["tables"].values()))
    if "edition" in first["columns"] and (Path(folder) / first["file"]).exists():
        editions = set(pq.read_table(Path(folder) / first["file"], columns=["edition"]).column(0).to_pylist())
    for name, t in scheme["tables"].items():
        f = Path(folder) / t["file"]
        if "editions" in t and not editions & set(t["editions"]):
            if f.exists():
                fail(name, "table of another edition", 0, t["file"])
            continue
        if not f.exists():
            fail(name, "file missing", 0, t["file"])
            continue
        tab = pq.read_table(f)
        tables[name] = tab
        counts[name] = {"rows": tab.num_rows}
        want = collections.OrderedDict()
        for col, c in t["columns"].items():
            want[col] = c
            if c.get("basis"):
                want[col + "_basis"] = {"type": "string", "kind": "basis"}
                want[col + "_p"] = {"type": "float", "kind": "sureness"}
        for col in tab.schema.names:
            if col not in want:
                fail(name, "column not in the scheme", tab.num_rows, col)
        data = {}
        for col, c in want.items():
            if col not in tab.schema.names:
                fail(name, "column missing", tab.num_rows, col)
                continue
            if not TYPES[c["type"]](tab.schema.field(col).type):
                fail(name, f"type of {col} is not {c['type']}", tab.num_rows, str(tab.schema.field(col).type))
                continue
            data[col] = tab.column(col).to_pylist()
        for col, c in want.items():
            if col not in data:
                continue
            vals = data[col]
            if c.get("required"):
                bad = [i for i, v in enumerate(vals) if not filled(v)]
                if bad:
                    fail(name, f"{col} empty", len(bad), bad[0])
            if c.get("values"):
                ok = sets[c["values"]]
                bad = collections.Counter()
                for v in vals:
                    for x in (v if isinstance(v, list) else [v]):
                        if filled(x) and x not in ok:
                            bad[x] += 1
                if bad:
                    fail(name, f"{col} has values outside {c['values']}", sum(bad.values()), bad.most_common(3))
            if c.get("prefix"):
                bad = [x for v in vals for x in (v if isinstance(v, list) else [v]) if filled(x) and not x.startswith(c["prefix"])]
                if bad:
                    fail(name, f"{col} without the prefix {c['prefix']}", len(bad), bad[0])
            if c["type"] in ("int", "float") and c.get("kind") != "sureness":
                bad = [v for v in vals if v is not None and v < c.get("min", 0)]
                if bad:
                    fail(name, f"{col} below {c.get('min', 0)}", len(bad), bad[0])
            if c.get("kind") == "sureness":
                bad = [v for v in vals if v is not None and not 0 <= v <= 1]
                if bad:
                    fail(name, f"{col} outside 0..1", len(bad), bad[0])
            if c.get("kind") == "basis":
                base = data.get(col[:-len("_basis")])
                bad = [v for v in vals if filled(v) and v not in bases]
                if bad:
                    fail(name, f"{col} is no allowed basis", len(bad), bad[0])
                if base is not None:
                    bad = [i for i, (v, b) in enumerate(zip(base, vals)) if filled(v) != filled(b)]
                    if bad:
                        fail(name, f"{col} not filled exactly where the value is", len(bad), bad[0])
        key = t.get("key")
        if key and all(k in data for k in key):
            seen = collections.Counter(zip(*[data[k] for k in key]))
            dup = [k for k, v in seen.items() if v > 1]
            if dup:
                fail(name, "key not unique", len(dup), list(dup[0]))
        for a, b in t.get("ordered", []):
            if a in data and b in data:
                bad = [i for i, (x, y) in enumerate(zip(data[a], data[b])) if x is not None and y is not None and x > y]
                if bad:
                    fail(name, f"{a} after {b}", len(bad), bad[0])
        counts[name]["columns"] = len(tab.schema.names)
    def column(ref):
        t, c = ref.split(".")
        return tables[t].column(c).to_pylist() if t in tables and c in tables[t].schema.names else None

    def members(vals):
        return [x for v in vals for x in (v if isinstance(v, list) else [v]) if filled(x)]

    for j in scheme.get("joins", []):
        to = j["to"] if isinstance(j["to"], list) else [j["to"]]
        src, dst = column(j["from"]), [column(x) for x in to]
        if src is None or any(d is None for d in dst):
            continue
        have = set(members([v for d in dst for v in d]))
        bad = [x for x in members(src) if x not in have]
        if bad:
            fail(j["from"].split(".")[0], f"{j['from'].split('.')[1]} not found in {' or '.join(to)}", len(bad), bad[0])
    for d in scheme.get("disjoint", []):
        a, b = column(d["a"]), column(d["b"])
        if a is None or b is None:
            continue
        both = set(members(a)) & set(members(b))
        if both:
            fail(d["a"].split(".")[0], f"{d['a'].split('.')[1]} also in {d['b']}", len(both), sorted(both)[0])
    return {"scheme": scheme.get("scheme"), "version": scheme.get("version"), "result": "FAIL" if fails else "PASS",
            "tables": counts, "fails": fails}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("scheme", type=Path)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    r = validate(a.scheme, a.folder)
    text = json.dumps(r, ensure_ascii=False, indent=1)
    if a.out:
        a.out.write_text(text + "\n")
    print(text)
    sys.exit(0 if r["result"] == "PASS" else 1)


if __name__ == "__main__":
    main()
