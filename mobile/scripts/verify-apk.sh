#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /path/to/wenxi.apk" >&2
  exit 2
fi
if [[ -z "${ANDROID_SDK_ROOT:-}" ]]; then
  echo "ANDROID_SDK_ROOT is required" >&2
  exit 2
fi

APK="$1"
APKSIGNER="$(find "$ANDROID_SDK_ROOT/build-tools" -type f -name apksigner | sort | tail -1)"
AAPT="$(find "$ANDROID_SDK_ROOT/build-tools" -type f -name aapt | sort | tail -1)"

test -f "$APK"
"$APKSIGNER" verify --verbose --print-certs "$APK"
"$AAPT" dump badging "$APK" | head -5
shasum -a 256 "$APK"
