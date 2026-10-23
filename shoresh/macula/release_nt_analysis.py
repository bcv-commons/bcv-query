"""Package exported Hebrew NT analyses as a release of the dataset bcv-commons/hebrew-nt-analysis. Nothing is uploaded: the files are
written to a folder for review, and published by hand.

    python -m macula.release_nt_analysis --tag v0.1 --out DIR [--editions heb_scg] [--src macula/data/clause-tagger/export] [--allow-dirty]

DIR gets:
  README.md                  the dataset card (macula/nt_analysis_card.md with the version fields filled in)
  <edition>/words.parquet    one row per word part, from `python -m macula.clause_tagger export`
  <edition>/clauses.parquet  one row per clause segment
  <edition>/manifest.json    the text fingerprints, the model's sha256, the tokenizer and verse-text versions
  SHA256SUMS                 SHA-256 of every file

The export must come from committed code (`git status` clean for macula/clause_tagger.py, macula/vendor_bibles/, this script and the
card), unless --allow-dirty.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shutil
import subprocess
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CARD = HERE / "nt_analysis_card.md"
CODE = [HERE / "clause_tagger.py", HERE / "vendor_bibles", Path(__file__).resolve(), CARD]
EDITIONS = {"heb_scg": "Salkinson–Ginsburg Hebrew New Testament (1885/86), public domain; text from bible.helloao.org (from eBible.org, hebsg)"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--editions", default="heb_scg")
    ap.add_argument("--src", default=str(HERE / "data" / "clause-tagger" / "export"))
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    src, out = Path(a.src), Path(a.out)
    if not a.allow_dirty:
        dirty = subprocess.run(["git", "status", "--porcelain", "--", *map(str, CODE)], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        if dirty:
            raise SystemExit("uncommitted changes in the tagger's code or card; commit first (or --allow-dirty):\n" + dirty)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if out.exists():
        shutil.rmtree(out)
    files = []
    stats = {}
    import pyarrow.parquet as pq
    for ed in a.editions.split(","):
        if ed not in EDITIONS:
            raise SystemExit(f"{ed}: not an edition this card describes")
        (out / ed).mkdir(parents=True)
        for name in ("words.parquet", "clauses.parquet", "manifest.json"):
            shutil.copy(src / ed / name, out / ed / name)
            files.append(out / ed / name)
        words = pq.read_table(out / ed / "words.parquet", columns=["book", "chapter", "verse", "i", "class", "source"]).to_pylist()
        tokens = {(r["book"], r["chapter"], r["verse"], r["i"]): r for r in words if r["class"] != "verse-number"}
        stats[ed] = {"parts": len(words), "words": len(tokens), "macula": sum(r["source"] == "macula" for r in tokens.values()),
                     "segments": pq.read_metadata(out / ed / "clauses.parquet").num_rows,
                     "manifest": json.loads((out / ed / "manifest.json").read_text())}
    s = stats["heb_scg"]
    pin = tomllib.loads((HERE / "clause_layout.toml").read_text())["sources"]["macula_hebrew"]
    fields = {"@TAG@": a.tag, "@BUILT@": datetime.date.today().isoformat(), "@COMMIT@": commit,
              "@WORDS@": f"{s['words']:,}", "@PARTS@": f"{s['parts']:,}", "@SEGMENTS@": f"{s['segments']:,}",
              "@MACULA_WORDS@": f"{s['macula']:,}", "@MACULA_SHARE@": f"{s['macula'] / s['words']:.1%}",
              "@MODEL_WORDS@": f"{s['words'] - s['macula']:,}", "@MODEL_SHA@": s["manifest"]["model"]["sha256"],
              "@VERSE_TEXT@": s["manifest"]["bibles_verse_text"], "@TOKENIZER@": str(s["manifest"]["tokenizer_version"]),
              "@MACULA_COMMIT@": pin["commit"][:7]}
    card = CARD.read_text(encoding="utf-8")
    for k, v in fields.items():
        card = card.replace(k, v)
    if any(w.strip("`(),.") .startswith("@") and w.strip("`(),.").endswith("@") and len(w.strip("`(),.")) > 2 for w in card.split()):
        raise SystemExit("the card has a field that was not filled in")
    (out / "README.md").write_text(card, encoding="utf-8")
    files.append(out / "README.md")
    sums = [(hashlib.sha256(f.read_bytes()).hexdigest(), f.relative_to(out).as_posix()) for f in sorted(files)]
    (out / "SHA256SUMS").write_text("".join(f"{h}  {n}\n" for h, n in sums), encoding="utf-8")
    print(f"{out}: {len(files)} files; heb_scg {s['words']:,} words, {s['parts']:,} parts, {s['segments']:,} segments (code {commit})")


if __name__ == "__main__":
    main()
