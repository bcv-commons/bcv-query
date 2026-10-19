# Hebrew speaker layer

Who speaks where in the Hebrew Bible, on MACULA Hebrew's words and on the clause segments of the clause layout
(`shoresh/macula/data/clause-layout`). A layer of its own: it is refined and checked here first, and goes into the clause layout only
after that. Built by `shoresh/macula/build_speaker_layer.py` into `shoresh/macula/data/speaker-layer/` (not tracked); this folder holds
what is tracked: the hand corrections (`corrections.tsv`), the review rows (`review.tsv`), the prophet of each prophetic book
(`prophets.tsv`) and this description.

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
  its `frame` (the speaker of a text that is speech from its start: a psalm's psalmist, a prophetic book's prophet).
- `report.md`: the figures and the work lists of doubtful places.
- `parallels.tsv` (from `macula.speaker_parallels`): where parallel texts differ.
- `_work/` (not released): `evidence.jsonl`, the evidence per segment for the review; `review_unapplied.tsv`, review rows the build
  could not apply (empty when all apply); `review/`, the review's passages and answers.

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
   More nesting rules: a song announced by its inquit ("אֶת־דִּבְרֵי הַשִּׁירָה הַזֹּאת", Deut 31:30) is one quotation of its singer, to the
   narrative where the singer acts again (Deut 32:1-43), with the voices in it nested; a wayyiqtol of saying inside a quotation
   followed by direct speech ("וָאֹמַר", "וַיֹּאמֶר אַסְתִּירָה פָנַי", Deut 32:20) opens a quotation inside it, to the end of its verse
   and on while "I" or "you" in the next verses are the inner speaker or addressee (MACULA's participant references); in a story the
   speaker tells about himself, his next wayyiqtol ends it; the translations' votes also nest a stretch deeper than our level where
   most of them are deeper still (the enemies' words inside God's words inside the Song, Deut 32:27); a nested stretch of the
   layout ends where the outer speaker narrates again in the first person ("וָאֲדַבֵּר אֲלֵיכֶם", Deut 1:43); a quotation inside a
   quotation by a named person ends where that person is named in the third person ("אַל־תִּשְׁמְעוּ אֶל־חִזְקִיָּהוּ", 2 Kgs 18:31). A
   quotation the layout adds goes on through following verses that still speak in the first or second person (Daniel's prayer,
   Dan 9:4-19), and is named through "I" when its inquit names no one.
   Law as a message: a command inside God's speech to say something ("דַּבֵּר אֶל־בְּנֵי יִשְׂרָאֵל … וְאָמַרְתָּ אֲלֵהֶם") opens the
   message, spoken by the one God addresses in the narrative inquit (Moses, Aaron), to the end of God's speech, over chapter breaks
   (Lev 4:2-5:13, Lev 25:2-26:45), where the clause layout restarts each chapter at the margin.
4. The frame: a psalm is its psalmist's speech from its first line (`books.frame_poems`; the name in the title's "לְ" + name, else
   "Psalmist"); a first-person account (a chapter of Ezra or Nehemiah whose own narration is mostly in the first person) is its
   narrator's ("narrator (I)"): Ezra 9 and Neh 13, where the account leads into the narrator's prayer and speech; Ezra 8 and Neh 1-2
   are first-person narrative and have none, by correction. Recorded per segment as `frame`, not as a level.
   The prophets: the frame of a prophetic book is its prophet (`prophets.tsv`, as its heading names him), and God's words are always
   a quotation. A stretch of the book starts after a divine messenger formula ("כֹּה אָמַר יְהוָה") or the word-event formula
   ("הָיָה דְבַר־יְהוָה אֵלַי"), or at a line in the first or second person outside quotations (Hosea, Joel, Isa 1:2-20), and ends at
   prose narrative the clause layout has outside any speech (Jer 36:4, Isa 37:36). Within it, verse by verse, God speaks where "I" is
   God (or an "I" MACULA doesn't resolve, or the verse is partly God's own quotation), the prophet where "I" is someone else
   (Jeremiah's laments) or God is named in the third person with no "I" (Isa 11, 19); a verse with neither keeps the one before;
   the formula lines are the prophet's. God's verses that no quotation of God holds yet become one (`basis` `oracle`), around
   whole quotations only: God's words inside a larger speech (Jeremiah's to the people, Jer 44:24-29) stay in it. God's quotations
   with only a formula line between them are one ("נְאֻם־יְהוָה", "אָמַר יְהוָה", "לָכֵן כֹּה אָמַר יְהוָה" inside God's words, as the
   translations have them). A message God tells the prophet to deliver ("וְאָמַרְתָּ … הָרֵי יִשְׂרָאֵל", Ezek 6:3) is the
   prophet's. So the levels read two ways: levels alone (the book as a text with God's words quoted) or the frame counted as a
   level (the prophet's speech with God's words quoted in it, as unfoldingWord's notes read it).
5. Corrections (`corrections.tsv`), then the review rows (`review.tsv`, below; `--no-review` leaves them out).
6. One structure: the rules keep three records (the quotations, each segment's level, each segment's innermost quotation), and a
   last pass makes them agree. A quotation a rule joined into another or dropped stands for the one that took it in; a quotation
   lying wholly outside its parent goes under the closest one around it; a quotation's level is its depth among its parents; a
   segment names a quotation that holds it at its level, else the deepest one inside the quotation it named, else takes that
   quotation's level. Counted in the report.

## Checks

- The parallel texts (`python -m macula.speaker_parallels`, in `shoresh/`): Samuel-Kings and Chronicles, Isa 36-39 and 2 Kgs
  18-20, Ps 18 and 2 Sam 22 and the others the BSB's section references pair, aligned word by word; the share of matched words at
  the same level and with the same speaker, and the stretches that differ (`parallels.tsv`). Some differences are by design (the
  tabernacle commanded in Exod 25-31 and built in 35-39; the Decalogue in Exod 20 and in Moses' speech, Deut 5).

- Clear's spans against the clause layout's speech structure, per segment (agreement in the report).
- Speakers against Glyssen's characters of the quotation's first verse (English numbering through the bibles verse map).
- The work lists in the report: third-person wayyiqtols inside quotations (a story told, or a quotation running too long),
  quotations without an inquit, first- and second-person verbs outside quotations, speakers Glyssen doesn't list.
- Our own yardstick: unfoldingWord's translationNotes on quotations inside quotations (`figs-quotesinquotes`, CC BY-SA 4.0; 647
  notes on OT verses; used to measure, not as input): the share of those notes where the layer nests somewhere in the verses
  noted (a frame counted as a level). v0.7: 54%; v0.8: 82%; v0.10: 87.0% (narrative 87.5%, law 85.5%, prophecy 87.4%, wisdom
  89.7%), 84.9% without the review rows.
- The parallel texts, v0.10: 77.4% of matched words at the same level, 93.4% with the same speaker.
- bsb-add-books checks the layer against BHSA's clause text types (narrative / quotation / discourse, with nesting), in figures and
  failures in words only (BHSA is non-commercial and is not used as input). v0.2: in narrative 97.5% of segments agree; quotation starts
  fall where BHSA has one 96% of the time and ends 94%; of the layer's nested quotations, 82% are nested in BHSA too. BHSA treats a text
  that is speech from its start (a psalm, most oracles) as a quotation at its top level; the layer, like Clear, records it as the
  `frame` field. v0.9: the prophets at BHSA's exact level in 83% of segments when each is read the way that fits it (levels alone
  or the frame counted), 45% in v0.8; the review rows moved 163 segments closer and 39 farther. The latest figures, by genre, are
  in the dataset card (`shoresh/macula/speaker_layer_card.md`).

## Correcting it

Add a row to `corrections.tsv`: the quotation's first word key, the field (`speaker`, `first`, `last` or `drop`), the new value, and
the reason the Hebrew text gives. Every correction needs a reason. A `frame` row, keyed on a chapter's first word, sets that chapter's
frame (empty for none: Ps 1 and 2, a teaching and a discourse with no single speaker from the start; Daniel for Dan 8-10, his own
account; Nebuchadnezzar for Dan 4, his letter). A `sender_last` row, keyed on a
relayed message's formula, gives the last word of the sender's words.

## The review

`shoresh/macula/speaker_review.py` picks doubtful passages from the build (the translations split; nesting from the layout alone;
God's words the layer made a quotation; parallel texts that differ; unfoldingWord's notes where the layer doesn't nest; unnamed
speakers), writes each as a passage file (the Hebrew per segment with the evidence as numbers: the translations' votes, the
verb, the subject, who "I" is, the markers of speech, Glyssen's characters; no English text, no BHSA) with the conventions the
layer follows (`conventions.md`), and merges the reviewers' answers into `review.tsv` (`--merge`). Reviewers so far: two AI
agents (Claude Opus 5.5) working independently on the same 48 passages, and a third deciding where they differed.

`review.tsv`: one row per change: `first` (the word key it is keyed on), `field` (`speaker`, `first`, `last`, `drop`: the quotation
named in `quotation`, else the one starting at `first`; `add`: a new quotation from `first` to `last` inside `parent`, its speaker
in `value`; `level`: the level of the segments from `first` to `last`; `frame`), `value`, `reason` (from the Hebrew; required),
`last`, `parent`, `source` (`agent:claude-opus-5-5:review-v1`, `+adjudicated` where the third agent decided, `+rekeyed` where a
row was moved to the quotations the build makes now), `confidence`, `quotation`. A `quotation` id that now names another stretch
is not used; an `add` row whose `parent` the rules no longer make goes under the closest quotation around it. The rows the build
can't apply are listed in `_work/review_unapplied.tsv`.

## Releases

`python -m macula.release_speaker_layer --tag vX --out DIR` (in `shoresh/`) packages a build for the dataset
bcv-commons/hebrew-speaker-layer: the card (`shoresh/macula/speaker_layer_card.md`), the files, a reproducible archive and SHA256SUMS.
Nothing is uploaded.
