# Build IOSOE (IOSonEverything) v0.0.1

Use JDK 17, Python 3.12, Android SDK 36/build tools 36.0.0, the supplied Gradle
wrapper and pinned Android Gradle/Chaquopy plugins. Only ARM64 is packaged.
The source bundle includes exact native payloads pinned in
`RELEASE-NATIVE-INPUTS.json`; app compilation reuses them.

1. Set `JAVA_HOME` to JDK 17 and create `local.properties` with `sdk.dir`.
2. Create `python-env` beside this project, or adjust `buildPython` in
   `app/build.gradle.kts` to an installed Python 3.12.
3. Run `gradlew.bat testDebugUnitTest lintRelease assembleRelease` on Windows.
4. Output: `app/build/outputs/apk/release/app-release.apk`.
5. With `app/src/main/python` on `PYTHONPATH`, run
   `python -m unittest discover -s tests_python -v`.

Release stripping is disabled to preserve qualified native bytes. The existing
local signing configuration is retained for update continuity. Signing keys and
local SDK paths are excluded; another key produces a different certificate/APK.

The earlier build/audit guide and third-party notices describe engine provenance,
dependency pins and historical reproduction limits. Source includes Android and
engine integration; `graphics-source` supplies the experimental linked guest
adapter, host bridge, pinned translator and tests. A graphics-only archive is
also provided. OS images, ROMs, SDKs and credentials are excluded.
