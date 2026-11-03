#!/usr/bin/env bash
# Back up the Docker deployment: a pg_dump of the database plus tarballs of the data volumes.
# Usage (repository root): scripts/backup.sh [backup-dir]   (default: deploy/backups/<timestamp>)
# Restore: see docs/deployment-docker.md, section "Backup and restore".
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE=(docker compose -f deploy/docker-compose.yml)
PROJECT=research-agent
STAMP=$(date +%Y%m%d-%H%M%S)
OUT=${1:-deploy/backups/$STAMP}
mkdir -p "$OUT"
chmod 700 "$OUT"
echo "database -> $OUT/db.dump"
"${COMPOSE[@]}" exec -T db pg_dump -U research -d research --format=custom > "$OUT/db.dump"
for volume in runs cache uploads evals gold caddydata; do
  if docker volume inspect "${PROJECT}_${volume}" > /dev/null 2>&1; then
    echo "volume $volume -> $OUT/$volume.tgz"
    docker run --rm -v "${PROJECT}_${volume}:/v:ro" -v "$(cd "$OUT" && pwd):/backup" alpine \
      tar czf "/backup/$volume.tgz" -C /v .
  fi
done
echo "done: $OUT (also keep RESEARCH_SECRETS_KEY from deploy/.env somewhere safe: saved user keys need it)"
