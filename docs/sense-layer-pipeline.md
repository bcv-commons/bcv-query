# The lex-anchored sense layer (occurrence → Hebrew-context senses)

How every Hebrew word gets a **sense** that is decided in the original and labelled in any
language — and how to regenerate, retune, or extend it.

## The idea in one line

Anchor on the **most granular original** — the per-occurrence BHSA word — and *derive*
everything coarser: the lexeme's senses, the Strong's-level view, and the English/other-language
labels. Sense *identity* is decided by **Hebrew context**; the gloss is only a *label*.

This is why the layer can do what Strong's can't: split homographs (733 Strong's codes cover
2+ BHSA lexemes), separate binyan meanings (qal "be holy" vs hif "declare holy"), and carry a
per-occurrence sense — all anchored on the Hebrew, none of it imposed from English.

## The pipeline

Each step re-derives from the stored anchor, so improving a later step never forces re-doing
an earlier one. Scripts live in `bcv-RAG/scripts/`.

| # | script | in → out | notes |
|---|---|---|---|
| 1 | `build_lex_occurrences.py` | BHSA → `resources/occurrences/hbo.db` | one row per BHSA word: `node` (stable id), `ref`, `lex`, `stem` (binyan), `strong`, **`context`** (the Hebrew clause), + reserved `gloss`/`sense*`. Needs `cfabric` + the local BHSA text-fabric corpus. |
| 2 | `build_lex_senses.py` | + MACULA glosses | aligns BHSA↔MACULA by Strong's sequence (LCS — MACULA splits suffixes into extra rows), attaches each occurrence's **contextual gloss**, and writes a heuristic (inflection-collapsed) sense baseline. |
| 3 | `embed_context.py` | clauses → `resources/occurrences/context_emb.npz` | **the long batch** — embeds the ~78k distinct Hebrew clauses with local **bge-m3** (multilingual → embeds Hebrew directly). Mac GPU; no Cloudflare/API quota. |
| 4 | `cluster_senses_hebrew.py` | embeddings → `resources/senses/hbo_lex.tsv` | the real derivation: within each `(lex, stem)`, merge gloss-buckets whose **Hebrew-clause centroids** are close (single-linkage, `--thresh 0.88`). Labels: **dominant sense = the curated per-stem gloss** (clean, multilingual-ready); sub-senses = scrubbed MACULA gloss. Re-runs in seconds — sweep `--thresh` without re-embedding. |
| 5 | `tag_lex_occurrences.py` | sidecar → `index.db` tags | adds `lex:` / `stem:` / `lexstem:` / `sense:<lex>.<stem>.<n>` tags to the morphology chunks (verse-ref join, pure inserts — no re-embed; `--revert` removes them). |

`merge_senses_embed.py` is the **superseded** English-gloss-embedding baseline — kept for
reference; step 4 (Hebrew context) replaced it because deciding Hebrew sense boundaries in
English space was an English artifact (it split synonyms the Hebrew sees as one).

## Artifacts

- **Committed / served:** `resources/senses/hbo_lex.tsv` (the inventory) + the `sense:`/`lex:`/
  `stem:` tags written into the bcv-RAG `index.db`.
- **Gitignored build artifacts** (regenerable from BHSA + MACULA): `resources/occurrences/*.db`,
  `resources/occurrences/context_emb.npz`.

## Regenerate / retune

```bash
# 1–2 (cheap): occurrence sidecar + MACULA gloss labels
shoresh/.venv/bin/python bcv-RAG/scripts/build_lex_occurrences.py
python3 bcv-RAG/scripts/build_lex_senses.py
# 3 (the long batch — local bge-m3):
shoresh/.venv/bin/python bcv-RAG/scripts/embed_context.py
# 4 (seconds; retune freely):
python3 bcv-RAG/scripts/cluster_senses_hebrew.py --thresh 0.88
# 5 (apply to an index.db — local, then the server volume):
python3 bcv-RAG/scripts/tag_lex_occurrences.py [path/to/index.db]
```

Prod rollout = copy the ~80M sidecar to the host, run step 5 against the serving
`index.db` (re-tag, no re-embed), commit `hbo_lex.tsv`, deploy bcv-rag + shoresh.

## How it's surfaced

- **bcv-RAG `morphology_concordance` MCP tool** — precise concordance by `lex` + `stem` +
  `sense`; the response lists the available senses so a caller can drill in (e.g. `QDC[ hif`
  sense 1 "consecrate" → its verses, distinct from the sub-senses).
- **shoresh `/wordstudy` card** — `lex_senses`: per lexeme, per binyan, the Hebrew-context
  senses with shares; `gloss_lang` localizes the dominant-sense label into any of the 11
  gloss languages (sense identity stays Hebrew).

## Forward-looking — next steps

- **Sub-sense labels.** Dominant senses read clean (the curated per-stem gloss); low-share
  sub-senses still show a scrubbed MACULA gloss (e.g. "setting apart as holy"). Options: a
  light English lemmatiser, or an LLM pass to mint short sense names. Cheap — it's a re-label
  on the stored anchor (re-run step 4 only).
- **Multilingual sub-senses.** Only the *dominant* sense is multilingual today (it reuses the
  curated per-stem gloss). Sub-senses are English. To localise them, map each sense cluster to
  a target-language gloss (per-stem gloss + LLM fallback) — the clusters are language-neutral.
- **Sense-correct synthesis.** The per-occurrence `sense` is in the sidecar and the index tags
  but is not yet fed into bcv-RAG answer *grounding*. Wiring the cited verse's sense into the
  synthesis prompt would reduce sense-confusion in generated answers.
- **Publish.** `hbo_lex.tsv` (lex-anchored, binyan-aware, homograph-split, occurrence-derived)
  is a reusable dataset in its own right — a candidate for the `bcv-commons` org alongside
  `strongs`.
- **Aramaic + Greek.** Aramaic verbs have stems too (small tail). Greek has no binyanim, so its
  "senses" are single — the layer is meaningfully Hebrew-only; that's expected.
- **A finer anchor.** Today the context is the BHSA *clause*. A tighter window (the target word
  + syntactic dependents) or a target-marked embedding could sharpen rare-sense clusters — a
  pure re-derivation (re-run steps 1, 3, 4), no re-ingest.

## Related

- Glosses (the per-stem multilingual labels): `resources/word_glosses/README.md`.
- The occurrence/binyan retrieval foundation (Phase 1) and the published Strong's dataset are
  summarised in `docs/ROADMAP.md`.
