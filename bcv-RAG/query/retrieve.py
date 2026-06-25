"""Hybrid retrieval — FTS5 + passage + tag + (v2) vector ANN, fused via RRF.

Vector retrieval is OPTIONAL: if sqlite-vec isn't loaded or no `query_vec`
is supplied, the v1 retrievers still run on their own.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from threading import Lock

import httpx

from .analyzer import QueryAnalysis
from lang import canon, to_web

logger = logging.getLogger(__name__)

CORPUS_URL = os.environ.get("CORPUS_URL", "").rstrip("/")  # legacy; local engine preferred


@dataclass
class Hit:
    chunk_id: str
    score: float
    retrievers: list[str]


# ---------- candidate filtering ----------
# Only passages act as a HARD filter on the candidate set. Tags are treated
# as ranking BOOSTS (via tag_search → RRF) — that way an analyzer mis-guess
# can never exclude relevant content; it just doesn't help.

def _docs_overlapping_passages(db: sqlite3.Connection, passages: list[tuple[int, int]]) -> set[str] | None:
    """Set of doc_ids whose passage ranges overlap any of `passages`. None = no filter."""
    if not passages:
        return None
    where = " OR ".join("(start_bbcccvvv <= ? AND end_bbcccvvv >= ?)" for _ in passages)
    params: list[int] = []
    for s, e in passages:
        params.extend([e, s])  # query end >= ref.start AND query start <= ref.end
    rows = db.execute(f"SELECT DISTINCT doc_id FROM passage_refs WHERE {where}", params).fetchall()
    return {r[0] for r in rows}


def _docs_by_source(db: sqlite3.Connection, source: str | None) -> set[str] | None:
    """Restrict candidate docs to one source. None / 'all' = no filter.

    'door43'  = chunks NOT carrying `resource:aquifer`
    'aquifer' = chunks carrying `resource:aquifer`
    """
    if not source or source == "all":
        return None
    if source == "aquifer":
        rows = db.execute(
            "SELECT DISTINCT doc_id FROM tags WHERE tag = 'resource:aquifer'"
        ).fetchall()
        return {r[0] for r in rows}
    if source == "door43":
        rows = db.execute(
            "SELECT id FROM documents "
            "WHERE id NOT IN (SELECT doc_id FROM tags WHERE tag = 'resource:aquifer')"
        ).fetchall()
        return {r[0] for r in rows}
    raise ValueError(f"unknown source filter: {source!r} (expected 'door43', 'aquifer', or 'all')")


def _intersect_filters(*filters: set[str] | None) -> set[str] | None:
    """Intersect multiple optional doc-id filters. None means 'no constraint'."""
    out: set[str] | None = None
    for f in filters:
        if f is None:
            continue
        out = f if out is None else (out & f)
    return out


# v2 content taxonomy — the kinds existing retrievers know how to rank
# against. Defense-in-depth filter: v3 expansion content (lexicons,
# morphology, …) is already excluded from `chunks_fts` by the per-kind
# FTS routing in `indexer.build` (see schema.sql + V3_KIND_TO_FTS), so
# fts_search is naturally clean. This filter remains useful for:
#   - title_search (documents_fts is not yet partitioned per kind, so v3
#     doc titles can still leak via title-FTS — e.g., a lexicon entry's
#     "LSJ — ἀγάπη …" title matching a stemmed English keyword)
#   - vector_search once stage 3 embeds v3 content
# TODO(stage-3): drop this gate when intent-routed retrievers land.
_V2_KIND_TAGS: tuple[str, ...] = (
    "kind:scripture", "kind:translator-note", "kind:question",
    "kind:term", "kind:methodology", "kind:study-note",
    "kind:book-intro", "kind:map", "kind:image",
    # Section headings & full-Bible BSB are v3 expansion content; stage-3
    # retrievers will reach them via chunks_fts_section_heading and
    # chunks_fts_bible respectively.
)


_V2_SUBQUERY = (
    "SELECT DISTINCT doc_id FROM tags WHERE tag IN ("
    + ",".join(f"'{t}'" for t in _V2_KIND_TAGS)
    + ") AND doc_id NOT IN (SELECT doc_id FROM tags WHERE tag='resource:aquifer')"
)


def _docs_v2_only(db: sqlite3.Connection) -> set[str]:
    """Doc-ids tagged with a v2 taxonomy `kind:*` value, EXCLUDING Aquifer.

    Aquifer shares v2 kinds (study-note/term/question/…) but is isolated to its
    own retriever (aquifer_search) — subtract it here so its large multilingual
    corpus never enters the primary fts/title/passage/vec retrievers (which all
    intersect this set as their doc_filter). Without this it leaks via every
    generic retriever and crowds out Door43 primary content.

    NOTE: callers that pass this set to fts_search/title_search must use
    _V2_SUBQUERY instead to avoid the SQLite 999-variable limit — see
    _gather_hits() which intercepts those two retrievers specially.
    """
    try:
        rows = db.execute(_V2_SUBQUERY).fetchall()
        return {r[0] for r in rows}
    except sqlite3.OperationalError:
        return set()


# ---------- retrievers ----------

def fts_search(db: sqlite3.Connection, query: str, *,
               doc_filter: set[str] | None = None,
               doc_subquery: str | None = None,
               kind_tag: str | None = None,
               limit: int = 50) -> list[Hit]:
    """FTS5 match on chunks_fts, optionally constrained to a doc_id whitelist.

    Prefer doc_subquery (a SQL subquery string) over doc_filter (a Python set)
    when the candidate set is large — IN (?, ...) hits SQLite's 999-variable
    limit on sets > 999 ids.

    kind_tag: add an EXISTS filter on the tags table for a single kind tag.
    More efficient than doc_filter/doc_subquery for uniform kind restrictions
    (e.g. 'kind:scripture') because it probes the (tag, doc_id) index once per
    FTS hit rather than materializing the full set.
    """
    if not query.strip():
        return []
    sql = (
        "SELECT chunks.id, rank "
        "FROM chunks_fts "
        "JOIN chunks ON chunks_fts.rowid = chunks.rowid "
        "WHERE chunks_fts MATCH ?"
    )
    params: list = [query]
    if kind_tag is not None:
        sql += " AND EXISTS (SELECT 1 FROM tags WHERE doc_id = chunks.doc_id AND tag = ?)"
        params.append(kind_tag)
    if doc_subquery is not None:
        sql += f" AND chunks.doc_id IN ({doc_subquery})"
    elif doc_filter is not None:
        if not doc_filter:
            return []
        placeholders = ",".join("?" * len(doc_filter))
        sql += f" AND chunks.doc_id IN ({placeholders})"
        params.extend(doc_filter)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    try:
        rows = db.execute(sql, params).fetchall()
    except sqlite3.OperationalError as e:
        # FTS5 syntax errors (e.g. user query contains reserved chars) — degrade gracefully.
        print(f"fts_search: skipping due to {e!r}", flush=True)
        return []
    # FTS5 rank: lower is better; negate so larger = better for downstream UX.
    return [Hit(chunk_id=r[0], score=-float(r[1]), retrievers=["fts"]) for r in rows]


_PASSAGE_MAX_WIDTH = 3000   # ~3 chapters; wider docs are not "about" a verse
_PASSAGE_WIDTH_SCORE_CAP = 500  # width ≤ this gets full specificity credit


def passage_search(db: sqlite3.Connection, passages: list[tuple[int, int]], *,
                   doc_filter: set[str] | None = None, limit: int = 50) -> list[Hit]:
    """One Hit per overlapping doc — chunk_index=0 is the canonical chunk.

    Excludes kind:bible (handled by bible_search) and kind:morphology (handled
    by morphology_search) via NOT EXISTS rather than a large IN (doc_ids).

    Excludes docs whose passage range is wider than _PASSAGE_MAX_WIDTH — Bible-
    spanning TA articles and video transcripts overlap every verse but add noise
    for specific verse queries. Scores by passage specificity (narrower = higher)
    so a verse-level note outranks a chapter-level note in RRF fusion.
    """
    if not passages:
        return []
    where = " OR ".join("(passage_refs.start_bbcccvvv <= ? AND passage_refs.end_bbcccvvv >= ?)" for _ in passages)
    params: list = []
    for s, e in passages:
        params.extend([e, s])
    sql = (
        "SELECT DISTINCT chunks.id, "
        "  passage_refs.end_bbcccvvv - passage_refs.start_bbcccvvv AS width "
        "FROM passage_refs "
        "JOIN chunks ON chunks.doc_id = passage_refs.doc_id AND chunks.chunk_index = 0 "
        f"WHERE ({where}) "
        f"AND (passage_refs.end_bbcccvvv - passage_refs.start_bbcccvvv) <= {_PASSAGE_MAX_WIDTH} "
        "AND NOT EXISTS (SELECT 1 FROM tags WHERE doc_id = chunks.doc_id AND tag = 'kind:bible') "
        "AND NOT EXISTS (SELECT 1 FROM tags WHERE doc_id = chunks.doc_id AND tag = 'kind:morphology')"
    )
    if doc_filter is not None:
        if not doc_filter:
            return []
        placeholders = ",".join("?" * len(doc_filter))
        sql += f" AND chunks.doc_id IN ({placeholders})"
        params.extend(doc_filter)
    sql += " ORDER BY width LIMIT ?"
    params.append(limit)
    rows = db.execute(sql, params).fetchall()
    # Score: narrower passage = higher specificity. Width 0 (exact verse) → 1.0;
    # width at cap → 0.5; linear interpolation.
    return [
        Hit(chunk_id=r[0],
            score=1.0 - 0.5 * min(r[1], _PASSAGE_WIDTH_SCORE_CAP) / _PASSAGE_WIDTH_SCORE_CAP,
            retrievers=["passage"])
        for r in rows
    ]


def _overlaps_any(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    """True if [start,end] overlaps any range in the sorted list."""
    import bisect
    # ranges sorted by start; find the last range starting <= end, walk back a few
    i = bisect.bisect_right(ranges, (end, 10**12))
    for s, e in reversed(ranges[:i]):
        if e >= start:
            return True
        if e < start and s < start - 999_000:   # ranges are sorted by start; once
            break                                # starts fall far below, stop
    return False


def speaker_search(db: sqlite3.Connection, *, speaker: str | None, fts_query: str,
                   limit: int = 40) -> list[Hit]:
    """S1 — Bible verses spoken by `speaker`, intersected with the topic.

    "What did Jesus say about faith" = verses within Jesus's quotation ranges
    (resources/speaker_quotations) that also match the topic FTS. With no topic,
    returns the speaker's verses in canonical order (the whole red-letter set).
    """
    if not speaker:
        return []
    from query import speakers as speakers_mod
    ranges = sorted(speakers_mod.speaker_passages(speaker))
    if not ranges:
        return []

    if fts_query.strip():
        rows = db.execute(
            "SELECT chunks.id, passage_refs.start_bbcccvvv, passage_refs.end_bbcccvvv "
            "FROM chunks_fts_bible "
            "JOIN chunks ON chunks.rowid = chunks_fts_bible.rowid "
            "JOIN passage_refs ON passage_refs.doc_id = chunks.doc_id "
            "WHERE chunks_fts_bible MATCH ? "
            "ORDER BY rank LIMIT 3000",
            (fts_query,),
        ).fetchall()
    else:
        # whole speech: bible verses overlapping any speaker range (capped)
        where = " OR ".join("(passage_refs.start_bbcccvvv <= ? AND passage_refs.end_bbcccvvv >= ?)"
                            for _ in ranges[:400])
        params: list = []
        for s, e in ranges[:400]:
            params.extend([e, s])
        rows = db.execute(
            "SELECT chunks.id, passage_refs.start_bbcccvvv, passage_refs.end_bbcccvvv "
            "FROM passage_refs JOIN chunks ON chunks.doc_id = passage_refs.doc_id "
            "AND chunks.chunk_index = 0 "
            "WHERE EXISTS (SELECT 1 FROM tags WHERE doc_id = chunks.doc_id AND tag = 'kind:bible') "
            f"AND ({where}) ORDER BY passage_refs.start_bbcccvvv LIMIT ?",
            [*params, limit],
        ).fetchall()
        return [Hit(chunk_id=r[0], score=1.0 - i / max(1, len(rows)), retrievers=["speaker"])
                for i, r in enumerate(rows)]

    hits: list[str] = []
    for cid, s, e in rows:
        if _overlaps_any(s, e, ranges):
            hits.append(cid)
            if len(hits) >= limit:
                break
    return [Hit(chunk_id=cid, score=1.0 - i / max(1, len(hits)), retrievers=["speaker"])
            for i, cid in enumerate(hits)]


def scripture_search(
    db: sqlite3.Connection,
    passages: list[tuple[int, int]],
    query_vec: list[float] | None,
    *,
    fts_query: str = "",
    limit: int = 25,
) -> list[Hit]:
    """Two-pass `kind:scripture` retrieval within the passage filter.

    Pass 1 — vec-rank scripture chunks (when query_vec available).
    Pass 2 — FTS5 rank scripture chunks against `fts_query` (when present).

    Both passes feed RRF, so a verse that matches FTS keywords ("must be
    blameless") OR is semantically close to the question ranks well even
    when the embedding alone misses it. Without this dual signal, vec
    ranking with text-embedding-3-small often prefers greeting/closing
    verses over the actual answer-bearing verses on thematic questions.

    Why this exists: when a passage filter is active, the actual verse text
    is often the highest-value content — but commentary uses the user's
    vocabulary directly while verses use biblical vocabulary, so naive
    full-corpus retrieval lets commentary push scripture below top-K. This
    retriever contributes an INDEPENDENT scripture-only ranking that RRF
    then folds in alongside the general retrievers.
    """
    if not query_vec and not fts_query.strip():
        return []
    # Without passages or semantic, fts_search (main index) + bible_search
    # already cover scripture FTS. scripture_search adds unique signal only
    # when a passage filter is active (focused on specific verses) or when
    # query_vec is set (scripture-only vector ranking outranks commentary).
    if not query_vec and not passages:
        return []

    # Build the scripture doc-id filter. With explicit passages, restrict to
    # docs overlapping them; without passages (thematic queries), restrict to
    # ALL `kind:scripture` docs so vec/FTS still get a scripture-only ranking
    # to RRF in. Without this fallback, thematic queries got their scripture
    # chunks displaced once Voyage's higher-confidence vec started ranking
    # commentary/study-notes above raw verse text.
    _scripture_subquery = "SELECT DISTINCT doc_id FROM tags WHERE tag = 'kind:scripture'"

    out: list[Hit] = []
    if passages:
        where_passage = " OR ".join(
            "(passage_refs.start_bbcccvvv <= ? AND passage_refs.end_bbcccvvv >= ?)"
            for _ in passages
        )
        params: list = []
        for s, e in passages:
            params.extend([e, s])
        rows = db.execute(
            f"""
            SELECT DISTINCT passage_refs.doc_id
            FROM passage_refs
            JOIN tags ON tags.doc_id = passage_refs.doc_id AND tags.tag = 'kind:scripture'
            WHERE {where_passage}
            """,
            params,
        ).fetchall()
        scripture_doc_ids: set[str] | None = {r[0] for r in rows}
        if not scripture_doc_ids:
            return []
        # Passage filter is small enough for IN clause.
        doc_kw: dict = {"doc_filter": scripture_doc_ids}
    else:
        # No passages → all kind:scripture docs. Use EXISTS via kind_tag to
        # avoid materializing 148k IDs (would exceed SQLite's 999-var IN limit
        # and also requires a full tags scan to build the set).
        scripture_doc_ids = None

    # Pass 1 — vec-ranked scripture (broader limit; RRF handles dedup).
    if query_vec:
        vec_filter = scripture_doc_ids or set(
            r[0] for r in db.execute(_scripture_subquery).fetchall()
        )
        for h in vector_search(db, query_vec, doc_filter=vec_filter, limit=limit):
            out.append(Hit(chunk_id=h.chunk_id, score=h.score, retrievers=["scripture"]))
    # Pass 2 — FTS5-ranked scripture.
    if fts_query.strip():
        fts_kw: dict = (
            {"doc_filter": scripture_doc_ids} if scripture_doc_ids is not None
            else {"kind_tag": "kind:scripture"}
        )
        for h in fts_search(db, fts_query, **fts_kw, limit=limit):
            out.append(Hit(chunk_id=h.chunk_id, score=h.score, retrievers=["scripture"]))
    return out


_V3_KIND_TAGS: tuple[str, ...] = (
    "kind:lexicon", "kind:morphology", "kind:section-heading", "kind:bible",
    "kind:video-transcript",
)
_V3_EXCLUSION_SQL = (
    "SELECT 1 FROM tags _x WHERE _x.doc_id = documents.id AND _x.tag IN ("
    + ",".join(f"'{t}'" for t in _V3_KIND_TAGS)
    + ")"
)


def title_search(
    db: sqlite3.Connection,
    query: str,
    *,
    doc_filter: set[str] | None = None,
    doc_subquery: str | None = None,
    limit: int = 20,
) -> list[Hit]:
    """FTS5 over document titles — pinpoint hits for entity / term lookups.

    Why: chunk-body FTS saturates with noise on entity questions (every
    narrative passage with the entity's name competes). Title FTS is
    discriminative: TW articles, book intros, and named verses get titles
    like "TW — Boaz" / "Aquifer — Titus 1:1" that pin the entity hit.

    v3 content (lexicon, morphology, bible, …) is excluded via NOT EXISTS
    rather than an IN (ids) clause — the candidate set is too large for
    SQLite's 999-variable limit now that the index has 1M+ documents.
    """
    if not query.strip():
        return []
    sql = (
        "SELECT documents.id "
        "FROM documents_fts "
        "JOIN documents ON documents_fts.rowid = documents.rowid "
        f"WHERE documents_fts MATCH ? AND NOT EXISTS ({_V3_EXCLUSION_SQL})"
    )
    params: list = [query]
    if doc_subquery is not None:
        sql += f" AND documents.id IN ({doc_subquery})"
    elif doc_filter is not None:
        if not doc_filter:
            return []
        placeholders = ",".join("?" * len(doc_filter))
        sql += f" AND documents.id IN ({placeholders})"
        params.extend(doc_filter)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    try:
        doc_rows = db.execute(sql, params).fetchall()
    except sqlite3.OperationalError as e:
        # FTS5 syntax errors on user input — degrade gracefully.
        print(f"title_search: skipping due to {e!r}", flush=True)
        return []
    if not doc_rows:
        return []

    # Map matching doc_ids → their canonical (chunk_index=0) chunks.
    doc_ids = [r[0] for r in doc_rows]
    placeholders = ",".join("?" * len(doc_ids))
    chunk_rows = db.execute(
        f"SELECT id, doc_id FROM chunks WHERE doc_id IN ({placeholders}) AND chunk_index = 0",
        doc_ids,
    ).fetchall()
    chunk_by_doc = {r[1]: r[0] for r in chunk_rows}
    n = len(doc_ids)
    hits: list[Hit] = []
    for i, did in enumerate(doc_ids):
        chunk_id = chunk_by_doc.get(did)
        if chunk_id:
            hits.append(Hit(chunk_id=chunk_id, score=1.0 - i / max(1, n), retrievers=["title"]))
    return hits


def vector_search(
    db: sqlite3.Connection,
    query_vec: list[float] | None,
    *,
    doc_filter: set[str] | None = None,
    limit: int = 50,
    overfetch: int = 4,
) -> list[Hit]:
    """KNN over chunks_vec using sqlite-vec. Returns [] if vec unavailable."""
    if not query_vec:
        return []
    try:
        # Existence check — fails fast if chunks_vec isn't there or sqlite-vec isn't loaded.
        db.execute("SELECT count(*) FROM chunks_vec LIMIT 1")
    except sqlite3.OperationalError:
        return []

    from indexer.embed import serialize_vector  # lazy: avoids importing on v1-only paths

    qvec = serialize_vector(query_vec)
    # sqlite-vec rejects LIMIT alongside `k = ?` on its virtual tables.
    # Use `k` to bound the ANN scan; clamp client-side after fetch.
    k = max(limit * overfetch, limit)
    try:
        if doc_filter is None:
            rows = db.execute(
                "SELECT chunk_id, distance FROM chunks_vec "
                "WHERE embedding MATCH ? AND k = ? "
                "ORDER BY distance",
                (qvec, limit),
            ).fetchall()
        else:
            if not doc_filter:
                return []
            placeholders = ",".join("?" * len(doc_filter))
            # Outer SELECT can use LIMIT freely — only the chunks_vec MATCH is restricted.
            rows = db.execute(
                f"""
                WITH knn AS (
                    SELECT chunk_id, distance
                    FROM chunks_vec
                    WHERE embedding MATCH ? AND k = ?
                )
                SELECT knn.chunk_id, knn.distance
                FROM knn
                JOIN chunks ON chunks.id = knn.chunk_id
                WHERE chunks.doc_id IN ({placeholders})
                ORDER BY knn.distance
                LIMIT ?
                """,
                [qvec, k, *doc_filter, limit],
            ).fetchall()
    except sqlite3.OperationalError as e:
        print(f"vector_search: skipping due to {e!r}", flush=True)
        return []

    # cosine distance — lower is closer; negate so larger == more relevant.
    return [Hit(chunk_id=r[0], score=-float(r[1]), retrievers=["vec"]) for r in rows]


def tag_search(db: sqlite3.Connection, tags: list[str], *, limit: int = 50) -> list[Hit]:
    if not tags:
        return []
    placeholders = ",".join("?" * len(tags))
    # Aquifer is reachable ONLY via aquifer_search (its own FTS + tuned weight).
    # Exclude it here so its book:/acai: tags don't leak it into primary tag
    # retrieval and crowd out Door43 notes (it has no Strong's tags anyway).
    sql = (
        "SELECT DISTINCT chunks.id "
        "FROM tags "
        "JOIN chunks ON chunks.doc_id = tags.doc_id AND chunks.chunk_index = 0 "
        f"WHERE tags.tag IN ({placeholders}) "
        "AND NOT EXISTS (SELECT 1 FROM tags ax WHERE ax.doc_id = chunks.doc_id AND ax.tag = 'resource:aquifer') "
        "LIMIT ?"
    )
    params = list(tags) + [limit]
    rows = db.execute(sql, params).fetchall()
    n = len(rows)
    return [Hit(chunk_id=r[0], score=1.0 - i / max(1, n), retrievers=["tag"]) for i, r in enumerate(rows)]


# ---------- v3 retrievers (stage-3) ----------
# These target the per-kind FTS tables and the entity/topic/xref auxiliary
# tables populated in stage 2. Unlike the v2 retrievers, they ignore the
# `v2_filter` — they explicitly seek out v3 expansion content. They return
# empty lists when their structured inputs (Strong's tags, entity_query,
# topic name, etc.) aren't populated by the analyzer, so it's safe to always
# call them; intent-weighted RRF handles whether their hits surface.

def _strongs_lemma_filter(tags: list[str]) -> tuple[list[str], list[str]]:
    """Split analyzer-extracted tags into Strong's vs lemma subsets."""
    strongs = [t for t in tags if t.startswith("strongs:")]
    lemmas = [t for t in tags if t.startswith("lemma:")]
    return strongs, lemmas


_lexicon_strongs_cache: dict[str, list[str]] | None = None  # strongs_tag → [chunk_id, ...]
_lexicon_cache_lock = Lock()


def _lexicon_strongs_map(db: sqlite3.Connection) -> dict[str, list[str]]:
    """Lazy in-process cache: strongs tag → list of lexicon chunk IDs.

    Built once per process from a single query (tags table is read-heavy and
    the 1:1 strongs→lexicon-entry mapping is stable for the lifetime of the
    index). Avoids the 1-2s per-request tags join caused by the single-column
    idx_tags_tag index having to fetch doc_id from the main table row.
    """
    global _lexicon_strongs_cache
    if _lexicon_strongs_cache is not None:
        return _lexicon_strongs_cache
    with _lexicon_cache_lock:
        if _lexicon_strongs_cache is not None:  # double-checked
            return _lexicon_strongs_cache
        cache: dict[str, list[str]] = {}
        for tag, cid in db.execute(
            "SELECT t.tag, c.id "
            "FROM tags t "
            "JOIN chunks c ON c.doc_id = t.doc_id AND c.chunk_index = 0 "
            "JOIN tags k ON k.doc_id = t.doc_id AND k.tag = 'kind:lexicon' "
            "WHERE t.tag LIKE 'strongs:%'"
        ).fetchall():
            cache.setdefault(tag, []).append(cid)
        _lexicon_strongs_cache = cache
        return cache


def lexicon_search(
    db: sqlite3.Connection,
    *,
    fts_query: str,
    word_study_terms: list[str],
    strongs_tags: list[str],
    lemma_tags: list[str],
    limit: int = 50,
) -> list[Hit]:
    """Lookup over chunks_fts_lexicon plus tag joins on strongs:/lemma:.

    Three signal sources:
      1. Strong's-number tags (strongest — exact lookup)
      2. Lemma transliterations (also tag-based)
      3. FTS over chunks_fts_lexicon for English keywords / paraphrased queries

    Strong's hits get a synthetic high score so they outrank FTS noise.
    """
    hits: dict[str, float] = {}

    # 1. Strong's tag exact match — use in-process cache to avoid the slow
    #    tags join (single-column idx_tags_tag forces 28k+ table row reads).
    if strongs_tags:
        strongs_map = _lexicon_strongs_map(db)
        matched: list[str] = []
        for tag in strongs_tags:
            matched.extend(strongs_map.get(tag, []))
        for i, cid in enumerate(matched[:limit]):
            hits[cid] = max(hits.get(cid, 0.0), 1.0 - i / max(1, len(matched)))

    # 2. Lemma tag match — exact preferred over ASCII-stripped prefix.
    #
    # LSJ/Abbott-Smith transliterations contain diacritics ("agapē"); after
    # NFKD-normalize+strip in ingest, the tag is `lemma:agape` for those.
    # But some legacy slugs may have lost a trailing vowel; we keep a prefix
    # fallback for that case. Critically: the EXACT match must outrank the
    # prefix match (e.g., `lemma:logos` should beat `lemma:logomacheō` for
    # the user's "logos" query). Two-pass query handles ranking.
    exact_candidates = list(lemma_tags)
    prefix_candidates: list[str] = []
    for w in word_study_terms:
        slug = re.sub(r"[^a-z0-9]+", "", w.lower())
        if not slug:
            continue
        exact_candidates.append(f"lemma:{slug}")
        if len(slug) >= 4:
            prefix_candidates.append(f"lemma:{slug[:max(3, len(slug)-1)]}")

    # Pass 1: exact-match lemmas (highest tier — score 1.0 - i/n)
    seen_via_exact: set[str] = set()
    if exact_candidates:
        placeholders = ",".join("?" * len(exact_candidates))
        rows = db.execute(
            "SELECT DISTINCT chunks.id FROM tags "
            "JOIN chunks ON chunks.doc_id = tags.doc_id "
            "JOIN tags k ON k.doc_id = chunks.doc_id AND k.tag = 'kind:lexicon' "
            f"WHERE tags.tag IN ({placeholders}) LIMIT ?",
            [*exact_candidates, limit],
        ).fetchall()
        for i, (cid,) in enumerate(rows):
            hits[cid] = max(hits.get(cid, 0.0), 0.95 - i / max(1, len(rows)) * 0.1)
            seen_via_exact.add(cid)

    # Pass 2: prefix-match (only fills slots NOT taken by exact match;
    # capped at lower score so exact still wins.)
    if prefix_candidates:
        for prefix in prefix_candidates:
            rows = db.execute(
                "SELECT DISTINCT chunks.id FROM tags "
                "JOIN chunks ON chunks.doc_id = tags.doc_id "
                "JOIN tags k ON k.doc_id = chunks.doc_id AND k.tag = 'kind:lexicon' "
                "WHERE tags.tag LIKE ? LIMIT ?",
                (prefix + "%", limit),
            ).fetchall()
            for i, (cid,) in enumerate(rows):
                if cid in seen_via_exact:
                    continue
                hits[cid] = max(hits.get(cid, 0.0), 0.7 - i / max(1, len(rows)) * 0.2)

    # 3. FTS over the lexicon body
    if fts_query.strip():
        try:
            rows = db.execute(
                "SELECT chunks.id, rank "
                "FROM chunks_fts_lexicon "
                "JOIN chunks ON chunks.rowid = chunks_fts_lexicon.rowid "
                "WHERE chunks_fts_lexicon MATCH ? ORDER BY rank LIMIT ?",
                (fts_query, limit),
            ).fetchall()
            n = len(rows)
            for i, (cid, _rank) in enumerate(rows):
                fts_score = 0.7 - i / max(1, n) * 0.5
                hits[cid] = max(hits.get(cid, 0.0), fts_score)
        except sqlite3.OperationalError as e:
            print(f"lexicon_search: FTS5 skipped ({e!r})", flush=True)

    ranked = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
    return [Hit(chunk_id=cid, score=score, retrievers=["lexicon"]) for cid, score in ranked]


def morphology_search(
    db: sqlite3.Connection,
    *,
    strongs_tags: list[str],
    lemma_tags: list[str],
    passages: list[tuple[int, int]],
    limit: int = 50,
) -> list[Hit]:
    """Tag- or passage-based lookup over chunks tagged kind:morphology
    (verse-level word-by-word parses)."""
    hits: dict[str, float] = {}

    # Tag-based (find verses containing this Strong's / lemma)
    tag_filters = [*strongs_tags, *lemma_tags]
    if tag_filters:
        placeholders = ",".join("?" * len(tag_filters))
        rows = db.execute(
            "SELECT DISTINCT chunks.id "
            "FROM tags "
            "JOIN chunks ON chunks.doc_id = tags.doc_id "
            f"WHERE tags.tag IN ({placeholders}) "
            "AND EXISTS (SELECT 1 FROM tags k WHERE k.doc_id = chunks.doc_id AND k.tag = 'kind:morphology') "
            "LIMIT ?",
            [*tag_filters, limit],
        ).fetchall()
        for i, (cid,) in enumerate(rows):
            hits[cid] = max(hits.get(cid, 0.0), 1.0 - i / max(1, len(rows)))

    # Passage-based (find morphology for "John 1:1")
    # Start from kind:morphology tags (29k rows) → join passage_refs for the
    # passage filter. This is more selective than starting from passage_refs
    # (591k rows) and checking EXISTS for morphology.
    if passages:
        where = " OR ".join("(passage_refs.start_bbcccvvv <= ? AND passage_refs.end_bbcccvvv >= ?)" for _ in passages)
        params: list = []
        for s, e in passages:
            params.extend([e, s])
        rows = db.execute(
            "SELECT DISTINCT chunks.id "
            "FROM tags k "
            "JOIN chunks ON chunks.doc_id = k.doc_id "
            "JOIN passage_refs ON passage_refs.doc_id = k.doc_id "
            f"WHERE k.tag = 'kind:morphology' AND ({where}) LIMIT ?",
            [*params, limit],
        ).fetchall()
        for i, (cid,) in enumerate(rows):
            hits[cid] = max(hits.get(cid, 0.0), 0.9 - i / max(1, len(rows)))

    ranked = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
    return [Hit(chunk_id=cid, score=score, retrievers=["morphology"]) for cid, score in ranked]


def entity_search(
    db: sqlite3.Connection,
    *,
    entity_query: dict | None,
    lang: str = "en",
    limit: int = 30,
) -> list[Hit]:
    """Graph traversal over entities + entity_relations.

    `entity_query`:
      {"name": "David"}                          → David's term/scripture chunks
      {"name": "David", "relation": "father-of"} → outbound: people David is
                                                    father of (his children)
      {"name": "David", "relation": "father-of-rev"} → inbound: David's father (Jesse)

    Returns chunks for the resolved entities — a mix of TW term articles
    (kind:term tagged term:<name> / acai:person:<Name>) and Bible chunks at
    the entity's first mention. The mix surfaces both prose (TW: who Jesse
    was) and verses (BSB: where Jesse appears).
    """
    if not entity_query or not entity_query.get("name"):
        return []
    name = entity_query["name"].strip()
    relation = entity_query.get("relation")

    # 1. Find matching entities by name (case-insensitive exact match preferred,
    #    then case-insensitive prefix).
    matches = db.execute(
        "SELECT id, type, name FROM entities "
        "WHERE LOWER(name) = LOWER(?) ORDER BY id LIMIT 8",
        (name,),
    ).fetchall()
    if not matches:
        matches = db.execute(
            "SELECT id, type, name FROM entities "
            "WHERE LOWER(name) LIKE LOWER(?) ORDER BY id LIMIT 8",
            (name + "%",),
        ).fetchall()
    if not matches and canon(lang) != "eng":
        # Strong's bridge: localized name → Strong's → English entity name.
        # Lets non-English genealogy ("отец Давида", "uban Dauda") resolve
        # against the English-only entities graph.
        from query.name_bridge import localized_to_english
        for en_name in localized_to_english(db, name, lang):
            matches = db.execute(
                "SELECT id, type, name FROM entities "
                "WHERE LOWER(name) = LOWER(?) ORDER BY id LIMIT 8",
                (en_name,),
            ).fetchall()
            if matches:
                break
    if not matches:
        return []

    target_entities: list[tuple[str, str, str]] = []  # (id, type, name)

    if relation:
        # Traverse one hop. 'father-of-rev' (etc.) means inbound to the matched
        # entity ("who is the father OF X" — find someone with father-of edge to X).
        reverse = relation.endswith("-rev")
        rel = relation[:-4] if reverse else relation
        for eid, _typ, _ename in matches:
            if reverse:
                rows = db.execute(
                    "SELECT er.source_id, e.type, e.name "
                    "FROM entity_relations er "
                    "JOIN entities e ON e.id = er.source_id "
                    "WHERE er.target_id = ? AND er.relation = ?",
                    (eid, rel),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT er.target_id, e.type, e.name "
                    "FROM entity_relations er "
                    "JOIN entities e ON e.id = er.target_id "
                    "WHERE er.source_id = ? AND er.relation = ?",
                    (eid, rel),
                ).fetchall()
            target_entities.extend(rows)
        # Always include the original matches too — useful UX context
        # ("you asked about David; here's both David and Jesse").
        target_entities.extend(matches)
    else:
        target_entities = list(matches)

    if not target_entities:
        return []

    # Dedup by entity id
    seen: set[str] = set()
    target_entities = [t for t in target_entities if not (t[0] in seen or seen.add(t[0]))]

    hits: dict[str, float] = {}

    # 2. For each target entity, gather chunks
    rank_counter = 0
    for eid, etype, ename in target_entities:
        # 2a. TW term articles (kind:term) tagged with the entity's name slug
        slug = re.sub(r"[^a-z0-9]+", "", ename.lower())
        tag_candidates = [
            f"term:{slug}",
            f"acai:person:{ename}",
            f"acai:place:{ename}",
            f"acai:keyterm:{ename}",
        ]
        placeholders = ",".join("?" * len(tag_candidates))
        rows = db.execute(
            "SELECT DISTINCT chunks.id FROM tags "
            "JOIN chunks ON chunks.doc_id = tags.doc_id "
            f"WHERE tags.tag IN ({placeholders}) LIMIT 5",
            tag_candidates,
        ).fetchall()
        for (cid,) in rows:
            rank_counter += 1
            hits[cid] = max(hits.get(cid, 0.0), 1.0 - rank_counter / 100.0)

        # 2b. Bible/scripture chunks at the entity's passages (chunk_index=0)
        rows = db.execute(
            "SELECT DISTINCT chunks.id "
            "FROM entity_passages ep "
            "JOIN passage_refs pr ON pr.start_bbcccvvv <= ep.end_bbcccvvv "
            "                     AND pr.end_bbcccvvv   >= ep.start_bbcccvvv "
            "JOIN chunks ON chunks.doc_id = pr.doc_id AND chunks.chunk_index = 0 "
            "JOIN tags k ON k.doc_id = chunks.doc_id "
            "             AND k.tag IN ('kind:bible', 'kind:scripture') "
            "WHERE ep.entity_id = ? "
            "LIMIT 5",
            (eid,),
        ).fetchall()
        for (cid,) in rows:
            rank_counter += 1
            hits[cid] = max(hits.get(cid, 0.0), 0.9 - rank_counter / 100.0)

        if rank_counter >= limit:
            break

    ranked = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
    return [Hit(chunk_id=cid, score=score, retrievers=["entity"]) for cid, score in ranked]


def _consolidate_bible_hits(
    db: sqlite3.Connection,
    hits: dict[str, float],
    gap: int = 2,
) -> list[Hit]:
    """Merge adjacent BSB verse hits into passage-level hits.

    Verses within `gap` BBCCCVVV of each other are grouped together.
    The group keeps the best score and the first chunk_id as representative.
    """
    placeholders = ",".join("?" * len(hits))
    rows = db.execute(
        f"SELECT chunks.id, passage_refs.start_bbcccvvv "
        f"FROM chunks "
        f"JOIN passage_refs ON passage_refs.doc_id = chunks.doc_id "
        f"WHERE chunks.id IN ({placeholders}) "
        f"ORDER BY passage_refs.start_bbcccvvv",
        list(hits.keys()),
    ).fetchall()

    if not rows:
        ranked = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
        return [Hit(chunk_id=cid, score=s, retrievers=["bible"]) for cid, s in ranked]

    groups: list[tuple[str, float]] = []
    grp_cid, grp_score, prev_bb = rows[0][0], hits[rows[0][0]], rows[0][1]

    for cid, bb in rows[1:]:
        if bb - prev_bb <= gap:
            if hits[cid] > grp_score:
                grp_score = hits[cid]
                grp_cid = cid
        else:
            groups.append((grp_cid, grp_score))
            grp_cid, grp_score = cid, hits[cid]
        prev_bb = bb

    groups.append((grp_cid, grp_score))
    groups.sort(key=lambda kv: kv[1], reverse=True)
    return [Hit(chunk_id=cid, score=score, retrievers=["bible"]) for cid, score in groups]


def bible_search(
    db: sqlite3.Connection,
    *,
    fts_query: str,
    passages: list[tuple[int, int]],
    limit: int = 15,
    lang: str = "en",
) -> list[Hit]:
    """FTS over chunks_fts_bible + passage filter, with adjacent-verse
    consolidation so multiple nearby verses merge into one passage-level hit.

    Filtered to the query language (`lang:<lang>` tag): chunks_fts_bible now
    holds multiple translations (BSB en, RV09 es, …), so without this an es
    query would surface English verses and vice versa.
    """
    hits: dict[str, float] = {}
    # index.db lang: tags use the short/web form (en, es, zh-Hant); map the
    # canonical request tag to it so existing indexes match without a re-index.
    lang_tag = f"lang:{to_web(canon(lang))}"

    if passages:
        where = " OR ".join("(passage_refs.start_bbcccvvv <= ? AND passage_refs.end_bbcccvvv >= ?)" for _ in passages)
        params: list = []
        for s, e in passages:
            params.extend([e, s])
        rows = db.execute(
            "SELECT DISTINCT chunks.id "
            "FROM chunks "
            "JOIN passage_refs ON passage_refs.doc_id = chunks.doc_id "
            f"WHERE ({where}) "
            "AND EXISTS (SELECT 1 FROM tags WHERE doc_id = chunks.doc_id AND tag = 'kind:bible') "
            "AND EXISTS (SELECT 1 FROM tags WHERE doc_id = chunks.doc_id AND tag = ?) "
            "ORDER BY passage_refs.start_bbcccvvv LIMIT ?",
            [*params, lang_tag, limit],
        ).fetchall()
        for i, (cid,) in enumerate(rows):
            hits[cid] = max(hits.get(cid, 0.0), 1.0 - i / max(1, len(rows)))

    if fts_query.strip():
        try:
            rows = db.execute(
                "SELECT chunks.id, rank "
                "FROM chunks_fts_bible "
                "JOIN chunks ON chunks.rowid = chunks_fts_bible.rowid "
                "WHERE chunks_fts_bible MATCH ? "
                "AND EXISTS (SELECT 1 FROM tags WHERE doc_id = chunks.doc_id AND tag = ?) "
                "ORDER BY rank LIMIT ?",
                (fts_query, lang_tag, limit),
            ).fetchall()
            n = len(rows)
            for i, (cid, _rank) in enumerate(rows):
                hits[cid] = max(hits.get(cid, 0.0), 0.7 - i / max(1, n) * 0.5)
        except sqlite3.OperationalError as e:
            print(f"bible_search: FTS5 skipped ({e!r})", flush=True)

    if not hits:
        return []

    return _consolidate_bible_hits(db, hits)


def aquifer_search(
    db: sqlite3.Connection,
    *,
    fts_query: str,
    lang: str = "en",
    limit: int = 15,
) -> list[Hit]:
    """FTS over chunks_fts_aquifer — Aquifer study breadth (study notes,
    dictionaries, key terms), isolated from the main chunks_fts so its large
    multilingual corpus doesn't pollute primary BM25 statistics. Scoped to the
    query language plus English (the universal study fallback)."""
    if not fts_query.strip():
        return []
    lang_tag = f"lang:{to_web(canon(lang))}"
    try:
        rows = db.execute(
            "SELECT chunks.id, rank "
            "FROM chunks_fts_aquifer "
            "JOIN chunks ON chunks.rowid = chunks_fts_aquifer.rowid "
            "WHERE chunks_fts_aquifer MATCH ? "
            "AND EXISTS ("
            "  SELECT 1 FROM tags WHERE doc_id = chunks.doc_id AND tag IN (?, 'lang:en')"
            ") "
            "ORDER BY rank LIMIT ?",
            (fts_query, lang_tag, limit),
        ).fetchall()
    except sqlite3.OperationalError as e:
        print(f"aquifer_search: skipped ({e!r})", flush=True)
        return []
    n = len(rows)
    return [Hit(chunk_id=cid, score=1.0 - i / max(1, n), retrievers=["aquifer"])
            for i, (cid, _rank) in enumerate(rows)]


def topic_search(
    db: sqlite3.Connection,
    *,
    topic_query: str | None,
    limit: int = 30,
) -> list[Hit]:
    """Nave's-style topic lookup: topic name → BBCCCVVV passages → BSB chunks."""
    if not topic_query:
        return []

    # Resolve topic by exact-name (case-insensitive) match first; fall back to LIKE.
    rows = db.execute(
        "SELECT id FROM topics WHERE LOWER(name) = LOWER(?) LIMIT 5",
        (topic_query,),
    ).fetchall()
    if not rows:
        rows = db.execute(
            "SELECT id FROM topics WHERE LOWER(name) LIKE LOWER(?) LIMIT 5",
            (topic_query + "%",),
        ).fetchall()
    topic_ids = [r[0] for r in rows]
    if not topic_ids:
        return []

    placeholders = ",".join("?" * len(topic_ids))
    # Get up to `limit` BBCCCVVV pairs from topic_passages, then join to BSB chunks.
    rows = db.execute(
        "SELECT DISTINCT chunks.id "
        "FROM topic_passages tp "
        "JOIN passage_refs pr ON pr.start_bbcccvvv <= tp.end_bbcccvvv "
        "                     AND pr.end_bbcccvvv >= tp.start_bbcccvvv "
        "JOIN chunks ON chunks.doc_id = pr.doc_id AND chunks.chunk_index = 0 "
        f"WHERE tp.topic_id IN ({placeholders}) "
        "AND EXISTS (SELECT 1 FROM tags WHERE doc_id = chunks.doc_id AND tag = 'kind:bible') "
        "ORDER BY tp.start_bbcccvvv LIMIT ?",
        [*topic_ids, limit],
    ).fetchall()
    n = len(rows)
    return [
        Hit(chunk_id=r[0], score=1.0 - i / max(1, n), retrievers=["topic"])
        for i, r in enumerate(rows)
    ]


def xref_search(
    db: sqlite3.Connection,
    *,
    source_bbcccvvv: int | None,
    limit: int = 30,
) -> list[Hit]:
    """Cross-reference followup: source verse → TSK/BSB-parallel target verses → BSB chunks."""
    if source_bbcccvvv is None:
        return []
    # Ordering: bsb-parallel xrefs first (editorial-marked, deliberate
    # parallels with no rank field), then TSK refs by rank ascending. Putting
    # bsb-parallel at the bottom (the previous (rank IS NULL) sort) buried
    # the most pedagogically valuable parallels behind TSK long-tail.
    rows = db.execute(
        """
        SELECT DISTINCT chunks.id, xr.rank, xr.source_attribution
        FROM cross_references xr
        JOIN passage_refs pr ON pr.start_bbcccvvv <= xr.target_end_bbcccvvv
                             AND pr.end_bbcccvvv   >= xr.target_start_bbcccvvv
        JOIN chunks ON chunks.doc_id = pr.doc_id AND chunks.chunk_index = 0
        JOIN tags k ON k.doc_id = chunks.doc_id AND k.tag = 'kind:bible'
        WHERE xr.source_bbcccvvv = ?
        ORDER BY
          CASE xr.source_attribution WHEN 'bsb-parallel' THEN 0 ELSE 1 END,
          (xr.rank IS NULL),
          xr.rank ASC
        LIMIT ?
        """,
        (source_bbcccvvv, limit),
    ).fetchall()
    n = len(rows)
    return [
        Hit(chunk_id=r[0], score=1.0 - i / max(1, n), retrievers=["xref"])
        for i, r in enumerate(rows)
    ]


# ---------- corpus (local Context-Fabric engine) ----------

_corpus_book_map: dict[str, tuple[str, str]] | None = None


def _ensure_book_map() -> dict[str, tuple[str, str]]:
    """Build USFM → (corpus_book_name, corpus_id) from the local corpus engine."""
    global _corpus_book_map
    if _corpus_book_map:
        return _corpus_book_map

    from indexer.references import BOOK_NUMBERS

    mapping: dict[str, tuple[str, str]] = {}
    try:
        from corpus import engine
        for corpus_id, num_range in [("hebrew", (1, 40)), ("greek", (40, 100))]:
            books = engine.list_books(corpus_id)
            corpus_names = [b.name for b in books]

            usfm_codes = sorted(
                [(code, num) for code, num in BOOK_NUMBERS.items()
                 if num_range[0] <= num < num_range[1]],
                key=lambda x: x[1],
            )
            for (usfm, _num), corpus_name in zip(usfm_codes, corpus_names):
                mapping[usfm] = (corpus_name, corpus_id)

        logger.info("Loaded %d book mappings from corpus engine", len(mapping))
    except Exception as e:
        logger.warning("Failed to load book names from corpus engine: %s", e)

    _corpus_book_map = mapping
    return _corpus_book_map


def _usfm_to_corpus(book_code: str) -> tuple[str, str]:
    """Map USFM book code → (corpus_book_name, corpus_id)."""
    book_map = _ensure_book_map()
    if book_code in book_map:
        return book_map[book_code]
    raise ValueError(f"unknown book code for corpus mapping: {book_code}")


def cfabric_search(
    passages: list[tuple[int, int]],
    *,
    limit: int = 20,
    timeout: float = 0.8,
) -> list[Hit]:
    """Retrieve syntactic context from the local corpus engine for passage-bearing queries.

    `timeout` caps the total wall time for all corpus calls in this retriever.
    The corpus engine can be slow (cold cache, cold connection) and must not
    block the entire request.
    """
    if not passages:
        return []

    import concurrent.futures
    from indexer.references import decode

    def _run() -> list[Hit]:
        hits: dict[str, float] = {}
        seen_verses = 0
        from corpus import engine  # noqa: PLC0415
        for start, end in passages:
            s_code, s_ch, s_v = decode(start)
            e_code, e_ch, e_v = decode(end)
            if s_code != e_code:
                continue
            try:
                book_name, corpus = _usfm_to_corpus(s_code)
            except ValueError:
                continue
            for v in range(s_v, e_v + 1):
                if seen_verses >= limit:
                    break
                data = engine.get_context(
                    book=book_name, chapter=s_ch, verse=v, corpus=corpus,
                )
                if "error" in data:
                    continue
                bbcccvvv = start + (v - s_v)
                hits[f"corpus:{bbcccvvv}"] = 1.0 - seen_verses / max(1, limit)
                seen_verses += 1
        ranked = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
        return [Hit(chunk_id=cid, score=score, retrievers=["cfabric"]) for cid, score in ranked]

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_run)
            return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        logger.warning("cfabric_search: timed out after %.1fs", timeout)
        return []
    except Exception as e:
        logger.warning("corpus engine error: %s", e)
        return []


# ---------- fusion ----------

def rrf(
    hit_lists: list[list[Hit]],
    *,
    k: int = 60,
    weights: list[float] | None = None,
) -> list[Hit]:
    """Reciprocal Rank Fusion across ranked retriever outputs, with optional per-list weights."""
    if weights is None:
        weights = [1.0] * len(hit_lists)
    if len(weights) != len(hit_lists):
        raise ValueError(f"weights length {len(weights)} != hit_lists length {len(hit_lists)}")
    scores: dict[str, float] = {}
    retrievers: dict[str, set[str]] = {}
    for hits, weight in zip(hit_lists, weights):
        if weight == 0:
            continue
        for rank, h in enumerate(hits, start=1):
            scores[h.chunk_id] = scores.get(h.chunk_id, 0.0) + weight / (k + rank)
            retrievers.setdefault(h.chunk_id, set()).update(h.retrievers)
    fused = [
        Hit(chunk_id=cid, score=score, retrievers=sorted(retrievers[cid]))
        for cid, score in scores.items()
    ]
    fused.sort(key=lambda h: h.score, reverse=True)
    return fused


# ---------- top-level ----------

# Per-intent RRF weights. Order:
#   [fts, title, passage, scripture, tag, vec, lexicon, morphology, entity, bible, topic, xref, cfabric, aquifer]
#
# Title-search is gold for entity_lookup (Who/What is X?) and useful for
# methodology (matching module names like "Metaphor"). For thematic and
# passage-shaped queries, title hits over-weight TW term articles and push
# narrative notes / per-verse content out of top-K, which kills queries
# where the answer is in a TN body, not a TW title. Down-weight title there.
#
# v3 retrievers (lexicon, morphology, entity, bible, topic, xref) get
# weight 0 for v2-shaped intents — they'd otherwise pollute results when
# their structured inputs aren't actually relevant. They light up only
# under the new intent classes that the analyzer routes to them.
_INTENT_WEIGHTS: dict[str, list[float]] = {
    #                    fts  titl pass scrp tag  vec   lex  mrph ent  bib  top  xrf  cfab aqf  spkr
    "thematic":         [1.0, 0.5, 1.0, 0.0, 1.0, 1.0,  0.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0, 0.5, 0.0],
    "entity_lookup":    [1.0, 2.5, 0.8, 0.0, 1.5, 1.0,  0.0, 0.0, 0.5, 0.5, 0.0, 0.0, 0.0, 0.2, 0.0],
    # bible (the verse TEXT) leads passage queries: "what does <verse> SAY" wants
    # the verse first, not commentary about it. Was 0.5 — study notes (passage,
    # 1.2) buried the BSB verse at rank ~163. See eval tit_1_1_servant.
    "passage_specific": [1.0, 0.6, 1.2, 0.0, 1.0, 1.0,  0.0, 0.0, 0.0, 2.0, 0.0, 0.5, 1.5, 0.2, 0.0],
    "passage_book":     [1.0, 0.6, 1.1, 0.0, 1.0, 1.0,  0.0, 0.0, 0.0, 1.5, 0.0, 0.0, 0.5, 0.2, 0.0],
    "methodology":      [1.0, 1.5, 1.0, 0.0, 1.0, 1.2,  0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "word_study":       [0.3, 0.5, 0.0, 0.0, 0.5, 0.5,  3.0, 1.5, 0.0, 0.0, 0.0, 0.0, 2.0, 0.2, 0.0],
    "morphology":       [0.3, 0.3, 0.5, 0.0, 0.5, 0.0,  1.0, 3.0, 0.0, 0.5, 0.0, 0.0, 2.5, 0.2, 0.0],
    "genealogy":        [0.5, 1.0, 0.0, 0.0, 1.0, 0.5,  0.0, 0.0, 3.0, 0.5, 0.0, 0.0, 0.0, 0.2, 0.0],
    "topic":            [0.5, 0.5, 0.5, 0.0, 0.5, 0.5,  0.0, 0.0, 0.0, 0.5, 3.0, 0.0, 0.0, 0.4, 0.0],
    "xref":             [0.5, 0.5, 0.5, 0.0, 0.5, 0.5,  0.0, 0.0, 0.0, 0.5, 0.0, 3.0, 0.0, 0.2, 0.0],
    # S1 speaker scoping: the speaker retriever dominates; fts/bible/aquifer keep
    # the topic in play for the synthesis context.
    "speaker":          [0.5, 0.3, 0.0, 0.0, 0.5, 0.5,  0.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0, 0.3, 3.0],
}

# Retriever execution order — index aligns with each _INTENT_WEIGHTS row and
# with the list passed to rrf(). The single source of truth for both the flat
# and branched paths.
_RETRIEVER_ORDER = (
    "fts", "title", "passage", "scripture", "tag", "vector", "lexicon",
    "morphology", "entity", "bible", "topic", "xref", "cfabric", "aquifer",
    "speaker",
)


def _gather_hits(
    db: sqlite3.Connection,
    analysis: QueryAnalysis,
    *,
    query_vec: list[float] | None,
    source_filter: str | None,
    lang: str,
) -> list[list[Hit]]:
    """Run query expansion, build filters, and execute every retriever once.

    Returns the per-retriever hit lists in `_RETRIEVER_ORDER`. Shared by
    `retrieve()` (weighted RRF → flat top-k) and `retrieve_branched()` (bucket
    by kind → tree) so both pay the retriever cost once and see identical
    candidates. NOTE: mutates `analysis.tags`/`analysis.passages` with the
    expansions, exactly as the inline code did — callers pass a per-request
    analysis, so this is single-shot.
    """
    # Strategy 1: concept expansion (always-on, <1ms)
    from query.concept_expand import expand_concepts
    concept_tags = expand_concepts(analysis.fts_query, analysis.tags, lang=lang)
    if concept_tags:
        analysis.tags.extend(concept_tags)

    # Strategy 2: LXX bridge expansion (always-on when H-tags present, ~50ms)
    from query.lxx_expand import expand_lxx
    lxx_tags = expand_lxx(analysis.tags)
    if lxx_tags:
        analysis.tags.extend(lxx_tags)

    # Strategy 3: morph pre-filter (only on morph-keyword queries, ~50-150ms)
    from query.morph_prefilter import detect_morph_pattern, morph_passages, _extract_book_code
    morph_pattern = detect_morph_pattern(analysis.fts_query)
    if morph_pattern:
        book_code = _extract_book_code(analysis.passages)
        morph_refs = morph_passages(morph_pattern, book=book_code)
        if morph_refs:
            analysis.passages.extend(morph_refs)

    narrow = analysis.passages and any((e - s) < 999 for s, e in analysis.passages)
    source = _docs_by_source(db, source_filter)
    # passages_filter and v2_filter are only needed by vector_search — all other
    # retrievers handle kind filtering via NOT EXISTS. Building either filter
    # materializes 100k-250k doc IDs and costs 0.5-2.5s; skip when no semantic.
    if query_vec:
        passages_filter = _docs_overlapping_passages(db, analysis.passages) if narrow else None
        v2_filter = _docs_v2_only(db)
    else:
        passages_filter = None
        v2_filter = None
    doc_filter = _intersect_filters(passages_filter, source, v2_filter)

    strongs_tags, lemma_tags = _strongs_lemma_filter(analysis.tags)

    # Order MUST match _RETRIEVER_ORDER and the _INTENT_WEIGHTS columns.
    return [
        fts_search(db, analysis.fts_query),
        title_search(db, analysis.fts_query),
        passage_search(db, analysis.passages),
        scripture_search(db, analysis.passages, query_vec, fts_query=analysis.fts_query),
        tag_search(db, analysis.tags),
        vector_search(db, query_vec, doc_filter=doc_filter) if query_vec else [],
        lexicon_search(db, fts_query=analysis.fts_query,
                       word_study_terms=analysis.word_study_terms,
                       strongs_tags=strongs_tags, lemma_tags=lemma_tags),
        morphology_search(db, strongs_tags=strongs_tags, lemma_tags=lemma_tags,
                          passages=analysis.passages),
        entity_search(db, entity_query=analysis.entity_query, lang=lang),
        bible_search(db, fts_query=analysis.fts_query, passages=analysis.passages, lang=lang),
        topic_search(db, topic_query=analysis.topic_query),
        xref_search(db, source_bbcccvvv=analysis.xref_source),
        cfabric_search(analysis.passages),
        aquifer_search(db, fts_query=analysis.fts_query, lang=lang),
        speaker_search(db, speaker=analysis.speaker, fts_query=analysis.fts_query),
    ]


def _language_gate(db: sqlite3.Connection, hits: list[Hit], lang: str) -> list[Hit]:
    """Drop cross-language hits (shared by flat + branched paths).

    Content now exists in many languages (bibles + Aquifer study notes),
    reachable via every retriever:
      • kind:bible — STRICT: only the query language (we have the bible in that
        language; an English verse would be redundant/wrong).
      • everything else — query language OR English (the universal study
        fallback when query-language notes don't exist).
      • lang-neutral content (no lang: tag — entities, cross-refs, …) is kept.
    Look up lang/kind tags ONLY for the candidate docs (a few hundred), not the
    whole tags table — those scans dominated request latency.
    """
    cand_docs = {h.chunk_id.split(":", 1)[0] for h in hits}
    if not cand_docs:
        return hits
    is_bible: set[str] = set()
    langs_by_doc: dict[str, set[str]] = {}
    ph = ",".join("?" * len(cand_docs))
    for did, tag in db.execute(
        f"SELECT doc_id, tag FROM tags WHERE doc_id IN ({ph}) "
        f"AND (tag='kind:bible' OR tag LIKE 'lang:%')", list(cand_docs)).fetchall():
        if tag == "kind:bible":
            is_bible.add(did)
        else:
            langs_by_doc.setdefault(did, set()).add(tag[len("lang:"):])

    wl = to_web(canon(lang))   # index lang: tags are short/web form (en, es, …)

    def _keep(did: str) -> bool:
        dl = langs_by_doc.get(did)
        if did in is_bible and (not dl or wl not in dl):
            return False  # foreign-language bible (strict)
        if dl and wl not in dl and "en" not in dl:
            return False  # foreign-language non-bible (no English fallback)
        return True

    return [h for h in hits if _keep(h.chunk_id.split(":", 1)[0])]


# ---------- branched retrieval ----------

@dataclass
class Branch:
    """One drill-down node of the result tree."""
    key: str            # stable drill-down parameter
    label: str          # default display string (UI may localize)
    featured: bool      # auto-intent expanded this branch?
    hits: list[Hit]     # ranked, capped to per_branch
    total: int          # hits available before the cap (for "+N more")


# User-facing branch taxonomy: each branch groups one or more index `kind:`
# tags. ALL branches are always retrieved; the per-intent featured set only
# decides expanded-vs-collapsed — never on/off. This is the deliberate
# reinterpretation of an _INTENT_WEIGHTS 0.0 as "collapsed", not "excluded".
#
# `key` is the language-neutral contract (stable across releases); clients with
# their own i18n should localize from it. `label` is a default English string;
# _branch_label() localizes it for the common UI languages, English otherwise.
_BRANCH_SPEC: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("lexicon",     "Lexicon / words",   ("lexicon",)),
    ("study",       "Study notes",       ("study-note", "book-intro")),
    ("terms",       "Key terms",         ("term", "translator-note", "question")),
    ("verses",      "Verses",            ("bible", "scripture")),
    ("morphology",  "Morphology",        ("morphology",)),
    ("methodology", "Methodology",       ("methodology",)),
    ("media",       "Resources",         ("video-transcript", "section-heading")),
    ("other",       "Other",             ()),  # catch-all for unmapped kinds
)
_KIND_TO_BRANCH = {k: key for key, _, kinds in _BRANCH_SPEC for k in kinds}
_BRANCH_LABEL_EN = {key: label for key, label, _ in _BRANCH_SPEC}
_BRANCH_ORDER = [key for key, _, _ in _BRANCH_SPEC]

# Optional server-side localization of the default label, keyed by canonical
# query language. Clients that localize from `key` ignore this; clients without
# their own i18n get a sensible localized default (English fallback).
_BRANCH_LABELS_I18N: dict[str, dict[str, str]] = {
    "spa": {
        "lexicon": "Léxico / palabras", "study": "Notas de estudio",
        "terms": "Términos clave", "verses": "Versículos",
        "morphology": "Morfología", "methodology": "Metodología",
        "media": "Recursos", "other": "Otros",
    },
}


def _branch_label(key: str, lang: str) -> str:
    """Localized default label for a branch key (English fallback)."""
    return _BRANCH_LABELS_I18N.get(canon(lang), {}).get(key, _BRANCH_LABEL_EN[key])

# Which branches the auto-intent FEATURES (expands). Others come back collapsed
# but populated and drill-down-addressable. Unknown intent → thematic.
_FEATURED_BRANCHES: dict[str, tuple[str, ...]] = {
    "thematic":         ("lexicon", "study", "terms"),
    "word_study":       ("lexicon", "morphology", "terms"),
    "morphology":       ("morphology", "lexicon", "verses"),
    "entity_lookup":    ("terms", "study", "verses"),
    "methodology":      ("methodology", "terms"),
    "topic":            ("study", "terms", "verses"),
    "xref":             ("verses", "study"),
    "genealogy":        ("terms", "study"),
    "passage_specific": ("verses", "study", "terms"),
    "passage_book":     ("study", "verses", "terms"),
}


def _kinds_for_docs(db: sqlite3.Connection, doc_ids: set[str]) -> dict[str, str]:
    """doc_id -> its kind:* value (first one wins; missing → '')."""
    out: dict[str, str] = {}
    if not doc_ids:
        return out
    ph = ",".join("?" * len(doc_ids))
    for did, tag in db.execute(
        f"SELECT doc_id, tag FROM tags WHERE doc_id IN ({ph}) AND tag LIKE 'kind:%'",
        list(doc_ids)).fetchall():
        out.setdefault(did, tag[len("kind:"):])
    return out


def retrieve_branched(
    db: sqlite3.Connection,
    analysis: QueryAnalysis,
    *,
    query_vec: list[float] | None = None,
    source_filter: str | None = None,
    lang: str = "en",
    per_branch: int = 8,
    force: list[str] | None = None,
) -> list[Branch]:
    """Branched retrieval: run every retriever once, then GROUP results by kind
    into user-facing branches instead of fusing into one flat top-k.

    Auto-intent (`analysis.intent`) decides which branches are *featured*
    (expanded); the rest come back collapsed but populated, so a client can
    drill into any branch — including ones the intent didn't feature — via
    `force`. Within a branch, hits rank by UNWEIGHTED RRF, so a correctly
    anchored hit (e.g. lexicon ἀγάπη for a 'thematic' query, whose flat intent
    weight is 0.0) is never discarded — the entire point of branching.
    """
    hit_lists = _gather_hits(db, analysis, query_vec=query_vec,
                             source_filter=source_filter, lang=lang)
    # Unweighted fusion: every retriever counts equally so branch-native hits
    # survive regardless of the flat intent weight that would zero them.
    fused = _language_gate(db, rrf(hit_lists), lang)
    kinds = _kinds_for_docs(db, {h.chunk_id.split(":", 1)[0] for h in fused})

    buckets: dict[str, list[Hit]] = {key: [] for key in _BRANCH_ORDER}
    for h in fused:  # fused is already ranked, so buckets stay ranked
        kind = kinds.get(h.chunk_id.split(":", 1)[0], "")
        buckets[_KIND_TO_BRANCH.get(kind, "other")].append(h)

    # Anchored term lookup. The lexicon/morphology branches have Strong's-anchored
    # retrievers; the terms branch did not — it relied on tag_search, which is
    # diluted by the hundreds of verses sharing a code, so a single dedicated
    # term article (TW "Love" → strongs:G0026) gets buried below the cut. Pull
    # kind:term docs by the query's Strong's anchors directly and lead with them.
    strongs = [t for t in analysis.tags if t.startswith("strongs:")]
    if strongs:
        seen_terms = {h.chunk_id for h in buckets["terms"]}
        ph = ",".join("?" * len(strongs))
        rows = db.execute(
            f"SELECT c.id, COUNT(*) AS m FROM tags t "
            f"JOIN chunks c ON c.doc_id = t.doc_id "
            f"JOIN tags k ON k.doc_id = c.doc_id AND k.tag = 'kind:term' "
            f"WHERE t.tag IN ({ph}) GROUP BY c.id ORDER BY m DESC LIMIT 30", strongs).fetchall()
        anchored = _language_gate(
            db, [Hit(chunk_id=r[0], score=1.0, retrievers=["term_anchor"])
                 for r in rows if r[0] not in seen_terms], lang)
        buckets["terms"] = anchored + buckets["terms"]  # anchored articles lead

    featured = set(_FEATURED_BRANCHES.get(analysis.intent, _FEATURED_BRANCHES["thematic"]))
    if force:
        featured |= set(force)

    branches: list[Branch] = []
    for key in _BRANCH_ORDER:
        hits = buckets[key]
        if not hits and key not in featured:
            continue  # empty + not requested → omit
        branches.append(Branch(key=key, label=_branch_label(key, lang),
                               featured=key in featured,
                               hits=hits[:per_branch], total=len(hits)))
    # Featured branches first; stable sort preserves spec order within a group.
    branches.sort(key=lambda b: not b.featured)
    return branches


def retrieve(
    db: sqlite3.Connection,
    analysis: QueryAnalysis,
    *,
    top_k: int = 10,
    query_vec: list[float] | None = None,
    source_filter: str | None = None,
    lang: str = "en",
) -> list[Hit]:
    """Run all configured retrievers, fuse via intent-weighted RRF, return top_k chunks.

    `query_vec`     enables the vector retriever; if None, vector is skipped.
    `source_filter` 'door43' / 'aquifer' / 'all'. Restricts candidate docs.

    Note on passage filtering: a NARROW passage (specific verse(s), range
    < 999 verses) acts as a hard `doc_filter` to constrain FTS/vec. A BROAD
    passage (whole-book range from "according to Titus" / "the gospel of John")
    is treated as a soft hint — it still drives `scripture_search` and
    `passage_search`, but does NOT exclude content from FTS/vec. That way an
    inferred book scope helps without crowding out cross-book term articles
    or narrative notes that legitimately bear on the question.
    """
    hit_lists = _gather_hits(db, analysis, query_vec=query_vec,
                             source_filter=source_filter, lang=lang)
    weights = _INTENT_WEIGHTS.get(analysis.intent, _INTENT_WEIGHTS["thematic"])
    fused = rrf(hit_lists, weights=weights)
    fused = _language_gate(db, fused, lang)
    return fused[:top_k]
