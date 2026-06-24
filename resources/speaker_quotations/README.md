# speaker_quotations — who speaks where (S1)

Roadmap **S1** (speaker / red-letter index). Every biblical quotation projected
onto its **speaker**, as a flat verse-range table. *Who says what, where.*

Powers speaker-scoped retrieval — "what did **Jesus** say about X" (red-letter),
"**God's** promises", "the words of **Paul**" — by intersecting a speaker's ranges
with the passage scheme the index already uses (`passage_refs`, BBCCCVVV).

## File
`speaker_quotations.tsv` — one row per (speaker, verse-range) quotation span.

## Schema
| column | meaning |
|---|---|
| `speaker` | FCBH character (e.g. `God`, `Jesus`, `Moses`, `Paul`) |
| `alt_speaker` | secondary speaker when ambiguous (often empty) |
| `start_bbcccvvv` / `end_bbcccvvv` | the quotation's verse range, BBCCCVVV (= `passage_refs` scheme) |
| `quote_type` | FCBH quote type (`Normal`, …) |
| `delivery` | FCBH delivery (often empty) |
| `divine` | `Y` if the speaker is divine (God / Jesus / Holy Spirit) — the **red-letter** flag |

Sorted by `start_bbcccvvv`, then `speaker`. **5,938 ranges, 959 speakers, 2,173
divine.** Top speakers: God, Jesus, Moses, David, Jeremiah.

## Anchor & granularity
Verse-range (the projection's `START VS`/`END VS` → BBCCCVVV). Robust and
join-ready — no dependence on aligning the source's MACULA word ids to our spine
word indices. The source's word-level spans (`CLEAR START`/`END`) are a possible
future refinement for word-precise red-lettering.

## Source / license
Built from **[Clear-Bible/speaker-quotations](https://github.com/Clear-Bible/speaker-quotations)**
(`Clear-Aligned-Projections.tsv`, the translation-independent consensus, +
`character_detail.semantic_data.tsv` for the divine flag) by
`bcv-RAG/scripts/build_speaker_quotations.py` (re-derivable; fetches from GitHub).

> MACULA Quotation and Speaker Data, © 2023 by Clear Bible, Inc — **CC-BY-4.0** —
> https://github.com/Clear-Bible/speaker-quotations/
