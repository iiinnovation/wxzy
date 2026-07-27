#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DB_PATH="$(mktemp /private/tmp/wxzy-mobile-e2e.XXXXXX.db)"
API_PORT="${WXZY_E2E_API_PORT:-18001}"
APP_PORT="${WXZY_E2E_APP_PORT:-4175}"
API_PID=""
APP_PID=""

cleanup() {
  [[ -n "$API_PID" ]] && kill "$API_PID" 2>/dev/null || true
  [[ -n "$APP_PID" ]] && kill "$APP_PID" 2>/dev/null || true
  rm -f "$DB_PATH"
}
trap cleanup EXIT INT TERM

export APP_ENV=test
export AUTH_MODE=wechat
export WECHAT_APP_ID=wx-mobile-e2e
export WECHAT_APP_SECRET=mobile-e2e-secret-not-for-production
export DATABASE_URL="sqlite+pysqlite:///$DB_PATH"
export WXZY_MOBILE_E2E=1
export PYTHONPATH="$ROOT_DIR/server"

cd "$ROOT_DIR/server"
.venv/bin/alembic upgrade head >/private/tmp/wxzy-mobile-e2e-alembic.log
ACTIVATION_CODE="$(.venv/bin/python ../tools/mobile_e2e_seed.py)"
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" >/private/tmp/wxzy-mobile-e2e-api.log 2>&1 &
API_PID="$!"

cd "$ROOT_DIR/mobile"
env VITE_API_BASE_URL="http://127.0.0.1:$API_PORT" npm run dev -- --host 127.0.0.1 --port "$APP_PORT" >/private/tmp/wxzy-mobile-e2e-web.log 2>&1 &
APP_PID="$!"

for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:$API_PORT/health" >/dev/null 2>&1 && curl -fsS "http://127.0.0.1:$APP_PORT/" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

curl -fsS "http://127.0.0.1:$API_PORT/health" >/dev/null
curl -fsS "http://127.0.0.1:$APP_PORT/" >/dev/null

env \
  WXZY_E2E_APP_URL="http://127.0.0.1:$APP_PORT" \
  WXZY_E2E_ACTIVATION_CODE="$ACTIVATION_CODE" \
  npx playwright test e2e/learning-flow.spec.ts
