# bcv-RAG — retrieval & Q&A, explained

bcv-RAG answers questions about the Bible. You ask in plain language (in any of 11
languages) and it returns a **cited answer** drawn from Bible translations and
study resources — or, if you'd rather, just the **ranked source passages** with no
LLM involved at all.

This page is the friendly tour. To **connect a client** and call the service, see the
[Client Integration Guide](client-guide.md). For the exact request/response shapes see
[`bcv-RAG/docs/API.md`](../bcv-RAG/docs/API.md); for the internals see
[`bcv-RAG/docs/architecture.md`](../bcv-RAG/docs/architecture.md).

---

## Why it's different

Most Bible search matches the *words you typed*. bcv-RAG also matches the
*concept behind them*, by translating your query words into **Strong's numbers**
(stable ids for the underlying Hebrew/Greek words). So a search for Spanish *fe*
("faith") can find passages tagged with the Greek concept even when the surface
word differs — and a name in one language resolves to the same biblical person as
in any other. This original-language anchoring runs through the whole pipeline.

## Three cost modes — you choose

You can run bcv-RAG completely free, or layer on quality where it's worth paying.

| Mode | What runs | Needs | Cost |
|---|---|---|---|
| **A** | All 13 retrievers + expansion strategies + the embedded corpus engine. Keyword (FTS) and, if you add an embedding key, vector search. | nothing (vectors optional) | **$0** |
| **B** | Mode A + a hosted reranker for sharper ordering | reranker access | ~$0.002 / query |
| **C** | Mode B + LLM synthesis — the cited natural-language answer (`/api/ask`) | an LLM key (Groq or OpenAI) | LLM tokens |

`/api/search` and every lookup/corpus endpoint work in **Mode A**. Only
`/api/ask` requires an LLM key. Query embedding (for vector search) is done via
Cloudflare Workers AI, which is also $0.

## How a question flows

```
Question → Analyzer → [3 automatic strategies] → 13 Retrievers → RRF fusion → [3 opt-in strategies] → Answer
                                                                                       ↑
                                                                       LLM synthesis (Mode C only)
```

1. **Analyzer** reads the question and extracts keywords, any passage references
   (e.g. "Romans 3:24"), Strong's/term tags, and an **intent** (one of ten:
   thematic, entity lookup, passage, methodology, word study, morphology,
   genealogy, topic, cross-reference, …). The intent decides how the retrievers
   are weighted. Each language has its own analyzer config in
   [`resources/analyzer_lang/`](../resources/analyzer_lang).

2. **Automatic pre-processing** (fast, always on):
   - **Concept expansion** (<1 ms) — query words → Strong's tags via reverse gloss.
   - **LXX bridge** (~50 ms) — Hebrew Strong's → Greek via the Septuagint (calls shoresh).
   - **Morph pre-filter** (~50–150 ms) — morphology keywords → a passage filter (calls shoresh).

3. **13 retrievers** each score the corpus a different way — full-text, title,
   passage-range, scripture, tag, vector (ANN), lexicon, morphology, entity
   graph, Bible text, topical, cross-reference, and the embedded corpus engine.

4. **RRF fusion** (Reciprocal Rank Fusion) merges all 13 ranked lists into one,
   using the intent-specific weights from step 1.

5. **Opt-in post-processing** (pass `expand`): clause→RAG search, cross-reference
   "snowball" (follow xrefs one hop), and topic→clause expansion. All $0; each
   adds a few hundred ms.

6. **Synthesis (Mode C only)** — an LLM writes a cited answer from the top
   passages, with a strict rule that every claim must point at a source chunk.
   Answers come back in the query's language. The model is configurable via the
   `GROQ_MODEL` env var (reasoning models supported via `GROQ_REASONING_EFFORT`).

Everything lives in **one SQLite file** (`index.db`): documents, chunks, an FTS5
full-text index, `sqlite-vec` vectors (1024-d BGE-M3), passage references, and
tags. The Hebrew/Greek **corpus engine** (BHSA + Nestle 1904, via Text/Context-
Fabric) is embedded as a local module — no network call.

## Three ways to use it

- **REST API** — `POST /api/ask`, `GET /api/search`, plus lookups
  (`/api/chunk`, `/api/cross-references`, `/api/concordance`, `/api/entity`,
  `/api/topic`) and corpus endpoints (`/api/books`, `/api/clauses`,
  `/api/passage`, `/api/context`, `/api/trees`). Full reference:
  [API.md](../bcv-RAG/docs/API.md).
- **MCP server** — the same capabilities as read-only tools over the Model
  Context Protocol (at `/mcp`): `search`, `get_chunk`, `passage_lookup`,
  `entity_lookup`, `tree_listing`, `study`, `cross_references`, `concordance`,
  `morphology_concordance` (binyan-conditioned, homograph-precise, sense-aware),
  `topics`, `topic`, and the `corpus_*` tools. The default tools make **zero
  LLM calls** — your MCP client does any synthesis itself.
- **CLI** — `python -m query.ask "your question"` (add `--no-llm` for Mode A,
  `--lang`, `--top-k`, `--json`, …).

Language codes are canonical **ISO 639-3 / BCP 47** (`eng`, `spa`, `arb`,
`cmn-Hant`, …); legacy 2-letter codes (`en`, `es`) are still accepted everywhere
and normalized internally (see `bcv-RAG/lang.py`).

## What it's built from

| Source | Content | License |
|---|---|---|
| Door43 / unfoldingWord | ULT, UST, translationNotes/Questions/Words, Academy | CC BY-SA 4.0 |
| BibleAquifer | Study notes + ACAI entity tags | per-repo |
| BSB | Bible text, cross-references, section headings | CC BY-SA 4.0 |
| STEPBible | Strong's, morphology (TAHOT / TAGNT) | CC BY 4.0 |
| Theographic (viz.bible) | Entity graph (persons, places, events) | MIT |
| Nave's Topical | Topical index | public domain |

Source corpora and the built `index.db` are **re-derivable** and not committed;
the small **Strong's-keyed tables** live in the shared [`resources/`](../resources)
folder and ship in the image.

## Run it locally

```bash
cd bcv-RAG
pip install -r indexer/requirements.txt -r ingest/requirements.txt \
            -r query/requirements.txt  -r server/requirements.txt

# 1. fetch a book (repeat --source/--book as needed)
python -m ingest.cli --source door43 --book TIT --lang eng
# 2. build the index
python -m indexer.build --source ingest/_staging --reset
# 3a. ask from the CLI
GROQ_API_KEY=... python -m query.ask "what does Titus 1:1 say?"
#  (drop the key and add --no-llm for a $0 Mode-A search)
# 3b. …or serve the API + MCP
uvicorn server.app:app --port 8000
```

### Key environment variables

| Variable | When | Purpose |
|---|---|---|
| `GROQ_API_KEY` | Mode C | LLM synthesis (primary) |
| `OPENAI_API_KEY` | Mode C | LLM synthesis (fallback) |
| `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN` | vector search | BGE-M3 query embedding ($0) |
| `SHORESH_URL` | optional | shoresh URL for strategies 2–4 & 6, and citation enrichment |
| `INDEX_DB_PATH` | optional | SQLite index location (default `/data/index.db`) |
| `API_PASSWORD` | optional | password-protect `/api/ask` |
| `BCV_RESOURCES_DIR` | optional | override the shared `resources/` location |

See [bcv-RAG/README.md](../bcv-RAG/README.md) for the complete list.

## How it relates to shoresh

bcv-RAG calls **[shoresh](shoresh.md)** for original-language depth: enriching
citations with the underlying Hebrew/Greek words, the LXX-bridge expansion, the
morphology pre-filter, and clause/topic→clause search. bcv-RAG works fine without
it (those strategies simply no-op), but together they give the full
original-language-aware experience. The connection is one env var: `SHORESH_URL`.

## Deployment

Currently **self-hosted on Hetzner** with Docker Compose (the image bakes in the
BHSA/Nestle1904 corpus and the shared `resources/`; `index.db` lives on a mounted
volume). The repo still ships a `Dockerfile` and `railway.toml` so it can run on
Railway or any Docker host. Operator-specific runbooks (host, hardening, incident
response) are kept in private notes, not in this public repo.

## Where it's going

- Become a **consumer of shoresh** for all original-language data, as that
  service takes ownership of the Hebrew/Greek layer (see the ROADMAP's
  "shoresh-first" direction).
- Gain new **derived tables** — speaker/red-letter index, semantic domains,
  OT-in-NT quotations, ranked cross-references, geography — each a build-time
  table projected through Strong's. The ordered plan is in
  **[ROADMAP.md](ROADMAP.md)**.
