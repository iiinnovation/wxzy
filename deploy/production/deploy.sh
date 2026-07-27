#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/deploy/production/compose.yml"
ENV_FILE="$ROOT_DIR/deploy/production/.env.production"
PROJECT_NAME="${WXZY_COMPOSE_PROJECT:-wxzy}"
API_HOST_PORT="${WXZY_API_HOST_PORT:-18000}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing production environment: $ENV_FILE" >&2
  exit 1
fi

if grep -Eq '^(POSTGRES_PASSWORD|WECHAT_APP_SECRET)=$|^(POSTGRES_PASSWORD|WECHAT_APP_SECRET)=(replace_|REPLACE_)' "$ENV_FILE"; then
  echo "production secrets are missing or still use placeholders" >&2
  exit 1
fi

cd "$ROOT_DIR"
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config --quiet
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build api migrate import-publication
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d db
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" run --rm migrate
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" run --rm import-publication
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d api
docker compose -p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps

for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error "http://127.0.0.1:$API_HOST_PORT/health" >/dev/null; then
    echo "wxzy production API is healthy"
    exit 0
  fi
  sleep 2
done

echo "wxzy production API did not become healthy" >&2
exit 1
