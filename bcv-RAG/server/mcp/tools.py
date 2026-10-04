"""MCP tool definitions and handlers.

Each tool is a thin wrapper over the underlying retrieval / resolver code.
Handlers take (arguments: dict, db: sqlite3.Connection) and return the
JSON-serializable result dict that goes into the MCP `content` text body.
"""
from __future__ import annotations

import collections
import functools
import json
import sqlite3
from typing import Callable

from indexer import citations as citations_mod
from indexer.db import has_vec
from indexer.references import decode, human, parse_references
from query.analyzer import analyze
from query.concept_expand import expand_concepts, filter_biblical_words
from query.lang_detect import resolve_lang
from query.retrieve import retrieve
from server.corpus_cards import resolve_corpus_hits
from server.resolver import chunk_preview_from_card, resolve_chunk
from server.trees import BUILDERS
from lang import canon, to_web

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

# shared retrieval fields for `search` / `semantic_search` (identical except the vector step)
_SEARCH_PROPS = {
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
}


@register_tool(
    name="search",
    description=(
        "Search the indexed Bible-translation corpus (lexical). Returns ranked chunks "
        "with metadata; does NOT generate an answer — caller (you) should read the "
        "chunks and synthesize.\n\n"
        "FTS5 keyword matching, passage-range matching, title matching, tag filters, and "
        "automatic concept expansion (query words → Strong's-anchored related terms) fused "
        "with reciprocal rank fusion — no model calls, no API key, deterministic, $0. For "
        "paraphrased queries, rephrase and search again; the concept expansion widens matches."
    ),
    input_schema={"type": "object", "properties": dict(_SEARCH_PROPS), "required": ["query"]},
)
def _search(args: dict, db: sqlite3.Connection) -> dict:
    return _run_search(args, db, semantic=False)


# NB: semantic/vector search is intentionally NOT an MCP tool — it's the one paid
# (embedding) path and stays REST-only (`GET /api/search?semantic=true`, key-gated). The
# MCP surface is uniformly $0; concept expansion (below) makes lexical search meaning-aware.
def _run_search(args: dict, db: sqlite3.Connection, semantic: bool = False) -> dict:
    q = args.get("query", "").strip()
    if not q:
        raise ValueError("'query' is required and non-empty")
    lang = args.get("lang", "en")
    top_k = int(args.get("top_k", 10))

    analysis = analyze(q, lang=lang)
    if args.get("kind"):
        analysis.tags.append(f"kind:{args['kind']}")
    if args.get("book"):
        analysis.tags.append(f"book:{str(args['book']).upper()}")
    # concept expansion (query words → Strong's tags → related terms): makes lexical
    # search meaning-aware without a vector — the $0 stand-in for semantic_search.
    if canon(lang) != "eng":
        analysis.fts_query = filter_biblical_words(q, lang=lang)
    analysis.tags.extend(expand_concepts(analysis.fts_query, analysis.tags, lang=lang))

    query_vec = None
    if semantic and has_vec(db):
        from indexer.embed import embed_texts
        query_vec = embed_texts([q], input_type="query")[0]

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
            "lang": {"type": "string",
                     "description": "ISO 639-3 (spa/fra/…). Omit or pass 'auto' to "
                                    "detect the language from the query text."},
            "book": {"type": "string", "description": "USFM book code (e.g. 'TIT')."},
            "source": {"type": "string", "enum": ["all", "door43", "aquifer"], "default": "all"},
            "per_branch": {"type": "integer", "default": 8, "minimum": 1, "maximum": 50,
                           "description": "Max hits returned per branch."},
            "force": {
                "type": "array", "items": {"type": "string"},
                "description": "Branch keys to force-expand even if the intent didn't "
                               "feature them, e.g. ['lexicon','morphology'].",
            },
        },
        "required": ["query"],
    },
)
def _search_branched(args: dict, db: sqlite3.Connection) -> dict:
    q = args.get("query", "").strip()
    if not q:
        raise ValueError("'query' is required and non-empty")
    lang = resolve_lang(q, args.get("lang"))   # absent/"auto" → detect

    analysis = analyze(q, lang=lang)
    if canon(lang) != "eng":
        analysis.fts_query = filter_biblical_words(q, lang=lang)
    if args.get("book"):
        analysis.tags.append(f"book:{str(args['book']).upper()}")

    query_vec = None   # lexical/structured only ($0); for meaning-based ranking use semantic_search
    from server.branched import build_branches
    from server.cards import suggested_layout
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
        "suggested_layout": suggested_layout(result["branches"]),   # advisory (Phase 3)
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


@functools.lru_cache(maxsize=1)
def _lex_sense_inventory() -> dict:
    """{(lex, stem): [(sense, gloss, share)]} from resources/senses/hbo_lex.tsv — the
    Hebrew-context-derived sense inventory (sense identity decided in Hebrew, gloss = label)."""
    from resource_paths import resource_path
    out: dict = collections.defaultdict(list)
    p = resource_path("senses/hbo_lex.tsv")
    if p.exists():
        with open(p, encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) == 6:
                    lex, stem, sense, gloss, _count, share = parts
                    out[(lex, stem)].append((sense, gloss, round(float(share), 3)))
    return out


@register_tool(
    name="morphology_concordance",
    description=(
        "Concordance by BHSA lexeme + verbal stem (binyan) + sense: every verse where a "
        "Hebrew lexeme occurs in a given stem and/or sense. A PRECISE structured lookup (not "
        "fuzzy search) over BHSA-derived tags — separating distinctions Strong's can't. "
        "lex='QDC[', stem='hif' → verses where קדשׁ is causative, distinct from stem='piel'; "
        "it distinguishes homographs a single Strong's conflates; and senses are derived from "
        "HEBREW context (e.g. lex='>B/' sense='1' = 'father', sense='2' = a distinct usage). "
        "The response lists the available `senses` for the lex+stem so you can drill in via "
        "`sense`. `lex` is the BHSA lex-id (from shoresh /words or /wordstudy). Omit `stem`/"
        "`sense` to broaden."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "lex": {"type": "string", "description": "BHSA lex-id, e.g. 'QDC[' (qadash)."},
            "stem": {
                "type": "string",
                "description": "Verbal stem / binyan, e.g. 'qal','nif','piel','hif'. Omit for any.",
            },
            "sense": {
                "type": "string",
                "description": "Sense number within the lex+stem (see `senses` in the response). Omit for all.",
            },
            "top_k": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500},
            "lang": {"type": "string", "default": "en"},
        },
        "required": ["lex"],
    },
)
def _morphology_concordance(args: dict, db: sqlite3.Connection) -> dict:
    lex = args.get("lex", "").strip()
    if not lex:
        raise ValueError("'lex' is required (BHSA lex-id, e.g. 'QDC[')")
    stem = args.get("stem", "").strip()
    sense = str(args.get("sense", "")).strip()
    top_k = int(args.get("top_k", 50))
    if sense:
        tag = f"sense:{lex}.{stem}.{sense}"
    elif stem:
        tag = f"lexstem:{lex}.{stem}"
    else:
        tag = f"lex:{lex}"
    total = db.execute("SELECT count(*) FROM tags WHERE tag = ?", (tag,)).fetchone()[0]
    rows = db.execute(
        """
        SELECT chunks.id
        FROM chunks
        JOIN tags ON tags.doc_id = chunks.doc_id AND tags.tag = ?
        JOIN passage_refs ON passage_refs.doc_id = chunks.doc_id
        ORDER BY passage_refs.start_bbcccvvv
        LIMIT ?
        """,
        (tag, top_k),
    ).fetchall()
    cards = citations_mod.resolve_many(db, [r[0] for r in rows])
    inv = _lex_sense_inventory().get((lex, stem), [])
    out = {
        "lex": lex,
        "stem": stem or None,
        "sense": sense or None,
        "tag": tag,
        "total": total,
        "senses": [{"sense": s, "gloss": g, "share": sh} for s, g, sh in inv],
        "verses": [chunk_preview_from_card(c, lang=args.get("lang", "en")) for c in cards],
    }
    if sense:
        out["sense_gloss"] = next((g for s, g, _sh in inv if s == sense), None)
    return out


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


# ---------- Torah literary-unit structure (Kline's "Woven Torah", CC BY 4.0) ----------
#
# Cited third-party content, not something this project derives or validates — see
# ingest/torah_weave.py's docstring. `_KLINE_ATTRIBUTION` is included on every response; CC BY
# requires it, and it also keeps the tool's output honestly labeled as someone else's structural
# claim rather than something bcv-query itself determined.
_KLINE_ATTRIBUTION = {
    "author": "Moshe Kline",
    "citation": "Before Chapter and Verse: Reading the Woven Torah (self-published, 2022)",
    "url": "https://chaver.com",
    "license": "CC BY 4.0",
}


def _torah_verse_text(db: sqlite3.Connection, start: int, end: int, lang: str) -> str | None:
    """Best-effort: this language's chunk body covering [start, end], or None if not indexed."""
    lang_tag = f"lang:{to_web(canon(lang))}"
    rows = db.execute(
        "SELECT chunks.body FROM chunks "
        "JOIN passage_refs ON passage_refs.doc_id = chunks.doc_id "
        "WHERE passage_refs.start_bbcccvvv <= ? AND passage_refs.end_bbcccvvv >= ? "
        "AND EXISTS (SELECT 1 FROM tags WHERE doc_id = chunks.doc_id AND tag = 'kind:bible') "
        "AND EXISTS (SELECT 1 FROM tags WHERE doc_id = chunks.doc_id AND tag = ?) "
        "ORDER BY passage_refs.start_bbcccvvv",
        (end, start, lang_tag),
    ).fetchall()
    if not rows:
        return None
    # Some languages carry more than one kind:bible-tagged chunk per verse (e.g. an aligned pass
    # plus a separate plain-text OT-completion pass, see ingest/bible_text.py) — dedupe identical
    # bodies rather than concatenating repeats, order-preserving.
    bodies = list(dict.fromkeys(r[0] for r in rows if r[0]))
    return " ".join(bodies) if bodies else None


def _torah_shared_lexemes(start_a: int, end_a: int, start_b: int, end_b: int) -> list[str] | None:
    """Strong's numbers occurring in BOTH verse ranges (hbo.db) — best-effort, never raises."""
    try:
        import sqlite3 as _sqlite3
        from resource_paths import resource_path
        hbo = _sqlite3.connect(f"file:{resource_path('occurrences/hbo.db')}?mode=ro", uri=True)
    except Exception:
        return None

    def _strongs(start: int, end: int) -> set[str]:
        b1, c1, v1 = decode(start)
        b2, c2, v2 = decode(end)
        if b1 != b2:
            return set()  # Kline's cells never cross books; a defensive no-op if that ever changes
        rows = hbo.execute(
            "SELECT DISTINCT strong FROM occurrence WHERE book = ? AND strong != '' "
            "AND (chapter > ? OR (chapter = ? AND verse >= ?)) "
            "AND (chapter < ? OR (chapter = ? AND verse <= ?))",
            (b1, c1, c1, v1, c2, c2, v2),
        ).fetchall()
        return {r[0] for r in rows}

    try:
        shared = sorted(_strongs(start_a, end_a) & _strongs(start_b, end_b))
    except Exception:
        return None
    finally:
        hbo.close()
    return shared or None


@register_tool(
    name="torah_unit_lookup",
    description=(
        "Look up which of Moshe Kline's 86 'Woven Torah' literary units (CC BY 4.0) a Torah verse "
        "falls in, and its claimed structurally-paired cell(s) — a cited literary-structure "
        "hypothesis, not a bcv-query claim. Optionally overlays the paired verses in another "
        "language and any Strong's numbers repeated between them, both best-effort."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "reference": {"type": "string", "description": "A Torah verse, e.g. 'Genesis 1:14'"},
            "lang": {"type": "string", "default": "en", "description": "Overlay the paired verses in this language, if indexed."},
        },
        "required": ["reference"],
    },
)
def _torah_unit_lookup(args: dict, db: sqlite3.Connection) -> dict:
    ref = args.get("reference", "").strip()
    passages = parse_references(ref)
    if not passages:
        raise ValueError(f"could not parse Bible reference: {ref!r}")
    bb = passages[0][0]
    lang = args.get("lang", "en")

    row = db.execute(
        "SELECT c.unit_id, c.cell_label, c.row_number, c.column_letter, c.subdivision, "
        "       c.start_bbcccvvv, c.end_bbcccvvv, u.title, u.format, u.unit_type "
        "FROM torah_unit_cells c JOIN torah_units u ON u.unit_id = c.unit_id "
        "WHERE c.start_bbcccvvv <= ? AND c.end_bbcccvvv >= ? LIMIT 1",
        (bb, bb),
    ).fetchone()
    if row is None:
        return {"reference": human(bb, bb), "in_torah_unit": False, "attribution": _KLINE_ATTRIBUTION}

    (unit_id, cell_label, row_number, column_letter, subdivision,
     c_start, c_end, title, fmt, unit_type) = row

    partners = db.execute(
        "SELECT cell_label, column_letter, start_bbcccvvv, end_bbcccvvv FROM torah_unit_cells "
        "WHERE unit_id = ? AND row_number = ? "
        "AND subdivision IS ? AND cell_label != ? ORDER BY column_letter",
        (unit_id, row_number, subdivision, cell_label),
    ).fetchall()

    cell_out = {
        "cell_label": cell_label, "verses": human(c_start, c_end),
        "start_bbcccvvv": c_start, "end_bbcccvvv": c_end,
    }
    if lang != "en":
        text = _torah_verse_text(db, c_start, c_end, lang)
        if text:
            cell_out["text"] = text

    partner_out = []
    for p_label, p_col, p_start, p_end in partners:
        p = {"cell_label": p_label, "verses": human(p_start, p_end),
             "start_bbcccvvv": p_start, "end_bbcccvvv": p_end}
        if lang != "en":
            text = _torah_verse_text(db, p_start, p_end, lang)
            if text:
                p["text"] = text
        shared = _torah_shared_lexemes(c_start, c_end, p_start, p_end)
        if shared:
            p["shared_strongs"] = shared
        partner_out.append(p)

    return {
        "reference": human(bb, bb),
        "in_torah_unit": True,
        "unit": {"unit_id": unit_id, "title": title, "format": fmt, "unit_type": unit_type},
        "cell": cell_out,
        "structural_partners": partner_out,
        "attribution": _KLINE_ATTRIBUTION,
    }


@register_tool(
    name="torah_units",
    description=(
        "Browse Moshe Kline's 86 'Woven Torah' literary units (CC BY 4.0) as a Torah outline — "
        "title and verse range per unit, independent of the row/column pairing claim."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "book": {"type": "string", "description": "USFM code to filter to one book, e.g. 'GEN'"},
        },
    },
)
def _torah_units(args: dict, db: sqlite3.Connection) -> dict:
    sql = ("SELECT serial_number, book, unit_number, title, start_bbcccvvv, end_bbcccvvv, format "
           "FROM torah_units")
    params: list = []
    if args.get("book"):
        sql += " WHERE book = ?"
        params.append(args["book"].upper())
    sql += " ORDER BY serial_number"
    units = [
        {"serial_number": s, "book": b, "unit_number": n, "title": t,
         "verses": human(a, e), "format": f}
        for s, b, n, t, a, e, f in db.execute(sql, params).fetchall()
    ]
    return {"count": len(units), "units": units, "attribution": _KLINE_ATTRIBUTION}


# ---------- BHSA clause-level dependency graph ----------
#
# Discourse structure (which clause grammatically depends on which, and how), not a lexical/word-pair
# signal -- see indexer/schema.sql's clause_dependencies comment for the full caveat list. Surfaced
# in every response so a caller can't miss it, same posture as the Torah attribution above.
_CLAUSE_DEP_CAVEAT = (
    "BHSA clause-level dependency (Objc/Attr/Adju/Coor/Resu/...), not a bcv-query claim -- Context "
    "Fabric reports grammatical annotation, it doesn't infer. One caveat worth knowing before reading "
    "'depth' as meaningful: a long flat coordinated list (Coor chains, e.g. a genealogy/name roster) "
    "chains exactly as deep as genuine narrative subordination -- checked directly, this dataset's "
    "single deepest chain (20 clauses) is 1 Chronicles 11:27's roster of names, not an argument."
)


@register_tool(
    name="clause_dependency_lookup",
    description=(
        "A verse's clause-level BHSA dependency structure: which of its clauses depend on which "
        "other clause/phrase/word, and how (Objc/Attr/Adju/Coor/Resu/...) -- discourse structure, "
        "'why does this clause relate to that one', not word-level syntax. Also reports which OTHER "
        "clauses depend on this verse's clauses (the reverse direction), so a governing/'hub' clause "
        "shows its full set of dependents. Hebrew Bible only."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "reference": {"type": "string", "description": "A Hebrew Bible verse, e.g. 'Zechariah 8:14'"},
        },
        "required": ["reference"],
    },
)
def _clause_dependency_lookup(args: dict, db: sqlite3.Connection) -> dict:
    ref = args.get("reference", "").strip()
    passages = parse_references(ref)
    if not passages:
        raise ValueError(f"could not parse Bible reference: {ref!r}")
    bb = passages[0][0]

    as_dependent = db.execute(
        "SELECT dependent_text, mother_text, mother_otype, mother_start_bbcccvvv, "
        "mother_end_bbcccvvv, rela FROM clause_dependencies "
        "WHERE dependent_start_bbcccvvv <= ? AND dependent_end_bbcccvvv >= ?",
        (bb, bb),
    ).fetchall()
    as_mother = db.execute(
        "SELECT mother_text, dependent_text, rela FROM clause_dependencies "
        "WHERE mother_start_bbcccvvv <= ? AND mother_end_bbcccvvv >= ? AND mother_otype = 'clause'",
        (bb, bb),
    ).fetchall()

    depends_on = [
        {"clause": dep_txt, "depends_on": mom_txt, "mother_otype": mom_ot,
         "mother_reference": human(mom_s, mom_e), "rela": rela}
        for dep_txt, mom_txt, mom_ot, mom_s, mom_e, rela in as_dependent
    ]
    dependents = [
        {"clause": mom_txt, "dependent_clause": dep_txt, "rela": rela}
        for mom_txt, dep_txt, rela in as_mother
    ]
    return {
        "reference": human(bb, bb),
        "depends_on": depends_on,
        "dependents_of_this_verses_clauses": dependents,
        "note": _CLAUSE_DEP_CAVEAT,
    }


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


# ---------- original-language tools (shoresh-backed, over private networking, $0) ----------

def _ref_to_bcv(reference: str) -> tuple[str, int, int]:
    """'John 3:16' / 'JHN 3:16' → (USFM, chapter, verse). Raises on no single-verse ref."""
    refs = parse_references(reference or "")
    if not refs:
        raise ValueError(f"could not parse a verse reference from {reference!r}")
    code, ch, v = decode(refs[0][0])
    return code, ch, v


def _glang(lang: str | None) -> str:
    from server.cards import _gloss_lang       # lazy: avoid import cycle
    return _gloss_lang(lang or "en")


@register_tool(
    name="word_study",
    description=(
        "Original-language word study for a Strong's number (Hebrew H#### or Greek G####). "
        "Returns the localized gloss, keyness (how distinctively biblical), per-binyan stem "
        "senses (Hebrew verbs), sense distribution, semantic domains (Louw-Nida; for Hebrew also the "
        "CC0 semantic `group`, named by a Hebrew exemplar word, with a high/extended confidence), related "
        "lexemes, and Translation-Words article(s). $0, no model. Localized via `lang`."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "strong": {"type": "string", "description": "Strong's number, e.g. 'G0025' or 'H0430'."},
            "lang": {"type": "string", "default": "en"},
        },
        "required": ["strong"],
    },
)
def _word_study(args: dict, db: sqlite3.Connection) -> dict:
    from server.original_words import shoresh_get
    s = str(args.get("strong", "")).strip()
    if not s:
        raise ValueError("'strong' is required")
    return shoresh_get(f"/wordstudy/{s}", {"gloss_lang": _glang(args.get("lang"))}) or {"strong": s, "unavailable": True}


@register_tool(
    name="verse_interlinear",
    description=(
        "Per-word interlinear for a verse: each original word with surface, lemma, Strong's, "
        "morphology, localized gloss, binyan-correct sense (Hebrew), and domain: Louw-Nida (Greek) or "
        "the Hebrew semantic group as 'Hebrew label · gloss' (Hebrew), plus the LXX parallel for OT "
        "verses. $0. Localized via `lang`."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "reference": {"type": "string", "description": "A single verse, e.g. 'John 3:16'."},
            "lang": {"type": "string", "default": "en"},
        },
        "required": ["reference"],
    },
)
def _verse_interlinear(args: dict, db: sqlite3.Connection) -> dict:
    from server.original_words import verse_interlinear
    code, ch, v = _ref_to_bcv(args.get("reference", ""))
    return verse_interlinear(code, ch, v, _glang(args.get("lang"))) or {"reference": args.get("reference"), "unavailable": True}


@register_tool(
    name="verse_syntax",
    description=(
        "Clause→phrase syntax tree for a verse (who-did-what): clauses with type/relation, "
        "phrases with grammatical function and their words. Hebrew (BHSA) / Greek (Nestle1904). $0."
    ),
    input_schema={
        "type": "object",
        "properties": {"reference": {"type": "string", "description": "A single verse, e.g. 'Genesis 1:1'."}},
        "required": ["reference"],
    },
)
def _verse_syntax(args: dict, db: sqlite3.Connection) -> dict:
    from server.original_words import verse_syntax
    code, ch, v = _ref_to_bcv(args.get("reference", ""))
    return verse_syntax(code, ch, v) or {"reference": args.get("reference"), "unavailable": True}


@register_tool(
    name="lexeme_profile",
    description=(
        "Profile of a BHSA/Nestle1904 lexeme (the granular original anchor): stems × senses × "
        "counts × sample references × gloss. Deeper than a Strong's number (Strong's conflates "
        "homographs). $0. Localized via `lang`."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "lex": {"type": "string", "description": "BHSA lex (Hebrew, e.g. 'QDC[') or Nestle1904 lemma (Greek)."},
            "lang": {"type": "string", "default": "en"},
        },
        "required": ["lex"],
    },
)
def _lexeme_profile(args: dict, db: sqlite3.Connection) -> dict:
    from server.original_words import shoresh_get
    lex = str(args.get("lex", "")).strip()
    if not lex:
        raise ValueError("'lex' is required")
    return shoresh_get(f"/lexeme/{lex}", {"gloss_lang": _glang(args.get("lang"))}) or {"lex": lex, "unavailable": True}


@register_tool(
    name="semantic_domain",
    description=(
        "Every lexeme in a semantic domain or group, glossed — 'all the words for Love/Affection'. "
        "axis=sdbg (default): Louw-Nida domain, Greek + the Hebrew the LXX renders into it (codes like "
        "'025003'). axis=group: a Hebrew semantic group (CC0, ids like 'c27', named by a Hebrew exemplar "
        "word; find a word's group via word_study or verse_interlinear). axis=setting: a Hebrew setting "
        "(ids 's01'-'s40'; the topical setting words are used in, e.g. altar/burnt offering, battle, "
        "household; found per word in verse_interlinear and word_study). $0. Localized via `lang`."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Domain code ('025003'), group id ('c27') or setting id ('s01')."},
            "axis": {"type": "string", "enum": ["sdbg", "group", "setting"], "default": "sdbg"},
            "lang": {"type": "string", "default": "en"},
        },
        "required": ["code"],
    },
)
def _semantic_domain(args: dict, db: sqlite3.Connection) -> dict:
    from server.original_words import shoresh_get
    code = str(args.get("code", "")).strip()
    if not code:
        raise ValueError("'code' is required")
    axis = str(args.get("axis") or "sdbg").strip()
    return (shoresh_get(f"/domain/{code}", {"gloss_lang": _glang(args.get("lang")), "axis": axis})
            or {"code": code, "unavailable": True})


@register_tool(
    name="cross_language",
    description=(
        "Hebrew↔Greek equivalents for a Strong's number via the Septuagint (LXX) bridge — how a "
        "Hebrew word was rendered in Greek (or vice versa), with counts. $0."
    ),
    input_schema={
        "type": "object",
        "properties": {"strong": {"type": "string", "description": "Strong's number, e.g. 'H0430'."}},
        "required": ["strong"],
    },
)
def _cross_language(args: dict, db: sqlite3.Connection) -> dict:
    from server.original_words import shoresh_get
    s = str(args.get("strong", "")).strip()
    if not s:
        raise ValueError("'strong' is required")
    return shoresh_get(f"/bridge/{s}") or {"strong": s, "unavailable": True}
