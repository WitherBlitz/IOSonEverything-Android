package io.github.dylanneve1.iosonpixel.install

import java.io.File
import java.security.MessageDigest
import org.json.JSONObject

/** Receipt and directory renames reconcile a killed installer before preference adoption. */
object GuestRecord {
    private val required = setOf("root", "kernel", "dtb", "trustcache", "sep_rom", "sep_fw", "vm.properties",
        "firmware", "syscfg", "ctrl_bits", "nvram", "effaceable", "panic_log", "sep_nvram", "sep_ssc")

    private val immutable = setOf("kernel", "dtb", "trustcache", "sep_fw", "sep_rom")

    /** The UI polls metadata; recovery also streams the recorded immutable-file digests once. */
    fun ready(directory: File, verifyHashes: Boolean = false,
        expectedProfile: String = "iphone11-18A5351d-cpu-v1"): Boolean = runCatching {
        val receipt = File(directory, "installation.json")
        if (!receipt.isFile || receipt.length() > 64 * 1024) return false
        val data = JSONObject(receipt.readText())
        if (data.optString("profile") != expectedProfile || !data.optBoolean("restored") || !data.optBoolean("patched")) return false
        val files = data.getJSONObject("files")
        if (!required.all { files.has(it) }) return false
        files.keys().forEach { name ->
            val file = File(directory, name)
            val size = files.getLong(name)
            if (File(name).name != name || file.canonicalFile.parentFile != directory.canonicalFile ||
                size <= 0 || !file.isFile || file.length() != size) return false
        }
        val hashes = data.getJSONObject("static_sha256")
        for (name in immutable) {
            val expected = hashes.getString(name)
            if (!expected.matches(Regex("[0-9a-f]{64}"))) return false
            if (verifyHashes) {
                val digest = MessageDigest.getInstance("SHA-256")
                File(directory, name).inputStream().use { input ->
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

    fun recover(base: File, activeDirectory: File? = null): File? {
        if (activeDirectory != null && ready(activeDirectory, verifyHashes = true)) return activeDirectory
        val current = File(base, "ios-current")
        if (ready(current, verifyHashes = true)) return current
        val previous = File(base, "ios-current.previous")
        val candidates = listOf(previous) + base.listFiles().orEmpty()
            .filter { it.name.matches(Regex("ios-staging-[0-9]+")) }.sortedByDescending { it.name }
        for (candidate in candidates) {
            if (candidate.canonicalFile.parentFile != base.canonicalFile || !ready(candidate, verifyHashes = true)) continue
            if (current.exists() && !current.renameTo(File(base, "ios-damaged-${System.nanoTime()}"))) return null
            if (candidate.renameTo(current)) return current
        }
        return null
    }
}
