#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/deploy/production/compose.yml"
ENV_FILE="$ROOT_DIR/deploy/production/.env.production"
PROJECT_NAME="${WXZY_COMPOSE_PROJECT:-wxzy}"
API_HOST_PORT="${WXZY_API_HOST_PORT:-18000}"
BACKUP_FILE="${1:-}"

if [[ -z "$BACKUP_FILE" || ! -f "$BACKUP_FILE" ]]; then
  echo "usage: CONFIRM_RESTORE=wxzy $0 /path/to/wxzy-backup.sql.gz" >&2
  exit 1
fi
if [[ "${CONFIRM_RESTORE:-}" != "wxzy" ]]; then
  echo "restore requires CONFIRM_RESTORE=wxzy" >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing production environment: $ENV_FILE" >&2
  exit 1
fi
if grep -Eq '^POSTGRES_PASSWORD=$|^POSTGRES_PASSWORD=(replace_|REPLACE_)' "$ENV_FILE"; then
  echo "production database secret is missing or still uses a placeholder" >&2
  exit 1
fi

gzip -t "$BACKUP_FILE"
if [[ -f "$BACKUP_FILE.sha256" ]]; then
  (cd "$(dirname "$BACKUP_FILE")" && sha256sum -c "$(basename "$BACKUP_FILE").sha256")
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
export WXZY_API_HOST_PORT="$API_HOST_PORT"

docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \
  up -d --wait --wait-timeout 120 db
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" stop api || true
gzip -dc "$BACKUP_FILE" | docker compose -p "$PROJECT_NAME" \
  --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T db \
  psql --set ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d api

for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error "http://127.0.0.1:$API_HOST_PORT/health" >/dev/null; then
    echo "wxzy restore completed and API is healthy"
    exit 0
  fi
  sleep 2
done

echo "restore completed but API did not become healthy" >&2
exit 1
