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
- **Quotation depth in nine translations** (`shoresh/macula/speaker_votes.py`), votes for nesting: Clear's "alignment-quotations"
  files (Clear-Bible/speaker-quotations, CC BY 4.0, pinned commit b09e308a3a1a) for the CSB, ESV, HCSB, LEB, NASB 1977 and 1995,
  NIV 1984 and NRSV (the depth of each MACULA word, projected from the translation's quotation marks through the alignment; numbers
  only, no English text), and the BSB Translation Tables (public domain, sha256 09bbee6f9fe4…), the BSB's quotation marks on each
  Hebrew word.
- **Participant references:** MACULA's `participantref` / `subjref` (CC BY 4.0, from `macula-spine.db`), to name a nested speaker
  through "I".
- **The Hebrew text, its words and syntax:** MACULA Hebrew (CC BY 4.0), the clause layout built from it, the English names of
  biblical persons from `resources/proper_nouns` (TIPNR, CC BY 4.0).

The layer is CC BY 4.0. Keep the attribution to Clear Bible, Inc. and, for the names, to SIL / FCBH (MIT).

## Files (build output)

- `quotations.tsv`: one row per quotation: `id`, `level` (1 = outermost), `parent`, `speaker` (English, Glyssen's names where
  possible), `speaker_hebrew` (the inquit's subject as MACULA lemmas, nested quotations), `divine`, `quote_type`, `basis` (`block`,
  `referent`, `character`, `correction`: from the speaker data; `layout`: from the clause layout), `first` / `last` (MACULA word keys),
  `from` / `to` (verses, Hebrew numbering), `start_fit` / `end_fit` (how the edges fit the clause segments), `pieces`, `inquit`.
- `segments/<BOOK>.tsv`: per clause segment: its innermost quotation, its level, speaker, the share of its words in the quotation, and
  its `frame` (the speaker of a text that is speech from its start, the psalms).
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
   - a quotation that ends on an inquit ("וַיֹּאמֶר …" as its last line) ends before it (the mirror of the first refinement);
   - Glyssen's "Implicit" pieces are one speech: a quotation that touches the one before it with no inquit between and carries a
     voice implied in it is part of it (Moses' speeches in Deuteronomy alternate Moses and God verse by verse in the source; as one
     speech of Moses, God's words in it are nested by the votes: the Decalogue, Deut 5:6-21).
3. Nesting. The translations' votes: inside a quotation, a word is nested in a translation when its depth there is greater than the
   translation's usual depth over the quotation's first three segments (the absolute depth is a convention: whether a translation
   quotes Moses' or a prophet's whole speech); a segment's vote is the share of translations nesting its words, where five or more
   have them.
   Inside a quotation, a stretch where the clause layout stands a speech level deeper than at the quotation's start is a
   quotation inside it when the line it hangs on, or the line before it, introduces speech (a verb of saying, "לֵאמֹר", a messenger
   formula) or when most translations nest it too; otherwise it is the layout's depth inside one speech (a vocative "בֶּן־אָדָם", a
   "כִּי" clause of the same saying) and is not a quotation. Where the translations nest its start and then, for two segments or
   more, clearly not, it ends there (the quoted words end and the speaker goes on: Deut 26:10, Gen 24:7). A stretch at the
   quotation's own level that most translations nest is a quotation inside it (`basis` `translations`: a saying quoted in a speech,
   1 Kgs 1:24; God's words in Moses' speeches; a letter, Ezra 5:7-17; the vision's voice, Job 4:17-21); its speaker from an inquit
   right before it, else the one character besides the outer speaker Glyssen gives for the verse, else "I" through MACULA's
   participant references. Also, and a messenger formula inside a quotation ("כֹּה אָמַר X", 2 Kgs 19:20, Josh 24:2, Judg 11:15) opens X's words,
   one level deeper, to the end of the quotation (`basis` `messenger formula`). Its speaker: the outer speaker for an inquit in the first person; God for a divine name in the inquit's
   subject; a person's name (matched to Glyssen's characters for the verse) for a proper noun; "the one addressed" for a second-person
   inquit; "he/she" / "they" when the subject is only in the verb.
   Relayed messages: a messenger formula outside any quotation right before one ("וַיֹּאמֶר יְהוֹשֻׁעַ … כֹּה־אָמַר יְהוָה", Josh 24:2; "וַיִּשְׁלַח
   מֹשֶׁה מַלְאָכִים … כֹּה אָמַר אָחִיךָ יִשְׂרָאֵל", Num 20:14), in the narrative books: the formula line is the messenger's speech (level 1,
   `basis` `relayed message`), and the quotations that follow without a break are the sender's words inside it (level 2, their speaker
   the sender, whatever voice FCBH cast). A speaker who tells messengers what to say ("אִמְרוּ־נָא אֶל־חִזְקִיָּהוּ כֹּה־אָמַר הַמֶּלֶךְ
   הַגָּדוֹל", Isa 36:4, 2 Kgs 18:19) speaks the command at level 1, the formula is what is to be said (level 2), the sender's words
   are inside it (level 3); in the prophets these rules apply to a sender who is not God. A psalm whose title ends with an inquit ("וַיֹּאמַר", Ps 18:2) is a quotation opened by it
   (`basis` `titled psalm`), as in 2 Sam 22.
   Inside a relayed message, a repeated messenger formula ("כִּי־כֹה אָמַר יְהוָה", 2 Kgs 3:17) is the messenger's own line again, at
   level 1, and the sender's words go on after it at level 2. Where the sender's words end before the quoted stretch does, a hand
   correction says so (`sender_last`: Josh 24:14-15 is Joshua's own appeal); "וְעַתָּה" alone is no signal, the sender's words go on
   after it in Judg 11:23, 2 Chr 21:15 and 32:15.
4. The frame: a psalm is its psalmist's speech from its first line (`books.frame_poems`; the name in the title's "לְ" + name, else
   "Psalmist"); a first-person account (a chapter of Ezra or Nehemiah whose own narration is mostly in the first person) is its
   narrator's ("narrator (I)"): Ezra 9 and Neh 13, where the account leads into the narrator's prayer and speech; Ezra 8 and Neh 1-2
   are first-person narrative and have none, by correction. In the prophets, an oracle is God's speech (frame "God") from the line
   after a divine messenger formula ("כֹּה אָמַר יְהוָה") or the word-event formula ("הָיָה דְבַר־יְהוָה אֵלַי") to the next one; it ends
   earlier at prose narrative that the clause layout has outside any speech (Jer 36:4, Isa 37:36). Oracles with no formula (Hosea,
   Joel, Habakkuk, Zephaniah, much of Isaiah) have none. Recorded per segment as `frame`, not as a level, so the levels stay
   comparable with Clear's.
5. Corrections (`corrections.tsv`) last.

## Checks

- Clear's spans against the clause layout's speech structure, per segment (agreement in the report).
- Speakers against Glyssen's characters of the quotation's first verse (English numbering through the bibles verse map).
- The work lists in the report: third-person wayyiqtols inside quotations (a story told, or a quotation running too long),
  quotations without an inquit, first- and second-person verbs outside quotations, speakers Glyssen doesn't list.
- Our own yardstick: unfoldingWord's translationNotes on quotations inside quotations (`figs-quotesinquotes`, CC BY-SA 4.0; 647 OT
  verses; used to measure, not as input): the share of those verses where the layer nests (a frame counted as a level). v0.7: 54%;
  v0.8: 82% (narrative 88%, law 72%, prophecy 74%, wisdom 88%).
- bsb-add-books checks the layer against BHSA's clause text types (narrative / quotation / discourse, with nesting), in figures and
  failures in words only (BHSA is non-commercial and is not used as input). v0.2: in narrative 97.5% of segments agree; quotation starts
  fall where BHSA has one 96% of the time and ends 94%; of the layer's nested quotations, 82% are nested in BHSA too. BHSA treats a text
  that is speech from its start (a psalm, most oracles) as a quotation at its top level; the layer, like Clear, records it as the
  `frame` field. The latest figures, by genre, are in the dataset card (`shoresh/macula/speaker_layer_card.md`).

## Correcting it

Add a row to `corrections.tsv`: the quotation's first word key, the field (`speaker`, `first`, `last` or `drop`), the new value, and
the reason the Hebrew text gives. Every correction needs a reason. A `frame` row, keyed on a chapter's first word, sets that chapter's
frame (empty for none: Ps 1 and 2, a teaching and a discourse with no single speaker from the start). A `sender_last` row, keyed on a
relayed message's formula, gives the last word of the sender's words.

## Releases

`python -m macula.release_speaker_layer --tag vX --out DIR` (in `shoresh/`) packages a build for the dataset
bcv-commons/hebrew-speaker-layer: the card (`shoresh/macula/speaker_layer_card.md`), the files, a reproducible archive and SHA256SUMS.
Nothing is uploaded.
