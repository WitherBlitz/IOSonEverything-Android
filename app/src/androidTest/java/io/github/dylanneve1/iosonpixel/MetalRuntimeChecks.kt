package io.github.dylanneve1.iosonpixel

import android.content.Context
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject

/** Explicit private-device qualification; never launched by a product screen. */
object MetalRuntimeChecks {
    fun run(context: Context): String {
        val lib = context.applicationInfo.nativeLibraryDir
        val fixture = File(context.filesDir, "metal-authored.metallib")
        val hash = MessageDigest.getInstance("SHA-256").digest(fixture.readBytes())
            .joinToString("") { "%02x".format(it) }
        check(hash == "171ce8f3ac54a4877424bccd48112fa5e0759bcf04a6267e94b649b4ffeb9ea1")
        val runCache = File(context.cacheDir, "metal-test-${android.os.SystemClock.elapsedRealtimeNanos()}")
        check(runCache.mkdir()) { "A fresh qualification cache is required" }
        val reports = JSONArray()
        for (worker in listOf(false, true)) for (negative in listOf(false, true)) {
            val cache = File(runCache, if (worker) "worker" else "direct").apply { mkdirs() }
            val log = File(context.filesDir, "metal-abi-app-${if (worker) "worker-" else ""}${if (negative) "negative" else "positive"}.log")
            val args = mutableListOf("$lib/libios_metal_abi_test.so", "$lib/${if (worker) "libios_gpu.so" else "libiosgpu_metal.so"}",
                fixture.absolutePath, cache.absolutePath)
            if (negative) args.add("--negative")
            if (worker) args.add("--worker")
            val builder = ProcessBuilder(args).redirectErrorStream(true).redirectOutput(log)
            builder.environment()["TMPDIR"] = cache.absolutePath
            val process = builder.start()
            val ended = process.waitFor(45, TimeUnit.SECONDS)
            if (!ended) {
                process.destroyForcibly()
                check(process.waitFor(2, TimeUnit.SECONDS)) { "Timed-out Metal child did not terminate" }
                error("Metal runtime test exceeded 45 seconds")
            }
            check(log.length() <= 1024 * 1024) { "Metal diagnostic exceeded output cap" }
            val output = log.readText()
            val expected = if (negative) 1 else 0
            check(process.exitValue() == expected && output.contains("METAL_ABI_RESULT pass=${!negative}")) {
                "Metal ABI qualification exit=${process.exitValue()}: ${output.takeLast(6000)}"
            }
            check(output.contains("uid=${android.os.Process.myUid()} domain=u:r:untrusted_app")) {
                "Metal diagnostic did not execute under the ordinary app identity: ${output.take(1000)}"
            }
            reports.put(JSONObject().put("worker", worker).put("negative", negative).put("exit", expected)
                .put("readback_verified", true).put("cold_cache", !negative).put("log", log.name))
        }
        return JSONObject().put("uid", android.os.Process.myUid()).put("ordinary_app_domain", true)
            .put("scope", "typed Android Metal runtime; guest integration not yet qualified")
            .put("tests", reports).toString()
    }
}
