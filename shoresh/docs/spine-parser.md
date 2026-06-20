# Spine parser — specification

The contract for the UHB/UGNT spine parser, locked before implementation.
Background and rationale: [embedding-enrichment.md](embedding-enrichment.md).
Validation and data: [`../spine/`](../spine/).

Status: **implemented** — [`spine/parse.py`](../spine/parse.py) (+
[`spine/common.py`](../spine/common.py)). Reconciliation solved at 99.59%
OT-wide (`spine/reconciliation/summary.md`). This doc is the contract the
parser implements.

## Inputs (pin exact versions)

| Input | Source | Pin |
|---|---|---|
| UHB (Hebrew OT) | `unfoldingWord/hbo_uhb` USFM | **`v2.1.32`** (latest; byte-identical to the validated `master`) |
| UGNT (Greek NT) | `unfoldingWord/el-x-koine_ugnt` USFM | **`v0.34`** (latest) |
| BHSA↔Strong's crosswalk | OpenHebrewBible `002` | `BHS-with-Strong-no.csv` (etcbc4c-keyed) |
| Versification map | OpenHebrewBible `019` | `BHSA_KJV_versification_all_differences.csv` |
| Strong's equivalences | `spine/strongs_equivalence.tsv` | in-repo |

License note: several inputs are non-commercial — see
[`../spine/ATTRIBUTION.md`](../spine/ATTRIBUTION.md).

## Output

One record per original-language word, in text order:

```
(book, chapter, verse, index, surface, strong, lemma, morph)
```

- `book`/`chapter`/`verse` — UHB/UGNT (standard) versification.
- `index` — 0-based word position within the verse.
- `surface` — the pointed Hebrew/Greek form (joiner-split available).
- `strong` — content Strong's (last `:`-segment), normalized (see below).
- `lemma`, `morph` — as given.

Downstream, the **Lexical** prefix line keeps content words (noun/verb/
adjective heads), dropping function morphemes (article, preposition,
conjunction, DOM) as noise.

## Parsing rules

1. **Per-word extraction** — match `\w surface|...strong="..." ...
   x-morph="..."\w*`. No `\zaln`, **no dedup** (UHB/UGNT are the source
   texts, not a translation alignment).
2. **Morpheme segmentation** — split `x-morph` (after the `He,`/`Gr,`
   tag) and `strong` on `:`. Prefix segments precede the head POS;
   `S*` segments are suffixes.
3. **Strong's normalization** — `[HG]0*(\d+)[a-z]?` → integer; the
   content Strong's is the last `:`-segment. Then apply
   `strongs_equivalence.tsv` (variant → canonical).
4. **BHSA-comparable count** (only when reconciling/joining counts):
   count non-`S` segments; expand portmanteau `Rd` (prep+elided article)
   to 2.

## Fidelity assertions (run at parse time)

- **Triangulation** — per word, the joiner-piece count of `surface`, the
  `:`-prefix count of `strong`, and the `:`-segment count of `x-morph`
  must agree. Mismatch → flag the word (malformed source).
- **Strong's coverage** — per book, ≥99% of content words carry a
  resolvable Strong's after equivalences (the reconciliation baseline).
  A drop flags a version/parse problem.

## Joins (downstream, not the parser's job but specified here)

- **Spine ↔ BHSA syntax (Layer 4)** — match BHSA role-head → spine word by
  Strong's within the verse (BHSA Strong's via the `002` crosswalk).
  ~99.6% OT-wide.
- **Spine ↔ translation chunk** — map the chunk's English reference onto
  the spine verse via the `019` versification map (~4% of verses differ;
  e.g. Genesis 32).

## Out of scope

- The rigorous per-node BHSA-version map (only needed for exact
  cross-corpus token queries; the loose Strong's join covers Layer 4).
- The last ~0.4% reconciliation tail (sparse, diminishing returns).
- UGNT↔Greek-syntax: NT syntactic annotation is thin; Layer 4 is OT-first.
