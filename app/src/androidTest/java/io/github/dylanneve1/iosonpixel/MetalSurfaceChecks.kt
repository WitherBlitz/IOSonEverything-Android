package io.github.dylanneve1.iosonpixel

import android.app.Instrumentation
import io.github.dylanneve1.iosonpixel.install.InstallService
import java.io.File
import java.io.RandomAccessFile
import org.json.JSONObject

/** Deliberate real-service refusal tests, restricted to the owned Metal installation. */
object MetalSurfaceChecks {
    fun run(instrumentation: Instrumentation, mode: String): String {
        require(mode in listOf("enable", "migrate-vnc", "corrupt", "cancel", "cpu-dev", "boot-smoke"))
        val ctx = instrumentation.targetContext
        check(VmState.status == VmState.Status.STOPPED)
        if (mode == "cpu-dev") {
            checkNotNull(DiskLease.acquire(ctx.filesDir)).close()
            val paths = AppPaths(ctx, Installs.DEVELOPER_ID).also { it.prepare() }
            val process = QemuInProcess(ctx, paths, listOf(paths.qemu.absolutePath, "--version"),
                ctx.filesDir.absolutePath, mapOf("TMPDIR" to paths.tmpDir.absolutePath))
            instrumentation.runOnMainSync { check(process.bind()) }
            val lines = mutableListOf<String>()
            val exit = process.pump { lines.add(it) }
            check(exit == 0) { "CPU developer Surface engine failed: exit=$exit, console=$lines" }
            checkNotNull(DiskLease.acquire(ctx.filesDir)).close()
            return JSONObject().put("mode", mode).put("exit", exit)
                .put("console", lines.joinToString("\n")).put("disk_ownership_released", true).toString()
        }
        val install = checkNotNull(Installs.forProfile(ctx, GuestProfile.IOS14_METAL))
        if (mode == "boot-smoke") {
            check(install.settings.inProcess)
            checkNotNull(DiskLease.acquire(ctx.filesDir)).close()
            Installs.select(ctx, install.id)
            VmService.start(ctx, install)
            var snapshot = ""
            try {
                val deadline = android.os.SystemClock.elapsedRealtime() + 120000
                while (android.os.SystemClock.elapsedRealtime() < deadline) {
                    snapshot = VmState.log()
                    if (snapshot.contains("METAL_VISIBLE_RESULT registered=true registration_only=true")) break
                    if (snapshot.contains("METAL_SURFACE verified;") && VmState.status == VmState.Status.STOPPED)
                        error("Surface VM exited before guest registration: $snapshot")
                    Thread.sleep(200)
                }
                check(snapshot.contains("METAL_VISIBLE_RESULT registered=true registration_only=true")) {
                    "Guest registration did not finish: $snapshot"
                }
                check(snapshot.contains("METAL_SURFACE verified;"))
            } finally {
                VmService.stop(ctx)
                val deadline = android.os.SystemClock.elapsedRealtime() + 30000
                while (VmState.status != VmState.Status.STOPPED && android.os.SystemClock.elapsedRealtime() < deadline)
                    Thread.sleep(100)
                check(VmState.status == VmState.Status.STOPPED) { "Surface VM did not stop" }
            }
            check(VmState.lastExit == 0) { "Surface shutdown exit=${VmState.lastExit}" }
            checkNotNull(DiskLease.acquire(ctx.filesDir)).close()
            return JSONObject().put("mode", mode).put("exit", VmState.lastExit)
                .put("guest_registered", true).put("visible_qualified", false)
                .put("console_tail", snapshot.takeLast(16000)).put("disk_ownership_released", true).toString()
        }
        val paths = AppPaths(ctx, install.id)
        val kernel = File(install.dir, "kernel")
        val savedTime = kernel.lastModified()
        var savedByte: Int? = null
        val lease = checkNotNull(DiskLease.acquire(ctx.filesDir)) { "A guest or file operation is still live" }
        lease.use {
            check(MetalGuestRecipe.ready(install.dir))
            Installs.update(ctx, install.copy(settings = install.settings.copy(
                inProcess = mode != "migrate-vnc", backend = Backend.QEMU)))
            if (mode == "corrupt") {
                RandomAccessFile(kernel, "rw").use { file ->
                    savedByte = file.readUnsignedByte()
                    file.seek(0)
                    file.writeByte(savedByte!! xor 1)
                }
                check(kernel.setLastModified(savedTime))
            }
        }
        if (mode == "enable" || mode == "migrate-vnc") {
            // Exercise the same startup reconciliation as MainActivity. A mode
            // toggle which is silently undone on the next Open is not usable.
            check(InstallService.reconcile(ctx)) { "Startup reconciliation did not run" }
            val actual = checkNotNull(Installs.get(ctx, install.id))
            check(actual.settings.inProcess) { "Metal must always use direct Surface output" }
            val command = QemuCommand.build(paths, checkNotNull(MetalGuestRecipe.verifiedLayout(actual.dir)), actual.settings)
            check("-vnc" !in command && command[command.indexOf("-display") + 1] == "android")
            check(Installs.forProfile(ctx, GuestProfile.IOS14_GPU)?.settings?.inProcess != true) {
                "GLES must continue to use the child engine"
            }
            return JSONObject().put("mode", mode).put("install", install.id)
                .put("surface", actual.settings.inProcess).put("survived_startup_reconciliation", true)
                .put("vnc_arguments", false).toString()
        }

        val lines = mutableListOf<String>()
        var instance: QemuInProcess? = null
        var exit = -999
        try {
            val process = QemuInProcess(ctx, paths, listOf("unused-unverified-argv"), install.dir.absolutePath,
                mapOf("IOSVM_GPU_LIBRARY" to File(ctx.applicationInfo.nativeLibraryDir, "libios_gpu.so").absolutePath,
                    "TMPDIR" to paths.tmpDir.absolutePath))
            instance = process
            instrumentation.runOnMainSync { check(process.bind()) }
            exit = process.pump { line ->
                synchronized(lines) { lines.add(line) }
                if (mode == "cancel" && line.startsWith("METAL_SURFACE verifying")) process.stop()
            }
            check(exit != 0) { "Refused startup unexpectedly returned success" }
            check(lines.any { it.startsWith("METAL_SURFACE verifying") }) { "Service verifier was not exercised: $lines" }
            check(lines.none { it.startsWith("METAL_SURFACE verified;") }) { "Native engine was permitted after refusal: $lines" }
            check(lines.none { it.contains("QEMU ") }) { "Unexpected native engine output: $lines" }
        } finally {
            if (instance?.isAlive == true) instance.stop()
            val deadline = android.os.SystemClock.elapsedRealtime() + 15000
            var restoreLease: DiskLease? = null
            while (restoreLease == null && android.os.SystemClock.elapsedRealtime() < deadline) {
                restoreLease = DiskLease.acquire(ctx.filesDir)
                if (restoreLease == null) Thread.sleep(50)
            }
            checkNotNull(restoreLease) { "Service retained disk ownership after terminal pump" }.use {
                savedByte?.let { original ->
                    RandomAccessFile(kernel, "rw").use { it.writeByte(original) }
                    check(kernel.setLastModified(savedTime))
                    check(MetalLaunchIntegrity.verify(install.dir) { true }) { "Original kernel restoration failed verification" }
                }
            }
        }
        return JSONObject().put("mode", mode).put("install", install.id).put("exit", exit)
            .put("refused_before_native_load", true).put("disk_ownership_released", true)
            .put("kernel_restored", savedByte != null).put("console", lines.joinToString("\n")).toString()
    }
}
