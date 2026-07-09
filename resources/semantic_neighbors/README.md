# `semantic_neighbors/` — CC0 data-derived semantic proximity

A **CC0** "which lexemes are semantically near" signal — a clean stand-in for the NC Louw-Nida / SDBH
domains, **re-derived from open data** rather than laundered from the MARBLE taxonomy (which is UBS
"used with permission," not CC-BY). Design + rationale: `internal-docs/semantic-neighbors-pack.md`.

## Schema — `neighbors.parquet` (bulk, gitignored; regenerable)
| column | meaning |
|---|---|
| `lexeme` | MACULA anchor (`hbo:0430`) — CC-BY, homograph-precise |
| `neighbor_lexeme` | a semantically near lexeme |
| `score` | 0..1 consensus strength (mean-centered cosine + corroboration boost) |
| `sources` | which signals agreed: `emb` \| `lxx` \| `gloss` \| `llm` (pipe-joined) |
| `confidence` | `high` (LLM prior **and** embedding agree) \| `recall` (embedding-only) \| `prior` (LLM-only) |
| `relation` | `similar` \| `antonym` (LLM flagged an embedding false-positive — opposites co-occur) |

**Consume by tier:** `confidence=high` for domain-grade tie-breaking, `high`+`prior` for good coverage,
everything for broad concept expansion; **exclude `relation=antonym`** from any "similar" use.

`manifest.json` (committed) carries the counts + `content_sha256`. Hebrew/OT only (the context
embeddings are Hebrew clauses).

## How it's derived (all clean sources)
- **`emb`** *(empirical, primary)* — each lexeme's occurrence **clauses** are bge-m3 embeddings
  (`occurrences/context_emb.npz`); mean-pool per lexeme → centroid; **mean-center** to remove the
  "generic biblical clause" direction (embedding anisotropy) → cosine kNN.
- **`lxx`** — Hebrew lexemes the LXX renders into the **same Greek** Strong's (`lxx_bridge.tsv`, CC-BY).
- **`gloss`** — lexemes whose English glosses share content words.
- **`llm`** *(scholarly prior)* — a biblical-Hebrew lexicographer model's syn/ant judgments
  (`bcv-RAG/scripts/build_llm_neighbors.py` → `llm_edges.tsv`, `source=llm`). Supplies the *synonymy*
  the distributional signal structurally can't, and flags antonyms the embedding confuses.

**The tiering is the point:** LLM (prior) and embedding (empirical) are independent, so **agreement =
trust** — `high` edges are LLM-asserted AND embedding-confirmed. In a demo run, `high` scored **100%**
same-domain and LLM-only `prior` **95%** vs **42%** for embedding-only — the intersection is
domain-grade. `llm` provenance is a clean *output* reconstruction of the scholarship (a prior, not
attestation); it is only trusted where the empirical layer confirms it.

Public texts + an open model + CC-BY tables + LLM output → **CC0**. No MARBLE data is an input or output.

## Quality (internal yardstick — not shipped)
`--validate` scores derived neighbors against the NC domains (we may *use* MARBLE here, just not
publish it): **41.7%** of neighbors share ≥1 domain vs **15.1%** random baseline (2.75×). Spot-checks
are sensible — `hbo:0430` (God) → god / Yahweh / idols; `hbo:2617` (ḥesed) → faithful / refuge /
sustain. It captures a broader relatedness than the specific taxonomy, by design.

## Regenerate
```bash
python -m macula.build_semantic_neighbors --validate     # -> neighbors.parquet + manifest.json
```
Rebuild only when the embedding model or the spine changes (language-independent, publish-once).

## Uses
- The aligner: a tie-breaking prior for the gloss/neural runs (published to `bcv-commons` alongside
  the clean prior pack).
- shoresh `/concept`: a domain-free semantic field.
- The NC `semantic_domains/` table stays for internal richness; this is the **publishable** layer —
  two layers, license-separated, same purpose.
