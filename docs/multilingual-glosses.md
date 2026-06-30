# Multilingual Strong's Gloss Index

Maps Strong's numbers (Hebrew H-codes, Greek G-codes) to short glosses in **11
languages**, with **per-binyan (verbal-stem) detail for Hebrew verbs**. These
glosses are what let you search the Bible in any supported language: concept
expansion (bcv-RAG Strategy 1) translates your query words into Strong's tags,
and shoresh's `/words` vocab-trainer feed reads them directly.

## Coverage

11 languages: **English, Spanish, French, Portuguese, Chinese (Simplified +
Traditional), Russian, Arabic, Hindi, Bengali, Assamese, Hausa**.

Language codes are the **canonical ISO 639-3 tag (BCP 47)** — `eng`, `spa`,
`cmn-Hant`, `arb`, … (see
[resources/strongs/README.md](../resources/strongs/README.md#language-codes)).
The per-language gloss tables live under
[`resources/strongs/glosses/`](../resources/strongs/glosses) (one `.tsv` +
`.parquet` per language) and are published as part of the open
[`bcv-commons/strongs`](https://huggingface.co/datasets/bcv-commons/strongs)
dataset.

## File format

Each `<lang>.tsv` is tab-separated. The English row carries a transliteration;
other languages carry the localized gloss:

```
strong  gloss       translit    lang
H0157   love        a.hav       eng
H0157   amar                    spa
H0157   aimer                   fra
G0025   love        agapaō      eng
G0025   amar                    spa
```

Hebrew verbs additionally carry **per-binyan** glosses (a different sense per
verbal stem), keyed to the sense layer — see
[sense-layer-pipeline.md](sense-layer-pipeline.md).

## Sources and licenses

- **English**: derived from shoresh spine data + LLM gloss generation.
- **Other languages**: extracted from the BibleAquifer UBS Hebrew/Greek
  Dictionaries (CC BY-SA 4.0), extended with LLM-generated glosses for
  from-scratch languages.

Per-source provenance and license are recorded in
[`resources/strongs/README.md`](../resources/strongs/README.md).

## Rebuilding

```bash
python3 bcv-RAG/scripts/build_multilingual_glosses.py
```

## Where it's going

Scaling the language registry to thousands (Glottolog/URIEL/CLDR → `languages.db`)
and adding per-binyan glosses for more from-scratch languages. See
[docs/ROADMAP.md](ROADMAP.md).
