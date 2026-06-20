# spine/

The original-language spine: per-word Strong's + lemma + morphology from
UHB (Hebrew OT) and UGNT (Greek NT), 99.59% reconciled to BHSA.

Originally built to test prepending a language-neutral anchor to embedding
inputs. That investigation **concluded: do not re-embed** — the anchor
belongs in the deterministic / structural layer, not the embeddings (see
[../docs/embedding-enrichment.md](../docs/embedding-enrichment.md)). The
spine *data* remains a validated, durable asset: it powers exact
`strongs:`/`lemma:` retrieval today and is the lexical foundation for the
original-language-anchoring direction
([../../docs/original-language-anchoring.md](../../docs/original-language-anchoring.md)).
Parser spec: [../docs/spine-parser.md](../docs/spine-parser.md).

## Contents

| Path | What |
|---|---|
| `parse.py` | **the spine parser** — UHB/UGNT → per-word records → `spine.db` |
| `common.py` | shared constants/helpers (pinned tags, book maps, Strong's normalization) |
| `build_glosses.py` | builds `strongs_gloss.tsv` from STEPBible TBESH/TBESG (CC BY) |
| `strongs_gloss.tsv` | Strong's → concise English gloss (Lexical line); 100% coverage of the OT spine |
| `prefix.py` | **the prefix builder** — `PrefixBuilder.build(passage_refs)` → Location + Lexical lines for a chunk |
| `ablation.py` | easy thematic ablation (saturated — production model already nails distinct-verse + cross-lingual retrieval) |
| `ablation_wordstudy.py` | **discriminating ablation** — original-language precision: clustering separation + word-study queries over confusable create-family verbs (ULT bodies, spine.db ground truth). Arms: body / code+gloss / gloss-only / **hebrew_lemma** / **lemma+gloss** (the last two = arm A, anchoring in the original language's own space) |
| `reconcile.py` | UHB↔BHSA Strong's reconciliation (validation + residual catalogue) |
| `strongs_equivalence.tsv` | hand-built variant→canonical Strong's map (closes the OSHB↔crosswalk gap) |
| `reconciliation/` | reconciliation outputs (per-book rates, residual pairs, summary) |
| `spine.db` | parser output (SQLite `spine_words`) — gitignored, re-derivable |
| `data/` | downloaded sources (crosswalk CSV, etc.) — gitignored |
| `ATTRIBUTION.md` | source licenses — **note the non-commercial constraint** |

## Status

- Reconciliation **solved at 99.59%** OT-wide (`reconciliation/summary.md`).
- Parser **implemented** (`parse.py`) — fetches the pinned UHB `v2.1.32` /
  UGNT `v0.34`, parses to per-word records with fidelity assertions,
  writes `spine.db`. Spec: [`../docs/spine-parser.md`](../docs/spine-parser.md).
- Gloss dictionary **built** (`strongs_gloss.tsv`) — **100% coverage** of
  the OT spine's content words.
- Prefix builder **implemented** (`prefix.py`) — Location + Lexical lines
  (no dedup; broad-range cap; gloss-only ablation flag). Genesis 1:1:
  `Genesis 1:1 | GEN 1:1` / `H7225 first H1254 create H430 God H8064 heaven H776 land`.
- Ablations **run and concluded** (`ablation.py`, `ablation_wordstudy.py`):
  prepending the prefix did **not** beat the English body on the production
  model; the original-language lemma arms scored worst on clustering
  separation. **No re-embed.** The prefix builder stands as the generator
  for the deterministic tag layer, not for embedding inputs. Full evidence:
  `docs/embedding-enrichment.md`.

## Run

Run from `bcv-RAG/` with `PYTHONPATH=.` (Python 3.11+ does not auto-add the
current dir to the import path):

```bash
cd bcv-RAG
PYTHONPATH=. python3 -m spine.parse           # build spine.db (OT+NT) — needs httpx
PYTHONPATH=. python3 -m spine.parse --ot      # OT only
PYTHONPATH=. python3 -m spine.build_glosses   # build strongs_gloss.tsv — needs httpx
PYTHONPATH=. python3 -m spine.reconcile       # validate vs BHSA — needs cfabric + local BHSA

# ablation — needs voyageai (pip install voyageai); set the model to match production:
PYTHONPATH=. BTMCP_EMBEDDING_MODEL=voyage-3-large VOYAGE_API_KEY=... \
  python3 -m spine.ablation
```

The ablation prints MRR / recall@1 / recall@3 for **body** vs **prefix** vs
**gloss_only**, with a cross-lingual subset (foreign-language verse bodies an
English query can only reach via the spine's anchors) and a per-query
rank breakdown. A prefix that helps would show higher MRR — but it did
**not** (see Status above and `docs/embedding-enrichment.md`); the tool is
kept to reproduce that result.

## Licensing

Sources include **non-commercial** data (OpenHebrewBible CC BY-NC, BHSA
CC BY-NC-SA). The spine and anything derived from it are therefore
non-commercial. See `ATTRIBUTION.md`.
