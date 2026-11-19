---
license: cc-by-sa-4.0
language:
- hbo
- arc
- grc
pretty_name: Entity mentions
tags:
- bible
- hebrew
- greek
- named-entities
- coreference
---

# entity-mentions @TAG@

Who or what each word of the Tanakh and the Greek NT refers to: a person, place, group, deity, object (realia), plant or animal.
It covers names and nouns, pronouns and pronoun suffixes, and the implied subject a verb carries. Each row is a MACULA word
key and an entity. The dataset also has the entities themselves and their kinship.

**Two routes, kept side by side.** `acai`: ACAI's own word links. `chain`: MACULA's reference from the word (subject reference,
participant reference, referent), followed up to 4 steps to a word ACAI links. Where both routes reach a word and name the
same entity, it gets one row. Where they name different entities, it gets a row for each, both marked `differs`, and neither is
preferred.

**No English.** Entities have neutral codes (`e` + 10 hex digits: the same codes as bcv-commons/reference-status and
addressees). ACAI's ids are English names, so they are not carried, and neither are its labels, descriptions, subtypes or
roles. Lemmas are Hebrew, Aramaic and Greek.

## Tables (`data/`)

`mentions.parquet` (@ROWS@ rows):

| column | |
|---|---|
| `key` | MACULA word key (Tanakh 12 digits, Greek NT Nestle 1904 11 digits) |
| `lang` | `hbo` (Hebrew and Aramaic) or `grc` |
| `entity` | the entity code |
| `kind` | `explicit` (a name or noun), `pronominal` (a pronoun or suffix), `subject` (a verb's implied subject), `other` (a chain from another word class) |
| `route` | `acai`, `chain`, or `acai+chain` (both, same entity) |
| `agree` | `same`, `differs`, `acai_only`, `chain_only` |

`entities.parquet` (@ENTS@: @TYPES@): `entity`, `type`, `gender` (`m`, `f` or empty), `lemmas` (`he:` / `arc:` / `el:` + the
lemma, from ACAI), `characters` (the speaker layers' character ids joined to it), `apocrypha_only`, `non_biblical`, `mentions`
(rows here).

`kinship.parquet` (@KIN@ rows): `entity`, `relation` (father, mother, partner, offspring, sibling, tribe, group_origin,
birth_place, death_place, possibly_same_as: ACAI's relation codes), `other`.

## How the routes agree

| | Hebrew and Aramaic | Greek NT |
|---|---|---|
| words with an entity | @H_WORDS@ | @G_WORDS@ |
| both routes | @H_BOTH@ | @G_BOTH@ |
| same entity | @H_SAME@ (@H_SHARE@) | @G_SAME@ (@G_SHARE@) |
| different entities (two rows each) | @H_DIFF@ | @G_DIFF@ |
| ACAI only | @H_AONLY@ | @G_AONLY@ |
| chain only | @H_CONLY@ | @G_CONLY@ |

The chain can only reach entities that ACAI links somewhere nearby. Where it reaches none, the word has no chain row.
Pronouns that neither route resolves are not here. bcv-commons/reference-status lists them as `unresolved`.

## Sources and licence

ACAI Biblical Entity Data, © Mission Mutual / BiblioNexus, CC BY-SA 4.0, github.com/BibleAquifer/ACAI tag @ACAI_TAG@
(commit @ACAI_COMMIT@). Its Greek links (SBLGNT) are carried to Nestle 1904 ids by aligning the two MACULA Greek editions on
their lemmas. MACULA Hebrew and Greek (CC BY 4.0): word keys and the reference attributes. Nothing comes from BHSA or TBTA.
This dataset: CC BY-SA 4.0.

## Provenance

Code @CODE@: `shoresh/macula/build_entities.py` (ACAI to MACULA keys), `shoresh/macula/release_entity_mentions.py`.
