# shoresh

Original-language anchoring service. Deterministic Hebrew/Greek endpoints ($0) plus clause-level semantic search.

> **New here?** Read the first-time-user deep-dive: **[../docs/shoresh.md](../docs/shoresh.md)**.
> This README is the quick reference (endpoints, data assets, env vars).

## Endpoints

All under the service root. Deterministic endpoints have no external dependency.

| Endpoint | What | Cost |
|----------|------|------|
| `GET /verse/{book}/{ch}/{v}` | Interlinear — LXX Greek + Hebrew/Greek spine with morphology + gloss. `?versification=<scheme>` (eng, rso, vul, org, lxx, orgw, or any scheme bibles publishes a map for) reads the reference in the reader's numbering and serves the same verse in Hebrew (and LXX) numbering (MACULA base, `VERSE_HEBREW_BASE=macula`) | $0 |
| `GET /verse/{book}/{ch}/{v}/malbim` | Malbim's verse commentary in Hebrew (19th c.; whole Hebrew Bible), comment by comment | $0 |
| `GET /files` | Data files published for direct download (the original-language spines): size, sha256, licence, source, URL | $0 |
| `GET /files/{name}` | One published file, e.g. `lexeme-spine-macula.db` (HTTP Range supported); verify its sha256 against `/files`. Served from the DNS-only host `https://files.qombi.com/files/{name}` (the same path on `shoresh.qombi.com` redirects there) | $0 |
| `GET /word/{strong}` | Concordance — every occurrence of a Strong's number (Hebrew refs in Hebrew numbering and with the token `key` when `LEXEME_BASE=macula`) | $0 |
| `GET /senses/{strong}` | Sense groups of a Hebrew Strong's: lexeme × stem × sense, with counts and sample refs | $0 |
| `GET /lexeme/{lex}` | Lexeme profile. `lex` is a MACULA lexeme id (`hbo:6942`, homographs `hbo:0871a`) or a Strong's code (`H6942`, which fans out to its homographs); BHSA ids (`QDC[`) are no longer accepted. A `hbo:` id is always answered from MACULA | $0 |
| `GET /words` | Vocab-trainer feed — glosses in 11 languages, per-binyan for Hebrew verbs | $0 |
| `GET /wordstudy/{strong}` | Word-study card — multilingual sense breakdown for a Strong's number | $0 |
| `GET /tw/{strong}` | Translation-Words article(s) explaining a Strong's number, ranked (e.g. G0026 → bible/kt/love) | $0 |
| `GET /gloss/{word}` | Reverse gloss — English word → Hebrew/Greek Strong's numbers | $0 |
| `GET /concept/{word}` | Concept pivot — English → Strong's + sample occurrences | $0 |
| `GET /morph?pattern=&book=&chapter=` | Morphology search — imperatives, participles, verbs, nouns | $0 |
| `GET /bridge/{strong}` | LXX bridge — how the Septuagint translates a Hebrew word, or vice versa | $0 |
| `GET /lxx-lexeme/{wordid}` | LXX-only Greek lexeme (no Strong's number) — citation form + variants | $0 |
| `GET /structure/{book}/{ch}/{v}` | Syntax — clause/phrase hierarchy from MACULA lowfat trees | $0 |
| `GET /scaffold/{book}/{ch}` | Original-language scaffold of a chapter, every token keyed by its MACULA token key (joins to lexeme-aligner alignments); example client in `docs/examples/interlinear` | $0 |
| `GET /search?q=&lang=hbo&k=10` | Hebrew clause search (MACULA clauses) | $0 |
| `GET /search?q=&lang=grc&k=10` | Greek clause search (MACULA Greek sentences) | $0 |
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
| `spine.db` | 41MB | UHB/UGNT, 443k words |
| `lxx-glaux.db` | 82MB | GLAUx (CC BY-SA), 592k words, 54 books, 93% Strong's-tagged |
| `spine_glosses.tsv` | 465KB | STEPBible TBESH/TBESG (CC BY), 14,300 entries |
| `clauses_hbo.npy` | 311MB | 101,200 MACULA clauses, 768d BEREL vectors |
| `clauses_grc.npy` | 141MB | 46,050 MACULA clauses, 768d SPhilBERTa vectors |

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SEARCH_EMBEDDER` | `cloudflare` | `cloudflare`, `bge-m3-local`, or `berel` |
| `CLOUDFLARE_ACCOUNT_ID` | — | Required for cloudflare embedder |
| `CLOUDFLARE_API_TOKEN` | — | Required for cloudflare embedder |
| `CORPUS_URL` | — | Legacy: only reported by `/health` and used by the offline clause-vector builds below |
| `SHORESH_DATA` | `/data` | Clause vector directory |
| `SHORESH_FILES_BASE` | — | Base URL advertised by `GET /files` (e.g. `https://files.qombi.com`); default: the host the client used |
| `SHORESH_FILES_LIMIT` | `8/hour` | Per-IP limit on `GET /files/{name}` |
| `TREES_DB` | `/data/trees-macula.db`, `/data/public/…`, then `macula/` | The tree database |
| `LEXEME_SPINE_DB`, `VERSE_SENSES_DB` | `/data/<name>`, `/data/public/<name>`, then `macula/` | The two MACULA lexeme databases |
| `WORD_GLOSSES_DIR` | `/data/word_glosses` | Where the built `hbo_lexeme/<Language>.csv` tables are read from (MACULA-keyed BibleOL glosses; build output, not in git: `python -m macula.build_word_glosses_lexeme`, ship with `deploy/deploy-data.sh`); then `macula/data/word_glosses` |
| `VERSIFICATION_MAP_DIR` | `/data/vrs` | Where bibles' published versification files (`index.json`, `<scheme>.vrs`, `<scheme>-to-eng*.json`) are read from; fetched from the CDN when missing and revalidated by ETag at most daily (only changed files are downloaded) |
| `VERSIFICATION_BASE` | `https://cdn.bibel.wiki` | The CDN those files come from |

## Run locally

```bash
pip install -r requirements.txt          # default (no torch)
pip install -r requirements-berel.txt    # opt-in for BEREL/SPhilBERTa
pip install -r requirements-macula.txt   # opt-in for macula/ build scripts (networkx, pyarrow)
python -m spine.parse && python -m lxx.build_glaux   # spine.db; lxx/data/lxx-glaux.db (ship it to /data)
SHORESH_DATA=./data uvicorn app:app --port 8080
```

## License

Code MIT; data per source (UHB/UGNT and GLAUx CC BY-SA, MACULA CC BY). The service reads no non-commercial data since 2026-10-10 ("NC exit status" in `docs/ROADMAP.md`); attribution in `spine/ATTRIBUTION.md`.
