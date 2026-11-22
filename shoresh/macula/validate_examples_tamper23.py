"""Stage 23 tamper test: five scratch copies of build d1, one value changed in one table each, and the validator run
on each copy over the stage whose condition must catch it. Passes (exit 0) only when the validator fails every time.

    shoresh/.venv/bin/python -I shoresh/macula/validate_examples_tamper23.py

Writes data/source-examples/d1-tamper23-<n>/ (never deletes; an existing folder is moved to trash-<date>/ first) and
the validator's output to /tmp/claude-1000/source-examples/s23/tamper-<n>.log.
"""
import datetime
import json
import os
import shutil
import subprocess
import sys

import pyarrow as pa
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "data", "source-examples")
LOGS = "/tmp/claude-1000/source-examples/s23"


def edit_parquet(path, fn):
    t = pq.read_table(path)
    d = t.to_pydict()
    what = fn(d)
    pq.write_table(pa.Table.from_pydict(d, schema=t.schema), path)
    return what


def t_words(b):
    def f(d):
        old = d["text"][1000]
        d["text"][1000] = old + "ְ"
        return f"hbo words.parquet row 1001 text {old} -> {d['text'][1000]}"
    return edit_parquet(os.path.join(b, "hbo", "words.parquet"), f)


def t_terms(b):
    p = os.path.join(b, "grc", "terms.tsv")
    with open(p, encoding="utf-8") as fh:
        s = fh.read()
    s2 = s.replace("\tσκοπός\t", "\tτέρμα\t", 1)
    assert s2 != s
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(s2)
    return "grc terms.tsv sem_role goal σκοπός -> τέρμα"


def t_links(b):
    def f(d):
        i = next(i for i, (bs, am) in enumerate(zip(d["basis"], d["agree_model"])) if bs == "linked" and am == 0)
        d["agree_model"][i] = 1
        return f"arc links.parquet row {i + 1} (t {d['t'][i]}, n {d['n'][i]}, s {d['s'][i]}) agree_model 0 -> 1"
    return edit_parquet(os.path.join(b, "arc", "links.parquet"), f)


def t_source_errors(b):
    p = os.path.join(b, "hbo", "source_errors.tsv")
    with open(p, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    i = next(i for i, ln in enumerate(lines) if ln.startswith("SE1\t"))
    parts = lines[i].split("\t")
    old = parts[2]
    t, n = old.split(".")
    parts[2] = f"{int(t) + 1}.{n}"
    lines[i] = "\t".join(parts)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    return f"hbo source_errors.tsv SE1 row place {old} -> {parts[2]}"


def t_constituents(b):
    terms = {}
    with open(os.path.join(b, "hbo", "terms.tsv"), encoding="utf-8") as fh:
        for ln in fh.read().split("\n")[1:]:
            if ln.startswith("sem_role\t"):
                x = ln.split("\t")
                terms[x[1]] = x[2]

    def f(d):
        i = next(i for i, v in enumerate(d["sem_role"]) if v == terms["actor"])
        d["sem_role"][i] = terms["undergoer"]
        return f"hbo constituents.parquet row {i + 1} ({d['clause'][i]} {d['ord'][i]}) sem_role actor -> undergoer"
    return edit_parquet(os.path.join(b, "hbo", "constituents.parquet"), f)


CASES = [("1", t_words, "23"), ("2", t_terms, "14"), ("3", t_links, "19"), ("4", t_source_errors, "23"),
         ("5", t_constituents, "23")]


def scratch(n):
    b = os.path.join(ROOT, f"d1-tamper23-{n}")
    if os.path.exists(b):
        tr = os.path.join(ROOT, f"trash-{datetime.date.today().isoformat()}")
        os.makedirs(tr, exist_ok=True)
        k = 1
        while os.path.exists(os.path.join(tr, f"d1-tamper23-{n}-{k}")):
            k += 1
        os.rename(b, os.path.join(tr, f"d1-tamper23-{n}-{k}"))
    src = os.path.join(ROOT, "d1")
    shutil.copytree(src, b, ignore=lambda d, names: [x for x in names if d == os.path.join(src, "cache") and x != "morphid.parquet"])
    return b


def main():
    os.makedirs(LOGS, exist_ok=True)
    caught = 0
    for n, fn, stage in CASES:
        b = scratch(n)
        what = fn(b)
        log = os.path.join(LOGS, f"tamper-{n}.log")
        with open(log, "w", encoding="utf-8") as fh:
            r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "validate_examples.py"), "--build",
                                os.path.basename(b), "--upto", "23", "--only", stage], stdout=fh, stderr=subprocess.STDOUT)
        with open(log, encoding="utf-8") as fh:
            fails = [ln.rstrip() for ln in fh if ln.startswith("FAIL")]
        ok = r.returncode != 0 and bool(fails)
        caught += ok
        print(f"tamper {n}: {what}; validator --only {stage}: exit {r.returncode}, {len(fails)} FAIL "
              f"-> {'caught' if ok else 'NOT CAUGHT'}")
        for ln in fails:
            print(f"    {ln[:220]}")
    print(f"{caught} of {len(CASES)} tampered copies failed the validator")
    sys.exit(0 if caught == len(CASES) else 1)


if __name__ == "__main__":
    main()
