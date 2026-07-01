# shoresh — the original-language engine, explained

*shoresh* (Hebrew **שֹׁרֶשׁ**, "root") is the service that knows the Bible's
**original Hebrew and Greek**. Give it a verse and it returns the interlinear with
morphology and glosses; give it a Strong's number and it returns every occurrence;
give it an English (or original-language) word and it finds the matching concepts.
It also serves a **vocab-trainer feed** and a **word-study card**, runs a
**Hebrew→Greek bridge** through the Septuagint, and does **clause-level semantic
search** — "find clauses that mean roughly this" over 88k Hebrew clauses and 8k
Greek sentences.

shoresh anchors its data on the most granular *original* unit — the Hebrew lexeme
and each individual word occurrence — and derives the rest (Strong's numbers,
multilingual glosses, per-word senses) from it.

Almost everything it does is **deterministic and $0** — no model, no LLM, no
external call. The one exception is clause search, which needs a query embedding.

> Connecting a client? The [Client Integration Guide](client-guide.md) covers how to
> call shoresh (and bcv-RAG) — base URLs, the `gloss_lang` parameter, and the endpoint map.

---

## What you can ask it

All endpoints are plain `GET`s under the service root.

| Endpoint | What it gives you | Cost |
|---|---|---|
| `GET /verse/{book}/{ch}/{v}` | Interlinear — LXX Greek + Hebrew/Greek spine, with morphology + gloss | $0 |
| `GET /word/{strong}` | Concordance — every occurrence of a Strong's number | $0 |
| `GET /words` | Vocab-trainer feed — glosses in 11 languages, per-binyan for Hebrew verbs | $0 |
| `GET /wordstudy/{strong}` | Word-study card — a multilingual sense breakdown for a Strong's number | $0 |
| `GET /gloss/{word}` | Reverse gloss — a word → the Hebrew/Greek Strong's numbers behind it | $0 |
| `GET /concept/{word}` | Concept pivot — word → Strong's + sample occurrences | $0 |
| `GET /morph?pattern=&book=&chapter=` | Morphology search — imperatives, participles, nouns, … | $0 |
| `GET /bridge/{strong}` | LXX bridge — how the Septuagint renders a Hebrew word in Greek (H→G) | $0 |
| `GET /structure/{book}/{ch}/{v}` | Syntax — BHSA/Nestle1904 hierarchy (proxied from the corpus engine) | $0 |
| `GET /search?q=&lang=hbo` | **Hebrew** clause search (88,131 BHSA clauses) | $0 |
| `GET /search?q=&lang=grc` | **Greek** clause search (8,011 Nestle1904 sentences) | $0 |
| `GET /search?translate=gloss` | Search an English query against Hebrew via deterministic gloss lookup | $0 |
| `GET /search?translate=llm` | …or translate the query with an LLM first | ~$0.0001 |
| `GET /search?enrich=true` | Add a per-word breakdown to each search result | $0 |

There's also a small authenticated `POST /upload/{filename}` used to push the
clause-vector files to a running deployment.

**Sense layer.** Every Hebrew word carries a context-derived sense, which is what
makes `/wordstudy` and the binyan-conditioned, homograph-precise concordance
precise. How it's built is documented separately in
[`docs/sense-layer-pipeline.md`](sense-layer-pipeline.md).

## What's inside

| Module | Purpose |
|---|---|
| `spine/` | The original-language **spine** — UHB (Hebrew OT) + UGNT (Greek NT), ~443k words, 99.6% reconciled against BHSA. Builds `spine.db`. |
| `lxx/` | The **Septuagint** (Greek OT), Rahlfs 1935 — ~587k words across 54 books, 93% Strong's-tagged. Builds `lxx.db`. |
| `search/` | Clause-level semantic search: the embedder selector, the build pipeline, and a brute-force cosine store loaded at startup. |
| `embed_eval/` | A harness for measuring embedder quality (sense separation + word-study retrieval) — how we know BEREL/SPhilBERTa beat the baseline. |
| `data/` | Runtime volume: the clause vectors (`clauses_<lang>.npy`) + metadata (`clauses_<lang>.sqlite`). |
| `legal/` | The CATSS/CCAT user declaration governing the LXX morphological data. |
| `docs/` | [`spine-parser.md`](../shoresh/docs/spine-parser.md) and [`embedding-enrichment.md`](../shoresh/docs/embedding-enrichment.md). |

### Data assets

| Asset | Size | Source |
|---|---|---|
| `spine.db` | 41 MB | UHB/UGNT, 443k words, 99.59% BHSA-reconciled |
| `lxx.db` | — | Rahlfs 1935, 587k words, 54 books, 93% Strong's-tagged |
| `strongs_gloss.tsv` | 465 KB | STEPBible TBESH/TBESG (CC BY), ~14,300 entries |
| `clauses_hbo.npy` | ~270 MB | 88,131 BHSA clauses, 1024-d BGE-M3 vectors |
| `clauses_grc.npy` | ~25 MB | 8,011 Nestle1904 sentences, 1024-d BGE-M3 vectors |

The source databases and clause vectors are **re-derivable** and not committed —
you build them locally (see below).

## Clause search & embedders

Clause search compares a query embedding against pre-computed clause vectors with
a fast brute-force cosine scan (~50 ms over 88k clauses). The embedder is chosen
with the `SEARCH_EMBEDDER` env var — and the **query-time embedder must match the
one used to build the vectors**.

| `SEARCH_EMBEDDER` | Model | RAM | Cold start | Quality |
|---|---|---|---|---|
| `cloudflare` (default) | BGE-M3 via Cloudflare Workers AI | ~200 MB | 2–3 s | 1× baseline |
| `berel` (opt-in) | BEREL 3.0 (Hebrew) + SPhilBERTa (Greek), native | ~3 GB | 30–60 s | 5.5× Hebrew, 3.7× Greek |
| `bge-m3-local` | BGE-M3 via local `sentence-transformers` | — | — | for batch builds |

Switching the embedder means: change the env var → rebuild the clause vectors →
upload them → redeploy.

## Run it locally

```bash
cd shoresh
pip install -r requirements.txt          # default (no torch)
# pip install -r requirements-berel.txt  # only if you want the BEREL/SPhilBERTa embedder

# build the data
python -m lxx.parse --all && python -m spine.parse

# serve
SHORESH_DATA=./data uvicorn app:app --port 8080
```

Building the clause vectors needs the corpus engine running — it lives in
bcv-RAG (the former `bcv-corpus` service), run locally or pointed at a deployed
bcv-RAG `/api`:

```bash
CORPUS_URL=http://localhost:8000 SHORESH_DATA=./data \
  python -m search.build --lang hbo --embedder bge-m3-local
CORPUS_URL=http://localhost:8000 SHORESH_DATA=./data \
  python -m search.build --lang grc --embedder bge-m3-local
```

### Key environment variables

| Variable | Default | Purpose |
|---|---|---|
| `SEARCH_EMBEDDER` | `cloudflare` | `cloudflare`, `bge-m3-local`, or `berel` |
| `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN` | — | required for the `cloudflare` embedder |
| `CORPUS_URL` | — | the corpus engine URL for `/structure` proxy and clause builds |
| `SHORESH_DATA` | `/data` | where the clause vectors live |

## How it relates to bcv-RAG

The two services are complementary. **[bcv-RAG](bcv-RAG.md)** handles broad
retrieval and Q&A; **shoresh** owns the original-language detail. bcv-RAG calls
shoresh to enrich citations with Hebrew/Greek words, to run the LXX-bridge and
morphology strategies, and for clause search. shoresh in turn proxies a couple of
structural endpoints (`/structure`) from the corpus engine via `CORPUS_URL`.

Going forward the project is **"shoresh-first"**: original-language data and logic
get first priority here, and bcv-RAG becomes a consumer via this API. See
**[ROADMAP.md](ROADMAP.md)** for the items slated to be built in shoresh
(speaker/quotation index, semantic domains, OT-in-NT quotations, multilingual
glosses).

## Deployment

Currently **self-hosted on Hetzner** with Docker Compose, co-hosted alongside
bcv-RAG. The repo still ships a `Dockerfile` and `railway.toml` for portability.
Clause vectors are pushed to the running volume via the `/upload` endpoint (or
mounted directly when self-hosting).

## License

The original-language data is **non-commercial** (BHSA CC BY-NC-SA, OpenHebrewBible
CC BY-NC; LXX morphology under the CATSS/CCAT declaration in `legal/`). The
service **code** is MIT like the rest of the repo.
