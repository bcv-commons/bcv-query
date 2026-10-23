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
| `build.json` | the build record: counts, the MACULA trees' and the speaker data's SHA-256 |
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
| `speaker` | that speech's speaker, as the speaker data names them |
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
  governs or introduces (εἰς τὸ φαγεῖν).
- No line is function words alone (ἀλλὰ, οὐ γὰρ, καὶ ἰδοὺ, a relative pronoun): such words go with the line they introduce. A short
  question (τί γάρ;) stays a line.
- A line breaks where a speech starts or ends inside it (ὁ δὲ ἔφη / Ἄνδρες ἀδελφοί…, Acts 7:2), at the start of the phrase the break
  falls in (@SPLIT@ lines).

**Levels (`text_depth`).** Inside a sentence the levels are the tree's. Every speech of the speaker data is a level too: its lines
stand at least one level in from the line that introduces it, and none goes further out while it lasts, also over the many
sentences of a long speech (Matthew 5:3–7:27 stay in from 5:2 "λέγων"). A speech inside a speech is one further in; a speech that
follows another directly (no introducing line) stands where that one stands. Two speeches of one speaker with only a few verbless
words between them are one (@JOINED@ joins; the speaker data leaves Luke 1:74 out of Zechariah's song). Last, a line steps in one
level at a time: where the tree has a level with no line of its own, deeper lines move out to one in from the line above, keeping
the order of the levels.

Lines per level: @DEPTHS@.

## What it does not do (yet)

- No text-level hierarchy between sentences beyond the speeches: a paragraph's sentences all start at the margin of their speech.
- Where MACULA's tree or the speaker data differs from a reading you'd expect, the layout follows them: Rev 4:8 "ὁ ἦν" stands one
  level deeper than "καὶ ὁ ὢν καὶ ὁ ἐρχόμενος"; John 4:9 "οὐ γὰρ συνχρῶνται Ἰουδαῖοι Σαμαρείταις" is inside the woman's words; Acts
  7:7 "ὁ Θεὸς εἶπεν" is inside Stephen's quotation of God. @NO_CLAUSE@ lines have no clause in MACULA (titles such as Matt 1:1).
- Not checked by hand beyond reading passages from each kind of book. A cross-check against a Hebrew translation of the New
  Testament ([hebrew-nt-analysis](https://huggingface.co/datasets/bcv-commons/hebrew-nt-analysis)) is planned.

## Sources and licence

| Part | Source | Licence |
|---|---|---|
| Greek text, clauses, sentence trees | MACULA Greek (Clear Bible / Biblica), `Nestle1904/lowfat`, through trees-macula.db (SHA-256 `@TREES_SHA@…`) | CC BY 4.0 |
| Speeches and speakers | MACULA Quotation and Speaker Data (Clear Bible), with character names from SIL Glyssen `CharacterVerse.txt`, as `resources/speaker_quotations` in bcv-query (SHA-256 `@SPEAKERS_SHA@…`) | CC BY 4.0; Glyssen MIT |
| The layout | bcv-commons | **CC BY 4.0** |
| The code (`macula/build_nt_clause_layout.py`, bcv-query) | bcv-commons | MIT |

**Attribution** when you use this dataset:

> Greek New Testament Clause Layout (@TAG@), bcv-commons, CC BY 4.0. Text and syntax: MACULA Greek, Clear Bible / Biblica (CC BY 4.0).
> Speeches: MACULA Quotation and Speaker Data, Clear Bible (CC BY 4.0), with character data from SIL Glyssen (MIT).

## Feedback

Issues and requests: [bcv-commons/bcv-query](https://github.com/bcv-commons/bcv-query/issues). Please name the chapter and verse, the
line, and what you expected.
