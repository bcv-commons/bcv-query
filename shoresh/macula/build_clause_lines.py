"""The clause layouts cut at poetic lines, with the share-alike facts: the CC BY-SA 4.0 editions bcv-commons/hebrew-clause-lines and
bcv-commons/greek-nt-clause-lines. Nothing is uploaded: the files are written to a folder for review.

    python -m macula.build_clause_lines --lang hbo|grc --tag v0.1 --out DIR [--allow-dirty]

Each row of the clause layout (Hebrew: macula/data/clause-layout; Greek: macula/data/nt-clause-layout) is cut where a poetic line
starts inside it. The lines come from Miqra according to the Masorah (Hebrew: the songs and the poetic lines of Psalms, Proverbs and
Job, with MAM's line-break templates) and, in verses where MAM gives none, from the unfoldingWord Literal Text (its \\q1, \\q2 lines,
placed on the Hebrew and Greek words by its own alignment). A row that no line starts inside stays as it is.

A row: every field of the layout row (the segment it is cut from), with `words`, `first`, `last` and `text` of the line, and:
  line           1, 2, ... for the pieces of one segment (1 where it is not cut)
  line_source    mam / ult where a poetic line starts at this row's first word, else null
  line_marker    that line's marker: MAM v (a line that starts the verse), r0..r4 (MAM's templates ר0..ר4); ULT q1, q2, ...
  the CC BY columns of the layout releases (macula.segment_columns), and from share-alike sources:
  notes          unfoldingWord Translation Notes on these words: tn.* codes (rhetorical question, apostrophe, parallelism, ...)
  domain         the meaning domain of the verb that introduces a speech, where it stands here: sd.* (SDBH) / ln.* (Louw-Nida)
  para_end_mam   Hebrew: sc.pe / sc.sa where a MAM paragraph (Aleppo Codex tradition) ends with this row
`text` is the line's MACULA surface text (WLC for Hebrew, Nestle 1904 for Greek). Codes: bcv-commons/passage-facts codes.tsv.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import glob
import hashlib
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

from macula import build_passage_facts as pf
from macula import segment_columns

HERE = Path(__file__).resolve().parent
CARD = HERE / "clause_lines_card.md"
SCHEMA = 1
LAYOUT = {"hbo": HERE / "data" / "clause-layout" / "clauses", "grc": HERE / "data" / "nt-clause-layout" / "clauses"}
DATASET = {"hbo": "bcv-commons/hebrew-clause-lines", "grc": "bcv-commons/greek-nt-clause-lines"}


def layout_rows(lang: str, book: str) -> list[dict]:
    rows = []
    for f in sorted(glob.glob(str(LAYOUT[lang] / book / f"{book}_*.jsonl"))):
        ch = int(Path(f).stem.split("_")[1])
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            r.setdefault("book", book)
            r.setdefault("chapter", ch)
            rows.append(r)
    return rows


def book_lines(lang: str, book: str, spans: list[dict], surf: dict) -> tuple[list[dict], collections.Counter]:
    rows = layout_rows(lang, book)
    by = segment_columns.columns(book, rows, spans)
    b = pf.Builder(book, pf.Codes())
    facts = b.build(spans)
    bk = b.bk
    stat = collections.Counter()
    # line starts: MAM first; ULT only in verses MAM gives no lines for
    starts: dict[str, tuple[str, str]] = {}
    mam_verses = set()
    for f in facts:
        if f["kind"] == "form" and f["value"] in ("fm.ms.song", "fm.ms.lines"):
            marks = f.get("markers") or ["song"] * len(f["lines"])
            for (a, _), m in zip(f["lines"], marks):
                starts[a] = ("mam", m if m != "song" else "s")
                mam_verses.add(bk.cv(a))
    for f in facts:
        if f["kind"] == "form" and "ult" in f["src"]:
            for (a, _), m in zip(f["lines"], f.get("markers") or []):
                if bk.cv(a) not in mam_verses and a not in starts:
                    starts[a] = ("ult", m)
    # share-alike facts per word
    notes, domain, mam_end = collections.defaultdict(list), {}, {}
    for f in facts:
        if f["kind"] == "note":
            notes[f["at"][0]].append(f["value"])
        elif f["kind"] == "domain":
            domain[f["first"]] = f["value"]
        elif f["kind"] == "section" and f["src"] == ["mam"]:
            mam_end[f["after"]] = f["value"]
    out = []
    for r, c in zip(rows, by):
        ws = r["words"]
        cut = [i for i, k in enumerate(ws) if i and k in starts]
        parts = [ws[a:b] for a, b in zip([0] + cut, cut + [len(ws)])]
        stat["segments"] += 1
        stat["segments cut"] += bool(cut)
        for n, part in enumerate(parts, 1):
            row = {**r, **c, "line": n, "words": part, "first": part[0], "last": part[-1],
                   "text": "".join(surf.get(k, ("", ""))[0] + (surf.get(k, ("", ""))[1] or "") for k in part).strip()}
            src_mark = starts.get(part[0])
            row["line_source"], row["line_marker"] = (src_mark if src_mark else (None, None))
            row["notes"] = sorted({v for k in part for v in notes.get(k, [])})
            row["domain"] = next((domain[k] for k in part if k in domain), None)
            if lang == "hbo":
                row["para_end_mam"] = next((mam_end[k] for k in part if k in mam_end), None)
            if n > 1 and lang == "hbo":
                row["para_end"] = c.get("para_end") if n == len(parts) else None
            elif n < len(parts) and lang == "hbo":
                row["para_end"] = None
            out.append(row)
            stat["rows"] += 1
            stat[f"line starts from {src_mark[0]}" if src_mark else "rows without a line start"] += 1
    return out, stat


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=["hbo", "grc"], required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    ours = ["macula/build_clause_lines.py", "macula/clause_lines_card.md", "macula/segment_columns.py", "macula/build_passage_facts.py",
            "macula/unfoldingword.py", "macula/mam.py", "macula/ubs.py", "../resources/passage_facts"]
    code = subprocess.check_output(["git", "log", "-1", "--format=%h", "--", *ours], cwd=HERE.parent, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", *ours], cwd=HERE.parent, text=True).strip()
    assert a.allow_dirty or (code and not dirty), "commit the builders, readers, card and resources/passage_facts first (or --allow-dirty)"
    a.out.mkdir(parents=True, exist_ok=False)
    spans = [r for r in pf._tsv(pf.SPEAKER_SPANS) if r["word_start"]]
    corpus = a.lang
    surf = {k: (s, aft) for k, s, aft in sqlite3.connect(pf.TREES).execute(
        "SELECT key, surface, after FROM words WHERE corpus=? AND inserted=0", (corpus,))}
    books = sorted((p.name for p in LAYOUT[a.lang].iterdir()), key=lambda b: layout_rows(a.lang, b)[0]["first"][:2])
    import pyarrow as pa
    import pyarrow.parquet as pq
    (a.out / "data").mkdir()
    total = collections.Counter()
    per_book = {}
    for book in books:
        rows, stat = book_lines(a.lang, book, spans, surf)
        total.update(stat)
        per_book[book] = rows
        print(book, dict(stat))
    schema = pa.Table.from_pylist([r for rows in per_book.values() for r in rows]).schema      # one schema for every book
    for book, rows in per_book.items():
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), a.out / "data" / f"lines-{book}.parquet", compression="zstd")
    for name in ("codes.tsv", "sources.tsv"):
        shutil.copy(pf.PF / name, a.out / name)
    build = {"schema": SCHEMA, "dataset": DATASET[a.lang], "tag": a.tag, "built": datetime.date.today().isoformat(), "code": code,
             "licence": "CC BY-SA 4.0", "counts": dict(total), "books": len(books),
             "inputs": {"layout": str(LAYOUT[a.lang].parent.name), "unfoldingWord": "en_ult, en_tn v91", "MAM": "MAM-basics cfdbb64e",
                        "UBS": "ubs-open-license 33dcc8c6"}}
    (a.out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    card = CARD.read_text(encoding="utf-8")
    lang_name = {"hbo": "Hebrew Bible", "grc": "Greek New Testament"}[a.lang]
    for k, v in {"@TAG@": a.tag, "@BUILT@": build["built"], "@CODE@": code or "uncommitted", "@LANG_NAME@": lang_name,
                 "@DATASET@": DATASET[a.lang], "@LAYOUT@": "bcv-commons/hebrew-clause-layout" if a.lang == "hbo" else "bcv-commons/greek-nt-clause-layout",
                 "@SEGMENTS@": f"{total['segments']:,}", "@CUT@": f"{total['segments cut']:,}", "@ROWS@": f"{total['rows']:,}",
                 "@MAM@": f"{total['line starts from mam']:,}", "@ULT@": f"{total['line starts from ult']:,}",
                 "@LANG_CODE@": "hbo" if a.lang == "hbo" else "grc"}.items():
        card = card.replace(k, v)
    assert "@" not in "".join(w for w in card.split() if w.startswith("@") and w.endswith("@")), "unfilled card field"
    (a.out / "README.md").write_text(card, encoding="utf-8")
    files = sorted(p for p in a.out.rglob("*") if p.is_file())
    (a.out / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(a.out)}\n" for p in files),
                                      encoding="utf-8")
    print(f"{a.tag}: {dict(total)} -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
