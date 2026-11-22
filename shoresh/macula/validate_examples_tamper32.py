"""Stage 32's tamper test (SPEC 1.4 section 14): scratch copies of f1, each with one value changed, each of which the
validator's stage 32 must fail.

    shoresh/.venv/bin/python -I shoresh/macula/validate_examples_tamper32.py [--build f1]

A copy of the table folders (not cache/) is made with hard links (`cp -al`) beside f1 as `f1-tamper32-<stamp>-<n>`; the one file changed is written
anew into the copy (a new inode), so f1 itself is never written. Then `validate_examples.py --build <copy> --upto 32
--only 32` runs; the tamper passes the test when the validator ends non-zero and a FAIL line names the changed thing.
Ends non-zero when one tamper is not caught. The copies stay (no deletion); move them to a trash folder when done.
"""
import argparse
import csv
import os
import subprocess
import sys
import time

import pyarrow as pa
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "data", "source-examples")
PY = sys.executable


def rewrite_parquet(path, fn):
    t = pq.read_table(path)
    rows = t.to_pylist()
    what = fn(rows)
    tmp = path + ".tamper"
    pq.write_table(pa.Table.from_pylist(rows, schema=t.schema), tmp, compression="zstd")
    os.replace(tmp, path)
    return what


def rewrite_tsv(path, fn):
    with open(path, encoding="utf-8", newline="") as fh:
        lines = fh.read().split("\n")
    head = lines[0].split("\t")
    rows = [dict(zip(head, ln.split("\t"))) for ln in lines[1:] if ln]
    what = fn(rows)
    tmp = path + ".tamper"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join(head) + "\n" + "".join("\t".join(r[h] for h in head) + "\n" for r in rows))
    os.replace(tmp, path)
    return what


def t_part_key(rows):
    i = next(i for i, r in enumerate(rows) if r["key_rule"] == "K1")
    j = next(j for j in range(i + 1, len(rows)) if rows[j]["lexeme"].startswith("lex:") and rows[j]["lexeme"] != rows[i]["lexeme"])
    old, rows[i]["lexeme"] = rows[i]["lexeme"], rows[j]["lexeme"]
    return f"heb_mod parts s={rows[i]['s']} p={rows[i]['p']}: lexeme {old} -> {rows[i]['lexeme']}"


def t_part_basis(rows):
    i = next(i for i, r in enumerate(rows) if r["basis"] == "derived")
    rows[i]["basis"] = "model"
    return f"heb_scg parts s={rows[i]['s']} p={rows[i]['p']}: basis derived -> model"


def t_state(rows):
    r = next(r for r in rows if r["state"] == "alone")
    r["state"] = "spread"
    return f"lexemes.tsv {r['lexeme']}: state alone -> spread"


def t_pair_count(rows):
    r = next(r for r in rows if r["evidence"] == "sept_number")
    r["count"] += 1
    return f"pairs {r['a']} {r['b']} sept_number: count {r['count'] - 1} -> {r['count']}"


def t_group_member(rows):
    strict = [r for r in rows if r["basis"] == "derived"]
    a = next(r for r in strict if not r["head"])
    b = next(r for r in strict if r["group"] != a["group"])
    old = a["group"]
    a["group"] = b["group"]
    rows.sort(key=lambda r: (r["group"], r["lexeme"]))
    return f"groups {a['lexeme']}: moved from {old} to {b['group']}"


def t_equiv_kind(rows):
    r = next(r for r in rows if r["relation"] == "equivalent_of" and r["kind"] == "derived")
    r["kind"] = "model"
    return f"arc facts equivalent_of {r['subject']} -> {r['object']}: kind derived -> model"


TAMPERS = [  # (file in the build, how, expected words in a FAIL line)
    ("other/heb_mod/parts.parquet", t_part_key, rewrite_parquet, "heb_mod parts.parquet"),
    ("other/heb_scg/parts.parquet", t_part_basis, rewrite_parquet, "heb_scg parts.parquet"),
    ("lexicon/lexemes.tsv", t_state, rewrite_tsv, "lexemes.tsv state"),
    ("lexicon/pairs.parquet", t_pair_count, rewrite_parquet, "pairs.parquet"),
    ("lexicon/groups.parquet", t_group_member, rewrite_parquet, "groups.parquet"),
    ("arc/facts.parquet", t_equiv_kind, rewrite_parquet, "equivalent_of"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", default="f1")
    a = ap.parse_args()
    src = os.path.join(ROOT, a.build)
    stamp = time.strftime("%H%M%S")
    missed = 0
    for n, (f, fn, rw, expect) in enumerate(TAMPERS, 1):
        name = f"{a.build}-tamper32-{stamp}-{n}"
        dst = os.path.join(ROOT, name)
        os.makedirs(dst)
        for sub in ("hbo", "arc", "grc", "other", "lexicon"):     # the tables; not cache/ (stage 32 reads none of it)
            subprocess.run(["cp", "-al", os.path.join(src, sub), os.path.join(dst, sub)], check=True)
        what = rw(os.path.join(dst, f), fn)
        p = subprocess.run([PY, "-I", os.path.join(HERE, "validate_examples.py"), "--build", name, "--upto", "32", "--only", "32"],
                           capture_output=True, text=True)
        fails = [ln for ln in p.stdout.splitlines() if ln.startswith("FAIL")]
        named = [ln for ln in fails if expect in ln]
        ok = p.returncode != 0 and bool(named)
        missed += not ok
        print(f"tamper {n}: {what}")
        print(f"  validator exit {p.returncode}; {len(fails)} FAIL line(s); caught: {'yes' if ok else 'NO'}")
        for ln in fails:
            print("    " + ln[:300])
        # the source f1 is unchanged: the changed file of the copy is a new inode
        print(f"  {f} in {a.build} untouched: {os.stat(os.path.join(src, f)).st_ino != os.stat(os.path.join(dst, f)).st_ino}")
    print(f"== {len(TAMPERS) - missed} of {len(TAMPERS)} tampers caught")
    sys.exit(1 if missed else 0)


if __name__ == "__main__":
    main()
