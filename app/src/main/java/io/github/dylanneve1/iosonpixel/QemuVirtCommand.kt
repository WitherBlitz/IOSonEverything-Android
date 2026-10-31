package io.github.dylanneve1.iosonpixel

import java.io.File

/** Exact iOS16 virt recipe. Apple t8030 boot files are never reused by this board. */
object QemuVirtCommand {
    fun build(engine: File, guest: File, run: File, data: File, settings: VmSettings,
        writableArchive: Boolean = false): List<String> {
        require(!guest.absolutePath.contains(',')) { "Guest directory contains a QEMU drive separator" }
        val cpus = settings.smp.coerceIn(1, 4)
        val boot = "md0=rvblk0 cpus=$cpus security=bringup virtio_input=1 " +
            "vgpu_width=1125 vgpu_height=2436 -v" +
            if (writableArchive) " virtio_blk_rw=1 var_store=1 virt_var_store=1 var_save_ms=20000" else ""
        return buildList {
            addAll(listOf(engine.absolutePath, "-L", data.absolutePath,
                "-M", "virt,gic-version=3", "-cpu", "cortex-a76",
                "-accel", "tcg,thread=multi,tb-size=${settings.tbSizeMb.coerceIn(64, 1024)}",
                "-smp", cpus.toString(), "-m", "${settings.ramGb.coerceIn(1, 4)}G",
                "-kernel", File(guest, "Image").absolutePath,
                "-initrd", File(guest, "payload.bin").absolutePath, "-append", boot,
                "-drive", "file=${File(guest, "system.apfs").absolutePath},format=raw,if=none,id=ios16sys,readonly=on",
                "-device", "virtio-blk-pci,drive=ios16sys"))
            if (writableArchive) addAll(listOf("-drive",
                "file=${File(guest, "data.store").absolutePath},format=raw,if=none,id=ios16data",
                "-device", "virtio-blk-pci,drive=ios16data"))
            addAll(listOf("-device", "virtio-gpu-pci,xres=1125,yres=2436",
                "-device", "virtio-tablet-pci", "-device", "virtio-keyboard-pci",
                "-display", "none", "-vnc", "unix:${File(run, "vnc.sock").absolutePath}",
                "-qmp", "unix:${File(run, "qmp.sock").absolutePath},server=on,wait=off",
                "-monitor", "unix:${File(run, "monitor.sock").absolutePath},server=on,wait=off",
                "-serial", "stdio", "-nic", "none", "-no-reboot"))
        }
    }

    fun key(button: HardwareButton): String? = when (button) {
        HardwareButton.HOME -> "h"
        HardwareButton.POWER -> "l"
        HardwareButton.VOLUME_UP -> "up"
        HardwareButton.VOLUME_DOWN -> "down"
        HardwareButton.RINGER -> null
    }
}
