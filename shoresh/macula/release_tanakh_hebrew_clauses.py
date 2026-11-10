"""Package the dataset bcv-commons/tanakh-hebrew-clauses: the Hebrew words of each clause segment of the Tanakh, one JSON file per chapter,
for make-tanakh-review's editor (request of 2026-11-10). Nothing is uploaded: the files are written to a folder for review.

    python -m macula.release_tanakh_hebrew_clauses --layout DIR --spine DB --out DIR [--allow-dirty]

--layout is a download of bcv-commons/hebrew-clause-layout at the revision in LAYOUT_REV (its data/clauses-<BOOK>.parquet); --spine is
lexeme-spine-macula.db from the spine release SPINE_TAG, checked against SPINE_SHA256. Only the layout's chapter, verse, seg, clause_key,
kind, rule and words are read (the CC BY 4.0 part; never `text` or the hierarchy), and from the spine only key, surface and is_content.
No English: MACULA's glosses are not carried (a reader joins them from the spine release by word key).

data/<BOOK>/<CCC>.json, per verse one entry per segment in `seg` order (an interrupted clause appears again for its later piece):
  {"format": "tanakh-hebrew-clauses/1", "book": "RUT", "chapter": 1,
   "verses": {"1": [{"key": "080010010011", "kind": "VC", "rule": "V-PP",
                     "words": [{"id": "08001001001", "surface": "וַיְהִ֗י", "content": true}, ...]}, ...]}}
  word id = the first 11 digits of the morpheme keys; surface = the morphemes' surfaces joined; content = any morpheme is a content word.
Also README.md (tanakh_hebrew_clauses_card.md filled in), build.json and SHA256SUMS.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
CARD = HERE / "tanakh_hebrew_clauses_card.md"
FORMAT = "tanakh-hebrew-clauses/1"
LAYOUT_REPO, LAYOUT_TAG, LAYOUT_REV = "bcv-commons/hebrew-clause-layout", "v0.37", "f7e58a2211973852d1fd7704dfb86ada34c82672"
SPINE_TAG = "lexeme-spine-macula-2026-10-12"
SPINE_SHA256 = "f1003a2b19036788bfc063427cb5da1e883181d39c5c87e7ccb79eb5f7bf956d"
COLUMNS = ["book", "chapter", "verse", "seg", "clause_key", "kind", "rule", "words"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--layout", type=Path, required=True)
    ap.add_argument("--spine", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()
    assert sha256(a.spine) == SPINE_SHA256, f"{a.spine} is not {SPINE_TAG}"
    spine = {k: (s, bool(c)) for k, s, c in sqlite3.connect(a.spine).execute(
        "SELECT key, surface, is_content FROM spine_words")}
    files = sorted((a.layout / "data").glob("clauses-*.parquet"))
    assert len(files) == 39, f"{len(files)} books in {a.layout / 'data'}"
    a.out.mkdir(parents=True, exist_ok=False)
    chapters, segments, words, missing = {}, 0, 0, []
    for f in files:
        rows = sorted(pq.read_table(f, columns=COLUMNS).to_pylist(), key=lambda r: (r["chapter"], r["seg"]))
        book = rows[0]["book"]
        by_ch: dict[int, dict] = {}
        for r in rows:
            ws: list[dict] = []
            for k in r["words"]:
                if k not in spine:
                    missing.append(k); continue
                s, c = spine[k]
                if ws and ws[-1]["id"] == k[:11]:
                    ws[-1]["surface"] += s; ws[-1]["content"] |= c
                else:
                    ws.append({"id": k[:11], "surface": s, "content": c})
            words += len(ws); segments += 1
            by_ch.setdefault(r["chapter"], {}).setdefault(str(r["verse"]), []).append(
                {"key": r["clause_key"], "kind": r["kind"], "rule": r["rule"], "words": ws})
        (a.out / "data" / book).mkdir(parents=True)
        for ch, verses in by_ch.items():
            doc = {"format": FORMAT, "book": book, "chapter": ch, "verses": verses}
            (a.out / "data" / book / f"{ch:03d}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        chapters[book] = len(by_ch)
    assert not missing, f"{len(missing)} layout words not in the spine, e.g. {missing[:5]}"
    ours = [str(Path(__file__).relative_to(HERE.parent)), str(CARD.relative_to(HERE.parent))]
    code = subprocess.check_output(["git", "log", "-1", "--format=%h", "--", *ours], cwd=HERE.parent, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", *ours], cwd=HERE.parent, text=True).strip()
    assert a.allow_dirty or (code and not dirty), "commit the builder and its card first (or --allow-dirty)"
    build = {"format": FORMAT, "built": datetime.date.today().isoformat(), "code": code,
             "layout": {"repo": LAYOUT_REPO, "tag": LAYOUT_TAG, "revision": LAYOUT_REV, "columns": COLUMNS[1:]},
             "spine": {"release": SPINE_TAG, "repo": "bcv-commons/spine-releases", "sha256": SPINE_SHA256, "columns": ["key", "surface", "is_content"]},
             "books": len(chapters), "chapters": sum(chapters.values()), "segments": segments, "words": words, "chapters_per_book": chapters}
    (a.out / "build.json").write_text(json.dumps(build, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    card = CARD.read_text(encoding="utf-8")
    for k, v in {"@LAYOUT_TAG@": LAYOUT_TAG, "@LAYOUT_REV@": LAYOUT_REV, "@SPINE_TAG@": SPINE_TAG, "@SPINE_SHA@": SPINE_SHA256,
                 "@BUILT@": build["built"], "@CODE@": code, "@CHAPTERS@": f"{build['chapters']:,}", "@SEGMENTS@": f"{segments:,}",
                 "@WORDS@": f"{words:,}"}.items():
        card = card.replace(k, v)
    assert "@" not in card.replace("@main", ""), "unfilled field in the card"
    (a.out / "README.md").write_text(card, encoding="utf-8")
    sums = sorted(p for p in a.out.rglob("*") if p.is_file())
    (a.out / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.relative_to(a.out)}\n" for p in sums), encoding="utf-8")
    print(f"{build['books']} books, {build['chapters']} chapters, {segments:,} segments, {words:,} words -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
