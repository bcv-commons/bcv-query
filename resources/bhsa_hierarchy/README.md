# `bhsa_hierarchy/` — Hebrew broader/narrower hierarchy from BHSA grammar

Text-anchored, no SDBH/MARBLE as an input at any stage (SDBH retired as a validation yardstick, see
`internal-docs/text-anchored-semantics-plan.md`). Full derivation history and every finding below:
`internal-docs/phase-c-instrument-calibration-plan.md`.

## Scope: how this compares to SDBH's domain hierarchy — read this first

**This is a small, different kind of thing, not a smaller version of the same thing.** Concrete
numbers: SDBH's domain tags (`resources/semantic_domains/hbo.tsv`) cover **7,198** distinct Hebrew
Strong's numbers — near-total coverage of the ~6,598-word OT vocabulary. `published_hierarchy.tsv`
covers **403** — about 6% of the vocabulary, 18x smaller by that measure alone.

But the size gap isn't the main difference:

- **SDBH is a classification system** — every word gets filed into one of 641 fixed topic buckets
  (2-level: major domain → subdomain). Two words in "Kinship" aren't related to each other directly,
  they're both just tagged "Kinship." Good for topical search / faceted browsing / "show me
  everything in this semantic field."
- **This is a relation graph** — direct word-to-word broader/narrower pairs (e.g. "Nile IS-A River"),
  no bucket in between. Good for query narrowing/broadening on a *specific* term, WordNet-style is-a
  reasoning — but only where a measured edge exists, which today is a small, patchy set, not full
  coverage.

They're complementary, not alternate versions of each other. If what you actually want is SDBH's
*role* (topical grouping over most of the vocabulary), the closer analog already in this project is
`resources/semantic_neighbors/domain_clusters.tsv` (634 Louvain communities), not this directory —
this directory fills a gap neither of those addresses (genuine multi-level is-a chains between
specific words), at much narrower coverage so far.

## Two layers — internal (full) vs. published (pruned)

Same split as `semantic_neighbors/`'s parquet-vs-TSV pattern.

- **`hierarchy_dag.tsv`** (internal) — the full DAG: 519 nodes, 636 edges, from apposition direction
  (BHSA grammar) + distributional inclusion (held-out verified). `tier`: `high` = independently
  CONFIRMED by `direction_yardstick.py`'s 5-seed held-out check; `medium` = UNDETERMINED there (usually
  held-out sparsity, not counter-evidence). `berel_cos`: BEREL-embedding relatedness (symmetric, not a
  direction check) — see `berel_relatedness_check.py`. Structurally messy: 28.9% multi-parent, one
  386-node hub-glued component, depth up to 9 — not meant for direct consumption, kept for provenance
  and as the source for the published layer.
- **`published_hierarchy.tsv`** (consume this) — pruned + tree-shaped: hub-anchored edges dropped
  (out-degree ≥ 6 in the internal DAG) and each node collapsed to its single best parent (tier, then
  `berel_cos`, as tie-break). 271 edges, max depth 4, largest component 21 nodes. **Edge-only**: rows
  are direct parent→child pairs; chaining rows into a multi-hop path is NOT asserted to be
  semantically coherent (checked directly — depth≥3 chains read as noise even after pruning, e.g.
  "head → great → River → Nile"). `published_manifest.json` carries the method + counts.

Shape target for the pruning was a one-time structural comparison to how SDBH/Louw-Nida publishes its
own domain hierarchy (2 levels, ~93 top-level domains, strict tree, branching ~8.9) — comparison only,
no SDBH data used as an input; the retirement decision is unchanged.

## Side files (diagnostic, not for consumption)

- `hierarchy_dag_flagged.tsv` — 2 edges `direction_yardstick.py` actively CONTRADICTED (dropped from
  the internal DAG, not deleted).
- `hierarchy_dag_suspect.tsv` — 17 medium-tier edges scoring below the BEREL random-baseline 25th
  percentile (flagged, not dropped — candidates for being noise apposition pairs).
- `dropped_edges.tsv` / `dropped_edges_yardstick.tsv` / `direction_llm_verdicts.tsv` — the 581-edge
  pool `build_hierarchy_dag.py`'s acyclic filter couldn't place at all, plus two independent
  adjudication attempts (held-out yardstick, Haiku) that only double-corroborated 93/569 pairs — left
  excluded, recorded as a closed negative result.
- `apposition_directed.tsv` / `construct_pairs.tsv` / `clause_mother.tsv` / `direction_verdicts.tsv` —
  intermediate BHSA-grammar extraction and the multi-seed direction verdicts feeding the tiers above.

## Regenerating

Order matters — each step consumes the previous one's output:

```
python -m macula.build_hierarchy_dag        # -> hierarchy_dag.tsv (untiered) + dropped_edges.tsv
python -m macula.direction_yardstick         # -> direction_verdicts.tsv (5-seed multi-seed)
python -m macula.tier_hierarchy_dag          # -> hierarchy_dag.tsv gains `tier`, hierarchy_dag_flagged.tsv
python -m macula.berel_relatedness_check     # -> hierarchy_dag.tsv gains `berel_cos`, hierarchy_dag_suspect.tsv
python -m macula.publish_hierarchy_dag       # -> published_hierarchy.tsv + published_manifest.json
```
