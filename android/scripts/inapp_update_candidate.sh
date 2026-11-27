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
python3 "$ROOT/android/scripts/verify_apk_signers.py" --self-test
export ADB="$SDK/platform-tools/adb" ANDROID_SERIAL=emulator-5584
# Use the build-tools version installed by this job, not a rolling runner version.
AAPT="$SDK/build-tools/35.0.0/aapt"
SIGNER="$SDK/build-tools/35.0.0/apksigner"
test -x "$AAPT" && test -x "$SIGNER"
AVDMANAGER=$(find "$SDK/cmdline-tools" -path '*/bin/avdmanager' | head -1)
test -r /dev/kvm && test -w /dev/kvm
# Validate the candidate bytes before deriving a strictly lower synthetic version.
BASE=$(python3 "$ROOT/android/scripts/verify_candidate_update.py" prepare "$RELEASE")
cd "$ROOT/android/apk"
chmod +x ./gradlew
./gradlew assembleDebug assembleDebugAndroidTest -Plorabge.skipNative=true "-Plorabge.versionName=$BASE" --no-daemon
cp app/build/outputs/apk/debug/app-debug.apk "$STAGE/baseline.apk"
cp app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk "$STAGE/test.apk"
python3 "$ROOT/android/scripts/verify_apk_signers.py" "$SIGNER" "$STAGE/baseline.apk" "$RELEASE/app-debug.apk" "$STAGE"
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
i=0
until xdpyinfo >/dev/null 2>&1; do
  kill -0 "$XVFB_PID"
  i=$((i + 1)); test "$i" -lt 50
  sleep 0.2
done
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

# The exact installed candidate (not the synthetic baseline) now exercises
# correction before and after a fresh process. The preservation gate above
# must run first: the UI fixture intentionally replaces disposable test memory.
timeout 30 "$ADB" -s "$ANDROID_SERIAL" shell am force-stop com.lorabge.memory
timeout 30 "$ADB" -s "$ANDROID_SERIAL" shell wm size 480x920
timeout 30 "$ADB" -s "$ANDROID_SERIAL" shell wm density 180
run_candidate_correction() {
  rc=0
  timeout 165 "$ADB" -s "$ANDROID_SERIAL" shell am instrument -w -r \
    -e class com.lorabge.memory.CorrectionChatTest -e correctionMode "$1" \
    com.lorabge.memory.test/androidx.test.runner.AndroidJUnitRunner > "$STAGE/correction-$1.log" 2>&1 || rc=$?
  cat "$STAGE/correction-$1.log"
  test "$rc" -eq 0
  grep -Fq 'OK (1 test)' "$STAGE/correction-$1.log"
}
run_candidate_correction candidate
timeout 30 "$ADB" -s "$ANDROID_SERIAL" shell am force-stop com.lorabge.memory
run_candidate_correction restart
