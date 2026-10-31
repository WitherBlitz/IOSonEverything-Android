package io.github.dylanneve1.iosonpixel.rfb

import org.junit.Assert.*
import org.junit.Test

class RfbDamageTest {
    @Test fun fragmentedFramePublishesOneRegionContainingEveryChangedPixel() {
        val damage = RfbDamage()
        damage.resize(1440, 3120)
        repeat(3120) { y -> damage.add(32, y, 1408, 1) }
        val copies = mutableListOf<List<Int>>()
        damage.publish { x, y, w, h -> copies += listOf(x, y, w, h) }
        assertEquals(listOf(listOf(32, 0, 1408, 3120)), copies)
        damage.publish { _, _, _, _ -> fail("An idle update must not copy old damage") }
    }

    @Test fun disjointChangesKeepTheirCoordinatesAndIncludeTheGap() {
        val damage = RfbDamage(); damage.resize(20, 30)
        damage.add(2, 3, 4, 5); damage.add(14, 20, 3, 8)
        damage.publish { x, y, w, h -> assertEquals(listOf(2, 3, 15, 25), listOf(x, y, w, h)) }
    }

    @Test fun resizeDropsDamageForReplacedFramebufferAndEmptyRectsDoNothing() {
        val damage = RfbDamage(); damage.resize(1440, 3120); damage.add(0, 0, 1440, 3120)
        damage.resize(16, 16); damage.add(16, 16, 0, 0)
        damage.publish { _, _, _, _ -> fail("Resize replaced the pixels and discarded old damage") }
        damage.add(15, 15, 1, 1)
        damage.publish { x, y, w, h -> assertEquals(listOf(15, 15, 1, 1), listOf(x, y, w, h)) }
    }

    @Test fun outOfBoundsRectanglesAreRejectedBeforePixelWrites() {
        val damage = RfbDamage(); damage.resize(16, 16)
        for (rect in listOf(listOf(-1, 0, 1, 1), listOf(0, 16, 1, 1),
                listOf(15, 0, Int.MAX_VALUE, 1), listOf(0, 0, 1, -1))) {
            try { damage.add(rect[0], rect[1], rect[2], rect[3]); fail("Accepted $rect") }
            catch (_: IllegalArgumentException) {}
        }
        damage.publish { _, _, _, _ -> fail("Rejected damage must not be published") }
    }
}
