# lxx_bridge_tiers — the Hebrew ↔ Greek lexeme bridge, every pair with its tier

`../lxx_bridge.tsv` keeps the top 4 Greek lexemes per Hebrew lexeme. That suits Hebrew → Greek expansion, but it cuts the tail of
Greek → Hebrew. These files keep every pair with count ≥ 3, and the tier each comes from. They are one file per licence:

| file | tier | count | score | pairs | licence |
|---|---|---|---|---|---|
| `macula.tsv` | `macula`: MACULA Hebrew's per-occurrence `greekstrong` column | occurrences | P(greek \| hebrew) | 4,496 (Hebrew 1,863, Greek 1,669) | CC BY 4.0 |
| `glaux.tsv` | `glaux`: verse co-occurrence of the Hebrew text and the Septuagint | verses with both | Dice over the two verse sets, ≥ 0.3 | 1,941 (Hebrew 1,588, Greek 1,372) | CC BY-SA 4.0 |

Both files have the columns `hebrew_strong, greek_strong, tier, count, score`. The codes are zero-padded (`H2617`, `G1656`). Rows
are sorted by Hebrew lexeme, then by count, highest first.

- **`lxx_bridge.tsv` is the top 4 of `macula.tsv`** per Hebrew lexeme, row for row; the builder's check reproduces it exactly. The
  Hebrew key is MACULA's `strongnumberx` with its homonym letter dropped, not the lexeme spine's `strong`. The spine merges some
  numbers (H0582 into H0376, H2009 into H2005, H3069 into H3068), and a reader looks the bridge up by the number they have.
- **`glaux`** pairs Hebrew and Greek content words that stand in the same verses. Both texts are converted to the English verse
  scheme with `shoresh/vrsmap.py` (bibles' TVTMS maps): the Hebrew text from MACULA numbering, and the Septuagint (`lxx-glaux.db`,
  canonical books only) from Septuagint numbering; Daniel from Theodotion (GLAUx 0527-057, `lxx-glaux-dan-theodotion.db`, moved to
  Hebrew numbering by `shoresh/macula/lxx_verses.py`), which follows the Hebrew and Aramaic closely where the Old Greek of chapters
  3-6 is free: Aramaic lexemes with a pair go from 45 to 86. 22,724 verses match. 1,108 of its pairs are also in `macula`.
  569 pairs cover 473 Hebrew lexemes that `macula` has no pair for. Make-tanakh-grammar found that below Dice 0.3 the pairs are collocates rather
  than equivalents.

## Greek numbers: one per word, as the Greek NT has them (2026-11-16)

MACULA Hebrew's `greekstrong` gives some Greek words the number of an inflected form, following Strong's own per-form entries:
σου 4675, εἶπεν 2036, ἔσται 2071, τοῦτο 5124 and others. MACULA's Greek NT has one number per word. 78 such numbers, on 29,494
of the 323,362 Hebrew-to-Greek links (9.1%), never occur in the Greek NT, so a pair on them never met an NT word: אמר reached
εἶπεν 2036 but not λέγω 3004.

`greek_numbers.tsv` lists all 78 with the NT number of their forms, where MACULA's Greek NT shows one:

| column | meaning |
|---|---|
| `source_strong` | the number in MACULA Hebrew's `greekstrong` |
| `nt_strong`, `nt_lemma` | the Greek NT's number and lemma for its forms; empty when there is no clear evidence |
| `links` | Hebrew words aligned to this number |
| `found`, `share` | how many of those have a Greek form that occurs in the Greek NT, and the share of them under `nt_strong` |
| `example` | the commonest Greek form |

- **Rule:** each occurrence's Greek form is looked up among the Greek NT's forms: as written; then with a grave accent read as
  acute; then without acute and grave, keeping circumflex and breathings (ἰδέ and ἴδε are one form, ἦ and ἤ are not); forms
  written with no accent at all (the names) also without accents. A number is mapped when at least 3 occurrences are found and
  0.9 of them agree. 58 numbers are mapped (29,199 links); 20 stay as they are (295 links: compounds such as μήποτε 3379 that
  the NT splits, and words the NT lacks).
- **Compound links count each number (2026-11-17).** Eight words carry two numbers: בִּי as ἐν|ἐμοί (`1722|1698`, 6) and
  Zechariah 2:13 (Hebrew numbering; English 2:9) as ἐπ’|αὐτούς (`1909|848`, 2). Before, only the first number was read; now both are, and a
  pair's score still divides by the Hebrew word's occurrences. One pair is new: H0994 G1473 (ἐγώ), 6.
- **`macula.tsv` and `../lxx_bridge.tsv` count by the mapped number**, so the forms of one word merge: 4,643 pairs became 4,496.
  `glaux.tsv` is built from GLAUx lemmas and did not change.
- **Not changed:** numbers the Greek NT does use, also where the alignment's Greek form belongs to another NT word. This was not
  counted, because some `greek` forms in MACULA Hebrew are garbled (ξ for χ: ἀρξῆς for ἀρχῆς under 746).
- **Check:** make-tanakh-research's own list (50 pairs, from GLAUx lemmas and Strong's form lists) agrees on all 48 numbers the
  two share. This rule maps 10 more (160 links), among them μικρόν 3397 to μικρός and μείζων 3187 to μέγας.

Built by `shoresh/macula/build_lxx_bridge_tiers.py` from the MACULA Hebrew WLC TSV (sha256 `965cb0599beed2fe…`) and `lxx-glaux.db`
(sha256 `42f00ecfc31e502d…`). Make-tanakh-grammar's `lab/bridge/strong_bridge.py` was the reference (2026-10-30); the thresholds
are theirs.

## Source / licence
- `macula.tsv`: MACULA Hebrew, © Clear Bible / Biblica, **CC BY 4.0**, https://github.com/Clear-Bible/macula-hebrew. Only the two
  Strong's columns and, for the Greek numbers, the `greek` form are read; MACULA does not say which Hebrew–LXX alignment its `greekstrong` comes from (see
  `../prior_pack/README.md`).
- `glaux.tsv`: also GLAUx (Alek Keersmaekers, KU Leuven, https://github.com/alekkeersmaekers/glaux), **CC BY-SA 4.0**, share-alike
  (see `../LICENSES.md`). The verse maps are TVTMS (Tyndale House, CC BY 4.0).

The pair files hold only Strong's numbers, counts and scores, with no text. `greek_numbers.tsv` also holds one Greek lemma and one
Greek form per number (MACULA, CC BY 4.0).
