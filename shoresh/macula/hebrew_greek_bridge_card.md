---
license: cc-by-sa-4.0
language:
- hbo
- grc
pretty_name: Hebrew-Greek bridge (Septuagint lexemes and verb forms)
tags:
- bible
- hebrew
- greek
- septuagint
- lexicon
---

# Hebrew-Greek bridge @TAG@

Which Greek lexemes render a Hebrew lexeme in the Septuagint tradition, and which Greek tense, voice and mood a Hebrew verb form
corresponds to: one pinned dataset, both directions, from Hebrew and Greek sources only. With it a Hebrew word or verb can ask a
translation's New Testament for evidence (how the team rendered the Greek partner).

No English: no glosses, no definitions, no English as a pivot. Pairs found by matching English glosses are not here.
Pairs chosen by a language model are in a separate dataset,
[bcv-commons/hebrew-greek-lexeme-bridge-model](https://huggingface.co/datasets/bcv-commons/hebrew-greek-lexeme-bridge-model), for
lexemes this bridge leaves without a partner; read it beside this one if you want them.

## Files

| File | What |
|---|---|
| `data/lexemes.parquet` | one row per Hebrew-Greek lexeme pair and tier: `hebrew_strong`, `greek_strong` (`H0001`, `G3962`), `tier`, `count`, `score`, `score_reverse` |
| `data/verb_forms.parquet` | one row per Hebrew verb form and Greek verb form: `hebrew_form` (`wayyiqtol\|qal`), `greek_form` (`aorist\|active\|indicative`), `count`, `p_greek_given_hebrew`, `p_hebrew_given_greek` |
| `data/greek_numbers.parquet` | MACULA Hebrew `greekstrong` numbers the Greek NT never uses (Strong's numbers of inflected forms) and the NT number of their forms |
| `strong_bridge.json` | the lexeme rows as `{"h2g": {"1": [[3962, "macula", 1072, 0.723], ...]}, "g2h": {...}}`, numbers without padding, best first |
| `grammar_bridge.json` | the verb-form rows as `{"pairs": [...], "h2g": {"wayyiqtol\|qal": [["aorist\|active\|indicative", 0.67], ...]}, "g2h": {...}}` |

The two JSON files have the shape make-tanakh-grammar's drafting reads. Tier `glaux` is the tier its own file calls `lxx`.

## Lexemes

@MACULA_ROWS@ `macula` rows and @GLAUX_ROWS@ `glaux` rows; @HEBREW@ Hebrew and @GREEK@ Greek lexemes.

| Tier | Source | `count` | `score` (Hebrew → Greek) | `score_reverse` (Greek → Hebrew) |
|---|---|---|---|---|
| `macula` | MACULA Hebrew's per-word Septuagint alignment (`greekstrong`) | occurrences | share of the Hebrew lexeme's aligned occurrences | share of the Greek lexeme's aligned occurrences (over the pairs kept) |
| `glaux` | the Hebrew text against the Septuagint of GLAUx, verse by verse (verses mapped with STEPBible TVTMS); canonical books, content words | verses with both | Dice over the two verse sets | the same |

Pairs with a count of at least 3; `glaux` at Dice ≥ 0.3. The Hebrew number is MACULA's `strongnumberx` without its letter. The
Greek number follows MACULA's Greek NT: @NUMS@ numbers MACULA Hebrew gives to inflected forms (σου, εἶπεν …) are mapped to the NT
number of the word (`greek_numbers.parquet`), so a pair can meet the NT.

## Verb forms

@FORM_ROWS@ form pairs (@HFORMS@ Hebrew forms, @GFORMS@ Greek forms). A Hebrew verb and a Greek verb count as a pair when they stand in
the same verse and their lexemes are a pair in either tier. Hebrew form: MACULA's `type` and `stem` (`?` where one is empty);
Greek: GLAUx's tense, voice and mood, person and number left out. Daniel's Greek is Theodotion.

## Provenance

| Part | Source | Licence |
|---|---|---|
| `macula` tier, Hebrew forms | MACULA Hebrew (Clear Bible / Biblica), WLC | CC BY 4.0 |
| `glaux` tier, Greek forms | GLAUx (Alek Keersmaekers, KU Leuven) Septuagint | CC BY-SA 4.0 |
| verse maps | STEPBible TVTMS (Tyndale House), via bcv-commons/bibles | CC BY 4.0 |
| Greek number map | from MACULA Hebrew and MACULA Greek | CC BY 4.0 |

Built by bcv-commons (`shoresh/macula/build_lxx_bridge_tiers.py`, `build_grammar_bridge.py`, `release_hebrew_greek_bridge.py`;
code @CODE@). make-tanakh-grammar's research versions were the reference for the counting and thresholds (2026-10-30). No BHSA,
no TBTA, no model output.

## Licence

CC BY-SA 4.0, because of GLAUx. The `macula` rows alone (with `greek_numbers.parquet`) come from CC BY 4.0 sources only.

## Versions

- v0.1: first release (the lexeme tiers of 2026-11-17 with the Greek number map; the verb-form table of 2026-11-14).
