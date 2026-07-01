#!/usr/bin/env python3
"""Build topic_strongs.tsv: per-Nave's-topic set of Strong's codes attested in
that topic's verses — the offline half of the *topic-anchoring* branch
de-noiser (see internal-docs/roadmap.md).

At query time, concept expansion maps query words → strongs: tags but can't
tell the SUBJECT ("amor"→G0026 ágape) from interrogative FRAME words
("habla"→G2980 speak, "diferentes"→H8133). Frame codes are legitimate exact
glosses, so no Strong's *statistic* separates them. But a thematic query that
matches a Nave's topic (LOVE) gives a semantic anchor: the LOVE topic's verses
are saturated with G0026 and carry NONE of the frame codes. So we boost
expanded codes attested in the query's matched topic and demote those absent.

Building this LIVE per query is non-viable: the topic_passages × passage_refs
range-overlap join over 436k refs runs >60 s. Precompute it once here with an
in-memory bisect over the (91%-single-verse) passage_refs, then ship the TSV.

Inputs (read-only, local): indexer/index.db
  topics, topic_passages(topic_id, start_bbcccvvv, end_bbcccvvv),
  passage_refs(doc_id, start/end_bbcccvvv), tags(doc_id, 'strongs:G####')

Output: resources/topic_strongs.tsv  columns: topic_id, strong, verse_count
  verse_count = # of the topic's verses carrying that code (higher = more
  central; lets the loader drop a min-count tail of incidental codes).

Generated once locally and committed — same ship-as-TSV pattern as
strongs_freq.tsv / strongs_keyness.tsv.
"""
from __future__ import annotations

import bisect
import collections
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from resource_paths import resource_path  # noqa: E402

DB = Path(__file__).resolve().parent.parent / "indexer" / "index.db"
OUT = resource_path("topic_strongs.tsv")
MIN_COUNT = 1  # keep all; loader can threshold


def main() -> int:
    if not DB.exists():
        print(f"index.db not found: {DB}", file=sys.stderr)
        return 2
    db = sqlite3.connect(DB)

    # verse(bbcccvvv) -> {strong codes}, from single-verse strongs-tagged docs
    # (bible is per-verse; this is where the strongs: tags live). One indexed
    # scan — fast, unlike the live range-overlap join.
    verse_codes: dict[int, set[str]] = collections.defaultdict(set)
    for verse, tag in db.execute(
        "SELECT pr.start_bbcccvvv, t.tag "
        "FROM passage_refs pr "
        "JOIN tags t ON t.doc_id = pr.doc_id AND t.tag LIKE 'strongs:%' "
        "WHERE pr.start_bbcccvvv = pr.end_bbcccvvv"
    ):
        verse_codes[verse].add(tag[len("strongs:"):])
    verses = sorted(verse_codes)
    print(f"  indexed {len(verses)} verses carrying Strong's codes", flush=True)

    # topic_id -> Counter(code): for each topic passage range, union the codes
    # of the verses it spans (bisect into the sorted verse list).
    topic_codes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    n_ranges = 0
    for tid, s, e in db.execute(
        "SELECT topic_id, start_bbcccvvv, end_bbcccvvv FROM topic_passages"
    ):
        lo = bisect.bisect_left(verses, s)
        hi = bisect.bisect_right(verses, e)
        for v in verses[lo:hi]:
            for c in verse_codes[v]:
                topic_codes[tid][c] += 1
        n_ranges += 1
    print(f"  aggregated {n_ranges} topic passage ranges → {len(topic_codes)} topics", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    with OUT.open("w", encoding="utf-8") as fh:
        fh.write("topic_id\tstrong\tverse_count\n")
        for tid in sorted(topic_codes):
            for code, cnt in topic_codes[tid].most_common():
                if cnt < MIN_COUNT:
                    break
                fh.write(f"{tid}\t{code}\t{cnt}\n")
                rows += 1
    print(f"  wrote {rows} rows → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
