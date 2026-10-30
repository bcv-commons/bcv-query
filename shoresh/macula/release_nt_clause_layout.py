"""Package a built Greek NT clause layout as a release of the dataset bcv-commons/greek-nt-clause-layout. Nothing is uploaded: the
files are written to a folder for review, and published by hand.

    python -m macula.release_nt_clause_layout --tag v0.1 --out DIR [--src macula/data/nt-clause-layout] [--allow-dirty]

DIR gets:
  README.md              the dataset card (macula/nt_clause_layout_card.md with the version fields filled in)
  data/clauses.parquet   one row per line (clause segment), in text order
  layout/<BOOK>.txt      the indented reading text, one line per segment ("chapter:verse<TAB>indent text"; four spaces a level)
  build.json             the build record (copied), with the speaker data's SHA-256 added
  crosscheck/            crosscheck.json and crosscheck-disagreements.tsv from `python -m macula.nt_layout_crosscheck` (required)
  SHA256SUMS             SHA-256 of every file

The build must come from committed code (`git status` clean for macula/build_nt_clause_layout.py, macula/greek_speakers.py, the
speaker data and its characters table), unless
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
          ("speaker", "string"), ("speaker_ref", "list<string>"), ("speaker_basis", "string"), ("alt_eng", "string"), ("speaker_id", "string"), ("speaker_name", "string"), ("speaker_name_ref", "string"), ("speaker_members", "list<string>"), ("inline", "list<string>"), ("split_at_quotation", "bool_"), ("first", "string"), ("last", "string"),
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
        dirty = subprocess.run(["git", "status", "--porcelain", "--", str(BUILDER), str(SPEAKERS), str(HERE / "greek_speakers.py"),
                                str(SPEAKERS.parent / "nt_characters.tsv"), str(SPEAKERS.parent / "nt_review.tsv")], cwd=ROOT, capture_output=True,
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

    cc = json.loads((src / "crosscheck.json").read_text(encoding="utf-8"))
    if (src / "crosscheck.json").stat().st_mtime < (src / "build.json").stat().st_mtime:
        raise SystemExit("crosscheck.json is older than the build: rerun python -m macula.nt_layout_crosscheck")
    (out / "crosscheck").mkdir()
    for name in ("crosscheck.json", "crosscheck-disagreements.tsv"):
        shutil.copy(src / name, out / "crosscheck" / name)
    names = {"MAT": "Matthew", "MRK": "Mark", "LUK": "Luke", "JHN": "John", "ACT": "Acts", "ROM": "Romans", "1CO": "1 Corinthians",
             "2CO": "2 Corinthians", "GAL": "Galatians", "EPH": "Ephesians", "PHP": "Philippians", "COL": "Colossians",
             "1TH": "1 Thessalonians", "2TH": "2 Thessalonians", "1TI": "1 Timothy", "2TI": "2 Timothy", "TIT": "Titus",
             "PHM": "Philemon", "HEB": "Hebrews", "JAS": "James", "1PE": "1 Peter", "2PE": "2 Peter", "1JN": "1 John",
             "2JN": "2 John", "3JN": "3 John", "JUD": "Jude", "REV": "Revelation"}
    book_rows = "\n".join(f"| {names.get(b, b)} | {f['pairs']:,} | {f['agree']:.1%} | {f['boundary_f1']:.1%} |"
                          for b, f in sorted(cc["books"].items(), key=lambda x: books.index(x[0])))
    depth = collections.Counter(r["text_depth"] for r in rows)
    fields = {"@TAG@": a.tag, "@BUILT@": datetime.date.today().isoformat(), "@COMMIT@": commit, "@LINES@": f"{len(rows):,}",
              "@CLAUSES@": f"{build['clauses']:,}", "@WORDS@": f"{build['words']:,}", "@BOOKS@": str(len(books)),
              "@IN_QUOTE@": f"{build['in_quotation']:,}", "@QUOTATIONS@": f"{build['quotations']:,}",
              "@JOINED@": str(build["quotations_joined_over_a_gap"]), "@INLINE@": str(build["inline_participles"]),
              "@SPLIT@": str(build["split_at_quotation"]), "@NO_CLAUSE@": str(build["no_clause"]),
              "@DEPTHS@": ", ".join(f"{k}: {v:,}" for k, v in sorted(depth.items())),
              "@TREES_SHA@": build["trees_db_sha256"][:12], "@SPEAKERS_SHA@": build["speaker_data_sha256"][:12],
              "@LOWFAT_SHA@": build["lowfat_grc_sha256"][:12], "@GREEK_SPEAKERS@": f"{build['quotations_with_greek_speaker']:,}",
              "@BY_INQUIT@": f"{build['speaker_basis'].get('inquit', 0):,}", "@ALT_ENG@": f"{build['quotations_with_alt_eng']:,}",
              "@CHARACTERS@": f"{build['characters']:,}", "@WITH_ID@": f"{build['quotations_with_character']:,}",
              "@CHAR_NAMED@": f"{build['characters_named']:,}", "@NAME_QUOTES@": f"{build['quotations_with_speaker_name']:,}", "@HAND@": str(build["characters_named_by_hand"]),
              "@GROUPS@": f"{build['groups']:,}", "@GROUP_QUOTES@": f"{build['group_quotations']:,}",
              "@WITH_MEMBERS@": f"{build['group_quotations_with_members']:,}", "@REVIEWED@": f"{build['quotations_reviewed']:,}",
              "@CC_ALIGNMENTS@": cc["alignments"], "@CC_PAIRS@": f"{cc['pairs']:,}", "@CC_AGREE@": f"{cc['agree']:.1%}",
              "@CC_P@": f"{cc['hebrew_boundary_also_greek']:.1%}", "@CC_R@": f"{cc['greek_boundary_also_hebrew']:.1%}",
              "@CC_F1@": f"{cc['boundary_f1']:.1%}", "@CC_ANALYSIS@": cc["analysis"], "@CC_BOOKS@": book_rows,
              "@CC_DISAGREE@": f"{cc['pairs'] - round(cc['agree'] * cc['pairs']):,}"}
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
