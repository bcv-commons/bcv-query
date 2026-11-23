"""Package word-parts v1.0 (Greek parts + Hebrew level 2, one id standard) from committed code. Nothing is uploaded.

    cd shoresh && .venv/bin/python -m macula.release_word_parts_v1 --out DIR [--allow-dirty]

Rebuilds both languages into DIR (build_greek_parts.py, build_hebrew_parts.py), checks that their parts.tsv equal the
frozen local builds that were reviewed (internal-docs/greek-parts/v1, internal-docs/word-parts-v1/hebrew), copies the hand
reviews beside them, measures Hebrew against BHSA (counts only, check_hebrew_parts_bhsa.py), maps word-parts v0.1 (route a)
onto v1.0 per language (part_id_map.py), and writes the card, build.json and one SHA256SUMS over every file.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pyarrow.parquet as pq

from macula import release_guard  # refuses TBTA and private inputs

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "internal-docs"
GREEK_FROZEN = DOCS / "greek-parts" / "v1"
HEBREW_FROZEN = DOCS / "word-parts-v1" / "hebrew"
STANDARD = DOCS / "word-parts-v1" / "ID-STANDARD.md"
SOURCES = DOCS / "greek-parts" / "sources"
V01 = DOCS / "word-parts-release" / "v0.1-a" / "data"
VERSION, SCHEMA = "v1.0", 2


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def run(*args):
    subprocess.run([sys.executable, "-m", *args], cwd=ROOT / "shoresh", check=True, stdout=subprocess.DEVNULL)


def v01_tsv(scratch: Path):
    """word-parts v0.1 route a as parts tables part_id_map.py reads (Greek by word, Hebrew by MACULA part)"""
    g = pq.read_table(V01 / "src_part_grc.parquet").to_pylist()
    with open(scratch / "v01_greek.tsv", "w", encoding="utf-8") as f:
        f.write("key\tn\ttext\tkind\n")
        f.writelines(f"{r['key']}\t{r['n']}\t{r['text']}\t{r['kind']}\n" for r in g)
    h = pq.read_table(V01 / "src_part_hbo.parquet").to_pylist()
    with open(scratch / "v01_hebrew.tsv", "w", encoding="utf-8") as f:
        f.write("part_id\tmacula_id\tn\ttext\tkind\n")
        f.writelines(f"{r['token']}\t{r['token']}\t1\t{r['text']}\t{r['kind']}\n" for r in h)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    release_guard.check(a)
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "shoresh/macula"], cwd=ROOT, text=True).strip()
    if dirty and not a.allow_dirty:
        raise SystemExit(f"uncommitted changes in shoresh/macula:\n{dirty}")
    code = subprocess.check_output(["git", "log", "-1", "--format=%h"], cwd=ROOT, text=True).strip() + ("+uncommitted" if dirty else "")
    out = a.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty; give a fresh directory")
    gr, he, scratch = out / "greek", out / "hebrew", out.parent / (out.name + ".work")
    scratch.mkdir(parents=True, exist_ok=True)

    run("macula.build_greek_parts", "--out", str(gr))
    run("macula.build_hebrew_parts", "--out", str(he), "--no-aramaic")   # v1.0: Aramaic uncut
    for lang, d, frozen in (("Greek", gr, GREEK_FROZEN), ("Hebrew", he, HEBREW_FROZEN)):
        if sha256(d / "parts.tsv") != sha256(frozen / "parts.tsv"):
            raise SystemExit(f"{lang} parts.tsv differs from the reviewed build in {frozen}")
        (d / "SHA256SUMS").unlink()
    shutil.copy(GREEK_FROZEN / "sample_200.tsv", gr / "sample_200.tsv")
    shutil.copy(GREEK_FROZEN / "sample_review.md", gr / "sample_review.md")
    (gr / "recheck").mkdir()
    for n in ("summary.md", "summary_nouns.md"):
        shutil.copy(GREEK_FROZEN / "recheck" / n, gr / "recheck" / n)
    for n in ("sample_200.tsv", "review.md"):
        shutil.copy(HEBREW_FROZEN / n, he / n)
    run("macula.check_hebrew_parts_bhsa", "--parts", str(he / "parts.tsv"), "--out", str(he / "checks_bhsa.md"))

    v01_tsv(scratch)
    churn = {}
    for lang, d, old, extra in (("greek", gr, "v01_greek.tsv", ()),
                                ("hebrew", he, "v01_hebrew.tsv", ("--extends", "--unit", "MACULA parts"))):
        run("macula.part_id_map", "--old", str(scratch / old), "--new", str(d / "parts.tsv"), "--out", str(d / "churn-from-v0.1"),
            "--title", f"word-parts v0.1 (route a) {lang} -> word-parts v1.0 {lang}", *extra)
        churn[lang] = (d / "churn-from-v0.1" / "churn.md").read_text(encoding="utf-8").splitlines()[2]
    for d in (gr, he):  # the language's build.json: the release named, the rest as built
        b = json.loads((d / "build.json").read_text(encoding="utf-8"))
        b["release"] = f"word-parts {VERSION}"
        (d / "build.json").write_text(json.dumps(b, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    shutil.copy(STANDARD, out / "ID-STANDARD.md")
    (out / "LICENSES").mkdir()
    for n in ("greek-inflexion-LICENSE", "dodson-LICENSE"):
        shutil.copy(SOURCES / n, out / "LICENSES" / n)
    gb = json.loads((gr / "build.json").read_text(encoding="utf-8"))
    hb = json.loads((he / "build.json").read_text(encoding="utf-8"))
    built = datetime.date.today().isoformat()
    (out / "build.json").write_text(json.dumps({
        "version": VERSION, "schema": SCHEMA, "built": built, "code": code, "licence": "CC BY 4.0",
        "greek": {"words": gb["words"], "parts": gb["parts"], "parts_sha256": sha256(gr / "parts.tsv")},
        "hebrew": {"macula_parts": hb["macula_parts"], "parts": hb["parts"], "parts_sha256": sha256(he / "parts.tsv"),
                   "macula_hebrew_commit": hb["macula_hebrew"]["commit"]},
        "churn_from_v0.1": churn}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    card = (ROOT / "shoresh" / "macula" / "word_parts_v1_card.md").read_text(encoding="utf-8")
    (out / "README.md").write_text(card.replace("{code}", code).replace("{built}", built)
                                   .replace("{churn_greek}", churn["greek"]).replace("{churn_hebrew}", churn["hebrew"]),
                                   encoding="utf-8")
    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (out / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.relative_to(out).as_posix()}\n" for p in files), encoding="utf-8")
    print(f"{out}: {len(files)} files, code {code}")
    for k, v in churn.items():
        print(k, v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
