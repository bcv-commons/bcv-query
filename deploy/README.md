# deploy/

Host-agnostic deploy for the bcv-query services (`bcv-rag`, `shoresh`). The image
is built **natively on the host** (no registry) and the service is recreated via
its docker compose stack.

The split that keeps this generic:
- **`deploy.sh`** — generic build/deploy logic (tracked).
- **`deploy.local.env`** — your host's paths/image names (gitignored; copy from
  `deploy.local.env.example`). **No secrets.**
- **each stack's `docker-compose.yml` + `.env`** — host-specific volumes, ports,
  and secrets (live on the host, not in this repo). See `examples/`.

## Deploy (existing host)
```bash
deploy/deploy.sh bcv-rag           # git pull → build → compose up --force-recreate
deploy/deploy.sh shoresh
deploy/deploy.sh shoresh --base    # also rebuild shoresh-base (after requirements/spine/lxx change)
deploy/deploy.sh bcv-rag --no-pull # build the current tree without pulling (local test)
```

## New host (one-time provisioning)
1. Checkout this repo on the host (public — `git clone https://github.com/bcv-commons/bcv-query.git`).
2. `cp deploy/deploy.local.env.example deploy/deploy.local.env` and set `BCV_RAG_STACK` / `SHORESH_STACK` to where each stack will live.
3. For each service: create the stack dir, copy `deploy/examples/<svc>.compose.yml` → `<stack>/docker-compose.yml`, create its `.env` (secrets) and `data/`, and provision any host volumes the compose references (e.g. the text-fabric corpus for shoresh, and `index.db` in bcv-rag's `data/`).
4. `deploy/deploy.sh <svc>`.

Requirements on the host: docker + compose (v2 plugin or v1) and git.
Rollback: every deploy first tags the running image `<image>:previous`, then waits for the new
container's healthcheck; if it isn't healthy within `HEALTH_TIMEOUT` seconds (default 180) the
script restores `:previous` by itself and exits 1. To roll back by hand later:
`deploy/deploy.sh <svc> --rollback` (one step back). For older versions:
`git -C <repo> checkout <tag-or-sha> && deploy/deploy.sh <svc> --no-pull`.

## Data artifacts on the shoresh volume

Some data is built locally or fetched, not baked into the image or tracked in git. It lives under the shoresh `data/` volume (`/data` in the container) and is shipped with `deploy/deploy-data.sh <file> <name> [remote-dir]`:

| Path in `/data` | What | How it gets there |
|---|---|---|
| `public/lexeme-spine-macula.db` (published at `/files`), `verse-senses.db` | MACULA lexeme spine + per-occurrence senses (`LEXEME_BASE=macula`; `VERSE_HEBREW_BASE=macula` reads `macula-spine.db`). Both are looked up in `/data` and `/data/public` | `deploy-data.sh` |
| `word_glosses/hbo_lexeme/<Language>.csv` | MACULA-keyed BibleOL glosses (build output of `shoresh/macula/build_word_glosses_lexeme.py`) | one `deploy-data.sh` call per file with remote dir `.../word_glosses/hbo_lexeme` |
| `vrs/` | bibles' versification files | fetched from `cdn.bibel.wiki` on first use and revalidated by ETag daily; `deploy-data.sh shoresh/data/vrs/index.json index.json <data>/vrs` pre-seeds it |

The switches (`VERSE_HEBREW_BASE`, `LEXEME_BASE`, `SHORESH_FILES_BASE`) are environment entries in the stack's `docker-compose.yml`; change one, then `docker compose up -d shoresh`. The bcv-RAG `index.db` is retagged locally (`bcv-RAG/scripts/tag_lexeme_occurrences.py <index.db>`) before upload.
