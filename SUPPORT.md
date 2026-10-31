# v0.0.1 support and evidence

Name: **IOSOE (IOSonEverything)**. Version name `0.0.1`, version code `4`, ARM64
only, minimum Android 14/API 34. Package identifier
`io.github.witherblitz.iosoneverything.gpulab` is retained for update continuity
and access to existing prepared lab guests.

## Supported installation

The integrated installer targets iPhone 11/iPhone12,1, iOS 14.0 beta 5,
build 18A5351d. CPU rendering/emulation is the default. The October 23–24 tests
demonstrated SpringBoard, touch, Home, repeat boot, saved appearance and a
five-minute running sample on SM-S948U. These are development-device results,
not broad Android-device qualification.

## Experimental graphics

Prepared GLES and Metal guests require separately verified receipts. They are
not created by the one-button installer. GPU support is qualified only on the
tested Adreno device and supported workloads. Metal uses Vulkan,
AHardwareBuffer snapshots and IOSurface/Core Animation integration.

The October 28 compositor run recorded 6,300 GPU publications, 3,360 resolves,
orange/green/blue touch changes, visible device-reset retirement and working
SpringBoard afterward. Eight thousand composed pixels matched expected colors.
Native router tests checked 9,116,789 pixels without a mismatch, alongside
ownership/lifetime regressions. GPU publications do not count unique physical
screen refreshes. About 24.7 publications/s is not panel FPS; final compositor
framebuffer copying remains.

Native payloads are retained from device-qualified v5 APK SHA-256
`2fab61aae409a684ab0a68c0b0bc1a83fc702c101802dc74a67378a2bc528a3f`.
`RELEASE-NATIVE-INPUTS.json` pins their hashes. The newer uninstalled strided
candidate is excluded. The release branding, support dialog and release build
are verified separately; compilation/unit tests do not establish fresh on-phone
v0.0.1 performance. The bundled graphics source and recorded build manifest
preserve the experimental backend's source scope.

## Not generally supported

- Automatic iOS 16.5 installation or general iOS 16 GUI/input/persistence.
- CPU hardware virtualization on the tested unrooted Samsung phone.
- General Metal app/game compatibility, GPU passthrough or 60 FPS.
- Replacing Android with iOS, cellular service, Apple hardware services or broad
  peripheral compatibility.

No Apple OS/restore images, SEP ROMs or SDKs are included. Guest disks stay
app-private; preparation downloads are separate from the APK.
