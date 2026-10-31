# IOSOE (IOSonEverything) v0.0.1

First experimental Android release under the IOSOE name.

- Launcher and app header renamed to **IOSOE (IOSonEverything)**.
- Added **Supported now** with current support boundaries.
- Working iOS 14.0 beta 5 CPU installer, guest management and diagnostics.
- Qualified native GPU backend retained; GLES/Metal remain prepared-guest research features.
- Matching source, support notes, component notices and SHA-256 checksums included.

**Requirements:** ARM64 Android 14+, at least 20 GB free, and network access for
about 5.5 GB of preparation downloads. Tested on Galaxy S26 Ultra SM-S948U.

**Supported:** iOS 14 CPU boot, SpringBoard, touch, Home and retained guest state
have been demonstrated. Metal testing covers linked authored scenes on a
prepared iOS 14 guest; automatic GPU preparation and general Metal app/game
compatibility are unverified. iOS 16.5 remains preparation/research only.
CPU hardware virtualization is unavailable on the tested unrooted phone.
See `SUPPORT.md` for evidence and limitations.

The recorded scene reached about 24.7 GPU publications/second; that is not
phone-panel FPS. Final compositor copying remains and 60 FPS is not claimed.
The unverified strided-download candidate is excluded.

Apple images, SEP ROMs and SDKs are not bundled. Android stays installed.
Install the APK, select **iOS 14.0 beta 5**, then **Install supported iOS**.
