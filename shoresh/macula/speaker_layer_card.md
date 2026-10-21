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
| Review | @REVIEW_ROWS@ reviewed changes, each with its reason (`review.tsv`) |
| Licence | CC BY 4.0 |

## Files

- `quotations.tsv`: one row per quotation.
- `segments/<BOOK>.tsv`: one row per clause segment of the clause layout.
- `corrections.tsv`: the hand corrections, each with the reason the Hebrew text gives.
- `review.tsv`: the changes from the review of doubtful passages, each with its reason, its source and a confidence.
- `prophets.tsv`: the prophet of each prophetic book, as its heading names him (the `frame` there).
- `parallels.tsv`: where parallel texts (Samuel-Kings and Chronicles, Isa 36-39 and 2 Kgs 18-20, Ps 18 and 2 Sam 22 …) differ in
  level or speaker.
- `report.md`: the build's figures and its lists of doubtful places.
- `hebrew-speaker-layer-@TAG@.tar.gz`: all of the above in one pinned download; `SHA256SUMS`.

### quotations.tsv

| Column | |
|---|---|
| `id` | the quotation: `q…` from Clear's data, `L…` added from the clause layout, `S…` a song or speech, `N…` a song its inquit announces, `W…` a quotation the layer puts around others (God's words in the prophets, a relayed message, a psalm opened by an inquit), `R…` added by a review row; a suffix (`.1`, `.m2`, `.t3`, `.i4`, `.r5`) marks a quotation inside the one before it |
| `level`, `parent` | 1 for an outermost quotation; a quotation inside another is one level deeper and names it as `parent` |
| `speaker` | in English, Glyssen's character names where possible ("God", "Moses", "Abraham's chief servant"); "(the one addressed)", "(he/she)", "(they)" where the Hebrew gives no name |
| `speaker_hebrew` | for nested quotations: the subject of the inquit, as MACULA lemmas |
| `divine` | `Y` when the speaker is God |
| `quote_type`, `basis` | where the quotation comes from: Clear's data (`block`, `referent`, `character`), the clause layout (`layout`), the translations' votes (`translations`), a saying verb inside a quotation (`inner inquit`), God's words in the prophets (`oracle`), a messenger formula (`messenger formula`, `relayed message`, `commanded message`), a song (`song`, `voice`), a psalm title (`titled psalm`), a hand correction (`correction`), a review row (`review`) |
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
| `frame` | the speaker of a text that is speech from its first line, as a field rather than a level: a psalm's psalmist (the name in its title, "לְדָוִד", else "Psalmist"); in the prophetic books the prophet; a first-person account's narrator (Ezra 9, Neh 13, Dan 8-10) and Nebuchadnezzar's letter (Dan 4) |

Every segment's `quotation` is in `quotations.tsv` at the segment's `level`, and every `parent` holds its quotation.

### Two readings of the prophets

In a prophetic book the `frame` is the prophet, and God's words are always a quotation (level 1, or deeper inside a message).
So the levels can be read two ways:
- **levels alone:** the book as a text with God's words quoted in it (Ezek 6:2 level 1, Amos 3:8, the prophet's own words, level 0);
- **the frame counted as a level:** the book as the prophet's speech with God's words quoted in it, as unfoldingWord's
  translationNotes read it (Ezek 6:2 level 2, Amos 3:8 level 1).

Translations and reference works differ here, from book to book and within a book; the layer carries both and leaves the choice to
the user.

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
     or speech (1 Chr 16:8–35); a song its inquit announces ("אֶת־דִּבְרֵי הַשִּׁירָה הַזֹּאת", Deut 31:30) is one quotation of its singer.
3. **Quotations inside quotations**, from three kinds of evidence:
   - the Hebrew structure: a speech the clause layout opens inside a speech when the line it hangs on introduces speech (a verb of
     saying, "לֵאמֹר", a messenger formula); a saying verb inside a quotation followed by direct speech ("וָאֹמַר", Deut 32:20); a
     messenger formula "כֹּה אָמַר X" inside a quotation; the relayed message, where "כֹּה אָמַר X" comes before a quotation (Josh 24:2,
     Judg 11:15: the formula line is the messenger's speech, the sender's words one level deeper), and a speaker's command to say it
     (Isa 36:4: three levels); a psalm whose title ends with an inquit (Ps 18);
   - a message God tells someone to deliver ("דַּבֵּר אֶל־בְּנֵי יִשְׂרָאֵל", "וְאָמַרְתָּ אֲלֵיהֶם") is a quotation inside God's speech, spoken
     by the one told; in the law it runs to the end of God's speech, over chapter breaks (Lev 4:2–5:13, Lev 25:2–26:45, spoken by Moses);
   - the quotation marks of nine translations, as votes on the Hebrew words: Clear's per-word depth for eight translations and the
     BSB's own marks, compared within each quotation (whether a translation quotes a whole speech is its convention). Most of them
     nesting a stretch makes it a quotation inside the speech (a saying quoted in a speech, God's words in Moses' speeches, a letter,
     a vision's voice); a nested stretch of the layout that has neither a speech opener nor their support is dropped (a vocative, a
     "כִּי" clause of the same saying), and one that runs on past their support ends there.
4. **The prophets:** the frame is the book's prophet (`prophets.tsv`). Verse by verse, a stretch is God's words where "I" is God,
   and the prophet's own where "I" is the prophet (Jeremiah's laments) or God is named in the third person (Isa 11, 19); God's
   words that no quotation holds yet become one (`basis` `oracle`). A formula inside God's words ("נְאֻם־יְהוָה", "אָמַר יְהוָה",
   "לָכֵן כֹּה אָמַר יְהוָה") stays inside his quotation. Prose narrative outside any speech ends a stretch (Jer 36:4, Isa 37:36).
5. **Speakers** are checked against Glyssen's characters for each verse; nested speakers are read from the Hebrew inquit (God for a
   divine name, a person's name matched to Glyssen's characters, the outer speaker for "I"), else from Glyssen's other character for
   the verse, else from "I" through MACULA's participant references.
6. **Hand corrections** (`corrections.tsv`), each with its reason.
7. **The review rows** (`review.tsv`) last: changes from a review of doubtful passages, each with the reason the Hebrew gives (see
   below).

The code is `shoresh/macula/build_speaker_layer.py` in [bcv-commons/bcv-query](https://github.com/bcv-commons/bcv-query).

### The review

48 doubtful passages (8 of each kind: the translations split, nesting from the layout alone, God's words the layer made a
quotation, parallel texts that differ, unfoldingWord's notes where the layer doesn't nest, unnamed speakers) were reviewed by two
AI agents independently (Claude Opus 5.5), each given the Hebrew of the passage with the evidence as numbers (the translations'
votes, the grammar, Glyssen's characters, MACULA's participant references), no English text and no BHSA, and the conventions this
layer follows. Where the two agreed, their rows were taken; where they differed, a third agent decided. Each row records its
source (`agent:claude-opus-5-5:review-v1`, `+adjudicated`, `+rekeyed` where a row was moved to the build's current quotations) and
a confidence. The layer is also built without them (`--no-review`). A review of all doubtful passages (about 700) is planned.

Since v0.11 the clause layout takes its speech levels from this layer, and mistakes found there are fixed here as more rows
(source `agent:claude-opus-5-5:layout-check-v1`, each with its reason from the Hebrew): in v0.11, Lev 17:14-16 (the message of 17:8
runs to 17:16; "וָאֹמַר" is God's), Jer 1:7-8 and 2:2-3 ("נְאֻם־יְהוָה" closes God's words), Jer 24:5-10 (God's words end with the
chapter) and Jer 25 (Jeremiah's speech of 25:3-38, with God's words inside it).

## How it was checked

**Against BHSA, privately.** The rules were developed and tuned with the help of a comparison with the ETCBC's BHSA
(CC BY-NC 4.0), made privately by **bcv-commons/bsb-add-books** as a reference for evaluation only: only figures and failure cases
in words were exchanged, and no BHSA values, codes or files are in the code or in this release. BHSA marks each clause as
narrative, quotation or discourse, with nesting, and leaves many clauses undetermined (most of Ps 19, 107, 125, 127 and 133, for
example).

BHSA counts a text that is speech from its start (a psalm, the laws of Exodus and Deuteronomy, many oracles) as a quotation at
its top level; this layer records that as the `frame` field. So the figures are given three ways: **A** with BHSA's top level
counted, **B** without it, and **A with the frame counted** as a level. Measured on v0.9 (before the formula and review fixes
below), per clause segment in or out of a quotation:

| Genre | A | B | A, frame counted |
|---|---|---|---|
| All | 82.1% | 86.4% | **91.8%** |
| Narrative | 97.9% | 93.5% | **98.4%** |
| Law | **87.2%** | 63.8% | **87.2%** |
| Prophecy | 77.1% | 74.2% | **89.0%** |
| Poetry | 15.0% | **96.9%** | 84.9% |
| Wisdom | 66.6% | **84.8%** | 66.6% |

Quotations inside quotations (v0.9, by the layer's own levels): of BHSA's nested segments the layer has 54% (narrative 74%, law
88%, prophecy 40%, wisdom 43%); of the layer's, 88% are nested in BHSA too.

Quotation edges (v0.9): of the layer's starts, the share at a start in BHSA, and of BHSA's starts, the share the layer has; the
same for ends:

| Genre | Starts | Ends |
|---|---|---|
| Narrative | 97% / 92% | 96% / 93% |
| Law | 89% / 86% | 69% / 75% |
| Prophecy | 78% / 75% | 54% / 62% |

The prophecy ends were low because an oracle formula inside God's words ended his quotation; this release keeps such formulas
inside it, which bsb-add-books' check traced most of those ends to.

**The prophets in both readings** (v0.9, the share of segments at BHSA's exact level): levels alone 49%, the frame counted 46%,
and the better of the two per segment 83% (v0.8: 45%). BHSA itself follows one convention in some books (levels alone in
Ezekiel, Obadiah and Malachi; the frame counted in Micah, Nahum and Habakkuk) and both within others (Isaiah, Jeremiah,
Zechariah). The levels are right in most of the prophets once the reading is chosen.

**The review rows** (v0.9 pilot): of the segments they changed, 163 moved closer to BHSA's level and 39 farther; 21 of the 39 were
one row applied to the wrong quotation (2 Kgs 19:29–34), fixed in this release, and 12 a reading by convention (Amos 3:3–5, the
prophet's own questions).

**Our own measures for this release** (bcv-query's checks):
- unfoldingWord's translationNotes mark 647 quotations inside quotations in the OT (`figs-quotesinquotes`, CC BY-SA 4.0; used to
  measure, not as input). With the frame counted as a level, the layer nests at 87.0% of them (narrative 87.5%, law
  85.5%, prophecy 87.4%, wisdom 89.7%); without the review rows 84.9% (v0.7: 54%).
- Parallel texts, aligned word by word: 77.4% of matched words at the same level (the frame counted) and 93.4% with
  the same speaker. Some differences are by design (the Decalogue in Exod 20 and in Moses' speech, Deut 5).

**Known gaps (open work):**
- the Rabshakeh's words in Isa 36:7b are one level deeper than in 2 Kgs 18:22;
- a decree quoted in a letter (Ezra 6:3–12) and most levels of Nebuchadnezzar's letter (Dan 4);
- a nested speaker named through "I" can be the outer speaker where the reference chain does not reach the quoted person (Jer 22:18);
- the prophecy ends have not been measured against BHSA since the formula fix;
- the review covered 48 passages of about 700 doubtful ones.

## Sources and licence

| Part | Source | Licence |
|---|---|---|
| Quotations and speakers | Clear's "MACULA Quotation and Speaker Data", © 2023 Clear Bible, Inc. | CC BY 4.0 |
| Character names per verse | Glyssen `CharacterVerse.txt`, © 2014–2020 SIL LSDev and Faith Comes By Hearing | MIT |
| Hebrew words, syntax | MACULA Hebrew (Clear Bible / Biblica) | CC BY 4.0 |
| Clause segments | Hebrew Bible Clause Layout (bcv-commons) | CC BY-SA 4.0 (the segments are referenced by key) |
| Names of persons | STEPBible TIPNR (Tyndale House) | CC BY 4.0 |
| Quotation depth per word in eight translations (numbers only) | Clear's alignment-quotations, Clear-Bible/speaker-quotations @ b09e308a3a1a | CC BY 4.0 |
| The BSB's quotation marks per Hebrew word | Berean Standard Bible Translation Tables | public domain |
| Participant references | MACULA Hebrew (Clear Bible / Biblica) | CC BY 4.0 |
| Review rows | written by AI agents (Claude Opus 5.5) from the Hebrew and the evidence above, under bcv-commons' conventions | part of this layer |
| This layer | bcv-commons | **CC BY 4.0** |

**Attribution** when you use this dataset:

> Hebrew Bible Speaker Layer (@TAG@), bcv-commons, CC BY 4.0. Quotations and speakers: MACULA Quotation and Speaker Data, Clear Bible,
> Inc. (CC BY 4.0). Character names: Glyssen, SIL / FCBH (MIT). Syntax: MACULA Hebrew, Clear Bible / Biblica (CC BY 4.0).

## Corrections and feedback

Hebrew readers are invited to refine the layer: a correction is a row in `corrections.tsv` (the quotation's first word, the field,
the new value, and the reason the Hebrew text gives). Corrections to the review rows are welcome the same way. Issues and requests:
[bcv-commons/bcv-query](https://github.com/bcv-commons/bcv-query/issues).
