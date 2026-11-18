---
license: cc-by-4.0
language:
- hbo
- grc
pretty_name: Clause subjects, model-made (Hebrew Bible and Greek New Testament)
tags:
- bible
- hebrew
- greek
- model-made
---

# Clause subjects, model-made @TAG@

**Model output, no human check.** For clauses that the clause layers leave without a subject participant (mostly participles,
infinitives and verbless clauses), a language model (Jev, by typesafe.ai) chose who or what the subject is, from candidates that
code proposed. Nothing was generated: every participant is a lemma from the text around the clause.

Use only rows with `usable` = true (confidence ≥ 0.7, the bar fixed before the run). On a pilot of 200 clauses per side whose
participant was known and hidden, precision at that bar was **0.857** (Greek; 0.901 at ≥ 0.9) and **0.813** (Hebrew)
(make-tanakh-research's figures).

| | Hebrew Bible | Greek NT |
|---|---|---|
| clauses asked | @OT_ASKED@ | @NT_ASKED@ |
| a participant named | @OT_NAMED@ | @NT_NAMED@ |
| "none of these, or impersonal" | @OT_NONE@ | @NT_NONE@ |
| `usable` (named, confidence ≥ 0.7) | @OT_USABLE@ | @NT_USABLE@ |

## Rows

`data/hebrew.parquet`, `data/greek-nt.parquet`, one row per clause asked:

| Field | Meaning |
|---|---|
| `clause_key` | the clause's key in [bcv-commons/clause-columns](https://huggingface.co/datasets/bcv-commons/clause-columns): Hebrew, the [Hebrew clause layout](https://huggingface.co/datasets/bcv-commons/hebrew-clause-layout)'s `clause_key`; Greek, the first word of the [Greek NT layout](https://huggingface.co/datasets/bcv-commons/greek-nt-clause-layout)'s line |
| `ref` | book chapter:verse.segment of the clause |
| `participant` | the chosen participant's lemma (MACULA), empty for "none" |
| `participant_strong` | Hebrew: the Strong's number where the participant was named by number (@OT_BY_NUMBER@ rows; the lemma is MACULA's commonest lemma for that number) |
| `choice` | the candidate chosen (`1` …) or `none` |
| `p`, `confidence` | the model's probability for its choice, and its confidence |
| `candidates` | how many candidates it saw |
| `usable` | named and confidence ≥ 0.7 |

## How it was made

make-tanakh-research, 2026-11-03 (packet 34 to bcv-commons, manifest `@PACKET_SHA@…`): for each clause without a subject
participant, candidates were the participants of up to four previous clauses in the chapter, the parent clause's participant, and the
clause's own nouns and pronouns, plus "none / impersonal". The model saw the clause's Hebrew or Greek words, its parent clause, the
two previous clauses with their known participants, and the candidate lemmas. No glosses, no English text; the instructions to the
model were in English. 16.5 million model tokens, about USD 0.70.

The code (research's `clause_part_jev.py`) calls the model service and reads research's private clause files, so it is not
part of this repository; this card is its provenance. Packaged by bcv-commons (`shoresh/macula/release_clause_subjects_model.py`,
code @CODE@).

## Sources and licence

CC BY 4.0. The words, lemmas and clause structure come from MACULA Hebrew and MACULA Greek (Clear Bible / Biblica, CC BY 4.0) via
research's clause layers and bcv-commons' layouts; the choices are model output. No BHSA, no TBTA, no English as evidence.

## Versions

- v0.1: first release (research's run of 2026-11-03).
