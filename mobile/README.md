# Wenxi mobile

React, TypeScript, Vite, and Capacitor client for the private Android application.

## Web checks

```bash
npm ci
cp .env.example .env.local
npm run lint
npm run typecheck
npm test
VITE_API_BASE_URL=https://api.luoandlt.xin npm run build
```

Set `VITE_API_BASE_URL` to the HTTPS API origin without `/api/v1`. Development defaults to
`http://127.0.0.1:8000`; production builds must set the variable explicitly. The browser runtime
uses an in-memory Session store and never persists tokens to `localStorage`.

## Android debug build

Install JDK 21 and Android SDK 36, then export standard SDK variables for the local installation:

```bash
export JAVA_HOME=/path/to/jdk-21
export ANDROID_SDK_ROOT=/path/to/android-sdk
export PATH="$ANDROID_SDK_ROOT/platform-tools:$PATH"

npm ci
VITE_API_BASE_URL=https://api.luoandlt.xin npm run build
npx cap sync android
cd android
./gradlew test lintDebug assembleDebug
```

The generated APK is `android/app/build/outputs/apk/debug/app-debug.apk`. The verified internal
test copy is `artifacts/wenxi-0.1.0-debug.apk`. It uses the Android debug certificate and is only
for controlled internal installation tests; do not distribute it as a production release.

The Android runtime stores the Session through the custom `SecureSession` Capacitor plugin. The
plugin encrypts data with an Android Keystore AES-GCM key before writing private SharedPreferences,
and Android system backup is disabled. Compilation and static checks pass, but persistence and
logout still require validation on the target OPPO Find X7 Pro device.

## Release signing pause point

Do not create or commit a release keystore automatically. Before producing a user release, the
owner must choose the keystore password and an offline encrypted backup location. Keep the
keystore and `keystore.properties` outside version control, configure the Gradle release signing
block locally, then build and verify the signed artifact with `apksigner verify --verbose`.

After the owner creates and backs up the keystore, copy `android/keystore.properties.example` to
`android/keystore.properties`, set its four values, and run:

```bash
export ANDROID_SDK_ROOT=/path/to/android-sdk
export JAVA_HOME=/path/to/jdk-21
./scripts/build-release.sh
```

The script builds with the production API origin, syncs Capacitor, runs release lint and unit tests,
requires a configured signing key, verifies the resulting APK signature, and writes the APK,
SHA-256 file, and certificate report under ignored `artifacts/`. A release build fails explicitly
when `keystore.properties` is absent; it never silently emits an unsigned delivery artifact.

To verify any APK independently:

```bash
./scripts/verify-apk.sh /path/to/wenxi.apk
```

A final user release also requires completion of the remaining learning pages, target-device
installation and workflow checks, and an upgrade test signed by the same release certificate.
