---
license: cc-by-sa-4.0
language:
- hbo
- grc
tags:
- bible
- hebrew
- greek
- clauses
- similarity
pretty_name: Clauses similar (Tanakh, Greek NT)
---

# clauses-similar @TAG@

For every clause of the Tanakh and of the Greek New Testament, the @TOP@ most similar clauses of the same text outside its own
verse, by contextual vectors: ids and scores only, no text. Computed (no model choice, no human check); the "-similar" ending
marks a table computed from encoder vectors. Code @CODE@ (bcv-commons, `shoresh/macula/build_clauses_similar.py`).

| File | Rows | Columns |
|---|---|---|
| `data/hebrew.parquet` | @HEB_ROWS@ (@HEB_CLAUSES@ clauses) | `clause_key`, `rank`, `other`, `score` |
| `data/greek-nt.parquet` | @GRC_ROWS@ (@GRC_CLAUSES@ clauses) | the same |
| `checks.json` | | the yardsticks below |

Clause keys are those of hebrew-clause-layout (`clause_key`) and greek-nt-clause-layout (`first`), the keys of clause-columns.
`score` is the cosine of the two clause vectors.

## How

A clause vector is the mean of its content words' occurrence vectors (noun, verb, adjective, adverb; all its words when it has
none), each text centred on its own mean. Hebrew: BEREL 3.0 on the unpointed Tanakh; Greek: GreBerta on the Greek NT; four
layers. The Greek side is mapped onto the Hebrew space (orthogonal Procrustes on @MAP_PAIRS@ Tanakh–Septuagint word pairs that
MACULA Hebrew aligns), so both tables and tanakh-nt-clauses-similar share one space.

## Yardsticks

| Check | Figure |
|---|---|
| Chronicles clauses whose best neighbour outside Chronicles is in Samuel–Kings | @CHR_HIT@ (those books hold @CHR_BASE@ of the clauses: lift @CHR_LIFT@) |
| Matthew clauses whose best neighbour outside Matthew is in Mark or Luke | @MAT_HIT@ (share @MAT_BASE@: lift @MAT_LIFT@) |
| Salkinson's Hebrew NT verse → its Greek NT verse among @CAND@ (the cross-language space; no NT pair trains the map) | recall@1 @R1@, @10 @R10@ |

Similar means close in the encoders' space: shared words and phrasing first, then theme. It is a retrieval aid, not a claim
that two clauses mean the same.

## Sources and licence

| Part | Source | Licence |
|---|---|---|
| Words, clauses, Tanakh–Septuagint alignment | MACULA Hebrew and Greek (Clear Bible) | CC BY 4.0 |
| Septuagint words (the map) | GLAUx Septuagint (Alek Keersmaekers, KU Leuven) | CC BY-SA 4.0 |
| Vector models | BEREL 3.0 (DICTA), GreBerta (Riemenschneider and Frank) | Apache 2.0 |

CC BY-SA 4.0, because the map is trained on GLAUx.
