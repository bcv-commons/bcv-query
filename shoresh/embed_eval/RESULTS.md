# Embedding spike — results & verdict

Run locally (CPU, Python 3.14 venv) over the confusable create/make family,
Strong's as ground truth, multilingual-E5 as the shared baseline. Primary
metric = **separation** (mean within-sense − mean across-sense cosine;
query-free, so fair to monolingual models).

## Results

| Plan | Corpus | Native model | E5 baseline | Native advantage |
|---|---|---|---|---|
| **A — Greek** (LXX, `lxx.db`, 60 verses) | poieō/ktizō/plassō/oikodomeō | **SPhilBERTa  sep 0.0285** · P@5 0.450 · MRR 0.500 | sep 0.0078 · P@5 0.350 · MRR 0.458 | **3.7×** separation, ahead on all 3 |
| **C — Hebrew** (spine, `spine.db`, 53 verses) | bara/asah/yatsar/banah | **BEREL_3.0  sep 0.0426** | sep 0.0077 | **5.5×** separation |

E5 separation is ~0.0077 in both runs — stable baseline (sanity check).

## Verdict

**Original-language-native embedding is worth building.** Both languages show
the native model representing the original text materially better than the
multilingual baseline — strongest in Hebrew (BEREL). This is the inverse of
the spine ablation (where prepending the spine to *English* embeddings was
null): the win comes from embedding the *original language with a native
model*, not from enriching English.

→ Proceed to **Plan B**: an original-language `/search` using **SPhilBERTa**
(Greek) + **BEREL_3.0** (Hebrew, mean-pooled), ensembled with **E5** for
recall (per [resource-inventory Gap 6](../../docs/resource-inventory.md#gap-6--original-language-embedding-models-to-embed-the-above)).

## Caveats (honest)

- Small corpora (60 / 53 verses), single run, no significance test — but the
  signal is **relative and consistent**: native > E5 across both languages,
  and across all three Greek metrics.
- Absolute separation is low (~0.03–0.04); it's the *ratio* to baseline that
  carries the result, corroborated by the Greek retrieval metrics.
- Tests **sense discrimination** on one word-family (create/make). Broader
  families and a cross-lingual-query task are follow-ups if needed.
- BEREL: the MLM head + CLS pooler are unused — we mean-pool `last_hidden_state`,
  so the `pooler MISSING` load warning is benign.

## Reproduce

```bash
cd shoresh && source .venv/bin/activate
PYTHONPATH=. python -m embed_eval.spike --config greek
PYTHONPATH=. python -m embed_eval.spike --config hebrew
```
