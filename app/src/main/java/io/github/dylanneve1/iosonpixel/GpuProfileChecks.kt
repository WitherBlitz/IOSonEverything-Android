package io.github.dylanneve1.iosonpixel

import java.io.File

/** Shared by diagnostics and the actual Inferno launch path; selection alone grants no GPU readiness. */
object GpuProfileChecks {
    private val requiredLibraries = listOf("libios_gpu.so", "libios_gpu_worker.so", "libgfxstream_backend.so", "libc++.so")

    fun problems(profileId: String?, directory: File, libraries: File): List<String> {
        val profile = GuestProfile.fromId(profileId)?.takeIf { it.usesGpuRuntime } ?: return emptyList()
        return buildList {
            if (!profile.ready(directory))
                add("The separate iOS14 GPU guest has not passed preparation checks.")
            for (name in requiredLibraries + if (profile == GuestProfile.IOS14_METAL) listOf("libiosgpu_metal.so") else emptyList()) {
                val file = File(libraries, name)
                if (!file.isFile || file.length() <= 0 || file.canonicalFile.parentFile != libraries.canonicalFile)
                    add("Required GPU runtime is missing: $name")
            }
        }
    }
}
