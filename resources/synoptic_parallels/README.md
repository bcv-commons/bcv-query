# Synoptic Gospel parallels (X2)

`parallels.tsv` — pairs of Gospel verses that tell the same passage, found by matching **content Greek
Strong's** shared across Gospels (same technique as the OT-in-NT quotation detector, applied within
Matt/Mark/Luke/John). Built by `shoresh/macula/build_synoptic.py`.

## Columns
| col | meaning |
|---|---|
| `ref_a`, `ref_b` | the two parallel verses (canonical order; cross-Gospel; symmetric-deduped) |
| `confidence` | `high` (IDF-cosine ≥ 0.45) · `med` (0.30–0.45) |
| `n_shared` | count of shared content Greek Strong's |
| `score` | IDF-cosine of the two verses' content-Strong's bags (∈ [0,1]) |
| `shared_strongs` | the shared Greek Strong's (`G0740,…`) |

Each verse keeps up to 4 parallels (a pericope spans ≤3 other Gospels).

## Coverage & validation
3,388 pairs over the 3,770 Gospel verses; 1,248 high-confidence. The by-Gospel distribution matches
synoptic theory — **MAT-MRK / LUK-MAT / LUK-MRK dominate** (double/triple tradition), **John has far
fewer high-conf pairs** (largely independent of the synoptics). On 6 well-known parallels the pair is
found 6/6 (Beatitudes, render-to-Caesar, mustard seed, leper, paralytic, camel-and-needle); the
perfect-score pairs are classic verbatim Q material (MAT 3:12 // LUK 3:17). Prefer `confidence=high`.

## Method note
Strong's-overlap catches **verbally parallel** passages (shared vocabulary). It will miss parallels
that narrate the same event in *different words*, and a few passion-narrative verses over-link on common
vocabulary (capped per verse; the confidence tier separates the precise ones). It is a lexical-overlap
signal, not a redaction-critical pericope map.

## Rebuild
```bash
python -m macula.build_synoptic     # -> resources/synoptic_parallels/parallels.tsv
```
