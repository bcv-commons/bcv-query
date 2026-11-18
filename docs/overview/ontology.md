# Overview: the source-side ontology and what it is pinned on

What we hold as ontology data for the Hebrew and Greek text, which tables feed it, and the exact versions each rests on. State:
2026-11-18. The design is in `internal-docs/ontology-design-note-2026-11-17.md`; this page is the inventory.

## Principles

- **Tables are the source of truth.** The ontology is a set of Parquet tables with stable ids. An RDF (Turtle) export per release
  can be generated from them; a SPARQL endpoint only if someone asks for one.
- **Every relation says where it comes from:** `kind` (asserted by a source / derived), `method` (source / computed / model),
  `source` (dataset@version), and `confidence`, `count`, `share`, `tier` where the source gives them, so a consumer can filter by
  provenance or by confidence band.
- **Original language only.** Lemmas are Hebrew and Greek, everything else is ids and codes; no English definition or gloss is read.
- **The anchor is the word.** Every mention is a MACULA word id (Tanakh, Greek NT) or a GLAUx word id (Septuagint), so everything
  joins to the clause layouts, the grammar layers and the word alignments.

## What exists

Built by `shoresh/macula/build_source_ontology.py` (phases 1 and 2a). **Local, not yet published**; when it is, it will be a
`-model` dataset, because `concept_of` and the model tier of `rendered_by` are model-made.

| Table | Contents | Count |
|---|---|---|
| `classes` | lexeme `lex:H0001` / `lex:G3962` | 13,786 |
| | concept `con:H1.1` | 8,555 |
| | sense `sense:<UBS sense id>` | 18,606 |
| | domain `dom:<UBS domain code>` | 638 |
| `relations` | `concept_of` (concept → lexeme; model) | 8,519 |
| | `from_sense` (concept → UBS sense; source) | 8,555 |
| | `sense_of` (sense → lexeme; source) | 18,605 |
| | `in_domain` (sense → domain; source) | 24,235 |
| | `rendered_by`, computed tiers (Hebrew lexeme → Greek lexeme) | 6,438 |
| | `rendered_by`, model tier (lexeme pairs; concept → Greek lexeme) | 4,906 |
| `mentions` | Tanakh / Greek NT / Septuagint words, each with its lexeme, and concept and UBS sense where known | 469,476 / 137,779 / 491,860 |
| | with a concept: Tanakh 152,511, Greek NT 56,406; with a UBS sense: 239,117, 127,445 | |
| `aligned` | Tanakh → Septuagint word (MACULA's alignment, basis sure / order / neighbours / number) | 345,461 |
| | Greek NT → Hebrew NT word part: Salkinson–Ginsburg / Delitzsch | 123,728 / 64,531 |

Integrity checks at build: no dangling ids, every aligned mention is a mention, no English values. Concepts `con:H0.*` belong to
words with no Strong's number and have no `concept_of`.

## Tables coming in (pins)

| Input | Version | Revision | Gives |
|---|---|---|---|
| hebrew-word-concepts-model | v0.6 | `dbdb2c9f` | concepts, Tanakh word → concept, concept → Greek lexeme |
| greek-nt-concepts-model | v0.1 | `6f73ed21` | Greek NT word → concept |
| word-senses | v0.1 | `00690ee3` | word → UBS sense, sense → domains |
| hebrew-greek-bridge | v0.1 | `1bee0403` | computed `rendered_by` with tiers, counts, shares |
| hebrew-greek-lexeme-bridge-model | v0.3 | `ffcb5e7c` | model `rendered_by` |
| hebrew-nt-bridge | v0.1 | `525db08f` | Greek NT → Hebrew NT `aligned` (v0.2 `ac40621f` is current: the next build moves to it) |
| bridge corpus (local build b15, published as hebrew-greek-cf) | v0.2 | `c8b8f759` | words, lexemes, the Septuagint alignment edge, GLAUx ids |

Beneath those, the base sources every layer above rests on:

| Source | Pinned as | Licence |
|---|---|---|
| MACULA Hebrew (WLC, lowfat) | git commit `47db250b` (recorded in the tree store) | CC BY 4.0 |
| MACULA Greek (Nestle 1904, lowfat) | file hash recorded in the tree store from its next build | CC BY 4.0 |
| GLAUx Septuagint | the bridge corpus build | CC BY-SA 4.0 |
| UBS Dictionaries of Biblical Hebrew and Greek (senses, domains) | word-senses v0.1 | CC BY-SA 4.0 |
| Salkinson–Ginsburg and Delitzsch Hebrew NTs | hebrew-nt-analysis v0.2 | analysis CC BY 4.0 (the texts' own terms: see its card) |

## Related data that already behaves like ontology, outside these tables

| Data | Where | What it adds |
|---|---|---|
| Person ids for speakers | hebrew-speaker-layer `speaker_id`, `speaker_members` | one id per person or group across quotations |
| Referents | reference-status (ACAI entity ids) | who a noun phrase refers to |
| Addressees | addressees | speaker-to-hearer relation per quotation |
| Noun relations | noun-relations | kin, part, ruler, material, possessor … between words |
| Argument roles | argument-roles | actor, undergoer, recipient, goal … per constituent |
| Root families, parallelism, synsets | hebrew-lexical-references | BDB roots, T'OMIM pairs, Hebrew WordNet (as references, not our judgments) |
| Aramaic ↔ Hebrew | aramaic-hebrew-equivalents | equivalent lexemes |

## Not yet

- **Entities** (people, places, groups as first-class nodes linked to mentions): designed (step O1), waiting for a go to upload.
- **`status` per relation** (asserted / disputed / rejected), the third item in research's order of demand.
- **Publishing** the tables, and the Turtle export: when a consumer needs them.
