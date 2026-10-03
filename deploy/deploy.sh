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
#   deploy/deploy.sh <bcv-rag|shoresh> [--no-pull] [--base] [--rollback]
#     --no-pull   skip `git pull` (deploy the current working tree, e.g. a test)
#     --base      force-rebuild shoresh-base (do this when requirements*.txt or
#                 the spine/ or lxx/ packages change; otherwise it's reused)
#     --rollback  no build: put the image from the previous deploy (<image>:previous)
#                 back and recreate the service
#
# Safety net: before building, the running image is tagged <image>:previous; after
# recreating, the script waits for the container's healthcheck and, if it isn't
# healthy within HEALTH_TIMEOUT seconds (default 180), restores :previous and exits 1.
# (Added after 2026-10-03, when a rebuild pulled an incompatible dependency and the
# old image had already been pruned, so there was nothing to roll back to.)
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SVC="${1:?usage: deploy.sh <bcv-rag|shoresh> [--no-pull] [--base]}"; shift || true

NO_PULL=0; FORCE_BASE=0; ROLLBACK=0
for a in "$@"; do
  case "$a" in
    --no-pull)  NO_PULL=1 ;;
    --base)     FORCE_BASE=1 ;;
    --rollback) ROLLBACK=1; NO_PULL=1 ;;
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

# Tag the image the service runs now as :previous (kept by the build-cache prune below).
keep_previous() { local img="$1"
  if docker image inspect "$img" >/dev/null 2>&1; then
    docker tag "$img" "${img%:*}:previous" && echo "→ kept current image as ${img%:*}:previous"
  fi; }

# Wait for the container's healthcheck; on failure restore :previous and recreate.
verify_or_rollback() { local img="$1" stack="$2" waited=0 st
  local limit="${HEALTH_TIMEOUT:-180}"
  echo "→ waiting for $SVC to report healthy (up to ${limit}s)"
  while [ "$waited" -lt "$limit" ]; do
    st=$(docker inspect "$SVC" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' 2>/dev/null || echo missing)
    case "$st" in
      healthy|running) echo "→ $SVC is $st"; return 0 ;;
    esac
    sleep 5; waited=$((waited + 5))
  done
  echo "✗ $SVC not healthy after ${limit}s (last state: $st). Last log lines:" >&2
  docker logs --tail 20 "$SVC" >&2 || true
  if docker image inspect "${img%:*}:previous" >/dev/null 2>&1; then
    echo "→ rolling back to ${img%:*}:previous" >&2
    docker tag "${img%:*}:previous" "$img"
    compose "$stack" up -d --force-recreate
  else
    echo "✗ no ${img%:*}:previous image to roll back to" >&2
  fi
  exit 1; }

if [ "$NO_PULL" = 0 ] && [ -d "$REPO/.git" ]; then
  echo "→ git pull"; git -C "$REPO" pull --ff-only
fi

case "$SVC" in
  bcv-rag)
    : "${BCV_RAG_STACK:?set BCV_RAG_STACK in deploy.local.env}"
    IMAGE="${BCV_RAG_IMAGE:-bcv-commons/bcv-rag:latest}"
    STACK="$BCV_RAG_STACK"
    if [ "$ROLLBACK" = 1 ]; then
      docker tag "${IMAGE%:*}:previous" "$IMAGE"
    else
      keep_previous "$IMAGE"
      echo "→ build $IMAGE (context: repo root)"
      docker build -f "$REPO/bcv-RAG/Dockerfile" -t "$IMAGE" "$REPO"
    fi
    echo "→ recreate via compose at $STACK"
    compose "$STACK" up -d --force-recreate
    ;;

  shoresh)
    : "${SHORESH_STACK:?set SHORESH_STACK in deploy.local.env}"
    IMAGE="${SHORESH_IMAGE:-shoresh:latest}"
    STACK="$SHORESH_STACK"
    EMB="${SEARCH_EMBEDDER:-berel}"
    if [ "$ROLLBACK" = 1 ]; then
      docker tag "${IMAGE%:*}:previous" "$IMAGE"
      echo "→ recreate via compose at $STACK"
      compose "$STACK" up -d --force-recreate
      verify_or_rollback "$IMAGE" "$STACK"
      echo "✓ rolled back $SVC"; exit 0
    fi
    keep_previous "$IMAGE"
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

verify_or_rollback "$IMAGE" "$STACK"

echo "✓ deployed $SVC — running image: $(docker inspect "$SVC" --format '{{.Image}}' 2>/dev/null || echo '?')"

# Every `docker build` here leaves cache layers behind (BuildKit never expires
# them on its own), and this script runs a native build on the host every
# deploy — left unchecked that's unbounded growth (seen in practice: 30GB+
# after a few weeks). Build cache is pure intermediate layers, not referenced
# by any running container/image, so pruning it is always safe. Deliberately
# NOT `docker image prune`: that would remove shoresh-base:latest (kept on
# purpose above to skip its 3-4 min rebuild) since it has 0 running containers.
echo "→ prune build cache"
docker builder prune -f >/dev/null || true
# Untagged (dangling) images only: each deploy retags :latest and :previous, leaving the image they
# pointed at before untagged. Tagged images (shoresh-base, both :latest, both :previous) are kept.
echo "→ prune untagged images"
docker image prune -f >/dev/null || true
