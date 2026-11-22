"""Stage 35's tamper test (SPEC 1.5 section 14): scratch copies of g1, each with one value changed, each of which the
validator must fail.

    shoresh/.venv/bin/python -I shoresh/macula/validate_examples_tamper35.py [--build g1]

A copy of the table folders (not cache/) is made with hard links (`cp -al`) as `g<stamp><n>` beside g1 (a g build, so
that the validator checks it by 1.5); the one file changed is written anew into the copy (a new inode), so g1 is never
written. Then `validate_examples.py --build <copy> --upto 35 --only 32 --only 35` runs (stage 32: the lexicon and keys
recomputed; stage 35: every 1.5 condition against f1). The tamper is caught when the validator ends non-zero and a FAIL
line names the changed table. Ends non-zero when one is not caught. The copies stay; move them to a trash folder.
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


def t_added_who(rows):
    r = next(r for r in rows if r["who"] and r["who_reason"] == "verb_and_antecedent" and r["role"] == "A0")
    other = next(x["who"] for x in rows if x["who"] and x["who"] != r["who"])
    old, r["who"] = r["who"], other
    return f"added {r['clause']} {r['verb']} {r['role']}: who {old} -> {other}"


def t_added_back(rows, f1rows):
    keys = {(r["clause"], r["verb"], r["role"]) for r in rows}
    x = next(dict(r) for r in f1rows if (r["clause"], r["verb"], r["role"]) not in keys)
    x["who_reason"] = "no_antecedent" if not x["antecedent"] else "antecedent_no_participant"
    rows.append(x)
    rows.sort(key=lambda r: (r["verb"], r["role"], r["clause"]))
    return f"added: f1's dropped row {x['clause']} {x['verb']} {x['role']} put back"


def t_ref_back(rows, f1rows):
    i = next(i for i, (a, b) in enumerate(zip(f1rows, rows)) if a["role"] == "v" and a["ref_status"] and not b["ref_status"])
    rows[i]["ref_status"], rows[i]["ref_form"] = f1rows[i]["ref_status"], f1rows[i]["ref_form"]
    j = next(j for j in range(len(rows)) if j != i and rows[j]["clause"] == rows[i]["clause"] and rows[j]["ref_status"]
             and (rows[j]["first"], rows[j]["last"]) == (rows[i]["first"], rows[i]["last"]))
    rows[j]["ref_status"], rows[j]["ref_form"] = "", ""
    return f"constituents {rows[i]['clause']} ord {rows[i]['ord']}: ref_status moved back onto the v part"


def t_connective(rows, f1rows):
    import json
    i = next(i for i, (a, b) in enumerate(zip(f1rows, rows)) if json.loads(a["marks"]).get("connective") and
             json.loads(a["marks"]).get("connective") == json.loads(b["marks"]).get("connective"))
    r = rows[i]
    m = json.loads(r["marks"])
    old = m.pop("connective")
    r["marks"] = json.dumps(m, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"clauses {r['clause']}: connective {old} taken away"


def t_h2_back(rows, f1rows):
    i = next(i for i, r in enumerate(rows) if r["key_rule"] == "H2")
    rows[i]["lexeme"], rows[i]["key_rule"] = f1rows[i]["lexeme"], f1rows[i]["key_rule"]
    return f"heb_mod parts s={rows[i]['s']} p={rows[i]['p']}: H2 key put back to the lookup's {rows[i]['lexeme']}"


def t_group_member(rows):
    strict = [r for r in rows if r["basis"] == "derived"]
    a = next(r for r in strict if not r["head"])
    b = next(r for r in strict if r["group"] != a["group"])
    old = a["group"]
    a["group"] = b["group"]
    rows.sort(key=lambda r: (r["group"], r["lexeme"]))
    return f"groups {a['lexeme']}: moved from {old} to {b['group']}"


def t_cognate(rows):
    r = next(r for r in rows if r["joined_by"] == "aramaic_cognate" and r["basis"] == "derived")
    r["joined_by"] = "aramaic_list"
    return f"groups {r['group']} {r['lexeme']}: joined_by aramaic_cognate -> aramaic_list"


def t_part_key(rows):
    i = next(i for i, r in enumerate(rows) if r["key_rule"] == "K1")
    j = next(j for j in range(i + 1, len(rows)) if rows[j]["lexeme"].startswith("lex:") and rows[j]["lexeme"] != rows[i]["lexeme"])
    old, rows[i]["lexeme"] = rows[i]["lexeme"], rows[j]["lexeme"]
    return f"heb_mod parts s={rows[i]['s']} p={rows[i]['p']}: lexeme {old} -> {rows[i]['lexeme']}"


TAMPERS = [  # (file in the build, how, uses f1's file, expected words in a FAIL line)
    ("hbo/added.parquet", t_added_who, False, "added"),
    ("grc/added.parquet", t_added_back, True, "added"),
    ("hbo/constituents.parquet", t_ref_back, True, "ref_status"),
    ("grc/clauses.parquet", t_connective, True, "connective"),
    ("other/heb_mod/parts.parquet", t_h2_back, True, "heb_mod parts"),
    ("other/heb_scg/parts.parquet", t_part_key, False, "heb_scg parts"),
    ("lexicon/groups.parquet", t_group_member, False, "groups"),
    ("lexicon/groups.parquet", t_cognate, False, "groups"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", default="g1")
    a = ap.parse_args()
    src = os.path.join(ROOT, a.build)
    f1 = os.path.join(ROOT, "f1")
    stamp = time.strftime("%H%M%S")
    procs = []
    for n, (f, fn, uses, expect) in enumerate(TAMPERS, 1):
        name = f"g{stamp}t{n}"
        dst = os.path.join(ROOT, name)
        os.makedirs(dst)
        for sub in ("hbo", "arc", "grc", "other", "lexicon"):
            subprocess.run(["cp", "-al", os.path.join(src, sub), os.path.join(dst, sub)], check=True)
        if uses:
            f1rows = pq.read_table(os.path.join(f1, f)).to_pylist()
            what = rewrite_parquet(os.path.join(dst, f), lambda rows: fn(rows, f1rows))
        else:
            what = rewrite_parquet(os.path.join(dst, f), fn)
        if len([q for q in procs if q[5].poll() is None]) >= 3:      # at most 3 at a time (memory)
            next(q for q in procs if q[5].poll() is None)[5].wait()
        p = subprocess.Popen([PY, "-I", os.path.join(HERE, "validate_examples.py"), "--build", name, "--upto", "35",
                              "--only", "32", "--only", "35"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        procs.append((n, f, what, expect, name, p))
    missed = 0
    for n, f, what, expect, name, p in procs:
        out, _ = p.communicate()
        fails = [ln for ln in out.splitlines() if ln.startswith("FAIL")]
        named = [ln for ln in fails if expect in ln]
        ok = p.returncode != 0 and bool(named)
        missed += not ok
        print(f"tamper {n} ({name}): {what}")
        print(f"  validator exit {p.returncode}; {len(fails)} FAIL line(s); caught: {'yes' if ok else 'NO'}")
        for ln in fails:
            print("    " + ln[:300])
        print(f"  {f} in {a.build} untouched: {os.stat(os.path.join(src, f)).st_ino != os.stat(os.path.join(ROOT, name, f)).st_ino}")
    print(f"== {len(TAMPERS) - missed} of {len(TAMPERS)} tampers caught")
    sys.exit(1 if missed else 0)


if __name__ == "__main__":
    main()
