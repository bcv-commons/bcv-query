# Proper-noun lexicon (N1)

`proper_nouns.tsv` — each biblical **name** Strong's (person/place) → how that name is written across
languages. Built by `shoresh/macula/build_proper_nouns.py`. Lets the analyzer recognize a name in a
query (in any language) → map to its Strong's → retrieve + drive the name-bridge.

## Columns
| col | meaning |
|---|---|
| `strong` | name Strong's (`H1732`) |
| `translit` | romanized name, language-independent anchor (`da.vid`) |
| `lang` | ISO code |
| `surface` | a rendering of the name in that language |
| `source` | `gloss` = curated localized name (`strongs_gloss.tsv`) · `aligned` = attested in a real translation (`aligned_lex/`) |
| `weight` | `1.0` for gloss · alignment `share` for aligned |

## Two complementary signals
- **`gloss`** — the canonical name per language, broad coverage (14 langs incl. amh/cmn/rus). Authoritative but one form.
- **`aligned`** — names *actually attested* in translations, including morphological variants a query
  might use: Arabic clitic forms (دَاوُدُ / وَدَاوُدُ / لِدَاوُدَ), English `david's`. Empirical, per-language.

Consumers pick: `source=gloss` for the canonical name, `source=aligned` (or both) for recognition recall.

## Coverage & scope
1,485 name Strong's · 1,218 with aligned surfaces · 17,187 renderings · 14 languages.

**OT / Hebrew only.** Proper nouns are identified by STEPBible's `Np` morph (`proper_strongs()`), which
is Hebrew. MACULA Greek carries **no proper-noun flag** (Δαυίδ/Ἰησοῦς are just `noun`), so **NT Greek
names are not yet covered** — that needs **TIPNR** (Tyndale proper names, CC-BY; also gives
person/place/people-group typing) or STEP TAGNT. That is the full N1 (see
`internal-docs/greek-lexeme-and-neighbors.md` neighbourhood / roadmap N1); this file is the unblocked
OT down-payment, and its join code is reused by the full version.

## Rebuild
```bash
python -m macula.build_proper_nouns     # -> resources/proper_nouns/proper_nouns.tsv
```
