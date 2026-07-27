#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ANDROID_DIR="$ROOT_DIR/android"
OUTPUT_DIR="$ROOT_DIR/artifacts"
API_BASE_URL="${VITE_API_BASE_URL:-https://api.luoandlt.xin}"

if [[ ! -f "$ANDROID_DIR/keystore.properties" ]]; then
  echo "Missing $ANDROID_DIR/keystore.properties" >&2
  echo "Copy keystore.properties.example and configure the owner-managed release keystore." >&2
  exit 2
fi

if [[ -z "${ANDROID_SDK_ROOT:-}" ]]; then
  echo "ANDROID_SDK_ROOT is required" >&2
  exit 2
fi

APKSIGNER="$(find "$ANDROID_SDK_ROOT/build-tools" -type f -name apksigner | sort | tail -1)"
if [[ -z "$APKSIGNER" ]]; then
  echo "apksigner was not found under $ANDROID_SDK_ROOT/build-tools" >&2
  exit 2
fi

cd "$ROOT_DIR"
env VITE_API_BASE_URL="$API_BASE_URL" npm run build
npx cap sync android

cd "$ANDROID_DIR"
./gradlew test lintRelease assembleRelease

APK_SOURCE="$ANDROID_DIR/app/build/outputs/apk/release/app-release.apk"
if [[ ! -f "$APK_SOURCE" ]]; then
  echo "Signed release APK was not produced at $APK_SOURCE" >&2
  exit 1
fi

VERSION_NAME="$(sed -n 's/.*versionName "\([^"]*\)".*/\1/p' "$ANDROID_DIR/app/build.gradle" | head -1)"
APK_NAME="wenxi-${VERSION_NAME}-release.apk"
mkdir -p "$OUTPUT_DIR"
cp "$APK_SOURCE" "$OUTPUT_DIR/$APK_NAME"

"$APKSIGNER" verify --verbose --print-certs "$OUTPUT_DIR/$APK_NAME" > "$OUTPUT_DIR/$APK_NAME.cert.txt"
shasum -a 256 "$OUTPUT_DIR/$APK_NAME" > "$OUTPUT_DIR/$APK_NAME.sha256"

echo "Release artifact: $OUTPUT_DIR/$APK_NAME"
cat "$OUTPUT_DIR/$APK_NAME.sha256"
echo "Certificate report: $OUTPUT_DIR/$APK_NAME.cert.txt"
