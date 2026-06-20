# embed_eval/

Measurement spikes for the embedding layer: **does an original-language model
represent the original-language text better than a multilingual baseline?**
Decide build-vs-not by numbers before standing up any model-serving infra —
the same discipline as the spine ablation (which concluded *don't re-embed*).

- **Plan A — `--config greek`:** SPhilBERTa vs multilingual-E5 over LXX Greek (`lxx.db`).
- **Plan C — `--config hebrew`:** BEREL_3.0 vs multilingual-E5 over the Hebrew spine (`spine.db`). Same harness; BEREL is an MLM encoder so it runs through a mean-pool wrapper.

## Metrics (ground truth = Strong's, on the confusable create/make family)

- **Separation (primary, query-free):** mean(within-sense cosine) − mean(across-sense cosine). Higher = same-original-word verses cluster tighter. Fair to monolingual models (no query needed) — so it's the primary signal for both A and C.
- **Word-study retrieval (secondary):** sense query → P@5 / MRR. English queries work for SPhilBERTa/E5 (Plan A); the monolingual Hebrew/BEREL arm has no English query, so Plan C reports `n/a` and leans on separation.

**Win condition:** the original-language model shows materially higher separation than E5 over the *same* original-language text → it earns its infra (→ Plan B build). Flat/negative → multilingual suffices; don't self-host it.

## Run (local, CPU)

```bash
cd shoresh
python3 -m venv .venv && source .venv/bin/activate
pip install -r embed_eval/requirements.txt          # ~2 GB (torch); one-time

PYTHONPATH=. python -m embed_eval.spike --config greek --corpus-only   # data only, no models
PYTHONPATH=. python -m embed_eval.spike --config greek                 # Plan A
PYTHONPATH=. python -m embed_eval.spike --config hebrew                # Plan C
PYTHONPATH=. python -m embed_eval.spike --config greek --arms sphilberta   # one arm
```

First run downloads the models to the HF cache (`~/.cache/huggingface`).
Models are ~0.1–0.3 B and run on CPU in minutes for this small corpus. `$0`
(HF models are free; only an optional Voyage reference arm would cost cents).

Requires `lxx.db` (`python -m lxx.parse --all`) and, for Plan C, `spine.db`
(`python -m spine.parse`).
