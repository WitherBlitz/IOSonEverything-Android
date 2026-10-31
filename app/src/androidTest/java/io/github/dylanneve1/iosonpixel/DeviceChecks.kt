package io.github.dylanneve1.iosonpixel

import android.app.Activity
import android.app.Instrumentation
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.os.Bundle
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import io.github.dylanneve1.iosonpixel.install.InstallService
import org.json.JSONObject

/** Explicit ADB-driven checks in the real app sandbox; no exported product hook. */
class DeviceChecks : Instrumentation() {
    private var options = Bundle()
    override fun onCreate(arguments: Bundle?) {
        options = arguments ?: Bundle()
        super.onCreate(arguments)
        start()
    }

    override fun onStart() {
        try {
            if (options.getString("metal_native_libraries") == "true") {
                val lease = DiskLease.acquire(targetContext.filesDir) ?: error("Stop the guest before native AIR qualification")
                val report = lease.use { NativeMetalLibraryChecks.run(targetContext) }
                finish(Activity.RESULT_OK, Bundle().apply { putString("report", report) })
                return
            }
            if (options.getString("rfb_protocol") == "true") {
                val report = RfbProtocolChecks.run()
                finish(Activity.RESULT_OK, Bundle().apply { putString("report", report) })
                return
            }
            if (options.getString("metal_rfb_delivery") == "true") {
                val report = RfbDeliveryChecks.run(this)
                finish(Activity.RESULT_OK, Bundle().apply { putString("report", report) })
                return
            }
            if (options.getString("metal_surface_delivery") == "true") {
                val report = SurfaceDeliveryChecks.run(this)
                finish(Activity.RESULT_OK, Bundle().apply { putString("report", report) })
                return
            }
            options.getString("metal_surface_check")?.let { mode ->
                val report = MetalSurfaceChecks.run(this, mode)
                finish(Activity.RESULT_OK, Bundle().apply { putString("report", report) })
                return
            }
            if (options.getString("metal_runtime") == "true") {
                val lease = DiskLease.acquire(targetContext.filesDir)
                    ?: error("Stop the guest before Metal runtime qualification")
                val report = lease.use { MetalRuntimeChecks.run(targetContext) }
                finish(Activity.RESULT_OK, Bundle().apply { putString("report", report) })
                return
            }
            if (options.getString("start_ios16_preparation") == "true") {
                check((targetContext.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
                    "iOS16 preparation qualification requires a debuggable target"
                }
                check(!InstallService.running && VmState.status == VmState.Status.STOPPED && !ImportState.running)
                val attempt = java.util.UUID.randomUUID().toString()
                val preparation = targetContext.getSharedPreferences(GuestProfile.IOS16_5.preferenceName, 0)
                targetContext.startForegroundService(Intent(targetContext, InstallService::class.java)
                    .putExtra("guest_profile", GuestProfile.IOS16_5.id)
                    .putExtra(InstallService.INTERNAL_PREPARATION_ID, attempt)
                    .putExtra(InstallService.INTERNAL_IOS16_QUALIFICATION, true))
                val startup = android.os.SystemClock.elapsedRealtime() + 15000
                while (preparation.getString("preparation_attempt", null) != attempt &&
                    android.os.SystemClock.elapsedRealtime() < startup) Thread.sleep(50)
                check(preparation.getString("preparation_attempt", null) == attempt) { "iOS16 preparation service did not acknowledge this attempt" }
                val seconds = options.getString("preparation_timeout_seconds")?.toLongOrNull()?.coerceIn(1, 21600) ?: 21600
                val deadline = android.os.SystemClock.elapsedRealtime() + seconds * 1000
                while (InstallService.running && android.os.SystemClock.elapsedRealtime() < deadline) Thread.sleep(1000)
                if (InstallService.running) {
                    targetContext.startService(Intent(targetContext, InstallService::class.java).setAction(InstallService.CANCEL))
                    val cancelled = android.os.SystemClock.elapsedRealtime() + 120000
                    while (InstallService.running && android.os.SystemClock.elapsedRealtime() < cancelled) Thread.sleep(100)
                    error("iOS16 preparation qualification reached its external deadline; cancellation requested")
                }
                val lease = DiskLease.acquire(targetContext.filesDir) ?: error("Another disk owner appeared after preparation")
                val report = lease.use {
                    val directory = java.io.File(targetContext.filesDir, GuestProfile.IOS16_5.directoryName)
                    check(preparation.getString("preparation_attempt", null) == attempt &&
                        preparation.getBoolean("preparation_complete", false) &&
                        preparation.getBoolean("preparation_success", false)) {
                        "This iOS16 preparation attempt failed: " + preparation.getString("message", "no status")
                    }
                    check(targetContext.getSharedPreferences(GuestProfile.IOS16_5.preferenceName, 0).getBoolean("installed", false)) {
                        "Preparation failed: " + targetContext.getSharedPreferences(GuestProfile.IOS16_5.preferenceName, 0).getString("message", "no status")
                    }
                    check(GuestProfile.IOS16_5.ready(directory, verifyHashes = true)) { "Prepared iOS16 immutable verification failed" }
                    check(!GuestProfile.IOS16_5.installationEnabled) { "Product install gate was unexpectedly enabled" }
                    JSONObject().put("profile", GuestProfile.IOS16_5.id).put("prepared", true)
                        .put("device_guest_qualified", false).put("product_install_enabled", false).toString()
                }
                finish(Activity.RESULT_OK, Bundle().apply { putString("report", report) })
                return
            }
            if (options.getString("installer_tools_smoke") == "true") {
                val lease = DiskLease.acquire(targetContext.filesDir)
                    ?: error("Stop the guest before checking installer tools")
                val report = lease.use {
                    if (!Python.isStarted()) Python.start(AndroidPlatform(targetContext))
                    val tools = Python.getInstance().getModule("iosvm.device_checks").callAttr(
                        "installer_tools_smoke", targetContext.filesDir.absolutePath,
                        targetContext.applicationInfo.nativeLibraryDir,
                    ).toString()
                    val sqlite = Python.getInstance().getModule("iosvm.installer16")
                        .callAttr("sqlite_smoke", targetContext.filesDir.absolutePath).toString()
                    check(JSONObject(sqlite).getInt("uid") == android.os.Process.myUid()) { "SQLite smoke UID differs" }
                    JSONObject(tools).put("sqlite3", JSONObject(sqlite)).toString()
                }
                finish(Activity.RESULT_OK, Bundle().apply { putString("report", report) })
                return
            }
            if (options.getString("installer_audit") == "true") {
                val lease = DiskLease.acquire(targetContext.filesDir)
                    ?: error("Stop the guest and all file operations before the installer audit")
                val report = lease.use {
                    if (!Python.isStarted()) Python.start(AndroidPlatform(targetContext))
                    Python.getInstance().getModule("iosvm.device_checks").callAttr(
                        "installer_audit", targetContext.filesDir.absolutePath,
                        targetContext.applicationInfo.nativeLibraryDir,
                        options.getString("audit_url") ?: error("Missing audit URL"),
                        options.getString("audit_hash") ?: error("Missing fixture hash"),
                    ).toString()
                }
                finish(Activity.RESULT_OK, Bundle().apply { putString("report", report) })
                return
            }
            if (options.getString("hardware_virtualization_probe") == "true") {
                val report = HardwareVirtualizationProbe.run(targetContext)
                finish(Activity.RESULT_OK, Bundle().apply { putString("report", report) })
                return
            }
            options.getString("lease_busy")?.let { expected ->
                val busy = DiskLease.busy(targetContext.filesDir)
                check(busy == expected.toBooleanStrict()) { "Native/Java ownership mismatch: busy=$busy, expected=$expected" }
                finish(Activity.RESULT_OK, Bundle().apply { putString("report", "native_java_lease_busy=$busy") })
                return
            }
            if (!Python.isStarted()) Python.start(AndroidPlatform(targetContext))
            val result = Python.getInstance().getModule("iosvm.device_checks").callAttr(
                "run", targetContext.filesDir.absolutePath, targetContext.applicationInfo.nativeLibraryDir)
            val shared = java.io.File(targetContext.applicationInfo.nativeLibraryDir, "libqemu-system-aarch64-shared.so")
            check(QemuNative.load(shared.absolutePath) == null) { "JNI QEMU/context loading failed" }
            check(QemuNative.hasDisplay()) { "Native direct Surface display is missing" }
            if (options.getString("patch_probe") == "true") {
                Python.getInstance().getModule("iosvm.device_checks").callAttr(
                    "patch_boot_probe", targetContext.filesDir.absolutePath,
                    targetContext.applicationInfo.nativeLibraryDir)
            }
            if (options.getString("start_install") == "true") {
                targetContext.startForegroundService(Intent(targetContext, InstallService::class.java))
                val deadline = android.os.SystemClock.elapsedRealtime() + 15000
                while (!InstallService.running && android.os.SystemClock.elapsedRealtime() < deadline) Thread.sleep(50)
                check(InstallService.running) { "Installer service did not start" }
                // Keep the instrumentation alive until cancellation/finish so
                // Android does not terminate its instrumented app mid-restore.
                while (InstallService.running) Thread.sleep(1000)
            }
            if (options.getString("start_vm") == "true") {
                val id = targetContext.getSharedPreferences("ios_install", 0).getString("target_install", null)
                val install = id?.let { Installs.get(targetContext, it) }
                check(install != null && io.github.dylanneve1.iosonpixel.install.GuestRecord.ready(install.dir)) {
                    "A completed guest installation is required"
                }
                Installs.select(targetContext, install.id)
                VmService.start(targetContext, install)
                val started = android.os.SystemClock.elapsedRealtime() + 15000
                while (VmState.status == VmState.Status.STOPPED && android.os.SystemClock.elapsedRealtime() < started)
                    Thread.sleep(50)
                check(VmState.status != VmState.Status.STOPPED) { "VM service did not start: ${VmState.log()}" }
                targetContext.startActivity(Intent(targetContext, DisplayActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                val deadline = android.os.SystemClock.elapsedRealtime() + 30 * 60 * 1000
                while (VmState.status != VmState.Status.STOPPED && android.os.SystemClock.elapsedRealtime() < deadline)
                    Thread.sleep(1000)
                if (VmState.status != VmState.Status.STOPPED) {
                    VmService.stop(targetContext)
                    val stopped = android.os.SystemClock.elapsedRealtime() + 20000
                    while (VmState.status != VmState.Status.STOPPED && android.os.SystemClock.elapsedRealtime() < stopped)
                        Thread.sleep(100)
                }
            }
            finish(Activity.RESULT_OK, Bundle().apply { putString("report", result.toString()) })
        } catch (error: Throwable) {
            finish(Activity.RESULT_CANCELED, Bundle().apply { putString("failure", error.stackTraceToString()) })
        }
    }
}
