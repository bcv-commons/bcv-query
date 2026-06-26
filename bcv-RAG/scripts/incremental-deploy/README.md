# Incremental data deploy (hybrid)

Ship a small **delta** (changed rows + new vectors) instead of rsyncing the whole
multi-GB `index.db`. Embedding stays **local** (where your GPU is); the server
only imports the delta and rebuilds FTS — it never re-builds rows, so chunk_ids
can never diverge from the vectors they belong to.

```
export_delta.py   (local)   build delta.db from the freshly-embedded index
import_delta.py   (server)  apply rows + vectors to a WORK COPY  (runs in the image)
rebuild_fts.py    (server)  delete-all + repopulate every FTS partition
deploy.sh                   orchestrates the server side: scp → import → fts → swap
```

Why this shape (vs. having the server build rows from staging): the rows come
from the same machine that produced the vectors, so a chunk_id mismatch is
structurally impossible; and FTS is refreshed by the *delete-all* path (one
command per partition, never per-row), which avoids the FTS5 external-content
corruption that mass per-row deletes can trigger.

---

## When to use it

Adding or changing a bounded slice of content (a new language, a new source, a
re-ingested resource) where re-shipping the entire index would be wasteful. For
a from-scratch rebuild, or a change touching most documents, just build + embed
locally and deploy the whole `index.db`.

Not suitable for **large deletions**: `import_delta.py` aborts above
`--max-deletes` (default 5000), because deletes cascade into the per-row FTS
delete trigger. For big removals, do a full rebuild + whole-index deploy.

---

## Sequence

All local steps use your project venv, from `bcv-RAG/`.

```bash
cd bcv-RAG

# 1. Snapshot the chunk_ids that lack a vector NOW — these are the vectors to
#    ship. (Captures any previously-deployed-but-unembedded backlog as well as
#    the new content.)
.venv/bin/python - <<'PY'
import sys; sys.path.insert(0,'.')
from indexer.db import open_db
db = open_db('indexer/index.db')
ids = [r[0] for r in db.execute(
    "SELECT id FROM chunks WHERE id NOT IN (SELECT chunk_id FROM chunks_vec)")]
open('/tmp/pending_chunk_ids.txt','w').write("\n".join(ids))
print(len(ids), "pending chunk_ids snapshotted")
PY

# 2. (optional) List doc_ids to DELETE on the server, e.g. docs you removed
#    locally that the server still has. Write one id per line to /tmp/del_ids.txt.

# 3. Embed locally (GPU). Fills vectors for the snapshotted chunks.
.venv/bin/python -m indexer.embed --local

# 4. Build the delta: new/changed ROWS (via --rows-where) + all newly-embedded
#    VECTORS (--extra-vec-ids-file) + DELETES (--deletes-file).
python scripts/incremental-deploy/export_delta.py \
  --db indexer/index.db \
  --rows-where "<SQL predicate over `documents` selecting the changed docs>" \
  --extra-vec-ids-file /tmp/pending_chunk_ids.txt \
  --deletes-file /tmp/del_ids.txt \
  --out /tmp/delta.db

# 5. Deploy (server side, automated). Configure the target via env first:
export BCV_HOST=user@your.server
export BCV_DATA_DIR=/path/to/data        # the dir bind-mounted to /data
export BCV_IMAGE=bcv-commons/bcv-rag:latest
scripts/incremental-deploy/deploy.sh /tmp/delta.db
```

`--rows-where` is a raw SQL predicate over the `documents` table — e.g.
`"id IN (SELECT doc_id FROM tags WHERE tag='lang:fr')"`. It selects which docs'
rows (documents/chunks/tags/passage_refs) ship; their vectors ship automatically,
and `--extra-vec-ids-file` adds vectors for chunks whose rows are *already* on
the server.

---

## Safety / rollback

- The live `index.db` is **never** mutated in place — all work happens on
  `index.db.work`, swapped in only after `import_delta.py` passes `quick_check`
  + count asserts + "every imported chunk has a vector", and `rebuild_fts.py`
  passes `quick_check`.
- The previous DB is kept as `index.db.bak`. Rollback (the `deploy.sh` epilogue
  prints the exact command for your configured host):
  `cd <data> && mv index.db.bak index.db && cd <compose-dir> && docker compose restart`
- `import_delta.py` also aborts if the delta's `embedding_model` differs from the
  index's — a guard against silently mixing vector spaces.

## Maintenance note

`rebuild_fts.py` **duplicates** `indexer/build.py`'s `V3_KIND_TO_FTS` partition
routing. If a new per-kind FTS partition is added to the build, add it here too.
(Future cleanup: extract build's FTS block into a shared `indexer.fts.repopulate`
and call it from both.)
