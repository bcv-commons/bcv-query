# occurrences/

**Gitignored, regenerable build artifact** — not served, not committed.

Per-occurrence Hebrew sidecar feeding the lex-anchored sense layer:
- `hbo.db` — one row per Hebrew word occurrence (lex, stem, assigned sense, clause).
- `context_emb.npz` — bge-m3 embeddings of each occurrence's Hebrew clause.

These are inputs to the sense clustering (`bcv-RAG/scripts/cluster_senses_hebrew.py`);
the **served truth** is `../senses/hbo_lex.tsv` plus the Strong's/lex tags baked into
the bcv-RAG index. Both files are regenerable from BHSA/MACULA — see
[`docs/sense-layer-pipeline.md`](../../docs/sense-layer-pipeline.md).
