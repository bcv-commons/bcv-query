---
license: cc-by-4.0
language:
  - grc
  - hbo
pretty_name: Word Parts (Greek NT and Hebrew Bible)
tags:
  - bible
  - greek
  - hebrew
  - morphology
  - segmentation
size_categories:
  - 100K<n<1M
configs:
  - config_name: greek
    data_files: greek/parts.tsv
    sep: "\t"
  - config_name: hebrew
    data_files: hebrew/parts.tsv
    sep: "\t"
---

# Word Parts: Greek New Testament and Hebrew Bible

This dataset cuts every word of the Greek New Testament and of the Hebrew Bible into its parts. Each part has a stable id
keyed to MACULA's ids (Clear Bible). Read in order, a word's parts give its printed form exactly.

- **Greek:** preverb, augment, reduplication, stem and ending. Stems follow the grammar books.
- **Hebrew:** MACULA's own parts (prefixed particles, stem, pronominal suffix), cut once more inside: the yiqtol's person
  prefix, the verb's person and number ending, and the gender, number and state ending of nouns, adjectives and
  participles.

What it is for:
- aligning a translation to the source by parts, not only by whole words;
- keying data that belongs to a part, such as an ending, a prefix or a suffix;
- drafting a word's form from its stem and its endings;
- looking up words that share a stem.

| | |
|---|---|
| Version | v1.0 (`schema` 2), built {built} by `shoresh/macula/release_word_parts_v1.py` (bcv-query `{code}`) |
| Greek | 137,779 words of the Nestle 1904 New Testament (MACULA Greek), 220,871 parts, 12-digit ids |
| Hebrew | 469,476 MACULA parts of the Westminster Leningrad Codex (MACULA Hebrew), 578,786 parts, 13-digit ids |
| Licence | CC BY 4.0 |

**The id standard** is in [`ID-STANDARD.md`](ID-STANDARD.md): the shape of the ids, the kinds of part, the letter spans,
and the rules for how a later release may change them. In short:
- **Greek:** a part id is MACULA's word id (11 digits, without the `n`) followed by one part digit: `400010010011`.
- **Hebrew:** a part id is MACULA's 12-digit part id followed by one sub-part digit: `0100100100311` אֱלֹהִ, `0100100100312`
  ים. Where a MACULA part is not cut, its sub-part is 1. MACULA's id is therefore always the first 12 digits, so data keyed
  to MACULA Hebrew ids joins unchanged.

## Files

| file | one row per | columns |
|---|---|---|
| `greek/parts.tsv` | part of a Greek word | `part_id`, `word_id`, `n` (order in the word, from 1), `start`, `end` (letters within the word), `text`, `kind`, `features` |
| `greek/words.tsv` | Greek word | `word_id`, `lead`, `surface`, `trail` (punctuation), `lemma`, `morph` (Robinson's code as MACULA gives it), `basis` (which source gave the stem), `cut` (the parts joined by `\|`), `flags` |
| `hebrew/parts.tsv` | piece of a MACULA Hebrew part | `part_id`, `macula_id` (MACULA's part id), `word_id` (its first 11 digits), `n` (order in the MACULA part, from 1), `start`, `end` (letters within the MACULA part), `text`, `kind`, `features` (MACULA's morph code on prefixes, endings and fused pieces) |
| `*/checks.md` | | acceptance figures |
| `greek/sample_200.tsv`, `greek/sample_review.md`; `hebrew/sample_200.tsv`, `hebrew/review.md` | | a seeded sample of 200, read by hand, and the review |
| `greek/recheck/` | | the Greek stems compared with greek-inflexion (verbs) and Dodson (nouns) |
| `hebrew/checks_bhsa.md` | | the Hebrew pieces measured against BHSA's morpheme marks: counts only |
| `*/churn-from-v0.1/` | | `id_map.tsv` (v0.1 part id -> the v1.0 part ids sharing a letter with it, and the kind of change), `changed_words.tsv`, `churn.md` |
| `*/build.json`, `build.json` | | sources with commits or hashes, code, counts |
| `LICENSES/` | | the licence notices of greek-inflexion (MIT) and Dodson's lexicon (CC0) |
| `SHA256SUMS` | | the sha256 of every file |

A letter is a base character with its combining marks. Spans count from 0, the end is not included, and punctuation is
not counted.

**Kinds of part:**

| `kind` | language | what |
|---|---|---|
| `preverb` | Greek | the prefix of a compound verb, as the form writes it (ἀπ-, ἀφ-, συμ-); `features` `preverb=` |
| `augment` | Greek | the syllabic augment ἐ-; a temporal augment (a lengthened vowel) is never cut |
| `reduplication` | Greek | consonant + ε, ε or ει |
| `prefix` | Hebrew | the yiqtol's person prefix א ת י נ |
| `stem` | both | the stem |
| `ending` | both | Greek: the ending, with Robinson's code. Hebrew: the verb's person / number ending; the gender / number / state ending of nouns, adjectives and participles |
| `fused` | both | stem and ending merged in the letters, one part carrying the parse (Greek ποιῶ, ὄνομα; Hebrew כָּרַתִּי, where the ending's letter is the root's last letter written once) |
| `particle` | both | a Greek function word (one part), a Hebrew prefixed particle |
| `suffix` | Hebrew | a pronominal suffix (MACULA's) |

**Not cut, on purpose.**
- **Hebrew:**
  - the stem formatives: hiphil ה-, niphal נ-, hitpael הִתְ-, and the participle's מְ-;
  - the infinitive absolute;
  - proper nouns, pronouns and particles;
  - the Aramaic parts (5,503), which a later release may cut.
- **Greek:**
  - the article and the relative pronouns;
  - indeclinable words, crasis forms, elided forms and adverbs.

## How the cut is made

**Greek.** The stems follow the grammar books:
- greek-inflexion's stems for verbs;
- Dodson's lexicon for nouns and adjectives;
- a short written list for a few closed-class words.

Where no source stem fits the form, our own rule from v0.1 is used. The `basis` column of `greek/words.tsv` says which
source gave each word's stem.

**Hebrew.** The cut follows the grammar books' tables, written out in `shoresh/macula/build_hebrew_parts.py` and applied
to MACULA's morph code for each part. A cut never falls inside a letter, since a vowel sign belongs to the letter it is
written on. Two rules decide the harder cases:
- An ending begins with ו or י only when that letter is a vowel letter.
- A feminine ת is an ending unless the root in BDB's root groups ends in ת: בַּ|ת, דֶּלֶ|ת, but שַׁבָּת stays whole.

## Checks

- **Greek:**
  - 0 rebuild failures (lead + parts + trail against the surface), 0 duplicate ids, at most 5 parts per word;
  - the same stem boundary as greek-inflexion in 98.5% of the comparable verbs, and as Dodson in 94.7% of the comparable
    nouns. Most of the remaining nouns are Ἰησοῦς, which we cut by our rule on purpose.
- **Hebrew:**
  - 0 rebuild failures, 0 duplicate ids;
  - against BHSA's morpheme marks, as written: the prefix has the same letters in 100.0% of 272,468 compared parts, and
    the ending in 98.9% of 272,078. The deliberate differences are counted in `hebrew/checks_bhsa.md` and explained in
    `hebrew/review.md`.
- **Both:** the seeded sample of 200 per language was read by hand.

## Changes from v0.1

Every v0.1 part id maps onto v1.0 through `id_map.tsv`, by the letters each part covers.
- **Greek:** {churn_greek}
- **Hebrew:** {churn_hebrew} In v0.1 a Hebrew part was MACULA's part (12 digits). In v1.0 a part that is not cut is that
  id followed by 1, which the map counts as `same`. A part that is cut is `split`. The 117 fused parts stay one piece.

v0.1 stays downloadable at tag `v0.1`. Its sister dataset `bcv-commons/word-parts-sa` (route b, CC BY-SA 4.0) is retired
with this release: v1.0 takes its stems from greek-inflexion (MIT) and Dodson (public domain) instead of MorphGNT and
Morpheus, so the share-alike version is no longer needed.

## Stability

- A release is frozen: pin a tag and its revision.
- Word ids and MACULA Hebrew part ids never change.
- A correction comes only as a new release, which ships an `id_map.tsv` from the previous one.

The full rules are in `ID-STANDARD.md`.

## Licence and credit

CC BY 4.0. Credit:
- MACULA Greek and MACULA Hebrew Linguistic Datasets, © 2022 by Clear Bible, Inc (CC BY 4.0),
  https://github.com/Clear-Bible/macula-greek, https://github.com/Clear-Bible/macula-hebrew;
- greek-inflexion, © James Tauber (MIT; the notice is in `LICENSES/`);
- Dodson's Greek lexicon (public domain, via biblicalhumanities, CC0);
- BDB's root groups (public domain, via OpenScriptures/HebrewLexicon, CC BY 4.0).

BHSA (CC BY-NC 4.0) was read only to measure the Hebrew cut. No BHSA value is in the data, and `hebrew/checks_bhsa.md`
holds counts only.
