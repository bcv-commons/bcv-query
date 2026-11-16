---
license: cc-by-sa-4.0
language:
  - grc
  - hbo
pretty_name: Greek NT Concepts (model)
tags:
  - bible
  - greek
  - hebrew
  - new-testament
  - lexical-semantics
  - model-output
size_categories:
  - 10K<n<100K
---

# Greek NT Concepts (model)

A Hebrew concept for each content word of the Greek New Testament: which concept of
[hebrew-word-concepts-model](https://huggingface.co/datasets/bcv-commons/hebrew-word-concepts-model) a word expresses in its verse.
The Greek word and the Hebrew Bible then meet on one key, so that a word list or a translation built for the Hebrew Bible can be
read from the New Testament too.

**Every label here was chosen by a language model. No person has checked them.** @LABELLERS@ Use the confidence: see *Quality*.

| | |
|---|---|
| Version | @VERSION@ |
| Built | @BUILT@ by `macula/release_greek_nt_concepts_model.py` (bcv-query `@CODE@`) |
| Words | @WORDS@ Greek NT words (MACULA Greek, Nestle 1904) |
| Concepts | bcv-commons/hebrew-word-concepts-model v0.5 (`5a7af303`) |
| Licence | CC BY-SA 4.0 |

## How a word was labelled

Each word was put to the model in its Greek verse, with its lemma and morphology, and a numbered list of concepts to choose from (the
concept's definition and the UBS lexicon sense it belongs to). No translation, gloss or Hebrew text was shown. The list depends on
the word's set:

- `hebrew-nt`: a Hebrew New Testament (Salkinson-Ginsburg or Delitzsch, links of
  [hebrew-nt-bridge](https://huggingface.co/datasets/bcv-commons/hebrew-nt-bridge) v0.1) renders the word by a Hebrew lexeme that
  has concepts: the list is that lexeme's concepts (both editions' lexemes where they differ).
- `septuagint`: no such lexeme: the list is the ten concepts the Septuagint most often renders by this Greek lexeme, and one more
  choice, "none of the concepts above". Many of these words are function words or names; `none` = true marks that choice.

A word whose list holds one concept took it without a model (`labeller` = `one concept`).

## Files

| Path | What it holds |
|---|---|
| `data/words.parquet` | one row per Greek NT word labelled |
| `report.json` | counts by set and confidence, and the check on quoted words |
| `build.json` | inputs, models, counts |

Columns of `data/words.parquet`:

| Column | |
|---|---|
| `greek_id` | MACULA Greek word id (`n40001001001`) |
| `greek_strong`, `greek_lemma` | the word's Strong's number and lemma (MACULA Greek) |
| `set` | `hebrew-nt` or `septuagint` (above) |
| `concept` | the concept id of hebrew-word-concepts-model; empty where the model chose "none of the concepts" |
| `hebrew_strong` | the Hebrew lexeme the concept belongs to |
| `n_concepts` | how many concepts the model chose from |
| `confidence` | Jev's probability for its choice (0 to 1); empty for `one concept` |
| `none` | the model chose "none of the concepts" |
| `labeller` | `jev`, `opus` (Opus's choice, where Jev's confidence was below 0.8), or `one concept` |
| `jev_concept` | Jev's own choice (the same as `concept` unless `labeller` = `opus`) |
| `opus_sure` | for `opus` rows: Opus said its choice was clear (`false`: two concepts fit about equally well) |

## Quality

There is no hand-checked answer key for the New Testament. The check uses the words where the New Testament quotes the Hebrew Bible
and the Greek word stands for a Tanakh word with a concept of its own: there the Tanakh word's concept is taken as the answer. On
these @QUOTED@ words:

@QUALITY@

These words are easier than the average word (the quotation keeps the Hebrew close), so read the figures as upper figures. Jev's
confidence separates good from weak choices well; most of Jev's labels on the quoted words were Jev's own labels in the Tanakh, which
favours Jev here.

In make-tanakh-research's drafting tests (2026-11-16), using these labels to choose New Testament words by concept improved drafts of
New Testament-only engines in Indonesian, Swahili and Tagalog (chrF3 +0.8 to +1.0 with the labels at confidence 0.8 or above); with
the labels below 0.8 included the gain was smaller. Those figures are research's, not part of this release.

**Recommended use:** `confidence >= 0.8` (or `labeller` = `opus` with `opus_sure`) where precision matters; all labels where reach
matters more.

## Sources and licence

| Part | Source | Licence |
|---|---|---|
| Greek words, ids, lemmas, morphology | MACULA Greek (Clear Bible), Nestle 1904 | CC BY 4.0 |
| Concepts and their definitions | bcv-commons/hebrew-word-concepts-model v0.5 (concepts within the UBS senses) | CC BY-SA 4.0 |
| Hebrew lexemes of the Hebrew NTs | bcv-commons/hebrew-nt-bridge v0.1 | CC BY 4.0 |
| Septuagint candidates | bcv-commons resources (MACULA Hebrew's Septuagint links; GLAUx, KU Leuven) | CC BY 4.0 / CC BY-SA 4.0 |
| Labels | @MODELS@ | model output |

The whole is CC BY-SA 4.0.

## Versions

@VERSIONS@
