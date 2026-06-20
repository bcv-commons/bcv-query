"""Build an English-word → verse-list concordance from ingested BSB chunks.

  python -m ingest.english_concordance

Walks every chunk tagged `kind:bible` + `resource:bsb`, tokenizes the
body, filters stopwords + short tokens, and writes (word, bbcccvvv)
rows into the `english_concordance` table.

Use case: stage-3 MCP tool for exhaustive "every occurrence of <word>"
lookups. FTS5 over `chunks_fts_bible` covers ranked-keyword search;
this table covers the *complete listing* use case where porter
stemming and BM25 ordering would obscure the answer.

Pure SQL — no network, no external sources. Pre-requisite: `ingest.bsb`
must have run + `indexer.build` must have absorbed BSB chunks into
the `chunks` + `passage_refs` tables.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

from indexer.build import init_schema
from indexer.db import open_db
from indexer.env import load_env

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "indexer" / "index.db"

# A small English stopword set. Kept short on purpose — being too aggressive
# strips theologically-meaningful "lord"/"god"/"father" or words that legitimately
# concord ("not", "all", "many"). The goal is just to drop articles, pronouns,
# auxiliaries, prepositions and conjunctions where word-level frequency is
# pure noise.
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "had", "has", "have", "he", "her", "him", "his", "i", "if", "in", "into",
    "is", "it", "its", "me", "my", "of", "on", "or", "our", "she", "so",
    "that", "the", "their", "them", "then", "they", "this", "those", "to",
    "us", "was", "we", "were", "what", "when", "where", "which", "who",
    "will", "with", "would", "you", "your", "yours", "yourself",
    # BSB-specific markers, not English words.
    "vvv",  # marker for omitted/uncertain text in some BSB renderings
})

_TOKEN_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")  # simple word tokenizer; allows contractions


def tokenize(body: str) -> set[str]:
    """Return the set of unique normalized tokens in `body`, with stopwords + short
    tokens (<3 chars) filtered out."""
    out: set[str] = set()
    for m in _TOKEN_RE.findall(body):
        w = m.lower()
        if len(w) < 3 or w in _STOPWORDS:
            continue
        out.add(w)
    return out


def build(db) -> dict:
    counts = {"verses_processed": 0, "rows_inserted": 0, "unique_words": 0, "skipped_no_passage": 0}

    db.execute("DELETE FROM english_concordance")
    db.commit()

    rows = db.execute(
        """
        SELECT chunks.id, chunks.body, passage_refs.start_bbcccvvv
        FROM chunks
        JOIN tags ON tags.doc_id = chunks.doc_id AND tags.tag = 'kind:bible'
        JOIN tags r ON r.doc_id = chunks.doc_id AND r.tag = 'resource:bsb'
        LEFT JOIN passage_refs ON passage_refs.doc_id = chunks.doc_id
        """
    ).fetchall()

    insert_buffer: list[tuple[str, int]] = []
    word_freq: Counter[str] = Counter()

    for chunk_id, body, bb in rows:
        if bb is None:
            counts["skipped_no_passage"] += 1
            continue
        counts["verses_processed"] += 1
        for tok in tokenize(body):
            insert_buffer.append((tok, bb))
            word_freq[tok] += 1
            if len(insert_buffer) >= 5000:
                db.executemany(
                    "INSERT OR IGNORE INTO english_concordance(word_normalized, bbcccvvv) VALUES (?, ?)",
                    insert_buffer,
                )
                counts["rows_inserted"] += len(insert_buffer)
                insert_buffer = []

    if insert_buffer:
        db.executemany(
            "INSERT OR IGNORE INTO english_concordance(word_normalized, bbcccvvv) VALUES (?, ?)",
            insert_buffer,
        )
        counts["rows_inserted"] += len(insert_buffer)

    db.commit()

    counts["unique_words"] = len(word_freq)
    counts["top_5_words"] = word_freq.most_common(5)
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()
    load_env()

    started = time.time()
    db = open_db(args.db)
    init_schema(db)

    # Sanity: BSB chunks must exist.
    bsb_count = db.execute(
        "SELECT COUNT(DISTINCT doc_id) FROM tags WHERE tag = 'resource:bsb'"
    ).fetchone()[0]
    if bsb_count == 0:
        print("no BSB chunks found — run `python -m ingest.bsb && python -m indexer.build --source ingest/_staging` first",
              file=sys.stderr)
        return 2

    print(f"building concordance from {bsb_count} BSB documents", flush=True)
    counts = build(db)
    db.close()

    print(json.dumps({
        "elapsed_seconds": round(time.time() - started, 2),
        **counts,
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
