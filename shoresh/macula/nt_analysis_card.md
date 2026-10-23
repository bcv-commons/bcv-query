---
license: cc-by-4.0
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
---

# Hebrew New Testament Analysis

Hebrew translations of the New Testament, analysed word by word as MACULA Hebrew analyses the Old Testament. Each word is split
into its parts (prefixes and suffixes are parts of their own), and each part has a class, a lemma, a MACULA lexeme id and a Strong's
number. Each verse is also divided into clause segments, with their depth and parent inside the verse. It is meant for aligning a
Hebrew New Testament with the Greek, for lexical study across the two Testaments, and as a Hebrew reading of the New Testament's
clause structure.

| | |
|---|---|
| Release | **@TAG@**, built @BUILT@ from bcv-query `@COMMIT@` |
| Editions | `heb_scg`: Salkinson–Ginsburg (1885/86) |
| Size | @WORDS@ words, @PARTS@ word parts, @SEGMENTS@ clause segments |

**Most of this is model output.** The New Testament has no MACULA analysis. Words whose form occurs in MACULA's Old Testament with
one near-unanimous analysis take MACULA's own (`source = "macula"`, @MACULA_WORDS@ words, @MACULA_SHARE@). The rest, @MODEL_WORDS@
words, and every clause segment come from a tagger trained on MACULA Hebrew (`source = "model"`). It has not yet been checked by
hand on the New Testament: see *Quality*.

## Files

| File | Rows |
|---|---|
| `heb_scg/words.parquet` | one per word part |
| `heb_scg/clauses.parquet` | one per clause segment |
| `heb_scg/manifest.json` | per book: the text fingerprint, verse and word counts; the model's SHA-256; tokenizer and verse-text versions |
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
| `word` | the word with its vowel points |
| `text` | the part with its points. Concatenating the parts gives `word`. The article after a preposition is a part without letters (`""`), as in MACULA: בַּמָּשִׁיחַ is ב + the article + מָּשִׁיחַ |
| `class` | MACULA word class: noun, verb, prep, cj, art, pron, adj, adv, num, rel, ptcl, ij, om (object marker), x; `verse-number` for the verse number some editions carry at the start of the verse text (Salkinson: "א", "ב", … "טו"), which is not part of the text |
| `lemma` | MACULA's lemma. Where no lemma is given (`lexeme` empty), the part's own letters, unpointed |
| `lexeme` | MACULA lexeme id (`hbo:0559`); empty for a name or word MACULA does not have, and where no known lemma fits the letters |
| `strong` | Strong's number as MACULA gives it (`0559`, `3807a`) |
| `role` | MACULA role, where the part heads one (`v`, `s`, `o`, `p`, `adv`, …) |
| `source` | `macula`: the analysis of this form in MACULA's Old Testament (at least 90% of its occurrences analysed alike); `model`: the tagger's |
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

## How it was made

The tagger (`python -m macula.clause_tagger` in [bcv-query](https://github.com/bcv-commons/bcv-query)) reads a verse with a Hebrew
BERT ([dicta-il/dictabert](https://huggingface.co/dicta-il/dictabert), CC BY 4.0), whose tokenizer drops the vowel points, and with a
character channel that reads each word with its points. It was trained on MACULA Hebrew's Old Testament (commit `@MACULA_COMMIT@`): the
words, their parts, classes, lemmas and roles, MACULA's verb forms, and the clause segments, depth, parents, clause rules and
attachment kinds of MACULA's trees as the clause layout reads them. No BHSA data, and no English, went in. A lemma has to fit the
part: among the model's best lemmas the one whose strong consonants (not א ה ו י נ) the part carries most fully; where none
explains a part of three or more such consonants by more than one, no lemma is given. The model file (SHA-256 `@MODEL_SHA@`) is not
part of this release.

## Quality

Measured on 856 Old Testament verses the tagger was not trained on (Gen 37–45, Ruth, Jonah, 1 Sam 1–10, Deut 5–11; narrative and
discourse, the closest Old Testament match to a New Testament in this style), against MACULA, with the same lookup of known forms
as here (from the training books only):

| | All words | Forms not in the training books (12%) |
|---|---|---|
| Split into parts right | 97.9% | 82.7% |
| Class (rightly split words) | 99.0% | 95.0% |
| Lemma (rightly split words) | 95.3% | 66.3% |
| Lexeme given / right when given | | 86.7% of parts / 76.5% |

| Clauses | |
|---|---|
| Segment boundaries between words (F1) | 94.9% |
| Segments reproduced exactly | 88.6% |
| Depth in the verse, on exactly matched segments | 84.4% |
| Parent in the verse, where there is one (664 segments) | 89.3% |
| Verb found / verb form / person | 99.1% (recall) / 96.0% / 97.6% |

For comparison, a modern-Hebrew parser (Parsan, DictaBERT-based) on the same verses: segment boundaries 77.1%, segments exact 56.3%,
verb form 92.5%.

The forms not in the training books are the closest stand-in for the New Testament's own words (names, New Testament vocabulary,
new prefixed forms); on them expect the lower column. The New Testament has not been scored, since it has no reference analysis. To
favour precision, filter on `source`, `p_split` and an empty `lexeme`.

## Sources and licence

| Part | Source | Licence |
|---|---|---|
| Salkinson–Ginsburg Hebrew New Testament | via [bible.helloao.org](https://bible.helloao.org) (`heb_scg`), from eBible.org (`hebsg`) | public domain |
| Word parts, classes, lemmas, lexemes, verb forms, clauses (training data and the forms looked up) | MACULA Hebrew (Clear Bible / Biblica), `WLC/lowfat`, commit `@MACULA_COMMIT@` | CC BY 4.0 |
| Base model | dicta-il/dictabert | CC BY 4.0 |
| Verse text and words | bcv-commons/bibles verse-text @VERSE_TEXT@ | CC0 1.0 |
| This analysis | bcv-commons | **CC BY 4.0** |
| The code (bcv-query) | bcv-commons | MIT |

**Attribution** when you use this dataset:

> Hebrew New Testament Analysis (@TAG@), bcv-commons, CC BY 4.0. Analysis trained on MACULA Hebrew, Clear Bible / Biblica (CC BY 4.0).
> Text: Salkinson–Ginsburg Hebrew New Testament (public domain).

## Feedback

Issues and requests: [bcv-commons/bcv-query](https://github.com/bcv-commons/bcv-query/issues). Please name the edition, the verse and
the word, and what you expected.
