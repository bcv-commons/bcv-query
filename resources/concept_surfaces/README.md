# concept_surfaces — Strong's → surface family (per language)

Roadmap **R1**. For each language, the set of in-language **surface renderings**
that align to a Strong's number — i.e. every way a concept actually appears in
that language's Bible(s). The inverse of [`aligned_lex/`](../aligned_lex)
(`surface → Strong's`), re-keyed by Strong's.

**Why:** at query time, expand a query word to *every* rendering of its concept
before full-text search — so a search for "love" also matches "beloved",
"caridad", "charité", inflections, and synonyms that exact-match would miss.
Biggest lever on recall over prose (study notes, other-language Bibles).

## Files
`<lang>.tsv`, one per language (ISO 639-3), for the 10 languages that have an
`aligned_lex`: arb, asm, ben, eng, fra, hau, hin, por, rus, spa.

## Schema
| column | meaning |
|---|---|
| `strong` | `H####` / `G####`, normalized (the concept key) |
| `surface` | an in-language rendering aligned to that Strong's |
| `count` | alignment occurrences of this (strong, surface) pair |
| `share` | **surface→Strong's confidence**, carried from `aligned_lex` = `count / (this surface's total alignments)`. High = the surface genuinely renders this concept; ~0 = alignment-span noise (a function word like "of"/"de" bleeding into a content word's span). |

Rows are sorted by `strong` asc, then `count` desc — a concept's primary
rendering comes first.

## Using it (filter the noise)
All pairs are kept (no build-time floor) so the table stays reusable. **Filter on
`share`** to get a clean family — a ~`0.10` floor drops the function-word noise
(matches the floor `bcv-RAG/query/concept_expand.py` already uses on the same
underlying data). Example (eng, `G0026` agape): keep `love`, `love-feasts`; drop
`of`, `and`, `the` (share ≈ 0).

## Source / license
Derived from `resources/aligned_lex/<lang>.tsv` (Clear-Bible/Alignments manual
word alignment). License inherits `aligned_lex`. Re-derivable:
`python3 bcv-RAG/scripts/build_concept_surfaces.py`.
