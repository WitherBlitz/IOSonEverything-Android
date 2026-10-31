package io.github.dylanneve1.iosonpixel

import android.content.Context
import android.content.pm.ApplicationInfo
import android.os.Looper
import android.view.WindowManager
import io.github.dylanneve1.iosonpixel.rfb.RfbClient
import java.io.File
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * Software emulation: our Inferno build runs as a child process (or, with
 * [VmSettings.inProcess], as a library in the :vm process, see
 * [QemuInProcess]), its display is QEMU's VNC server on a unix socket (read
 * by [RfbClient]), the buttons go through the human monitor ([Monitor]) and
 * multi-touch goes through QMP ([QmpTouch]).
 */
class QemuBackend(ctx: Context, private val install: Install,
    private val launch: VerifiedLaunch<VmBackend.Instance> = VerifiedLaunch()) : VmBackend {
    private val app = ctx.applicationContext
    private val paths = AppPaths(app, install.id)
    private val dir get() = install.dir

    override val kind = Backend.QEMU

    private val inProcess get() = install.settings.inProcess
    private val contextLibrary get() = File(paths.qemu.parentFile, "libios_coroutines.so")
    private val libOk get() = paths.qemuLib.isFile && paths.qemuJni.isFile && contextLibrary.isFile
    private val profile get() = GuestProfile.fromId(install.profileId)
    private val gpu get() = profile?.usesGpuRuntime == true
    private val metal get() = profile == GuestProfile.IOS14_METAL
    private fun gpuProblems() = GpuProfileChecks.problems(install.profileId, dir, File(app.applicationInfo.nativeLibraryDir)) +
        listOfNotNull(GpuEnginePolicy.problem(profile, inProcess, install.backend, false))

    override fun checks(): List<VmBackend.Check> {
        val vm = VmLayout(dir)
        val problems = vm.problems()
        val qemuOk = paths.qemu.isFile
        return buildList {
            add(
                if (inProcess) {
                    if (libOk) VmBackend.Check(true, "QEMU library bundled (in-process)")
                    else VmBackend.Check(false, "QEMU library for in-process mode missing (run native/build-android.sh)")
                } else if (qemuOk) VmBackend.Check(true, "QEMU binary bundled")
                else VmBackend.Check(false, "QEMU binary missing (run native/build-android.sh)"),
            )
            if (problems.isEmpty()) add(VmBackend.Check(true, "VM folder looks complete"))
            else problems.forEach { add(VmBackend.Check(false, it)) }
            vm.ramdisk?.takeIf { it.isFile }?.let { add(VmBackend.Check(true, "ramdisk ${it.name} (passed as -initrd)")) }
            gpuProblems().forEach { add(VmBackend.Check(false, it)) }
        }
    }

    override fun problems(): List<String> = VmLayout(dir).problems() + gpuProblems() + listOfNotNull(
        if (inProcess) "QEMU library for in-process mode not bundled in this build".takeIf { !libOk }
        else "QEMU binary not bundled in this build".takeIf { !paths.qemu.isFile },
    )

    override fun start(settings: VmSettings, log: (String) -> Unit): VmBackend.Instance? {
        val graphicsProblems = gpuProblems()
        if (graphicsProblems.isNotEmpty()) { graphicsProblems.forEach { log("error: $it") }; return null }
        GpuEnginePolicy.problem(profile, settings.inProcess, install.backend,
            Looper.myLooper() == Looper.getMainLooper())?.let { log("error: $it"); return null }
        if (DiskLease.busy(app.filesDir)) {
            log("error: the previous guest or file operation still owns the disks")
            return null
        }
        val vm = VmLayout(dir)
        paths.prepare()
        installDataFiles()
        paths.vncSocket.delete()
        paths.monitorSocket.delete()
        paths.qmpSocket.delete()

        val extra = QemuCommand.extraArgs(app)
        val resolution = if (metal && DisplayPrefs.load(app).nativeResolution) {
            val bounds = app.getSystemService(WindowManager::class.java).maximumWindowMetrics.bounds
            GuestResolution.fromScreen(bounds.width(), bounds.height()).also {
                log(if (it != null) "Native guest display: " + it.width + "x" + it.height
                    else "Phone resolution is outside the guest display bounds; using standard resolution")
            }
        } else null
        if (metal && (settings.extraArgList.isNotEmpty() || extra.isNotEmpty())) {
            log("error: Extra QEMU arguments are unavailable for the managed Metal recipe")
            return null
        }
        if (extra.isNotEmpty()) log("debug: ${extra.size} extra QEMU args appended from files/qemu-extra-args.txt")
        fun command(layout: VmLayout) = (QemuCommand.build(paths, layout, settings, resolution) +
            settings.extraArgList + extra).also { log("$ " + it.joinToString(" ")) }

        if (settings.inProcess) {
            val cmd = command(vm)
            val env = buildMap {
                put("TMPDIR", paths.tmpDir.absolutePath)
                if (gpu) {
                    put("IOSVM_GPU_LIBRARY", File(paths.qemu.parentFile, "libios_gpu.so").absolutePath)
                    if ((app.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0 &&
                        File(app.filesDir, "gpu-profile-enabled").isFile) put("IOSVM_GPU_PROFILE", "1")
                }
                if (settings.effectiveVcpuAffinity.isNotBlank()) put("QEMU_VCPU_AFFINITY", settings.effectiveVcpuAffinity)
            }
            val vmProcess = QemuInProcess(app, paths, cmd, vm.dir.absolutePath, env)
            if (vmProcess.bind()) return vmProcess
            log("error: failed to start QEMU: cannot bind the :vm service")
            return null
        }

        fun process(layout: VmLayout): Process {
            val pb = ProcessBuilder(command(layout)).directory(layout.dir).redirectErrorStream(true)
            pb.environment()["TMPDIR"] = paths.tmpDir.absolutePath
            pb.environment()["LD_PRELOAD"] = contextLibrary.absolutePath
            if (gpu) {
                pb.environment()["IOSVM_GPU_LIBRARY"] = File(paths.qemu.parentFile, "libios_gpu.so").absolutePath
                if ((app.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0 &&
                    File(app.filesDir, "gpu-profile-enabled").isFile) pb.environment()["IOSVM_GPU_PROFILE"] = "1"
                else pb.environment().remove("IOSVM_GPU_PROFILE")
            } else pb.environment().remove("IOSVM_GPU_LIBRARY")
            pb.environment()["IOSVM_WRITER_LOCK"] = File(app.filesDir, "native-writer.lock").absolutePath
            pb.environment()["IOSVM_WRITER_PARENT"] = android.os.Process.myPid().toString()
            if (settings.effectiveVcpuAffinity.isNotBlank()) {
                pb.environment()["QEMU_VCPU_AFFINITY"] = settings.effectiveVcpuAffinity
            }
            return pb.start()
        }

        return try {
            launch.run(acquire = {
                DiskLease.acquire(app.filesDir).also {
                    if (it == null) log("error: a file operation acquired the guest disks before startup")
                }
            }, verify = { keepGoing ->
                if (!gpu) true else {
                    log("Verifying GPU guest immutable boot files…")
                    val integrity = if (metal) MetalLaunchIntegrity else GpuLaunchIntegrity
                    integrity.verify(dir, keepGoing).also {
                        if (!it) log(if (launch.cancelled) "GPU guest start cancelled."
                            else "error: GPU guest boot files failed full SHA-256 verification")
                    }
                }
            }, exec = { lease ->
                val finalLayout = if (metal) checkNotNull(MetalGuestRecipe.verifiedLayout(dir)) {
                    "Metal recipe changed before launch"
                } else vm
                Instance(process(finalLayout), lease)
            })
        } catch (e: Exception) {
            log("error: failed to start QEMU: $e")
            null
        }
    }

    override fun openDisplay(listener: VmDisplay.Listener): VmDisplay {
        check(!metal) { "Metal display uses the direct Android Surface" }
        return RfbClient(paths.vncSocket, listener)
    }

    override fun openTouch(): VmTouch = QmpTouch(paths)

    /** In-process the VM draws into the app's Surface (-display android); the child process uses VNC. */
    override fun surfaceDisplay(): SurfaceDisplay? = if (inProcess || metal) QemuInProcess else null

    override fun press(button: HardwareButton, holdMs: Int) {
        if (!inProcess) return Monitor.press(paths, key(button), holdMs)
        // Through QEMU's input layer, like the monitor's sendkey with a hold time.
        keys.execute {
            QemuInProcess.key(key(button), true)
            Thread.sleep(holdMs.toLong())
            QemuInProcess.key(key(button), false)
        }
    }

    /** Inferno maps the buttons to F-keys (see its "Using the Device's Buttons"). */
    private fun key(button: HardwareButton) = when (button) {
        HardwareButton.POWER -> "f5"
        HardwareButton.HOME -> "f6"
        HardwareButton.VOLUME_DOWN -> "f3"
        HardwareButton.VOLUME_UP -> "f4"
        HardwareButton.RINGER -> "f2"
    }

    private inner class Instance(private val p: Process, private val lease: DiskLease) : VmBackend.Instance {
        override val isAlive get() = p.isAlive

        override fun pump(onLine: (String) -> Unit): Int {
            try {
                VmConsole(paths.logFile).drain(p.inputStream, onLine)
            } catch (error: Exception) {
                onLine("error: guest console failed: $error")
                stop()
            } finally {
                // Console EOF/failure must not release the disk guard while the process lives.
                if (p.isAlive) stop()
                p.waitFor()
                lease.close()
            }
            return p.waitFor()
        }

        override fun stop() {
            // Ask QEMU to quit cleanly first so disk images are flushed.
            Monitor(paths).send("quit")
            if (!p.waitFor(10, TimeUnit.SECONDS)) {
                p.destroy()
                if (!p.waitFor(5, TimeUnit.SECONDS)) p.destroyForcibly()
            }
        }

        override fun kill() = p.destroy()
    }

    /** Copies keymaps etc. from assets so QEMU's -L data dir is populated. */
    private fun installDataFiles() {
        val assets = app.assets
        fun copy(assetPath: String, dest: File) {
            val children = assets.list(assetPath).orEmpty()
            if (children.isEmpty()) {
                dest.parentFile?.mkdirs()
                assets.open(assetPath).use { input -> dest.outputStream().use { input.copyTo(it) } }
            } else {
                children.forEach { copy("$assetPath/$it", File(dest, it)) }
            }
        }
        if (assets.list("qemu-data").orEmpty().isNotEmpty()) copy("qemu-data", paths.dataDir)
    }

    private companion object {
        /** Presses in order, one at a time (Apps is two Home presses). */
        val keys: ExecutorService = Executors.newSingleThreadExecutor()
    }
}

object QemuCommand {
    /**
     * Debug hook: whitespace-separated tokens from files/qemu-extra-args.txt (no quoting, no
     * comments), appended to the command line. Debuggable builds only; release builds ignore it.
     */
    fun extraArgs(ctx: Context): List<String> {
        if ((ctx.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) == 0) return emptyList()
        val f = File(ctx.filesDir, "qemu-extra-args.txt")
        if (!f.isFile) return emptyList()
        return runCatching { f.readText().split(Regex("\\s+")).filter { it.isNotEmpty() } }.getOrDefault(emptyList())
    }

    /** Mirrors the sample command from the Inferno guide, minus host-only display flags. */
    fun build(paths: AppPaths, vm: VmLayout, s: VmSettings, resolution: GuestResolution? = null): List<String> {
        fun path(key: String) = vm.file(key)!!.absolutePath
        val machine = (listOf(
            "t8030",
            "trustcache=${path("trustcache")}",
            "sep-fw=${path("sep_fw")}",
            "sep-rom=${path("sep_rom")}",
            "kaslr-off=true",
            // Connect out over a unix socket (retried quietly while nothing
            // listens) instead of the default TCP server, which needs INTERNET.
            "usb-uplink-type=inferno",
            "usb-uplink-addr=unix:${paths.usbUplinkSocket.absolutePath}",
        ) + listOfNotNull(vm.bootMode?.let { "boot-mode=$it" }) +
            (resolution?.machineOptions() ?: emptyList())).joinToString(",")

        val accel = buildString {
            append("tcg,thread=multi,tb-size=").append(s.tbSizeMb)
            if (s.splitWx) append(",split-wx=on")
        }

        // In-process the VM draws into the app's Surface; the child process serves VNC.
        val display = if (s.inProcess) listOf("-display", "android")
        else listOf("-display", "none", "-vnc", "unix:${paths.vncSocket.absolutePath}")

        val args = mutableListOf(
            paths.qemu.absolutePath,
            "-L", paths.dataDir.absolutePath,
            "-M", machine,
            "-accel", accel,
            "-kernel", path("kernel"),
            "-dtb", path("dtb"),
        )
        // Optional restore ramdisk; without the key the command is unchanged.
        vm.ramdisk?.takeIf { it.isFile }?.let { args += listOf("-initrd", it.absolutePath) }
        args += listOf(
            "-append", "tlto_us=-1 mtxspin=-1 agm-genuine=1 agm-authentic=1 agm-trusted=1 " +
                "serial=3 wdt=-1 -vm_compressor_wk_sw",
            "-smp", s.smp.toString(),
            "-m", "${s.ramGb}G",
            *display.toTypedArray(),
            "-monitor", "unix:${paths.monitorSocket.absolutePath},server=on,wait=off",
            "-qmp", "unix:${paths.qmpSocket.absolutePath},server=on,wait=off",
            "-serial", "stdio",
            // Shared storage is FUSE-backed; OFD locks there are unreliable.
            "-drive", "file=sep_nvram,if=pflash,format=raw,file.locking=off",
            "-drive", "file=sep_ssc,if=pflash,format=raw,file.locking=off",
        )

        fun nvme(id: String, file: String, format: String, device: String, nsid: Int, nstype: Int, extra: String = "") {
            args += listOf(
                "-drive", "file=$file,format=$format,if=none,id=$id,file.locking=off$extra",
                // Inferno dev looks namespaces up by id (e.g. peripheral/firmware).
                "-device", "$device,drive=$id,bus=nvme-bus.0,nsid=$nsid,nstype=$nstype,id=$id," +
                    "logical_block_size=4096,physical_block_size=4096",
            )
        }
        // Let guest TRIM (NVMe deallocate) and zero writes free qcow2 clusters, so the
        // image can shrink again (#56). If the host file system can't punch holes
        // (possibly shared storage's FUSE layer), QEMU just keeps the space.
        val reclaim = if (vm.rootFormat == "qcow2") ",discard=unmap,detect-zeroes=unmap" else ""
        nvme("root", vm.file("root")!!.name, vm.rootFormat, "nvme-ns", 1, 1, reclaim)
        for (ns in VmLayout.SMALL_DISKS) nvme(ns.name, ns.name, "raw", ns.device, ns.nsid, ns.nstype)
        return args
    }
}
