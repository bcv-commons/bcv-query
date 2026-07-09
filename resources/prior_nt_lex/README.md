# `prior_nt_lex/` — LXX cross-testament NT-gap dictionary (per language)

A **language-tailored prior** for the aligner's gloss/neural runs: candidate NT (Greek) renderings
derived by carrying a language's own **OT** attestation across the LXX bridge into its **NT**. Built
from the published `bcv-commons/aligned-lex` (OT rows) + `resources/lxx_bridge.tsv`. A *prior* (noisy
candidates), not truth — the aligner's run confirms it. Build: `bcv-RAG/scripts/build_nt_lex_priors.py`.

## Schema — `<iso>.parquet` (bulk, gitignored; regenerable)
| column | meaning |
|---|---|
| `grc_lexeme` / `grc_strong` | the NT Greek lexeme this prior is for (`grc:1656` / `G1656`) |
| `candidate_surface` | target-language surface proposed as an NT rendering |
| `via_hebrew` | Hebrew strong(s) that bridged it (LXX) |
| `ot_count` | how often the language attested this surface for the bridged Hebrew (OT) |
| `share` | its share among candidates for this Greek lexeme |
| `nt_confirmed` | surface already attested in the language's own NT eflomal (bridge agrees) |
| `nt_total` | total NT attestation for this Greek lexeme in the language — **0 = NT gap = highest value** |

## Use
The gloss run matches target tokens against `candidate_surface` (seeds languages whose NT dictionary was
thin); the neural run uses them as anchors / re-ranking. Prioritise rows where `nt_total` is low.

## License
**CC-BY-4.0** — derived from `aligned-lex` (CC0) + `lxx_bridge` (CC-BY MACULA `greekstrong`); attribute
MACULA. Surfaces belong to each source translation (per-edition license, see aligned-lex).

## Coverage note
Needs the language's **OT** in `aligned-lex`. Languages published NT-only (e.g. `fra`) yield nothing
until their OT partition is published.
