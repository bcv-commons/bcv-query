# speaker_quotations — who speaks where (S1)

Roadmap **S1** (speaker / red-letter index). Every biblical quotation projected
onto its **speaker**, as a flat verse-range table. *Who says what, where.*

Powers speaker-scoped retrieval — "what did **Jesus** say about X" (red-letter),
"**God's** promises", "the words of **Paul**" — by intersecting a speaker's ranges
with the passage scheme the index already uses (`passage_refs`, BBCCCVVV).

## File
`speaker_quotations.tsv` — one row per quotation span (one word span of the source).

## Schema
| column | meaning |
|---|---|
| `speaker` | FCBH character (e.g. `God`, `Jesus`, `Moses`, `Paul`) |
| `alt_speaker` | secondary speaker when ambiguous (often empty) |
| `start_bbcccvvv` / `end_bbcccvvv` | the verses of the quoted words, BBCCCVVV in English numbering (= `passage_refs` scheme) |
| `word_start` / `word_end` | first and last quoted word, MACULA word ids (`o…` Hebrew/Aramaic, `n…` Greek) |
| `start_partial` / `end_partial` | `Y` if the span covers only part of its first / last verse (e.g. "And God said" before the quote), `N` if the whole verse, empty if not known |
| `quote_type` | FCBH quote type (`Normal`, …) |
| `delivery` | FCBH delivery (often empty) |
| `divine` | `Y` if the speaker is divine (God / Jesus / Holy Spirit) — the **red-letter** flag |
| `block_speaker` | FCBH's speaker for the whole quote block (the source's `SPEAKER (FCBH)`) |
| `speaker_basis` | how `speaker` was chosen: `block` (= `block_speaker`), `referent`, `character` or `correction` (see below) |

Sorted by `start_bbcccvvv`, then `word_start`, then `speaker`. **7,305 spans, 965 speakers, 2,945 divine;
5,807 spans cover only part of their first or last verse; 217 speakers from the referent, 39 from the character.**

## Speaker per quotation
FCBH gives one speaker per quote block, so in a dialogue both sides got the same speaker (Gen 22:11 "Here I am" was the
angel's; 1 Sam 3:6 Samuel's answer was God's). Each span now gets its own speaker:
- `referent`: Clear's `SPEAKER REFERENT` (a MACULA word before the quotation) is a proper name or a name of God, and exactly
  one character that Glyssen's `CharacterVerse.txt` lists as speaking in the verse (quote type Normal, Dialogue, Quotation
  or Implicit) has that name, and it is not the block's speaker. "Potential" and other possible speakers are left out:
  there the referent is often the person addressed (Jer 15:20, 20:10).
- `character`: the block speaker is only FCBH's casting voice for one character in the verse (Glyssen's default character),
  e.g. `Jesus` for `Yahweh's angel` (17 spans; the angel is not flagged divine) or `Good Priest` for `expert in religious law`.
- `correction`: a hand correction from `corrections.tsv`, only where the Hebrew/Greek text itself settles who speaks; each
  row gives its reason (1 so far: Gen 16:8, the angel's question to Hagar, which the source's block gave to Hagar). Top speakers: God, Jesus, Moses, David, Jeremiah.

## Anchor & granularity
Word span: the source's `CLEAR START`/`CLEAR END` (MACULA word ids). Its verses are mapped from MACULA's numbering
(Hebrew numbering in the OT) to English with bibles' `org-to-eng` map (via `shoresh/vrsmap.py`); a Psalm title counts
as verse 1. `start_partial`/`end_partial` compare the span with its verse's first and last word in shoresh's MACULA
word table (on the MACULA verse). 25 NT rows without word ids keep the FCBH quote block's verse range.

Served by shoresh at `/speakers`, `/speaker/{name}` and `/speakers/at/{book}/{chapter}/{verse}` (each hit with
`partial` for the asked verse), each response with a `source` block (attribution, licence, method).

**Method caveat:** the spans come from quotation marks in aligned English translations, projected onto the
Hebrew/Greek words. They are not derived from the original-language text itself.

## Source / license
Built from **[Clear-Bible/speaker-quotations](https://github.com/Clear-Bible/speaker-quotations)**
(`Clear-Aligned-Projections.tsv`, the translation-independent consensus, +
`character_detail.semantic_data.tsv` for the divine flag) by
`bcv-RAG/scripts/build_speaker_quotations.py` (re-derivable; fetches from GitHub).

> MACULA Quotation and Speaker Data, © 2023 by Clear Bible, Inc — **CC-BY-4.0** —
> https://github.com/Clear-Bible/speaker-quotations/

It includes FCBH character data from SIL Glyssen (MIT). The per-quotation speaker also reads Glyssen's
`CharacterVerse.txt` (Copyright (c) 2014-2020 SIL LSDev and Faith Comes By Hearing, MIT, https://github.com/sillsdev/Glyssen). The source's `sources.md` states that every input was
CC BY or CC BY-SA at the time of use.
