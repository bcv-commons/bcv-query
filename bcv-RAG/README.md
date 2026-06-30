# bcv-RAG

Retrieval-augmented Q&A over Bible translation resources.

> **New here?** Read the first-time-user deep-dive: **[../docs/bcv-RAG.md](../docs/bcv-RAG.md)**.
> This README is the quick reference (data sources, env vars, deploy).

## Data sources

| Source | Content | License |
|--------|---------|---------|
| Door43/unfoldingWord | ULT, UST, TN, TQ, TWL, TW, TA | CC BY-SA 4.0 |
| BibleAquifer | Study notes + ACAI entity tags | Per-repo |
| BSB | Bible text, cross-refs, headings | CC BY-SA 4.0 |
| STEPBible | Strong's, morphology (TAHOT/TAGNT) | CC BY 4.0 |
| Theographic | Entity graph (persons, places, events) | MIT |
| Nave's Topical | Topical index | Public domain |

## Interfaces

- **REST API** — `/api/ask`, `/api/search`, `/api/books`, `/api/clauses`, and more. See [docs/API.md](docs/API.md).
- **MCP server** — same tools via Model Context Protocol (including `morphology_concordance`, a binyan-conditioned, sense-aware concordance). Default tools make zero LLM calls.
- **CLI** — `python -m query.ask "question"`

## Environment variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `GROQ_API_KEY` | Mode C | — | LLM synthesis (primary) |
| `GROQ_MODEL` | No | (see `query/llm.py`) | Synthesis model (configurable) |
| `GROQ_REASONING_EFFORT` | No | `none` | Reasoning effort for reasoning models (`low`/`medium`/`high`) |
| `OPENAI_API_KEY` | Mode C fallback | — | LLM synthesis (fallback) |
| `CLOUDFLARE_ACCOUNT_ID` | Mode A vectors | — | BGE-M3 query embedding |
| `CLOUDFLARE_API_TOKEN` | Mode A vectors | — | BGE-M3 query embedding |
| `BTMCP_EMBEDDING_MODEL` | No | `bge-m3` | Embedding model |
| `BTMCP_EMBEDDING_PROVIDER` | No | auto-detect | `cloudflare`, `bge-m3-local`, `voyage`, `openai` |
| `SHORESH_URL` | No | — | shoresh private URL for strategies 2-4, 6 |
| `INDEX_DB_PATH` | No | `/data/index.db` | SQLite index location |
| `API_PASSWORD` | No | — | Password-protect `/api/ask` |

## Deploy

Docker. Currently **self-hosted on Hetzner** via Docker Compose; the `Dockerfile`
and `railway.toml` also run it on Railway or any Docker host. The image is built
from the **repo root** (`docker build -f bcv-RAG/Dockerfile .`) so the shared
`resources/` is in context; the corpus data (BHSA/Nestle1904) is baked in at build
time, and `index.db` lives on a mounted volume.

## Docs

- [../docs/bcv-RAG.md](../docs/bcv-RAG.md) — the friendly overview (start here)
- [API.md](docs/API.md) — full endpoint reference
- [architecture.md](docs/architecture.md) — how the retrieval pipeline works
