# search/

Clause-level original-language semantic search — 88,131 Hebrew clauses
(BHSA) with configurable embedder.

## Embedder configuration

Set via `SEARCH_EMBEDDER` environment variable:

| Value | Model | RAM | Cold start | torch | Cost |
|-------|-------|-----|------------|-------|------|
| `cloudflare` (default) | BGE-M3 via Cloudflare Workers AI | ~200MB | 2-3s | No | $0 |
| `berel` (opt-in) | BEREL 3.0 (self-hosted, mean-pooled) | ~2.5GB | 30-60s | Yes | $0 |

BEREL has 5.5× better Hebrew precision (validated in `embed_eval/`), but
requires torch and heavy RAM. BGE-M3 is multilingual and lightweight.
Switch back anytime by changing the env var and rebuilding clause vectors.

## Pieces

| File | Role |
|---|---|
| `embedder.py` | `PooledEncoder` (BEREL) + `CloudflareEncoder` (BGE-M3); selected by `SEARCH_EMBEDDER` |
| `translate.py` | English → Hebrew query translation: `gloss` (deterministic, $0) or `llm` (Groq/OpenAI, near-$0) |
| `build.py` | one-off: fetch BHSA clauses from bcv-corpus → embed → write `clauses_<lang>.npy` + `.sqlite` to `DATA_DIR` |
| `store.py` | `ClauseStore`: load matrix at startup, brute-force cosine (~50ms for 88k clauses) |

## Build sequence (local)

```bash
# 1. start the corpus engine (now part of bcv-RAG — the former bcv-corpus):
cd bcv-RAG && uvicorn server.app:app --port 8000
# 2. build embeddings:
cd shoresh
CORPUS_URL=http://localhost:8000 SHORESH_DATA=./data python3 -m search.build --lang hbo
# 3. upload to a running deployment ($HOST = your service URL), or mount the
#    data volume directly when self-hosting (current setup: Hetzner + Compose):
curl -X POST "$HOST/upload/clauses_hbo.npy?secret=$SECRET&chunk=0" \
     --data-binary @data/clauses_hbo.npy   # (chunked for files >50MB)
curl -X POST "$HOST/upload/clauses_hbo.sqlite?secret=$SECRET" \
     --data-binary @data/clauses_hbo.sqlite
```

Clause vectors use USFM book codes (GEN, PSA, not Genesis, Psalms) —
language-neutral internal plumbing.

## Query

```
GET /search?q=<hebrew>&lang=hbo&k=10                    # direct Hebrew
GET /search?q=<english>&lang=hbo&translate=gloss&k=10   # English→Hebrew ($0)
GET /search?q=<english>&lang=hbo&translate=llm&k=10     # English→Hebrew (LLM)
GET /search?q=...&enrich=true                            # add word-level breakdown
```

## Greek (coming in consolidation step 4)

Nestle1904 has 8,011 clauses (all 27 NT books) via bcv-corpus — ready to
embed. Will be built alongside the embedder switch:
- BGE-M3 (default): same Cloudflare endpoint, $0
- SPhilBERTa (opt-in via `SEARCH_EMBEDDER=berel`): 3.7× Greek advantage

The LXX (OT Greek) has no clause boundaries — a future clause segmenter
would extend `/search?lang=grc` coverage to the 54 LXX books.
