---
license: cc-by-4.0
language:
- he
- arc
pretty_name: Hebrew Bible Speaker Layer
tags:
- bible
- hebrew
- old-testament
- quotation
- speaker
- discourse
size_categories:
- 10K<n<100K
---

# Hebrew Bible Speaker Layer

Who speaks where in the Hebrew Bible: every quotation, its speaker, its edges on the Hebrew words, and the quotations inside
quotations, on MACULA Hebrew's words and on the clause segments of the
[Hebrew Bible Clause Layout](https://huggingface.co/datasets/bcv-commons/hebrew-clause-layout).

| | |
|---|---|
| Release | **@TAG@**, built @BUILT@ |
| Quotations | @QUOTATIONS@ outer, @NESTED@ inside other quotations |
| Clause segments in a quotation | @IN_QUOTE@ of @SEGMENTS@ |
| Clause segments from | the clause layout's segmentation `8977039d6ddb5383` (the same in every clause-layout release since v0.22) |
| Licence | CC BY 4.0 |

## Files

- `quotations.tsv`: one row per quotation.
- `segments/<BOOK>.tsv`: one row per clause segment of the clause layout.
- `corrections.tsv`: the hand corrections, each with the reason the Hebrew text gives.
- `report.md`: the build's figures and its lists of doubtful places.
- `hebrew-speaker-layer-@TAG@.tar.gz`: all of the above in one pinned download; `SHA256SUMS`.

### quotations.tsv

| Column | |
|---|---|
| `id` | the quotation (`q…` from Clear's data, `L…` added from the clause layout, `S…` a song or speech, `W…` a relayed message or a psalm opened by an inquit; `.n` / `.m n` a quotation inside it) |
| `level`, `parent` | 1 for an outermost quotation; a quotation inside another is one level deeper and names it as `parent` |
| `speaker` | in English, Glyssen's character names where possible ("God", "Moses", "Abraham's chief servant"); "(the one addressed)", "(he/she)", "(they)" where the Hebrew gives no name |
| `speaker_hebrew` | for nested quotations: the subject of the inquit, as MACULA lemmas |
| `divine` | `Y` when the speaker is God |
| `quote_type`, `basis` | where the quotation comes from: Clear's data (`block`, `referent`, `character`), the clause layout (`layout`), a song (`voice`), a messenger formula (`messenger formula`, `relayed message`), a psalm title (`titled psalm`), a hand correction (`correction`) |
| `first`, `last` | the first and last word, MACULA word keys (12 digits: book, chapter, verse, word, part) |
| `from`, `to` | the verses, Hebrew numbering |
| `start_fit`, `end_fit` | how the edges fit the clause segments |
| `inquit` | the line that opens a nested quotation |

### segments/<BOOK>.tsv

| Column | |
|---|---|
| `chapter`, `verse`, `seg`, `clause_key` | the clause segment, as in the clause layout |
| `quotation`, `level`, `speaker` | the innermost quotation the segment stands in, its level (0: none), its speaker |
| `share` | the share of the segment's words in that quotation |
| `frame` | the speaker of a text that is speech from its first line, as a field rather than a level: a psalm's psalmist (the name in its title, "לְדָוִד", else "Psalmist"), a first-person account's narrator |

## How it is made

1. **The outer quotations** are Clear's "MACULA Quotation and Speaker Data": quotation spans with speakers, projected from an
   English translation's quotation marks onto MACULA's Hebrew words through the word alignment, with one speaker per quotation.
2. **Refined on the Hebrew:**
   - a quotation that starts on its own inquit ("וַתֹּאמֶר", "לֵאמֹר") starts after it, and one that ends on the next inquit ends
     before it;
   - an edge that only leaves out a prefix, particle or suffix of a clause segment ("הֲ", "וְ", the article, "כִּי", "הִנֵּה", a pronoun
     suffix: the English word order put the quotation mark there) moves to the segment's edge;
   - pieces of one speech are joined (the same speaker, nothing between them but a speaking formula);
   - quotations Clear lacks are added where the clause layout has speech with a first- or second-person verb (not in the first-person
     memoirs of Ezra and Nehemiah), and a run of three or more verses in the first or second person outside any quotation is a song
     or speech (1 Chr 16:8–35).
3. **Quotations inside quotations:** where the clause layout opens a speech inside a speech; where a messenger formula "כֹּה אָמַר X"
   stands inside a quotation; and the relayed message, where "כֹּה אָמַר X" comes before a quotation (Josh 24:2, Judg 11:15): the
   formula line is the messenger's speech, the sender's words are one level deeper. A psalm whose title ends with an inquit (Ps 18)
   is a quotation opened by it.
4. **Speakers** are checked against Glyssen's characters for each verse; nested speakers are read from the Hebrew inquit (God for a
   divine name, a person's name matched to Glyssen's characters, the outer speaker for "I").
5. **Hand corrections** (`corrections.tsv`) come last, each with its reason.

The code is `shoresh/macula/build_speaker_layer.py` in [bcv-commons/bcv-query](https://github.com/bcv-commons/bcv-query).

## How it was checked

Against the ETCBC's BHSA (CC BY-NC 4.0), compared privately by **bcv-commons/bsb-add-books**, as a reference for evaluation only.
Only figures and failure cases in words were exchanged; no BHSA data is in this release. BHSA marks each clause as narrative,
quotation or discourse, with nesting.

BHSA counts a text that is speech from its start (a psalm, most oracles, the laws of Exodus and Deuteronomy) as a quotation at its
top level; this layer, like Clear, records that as the `frame` field instead. So the figures are given both ways: **A** with BHSA's
top level counted, **B** without it.

In or out of a quotation, per clause segment (v0.4; v0.5–v0.7 changed nesting, not these):

| Genre | A | B |
|---|---|---|
| Narrative | **97.7%** | 93.4% |
| Law | **87.2%** | 63.8% |
| Prophecy | 69.8% | **79.3%** |
| Poetry | 13.3% | **95.3%** |
| Wisdom | 66.6% | **84.8%** |

Quotation edges: of the layer's starts, the share at a start in BHSA, and in brackets the share of BHSA's starts the layer has;
the same for ends (v0.4):

| Genre | Starts | Ends |
|---|---|---|
| Narrative | 96% (86%) | 95% (86%) |
| Law | 97% (74%) | 76% (57%) |
| Prophecy | 83% (66%) | 63% (56%) |
| Poetry | 91% (41%) | 75% (64%) |
| Wisdom | 89% (58%) | 78% (53%) |

Nesting (v0.5): of the layer's nested segments, 83% are nested in BHSA too; of BHSA's, the layer has 41% (narrative 50%, law 87%,
prophecy 30%). Relayed messages (v0.6): 81% of their segments at BHSA's exact level. The psalm frame: 145 of 150 psalms agree; the
five that differ are left undetermined by BHSA.

**Known gaps (open work):**
- the prophets: where an oracle starts and ends, nesting (30%) and ends (63%);
- quotations inside quotations not yet built: letters and decrees and what they quote (Ezra 5–6, Dan 4, Dan 7), quotations inside
  Moses' speeches (the Decalogue, Deut 5; God's words in the Song, Deut 32), the prayers inside Daniel's account (Dan 8–9), a further
  quotation inside a relayed message (2 Kgs 19:21–28);
- the frame for the prophets.

## Sources and licence

| Part | Source | Licence |
|---|---|---|
| Quotations and speakers | Clear's "MACULA Quotation and Speaker Data", © 2023 Clear Bible, Inc. | CC BY 4.0 |
| Character names per verse | Glyssen `CharacterVerse.txt`, © 2014–2020 SIL LSDev and Faith Comes By Hearing | MIT |
| Hebrew words, syntax | MACULA Hebrew (Clear Bible / Biblica) | CC BY 4.0 |
| Clause segments | Hebrew Bible Clause Layout (bcv-commons) | CC BY-SA 4.0 (the segments are referenced by key) |
| Names of persons | STEPBible TIPNR (Tyndale House) | CC BY 4.0 |
| This layer | bcv-commons | **CC BY 4.0** |

**Attribution** when you use this dataset:

> Hebrew Bible Speaker Layer (@TAG@), bcv-commons, CC BY 4.0. Quotations and speakers: MACULA Quotation and Speaker Data, Clear Bible,
> Inc. (CC BY 4.0). Character names: Glyssen, SIL / FCBH (MIT). Syntax: MACULA Hebrew, Clear Bible / Biblica (CC BY 4.0).

## Corrections and feedback

Hebrew readers are invited to refine the layer: a correction is a row in `corrections.tsv` (the quotation's first word, the field,
the new value, and the reason the Hebrew text gives). Issues and requests:
[bcv-commons/bcv-query](https://github.com/bcv-commons/bcv-query/issues).
