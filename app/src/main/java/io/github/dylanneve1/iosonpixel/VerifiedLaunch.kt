package io.github.dylanneve1.iosonpixel

import java.io.Closeable
import java.io.File
import java.security.MessageDigest
import org.json.JSONObject

/** Cancellation is cheap during hashing and serialized with exec/publication. */
class VerifiedLaunch<T> {
    private val monitor = Any()
    @Volatile var cancelled = false
        private set
    private var started: T? = null

    fun cancel(stop: (T) -> Unit) {
        val child = synchronized(monitor) { cancelled = true; started }
        child?.let(stop)
    }

    /** A created child owns the lease until its output pump has waited for actual exit. */
    fun <L : Closeable> run(acquire: () -> L?, verify: (() -> Boolean) -> Boolean,
        exec: (L) -> T?): T? {
        if (cancelled) return null
        val lease = acquire() ?: return null
        var transferred = false
        try {
            if (cancelled || !verify { !cancelled }) return null
            return synchronized(monitor) {
                if (cancelled) null else exec(lease)?.also { started = it; transferred = true }
            }
        } finally {
            if (!transferred) lease.close()
        }
    }
}

/** The fingerprint caches UI assessment only. Every exec still streams all immutable bytes. */
open class GuestLaunchIntegrity(private val profile: GuestProfile, private val immutable: List<String>,
    private val extraUiFiles: List<String> = emptyList(), private val mutableUiFiles: Set<String> = emptySet()) {
    private data class Assessment(val fingerprint: List<String>, val verified: Boolean)
    private val assessments = mutableMapOf<String, Assessment>()

    private fun fingerprint(directory: File): List<String> =
        (immutable + listOf("installation.json") + extraUiFiles).map { name ->
            File(directory, name).let {
                "${it.canonicalPath}:${it.length()}:${if (name in mutableUiFiles) 0 else it.lastModified()}:${it.isFile}"
            }
        }

    fun record(directory: File, verified: Boolean) {
        val key = directory.canonicalPath
        val result = Assessment(fingerprint(directory), verified)
        synchronized(assessments) { assessments[key] = result }
    }

    fun assessedForUi(directory: File): Boolean = assessment(directory) != null
    fun verifiedForUi(directory: File): Boolean = assessment(directory)?.verified == true
    private fun assessment(directory: File): Assessment? = runCatching {
        val saved = synchronized(assessments) { assessments[directory.canonicalPath] } ?: return null
        saved.takeIf { it.fingerprint == fingerprint(directory) }
    }.getOrNull()

    /** Caller must hold DiskLease. Cancellation is polled between bounded reads. */
    fun verify(directory: File, keepGoing: () -> Boolean): Boolean {
        val verified = runCatching {
            if (!keepGoing() || !profile.ready(directory)) return@runCatching false
            val receipt = File(directory, "installation.json")
            val receiptText = receipt.readText()
            val data = JSONObject(receiptText)
            val before = fingerprint(directory)
            val chunk = ByteArray(65536)
            for (name in immutable) {
                if (!keepGoing()) return@runCatching false
                val digest = MessageDigest.getInstance("SHA-256")
                File(directory, name).inputStream().use { input ->
                    while (true) {
                        if (!keepGoing()) return@runCatching false
                        val count = input.read(chunk)
                        if (count < 0) break
                        digest.update(chunk, 0, count)
                    }
                }
                val actual = digest.digest().joinToString("") { "%02x".format(it) }
                val expected = if (profile.isIos14) data.getJSONObject("static_sha256").getString(name)
                    else data.getJSONObject("files").getJSONObject(name).getString("sha256")
                if (actual != expected) return@runCatching false
            }
            keepGoing() && before == fingerprint(directory) && receiptText == receipt.readText() &&
                profile.ready(directory)
        }.getOrDefault(false)
        // A user cancelling a recheck is not evidence that unchanged files became corrupt.
        if (keepGoing()) record(directory, verified)
        return verified
    }
}

object Ios16LaunchIntegrity : GuestLaunchIntegrity(GuestProfile.IOS16_5,
    listOf("Image", "payload.bin", "system.apfs"), listOf("data.store"), setOf("data.store"))

object GpuLaunchIntegrity : GuestLaunchIntegrity(GuestProfile.IOS14_GPU,
    listOf("kernel", "dtb", "trustcache", "sep_fw", "sep_rom"), listOf("gpu-lab-enabled"))

object MetalLaunchIntegrity : GuestLaunchIntegrity(GuestProfile.IOS14_METAL,
    listOf("kernel", "dtb", "trustcache", "sep_fw", "sep_rom", "vm.properties"), listOf("metal-lab-enabled"))
