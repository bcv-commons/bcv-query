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
#   DATA_SSH   — ssh target, e.g. lgunnars@37.27.81.207 (a normal account with passwordless sudo; root@… also works)
#   DATA_DIR   — remote data dir (the compose `./data`), e.g. /opt/bcv-query/data
#
# The upload is atomic + keeps one .bak: rsync to a temp name, back up the current file,
# then `mv` into place — so the container never reads a half-written file. A RUNNING
# container keeps the old file open (mmap) until recreated, so pick up the new one with:
#   deploy/deploy.sh bcv-rag
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${1:?usage: deploy-data.sh <local-file> [remote-name] [remote-dir]}"
NAME="${2:-$(basename "$SRC")}"
DEST_ARG="${3:-}"                     # optional: override the remote dir (e.g. shoresh's /opt/shoresh/data)

[ -f "$SRC" ] || { echo "no such file: $SRC" >&2; exit 2; }

CFG="${DEPLOY_ENV:-$REPO/deploy/deploy.local.env}"      # DEPLOY_ENV=<file> overrides (testing another target)
[ -f "$CFG" ] || { echo "missing $CFG — copy deploy/deploy.local.env.example and edit it" >&2; exit 2; }
# shellcheck disable=SC1090
. "$CFG"
: "${DATA_SSH:?set DATA_SSH in deploy.local.env (e.g. admin@1.2.3.4, an account with passwordless sudo)}"
DEST="${DEST_ARG:-${DATA_DIR:?set DATA_DIR in deploy.local.env, or pass a remote-dir arg}}"

SIZE="$(du -h "$SRC" | cut -f1)"
echo "→ shipping $SRC ($SIZE) → $DATA_SSH:$DEST/$NAME"
# The data dirs are root-owned. With a root target (root@host) nothing changes; with a normal
# account (the host's admin user, passwordless sudo) the privileged steps run under sudo.
SUDO=""; RSYNC_SUDO=()
case "$DATA_SSH" in
  root@*) ;;
  *) SUDO="sudo"; RSYNC_SUDO=(--rsync-path="sudo rsync") ;;
esac

ssh "$DATA_SSH" "$SUDO mkdir -p '$DEST'"

rsync -h --progress --inplace "${RSYNC_SUDO[@]}" "$SRC" "$DATA_SSH:$DEST/.$NAME.tmp"
ssh "$DATA_SSH" "cd '$DEST' && { [ -f '$NAME' ] && $SUDO cp -f '$NAME' '$NAME.bak' || true; } && $SUDO mv -f '.$NAME.tmp' '$NAME'"

echo "✓ shipped $NAME (previous kept as $NAME.bak)"
echo "  recreate the service to load it:  deploy/deploy.sh bcv-rag"
