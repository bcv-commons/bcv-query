# Overview: the bcv-commons datasets on Hugging Face

All 56 datasets under [huggingface.co/bcv-commons](https://huggingface.co/bcv-commons), grouped by what they are for. Each card on
Hugging Face is the authority for its columns, sources and licence; this page is the map. State: 2026-11-18.

Conventions across the set:

- **Keys.** Hebrew and Greek words are keyed by MACULA word ids (Hebrew 12 digits `BBCCCVVVWWWP`, Greek 11 digits
  `BBCCCVVVWWW`, often with an `n` prefix); clauses by the clause keys of the two clause layouts; lexemes by Strong's numbers.
  Anything can be joined to anything else through these keys, and to a translation through the word alignments (last group).
- **Pins.** A dataset with tags is versioned: pin a tag or a commit, not `main`. Untagged datasets are published once or updated
  in place.
- **Names.** `-model` = written by a language model, no human check (the card names the model and the run). `-similar` =
  computed from encoder vectors. `-sa` = the share-alike part of a dataset that also has a CC BY or CC0 part.
- **No English content.** Values are Hebrew, Greek, ids or codes; English appears only as code names and in the cards.

## 1. The Hebrew and Greek text, laid out

| Dataset | Latest | Licence | What it is |
|---|---|---|---|
| [hebrew-clause-layout](https://huggingface.co/datasets/bcv-commons/hebrew-clause-layout) | v0.37.2 | CC BY-SA 4.0 | The Hebrew Bible (with its Aramaic) one clause segment per line, with indentation, clause dependency across verses, quotations and speakers, and MACULA clause columns |
| [greek-nt-clause-layout](https://huggingface.co/datasets/bcv-commons/greek-nt-clause-layout) | v0.7.1 | CC BY 4.0 | The same for the Greek New Testament (Nestle 1904) |
| [hebrew-clause-lines](https://huggingface.co/datasets/bcv-commons/hebrew-clause-lines) | v0.2 | CC BY-SA 4.0 | The Hebrew layout cut at poetic lines (Miqra according to the Masorah, else the ULT's lines), with share-alike facts per line |
| [greek-nt-clause-lines](https://huggingface.co/datasets/bcv-commons/greek-nt-clause-lines) | v0.2 | CC BY-SA 4.0 | The same for the Greek New Testament |
| [tanakh-hebrew-clauses](https://huggingface.co/datasets/bcv-commons/tanakh-hebrew-clauses) | untagged | CC BY 4.0 | The Hebrew words of every clause segment, one JSON file per chapter, for showing Hebrew beside each clause |
| [hebrew-speaker-layer](https://huggingface.co/datasets/bcv-commons/hebrew-speaker-layer) | v0.16 | CC BY 4.0 | Every quotation of the Hebrew Bible: its speaker (named in Hebrew, with a person id), its edges on the words, nested quotations |
| [passage-facts](https://huggingface.co/datasets/bcv-commons/passage-facts) | v0.3.2 | CC BY-SA 4.0 (CC BY subset included) | Who is heard, what kind of speech, how the text is set (song, poetic lines and verse halves, prose, acrostics, refrains, psalm headings and selah), psalm types, sections and purpose, moods and register cues for the whole Bible, Greek paragraphs; each fact on exact words with its source |
| [word-parts](https://huggingface.co/datasets/bcv-commons/word-parts) / [word-parts-sa](https://huggingface.co/datasets/bcv-commons/word-parts-sa) | v0.1 | CC BY 4.0 / CC BY-SA 4.0 | Every Greek word cut into preverb, augment, reduplication, stem, ending; every Hebrew word into MACULA's morphemes |
| [hebrew-greek-cf](https://huggingface.co/datasets/bcv-commons/hebrew-greek-cf) | v0.2 | CC BY-SA 4.0 | One searchable Context Fabric corpus: Tanakh, Greek NT, Septuagint and two Hebrew NTs on shared keys, linked both ways, with the layers below as features |

## 2. Clause and phrase grammar (one row per clause or constituent)

All keyed by the clause keys of the two layouts; all built by rule from MACULA and other open sources.

| Dataset | Latest | Licence | What it is |
|---|---|---|---|
| [clause-columns](https://huggingface.co/datasets/bcv-commons/clause-columns) | v1.2 | CC BY-SA 4.0 | Main verb and its form, voice, stem, person; negation and scope; force; quotation and speaker; narrative line; subject and subject switch |
| [argument-roles](https://huggingface.co/datasets/bcv-commons/argument-roles) | v0.2 | CC BY-SA 4.0 | Every constituent with its relation, the verb frame's macrorole and a semantic role (actor, recipient, goal, source, location …) |
| [clause-connectives](https://huggingface.co/datasets/bcv-commons/clause-connectives) | v0.1 | CC BY-SA 4.0 | The connective that opens each clause and the kind of link it makes |
| [clause-extras](https://huggingface.co/datasets/bcv-commons/clause-extras) | v0.1 | CC BY-SA 4.0 | Polarity, mood, reflexivity and degree per clause |
| [time-aspect](https://huggingface.co/datasets/bcv-commons/time-aspect) | v0.2 | CC BY-SA 4.0 | Time, aspect and salience band per clause |
| [reference-status](https://huggingface.co/datasets/bcv-commons/reference-status) | v0.2 | CC BY-SA 4.0 | For every noun-phrase head: its referent and its status in the episode (new, given, restaged, known), the basis of "a" / "the" / "this" / a pronoun |
| [noun-relations](https://huggingface.co/datasets/bcv-commons/noun-relations) | v0.1 | CC BY-SA 4.0 | The relation of each noun joined to a noun (construct, suffix, genitive): kin, part, member, ruler, material, origin, possessor … with the dependent's animacy |
| [inclusive-we](https://huggingface.co/datasets/bcv-commons/inclusive-we) | v0.1 | CC BY-SA 4.0 | Whether each "we" includes the person spoken to |
| [addressees](https://huggingface.co/datasets/bcv-commons/addressees) | v0.1 | CC BY-SA 4.0 | Who each quotation is spoken to where the text shows it, how that was found, and the speaker-to-hearer relation |

## 3. Words and meanings

| Dataset | Latest | Licence | What it is |
|---|---|---|---|
| [word-senses](https://huggingface.co/datasets/bcv-commons/word-senses) | v0.1 | CC BY-SA 4.0 | The UBS dictionaries' sense and domains on 366,562 Hebrew, Aramaic and Greek words |
| [hebrew-word-senses](https://huggingface.co/datasets/bcv-commons/hebrew-word-senses) | untagged | CC BY 4.0 | Hebrew lexemes split into senses by how translations render them |
| [hebrew-lexical-references](https://huggingface.co/datasets/bcv-commons/hebrew-lexical-references) | untagged | CC0 | Strong's-linked transcriptions of outside references: BDB roots, Hebrew WordNet synsets, T'OMIM parallelism, the Septuagint bridge |
| [semantic-neighbors](https://huggingface.co/datasets/bcv-commons/semantic-neighbors) | untagged | CC0 | 6,671 Hebrew word pairs judged close in meaning. Note: two of its signals are English gloss overlap and LLM verdicts, so it serves as a measurement; a gloss- and LLM-free rebuild was tried twice (2026-11-18) and did not reach its precision |
| [strongs](https://huggingface.co/datasets/bcv-commons/strongs) | untagged | CC BY-SA 4.0 | Per Strong's number, the words each language uses for it, with how each was obtained |
| [prior-pack](https://huggingface.co/datasets/bcv-commons/prior-pack) | untagged | CC BY-SA 4.0 | Language-independent lexeme priors for the aligner |
| [senses-attested](https://huggingface.co/datasets/bcv-commons/senses-attested) | untagged | CC BY-SA 4.0 | For each UBS Hebrew sense, the target-language words that render it, from the alignments |
| [senses-attested-bhsa](https://huggingface.co/datasets/bcv-commons/senses-attested-bhsa) | untagged | CC BY-NC-SA 4.0 | Legacy: the same on BHSA-numbered senses; retired, non-commercial |

## 4. Hebrew–Greek bridges

| Dataset | Latest | Licence | What it is |
|---|---|---|---|
| [hebrew-greek-bridge](https://huggingface.co/datasets/bcv-commons/hebrew-greek-bridge) | v0.1 | CC BY-SA 4.0 | Which Greek lexemes render a Hebrew lexeme in the Septuagint, and which Greek tense, voice and mood a Hebrew verb form corresponds to |
| [hebrew-nt-analysis](https://huggingface.co/datasets/bcv-commons/hebrew-nt-analysis) | v0.2 | CC BY 4.0 | The Hebrew NTs of Salkinson–Ginsburg and Delitzsch analysed word by word as MACULA analyses the Tanakh |
| [hebrew-nt-bridge](https://huggingface.co/datasets/bcv-commons/hebrew-nt-bridge) | v0.2 | CC BY 4.0 | Which Hebrew word renders which Greek NT word, in those two Hebrew NTs |
| [aramaic-hebrew-equivalents](https://huggingface.co/datasets/bcv-commons/aramaic-hebrew-equivalents) | v0.1.1 | CC BY-SA 4.0 | The Hebrew equivalent of each Aramaic lexeme, so Hebrew data reaches the Aramaic parts |

## 5. Model-made layers (`-model`: no human check)

| Dataset | Latest | Licence | What it is |
|---|---|---|---|
| [hebrew-word-concepts-model](https://huggingface.co/datasets/bcv-commons/hebrew-word-concepts-model) | v0.6 | CC BY-SA 4.0 | Finer concepts for contested Hebrew content words, per occurrence |
| [greek-nt-concepts-model](https://huggingface.co/datasets/bcv-commons/greek-nt-concepts-model) | v0.1 | CC BY-SA 4.0 | Which of those Hebrew concepts each Greek NT content word expresses |
| [hebrew-greek-lexeme-bridge-model](https://huggingface.co/datasets/bcv-commons/hebrew-greek-lexeme-bridge-model) | v0.3 | CC BY-SA 4.0 | A partner lexeme on the other side for lexemes the Septuagint bridge leaves without one |
| [hebrew-nt-review-model](https://huggingface.co/datasets/bcv-commons/hebrew-nt-review-model) | v0.1.1 | CC BY 4.0 | A model's review of the Greek–Hebrew NT word links |
| [hebrew-phrase-types-model](https://huggingface.co/datasets/bcv-commons/hebrew-phrase-types-model) | v0.1 | CC BY 4.0 | Semantic types for the 50,829 clause-level prepositional phrases of the Hebrew Bible |
| [clause-subjects-model](https://huggingface.co/datasets/bcv-commons/clause-subjects-model) | v0.1 | CC BY 4.0 | Who or what the subject is, for clauses the rule layers leave without one |
| [passage-moods-model](https://huggingface.co/datasets/bcv-commons/passage-moods-model) | v0.1 | CC BY-SA 4.0 | Which feelings the Hebrew or Greek of a passage marks, and by which words, for 598 passages the mood rules leave open; read by a model, no human check |
| [hebrew-commentary-terms](https://huggingface.co/datasets/bcv-commons/hebrew-commentary-terms) | v0.1 | CC BY-SA 4.0 | What the classical Hebrew commentators say about words and psalms, in their own Hebrew terms, on MACULA word keys: 15,095 statements from fixed formulas (Metzudat Zion, Radak, Meiri, Ibn Ezra, Rashi, Malbim), with the sages' word lists |
| [hebrew-commentary-terms-model](https://huggingface.co/datasets/bcv-commons/hebrew-commentary-terms-model) | v0.1 | CC BY-SA 4.0 | The same commentators' openings on all 150 psalms read by a model (kind, voice, occasion, turn), terms copied from the text; no human check |

## 6. Vector tables (`-similar`)

| Dataset | Latest | Licence | What it is |
|---|---|---|---|
| [clauses-similar](https://huggingface.co/datasets/bcv-commons/clauses-similar) | v0.1 | CC BY-SA 4.0 | Per clause, the 10 most similar clauses of the same text (Tanakh; Greek NT) outside its own verse |
| [tanakh-nt-clauses-similar](https://huggingface.co/datasets/bcv-commons/tanakh-nt-clauses-similar) | v0.1 | CC BY-SA 4.0 | Per Tanakh clause, the 10 most similar Greek NT clauses |

How they are made: [vector-store.md](vector-store.md).

## 7. Alignments and target languages (built by lexeme-aligner)

These connect the Hebrew and Greek keys above to translations. They carry no running text of any translation.

| Dataset | Latest | Licence | What it is |
|---|---|---|---|
| [lexeme-alignments](https://huggingface.co/datasets/bcv-commons/lexeme-alignments) | untagged | CC0 | Per language: target word forms and the lexemes they render, with counts and confidence |
| [compact-alignments](https://huggingface.co/datasets/bcv-commons/compact-alignments) | untagged | CC0 | Per edition and book, verse by verse: which Hebrew/Greek content word aligned to which target token (positions only); [-extra](https://huggingface.co/datasets/bcv-commons/compact-alignments-extra) and [-meta](https://huggingface.co/datasets/bcv-commons/compact-alignments-meta) are optional layers |
| [alignments-by-id](https://huggingface.co/datasets/bcv-commons/alignments-by-id) | v1.1 | CC0 | NT translations aligned to MACULA Greek word ids |
| [alignments-tr](https://huggingface.co/datasets/bcv-commons/alignments-tr) | untagged | CC0 | Translations made from the Textus Receptus, aligned to its words |
| [aligned-mwe](https://huggingface.co/datasets/bcv-commons/aligned-mwe) | untagged | CC0 | Lexemes rendered by a multi-word phrase |
| [full-alignments-llm](https://huggingface.co/datasets/bcv-commons/full-alignments-llm) | v1.4 | CC0 | Every word of a verse aligned, function words included, checked by a model |
| [full-alignments-manual](https://huggingface.co/datasets/bcv-commons/full-alignments-manual) / [-sa](https://huggingface.co/datasets/bcv-commons/full-alignments-manual-sa) | v1.1 / untagged | CC BY 4.0 / CC BY-SA 4.0 | Full alignments made by people (gold) |
| [alignment-conventions](https://huggingface.co/datasets/bcv-commons/alignment-conventions) | untagged | CC BY 4.0 | Per-language rules given to the model that checks alignments |
| [cross-lingual-span-profile](https://huggingface.co/datasets/bcv-commons/cross-lingual-span-profile) | untagged | CC0 | Per lexeme, whether languages tend to need one word or a phrase for it |
| [constituent-order-profile](https://huggingface.co/datasets/bcv-commons/constituent-order-profile) | untagged | CC0 | Per language, how it reorders Hebrew clause constituents |
| [target-morphology](https://huggingface.co/datasets/bcv-commons/target-morphology) | untagged | CC0 | Learned prefixes, suffixes and stems per language |
| [target-stopwords](https://huggingface.co/datasets/bcv-commons/target-stopwords) | untagged | CC0 | Induced function-word lists per language |
| [gram-struct](https://huggingface.co/datasets/bcv-commons/gram-struct) | untagged | per partition | Per language, grammar facts fused from the aligner's sources, split by licence |
| [language-analysis](https://huggingface.co/datasets/bcv-commons/language-analysis) | untagged | CC0 | What the bsb-add-books drafting projects learned about each target language |

## Licences in short

CC0 and CC BY 4.0 need attribution at most; CC BY-SA 4.0 (most of the grammar layers, because of share-alike sources such as GLAUx
and unfoldingWord) passes share-alike on to what is built from it; CC BY-NC-SA appears only on the retired `senses-attested-bhsa`.
Where a dataset has a CC BY part beside a CC BY-SA one (passage-facts `data-cc-by/`, word-parts, full-alignments-manual), the card
says which files are which.
