# IOSOE (IOSonEverything)

**v0.0.1 — experimental Android release.** Run a supported iOS guest inside an
Android app while Android stays installed.

The app includes **Install supported iOS**, guest selection, diagnostics and
**Supported now**. Apple OS images and SEP ROM are not included in the APK.
Preparation retrieves and checks its separately obtained inputs.

## Android download

Install [IOSOE-v0.0.1-android-arm64.apk](https://github.com/WitherBlitz/IOSonEverything-Android/releases/download/v0.0.1/IOSOE-v0.0.1-android-arm64.apk) from the [v0.0.1 release](https://github.com/WitherBlitz/IOSonEverything-Android/releases/tag/v0.0.1). Requirements:
**64-bit ARM, Android 14/API 34 or newer, at least 20 GB free**, and network
access for about **5.5 GB** of preparation downloads. CPU preparation can take
several hours. Tested phone: **Galaxy S26 Ultra SM-S948U, Adreno 840**; other
Android devices have not been qualified.

Select **iOS 14.0 beta 5**, choose **Install supported iOS**, then open it after
preparation finishes. Installation and booting the guest are separate steps.

## What works now

| Area | v0.0.1 status |
| --- | --- |
| iOS 14.0 beta 5, 18A5351d | Integrated installer; CPU-emulated iPhone 11. SpringBoard, touch, Home, repeated boot and saved appearance demonstrated on the test phone. |
| Android display | Direct Android Surface output for default CPU and managed Metal profiles. Metal display qualification used VNC disabled. A legacy child-engine GLES path remains. |
| Guest selection | Separate supported/research guests; stop the running guest before switching. |
| GLES acceleration | Experimental prepared iOS 14 guest on Adreno. No automatic GPU-guest installer. |
| Metal to Vulkan | Experimental prepared iOS 14 guest with linked authored demonstration apps. Actual frames reached Core Animation; 6,300 GPU publications and touch changes observed. General Metal app/game compatibility is unverified. |
| iOS 16.5 | Preparation/research profile. Automatic installation and general GUI/input/persistence support are not enabled. |
| CPU hardware virtualization | Not available on the tested unrooted S26 Ultra. Qualified iOS execution uses QEMU TCG emulation. |
| Performance | About 24.7 GPU publications/second in the recorded scene; **not measured phone-panel FPS** or a 60 FPS guarantee. Final compositor framebuffer copying remains. |

See [SUPPORT.md](SUPPORT.md) for the evidence and boundaries. The newer unverified
strided-download optimization is excluded from this release's native payloads.

## Source and build

Release assets include the Android APK, app and graphics source, support notes
and SHA-256 checksums. The source archive contains `graphics-source`; a smaller
graphics-only archive is also provided for backend work. Read
[BUILDING-IOSOE.md](BUILDING-IOSOE.md) for this release and the preserved
[earlier detailed audit](BUILDING-IOSONEVERYTHING.md) for provenance limits.

Unofficial derivative of Scion/Pyre and Inferno tooling. Original documentation,
copyright and license notices remain in [README-SCION.md](README-SCION.md),
[LICENSE](LICENSE) and [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## Repository source layout

The pinned Metal2Vulkan translator is a Git submodule at the recorded revision.
Use `git submodule update --init --recursive` for that backend source, or download
the complete flat source archive from the release. `SOURCE-CONTENTS.json` describes
that flat source archive. Pyre/Inferno source is vendored under `third_party/inferno`.

The earlier directory of related projects is preserved in
[the October 22 project index](docs/PROJECT-INDEX-2026-10-22.md).
