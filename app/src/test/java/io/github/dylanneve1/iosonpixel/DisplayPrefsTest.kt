package io.github.dylanneve1.iosonpixel

import org.junit.Assert.*
import org.junit.Test

class DisplayPrefsTest {
    @Test fun defaultDisplayFillsS26UltraWithoutAnArtificialGestureFrame() {
        val preferences = DisplayPrefs()
        assertFalse("Default gesture border makes the guest unnecessarily small", preferences.border)
        val box = EdgeMap.fit(1440, 3120, if (preferences.border) 184 else 0, 832, 1792)
        assertEquals(1440, box.width)
        assertTrue(box.top <= 10)
        assertEquals(0, box.left)
    }
}
