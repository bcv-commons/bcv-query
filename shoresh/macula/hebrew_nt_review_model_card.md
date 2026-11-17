---
license: cc-by-4.0
language:
  - he
  - grc
pretty_name: Hebrew NT Review (model-made)
tags:
  - bible
  - hebrew
  - greek
  - new-testament
  - word-alignment
  - model-made
configs:
  - config_name: records
    default: true
    data_files:
      - split: heb_scg
        path: records/heb_scg.jsonl
      - split: heb_mod
        path: records/heb_mod.jsonl
---

# Hebrew NT Review (model-made)

A model's review of the word links between the Greek New Testament and two Hebrew translations of it: Salkinson–Ginsburg
(`heb_scg`) and Delitzsch (`heb_mod`). There is one record for each Greek noun, verb and adjective of the New Testament (MACULA Greek,
Nestle 1904). A record says which Hebrew word renders the Greek word, how it renders it, and who decided.

**Model-made, no human check.** The decisions are by the Jev model (TypeSafe, `jev-1.14.0`) and by Claude (Anthropic,
`claude-opus-5-5`). No person has checked them. The review was made by make-tanakh-research on 2026-10-31 and handed over to
bcv-query on 2026-11-17. Its code is in bcv-query `shoresh/macula/hnt_review/`.

| | |
|---|---|
| Release | **@TAG@**, built @BUILT@ from bcv-query `@COMMIT@` |
| Links reviewed | [hebrew-nt-bridge](https://huggingface.co/datasets/bcv-commons/hebrew-nt-bridge) v0.2 (`heb_scg`: alignments-by-id v1.0 = v1.1; `heb_mod`: the by-id links handed over with this review) |

## Records

`records/<edition>.jsonl` has one JSON object per Greek word:

| Field | |
|---|---|
| `gid` | the Greek word's MACULA id (`n46002013012`) |
| `ref` | the verse (`1CO 2:13`) |
| `group` | the review pool the word was drawn from |
| `before` | the link at review time: `link` = [[Hebrew word, part], ...] and its class. **This is the staleness key.** When the published link of this Greek word changes, the record no longer applies to it |
| `after` | the decision: `link` + `status` (kept), or `words` (the Hebrew words that render it) + `verdict` (`right`, `partial`, `wrong`) |
| `how` | `lexical` (a word that means it), `phrase` (a Hebrew phrase renders it), `free` (a free rendering), `uncertain`, or null (no Hebrew word renders it) |
| `decided_by` | `published` (the link agrees with a Hebrew–Greek lexeme pair the review's bridge already had; kept without a model's decision), `jev-check-v1` (Jev, above its calibrated threshold), `claude-review-v1` (Claude, for what Jev did not decide) |
| `evidence` | what the decision rests on: `bridge`, Jev's `choice` and probability `p`, the lexical `mark` |
| `evidence.bridge_pair_from_glosses` | true where the only bridge pair that supports a `published` record was found by matching English glosses (see *Known limits*) |
| `note`, `rules`, `model`, `date` | for Claude's decisions: the working note (Greek = Hebrew), the rules version and the model |

Notes are the reviewer's working notes. English words quoted in them, and English glosses in brackets, are removed (shown as `…`).

| | `heb_scg` | `heb_mod` |
|---|---|---|
| Records | @SCG_N@ | @MOD_N@ |
| `published` | @SCG_PUB@ | @MOD_PUB@ |
| `jev-check-v1` | @SCG_JEV@ | @MOD_JEV@ |
| `claude-review-v1` | @SCG_CLAUDE@ | @MOD_CLAUDE@ |
| `lexical` / `phrase` / `free` | @SCG_LEX@ / @SCG_PHRASE@ / @SCG_FREE@ | @MOD_LEX@ / @MOD_PHRASE@ / @MOD_FREE@ |
| `uncertain` / not rendered | @SCG_UNC@ / @SCG_NONE@ | @MOD_UNC@ / @MOD_NONE@ |
| `published` on a gloss-found pair only | @SCG_GLOSS@ | @MOD_GLOSS@ |

## Calibration

`calibration/<edition>.json` has Jev's thresholds per kind of decision (keep, move, add) and how they were set. They were set on
240 reference words judged blind by Claude, with a target of 0.95. Jev's "not rendered" answers always went to Claude.

## The function-word check

The review covers content words only. The links of function words (articles, prepositions, conjunctions, pronouns, particles)
were checked separately in bcv-query on 2026-11-17. For each class and translation, 40 Greek words were drawn, one per verse. A model
(Claude Opus 5.5, not a person) judged each from the two verses without seeing the link. `checks/function-words/<edition>/` has the
items with the links, the judgments and the scores. Right = the same Hebrew parts; partial = an overlap.

| Class | `heb_scg` right / + partial | `heb_mod` right / + partial |
|---|---|---|
| article | 48% / 50% | 40% / 48% |
| preposition | 60% / 80% | 57% / 88% |
| conjunction | 62% / 75% | 60% / 82% |
| pronoun | 78% / 88% | 75% / 85% |
| particle | 62% / 80% | 57% / 78% |

## Known limits

- **Model-made.** Two models decided; no person checked.
- **Gloss-found pairs.** The bridge that let a link be kept without a model's decision (`published`) includes 212 Hebrew–Greek pairs
  whose candidates were found by matching English glosses; Jev then chose among them on the Hebrew and Greek verses. The records
  that rest on such a pair alone are flagged `bridge_pair_from_glosses`. Leave them out for work that must rest on the original
  languages only.
- Both translations follow the Textus Receptus; the Greek ids are Nestle 1904.

## Sources and licence

| Part | Source | Licence |
|---|---|---|
| Greek words | MACULA Greek, Nestle 1904 (Clear Bible / Biblica) | CC BY 4.0 |
| Links reviewed | lexeme-aligner's method (alignments-by-id; Delitzsch run by make-tanakh-research) | CC0 1.0 |
| Hebrew words and parts | bcv-commons/hebrew-nt-analysis v0.2 | CC BY 4.0 |
| Decisions | Jev (TypeSafe) and Claude (Anthropic), run by make-tanakh-research | model output |
| This dataset | bcv-commons | **CC BY 4.0** |

The files hold no verse text. They hold ids, positions, references, decisions and short working notes that quote Greek and Hebrew
words.

## Versions

- v0.1: the review of 2026-10-31 for both translations, and the function-word check of 2026-11-17.
