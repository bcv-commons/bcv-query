# Multilingual Strong's Gloss Index

Maps Strong's numbers (Hebrew H-codes, Greek G-codes) to short glosses in multiple languages. Used by concept expansion (Strategy 1) to translate query words into Strong's tags — enabling Bible search in any supported language.

## Coverage

Language codes are the **canonical ISO 639-3 tag (BCP 47)** — `eng`, `spa`,
`cmn-Hant`, … (see [resources/strongs/README.md](../resources/strongs/README.md#language-codes)).

| Language | Code | Entries | Hebrew | Greek | Source |
|----------|------|---------|--------|-------|--------|
| English | eng | 19,567 | 8,723 | 10,844 | shoresh `strongs_gloss.tsv` |
| Spanish | spa | 12,794 | 7,404 | 5,390 | UBS Hebrew + Greek Dictionaries |
| French | fra | 12,836 | 7,446 | 5,390 | UBS Hebrew + Greek Dictionaries |
| Portuguese | por | 7,226 | 7,226 | — | UBS Hebrew Dictionary |
| Chinese (Simplified) | cmn-Hans | 12,595 | 7,232 | 5,363 | UBS Hebrew + Greek Dictionaries |
| Chinese (Traditional) | cmn-Hant | 12,623 | 7,233 | 5,390 | UBS Hebrew + Greek Dictionaries |

**Total: 77,641 entries**

## File format

`strongs_gloss.tsv` — tab-separated, 4 columns:

```
strong  gloss       translit    lang
H0157   love        a.hav       eng
H0157   amar                    spa
H0157   aimer                   fra
H0157   amar                    por
H0157   爱                       cmn-Hans
H0157   愛                       cmn-Hant
G0025   love        agapaō      eng
G0025   amar                    spa
G0025   aimer                   fra
G0025   爱;爱心关怀;关爱;喜爱       cmn-Hans
```

## Sources and licenses

- **English glosses**: derived from shoresh spine data
- **spa, fra, por, cmn-Hans, cmn-Hant**: extracted from [BibleAquifer/UBSHebrewDictionary](https://github.com/BibleAquifer/UBSHebrewDictionary) and [BibleAquifer/UBSGreekNTDictionary](https://github.com/BibleAquifer/UBSGreekNTDictionary), licensed CC BY-SA 4.0

## Rebuilding

```bash
python3 bcv-RAG/scripts/build_multilingual_glosses.py
```

Downloads from GitHub, merges with existing English glosses, outputs `bcv-RAG/strongs_gloss.tsv`.
