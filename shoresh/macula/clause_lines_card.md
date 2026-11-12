---
license: cc-by-sa-4.0
language:
  - @LANG_CODE@
pretty_name: "@LANG_NAME@ Clause Lines"
tags:
  - bible
  - poetry
  - clauses
  - speech
---

# @LANG_NAME@ Clause Lines (@TAG@)

The clause segments of [@LAYOUT@](https://huggingface.co/datasets/@LAYOUT@), cut where a poetic line starts inside a segment, with
facts from share-alike sources on each line. It is the share-alike companion of the clause layout. Use the layout itself where you need
CC BY 4.0.

| | |
|---|---|
| Built | @BUILT@ by `macula/build_clause_lines.py` (bcv-query `@CODE@`) |
| Rows | @ROWS@ lines from @SEGMENTS@ segments; @CUT@ segments are cut into two or more lines |
| Line starts | @MAM@ from Miqra according to the Masorah, @ULT@ from the unfoldingWord Literal Text |
| Licence | CC BY-SA 4.0 |

## Files

| Path | What it holds |
|---|---|
| `data/lines-<BOOK>.parquet` | one row per line, in text order |
| `codes.tsv`, `sources.tsv` | the decoding table of every code, and the sources with their licences (from bcv-commons/passage-facts) |
| `build.json` | inputs, counts, `schema` |
| `SHA256SUMS` | the sha256 of every file |

## A row

Every field of the layout row it is cut from, the fields its release adds (speaker, `force`, `you`, ...), with `words`, `first`,
`last` and `text` of the line itself. Then:

| Field | Meaning |
|---|---|
| `line` | 1, 2, ... for the lines of one segment; 1 where the segment is not cut |
| `line_source` | `mam` or `ult` where a poetic line starts at this row's first word; null where it does not |
| `line_marker` | that line's marker: MAM `v` (starts the verse), `r0`–`r4` (MAM's line templates ר0–ר4: the level of the line), `s` (a line of a song); ULT `q1`, `q2`, ... (its indent level) |
| `notes` | unfoldingWord Translation Notes on these words, as codes `tn.<article>`: the translation issue each note names (rhetorical question, metaphor, parallelism, ...). Not the note's English text |
| `domain` | the meaning domain of a speech's introducing verb, where it stands in this line: `sd.*` (SDBH) or `ln.*` (Louw-Nida) |
| `para_end_mam` | Hebrew: `sc.pe` / `sc.sa` where a MAM paragraph (Aleppo Codex tradition) ends in this line; `para_end` is the Leningrad Codex mark |

Line starts come from MAM where MAM sets the verse in lines (the songs; Psalms, Proverbs, Job). In other verses they come from the ULT,
placed on the Hebrew or Greek words by the ULT's own word alignment. A segment that no line starts inside stays one row. The segments,
their keys and the text-level hierarchy are those of the layout; only the cut is new. The data holds no English: look codes up in
`codes.tsv`.

## Sources and licence

| Part | Source | Licence |
|---|---|---|
| Segments, hierarchy, speaker, `force`, `you`, `para_end`, `printed` | @LAYOUT@ (its card lists its own sources) | CC BY 4.0 / CC BY-SA 4.0 |
| Poetic lines (Hebrew) | Miqra according to the Masorah (MAM), MAM-parsed plus, MAM-basics commit cfdbb64e | CC BY-SA 4.0 |
| Poetic lines elsewhere, `notes` | unfoldingWord Literal Text and Translation Notes, release v91 | CC BY-SA 4.0 |
| `domain` | UBS Dictionary of Biblical Hebrew (SDBH), UBS Dictionary of the Greek NT (Louw-Nida), ubs-open-license commit 33dcc8c6 | CC BY-SA 4.0 |
| The cut and the code | bcv-commons | CC BY-SA 4.0 / MIT |

**Attribution:**

> @LANG_NAME@ Clause Lines (@TAG@), bcv-commons, CC BY-SA 4.0. Clause layout: @LAYOUT@, bcv-commons. Lines: Miqra according to the
> Masorah (CC BY-SA 4.0) and unfoldingWord Literal Text (CC BY-SA 4.0). Notes: unfoldingWord Translation Notes (CC BY-SA 4.0). Domains:
> UBS Dictionaries (CC BY-SA 4.0). Syntax: MACULA, Clear Bible / Biblica (CC BY 4.0).

## Versions

Pin a tag. `schema` in `build.json` goes up only when a field is renamed, dropped or changes meaning. A new layout release, or new
releases of MAM or unfoldingWord, give a new tag.

## Feedback

Issues and requests: [bcv-commons/bcv-query](https://github.com/bcv-commons/bcv-query/issues).
