# Hebrew speaker layer

Who speaks where in the Hebrew Bible, on MACULA Hebrew's words and on the clause segments of the clause layout
(`shoresh/macula/data/clause-layout`). A layer of its own: it is refined and checked here first, and goes into the clause layout only
after that. Built by `shoresh/macula/build_speaker_layer.py` into `shoresh/macula/data/speaker-layer/` (not tracked); this folder holds
what is tracked: the corrections and this description.

## Sources and licence

- **Quotations and speakers:** Clear's "MACULA Quotation and Speaker Data" (© 2023 Clear Bible, Inc., CC BY 4.0,
  https://github.com/Clear-Bible/speaker-quotations): quotation spans with their speakers, projected from an English translation's
  quotation marks onto MACULA's Hebrew words through the alignment. Here as in `resources/speaker_quotations` (one speaker per
  quotation).
- **Character names per verse:** Glyssen `CharacterVerse.txt` (© 2014-2020 SIL LSDev and Faith Comes By Hearing, MIT,
  https://github.com/sillsdev/Glyssen), for checking speakers and naming the speakers of nested quotations.
- **The Hebrew text, its words and syntax:** MACULA Hebrew (CC BY 4.0), the clause layout built from it, the English names of
  biblical persons from `resources/proper_nouns` (TIPNR, CC BY 4.0).

The layer is CC BY 4.0. Keep the attribution to Clear Bible, Inc. and, for the names, to SIL / FCBH (MIT).

## Files (build output)

- `quotations.tsv`: one row per quotation: `id`, `level` (1 = outermost), `parent`, `speaker` (English, Glyssen's names where
  possible), `speaker_hebrew` (the inquit's subject as MACULA lemmas, nested quotations), `divine`, `quote_type`, `basis` (`block`,
  `referent`, `character`, `correction`: from the speaker data; `layout`: from the clause layout), `first` / `last` (MACULA word keys),
  `from` / `to` (verses, Hebrew numbering), `start_fit` / `end_fit` (how the edges fit the clause segments), `pieces`, `inquit`.
- `segments/<BOOK>.tsv`: per clause segment: its innermost quotation, its level, speaker, and the share of its words in the quotation.
- `report.md`: the figures and the work lists of doubtful places.

## How it is made

1. Clear's spans on MACULA's word keys (a word part MACULA doesn't have goes to the nearest token of the same word).
2. Refinements, each counted in the report:
   - a quotation that starts on its own inquit ("וַתֹּאמֶר", "לֵאמֹר") starts after it;
   - an edge inside a clause segment that only leaves out a prefix, particle or suffix ("הֲ", "וְ", the article, "כִּי", "הִנֵּה", the
     object marker, a pronoun suffix: the English word order put the quotation mark there) moves to the segment's edge; a start after an
     inquit in the same segment moves to the next segment;
   - pieces of one speech are joined: the next span of the same speaker, with nothing between them but a speaking formula;
   - in the narrative books, a stretch the clause layout has as speech, with no Clear quotation and a first- or second-person verb, is
     added as a quotation (`basis` `layout`), its speaker read from its inquit; not in the first-person memoirs of Ezra and Nehemiah
     (`books.memoirs`), where "I" is the narrator;
   - in the narrative books (not those whose narrator speaks in the first person), a run outside quotations in which at least three
     verses speak in the first or second person is a song or speech (`basis` `voice`; 1 Chr 16:8-35, David's psalm), its speaker from the
     nearest frame before it with a named subject.
3. Nesting: inside a quotation, a stretch where the clause layout stands a speech level deeper than at the quotation's start is a
   quotation inside it. Its speaker: the outer speaker for an inquit in the first person; God for a divine name in the inquit's
   subject; a person's name (matched to Glyssen's characters for the verse) for a proper noun; "the one addressed" for a second-person
   inquit; "he/she" / "they" when the subject is only in the verb.
4. Corrections (`corrections.tsv`) last.

## Checks

- Clear's spans against the clause layout's speech structure, per segment (agreement in the report).
- Speakers against Glyssen's characters of the quotation's first verse (English numbering through the bibles verse map).
- The work lists in the report: third-person wayyiqtols inside quotations (a story told, or a quotation running too long),
  quotations without an inquit, first- and second-person verbs outside quotations, speakers Glyssen doesn't list.
- bsb-add-books checks the layer against BHSA's clause text types (narrative / quotation / discourse, with nesting), in figures and
  failures in words only (BHSA is non-commercial and is not used as input). v0.2: in narrative 97.5% of segments agree; quotation starts
  fall where BHSA has one 96% of the time and ends 94%; of the layer's nested quotations, 82% are nested in BHSA too. BHSA treats a text
  that is speech from its start (a psalm, most oracles) as a quotation at its top level; the layer, like Clear, doesn't (yet).

## Correcting it

Add a row to `corrections.tsv`: the quotation's first word key, the field (`speaker`, `first`, `last` or `drop`), the new value, and
the reason the Hebrew text gives. Every correction needs a reason.
