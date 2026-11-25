---
license: cc-by-sa-4.0
language:
- hbo
- arc
- grc
pretty_name: Passage mood spans (model)
tags:
- bible
- hebrew
- greek
- emotion
- model-generated
---

# passage-mood-spans-model @TAG@

The mood of every chapter of the Bible, and of the spans inside it, against a fixed list of thirteen moods, **as read by
two language models in two independent passes**: pass a `claude-opus-5-5`, pass b `claude-sonnet-5-5` (through Claude
Code's headless mode, 2026-11-24/25). **No human has checked these readings.** Asked by bible-song-builder, for setting
passages to song; the mood list (ids, Hebrew nouns, Strong's numbers, Greek nouns, families) is theirs, revision 5.

## What the readers saw

- The chapter's clause lines in Hebrew (WLC) or Greek (Nestle 1904): the rows of
  [hebrew-clause-lines](https://huggingface.co/datasets/bcv-commons/hebrew-clause-lines) and
  [greek-nt-clause-lines](https://huggingface.co/datasets/bcv-commons/greek-nt-clause-lines) v0.3, numbered, with the
  verse, the quotation id and the speaker.
- `moods_he.toml` (in this dataset): the thirteen moods, each with a Hebrew sentence of what it is and what it is not,
  and the reading rules under `[rules]`: who feels the mood; hatred only where someone in the passage hates; awe
  (yirah) against dread (pachad); strength is rare at 3. The `is` / `not` sentences and the rules are our Hebrew wording
  of theirs. **No English was shown to the readers, and the data holds none.**
- Nothing else: no translation, no commentary, no source notes.

Every row carries `moods_sha` = @MOODS_SHA@, the first 12 hex digits of the sha256 of the `moods_he.toml` they read.

## Data

`data/spans.jsonl`, one row per reading, both passes, in Bible order:

| field | |
|---|---|
| `id` | `<chapter>.<pass><n>` (`.<pass>0` is the chapter row) |
| `chapter`, `book`, `lang` | `GEN.22` (WLC / Nestle numbering), the book code, hbo or grc (Aramaic chapters are under hbo, as in the clause lines) |
| `kind` | chapter (the chapter's own mood) or span |
| `first`, `last` | the first word key of the span's first clause line and the last word key of its last line (MACULA keys; clause-lines rows are found by `first`) |
| `verses` | first and last verse of the span |
| `mood`, `second` | mood ids of `moods_he.toml`; `second` may be null; a chapter row's mood may be `none` |
| `strength` | 1 (a colour), 2 (a clear mood), 3 (the chapter's main mood or a sharp turn; few per chapter) |
| `because` | words copied from the span's own Hebrew or Greek; checked by rule to be words of the span |
| `unit` | the quotation id (clause-lines `quotation`) where the span is one speech, else null |
| `pass`, `model` | a (Opus) or b (Sonnet), and the model |
| `agree` | the other pass has a span with the same mood (as its mood or second) over at least half of this span's lines; for a chapter row, the same chapter mood |
| `other_mood` | chapter rows only: the other pass's chapter mood |
| `moods_sha` | as above |

Disagreeing spans are kept and marked (`agree` false), as bible-song-builder asked.

`data/source_notes.jsonl`: what our sources already say in each chapter, joined by rule and **not shown to the readers**:
the facts of [passage-facts](https://huggingface.co/datasets/bcv-commons/passage-facts) v0.3.4 of kinds mood, cue and
delivery, and the forms fm.ps.* (psalm headings), fm.gn.* (psalm types) and fm.pu.* (purpose). Fields: `chapter`,
`fact` (the passage-facts id), `kind`, `value`, `first`, `last`.

## Figures

@CHAPTERS@ chapters (@LINES@ clause lines), each read by both passes.

| | pass a (Opus) | pass b (Sonnet) |
|---|---|---|
| spans | @A_SPANS@ | @B_SPANS@ |
| agree with the other pass | @A_AGREE@ | @B_AGREE@ |
| strength 3 / 2 / 1 | @A_STR@ | @B_STR@ |
| spans refused by the check (not in the data) | @A_REF@ | @B_REF@ |

The two passes give the same chapter mood in @CH_AGREE@ chapters.

Spans per mood (as `mood`):

| mood | pass a | pass b |
|---|---|---|
@MOOD_ROWS@

## Licence and sources

CC BY-SA 4.0, as the clause lines and passage-facts it is read from. Text and word keys: MACULA Hebrew and Greek (CC BY
4.0), WLC and Nestle 1904 (public domain). Mood list: bible-song-builder. Model output: Anthropic,
`claude-opus-5-5` and `claude-sonnet-5-5`.

## Provenance

Code @CODE@: `shoresh/macula/mood_spans.py` (prepare, check, compare), `release_passage_mood_spans_model.py`. Each batch
of about 3,000 lines was read by one headless session per pass; a check refused rows that broke a rule (an unknown mood,
a span outside the chapter, `because` words not in the span, a `unit` not in the span) and failed a batch where more
than 40% of spans (30% in the first batch) had strength 3. The run reported USD @COST_A@ (pass a) and USD @COST_B@ (pass
b) at API prices.
