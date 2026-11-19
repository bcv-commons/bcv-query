"""Package hebrew-commentary-terms (rule rows) or hebrew-commentary-terms-model (model rows). Nothing is uploaded.

    cd shoresh && .venv/bin/python -m macula.release_commentary_terms --tag v0.1 --out DIR [--allow-dirty]
    cd shoresh && .venv/bin/python -m macula.release_commentary_terms --model --tag v0.2 --out DIR [--run DIR ...]

Rule dataset: builds macula/build_commentary_terms.py into DIR's work folder and writes data/statements.parquet,
data/terms.parquet, lists.tsv, witnesses.tsv, README.md (commentary_terms_card.md), build.json, SHA256SUMS.
Model dataset: the Metzudat Zion rows whose word only the cached model fallback anchored, plus the model reading of the Psalms
openings (macula/commentary_model.py collect): data/statements.parquet, witnesses.tsv, README.md
(commentary_terms_model_card.md), SHA256SUMS.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUNS = [HERE / ".cache" / "commentary-model" / "2026-11-18", HERE / ".cache" / "commentary-model" / "2026-11-19-midrash"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fill(card: Path, values: dict, out: Path) -> None:
    t = card.read_text(encoding="utf-8")
    for k, v in values.items():
        t = t.replace(k, str(v))
    left = re.findall(r"@[A-Z_]+@", t)
    if left:
        raise SystemExit(f"unfilled card fields: {left}")
    (out / "README.md").write_text(t, encoding="utf-8")


def sums(out: Path) -> None:
    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (out / "SHA256SUMS").write_text("".join(f"{sha(p)}  {p.relative_to(out)}\n" for p in files))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", action="store_true")
    ap.add_argument("--run", type=Path, nargs="+", default=RUNS, help="commentary_model run folders (collect done)")
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    import pyarrow as pa
    import pyarrow.parquet as pq
    from macula import build_commentary_terms as ct
    code = [HERE / "release_commentary_terms.py", HERE / "build_commentary_terms.py", HERE / "commentary_model.py",
            HERE / "hebrew_refs.py", HERE / "commentary_terms_card.md", HERE / "commentary_terms_model_card.md", ct.RES]
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *map(str, code)], cwd=ROOT, capture_output=True, text=True).stdout
    if dirty.strip() and not a.allow_dirty:
        raise SystemExit("uncommitted changes; commit first (or --allow-dirty):\n" + dirty)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    commit += " (dirty)" if dirty.strip() else ""
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; use a new folder")
    work = a.out.parent / (a.out.name + ".work")
    if work.exists():
        raise SystemExit(f"{work} exists; use a new folder")
    stats = ct.build(work)
    (a.out / "data").mkdir(parents=True)
    shutil.copy(work / "witnesses.tsv", a.out / "witnesses.tsv")
    if not a.model:
        rows = [json.loads(l) for l in (work / "statements.jsonl").open(encoding="utf-8")]
        pq.write_table(pa.Table.from_pylist(rows), a.out / "data" / "statements.parquet", compression="zstd")
        terms = []
        for line in (work / "terms.tsv").read_text(encoding="utf-8").splitlines()[1:]:
            t, n, says, strong, lists = line.split("\t")
            terms.append({"term": t, "statements": int(n), "says": says or None, "lemma_strong": strong or None,
                          "lists": lists.split("|") if lists else []})
        pq.write_table(pa.Table.from_pylist(terms), a.out / "data" / "terms.parquet", compression="zstd")
        shutil.copy(work / "lists.tsv", a.out / "lists.tsv")
        by = collections.Counter((r["witness"], r["says"]) for r in rows)
        table = "\n".join(f"| {w} | {s} | {n:,} |" for (w, s), n in sorted(by.items()))
        fill(HERE / "commentary_terms_card.md", {"@TAG@": a.tag, "@CODE@": commit, "@STATEMENTS@": f"{len(rows):,}",
                                                  "@TERMS@": f"{len(terms):,}", "@BY_WITNESS@": table,
                                                  "@PSALMS@": len({r['subject_first'][:5] for r in rows if r['says'] in ('kind', 'voice', 'occasion')})},
             a.out)
        (a.out / "build.json").write_text(json.dumps({**stats, "code": commit}, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        rows = [json.loads(l) for l in (work / "model" / "statements.jsonl").open(encoding="utf-8")]
        for r in rows:
            r["model"] = "anchor fallback (macula/anchor_llm.py)"
        prows = [json.loads(l) for run in a.run for l in (run / "statements.jsonl").open(encoding="utf-8")]
        from macula import commentary_model as cm
        for r in prows:
            r["model"] = cm.MODEL
        allrows = [{**{k: r.get(k) for k in ("id", *ct.COLUMNS)}, "model": r["model"]} for r in rows + prows]
        for i, r in enumerate(allrows, start=1):
            r["id"] = f"m{i:06d}"
        pq.write_table(pa.Table.from_pylist(allrows), a.out / "data" / "statements.parquet", compression="zstd")
        cols = [json.loads((run / "collect.json").read_text(encoding="utf-8")) for run in a.run]
        col = {k: round(sum(c.get(k, 0) for c in cols), 2) for k in ("units_answered", "usd_reported", "given")}
        col.update({k: sum(c.get(k, 0) for c in cols) for c in cols for k in c if k.startswith("dropped_")})
        by = collections.Counter((r["witness"], r["says"]) for r in prows)
        table = "\n".join(f"| {w} | {s} | {n:,} |" for (w, s), n in sorted(by.items()))
        fill(HERE / "commentary_terms_model_card.md", {
            "@TAG@": a.tag, "@CODE@": commit, "@MODEL@": cm.MODEL, "@EFFORT@": cm.EFFORT, "@UNITS@": col["units_answered"],
            "@STATEMENTS@": f"{len(prows):,}", "@ANCHOR_ROWS@": len(rows), "@BY_WITNESS@": table, "@USD@": col["usd_reported"],
            "@DROPPED@": sum(v for k, v in col.items() if k.startswith("dropped_")), "@GIVEN@": col.get("given", 0),
            "@RUN_SHA@": ", ".join(sha(run / "raw.jsonl")[:12] for run in a.run)}, a.out)
    sums(a.out)
    print(a.out, len(allrows) if a.model else len(rows), "rows; code", commit)


if __name__ == "__main__":
    main()
