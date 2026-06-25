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

BHSA_TO_USFM = {
    "Genesis": "GEN", "Exodus": "EXO", "Leviticus": "LEV", "Numbers": "NUM",
    "Deuteronomy": "DEU", "Joshua": "JOS", "Judges": "JDG", "Ruth": "RUT",
    "1_Samuel": "1SA", "2_Samuel": "2SA", "1_Kings": "1KI", "2_Kings": "2KI",
    "1_Chronicles": "1CH", "2_Chronicles": "2CH", "Ezra": "EZR",
    "Nehemiah": "NEH", "Esther": "EST", "Job": "JOB", "Psalms": "PSA",
    "Proverbs": "PRO", "Ecclesiastes": "ECC", "Song_of_songs": "SNG",
    "Isaiah": "ISA", "Jeremiah": "JER", "Lamentations": "LAM",
    "Ezekiel": "EZK", "Daniel": "DAN", "Hosea": "HOS", "Joel": "JOL",
    "Amos": "AMO", "Obadiah": "OBA", "Jonah": "JON", "Micah": "MIC",
    "Nahum": "NAM", "Habakkuk": "HAB", "Zephaniah": "ZEP", "Haggai": "HAG",
    "Zechariah": "ZEC", "Malachi": "MAL",
}


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


def build(lang: str) -> None:
    import numpy as np
    corpus = CORPUS_OF[lang]
    print(f"reading {corpus} clauses from the local corpus engine …", file=sys.stderr)
    clauses = fetch_clauses(corpus)
    print(f"embedding {len(clauses)} clauses with the {lang} model …", file=sys.stderr)

    encoder = get_encoder(lang)
    texts = [c["text"] for c in clauses]
    vecs = []
    batch = int(os.environ.get("EMBED_BATCH", "32"))
    for i in range(0, len(texts), batch):
        vecs.extend(encoder.encode(texts[i:i + batch]))
        print(f"  embedded {min(i + batch, len(texts))}/{len(texts)}", file=sys.stderr)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    vec_path = DATA_DIR / f"clauses_{lang}.npy"
    meta_path = DATA_DIR / f"clauses_{lang}.sqlite"
    np.save(vec_path, np.asarray(vecs, dtype="float32"))

    meta_path.unlink(missing_ok=True)
    db = sqlite3.connect(meta_path)
    db.execute("CREATE TABLE clauses (id INTEGER PRIMARY KEY, book TEXT, "
               "chapter INTEGER, verse INTEGER, text TEXT)")
    db.executemany(
        "INSERT INTO clauses VALUES (?,?,?,?,?)",
        [(i, BHSA_TO_USFM.get(c["book"], c["book"]),
          c["chapter"], c["verse"], c["text"])
         for i, c in enumerate(clauses)])
    db.commit()
    db.close()
    print(f"wrote {len(clauses)} clauses → {vec_path.name} + {meta_path.name} "
          f"in {DATA_DIR}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="Build the clause vector store")
    ap.add_argument("--lang", choices=list(CORPUS_OF), default="hbo")
    ap.add_argument("--embedder", choices=["cloudflare", "bge-m3-local", "berel"],
                    default=None,
                    help="Override SEARCH_EMBEDDER for this build")
    args = ap.parse_args()
    if args.embedder:
        os.environ["SEARCH_EMBEDDER"] = args.embedder
    build(args.lang)


if __name__ == "__main__":
    main()
