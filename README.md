# IOSonEverything (Android)

A large directory of projects exploring iOS, iPadOS, and Apple's XNU kernel on
Android hardware. Inspired by [ios-sweet](https://github.com/dipa-studio/ios-sweet).

Browse the [ios-sweet forks](https://github.com/dipa-studio/ios-sweet/forks)
for more community development trees and device-porting experiments.

**Research snapshot: October 22, 2026.** This is a project index, not a promise
that every listed phone can run iOS. It includes experimental ports, early
device bring-up, build tools, and explicitly labelled research targets.

## Contents

- [How to read the list](#how-to-read-the-list)
- [Xiaomi, Redmi, and POCO phones](#xiaomi-redmi-and-poco-phones)
- [OnePlus phones](#oneplus-phones)
- [Samsung phones](#samsung-phones)
- [Google Pixel phones](#google-pixel-phones)
- [Other phones](#other-phones)
- [Related Android tablets](#related-android-tablets)
- [Emulation and virtualization](#emulation-and-virtualization)
- [Porting frameworks, firmware, and tools](#porting-frameworks-firmware-and-tools)
- [Contributing](#contributing)

## How to read the list

| Label | Meaning |
| --- | --- |
| Reported GUI | The device-specific README reports an iOS or iPadOS graphical interface. This index has not reproduced it. |
| Bring-up | Device-specific adaptation or investigation exists; read the project for the exact boot milestone. |
| Build only | Kernel compilation or packaging work; this does not establish a bootable phone OS. |
| Declared target | The repository name or description names this device, but its README still describes an upstream device. Device-specific progress is unverified. |
| Research | Supporting experiments, frameworks, or emulation rather than a native phone port. |

Sources are the linked projects' own READMEs and repository descriptions.
Repository availability and documentation were checked for this snapshot;
hardware behavior, releases, and flashing instructions were not tested.
An upstream README's boot claim is **not** evidence that a fork's new target boots.
The list is growing and is not exhaustive.

Some projects overwrite Android's user data and disable platform security.
Read the exact device and model requirements, limitations, and backup instructions
in the linked project before attempting installation. Apple firmware is not
included here.

## Xiaomi, Redmi, and POCO phones

### Redmi

| Device | Codename | Project | Status / scope |
| --- | --- | --- | --- |
| Redmi Note 10 Pro | `sweet` | [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet) | Reported GUI; original project supplied as the example. |
| Redmi Note 10 Pro | `sweet` | [DC28088/hackios-sweet](https://github.com/DC28088/hackios-sweet) | Bring-up; README explicitly says phone boot and GPU rendering are not established. |
| Redmi Note 10 Pro | `sweet` | [CrackerCat/UniXNU-sweet](https://github.com/CrackerCat/UniXNU-sweet) | Bring-up; no bootable sweet image reported. |
| Redmi Note 12 4G | `topaz` / `tapas` | [MakrSas/ios-topaz](https://github.com/MakrSas/ios-topaz) | Reported GUI; device-specific iOS 16 port. |
| Redmi Note 12 4G | `topaz` | [turgayasuk-sketch/ios-topaz](https://github.com/turgayasuk-sketch/ios-topaz) | Reported GUI; separate topaz development tree. |
| Redmi Note 13 4G | `sapphire` | [Angelpro09xd/ios-sapphire](https://github.com/Angelpro09xd/ios-sapphire) | Bring-up; device-specific derivative of ios-topaz. |
| Redmi Note 9 Pro family | `miatoll` | [olaffx/ios-miatoll](https://github.com/olaffx/ios-miatoll) | Declared target; README retains sweet instructions. |
| Redmi Note 11 | `spes` | [dinosaurrus/ios-spes-touch-fix](https://github.com/dinosaurrus/ios-spes-touch-fix) | Bring-up; see the README's Spes section and `spes-port` branch. |
| Redmi Note 12 Pro 5G | `ruby` | [lky005/ruby-ios-bringup](https://github.com/lky005/ruby-ios-bringup) | Bring-up; MediaTek MT6877, with device touch experiments documented. |
| Redmi Note 14 Pro+ 5G | `amethyst` | [andr0d1v/UniXNU-amethyst](https://github.com/andr0d1v/UniXNU-amethyst) | Bring-up; README says waiting for UEFI. |
| Redmi Note 5A | `ugglite` | [TheArchitectEngineer/ios-ugglite](https://github.com/TheArchitectEngineer/ios-ugglite) | Bring-up; ugglite shim and probe work, alongside inherited sweet documentation. |
| Redmi 5 Plus | `vince` | [arabaci0711-ux/ios-vince](https://github.com/arabaci0711-ux/ios-vince) | Bring-up; XNU kernel and device boot shim. |
| Redmi 9A | `dandelion` | [licg89/UniXNU-dandelion](https://github.com/licg89/UniXNU-dandelion) | Bring-up; MediaTek device repository targeting iOS 16. |
| Redmi 9C | `angelica` | [kakaed3000/nexredmi-xnul](https://github.com/kakaed3000/nexredmi-xnul) | Bring-up; device-specific xnuL loader and userland work. |
| Redmi K20 Pro / Mi 9T Pro | `raphael` | [Gsjsjzhznsz/ios-raphael](https://github.com/Gsjsjzhznsz/ios-raphael) | Bring-up; device-specific hardware and touch progress documented. |
| Redmi K20 Pro | `raphael` | [HeliumStudio-Dev/ios-raphael](https://github.com/HeliumStudio-Dev/ios-raphael) | Bring-up; raphael kernel and screen logs; distinguish these from inherited sweet GUI claims. |
| Redmi K20 Pro / Mi 9T Pro | `raphael` | [penYo22/UniXNU-raphael](https://github.com/penYo22/UniXNU-raphael) | Bring-up; README says the kernel build is not yet working. |
| Redmi K30 5G | `picasso` | [YinCQL/UniXNU-picasso](https://github.com/YinCQL/UniXNU-picasso) | Bring-up; firmware menu reached, XNU does not boot yet. |
| Redmi K40 Pro | `haydn` | [xiaomi-haydn-dev/UniXNU-haydn4](https://github.com/xiaomi-haydn-dev/UniXNU-haydn4) | Declared target; README still describes OnePlus 7 Pro. |
| Redmi K60 | `mondrian` | [XTOM0706/ios-sweet-k60](https://github.com/XTOM0706/ios-sweet-k60) | Declared target; README retains sweet instructions. |
| Redmi K70 | `vermeer` | [xyyyds0106/ios-vermeer-lab](https://github.com/xyyyds0106/ios-vermeer-lab) | Bring-up; device-specific lab with partial GUI and root-image experiments. |
| Redmi K70 | `vermeer` | [yyx2025/UniXNU-vermeer](https://github.com/yyx2025/UniXNU-vermeer) | Bring-up; UniXNU board adaptation with unverified components marked. |
| Redmi K70 | `vermeer` | [mansar1337/UniXNU-vermeer](https://github.com/mansar1337/UniXNU-vermeer) | Build only; README explicitly distinguishes the kernel build from a phone boot image. |

### POCO

| Device | Codename | Project | Status / scope |
| --- | --- | --- | --- |
| POCO X5 Pro 5G | `redwood` | [oosexgang/hackios-xnu-kernel](https://github.com/oosexgang/hackios-xnu-kernel) | Bring-up; primary HackiOS kernel, loader, and device-porting tree. |
| POCO X3 Pro | `vayu` | [nomorecoolnicknames/hackios-xnu-kernel-vayu](https://github.com/nomorecoolnicknames/hackios-xnu-kernel-vayu) | Declared target; kernel fork retains upstream device documentation. |
| POCO X3 Pro | `vayu` | [nomorecoolnicknames/hackios-xnu-userland-vayu](https://github.com/nomorecoolnicknames/hackios-xnu-userland-vayu) | Declared target; companion userland tree retains upstream documentation. |
| POCO F3 | `alioth` | [misaghbab/ios-sweet](https://github.com/misaghbab/ios-sweet) | Declared target; repository description names POCO F3, README describes sweet. |
| POCO F5 | `marble` | [jebbranch/ios-port-marble](https://github.com/jebbranch/ios-port-marble) | Build only; XNU build workflow for marble. |
| POCO F6 / Redmi Turbo 3 | `peridot` | [Olegu621/xlamiOS-xnu-kernel](https://github.com/Olegu621/xlamiOS-xnu-kernel) | Bring-up; device-specific XNU and iOS userland work. |
| POCO F6 / Redmi Turbo 3 | `peridot` | [hoshikv/UniXNU-peridot-standalone](https://github.com/hoshikv/UniXNU-peridot-standalone) | Bring-up; standalone UniXNU device tree, marked WIP. |
| POCO F7 | `onyx` | [mkygraphics-dev/ONYXIOS_POCO_F7](https://github.com/mkygraphics-dev/ONYXIOS_POCO_F7) | Bring-up; description explicitly says it has never run on the phone. |

### Xiaomi and Mi

| Device | Codename | Project | Status / scope |
| --- | --- | --- | --- |
| Xiaomi Mi 6 | `sagit` | [nftuoa/ios-sweet-sagit](https://github.com/nftuoa/ios-sweet-sagit) | Declared target; README retains sweet instructions. |
| Xiaomi Mi MIX 2 | `chiron` | [sbccc1888/ios-sweet](https://github.com/sbccc1888/ios-sweet) | Declared target; description names MIX 2, README describes sweet. |
| Xiaomi Mi MIX 2S | `polaris` | [JaneAwA/iOS16_on_mix2s](https://github.com/JaneAwA/iOS16_on_mix2s) | Bring-up; UEFI and ARM64 boot-shim research. |
| Xiaomi Mi 9 | `cepheus` | [lianghhj/ios-cepheus](https://github.com/lianghhj/ios-cepheus) | Declared target; README retains topaz instructions. |
| Xiaomi Mi 9 SE | `grus` | [nmtm82g6zw-commits/ios-sweet-grus](https://github.com/nmtm82g6zw-commits/ios-sweet-grus) | Bring-up; device-specific `PORTING-GRUS.md` and build options. |
| Xiaomi Mi 10T / Mi 10T Pro | `apollo` | [IXackerr/ios-apollo](https://github.com/IXackerr/ios-apollo) | Bring-up; apollo-specific port notes; upstream sweet boot claims do not establish apollo support. |
| Xiaomi Mi 11 Lite 5G | `renoir` | [daimile2/ios-renoir](https://github.com/daimile2/ios-renoir) | Bring-up; independent device adaptation retaining upstream history. |
| Xiaomi 13 | `fuxi` | [bangprovn/ios-fuxi](https://github.com/bangprovn/ios-fuxi) | Reported GUI; device-specific README reports home screen, touch, and buttons. |
| Xiaomi 13 | `fuxi` | [hanzi123-bilp/unixnu-fuxi](https://github.com/hanzi123-bilp/unixnu-fuxi) | Declared target; README still describes sheng. |
| Xiaomi 13 Pro | `nuwa` | [wh1stl3/UniXNU-nuwa](https://github.com/wh1stl3/UniXNU-nuwa) | Bring-up; see device-specific status and source-build notes. |
| Xiaomi 13 Lite | `ziyi` | [TopPlayer254/ios-sweet](https://github.com/TopPlayer254/ios-sweet) | Bring-up; retargeted README claims GUI progress but closely follows the upstream text. |
| Xiaomi 15 | `dada` | [7Night-kqx/UniXNU-dada](https://github.com/7Night-kqx/UniXNU-dada) | Bring-up; README explicitly says nothing has booted on hardware yet. |

## OnePlus phones

| Device | Codename | Project | Status / scope |
| --- | --- | --- | --- |
| OnePlus 5 | `cheeseburger` | [lss717/UniXNU-cheeseburger](https://github.com/lss717/UniXNU-cheeseburger) | Bring-up; UniXNU loader, DarwinBoot, and 4 KiB XNU route. |
| OnePlus 6T | `fajita` | [edi194/ios-fajita](https://github.com/edi194/ios-fajita) | Bring-up; README explicitly distinguishes fajita work from inherited sweet notes. |
| OnePlus 6T | `fajita` | [johnpanos/UniXNU-fajita](https://github.com/johnpanos/UniXNU-fajita) | Bring-up; README reports XNU reaching root mount, not a working iOS GUI. |
| OnePlus 7 Pro | `guacamole` | [wochgn/UniXNU-guacamole](https://github.com/wochgn/UniXNU-guacamole) | Bring-up; UEFI, payload, and DarwinBoot integration. |
| OnePlus 8 Pro | `instantnoodlep` | [zhangp996/UniXNU-instantnoodlep](https://github.com/zhangp996/UniXNU-instantnoodlep) | Bring-up; board and firmware configuration; device drivers remain work in progress. |
| OnePlus 8T | `kebab` | [GFander/UniXNU-kebab](https://github.com/GFander/UniXNU-kebab) | Build only; first milestone is a kernel and minimal Apple-format device tree. |
| OnePlus 10 Pro 5G | `negroni` | [pawlickerr/UniXNU-negroni](https://github.com/pawlickerr/UniXNU-negroni) | Bring-up; device-specific UniXNU integration. |
| OnePlus Ace 5 | `giulia` | [tycykp/UniXNU-OnePlus-Ace5](https://github.com/tycykp/UniXNU-OnePlus-Ace5) | Bring-up; experimental UEFI and Darwin/XNU port. |
| OnePlus 13 | `dodge` | [palazik/ios-dodge](https://github.com/palazik/ios-dodge) | Bring-up; early XNU/MMU milestone; README says it does not boot iOS. |
| OnePlus 15R / Ace 6T | `macan` / `macanc` | [hxfuxyy/ios-macan](https://github.com/hxfuxyy/ios-macan) | Bring-up; device-specific RAM-boot XNU and iOS 16.5 project. |

## Samsung phones

| Device | Codename / model | Project | Status / scope |
| --- | --- | --- | --- |
| Galaxy S8, Exynos | `dreamlte`, SM-G950F | [Floppikrob/ios-galaxy-s8](https://github.com/Floppikrob/ios-galaxy-s8) | Reported GUI; Exynos-specific iOS 16.7 project. |
| Galaxy A40 | SM-A405FN | [tlfares/iOS16-on-A40](https://github.com/tlfares/iOS16-on-A40) | Reported GUI; README reports SpringBoard, touch, and buttons. |
| Galaxy A5 (2016) target | `a5xelte` | [orhunnx/ios-a5xelte](https://github.com/orhunnx/ios-a5xelte) | Declared target; inferred from repository codename, README describes sweet. |
| Galaxy A02s | Model not specified in description | [jode401/ios-sweet](https://github.com/jode401/ios-sweet) | Declared target; repository description names A02s, README describes sweet. |
| Galaxy S22+, Exynos | Model not specified in description | [ahenyao/ios-sweet](https://github.com/ahenyao/ios-sweet) | Declared target; repository description names S22+, README describes sweet. |
| Galaxy S23 Ultra | `dm3q`, SM-S918B | [tomaswarner/ios-dm3q](https://github.com/tomaswarner/ios-dm3q) | Declared target; README retains sweet instructions. |
| Galaxy Z Fold3 | `q2q` | [agcarbajo/UniXNU-q2q](https://github.com/agcarbajo/UniXNU-q2q) | Build only; source compilation harness, explicitly not a usable OS. |

## Google Pixel phones

| Device | Codename | Project | Status / scope |
| --- | --- | --- | --- |
| Google Pixel (first generation) | `sailfish` | [joranv1/ios-sailfish](https://github.com/joranv1/ios-sailfish) | Bring-up; device-specific README reports iOS 16.7.16 and GPU work. |
| Google Pixel 9a | `tegu` | [LeR33/ios-tegu](https://github.com/LeR33/ios-tegu) | Bring-up; experimental Tensor G4 target. |

Pixel 10 emulation is listed in [Emulation and virtualization](#emulation-and-virtualization).

## Other phones

| Device | Codename / model | Project | Status / scope |
| --- | --- | --- | --- |
| Nothing Phone (3a) | `asteroids` | [rootstockos/UniXNU-asteroids](https://github.com/rootstockos/UniXNU-asteroids) | Bring-up; README says hardware support is incomplete and images are not ready to flash. |
| Nothing Phone 3a | SM7635 target | [Sha1zen/iOS-On-Nothing](https://github.com/Sha1zen/iOS-On-Nothing) | Research; older Darwin/XNU base, QEMU first, native hardware later. |
| Sony Xperia 1 II | `pdx203` | [chardidathing/UniXNU-pdx203](https://github.com/chardidathing/UniXNU-pdx203) | Bring-up; device board, UFS, device-tree, and boot notes. |
| Motorola Moto G9 Play | `guamp` | [itsChris122/UniXNU-guamp](https://github.com/itsChris122/UniXNU-guamp) | Bring-up; SM6115 device repository. |
| Microsoft Surface Duo 2 | `zeta` | [none24smu/UniXNU-zeta](https://github.com/none24smu/UniXNU-zeta) | Bring-up; device repository with iOS 26 userland as its stated target. |
| LeEco Le Pro 3 | `zl1`, LEX727 | [lvyufeng/ios-le-pro3](https://github.com/lvyufeng/ios-le-pro3) | Bring-up; README explicitly says nothing boots iOS yet. |
| LG V60 ThinQ 5G | `timelm` | [ch1tmdgus/ios-v60](https://github.com/ch1tmdgus/ios-v60) | Reported GUI; device-specific README reports GUI boot and touch progress. |
| OPPO Find X7 Ultra, satellite edition | PHY120 | [peiyuesheng666/UniXNU-PHY120](https://github.com/peiyuesheng666/UniXNU-PHY120) | Bring-up; UniXNU device adaptation. |
| RedMagic 8 Pro+ | NX729J | [2713385115/UniXNU-nx729j](https://github.com/2713385115/UniXNU-nx729j) | Declared target; README still describes sheng. |
| Infinix Note 12 2023 | X676C, MT6789 | [squeeeezy/HelioDarwin](https://github.com/squeeeezy/HelioDarwin) | Bring-up; Darwin/XNU and graphics research, not a verified complete iOS port. |

## Related Android tablets

These are tablet projects, included separately for iPadOS and shared XNU porting work.

| Device | Codename / model | Project | Status / scope |
| --- | --- | --- | --- |
| Xiaomi Pad 5 | `nabu` | [glebenekt/ios-nabu](https://github.com/glebenekt/ios-nabu) | Bring-up; iPadOS 16.6.1 target, hardware XNU and UFS progress documented. |
| Xiaomi Pad 5 | `nabu` | [Lux12138/unixnu-nabu](https://github.com/Lux12138/unixnu-nabu) | Bring-up; README reports kernel entry, with userspace still a later milestone. |
| Xiaomi Pad 5 Pro 5G | `enuma` | [wh1stl3/UniXNU-enuma](https://github.com/wh1stl3/UniXNU-enuma) | Bring-up; iPadOS 17.7.11 target. |
| Xiaomi Pad 6 | `pipa` | [xVanTuring/UniXNU-pipa](https://github.com/xVanTuring/UniXNU-pipa) | Bring-up; author explicitly says the project has not run on the tablet. |
| Xiaomi Pad 6 Pro | `liuqin` | [1696108518/UniXNU-liuqin](https://github.com/1696108518/UniXNU-liuqin) | Bring-up; board-data skeleton, README says not buildable or flashable yet. |
| Xiaomi Pad 6S Pro | `sheng` | [UniXNU/UniXNU-sheng](https://github.com/UniXNU/UniXNU-sheng) | Reported GUI; project reports native Adreno/Metal system-UI rendering. |
| Xiaomi Pad 7 / POCO Pad X1 | `uke` | [Allenwdk/UniXNU-uke](https://github.com/Allenwdk/UniXNU-uke) | Bring-up; firmware, loader, and kernel-entry milestones documented. |
| Xiaomi Pad 8 Pro | `piano` | [code002-2/UniXNU-piano](https://github.com/code002-2/UniXNU-piano) | Bring-up; device repository and board configuration. |
| OnePlus Pad Pro | `caihong`, OPD2404 | [Axiang-dev/UniXNU-caihong](https://github.com/Axiang-dev/UniXNU-caihong) | Bring-up; skeleton and board checks; firmware integration pending. |
| OnePlus Pad 2 Pro | `erhai`, OPD2413 | [wally001012-cyber/UniXNU-erhai](https://github.com/wally001012-cyber/UniXNU-erhai) | Bring-up; device-specific kernel-entry target. |
| Lenovo Xiaoxin Pad 2022 | TB128FU | [xVanTuring/UniXNU-tb128fu](https://github.com/xVanTuring/UniXNU-tb128fu) | Reported GUI; README reports iPadOS home screen and touch, CPU rendering. |
| Samsung Galaxy Tab S9 Ultra, Wi-Fi | `gts9uwifi`, SM-X910 | [zc47796741-pixel/UniXNU-gts9uwifi](https://github.com/zc47796741-pixel/UniXNU-gts9uwifi) | Declared target; README still describes sheng. |
| Samsung Galaxy Tab A7 10.4 (2020) | `gta4l`, SM-T500 / SM-T505 | [NoNameBuilder/UniXNU-gta4l](https://github.com/NoNameBuilder/UniXNU-gta4l) | Bring-up; board, firmware, and XNU integration. |
| Benesse TAB-A04-BR3 | `a04br3`, MT8167 | [mouseos/UniXNU-a04br3](https://github.com/mouseos/UniXNU-a04br3) | Bring-up; README says no UniXNU hardware run is documented. |
| Brave Ark | KU1381 | [tattwamashi/UniXNU-braveark](https://github.com/tattwamashi/UniXNU-braveark) | Bring-up; SM8635 device repository. |

## Emulation and virtualization

These projects run or investigate Apple software through emulation or virtual
machines. They do not establish native boot support for an Android device.

| Project | Scope |
| --- | --- |
| [dylanneve1/scion](https://github.com/dylanneve1/scion) | Pixel 10 research using a QEMU/Pyre backend and Android virtualization; README reports an emulated iPhone 11 running iOS 14. |
| [Droid-VM/UniXNU-droidvm](https://github.com/Droid-VM/UniXNU-droidvm) | UniXNU guest for crosvm on the Gunyah hypervisor of a Snapdragon phone. |
| [BigfootACA/unixnu-droidvm-ci](https://github.com/BigfootACA/unixnu-droidvm-ci) | CI and kernel builds for QEMU/KVM and DroidVM targets. |
| [xVanTuring/UniXNU-qemu](https://github.com/xVanTuring/UniXNU-qemu) | QEMU ARM64 virtual-machine target; README reports an iPadOS 17 GUI. |
| [20kiwy/ios-sweet-qemu](https://github.com/20kiwy/ios-sweet-qemu) | QEMU development derivative of ios-sweet; inherited phone documentation is not evidence of native support. |
| [20kiwy/ios-sweet-rust](https://github.com/20kiwy/ios-sweet-rust) | Rust implementation of the iPhone X / ios-sweet QEMU boot pipeline. |
| [b1ackmarket/qemu-n90ap](https://github.com/b1ackmarket/qemu-n90ap) | iPhone 4 / iOS 4.3.1 XNU emulation and boot research. |
| [touchHLE/touchHLE](https://github.com/touchHLE/touchHLE) | High-level emulator for selected early iOS apps, including an Android host; not a full iOS installation. |

## Porting frameworks, firmware, and tools

Supporting projects are useful to developers, but are not additional working
phone ports.

| Project | Purpose |
| --- | --- |
| [UniXNU/UniXNU](https://github.com/UniXNU/UniXNU) | UEFI-based framework and build driver for non-Apple ARM64 hardware. |
| [oosexgang/hackios-xnu-userland](https://github.com/oosexgang/hackios-xnu-userland) | Companion userland tooling for the HackiOS kernel linked in the POCO table. |
| [UniXNU/DarwinBoot](https://github.com/UniXNU/DarwinBoot) | UEFI loader for XNU, payloads, device trees, and trust caches. |
| [UniXNU/ArmCpu](https://github.com/UniXNU/ArmCpu) | ARM64 CPU, interrupt-controller, and timer driver. |
| [UniXNU/NativeAdreno](https://github.com/UniXNU/NativeAdreno) | Native XNU Adreno driver; current README focuses on sheng / Adreno 740. |
| [UniXNU/uefi-sheng](https://github.com/UniXNU/uefi-sheng) | UEFI firmware tree associated with the Xiaomi Pad 6S Pro project. |
| [hanzi123-bilp/uefi-fuxi](https://github.com/hanzi123-bilp/uefi-fuxi) | Xiaomi 13 firmware target; inherited generic UEFI README, device support unverified here. |
| [wh1stl3/uefi-nuwa](https://github.com/wh1stl3/uefi-nuwa) | Xiaomi 13 Pro firmware tree; repository description marks hardware bring-up unverified. |
| [sbccc1888/sweet-uefi](https://github.com/sbccc1888/sweet-uefi) | Graphical UEFI boot-menu project initially targeting Xiaomi Mi MIX 2. |
| [CrackerCat/ios-extra](https://github.com/CrackerCat/ios-extra) | Driver experiments and bring-up work related to ios-sweet. |
| [2010475745xie/ios16-xnu-bringup](https://github.com/2010475745xie/ios16-xnu-bringup) | Windows/WSL2 host-side XNU and iOS-root-filesystem build notes. |
| [luuu20309/polaris-ios-patches](https://github.com/luuu20309/polaris-ios-patches) | Xiaomi Mi MIX 2S shim, display, and device-porting patches. |
| [lky005/ruby-ios-probes](https://github.com/lky005/ruby-ios-probes) | Read-only probes and test records for the ruby / MT6877 project. |
| [369099105XDai/hackios-picasso-build](https://github.com/369099105XDai/hackios-picasso-build) | Source-build recipe for Redmi K30 5G kernel experiments; not an installer. |
| [blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build) | Scripts for building XNU and related kernel research artifacts. |
| [blacktop/ipsw](https://github.com/blacktop/ipsw) | Apple-firmware inspection, extraction, and research toolkit. |
| [apple-oss-distributions/xnu](https://github.com/apple-oss-distributions/xnu) | Apple's published XNU source; not the complete iOS operating system. |

## Contributing

Know another device project? Open an issue or propose a README change with:

- The original project link and exact phone or tablet model.
- Its codename and the relevant device-specific documentation.
- Whether it is a native port, a build experiment, or emulation.
- A dated boot log, demonstration, or maintainer status note when available.
- A clear explanation if the README still contains an upstream device's claims.

Keep distinct device targets and meaningful development branches. Avoid adding
unchanged mirrors just to increase the list size, and do not describe a successful
build as a working iOS installation.

This directory is independent of Apple and the linked projects. Names and
trademarks belong to their respective owners.
