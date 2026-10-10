# The sense layer (occurrence → sense, anchored on MACULA tokens)

How every Hebrew word gets a **sense** that is decided in the original and labelled in any
language — and how to regenerate or extend it. (The earlier BHSA-based pipeline, with Hebrew-context
embeddings, is retired; it lives in the git history and in the ignored `doc-bak/`.)

## The idea in one line

Anchor on the **most granular original** — the per-occurrence MACULA token (its `key`) — and *derive*
everything coarser: the lexeme's senses, the Strong's-level view, and the English/other-language
labels. Sense *identity* is decided from how translators render the occurrences (which occurrences
are rendered alike across languages); the gloss is only a *label*.

This is why the layer can do what Strong's can't: split homographs (733 Strong's codes cover 2+
lexemes, e.g. `hbo:0871a` the prefix בְּ vs `hbo:0871` a place name), separate binyan meanings, and carry a
per-occurrence sense — anchored on the Hebrew, none of it imposed from English.

## The pipeline

| # | script | in → out | notes |
|---|---|---|---|
| 1 | (lexeme-aligner project) | translations + alignments → the CC BY 4.0 `hebrew-word-senses` release | `occurrences.parquet` (key, book, chapter, verse, lexeme, sense) and `senses.tsv` (lexeme, strong, lemma, sense, label, count, share); no BHSA input |
| 2 | `shoresh/macula/build_verse_senses.py` | release → `verse-senses.db` | `occ(key, lexeme, sense)`, `senses(lexeme, sense, label, n, share)`, `meta`; `/verse` shows a label only for lexemes with more than one sense |
| 3 | `shoresh/macula/build_stem_senses.py` | `verse-senses.db` + the aligner's `rend` ids → `verse-senses-stem.db` | verbs that occur in two or more stems are re-split per (lexeme, stem); sense numbers stay unique per lexeme, so readers need no change (`sense_stem` table) |
| 4 | `bcv-RAG/scripts/tag_lexeme_occurrences.py` | `lexeme-spine-macula.db` + `verse-senses.db` → `index.db` tags | `lexeme:hbo:6942`, `lexemestem:<id>.<stem>`, `lexemesense:<id>.<n>`, `lexemestemsense:<id>.<stem>.<n>`, `stem:<stem>`; pure inserts, idempotent, `--revert` removes them |

Each step re-derives from the stored anchor (the token key), so improving a later step never forces
re-doing an earlier one.

## Regenerate

```bash
cd shoresh
python -m macula.build_verse_senses                # release → macula/verse-senses.db
python -m macula.build_stem_senses                 # optional per-stem split → verse-senses-stem.db
python3 ../bcv-RAG/scripts/tag_lexeme_occurrences.py [path/to/index.db]
```

Ship the sense database to the service data volume with `deploy/deploy-data.sh` (host
`/opt/shoresh/data`, container `/data/verse-senses.db`); re-tag the serving `index.db` (no re-embed) and
deploy bcv-rag + shoresh.

## How it's surfaced

- **bcv-RAG `morphology_concordance` MCP tool** — precise concordance by lexeme + stem + sense; the
  response lists the available senses so a caller can drill in.
- **shoresh `/verse`** — each Hebrew word carries its sense (label only for lexemes with more than one).
- **shoresh `/wordstudy` card** — per lexeme, per binyan, the senses with shares; `gloss_lang` localizes
  the label (sense identity stays Hebrew).

## Forward-looking

- **Sub-sense labels and multilingual sub-senses.** The dominant sense of a (lexeme, stem) uses the curated
  per-stem gloss and is multilingual; low-share sub-senses carry an English rendering label. The clusters are
  language-neutral, so localizing them is a re-label.
- **Sense-correct synthesis.** The per-occurrence sense is in `verse-senses.db` and the index tags but is not
  yet fed into bcv-RAG answer grounding.
- **Aramaic and Greek.** Aramaic verbs have stems too (small tail); Greek has no binyanim, so its senses are single.

## Related

- Glosses (the per-stem multilingual labels): `resources/word_glosses/README.md`.
- The Strong's dataset and the wider plan: `docs/ROADMAP.md`.
