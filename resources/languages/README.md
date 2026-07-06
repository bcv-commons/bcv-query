# `languages/` — code-keyed language registry (scaled to all ISO 639-3)

The built, **all-languages** registry — the superset successor to the hand-curated
[`related_langs/`](../related_langs/README.md) bootstrap. Keyed by `iso639_3`, covering every
ISO 639-3 language (~7,900), so cross-language ranking and reference-language fallback work for
*any* language, not just onboarded ones. Design + roadmap: `internal-docs/languages-db-design.md`.

> **Status: Phase A (registry) + follow-ups + Phase B (relatedness) done.** Phase C
> (`languages.db` + cutover of the live consumers) is not built yet — see the design note.

## Files

| file | what |
|---|---|
| `languages.tsv` | one row per ISO 639-3 language — `iso639_3 · iso639_1 · name · glottocode · stock · group · branch · scripts · macrolanguage` |
| `related.tsv` | relatedness edges — `iso639_3 · rank · related_iso639_3 · distance · basis` (top-25 relatives per language) |
| `code_alias.tsv` | retired ISO 639-3 code → current code (`old_code · current_code`), so old citations still resolve |
| `_raw/` | downloaded source cache (git-ignored; re-fetched on build) |

## Relatedness (`related.tsv`)

Top-25 nearest relatives per language, ranked by **genetic distance** from the Glottolog
classification tree (shared-ancestor depth = `distance`, steps A→LCA→B; smaller is closer),
with **geographic distance** (Glottolog lat/long, great-circle) as the tiebreak among
genetically-equidistant siblings. `basis=genetic-glottolog`. Candidates share a `stock`
(cross-family relatedness is 0). Chosen over URIEL/lang2vec because Glottolog covers all ~7,800
classified languages (URIEL ~4,000) with the same tree-derived genetic signal and no heavy
dependency; URIEL *typological/lexical* distance is a future layer (add edges with a distinct
`basis`, blend at query time — the column keeps them separable).

**Pure linguistics** (the availability-agnostic rule): edges include ancient/extinct/creole
relatives (e.g. `eng`→Middle English, `hbo`→Moabite/Ugaritic). Consumers intersect with what's
actually resourced at use time — the registry never encodes availability.

## Columns & provenance

- `iso639_3`, `iso639_1`, `name`, `macrolanguage` — **ISO 639-3** tables (SIL, free): the code
  spine + individual↔macrolanguage links. Scopes `I` (individual) + `M` (macrolanguage); `S`
  (special, e.g. `mul`/`und`) excluded.
- `glottocode`, `stock` — **Glottolog CLDF** (CC-BY-SA), joined on the ISO code. `stock` = the
  top-level family (e.g. Indo-European, Afro-Asiatic). Language-level nodes preferred; dialect
  nodes fill ISO codes Glottolog only carries as dialects (e.g. `srp`/`hrv`). Macrolanguage rows
  (no Glottolog ISO of their own) inherit `stock` from a member individual.
- `group`, `branch` — the two Glottolog **classification-path** levels just below the stock
  (`stock/group/branch/…/language`). Tree depth varies and Glottolog has intermediate "filler"
  nodes (e.g. every Indo-European language gets `group = Classical Indo-European`, with the useful
  subdivision at `branch = Germanic`/`Italic`/…), so these are taken **verbatim**, not colloquial
  family names. Curated `related_langs/` values (Germanic/Romance/…) win at the Phase-C cutover.
- `scripts` — ISO 15924 codes from **CLDR** `languageData` (Unicode), keyed by 639-1 else 639-3;
  macrolanguage members inherit their macro's scripts (`cmn`→Hans via `zh`). CLDR only covers
  ~900 languages, so `scripts` is **sparse by nature** (~1,170 filled); the rest fill at cutover
  or stay blank.

Coverage at build: **7,925 languages** — `stock` ~98%, `glottocode` ~98%, `group` ~90%,
`branch` ~83%, `scripts` ~15% (CLDR-limited).

## Design rule (inherited from `related_langs/`)

This registry is **pure linguistics** — availability-agnostic. It carries **no**
`is_source` / `available` / `gloss_names` columns; which languages we actually serve is derived
data reconciled at cutover, never baked into the registry.

## Licences

Glottolog CC-BY-SA · ISO 639-3 free (SIL) · CLDR Unicode licence — all within the project's
licensing acceptance (see `internal-docs/roadmap.md`).

## Regenerating

```bash
python -m scripts.build_languages_registry            # Phase A: languages.tsv + code_alias.tsv
python -m scripts.build_languages_registry --no-net   #   (rebuild from the _raw/ cache only)
python -m scripts.build_language_relatedness          # Phase B: related.tsv (reads the cache)
```
(from `bcv-RAG/`). The `.tsv` outputs are the git-tracked source of truth; `_raw/` is a cache.
This README is hand-authored, not regenerated.
