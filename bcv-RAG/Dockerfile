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

# Download + compile Context-Fabric corpora (BHSA + Nestle1904).
# This is expensive (~5-10 min) and only depends on pip packages,
# so it runs BEFORE copying app code to preserve Docker cache.
ENV HOME=/root
RUN python -c "\
from tf.app import use; \
use('ETCBC/bhsa', silent='deep'); \
use('ETCBC/nestle1904', silent='deep')" \
 && echo '=== Corpus pre-download OK ==='

RUN python -c "\
import cfabric; \
CF = cfabric.Fabric(locations='/root/text-fabric-data/github/ETCBC/bhsa/tf/2021', silent=True); \
CF.loadAll(silent=True); \
print('Compiled: BHSA')" \
 && echo '=== BHSA .cfm OK ==='

RUN mv /root/text-fabric-data/github/ETCBC/nestle1904/tf/*/nodeId.tf \
       /root/text-fabric-data/github/ETCBC/nestle1904/tf/nodeId.tf._skip 2>/dev/null; \
    python -c "\
import cfabric; \
CF = cfabric.Fabric(locations='/root/text-fabric-data/github/ETCBC/nestle1904/tf/0.4.0', silent=True); \
CF.loadAll(silent=True); \
print('Compiled: Nestle1904')" \
 && mv /root/text-fabric-data/github/ETCBC/nestle1904/tf/nodeId.tf._skip \
       /root/text-fabric-data/github/ETCBC/nestle1904/tf/*/nodeId.tf 2>/dev/null; \
    echo '=== Nestle1904 .cfm OK ==='

COPY bcv-RAG/indexer /app/indexer
COPY bcv-RAG/ingest  /app/ingest
COPY bcv-RAG/query   /app/query
COPY bcv-RAG/server  /app/server
COPY bcv-RAG/corpus  /app/corpus
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
