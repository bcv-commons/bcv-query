# Passage facts

Who is heard in a passage, what kind of speech it is, and how the text is set (song, poetic lines, prose), as facts tied to exact
words of the Hebrew and Greek text, each with its source. Built by `shoresh/macula/build_passage_facts.py`:

    python -m macula.build_passage_facts --books EXO LUK --out DIR [--licence by-sa|by] [--update-codes]

No fact is a model's reading of the text. A fact is either a source's own value (`b.source`), read from the Hebrew or Greek grammar
by a fixed rule (`b.text`), inferred by a published rule from other facts (`b.rule`), or set by a review row whose reason is in this
repository (`b.review`).

## Files

| File | What it holds |
|---|---|
| `<BOOK>.jsonl` | the facts of one book, one JSON object per line |
| `codes.tsv` | **the decoding table**: every code in the data, with its English meaning, the source it comes from, and notes |
| `sources.tsv` | the sources: name, licence, share-alike or not, enabled or not, attribution wording, what each gives |
| `build.json` | the export's licence, the sources used, the input hashes and pins, counts per book, the facts left out (see *Licence*), and `checks` per book: how well each source landed on the words (notes placed, partial and not found; ULT alignment words placed and not found; speeches with an introducing verb; Leningrad and MAM paragraph marks at the same word; Nestle passages with printed lines) |
| `nestle1904_layout.tsv` | (input) the passages the Nestle 1904 edition prints set apart, read from the page images |

## A fact

```json
{"id": "EXO.00001", "kind": "quote", "value": "qt.normal", "first": "020010090041", "last": "020010100192", "ref": "EXO 1:9-10",
 "basis": "b.source", "precision": "p.word", "src": ["clear", "layer"], "lic": "CC BY 4.0",
 "level": 1, "quote": "q00503", "found": "qf.block", "speaker": "מֶלֶךְ", "speaker_ref": ["020010080021"], "speaker_by": "sb.inquit",
 "speaker_id": "c0073", "speaker_name": "פַּרְעֹה", "speaker_name_ref": ["020010220021"]}
```

| Field | Meaning |
|---|---|
| `kind` | what the fact is about: `voice`, `quote`, `frame`, `domain`, `delivery`, `force`, `addressee`, `section`, `form`, `note` (and, once enabled, TBTA's `listener`, `attitude`, `age_relation`, `tb_force`, `rhetorical`) |
| `value` | a code from `codes.tsv`. For `frame` it is the verb's lemma in Hebrew or Greek |
| `first`, `last` | the anchor: the first and last word of the stretch, as MACULA word keys (Hebrew 12 digits `BBCCCVVVWWWP`, a morpheme; Greek 11 digits `BBCCCVVVWWW`) |
| `pieces` | where words of another voice interrupt the stretch: its parts as `[first, last]` pairs |
| `lines` | for a printed layout: each printed line as `[first, last]` |
| `at` | the words a grammar rule read (the imperative, the vocative, the second-person forms) |
| `after` | for `section`: the word after which the break stands |
| `ref` | the verses, for reading; the anchor is `first`..`last` |
| `basis`, `precision` | how the fact was found (`b.*`) and how exact its anchor is: `p.word` exact words, `p.verse` the source speaks of whole verses |
| `src`, `lic` | the sources (keys of `sources.tsv`) and the licence of the fact (CC BY-SA 4.0 if any of its sources is share-alike) |
| `of` | the fact (a `quote`) this one describes |
| `level`, `parent` | for `quote`: 1 = spoken in the narrative or text, 2 = a speech inside a speech, …; `parent` the enclosing quote |
| `speaker`, `speaker_ref` | for `quote`: who speaks, as the Hebrew or Greek lemmas of the words that name them, and those words' keys |
| `speaker_by` | how the speaker was named (`sb.*`) |
| `speaker_id`, `speaker_name`, `speaker_name_ref`, `members` | one person across speeches; that person's proper name in the text; for a group, its members' ids |
| `divine` | the source marks the speaker as God (Jesus, the Spirit) |
| `fit` | for a `note`: `partial` where the note quotes a text (UGNT, UHB) that differs a little from ours and at least 80% of its words were found in order; otherwise the match is exact |
| `tn_id` | for a `note`: the note's ID in unfoldingWord's Translation Notes, to look the note up there |
| `markers` | for the ULT's `form`: its paragraph marker per line (`q1`, `q2`: indent levels) |
| `start`, `end` | for a verse-precision `form`: whether the first and last verse are set that way in full (`cv.all`) or in part (`cv.part`) |

The data holds no English. To show a fact in English, look its codes up in `codes.tsv`. Delivery codes (`dl.*`), domain codes (`sd.*` SDBH, `ln.*` Louw-Nida, its code in the note column) and TBTA codes
carry the source's own wording; new values are appended with the next free number and never renumbered, so a code keeps its meaning across
builds.

## What each kind gives

| Kind | Rule | Sources |
|---|---|---|
| `voice` | `vc.narrator`: the words outside every speech (Hebrew books and Gospels, Acts). `vc.frame`: a text that is one speaker's from its start (a psalm's psalmist), with `speaker` | speaker layer; Clear |
| `quote` | each speech with its speaker, nesting, quote type (`qt.*`) and how it was found (`qf.*`) | Clear (CC BY), speaker layer / Greek layout speaker columns |
| `frame` | the verb that introduces a speech: the nearest verb in the 15 words before it, not inside another speech of the same level, with no Greek sentence end between; a Hebrew לֵאמֹר gives way to the verb before it in its clause. About 2% of speeches have no introducing verb, and the nearest verb is then not one of speaking | MACULA, clause layout |
| `domain` | the meaning domain of that verb in its place (Speak, Sing, Shout; Louw-Nida Speak/Talk, Inform/Announce, Question/Answer) | UBS dictionaries (CC BY-SA) |
| `delivery` | the speaker data's note on how a speech is delivered (praying, rebuking, singing) | Glyssen, carried in Clear's data |
| `force` | per clause inside a speech: imperative, jussive, cohortative, question (Hebrew interrogative words; the Greek question mark), Greek vocative. ἰδού, ἴδε and ἄγε are imperative in form but particles in use; they count neither here nor for `addressee` | MACULA, clause layout |
| `addressee` | `ad.sg`, `ad.pl`, `ad.both`: the number of the speech's own second-person forms. `ad.named`: the one spoken to in the inquit (Greek: the verb's A2 argument; Hebrew: the object of אֶל in the inquit's clause) | MACULA |
| `section` | petuchah and setumah, word-exact (a mark inside a verse stands after its word): the Leningrad Codex, and MAM's Aleppo Codex tradition, each as its own fact | OSHB; MAM (CC BY-SA) |
| `form` | `fm.ms.song`: the Masoretic song layout, line by line (Exod 15, Deut 32, Judg 5, 2 Sam 22, some lists). `fm.ed.*`: Nestle 1904 prints the words as poetic lines, a hymn block, or lines quoted from the Scriptures (from the page images; printed lines from the digital edition). `fm.tr.poetry`: a translation sets the words in indented lines: the ULT line by line through its word alignment, the BSB by verse | MAM (CC BY-SA); Nestle 1904; ULT (CC BY-SA); BSB |
| `note` | an unfoldingWord Translation Note of one of 27 articles on speech, address and poetry (rhetorical question, quotation in a quotation, apostrophe, parallelism, singular/plural 'you', inclusive/exclusive 'we', ...), on the Hebrew or Greek words it quotes. Only the article and the place are carried, not the note's English | unfoldingWord Translation Notes (CC BY-SA) |

## Licence

**The export is CC BY-SA 4.0 unless a CC BY 4.0 export is asked for.**

- Each fact keeps its own licence in `lic`, and each source's licence and attribution are in `sources.tsv` and `build.json`.
- The default export (`--licence by-sa`) holds every fact and is published under CC BY-SA 4.0 as a whole. Facts from share-alike
  sources (unfoldingWord, MAM, the UBS dictionaries) can only be shared under CC BY-SA, so the export as a
  whole carries that licence. The facts from CC BY 4.0, MIT and public-domain sources stay under their own terms. You may take them
  out and use them under those terms, with the attribution in `sources.tsv`.
- A CC BY 4.0 export (`--licence by`) leaves out every fact with a share-alike source. `build.json` says how many facts were left out
  per book (`dropped_share_alike`).
- The share-alike sources are unfoldingWord (ULT lines, Translation Notes), MAM (song layout, its paragraph marks) and the UBS
  dictionaries (domains). Their facts are `lic` CC BY-SA 4.0 and are the ones a CC BY export leaves out. Everything else is CC BY 4.0,
  MIT (Glyssen's delivery notes) or public domain (Nestle 1904, the BSB).
- A source can only be enabled with an open licence: CC BY 4.0, CC BY-SA 4.0, MIT or public domain. `share_alike` must match its
  licence; the build stops otherwise.

Attribution: name this export ("Passage facts, bcv-commons") and the sources of the facts you use, with the wording in the
`attribution` column of `sources.tsv`. For Glyssen's delivery notes, keep its MIT copyright notice.

## TBTA

The Bible Translator's Assistant (All the Word) records the listener, the speaker's attitude, the speaker–listener age relation and
the illocutionary force of each clause. Its export states no licence, so the source is **disabled** (`enabled` 0) and none of its
values are written. The reader is in place: when All the Word grants a licence, set `licence` and `share_alike` in `sources.tsv` and
`enabled` to 1, point `$TBTA_EXPORT_DIR` at the export's `json/` folder, and build with `--update-codes`, which gives TBTA's values codes
(`tl.*`, `ta.*`, `tg.*`, `tf.*`, `tr.*`). Its facts are verse-precision (`p.verse`) until its clauses are matched to the clause layout's.

## Not yet

- Anchors are a draft; they will follow the link-type specification when it arrives.
- OpenText.org's Greek discourse annotation: listed in `sources.tsv` but disabled and not read, since no open licence from its authors is known.
- Voice in the letters and Revelation (the author's voice) is not yet given.
- Hebrew poetic form from the text itself (the accent system of Psalms, Proverbs and Job; the song layout of the Leningrad Codex),
  refrains and acrostics; Greek speech that Clear's spans do not mark.
