# bcv-query

**Bible study search that understands the original languages.**

bcv-query answers questions about the Bible the way a translator would — by
anchoring every word back to its **original Hebrew or Greek** and reasoning
across many translations and study resources at once. Ask a question in one of
11 languages and get a cited answer grounded in the text.

**The guiding idea:** anchor the data on the most granular *original* unit — the
Hebrew lexeme and each individual word as it occurs — and *derive* everything
coarser from it: Strong's numbers, glosses in many languages, and per-word
senses. Granular original first; everything else falls out of it.

> New here? Start with **[What it is](#what-it-is)**, then read the deep-dive for
> whichever service interests you: **[bcv-RAG](docs/bcv-RAG.md)** (search & Q&A)
> or **[shoresh](docs/shoresh.md)** (original languages). Want to help build it?
> Jump to the **[ROADMAP](docs/ROADMAP.md)** — it's written for new contributors.

---

## What it is

The project is two small, self-contained services that share one idea: the
**Strong's number** (a stable id for each Hebrew/Greek word) is a universal key
that ties together translations, glosses, morphology, and study notes in any
language.

| Service | What it does | Docs |
|---|---|---|
| **[bcv-RAG](bcv-RAG/)** | Retrieval-augmented Q&A over Bible translations + study resources. 13 retrievers fused with Reciprocal Rank Fusion, plus multi-step expansion strategies. Three cost modes — from $0 keyword/vector search to full LLM-synthesized answers. | **[docs/bcv-RAG.md](docs/bcv-RAG.md)** |
| **[shoresh](shoresh/)** | The original-language engine: interlinear, concordance, morphology search, a vocab-trainer feed, a word-study card, a Hebrew→Greek (LXX) bridge, and clause-level semantic search over 88k Hebrew + 8k Greek clauses. Most endpoints cost $0. | **[docs/shoresh.md](docs/shoresh.md)** |

Both read from a shared, **[`resources/`](resources/)** folder of Strong's-keyed
data (glosses, word-alignments, analyzer configs, book names) — the same data
that makes the multilingual support work.

```
                 your question (any of 11 languages)
                              │
                  ┌───────────▼───────────┐
                  │        bcv-RAG         │   13 retrievers + RRF fusion
                  │  search · Q&A · MCP    │   3 modes: A ($0) · B (rerank) · C (LLM)
                  └───────────┬───────────┘
                              │ asks for original-language detail
                  ┌───────────▼───────────┐
                  │        shoresh         │   interlinear · concordance · morphology
                  │ original-language core │   LXX bridge · clause semantic search
                  └───────────┬───────────┘
                              │
                  ┌───────────▼───────────┐
                  │      resources/        │   Strong's-keyed shared data
                  │  glosses · aligned_lex │   (11 languages)
                  └────────────────────────┘
```

**Languages today:** English, Spanish, French, Portuguese, Chinese, Russian,
Arabic, Hindi, Bengali, Assamese, Hausa — with **per-binyan (verbal-stem)**
detail for Hebrew verbs. Book names are locale-aware; internally everything is
keyed by USFM book codes + Strong's numbers.

## What's new / coming next

- **Multilingual glosses, 11 languages.** Short glosses keyed by Strong's number,
  with **per-binyan (verbal-stem)** detail for Hebrew verbs — these feed
  shoresh's `/words` vocab-trainer.
- **A per-occurrence sense layer.** Every Hebrew word carries a
  context-derived sense, powering a binyan-conditioned, homograph-precise
  concordance (the `morphology_concordance` MCP tool) and the multilingual sense
  breakdown on the `/wordstudy` card. How it's built:
  [`docs/sense-layer-pipeline.md`](docs/sense-layer-pipeline.md).
- **Open data published.** The Strong's→words tables are now a standalone,
  provenance-marked open dataset for people who want *just the data* (not the
  services): **[huggingface.co/datasets/bcv-commons/strongs](https://huggingface.co/datasets/bcv-commons/strongs)**
  (full, with a browsable viewer) and **[github.com/bcv-commons/strongs](https://github.com/bcv-commons/strongs)**
  (samples + pointer). It lives under the **[`bcv-commons`](https://github.com/bcv-commons)**
  org — home for the reusable Bible datasets and the services that produce them;
  a `bibles` repo (translations) is next. Dataset card + build: [`resources/strongs/`](resources/strongs).
- **Hosting moved to Hetzner.** The services are now self-hosted on a Hetzner
  server via Docker Compose (they previously ran on Railway; the Railway configs
  are still in the repo for portability). Hosting specifics are kept in
  operator-only notes, not in this public repo.
- **An `aligner` is coming.** A new sibling service that word-aligns *any*
  translation to the Strong's-bearing original — turning a plain translation into
  a Strong's-tagged interlinear and growing `resources/aligned_lex` to new
  languages. It's at the planning stage: see **[docs/aligner-plan.md](docs/aligner-plan.md)**.
- **A living roadmap.** Lots of the value here comes from *derived* data tables
  (speaker/red-letter index, semantic domains, OT-in-NT quotations, …). The plan
  and the open datasets to build them from are catalogued in
  **[docs/ROADMAP.md](docs/ROADMAP.md)**.

## Quick start

Each service runs on its own. You only need Python 3.12+ and `pip`.

```bash
# ── bcv-RAG: build a tiny index and ask a question ──
cd bcv-RAG
pip install -r indexer/requirements.txt -r ingest/requirements.txt \
            -r query/requirements.txt  -r server/requirements.txt
python -m ingest.cli  --source door43 --book TIT --lang eng  # fetch one book (ISO 639-3)
python -m indexer.build --source ingest/_staging --reset      # index it
GROQ_API_KEY=... python -m query.ask "what does Titus 1:1 say?"   # ask (Mode C)
#  …or run the API:  uvicorn server.app:app --port 8000

# ── shoresh: build the data and serve it ──
cd shoresh
pip install -r requirements.txt
python -m lxx.parse --all && python -m spine.parse   # build lxx.db + spine.db
SHORESH_DATA=./data uvicorn app:app --port 8080
```

Full setup, endpoint references, and environment variables are in each service's
deep-dive: **[docs/bcv-RAG.md](docs/bcv-RAG.md)** · **[docs/shoresh.md](docs/shoresh.md)**.

## Repository layout

```
bcv-query/
├── README.md            ← you are here
├── docs/                ← start here as a new reader
│   ├── bcv-RAG.md          the RAG / Q&A service, explained
│   ├── shoresh.md          the original-language service, explained
│   ├── ROADMAP.md          the vision + how to contribute
│   ├── aligner-plan.md     the upcoming word-aligner (planning)
│   └── multilingual-glosses.md
├── bcv-RAG/             ← service 1: retrieval + Q&A  (its own README + docs/)
├── shoresh/             ← service 2: original languages (its own README + docs/)
└── resources/           ← shared Strong's-keyed data (ISO 639-3 codes)
    └── strongs/            the published open dataset → bcv-commons/strongs
                            (data git-ignored & re-derivable; card + LICENSE kept)
```

## Contributing

This repo is meant to be **walked into**. If you care about Bible software, open
data, multilingual NLP, or original-language tooling, there's a clear on-ramp:

1. Read this README and the two service deep-dives in `docs/`.
2. Read the **[ROADMAP](docs/ROADMAP.md)** — it lays out the work in ordered
   phases, with the cheapest, highest-leverage items first and the open datasets
   to build each one from.
3. Pick something. Many roadmap items are self-contained "project an existing
   table through Strong's, commit it, ship it" tasks — friendly first
   contributions that don't require touching the serving path.

Issues, ideas, and pull requests are welcome.

## License

Code: **MIT.** Content and data retain their source licenses — Door43/unfoldingWord
CC BY-SA 4.0, STEPBible CC BY 4.0, BHSA CC BY-NC-SA, and others per source (each
`resources/` subfolder and data table records its own `source` / `license`).
The project accepts both share-alike (CC-BY-SA) and non-commercial (CC-NC) data;
attribute, and keep SA-derived data under a compatible license.
