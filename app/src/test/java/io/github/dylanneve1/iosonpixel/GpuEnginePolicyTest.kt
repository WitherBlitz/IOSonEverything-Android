package io.github.dylanneve1.iosonpixel

import org.junit.Assert.*
import org.junit.Test

class GpuEnginePolicyTest {
    @Test fun metalSurfaceMayStartOffMain() {
        assertNull(GpuEnginePolicy.problem(GuestProfile.IOS14_METAL, true, Backend.QEMU, false))
    }
    @Test fun gpuNeverStartsOnUiThread() {
        for (shared in listOf(false, true))
            assertNotNull(GpuEnginePolicy.problem(GuestProfile.IOS14_METAL, shared, Backend.QEMU, true))
    }
    @Test fun glesKeepsQualifiedChildMode() {
        assertNotNull(GpuEnginePolicy.problem(GuestProfile.IOS14_GPU, true, Backend.QEMU, false))
        assertNull(GpuEnginePolicy.problem(GuestProfile.IOS14_GPU, false, Backend.QEMU, false))
    }
    @Test fun normalCpuRemainsAvailableAndMetalCannotFallBackToVnc() {
        assertNull(GpuEnginePolicy.problem(GuestProfile.IOS14, true, Backend.QEMU, false))
        assertNotNull(GpuEnginePolicy.problem(GuestProfile.IOS14_METAL, false, Backend.QEMU, false))
    }
}
