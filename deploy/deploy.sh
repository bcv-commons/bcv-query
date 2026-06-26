#!/usr/bin/env bash
#
# Generic native build + compose deploy for bcv-query services.
#
# Host-agnostic: this script holds only generic build/deploy LOGIC. Everything
# host-specific lives outside git —
#   • paths/image names → deploy/deploy.local.env  (gitignored; copy from the
#     .example next to it)
#   • volumes, ports, secrets → each host's compose file + its .env
#
# Builds the image NATIVELY on the host (no registry round-trip) and recreates
# the service via its docker compose stack. Works on any host that has docker +
# compose and a checkout of this repo.
#
#   deploy/deploy.sh <bcv-rag|shoresh> [--no-pull] [--base]
#     --no-pull   skip `git pull` (deploy the current working tree, e.g. a test)
#     --base      force-rebuild shoresh-base (do this when requirements*.txt or
#                 the spine/ or lxx/ packages change; otherwise it's reused)
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SVC="${1:?usage: deploy.sh <bcv-rag|shoresh> [--no-pull] [--base]}"; shift || true

NO_PULL=0; FORCE_BASE=0
for a in "$@"; do
  case "$a" in
    --no-pull) NO_PULL=1 ;;
    --base)    FORCE_BASE=1 ;;
    *) echo "unknown flag: $a" >&2; exit 2 ;;
  esac
done

CFG="$REPO/deploy/deploy.local.env"
[ -f "$CFG" ] || { echo "missing $CFG — copy deploy/deploy.local.env.example and edit it" >&2; exit 2; }
# shellcheck disable=SC1090
. "$CFG"

# docker compose v2 (plugin) or v1 (docker-compose), run inside a stack dir.
compose() { local dir="$1"; shift
  if docker compose version >/dev/null 2>&1; then (cd "$dir" && docker compose "$@")
  else (cd "$dir" && docker-compose "$@"); fi; }

if [ "$NO_PULL" = 0 ] && [ -d "$REPO/.git" ]; then
  echo "→ git pull"; git -C "$REPO" pull --ff-only
fi

case "$SVC" in
  bcv-rag)
    : "${BCV_RAG_STACK:?set BCV_RAG_STACK in deploy.local.env}"
    IMAGE="${BCV_RAG_IMAGE:-bcv-commons/bcv-rag:latest}"
    echo "→ build $IMAGE (context: repo root)"
    docker build -f "$REPO/bcv-RAG/Dockerfile" -t "$IMAGE" "$REPO"
    echo "→ recreate via compose at $BCV_RAG_STACK"
    compose "$BCV_RAG_STACK" up -d --force-recreate
    ;;

  shoresh)
    : "${SHORESH_STACK:?set SHORESH_STACK in deploy.local.env}"
    IMAGE="${SHORESH_IMAGE:-shoresh:latest}"
    EMB="${SEARCH_EMBEDDER:-berel}"
    # Heavy base (model bake + LXX/spine parse) is a separate image so app-code
    # rebuilds stay fast. Build it only when forced or missing.
    if [ "$FORCE_BASE" = 1 ] || ! docker image inspect shoresh-base:latest >/dev/null 2>&1; then
      echo "→ build shoresh-base:latest (heavy: ~3-4 min; context: shoresh/)"
      docker build -f "$REPO/shoresh/Dockerfile.base" --build-arg SEARCH_EMBEDDER="$EMB" \
        -t shoresh-base:latest "$REPO/shoresh"
    fi
    echo "→ build $IMAGE (thin; context: repo root)"
    docker build -f "$REPO/shoresh/Dockerfile" -t "$IMAGE" "$REPO"
    echo "→ recreate via compose at $SHORESH_STACK"
    compose "$SHORESH_STACK" up -d --force-recreate
    ;;

  *) echo "unknown service: $SVC (expected bcv-rag|shoresh)" >&2; exit 2 ;;
esac

echo "✓ deployed $SVC — running image: $(docker inspect "$SVC" --format '{{.Image}}' 2>/dev/null || echo '?')"
