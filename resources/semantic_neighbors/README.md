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

## Committed service forms (small, tracked — the parquet is the bulk/gitignored source)
Two flattened views of the `high`+`prior` tiers (plus antonyms), for the shoresh `/field` + `/concept`
endpoints:

- **`by_strong.tsv`** — rolled lexeme→Strong's (`strong, neighbor, neighbor_gloss, relation,
  confidence, score`). Fallback / legacy form. **Lossy for meaning:** 64% of Strong's numbers cover
  >1 lexeme, so it *merges* distinct words' fields (`H0352` = ram **and** oak **and** pillar → one
  blurred list).
- **`by_lexeme.tsv`** — homograph-precise, **not** rolled (`strong, lexeme, lexeme_gloss,
  neighbor_strong, neighbor_lexeme, neighbor_gloss, relation, confidence, score`). Keeps each MACULA
  lexeme separate with its own gloss + neighbors. `semantic_field()` serves this split under
  `lexemes` and falls back to `by_strong` for Greek / lexeme-less codes.

Both regenerate from `neighbors.parquet` (`_write_by_strong` / `_write_by_lexeme`).

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

(Note: the sections above predate 2026-08's signal additions — BDB etymological roots, T'OMIM
parallelism, Hebrew WordNet, BHSA structural pairs, and a cross-lingual/Wiktionary "corroborated" tier
are now also active signals, not reflected in the schema/quality numbers above. See
`shoresh/macula/build_semantic_neighbors.py` for the current signal list.)

## Published subset — `published_pairs.tsv` (2026-08, gitignored, on HF)

The confident subset of the pack, published standalone at
[bcv-commons/semantic-neighbors](https://huggingface.co/datasets/bcv-commons/semantic-neighbors)
(7,977 pairs, CC0). Built by `shoresh/macula/build_published_pairs.py`, which merges three independent
publication-confidence gates:

- **`cross_signal`** — pairs asserted by >= 2 methodologically independent signal families (not just
  >= 2 raw source tags — see `build_confidence_tiers.py` for the family grouping). 70.2% SDBH
  `core`-agreement on its own.
- **`llm_verified`** — single-signal-family pairs, individually judged by a dedicated LLM pass
  (`shoresh/macula/verify_pairs_llm.py`, ~$3 for ~33,500 pairs). Only "yes" verdicts published. 69.5%
  on its own.
- **`sefer_hashorashim_verified`** — candidates from Radak's *Sefer HaShorashim* (Public Domain,
  medieval rabbinic Hebrew root dictionary, via Sefaria — `build_sefer_hashorashim.py`), also
  LLM-verified the same way (~$1.83 for ~19,600 pairs). 62.9% on its own (this gate's *unique*
  contribution, after removing overlap with the other two — the full "yes" tier alone was 74.1% on a
  761-pair checkable sample before dedup).

1,241 pairs pass **more than one** gate — that subset scores 78.4%, the highest-confidence layer in the
dataset. These levers were chosen because raising the WHOLE pack's average wasn't working —
cross-signal/cross-source agreement was the single biggest quality lever found in this whole project
(see `internal-docs/domain-replacement-roadmap.md`, not in this repo's public history). The
SDBH-agreement percentages are an internal proxy, not an independent correctness audit — see the HF
dataset card for the full caveat before treating them as ground truth.
