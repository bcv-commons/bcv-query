#!/usr/bin/env python3
"""NC exit step 2 — tag the morphology chunks of index.db with MACULA lexeme / stem / sense (replaces tag_lex_occurrences.py, which read the BHSA hbo.db).

For each verse-level morphology chunk (Hebrew numbering, TAHOT), look up the distinct lexemes, stems and senses of the verse's MACULA tokens
(shoresh/macula/lexeme-spine-macula.db: key, book, chapter, verse, lexeme, stem; shoresh/macula/verse-senses.db: occ(key, lexeme, sense)) and add tags:
  lexeme:<id>                    e.g. lexeme:hbo:6942        → this lexeme (homographs have their own letters: hbo:0871a)
  lexemestem:<id>.<stem>         e.g. lexemestem:hbo:6942.hiphil
  lexemesense:<id>.<n>           e.g. lexemesense:hbo:6942.4  → senses are global per lexeme
  lexemestemsense:<id>.<stem>.<n>
  stem:<stem>                    any verb in that stem
Pure INSERT OR IGNOREs into the tags table: no re-chunk, no re-embed; idempotent and reversible (--revert). The old BHSA tags (lex:, lexstem:, sense:) are left in place;
remove them with `tag_lex_occurrences.py --revert` once the tool runs on the new ones.
Coverage is reported both ways (MACULA verses without a chunk, chunks without tokens): a numbering mismatch shows up there.

  python bcv-RAG/scripts/tag_lexeme_occurrences.py [path/to/index.db] [--revert] [--spine X] [--senses Y]
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
MACULA = ROOT / "shoresh" / "macula"
DEFAULT_IDX = ROOT / "bcv-RAG" / "indexer" / "index.db"
sys.path.insert(0, str(ROOT / "bcv-RAG"))
PREFIXES = ("lexeme:", "lexemestem:", "lexemesense:", "lexemestemsense:")


def verse_tags(spine: Path, senses: Path) -> dict[int, set[str]]:
    """{BBCCCVVV: {tag, ...}} from the MACULA token tables."""
    from indexer.references import encode
    con = sqlite3.connect(f"file:{spine}?mode=ro", uri=True)
    con.execute("ATTACH DATABASE ? AS vs", (f"file:{senses}?mode=ro",))
    out: dict[int, set[str]] = collections.defaultdict(set)
    for book, ch, v, lexeme, stem, sense in con.execute(
            "SELECT w.book, w.chapter, w.verse, w.lexeme, w.stem, o.sense FROM spine_words w LEFT JOIN vs.occ o ON o.key=w.key WHERE w.lexeme LIKE 'hbo:%'"):
        try:
            ref = encode(book, ch, v)
        except ValueError:
            continue
        t = out[ref]
        t.add(f"lexeme:{lexeme}")
        if stem:
            t.add(f"stem:{stem}"); t.add(f"lexemestem:{lexeme}.{stem}")
        if sense is not None:
            t.add(f"lexemesense:{lexeme}.{sense}")
            if stem:
                t.add(f"lexemestemsense:{lexeme}.{stem}.{sense}")
    con.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("index", nargs="?", default=str(DEFAULT_IDX))
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--spine", default=str(MACULA / "lexeme-spine-macula.db"))
    ap.add_argument("--senses", default=str(MACULA / "verse-senses.db"))
    a = ap.parse_args()
    idx_path = Path(a.index)
    if not idx_path.exists():
        sys.exit(f"no index: {idx_path}")
    idx = sqlite3.connect(idx_path)
    if a.revert:
        n = sum(idx.execute("DELETE FROM tags WHERE tag LIKE ?", (p + "%",)).rowcount for p in PREFIXES)
        idx.commit()
        print(f"reverted {n} lexeme tags from {idx_path.name}")
        return 0
    for f in (a.spine, a.senses):
        if not Path(f).exists():
            sys.exit(f"missing {f}")
    vt = verse_tags(Path(a.spine), Path(a.senses))
    chunks = idx.execute(
        "SELECT p.doc_id, p.start_bbcccvvv FROM passage_refs p JOIN tags t ON t.doc_id=p.doc_id AND t.tag='kind:morphology' "
        "JOIN tags l ON l.doc_id=p.doc_id AND l.tag='lang:hbo' WHERE p.start_bbcccvvv=p.end_bbcccvvv").fetchall()
    chunk_refs = {ref for _, ref in chunks}
    inserts, tagged = [], 0
    for doc_id, ref in chunks:
        tags = vt.get(ref)
        if tags:
            tagged += 1
            inserts.extend((doc_id, t) for t in tags)
    idx.executemany("INSERT OR IGNORE INTO tags(doc_id, tag) VALUES (?,?)", inserts)
    idx.commit()
    print(f"{idx_path.name}: {len(chunks)} Hebrew verse chunks; {tagged} tagged ({100*tagged/max(len(chunks),1):.1f}%), {len(inserts)} tag rows")
    only_macula = sorted(set(vt) - chunk_refs)
    print(f"MACULA verses with no chunk: {len(only_macula)} {only_macula[:5]}; chunks with no MACULA tokens: {len(chunk_refs - set(vt))} {sorted(chunk_refs - set(vt))[:5]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
