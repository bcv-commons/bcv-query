# Architecture

## Overview

```
Question → Analyzer → [3 auto-strategies] → 13 Retrievers → RRF → [3 opt-in strategies] → Answer
                                                                         ↑
                                                              LLM synthesis (Mode C only)
```

One SQLite file (`index.db`) holds everything: documents, chunks, FTS5 index, sqlite-vec vectors (1024d BGE-M3), passage references (BBCCCVVV), and tags. The corpus engine (BHSA/Nestle1904) runs locally as an embedded module.

## Analyzer

Extracts from the question: FTS keywords, passage references (BBCCCVVV), tags, and intent. Ten intent types: `thematic`, `entity_lookup`, `passage_specific`, `passage_book`, `methodology`, `word_study`, `morphology`, `genealogy`, `topic`, `xref`. Each intent weights the retrievers differently via RRF.

## Automatic pre-processing (before retrieval)

| # | Strategy | Latency | What it does |
|---|----------|---------|-------------|
| 1 | Concept expansion | <1ms | Query words → Strong's tags via reverse gloss |
| 2 | LXX bridge | ~50ms | Hebrew Strong's → Greek via Septuagint |
| 3 | Morph pre-filter | ~50-150ms | Morph keywords → passage filter from shoresh |

## 13 Retrievers

Each returns scored hits. RRF fuses them with intent-specific weights.

| # | Retriever | Source |
|---|-----------|--------|
| 1 | FTS (body) | `chunks_fts` (porter stemming) |
| 2 | FTS (title) | `documents.title` |
| 3 | Passage | `passage_refs` range overlap |
| 4 | Scripture | Dual-pass within `kind:scripture` |
| 5 | Tag | Exact match (`strongs:`, `term:`, `kind:`) |
| 6 | Vector | sqlite-vec ANN (1024d BGE-M3) |
| 7 | Lexicon | Strong's / lemma / gloss lookup |
| 8 | Morphology | Strong's / lemma / passage parse |
| 9 | Entity | Theographic graph traversal |
| 10 | Bible | BSB verse text with consolidation |
| 11 | Topic | Nave's topical index |
| 12 | Cross-ref | TSK + BSB parallel traversal |
| 13 | Corpus | BHSA/Nestle1904 structural context (local) |

## Opt-in post-processing (`"expand"` parameter)

| # | Strategy | Latency | What it does |
|---|----------|---------|-------------|
| 4 | Clause→RAG | +200-500ms | BGE-M3 clause search → passage filter |
| 5 | Cross-ref snowball | +100-200ms | Follow xrefs one hop, second-pass retrieval |
| 6 | Topic→clause | +300-600ms | Nave's → Strong's → clause search expansion |

## Embedding

Split architecture:
- **Ingest:** BGE-M3 locally via `sentence-transformers` (~30 min for 238k chunks)
- **Query:** BGE-M3 via Cloudflare Workers AI ($0, <1s)

Providers: `cloudflare` (default), `bge-m3-local`, `voyage`, `openai`. Configured via `BTMCP_EMBEDDING_MODEL` and `BTMCP_EMBEDDING_PROVIDER`.

## Synthesis (Mode C)

LLM generates a cited answer from the top-K chunks. Groq (llama-3.3-70b) primary, OpenAI (gpt-4o-mini) fallback. Strict citation constraint — every claim must reference a source chunk.

## Corpus engine

BHSA (39 Hebrew books) + Nestle 1904 (27 Greek books) via Context-Fabric, embedded as a local module. Provides morphological annotations, syntactic structure (clause/phrase/sentence hierarchy), vocabulary, and lexeme data. No network dependency.

## shoresh integration

bcv-RAG calls [shoresh](../../shoresh/) for:
- **Bridge 1** — enrich citations with original-language words
- **Strategy 2** — LXX bridge expansion (Hebrew Strong's → Greek)
- **Strategy 3** — morphological pre-filter
- **Strategies 4, 6** — clause search and topic→clause expansion

Connection: `SHORESH_URL` (a private-network or public URL for the shoresh service).
