#!/usr/bin/env bash
set -euo pipefail

umask 077
ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/deploy/production/compose.yml"
ENV_FILE="$ROOT_DIR/deploy/production/.env.production"
PROJECT_NAME="${WXZY_COMPOSE_PROJECT:-wxzy}"
BACKUP_DIR="${WXZY_BACKUP_DIR:-/var/backups/wxzy}"
RETENTION_DAYS="${WXZY_BACKUP_RETENTION_DAYS:-14}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing production environment: $ENV_FILE" >&2
  exit 1
fi

if grep -Eq '^POSTGRES_PASSWORD=$|^POSTGRES_PASSWORD=(replace_|REPLACE_)' "$ENV_FILE"; then
  echo "production database secret is missing or still uses a placeholder" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

mkdir -p "$BACKUP_DIR"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$BACKUP_DIR/wxzy-$timestamp.sql.gz"
temporary="$target.tmp"
trap 'rm -f "$temporary"' EXIT

docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T db \
  pg_dump --clean --if-exists --no-owner --no-privileges \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" | gzip -9 > "$temporary"

gzip -t "$temporary"
mv "$temporary" "$target"
trap - EXIT
(cd "$BACKUP_DIR" && sha256sum "$(basename "$target")" > "$(basename "$target").sha256")
find "$BACKUP_DIR" -type f -name 'wxzy-*.sql.gz*' -mtime "+$RETENTION_DAYS" -delete
echo "$target"
