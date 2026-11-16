# hebrew_nt_bridge — Greek NT lexeme → Hebrew lexeme, from the Hebrew translations of the NT

The Septuagint bridge (`../lxx_bridge_tiers`) goes from a Hebrew source to its Greek translation. These files go the other way:
the Greek NT is the source, and a Hebrew translation of it says which Hebrew word a translator chose for each Greek word. One
file per translation:

| file | translation | links from | pairs (count ≥ 3) | Hebrew / Greek lexemes |
|---|---|---|---|---|
| `heb_scg.tsv` | Salkinson–Ginsburg (1885/86), pointed | lexeme-aligner's links by Greek word id, with classes | 3,209 | 1,154 / 1,557 |
| `heb_mod.tsv` | Delitzsch, as eBible's "Modern Hebrew Bible" has it, unpointed | lexeme-aligner's compact links (content words, whole tokens) | 2,485 | 1,100 / 1,505 |

Columns: `hebrew_strong, greek_strong, tier, count, kept, score, quoted`. Codes are zero-padded as in the Septuagint tiers (`H0559`,
`G3004`); the Hebrew key drops the homonym letter, as they do. Rows are sorted by Greek lexeme, then by count.

- `count`: Greek words of the lexeme linked to a part of the Hebrew lexeme. Links of class `edited-wide` are not counted.
- `kept`: of them, links of the aligner's safest class. Empty for `heb_mod`, whose links have no classes.
- `score`: `count` / all counted links of the Greek lexeme = P(hebrew | greek), the direction of translation. (The Septuagint
  tier `macula` has P(greek | hebrew): there Hebrew is the source.)
- `quoted`: of `count`, links to a Hebrew word inside a stretch that follows a Tanakh verse (below). `count` − `quoted` is the
  evidence that does not lean on the Tanakh's own wording.

The two files are not like for like in the function words: `heb_scg`'s links cover every Greek word, `heb_mod`'s only nouns,
verbs and adjectives. On those alone, `heb_scg` has 2,337 pairs and `heb_mod` 2,482.

## How a pair is made

1. The Greek word: MACULA Greek (Nestle 1904), its id, lemma and Strong's number.
2. The link: lexeme-aligner's alignment of the edition, read from its published datasets at a pinned revision
   (bcv-commons/alignments-by-id `v1.0` for `heb_scg`; bcv-commons/compact-alignments `11583082` for `heb_mod`, which has no by-id
   form). A file is only read when its name carries the fingerprint of the text our analysis was made on.
3. The Hebrew word part and its lexeme: our analysis of the edition (bcv-commons/hebrew-nt-analysis; `macula.clause_tagger`).
4. A link to a whole Hebrew word is resolved to parts by rule: a word of one part is that part; for a Greek noun, verb, adjective,
   adverb or numeral, the word's parts of those classes; for a Greek function word, the parts of the same family.

Built by `shoresh/macula/build_hebrew_nt_bridge.py`. The word-level table (one row per Greek word and Hebrew part) is a build
output, `shoresh/macula/data/hebrew-nt-bridge/<edition>/links.parquet`, packaged by `macula/release_hebrew_nt_bridge.py`.

## Verses that follow the Tanakh (`quotes/<edition>.tsv`, the column `quoted`)

Where the NT quotes the Hebrew Bible the translators could write the Hebrew verse instead of translating the Greek, and elsewhere
they borrowed its phrases (Salkinson's אוּד מֻצָּל מֵאֵשׁ in 1CO 3:15 is ZEC 3:2). There the Hebrew word is the Tanakh's choice, so the
link is no second witness beside the Septuagint.

- **Rule**, on the Hebrew side alone, with no list of quotations: a verse's nouns, verbs, adjectives, adverbs and numerals with a
  Tanakh lexeme are compared, as a sequence, with those of every Tanakh verse (MACULA Hebrew). What they share in the same order
  (difflib) counts where it is a stretch of two lexemes or more. Weight: the sum over those lexemes of
  ln(Tanakh verses / Tanakh verses with the lexeme). Listed from weight 16; marked (links' `tanakh`, pairs' `quoted`) from 20.
- **`quotes/<edition>.tsv`**: `nt_ref, tanakh_ref, weight, lexemes, longest`, in the order of the text. `tanakh_ref` has MACULA
  Hebrew's (the Hebrew) verse numbers.

| | `heb_scg` | `heb_mod` |
|---|---|---|
| Pairs of verses listed | 739 | 559 |
| NT verses with a marked stretch | 226 | 179 |
| Hebrew word parts in them | 1,450 | 1,181 |
| Counted links to them | 1,302 | 983 |
| Pairs left with fewer than 3 links without them | 68 | 41 |
| Content links on a Septuagint pair: inside / outside the marked stretches | 80.1% / 65.8% | 79.5% / 63.7% |

- 156 verses are marked in both translations, 249 in at least one.
- **Check of the weight** against `../ot_nt_quotations` (made another way, from the Greek the NT shares with the Septuagint; only
  counted, not read into the data): on `heb_scg` it has the same book and chapter (within one) for 107 of 122 verses of weight ≥ 25,
  53 of 104 at 20-25, 59 of 270 at 16-20. A model's reading of 14 verses per band: from 25 nearly all quotations; 20-25 quotations
  and borrowed phrases; 16-20 about half are phrases any Hebrew text shares.
- **Not found:** short quotations in common words (HEB 1:5 from PSA 2:7; JHN 19:37 from ZEC 12:10); quotations the tagger read
  wrongly (more often in `heb_mod`); a quotation over two Tanakh verses is weighed verse by verse.
- This list is CC BY 4.0 (MACULA only), where `../ot_nt_quotations` is CC BY-SA (GLAUx). The two answer different questions: that
  one says where the NT's Greek follows the Septuagint, this one where a Hebrew translation follows the Hebrew Bible.

## Figures (2026-11-16; all in `report.json`)

| | `heb_scg` | `heb_mod` |
|---|---|---|
| Greek nouns, verbs and adjectives (of 65,264) linked to a Hebrew word | 61,542 | 62,057 |
| of them on a Hebrew lexeme of the Tanakh | 51,196 | 56,527 |
| Pairs the Septuagint tiers also have | 1,578 (49.2%) | 1,082 (43.5%) |
| Share of the links that lie on those pairs | 86.5% | 79.7% |
| Pairs the Septuagint tiers lack | 1,631 | 1,403 |
| Greek NT lexemes with no Septuagint pair that gain a Hebrew lexeme | 448 (7,702 NT words) | 478 (6,951 NT words) |
| Hebrew lexemes with no Septuagint pair that gain a Greek lexeme | 118 | 132 |

- **The two translations against each other:** of 47,599 Greek content words that reach a Hebrew lexeme in both, 71.0% reach
  the same one (72.5% have one in common). Two translators' choices: a difference is not an error.
- **What the compact form costs** (measured on `heb_scg`, which has both forms): of 50,491 Greek content words that reach a Hebrew
  lexeme by both, 97.9% reach the same one.
- **What the missing vowel points cost** (`heb_mod`'s analysis reads none): Salkinson's text tagged with its points stripped keeps
  the same Strong's number for 93.3% of its content parts.

## Limits

- Machine-made, not checked by hand: the links are an aligner's (reviewed by a model for `heb_scg`), the lexemes a tagger's.
- The translators knew the Hebrew Bible, and the Septuagint tradition behind the NT's vocabulary. Agreement with the Septuagint
  bridge is therefore not independent confirmation; and where the NT quotes the Tanakh they could write the Hebrew verse instead
  of translating the Greek. Those stretches are marked (above); the first caution holds outside them too.
- Both translations follow the Textus Receptus; the Greek ids are Nestle 1904.
- `heb_mod`'s text has verses whose boundary is lost or moved (10 verses without words); links there are wrong or missing.
- Known tagger fault: a part with one strong consonant can get a wrong lemma (אַהֲבָה read as נָבִיא: the pair `H5030 G0026`).

## Source / licence

MACULA Greek (Clear Bible / Biblica, CC BY 4.0); lexeme-aligner's alignments (CC0 1.0); hebrew-nt-analysis (bcv-commons, CC BY 4.0,
trained on MACULA Hebrew, CC BY 4.0); the Hebrew texts are public domain. These files: **CC BY 4.0**. They hold lexeme numbers,
counts and scores, no text.
