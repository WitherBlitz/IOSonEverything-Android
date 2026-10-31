package io.github.dylanneve1.iosonpixel

import java.io.File
import org.junit.Assert.*
import org.junit.Test

class QemuVirtCommandTest {
    private fun path(value: String) = File(value).absolutePath
    private fun command(dir: File = File("/private/ios16"), data: Boolean = false) =
        QemuVirtCommand.build(File("/native/virt.so"), dir, File("/private/run/16"),
            File("/private/qemu-data"), GuestProfile.IOS16_5.defaultSettings, data)

    @Test fun usesSeparateEngineVirtBoardAndSoftwareAcceleration() {
        val args = command()
        assertEquals(path("/native/virt.so"), args.first())
        assertEquals("virt,gic-version=3", args[args.indexOf("-M") + 1])
        assertEquals("tcg,thread=multi,tb-size=256", args[args.indexOf("-accel") + 1])
        assertFalse(args.any { it.contains("kvm") || it.contains("t8030") || it.contains("sep_") })
        // The persistent recipe is device-qualified with four software vCPUs.
        assertEquals("4", args[args.indexOf("-smp") + 1])
    }

    @Test fun systemIsReadOnlyAndGuestFilesBelongToSelectedProfile() {
        val args = command()
        assertTrue(args.contains("file=${path("/private/ios16/system.apfs")},format=raw,if=none,id=ios16sys,readonly=on"))
        assertEquals(path("/private/ios16/Image"), args[args.indexOf("-kernel") + 1])
        assertEquals(path("/private/ios16/payload.bin"), args[args.indexOf("-initrd") + 1])
        assertFalse(args.any { it.contains("ios-current") })
    }

    @Test fun displayAndInputUseStandardVirtioAndPrivateSockets() {
        val args = command()
        assertTrue(args.contains("virtio-gpu-pci,xres=1125,yres=2436"))
        // The iOS16 input driver consumes ABS_X/ABS_Y and BTN_LEFT, as VNC emits.
        assertTrue(args.contains("virtio-tablet-pci"))
        assertFalse(args.contains("virtio-multitouch-pci"))
        assertTrue(args.contains("virtio-keyboard-pci"))
        assertTrue(args.contains("unix:${path("/private/run/16/vnc.sock")}"))
        assertTrue(args.contains("unix:${path("/private/run/16/qmp.sock")},server=on,wait=off"))
        assertFalse(args.any { it.contains("scfb") || it.contains("gfxstream") })
    }

    @Test fun writableArchiveIsSeparateAndExplicit() {
        assertFalse(command().any { it.contains("data.store") || it.contains("virtio_blk_rw=1") })
        val args = command(data = true)
        assertTrue(args.contains("file=${path("/private/ios16/data.store")},format=raw,if=none,id=ios16data"))
        assertTrue(args.contains("virtio-blk-pci,drive=ios16data"))
        assertTrue(args[args.indexOf("-append") + 1].contains("virtio_blk_rw=1"))
    }

    @Test fun profileButtonMappingDoesNotUseIphone14FunctionKeys() {
        assertEquals("h", QemuVirtCommand.key(HardwareButton.HOME))
        assertEquals("l", QemuVirtCommand.key(HardwareButton.POWER))
        assertEquals("up", QemuVirtCommand.key(HardwareButton.VOLUME_UP))
        assertEquals("down", QemuVirtCommand.key(HardwareButton.VOLUME_DOWN))
        assertNull(QemuVirtCommand.key(HardwareButton.RINGER))
    }

    @Test(expected = IllegalArgumentException::class)
    fun commaInDiskPathCannotInjectDriveOptions() { command(File("/private/name,readonly=off")) }
}
