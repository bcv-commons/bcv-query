---
license: cc-by-4.0
language:
  - hbo
  - arc
pretty_name: Hebrew Phrase Types (model layer)
tags:
  - bible
  - hebrew
  - semantic-roles
  - prepositional-phrases
  - model-output
size_categories:
  - 10K<n<100K
---

# Hebrew Phrase Types: a model layer

**Model output, not a fact layer.** This dataset gives semantic types for the 50,829 clause-level prepositional phrases of
the Hebrew Bible: the phrases MACULA Hebrew gives the role `pp`.

- Two language models read them. Jev (TypeSafe) read every phrase; Claude Opus 5.5 read, as a second judge, the 24,057
  phrases that a fixed rule calls unsure.
- No person has reviewed the rows.
- It is published apart from the bcv-commons fact layers (the clause layouts, passage facts, word parts) and is never merged into them.

| | |
|---|---|
| Version | @VERSION@ (`schema` 1); from make-tanakh-research's table version 2.1 (sha256 `@TABLE_SHA@`) |
| Built | @BUILT@ by `shoresh/macula/release_phrase_types_model.py` (bcv-query `@CODE@`) |
| Rows | 50,829 phrases: 44,291 with a nominal head, 6,538 preposition + infinitive or participle |
| Licence | CC BY 4.0 |

## Why

MACULA Greek types its adjuncts; MACULA Hebrew gives a clause-level prepositional phrase the role `pp` and no type. We found no
openly licensed source that types them. This layer fills that gap as a judgement, with its confidence stated, for readers and
drafting tools that need to know whether "to Jerusalem" is a goal and "to Abraham" a recipient.

## The labels

Fifteen labels:
- Recipient, Beneficiary, Goal, Place, Source, Time, Instrument, Accompaniment, Manner, Comparison, Relation, Purpose, Possessor;
- Object (the verb's prepositional object);
- Other.

Each label belongs to one of four groups:

| group | labels |
|---|---|
| participant | Recipient, Beneficiary, Object, Possessor, Accompaniment |
| space | Goal, Place, Source |
| time | Time |
| circumstance | the other six |

## The file

`data/hebrew_phrase_types.parquet`, one row per phrase:

| column | meaning |
|---|---|
| `phrase_key` | the phrase: `<first word>-<last word>:pp:<level>`, MACULA Hebrew word ids. `level` counts from the top within a chain of tree nodes over the same words; it is 0 for nearly all. |
| `first_word` | the phrase's first word id (12 digits, MACULA Hebrew) |
| `preposition` | the preposition's lemma |
| `head` | `nominal`, or `verb` (preposition + infinitive or participle) |
| `label` | **the published label**: Opus's where Opus was asked, else Jev's |
| `basis` | how `label` came about (below) |
| `group` | the coarse group of `label` |
| `jev_label`, `jev_confidence` | Jev's choice and its probability |
| `jev_second`, `jev_second_p` | Jev's second-likeliest label and its probability |
| `jev_group_p` | the probability Jev gave to the group of `label`, summed over its labels |
| `opus_label` | Opus's label where Opus was asked, else empty |

`jev_confidence` describes `jev_label`. Where `basis` is `opus`, it does not describe `label`.

## Use `basis`

| `basis` | rows | share | what it means |
|---|---|---|---|
| `jev` | 26,772 | 53 % | Jev alone, confident; right in about 96 % of a random sample |
| `jev+opus` | 12,643 | 25 % | asked of both, and the two models agree; right in 97–98 % where the reference decides |
| `opus` | 11,414 | 22 % | asked of both, and they differ; Opus's label stands. These are the hard phrases: one in six is contested even between two careful labellings, and the label there is one of two defensible readings. |

## How good it is

**The yardstick** is a simple random sample of 450 phrases (300 with a nominal head, 150 with a verb head).
- Each phrase was labelled twice by Claude Opus 5.5, in two orders. Where the two labellings agree (283 and 133 phrases), that label is the reference; on 17 + 17 phrases they differ, and those are "contested".
- **Caution:** the second judge is the same model as the reference's labellers. Where `label` is Opus's, "equals the reference" measures Opus's consistency with itself, not an independent check. The independent evidence is where two different models agree, and the comparison with a human analysis below.

| sample | n | equals the reference | contested | differs | share, of those with a reference |
|---|---|---|---|---|---|
| nominal heads, `label` | 300 | 273 | 17 | 10 | 0.965 |
| nominal heads, Jev alone | 300 | 242 | 17 | 41 | 0.855 |
| verb heads, `label` | 150 | 130 | 17 | 3 | 0.977 |
| verb heads, Jev alone | 150 | 87 | 17 | 46 | 0.654 |

**Overall.** Weighted by the two head kinds, `label` equals the reference in 96.7 % of the phrases where the reference
decides (Jev alone 82.9 %). Counting contested phrases as unconfirmed, it is 90.4 % of all phrases (Jev alone 77.8 %).
The group of `label` equals the reference's group in 98.2 % (nominal heads) and 98.5 % (verb heads).

**Jev's confidence is calibrated where Jev stands alone.** Share of Jev's labels that equal the reference, by confidence:

| `jev_confidence` | nominal heads | verb heads |
|---|---|---|
| below 0.5 | 0.44 | 0.25 |
| 0.5–0.7 | 0.84 | 0.73 |
| 0.7–0.9 | 0.95 | 0.83 |
| above 0.9 | 0.98 | 0.97 |

**Against a human analysis.** This compares nominal heads with the ETCBC's BHSA phrase functions. It gives figures only: no
BHSA value is in this dataset.

| line | `label` | Jev alone |
|---|---|---|
| their Time phrases are typed Time | 0.983 | 0.977 |
| their Location phrases are typed Place | 0.884 | 0.838 |
| their Location phrases are typed Place, Goal or Source | 0.986 | 0.968 |
| typed Recipient or Object is their Complement | 0.941 | 0.896 |
| typed Time is their Time | 0.791 | 0.804 |

Where the two models differ, Opus's label is nearer the human analysis on every line. "Typed Time is their Time" is
low on the unsure phrases for both models: these are phrases BHSA files as adjunct or complement ("to your generations",
"on this day").

**A registered check fired, and we say so.** Before the second pass we wrote down a rule: the merged layer's Time and Place
figures must not fall more than 0.05 below Jev's figures at confidence ≥ 0.7.
- Two of the three figures held. "Typed Time is their Time" fell by 0.070. The cause is that the check compared the whole
  layer with Jev's confident part, so it fell when the unsure phrases came in, whoever labels them: Jev alone on all phrases
  gives 0.804.
- On like phrases the second judge is the better one. The merged `label` is published; `jev_label` and `opus_label` are
  both given, so that either reading can be used.

## Known limits

- **The fifteen labels are our list.** The judges differ most at these boundaries:
  - Recipient / Beneficiary;
  - Goal / Place;
  - Purpose / Manner (for `לֵאמֹר` and other infinitives);
  - Object / Beneficiary;
  - Recipient / Object.
- **Recipient against Beneficiary is a convention, not an error.** For "bear to", "forgive" and "give", the layer says Recipient throughout.
- **Only clause-level `pp`.** Phrases inside noun phrases, predicates of verbless clauses and members of coordinated phrases are not typed here.
- **Complement against adjunct is not in this layer.**
- **No person has reviewed the rows.** Corrections are welcome as issues on bcv-commons/bcv-query, most of all on the `opus` rows.

## Sources and licence

| | |
|---|---|
| Inputs sent to the models | the Hebrew text's words with MACULA Hebrew's lemmas and glosses (CC BY 4.0, © Clear Bible, Inc) |
| Phrase boundaries and word ids | MACULA Hebrew (WLC lowfat), CC BY 4.0 |
| Labels | Jev (TypeSafe) and Claude Opus 5.5, prepared by make-tanakh-research for bcv-commons |
| Witness for the figures only | ETCBC BHSA (CC BY-NC 4.0); none of its values are in the data |

This dataset is licensed **CC BY 4.0**. Please credit "Hebrew Phrase Types (model layer), bcv-commons
(bcv-commons/hebrew-phrase-types-model @VERSION@)" and MACULA Hebrew, © Clear Bible, Inc.

## Versions

- @VERSION@ (@BUILT@): first release (research table version 2.1).
- `schema` in `build.json` is the version of the file shape. It is raised only when a column is renamed, dropped or changes meaning.
