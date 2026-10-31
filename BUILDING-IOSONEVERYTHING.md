# Building IOSonEverything

This development application runs a private iPhone 11 guest inside Android. The
selected preparation profile is iOS 14.0 beta 5, build 18A5351d, iPhone12,1/n104ap.
Installation and a verified SpringBoard boot are separate milestones. Consult the
delivered device report for the milestones actually demonstrated on the S26 Ultra.

## Android build

The recorded Windows build uses JDK 17, Python 3.12, Android platform 36, build tools
36.0.0, Gradle 9.7.1, Android Gradle Plugin 9.3.3, and Chaquopy 17.1.0. The minimum
Android version is 14/API 34. Only arm64-v8a is packaged.

1. Extract the complete source archive, including its native libraries and assets.
2. Create a Python 3.12 virtual environment named `python-env` beside the extracted
   repository directory. The Gradle configuration uses
   `../python-env/Scripts/python.exe`. For a Linux/macOS build, change that one
   buildPython path to the corresponding Python 3.12 executable.
3. Install Android platform 36, build tools 36.0.0 and NDK 28.2.13676358 (r28c)
   with Google's SDK tools. Retain that NDK for the recorded native stripping
   results; app builds reuse the supplied engines without compiling them.
4. Set JAVA_HOME to JDK 17. Create local.properties with sdk.dir pointing to that
   SDK. Escape the drive-letter colon in Windows property files, for example:
   `sdk.dir=C\:/Android/sdk`.
5. Run `gradlew.bat testDebugUnitTest lintDebug assembleDebug` from this directory.
6. Activate the host virtual environment and install its test dependencies:
   `python -m pip install pyasn1==0.6.1 pyasn1-modules==0.4.2 cryptography==46.0.3 unicorn==2.1.4`.
   Run Python tests with app/src/main/python on PYTHONPATH:
   `python -m unittest discover -s tests_python -v`, followed by
   `python -m unittest discover -s native/tests -v`.
   These host-test dependencies do not add cryptography or Unicorn to the APK.
   Android SEP decryption uses the platform AES implementation.

If Java reports a Windows UNIX-domain loopback error, point the JVM property
`jdk.net.unixdomain.tmpdir` to an existing short, writable directory for the build
process. This is a process-local Java setting; no Android security policy change
is needed.

The APK is written to app/build/outputs/apk/debug/app-debug.apk. Host Python
3.12.14 and Android Python Maven target 3.12.15-0 were used in this audit.
Gradle's debug
signing key is local build state and is not included in the source archive.
The archive rebuild passes tests/lint and reproduces the DEX and five product
native payloads. It is not a byte-identical APK: Python timestamp headers and
generated asset hashes vary, and the Chaquopy Java library's non-loadable ELF
section-name table differed. Its loadable segments and allocated sections match.
See the final audit evidence for the actual comparison, including Python code
object checks. A different local signing key also changes the APK signature.

## Native engine and original guest tools

The engine binaries originate from the hash-verified Scion CI artifact recorded
in provenance.json. Their two undefined coroutine imports are redirected to the
app-local context library by native/context_imports.py. The executable preloads
that library; the rebuilt JNI shim loads it before the shared engine. Only QEMU
calls these uniquely named functions. Android's libc and system policy are
unchanged. Matching emulator source is included under
third_party/inferno. Scion's native/build-android.sh describes an Android NDK
28.2.13676358 cross-build and its pinned dependencies. It produces the executable,
shared engine and JNI shim; the AVF framebuffer helper source is in
app/src/main/cpp. An APK build reuses the supplied verified libraries; install
the recorded NDK to keep native stripping consistent. Native-source rebuilding requires the script's Linux/macOS
host tools and dependency toolchain. The context library's original AOSP/BSD
source and attribution are in third_party/android-setjmp. Rebuild it with
`python native/build-coroutines.py NDK_PATH BUILD_DIRECTORY`, then copy the
resulting libios_coroutines.so into app/src/main/jniLibs/arm64-v8a. Rebuild
native/qemu_jni.c with the NDK's aarch64-linux-android34-clang as a shared library,
linking libandroid, liblog and libdl. For exact upstream engine binaries, invoke
native/context_imports.py with input, output, and the original --sha256 recorded
in provenance.json. Run native/tests with unittest before packaging. This
same-length import transformation leaves code, relocations and layout unchanged.
The same small library also builds native/writer-lease.c. Executable QEMU children
receive an explicit parent PID and app-private writer-lock path. Its constructor
checks parent identity, requests SIGTERM on parent-thread death and retains a
POSIX writer lock before QEMU can open guest files. The default in-process engine
uses its native service's Java DiskLease instead. Install/import/move/recovery and
deletion check both ownership files, including after a main-process restart.
Run `python3 -m unittest discover -s native/tests_linux -v` on Linux with a C
compiler to test actual independent processes, lock contention, dead-parent
rejection and parent-death termination. These four process tests were run in the
build VM; no emulated guest is required for them.
The native/build-android.sh engine build invokes these context steps automatically
for newly compiled engines. It does not reproduce the original CI binary exactly;
the pinned input/output hashes describe the supplied artifact adaptation.

The engine script does not build libscfb.so. Rebuild that retained display/camera
helper separately with `python native/build-scfb.py NDK_PATH BUILD_DIRECTORY`,
then copy BUILD_DIRECTORY/libscfb.so to app/src/main/jniLibs/arm64-v8a. Its API31
target matches the retained upstream ELF Android note; the app itself requires
API34. The helper recipe was compiled successfully with r28c, with AArch64/JNI
exports checked. A byte-identical rebuild of the historical helper is not claimed.
This AVF helper is not an implementation of iOS guest GPU acceleration.

Two inherited native wraps previously used moving main/master refs. Future
builds now pin libyuv to 47ba8e2160b71a7cf95c0720cd8944ab771e533e and mlib to
93cddfb56c32976d8aeefd45ef9094167f64b285. Their resolved revisions in the
historical CI artifact could not be recovered. SOURCE-AUDIT.json records this
limitation; these future pins do not prove historical source/binary identity.

provenance.json distinguishes the native files under jniLibs (`input_libraries`)
from the APK entries (`apk_libraries`). Android Gradle Plugin strips unneeded
symbols from libios_coroutines.so and libqemu_jni.so. NDK r28c's
`llvm-strip --strip-unneeded INPUT -o OUTPUT` reproduces each of those APK entries
byte-for-byte. The other three libraries retain their input hashes. The recorded
APK hash also matches the copy installed on the phone; stripping changes no
source or runtime configuration.

The Linux rebuild uses Meson 1.12.0, matching Scion's CI pin. Ubuntu 24.04's
distribution Meson is too old for the pinned GLib. Install Meson in a Python
virtual environment and put that environment on PATH. Host prerequisites include
a C/C++ compiler, make, m4, autoconf, automake, libtool, bison, flex, pkg-config,
Ninja, CMake, Git, curl, patch, Perl and Python 3. Invoke the native build with
ANDROID_NDK_HOME pointing to NDK r28c and API=34. The source archive preserves
POSIX executable modes and LF line endings for scripts; when cloning on Windows,
use a separate LF checkout for the Linux build.

Original guest helper source, upstream build recipe and licenses are retained in
third_party/guest-tools-source. The supplied helper binaries were extracted from
MakrSas/Inferno-iOS v0.3.1 after checking the published IPA SHA-256. Building those
ARM64e Mach-O helpers requires an Apple iPhoneOS SDK and ad-hoc signing, as the
retained build recipe specifies. They execute inside the emulated guest.
The upstream script also builds an iOS frontend whose other files are not part
of this Android source package. To build only the retained original helpers on
macOS, run the following from the extracted Android repository:

```bash
SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
mkdir -p build-guest-tools
xcrun --sdk iphoneos clang -arch arm64e -isysroot "$SDK" -mios-version-min=14.0 -O2 \
  -o build-guest-tools/inferno_patcher third_party/guest-tools-source/patcher-daemon-upstream.c
xcrun --sdk iphoneos clang++ -arch arm64e -isysroot "$SDK" -mios-version-min=14.0 -O2 \
  -std=c++17 -o build-guest-tools/inferno_fs_patcher third_party/guest-tools-source/InfernoFSPatcher/src/main.cpp
codesign -f -s - build-guest-tools/inferno_patcher
codesign -f -s - build-guest-tools/inferno_fs_patcher
```

These source-build commands require the Apple SDK and were not executed on this
Windows host. They are not a claim of identical Mach-O outputs. The hash-checked
adaptation below uses the supplied original binary and was tested separately.

The guest daemon is adapted by native/adapt_guest_daemon.py from the retained,
hash-pinned original-inferno_patcher. For this single-cache iOS 14 profile it
excludes dotted sidecars, including .InfernoOriginalBytes, and logs child exec
paths. native/guest-exec-trace.S documents the Darwin ARM64 calling convention
used by the small trace trampoline. The script preserves file layout and checks
and regenerates only the existing ad-hoc CodeDirectory page hashes. Its input
and output hashes are recorded in provenance.json. native/guest-sep-prepare.S
adds the cold-boot sequence for mounting the existing xART volume, initializing
its gigalocker, loading the prepared SEP firmware with --wait, and checking a
ping. It closes the gigalocker and unmounts xART after Data is unmounted. The
routine checks each command and does not invoke an erase operation. This restore
ramdisk has no umount program; the routine uses the guest's SYS_unmount (159)
with flags zero, checks and logs the result, and preserves the normal kernel
permission checks. Reproduce
its small binary with `python native/build-guest-sep.py PATH_TO_NDK_LLVM_BIN`,
then run `python native/adapt_guest_daemon.py third_party/guest-tools-source/original-inferno_patcher app/src/main/assets/guest-tools/inferno_patcher`.
These same-layout adaptations require LLVM but no Apple SDK. The upstream daemon source
and the corresponding edited source are both retained with the guest tools.

`python -m unittest discover -s native/tests -v` verifies binary layout/hashes and
control flow. Install test-only `unicorn==2.1.4` to execute the AArch64 routines
with deterministic syscall/import responses, including failed preparation and
cleanup. Unicorn is not included in or used by the Android app.

No Apple operating-system image or SEP ROM is bundled in the APK or source archive.
The app downloads the exact IPSW from Apple's CDN and the documented SEP ROM from
the research collection, then verifies the pinned SHA-256 values. Its small
research ticket template contains only the public ApImg4Ticket from the upstream
setup guide; unrelated template metadata was removed. Sources and hashes are in
provenance.json and iosvm/installer.py.

## Installer and lifecycle

The installer uses a foreground service, a private UNIX USB bridge, streaming ASR,
and sparse private guest disks. It checks the production erase identity, prepares
the SEP firmware, restores a staging disk, and boots a separate recovery ramdisk
to apply CPU-renderer filesystem patches. A patch-only boot uses exit_recovery
plus rd=md0 without the -restore/NAND-reformat boot settings, and its ramdisk
disables the idle restore daemon. The patcher handles the saved SEP state before
mounting the encrypted Data volume. A durable successful-restore checkpoint
survives patch failure or cancellation and can resume patching offline without
firmware downloads. It promotes the result only after the
restore and patch checks succeed. Receipts and retained directories reconcile a
killed promotion. Failed staging directories are reclaimed; partial downloads are
retained for retry. Diagnostics exposes bounded installer console logs and includes
them in a user-requested debug export.

Normal guest execution uses the separate native VM service process and direct
Android Surface output. It does not start Python. The selected defaults are 3 GB
guest RAM, four emulator vCPUs including SEP, a 256 MB translation buffer, and no
Pixel-specific CPU affinity. This profile uses CPU emulation and CPU guest
rendering. Host Surface presentation is not guest GPU acceleration.
The VM retains disk ownership until confirmed process death, including console
I/O failure. Its service observes owner Binder death and requests a clean quit,
with a bounded force-stop fallback. Normal console logs retain at most two 1 MiB
files and 16 KiB per line. Log-write failures disable disk logging while continuing
to drain output. Recovery verifies immutable boot-file SHA-256 digests and also
recognizes a valid profile moved to its recorded shared-storage directory.

## Device instrumentation

`gradlew.bat assembleDebugAndroidTest` builds the separate test APK. Its DeviceChecks
instrumentation validates the platform AES implementation, private UNIX sockets,
and native engine execution. Passing those checks does not demonstrate an iOS boot.

After installing both APKs on the authorized device:

```powershell
adb -s DEVICE shell am instrument -w io.github.witherblitz.iosoneverything.test/io.github.dylanneve1.iosonpixel.DeviceChecks
```

The additional instrumentation argument `-e start_install true` invokes the real
foreground installer and stays attached until it finishes or is cancelled. The
product service remains unexported. No root, bootloader unlock, flashing, or global
hidden-API/security-policy changes are part of this build or its tests.

The test-only `-e hardware_virtualization_probe true` branch queries AVF capability
bits, current app grants and direct Gunyah access, then attempts Scion's normal
non-protected config construction. It starts no guest and does not initialize
Python. Stop any running guest before instrumentation. Its report is written to
files/hardware-virtualization-report.json; the disposable config file is removed.
See the delivered Hardware-Virtualization-Report.md for the separately executed
protected Microdroid and custom raw-guest controls and their actual rejection logs.

Prompt 3 adds the test-only `-e installer_audit true -e audit_url URL -e audit_hash SHA256`
mode. It uses disposable HTTP fixture inputs and production acquisition code,
then verifies existing-guest reuse under DiskLease without launching a restore.
The host fixture/capture scripts and exact results are in Installer-Test-Evidence.zip.
Supported-iOS-Profile.json records the qualified guest's full input and component
hashes, storage layout and preparation sequence. Short Content-Length transfers
retain their partial file; preparation recovery requires all five immutable hashes.

## Attribution

Scion/Pyre and the Inferno filesystem patcher use AGPLv3; the restore reference and
ported restore/preparation code use GPLv3-compatible terms. Preserve the included
copyright notices and license texts. This derivative is unofficial and is not
endorsed by Apple, Samsung, ChefKiss, or the upstream authors.
THIRD-PARTY-NOTICES.md inventories native, Python and runtime dependencies, with
retained publisher texts under third_party/notices. Preserve that directory and
the original component licenses when sharing the development package.
