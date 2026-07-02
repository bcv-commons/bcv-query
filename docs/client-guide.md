# Client Integration Guide

How to connect to and use the Bible-study services from a client application. This is a
practical integration guide; per-field detail lives in each service's OpenAPI (`/openapi.json`).

## The two services

| Service | Purpose | You call it for |
|---|---|---|
| **bcv-RAG** | Retrieval + RAG over Bible study content | Ask a question → a cited answer, plus study **cards** and **branches** |
| **shoresh** | Original-language (Hebrew/Greek) data | Per-word glosses, senses, lexemes, verse structure — the **drill-in** target behind cards |

The normal flow: your client sends a question to **bcv-RAG**; the response includes
`cards[]`, each with a relative `drill` path into **shoresh**; your client fetches those
paths (with the reader's language) to render deeper study views.

> Building an **AI assistant** rather than a REST client? bcv-RAG also speaks **MCP** —
> see the [MCP Guide](mcp.md).

## Connecting

Both services are plain HTTP + JSON. Use the base URLs your deployment gives you:

```
{BCV_RAG_BASE}     e.g. https://api.example.org
{SHORESH_BASE}     e.g. https://shoresh.example.org
```

- Every response is JSON; send `Content-Type: application/json` on POST bodies.
- Health checks: `GET {BCV_RAG_BASE}/api/health`, `GET {SHORESH_BASE}/health`.
- If your deployment only exposes bcv-RAG publicly, ask the operator to also expose (or
  proxy) shoresh — the card `drill` links are shoresh paths.

### Authentication

Only the **synthesis (LLM) + MCP + write** paths need a key; everything else is open
(anonymous, rate-limited). Send the key on the gated calls as a header:

```
X-API-Key: <your key>
# or
Authorization: Bearer <your key>
```

**Requires a key:**
- `POST /api/ask`, `POST /api/ask/branched` — the LLM-synthesized answer.
- the whole **MCP** surface (`/mcp`) — see the [MCP Guide](mcp.md).
- any write method (PUT/PATCH/DELETE).

**Open (no key)** — everything else, including **semantic search** (embedding is Cloudflare
BGE-M3, $0): `GET /api/search` (incl. `?semantic=true`), `GET /api/search/branched`,
`POST /api/study`, `/api/concordance/*`, `/api/cross-references/*`, `/api/topics`,
`/api/entities`, trees, chunk, `/api/health`, `/` — and **all shoresh endpoints**.

All requests (open included) are **rate-limited** per key (or per IP when anonymous):
`429 + Retry-After` when exceeded; gated paths get a tighter cap.

## Quick start

```bash
curl -X POST {BCV_RAG_BASE}/api/ask \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $KEY" \
  -d '{"question": "What does John 3:16 teach about God'\''s love?"}'
```

## The main endpoint — `POST /api/ask`

### Request

```jsonc
{
  "question": "What does John 3:16 teach about God's love?",  // required
  "lang": "en",                 // optional — omit to auto-detect from the question
  "scope": { "source": "all", "book": null },  // optional; source: all | door43 | aquifer
  "top_k": 10,                  // optional, 1..50
  "expand": []                  // optional
}
```

### Response

```jsonc
{
  "question": "...",
  "answer": "...",              // cited prose, in the resolved language
  "citations": [ { "passage": "John 3:16", ... } ],
  "confidence": "high",         // overall answer confidence
  "lang": "eng",                // resolved language (ISO 639-3)
  "word_study": { ... },        // original-language enrichment for cited words
  "cards": [ ... ],             // study cards — see "Cards"
  "branches": [ ... ],          // results grouped by branch — see "Branches"
  "suggested_layout": "hero",   // layout hint: hero | deck | tree | explore
  "analysis": { ... }           // how the query was interpreted
}
```

## Languages

`lang` is optional on `/api/ask`:

- **Omit it** → the server detects the language from the question and answers in it.
- **Pass it** to force the language. Accepts **ISO 639-1** (`en`, `es`, `de`, `id`, `fr`, `pt`,
  `ru`, `ar`, `hi`, …) or **ISO 639-3** (`eng`, `spa`, `deu`, `ind`, …).
- The response echoes the **resolved** language in `lang` (639-3). Use it for display.

All content localizes to the resolved language: the answer prose, book names, per-word
glosses, binyan (Hebrew stem) senses, semantic domains, and Translation-Words articles.
Coverage varies by language — anything without a localized value falls back to English
gracefully.

## Cards

`cards[]` is a never-exclusive set of study cards. Render all of them (they are drill-downs,
not competing claims); rank by `featured` then `confidence`.

```jsonc
{
  "kind": "passage",            // passage | concept | entity | speaker | cross-ref
  "headline": "PASSAGE John 3:16 (grc) [Jesus, red-letter] — agapaō=love · pisteuō=believe …",
  "anchor": "John 3:16",        // localized display label
  "drill": "/verse/JHN/3/16",   // relative shoresh path — prepend {SHORESH_BASE}
  "confidence": 1.0,            // 0..1
  "featured": true,             // confidence ≥ 0.7

  // passage-only extras:
  "syntax": "/structure/JHN/3/16/syntax",
  "domains": ["agapaō: Love, Affection, Compassion", "pisteuō: Be a Believer", …],
  "lxx": [ ... ], "frame": null
}
```

- **`drill`** is a **relative shoresh path**. Prepend `{SHORESH_BASE}` and append the reader's
  language (see "Following drill links"). By kind: passage → `/verse/{USFM}/{ch}/{v}`,
  concept → `/wordstudy/{STRONG}`, speaker/entity → `/speaker/{name}` (or `null`).
- Always build shoresh URLs from `drill`/`syntax` — **not** from `anchor` (localized display text).

## Branches

`branches[]` groups results by dimension of study; `suggested_layout` is a rendering hint.

```jsonc
"branches": [
  { "kind": "passage", "label": "Passage", "featured": true, "n": 1,
    "leads": [ { "kind": "passage", "headline": "...", "excerpt": "...", "tags": [...], "score": 0.9 } ] }
],
"suggested_layout": "hero"
```

- **branch** = a study dimension; **leads** = pointers to go deeper.
- `suggested_layout`: **hero** (one dominant result) · **deck** (one branch, many leads) ·
  **tree** (several branches) · **explore** (weak / no strong lead). The client owns the final
  layout; this is only a hint.
- The same `{kind, label, featured, n, leads}` + `suggested_layout` contract is returned by
  `POST /api/ask/branched` and `POST /api/search/branched`.

## Following drill links → shoresh

The card `drill`/`syntax` paths point at shoresh. To localize per-word data, append
`?gloss_lang=<DisplayName>`.

> **Naming note:** bcv-RAG's `lang` is an **ISO code** (`ind`); shoresh's `gloss_lang` is a
> **display name** (`Indonesian`). The drill links don't carry it — you append it. Get valid
> names from `GET {SHORESH_BASE}/gloss-languages`, or map ISO → name (`eng`→`English`,
> `spa`→`Spanish`, `deu`→`German`, `ind`→`Indonesian`, …).

**`GET {SHORESH_BASE}/verse/{USFM}/{chapter}/{verse}?gloss_lang=Indonesian`**

```jsonc
{ "book": "JHN", "chapter": 3, "verse": 16, "lxx": [ ... ],
  "spine": { "language": "grc", "words": [
    { "idx": 3, "surface": "ἠγάπησεν", "lemma": "ἀγαπάω", "strong": "G25",
      "morph": "...", "translit": "...",
      "gloss": "cinta",                     // localized per-word gloss (Hebrew + Greek)
      "sense": "...",                       // Hebrew only: binyan-correct localized sense
      "domain": "Love, Affection, Compassion" // Greek NT only: Louw-Nida semantic domain
    } ] } }
```

**`GET {SHORESH_BASE}/wordstudy/{STRONG}?gloss_lang=Indonesian`** — a composite word study:
localized headline `gloss`, `keyness` (how distinctively biblical), `stems` (per-binyan
senses for Hebrew verbs), `lex_senses`, `senses`, `sense_distribution`, `domains`, `siblings`,
and `tw[]` (Translation-Words articles, each with `title` + `definition`).

**`GET {SHORESH_BASE}/structure/{USFM}/{chapter}/{verse}/syntax`** — the clause→phrase syntax
tree (the passage card's `syntax` link).

## Endpoint reference

### bcv-RAG (`{BCV_RAG_BASE}`)

Key required only on `/api/ask`, `/api/ask/branched` (LLM), `/mcp`, and writes; everything else is open.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/ask` | Question → cited answer + cards + branches |
| POST | `/api/ask/branched` | Same, results as the branch/lead tree |
| GET | `/api/search` | Keyword / structured retrieval; `?semantic=true` adds vector (open, $0) |
| GET | `/api/search/branched` | Search results as branches |
| POST | `/api/study` | Build a study packet for a query |
| GET | `/api/concordance/{word}` | Occurrences of a word |
| GET | `/api/cross-references/{bbcccvvv}` | Cross-references for a verse (8-digit ref) |
| GET | `/api/entities`, `/api/entity/{id}` | Biblical people/places |
| GET | `/api/topics`, `/api/topic/{id}` | Topical index |
| GET | `/api/trees`, `/api/tree/{name}[/{path}]` | Browsable trees (entities, topics) |
| GET | `/api/chunk/{chunk_id}` | Raw source chunk behind a citation |
| GET | `/api/health` · `GET /` | Liveness / discovery (open) |
| POST/GET | `/mcp` | MCP tool surface — see the [MCP Guide](mcp.md) |

### shoresh (`{SHORESH_BASE}`) — all accept `?gloss_lang=` where a gloss is returned

| Path | Purpose |
|---|---|
| `/verse/{book}/{ch}/{v}` | Interlinear: per-word gloss, sense, domain (+ LXX parallel for OT) |
| `/wordstudy/{strong}` | Composite word study (gloss, stems, senses, domains, TW articles) |
| `/word/{strong}` | Concordance for a Strong's number |
| `/senses/{strong}` | Sense distribution for a Strong's number |
| `/lexeme/{lex}` | Lexeme profile (stems × senses × counts × sample refs) |
| `/concept/{word}` | Words sharing a concept |
| `/domain/{code}` | Every lexeme in a Louw-Nida / SDBH semantic domain |
| `/tw/{strong}` | Translation-Words article(s) for a Strong's number |
| `/bridge/{strong}` | Hebrew ↔ Greek (LXX) equivalents |
| `/morph` | Morphology search |
| `/structure/{book}/{ch}/{v}[/syntax]` | Verse clause/phrase structure |
| `/speakers`, `/speakers/at/{book}/{ch}/{v}`, `/speaker/{name}` | Speaker / red-letter index |
| `/participants/{book}/{ch}/{v}`, `/coref/…`, `/frame/…` | Coreference / semantic-role data |
| `/gloss-languages` | Languages available for `gloss_lang` (display names) |
| `/words`, `/gloss/{word}` | Vocabulary lookups for a trainer |
| `/health` | Liveness |

## Notes & good practices

- **Don't hard-code English** — either omit `lang` (auto-detect) or pass the reader's UI
  language; pass `"lang": "en"` only where you specifically need English.
- **Read the resolved `lang`** from each answer and use it consistently for display and for
  the `gloss_lang` you append to drill links.
- **Treat cards as additive** — new `kind`s may appear; render what you recognize, ignore
  the rest. Same for extra fields on existing objects.
- **8-digit refs** (`bbcccvvv`) encode book·chapter·verse (`43003016` = John 3:16); shoresh
  paths use the 3-letter USFM code + numeric chapter/verse instead.
- **Errors** are standard HTTP: `401` (missing/invalid key), `400` (bad parameters), `422`
  (validation). Endpoints are best-effort — enrichment that can't be produced is simply
  omitted rather than failing the whole response.
