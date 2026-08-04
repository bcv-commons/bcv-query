# Proper-noun lexicon (N1)

`<lang>.tsv` (one file per language, e.g. `eng.tsv`, `fra.tsv`) — each biblical **name** Strong's
(person/place/other) → how that name is written in that language. Built by
`shoresh/macula/build_proper_nouns.py`. Lets the analyzer recognize a name in a query (in any
language) → map to its Strong's → retrieve + drive the name-bridge; the `type` column distinguishes
people/places/other.

**Not committed** (`resources/proper_nouns/*.tsv` is gitignored) — regenerable, and large (~930
files, ~54MB) since `aligned_lex_hf` started feeding it. Published to HF (`bcv-commons`); this
README + any manifest stay tracked, same pattern as `resources/prior_pack/`.

## Columns
Per-language file — `lang` is implied by the filename, not a column:

| col | meaning |
|---|---|
| `strong` | name Strong's (`H1732`, `G2424`) |
| `translit` | romanized name, language-independent anchor (`da.vid`, `Iēsous`) |
| `type` | `person` · `place` · `other` (from TIPNR) · `name` (untyped — STEPBible `Np` only) |
| `surface` | a rendering of the name in this file's language |
| `source` | `tipnr` = original Heb/Greek surface · `gloss` = curated localized name (`strongs_gloss.tsv`) · `aligned` = attested in a real translation (`aligned_lex/` or `aligned_lex_hf/`) |
| `weight` | `1.0` for tipnr/gloss · alignment `share` for aligned |

## Three complementary signals
- **`tipnr`** — the authoritative proper-name set (STEPBible-Data TIPNR): OT **and NT**, typed, with the
  original Hebrew/Greek surface (Ἰησοῦς, דָּוִד). This is what brings NT Greek names in.
- **`gloss`** — the canonical name per language, broad coverage (19 langs incl. amh/cmn/rus).
- **`aligned`** — names *actually attested* in translations, including morphological variants a query
  might use: Arabic clitic forms (يَسُوعُ / وَيَسُوعُ / لِيَسُوعَ), English `david's`. `aligned_lex/` (manual,
  ~10 languages) is preferred where present; `aligned_lex_hf/` (automated, ~924 languages, from
  `bcv-commons/lexeme-alignments`) fills in the rest.

Consumers pick: `type` to filter people vs places; `source=tipnr|gloss` for canonical forms,
`source=aligned` (or all) for recognition recall.

## Coverage
3,415 name Strong's (622 NT/Greek) · person 2,172 / place 1,074 / other 141 / untyped 28 ·
1,228,065 renderings · 930 languages.

## Build dependency
The proper-noun **set + typing** come from **TIPNR** (`STEPBible-Data`, CC-BY), staged at
`bcv-RAG/ingest/_staging/tipnr/` (gitignored). It's staged as a side-effect of bcv-RAG's TIPNR ingest:
```bash
cd bcv-RAG && python -m ingest.tipnr    # fetches TIPNR_{people,places,other}.json into _staging/tipnr/
cd shoresh && python -m macula.build_proper_nouns   # -> resources/proper_nouns/<lang>.tsv
```
Without TIPNR staged it falls back to STEPBible `Np` (OT-Hebrew only, all `type=name`).
`aligned_lex_hf/` must be populated first (`python3 bcv-RAG/scripts/build_aligned_lex_hf.py`) for
full language coverage — without it, coverage falls back to `aligned_lex/`'s ~10 manual languages.
