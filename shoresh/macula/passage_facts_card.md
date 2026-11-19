---
license: cc-by-sa-4.0
language:
  - hbo
  - arc
  - grc
pretty_name: Passage Facts
tags:
  - bible
  - hebrew
  - greek
  - speech
  - poetry
  - discourse
size_categories:
  - 10K<n<100K
---

# Passage Facts

Who is heard in a passage, what kind of speech it is, and how the text is set (song, poetic lines, prose), for the whole Bible. Each
fact is tied to exact words of the Hebrew or Greek text (MACULA word ids) and names its source and licence, so that it can be carried
through word alignments into any translation.

No fact is a model's reading of the text. A fact is a source's own value (`b.source`), read from the Hebrew or Greek grammar by a
fixed rule (`b.text`), inferred by a published rule from other facts (`b.rule`), or set by a review row (`b.review`).

| | |
|---|---|
| Built | @BUILT@ by `macula/build_passage_facts.py` (bcv-query `@CODE@`) |
| Size | 66 books, @FACTS@ facts (@SA_FACTS@ of them CC BY-SA 4.0); CC BY subset: @BY_FACTS@ facts |
| Schema | @SCHEMA@ (see *Versions*) |

## Files

| Path | What it holds |
|---|---|
| `data/<BOOK>.jsonl` | **all facts** of a book, one JSON object per line. Licence of the whole: CC BY-SA 4.0 |
| `data-cc-by/<BOOK>.jsonl` | **only the facts of sources that are not share-alike**. Licence: CC BY 4.0 |
| `codes.tsv` | the decoding table: every code in the data, with its English meaning, its source, and notes |
| `sources.tsv` | the sources: licence, share-alike or not, enabled or not, attribution wording, what each gives |
| `mood_families.tsv` | the mood families: Hebrew and Greek head words, the SDBH and Louw-Nida domains and lemmas that mark each |
| `build.json` | sources used, input hashes and pins, counts per book, and `checks`: how well each source landed on the words |
| `SHA256SUMS` | the sha256 of every file |

## A fact

```json
{"id": "EXO.00001", "kind": "quote", "value": "qt.normal", "first": "020010090041", "last": "020010100192", "ref": "EXO 1:9-10",
 "basis": "b.source", "precision": "p.word", "src": ["clear", "layer"], "lic": "CC BY 4.0",
 "level": 1, "quote": "q00503", "found": "qf.block", "speaker": "מֶלֶךְ", "speaker_ref": ["020010080021"], "speaker_by": "sb.inquit",
 "speaker_id": "c0073", "speaker_name": "פַּרְעֹה", "speaker_name_ref": ["020010220021"]}
```

@FIELDS@

The data holds no English. To show a fact in English, look its codes up in `codes.tsv`. Speakers are named by the Hebrew or Greek
words of the text; a `frame` fact gives the verb's lemma.

## What the facts are

@KINDS@

## Sources and licence

@SOURCES@

**Why two folders.** Facts from share-alike sources (unfoldingWord, MAM, the UBS dictionaries) can only be shared under CC BY-SA 4.0,
so `data/`, which holds all facts, is CC BY-SA 4.0 as a whole. Every other fact stays under its own licence (CC BY 4.0, MIT, public
domain), and `data-cc-by/` holds exactly those, under CC BY 4.0. Each fact also says its own licence in `lic`.

**Attribution.** Name this dataset ("Passage Facts, bcv-commons") and the sources of the facts you use, with the wording in the
`attribution` column of `sources.tsv`. For Glyssen's delivery notes keep its MIT copyright notice.

Not included: The Bible Translator's Assistant (All the Word) and OpenText.org. Both are in `sources.tsv` but disabled, because
neither states an open licence.

## How well the sources landed

@CHECKS@

## Versions

A new build gets a new revision; a revision is never changed. Pin the revision. `schema` in `build.json` is the version of the fact
shape. It goes up only when a field is renamed, dropped or changes meaning; a new field, kind or code leaves it unchanged. Codes are
never renumbered. Anchors (`first`, `last`, `pieces`, `lines`, `at`, `after`) are a first version and may follow a link-type
specification later; that would be a schema change, listed here.

- v0.3.3: no English meaning words left in the values. The psalm types are named by Hebrew terms with `head`
  (`fm.gn.qinah` קִינָה, `qinat_tsibbur` קִינַת צִבּוּר, `tehillah` תְּהִלָּה, `todah` תּוֹדָה, `mivtach` מִבְטָח, `chokhmah` חָכְמָה,
  `melekh` מֶלֶךְ, `viduy` וִדּוּי, `tsiyyon` צִיּוֹן, `malkhut` מַלְכוּת, `tefillah` תְּפִלָּה, `qelalah` קְלָלָה, `aliyah` עֲלִיָּה לָרֶגֶל;
  were lament, communal lament, praise, thanksgiving, trust, wisdom, royal, penitential, zion, kingship, prayer, imprecation,
  pilgrimage); same facts. A mood fact's `marks` give a UBS domain as its `sd.*` / `ln.*` code (v0.3.1-2 printed the domain's
  English name). The mood families gain a third, Public Domain kind of mark: the words Metzudat Zion explains with one of a
  family's feeling terms (`mz:כעס`, `mz:יללה` …; `mood_families.tsv` column `commentary_terms`; source `metzudat_zion`).
- v0.3.2: the psalm purposes are named by Hebrew terms with `head`: `fm.pu.qinah` קִינָה (was lament), `fm.pu.tefillah`
  תְּפִלָּה (petition), `fm.pu.tehillah` תְּהִלָּה (praise), `fm.pu.todah` תּוֹדָה (thanks), `fm.pu.mivtach` מִבְטָח (confidence),
  `fm.pu.musar` מוּסָר (instruct). Same facts, new codes.
- v0.3.1: moods by the text's own feeling words. The `md.*` values of v0.3 were the sources' English mood words (Scriptura's
  At-a-Glance, Glyssen's deliveries); from v0.3.1 a mood is one of 9 families named by its Hebrew head word (`md.samach` שָׂמַח,
  `md.bakah` בָּכָה, `md.yare` יָרֵא, `md.aph` אַף, `md.bosh` בּוֹשׁ, `md.batach` בָּטַח, `md.tsarah` צָרָה, `md.ahav` אָהֵב, `md.sane`
  שָׂנֵא), defined in `mood_families.tsv` by UBS domains (SDBH, Louw-Nida) and lemmas, and a mood fact is kept only where Hebrew
  or Greek words in its span mark that family (`marked_by`, `marks`). Mood facts so carry UBS evidence and are CC BY-SA. Scriptura's
  At-a-Glance is now read for all 65 psalms that have it (39 of them from a picture by OCR, `read` picture): sections `sc.part` on
  62 psalms. The Ps 91 purpose (fm.pu) is read.
- v0.3: passage-level facts from three new sources, and the whole Bible's moods by rule. Schema unchanged (new kinds and codes
  only). 70,072 facts (67,718 in v0.2). New: `cue` 285, `link` 604, `mood` 381 (119 from Scriptura, 262 from
  deliveries), `fm.gn.*` 104 on 88 psalms, `fm.pu.*` 46, `sc.part` 85, `sc.np` 722, `nt.key_term` 40, chapter register 22.
  - Psalm types `fm.gn.*` (lament, praise, thanksgiving, trust, wisdom, royal …), read from the Tyndale Open Study Notes'
    introductions by fixed keyword rules, on the whole psalm or on the part the note gives. Every match was read against its
    note by Claude, not by a human. Purpose `fm.pu.*`, sections `sc.part`, moods `md.*`, background links `lk.background` (a psalm
    and a passage its Background Orientation cites) and key terms `nt.key_term` (a Hebrew word it explains) come from Scriptura's
    Psalms: Layer by Layer, a snapshot of 2026-11-18. The site has these pages for 65 psalms, so these facts cover 65 psalms. Only codes and places are stored, never the sources' English. Sources may
    disagree, and each fact stands on its own.
  - Moods beyond the Psalms: a speech whose Glyssen delivery names a feeling (angry, afraid, weeping …) gets that mood, by a
    fixed table (b.rule).
  - New kind `cue`: words that mark a register by their lemma, namely woe, a named lament, אֵיכָה opening Lamentations 1, 2
    and 4, blessing and hallelujah.
  - The chapter register: one delivery code that covers at least 40% of a chapter's words gives a chapter fact (Ezek 19, 27,
    32 lament; 1 Kgs 8, Neh 9 and Jonah 2 praying; Exod 15 and Judg 5 singing).
  - `fm.ms.song` carries `layout` song or list. List is Josh 12 and Esth 9, after b. Megillah 16b.
  - Greek NT paragraphs `sc.np`, from Nestle 1904.
  - MAM alignment corrected: a MAM word joined from two MACULA words, or a name inside a נוסח note, is now matched. Esther 9:7-10
    lists all ten sons. The poetic lines gain 495 words that v0.2 had left out, and none are lost. Verse halves with a gap between
    them fall from 69 to 6, and halves that divide at an oleh-weyored on a joined word now divide after it. Three paragraph
    marks are added: before Exod 34:1 and before Lev 7:22 and 7:28.
  - Left out: unfoldingWord's new psalm introductions with a Purpose line, because they credit Scriptura and would count it
    twice.
- v0.2: two new `form` codes read from the letters by rule: `fm.tx.acrostic` (13 acrostics: Ps 9, 25, 34, 37, 111, 112, 119, 145,
  Prov 31, Lam 1-4, each letter on its verse or poetic line; the broken acrostics of Ps 10 and Nah 1 are not found) and
  `fm.tx.refrain` (449 lines that come back in their chapter); `fm.tx.halves` (every poetic verse of Psalms, Proverbs and Job split
  at its main accent into half A and half B, the couplet, with the lines in each and the words that echo across them by lexeme or
  BDB root); `fm.ps.*` (the psalm headings' terms and סלה, הגיון, הללו יה on their words: 55 for the leader, 57 mizmor, 71 selah, 73
  ascribed to David). Built on the speaker layer v0.16 and the clause layouts v0.37.2 /
  v0.7.1; every other fact is the same as in v0.1 (62,663 facts; 67,718 with the new ones). Schema unchanged (new codes only).
- v0.1: first release.

## Feedback

Issues and requests: [bcv-commons/bcv-query](https://github.com/bcv-commons/bcv-query/issues).
