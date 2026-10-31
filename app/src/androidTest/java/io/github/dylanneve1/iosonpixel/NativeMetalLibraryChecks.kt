package io.github.dylanneve1.iosonpixel

import android.content.Context
import java.io.File
import java.security.MessageDigest
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.TimeUnit
import org.json.JSONArray
import org.json.JSONObject

/** Private native iOS14 inputs: report pipeline creation, never shader names or bodies. */
object NativeMetalLibraryChecks {
    fun run(context: Context): String {
        val hashes = listOf("29cbdc2cf9697b49d81654512bc083d2cc5b341d729da15f343b1b7709c5ff8f",
            "42734062c987cb8adebfa6ad72e81a6c3f881d278149f404d63c7892a94a4971",
            "5292421ef7c34cc73d8ba136706937ecc4c8f3daa8632d8cb49801d79406a0fa")
        val run = File(context.cacheDir, "native-air-${android.os.SystemClock.elapsedRealtimeNanos()}")
        check(run.mkdir())
        val lib = context.applicationInfo.nativeLibraryDir
        val cases = JSONArray()
        for ((ordinal, expected) in hashes.withIndex()) {
            val input = File(context.filesDir, "native-air-$ordinal.metallib")
            check(input.length() in 1..8L * 1024 * 1024)
            val hash = MessageDigest.getInstance("SHA-256").digest(input.readBytes()).joinToString("") { "%02x".format(it) }
            check(hash == expected) { "Private native audit input identity differs" }
            for (worker in listOf(false, true)) for (vertexLayout in if (ordinal == 2) listOf(false, true) else listOf(false)) {
                val cache = File(run, "$ordinal-$worker-$vertexLayout").apply { check(mkdir()) }
                val log = File(context.filesDir, "native-air-$ordinal-$worker-$vertexLayout.private.log")
                val args = mutableListOf("$lib/libios_metal_native_audit.so", "$lib/${if (worker) "libios_gpu.so" else "libiosgpu_metal.so"}", input.absolutePath, cache.absolutePath)
                if (worker) args.add("--worker")
                if (vertexLayout) {
                    // Caller descriptor matching this native input's two float2
                    // stage-in attributes. This is test data, not runtime inference.
                    val data = ByteBuffer.allocate(72).order(ByteOrder.LITTLE_ENDIAN)
                    data.putInt(2)
                    data.putInt(0).putInt(29).putLong(0).putInt(1)
                    data.putInt(1).putInt(29).putLong(8).putInt(1)
                    data.putInt(1).putInt(1).putLong(16).putInt(1).putLong(1)
                    val descriptor = File(cache, "caller-vertex-layout.bin").apply { writeBytes(data.array()) }
                    args.addAll(listOf("--layout", descriptor.absolutePath))
                }
                val builder = ProcessBuilder(args).redirectErrorStream(true).redirectOutput(log)
                builder.environment()["TMPDIR"] = cache.absolutePath
                val child = builder.start()
                if (!child.waitFor(65, TimeUnit.SECONDS)) {
                    child.destroyForcibly(); check(child.waitFor(2, TimeUnit.SECONDS))
                    error("Native Metal pipeline audit exceeded its deadline")
                }
                check(log.length() <= 1024 * 1024)
                val text = log.readText()
                check(child.exitValue() in 0..1 && text.contains("NATIVE_METAL_RESULT ")) { "Native pipeline probe did not return a bounded semantic result; private log retained" }
                check(text.contains("uid=${android.os.Process.myUid()} domain=u:r:untrusted_app"))
                cases.put(JSONObject().put("ordinal", ordinal).put("sha256", hash).put("worker", worker).put("vertex_layout", vertexLayout)
                    .put("exit", child.exitValue()).put("summary", JSONArray(text.lines().filter { it.startsWith("NATIVE_METAL_") })))
            }
        }
        return JSONObject().put("scope", "Native iOS14 pipeline creation on Adreno; no dispatched workload or checked pixels")
            .put("uid", android.os.Process.myUid()).put("ordinary_app_domain", true).put("cases", cases).toString()
    }
}
