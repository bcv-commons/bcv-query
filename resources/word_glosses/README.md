# word_glosses/

Target-language glosses for `/words`, keyed by the **ETCBC/BHSA lexeme id** (`lex`) —
the same value the word API returns. Lets the trainer show vocabulary in any language
without the client shipping its own CSV.

```
word_glosses/
  hbo/<Language>.csv      # Hebrew + Aramaic (BHSA lex)
  grc/<Language>.csv      # Greek (Nestle1904 lemma) — its own sources
```

Adding a language is a **server-only job**: drop a CSV here, commit, thin deploy. It
appears in `GET /gloss-languages?language=…` and is selectable via `GET /words?...&gloss_lang=…`.

## CSV format
Columns: `lex`, `default`, then one column per **verbal stem** (`qal`, `nif`, `piel`,
`pual`, `hit`, `hif`, `hof`, …). A leading unnamed index column (pandas export) is
ignored. Most rows may be empty — only lexemes with a non-empty gloss are served.

Resolution per word (mirrors the client rule exactly):
- **verb** (the word's `stem` ≠ `NA`): the gloss in that **stem column**; if empty, the
  **first non-empty stem column**.
- **non-verb**: the **`default`** column; if empty, the first non-empty column.
- The **full gloss string is returned unmodified** (e.g. `"sige, tænke"`); the client
  may split on `; ` / `, ` to accept any synonym.

`English` is also available inline from the corpus, so it works even without a file;
a per-stem `hbo/English.csv` is present here as the source the other languages bridge from.

## Languages (11)
`hbo/` Hebrew+Aramaic carries **per-binyan** columns; `grc/` Greek is single-gloss.

Danish, German, Dutch, Portuguese, Spanish, Swahili, Amharic, French,
Chinese-Simplified, Chinese-Traditional, English. (`English` is also available
inline from the corpus and needs no file.)

Provenance: the per-stem **English** came from BibleOL; the other languages were
bridged/converted from it; **Chinese-Traditional** via OpenCC from Simplified. A
per-stem LLM pipeline (`build_perstem_glosses_llm.py`) fills the catch-up gaps.

## Forward
Per-stem catch-up for more languages via the LLM pipeline — drop the generated CSV
here, commit, thin deploy.

## Licensing
Each gloss set carries its own terms — record provenance/licence per file as more are
added (these are lexeme-level target-language glosses, independent of the Strong's-keyed
`strongs_gloss.tsv`).
