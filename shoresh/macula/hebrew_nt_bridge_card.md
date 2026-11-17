---
license: cc-by-4.0
language:
  - he
  - grc
pretty_name: Hebrew NT Bridge (Greek NT lexeme to Hebrew lexeme)
tags:
  - bible
  - hebrew
  - greek
  - new-testament
  - lexicon
  - word-alignment
  - translation
size_categories:
  - 100K<n<1M
configs:
  - config_name: pairs
    default: true
    data_files:
      - split: heb_scg
        path: pairs/heb_scg.tsv
      - split: heb_mod
        path: pairs/heb_mod.tsv
    sep: "\t"
  - config_name: links
    data_files:
      - split: heb_scg
        path: links/heb_scg.parquet
      - split: heb_mod
        path: links/heb_mod.parquet
  - config_name: quotes
    data_files:
      - split: heb_scg
        path: quotes/heb_scg.tsv
      - split: heb_mod
        path: quotes/heb_mod.tsv
    sep: "\t"
---

# Hebrew NT Bridge

Which Hebrew word renders which Greek word of the New Testament, read from two Hebrew translations of it: Salkinson–Ginsburg
(`heb_scg`) and Delitzsch (`heb_mod`). Every Greek word is a word of MACULA Greek (Nestle 1904) and every Hebrew word part carries
the lexeme MACULA Hebrew uses for the Tanakh, so the two Testaments meet on the same keys.

It is the counterpart of a Septuagint bridge. The Septuagint goes from a Hebrew source to its Greek translation; this goes from the
Greek source to a Hebrew translation, in the Greek of the New Testament itself.

| | |
|---|---|
| Release | **@TAG@**, built @BUILT@ from bcv-query `@COMMIT@` |
| Editions | `heb_scg`: Salkinson–Ginsburg (1885/86), pointed. `heb_mod`: Delitzsch, as eBible's "Modern Hebrew Bible" has it, without vowel points |
| Greek | MACULA Greek, Nestle 1904: 137,779 words, of which @SCG_CONTENT@ nouns, verbs and adjectives |

**This is machine-made and has not been checked by hand.** The links are word alignments by lexeme-aligner's method (its
statistical chain by word parts, then the Jev model of TypeSafe by verse or clause). The Hebrew lexemes come from a tagger trained
on MACULA Hebrew. A model's review of every Greek noun, verb and adjective, for both translations, is a dataset of its own:
[hebrew-nt-review-model](https://huggingface.co/datasets/bcv-commons/hebrew-nt-review-model). See *Quality* before relying on a
single link.

## Files

| File | Rows |
|---|---|
| `pairs/<edition>.tsv` | one per pair of a Hebrew and a Greek lexeme seen at least 3 times |
| `links/<edition>.parquet` | one per Greek word and Hebrew word part it is linked to |
| `quotes/<edition>.tsv` | one per verse of the translation and Tanakh verse it follows |
| `report.json` | the figures on this card, and more |
| `SHA256SUMS` | SHA-256 of every file |

## The pairs

| Column | |
|---|---|
| `hebrew_strong` | the Hebrew lexeme: Strong's number as MACULA Hebrew gives it, zero-padded, homonym letter dropped (`H0559`) |
| `greek_strong` | the Greek lexeme: Strong's number of MACULA Greek (`G3004`) |
| `tier` | the edition |
| `count` | Greek words of this lexeme linked to a part of this Hebrew lexeme (links of class `edited-wide` are not counted) |
| `kept` | of them, links of class `kept`, the safest class |
| `score` | `count` divided by all counted links of the Greek lexeme: how often the translator chose this Hebrew word for it |
| `quoted` | of `count`, links to a Hebrew word inside a stretch that follows a Tanakh verse (see *Verses that follow the Tanakh*). `count` minus `quoted` is the evidence that does not lean on the Tanakh's own wording |

Rows are sorted by Greek lexeme, then by count. A Greek word rendered by two Hebrew words (ἀρχιερεύς by הַכֹּהֵן הַגָּדוֹל) counts for both.

| | `heb_scg` | `heb_mod` |
|---|---|---|
| Links from | Greek word ids, with classes (`@SCG_FORM@`) | Greek word ids, with classes (`@MOD_FORM@`) |
| Greek nouns, verbs and adjectives linked to a Hebrew word | @SCG_LINKED@ | @MOD_LINKED@ |
| of them on a Hebrew lexeme of the Tanakh | @SCG_LEXEME@ | @MOD_LEXEME@ |
| Pairs (count ≥ 3) | @SCG_PAIRS@ | @MOD_PAIRS@ |
| Hebrew lexemes / Greek lexemes in them | @SCG_HEB@ / @SCG_GRC@ | @MOD_HEB@ / @MOD_GRC@ |

## The links

| Column | |
|---|---|
| `edition` | `heb_scg` or `heb_mod` |
| `greek_id` | the word's id in the MACULA Greek trees (`n40001001001` = Matthew 1:1, word 1) |
| `greek_strong`, `greek_lemma`, `greek_class` | MACULA Greek's lexeme, lemma and word class |
| `book`, `chapter`, `verse` | the verse of the Hebrew edition |
| `i`, `part` | the Hebrew word in the verse and the part in the word, as in [hebrew-nt-analysis](https://huggingface.co/datasets/bcv-commons/hebrew-nt-analysis) |
| `hebrew_strong`, `hebrew_lemma`, `hebrew_class` | the part's lexeme (empty for a name or a word the Tanakh lacks), lemma and class |
| `source` | where the part's analysis comes from: `macula` (the form occurs in the Tanakh with one analysis) or `model` (the tagger) |
| `link` | the aligner's class: `kept`, `inside`, `part`, `edited`, `edited-wide`; `compact` where the links have no classes |
| `form` | `by-id` (links by Greek word id to a word or part) or `compact` (links from the verse's content words to whole words) |
| `tanakh` | the Tanakh verse whose wording the Hebrew word follows (`ISA 9:1`, Hebrew verse numbers), empty elsewhere |

A link to a whole Hebrew word is resolved to parts by rule: a word of one part is that part; for a Greek noun, verb, adjective,
adverb or numeral, the word's parts of those classes; for a Greek function word, the parts of the same family (conjunction,
preposition, article, pronoun, particle). `links` has @SCG_ROWS@ rows for `heb_scg` and @MOD_ROWS@ for `heb_mod`.

## Verses that follow the Tanakh

The translators knew the Hebrew Bible. Where the New Testament quotes it, they could write the Hebrew verse instead of translating
the Greek, and elsewhere they borrowed its phrases (Salkinson's אוּד מֻצָּל מֵאֵשׁ in 1 Corinthians 3:15 is Zechariah 3:2). In such a
stretch the Hebrew word is the Tanakh's choice, not the translator's answer to the Greek word, so a link there does not count as a
second witness beside the Septuagint. These stretches are marked.

They are found on the Hebrew side alone, with no list of quotations. The nouns, verbs, adjectives, adverbs and numerals of a verse
that have a Tanakh lexeme are compared, as a sequence, with those of every Tanakh verse (MACULA Hebrew). What the two have in common
in the same order is kept where it is a stretch of two lexemes or more. A stretch weighs the sum, over its lexemes, of
ln(Tanakh verses / Tanakh verses with the lexeme): a lexeme found in one verse of 150 weighs 5. A pair of verses is listed in `quotes`
from weight @Q_LIST@, and its stretches are marked in `links` and counted in `quoted` from weight @Q_MARK@.

| `quotes` column | |
|---|---|
| `nt_ref` | the verse of the translation (`MAT 4:16`) |
| `tanakh_ref` | the Tanakh verse, in MACULA Hebrew's (the Hebrew) verse numbers (`ISA 9:1`) |
| `weight` | the weight of the shared stretches |
| `lexemes`, `longest` | the lexemes in them, and in the longest one |

| | `heb_scg` | `heb_mod` |
|---|---|---|
| Pairs of verses listed (weight ≥ @Q_LIST@) | @SCG_Q_LISTED@ | @MOD_Q_LISTED@ |
| Verses with a marked stretch (weight ≥ @Q_MARK@) | @SCG_Q_VERSES@ | @MOD_Q_VERSES@ |
| Hebrew word parts in the marked stretches | @SCG_Q_PARTS@ | @MOD_Q_PARTS@ |
| Counted links to them | @SCG_Q_LINKS@ | @MOD_Q_LINKS@ |
| Pairs left with fewer than 3 links without them | @SCG_Q_LOST@ | @MOD_Q_LOST@ |
| Content links on a pair the Septuagint bridge has: inside / outside the marked stretches | @SCG_Q_IN@ / @SCG_Q_OUT@ | @MOD_Q_IN@ / @MOD_Q_OUT@ |

@Q_BOTH@ verses are marked in both translations, @Q_EITHER@ in at least one. The last row is the check the mark allows: inside a
marked stretch the Hebrew is the Tanakh's own wording, which the Septuagint translated, and there the Septuagint's pairs fit more often.

How far to trust the weight, on `heb_scg`: a list of quotations made another way (from the Greek the New Testament shares with the
Septuagint) has the same book and chapter for 107 of the 122 verses of weight 25 and more, for 53 of 104 between 20 and 25, and for
59 of 270 between 16 and 20. Read by sample (14 verses per band, by a model, not a person): from 25 nearly all are quotations;
between 20 and 25 quotations and borrowed phrases; between 16 and 20 about half are phrases any Hebrew text shares (numbers,
"eat and drink"). Matthew's genealogy is marked too: it follows Ruth 4 and 1 Chronicles 2 name by name.

Not found: short quotations in common words (Hebrews 1:5 from Psalm 2:7; John 19:37 from Zechariah 12:10), and a quotation the
tagger read wrongly, which is more often the case in `heb_mod`. A quotation that runs over two Tanakh verses is weighed verse by verse.

## Quality

**The links.** For `heb_scg` they are bcv-commons/alignments-by-id (`@BY_ID@`), whose card gives a check per class: `kept` 25 of
25 right, `inside` 21 of 25, `part` 21 of 25, `edited` 25 of 39, `edited-wide` 17 of 36. For `heb_mod` (since v0.2) they are made the
same way: lexeme-aligner's own alignments-by-id builder, run by make-tanakh-research on 2026-10-31 on its alignment of Delitzsch
(the statistical chain by word parts, then Jev v4 by clause; USD 5.61) and handed over to bcv-query, its parts mapped onto
hebrew-nt-analysis v0.2 (141 words split differently; 10 links moved). Function words are linked too. v0.1 had only the coarser
form (bcv-commons/compact-alignments, `@COMPACT@`: nouns, verbs and adjectives, whole words); on `heb_mod`, of @MODCAL_N@ Greek
content words that reach a Hebrew lexeme by both forms, @MODCAL_SAME@ reach the same one (on `heb_scg`, @CAL_N@ and @CAL_SAME@).

**Function words** (articles, prepositions, conjunctions, pronouns, particles) were checked blind on 2026-11-17: 40 Greek words per
class and translation, one per verse, judged by a model (Claude Opus 5.5, not a person) from the two verses without seeing the link,
then compared with it. Right = the same Hebrew parts; partial = an overlap:

| Class | `heb_scg` right / + partial | `heb_mod` right / + partial |
|---|---|---|
| article | 48% / 50% | 40% / 48% |
| preposition | 60% / 80% | 57% / 88% |
| conjunction | 62% / 75% | 60% / 82% |
| pronoun | 78% / 88% | 75% / 85% |
| particle | 62% / 80% | 57% / 78% |

Most misses are links to the whole Hebrew word or to the next word, and Greek articles left unlinked where the Hebrew has ה. Use
function-word links with care; the content-word links are the ones the review dataset checks.

**The Hebrew lexemes.** The New Testament has no reference analysis. On Tanakh text the tagger was not trained on, with the same
lookup of known forms: see the card of hebrew-nt-analysis (pointed text for `heb_scg`, unpointed for `heb_mod`, which is weaker).

**The two translations against each other.** Of @AGREE_N@ Greek content words that reach a Hebrew lexeme in both, @AGREE_SAME@ reach
the same one, and @AGREE_COMMON@ have a lexeme in common. They are two translators' choices, so a difference is not an error.

**Against the Septuagint.** Compared with the pairs of the Septuagint bridge (MACULA Hebrew's word links to the Septuagint, and
verse co-occurrence with GLAUx):

| | `heb_scg` | `heb_mod` |
|---|---|---|
| Pairs the Septuagint bridge also has | @SCG_IN_LXX@ (@SCG_IN_LXX_SHARE@) | @MOD_IN_LXX@ (@MOD_IN_LXX_SHARE@) |
| Share of the links that lie on those pairs | @SCG_IN_LXX_LINKS@ | @MOD_IN_LXX_LINKS@ |
| Pairs the Septuagint bridge lacks | @SCG_NEW@ | @MOD_NEW@ |
| Greek NT lexemes with no Septuagint pair that gain a Hebrew lexeme | @SCG_NEW_GRC@ (@SCG_NEW_GRC_WORDS@ NT words) | @MOD_NEW_GRC@ (@MOD_NEW_GRC_WORDS@ NT words) |
| Hebrew lexemes with no Septuagint pair that gain a Greek lexeme | @SCG_NEW_HEB@ | @MOD_NEW_HEB@ |

**Known limits.**

- The translators knew the Hebrew Bible and the tradition behind the New Testament's Greek. Agreement with the Septuagint bridge is
  therefore not independent confirmation, also outside the marked stretches.
- Both translations follow the Textus Receptus; the Greek ids are Nestle 1904. Greek words the translation's base lacks have no link.
- The `heb_mod` text has verses whose boundary is lost or moved (10 verses with no text, their words in the verse before). Links in
  such verses are wrong or missing. The text is used as the source gives it.
- A pair with a low count can be a wrong link. Filter on `count`, `score`, and for `heb_scg` on `kept`.

## Sources and licence

| Part | Source | Licence |
|---|---|---|
| Greek words | MACULA Greek, Nestle 1904 (Clear Bible / Biblica) | CC BY 4.0 |
| Tanakh lexemes, for the mark | MACULA Hebrew (Clear Bible / Biblica) | CC BY 4.0 |
| Word links | `heb_scg`: bcv-commons/alignments-by-id (`@BY_ID@`), by lexeme-aligner. `heb_mod`: lexeme-aligner's method and builder, run by make-tanakh-research, handed over to bcv-query. Compared with bcv-commons/compact-alignments (`@COMPACT@`) | CC0 1.0 (the aligner's); this dataset CC BY 4.0 |
| Hebrew word parts and lexemes | bcv-commons/hebrew-nt-analysis, trained on MACULA Hebrew (Clear Bible / Biblica) | CC BY 4.0 |
| Hebrew texts | Salkinson–Ginsburg; Delitzsch (eBible "Modern Hebrew Bible"), via bible.helloao.org, by the route bcv-commons/bibles names | public domain |
| This dataset | bcv-commons | **CC BY 4.0** |
| The code (bcv-query, `macula/build_hebrew_nt_bridge.py`) | bcv-commons | MIT |

The files hold no verse text: ids, positions, references, lemmas, lexeme numbers and classes.

**Attribution** when you use this dataset:

> Hebrew NT Bridge (@TAG@), bcv-commons, CC BY 4.0. Greek: MACULA Greek, Clear Bible / Biblica (CC BY 4.0). Hebrew lexemes: analysis
> trained on MACULA Hebrew, Clear Bible / Biblica (CC BY 4.0). Word links: lexeme-aligner (CC0).

## Feedback

Issues and requests: [bcv-commons/bcv-query](https://github.com/bcv-commons/bcv-query/issues). Please name the edition, the verse and
the word, and what you expected.

## Versions

- v0.1 (2026-11-16): both translations; `heb_mod` from the compact form.
- v0.2: `heb_mod` by Greek word id, with classes, word parts and function words (handed over by make-tanakh-research);
  `heb_scg` read from alignments-by-id v1.1 (its files are the same as v1.0's); the function-word check.
