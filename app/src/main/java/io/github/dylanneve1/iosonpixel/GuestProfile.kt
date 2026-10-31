package io.github.dylanneve1.iosonpixel

import java.io.File
import java.security.MessageDigest
import org.json.JSONObject
import io.github.dylanneve1.iosonpixel.install.GuestRecord

enum class GuestProfile(val id: String, val directoryName: String, val preferenceName: String,
    val displayName: String) {
    IOS14("iphone11-18A5351d-cpu-v1", "ios-current", "ios_install", "iOS 14.0 beta 5"),
    IOS16_5("ios16.5-20F66-virt-cpu-v1", "ios16-current", "ios16_install", "iOS 16.5"),
    IOS14_GPU("iphone11-18A5351d-gles-v1", "ios14-gpu-lab", "ios14_gpu_install", "iOS 14 · GPU (experimental)"),
    IOS14_METAL("iphone11-18A5351d-metal-v1", "ios14-metal-lab", "ios14_metal_install", "iOS 14 · Metal (experimental)");

    /** Only iOS14 currently has an integrated, reproducible on-device installer. */
    val installationEnabled: Boolean get() = this == IOS14

    /** The generic folder copier cannot preserve the managed GPU/virt recipes. */
    val supportsFolderImport: Boolean get() = this == IOS14

    val requiresVerifiedLaunch: Boolean get() = this != IOS14
    fun assessedForUi(directory: File): Boolean = when (this) {
        IOS14 -> true
        IOS16_5 -> Ios16LaunchIntegrity.assessedForUi(directory)
        IOS14_GPU -> GpuLaunchIntegrity.assessedForUi(directory)
        IOS14_METAL -> MetalLaunchIntegrity.assessedForUi(directory)
    }
    fun verifiedForUi(directory: File): Boolean = when (this) {
        IOS14 -> true
        IOS16_5 -> Ios16LaunchIntegrity.verifiedForUi(directory)
        IOS14_GPU -> GpuLaunchIntegrity.verifiedForUi(directory)
        IOS14_METAL -> MetalLaunchIntegrity.verifiedForUi(directory)
    }

    val isIos14: Boolean get() = this != IOS16_5
    val usesGpuRuntime: Boolean get() = this == IOS14_GPU || this == IOS14_METAL

    val defaultSettings: VmSettings get() = VmSettings(ramGb = if (isIos14) 3 else 4, smp = 4,
        tbSizeMb = 256, vcpuAffinity = "", inProcess = this == IOS14 || this == IOS14_METAL)

    /** Resolve metadata only. Selection never moves, copies or rewrites a guest directory. */
    fun resolve(installs: List<Install>, savedId: String?, baseDir: File): Install? {
        val assigned = installs.filter { it.profileId == id }
        if (assigned.isNotEmpty()) return assigned.singleOrNull()
        val otherDirectories = entries.filter { it != this }.map { File(baseDir, it.directoryName).canonicalFile }
        installs.singleOrNull { it.id == savedId && it.profileId == null &&
            it.dir.canonicalFile !in otherDirectories }?.let { return it }
        val directory = File(baseDir, directoryName).canonicalFile
        return installs.filter { it.profileId == null && it.dir.canonicalFile == directory }.singleOrNull()
    }

    /** UI polling checks receipt metadata only; import/recovery must request full hashes once. */
    fun ready(directory: File, verifyHashes: Boolean = false): Boolean {
        if (isIos14) {
            if (usesGpuRuntime) {
                val marker = File(directory, if (this == IOS14_METAL) "metal-lab-enabled" else "gpu-lab-enabled")
                if (!marker.isFile || marker.length() !in 1..256 ||
                    marker.canonicalFile.parentFile != directory.canonicalFile) return false
            }
            if (this == IOS14_METAL && !MetalGuestRecipe.ready(directory, verifyHashes)) return false
            return GuestRecord.ready(directory, verifyHashes, expectedProfile = id)
        }
        return runCatching {
            val data = receipt(directory) ?: return false
            if (data.optString("profile") != id || data.optInt("schema_version") != 1 ||
                !data.optBoolean("prepared") || !data.optBoolean("kernel_patches_verified")) return false
            val files = data.getJSONObject("files")
            if ((files.has("data.store") || data.optBoolean("persistence_verified")) &&
                !validDataArchive(directory, files.optJSONObject("data.store"))) return false
            for (name in listOf("Image", "payload.bin", "system.apfs")) {
                val record = files.getJSONObject(name)
                val file = File(directory, name)
                val size = record.getLong("bytes")
                val expected = record.getString("sha256")
                if (size <= 0 || !file.isFile || file.length() != size ||
                    file.canonicalFile.parentFile != directory.canonicalFile ||
                    !expected.matches(Regex("[0-9a-f]{64}"))) return false
                if (verifyHashes) {
                    val digest = MessageDigest.getInstance("SHA-256")
                    file.inputStream().use { input ->
                        val chunk = ByteArray(65536)
                        while (true) {
                            val count = input.read(chunk)
                            if (count < 0) break
                            digest.update(chunk, 0, count)
                        }
                    }
                    if (digest.digest().joinToString("") { "%02x".format(it) } != expected) return false
                }
            }
            true
        }.getOrDefault(false)
    }

    fun qualified(directory: File): Boolean = this == IOS16_5 && ready(directory) && runCatching {
        receipt(directory)?.let { it.optBoolean("gui_boot_verified") && it.optBoolean("input_verified") &&
            it.optBoolean("persistence_verified") } ?: false
    }.getOrDefault(false)

    fun hasPersistentArchive(directory: File): Boolean = this == IOS16_5 && runCatching {
        validDataArchive(directory, receipt(directory)?.optJSONObject("files")?.optJSONObject("data.store"))
    }.getOrDefault(false)

    private fun validDataArchive(directory: File, record: JSONObject?): Boolean {
        if (record == null || !record.optBoolean("mutable") || !record.optBoolean("sha256_is_initial_only")) return false
        val file = File(directory, "data.store")
        return record.optLong("bytes") > 0 && file.isFile && file.length() == record.optLong("bytes") &&
            file.canonicalFile.parentFile == directory.canonicalFile &&
            record.optString("sha256").matches(Regex("[0-9a-f]{64}"))
    }

    private fun receipt(directory: File): JSONObject? {
        val file = File(directory, "installation.json")
        return if (file.isFile && file.length() in 1..65536) JSONObject(file.readText()) else null
    }

    companion object {
        fun fromId(id: String?): GuestProfile? = entries.firstOrNull { it.id == id }
        fun switchAllowed(vmActive: Boolean, installerActive: Boolean, fileOperationActive: Boolean,
            diskBusy: Boolean): Boolean = !vmActive && !installerActive && !fileOperationActive && !diskBusy
    }
}
