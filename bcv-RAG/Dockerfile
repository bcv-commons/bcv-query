FROM python:3.13-slim AS base

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Install python deps (cache-bust: httpx added 2026-06-05)
# NOTE: build context is the REPO ROOT (build with `docker build -f bcv-RAG/Dockerfile .`)
# so the shared repo-root resources/ dir is in context. App code is under bcv-RAG/.
COPY bcv-RAG/indexer/requirements.txt /app/indexer/requirements.txt
COPY bcv-RAG/ingest/requirements.txt  /app/ingest/requirements.txt
COPY bcv-RAG/query/requirements.txt   /app/query/requirements.txt
COPY bcv-RAG/server/requirements.txt  /app/server/requirements.txt
RUN pip install --no-cache-dir \
    -r /app/indexer/requirements.txt \
    -r /app/ingest/requirements.txt \
    -r /app/query/requirements.txt \
    -r /app/server/requirements.txt

# The Context-Fabric corpus engine (BHSA + Nestle1904) was removed from bcv-RAG and
# now lives in shoresh (migration). bcv-RAG's search path fetches syntactic data
# from shoresh over SHORESH_URL (see server/corpus_cards.py) — no engine, no
# text-fabric deps, and no corpus volume mount here anymore.

COPY bcv-RAG/indexer /app/indexer
COPY bcv-RAG/ingest  /app/ingest
COPY bcv-RAG/query   /app/query
COPY bcv-RAG/server  /app/server
COPY bcv-RAG/resource_paths.py /app/resource_paths.py
COPY bcv-RAG/lang.py           /app/lang.py
# Shared data resources (repo-root resources/, Strong's/BCVW-keyed) — consumed
# via resource_paths.resource_path() (BCV_RESOURCES_DIR set below).
COPY resources /app/resources

ENV HOME=/root
ENV PYTHONUNBUFFERED=1
ENV INDEX_DB_PATH=/data/index.db
ENV BCV_RESOURCES_DIR=/app/resources
ENV PORT=8080
# Create the mountpoint directory at build time. Originally `VOLUME ["/data"]`
# did this implicitly, but Railway rejects that directive (mounts come from
# their Volumes config, not Dockerfile). Without an explicit mkdir, SQLite
# raises `OperationalError: unable to open database file` on the first
# request — the /data path simply doesn't exist in the image. Once a Railway
# volume is attached, it overlays this directory (preserving any files in
# the volume).
RUN mkdir -p /data
EXPOSE 8080

# Default: run the FastAPI HTTP server (REST + MCP).
# Override CMD to run the CLI (e.g. `python -m query.ask "..."`) or
# the stdio MCP transport (`python -m server.mcp.stdio`).
# --proxy-headers + --forwarded-allow-ips: trust X-Forwarded-For from the local
#   reverse proxy so per-IP rate limiting keys on the real client, not the proxy.
#   (Bind the published port to 127.0.0.1 in compose so only the proxy reaches
#   the container — then trusting "*" here is safe; tighten to the proxy IP else.)
# --limit-concurrency: shed load (503) under a flood instead of melting down.
CMD ["sh", "-c", "uvicorn server.app:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips=* --limit-concurrency ${UVICORN_LIMIT_CONCURRENCY:-64} --timeout-keep-alive 10"]
