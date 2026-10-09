# lexicons/

Vendored source lexicons used as **build inputs** (not served at runtime).

## heb_en.csv — BibleOL per-stem Hebrew lexicon (English)

Per-binyan English glosses for BHSA Hebrew lexemes: columns `Occurrences, lex,
Lexeme, Transliterated, None, Qal, Nifal, Piel, Pual, Hitpael, Hifil, Hofal,
Hishtafal, Passive Qal, Etpaal, Nitpael, Hotpaal, Tifal, Hitpoal, Poal, Poel`.

**Used by** `bcv-RAG/scripts/build_perstem_glosses_llm.py` as the per-stem *template*
(which lexeme×stem cells exist, + transliteration + English reference gloss) when
generating a new language's per-binyan glosses.

LOCAL ONLY since 2026-10-09 (git-ignored; BHSA-keyed, see resources/LICENSES.md). The script falls back to
`example/BibleOL/lexicons/heb_en.csv` or the local `word_glosses/hbo/English.csv`.

**Provenance / licence:** BibleOL (https://github.com/EzerIT/BibleOL), © 2015 Ezer IT
Consulting — **MIT License** (see the upstream `LICENSE`; ch.7 of its techdoc notes
special cases for sub-parts). Re-derivable from the BibleOL lexicon export.
