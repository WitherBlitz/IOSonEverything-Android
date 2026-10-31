package io.github.dylanneve1.iosonpixel

import java.io.File
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class BootModeTest {
    @get:Rule val temporary = TemporaryFolder()

    @Test fun installedProfileCanExitPersistentRecoveryWithoutRamdisk() {
        val directory = temporary.newFolder()
        File(directory, "vm.properties").writeText("boot_mode=exit_recovery\n")
        val vm = VmLayout(directory)
        assertEquals("exit_recovery", vm.bootMode)
        assertNull(vm.ramdisk)
    }

    @Test fun bootModeCannotInjectAdditionalMachineOptions() {
        val directory = temporary.newFolder()
        File(directory, "vm.properties").writeText("boot_mode=exit_recovery,gpu=on\n")
        assertNull(VmLayout(directory).bootMode)
    }
}
