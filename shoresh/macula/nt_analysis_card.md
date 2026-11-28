---
license: other
license_name: cc-by-4.0-and-cc-by-sa-4.0
license_link: https://huggingface.co/datasets/bcv-commons/hebrew-nt-analysis/blob/main/README.md#sources-and-licence
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
  - config_name: heb_scg-speech
    data_files:
      - split: train
        path: heb_scg/speech.parquet
  - config_name: heb_scg-entities
    data_files:
      - split: train
        path: heb_scg/entities.parquet
  - config_name: heb_mod-speech
    data_files:
      - split: train
        path: heb_mod/speech.parquet
  - config_name: heb_mod-entities
    data_files:
      - split: train
        path: heb_mod/entities.parquet
  - config_name: heb_scg-referents
    data_files:
      - split: train
        path: heb_scg/referents.parquet
  - config_name: heb_mod-referents
    data_files:
      - split: train
        path: heb_mod/referents.parquet
---

# Hebrew New Testament Analysis

Hebrew translations of the New Testament, analysed word by word as MACULA Hebrew analyses the Tanakh. Each word is split
into its parts (prefixes and suffixes are parts of their own), and each part has a class, a lemma, a MACULA lexeme id and a Strong's
number. Each verse is also divided into clause segments, with their depth and parent inside the verse. It is meant for aligning a
Hebrew New Testament with the Greek, for lexical study across the two Testaments, and as a Hebrew reading of the New Testament's
clause structure. From v0.3 each part also has its person, number, gender, state and definiteness, its head and relation in
the phrase, and, on the head of a constituent, its semantic role, reference status and kind of referent; each clause segment
has its clause marks (force, polarity, mood, time, aspect, relation, voice, negator, connective). From v0.4 each verb part
also has its stem (binyan), and each quotation segment its speaker and addressee, with the addressee's number. From v0.5
each pronoun, pronoun suffix and finite verb has its referent (an id shared along the chain) and the part that last names it.

| | |
|---|---|
| Release | **@TAG@**, built @BUILT@ from bcv-query `@COMMIT@` |
| Editions | `heb_scg`: Salkinson–Ginsburg (1885/86), with vowel points. `heb_mod`: Delitzsch, as eBible's "Modern Hebrew Bible" has it, without vowel points (new in v0.2) |
| Size, `heb_scg` | @SCG_WORDS@ words, @SCG_PARTS@ word parts, @SCG_SEGMENTS@ clause segments |
| Size, `heb_mod` | @MOD_WORDS@ words, @MOD_PARTS@ word parts, @MOD_SEGMENTS@ clause segments |
| New in v0.3 | `features.parquet`, `pieces.parquet`, `clause_marks.parquet` per edition; the v0.2 files are unchanged, file for file |
| New in v0.4 | `stem` in `features.parquet` (its other columns unchanged, value for value); `speech.parquet`, `entities.parquet` per edition |
| New in v0.5 | `referents.parquet` per edition; every other file unchanged |
| New in v0.6 | `speech.parquet` from the mended addressees layer (bcv-commons/addressees v0.2); `referents.parquet` rebuilt on it; every other file unchanged |
| New in v0.10 | **Speech inside speech.** The Greek speaker layer had one level only, so a parable's people, a cited psalm and an angel whose words Paul reports carried the outer quotation, its speaker and its hearers. `speech.parquet` now takes the quotations inside quotations of the Greek clause layout v0.8 and their hearers from bcv-commons/addressees v0.4 (new columns `quote_level`, `quote_around`; `quote`, `speaker`, `addressee` and the addressee's number change on the segments inside them, and the layer's number on many others, since the Greek "you" now counts pronouns too); `referents.parquet` and the scheme's `added` table are rebuilt on it; `scheme/clause_join.parquet` has the same rows in a fixed order. Every other file unchanged, `words.parquet` byte for byte |
| New in v0.9 | The **clause scheme**: `<edition>/scheme/` (clauses, their constituents, unsaid subjects, order statements), `clause-scheme.toml`, `validate_scheme.py`. `speech.parquet`: one quotation mended (Acts 2:14-36 is said to the crowd, bcv-commons/addressees v0.3); `referents.parquet` rebuilt on it. Every other file unchanged, `words.parquet` byte for byte |
| New in v0.8 | `features.parquet` only, its `stem` column only: fewer, surer stems (hold-out 97.3% → 99.5%); every other file and column unchanged |
| New in v0.7 | `referents.parquet` only: a verb takes a carried entity only from a Greek verb's subject; the ranker also reads DictaBERT word vectors (Tanakh test 87.4% → 90.4%); new columns `referent_p_calibrated`, `other_edition_referent`, `editions_agree` |

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
| `<edition>/features.parquet` | one per word part (the verse-number rows left out): person, number, gender, state, definiteness (v0.3), stem (v0.4); CC BY 4.0 |
| `<edition>/pieces.parquet` | one per word part with letters: head, relation, semantic role, reference status, kind of referent (v0.3; **CC BY-SA 4.0**) |
| `<edition>/clause_marks.parquet` | one per clause segment: the clause marks (v0.3; **CC BY-SA 4.0**) |
| `<edition>/speech.parquet` | one per clause segment with a quotation: speaker, addressee, the addressee's number (v0.4; **CC BY-SA 4.0**) |
| `<edition>/referents.parquet` | one per pronoun, pronoun suffix and finite verb: referent, basis, antecedent (v0.5; **CC BY-SA 4.0**) |
| `<edition>/entities.parquet` | one per entity id: its kind, Hebrew type word and name (v0.4; **CC BY-SA 4.0**) |
| `<edition>/scheme/clauses.parquet` | one per clause (segments joined): parent, rule, pattern, predicate, 17 marks (v0.9; **CC BY-SA 4.0**, as all of `scheme/`) |
| `<edition>/scheme/segments.parquet` | one per clause segment: the clause it belongs to, its words, `continues` |
| `<edition>/scheme/constituents.parquet` | one per constituent of a clause: role, head, first and last word, class, preposition, semantic role, reference status |
| `<edition>/scheme/added.parquet` | one per unsaid subject: the verb, person, number, gender, the antecedent, who it is |
| `<edition>/scheme/orders.parquet` | one per order statement: a relation between two word classes, how often the dependent stands before and after, places |
| `<edition>/scheme/clause_join.parquet` | one per pair of a clause here and a clause carried from the Greek that share words (see below) |
| `<edition>/scheme/BUILD.json` | the build's counts |
| `clause-scheme.toml`, `validate_scheme.py` | the scheme: every table, column, value set and join; and the check that reads only that file |
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
| `stem` | verbs (v0.4): the stem as MACULA Hebrew names it (qal, niphal, piel, pual, hiphil, hophal, hithpael, polel, …; MACULA's own `unknown: v` kept where it has it). Its tables add keys on the verb's lexeme (Strong's number) with its form, written beginning and ending, before the other verb keys; from v0.8 only a key with the written beginning, or the lexeme alone, gives a stem (the lexeme with its form alone was right in 73-85% on the hold-out and filled mostly qal where research's Swahili check found passive and causative verbs), and the person keys give none |
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
| verb stem | 77.3% (72.1% by the Tanakh form or part alone; v0.4-v0.7: 83.8%) | 71.8% (55.9%; v0.4-v0.7: 76.3%) |
| verb person / number / gender | 96 / 96 / 96% | 96 / 93 / 94% |
| noun number / gender / state | 90 / 91 / 88% | 85 / 90 / 85% |
| adjective number / gender / state | 99 / 99 / 95% | 97 / 98 / 91% |
| pronoun person / number / gender | 98 / 99 / 98% | 100 / 100 / 91% |

Hold-out: the affix tables applied to the parts the Tanakh form lookup did fill agree with the lookup in 97-100% (`heb_scg`; verb
person 98.1%, verb stem 99.5% (v0.4-v0.7: 97.3%), noun state 98.3%) and 96-100% (`heb_mod`; verb person 96.9%, verb stem 99.3%
(v0.4-v0.7: 97.4%)). What is left: names the Tanakh lacks, nouns whose state
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

## Speakers and addressees (v0.4, mended in v0.6; `speech.parquet`, `entities.parquet`)

**Carried from the Greek, not made here.** bcv-commons' source examples (build k1) give each Hebrew word the quotation and speaker
of the Greek clause it is linked to (lexeme-aligner's word links; the Greek values are bcv-commons' speaker layers on MACULA
Greek). Each clause segment takes the value most of its linked words have. From v0.6 the addressee comes from
[bcv-commons/addressees](https://huggingface.co/datasets/bcv-commons/addressees) v0.2 by the quotation's id. One row per segment with a
quotation (`heb_scg` @SCG_SPEECH_ROWS@, `heb_mod` @MOD_SPEECH_ROWS@), keys `book, chapter, verse, seg` as in `clauses.parquet`:

| Column | |
|---|---|
| `quote` | the Greek quotation's id (`q:` + MACULA Greek's id of its first word); from v0.10 the innermost one, where the Greek has a quotation inside a quotation |
| `quote_level`, `quote_around` | v0.10: 1 for a quotation of the speaker data, 2 or 3 for one inside another, and the `quote` of the quotation around it (empty at level 1) |
| `speaker`, `addressee` | entity ids (`person:…`, `deity:…`, `group:…`; the ids of `entities.parquet`) |
| `speech_basis` | `linked` (the strict values) |
| `speech_share` | the share of the segment's linked words whose clause has this quotation |
| `addressee_basis` | how the addressees layer found the addressee on the Greek: `inquit` (named in the frame of the speech verb), `second_person` (from the speech's second-person forms), `turn` (the other side of a dialogue: the quotation answers one said to this speaker), `review` (v0.9: a review row of the layer names the Greek words that name the hearer), empty (not said). A hearer named only by a word, a key term or a place has no entity here |
| `addressee_member` | v0.6: where the Greek hearer is plural ("he said to them") and the entity lookup gave one of them, that person; not the addressee |
| `addressee_number_form` | from the Hebrew of the segment: the number of its second-person verbs and pronouns (`features.parquet`) where they all agree; `mixed`; empty where it has none |
| `addressee_number_layer`, `addressee_number_layer_basis` | v0.6: the layer's number for the whole quotation, strongest first `second_person` (most of the Greek quotation's second-person words), `inquit_word` (the word naming the hearer), `entity` (a group plural, a person or deity singular) |
| `addressee_number`, `addressee_number_basis` | v0.6: the segment's form where it is singular or plural (basis `form`), else the layer's (its basis). In v0.4 and v0.5 this was the entity's number |
| `addressee_number_agree` | the layer's number against the form, where both are given |
| `quote_model`, `speaker_model`, `addressee_model` | the values a language model chose in the reviewed speaker layer of the Greek NT clause layout (Claude Opus 5.5, review rows `nt_review.tsv`; no human check), carried the same way; null where none. Basis `model`: keep them apart from the strict columns |

**The layer's number and the Hebrew form agree in 90%** of the segments that have both (`heb_scg` 2,865 of 3,181; `heb_mod`
2,756 of 3,070). In v0.4 the entity's number agreed in 75% (1,406 of 1,862): the addressees layer gave a group's speech to one
person or to the Lord (Peter's speech in Acts 2; "he said to them" as Andrew or James). make-tanakh-research's Swahili check found
these; of the 126 segments it named, the layer now has the right number in 72 and none in 32 (the speech's "you" is mixed, as in
Matthew 5), and 22 still differ (Matthew 5-7, Acts 2 and 7). Read `addressee_number` (the form first) for a pronoun choice.

**v0.9: Peter's speech in Acts 2:14-36 is said to the crowd.** It was still marked as said to the Lord (the singular "you" of
the psalm he cites outvoted the plural "you" of his hearers, which links to nothing). A review row of bcv-commons/addressees
v0.3 names the hearers from the speech's own opening words; the row is a language model's reading of the Greek text, not checked
by a person. 86 segments of `heb_scg` and 87 of `heb_mod` change (addressee, its basis, its number); `referents.parquet` is
rebuilt on it, and 21 referents in Acts 2 change in each edition. No other quotation changes; the figures above are v0.6's.

**v0.10: speech inside speech.** The Greek clause layout v0.8 finds the quotations inside a quotation (331 in the New
Testament: from the Greek text, a verb of saying inside a quotation and the clause MACULA hangs on it, with the quotation depth
of eight translations as the second witness; its card gives the rule and how the two agree). A Hebrew clause linked to a Greek
clause inside one takes that quotation: 1,136 segments of `heb_scg` and 1,120 of `heb_mod` (`quote_level` 2 or 3). Their
`speaker` is the entity of the inner speaker's character where it has one, else empty: the master of a parable is no longer
Jesus, and 1,003 segments of `heb_scg` (995 of `heb_mod`) that carried the outer speaker now carry none. Their addressee and
its number are the inner quotation's own (bcv-commons/addressees v0.4), where its inquit or its own "you" shows one. The outer
quotation's number no longer counts the inner words, and the Greek "you" now counts the pronoun as well as the verb.
**The layer's number and the Hebrew form now agree in 95%** of the segments that have both (`heb_scg` 3,297 of 3,477;
`heb_mod` 3,177 of 3,355), against 90% before. Of the 180 segments of `heb_scg` still against, 106 follow a Greek "you" of
that number in the same verse of the same quotation: the text's own change of number (a generic singular in a speech to many,
an apostrophe, a turn to one hearer); in others the Hebrew form is the edition's own (a third person feminine that is written
like a second person masculine; an imperative where the Greek has none), or the Hebrew clause has no link to the Greek clause
of the inner quotation and stays with the outer one. That reading of what is left is a language model's, of the worst cases
only, not a person's. `referents.parquet` is rebuilt on the table: 795 referents of `heb_scg` and 695 of `heb_mod` change
(first and second persons inside the inner quotations, and third persons the ranker now reads with other quotation borders);
where a part has a linked referent, the ranker's own choice is the same in 69.4% and 68.6%, against 69.1% and 68.2%. Fewer
referents rest on the speech table (the speaker and hearer of an inner quotation are often not named as an entity; the outer
ones were given before, rightly or not), and on those the two editions agree less: 92.1% of 343 parts and 91.4% of 349, against
93.7% of 397 and 93.3% of 405. In the scheme's `added` table 348 rows of `heb_scg` and 338 of `heb_mod` change (`who` and its
basis; 80 and 85 unsaid subjects that had the outer speaker have none now). `scheme/clause_join.parquet` has the same rows in
a fixed order (the text's): the order within a carried clause used to differ from build to build.

`entities.parquet` (`ent`, `kind`, `type`, `name`, `name_basis`, `ent_basis`): the entities of k1 for the edition, with the Hebrew
type word (אָדָם, עַם, אֱלֹוהַּ, …) and name where k1 has one; `ent_basis` `model` marks an entity that only a model's mentions found, `layer` (v0.6) one that only the addressees layer names (no name given).

## Referents (v0.5, revised in v0.7; `referents.parquet`)

One row per target part (`heb_scg` @SCG_REFERENT_ROWS@, `heb_mod` @MOD_REFERENT_ROWS@): every pronoun, pronoun suffix and verb with
a person (the referent of a verb is its subject, said or not). Keys `book, chapter, verse, i, part`.

| Column | |
|---|---|
| `target` | `pron`, `sfx` (a pronoun suffix), `verb` |
| `person` | `1`, `2`, `3` (from `features.parquet`), empty where it has none |
| `referent` | an entity id of `entities.parquet` (`person:…`, `deity:…`, `group:…`, …), or a chain id `x:<edition>:<book>.<chapter>.<verse>.<i>.<part>` (the chain's first part) where no entity reaches the chain |
| `referent_basis` | `linked` (the entity carried from the Greek to this part through lexeme-aligner's links, as in source examples k1; for a verb only where the Greek word is a verb whose subject is that entity, from v0.7: a Hebrew verb linked to a Greek noun, or to a Greek verb that names a thing, no longer takes what it evokes), `speech` (a first person inside a quotation is its `speaker`, a second person its `addressee`, from `speech.parquet`, where the number fits: a plural only a group, a singular never one; on the Tanakh 91.8% and 96.7% right), `model` (the ranker's antecedent, below), `model_new` (the ranker found no antecedent: a new chain starts here) |
| `referent_p` | for `model` and `model_new`: the ranker's probability |
| `referent_p_calibrated` | for `model` and `model_new`: how often the ranker is right at that probability, measured on the Tanakh's dev and test chapters (bins of 0.1, pooled where the share would fall; v0.7) |
| `other_edition_referent`, `editions_agree` | the other edition's referent on the part the strict word links tie to the same Greek word, and whether the two are the same (both entity ids; null where not); v0.7 |
| `antecedent_i`, `antecedent_part`, `antecedent_verse` | the part that last names the referent before this one: the ranker's choice (`model`), or the last earlier part with the same referent (`linked`, `speech`); null where none within the window |
| `model_antecedent_p`, `model_referent`, `model_agree` | the ranker's own choice on every row, and where the row is `linked`, whether the ranker reaches the same entity |

**The ranker** (`python -m macula.hebrew_nt_referents`) is a small network over forms, not words: for each target it scores the
previous 40 nouns, names, pronouns and verbs within six verses, or `new`, from their class, person, number and gender
(`features.parquet`), relation and head (`pieces.parquet`), distance, clause, quotation, and how often the candidate's lexeme
occurs in the window; from v0.7 also each word's vector from [dicta-il/dictabert](https://huggingface.co/dicta-il/dictabert) (CC BY 4.0;
frozen, the unpointed words of one verse at a time), for the target and each candidate. A noun or name without number or gender
whose carried entity is one person or deity is read as singular and as the entity's sex (input only; `features.parquet` is unchanged).
It was trained on the MACULA Hebrew Tanakh's referents as source examples k1 gives them (MACULA's subject and participant
references and bcv-commons' entities). No generative language model, no BHSA, no TBTA. A model value has not been checked by hand.

On the Tanakh test chapters (2,797 targets with a known referent) it picks a right antecedent (or `new` rightly) for 90.4%
(v0.5: 87.4%): third-person suffixes 85.7%, pronouns 80.0%, verbs 85.3%; first and second persons 91-100%. The nearest earlier
candidate that agrees in person, number and gender gets 63.0% (third persons 39-49%). By probability: 95.5% at 0.9 or more (45% of
the targets), 90.7% at 0.7-0.9, 83.1% below. On the New Testament, where a part also has a carried entity and the ranker reaches an
entity, the two agree in 79.0% (`heb_scg`) and 77.0% (`heb_mod`); 83.9% and 83.0% at a probability of 0.9 or more. About 70% of the
targets end with an entity id (v0.5: 64%); the rest have a chain id.

The two editions check each other (`editions_agree`): where both have an entity on parts tied to the same Greek word, `linked`
rows agree in 99.8%, `speech` rows in 91-92% (v0.10; 93-94% before), `model` rows in 73%. A `model` row whose `editions_agree` is false is the first to doubt.

## The clause scheme (v0.9, `scheme/`)

One form for the clause level, the same for the Tanakh
([bcv-commons/tanakh-clause-scheme](https://huggingface.co/datasets/bcv-commons/tanakh-clause-scheme)) and for each Hebrew New
Testament here. `clause-scheme.toml` (version @SCHEME_VERSION@) is the whole definition: tables, columns, kinds, value sets, joins.
`python validate_scheme.py clause-scheme.toml heb_scg/scheme` checks a folder against it (needs pyarrow only).

| | `heb_scg` | `heb_mod` |
|---|---|---|
| clauses (segments joined to another) | @SCG_SCHEME_CLAUSES@ (@SCG_SCHEME_JOINED@) | @MOD_SCHEME_CLAUSES@ (@MOD_SCHEME_JOINED@) |
| constituents (per clause) | @SCG_SCHEME_CONSTITUENTS@ (@SCG_SCHEME_PER_CLAUSE@) | @MOD_SCHEME_CONSTITUENTS@ (@MOD_SCHEME_PER_CLAUSE@) |
| clauses without a constituent | @SCG_SCHEME_NO_CONSTITUENT@ | @MOD_SCHEME_NO_CONSTITUENT@ |
| unsaid subjects (with `who`) | @SCG_SCHEME_ADDED@ (@SCG_SCHEME_WHO@) | @MOD_SCHEME_ADDED@ (@MOD_SCHEME_WHO@) |
| order statements | @SCG_SCHEME_ORDERS@ | @MOD_SCHEME_ORDERS@ |
| rows of `clause_join` | @SCG_SCHEME_JOIN@ | @MOD_SCHEME_JOIN@ |

**Ids.** A clause is `cl:<edition>:<BOOK>.<chapter>.<verse>.<seg>`, `seg` being the number of its first segment in
`clauses.parquet`. A word is `scg:` (`heb_scg`) or `del:` (`heb_mod`) and eleven digits: book number (40 to 66), chapter, verse,
and the word's position `i` in `words.parquet` plus one. A part is the word id, a dot, and `part` plus one. An entity (`who`) is
an id of `entities.parquet`.

**The clause.** `clauses.parquet` of this dataset has one row per segment: a clause broken by an inserted clause is two
segments. The scheme joins them (`segments.continues` names the segment a later piece continues), so a row of
`scheme/clauses.parquet` is a whole clause. A clause begins with the word that opens it (a conjunction, a relative word). A
segment with no written word is in no clause (@SCG_SCHEME_EMPTY@ in `heb_scg`, @MOD_SCHEME_EMPTY@ in `heb_mod`: a stray Latin label of the
source text, an empty token in `words.parquet`).

**Every value has its basis** in `<column>_basis`: `derived` (by a rule from other columns of this dataset), `model` (a tagger,
with its probability in `<column>_p`), `linked` (through word links to the Greek, for `who` only). No value comes from the Greek
text except `who` where its basis says `linked`. `frame_role` is empty here (it is MACULA's frame label, filled on the Tanakh).

- `clauses`: `parent` and `depth`; `rule` (the clause's roles in order, as MACULA names clause rules) and `pattern`; `pred`, the
  predicate's word, and `pred_kind` (`v` verb, `p` nominal predicate, `none`); the marks `kind`, `force`, `polarity`, `mood`,
  `time`, `time_abs`, `aspect`, `relation`, `voice`, `negator`, `connective`, `line_kind`, `fronted`, `subject_form`,
  `transitivity`, `neg_scope`, `subject_switch`. Meaning categories are Hebrew terms; the scheme file lists each value set.
  Ten marks are those of `clause_marks.parquet`, taken from the clause's first segment; `kind`, `pattern`, `fronted`,
  `subject_form`, `neg_scope` are derived from the constituents; `transitivity`, `line_kind`, `subject_switch` are a tagger's.
- `constituents`: the clause's own parts of speech in order (`ord`): `role` (`v`, `s`, `o`, `o2`, `p`, `pp`, `adv`), `head`,
  `first`, `last`, `class`, `prep` (the preposition's lexeme), `sem_role`, `ref_status`, `ref_form`. Derived from the tree of
  `pieces.parquet` (head and relation per part), which is model output.
- `added`: a finite verb with no subject said in its clause: `verb`, `person`, `number`, `gender`, `antecedent` (the part that
  names the subject earlier, from `referents.parquet`), `who` with `who_basis` and `who_reason` (`linked`, `speech`, `model`,
  `model_new`). Unsaid objects and possessors are not made.
- `orders`: for each tree relation between two word classes, how often the dependent stands before and after its head in this
  edition, with up to three places.
- `clause_join`: which clause here shares words with which clause of the tables carried over from the Greek New Testament
  (`same`, `split`, `merged`, `partial`). Those carried tables are a local build of bcv-commons and are not published; the table
  is of use only beside them.

**How right it is.** Nothing of the scheme was checked by a person on the New Testament. Measured on the Tanakh's test
chapters, read as the New Testament is read (the taggers' own segments, parts and tree), with and without vowel points:

| | pointed (`heb_scg`'s model) | without points (`heb_mod`'s) |
|---|---|---|
| constituents found / right when given / with the right span | 90.2% / 93.3% / 87.0% | 89.8% / 92.6% / 86.5% |
| found, by role | `v` 96.4, `pp` 91.4, `s` 87.1, `adv` 85.9, `o` 85.0, `p` 71.5 | |
| segments joined to the right clause (88 joins) | 69, 87% of the joins made right | 67, 84% |
| `kind`, `fronted`, `subject_form`, `neg_scope` (rule) | 99.4%, 97.0%, 95.2%, 99.9% | |
| `pattern` (rule: every role in order right) | 80.4% | |
| `transitivity`, `line_kind`, `subject_switch` (tagger) | 91.7%, 91.9%, 80.8% | 91.3%, 91.7%, 80.7% |

The two editions are two translations of one Greek text. Where a word of each stands for the same Greek word (53,006 pairs):
a word that heads a constituent in one edition does so in both in 80.3%, and then in the same role in 84.4% (`v` 91.6%, `pp`
82.6%, `s` 82.3%, `o` 77.2%, `p` 62.0%, `adv` 54.2%). This is not a score: the translations differ in truth.

Known faults, from 13 verses read by the building agent (not a human check): a word read as a verb that is none gives a clause
a wrong predicate; some clauses have a verb and no other constituent although the words are there (the tree gives them no role);
a constituent may stand in the neighbouring clause. About 1.8% of the clauses have three words or more and no constituent.

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

Known faults of the word table found since, not mended in v0.9 (the table is unchanged, since other datasets are keyed to its
parts): a numeral the tagger read on its own can have a wrong lexeme (`שְׁנֵי` "two of" filed under `שָׁנָה` or `שָׁנִי`: about
30 words of `heb_scg`, about 50 of `heb_mod`; read `class` = `num` with the written form there); and on a few tens of verbs that the
Tanakh does not have, the verb's own ending is cut off as a pronoun suffix (`שידענו`, `הבינותם`).

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
| Argument roles, reference status, entities, clause columns, time-aspect, clause connectives, addressees, speaker layer (the training values of `pieces.parquet`, `clause_marks.parquet` and `referents.parquet`, their carried values, and `speech`, `entities`) | bcv-commons' own layers on MACULA Hebrew (their sources on their dataset cards) | CC BY-SA 4.0 |
| MACULA Greek (the `_carried` values) | Clear Bible / Biblica | CC BY 4.0 |
| Word links of the `_carried` values | bcv-commons/lexeme-aligner | CC0 1.0 |
| This analysis: `words`, `clauses`, `features` | bcv-commons | **CC BY 4.0** |
| This analysis: `pieces`, `clause_marks`, `speech`, `entities`, `referents`, everything in `scheme/` | bcv-commons | **CC BY-SA 4.0** (ShareAlike, from the training and carried values) |
| `clause-scheme.toml`, `validate_scheme.py` | bcv-commons | MIT |
| The code (bcv-query) | bcv-commons | MIT |

**Attribution** when you use this dataset:

> Hebrew New Testament Analysis (@TAG@), bcv-commons, CC BY 4.0 (`pieces`, `clause_marks`, `speech`, `entities`, `referents`, `scheme/`: CC BY-SA 4.0). Analysis trained on
> MACULA Hebrew, Clear Bible / Biblica (CC BY 4.0).
> Texts: Salkinson–Ginsburg Hebrew New Testament; Delitzsch's Hebrew New Testament (public domain).

## Feedback

Issues and requests: [bcv-commons/bcv-query](https://github.com/bcv-commons/bcv-query/issues). Please name the edition, the verse and
the word, and what you expected.
