---
license: other
license_name: cc-by-4.0-and-cc-by-sa-4.0
license_link: README.md
language:
  - he
pretty_name: Hebrew New Testament Analysis
tags:
  - bible
  - hebrew
  - new-testament
  - morphology
  - syntax
  - clauses
  - lemmatization
  - translation
size_categories:
  - 100K<n<1M
configs:
  - config_name: heb_scg-words
    default: true
    data_files:
      - split: train
        path: heb_scg/words.parquet
  - config_name: heb_scg-clauses
    data_files:
      - split: train
        path: heb_scg/clauses.parquet
  - config_name: heb_mod-words
    data_files:
      - split: train
        path: heb_mod/words.parquet
  - config_name: heb_mod-clauses
    data_files:
      - split: train
        path: heb_mod/clauses.parquet
  - config_name: heb_scg-features
    data_files:
      - split: train
        path: heb_scg/features.parquet
  - config_name: heb_scg-pieces
    data_files:
      - split: train
        path: heb_scg/pieces.parquet
  - config_name: heb_scg-clause-marks
    data_files:
      - split: train
        path: heb_scg/clause_marks.parquet
  - config_name: heb_mod-features
    data_files:
      - split: train
        path: heb_mod/features.parquet
  - config_name: heb_mod-pieces
    data_files:
      - split: train
        path: heb_mod/pieces.parquet
  - config_name: heb_mod-clause-marks
    data_files:
      - split: train
        path: heb_mod/clause_marks.parquet
---

# Hebrew New Testament Analysis

Hebrew translations of the New Testament, analysed word by word as MACULA Hebrew analyses the Tanakh. Each word is split
into its parts (prefixes and suffixes are parts of their own), and each part has a class, a lemma, a MACULA lexeme id and a Strong's
number. Each verse is also divided into clause segments, with their depth and parent inside the verse. It is meant for aligning a
Hebrew New Testament with the Greek, for lexical study across the two Testaments, and as a Hebrew reading of the New Testament's
clause structure. From v0.3 each part also has its person, number, gender, state and definiteness, its head and relation in
the phrase, and, on the head of a constituent, its semantic role, reference status and kind of referent; each clause segment
has its clause marks (force, polarity, mood, time, aspect, relation, voice, negator, connective).

| | |
|---|---|
| Release | **@TAG@**, built @BUILT@ from bcv-query `@COMMIT@` |
| Editions | `heb_scg`: Salkinson–Ginsburg (1885/86), with vowel points. `heb_mod`: Delitzsch, as eBible's "Modern Hebrew Bible" has it, without vowel points (new in v0.2) |
| Size, `heb_scg` | @SCG_WORDS@ words, @SCG_PARTS@ word parts, @SCG_SEGMENTS@ clause segments |
| Size, `heb_mod` | @MOD_WORDS@ words, @MOD_PARTS@ word parts, @MOD_SEGMENTS@ clause segments |
| New in v0.3 | `features.parquet`, `pieces.parquet`, `clause_marks.parquet` per edition; the v0.2 files are unchanged, file for file |

**Most of this is model output.** The New Testament has no MACULA analysis. Words whose form occurs in MACULA's Tanakh with
one near-unanimous analysis take MACULA's own (`source = "macula"`: @SCG_MACULA_WORDS@ words of `heb_scg`, @SCG_MACULA_SHARE@;
@MOD_MACULA_WORDS@ of `heb_mod`, @MOD_MACULA_SHARE@). The rest (@SCG_MODEL_WORDS@ and @MOD_MODEL_WORDS@ words) and every clause segment
come from a tagger trained on MACULA Hebrew (`source = "model"`). It has not been checked by hand on the New Testament: see *Quality*.

**`heb_mod` is the weaker of the two.** Its text has no vowel points, so more forms can be read two ways: fewer words are settled by
their form alone, and the tagger is less sure of lemmas (see *Quality*). Its text also has verses whose boundary is lost or moved
(see *The `heb_mod` text*). The words and clauses of `heb_scg` are unchanged from v0.1, file for file.

## Files

| File | Rows |
|---|---|
| `<edition>/words.parquet` | one per word part |
| `<edition>/clauses.parquet` | one per clause segment |
| `<edition>/manifest.json` | per book: the text fingerprint, verse and word counts; the model's SHA-256 and whether it read vowel points; tokenizer and verse-text versions |
| `<edition>/features.parquet` | one per word part (the verse-number rows left out): person, number, gender, state, definiteness (v0.3; CC BY 4.0) |
| `<edition>/pieces.parquet` | one per word part with letters: head, relation, semantic role, reference status, kind of referent (v0.3; **CC BY-SA 4.0**) |
| `<edition>/clause_marks.parquet` | one per clause segment: the clause marks (v0.3; **CC BY-SA 4.0**) |
| `SHA256SUMS` | SHA-256 of every file |

## The words

A word is what the bcv-commons tokenizer (v@TOKENIZER@, bibles verse-text @VERSE_TEXT@) gives: a run of letters, split at spaces,
maqaf and punctuation. The verse text and the word positions are the same as in bcv-commons/lexeme-aligner's alignments of the
edition: `i` is the aligner's token number, and the text fingerprints in `manifest.json` match the aligner's file hashes.

| Column | |
|---|---|
| `book`, `chapter`, `verse` | USFM book code; the edition's chapter and verse |
| `i` | the word's position in the verse (0-based, the aligner's token) |
| `part` | the part's position in the word (0-based) |
| `token` | the word as the tokenizer gives it: unpointed |
| `word` | the word with its vowel points (`heb_mod`: as printed, without) |
| `text` | the part, with its points where the edition has them. Concatenating the parts gives `word`. The article after a preposition is a part without letters (`""`), as in MACULA: בַּמָּשִׁיחַ is ב + the article + מָּשִׁיחַ |
| `class` | MACULA word class: noun, verb, prep, cj, art, pron, adj, adv, num, rel, ptcl, ij, om (object marker), x; `verse-number` for the verse number some editions carry at the start of the verse text (Salkinson: "א", "ב", … "טו"; `heb_mod` has none), which is not part of the text |
| `lemma` | MACULA's lemma. Where no lemma is given (`lexeme` empty), the part's own letters, unpointed |
| `lexeme` | MACULA lexeme id (`hbo:0559`); empty for a name or word MACULA does not have, and where no known lemma fits the letters |
| `strong` | Strong's number as MACULA gives it (`0559`, `3807a`) |
| `role` | MACULA role, where the part heads one (`v`, `s`, `o`, `p`, `adv`, …) |
| `source` | `macula`: the analysis of this form in MACULA's Tanakh (at least 90% of its occurrences analysed alike; for `heb_mod` the form without its points, so a form with two readings is left to the tagger); `model`: the tagger's |
| `p_split` | for `model` words, on part 0: the tagger's confidence in the split (among the splits that fit the word) |
| `form`, `person` | on the verb part: MACULA's verb form (qatal, wayyiqtol, yiqtol, weqatal, imperative, jussive, cohortative, participle active/passive, infinitive construct/absolute) and the person (first, second, third) |
| `seg` | the clause segment of the verse the word stands in (1-based; see `clauses.parquet`) |

## The clauses

A clause segment is a run of whole words inside a verse that belongs to one clause, as in the
[Hebrew Bible Clause Layout](https://huggingface.co/datasets/bcv-commons/hebrew-clause-layout) built on MACULA's trees; a clause
interrupted by another gives two segments.

| Column | |
|---|---|
| `book`, `chapter`, `verse`, `seg` | the segment (1-based in the verse) |
| `first_i`, `last_i` | its first and last word (`i`) |
| `depth` | clause ancestors inside the verse, as MACULA's tree counts them (0 = on the verse's own group) |
| `parent` | where its parent clause stands, in segments from this one: `-1` the one before, `+1` the one after, `-4+`, `+2+`; `none` on the verse's own group |
| `kind` | `VC` (with a verb) or `NC` |
| `rule` | the MACULA clause rule, the order of its constituents (`V-S-PP`; the 60 most common rules, others `other`) |
| `att` | the MACULA attachment kind where the segment meets an earlier segment of the verse in the tree ("parent rule \| child index \| class \| role \| opening word", as the clause layout's `[tree]` setting reads it; `-` none; the 300 most common, others `other`) |

## Word features (v0.3, `features.parquet`)

One row per word part (`heb_scg` @SCG_FEATURE_ROWS@, `heb_mod` @MOD_FEATURE_ROWS@), on the keys `book, chapter, verse, i, part` of
`words.parquet`. No value comes from a language model; `*_model` in a basis marks values that stand on the tagger's reading of the
part (its class and lemma).

| Column | |
|---|---|
| `person`, `number`, `gender`, `state` | MACULA Hebrew's strings: first/second/third; singular/plural/dual; masculine/feminine/common/both; absolute/construct. Empty: no value (infinitives have no person, number, gender; participles no person; names and demonstratives no state, as in MACULA) |
| `definite` | `article` (an article part before it in the word, also the article hidden after a preposition), `suffix` (a pronoun suffix follows), `name` (a Tanakh proper noun's Strong's number), or empty |
| `<column>_basis` | strongest first: `form` / `form_model` (the whole word is a Tanakh form with this analysis, and MACULA gives it this value in at least 90% of its occurrences), `part` / `part_model` (the same for the single part), `affix` / `affix_model` (a table counted on the MACULA Tanakh: the part's ending, a verb's prefix letter and form, a suffix's host, the article and suffix in the word, the next word's first part, a noun's lexeme; the most specific key with at least 20 Tanakh cases decides if at least 90% of them agree), `rule` (`definite`) |
| `state_both` | the noun or adjective, with no article and no suffix, has a written form the Tanakh uses as both absolute and construct (each at least 3 times, the rarer at least 5%: חֶסֶד, אִישׁ, עֶבֶד). Its `state` is then the commoner Tanakh use or the next word's, not something the form decides: read the context |
| `rule_key` | the table key that decided an `affix` value |

Verb person is never taken from a table keyed on that same person: the prefix and ending alone decide it where they can, and they
replace the analysis's `person` (in `words.parquet`) only where the deciding key holds the prefix letter and an ending (for a qatal
or weqatal an ending of at least 3 written characters), or an ending alone in a qatal or weqatal; never from a prefix letter alone.
Where the form allows two persons (a ת-yiqtol), the analysis's person stays. `heb_scg`: 202 verb persons replaced, 47 dropped
(the Tanakh never has that person with that prefix and ending); `heb_mod`: 156 and 38.

Coverage where a value is expected:

| | `heb_scg` | `heb_mod` |
|---|---|---|
| verb person / number / gender | 96 / 96 / 96% | 96 / 93 / 94% |
| noun number / gender / state | 90 / 91 / 88% | 85 / 90 / 85% |
| adjective number / gender / state | 99 / 99 / 95% | 97 / 98 / 91% |
| pronoun person / number / gender | 98 / 99 / 98% | 100 / 100 / 91% |

Hold-out: the affix tables applied to the parts the Tanakh form lookup did fill agree with the lookup in 97-100% (`heb_scg`; verb
person 97.1%, noun state 98.3%) and 95-100% (`heb_mod`; verb person 94.9%). What is left: names the Tanakh lacks, nouns whose state
neither the form nor the next word decides, and in `heb_mod` unpointed הוא.

## Phrases, roles and clause marks (v0.3, `pieces.parquet`, `clause_marks.parquet`)

**All of these are model values**, from a second tagger (`python -m macula.hebrew_nt_layers`; dicta-il/dictabert with a character
channel, a biaffine head scorer and label heads; 3 epochs, seed 1), trained on the MACULA Hebrew Tanakh as bcv-commons' source
examples (build k1, format 1.9) give it: MACULA's tree as head and relation per part, and on the constituents the semantic role,
reference status and kind of referent of bcv-commons' argument-roles, reference-status and entity layers, and the clause marks of
its clause columns, time-aspect and clause-connectives layers. Only values from rules and sources went in (no model-made values,
no BHSA, no TBTA, no English text). Pointed model for `heb_scg` (SHA-256 `24ac70b4a9e6…`), unpointed for `heb_mod` (`5c489297678d…`);
the model files are not part of this release. No language model was called, and nothing of the Greek went into a value. The
values have not been checked by hand.

`pieces.parquet` (`heb_scg` @SCG_PIECE_ROWS@ rows, `heb_mod` @MOD_PIECE_ROWS@; the article hidden after a preposition has no letters
and no row), keys `book, chapter, verse, i, part`:

| Column | |
|---|---|
| `head_i`, `head_part`, `head_p` | the part it depends on (null: the verse's root), and the model's probability |
| `rel`, `rel_p` | the relation: the MACULA rule and slot inside phrases (`NPofNP:1` the second noun of a construct chain, `PrepNp:0`, `DetNP:0`, `Np-Appos:1`, `QuanNP:0`, …) or the clause role of a constituent head (`s`, `o`, `pp`, `adv`, `io`, `vc`, `root`, …); the 80 commonest Tanakh labels, else `other` |
| `sem_role`, `ref_status` (+ `_p`) | on the part that heads a constituent: its semantic role (פּוֹעֵל, נִפְעָל, מְקַבֵּל, מָקוֹם, …) and reference status (זְכִירָה רִאשׁוֹנָה, נִזְכָּר, …); `-` elsewhere |
| `who_kind` (+ `_p`) | the kind of referent: `person`, `deity`, `group`, `place`, `realia`, `fauna`, `flora`; `-` none |

`clause_marks.parquet`, one row per segment of `clauses.parquet` (`book, chapter, verse, seg`): `force`, `polarity`, `mood`,
`time`, `time_abs`, `aspect`, `relation`, `voice`, `negator`, `connective`, each with `_p`; `-` = the mark is absent.

Beside every value stands `<column>_carried`: the value carried from the Greek New Testament (MACULA Greek in the same source-examples
format) through lexeme-aligner's word links, null where no link carries one (a clause takes the Greek clause most of its words are in);
and `<column>_agree`. The carried value is a second witness, not a reference: the Greek tree has other labels and another shape
(head 44-48% and relation 28-30% agree), its participles give relative time where the Hebrew gives absolute time, it has no voice, and
its `relation` names the joining (חִבּוּר) where the Hebrew names the connective.

Measured on the same Tanakh test chapters as above, against the training format:

| model | head (UAS) | head + rel (LAS) | rel | sem_role | ref_status | who_kind | force | polarity | mood | time | time_abs | aspect | relation | voice | negator | connective |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pointed (`heb_scg`) | 93.2 | 87.9 | 89.4 | 78.3 | 66.8 | 62.1 | 98.4 | 99.7 | 95.3 | 89.9 | 88.4 | 93.8 | 90.9 | 97.7 | 99.8 | 99.0 |
| unpointed (`heb_mod`) | 93.1 | 87.3 | 88.8 | 77.9 | 67.9 | 61.4 | 98.1 | 99.9 | 95.0 | 89.1 | 87.3 | 92.6 | 90.5 | 96.2 | 99.9 | 99.0 |

`sem_role`, `ref_status` and `who_kind` count the parts where the reference or the prediction is not `-`. On the New Testament, two
checks against the Hebrew form: of the segments whose first verb is a wayyiqtol the model gives past (עָבָר) in 5,166 of 5,170
(`heb_scg`) and 5,914 of 6,096 (`heb_mod`); of the segments with a negator word, negative in 3,032 of 3,281 and 2,770 of 2,993.

A check against one translation (the Swahili ULB New Testament aligned to `heb_scg`, read for what Swahili marks; its floor, the fit
where both sides are surely right, is about 0.91-0.95): a Swahili negative verb in 66% of the segments the model calls negative and
1% of the affirmative ones (the carried value: 57% / 1.5%); a Swahili passive in 54% of model-passive verbs, 10% of active ones; a
demonstrative agrees with the model's head noun in 90%; the second noun of a construct chain with its head in 91% (94% where the
model's head is the adjacent noun). A noun subject (`rel` = `s`) agrees with its verb in 82%, and 87% where `rel_p` and `head_p` are
both at least 0.95: **read `rel` = `s` with both probabilities at 0.95 or more.** The model's `time` mostly restates the verb form;
keep `time_carried` beside it.

## How it was made

The tagger (`python -m macula.clause_tagger` in [bcv-query](https://github.com/bcv-commons/bcv-query)) reads a verse with a Hebrew
BERT ([dicta-il/dictabert](https://huggingface.co/dicta-il/dictabert), CC BY 4.0), whose tokenizer drops the vowel points, and with a
character channel that reads each word with its points. It was trained on MACULA Hebrew's Tanakh (commit `@MACULA_COMMIT@`): the
words, their parts, classes, lemmas and roles, MACULA's verb forms, and the clause segments, depth, parents, clause rules and
attachment kinds of MACULA's trees as the clause layout reads them. No BHSA data, and no English, went in. A lemma has to fit the
part: among the model's best lemmas the one whose strong consonants (not א ה ו י נ) the part carries most fully; where none
explains a part of three or more such consonants by more than one, no lemma is given.

For `heb_mod` a second model was trained the same way on the same data with the vowel points stripped (`train --unpointed`): the
character channel reads the bare letters, the parts are counted in letters, and the lemmas stay MACULA's. The model files (SHA-256
`@SCG_MODEL_SHA@` for `heb_scg`, `@MOD_MODEL_SHA@` for `heb_mod`) are not part of this release.

## Quality

Measured on 856 Tanakh verses the tagger was not trained on (Gen 37–45, Ruth, Jonah, 1 Sam 1–10, Deut 5–11; narrative and
discourse, the closest Tanakh match to a New Testament in this style), against MACULA, with the same lookup of known forms
as here (from the training books only):

| | With vowel points (`heb_scg`) | Without (`heb_mod`) |
|---|---|---|
| Split into parts right | 97.9% | 97.7% |
| Class (rightly split words) | 99.0% | 98.3% |
| Lemma (rightly split words) | 95.3% | 93.9% |
| Split, classes and lemmas of a word all right | 90.1% | 87.4% |
| Words settled by the lookup of known forms | 83.9% | 70.6% |
| Forms not in the training books: share of words | 11.9% | 8.1% |
| on them: split right / then lemma right | 82.7% / 66.3% | 86.0% / 65.9% |

| Clauses | With vowel points | Without |
|---|---|---|
| Segment boundaries between words (F1) | 94.9% | 94.3% |
| Segments reproduced exactly | 88.6% | 87.5% |
| Depth in the verse, on exactly matched segments | 84.4% | 84.6% |
| Verb found (recall) / verb form / person | 99.1% / 96.0% / 97.6% | 98.8% / 94.5% / 97.3% |

Without the lookup, the tagger alone has all of a word right for 81.2% of the words when it reads no vowel points.

**What the missing points cost on New Testament text.** The Salkinson–Ginsburg text was also tagged with its points stripped, by
the model that reads none, and compared with the analysis published here (the same words, so every difference comes from the points):
the split is the same for 97.2% of 115,262 words, split, classes and lemmas all for 89.9%; of the nouns, verbs, adjectives and
adverbs with a Strong's number, 93.3% keep the same number, and 93.0% of the clause segments are found again. This is agreement
between two models, not accuracy, but it is the nearest figure for `heb_mod` on its own kind of text.

For comparison, a modern-Hebrew parser (Parsan, DictaBERT-based) on the same verses, with their points: segment boundaries 77.1%,
segments exact 56.3%, verb form 92.5%.

The forms not in the training books are the closest stand-in for the New Testament's own words (names, New Testament vocabulary,
new prefixed forms); on them expect the lower column. The New Testament has not been scored, since it has no reference analysis. To
favour precision, filter on `source`, `p_split` and an empty `lexeme`.

Known fault: where a part has only one strong consonant, the lemma chosen by its consonants can be a wrong word (אַהֲבָה read as
נָבִיא in a few verses of both editions).

## The `heb_mod` text

The text is used as the source gives it. Ten verses have no words, and their words stand in the verse before: Matthew 5:37,
Mark 7:22, Luke 1:49, 5:31, 12:48, 22:47, Romans 6:14, 1 Corinthians 3:11, 2 Corinthians 13:13, Revelation 3:20. In about fifty
more places words seem to have moved across a verse boundary (counted against Salkinson–Ginsburg, not read one by one). In those
verses the clause segments, which never cross a verse, are affected. The source does not say which of Delitzsch's revisions it prints.

## Sources and licence

| Part | Source | Licence |
|---|---|---|
| Salkinson–Ginsburg Hebrew New Testament | via [bible.helloao.org](https://bible.helloao.org) (`heb_scg`), from eBible.org (`hebsg`) | public domain |
| Delitzsch's Hebrew New Testament | via [bible.helloao.org](https://bible.helloao.org) (`heb_mod`, the New Testament of eBible.org's "Modern Hebrew Bible", `heb`), the route bcv-commons/bibles names | public domain |
| Word parts, classes, lemmas, lexemes, verb forms, clauses (training data and the forms looked up) | MACULA Hebrew (Clear Bible / Biblica), `WLC/lowfat`, commit `@MACULA_COMMIT@` | CC BY 4.0 |
| Base model | dicta-il/dictabert | CC BY 4.0 |
| Verse text and words | bcv-commons/bibles verse-text @VERSE_TEXT@ | CC0 1.0 |
| Argument roles, reference status, entities, clause columns, time-aspect, clause connectives (the training values of `pieces.parquet` and `clause_marks.parquet`, and their `_carried` columns) | bcv-commons' own layers on MACULA Hebrew (their sources on their dataset cards) | CC BY-SA 4.0 |
| MACULA Greek (the `_carried` values) | Clear Bible / Biblica | CC BY 4.0 |
| Word links of the `_carried` values | bcv-commons/lexeme-aligner | CC0 1.0 |
| This analysis: `words`, `clauses`, `features` | bcv-commons | **CC BY 4.0** |
| This analysis: `pieces`, `clause_marks` | bcv-commons | **CC BY-SA 4.0** (ShareAlike, from the training values) |
| The code (bcv-query) | bcv-commons | MIT |

**Attribution** when you use this dataset:

> Hebrew New Testament Analysis (@TAG@), bcv-commons, CC BY 4.0 (`pieces` and `clause_marks`: CC BY-SA 4.0). Analysis trained on
> MACULA Hebrew, Clear Bible / Biblica (CC BY 4.0).
> Texts: Salkinson–Ginsburg Hebrew New Testament; Delitzsch's Hebrew New Testament (public domain).

## Feedback

Issues and requests: [bcv-commons/bcv-query](https://github.com/bcv-commons/bcv-query/issues). Please name the edition, the verse and
the word, and what you expected.
