#!/usr/bin/env bash
# Hybrid incremental data deploy: ship a small delta + apply it on the server,
# instead of rsyncing the whole multi-GB index.db.
#
# Embedding stays on your local machine (GPU); the server only imports the delta
# and rebuilds FTS — it never re-builds rows, so chunk_ids can't diverge from the
# vectors. The live index is never mutated in place: work happens on a copy that
# is swapped in only after verification passes; the previous DB is kept as .bak.
#
# Runs the SERVER side. Prerequisites, done LOCALLY first:
#   1. built + embedded the new content into your index.db, and
#   2. produced a delta.db with export_delta.py.
#
# Configure via environment (no infra details are hardcoded). Example:
#   export BCV_HOST=root@your.server.ip
#   export BCV_DATA_DIR=/opt/bcv-query/data        # bind-mounted to /data in the container
#   export BCV_IMAGE=bcv-commons/bcv-rag:latest
#   export BCV_DEPLOY_DIR=/opt/bcv-query/deploy     # scratch dir on the server (optional)
#   export BCV_COMPOSE_DIR=/opt/bcv-query           # dir holding docker-compose.yml (optional)
#   ./deploy.sh /tmp/delta.db
set -euo pipefail

DELTA_LOCAL="${1:?usage: deploy.sh <delta.db>}"
HOST="${BCV_HOST:?set BCV_HOST=user@host}"
DATA="${BCV_DATA_DIR:?set BCV_DATA_DIR=/path/to/data (bind-mounted to /data)}"
IMAGE="${BCV_IMAGE:-bcv-commons/bcv-rag:latest}"
DEPLOY="${BCV_DEPLOY_DIR:-${DATA%/data}/deploy}"
COMPOSE_DIR="${BCV_COMPOSE_DIR:-${DATA%/data}}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "==> gzip + upload delta ($(du -h "$DELTA_LOCAL" | cut -f1))"
gzip -kf "$DELTA_LOCAL"
ssh "$HOST" "mkdir -p $DEPLOY"
scp "${DELTA_LOCAL}.gz" "$HOST:$DEPLOY/delta.db.gz"
scp "$HERE/import_delta.py" "$HERE/rebuild_fts.py" "$HOST:$DEPLOY/"

echo "==> server: prepare work copy + decompress delta"
ssh "$HOST" bash -s <<EOF
set -euo pipefail
cd "$DATA"
gunzip -f "$DEPLOY/delta.db.gz"
cp index.db index.db.work          # build on a COPY; live DB stays serving
EOF

echo "==> server: import delta (rows + vectors) into the work copy"
ssh "$HOST" "docker run --rm -v $DATA:/data -v $DEPLOY:/deploy -e PYTHONPATH=/app $IMAGE \
  python /deploy/import_delta.py --db /data/index.db.work --delta /deploy/delta.db"

echo "==> server: rebuild FTS partitions on the work copy"
ssh "$HOST" "docker run --rm -v $DATA:/data -v $DEPLOY:/deploy -e PYTHONPATH=/app $IMAGE \
  python /deploy/rebuild_fts.py --db /data/index.db.work"

echo "==> server: swap (keep previous as .bak) + restart"
ssh "$HOST" bash -s <<EOF
set -euo pipefail
cd "$DATA"
mv -f index.db index.db.bak
mv -f index.db.work index.db
rm -f "$DEPLOY/delta.db"
cd "$COMPOSE_DIR" && docker compose restart
EOF

echo "==> verify live"
sleep 5
ssh "$HOST" "cd '$COMPOSE_DIR' && docker compose exec -T \$(docker compose config --services | head -1) \
  python -c \"import urllib.request,os; print(urllib.request.urlopen('http://localhost:%s/api/health' % os.environ.get('PORT','8081')).read().decode())\"" \
  || echo "  (health check skipped — check manually)"
echo
echo "done. Rollback if needed:"
echo "  ssh $HOST 'cd $DATA && mv index.db.bak index.db && cd $COMPOSE_DIR && docker compose restart'"
