#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -n "${PYTHON:-}" ]]; then
  PYTHON_BIN="$PYTHON"
elif [[ -x "server/.venv/bin/python" ]]; then
  PYTHON_BIN="server/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo "quality gate: Python 3.12+ not found" >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "quality gate: Node.js not found" >&2
  exit 1
fi

echo "==> runtime"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 12), sys.version'
node --version

echo "==> python lint and format"
"$PYTHON_BIN" -m ruff check server tools
"$PYTHON_BIN" -m ruff format --check server tools
"$PYTHON_BIN" -m mypy server/app server/migrations tools

echo "==> tests and coverage"
"$PYTHON_BIN" tools/quality_checks.py tests
"$PYTHON_BIN" -m coverage run -m pytest -q
"$PYTHON_BIN" -m coverage report

echo "==> miniprogram JavaScript"
js_count=0
while IFS= read -r file; do
  node --check "$file"
  js_count=$((js_count + 1))
done < <(find miniprogram -type f -name '*.js' -print | LC_ALL=C sort)
if [[ "$js_count" -eq 0 ]]; then
  echo "quality gate: no miniprogram JavaScript files found" >&2
  exit 1
fi
echo "javascript: ok ($js_count files)"

echo "==> structured files and documentation"
"$PYTHON_BIN" tools/quality_checks.py json
"$PYTHON_BIN" tools/quality_checks.py docs

echo "quality gate: PASS"
