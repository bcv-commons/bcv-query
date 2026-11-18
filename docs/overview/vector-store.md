# Overview: the semantic vector store

What is in our vector store, how it was made, what has been built from it, and how well each use holds up. State: 2026-11-18.
The store is a local working tool (`shoresh/macula/data/vector-store/`, about 2.4 GB, git-ignored), not a published dataset;
what we publish from it are computed tables with the `-similar` ending.

## What is in it

One contextual vector for every word of five texts of the bridge corpus (local build b15, published as hebrew-greek-cf v0.2).

| Text | Words | Encoder | File |
|---|---|---|---|
| Tanakh (MACULA Hebrew, WLC) | 469,476 | BEREL 3.0 (DICTA), unpointed text | `tanakh.npy` 688 MB |
| Septuagint (GLAUx) | 491,860 | GreBerta (Riemenschneider and Frank) | `septuagint.npy` 721 MB |
| Greek NT (MACULA Greek, Nestle 1904) | 137,779 | GreBerta | `greek_nt.npy` 202 MB |
| Salkinson–Ginsburg Hebrew NT | 179,037 | BEREL 3.0 | `salkinson.npy` 263 MB |
| Delitzsch Hebrew NT | 171,974 (171,966 with a vector) | BEREL 3.0 | `delitzsch.npy` 252 MB |
| Lexemes (mean over all occurrences) | 13,792 keys: 8,434 Hebrew, 5,358 Greek | | `lexemes.npy` 41 MB |

- **Vectors:** 768 dimensions, float16, the mean of a word's subword tokens over the last four layers. The parts of one Hebrew
  token (prefix, stem, suffix) share the token's vector.
- **Index files:** each `<text>.parquet` row gives the corpus word node, the lexeme key (`h`/`g` + Strong's number), part of speech,
  book, chapter and verse. Search is a normalised matrix product; the store is small enough that no separate index is needed.
- **Only native encoders.** One Hebrew model and one Greek model, each trained on its own language. No English-trained or
  multilingual encoder, and no English text, enters the store.
- Built by `shoresh/macula/build_vector_store.py`; models, corpus build and counts in `build.json`.

## The shared Hebrew–Greek space

The Hebrew and Greek models have separate spaces. One orthogonal map (Procrustes) carries Greek onto Hebrew. It is trained on
Tanakh–Septuagint word pairs that MACULA Hebrew aligns (content words, up to 400,000 pairs; 175,608 in the clause build). No New
Testament pair enters the map, so the New Testament checks below are unseeded.

| Map variant (V2, lexeme retrieval) | held-out Septuagint top 1 / top 10 | Salkinson pairs top 1 / top 10 | Delitzsch pairs top 1 / top 10 |
|---|---|---|---|
| lexeme means, Procrustes | 0.457 / 0.790 | 0.256 / 0.553 | 0.271 / 0.538 |
| **occurrence pairs, Procrustes (used)** | **0.506 / 0.840** | **0.297 / 0.595** | **0.300 / 0.555** |
| occurrence pairs + CSLS | 0.556 / 0.796 | 0.275 / 0.496 | 0.265 / 0.500 |
| contrastive linear + CSLS | 0.580 / 0.815 | 0.300 / 0.553 | 0.296 / 0.569 |

## What has been built from it

| Step | Output | Result |
|---|---|---|
| V3a: bridge candidates | Greek candidates for Tanakh lexemes without a partner, and Hebrew ones for Greek NT lexemes; a model chose among them | hebrew-greek-lexeme-bridge-model v0.3 (833 pairs) |
| V3b: concepts without English | an occurrence labelled by its nearest concept examples | pilot 0.643 against hebrew-word-concepts-model v0.6 (majority baseline 0.393); 0.890 where 6 of 7 neighbours agree. A full run was not made: the model gate agreed with itself only about 0.61 |
| V3e: clauses like this | clause vector = mean of its content words, centred per text | [clauses-similar](https://huggingface.co/datasets/bcv-commons/clauses-similar) v0.1. A Chronicles clause's best match outside Chronicles lies in Samuel–Kings 3.0 times as often as chance; Matthew to Mark/Luke 2.6 times |
| V3g: Tanakh clause → Greek NT clauses | the same vectors in the shared space | [tanakh-nt-clauses-similar](https://huggingface.co/datasets/bcv-commons/tanakh-nt-clauses-similar) v0.1. A Salkinson Hebrew NT verse finds its own Greek verse among 7,943 at top 1 0.629, top 10 0.877. Deut 6:5 → Matt 22:37, Luke 10:27, Mark 12:30; Ps 110:1 → Heb 1:13, Luke 20:42 |
| V3d: semantic neighbours without English | Hebrew lexeme pairs from vectors, the Septuagint, roots and parallelism | not published: two designs stayed below the published semantic-neighbors on research's back-off test (best 0.150 vs 0.171 Indonesian). The second design reaches twice as many rare words |
| Source ontology | `rendered_by` model tier uses V3a's output | see [ontology.md](ontology.md) |

## Limits

- **Similar means close in the encoders' space.** Shared words and phrasing count first, then theme. A high score is a retrieval
  aid, not a claim of the same meaning.
- **Mean pooling.** A clause or lexeme vector is a mean; long clauses and very frequent lexemes blur.
- **One model per language, frozen.** Nothing is fine-tuned; a better Hebrew or Greek encoder means rebuilding the store.
- **Licence of what comes out.** The map is trained on GLAUx (CC BY-SA 4.0), so tables computed in the shared space are CC BY-SA 4.0;
  both encoders are Apache 2.0.
