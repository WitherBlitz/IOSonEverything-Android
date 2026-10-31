package io.github.dylanneve1.iosonpixel.rfb

/** One dirty bounding box per RFB update, with constant storage even for fragmented frames. */
internal class RfbDamage {
    private var width = 0
    private var height = 0
    private var left = Int.MAX_VALUE
    private var top = Int.MAX_VALUE
    private var right = 0
    private var bottom = 0
    private fun clear() { left = Int.MAX_VALUE; top = Int.MAX_VALUE; right = 0; bottom = 0 }
    fun resize(width: Int, height: Int) { this.width = width; this.height = height; clear() }
    fun add(x: Int, y: Int, w: Int, h: Int) {
        require(x >= 0 && y >= 0 && w >= 0 && h >= 0 && x <= width && y <= height && w <= width - x && h <= height - y)
        if (w == 0 || h == 0) return
        left = minOf(left, x); top = minOf(top, y)
        right = maxOf(right, x + w); bottom = maxOf(bottom, y + h)
    }
    fun publish(copy: (Int, Int, Int, Int) -> Unit) {
        if (left == Int.MAX_VALUE) return
        val x = left; val y = top; val w = right - left; val h = bottom - top
        clear()
        copy(x, y, w, h)
    }
}
