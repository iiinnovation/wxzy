#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
ENV_FILE="$ROOT_DIR/deploy/production/.env.production"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing production environment: $ENV_FILE" >&2
  exit 1
fi

read -r -s -p "WeChat AppSecret: " secret
echo
if [[ ${#secret} -lt 16 || ${#secret} -gt 256 ]]; then
  unset secret
  echo "AppSecret length is invalid" >&2
  exit 1
fi
if [[ "$secret" == *$'\n'* || "$secret" == *$'\r'* ]]; then
  unset secret
  echo "AppSecret contains invalid line breaks" >&2
  exit 1
fi

temporary="$(mktemp "$ENV_FILE.XXXXXX")"
trap 'rm -f "$temporary"' EXIT
found=false
while IFS= read -r line || [[ -n "$line" ]]; do
  if [[ "$line" == WECHAT_APP_SECRET=* ]]; then
    printf 'WECHAT_APP_SECRET=%s\n' "$secret" >> "$temporary"
    found=true
  else
    printf '%s\n' "$line" >> "$temporary"
  fi
done < "$ENV_FILE"
if [[ "$found" != true ]]; then
  printf 'WECHAT_APP_SECRET=%s\n' "$secret" >> "$temporary"
fi
unset secret
chmod 600 "$temporary"
mv "$temporary" "$ENV_FILE"
trap - EXIT
echo "WeChat AppSecret saved to the protected production environment"
