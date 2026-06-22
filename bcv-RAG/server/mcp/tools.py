"""MCP tool definitions and handlers.

Each tool is a thin wrapper over the underlying retrieval / resolver code.
Handlers take (arguments: dict, db: sqlite3.Connection) and return the
JSON-serializable result dict that goes into the MCP `content` text body.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Callable

from indexer import citations as citations_mod
from indexer.db import has_vec
from indexer.references import human, parse_references
from query.analyzer import analyze
from query.concept_expand import filter_biblical_words
from query.retrieve import retrieve
from server.corpus_cards import resolve_corpus_hits
from server.resolver import chunk_preview_from_card, resolve_chunk
from server.trees import BUILDERS
from lang import canon

ToolHandler = Callable[[dict, sqlite3.Connection], dict]


# ---------- registry ----------

_REGISTRY: list[dict] = []
_HANDLERS: dict[str, ToolHandler] = {}


def register_tool(*, name: str, description: str, input_schema: dict):
    def decorate(fn: ToolHandler) -> ToolHandler:
        _REGISTRY.append({"name": name, "description": description, "inputSchema": input_schema})
        _HANDLERS[name] = fn
        return fn
    return decorate


def list_tools() -> list[dict]:
    return list(_REGISTRY)


def call_tool(name: str, arguments: dict, db: sqlite3.Connection) -> dict:
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"unknown tool: {name}")
    return handler(arguments or {}, db)


# ---------- tools ----------

@register_tool(
    name="search",
    description=(
        "Search the indexed Bible-translation corpus. Returns ranked chunks "
        "with metadata; does NOT generate an answer — caller (you) should read "
        "the chunks and synthesize.\n\n"
        "By default uses FTS5 keyword matching, passage-range matching, title "
        "matching, and tag filters via reciprocal rank fusion — no model calls, "
        "no API keys required, deterministic. Pass `use_semantic: true` to "
        "additionally enable vector ANN (requires OPENAI_API_KEY on the server "
        "and adds ~150ms per call); useful for paraphrased queries where keyword "
        "match misses the right chunks. NOTE: `use_semantic: true` is gated by "
        "the server-side API password (BTMCP_API_PASSWORD) — pass `Authorization: "
        "Bearer <password>` or `X-API-Key: <password>` on the MCP HTTP request."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Free-form question or keyword search."},
            "lang": {"type": "string", "default": "en"},
            "kind": {
                "type": "string",
                "enum": ["scripture", "translator-note", "question", "term", "methodology",
                         "study-note", "book-intro", "map", "image"],
            },
            "book": {"type": "string", "description": "USFM book code (e.g. 'TIT')."},
            "source": {"type": "string", "enum": ["all", "door43", "aquifer"], "default": "all"},
            "top_k": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
            "use_semantic": {
                "type": "boolean",
                "default": False,
                "description": "Opt-in: also rank by semantic vector similarity. Requires OPENAI_API_KEY on the server.",
            },
        },
        "required": ["query"],
    },
)
def _search(args: dict, db: sqlite3.Connection) -> dict:
    q = args.get("query", "").strip()
    if not q:
        raise ValueError("'query' is required and non-empty")
    lang = args.get("lang", "en")
    top_k = int(args.get("top_k", 10))

    analysis = analyze(q)
    if args.get("kind"):
        analysis.tags.append(f"kind:{args['kind']}")
    if args.get("book"):
        analysis.tags.append(f"book:{str(args['book']).upper()}")

    # MCP default: NO model calls. Pure FTS5 + structured retrieval.
    # Caller can opt in to semantic vec via use_semantic=true (costs an
    # OPENAI_API_KEY-backed embedding call per query).
    query_vec = None
    if args.get("use_semantic") and has_vec(db):
        try:
            from indexer.embed import embed_texts
            query_vec = embed_texts([q], input_type="query")[0]
        except Exception:
            pass

    hits = retrieve(db, analysis, top_k=top_k, query_vec=query_vec,
                    source_filter=args.get("source", "all"))

    local_hits = [h for h in hits if not h.chunk_id.startswith("corpus:")]
    corpus_hits = [h for h in hits if h.chunk_id.startswith("corpus:")]

    cards = citations_mod.resolve_many(db, [h.chunk_id for h in local_hits])
    by_id = {c.chunk_id: c for c in cards}
    corpus_previews = resolve_corpus_hits(corpus_hits) if corpus_hits else {}

    out_hits = []
    for h in hits:
        if h.chunk_id.startswith("corpus:"):
            preview = corpus_previews.get(h.chunk_id)
        else:
            card = by_id.get(h.chunk_id)
            preview = chunk_preview_from_card(card, lang=lang) if card else None
        if preview is None:
            continue
        preview["score"] = round(float(h.score), 6)
        preview["retrievers"] = h.retrievers
        out_hits.append(preview)

    return {
        "query": q,
        "lang": lang,
        "analysis": {
            "fts_query": analysis.fts_query,
            "passages": [list(p) for p in analysis.passages],
            "tags": analysis.tags,
            "intent": analysis.intent,
        },
        "hits": out_hits,
    }


@register_tool(
    name="search_branched",
    description=(
        "Branched search: SAME retrieval as `search`, but results are GROUPED "
        "by kind into featured/collapsed branches (Léxico/lexicon, study notes, "
        "key terms, verses, morphology, …) instead of one flat ranked list. No "
        "LLM, deterministic. Auto-intent FEATURES the branches most relevant to "
        "the question (e.g. for a word-meaning question the lexicon branch is "
        "featured and verses are collapsed); every other branch is still "
        "returned collapsed and can be expanded by passing its key in `force` "
        "(e.g. ['morphology']). Prefer this over `search` when a question spans "
        "resource types or when the answer is a definition/word study that flat "
        "ranking buries under verse quotes. `suggested_drilldown` lists the "
        "collapsed branches that still have content."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Free-form question or keyword search."},
            "lang": {"type": "string", "default": "en"},
            "book": {"type": "string", "description": "USFM book code (e.g. 'TIT')."},
            "source": {"type": "string", "enum": ["all", "door43", "aquifer"], "default": "all"},
            "per_branch": {"type": "integer", "default": 8, "minimum": 1, "maximum": 50,
                           "description": "Max hits returned per branch."},
            "force": {
                "type": "array", "items": {"type": "string"},
                "description": "Branch keys to force-expand even if the intent didn't "
                               "feature them, e.g. ['lexicon','morphology'].",
            },
            "use_semantic": {
                "type": "boolean", "default": False,
                "description": "Opt-in: also rank by semantic vector similarity. Requires OPENAI_API_KEY on the server.",
            },
        },
        "required": ["query"],
    },
)
def _search_branched(args: dict, db: sqlite3.Connection) -> dict:
    q = args.get("query", "").strip()
    if not q:
        raise ValueError("'query' is required and non-empty")
    lang = args.get("lang", "en")

    analysis = analyze(q, lang=lang)
    if canon(lang) != "eng":
        analysis.fts_query = filter_biblical_words(q, lang=lang)
    if args.get("book"):
        analysis.tags.append(f"book:{str(args['book']).upper()}")

    query_vec = None
    if args.get("use_semantic") and has_vec(db):
        try:
            from indexer.embed import embed_texts
            query_vec = embed_texts([q], input_type="query")[0]
        except Exception:
            pass

    from server.branched import build_branches
    result = build_branches(
        db, analysis, query_vec=query_vec, source_filter=args.get("source", "all"),
        lang=lang, per_branch=int(args.get("per_branch", 8)),
        force=args.get("force") or None,
    )
    return {
        "query": q,
        "lang": lang,
        "analysis": {
            "fts_query": analysis.fts_query,
            "passages": [list(p) for p in analysis.passages],
            "tags": analysis.tags,
            "intent": analysis.intent,
        },
        "branches": result["branches"],
        "suggested_drilldown": result["suggested_drilldown"],
    }


@register_tool(
    name="get_chunk",
    description=(
        "Fetch the full body of a specific chunk by chunk_id. Returns body text, "
        "tree paths the chunk lives in, and cross-references."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "chunk_id": {"type": "string"},
            "lang": {"type": "string", "default": "en"},
        },
        "required": ["chunk_id"],
    },
)
def _get_chunk(args: dict, db: sqlite3.Connection) -> dict:
    chunk_id = args.get("chunk_id", "").strip()
    if not chunk_id:
        raise ValueError("'chunk_id' is required")
    result = resolve_chunk(db, chunk_id, lang=args.get("lang", "en"))
    if result is None:
        raise ValueError(f"chunk_id not found: {chunk_id}")
    return result


@register_tool(
    name="passage_lookup",
    description=(
        "Get every chunk overlapping a Bible passage range. Returns chunks "
        "from all sources (ULT, UST, TN, TQ, linked TW articles, Aquifer "
        "study notes, etc.)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "reference": {
                "type": "string",
                "description": "Bible reference, e.g. 'Titus 1:1', 'Romans 3:24-25', 'Ruth chapter 1'.",
            },
            "lang": {"type": "string", "default": "en"},
        },
        "required": ["reference"],
    },
)
def _passage_lookup(args: dict, db: sqlite3.Connection) -> dict:
    ref = args.get("reference", "").strip()
    if not ref:
        raise ValueError("'reference' is required")
    passages = parse_references(ref)
    if not passages:
        raise ValueError(f"could not parse Bible reference: {ref!r}")

    where = " OR ".join(
        "(passage_refs.start_bbcccvvv <= ? AND passage_refs.end_bbcccvvv >= ?)"
        for _ in passages
    )
    params: list = []
    for s, e in passages:
        params.extend([e, s])
    rows = db.execute(
        f"""
        SELECT DISTINCT chunks.id
        FROM chunks
        JOIN passage_refs ON passage_refs.doc_id = chunks.doc_id
        WHERE {where}
        ORDER BY passage_refs.start_bbcccvvv
        """,
        params,
    ).fetchall()
    cards = citations_mod.resolve_many(db, [r[0] for r in rows])
    return {
        "reference": ref,
        "passages": [list(p) for p in passages],
        "chunks": [chunk_preview_from_card(c, lang=args.get("lang", "en")) for c in cards],
    }


@register_tool(
    name="entity_lookup",
    description=(
        "Find chunks about a person, place, or biblical concept. Merges Door43 "
        "Translation Words and Aquifer ACAI entity tags so a single name "
        "returns hits from both taxonomies."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "entity": {"type": "string", "description": "Entity name (e.g. 'Boaz', 'justification')."},
            "type": {
                "type": "string",
                "enum": ["any", "person", "place", "keyterm", "deity", "event"],
                "default": "any",
            },
            "lang": {"type": "string", "default": "en"},
        },
        "required": ["entity"],
    },
)
def _entity_lookup(args: dict, db: sqlite3.Connection) -> dict:
    entity = args.get("entity", "").strip()
    if not entity:
        raise ValueError("'entity' is required")
    type_ = (args.get("type") or "any").lower()
    lang = args.get("lang", "en")

    candidates: set[str] = set()
    # Door43 TW: term:<lowercase>
    candidates.add(f"term:{entity.lower()}")
    # Aquifer ACAI: acai:<type>:<entity>
    if type_ == "any":
        for t in ("person", "place", "keyterm", "deity", "event"):
            candidates.add(f"acai:{t}:{entity}")
            candidates.add(f"acai:{t}:{entity.lower()}")
    else:
        candidates.add(f"acai:{type_}:{entity}")
        candidates.add(f"acai:{type_}:{entity.lower()}")

    placeholders = ",".join("?" * len(candidates))
    rows = db.execute(
        f"""
        SELECT DISTINCT chunks.id
        FROM chunks
        JOIN documents ON documents.id = chunks.doc_id
        JOIN tags ON tags.doc_id = documents.id
        WHERE tags.tag IN ({placeholders})
        LIMIT 100
        """,
        list(candidates),
    ).fetchall()
    cards = citations_mod.resolve_many(db, [r[0] for r in rows])
    return {
        "entity": entity,
        "type": type_,
        "lang": lang,
        "matched_tags_searched": sorted(candidates),
        "chunks": [chunk_preview_from_card(c, lang=lang) for c in cards],
    }


@register_tool(
    name="tree_listing",
    description=(
        "Walk one of the perspective trees over the corpus. Returns the children "
        "of the requested node (intermediate) or the chunks at this leaf "
        "(terminal). Use to navigate the corpus structurally — by Bible "
        "book/chapter/verse, by source, by content kind, by entity, etc."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "tree": {
                "type": "string",
                "enum": ["scripture", "source", "kind", "term", "methodology", "pericope", "aquifer"],
            },
            "path": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
            },
            "lang": {"type": "string", "default": "en"},
        },
        "required": ["tree"],
    },
)
def _tree_listing(args: dict, db: sqlite3.Connection) -> dict:
    tree = args.get("tree", "")
    builder = BUILDERS.get(tree)
    if builder is None:
        raise ValueError(f"unknown tree: {tree!r}")
    path = args.get("path") or []
    if not isinstance(path, list):
        raise ValueError("'path' must be a list of strings")
    lang = canon(args.get("lang", "en"))
    if not path:
        return builder.root(db, lang=lang)
    return builder.descend(db, [str(p) for p in path], lang=lang)


# NOTE: a server-side RAG `ask` tool (internal LLM synthesis) was intentionally
# removed — an MCP client is itself an LLM and should synthesize from the raw
# sources returned by `search` / `get_chunk` / `study`, so a server-side
# completion is redundant token cost. Synthesized RAG remains on REST /api/ask.


@register_tool(
    name="study",
    description=(
        "Deterministic Bible-study packet — NO LLM, $0. Runs the full retrieval "
        "pipeline (concept / LXX / morphology / clause expansion, cross-ref "
        "snowball, topic expansion) and returns ranked, CITED sources plus which "
        "strategies fired. Preferred RAG entry point: you synthesize the answer "
        "from these raw cited sources yourself."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "lang": {"type": "string", "default": "en"},
            "source": {"type": "string", "enum": ["all", "door43", "aquifer"], "default": "all"},
            "book": {"type": "string", "description": "optional USFM book filter, e.g. 'ROM'"},
            "top_k": {"type": "integer", "default": 10},
        },
        "required": ["question"],
    },
)
def _study(args: dict, db: sqlite3.Connection) -> dict:
    question = args.get("question", "").strip()
    if not question:
        raise ValueError("'question' is required")
    from server.routes.study import run_study
    return run_study(
        db,
        question,
        lang=args.get("lang", "en"),
        source_filter=args.get("source", "all"),
        book=args.get("book"),
        top_k=int(args.get("top_k", 10)),
    )


@register_tool(
    name="cross_references",
    description=(
        "Curated cross-references (TSK + BSB parallel passages) for a single Bible "
        "verse. Give a reference like 'Romans 5:1'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "reference": {"type": "string", "description": "e.g. 'Romans 5:1'"},
            "source": {"type": "string", "description": "'tsk' | 'bsb-parallel' | omit for all"},
            "limit": {"type": "integer", "default": 100},
        },
        "required": ["reference"],
    },
)
def _cross_references(args: dict, db: sqlite3.Connection) -> dict:
    ref = args.get("reference", "").strip()
    passages = parse_references(ref)
    if not passages:
        raise ValueError(f"could not parse Bible reference: {ref!r}")
    bb = passages[0][0]
    limit = max(1, min(int(args.get("limit", 100)), 500))
    sql = ("SELECT target_start_bbcccvvv, target_end_bbcccvvv, source_attribution, rank "
           "FROM cross_references WHERE source_bbcccvvv = ?")
    params: list = [bb]
    if args.get("source"):
        sql += " AND source_attribution = ?"
        params.append(args["source"])
    sql += " ORDER BY (rank IS NULL), rank ASC, target_start_bbcccvvv ASC LIMIT ?"
    params.append(limit)
    refs = []
    for s, e, attr, rank in db.execute(sql, params).fetchall():
        try:
            h = human(s, e)
        except Exception:
            h = f"BBCCCVVV {s}-{e}"
        refs.append({"target_start_bbcccvvv": s, "target_end_bbcccvvv": e,
                     "human": h, "source": attr, "rank": rank})
    try:
        src_h = human(bb, bb)
    except Exception:
        src_h = f"BBCCCVVV {bb}"
    return {"source_passage": {"bbcccvvv": bb, "human": src_h},
            "count": len(refs), "cross_references": refs}


@register_tool(
    name="concordance",
    description=(
        "Exhaustive concordance: every BSB verse containing an English word "
        "(case-insensitive, no stemming). The complete-listing companion to "
        "'search' (which is BM25-ranked, not exhaustive)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "word": {"type": "string"},
            "limit": {"type": "integer", "default": 500},
            "offset": {"type": "integer", "default": 0},
        },
        "required": ["word"],
    },
)
def _concordance(args: dict, db: sqlite3.Connection) -> dict:
    word = args.get("word", "").strip()
    if not word:
        raise ValueError("'word' is required")
    norm = word.lower()
    limit = max(1, min(int(args.get("limit", 500)), 2000))
    offset = max(0, int(args.get("offset", 0)))
    total = db.execute("SELECT COUNT(*) FROM english_concordance WHERE word_normalized = ?",
                       (norm,)).fetchone()[0]
    verses = []
    if total:
        for (bb,) in db.execute(
            "SELECT bbcccvvv FROM english_concordance WHERE word_normalized = ? "
            "ORDER BY bbcccvvv LIMIT ? OFFSET ?", (norm, limit, offset)).fetchall():
            try:
                h = human(bb, bb)
            except Exception:
                h = f"BBCCCVVV {bb}"
            verses.append({"bbcccvvv": bb, "human": h})
    return {"word": word, "verse_count": total, "limit": limit,
            "offset": offset, "verses": verses}


@register_tool(
    name="topics",
    description=(
        "Browse Nave's Topical Bible topics alphabetically (filter with "
        "'starts_with'). Use 'topic' (singular) to get a topic's verse list."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "starts_with": {"type": "string"},
            "source": {"type": "string"},
            "limit": {"type": "integer", "default": 100},
            "offset": {"type": "integer", "default": 0},
        },
    },
)
def _topics(args: dict, db: sqlite3.Connection) -> dict:
    limit = max(1, min(int(args.get("limit", 100)), 500))
    offset = max(0, int(args.get("offset", 0)))
    where: list[str] = []
    params: list = []
    if args.get("source"):
        where.append("source = ?")
        params.append(args["source"])
    if args.get("starts_with"):
        where.append("LOWER(name) LIKE ?")
        params.append(args["starts_with"].lower() + "%")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    rows = db.execute(
        f"SELECT id, name, source FROM topics{clause} ORDER BY name LIMIT ? OFFSET ?",
        [*params, limit, offset]).fetchall()
    total = db.execute(f"SELECT COUNT(*) FROM topics{clause}", params).fetchone()[0]
    return {"total": total, "limit": limit, "offset": offset,
            "topics": [{"id": r[0], "name": r[1], "source": r[2]} for r in rows]}


@register_tool(
    name="topic",
    description="Nave's topic detail: the topic name + every passage grouped under it.",
    input_schema={
        "type": "object",
        "properties": {"topic_id": {"type": "string"}},
        "required": ["topic_id"],
    },
)
def _topic(args: dict, db: sqlite3.Connection) -> dict:
    tid = args.get("topic_id", "").strip()
    row = db.execute("SELECT id, name, source FROM topics WHERE id = ?", (tid,)).fetchone()
    if row is None:
        raise ValueError(f"topic not found: {tid}")
    passages = []
    for s, e in db.execute("SELECT start_bbcccvvv, end_bbcccvvv FROM topic_passages "
                           "WHERE topic_id = ? ORDER BY start_bbcccvvv", (tid,)).fetchall():
        try:
            h = human(s, e)
        except Exception:
            h = f"BBCCCVVV {s}-{e}"
        passages.append({"start_bbcccvvv": s, "end_bbcccvvv": e, "human": h})
    return {"id": row[0], "name": row[1], "source": row[2],
            "passage_count": len(passages), "passages": passages}


# --- Original-language corpus (Hebrew BHSA / Greek Nestle1904, Context-Fabric) ---

def _corpus_engine():
    try:
        from corpus import engine
        return engine
    except Exception as e:  # engine optional — may be absent in some deployments
        raise ValueError(f"corpus engine unavailable: {e}")


@register_tool(
    name="corpus_books",
    description="List books in the original-language corpus (corpus='hebrew' BHSA or 'greek' Nestle1904).",
    input_schema={
        "type": "object",
        "properties": {"corpus": {"type": "string", "default": "hebrew"}},
    },
)
def _corpus_books(args: dict, db: sqlite3.Connection) -> dict:
    eng = _corpus_engine()
    return {"books": [b.model_dump() for b in eng.list_books(args.get("corpus", "hebrew"))]}


@register_tool(
    name="corpus_clauses",
    description="List clauses in the original-language corpus, optionally filtered by book / clause_type.",
    input_schema={
        "type": "object",
        "properties": {
            "corpus": {"type": "string", "default": "hebrew"},
            "book": {"type": "string"},
            "clause_type": {"type": "string"},
        },
    },
)
def _corpus_clauses(args: dict, db: sqlite3.Connection) -> dict:
    eng = _corpus_engine()
    return {"clauses": eng.list_clauses(args.get("corpus", "hebrew"),
                                        args.get("book"), args.get("clause_type"))}


@register_tool(
    name="corpus_passage",
    description=("Original-language passage (word-by-word morphosyntax) from the "
                 "Context-Fabric corpus. Specify book, chapter, verse_start[, verse_end]."),
    input_schema={
        "type": "object",
        "properties": {
            "book": {"type": "string"},
            "chapter": {"type": "integer"},
            "verse_start": {"type": "integer", "default": 1},
            "verse_end": {"type": "integer"},
            "corpus": {"type": "string", "default": "hebrew"},
        },
        "required": ["book", "chapter"],
    },
)
def _corpus_passage(args: dict, db: sqlite3.Connection) -> dict:
    eng = _corpus_engine()
    res = eng.get_passage(
        args["book"], int(args["chapter"]), int(args.get("verse_start", 1)),
        (int(args["verse_end"]) if args.get("verse_end") is not None else None),
        args.get("corpus", "hebrew"))
    return res.model_dump()


@register_tool(
    name="corpus_context",
    description="Clause/word context around a specific word in the original-language corpus.",
    input_schema={
        "type": "object",
        "properties": {
            "book": {"type": "string"},
            "chapter": {"type": "integer"},
            "verse": {"type": "integer"},
            "word_index": {"type": "integer", "default": 0},
            "corpus": {"type": "string", "default": "hebrew"},
        },
        "required": ["book", "chapter", "verse"],
    },
)
def _corpus_context(args: dict, db: sqlite3.Connection) -> dict:
    eng = _corpus_engine()
    return {"context": eng.get_context(
        args["book"], int(args["chapter"]), int(args["verse"]),
        int(args.get("word_index", 0)), args.get("corpus", "hebrew"))}
