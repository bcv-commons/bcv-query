---
license: cc-by-4.0
language:
  - hbo
  - arc
pretty_name: Tanakh Hebrew Clauses
tags:
  - bible
  - hebrew
  - aramaic
  - clauses
  - tanakh
size_categories:
  - n<1K
---

# Tanakh Hebrew Clauses

The Hebrew words of every clause segment of the Tanakh, one JSON file per chapter, so that a reader or editor can show the Hebrew
beside each clause of a chapter by fetching one file. Built from two pinned bcv-commons releases and nothing else: the segmentation
of the [Hebrew Bible Clause Layout](https://huggingface.co/datasets/bcv-commons/hebrew-clause-layout) and the words of the lexeme
spine.

| | |
|---|---|
| Built | @BUILT@ by `macula/release_tanakh_hebrew_clauses.py` (bcv-query `@CODE@`) |
| Size | @CHAPTERS@ chapters, @SEGMENTS@ segments, @WORDS@ words |
| Clause layout | `bcv-commons/hebrew-clause-layout` @LAYOUT_TAG@, revision `@LAYOUT_REV@`; columns `chapter`, `verse`, `seg`, `clause_key`, `kind`, `rule`, `words` only |
| Words | `@SPINE_TAG@` from [bcv-commons/spine-releases](https://github.com/bcv-commons/spine-releases) (sha256 `@SPINE_SHA@`), table `spine_words`: `key`, `surface`, `is_content` |

## Files

- `data/<BOOK>/<CCC>.json`: one chapter (USFM book code, chapter zero-padded to three digits), in Hebrew verse numbering.
- `build.json`: the schema (see *Versions*), build date, layout revision, spine release and its sha256, and the counts.
- `SHA256SUMS`: the sha256 of every file.

Fetch a chapter at a pinned revision:
`https://huggingface.co/datasets/bcv-commons/tanakh-hebrew-clauses/resolve/<revision>/data/RUT/001.json`

```json
{"book": "RUT", "chapter": 1,
 "verses": {"1": [
   {"key": "080010010011", "kind": "VC", "rule": "V-PP", "words": [
     {"id": "08001001001", "surface": "וַיְהִ֗י", "content": true},
     {"id": "08001001002", "surface": "בִּימֵי֙", "content": true}]}, ...]}}
```

| Field | Meaning |
|---|---|
| `verses` | verse number (string) → the verse's segments in the layout's order (`seg`). A clause that another clause interrupts appears again for its later piece, with the same `key` |
| `key` | the layout's `clause_key`: the first word key of the clause, shared by all its segments |
| `kind`, `rule` | the layout's MACULA clause kind (`VC`, `NC`, …) and constituent rule |
| `words[].id` | the word: the first 11 digits of its MACULA morpheme keys (`BBCCCVVVWWW`) |
| `words[].surface` | the word's surface text (WLC, as MACULA Hebrew has it): its morphemes' surfaces joined |
| `words[].content` | true if any of its morphemes is a content word (noun, verb or adjective) in the spine |

The data holds no English. Glosses, lemmas and morphology are in the spine release, keyed by the morpheme keys (`<id>` plus a part
digit); join them from there.

## Sources and licence

| Part | Source | Licence |
|---|---|---|
| Segmentation (`key`, segment order, which words) | Hebrew Bible Clause Layout @LAYOUT_TAG@, bcv-commons: MACULA's clauses cut at word and verse boundaries | CC BY 4.0 |
| Clause kinds and rules, words, surfaces, content flags | MACULA Hebrew (Clear Bible / Biblica), through the lexeme spine | CC BY 4.0 |
| This compilation | bcv-commons | **CC BY 4.0** |

No CC BY-SA part of the clause layout is included: not its `text` (UHB) nor the text-level hierarchy.

**Attribution** when you use this dataset:

> Tanakh Hebrew Clauses, bcv-commons, CC BY 4.0. Segmentation: Hebrew Bible Clause Layout (@LAYOUT_TAG@), bcv-commons, segmentation
> CC BY 4.0. Syntax, words (WLC surfaces) and content flags: MACULA Hebrew, Clear Bible / Biblica (CC BY 4.0).

## Versions

A new layout or spine release gets a new revision of this dataset; a revision is never changed. Pin the revision.

`schema` in `build.json` is the version of the file shape. It is 1 now and goes up only when a field is renamed, dropped or
changes meaning; a new field or new data leaves it unchanged. Such a change is listed here.

## Feedback

Issues and requests: [bcv-commons/bcv-query](https://github.com/bcv-commons/bcv-query/issues).
