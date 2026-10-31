package io.github.dylanneve1.iosonpixel

/** Engine eligibility shared by visible checks and startup. */
object GpuEnginePolicy {
    fun problem(profile: GuestProfile?, shared: Boolean, backend: Backend, onUiThread: Boolean): String? = when {
        profile?.usesGpuRuntime != true -> null
        onUiThread -> "GPU verification must run off the UI thread."
        backend != Backend.QEMU -> "GPU profiles require the QEMU engine."
        profile == GuestProfile.IOS14_METAL && !shared -> "The Metal profile requires the direct Android Surface display."
        shared && profile != GuestProfile.IOS14_METAL -> "This GPU profile requires the child QEMU engine."
        else -> null
    }
}
