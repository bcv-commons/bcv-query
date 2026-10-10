# Interlinear for any edition: a client example

shoresh provides **only the original-language scaffold** (`GET /scaffold/{book}/{chapter}`). The client joins it to two things it fetches itself:

| piece | from | what it holds |
|---|---|---|
| scaffold | shoresh `/scaffold/{book}/{chapter}?gloss_lang=` | every Hebrew/Greek token of the chapter in text order, keyed by its MACULA token key; lemma, `lexeme`, Strong's, gloss, `sp`, morphology, and `clause`/`phrase` ids into `clauses` / `phrases` (role, type) |
| alignment | Hugging Face `bcv-commons/compact-alignments` | per verse `srcOrd:targetSpan` strings, the key list `_index/<BOOK>_keys.json` that maps `srcOrd` to a token key, and `manifest.json` |
| text | helloAO `…/api/<edition>/<BOOK>/<chapter>.json` | the edition's verses (no text passes through shoresh or the alignment dataset) |

`interlinear.js` (about 100 lines, no dependencies) does the join; `index.html` renders it with hover in both directions; `check.mjs` is a live test (`node check.mjs [shoresh-url]`).
`tokenize.js` is a copy of the aligner's reference tokenizer (CC0); target words are addressed by **position** in its output, so use exactly it, and refuse to decode if `manifest.tokenizer_version` differs (the code does).

## The join

1. List the edition's folder once (`/api/datasets/…/tree/main/<iso[0]>/<iso>/<edition>`) to learn the file name `<BOOK>_<hash>.json`.
2. Fetch scaffold, `_index/<BOOK>_keys.json`, the compact file and the helloAO chapter in parallel.
3. For a verse: `keys[ref][srcOrd]` is the token key; the compact string gives target positions for each `srcOrd`; tokenize the verse text with `tokenize()`; the scaffold token with that key is the Hebrew/Greek word.
4. Reverse direction: each target token collects the keys of the source words aligned to it.

## Things the example handles, and why

- **Absent ordinal = unaligned.** Show the source word without a translation.
- **Function words have no links of their own yet.** Articles, prepositions, conjunctions and אֵת are in the scaffold (`content: false`) but the aligner folds their target words into the neighbouring content word's span. Show them dimmed.
- **Scattered spans** (`3,5`) are weaker than contiguous (`3-4`); the demo italicizes them. Filter on `scattered` if you need precision.
- **Two keys joined by `+`** in `_keys.json` are one lexeme (MACULA's node pair); the link is given to both scaffold tokens.
- **Take `srcOrd` from the aligner's key list, not from the scaffold's `content` flag.** The two agree on all but about 130 of 440,000 tokens (a spine version difference: Psalm titles and ten single tokens). The key join itself is exact.
- **Psalm title labels** (מִזְמוֹר, לְדָוִד, לַמְנַצֵּחַ …) are marked superscription and get no alignment; the narrative part of a title ("when he fled from Absalom") is content and is aligned (fra_lsg: PSA 3:1 3 of 3, PSA 51:1 0 of 5).
- **Pooled verses** (a translation that numbers "3-4" as one block) have an empty string for the non-anchor verse.
- **Different verse numbering.** `loadChapter` takes a `verseMap(ref)` that turns the edition's `"BOOK C:V"` into the aligner's numbering. The default is identity, which holds for the editions tested (fra_lsg, swh_ulb). For others use the bibles versification maps (shoresh's `/verse?edition=` shows the conversion for the New Testament).
- **Verification.** The alignment file name carries a hash of the whole book's text, meant to detect a revised edition. I could not reproduce it from helloAO chapters (0 of 10 books tried), so the example does not verify. Ask the aligner team for a reference vector before relying on it.

Licences: the scaffold is CC BY / CC BY-SA (MACULA, UBS); the alignment data is CC0; the text carries its own edition licence (the alignment manifest links it).
