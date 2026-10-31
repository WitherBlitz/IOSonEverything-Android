# Third-party components and retained notices

Current release: IOSOE (IOSonEverything) v0.0.1. Publisher notices are retained
with source, under `third_party/notices/` and `third_party/gpu-notices/`, and in
the APK's `metal-licenses` assets. This is a factual source and notice inventory,
not a certification that every historical binary input has been established.

## v0.0.1 graphics additions

This release also includes Metal2Vulkan at
`a2c440b8bcdcf20d34aa1694b61ae22c2a7ea68b` (LGPL-3.0-or-later option),
the authored AGPL-3.0-or-later host bridge/guest adapters, gfxstream research
integration (Apache-2.0 source notice), and HackiOS integration references (MIT).
Pinned translator/bridge source is in `graphics-source`; matching guest adapter
source is preserved there from the qualified compositor checkpoint. Full
translator license texts are both in that tree and in the APK's metal-licenses.
Additional retained native dependency notices and the prior provenance inventory
are in `third_party/gpu-notices`. An APEX-wide notice and a research source pin
are not proof of an exact historical module-to-source mapping; the preserved
inventory and older audit state those limits. `RELEASE-NATIVE-INPUTS.json`
identifies the exact binaries shipped here.

The following October 24 inventory accompanied the unchanged
0.1.1-cpu-development APK and remains historical audit material for that CPU
development package; its earlier version/hash statements are not the
v0.0.1 APK identity. Current identity and checks are in `RELEASE-VERIFICATION.json`.
Prior notice hashes and download provenance are in `third_party/notices/INDEX.json`.

## App, engine and guest helpers

| Component | Recorded source | Retained notice |
| --- | --- | --- |
| Scion-derived Android app | dylanneve1/scion f76f9b943de32d55641fbe1f7f5215908845cdf9 plus local changes | root LICENSE, GNU AGPLv3; per-file notices |
| Pyre / Inferno / QEMU derivative | dylanneve1/pyre cefb274af5cea523dee6db97bd241421c2a76768 | third_party/inferno/LICENSE explains GPLv3 derivative, AGPLv3 additions and mixed per-file licenses; COPYING, COPYING.LIB and COPYING_AGPL-3.0 retained |
| Android context routines | Termux e02748430d74d980fc28587a2d3fdd3881aad57c, AOSP/BSD source | third_party/android-setjmp source headers; local adaptations in native/ |
| Inferno-iOS restore code and guest daemon | MakrSas/Inferno-iOS v0.3.1, release commit a8f688a3315ed7fd1effc83cd439fb6662501c85 | third_party/guest-tools-source/LICENSE.Inferno-iOS and Python vendor notice; original and adapted daemon source retained |
| InfernoFSPatcher | 3008aaaa0909824a71ee3040c9edc58703c250f5 | third_party/guest-tools-source/LICENSE.InfernoFSPatcher, AGPLv3; full retained helper source |
| QEMU en-us keymap | retained Scion native/keymaps/en-us | upstream GPL notice retained with source |

Engine provenance and original/adapted/packaged binary hashes are recorded in
`provenance.json`. Source-specific branding restrictions remain in
`third_party/inferno/ui/icons/CKBrandingNotice.md`; this derivative uses its own
application branding. Apple OS images and SEP ROMs are downloaded separately
and are absent from the APK/source/package. No Apple ownership or endorsement
is claimed.

## Native dependency recipes

The seven source archives in `native/build-android.sh` were downloaded and
verified against that script's pinned SHA-256 values during this audit.

| Component | Version | Retained texts under third_party/notices |
| --- | --- | --- |
| GMP | 6.3.0 | gmp: COPYING, COPYING.LESSERv3, AUTHORS; source specifies dual licensing |
| Nettle | 3.10.2 | nettle: COPYING.LESSERv3, AUTHORS; per-file terms remain in upstream archive |
| libtasn1 | 4.21.0 | libtasn1: COPYING, COPYING.LESSERv2, AUTHORS |
| LZ4 | 1.10.0 | lz4: library BSD notice and GPL program/test notices |
| LZFSE | 1.0 | lzfse/LICENSE, BSD notice |
| GLib | 2.88.4 | glib/LICENSES including LGPL-2.1-or-later and other source-component terms |
| Pixman | 0.46.4 | pixman/COPYING and AUTHORS, MIT-style component notices |
| GLib fallback libffi | 3.5.2 | glib-libffi/LICENSE and LICENSE-BUILDTOOLS |
| GLib fallback PCRE2 | 10.46 | glib-pcre2/LICENCE.md, BSD-3-Clause WITH PCRE2-exception |
| GLib fallback proxy-libintl | 0.5 | glib-proxy-libintl/COPYING, LGPL notice |
| libyuv | future pin 47ba8e2160b71a7cf95c0720cd8944ab771e533e | libyuv/LICENSE and PATENTS |
| mlib | future pin 93cddfb56c32976d8aeefd45ef9094167f64b285 | mlib-future/LICENSE, BSD-2-Clause |

GLib fallback URLs/hashes come from the pinned GLib archive's own wraps.
Notices for these build inputs do not establish their actual historical link
selection. The historical CI-resolved libyuv/mlib revisions remain unknown.
The two explicit future pins replace moving branch names; they must not be
represented as recovered historical inputs. See `SOURCE-AUDIT.json`.

## Python and Java runtime

The app uses Chaquopy 17.1.0 and Android Maven Python target **3.12.15-0**.
Host build/test Python 3.12.14 is separate. The publisher's pinned
[Python build recipe](https://github.com/chaquo/chaquopy/blob/17.1.0/target/python/build.sh)
names the following Python 3.12 dependencies. Runtime source-license versions
are matched to that recipe, not asserted to be a full independent binary rebuild.

| Component | Version / scope | Retained text |
| --- | --- | --- |
| Chaquopy | 17.1.0 | chaquopy/LICENSE.txt, MIT |
| CPython | 3.12.15 | cpython/LICENSE.txt and license.rst, PSF/history and incorporated component notices; expat-COPYING retained separately |
| OpenSSL | recipe 3.5.9-0 | openssl/LICENSE.txt, Apache-2.0 |
| SQLite | recipe 3.53.4-0 | publisher declares public domain at https://www.sqlite.org/copyright.html |
| bzip2 | recipe 1.0.8-3 | bzip2-1.0.8/LICENSE |
| libffi | recipe 3.4.4-3 | libffi-3.4.4/LICENSE, MIT-style |
| XZ / liblzma | recipe 5.4.6-1 | xz-5.4.6/COPYING and related texts; liblzma declared public domain in this version |
| pyasn1 | 0.6.1, actual APK | packaged/requirements-common.imy/pyasn1-0.6.1.dist-info/LICENSE.rst |
| pyasn1-modules | 0.4.2, actual APK | packaged/requirements-common.imy/pyasn1_modules-0.4.2.dist-info/licenses/LICENSE.txt |
| setuptools | 68.2.2, Chaquopy bootstrap | packaged/bootstrap.imy/setuptools-68.2.2.dist-info/LICENSE |
| pyelftools | 0.26, Chaquopy bootstrap | packaged/bootstrap.imy/java/_vendor/pyelftools-0.26.dist-info/LICENSE.txt |
| Kotlin stdlib | 2.2.10, resolved debugRuntimeClasspath | kotlin-2.2.10/LICENSE.txt, Apache-2.0 |
| JetBrains annotations | 13.0, resolved debugRuntimeClasspath | annotations/LICENSE.txt, publisher Apache-2.0 text observed on current branch; 13.0 POM retained in audit metadata |

The `packaged/` texts were extracted from the actual delivered APK's nested
Chaquopy archives. Android platform libraries (including Bionic, graphics and
Java cryptography) are provided by Android; they are not replaced by this app.
Build/test tools such as JDK, Gradle/AGP, Android SDK/NDK, Meson, JUnit,
cryptography and Unicorn are separate dependencies and are not all shipped
inside the product. The GPU diagnostic source/APK is a separate test artifact;
it is not part of the product's implemented guest rendering path.

Full emulator native source bit-for-bit reproduction, historical branch
resolution and exhaustive license compatibility review remain unestablished.
