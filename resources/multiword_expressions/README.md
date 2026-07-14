# Multi-word expressions (M1)

`<iso>.tsv` — for each language, **target phrases and the original-language lexeme(s) they render** —
so the analyzer can recognize a multi-word concept in a query and map it to its Strong's. Built by
`bcv-RAG/scripts/build_multiword.py` from `bcv-commons/lexeme-alignments` (the aligner's contiguous
multi-word surfaces).

## Two kinds
| `kind` | meaning | example |
|---|---|---|
| **`phrasal`** | a target phrase spanning **2+ original lexemes** | `bear fruit → {G2592, G2590, G5342}`, `beth shemesh → {H1053, H1030}` |
| **`fertility`** | a multi-word target phrase rendering **one** original lexeme | `only begotten ← G3439`, `loving kindness ← H2617`, `acacia wood ← H7848` |

## Columns
| col | meaning |
|---|---|
| `surface` | the multi-word target phrase (lowercased, ≥2 tokens) |
| `strongs` | the original Strong's number(s), share-ordered |
| `lexemes` | the MACULA lexeme(s) (homograph-precise anchor) |
| `kind` | `phrasal` (multi-lexeme) or `fertility` (single-lexeme) |
| `confidence` | best `share × hi_conf` — *placement* quality (mostly high; use `count` to rank reliability) |
| `count` | total aligned occurrences — the **evidence** axis (higher = more reliable) |
| `methods` | `eflomal` / `gloss` / `neural` that attested it |

## Quality — read before using
Derived from **type-level** alignments (surface→lexeme, no verse/occurrence ids), so a phrase's lexeme
*set* is the corpus union — we can't see per-verse co-occurrence. Filters applied: **content lexemes
only** (POS from the prior pack — drops article/preposition glue), **same-testament** sets (drops OT/NT
homograph pooling), `count ≥ 2`, `share ≥ 0.10`, and a leading-short-token drop on fertility.

- **`phrasal` is the high-precision subset** — genuine collocations, verb periphrases, and compound
  names. Prefer it for query phrase-detection.
- **`fertility` is mixed** — real content phrases (`loving kindness`, `acacia wood`, place names) plus
  alignment fragments (`according records`). **Threshold on `count`** (≥5 is clean); low-count fertility
  is noisy.

## Coverage (published languages)
~21k entries over 11 languages; ~1.3k `phrasal`. Yield scales with target morphology — compounding
languages (ind 368, swe 193, asm 123) surface more phrases than 1:1-aligning ones (spa 18, rus 12).

## Build
```bash
python3 bcv-RAG/scripts/build_multiword.py            # all published langs
python3 bcv-RAG/scripts/build_multiword.py eng spa    # subset
```
Rebuild when `bcv-commons/lexeme-alignments` publishes new/updated partitions. CC0 (derived counts).
