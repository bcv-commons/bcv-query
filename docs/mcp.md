# MCP Guide

bcv-RAG exposes its retrieval + study tools over the **Model Context Protocol (MCP)**, so
an AI assistant (Claude Desktop, Cursor, a custom agent, …) can search the Bible corpus,
pull original-language data, and build study packets as native tools.

## Human doc vs. AI doc — how this works

MCP is **self-describing**. A client connects and calls `tools/list`; the server returns
every tool's **name, description, and JSON input schema**. That live catalog *is* the
AI-facing documentation — the tool descriptions are written for the model, and an assistant
discovers and uses them automatically. There is no separate "AI prose doc" to maintain.

So this page is the **human** doc: how to connect, authenticate, and what the tools are.
The **canonical, always-current** reference for an AI is the live `tools/list` (a snapshot
is in [Tool catalog](#tool-catalog) below for quick human reference).

## Protocol

- **JSON-RPC 2.0**, MCP `protocolVersion` **2024-11-05**.
- Methods: `initialize` (handshake), `tools/list` (catalog), `tools/call` (invoke), `ping`.

## Transports

### stdio — for local desktop clients (recommended for Claude Desktop / Cursor)

Standard MCP clients speak stdio. Run the server as a local process from the `bcv-RAG/`
directory (it loads the same env + opens the same index DB as the web service):

```bash
cd bcv-RAG
python -m server.mcp.stdio
```

**Claude Desktop** — add to `claude_desktop_config.json`:

```jsonc
{
  "mcpServers": {
    "bcv-query": {
      "command": "python",
      "args": ["-m", "server.mcp.stdio"],
      "cwd": "/absolute/path/to/bcv-query/bcv-RAG",
      "env": {
        // only needed if you'll use semantic (vector) search — see Auth
        "BTMCP_API_PASSWORD": "<your key>"
      }
    }
  }
}
```

Cursor and other stdio MCP clients take the same `command` / `args` / `cwd`.

### HTTP — for remote / programmatic use

A plain JSON-RPC-over-HTTP endpoint (single request/response, not SSE):

- `POST {BCV_RAG_BASE}/mcp` — JSON-RPC calls (a single object or a batch array).
- `GET  {BCV_RAG_BASE}/mcp` — server info (protocol version, method list).

> This HTTP surface is a convenience for custom agents/scripts. Standard MCP clients that
> expect the official *Streamable HTTP* transport should use **stdio** instead; the HTTP
> endpoint is best consumed by your own JSON-RPC calls.

## Authentication — registration required

Access is **registration-gated**: every MCP request needs a valid API key (you're issued one
on registration). The tools are all **$0** — the key is for identity + rate-limiting, not
billing. Send it as either header:

```
X-API-Key: <your key>
# or
Authorization: Bearer <your key>
```

For stdio, put the key in the client's `env` (`BTMCP_API_PASSWORD`, as in the config above).
Requests are rate-limited per key (429 + `Retry-After` when exceeded).

> Vector/semantic search is intentionally **not** an MCP tool — it stays REST-only at
> `GET /api/search?semantic=true` (open, $0). On MCP, `search` already does concept expansion
> (Strong's-anchored related terms), so lexical search is meaning-aware.

> Remote plug-and-play via the SDK's **Streamable HTTP** transport is landing next; today the
> HTTP surface is the JSON-RPC endpoint below (stdio is fully standard now).

## Quick manual test

```bash
# server info
curl {BCV_RAG_BASE}/mcp

# list tools (the key is required on every request)
curl -X POST {BCV_RAG_BASE}/mcp -H "Content-Type: application/json" -H "X-API-Key: $KEY" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# call a tool
curl -X POST {BCV_RAG_BASE}/mcp -H "Content-Type: application/json" -H "X-API-Key: $KEY" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call",
       "params":{"name":"study","arguments":{"question":"the love of God in John 3:16"}}}'

# original-language depth (also on MCP now)
curl -X POST {BCV_RAG_BASE}/mcp -H "Content-Type: application/json" -H "X-API-Key: $KEY" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call",
       "params":{"name":"word_study","arguments":{"strong":"G0025","lang":"en"}}}'
```

## Tool catalog

`*` marks a required argument. `lang` is accepted almost everywhere (ISO 639-1 or 639-3;
omit to default to English). The live `tools/list` is authoritative for full schemas.

**Corpus / retrieval**

| Tool | Arguments | What it does |
|---|---|---|
| `search` | `query*, lang, kind, book, source, top_k` | Ranked chunks (lexical + passage/title/tags + **concept expansion**), RRF-fused. $0. |
| `search_branched` | `query*, lang, book, source, per_branch, force` | Same retrieval, results **grouped by kind** into branches. |
| `study` | `question*, lang, source, book, top_k` | Deterministic study packet (no LLM): the full pipeline, organized. |
| `passage_lookup` | `reference*, lang` | Every chunk overlapping a passage range (e.g. "John 3:16-18"). |
| `get_chunk` | `chunk_id*, lang` | Full body of a specific chunk (behind a citation). |
| `cross_references` | `reference*, source, limit` | Curated cross-references (TSK + BSB parallels) for a verse. |
| `concordance` | `word*, limit, offset` | Every BSB verse containing an English word. |
| `entity_lookup` | `entity*, type, lang` | Chunks about a person / place / biblical concept. |
| `topics` / `topic` | `starts_with…` / `topic_id*` | Browse / open Nave's Topical Bible topics. |
| `tree_listing` | `tree*, path, lang` | Walk a perspective tree (entities, topics, …). |

**Original language (Hebrew/Greek, shoresh-backed, $0, localized via `lang`)**

| Tool | Arguments | What it does |
|---|---|---|
| `word_study` | `strong*, lang` | Gloss · keyness · per-binyan senses · domains · TW article · related lexemes. |
| `verse_interlinear` | `reference*, lang` | Per-word gloss/sense/domain + LXX parallel for a verse. |
| `verse_syntax` | `reference*` | Clause→phrase syntax tree (who-did-what). |
| `lexeme_profile` | `lex*, lang` | A lexeme's stems × senses × counts × sample refs (finer than Strong's). |
| `semantic_domain` | `code*, lang` | Every lexeme in a Louw-Nida/SDBH domain, glossed. |
| `morphology_concordance` | `lex*, stem, sense, top_k, lang` | Verses by Hebrew lexeme + binyan + sense. |
| `cross_language` | `strong*` | Hebrew↔Greek equivalents via the LXX bridge. |

## Notes

- Tool results are best-effort JSON; enrichment that can't be produced is omitted rather
  than failing the call.
- New tools/fields may be added — clients should rely on `tools/list` and ignore unknown
  fields.
- `study` vs `search`: `study` is the one-call "give me everything on this question"
  (organized, deterministic); `search`/`search_branched` are lower-level retrieval.
