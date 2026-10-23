"""Package a built Greek NT clause layout as a release of the dataset bcv-commons/greek-nt-clause-layout. Nothing is uploaded: the
files are written to a folder for review, and published by hand.

    python -m macula.release_nt_clause_layout --tag v0.1 --out DIR [--src macula/data/nt-clause-layout] [--allow-dirty]

DIR gets:
  README.md              the dataset card (macula/nt_clause_layout_card.md with the version fields filled in)
  data/clauses.parquet   one row per line (clause segment), in text order
  layout/<BOOK>.txt      the indented reading text, one line per segment ("chapter:verse<TAB>indent text"; four spaces a level)
  build.json             the build record (copied), with the speaker data's SHA-256 added
  SHA256SUMS             SHA-256 of every file

The build must come from committed code (`git status` clean for macula/build_nt_clause_layout.py and the speaker data), unless
--allow-dirty.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CARD = HERE / "nt_clause_layout_card.md"
BUILDER = HERE / "build_nt_clause_layout.py"
SPEAKERS = ROOT / "resources" / "speaker_quotations" / "speaker_quotations.tsv"

SCHEMA = [("book", "string"), ("chapter", "int16"), ("verse", "int16"), ("seg", "int16"), ("text", "string"), ("depth", "int8"),
          ("text_depth", "int8"), ("clause", "string"), ("parent", "string"), ("kind", "string"), ("rule", "string"),
          ("role", "string"), ("via", "list<string>"), ("junction", "string"), ("sentence", "string"), ("quotation", "string"),
          ("speaker", "string"), ("inline", "list<string>"), ("split_at_quotation", "bool_"), ("first", "string"), ("last", "string"),
          ("words", "list<string>")]


def _type(pa, t: str):
    return pa.list_(pa.string()) if t == "list<string>" else getattr(pa, t)()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--src", default=str(HERE / "data" / "nt-clause-layout"))
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    src, out = Path(a.src), Path(a.out)
    if not a.allow_dirty:
        dirty = subprocess.run(["git", "status", "--porcelain", "--", str(BUILDER), str(SPEAKERS)], cwd=ROOT, capture_output=True,
                               text=True).stdout.strip()
        if dirty:
            raise SystemExit("uncommitted changes in the builder or the speaker data; commit first (or --allow-dirty):\n" + dirty)
    commit = subprocess.run(["git", "log", "-1", "--format=%h", "--", str(BUILDER)], cwd=ROOT, capture_output=True,
                            text=True).stdout.strip()
    build = json.loads((src / "build.json").read_text(encoding="utf-8"))
    if out.exists():
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    (out / "layout").mkdir()

    rows, sentence_key = [], {}

    def book_number(book: str) -> str:                       # canonical order: the book number of the first word id
        with open(sorted((src / "clauses" / book).glob("*.jsonl"))[0], encoding="utf-8") as fh:
            return json.loads(fh.readline())["first"][:2]
    books = []
    for book in sorted((p_.name for p_ in (src / "clauses").iterdir()), key=book_number):
        books.append(book)
        lines = []
        for f in sorted((src / "clauses" / book).glob("*.jsonl")):
            ch = int(f.stem.split("_")[-1])
            for line in f.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                sentence_key.setdefault(r["sentence"], r["first"])        # a sentence is named by its first word (node ids change)
                r = {"book": book, "chapter": ch, **r, "sentence": sentence_key[r["sentence"]]}
                rows.append(r)
            lines.append((src / "layout" / book / f"{f.stem}.txt").read_text(encoding="utf-8"))
        (out / "layout" / f"{book}.txt").write_text("".join(lines), encoding="utf-8")

    import pyarrow as pa
    import pyarrow.parquet as pq
    sch = pa.schema([(c, _type(pa, t)) for c, t in SCHEMA])
    table = pa.Table.from_pylist([{c: r.get(c) for c, _ in SCHEMA} for r in rows], schema=sch)
    pq.write_table(table, out / "data" / "clauses.parquet", compression="zstd")

    build["speaker_data_sha256"] = hashlib.sha256(SPEAKERS.read_bytes()).hexdigest()
    build["code_commit"] = commit
    (out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    depth = collections.Counter(r["text_depth"] for r in rows)
    fields = {"@TAG@": a.tag, "@BUILT@": datetime.date.today().isoformat(), "@COMMIT@": commit, "@LINES@": f"{len(rows):,}",
              "@CLAUSES@": f"{build['clauses']:,}", "@WORDS@": f"{build['words']:,}", "@BOOKS@": str(len(books)),
              "@IN_QUOTE@": f"{build['in_quotation']:,}", "@QUOTATIONS@": f"{build['quotations']:,}",
              "@JOINED@": str(build["quotations_joined_over_a_gap"]), "@INLINE@": str(build["inline_participles"]),
              "@SPLIT@": str(build["split_at_quotation"]), "@NO_CLAUSE@": str(build["no_clause"]),
              "@DEPTHS@": ", ".join(f"{k}: {v:,}" for k, v in sorted(depth.items())),
              "@TREES_SHA@": build["trees_db_sha256"][:12], "@SPEAKERS_SHA@": build["speaker_data_sha256"][:12]}
    card = CARD.read_text(encoding="utf-8")
    for k, v in fields.items():
        card = card.replace(k, v)
    left = [w for w in card.split() if w.strip("`(),.*").startswith("@") and w.strip("`(),.*").endswith("@") and len(w.strip("`(),.*")) > 2]
    if left:
        raise SystemExit(f"the card has fields that were not filled in: {left}")
    (out / "README.md").write_text(card, encoding="utf-8")

    files = sorted(p for p in out.rglob("*") if p.is_file())
    sums = [(hashlib.sha256(f.read_bytes()).hexdigest(), f.relative_to(out).as_posix()) for f in files]
    (out / "SHA256SUMS").write_text("".join(f"{h}  {n}\n" for h, n in sums), encoding="utf-8")
    print(f"{out}: {len(rows):,} lines, {len(books)} books, {len(files)} files (code {commit})")


if __name__ == "__main__":
    main()
