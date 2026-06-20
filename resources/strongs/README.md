---
license: cc-by-sa-4.0
pretty_name: "Strong's Words — multilingual, provenance-marked"
language:
  - ar
  - as
  - bn
  - en
  - es
  - fr
  - ha
  - hi
  - pt
  - ru
  - zh
language_bcp47:
  - zh-Hans
  - zh-Hant
tags:
  - bible
  - strongs
  - lexicon
  - word-alignment
  - low-resource
configs:
  - config_name: glosses
    data_files: "glosses/*.parquet"
  - config_name: surfaces
    data_files: "surfaces/*.parquet"
  - config_name: surfaces_by_method
    data_files: "surfaces_by_method/*.parquet"
  - config_name: attestations
    data_files: "attestations/*.parquet"
---

# strongs — Strong's numbers → the actual words, per language

A standalone dataset for anyone who wants **just the words**: given a Hebrew or
Greek **Strong's number**, what words does each language actually use for it — and
**how was each word obtained**. No need to run or understand the services around
it.

**Home:** [huggingface.co/datasets/bcv-data/strongs](https://huggingface.co/datasets/bcv-data/strongs)
(full data + viewer) · [github.com/bcv-data/strongs](https://github.com/bcv-data/strongs)
(samples + pointer). Produced by the [bcv-query](https://github.com/bcv-data) project.

- **Anchored on the original languages only.** Every row is keyed on `strong`
  (`H####` / `G####`) + the original `lemma` (Hebrew/Greek). English is never the
  anchor — it's just one more language file (`eng`).
- **One language per file.** No wide multi-language tables.
- **Every word carries its provenance** — how it was generated, from which
  source. That's the whole point: you can keep only what you trust.

> Currently 10 aligned languages + 12 gloss languages, **growing**.

## Language codes

Files are named with the **canonical ISO 639-3 code inside BCP 47 grammar** —
`eng`, `spa`, `por`, `arb`, `cmn-Hant`, … — matching the Bible-data ecosystem
(eBible / Clear-Bible / Paratext are all ISO 639-3) so the dataset composes with
external sources, while script/region (`cmn-Hant`, `pt-BR`) and translation
private-use subtags (`eng-x-bsb`) remain expressible. New languages use their ISO
639-3 code (so the set scales past the ~180 languages that have a 2-letter code).
For the web / Hugging Face `language:` field, use the shortest equivalent tag
(`eng → en`, `cmn-Hant → zh-Hant`).

## Loading

The files are **tab-separated** and carry a `#` provenance line on top, so pass
`sep="\t", comment="#"`. Each file is one language (the language is the file name,
not a column), so load a language at a time.

```python
# pandas — quickest peek
import pandas as pd
df = pd.read_csv(
    "https://huggingface.co/datasets/bcv-data/strongs/resolve/main/surfaces/spa.tsv",
    sep="\t", comment="#")

# datasets
from datasets import load_dataset
ds = load_dataset("bcv-data/strongs", data_files="surfaces/spa.tsv",
                  sep="\t", comment="#")
```

Tiers are exposed as configs (`glosses`, `surfaces`, `surfaces_by_method`,
`attestations`) — loading a whole config concatenates all languages. If Parquet
mirrors are present they load natively (no `sep`/`comment` needed):
`load_dataset("bcv-data/strongs", "surfaces")`.

## Two families

### 1. Glosses — `glosses/<code>.tsv`  *(type-level: one canonical word per Strong's)*

The dictionary-style answer: the word a language uses for a concept.

| column | meaning |
|---|---|
| `strong` | `H####` / `G####` (sense suffixes normalized away) |
| `lemma` | the original Hebrew/Greek dictionary form |
| `gloss` | the word in this language |
| `methods` | `;`-set of how it was produced — `lexicon`, `llm` |
| `sources` | `;`-set of where it came from — `ubs-dict`, `stepbible`, `inhouse-llm` |

Rows are collapsed to one per `(strong, gloss)`; when a dictionary and the LLM
independently produce the *same* word you'll see `lexicon;llm` (agreement).

### 2. Aligned surfaces — `surfaces/…`  *(token-level: real renderings in a real translation)*

How a published translation actually rendered each original word, with frequency
— derived from human/machine **word alignment** ([Clear-Bible/Alignments](https://github.com/Clear-Bible/Alignments)).
Three tiers of increasing detail; **pick the one you need**:

**`surfaces/<code>.tsv` — friendly (the default download)**, one row per `(strong, surface)`:

| column | meaning |
|---|---|
| `strong`, `lemma` | the Hebrew/Greek anchor |
| `surface` | the attested word in this language (lowercased) |
| `count` | how many times it renders this code |
| `share` | `P(strong \| surface)` — this code's fraction of the surface's alignments |
| `methods` | `;`-set — `manual`, `transfer` (room for `statistical`/`neural` later) |
| `review` | `human-verified` (any manual alignment) or `machine` |

**`surfaces_by_method/<code>.tsv` — full**, one row per `(strong, surface, method)` with `source_corpus`, `base_text`, `count`. Use it to filter by method/edition.

**`attestations/<code>.tsv` — per-occurrence (opt-in, large)**, one row for every aligned word instance:

| column | meaning |
|---|---|
| `strong`, `lemma`, `surface` | as above |
| `ref` | verse, `BBCCCVVV` (e.g. `40001001` = Matt 1:1) |
| `target_id` | occurrence id in the translation (`BBCCCVVV`+`WWW`) |
| `source_id` | the original-language token id (Clear/BCVW, e.g. `n40001001001`) |
| `method`, `source_corpus`, `base_text` | full provenance |

This is the **canonical source of truth** — the friendly and full tiers are
aggregations of it. Download it only if you need to verify each word back to a
specific verse, or to re-aggregate yourself.

## Provenance vocabulary

**`method`** — how a word was derived:

| value | meaning |
|---|---|
| `manual` | human word-alignment (Clear-Bible) |
| `transfer` | machine-projected alignment (Clear-Bible) |
| `lexicon` | from a dictionary (UBS / STEPBible) |
| `llm` | generated by an LLM, anchored on the original lemma |
| `statistical`, `neural`, `fuzzy`, `pattern` | reserved — produced by the upcoming aligner |

**`source`** — which dataset (→ attribution/license): `clear-alignments`,
`ubs-dict`, `stepbible`, `inhouse-llm`.

**`review`** — `human-verified` vs `machine`. Distinct from method: it answers
"did a person check this," not "how was it made."

## Languages

- **Aligned surfaces (10):** `arb asm ben eng fra hau hin por rus spa`
- **Glosses (12):** the above + `cmn-Hans cmn-Hant` (`spa` also merges its LLM glosses)

## Licenses

Per-file headers record `source` / `license` / `date`. Summary:

- **Aligned surfaces** — derived from [Clear-Bible/Alignments](https://github.com/Clear-Bible/Alignments)
  (per-source; original-language texts SBLGNT / WLC-Macula).
- **Glosses** — `ubs-dict`: UBS Hebrew/Greek dictionaries via
  [BibleAquifer](https://github.com/BibleAquifer) (**CC BY-SA 4.0**); `stepbible`:
  [STEPBible](https://github.com/STEPBible/STEPBible-Data) (**CC BY 4.0**);
  `inhouse-llm`: generated for this project.

Attribute the sources; keep share-alike (SA) derivatives under a compatible
license.

## Rebuild

```bash
cd bcv-RAG
python3 scripts/build_strongs_words.py          # surfaces (needs the alignments cache)
python3 scripts/build_strongs_words_glosses.py  # glosses
```

The surface builder reads a local extract of Clear-Bible/Alignments under
`bcv-RAG/.cache/alignments/` (populated by `scripts/build_aligned_all.py`).

> **Note on the attestation tier:** it's large (hundreds of MB across languages).
> It's intended to be distributed as an **opt-in download** (release asset /
> dataset config), not necessarily committed to git alongside the lighter tiers.
