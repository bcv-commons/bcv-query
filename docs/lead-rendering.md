# Rendering leads — a client guide

How a client should turn a **branched** response (`/api/search/branched`, `/api/ask/branched`,
or the MCP `search_branched` tool) into a sensible UI: what to show **up front**, what to keep
**one click away**, and how to use the per-lead scores. This is the "starting point" reference —
the server supplies shape + signals; **the client owns the layout** (Phase-3 contract).

See [Client Integration Guide](client-guide.md) for connection/auth and the response envelope.

## The shape you get

```jsonc
{
  "branches": [
    {
      "kind": "lexicon", "label": "Léxico / palabras",
      "featured": true,          // does this DIMENSION matter for the query (intent-driven)
      "n": 64,                   // TOTAL matches — the "browse all" count (keep it large)
      "leads": [                 // a ranked slice (top per_branch), each:
        { "kind": "lexicon", "headline": "...", "excerpt": "...", "tags": [...],
          "score": 0.0164,       // raw RRF (k=60) — implementation detail
          "confidence": 1.0,     // score ÷ branch-top  (RELATIVE, per branch)
          "agreement": 0.16,     // score ÷ theoretical-max (ABSOLUTE, cross-branch)
          "featured": true,      // server DEFAULT hint — override freely
          "drill": "<chunk_id>"  // fetch the full item
        }
      ]
    }
  ],
  "suggested_layout": "hero"     // hero | deck | tree | explore
}
```

Two independent signals, by design:

| Field | Meaning | Use it for |
|---|---|---|
| **branch `featured`** | this study dimension is relevant to the query (intent) | which branches to expand vs collapse |
| **branch `n`** | total matches | the "browse all (n)" affordance |
| lead **`confidence`** | strength **within** its branch (`score÷top`, relative) | per-branch front density / ordering |
| lead **`agreement`** | strength in **absolute** terms (cross-branch) | suppressing weak-consensus branches |
| lead **`score`** | raw RRF | debugging / your own scoring |
| lead **`featured`** | server default front hint | a fallback if you don't compute your own |

## The recommended rendering algorithm

Three tiers: **cards** (synthesized, from `/api/ask`'s `cards[]`) on top → **featured leads**
(a small preview under each relevant branch) → **browse-all** behind a `▸ (n)` expander.

```text
for each branch, sorted featured-first then by top confidence:
    render header:  {label}  ({n})  ▸
    # FRONT — the small preview shown without expanding:
    front = leads
            .filter(l => l.confidence >= FRONT_RATIO)     # near the branch's best
            .slice(0, FRONT_MAX)                           # cap the count
    if AGREE_MIN:                                          # optional stricter gate:
        front = front.filter(l => l.agreement >= AGREE_MIN)  # only genuinely-strong
    render each front lead as a small card/row (headline + excerpt)
    # BROWSE — on ▸ expand, list ALL leads (and page to n via drill/offset)
```

Recommended defaults (tune per client):

```
FRONT_RATIO = 0.8    # a lead is "front" if within 80% of its branch's best
FRONT_MAX   = 3      # at most 3 leads up front per branch
AGREE_MIN   = 0      # 0 = off; try ~0.3 for a stricter, cleaner front
```

The server already sends a `featured` flag computed with `FRONT_RATIO`/`FRONT_MAX` — if you
don't want to compute your own, just use `leads.filter(l => l.featured)`.

## Why relative + absolute (it makes the two hard cases behave)

- **Broad query ("love")** — leads are a tight cluster: `confidence ≈ [1.0, 0.98, 0.97, 0.95…]`,
  `agreement ≈ [0.16, 0.16, 0.15…]`. `FRONT_RATIO` admits many, so **`FRONT_MAX` caps the front to
  ~3 examples**; the other 61 stay behind `▸ (64)`. If you set `AGREE_MIN ≈ 0.3`, the branch shows
  **collapsed with just its count** (nothing is strongly-agreed) — a stricter, cleaner front.
- **Specific query (a verse ref)** — one lead dominates: `confidence ≈ [1.0, 0.34, 0.32…]`,
  `agreement ≈ [0.47, 0.16…]`. Only the top clears `FRONT_RATIO`, so the **front shows the single
  clear winner**; the rest are one `▸` away.

Same rules, opposite results — because `confidence` is relative and `agreement` is absolute.

## Layout hint

`suggested_layout` is a hint for the overall arrangement; the client decides:

| value | meaning | typical render |
|---|---|---|
| `hero` | one dominant result | a big primary card + collapsed branches |
| `deck` | one branch, many leads | a horizontal/vertical deck of that branch |
| `tree` | several relevant branches | the branch list above, each with its front preview |
| `explore` | weak / no strong lead | show branches collapsed with counts; invite drill-in |

## Drilling in

- Each lead's `drill` is a `chunk_id` → `GET /api/chunk/{chunk_id}` for the full body.
- Passage/word leads from `/api/ask` `cards[]` carry shoresh `drill` paths (`/verse/…`,
  `/wordstudy/…`) — see [Client Integration Guide](client-guide.md#following-drill-links--shoresh).
- To page past the returned `leads` slice toward `n`, re-request the branched endpoint with a
  larger `per_branch` (the browsable list can be as large as you like — navigation is cheap).

## Checklist

1. Keep `n` visible as "browse all"; never hide results — just tier them.
2. Front = `confidence ≥ FRONT_RATIO`, capped at `FRONT_MAX` (optionally `agreement ≥ AGREE_MIN`).
3. Expand vs collapse a branch by its **branch** `featured` flag; order featured-first.
4. Treat `featured` on a lead as a default you can override; `score` is raw and optional.
5. Cards (`/api/ask`) are the primary front surface; branch leads are the secondary preview.
