---
license: cc-by-sa-4.0
language:
- hbo
- grc
pretty_name: Source ontology
tags:
- bible
- hebrew
- greek
- septuagint
- ontology
- knowledge-graph
---

# source-ontology @TAG@

One id space for the meaning side of the Tanakh, the Septuagint and the Greek NT: lexemes, UBS senses and domains, concepts, the
words (mentions) that evoke them, the persons, places and things the words refer to, how lexemes are rendered across the
languages, which words are aligned to which, and one proposition per clause with its predicate, arguments and links. The
tables join bcv-commons datasets on shared keys (MACULA word ids, Strong's numbers, UBS codes); nothing here is new judgment
except what those datasets already hold.

**No English.** Lemmas are Hebrew and Greek (MACULA's homonym markers "(I)", "(II)" kept); senses and domains are UBS codes
(their English glosses and definitions are never read); feature values are the source datasets' codes; connectives are written
in Hebrew or Greek.

## Ids

| id | for |
|---|---|
| `lex:H0001`, `lex:G3962` | a lexeme by Strong's number (Aramaic under H) |
| `con:H1.1` | a concept (hebrew-word-concepts-model / greek-nt-concepts-model); `con:H0.*` belong to words without a Strong's number |
| `sense:<UBS sense id>` | a UBS dictionary sense |
| `dom:sdbh:<code>`, `dom:ln:<code>` | a UBS domain: SDBH lexical domain (Hebrew), Louw-Nida domain or subdomain (Greek) |
| `w:010010010011` | a Tanakh word (MACULA Hebrew id) |
| `w:40001001001` | a Greek NT word (MACULA Greek id, Nestle 1904, without its leading `n`) |
| `w:glx:104873137` | a Septuagint word (GLAUx id) |
| `w:heb_scg:MAT.1.1.3.0` | a word part in a Hebrew NT (edition, book, chapter, verse, word, part) |
| `ent:e0123456789` | an entity (person, place, group, deity, realia, flora, fauna), the codes of bcv-commons/entity-mentions |
| `prop:<clause key>` | a clause as a proposition; the key is the clause's first MACULA word, as in every bcv-commons clause dataset |

## Tables (`data/`)

| file | rows | |
|---|---|---|
| `classes.parquet` | lexeme @LEX@, sense @SENSE@, domain @DOM@, concept @CON@ | `id`, `class`, `lang`, `lemma` |
| `relations.parquet` | see below | `subject`, `relation`, `object`, `kind` (asserted / derived), `method` (source / computed / model), `source` (dataset@version), `confidence`, `count`, `share`, `tier` |
| `mentions.parquet` | Tanakh @M_TAN@, Greek NT @M_NT@, Septuagint @M_LXX@ | `mention`, `text`, `lexeme`, `concept` with `concept_labeller` and `concept_confidence`, `sense` |
| `aligned.parquet` | Septuagint @A_LXX@, Salkinson @A_SCG@, Delitzsch @A_MOD@ | `mention`, `other`, `edition`, `basis` (the source's own label), `method` |
| `propositions.parquet` | Hebrew @P_HBO@, Greek NT @P_GRC@ | `prop`, `lang`, `ref` and the clause's features (below) |
| `prop_relations.parquet` | see below | `subject`, `relation`, `object`, `tier`, `gram`, `word`, `source`, `target_basis` |
| `prop_accuracy.parquet` | one per checked feature | `lang`, `feature`, `figure`, `n`, `sample`, `basis` |
| `entities.parquet` | @ENT@ | `id` (`ent:e…`), `class` entity, `type`, `gender`, `lemmas` |
| `entity_relations.parquet` | refers_to @REFERS@, kinship @KIN@ | `subject`, `relation`, `object`, `kind`, `route`, `agree` |

Relations:

| relation | method | rows |
|---|---|---|
@REL_TABLE@

`concept_of` links a concept to its lexeme, `sense_of` a sense to its lexeme, `from_sense` a concept to the UBS sense it was made
from, `in_domain` a sense to its domain, `broader` a domain to its parent, `rendered_by` a lexeme (or concept) to a lexeme of the
other language with the tier, count and share of the bridge it comes from.

**Model rows.** Rows with `method` model come from bcv-commons datasets made by a language model (the `-model` datasets named in
`source`: concepts, concept labels per word, model-chosen lexeme pairs). They were not checked by a person; see each dataset's
card for the model and its figures. Filter on `method` to leave them out.

## Entities

From bcv-commons/entity-mentions @EM_TAG@ (code @EM_CODE@; ACAI with MACULA's reference chain). `refers_to` links a mention
to its entity, with the mention's `kind` (explicit, pronominal, subject, other), the `route` that found it (acai, chain,
acai+chain) and whether the routes `agree` (same, differs, acai_only, chain_only). Where the routes disagree, both rows are
here. `kin:<relation>` links an entity to another (ACAI's kinship codes: father, mother, partner, offspring, sibling, tribe,
group_origin, birth_place, death_place, possibly_same_as).

## Propositions

One row per clause of the Hebrew and Greek NT clause layouts. Features (codes, from the dataset in build-propositions.json):
`voice`, `neg`, `neg_scope`, `force`, `kind`, `interrog`, `speech` (speech level), `speaker_id`, `line` (narrative line),
`genre`, `front`, `focus`, `subj_switch`, `part_switch`, `causative` (clause-columns v1.2); `time`, `aspect`, `time_basis`
(time-aspect v0.2).

| relation | source | rows |
|---|---|---|
@PR_TABLE@

`has_predicate` points at the main verb's mention; `has_argument` at an argument's head word, with its role (actor, undergoer,
location, recipient …) in `tier` and its grammatical relation in `gram` (argument-roles v0.2); `linked_to` at the clause it
attaches to in the clause layout (`target_basis` layout), else at the clause before it in the same book (`target_basis`
previous), with the link type in `tier`, the relation in `gram` and the connective as written in `word` (clause-connectives
v0.1).

### How far the features can be trusted

`prop_accuracy.parquet` holds the figures of an audit of the clause columns (S2): blind samples of 100 clauses per language,
judged from the Hebrew or Greek text alone, exact agreement with the dataset. `sample` names the sample (seed and the
clause-columns version it checked; the Hebrew columns are unchanged in v1.2). `basis`: `same_word` (the judge's main verb is the
same word), `verb_morphology` (follows the main verb's MACULA morphology), `present` (a negator is there or not), `same_scope`
(predicate or constituent negation), `both_named` (subject switch, where judge and dataset both name a subject).

| lang | feature | figure | n | sample | basis |
|---|---|---|---|---|---|
@ACC_TABLE@

Features not listed have not been checked this way. In particular the argument roles of `has_argument` and the `linked_to`
targets carry no figure yet.

## Not here

- RDF: the tables are the source of truth; an RDF export is planned later.
- Rabbinic commentary terms: in bcv-commons/hebrew-commentary-terms; not joined in this version.
- Occurrence groups for lemmas UBS leaves without a sense (V3c): computed but not published; the groups have no labels, a
  two-way split can follow form rather than sense, and the commentary yardstick for them is thin.

## Sources and licence

Inputs (bcv-commons datasets, revision in brackets):

@INPUTS@

Underneath: MACULA Hebrew and Greek (CC BY 4.0), the UBS dictionaries (CC BY-SA 4.0), GLAUx (CC BY-SA 4.0), ACAI (CC BY-SA 4.0), the Hebrew NTs
of Salkinson-Ginsburg and Delitzsch (public domain). Nothing comes from BHSA or TBTA. This dataset: CC BY-SA 4.0.

## Provenance

Code @CODE@: `shoresh/macula/build_source_ontology.py`, `shoresh/macula/build_ontology_propositions.py`,
`shoresh/macula/release_source_ontology.py` (with `release_entity_mentions.py` for the entities).
