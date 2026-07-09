# OT-in-NT quotations (via the LXX)

`quotations.tsv` — for each NT verse, the OT verse(s) it most likely quotes, found by matching
**content Greek Strong's** the NT shares with the Septuagint (LXX). Each verse is an IDF-weighted
bag of content Strong's and the score is their **cosine similarity** — rare shared words (ἄρτος,
μάννα) drive the match, common ones (θεός, λέγω) barely count, and the cosine's length normalization
stops long LXX verses (the 3-Kingdoms/Esther narrative expansions) from colliding with everything.
Built by `shoresh/lxx/build_quotations.py`.

## Columns
| col | meaning |
|---|---|
| `nt_ref` | NT verse (`MAT 4:4`) |
| `ot_ref` | OT verse quoted, **Masoretic/English numbering** |
| `confidence` | `high` (cosine ≥ 0.45, ≈ real quotation) · `med` (0.30–0.45, candidate) |
| `vrs` | `mt` = ref normalized to Masoretic · `lxx?` = a merge/split boundary Psalm left in LXX numbering (needs the V1 verse-map) |
| `n_shared` | count of shared content Strong's |
| `score` | IDF-cosine of the two verses' content-Strong's bags (∈ [0,1]) |
| `shared_strongs` | the shared Greek Strong's (`G0740,…`) |

Up to 3 OT candidates per NT verse, ranked by score.

## Coverage & accuracy
6,594 links over 3,524 NT verses; **1,906** are `high`-confidence. On 12 well-known quotations the
top candidate is correct 8/12 (recall@3 = 8/12) and the high-conf tier concentrates in the expected
books (Psalms, Isaiah, Genesis, Jeremiah, Deuteronomy). The 4 misses are inherent to a bag-of-Strong's
method: short quotes with no rare-word signal (Heb 1:5 / Ps 2:7; the Shema, Mark 12:29 / Deut 6:4),
common-word quotes with a legitimate competitor (Rom 10:13 / Joel 3:5 vs Lam 3:55), and John 19:37,
which follows a **non-LXX** text of Zech 12:10 (correctly returns nothing). Prefer `confidence=high`
for downstream use.

## Versification
LXX Psalm chapters run one behind the Hebrew; `ot_ref` is normalized back to Masoretic/English via the
standard block map (`_psalm_lxx_to_mt`). The merge/split boundary Psalms (9, 113, 114, 115, 146, 147)
need verse-level remapping and are left in LXX numbering, flagged `vrs=lxx?`. Non-Psalm books pass
through unchanged.
