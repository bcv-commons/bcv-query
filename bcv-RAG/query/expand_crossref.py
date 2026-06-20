"""Strategy 5: Cross-reference snowball — follow xrefs one hop out.

After first-pass retrieval, extracts BCV passage refs from the top hits,
looks up cross-references for those passages, runs a second targeted
retrieval pass on the cross-ref targets, and merges the results.

Effect: "Explain the significance of Melchizedek" finds Genesis 14:18
in the first pass, then follows cross-refs to Psalm 110:4 and Hebrews 7
in the second pass — catching the full theological arc.

Opt-in: "expand": ["crossref"]. Cost: $0. Latency: +100-200ms.
All local (index.db), no network calls.
"""
from __future__ import annotations

import sqlite3

from query.retrieve import Hit, passage_search, rrf, _INTENT_WEIGHTS


def _passages_from_hits(
    db: sqlite3.Connection, hits: list[Hit], max_hits: int = 5
) -> list[int]:
    """Extract distinct BCV refs (start_bbcccvvv) from the top chunk hits."""
    if not hits:
        return []
    chunk_ids = [h.chunk_id for h in hits[:max_hits]]
    placeholders = ",".join("?" * len(chunk_ids))
    rows = db.execute(
        f"SELECT DISTINCT pr.start_bbcccvvv "
        f"FROM chunks c "
        f"JOIN passage_refs pr ON pr.doc_id = c.doc_id "
        f"WHERE c.id IN ({placeholders}) "
        f"AND (pr.end_bbcccvvv - pr.start_bbcccvvv) < 1000 "
        f"ORDER BY pr.start_bbcccvvv",
        chunk_ids,
    ).fetchall()
    return [r[0] for r in rows]


def _xref_targets(
    db: sqlite3.Connection, source_refs: list[int], limit: int = 20
) -> list[tuple[int, int]]:
    """Look up cross-reference targets for a set of source BCV refs."""
    if not source_refs:
        return []
    placeholders = ",".join("?" * len(source_refs))
    rows = db.execute(
        f"SELECT DISTINCT target_start_bbcccvvv, target_end_bbcccvvv "
        f"FROM cross_references "
        f"WHERE source_bbcccvvv IN ({placeholders}) "
        f"ORDER BY "
        f"  CASE source_attribution WHEN 'bsb-parallel' THEN 0 ELSE 1 END, "
        f"  (rank IS NULL), rank ASC "
        f"LIMIT ?",
        [*source_refs, limit],
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def crossref_snowball(
    db: sqlite3.Connection,
    first_pass_hits: list[Hit],
    intent: str = "thematic",
    top_k: int = 10,
) -> list[Hit]:
    """Run a second-pass retrieval on cross-ref targets of the first-pass hits."""
    source_refs = _passages_from_hits(db, first_pass_hits)
    if not source_refs:
        return []

    xref_passages = _xref_targets(db, source_refs)
    if not xref_passages:
        return []

    xref_hits = passage_search(db, xref_passages)
    if not xref_hits:
        return []

    for h in xref_hits:
        h.retrievers = ["xref_snowball"]

    weights = _INTENT_WEIGHTS.get(intent, _INTENT_WEIGHTS["thematic"])
    fused = rrf(
        [first_pass_hits, xref_hits],
        weights=[1.0, 0.6],
    )
    return fused[:top_k]
