"""Package vector track V3e + V3g as two datasets: bcv-commons/clauses-similar (Tanakh and Greek NT, within each text) and
bcv-commons/tanakh-nt-clauses-similar (Tanakh clause -> Greek NT clauses). Nothing is uploaded.

    python -m macula.release_clauses_similar --tag v0.1 --out DIR [--allow-dirty]

Runs build_clauses_similar into DIR/build, then writes DIR/clauses-similar and DIR/tanakh-nt-clauses-similar, each with data/,
checks.json, README.md, SHA256SUMS. Refuses uncommitted code unless --allow-dirty.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CODE = [HERE / "build_clauses_similar.py", HERE / "release_clauses_similar.py", HERE / "clauses_similar_card.md",
        HERE / "tanakh_nt_clauses_similar_card.md"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    import pyarrow.parquet as pq
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *map(str, CODE)], cwd=ROOT, capture_output=True, text=True).stdout
    if dirty.strip() and not a.allow_dirty:
        raise SystemExit("uncommitted changes; commit first (or --allow-dirty):\n" + dirty)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; use a new folder")
    build = a.out / "build"
    subprocess.run([sys.executable, "-m", "macula.build_clauses_similar", "--out", str(build)], cwd=HERE.parent, check=True)
    ck = json.loads((build / "checks.json").read_text())
    cr, chr_, mat = ck["cross: Salkinson verse -> Greek NT verse"], ck["within: Chronicles -> Samuel-Kings"], ck["within: Matthew -> Mark, Luke"]
    n = {f: pq.read_metadata(build / f"{f}.parquet").num_rows for f in ("hebrew", "greek-nt", "tanakh-nt")}
    top = ck["counts"]["top"]
    fill = {"@TAG@": a.tag, "@CODE@": commit + (" (dirty)" if dirty.strip() else ""), "@TOP@": str(top),
            "@MAP_PAIRS@": f"{ck['counts']['map pairs']:,}", "@CAND@": f"{cr['candidates']:,}", "@R1@": str(cr["recall@1"]),
            "@R10@": str(cr["recall@10"]), "@CHR_HIT@": str(chr_["best outside in parallel books"]),
            "@CHR_BASE@": str(chr_["their share of clauses"]), "@CHR_LIFT@": str(chr_["lift"]),
            "@MAT_HIT@": str(mat["best outside in parallel books"]), "@MAT_BASE@": str(mat["their share of clauses"]),
            "@MAT_LIFT@": str(mat["lift"]), "@HEB_ROWS@": f"{n['hebrew']:,}", "@GRC_ROWS@": f"{n['greek-nt']:,}",
            "@ROWS@": f"{n['tanakh-nt']:,}", "@HEB_CLAUSES@": f"{ck['counts']['hebrew clauses']:,}",
            "@GRC_CLAUSES@": f"{ck['counts']['greek-nt clauses']:,}", "@MED1@": str(ck["tanakh-nt score"]["median top-1"]),
            "@MED10@": str(ck["tanakh-nt score"]["median top-10"])}
    for name, card, files in (("clauses-similar", "clauses_similar_card.md", ("hebrew", "greek-nt")),
                              ("tanakh-nt-clauses-similar", "tanakh_nt_clauses_similar_card.md", ("tanakh-nt",))):
        d = a.out / name
        (d / "data").mkdir(parents=True)
        for f in files:
            shutil.copyfile(build / f"{f}.parquet", d / "data" / f"{f}.parquet")
        shutil.copyfile(build / "checks.json", d / "checks.json")
        t = (HERE / card).read_text(encoding="utf-8")
        for k, v in fill.items():
            t = t.replace(k, v)
        left = re.findall(r"@[A-Z0-9_]+@", t)
        if left:
            raise SystemExit(f"{card}: unfilled fields {left}")
        (d / "README.md").write_text(t, encoding="utf-8")
        ps = sorted(p for p in d.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
        (d / "SHA256SUMS").write_text("".join(f"{sha(p)}  {p.relative_to(d)}\n" for p in ps))
        print(d, {f: n[f] for f in files})
    print("code", fill["@CODE@"])


if __name__ == "__main__":
    main()
