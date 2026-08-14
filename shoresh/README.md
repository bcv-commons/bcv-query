# shoresh

Original-language anchoring service. Deterministic Hebrew/Greek endpoints ($0) plus clause-level semantic search.

> **New here?** Read the first-time-user deep-dive: **[../docs/shoresh.md](../docs/shoresh.md)**.
> This README is the quick reference (endpoints, data assets, env vars).

## Endpoints

All under the service root. Deterministic endpoints have no external dependency.

| Endpoint | What | Cost |
|----------|------|------|
| `GET /verse/{book}/{ch}/{v}` | Interlinear — LXX Greek + Hebrew/Greek spine with morphology + gloss | $0 |
| `GET /word/{strong}` | Concordance — every occurrence of a Strong's number | $0 |
| `GET /words` | Vocab-trainer feed — glosses in 11 languages, per-binyan for Hebrew verbs | $0 |
| `GET /wordstudy/{strong}` | Word-study card — multilingual sense breakdown for a Strong's number | $0 |
| `GET /tw/{strong}` | Translation-Words article(s) explaining a Strong's number, ranked (e.g. G0026 → bible/kt/love) | $0 |
| `GET /gloss/{word}` | Reverse gloss — English word → Hebrew/Greek Strong's numbers | $0 |
| `GET /concept/{word}` | Concept pivot — English → Strong's + sample occurrences | $0 |
| `GET /morph?pattern=&book=&chapter=` | Morphology search — imperatives, participles, verbs, nouns | $0 |
| `GET /bridge/{strong}` | LXX bridge — how the Septuagint translates a Hebrew word, or vice versa | $0 |
| `GET /lxx-lexeme/{wordid}` | LXX-only Greek lexeme (no Strong's number) — citation form + variants | $0 |
| `GET /structure/{book}/{ch}/{v}` | Syntax — BHSA/Nestle1904 hierarchy (proxied from bcv-RAG) | $0 |
| `GET /search?q=&lang=hbo&k=10` | Hebrew clause search (88,131 BHSA clauses) | $0 |
| `GET /search?q=&lang=grc&k=10` | Greek clause search (8,011 Nestle1904 sentences) | $0 |
| `GET /search?translate=gloss` | English→Hebrew via deterministic gloss lookup | $0 |
| `GET /search?translate=llm` | English→Hebrew via LLM | ~$0.0001 |
| `GET /search?enrich=true` | Add word-level breakdown per search result | $0 |

`/tw` reads the shared **`resources/strongs_tw.tsv`** (built by
`bcv-RAG/scripts/build_strongs_tw.py`). In a dev checkout it's found at the repo
root automatically. For a deployed image, sync it into shoresh's build context
first (shoresh builds from `shoresh/` only) — e.g. `cp resources/strongs_tw.tsv
shoresh/data/` before `docker build`, or set `STRONGS_TW_TSV` to its path.

## Embedder configuration

Set via `SEARCH_EMBEDDER` environment variable:

| Value | Model | RAM | Cold start | Quality |
|-------|-------|-----|------------|---------|
| `cloudflare` (default) | BGE-M3 via Cloudflare Workers AI | ~200MB | 2-3s | 1× baseline |
| `berel` (opt-in) | BEREL 3.0 (hbo) + SPhilBERTa (grc) | ~3GB | 30-60s | 5.5× hbo, 3.7× grc |

Switching: change env var → rebuild clause vectors → upload → redeploy.

## Build clause vectors

```bash
# start the corpus engine: it lives in bcv-RAG (the former bcv-corpus service,
# now its /api/passage + /api/context routes)
cd bcv-RAG && uvicorn server.app:app --port 8000

# build (in another terminal)
cd shoresh
CORPUS_URL=http://localhost:8000 SHORESH_DATA=./data python3 -m search.build --lang hbo --embedder bge-m3-local
CORPUS_URL=http://localhost:8000 SHORESH_DATA=./data python3 -m search.build --lang grc --embedder bge-m3-local

# upload to a running deployment (chunked for files >50MB); $HOST is your service URL
curl -X POST "$HOST/upload/clauses_hbo.npy?secret=$SECRET&chunk=0" --data-binary @data/clauses_hbo.npy
curl -X POST "$HOST/upload/clauses_hbo.sqlite?secret=$SECRET" --data-binary @data/clauses_hbo.sqlite
# (same for grc)
# When self-hosting (current setup: Hetzner + Docker Compose), you can instead
# mount the data volume directly and skip the upload step.
```

## Data assets

| Asset | Size | Source |
|-------|------|--------|
| `spine.db` | 41MB | UHB/UGNT, 443k words, 99.59% BHSA-reconciled |
| `lxx.db` | — | Rahlfs 1935, 587k words, 54 books, 93% Strong's-tagged |
| `spine_glosses.tsv` | 465KB | STEPBible TBESH/TBESG (CC BY), 14,300 entries |
| `clauses_hbo.npy` | 344MB | 88,131 BHSA clauses, 1024d BGE-M3 vectors |
| `clauses_grc.npy` | 31MB | 8,011 Nestle1904 sentences, 1024d BGE-M3 vectors |

## Corpus engine (BHSA / Nestle1904 via Context-Fabric)

`shoresh/corpus_engine/` and several `macula/build_*.py` scripts (`extract_hbo_syntax.py`,
`build_bhsa_structural_pairs.py`, `build_parallelism_pairs.py`, `spine/reconcile.py`,
`bcv-RAG/scripts/build_lex_occurrences.py`) read the ETCBC/BHSA (Hebrew) and ETCBC/nestle1904 (Greek)
corpora in Text-Fabric format, expected at `~/text-fabric-data`. This is a **CC BY-NC-SA download**,
not part of the repo or baked into any Docker image (production mounts it as a host volume — see
`internal-docs/hosting.md`) — a fresh clone or new dev machine needs to fetch it once:

```bash
python -c "from tf.app import use; use('ETCBC/bhsa', version='2021')"   # Hebrew — version pinned to
                                                                          # match the hardcoded tf/2021
                                                                          # path in the scripts above
python -c "from tf.app import use; use('ETCBC/nestle1904')"             # Greek — no version pinned in
                                                                          # code, latest is fine
```

This downloads into `~/text-fabric-data/github/ETCBC/<repo>/tf/<version>` — the exact path those
scripts hardcode. `context-fabric`'s own `cfabric.downloader` has no BHSA/Nestle1904 registration as
of 0.5.7 (`list_corpora()` returns `{}`); fetch via classic `text-fabric`'s `tf.app.use()` above —
`shoresh/corpus_engine/cf_engine.py` reads whatever lands at that path regardless of which tool
fetched it.

Loading the full corpus (`CF.loadAll()`) takes ~1.6GB RAM — `internal-docs/hosting.md` warns not to
re-bake it into a Docker image ("BHSA `loadAll` OOMs the box").

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_EMBEDDER` | `cloudflare` | `cloudflare`, `bge-m3-local`, or `berel` |
| `CLOUDFLARE_ACCOUNT_ID` | — | Required for cloudflare embedder |
| `CLOUDFLARE_API_TOKEN` | — | Required for cloudflare embedder |
| `CORPUS_URL` | — | bcv-RAG private URL for `/structure` proxy |
| `SHORESH_DATA` | `/data` | Clause vector directory |

## Run locally

```bash
pip install -r requirements.txt          # default (no torch)
pip install -r requirements-berel.txt    # opt-in for BEREL/SPhilBERTa
pip install -r requirements-macula.txt   # opt-in for macula/ build scripts (networkx, pyarrow)
python -m lxx.parse --all && python -m spine.parse
SHORESH_DATA=./data uvicorn app:app --port 8080
```

## License

Non-commercial (BHSA CC BY-NC-SA, OpenHebrewBible CC BY-NC).
