#!/usr/bin/env bash
#
# Ship a locally-built data artifact (index.db, hbo.db, …) to the host data volume.
#
# These .db files are built LOCALLY (BHSA + local GPU sense-embedding for hbo.db; the
# embedded index for index.db) — NOT in git, NOT buildable in Docker (unlike shoresh's
# in-image spine parse). So they follow the index.db pattern: build on the dev machine,
# rsync to the host's mounted `data/` dir, where the container reads them via a path env
# var (INDEX_DB_PATH / HBO_DB_PATH). Runs on the DEV MACHINE (pushes to the host).
#
#   deploy/deploy-data.sh <local-file> [remote-name]
#     deploy/deploy-data.sh resources/occurrences/hbo.db
#     deploy/deploy-data.sh bcv-RAG/indexer/index.db
#
# Host target from deploy/deploy.local.env (gitignored):
#   DATA_SSH   — ssh target, e.g. root@37.27.81.207
#   DATA_DIR   — remote data dir (the compose `./data`), e.g. /opt/bcv-query/data
#
# The upload is atomic + keeps one .bak: rsync to a temp name, back up the current file,
# then `mv` into place — so the container never reads a half-written file. A RUNNING
# container keeps the old file open (mmap) until recreated, so pick up the new one with:
#   deploy/deploy.sh bcv-rag
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${1:?usage: deploy-data.sh <local-file> [remote-name]}"
NAME="${2:-$(basename "$SRC")}"

[ -f "$SRC" ] || { echo "no such file: $SRC" >&2; exit 2; }

CFG="$REPO/deploy/deploy.local.env"
[ -f "$CFG" ] || { echo "missing $CFG — copy deploy/deploy.local.env.example and edit it" >&2; exit 2; }
# shellcheck disable=SC1090
. "$CFG"
: "${DATA_SSH:?set DATA_SSH in deploy.local.env (e.g. root@1.2.3.4)}"
: "${DATA_DIR:?set DATA_DIR in deploy.local.env (e.g. /opt/bcv-query/data)}"

SIZE="$(du -h "$SRC" | cut -f1)"
echo "→ shipping $SRC ($SIZE) → $DATA_SSH:$DATA_DIR/$NAME"
ssh "$DATA_SSH" "mkdir -p '$DATA_DIR'"

rsync -h --progress --inplace "$SRC" "$DATA_SSH:$DATA_DIR/.$NAME.tmp"
ssh "$DATA_SSH" "cd '$DATA_DIR' && { [ -f '$NAME' ] && cp -f '$NAME' '$NAME.bak' || true; } && mv -f '.$NAME.tmp' '$NAME'"

echo "✓ shipped $NAME (previous kept as $NAME.bak)"
echo "  recreate the service to load it:  deploy/deploy.sh bcv-rag"
