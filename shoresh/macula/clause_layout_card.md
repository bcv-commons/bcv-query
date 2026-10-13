---
license: cc-by-sa-4.0
language:
  - hbo
  - arc
pretty_name: Hebrew Bible Clause Layout (MACULA + UHB)
tags:
  - bible
  - hebrew
  - aramaic
  - syntax
  - clauses
  - old-testament
  - translation
size_categories:
  - 10K<n<100K
configs:
  - config_name: clauses
    default: true
    data_files:
      - split: train
        path: data/clauses-*.parquet
---

# Hebrew Bible Clause Layout

The Hebrew Bible, with its Aramaic portions, laid out **one clause segment per line**, chapter by chapter. Each line carries its
**indentation in the text**: which clause it depends on, across verses, and how far it is indented under it. The layout is built
from the **MACULA Hebrew** syntax trees over the **unfoldingWord Hebrew Bible (UHB)** text. It is meant for translators, and for the
tools and agents that help them, to read a chapter clause by clause, with each subordinate clause, speech and law case indented
under the clause it belongs to.

It is a share-alike alternative to clause layouts derived from the ETCBC BHSA (CC BY-NC 4.0). It contains no data under a
non-commercial licence.

| | |
|---|---|
| Release | **@TAG@** (rules @VERSION@), built @BUILT@ |
| Segmentation | `@SEGMENTATION@`: changes only when a segment boundary moves |
| Levels | `@LEVELS@`: the rules version and the hash of the settings the levels were computed with |
| Size | @BOOKS@ books, @CHAPTERS@ chapters, @VERSES@ verses, @SEGMENTS@ clause segments |

## Files

```
hebrew-clause-layout-@TAG@.tar.gz   the pinned download: everything below except data/, in one archive
clauses/<BOOK>/<BOOK>_<CCC>.jsonl     one JSON object per clause segment, one file per chapter (in the archive)
layout/<BOOK>/<BOOK>_<CCC>.txt        the same chapter as indented plain text (in the archive)
data/clauses-<BOOK>.parquet           the same rows, one file per book, for the dataset viewer and datasets.load_dataset
_clauses_source.json                  the version stamp (see "Versions")
build.json                            the build record: sources, versions, relation sets, settings
clause_layout.toml                    the rules and settings the layout was built with, each rule documented with examples
schema/clause_segment.schema.json     JSON Schema of a row
RELEASE_NOTES.md                      what is in this release, the rules and their reach, checksums
SHA256SUMS                            SHA-256 of the archive and the data files
```

- `<BOOK>` is the USFM book code (`GEN`, `RUT`, `PSA`, …), and `<CCC>` the zero-padded chapter (`001`).
- To pin this release, download
  `https://huggingface.co/datasets/bcv-commons/hebrew-clause-layout/resolve/@TAG@/hebrew-clause-layout-@TAG@.tar.gz`
  and check it against its SHA-256 in `SHA256SUMS`.

## What a clause segment is

A **clause segment** is a maximal run of whole words, inside one verse, that belongs to one clause.
- A clause interrupted by an embedded clause gives two segments, one before and one after the embedded clause, as BHSA's clause
  atoms do.
- A clause that runs over a verse boundary gives one segment per verse.
- A word is assigned as a whole, including its prefixes (וְ, בְּ, לְ, הַ, …).

The segments are MACULA's clauses, cut at word and verse boundaries. Every row has the MACULA word keys of its words, so a row can
be joined to anything keyed on MACULA words.

## The levels

MACULA has no clause-to-clause relations above the verse: a MACULA sentence is one verse, and the main clauses in a verse are
siblings. The text-level hierarchy is therefore **derived by rules** from MACULA's features: verb forms, the clause's first words,
verbs of saying, subordinators, person, and the MACULA tree. Every clause gets a `discourse_parent` and a `relation`.
- **`text_depth`**: the indentation shown in `layout/`. It counts the links up the `discourse_parent` chain that add a level: a
  speech, a subordinate clause, an embedded clause. Chain links (`continuation`, `coordination`, `asyndetic`, `parallel`, …; the set
  is `build.json` `relations.flat`) stay on the same level. 0 is the main line. Each chapter starts at the margin.
- **`text_depth_law`**: the same, with conditionals laid out as in BHSA's law. A protasis stands one level in, and its apodosis
  stands beside it. The later cases of a law step in one level each, and a new law stands where the law before it stands. It
  matters in the law books and casuistic prophecy; elsewhere it equals `text_depth`.
- **`tree_depth`**: every link counted except `parallel`, chain links included, so each clause of a chain nests under the one
  before it, as in BHSA's tree.
- **`depth`**: the number of clause ancestors in the MACULA tree, within the verse.

The tree keeps a protasis under its apodosis. A client that wants BHSA's direction for conditionals in the tree inverts those links
as `build.json` `relations.conditional_inversion` describes. For a flat view, use `text_depth_law`.

The rules (100, each with its scope and examples) are in `clause_layout.toml`, and the code in
[bcv-commons/bcv-query](https://github.com/bcv-commons/bcv-query) (`shoresh/macula/discourse_rules.py`). Settings files called
profiles can change the conventions. This release is built with the default profile: chapters start at the margin, and a speech
carried over a chapter break starts again at the margin.

## layout/: plain text

```
RUT 1
1:0 וַיְהִ֗י בִּימֵי֙
1:1 שְׁפֹ֣ט הַשֹּׁפְטִ֔ים
1:0 וַיְהִ֥י רָעָ֖ב בָּאָ֑רֶץ
1:0 וַיֵּ֨לֶךְ אִ֜ישׁ מִבֵּ֧ית לֶ֣חֶם יְהוּדָ֗ה
1:1 לָגוּר֙ בִּשְׂדֵ֣י מוֹאָ֔ב
```

- The first line is `<BOOK> <chapter>`.
- Every other line is `<verse>:<text_depth> <text>`. A reader shows the number as indentation: `"  " * n + text`.
- The text is the UHB surface text with vowels and accents. Words are separated by single spaces, maqaf `־` and paseq ` ׀ ` are
  kept, and sof pasuq `׃` ends the verse.
- The line shows the vocalised (qere) reading; the `clauses/` row has both readings.

## clauses/ and data/: one row per segment

Ruth 1:1, fifth segment:

```json
{"book": "RUT", "chapter": 1, "verse": 1, "seg": 5, "verse_ref_en": "RUT 1:1",
 "clause_key": "080010010131", "parent_key": "080010010081", "clause": 119513, "parent": 119508, "sentence": 119498,
 "depth": 1, "discourse_parent": "080010010081", "relation": "purpose", "discourse_attach": null, "discourse_rule": "embedded",
 "text_depth": 1, "text_depth_law": 1, "tree_depth": 3, "kind": "VC", "rule": "V-PP", "language": "hbo",
 "first": "080010010131", "last": "080010010151",
 "words": ["080010010131", "080010010132", "080010010141", "080010010142", "080010010151"],
 "text": "לָגוּר֙ בִּשְׂדֵ֣י מוֹאָ֔ב", "ketiv_qere": []}
```

| Field | Meaning |
|---|---|
| `book`, `chapter`, `verse` | USFM code, chapter and verse, in Hebrew numbering |
| `seg` | position of the segment in the chapter, from 1 |
| `verse_ref_en` | the same verse in English numbering (see "Versification") |
| `clause_key` | **stable clause id**: the first word key of the clause's first segment, shared by all segments of one clause |
| `parent_key` | `clause_key` of the nearest enclosing MACULA clause with words of its own, or `null` |
| `clause`, `parent`, `sentence` | row ids of the tree build; they change when it is rebuilt, so never key on them |
| `depth` | embedding depth in the MACULA tree, within the verse |
| `discourse_parent` | `clause_key` of the clause this one depends on in the text-level hierarchy, also across verses; `null` where nothing comes before it on its line (the first clause of a chapter or a Psalm, a fresh start after a paragraph break) |
| `relation` | the kind of link to `discourse_parent`: `continuation`, `coordination`, `asyndetic`, `parallel`, `speech`, `inquit`, `vocative`, `causal`, `purpose`, `temporal`, `conditional`, `relative`, `complement`, `circumstantial`, `consequence`, `adversative`, `embedded`; `null` where `discourse_parent` is `null` |
| `discourse_attach` | word key of the word inside the `discourse_parent` clause that this clause depends on (a relative clause's antecedent), or `null` |
| `discourse_rule` | the rule that set `discourse_parent` (for information; `relation` is the field to use) |
| `text_depth` | the indentation (flat view), as in `layout/` |
| `text_depth_law` | the indentation with conditionals laid out as in BHSA's law |
| `tree_depth` | the number of links up the `discourse_parent` chain, except `parallel` ones (chain links included) |
| `kind`, `rule` | MACULA clause kind (`VC` verbal, `NC` nominal, …) and constituent rule (`V-S-PP`) |
| `language` | `hbo` Hebrew or `arc` Aramaic |
| `first`, `last`, `words` | the MACULA word keys of the segment (BBCCCVVVWWW plus a part digit), in order |
| `text` | surface text of the segment, as in `layout/` |
| `ketiv_qere` | `{key, ketiv, qere}` for the words of the segment that have a ketiv/qere (from UHB); `ketiv` or `qere` is `null` where only one exists |

## Versification

Verses use the **Hebrew numbering** of the source text, which differs from English Bibles in places: Gen 31:55 = Hebrew 32:1;
Psalm superscriptions are verse 1; Joel 3–4; Malachi 3:19–24; and others. Every row carries `verse_ref_en`, the reference in
English numbering, from the bcv-commons/bibles verse map `org-to-eng` (from STEPBible TVTMS, CC BY 4.0). Where English divides a
Hebrew verse (Ps 13:6, Isa 63:19), `verse_ref_en` names the English verse the segment falls in.

## Versions

The chapter files carry no version header. `_clauses_source.json` is the version stamp:

```json
{"dataset": "bcv-commons/hebrew-clause-layout", "release": "@TAG@", "segmentation": "@SEGMENTATION@", "levels": "@LEVELS@",
 "books": {"RUT": {"chapters": 4, "verses": 85, "segments": …, "sha256": "…"}, …}}
```

- `segmentation` changes only when a segment boundary moves anywhere. Each book's `sha256` covers that book's segment boundaries
  (book, chapter, verse, first and last word key), so a rebuild that moves a boundary shows exactly which books changed.
- `levels` changes when the rules or their settings change. The relations, `discourse_parent` and the depths can then change, but
  the segments and their word keys don't.
- A **levels-only release** keeps `segmentation` and every book's `sha256`. Anything keyed on the segments (sidecars, alignments
  to clause segments) stays valid.

`build.json` records the sources: the MACULA Hebrew commit, the UHB tag, the TVTMS revision and the hashes of the versification
files.

## How the text-level hierarchy was checked

The hierarchy is derived by rules from MACULA Hebrew alone. No BHSA values, codes, links or files went into the rules' logic or into
the rows of this dataset. The documentation of some rules in `clause_layout.toml` cites, in words, figures and examples from the
comparison below.

The comparison with the ETCBC's BHSA (CC BY-NC 4.0) was made privately by **bcv-commons/bsb-add-books**, as a reference for
evaluation only. Only figures and failure cases in words were exchanged. No BHSA data is in this release.

Step agreement with BHSA's own clause links, laid out the same way: the share of line pairs where the step from one line to the
next (deeper, level, shallower) is the same. Rules @VERSION@, measured by bsb-add-books:

| Chapters | `text_depth` | `text_depth_law` |
|---|---|---|
| tuned (8 chapters the rules were developed on) | 88% | 89% |
| held-out (5 chapters never used for tuning) | 88% | 88% |
| prophets (9) | 83% | 83% |
| law (26) | 82% | 85% |
| expressions (39) | 85% | 86% |
| all delivered chapters | 84% | 85% |

Mean depth per chapter against BHSA's, over the 379 chapters of the Torah, the Latter Prophets and the Poetry for which a reference
was available: a mean absolute gap of 0.364 levels (`text_depth_law` 0.311). Per book, over all 39 books: 0.208.

Where the layout follows a convention, the convention is chosen for readers, documented in `clause_layout.toml`, and sometimes
differs from BHSA on purpose. For example, a chapter starts at the margin. Where the layout is deeper than BHSA and the extra
level reflects the text (a real subordination, a speech inside a speech), it is kept.

Known differences (see `RELEASE_NOTES.md`):
- The poetry is, on average, a little shallower than BHSA.
- In Micah 2 and Zephaniah 3 a chain after "לָכֵן" runs on longer than in BHSA.
- In a few law chapters (Num 30, Lev 15:13–15) the law view is one level deeper.

BHSA: Eep Talstra Centre for Bible and Computer, VU Amsterdam; DOI 10.17026/dans-z6y-skyh.

## Sources and licence

| Part | Source | Licence |
|---|---|---|
| Hebrew/Aramaic text, ketiv/qere | unfoldingWord Hebrew Bible (UHB) @UHB_TAG@, based on the Westminster Leningrad Codex | CC BY-SA 4.0 |
| Clauses, words, clause kinds and rules | MACULA Hebrew (Clear Bible / Biblica), `WLC/lowfat`, commit `@MACULA_COMMIT@` | CC BY 4.0 |
| English verse numbers | bcv-commons/bibles `org-to-eng`, from STEPBible TVTMS (rev. `@TVTMS_REV@`) | CC BY 4.0 |
| The text-level hierarchy, this compilation | bcv-commons | **CC BY-SA 4.0** |
| The rules and code (`clause_layout.toml`, bcv-query) | bcv-commons | MIT |

**Attribution** when you use this dataset:

> Hebrew Bible Clause Layout (@TAG@), bcv-commons, CC BY-SA 4.0. Text: unfoldingWord Hebrew Bible (CC BY-SA 4.0). Syntax: MACULA
> Hebrew, Clear Bible / Biblica (CC BY 4.0). Versification: STEPBible TVTMS (CC BY 4.0).

## Feedback

Issues and requests: [bcv-commons/bcv-query](https://github.com/bcv-commons/bcv-query/issues). Please name the chapter and verse, the
line, and what you expected.
