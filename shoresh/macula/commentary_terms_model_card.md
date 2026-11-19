---
license: cc-by-sa-4.0
language:
- hbo
pretty_name: Hebrew commentary terms (model)
tags:
- bible
- hebrew
- psalms
- rabbinic
- model-generated
---

# hebrew-commentary-terms-model @TAG@

Statements of the classical Hebrew commentators on the Psalms, **read by a language model** (`@MODEL@`, effort @EFFORT@,
through Claude Code's headless mode, 2026-11-18). **No human has checked them.** Same columns as
[hebrew-commentary-terms](https://huggingface.co/datasets/bcv-commons/hebrew-commentary-terms), plus `model` and `quote`.

## What was read

@UNITS@ openings: each of six commentators (Radak, Meiri, Ibn Ezra, Rashi, Metzudat David, Malbim) on each psalm, its
comments on the first two verses in Hebrew. The model listed what the commentator states about the psalm: `kind`, `voice`,
`occasion`, `turn` (where the psalm turns, on that verse). It had to copy the commentator's words: `term` (1-4 words) inside
`quote` inside the text, and a verse `citation` exactly as printed. Statements failing that check, or with a
longer term, were dropped (@DROPPED@ of @GIVEN@ given). No English was given to the model or is stored.

@STATEMENTS@ statements:

| witness | says | rows |
|---|---|---|
@BY_WITNESS@

Also here: @ANCHOR_ROWS@ Metzudat Zion word statements whose head word only the cached model fallback of
`macula/anchor_llm.py` found in its verse (`model` says so).

## Licence

CC BY-SA 4.0 as a whole, like hebrew-commentary-terms. The commentary texts are Public Domain or CC0 (Sefaria; `licence` per
row); word keys MACULA Hebrew (CC BY 4.0). Model output: Anthropic, `@MODEL@`.

## Provenance

Code @CODE@: `shoresh/macula/commentary_model.py` (prepare, cli, collect), `release_commentary_terms.py --model`. Run sha256
@RUN_SHA@…; the run reported USD @USD@ at API prices (it ran on a subscription).
