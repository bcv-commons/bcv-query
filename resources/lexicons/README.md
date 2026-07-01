# lexicons/

Vendored source lexicons used as **build inputs** (not served at runtime).

## heb_en.csv — BibleOL per-stem Hebrew lexicon (English)

Per-binyan English glosses for BHSA Hebrew lexemes: columns `Occurrences, lex,
Lexeme, Transliterated, None, Qal, Nifal, Piel, Pual, Hitpael, Hifil, Hofal,
Hishtafal, Passive Qal, Etpaal, Nitpael, Hotpaal, Tifal, Hitpoal, Poal, Poel`.

**Used by** `bcv-RAG/scripts/build_perstem_glosses_llm.py` as the per-stem *template*
(which lexeme×stem cells exist, + transliteration + English reference gloss) when
generating a new language's per-binyan glosses.

Committed here so per-stem generation no longer depends on a local (gitignored)
`example/BibleOL/` checkout. If absent, the script falls back to the committed
`resources/word_glosses/hbo/English.csv` (same per-stem data, without the
transliteration hint).

**Provenance / licence:** BibleOL (https://github.com/EzerIT/BibleOL), © 2015 Ezer IT
Consulting — **MIT License** (see the upstream `LICENSE`; ch.7 of its techdoc notes
special cases for sub-parts). Re-derivable from the BibleOL lexicon export.
