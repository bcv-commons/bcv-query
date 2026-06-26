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
Rollback: `git -C <repo> checkout <tag-or-sha> && deploy/deploy.sh <svc> --no-pull`.
