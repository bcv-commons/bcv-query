---
license: cc-by-sa-4.0
language:
- hbo
- arc
- grc
pretty_name: Entity mentions (model)
tags:
- bible
- hebrew
- greek
- coreference
- model-generated
---

# entity-mentions-model @TAG@

**Made by a language model (@MODEL@, effort @EFFORT@). No person has checked it.**

For pronouns that bcv-commons/entity-mentions @EM_TAG@ leaves without an entity (neither ACAI nor MACULA's reference chain
reaches them; bcv-commons/reference-status @RS_TAG@ lists them as `unresolved`), the entity the model reads them as referring
to, or why it gives none. Use it beside entity-mentions, not in place of it.

**Scope.** Personal, demonstrative, reflexive, reciprocal and relative pronouns and pronoun suffixes. Interrogatives
(מָה, מִי, τίς), indefinites (τὶς) and words of quantity or quality (ὅσος, τοιοῦτος) are left out: they refer to no entity
(Hebrew @OUT_H@, Greek @OUT_G@ words).

**No English.** Entities are entity-mentions' neutral codes; reasons are codes.

## How it was made

@UNITS@ calls, one per chapter (up to 25 words each). The model got, in Hebrew or Greek only: each word's verse and the
three verses before it, the words marked, every word entity-mentions links to an entity tagged with a candidate number, and
the candidates (the entities entity-mentions has in this chapter and the one before: type, gender, lemmas). It picked one
candidate per word or `none` with a reason. An answer naming no listed candidate is dropped. Run cost USD @USD@ (reported by
Claude Code; the user's subscription).

## Table (`data/answers.parquet`, @ROWS@ rows)

| column | |
|---|---|
| `key` | MACULA word key (Tanakh 12 digits, Greek NT Nestle 1904 11 digits) |
| `lang` | `hbo` or `grc` |
| `entity` | the entity code (entity-mentions), or empty |
| `none_reason` | where `entity` is empty: `proposition` (it points at a statement, event or matter), `not_listed` (an entity that is not among the candidates, often one entity-mentions does not have, such as "someone" or a group the text gathers), `unclear` |
| `candidates` | how many candidates the model had |

| | Hebrew and Aramaic | Greek NT |
|---|---|---|
| words | @H_N@ | @G_N@ |
| an entity | @H_ENT@ | @G_ENT@ |
| none: proposition | @H_PROPOSITION@ | @G_PROPOSITION@ |
| none: not listed | @H_NOT_LISTED@ | @G_NOT_LISTED@ |
| none: unclear | @H_UNCLEAR@ | @G_UNCLEAR@ |

## How far it agrees with blind judges

A sealed sample (seed 1119, 60 words per language, drawn before scoring; rules registered before judging) was judged
blind by Claude subagents, two per word, each from the word's verse and the three before it with the same candidates. Judges
are the same model family, so this measures agreement, not truth. Scored on the choice (candidate or none), once.

| | Hebrew | Greek | together |
|---|---|---|---|
| words | @H_SN@ | @G_SN@ | @A_SN@ |
| model = judge A | @H_AGREE_A@ | @G_AGREE_A@ | @A_AGREE_A@ |
| model = judge B | @H_AGREE_B@ | @G_AGREE_B@ | @A_AGREE_B@ |
| judges agree | @H_JUDGES_AGREE@ | @G_JUDGES_AGREE@ | @A_JUDGES_AGREE@ |
| model = judges, where they agree (n) | @H_AGREE_WHERE_JUDGES_AGREE@ (@H_JN@) | @G_AGREE_WHERE_JUDGES_AGREE@ (@G_JN@) | @A_AGREE_WHERE_JUDGES_AGREE@ (@A_JN@) |

Most answers on every side are `none`, which makes these figures easy to reach. Where the model or a judge chose an entity
(@E_N@ words; a count not registered beforehand), all three named the same entity for @E_SAME@; the others were Hebrew
words, most of them in the Psalms and Isaiah.

## Sources and licence

bcv-commons/entity-mentions @EM_TAG@ (CC BY-SA 4.0; ACAI, © Mission Mutual / BiblioNexus, CC BY-SA 4.0) for the entities and
candidates; bcv-commons/reference-status @RS_TAG@ (@RS_COMMIT@) for which words are unresolved; MACULA Hebrew and Greek (CC BY
4.0) for the text and keys. Nothing comes from BHSA or TBTA. This dataset: CC BY-SA 4.0.

## Provenance

Code @CODE@: `shoresh/macula/pronoun_model.py` (prepare, run, collect, sealed sample),
`shoresh/macula/release_entity_mentions_model.py`. Raw answers sha256 @RAW@ (in build.json in full).
