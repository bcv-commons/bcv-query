"""Stage 40 (levels feasibility): runs the counting scripts twice, checks the outputs' own consistency and that the
two runs give the same bytes. Ends non-zero when a condition fails.

  shoresh/.venv/bin/python -I shoresh/macula/validate_examples_levels40.py
"""
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from levels_feasibility_common import MAC, OUT, PARTS, SCRATCH, table  # noqa: E402

PY = sys.executable
SCRIPTS = ["levels_feasibility_explain.py", "levels_feasibility_switches.py", "levels_feasibility_nt.py",
           "levels_feasibility_routes.py"]
FILES = ["explain-counts.json", "explain-sample.md", "switches-counts.json",
         "added-sample.md", "nt-counts.json", "routes-counts.json", "routes-sample.md"]
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def run_all():
    times = {}
    for s in SCRIPTS:
        t = time.time()
        r = subprocess.run([PY, "-I", str(MAC / s)], capture_output=True, text=True)
        times[s] = round(time.time() - t, 1)
        if r.returncode != 0:
            print(r.stderr[-2000:])
        check(f"{s} exits 0", r.returncode == 0, f"{times[s]} s")
    h = {f: hashlib.sha256((OUT / f).read_bytes()).hexdigest() for f in FILES if (OUT / f).exists()}
    st = SCRATCH / "explain-statements.jsonl"
    if st.exists():
        h["scratch:explain-statements.jsonl"] = hashlib.sha256(st.read_bytes()).hexdigest()
    return times, h


def main():
    t1, h1 = run_all()
    t2, h2 = run_all()
    check("all output files written", len(h1) == len(FILES) + 1, f"{len(h1)} of {len(FILES) + 1}")
    check("second run gives the same bytes", h1 == h2,
          " ".join(f for f in FILES if h1.get(f) != h2.get(f)) or "all equal")
    ex = json.load(open(OUT / "explain-counts.json", encoding="utf-8"))
    for src in ("mz", "radak", "menahem", "malbim"):
        check(f"explain: {src} has statements", ex[src]["state"].get("statement", 0) > 0,
              str(ex[src]["state"].get("statement", 0)))
        check(f"explain: {src} states sum to rows", sum(ex[src]["state"].values()) == ex[src]["rows"])
    md = (OUT / "explain-sample.md").read_text(encoding="utf-8")
    for src in ("mz", "radak", "menahem", "malbim"):
        block = md.split(f"## {src} ")[1].split("\n## ")[0]
        n = sum(1 for l in block.splitlines() if l.startswith("| ") and not l.startswith("| place"))
        check(f"explain sample: 20 rows for {src}", n == 20, str(n))
    for part in PARTS:
        cov = ex["coverage"][part]
        bl = sum(v["lexemes"] for k, v in cov.items() if k != "all")
        bt = sum(v["tokens"] for k, v in cov.items() if k != "all")
        check(f"coverage {part}: bands sum to the whole", bl == cov["all"]["lexemes"] and bt == cov["all"]["tokens"])
    sw = json.load(open(OUT / "switches-counts.json", encoding="utf-8"))
    for part in PARTS:
        wa = table(part, "who_account", ("head_kind",))["head_kind"]
        n = sum(1 for h in wa if h in ("pronoun", "suffix", "verb_zero"))
        got = sum(v.get(f"heads:{k}", 0) for v in sw[part]["R"].values() for k in ("pronoun", "suffix", "verb_zero"))
        check(f"R {part}: every referring pronoun/suffix/zero head counted", n == got, f"{got} of {n}")
        rows = len(table(part, "added", ("clause",))["clause"])
        a = sum(v for sc in sw[part]["A"].values() for k, v in sc.items() if k.startswith("rows:"))
        ver = sum(v for sc in sw[part]["A"].values() for k, v in sc.items()
                  if k.startswith("verdict:") and k.count(":") == 1)
        check(f"A {part}: every added row counted and given one verdict", rows == a == ver, f"{rows} {a} {ver}")
    bad = {k: v for k, v in sw["pilot_chars_outside"].items() if k.endswith(":con") and v}
    check("pilot: consonant lines hold Hebrew letters and spaces only", not bad, json.dumps(bad))
    allowed = {f"U+{c:04X}" for c in list(range(0x05B0, 0x05BD)) + [0x05C1, 0x05C2, 0x05C7]}
    badp = {k: [c for c in v if c not in allowed] for k, v in sw["pilot_chars_outside"].items() if k.endswith(":poi")}
    check("pilot: pointed lines hold letters, space and the kept points only", not any(badp.values()), json.dumps(badp))
    sm = (OUT / "added-sample.md").read_text(encoding="utf-8")
    n = sum(1 for l in sm.splitlines() if l.startswith("| ") and l[2].isdigit())
    check("added sample: 40 rows", n == 40, str(n))
    rs = (OUT / "routes-sample.md").read_text(encoding="utf-8")
    for r in ("lex", "ubs", "nt2", "rend", "lxx", "vec"):
        block = rs.split(f"## {r} ")[1].split("\n## ")[0]
        n = sum(1 for l in block.splitlines() if l.startswith("| ") and not l.startswith("| a |"))
        check(f"routes sample: 30 rows for {r}", n == 30, str(n))
    nt = json.load(open(OUT / "nt-counts.json", encoding="utf-8"))
    ch = nt["greek_words_content_linked"]["choice"]
    check("nt: same + overlap + disjoint = Greek words linked in both", sum(ch.values()) ==
          nt["greek_words_content_linked"]["both"])
    print("timings, first run:", json.dumps(t1), "second run:", json.dumps(t2))
    failed = results.count(False)
    print(f"== {results.count(True)} PASS, {failed} FAIL")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
