#!/bin/sh
# Deterministic candidate gate: current-source baseline with a lower version,
# production lookup/download/PackageInstaller, exact build artifact as target.
# No production test hooks, release uploads or adb install -r of the candidate.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
SDK=${ANDROID_SDK_ROOT:-${ANDROID_HOME:-/usr/local/lib/android/sdk}}
export ANDROID_HOME="$SDK" ANDROID_SDK_ROOT="$SDK"
STAGE="$ROOT/android/out/inapp-candidate"
RELEASE="$ROOT/android/out/release"
mkdir -p "$STAGE"
export ADB="$SDK/platform-tools/adb" ANDROID_SERIAL=emulator-5584
AAPT=$(find "$SDK/build-tools" -path '*/aapt' | sort | tail -1)
SIGNER=$(find "$SDK/build-tools" -path '*/apksigner' | sort | tail -1)
AVDMANAGER=$(find "$SDK/cmdline-tools" -path '*/bin/avdmanager' | head -1)
test -r /dev/kvm && test -w /dev/kvm
# Validate the candidate bytes before deriving a strictly lower synthetic version.
BASE=$(python3 "$ROOT/android/scripts/verify_candidate_update.py" prepare "$RELEASE")
cd "$ROOT/android/apk"
chmod +x ./gradlew
./gradlew assembleDebug assembleDebugAndroidTest -Plorabge.skipNative=true "-Plorabge.versionName=$BASE" --no-daemon
cp app/build/outputs/apk/debug/app-debug.apk "$STAGE/baseline.apk"
cp app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk "$STAGE/test.apk"
CERT_A=$("$SIGNER" verify --print-certs "$STAGE/baseline.apk" | grep 'Signer #1 certificate SHA-256 digest:')
CERT_B=$("$SIGNER" verify --print-certs "$RELEASE/app-debug.apk" | grep 'Signer #1 certificate SHA-256 digest:')
test -n "$CERT_A" && test "$CERT_A" = "$CERT_B"
"$AAPT" dump badging "$RELEASE/app-debug.apk" > "$STAGE/candidate-badging.txt"
export ANDROID_AVD_HOME="$STAGE/avd-home"
mkdir -p "$ANDROID_AVD_HOME"
echo no | "$AVDMANAGER" create avd -n candidate-update -k 'system-images;android-35;google_apis;x86_64' --force
cleanup() {
  "$ADB" -s "$ANDROID_SERIAL" emu kill >/dev/null 2>&1 || true
  for pid in ${INSTRUMENT_PID:-} ${EMU_PID:-} ${XVFB_PID:-}; do
    kill "$pid" >/dev/null 2>&1 || true
    wait "$pid" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT
Xvfb :99 -screen 0 1280x2800x24 -ac > "$STAGE/xvfb.log" 2>&1 &
XVFB_PID=$!
export DISPLAY=:99
"$SDK/emulator/emulator" -avd candidate-update -port 5584 -no-audio -no-boot-anim -no-snapshot -wipe-data -gpu swiftshader_indirect -memory 3072 -accel on -no-metrics > "$STAGE/emulator.log" 2>&1 &
EMU_PID=$!
i=0
until [ "$("$ADB" -s "$ANDROID_SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)" = 1 ]; do
  kill -0 "$EMU_PID"
  i=$((i + 1)); test "$i" -lt 240
  sleep 2
done
"$ADB" -s "$ANDROID_SERIAL" shell input keyevent 82
"$ADB" -s "$ANDROID_SERIAL" install -t "$STAGE/baseline.apk"
"$ADB" -s "$ANDROID_SERIAL" install -t "$STAGE/test.apk"
"$ADB" -s "$ANDROID_SERIAL" shell appops set com.lorabge.memory REQUEST_INSTALL_PACKAGES allow
"$ADB" -s "$ANDROID_SERIAL" shell run-as com.lorabge.memory mkdir -p files/update-fixture files/setup
for name in app-debug.apk update.json; do
  "$ADB" -s "$ANDROID_SERIAL" push "$RELEASE/$name" "/data/local/tmp/$name"
  "$ADB" -s "$ANDROID_SERIAL" shell run-as com.lorabge.memory cp "/data/local/tmp/$name" "files/update-fixture/$name"
done
python3 "$ROOT/android/scripts/verify_candidate_update.py" seed "$RELEASE" "$STAGE"
"$ADB" -s "$ANDROID_SERIAL" shell am instrument -w -r -e class com.lorabge.memory.CandidateUpdateTest com.lorabge.memory.test/androidx.test.runner.AndroidJUnitRunner > "$STAGE/instrumentation.txt" 2>&1 &
INSTRUMENT_PID=$!
# Installing the candidate kills instrumentation. Never use that exit status as PASS.
python3 "$ROOT/android/scripts/verify_candidate_update.py" verify "$RELEASE" "$STAGE"
