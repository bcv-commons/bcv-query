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
pretty_name: Tanakh to Greek NT clauses similar
---

# tanakh-nt-clauses-similar @TAG@

For every Tanakh clause, the @TOP@ most similar Greek New Testament clauses, by contextual vectors in one Hebrew–Greek space:
ids and scores only, no text, no target-language data. Computed (no model choice, no human check). Code @CODE@
(bcv-commons, `shoresh/macula/build_clauses_similar.py`, the same build as clauses-similar @TAG@).

| File | Rows | Columns |
|---|---|---|
| `data/tanakh-nt.parquet` | @ROWS@ (@HEB_CLAUSES@ Tanakh clauses) | `clause_key` (hebrew-clause-layout), `rank`, `nt_clause` (greek-nt-clause-layout `first`), `score` (cosine) |
| `checks.json` | | the yardsticks |

Use: join `nt_clause` to a translation's own New Testament through a word alignment, so a drafter sees how the team rendered the
nearest NT clause. Median score of the best NT clause @MED1@, of the tenth @MED10@.

## How

As clauses-similar: a clause vector is the mean of its content words' occurrence vectors (BEREL 3.0 for Hebrew, GreBerta for
Greek), each text centred on its own mean; Greek mapped onto the Hebrew space by orthogonal Procrustes on @MAP_PAIRS@
Tanakh–Septuagint word pairs that MACULA Hebrew aligns. No New Testament pair trains the map; the check of the space in that
direction: Salkinson's Hebrew NT verse finds its Greek NT verse among @CAND@ at recall@1 @R1@, recall@10 @R10@.

Similar means close in the encoders' space (shared vocabulary and phrasing, then theme), not the same meaning; quotations of the
Tanakh in the NT tend to rank high, but this table is no list of quotations.

## Sources and licence

| Part | Source | Licence |
|---|---|---|
| Words, clauses, Tanakh–Septuagint alignment | MACULA Hebrew and Greek (Clear Bible) | CC BY 4.0 |
| Septuagint words (the map) | GLAUx Septuagint (Alek Keersmaekers, KU Leuven) | CC BY-SA 4.0 |
| Vector models | BEREL 3.0 (DICTA), GreBerta (Riemenschneider and Frank) | Apache 2.0 |

CC BY-SA 4.0, because the map is trained on GLAUx.
