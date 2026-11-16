# Android release gates

`android-release.yml` validates Android changes on `main`, the historical Android
branch, and pull requests targeting `main`. Pull requests cannot publish. A release
requires `build`, `upgrade`, and `inapp-update` to succeed, as well as the existing
`android/PUBLISH_OK` review marker. An existing release is never deleted/replaced;
bump the version for the next release instead.

## Candidate update gate

`inapp_update_candidate.sh` consumes the exact `android-release-apk` build artifact.
It builds a **synthetic baseline from current source** with a lower version and no
native libraries, using the same signing configuration. On an Android 35 Google
APIs emulator (ARM translation is needed for the real arm64 target APK), the
instrumentation test runs production `lookupUpdate`, `downloadUpdate`, and
`UpdateInstaller.install`. Release metadata and APK transport use local fixtures,
so the test does not require a public prerelease or legacy mirror availability.

The host approves the system installer, then requires the exact target version,
APK SHA256 **and** size, the production submission marker, preserved synthetic
memory/chat/model/settings files, and a successful activity launch. Replacing the
app kills instrumentation; its exit status is deliberately not treated as success.
Failure, timeout, skipped jobs, or cancellation block publication. Diagnostics are
uploaded even when the gate fails.

This gate does **not** establish compatibility with every historical published
APK, test the Settings/check-update button, validate external GitHub/mirror
availability, or validate model inference. Keep the separate live-network check,
unit tests, and `upgrade` UI checks. The historical
`inapp_update_014_to_015.sh` remains available for manual investigation only; its
obsolete mirror-dependent path is no longer a release gate.

Fast local checks (no Android SDK):

```sh
python3 -m unittest discover -s android/scripts -p 'test_release_gate.py' -v
sh -n android/scripts/inapp_update_candidate.sh
actionlint -shellcheck= .github/workflows/android-release.yml
```

The complete candidate test requires an Android SDK, Java 17, KVM, Xvfb and the
release artifact directory. CI supplies those prerequisites.

## Native shader build regression

`android/qvac/build_android.sh` applies `shader-generation.patch` to the pinned
QVAC source and runs `test_shader_generation.py` against the actual patched host
generator. On Linux, shader variants run serially within each source while CMake
still builds sources in parallel. Compiler failures, missing/empty SPIR-V, and
launch failures stop generation rather than leaving incomplete link inputs.
The fake-compiler regression covers Adreno variants, warnings, silent failures,
large diagnostics, partial progress, and a missing compiler. It does not replace
the full NDK/Vulkan build or emulator update gate.
