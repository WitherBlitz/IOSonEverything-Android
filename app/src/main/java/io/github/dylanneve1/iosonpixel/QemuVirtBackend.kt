package io.github.dylanneve1.iosonpixel

import android.content.Context
import android.os.Looper
import io.github.dylanneve1.iosonpixel.rfb.RfbClient
import java.io.File
import java.util.concurrent.TimeUnit

/** Separate CPU-emulated virt board for the custom iOS16 kernel. */
class QemuVirtBackend(ctx: Context, private val install: Install,
    private val launch: VerifiedLaunch<VmBackend.Instance> = VerifiedLaunch()) : VmBackend {
    private val app = ctx.applicationContext
    private val paths = AppPaths(app, install.id)
    private val runtime = File(paths.qemuVirt.parentFile, "libios_coroutines.so")
    override val kind = Backend.QEMU

    override fun problems(): List<String> = buildList {
        if (install.profileId != GuestProfile.IOS16_5.id) add("Guest profile is not the iOS 16.5 virt recipe")
        if (install.backend != Backend.QEMU) add("The iOS 16.5 profile requires its QEMU virt engine")
        if (!GuestProfile.IOS16_5.ready(install.dir)) add("iOS 16.5 preparation receipt or boot files are incomplete")
        if (!paths.qemuVirt.isFile || !runtime.isFile) add("The iOS 16.5 CPU engine is missing")
        if (install.dir.absolutePath.contains(',')) add("Guest directory contains an unsupported comma")
        if (File(install.dir, "data.store").exists() && File(install.dir, "data.store").length() == 0L)
            add("The persistent data archive is empty")
    }

    override fun checks(): List<VmBackend.Check> = problems().map { VmBackend.Check(false, it) } +
        listOf(VmBackend.Check(true, "iOS 16.5 · custom XNU · CPU emulation", false),
            VmBackend.Check(GuestProfile.IOS16_5.qualified(install.dir),
                if (GuestProfile.IOS16_5.qualified(install.dir)) "Display, input and persistence verified"
                else "Experimental preparation; display, input and persistence qualification pending", false))

    override fun start(settings: VmSettings, log: (String) -> Unit): VmBackend.Instance? {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            log("error: iOS 16.5 immutable verification must run off the UI thread"); return null
        }
        val issues = problems()
        if (issues.isNotEmpty()) { issues.forEach { log("error: $it") }; return null }
        return try {
            launch.run(acquire = {
                DiskLease.acquire(app.filesDir).also {
                    if (it == null) log("error: a guest or file operation still owns the disks")
                }
            }, verify = { keepGoing ->
                log("Verifying iOS 16.5 immutable boot files…")
                Ios16LaunchIntegrity.verify(install.dir, keepGoing).also { verified ->
                    if (!verified) log(if (launch.cancelled) "iOS 16.5 start cancelled."
                        else "error: iOS 16.5 boot files failed full SHA-256 verification")
                }
            }, exec = { lease ->
            paths.prepare()
            val keymap = File(paths.dataDir, "keymaps/en-us")
            keymap.parentFile?.mkdirs()
            app.assets.open("qemu-data/keymaps/en-us").use { input -> keymap.outputStream().use { input.copyTo(it) } }
            for (socket in listOf(paths.vncSocket, paths.monitorSocket, paths.qmpSocket)) socket.delete()
            val persistent = GuestProfile.IOS16_5.hasPersistentArchive(install.dir)
            val command = QemuVirtCommand.build(paths.qemuVirt, install.dir, paths.runDir, paths.dataDir,
                settings, persistent)
            log("$ " + command.joinToString(" "))
            val process = ProcessBuilder(command).directory(install.dir).redirectErrorStream(true).apply {
                environment()["TMPDIR"] = paths.tmpDir.absolutePath
                environment()["LD_PRELOAD"] = runtime.absolutePath
                environment()["IOSVM_WRITER_LOCK"] = File(app.filesDir, "native-writer.lock").absolutePath
                environment()["IOSVM_WRITER_PARENT"] = android.os.Process.myPid().toString()
                // iOS16 requires its own validated EAGL ABI before the experimental GPU channel is enabled.
                environment().remove("IOSVM_GPU_LIBRARY")
            }.start()
            Instance(process, lease, persistent, log)
            })
        } catch (error: Exception) { log("error: iOS 16.5 engine start failed: $error"); null }
    }

    override fun openDisplay(listener: VmDisplay.Listener): VmDisplay = RfbClient(paths.vncSocket, listener)
    override fun openTouch(): VmTouch = QmpTouch(paths)
    override fun press(button: HardwareButton, holdMs: Int) {
        QemuVirtCommand.key(button)?.let { Monitor.press(paths, it, holdMs) }
    }

    private inner class Instance(private val process: Process, private val lease: DiskLease,
        private val saveOnStop: Boolean, private val log: (String) -> Unit) : VmBackend.Instance {
        @Volatile private var savedShutdown = false
        override val isAlive get() = process.isAlive
        override fun pump(onLine: (String) -> Unit): Int {
            try { VmConsole(paths.logFile).drain(process.inputStream) { line ->
                if (line.contains("IOSGPU_PERSISTENCE_STOP_SAVED")) savedShutdown = true
                onLine(line)
            } }
            catch (error: Exception) { onLine("error: guest console failed: $error") }
            finally { if (process.isAlive) stop(); process.waitFor(); lease.close() }
            return process.waitFor()
        }
        @Synchronized override fun stop() {
            if (!process.isAlive) return
            if (saveOnStop) {
                Monitor(paths).send("sendkey f11 2000")
                if (process.waitFor(30, TimeUnit.SECONDS)) {
                    if (!savedShutdown) log("Guest exited without confirming a saved shutdown.")
                    return
                }
                log("Saved shutdown was not confirmed within 30 seconds; stopping the guest. The previous committed archive is retained.")
            }
            Monitor(paths).send("quit")
            if (!process.waitFor(10, TimeUnit.SECONDS)) {
                process.destroy()
                if (!process.waitFor(5, TimeUnit.SECONDS)) process.destroyForcibly()
            }
        }
        override fun kill() = process.destroy()
    }
}
