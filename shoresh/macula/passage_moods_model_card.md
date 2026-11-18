---
license: cc-by-sa-4.0
language:
- hbo
- grc
pretty_name: Passage moods (model)
tags:
- bible
- hebrew
- greek
- emotion
- model-generated
---

# passage-moods-model @TAG@

Which feelings the Hebrew or Greek text of a passage marks, and by which words, **as read by a language model**
(`@MODEL@`, effort @EFFORT@, through Claude Code's headless mode, 2026-11-18). **No human has checked these readings.** They
are kept apart from [passage-facts](https://huggingface.co/datasets/bcv-commons/passage-facts), whose `mood` facts come from
rules only.

The moods are the 9 families of passage-facts (from v0.3.1), each named by a Hebrew and a Greek head word and defined in
`mood_families.tsv` (SDBH and Louw-Nida domains, lemmas): @FAMILIES@ (units naming each family).

## What was asked

@UNITS@ passages, of two kinds (`asked_because`):

- `source`: a passage where a source names a feeling but no Hebrew or Greek word in it marks that feeling's family by our
  rules: a psalm section of Scriptura's At-a-Glance (`source` scriptura) or a speech with a Glyssen delivery note (`source`
  glyssen). The source's own mood word was **not** shown to the model and is not stored here.
- `hard`: a paragraph where our rules find painful and pleasant feeling words in near balance.

The model saw only the passage's Hebrew (pointed, without accents) or Greek words, each numbered, and for a speech the verse
before it as context; and the families by id, head words and their commonest Hebrew and Greek lemmas. No English glosses, no
definitions, no translation. It named at most three families, strongest first, with the numbers of the words that carry each,
or none. Word numbers were turned into MACULA word keys; all fell inside their passage.

## Data

`data/moods.parquet`, one row per passage:

| column | |
|---|---|
| `unit_id` | the passage's id in the run |
| `book`, `first`, `last`, `ref` | the span, as MACULA word keys (first and last) and a reference |
| `lang` | hbo or grc |
| `asked_because` | source or hard |
| `source` | scriptura or glyssen for a source passage, else null |
| `moods` | list of {`family` (md.*), `head` (the head word in the passage's language), `marked_by` (MACULA word keys)}, strongest first |
| `none` | true where the model found no feeling marked in the text |

@WITH_MOOD@ passages have at least one mood; @NONE@ have none.

## How it compares with the sources

The source passages carry the family a source's own word maps to (by the `source_words` column of `mood_families.tsv`). It
was not shown to the model; it is a yardstick only, and not a correct answer: the sources read the passage as a whole or as
a performance, the model reads the words.

| passages | n | the source's family among the model's | as the model's first | model: none |
|---|---|---|---|---|
| Scriptura psalm sections | @SCRIPTURA_N@ | @SCRIPTURA_HIT@ | @SCRIPTURA_FIRST@ | @SCRIPTURA_NONE@ |
| Glyssen speeches | @GLYSSEN_N@ | @GLYSSEN_HIT@ | @GLYSSEN_FIRST@ | @GLYSSEN_NONE@ |
| hard paragraphs (the rules' own families) | @RULES_N@ | @RULES_HIT@ | @RULES_FIRST@ | @RULES_NONE@ |

Glyssen's deliveries are directions for a voice (angry, weeping, joyful); many have no feeling word in the text, and the
model then says none. The hard paragraphs' figure only shows the model kept to the marked words; it is no test.

## Licence and sources

CC BY-SA 4.0, because the families are defined by the UBS dictionaries (SDBH, Louw-Nida; CC BY-SA 4.0). Word keys and text:
MACULA Hebrew and Greek (CC BY 4.0). The source passages were chosen from Psalms: Layer by Layer (Scriptura,
https://psalms.scriptura.org, CC BY 4.0, Overview pages as of 2026-11-18) and Glyssen's delivery notes (Glyssen, Copyright (c) 2014-2020 SIL LSDev and
Faith Comes By Hearing, MIT, https://github.com/sillsdev/Glyssen); only their spans are used. Model output: Anthropic, `@MODEL@`.

## Provenance

Code @CODE@: `shoresh/macula/mood_model.py` (prepare, cli, collect-cli), `release_passage_moods_model.py`. Run results
sha256 @RESULTS_SHA@…; @OUT_TOKENS@ output tokens; the run reported USD @COST@ at API prices (it ran on a subscription).
