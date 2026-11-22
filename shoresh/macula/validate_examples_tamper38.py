"""Stage 38's tamper test (SPEC 1.6 section 14): scratch copies of h1, each with one value changed, each of which the
validator must fail.

    shoresh/.venv/bin/python -I shoresh/macula/validate_examples_tamper38.py [--build h1]

A copy of the table folders (not cache/) is made with hard links (`cp -al`) as `h<stamp>t<n>` beside h1 (an h build,
so that the validator checks it by 1.6); the one file changed is written anew into the copy (a new inode), so h1 is
never written. Then `validate_examples.py --build <copy> --upto 38 --only 38` runs (every condition new in 1.6, and
section 13 against g1). The tamper is caught when the validator ends non-zero and a FAIL line names the changed table.
Ends non-zero when one is not caught. The copies stay; move them to a trash folder.
"""
import argparse
import os
import subprocess
import sys
import time

import pyarrow as pa
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "data", "source-examples")
PY = sys.executable


def rewrite_parquet(path, fn, old):
    t = pq.read_table(path)
    rows = t.to_pylist()
    what = fn(rows, old)
    tmp = path + ".tamper"
    pq.write_table(pa.Table.from_pylist(rows, schema=t.schema), tmp, compression="zstd")
    os.replace(tmp, path)
    return what


def rewrite_tsv(path, fn, old):
    with open(path, encoding="utf-8", newline="") as fh:
        lines = fh.read().split("\n")
    head = lines[0].split("\t")
    rows = [dict(zip(head, ln.split("\t"))) for ln in lines[1:] if ln]
    what = fn(rows, old)
    tmp = path + ".tamper"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join(head) + "\n" + "".join("\t".join(r[h] for h in head) + "\n" for r in rows))
    os.replace(tmp, path)
    return what


def _key(r):
    return (r["clause"], r["verb"], r["role"])


def t_subject_back(rows, old):
    """A new subject row (R1) put back to g1's kind (elsewhere) and form none."""
    g = {_key(r): r for r in old}
    r = next(r for r in rows if r["form"] == "ending" and g[_key(r)]["form"] == "none" and r["role"] == "A0")
    r["kind"], r["form"] = g[_key(r)]["kind"], "none"
    return f"hbo added {_key(r)}: kind/form -> {r['kind']} / none (g1's)"


def t_person_back(rows, old):
    """A person of an ending row put back to the dataset's (g1's)."""
    g = {_key(r): r for r in old}
    r = next(r for r in rows if r["form"] == "ending" and g[_key(r)]["person"] and r["person"] != g[_key(r)]["person"])
    was, r["person"] = r["person"], g[_key(r)]["person"]
    return f"hbo added {_key(r)}: person {was} -> {r['person']} (the dataset's)"


def t_who_cut(rows, old):
    """A plural who cut to one of its members."""
    r = next(r for r in rows if len(r["who"].split()) >= 2 and r["who_reason"] == "verb_and_antecedent")
    was, r["who"] = r["who"], r["who"].split()[0]
    return f"hbo added {_key(r)}: who {was} -> {r['who']}"


def t_se5_gone(rows, old):
    """An SE5 row taken away."""
    i = next(i for i, r in enumerate(rows) if r["rule"] == "SE5")
    r = rows.pop(i)
    return f"hbo source_errors.tsv: SE5 row {r['place']} taken away"


def t_member_back(rows, old):
    """A member that step 2b takes out put back into its group (g1's row)."""
    have = {(r["group"], r["lexeme"]) for r in rows}
    groups = {r["group"] for r in rows}
    x = next(dict(r) for r in old if r["basis"] == "derived" and r["joined_by"] == "anchor" and not r["head"]
             and r["lexeme"].startswith("lex:hbo:") and r["group"] in groups and (r["group"], r["lexeme"]) not in have)
    rows.append(x)
    rows.sort(key=lambda r: (r["group"], r["lexeme"]))
    return f"lexicon groups.parquet: {x['lexeme']} put back into {x['group']}"


def t_adonai(rows, old):
    """אֲדֹנָי put back to alone."""
    r = next(r for r in rows if r["lemma"] == "אֲדֹנָי" and r["lang"] == "hbo" and r["state"] == "kept_out")
    r["state"] = "alone"
    return f"lexicon lexemes.tsv: {r['lexeme']} kept_out -> alone"


# (file, function, tsv?, expected word in a FAIL line)
TAMPERS = [("hbo/added.parquet", t_subject_back, False, "added"),
           ("hbo/added.parquet", t_person_back, False, "added"),
           ("hbo/added.parquet", t_who_cut, False, "added"),
           ("hbo/source_errors.tsv", t_se5_gone, True, "source_errors"),
           ("lexicon/groups.parquet", t_member_back, False, "groups"),
           ("lexicon/lexemes.tsv", t_adonai, True, "kept_out")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", default="h1")
    a = ap.parse_args()
    src = os.path.join(ROOT, a.build)
    g1 = os.path.join(ROOT, "g1")
    stamp = time.strftime("%H%M%S")
    procs = []
    for n, (f, fn, tsv, expect) in enumerate(TAMPERS, 1):
        name = f"h{stamp}t{n}"
        dst = os.path.join(ROOT, name)
        os.makedirs(dst)
        for sub in ("hbo", "arc", "grc", "other", "lexicon"):
            subprocess.run(["cp", "-al", os.path.join(src, sub), os.path.join(dst, sub)], check=True)
        if tsv:
            what = rewrite_tsv(os.path.join(dst, f), fn, None)
        else:
            what = rewrite_parquet(os.path.join(dst, f), fn, pq.read_table(os.path.join(g1, f)).to_pylist())
        if len([q for q in procs if q[5].poll() is None]) >= 3:      # at most 3 at a time (memory)
            next(q for q in procs if q[5].poll() is None)[5].wait()
        p = subprocess.Popen([PY, "-I", os.path.join(HERE, "validate_examples.py"), "--build", name, "--upto", "38",
                              "--only", "38"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
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
