# grammar_bridge — Hebrew verb form ↔ Greek verb form over the Septuagint

`grammar_bridge.tsv` counts how the Septuagint renders each Hebrew verb form, in both directions. It sits beside the lexeme bridge
(`../lxx_bridge_tiers/`). A Hebrew verb and a Greek verb count as a pair when they stand in the same verse and their Strong's numbers
are a pair in `lxx_bridge_tiers` (any row of `macula.tsv` or `glaux.tsv`). Each verb pair counts once: there is no weighting and no
threshold, so a consumer cuts at a count.

| column | meaning |
|---|---|
| `hebrew_form` | MACULA Hebrew's `type` and `stem` of a word with class verb, `type\|stem` (`wayyiqtol\|qal`); `?` where MACULA leaves one empty |
| `greek_form` | GLAUx's tense, voice and mood, `tense\|voice\|mood` (`aorist\|active\|indicative`); person and number are left out |
| `count` | verb pairs with these two forms |
| `p_greek_given_hebrew` | count / all pairs with this `hebrew_form` |
| `p_hebrew_given_greek` | count / all pairs with this `greek_form` |

The table has 1,557 form pairs (140 Hebrew forms, 50 Greek forms). They come from 67,160 verb pairs in 20,667 verses that have verbs
on both sides. For example, `wayyiqtol|qal` → `aorist|active|indicative` has a count of 8,667, which is 0.67 of all `wayyiqtol|qal`
pairs. A few verbs that MACULA types `adjective`, `common`, `proper` or `relative` (participles used as nouns or adjectives) form
their own `hebrew_form` with small counts.

Verses of both texts are converted to the English scheme with `shoresh/vrsmap.py`, as for `glaux.tsv`. The Hebrew key is MACULA's
`strongnumberx`, as in the tier files. Built by `shoresh/macula/build_grammar_bridge.py`. Make-tanakh-grammar's
`lab/bridge/grammar_bridge.py` is the reference (2026-10-30). With their simple verse map and the lexeme spine's `strong`
(`--spine-strong`), the builder reproduces their 1,553 rows exactly. Two things set this table apart from theirs:
- vrsmap's multi-verse rows add 47 verses;
- the MACULA numbers keep the verbs that the spine merges, such as שָׂמַח (H8055), bridged.

## Source / licence
**CC BY-SA 4.0**, from GLAUx (Alek Keersmaekers, KU Leuven, https://github.com/alekkeersmaekers/glaux; share-alike, see
`../LICENSES.md`) and MACULA Hebrew (Clear Bible / Biblica, CC BY 4.0). The verse maps are TVTMS (Tyndale House, CC BY 4.0). The
table holds only form labels, counts and shares, with no text.
