package io.github.dylanneve1.iosonpixel

import java.io.File
import java.security.MessageDigest
import java.nio.file.Files
import org.json.JSONObject

/** Enabled only by a separately qualified preparation receipt. */
object MetalGuestRecipe {
    private val bindings = mapOf("kernel" to "kernel", "dtb" to "dtb", "trustcache" to "trustcache",
        "sep_fw" to "sep_fw", "sep_rom" to "sep_rom", "root" to "root",
        "root_format" to "raw", "boot_mode" to "exit_recovery")
    private val hash = Regex("[0-9a-f]{64}")
    private val immutable = listOf("kernel", "dtb", "trustcache", "sep_fw", "sep_rom", "vm.properties")

    private fun boundedFile(directory: File, name: String, maximum: Long): File? {
        val file = File(directory, name)
        return file.takeIf { it.isFile && it.length() in 1..maximum &&
            !Files.isSymbolicLink(it.toPath()) && it.canonicalFile.parentFile == directory.canonicalFile }
    }

    /** Strict authored recipe: no duplicate properties, escapes, aliases or extra keys. */
    private fun parse(bytes: ByteArray): Map<String, String>? {
        if (bytes.size !in 1..4096 || bytes.any { it.toInt() < 0 }) return null
        val lines = bytes.toString(Charsets.US_ASCII).replace("\r\n", "\n").trimEnd('\n').split('\n')
        if (lines.size != bindings.size) return null
        val parsed = mutableMapOf<String, String>()
        for (line in lines) {
            val fields = line.split('=')
            if (fields.size != 2 || parsed.put(fields[0], fields[1]) != null) return null
        }
        return parsed.takeIf { it == bindings }
    }

    fun ready(directory: File, verifyRecipeHash: Boolean = false): Boolean = runCatching {
        val receiptFile = boundedFile(directory, "installation.json", 65536) ?: return false
        val data = JSONObject(receiptFile.readText())
        if (data.optString("profile") != GuestProfile.IOS14_METAL.id) return false
        val qualification = data.getJSONObject("metal_qualification")
        if (qualification.optInt("schema_version") != 1 ||
            qualification.optString("scope") != "linked-authored-app" ||
            qualification.optString("upstream_pin") != "a2c440b8bcdcf20d34aa1694b61ae22c2a7ea68b") return false
        if (!listOf("public_api_verified", "visible_verified", "touch_verified", "relaunch_verified")
                .all { qualification.optBoolean(it) }) return false
        if (!listOf("driver_sha256", "app_sha256", "runtime_sha256", "metallib_sha256")
                .all { qualification.optString(it).matches(hash) }) return false
        val hashes = data.getJSONObject("static_sha256")
        if (!immutable.all { hashes.optString(it).matches(hash) }) return false
        val recipe = boundedFile(directory, "vm.properties", 4096)?.readBytes() ?: return false
        if (parse(recipe) == null) return false
        if (verifyRecipeHash && digest(recipe) != hashes.getString("vm.properties")) return false
        // Every fixed mutable disk must also stay inside this managed directory.
        (VmLayout.REQUIRED_KEYS + VmLayout.SMALL_DISKS.map { it.name } + VmLayout.PFLASH).all {
            File(directory, it).let { file ->
                file.isFile && !Files.isSymbolicLink(file.toPath()) &&
                    file.canonicalFile.parentFile == directory.canonicalFile
            }
        }
    }.getOrDefault(false)

    /** Caller holds DiskLease; construct argv from these same authenticated bytes. */
    fun verifiedLayout(directory: File): VmLayout? = runCatching {
        if (!ready(directory)) return null
        val recipe = boundedFile(directory, "vm.properties", 4096)?.readBytes() ?: return null
        val receiptFile = boundedFile(directory, "installation.json", 65536) ?: return null
        val expected = JSONObject(receiptFile.readText()).getJSONObject("static_sha256").getString("vm.properties")
        if (digest(recipe) != expected) return null
        val parsed = parse(recipe) ?: return null
        VmLayout(directory, parsed)
    }.getOrNull()

    private fun digest(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
        .digest(bytes).joinToString("") { "%02x".format(it) }
}
