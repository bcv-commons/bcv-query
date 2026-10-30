---
license: cc-by-4.0
language:
  - grc
pretty_name: Greek New Testament Clause Layout (MACULA Nestle 1904)
tags:
  - bible
  - greek
  - koine
  - syntax
  - clauses
  - new-testament
  - translation
size_categories:
  - 10K<n<100K
configs:
  - config_name: clauses
    default: true
    data_files:
      - split: train
        path: data/clauses.parquet
---

# Greek New Testament Clause Layout

The Greek New Testament (Nestle 1904) one clause segment per line, indented by level: subordinate clauses step in under the
clause they belong to, and speeches step in under the line that introduces them. It is built from the syntax trees of MACULA Greek
and the quotation data of Clear Bible, by rules written down below. It is meant for translators and readers who want to see the
structure of a sentence at a glance, and as a base for comparing the clause structure of translations.

| | |
|---|---|
| Release | **@TAG@**, built @BUILT@ from bcv-query `@COMMIT@` |
| Text | Nestle 1904, as MACULA Greek has it (@WORDS@ words, @BOOKS@ books) |
| Size | @LINES@ lines (clause segments) of @CLAUSES@ clauses; @IN_QUOTE@ lines inside a speech |
| Characters | @CHARACTERS@ people and @GROUPS@ groups (`speaker_id`) over @WITH_ID@ speeches (@GROUP_QUOTES@ spoken by a group, @WITH_MEMBERS@ of them with members in `speaker_members`); @CHAR_NAMED@ people with a proper name (`speaker_name`, on @NAME_QUOTES@ speeches) |
| Changes | v0.6: `speaker_id` agrees with the inquit: a review of @REVIEWED@ speeches (by Claude, an AI model, from the Greek text; each row gives its reason) where the speaker data's label or the inquit found was wrong (Pilate's questions labelled as Jesus', "Ναί" of Matt 17:25 as Jesus', Rom 10:19 "Μωϋσῆς λέγει" as David's); a speech that two or more speak (Ἰάκωβος καὶ Ἰωάνης, οἱ ἀρχιερεῖς καὶ οἱ πρεσβύτεροι) is a group's, with its own id and the ids of its members in the new column `speaker_members`. v0.5: who the speaker is across speeches, as keys: `speaker_id` (one person, one id) and `speaker_name` / `speaker_name_ref` (that person's proper name in the text: Κλεοπᾶς where the inquit says εἷς, Luke 24:18); `speaker` unchanged. v0.4: a speech whose inquit names no one takes its speaker's Greek name from the same speaker's other speeches (`speaker_basis`); `alt_eng` keeps the speaker data's English label only where no Greek name is found. v0.3: speakers named in Greek from the text itself, no English labels. v0.2: the cross-check below, and its one fix (no line ends in a conjunction or question particle) |
| Companion | [Hebrew Bible Clause Layout](https://huggingface.co/datasets/bcv-commons/hebrew-clause-layout), the same idea for the Hebrew Bible |

Matthew 5:1–4 in `layout/MAT.txt`:

```
5:1	    Ἰδὼν δὲ τοὺς ὄχλους
5:1	ἀνέβη εἰς τὸ ὄρος·
5:1	καὶ καθίσαντος αὐτοῦ
5:1	προσῆλθαν αὐτῷ οἱ μαθηταὶ αὐτοῦ·
5:2	    καὶ ἀνοίξας τὸ στόμα αὐτοῦ
5:2	ἐδίδασκεν αὐτοὺς λέγων
5:3	    Μακάριοι οἱ πτωχοὶ τῷ πνεύματι,
5:3	        ὅτι αὐτῶν ἐστιν ἡ βασιλεία τῶν οὐρανῶν.
5:4	    μακάριοι οἱ πενθοῦντες,
5:4	        ὅτι αὐτοὶ παρακληθήσονται.
```

## Files

| File | |
|---|---|
| `data/clauses.parquet` | one row per line, in text order |
| `layout/<BOOK>.txt` | the indented text, one line per row: `chapter:verse`, a tab, four spaces per level, the text |
| `build.json` | the build record: counts, the SHA-256 of the MACULA trees, the MACULA Greek files read for the speakers, and the speaker data |
| `crosscheck/crosscheck.json` | the cross-check against a Hebrew translation (see *Cross-check*), overall and per book |
| `crosscheck/crosscheck-disagreements.tsv` | every pair of words where the two readings disagree, with the Hebrew segments and Greek lines side by side |
| `SHA256SUMS` | SHA-256 of every file |

## The rows

| Column | |
|---|---|
| `book`, `chapter`, `verse` | USFM book code; Nestle 1904's chapter and verse |
| `seg` | the line's number in the chapter (1-based) |
| `text` | the line's Greek text, with MACULA's punctuation |
| `text_depth` | the line's level: what the layout indents by (0 = the margin) |
| `depth` | the clause's depth in MACULA's sentence tree, wrappers and coordinations not counted (see *How a line is made*) |
| `clause` | the clause's id: the MACULA word id of its first word. A clause interrupted by another, or running over a verse break, has several lines |
| `parent` | the id of the clause it belongs to in the tree (empty at the top of a sentence) |
| `kind` | `VC` (with a verb of its own) or `NC` |
| `rule` | MACULA's clause rule, the order of its constituents (`V-O`, `S-V-ADV`, …) |
| `role` | the clause's role in its parent (`adv`, `o`, `s`, …), from the clause or the wrapper around it |
| `via` | the rules of the wrapper and coordination nodes between the clause and its parent (`Conj-CL`, `sub-CL`, `CLaCL`, …) |
| `junction` | MACULA's junction of the clause, where given |
| `sentence` | the MACULA sentence: the word id of its first word. A sentence can run over several verses |
| `quotation` | the innermost speech the line stands in: the word id where it starts in the speaker data; empty in narrative |
| `speaker` | who speaks it, named from the Greek text: the subject of the verb that introduces the speech (Ἰησοῦς, Πέτρος, Στέφανος, μαθητής, ἡγεμών, φωνή), as a lemma; several subjects separated by commas. Empty where the text names no one (a passive γέγραπται, an unnamed "they", a participle) |
| `speaker_ref` | the word ids of the words that name the speaker; a pronoun or an article used as one (ὁ δὲ ἔφη) is followed to the word it refers to |
| `speaker_basis` | where `speaker` comes from: `inquit` (the speech's own inquit), `review` (the review gives the words, where the inquit found is wrong), `same speaker in book` / `same speaker in NT` (the same speaker's usual name from their other speeches, see below; `speaker_ref` then points there); empty where there is no name |
| `alt_eng` | the speaker data's English label, only where `speaker` is empty (@ALT_ENG@ speeches: "scripture", "crowd", "passers by"), so that no name the speaker data gives is lost; empty everywhere else |
| `speaker_id` | who speaks it across speeches: a stable id (`n0009`) for one person or group, the same in every speech they make and in later releases (`speaker` names each speech by its own inquit, so one person can be Πέτρος in one and Σίμων or μαθητής in the next). A person with a proper name has one id across the New Testament; a group or person without one ("crowd", "someone") one per book. Empty for a speaker the speaker data names no one by |
| `speaker_name` | that person's proper name as the text gives it (MACULA lemma; θεός for God): Ἰησοῦς, Πέτρος, Κλεοπᾶς; empty where the text of that book gives none (the blind men of Matt 20:30) |
| `speaker_members` | for a group's speech: the `speaker_id`s of its members who speak on their own in the same book (Ἰάκωβος, Ἰωάννης); empty for one person's speech and for members who never speak alone |
| `speaker_name_ref` | the word id of a word that gives that name: the speech's own inquit where it does, else the nearest speech's that does (in the same book first), else a word a hand table gives (Luke 24:18 ὀνόματι Κλεοπᾶς) |
| `inline` | clauses written on this line though they are clauses of their own (participles, see the rules) |
| `split_at_quotation` | the line was broken off its clause where a speech starts or ends (see the rules) |
| `first`, `last`, `words` | MACULA word ids (`BBCCCVVVWWW`, as `n…` ids in MACULA's files) |

## How a line is made

A line is a run of words, inside one verse, that belongs to one clause of MACULA's tree. A clause interrupted by an embedded
clause gives two lines; a clause that runs over a verse break gives one line per verse.

**Wrappers and coordinations.** MACULA Greek wraps many clauses in a clause node that holds only the word introducing them (a
conjunction: Conj-CL; a subordinator: sub-CL; ὅτι: that-VP; the article of an articular infinitive: DetCL; a particle: PtclCL; an
adverb such as ὁμοίως: AdvpCL). Such a wrapper is not a level: its words go with the clause they introduce (a postpositive δέ, γάρ,
οὖν stays after that clause's first word). A coordination of clauses (CLaCL, Conj3CL, …) is not a level either: its clauses are
siblings; a short member that MACULA puts straight into the coordination (ἀλλὰ ὁ ἀνήρ) is a line of its own at their level. A clause
of a vocative alone (Κύριε,) keeps its line and adds no level.

**Rules.** Each is anchored on a kind of expression, never on a place:
- A bare articular participle (the article and the participle, μή at most: οἱ πενθοῦντες) is a noun phrase in the line, not a line;
  so is a participle modifying a noun when the noun's line is nothing but that noun phrase (φωνὴ βοῶντος ἐν τῇ ἐρήμῳ). A participle
  with words of its own after a longer line keeps its line (τοῖς ἁγίοις / τοῖς οὖσιν ἐν Ἐφέσῳ). (@INLINE@ participles.)
- A preposition, conjunction, negation or ascensive καί that ends a line goes with the clause below it that follows, which it
  governs or introduces (εἰς τὸ φαγεῖν). Such a word, and the question particles οὐχί and μήτι, never ends a line inside a verse
  (ἵνα ἀγαπῶμεν ἀλλήλους; Κύριε, / οὐχὶ καλὸν σπέρμα…).
- No line is function words alone (ἀλλὰ, οὐ γὰρ, καὶ ἰδοὺ, a relative pronoun): such words go with the line they introduce. A short
  question (τί γάρ;) stays a line.
- A line breaks where a speech starts or ends inside it (ὁ δὲ ἔφη / Ἄνδρες ἀδελφοί…, Acts 7:2), at the start of the phrase the break
  falls in (@SPLIT@ lines).

**Levels (`text_depth`).** Inside a sentence the levels are the tree's. Every speech of the speaker data is a level too: its lines
stand at least one level in from the line that introduces it, and none goes further out while it lasts, also over the many
sentences of a long speech (Matthew 5:3–7:27 stay in from 5:2 "λέγων"). A speech inside a speech is one further in; a speech that
follows another directly (no introducing line) stands where that one stands. Two speeches of one speaker with only a few verbless
words between them are one (@JOINED@ joins; the speaker data leaves Luke 1:74 out of Zechariah's song). @GREEK_SPEAKERS@ of the @QUOTATIONS@ speeches have a speaker named from the text (@BY_INQUIT@ by their own inquit). A speech
whose inquit names no one (a quotation of scripture, a speech that goes on after a narrator's aside) takes the name of the same
speaker from their other speeches: the speaker data's label decides only who it is, the name comes from the Greek there. The name is
the speaker's usual one in the book (most of that speaker's named speeches there, at least two), else in the New Testament, and must
be a proper name or θεός, and mostly this speaker's. The speaker data's own labels for who speaks are in
English; they decide only who a speaker is and are not in the data (except `alt_eng`). **Characters:** each label gets a stable
id, kept in a table in the repository (`resources/speaker_quotations/nt_characters.tsv`, not released: its labels are English);
two labels of one person share an id (Jesus, Jesus (child)), and God, Moses, David and Solomon, who speak in quotations of scripture
across many books, have one id each. The name (`speaker_name`) is the proper name or θεός that more than half of the person's
speeches named by a proper name, and at least a third of those named at all, are named by in their own inquit, and that no other
person is named by more than three times as often; where no inquit names a person the text names elsewhere in the book, the table
gives the word that does (@HAND@ people: Κλεοπᾶς, Γαβριήλ, Στέφανος, θεός for God, whose inquits are mostly φωνή or γραφή).
Narrators get no name. **Review and groups:** where the label or the inquit found is wrong, a row in
`resources/speaker_quotations/nt_review.tsv` sets the speech's label or the words that name its speaker, with the reason in the
Greek text (@REVIEWED@ speeches). The inquit decides who speaks: a quotation of scripture is the speaker its inquit names (Ἠσαΐας
λέγει; τὸ ῥηθὲν ὑπὸ Κυρίου διὰ τοῦ προφήτου is God's), and a speech whose inquit names two or more is a group's: its id stands for
that set of names (one id across the New Testament where all are proper names, else one per book), it has no `speaker_name`, and
`speaker_members` lists its members' own ids. Last, a line steps in one
level at a time: where the tree has a level with no line of its own, deeper lines move out to one in from the line above, keeping
the order of the levels.

Lines per level: @DEPTHS@.

## What it does not do (yet)

- No text-level hierarchy between sentences beyond the speeches: a paragraph's sentences all start at the margin of their speech.
- Where MACULA's tree or the speaker data differs from a reading you'd expect, the layout follows them (the speaker data has no
  quotations inside a parable's speakers, so in Matt 13:27 the servants' second question stands at the parable's level): Rev 4:8 "ὁ ἦν" stands one
  level deeper than "καὶ ὁ ὢν καὶ ὁ ἐρχόμενος"; John 4:9 "οὐ γὰρ συνχρῶνται Ἰουδαῖοι Σαμαρείταις" is inside the woman's words; Acts
  7:7 "ὁ Θεὸς εἶπεν" is inside Stephen's quotation of God. @NO_CLAUSE@ lines have no clause in MACULA (titles such as Matt 1:1).
- Not checked by hand beyond reading passages from each kind of book; the cross-check below compares it with an independent
  reading.

## Cross-check

The layout was compared with an independent reading of the same text: the clause segments of Salkinson–Ginsburg's Hebrew New
Testament as given by a tagger trained on the Old Testament alone ([@CC_ANALYSIS@](https://huggingface.co/datasets/bcv-commons/hebrew-nt-analysis)),
joined to the Greek words through the alignment
[@CC_ALIGNMENTS@](https://huggingface.co/datasets/bcv-commons/alignments-by-id) (links of class `kept`, 25 of 25 right in its hand
check). Neither reading uses the alignment, nor the other. The unit is a pair of neighbouring Hebrew words whose Greek words are
known: are they in one clause segment in Hebrew, and on one line here? @CC_PAIRS@ pairs.

| | |
|---|---|
| Pairs where both readings agree | **@CC_AGREE@** |
| Hebrew segment boundaries that are also line breaks here | @CC_P@ |
| Line breaks here that are also Hebrew boundaries | @CC_R@ |
| Boundary F1 | @CC_F1@ |

This is agreement between two readings, not accuracy. Most of the @CC_DISAGREE@ disagreeing pairs are the translation: Salkinson
often makes a clause where the Greek has a phrase (Rev 9:11 adds "הוּא מַלְאַךְ"; Eph 2:8 renders διὰ πίστεως "עֵקֶב אֱמוּנַתְכֶם") or
renders a participle as a finite clause, so the letters with the densest participle and noun style agree least. Reading the
disagreements found one fault of the layout, fixed in v0.2: a conjunction or question particle ending a line (Matt 13:27 "Κύριε,
οὐχὶ / καλὸν σπέρμα"). The full list is in `crosscheck/`.

| Book | Pairs | Agree | Boundary F1 |
|---|---|---|---|
@CC_BOOKS@

## Sources and licence

| Part | Source | Licence |
|---|---|---|
| Greek text, clauses, sentence trees | MACULA Greek (Clear Bible / Biblica), `Nestle1904/lowfat`, through trees-macula.db (SHA-256 `@TREES_SHA@…`) | CC BY 4.0 |
| Where speeches run | MACULA Quotation and Speaker Data (Clear Bible), as `resources/speaker_quotations` in bcv-query (SHA-256 `@SPEAKERS_SHA@…`); used for its word spans, and to tell whether two speeches next to each other have one speaker (to join them over a gap); its names are not used | CC BY 4.0 |
| Who speaks | MACULA Greek's subject and referent links (`Nestle1904/lowfat`, SHA-256 `@LOWFAT_SHA@…`) | CC BY 4.0 |
| The layout | bcv-commons | **CC BY 4.0** |
| The code (`macula/build_nt_clause_layout.py`, bcv-query) | bcv-commons | MIT |

**Attribution** when you use this dataset:

> Greek New Testament Clause Layout (@TAG@), bcv-commons, CC BY 4.0. Text and syntax: MACULA Greek, Clear Bible / Biblica (CC BY 4.0).
> Speeches: MACULA Quotation and Speaker Data, Clear Bible (CC BY 4.0).

## Feedback

Issues and requests: [bcv-commons/bcv-query](https://github.com/bcv-commons/bcv-query/issues). Please name the chapter and verse, the
line, and what you expected.
