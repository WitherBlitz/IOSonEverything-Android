package io.github.dylanneve1.iosonpixel

/** Bounded portrait display request; independent of the guest disk recipe. */
data class GuestResolution(val width: Int, val height: Int) {
    init {
        require(width in 320..4096 && height in 320..4096 && width.toLong() * height <= 8L * 1024 * 1024)
    }
    fun machineOptions(): List<String> = listOf("disp-width=$width", "disp-height=$height")
    companion object {
        fun fromScreen(width: Int, height: Int): GuestResolution? = runCatching {
            GuestResolution(minOf(width, height), maxOf(width, height))
        }.getOrNull()
    }
}
