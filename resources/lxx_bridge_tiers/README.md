# lxx_bridge_tiers — the Hebrew ↔ Greek lexeme bridge, every pair with its tier

`../lxx_bridge.tsv` keeps the top 4 Greek lexemes per Hebrew lexeme. That suits Hebrew → Greek expansion, but it cuts the tail of
Greek → Hebrew. These files keep every pair with count ≥ 3, and the tier each comes from. They are one file per licence:

| file | tier | count | score | pairs | licence |
|---|---|---|---|---|---|
| `macula.tsv` | `macula`: MACULA Hebrew's per-occurrence `greekstrong` column | occurrences | P(greek \| hebrew) | 4,643 (Hebrew 1,862, Greek 1,724) | CC BY 4.0 |
| `glaux.tsv` | `glaux`: verse co-occurrence of the Hebrew text and the Septuagint | verses with both | Dice over the two verse sets, ≥ 0.3 | 1,881 (Hebrew 1,546, Greek 1,354) | CC BY-SA 4.0 |

Both files have the columns `hebrew_strong, greek_strong, tier, count, score`. The codes are zero-padded (`H2617`, `G1656`). Rows
are sorted by Hebrew lexeme, then by count, highest first.

- **`lxx_bridge.tsv` is the top 4 of `macula.tsv`** per Hebrew lexeme, row for row; the builder's check reproduces it exactly. The
  Hebrew key is MACULA's `strongnumberx` with its homonym letter dropped, not the lexeme spine's `strong`. The spine merges some
  numbers (H0582 into H0376, H2009 into H2005, H3069 into H3068), and a reader looks the bridge up by the number they have.
- **`glaux`** pairs Hebrew and Greek content words that stand in the same verses. Both texts are converted to the English verse
  scheme with `shoresh/vrsmap.py` (bibles' TVTMS maps): the Hebrew text from MACULA numbering, and the Septuagint (`lxx-glaux.db`,
  canonical books only) from Septuagint numbering. 22,704 verses match. 1,097 of its pairs are also in `macula`. 529 pairs cover
  447 Hebrew lexemes that `macula` has no pair for. Make-tanakh-grammar found that below Dice 0.3 the pairs are collocates rather
  than equivalents.

Built by `shoresh/macula/build_lxx_bridge_tiers.py` from the MACULA Hebrew WLC TSV (sha256 `965cb0599beed2fe…`) and `lxx-glaux.db`
(sha256 `42f00ecfc31e502d…`). Make-tanakh-grammar's `lab/bridge/strong_bridge.py` was the reference (2026-10-30); the thresholds
are theirs.

## Source / licence
- `macula.tsv`: MACULA Hebrew, © Clear Bible / Biblica, **CC BY 4.0**, https://github.com/Clear-Bible/macula-hebrew. Only the two
  Strong's columns are read; MACULA does not say which Hebrew–LXX alignment its `greekstrong` comes from (see
  `../prior_pack/README.md`).
- `glaux.tsv`: also GLAUx (Alek Keersmaekers, KU Leuven, https://github.com/alekkeersmaekers/glaux), **CC BY-SA 4.0**, share-alike
  (see `../LICENSES.md`). The verse maps are TVTMS (Tyndale House, CC BY 4.0).

The files hold only Strong's numbers, counts and scores, with no text.
