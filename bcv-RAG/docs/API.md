# API Reference

All endpoints are under `/api`. Base URL: `https://<your-host>/api` (locally,
`http://localhost:8000/api`).

The `lang` parameter takes a canonical **ISO 639-3 / BCP 47** code (`eng`, `spa`,
`arb`, `cmn-Hant`, …); legacy 2-letter codes (`en`, `es`) are also accepted.

## Core

### POST /api/ask

Full RAG: question → cited answer.

```json
{
  "question": "What does the Bible say about mercy?",
  "lang": "eng",
  "top_k": 10,
  "scope": {"source": "all", "book": null},
  "expand": []
}
```

`expand` enables multi-step strategies (all $0):
- `"clause"` — BEREL/BGE-M3 clause search → passage filter (+200-500ms)
- `"crossref"` — follow cross-references one hop, merge via RRF (+100-200ms)
- `"topic"` — Nave's → Strong's → clause search expansion (+300-600ms)
- `"all"` — enables all three

Response includes `answer`, `citations` (with `original_words` from shoresh when available), `confidence`, and `analysis`.

### GET /api/search

Retrieval only (no LLM). Returns ranked chunks.

| Param | Default | Description |
|-------|---------|-------------|
| `q` | required | Search query |
| `top_k` | 10 | Max results |
| `use_semantic` | false | Enable vector ANN (needs embedding API key) |

### GET /api/health

Returns `{"status": "ok", "ready": true, ...}` with index stats.

## Lookup

### GET /api/chunk/{chunk_id}

Raw chunk by ID.

### GET /api/cross-references/{bbcccvvv}

Cross-references for a verse. `bbcccvvv` is the 8-digit encoding (e.g., `45003024` = Romans 3:24).

### GET /api/concordance/{word}

Every occurrence of a word across indexed content.

### GET /api/entity/{entity_id}

Theographic entity (person, place, event) with relationships.

### GET /api/entities

List/search entities. Params: `q`, `type` (person/place/event).

### GET /api/topic/{topic_id}

Nave's topic with verse references.

### GET /api/topics

List/search topics. Param: `q`.

## Corpus (BHSA/Nestle1904)

Embedded Context-Fabric engine. No external dependency.

### GET /api/books

List books with chapter counts. Param: `corpus` (`hebrew` or `greek`).

### GET /api/clauses

List clause-level units. Params: `corpus`, `book`, `clause_type`.

### GET /api/passage

Verse text with per-word morphological annotations. Params: `book`, `chapter`, `verse_start`, `verse_end`, `corpus`.

### GET /api/context

Linguistic hierarchy for a word. Params: `book`, `chapter`, `verse`, `word_index`, `corpus`.

## Trees

### GET /api/trees

Available tree roots (Bible, topics, entities, sources, etc.).

### GET /api/tree/{name}/{path}

Navigate hierarchical tree. Returns children with labels and counts.

## MCP

The same tools are available via Model Context Protocol at `/mcp`. Default tools make zero LLM calls. See the MCP endpoint for tool discovery.

## Three access modes

| Mode | What runs | Cost |
|------|-----------|------|
| **A** | All retrievers + strategies + corpus engine. No API keys needed. | $0 |
| **B** | A + hosted reranker | ~$0.002/query |
| **C** | B + LLM synthesis (`/api/ask`) | LLM tokens |

`/api/search` and all lookup/corpus endpoints work in Mode A. Only `/api/ask` requires Mode C (LLM key).
