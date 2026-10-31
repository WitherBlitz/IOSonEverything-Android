package io.github.dylanneve1.iosonpixel

import org.junit.Assert.*
import org.junit.Test

class GuestResolutionTest {
    @Test fun s26UltraUsesRealPortraitPixelsAndExactlyFillsTheDisplay() {
        val resolution = GuestResolution.fromScreen(1440, 3120)
        assertNotNull(resolution)
        assertEquals(GuestResolution(1440, 3120), resolution)
        assertEquals(listOf("disp-width=1440", "disp-height=3120"), resolution!!.machineOptions())
        assertEquals(EdgeMap.Box(0, 0, 1440, 3120), EdgeMap.fit(1440, 3120, 0, resolution.width, resolution.height))
    }
    @Test fun rotatingAndroidDoesNotBootALandscapeIPhone() {
        assertEquals(GuestResolution(1440, 3120), GuestResolution.fromScreen(3120, 1440))
    }
    @Test fun unsupportedSizesCannotOverflowTransportOrAllocateUnboundedFrames() {
        for ((width, height) in listOf(0 to 3120, -1 to 1440, 1 to 1, 8192 to 8192,
                Int.MAX_VALUE to Int.MAX_VALUE, 320 to 5000, 4096 to 4096)) {
            assertNull(GuestResolution.fromScreen(width, height))
        }
    }
}
