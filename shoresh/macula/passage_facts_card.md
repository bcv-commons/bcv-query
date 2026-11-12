---
license: cc-by-sa-4.0
language:
  - hbo
  - arc
  - grc
pretty_name: Passage Facts
tags:
  - bible
  - hebrew
  - greek
  - speech
  - poetry
  - discourse
size_categories:
  - 10K<n<100K
---

# Passage Facts

Who is heard in a passage, what kind of speech it is, and how the text is set (song, poetic lines, prose), for the whole Bible. Each
fact is tied to exact words of the Hebrew or Greek text (MACULA word ids) and names its source and licence, so that it can be carried
through word alignments into any translation.

No fact is a model's reading of the text. A fact is a source's own value (`b.source`), read from the Hebrew or Greek grammar by a
fixed rule (`b.text`), inferred by a published rule from other facts (`b.rule`), or set by a review row (`b.review`).

| | |
|---|---|
| Built | @BUILT@ by `macula/build_passage_facts.py` (bcv-query `@CODE@`) |
| Size | 66 books, @FACTS@ facts (@SA_FACTS@ of them CC BY-SA 4.0); CC BY subset: @BY_FACTS@ facts |
| Schema | @SCHEMA@ (see *Versions*) |

## Files

| Path | What it holds |
|---|---|
| `data/<BOOK>.jsonl` | **all facts** of a book, one JSON object per line. Licence of the whole: CC BY-SA 4.0 |
| `data-cc-by/<BOOK>.jsonl` | **only the facts of sources that are not share-alike**. Licence: CC BY 4.0 |
| `codes.tsv` | the decoding table: every code in the data, with its English meaning, its source, and notes |
| `sources.tsv` | the sources: licence, share-alike or not, enabled or not, attribution wording, what each gives |
| `build.json` | sources used, input hashes and pins, counts per book, and `checks`: how well each source landed on the words |
| `SHA256SUMS` | the sha256 of every file |

## A fact

```json
{"id": "EXO.00001", "kind": "quote", "value": "qt.normal", "first": "020010090041", "last": "020010100192", "ref": "EXO 1:9-10",
 "basis": "b.source", "precision": "p.word", "src": ["clear", "layer"], "lic": "CC BY 4.0",
 "level": 1, "quote": "q00503", "found": "qf.block", "speaker": "מֶלֶךְ", "speaker_ref": ["020010080021"], "speaker_by": "sb.inquit",
 "speaker_id": "c0073", "speaker_name": "פַּרְעֹה", "speaker_name_ref": ["020010220021"]}
```

@FIELDS@

The data holds no English. To show a fact in English, look its codes up in `codes.tsv`. Speakers are named by the Hebrew or Greek
words of the text; a `frame` fact gives the verb's lemma.

## What the facts are

@KINDS@

## Sources and licence

@SOURCES@

**Why two folders.** Facts from share-alike sources (unfoldingWord, MAM, the UBS dictionaries) can only be shared under CC BY-SA 4.0,
so `data/`, which holds all facts, is CC BY-SA 4.0 as a whole. Every other fact stays under its own licence (CC BY 4.0, MIT, public
domain), and `data-cc-by/` holds exactly those, under CC BY 4.0. Each fact also says its own licence in `lic`.

**Attribution.** Name this dataset ("Passage Facts, bcv-commons") and the sources of the facts you use, with the wording in the
`attribution` column of `sources.tsv`. For Glyssen's delivery notes keep its MIT copyright notice.

Not included: The Bible Translator's Assistant (All the Word) and OpenText.org. Both are in `sources.tsv` but disabled, because
neither states an open licence.

## How well the sources landed

@CHECKS@

## Versions

A new build gets a new revision; a revision is never changed. Pin the revision. `schema` in `build.json` is the version of the fact
shape. It goes up only when a field is renamed, dropped or changes meaning; a new field, kind or code leaves it unchanged. Codes are
never renumbered. Anchors (`first`, `last`, `pieces`, `lines`, `at`, `after`) are a first version and may follow a link-type
specification later; that would be a schema change, listed here.

## Feedback

Issues and requests: [bcv-commons/bcv-query](https://github.com/bcv-commons/bcv-query/issues).
