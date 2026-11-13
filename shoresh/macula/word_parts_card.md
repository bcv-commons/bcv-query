---
license: @LICENCE_ID@
language:
  - grc
  - hbo
  - arc
pretty_name: Word Parts (Greek NT and Hebrew Bible)
tags:
  - bible
  - greek
  - hebrew
  - morphology
  - segmentation
size_categories:
  - 100K<n<1M
---

# Word Parts: Greek New Testament and Hebrew Bible

Every word of the Greek New Testament cut into its parts: preverb, augment, reduplication, stem and ending. Every word of the
Hebrew Bible in MACULA's morphemes: prefixed particles, stem, pronominal suffix. The parts of a word, joined in order, give
its printed form exactly. Each part is keyed to the MACULA word id.

What it is for:
- aligning a translation to the source by parts, not only by whole words;
- drafting a word's form from its stem and the grammatical marks of its endings;
- transliterating a name from its stem;
- looking up words that share a stem.

@ROUTE_TEXT@

| | |
|---|---|
| Version | @VERSION@ (`schema` 1) |
| Built | @BUILT@ by `shoresh/macula/build_word_parts.py --route @ROUTE@` and `release_word_parts.py` (bcv-query `@CODE@`) |
| Greek | @GRC_WORDS@ words of the Nestle 1904 New Testament (MACULA Greek), @GRC_PARTS@ parts |
| Hebrew | @HBO_WORDS@ written words of the Westminster Leningrad Codex (MACULA Hebrew), @HBO_PARTS@ parts |
| Licence | @LICENCE@ |

## Files

| file | one row per | columns |
|---|---|---|
| `data/src_part_grc.parquet` | part of a Greek word | `key` (MACULA Greek word id, 11 digits: book, chapter, verse, word), `n` (order in the word, from 1), `text`, `kind`, `features` |
| `data/src_part_hbo.parquet` | Hebrew morpheme | `key` (the written word: the first 11 digits of the morpheme ids), `n`, `token` (MACULA Hebrew's 12-digit morpheme id), `text`, `kind`, `features` (`class=` MACULA's word class) |
| `data/words_grc.parquet` | Greek word | `key`, `surface`, `lemma`, `morph` (Robinson's parse code as MACULA gives it), `group` (lemma in plain letters / principal part), `cut` (the parts joined by `\|`), `flags` |
| `exceptions_grc.tsv` | flag, lemma and principal part | the listed exceptions, with token counts and an example |
| `build.json` | | sources (with hashes or commits), code, counts |
| `SHA256SUMS` | | the sha256 of every file |

**Kinds of part:**

| `kind` | what | `features` |
|---|---|---|
| `preverb` | the prefix of a compound verb, as the form writes it (ἀπ-, ἀφ-, συμ-) | `preverb=` the preposition, in plain letters |
| `augment` | the syllabic augment ἐ- (ἠ- in ἤθελον) | `augment=syllabic` |
| `reduplication` | consonant + ε, ε, or ει | `reduplication=consonant` / `ε` / `ει` |
| `stem` | the stem | `pp=` the principal part (below); `lengthened=temporal` when a temporal augment or a vowel reduplication lengthened its first vowel. That vowel cannot be cut off. |
| `ending` | the ending | Robinson's parse code |
| `particle` | a Greek conjunction, preposition, particle or interjection, or a Hebrew prefixed particle | |
| `suffix` | a Hebrew pronominal suffix | |
| `mark` | punctuation inside a printed form, such as a dash | |

**Principal parts** (`pp`):

| `pp` | what |
|---|---|
| `P` | present and imperfect |
| `F` | future |
| `FP` | future passive |
| `A` | aorist |
| `AP` | aorist passive |
| `R` | perfect and pluperfect active |
| `RM` | perfect and pluperfect middle and passive |

## How the Greek cut is made

- **Stem and ending.** The stem is the beginning that a lexeme's forms share within one principal part (for a noun or adjective, across all its forms); the ending is what varies.
  - The endings a parse allows are learned from the lexemes with several forms in the New Testament: an ending counts when at least three lexemes show it.
  - A group's stem is a beginning shared by at least 0.6 of its forms, chosen so that the most forms have an allowed ending after it. On a tie the commoner endings win (μισθ\|ός, not μισθό\|ς), then the longer stem.
- **Suppletive lexemes** take several stems: ἐγώ with ἐμ- and ἡμ-; πολύς with πολ- and πλει-; the root aorist of καταβαίνω with βη- and βα-. A form that shares none stays whole (μου, ἦν).
- **Preverbs** are found from the lemma: the remainder is itself a New Testament verb, or an augmented form shows the augment after the preverb (ἀπ-έ-κτειναν).
  - Each form's own variant is then cut, following elision and assimilation (ἀπ- before a vowel, συμ- before a labial, ἐγ- before a velar).
  - Route b takes MorphGNT's preverb analyses instead.
- **Augment and reduplication** are read against the principal part's own base, not only the lemma:
  - εἶπον is read against εἰπεῖν and εἰπών; ἔφαγον against φαγεῖν;
  - a μι-verb's present reduplication is set aside (τί-θημι, so ἔ-θηκεν).
- **Formants stay in the stem.** The tense formants σ, θη and κ stay in the stem of their principal part: πιστεύσ\|ας, σωθήσ\|ομαι.
- **Third-declension stems.** The stem is what all forms share: αἰῶν\|ος, σαρκ\|ός, πνευμα\|τος. A nominative that does not share it is cut on its own (νὺ\|ξ) or stays whole, and is flagged.
- **Kept whole** (one `stem` part): the article; the relative pronouns ὅς, ὅστις, ὅσπερ, which are declined like the article; indeclinable words (proper names, numerals, letters); crasis forms (κἀγώ); elided forms; adverbs.

The Hebrew file only reads MACULA's morphemes. The verb's own endings (the afformatives of קָטַלְתִּי) are not cut.

## Checks

@CHECKS@

**Read by hand:** a sample of 200 words, seed 17, route a. Two cuts are wrong:
- ἀν\|έ\|β\|η should be ἀν\|έ\|βη;
- συν\|ε\|τέ\|θειντο, a minor case.

About twelve follow a convention that could be argued, among them πά\|ντα, πατ\|έρες, ζητημά\|των, θεραπεῦσ\|αι and οὐδε\|ὶς. The rest are sound.

**Flags** in `words_grc.tsv`:

| flag | what |
|---|---|
| `stem_differs` | the form does not carry its group's stem; it was cut by its ending alone |
| `ending_unlisted` | the ending was not among the learned ones for its parse |
| `suppletive_stem` | cut on one of a suppletive lexeme's several stems |
| `suppletive_alone` | a suppletive lexeme's form with no shared stem; kept whole |
| `no_cut` | the form shares no stem and has no allowed ending; kept whole |
| `article`, `relative`, `indeclinable`, `crasis`, `elided` | kept whole, for the reason named |
| `preverb_not_in_form` | the lemma's preverb is not at the head of the form (ἤνοιξεν of ἀνοίγω) |

## Known limits

- **New Testament Greek only.** The Septuagint is not cut.
- **Not cut, and listed in `exceptions_grc.tsv`:**
  - Attic reduplication (ἑώρακα, ἐλήλυθα, ἀπολώλεκα);
  - the double augment of ἀνοίγω;
  - some forms of ἀφίημι;
  - the pluperfect of οἶδα.
- **Formants are not separated.** A stem is per principal part: λυσ- for the aorist, λυ- for the present.
- **No person has reviewed all rows.** Corrections are welcome as issues on bcv-commons/bcv-query.

## Sources and licence

| source | licence | used for |
|---|---|---|
@SOURCES@

This dataset is licensed **@LICENCE@**. Please credit "Word Parts, bcv-commons (@REPO@ @VERSION@)" together with the sources above.

## Versions

- @VERSION@ (@BUILT@): first release.
- `schema` in `build.json` is the version of the file shape. It is raised only when a column is renamed, dropped or changes meaning.
