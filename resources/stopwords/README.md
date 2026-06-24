# stopwords — data-derived function-word stopwords (R2)

Roadmap **R2**. Per-language function words (articles, conjunctions, particles,
prepositions) **derived from alignment data**, not hand-authored — so they're
multilingual, reproducible, and reviewable, retiring the "needs native review"
caveat on the curated lists in `analyzer_lang/<lang>.json`.

A surface qualifies when **every** one of its primary renderings (alignment
`share ≥ 0.10`) maps to a *function* Strong's (`is_function=1` in
`strongs_freq.tsv`) **and** it occurs often enough to be a real function word
(total alignment `count ≥ 10` — the frequency gate that keeps rare content words
with one spurious function alignment, like "administrator", out).

The analyzer **unions** these with the hand-authored `analyzer_lang` stopwords —
they add the archaic/biblical particles the curated list misses (`thence`, `unto`,
`verily`, `whence`; es `aunque`, `bajo`, `ciertamente`).

## Files
`<lang>.tsv`, one per aligned language (arb, asm, ben, eng, fra, hau, hin, por,
rus, spa). ~1,671 stopwords total.

## Schema
| column | meaning |
|---|---|
| `surface` | lowercased in-language token (the stopword) |
| `codes` | the function Strong's it aligns to (comma-joined, provenance) |
| `max_share` | highest surface→Strong's share among them (confidence) |

## Source / license
Derived from `resources/aligned_lex/<lang>.tsv` + `resources/strongs_freq.tsv` by
`bcv-RAG/scripts/build_stopwords.py`. License inherits `aligned_lex`
(Clear-Bible/Alignments). Re-derivable.
