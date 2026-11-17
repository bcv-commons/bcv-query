---
license: cc-by-sa-4.0
language:
  - hbo
  - arc
  - grc
  - he
pretty_name: Hebrew–Greek Bible (Context Fabric)
tags:
  - bible
  - hebrew
  - greek
  - septuagint
  - new-testament
  - context-fabric
  - text-fabric
  - corpus
---

# Hebrew–Greek Bible (Context Fabric)

The Bible in Hebrew and Greek as one searchable [Context Fabric](https://context-fabric.ai) dataset: the Tanakh, the Greek New
Testament, the Septuagint and two Hebrew translations of the New Testament, on shared keys and linked word to word, with the
bcv-commons analysis layers on the words. The links make it a bridge between Hebrew and Greek in both directions: from the Hebrew
Bible to Greek through the Septuagint, and from the Greek New Testament to Hebrew through the Hebrew New Testaments.

| | |
|---|---|
| Version | @VERSION@ (dataset version `@DATAVERSION@`: the release and a hash of its pins) |
| Built | @BUILT@ by `macula/build_bridge_corpus.py` and `macula/release_hebrew_greek_cf.py` (bcv-query `@CODE@`) |
| Words | @WORDS@ in five texts |
| Licence | CC BY-SA 4.0 as a whole; every feature states its own source and licence |
| Checked | @QUERIES@ fixed queries with known counts (`queries.json`) |

## The texts

@TEXTS@

The base unit is `word`: a word part in Hebrew (as MACULA cuts it), a word in Greek. `token` is a written Hebrew word.

## The links between the texts

@BRIDGES@

Lexemes, concepts and persons are units shared by all five texts: a lexeme unit holds every occurrence of one Hebrew or Aramaic
lexeme (by Strong's number with MACULA's letter) or one Greek lemma, in any text; the `tier_*` edges link Hebrew and Greek lexemes
with their counts.

## Units

@UNITS@

Sections: `sec` on books (`GEN`, `MAT`; `LXX.GEN`, `LXX.DAN-TH` for Theodotion's Daniel; `SCG.MAT`, `DEL.MAT` for the Hebrew New
Testaments), then chapter and verse. `book` is the plain book name in every text.

## The layers

Each layer is a published bcv-commons dataset at a pinned revision (`pins.json`). A layer's columns are features named
`<prefix>_<column>`.

@LAYERS@

**Model-made layers** (`model_made=yes` in the feature's metadata): @MODEL@. A language model made these labels; no person has
checked them.

What is not in it: English content (glosses, English text columns), BHSA data, and anything from TBTA.

## Loading

```python
pip install context-fabric
from huggingface_hub import snapshot_download
import cfabric

path = snapshot_download("bcv-commons/hebrew-greek-cf", repo_type="dataset", revision="@VERSION@")
CF = cfabric.Fabric(locations=f"{path}/tf")
api = CF.loadAll()
```

The first load builds Context Fabric's cache beside the files (several minutes; 0.6: about 0.9 GB, 0.5: about 3.8 GB); later loads
take seconds. With Context Fabric 0.5.x, a reused cache forgets which edges carry values
([issue #15](https://github.com/Context-Fabric/context-fabric/issues/15)), so search refuses conditions like `-lxx=sure>`; set
the flag again after loading:

```python
for name, feat in CF.features.items():
    if getattr(getattr(api.E, name, None), "doValues", False):
        feat.edgeValues = True
```

Context Fabric 0.6.0rc1 needs no such step (tested on this dataset).

A query, Hebrew word parts with a Septuagint word placed for sure:

```
word lang=hbo
-lxx=sure> word
```

Readers without Context Fabric: the links between the texts are also flat tables in `bridges/` (Parquet), keyed by the words'
own ids (`mid` = the MACULA key, `lkey` = Septuagint word, `hkey` = Hebrew New Testament word part).

## Files

| Path | What it holds |
|---|---|
| `tf/` | the dataset: one `.tf` file per feature |
| `bridges/*.parquet` | the links between texts as flat tables |
| `pins.json` | every input with its revision and licence |
| `report.json` | the build's counts |
| `queries.json` | the fixed queries and their counts |
| `build.json` | version, code, inputs |

## Sources and licence

@SOURCES@

The whole is CC BY-SA 4.0. Each feature's metadata names its source and licence, so that an output can state which features it read.

## Versions

- v0.1: the first release (2026-11-17).
