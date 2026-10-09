"""Build the clause vector store — the one-off embed step.

Fetches BHSA clauses from the corpus engine, embeds them with the
original-language model (BEREL for Hebrew), and writes `clauses_<lang>.npy` +
`clauses_<lang>.sqlite` to DATA_DIR.

The Context-Fabric corpus engine is now in-process in shoresh (migration), so
this reads clauses directly from the local engine — no CORPUS_URL / network hop.
Needs the corpus volume mounted ($HOME/text-fabric-data). Run inside the shoresh
container (or any env with the engine + corpus data), then the .npy/.sqlite land
in DATA_DIR (/data):

    SHORESH_DATA=/data python3 -m search.build --lang hbo
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

from search.embedder import get_encoder
from search.store import DATA_DIR

CORPUS_OF = {"hbo": "hebrew", "grc": "greek"}


def fetch_clauses(corpus: str) -> list[dict]:
    """All clauses of a corpus, gathered book by book from the local engine."""
    from corpus_engine import engine
    clauses: list[dict] = []
    for b in engine.list_books(corpus):
        rows = engine.list_clauses(corpus, b.name)
        rows = [r for r in rows if "error" not in r]
        print(f"  {b.name}: {len(rows)} clauses", file=sys.stderr)
        clauses.extend(rows)
    return clauses


def fetch_clauses_macula(corpus: str, db: Path) -> list[dict]:
    """Clauses of the MACULA lowfat trees (trees-macula.db): the words of one clause node in reading order,
    surface + the separator that follows it. Needs no text-fabric corpus (NC exit step 5)."""
    key = {"hebrew": "hbo", "greek": "grc"}[corpus]
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute("SELECT cl, book, chapter, verse, surface, after FROM words WHERE corpus=? AND inserted=0 AND cl IS NOT NULL "
                       "ORDER BY seq", (key,))
    clauses, cur, parts, meta = [], None, [], {}
    for cl, book, ch, vs, surf, after in rows:
        if cl != cur:
            if parts:
                clauses.append({**meta, "text": "".join(parts).strip()})
            cur, parts, meta = cl, [], {"book": book, "chapter": ch, "verse": vs}
        parts.append((surf or "") + (after if after is not None else " "))
    if parts:
        clauses.append({**meta, "text": "".join(parts).strip()})
    return [c for c in clauses if c["text"]]


def build(lang: str, base: str = "bhsa", db: Path | None = None, out: Path | None = None) -> None:
    import numpy as np
    from corpus import name_to_usfm
    corpus = CORPUS_OF[lang]
    name2usfm = {} if base == "macula" else name_to_usfm(corpus)          # corpus book name -> USFM (from the one helper); MACULA rows carry USFM already
    print(f"reading {corpus} clauses from the local corpus engine …", file=sys.stderr)
    clauses = fetch_clauses_macula(corpus, db) if base == "macula" else fetch_clauses(corpus)
    print(f"embedding {len(clauses)} clauses with the {lang} model …", file=sys.stderr)

    encoder = get_encoder(lang)
    texts = [c["text"] for c in clauses]
    vecs = []
    batch = int(os.environ.get("EMBED_BATCH", "32"))
    for i in range(0, len(texts), batch):
        vecs.extend(encoder.encode(texts[i:i + batch]))
        print(f"  embedded {min(i + batch, len(texts))}/{len(texts)}", file=sys.stderr)

    data_dir = out or DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    vec_path = data_dir / f"clauses_{lang}.npy"
    meta_path = data_dir / f"clauses_{lang}.sqlite"
    np.save(vec_path, np.asarray(vecs, dtype="float32"))

    meta_path.unlink(missing_ok=True)
    db = sqlite3.connect(meta_path)
    db.execute("CREATE TABLE clauses (id INTEGER PRIMARY KEY, book TEXT, "
               "chapter INTEGER, verse INTEGER, text TEXT)")
    db.executemany(
        "INSERT INTO clauses VALUES (?,?,?,?,?)",
        [(i, name2usfm.get(c["book"], c["book"]),
          c["chapter"], c["verse"], c["text"])
         for i, c in enumerate(clauses)])
    db.commit()
    db.close()
    print(f"wrote {len(clauses)} clauses → {vec_path.name} + {meta_path.name} "
          f"in {data_dir}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="Build the clause vector store")
    ap.add_argument("--lang", choices=list(CORPUS_OF), default="hbo")
    ap.add_argument("--embedder", choices=["cloudflare", "bge-m3-local", "berel"],
                    default=None,
                    help="Override SEARCH_EMBEDDER for this build")
    ap.add_argument("--base", choices=["bhsa", "macula"], default="bhsa", help="clause source: text-fabric engine (BHSA/Nestle, non-commercial) or MACULA trees")
    ap.add_argument("--trees", type=Path, default=Path(__file__).resolve().parents[1] / "macula" / "trees-macula.db")
    ap.add_argument("--out", type=Path, default=None, help="write the vectors here instead of DATA_DIR")
    args = ap.parse_args()
    if args.embedder:
        os.environ["SEARCH_EMBEDDER"] = args.embedder
    build(args.lang, args.base, args.trees, args.out)


if __name__ == "__main__":
    main()
