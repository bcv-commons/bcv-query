"""Package word-parts v1.1 (v1.0 with the Aramaic parts cut) from committed code. Nothing is uploaded.

    cd shoresh && .venv/bin/python -m macula.release_word_parts_v1_1 --out DIR [--allow-dirty]

The previous release is the published v1.0, downloaded from Hugging Face at its pinned commit. Rebuilds both languages into
DIR: Greek must equal v1.0's Greek (nothing changes there), Hebrew must equal the reviewed local build
(internal-docs/word-parts-v1.1/hebrew). Copies v1.0's reviews and the Aramaic review, measures Hebrew against BHSA (counts
only), maps v1.0 onto v1.1 per language (part_id_map.py), and writes the card, the id standard, build.json and SHA256SUMS.
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

from macula import release_guard  # refuses TBTA and private inputs

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "internal-docs"
HEBREW_FROZEN = DOCS / "word-parts-v1.1" / "hebrew"
STANDARD = DOCS / "word-parts-v1.1" / "ID-STANDARD.md"
PREVIOUS = ("bcv-commons/word-parts", "v1.0", "9733875e")
VERSION, SCHEMA = "v1.1", 2


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def run(*args):
    subprocess.run([sys.executable, "-m", *args], cwd=ROOT / "shoresh", check=True, stdout=subprocess.DEVNULL)


def previous(dest: Path) -> Path:
    """word-parts v1.0 at its pinned commit, every file checked against its SHA256SUMS"""
    from huggingface_hub import HfApi, snapshot_download
    repo, tag, commit = PREVIOUS
    sha = HfApi().dataset_info(repo, revision=tag).sha
    if not sha.startswith(commit):
        raise SystemExit(f"{repo} tag {tag} is {sha[:8]}, the pin says {commit}")
    got = Path(snapshot_download(repo, repo_type="dataset", revision=sha, local_dir=dest))
    for line in (got / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        h, n = line.split("  ", 1)
        if sha256(got / n) != h:
            raise SystemExit(f"{repo}@{tag}: {n} does not match its SHA256SUMS")
    return got


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
    prev = previous(scratch / "v1.0")

    run("macula.build_greek_parts", "--out", str(gr))
    run("macula.build_hebrew_parts", "--out", str(he))   # Aramaic cut
    for lang, d, ref in (("Greek", gr, prev / "greek"), ("Hebrew", he, HEBREW_FROZEN)):
        if sha256(d / "parts.tsv") != sha256(ref / "parts.tsv"):
            raise SystemExit(f"{lang} parts.tsv differs from {ref}")
        (d / "SHA256SUMS").unlink()
    for n in ("sample_200.tsv", "sample_review.md", "recheck/summary.md", "recheck/summary_nouns.md"):
        (gr / n).parent.mkdir(exist_ok=True)
        shutil.copy(prev / "greek" / n, gr / n)
    for n in ("sample_200.tsv", "review.md"):
        shutil.copy(prev / "hebrew" / n, he / n)
    for n in ("sample_aramaic_60.tsv", "review_aramaic.md"):
        shutil.copy(HEBREW_FROZEN / n, he / n)
    run("macula.check_hebrew_parts_bhsa", "--parts", str(he / "parts.tsv"), "--out", str(he / "checks_bhsa.md"))

    churn = {}
    for lang, d in (("greek", gr), ("hebrew", he)):
        run("macula.part_id_map", "--old", str(prev / lang / "parts.tsv"), "--new", str(d / "parts.tsv"),
            "--out", str(d / "churn-from-v1.0"), "--title", f"word-parts v1.0 {lang} -> word-parts {VERSION} {lang}",
            *(("--unit", "MACULA parts") if lang == "hebrew" else ()))
        churn[lang] = (d / "churn-from-v1.0" / "churn.md").read_text(encoding="utf-8").splitlines()[2]
    for d in (gr, he):
        b = json.loads((d / "build.json").read_text(encoding="utf-8"))
        b["release"] = f"word-parts {VERSION}"
        (d / "build.json").write_text(json.dumps(b, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    std = STANDARD.read_text(encoding="utf-8").replace("{churn_hebrew}", churn["hebrew"])
    (out / "ID-STANDARD.md").write_text(std, encoding="utf-8")
    shutil.copytree(prev / "LICENSES", out / "LICENSES")
    gb = json.loads((gr / "build.json").read_text(encoding="utf-8"))
    hb = json.loads((he / "build.json").read_text(encoding="utf-8"))
    built = datetime.date.today().isoformat()
    (out / "build.json").write_text(json.dumps({
        "version": VERSION, "schema": SCHEMA, "built": built, "code": code, "licence": "CC BY 4.0",
        "previous": {"repo": PREVIOUS[0], "tag": PREVIOUS[1], "commit": PREVIOUS[2]},
        "greek": {"words": gb["words"], "parts": gb["parts"], "parts_sha256": sha256(gr / "parts.tsv")},
        "hebrew": {"macula_parts": hb["macula_parts"], "parts": hb["parts"], "parts_sha256": sha256(he / "parts.tsv"),
                   "macula_hebrew_commit": hb["macula_hebrew"]["commit"]},
        "churn_from_v1.0": churn}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    card = (ROOT / "shoresh" / "macula" / "word_parts_v1_1_card.md").read_text(encoding="utf-8")
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
