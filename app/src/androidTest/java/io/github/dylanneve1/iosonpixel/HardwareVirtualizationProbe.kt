package io.github.dylanneve1.iosonpixel

import android.content.Context
import android.os.ParcelFileDescriptor
import io.github.dylanneve1.iosonpixel.avf.AvfApi
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.lang.reflect.InvocationTargetException

/** Read-only API observation plus config construction; never starts or replaces a guest. */
object HardwareVirtualizationProbe {
    fun run(ctx: Context): String {
        check(!DiskLease.busy(ctx.filesDir)) { "Stop the iOS guest before running instrumentation" }
        val result = JSONObject().put("package", ctx.packageName)
            .put("uid", android.os.Process.myUid())
            .put("timestamp_ms", System.currentTimeMillis())
            .put("avf_feature", ctx.packageManager.hasSystemFeature(AvfApi.FEATURE))
        val permissions = JSONObject()
        for (name in listOf(AvfApi.PERM_MANAGE, AvfApi.PERM_CUSTOM))
            permissions.put(name, ctx.checkSelfPermission(name))
        result.put("permissions", permissions)
        val api = AvfApi.instance
        result.put("classes_present", api.present)
        result.put("blocked_members", JSONArray(api.blocked.map { it.key }))
        try {
            val manager = api.manager(ctx)
            result.put("manager_present", manager != null)
            if (manager != null) {
                val capabilities = api.capabilities(manager)
                result.put("capabilities", capabilities)
                    .put("protected_supported", capabilities and AvfApi.CAPABILITY_PROTECTED_VM != 0)
                    .put("nonprotected_supported", capabilities and AvfApi.CAPABILITY_NON_PROTECTED_VM != 0)
            }
        } catch (error: Throwable) {
            result.put("manager_error", describe(error))
        }
        try {
            ParcelFileDescriptor.open(File("/dev/gunyah"), ParcelFileDescriptor.MODE_READ_WRITE).use {
                result.put("direct_gunyah_open", "opened_without_ioctl")
            }
        } catch (error: Throwable) {
            result.put("direct_gunyah_open", describe(error))
        }
        val scratch = File(ctx.filesDir, "hardware-virtualization-config-probe")
        check(!scratch.exists()) { "Probe scratch already exists; refusing to reuse it" }
        check(scratch.mkdir())
        try {
            val kernel = File(scratch, "kernel.bin").apply { writeBytes(ByteArray(4096)) }
            try {
                api.buildConfig(ctx, AvfApi.Spec(
                    name = "iosoneverything-hardware-probe", kernel = kernel.absolutePath,
                    initrd = null, params = emptyList(), disks = emptyList(),
                    memoryBytes = 256L * 1024 * 1024, matchHostCpus = false,
                ))
                result.put("scion_nonprotected_config", "built_only_not_started")
            } catch (error: Throwable) {
                result.put("scion_nonprotected_config", describe(error))
            }
        } finally {
            check(File(scratch, "kernel.bin").delete())
            check(scratch.delete())
        }
        val text = result.toString(2)
        File(ctx.filesDir, "hardware-virtualization-report.json").writeText(text)
        return text
    }

    private fun describe(error: Throwable): String {
        var cause = error
        while (cause is InvocationTargetException && cause.cause != null) cause = cause.cause!!
        return cause.javaClass.name + ": " + cause.message
    }
}
