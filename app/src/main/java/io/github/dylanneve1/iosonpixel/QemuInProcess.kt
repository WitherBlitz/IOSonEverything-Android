package io.github.dylanneve1.iosonpixel

import android.app.ActivityManager
import android.app.ApplicationExitInfo
import android.app.Service
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.content.pm.ApplicationInfo
import android.os.Binder
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.Parcel
import android.os.ParcelFileDescriptor
import android.os.Process
import android.system.Os
import android.util.Log
import android.view.Surface
import android.view.WindowManager
import android.system.OsConstants
import java.io.FileDescriptor
import java.io.FileOutputStream
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.system.exitProcess

/** The JNI shim in native/qemu_jni.c; used in the :vm process only. */
object QemuNative {
    init { System.loadLibrary("qemu_jni") }

    /** Loads QEMU from [lib]; returns null, or the dlopen/dlsym error. */
    @JvmStatic external fun load(lib: String): String?
    @JvmStatic external fun hasDisplay(): Boolean
    /** Runs qemu_android_main(); ends the process with QEMU's exit status. */
    @JvmStatic external fun run(argv: Array<String>, cwd: String)

    // -display android (ui/android.c); no-ops if the library lacks it.
    @JvmStatic external fun setSurface(surface: Surface?)
    @JvmStatic external fun touch(x: Int, y: Int, w: Int, h: Int, down: Boolean)
    @JvmStatic external fun key(name: String, down: Boolean)

    /** Called by the shim on QEMU's main loop when the guest framebuffer size changes. */
    @JvmStatic fun onResize(w: Int, h: Int) = QemuVmService.onResize(w, h)
}

/**
 * Hosts QEMU as a library in its own process (android:process=":vm"), the
 * in-process alternative to exec'ing it. One process runs one VM: QEMU calls
 * exit() when it is done, which ends this process; the app learns about it
 * from the console pipe closing and reads the status from the exit info.
 *
 * Bound (not started) by [QemuInProcess] from VmService, so it gets the
 * foreground service's priority, and given its arguments over the binder.
 * The display (-display android) also goes over the binder: the app's
 * Surface, touches and keys in, framebuffer size changes out.
 */
class QemuVmService : Service() {
    private var consoleOutput: FileOutputStream? = null
    private fun consoleLine(message: String) {
        consoleOutput?.apply {
            write((message + "\n").toByteArray(Charsets.UTF_8))
            flush()
        }
    }
    private val binder = object : Binder() {
        override fun onTransact(code: Int, data: Parcel, reply: Parcel?, flags: Int): Boolean {
            when (code) {
                TX_START -> {
                    val lib = data.readString()!!
                    val argv = data.createStringArray()!!
                    val cwd = data.readString()!!
                    val env = data.createStringArray()!!
                    val owner = data.readStrongBinder()!!
                    val monitor = data.readString()!!
                    val console = data.readFileDescriptor()
                    val installId = data.readString()!!
                    val accepted = start(lib, argv, cwd, env, console, owner, monitor, installId)
                    reply?.writeInt(if (accepted) Process.myPid() else 0)
                }
                TX_STOP -> requestStop()
                TX_SURFACE -> {
                    val surface = if (data.readInt() != 0) Surface.CREATOR.createFromParcel(data) else null
                    val size = setSurface(surface, data.readStrongBinder())
                    reply?.writeInt(size.first)
                    reply?.writeInt(size.second)
                }
                TX_TOUCH -> if (loaded) {
                    QemuNative.touch(data.readInt(), data.readInt(), data.readInt(), data.readInt(), data.readInt() != 0)
                }
                TX_KEY -> if (loaded) QemuNative.key(data.readString()!!, data.readInt() != 0)
                else -> return super.onTransact(code, data, reply, flags)
            }
            return true
        }
    }

    override fun onBind(intent: Intent?): IBinder = binder

    private var owner: IBinder? = null
    private val ownerDied = IBinder.DeathRecipient { requestStop() }
    private var monitor: File? = null
    private var diskLease: DiskLease? = null
    private val stopping = AtomicBoolean(false)
    private val gpuLaunch = VerifiedLaunch<List<String>>()

    /** A dead main process must not leave a guest owning disks behind a fresh UI. */
    @Synchronized private fun requestStop() {
        if (!stopping.compareAndSet(false, true)) return
        gpuLaunch.cancel { }
        if (!started) { Process.killProcess(Process.myPid()); return }
        Thread({
            monitor?.let { Monitor(it).send("quit") }
            // A wedged engine must also go away if its owner can no longer drain it.
            Thread.sleep(10000)
            Process.killProcess(Process.myPid())
        }, "qemu-owner-stop").start()
    }

    override fun onUnbind(intent: Intent?): Boolean { requestStop(); return false }
    override fun onDestroy() { requestStop(); super.onDestroy() }

    @Synchronized private fun start(lib: String, argv: Array<String>, cwd: String, env: Array<String>,
        console: ParcelFileDescriptor, owner: IBinder, monitor: String, installId: String): Boolean {
        if (started) { console.close(); return false }
        if (stopping.get()) { console.close(); return false }
        val lease = DiskLease.acquire(filesDir) ?: run { console.close(); return false }
        try { owner.linkToDeath(ownerDied, 0) }
        catch (error: Exception) { lease.close(); console.close(); throw error }
        diskLease = lease
        this.owner = owner
        this.monitor = File(monitor)
        started = true
        // QEMU's stdout/stderr (the guest serial console and error messages)
        // go to the pipe the app reads, as with the child process. stdin is a
        // pipe nobody writes to, which is also what the child process had.
        Os.dup2(console.fileDescriptor, 1)
        Os.dup2(console.fileDescriptor, 2)
        consoleOutput = ParcelFileDescriptor.AutoCloseOutputStream(ParcelFileDescriptor.dup(console.fileDescriptor))
        console.close()
        val stdin = Os.pipe()
        Os.dup2(stdin[0], 0)
        stdinWriter = stdin[1]
        for (i in env.indices step 2) Os.setenv(env[i], env[i + 1], true)

        // The main loop runs on this thread; give it a native-sized stack.
        Thread(null, {
            try {
                val current = Installs.get(this, installId)
                // Explicit debug CPU overrides intentionally use an unsaved installation.
                val developerCpu = installId == Installs.DEVELOPER_ID &&
                    (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0 &&
                    env.indices.step(2).none { env[it] == "IOSVM_GPU_LIBRARY" }
                check(current != null || developerCpu) { "The selected installation no longer exists" }
                val profile = GuestProfile.fromId(current?.profileId)
                val finalArgv = if (current != null && profile?.usesGpuRuntime == true) {
                    check(profile == GuestProfile.IOS14_METAL && current.settings.inProcess && current.backend == Backend.QEMU) {
                        "Surface profile settings changed: ${current.profileId}, inProcess=${current.settings.inProcess}, backend=${current.backend}"
                    }
                    val paths = AppPaths(this, installId)
                    check(File(cwd).canonicalFile == current.dir.canonicalFile &&
                        File(lib).canonicalFile == paths.qemuLib.canonicalFile) { "Surface engine or guest identity changed" }
                    check(current.settings.extraArgList.isEmpty() && QemuCommand.extraArgs(this).isEmpty()) {
                        "Extra arguments are unavailable for the managed Metal Surface recipe"
                    }
                    check(env.indices.step(2).any { env[it] == "IOSVM_GPU_LIBRARY" &&
                        env[it+1] == File(applicationInfo.nativeLibraryDir, "libios_gpu.so").absolutePath })
                    val result = gpuLaunch.run(acquire = { lease }, verify = { keepGoing ->
                        consoleLine("METAL_SURFACE verifying immutable guest files under service ownership")
                        GpuProfileChecks.problems(profile.id, current.dir, File(applicationInfo.nativeLibraryDir)).isEmpty() &&
                            MetalLaunchIntegrity.verify(current.dir) { keepGoing() && !stopping.get() }
                    }, exec = {
                        val layout = checkNotNull(MetalGuestRecipe.verifiedLayout(current.dir)) { "Metal recipe changed during verification" }
                        val bounds = getSystemService(WindowManager::class.java).maximumWindowMetrics.bounds
                        val resolution = if (DisplayPrefs.load(this).nativeResolution)
                            GuestResolution.fromScreen(bounds.width(), bounds.height()) else null
                        QemuCommand.build(paths, layout, current.settings, resolution)
                    })
                    checkNotNull(result) { "Metal Surface verification refused or cancelled; native engine was not loaded" }.toTypedArray()
                } else {
                    check(env.indices.step(2).none { env[it] == "IOSVM_GPU_LIBRARY" }) { "Unexpected GPU environment for this installation" }
                    argv
                }
                check(!stopping.get() && !gpuLaunch.cancelled) { "Surface startup cancelled before native load" }
                if (profile == GuestProfile.IOS14_METAL) consoleLine("METAL_SURFACE verified; loading packaged engine in separate :vm service")
                QemuNative.load(lib)?.let { err ->
                    FileOutputStream(FileDescriptor.err).use { it.write("error: cannot load QEMU from $lib: $err\n".toByteArray()) }
                    exitProcess(127)
                }
                synchronized(displayLock) {
                    loaded = true
                    surface?.let { QemuNative.setSurface(it) }
                }
                check(!stopping.get() && !gpuLaunch.cancelled) { "Surface startup cancelled before native run" }
                QemuNative.run(finalArgv, cwd)
            } catch (t: Throwable) {
                Log.e(TAG, "in-process QEMU failed", t)
                consoleLine("error: in-process QEMU: $t")
            }
            exitProcess(127)
        }, "qemu-main", 8L shl 20).start()
        return true
    }

    companion object {
        private const val TAG = "QemuVmService"
        const val TX_START = IBinder.FIRST_CALL_TRANSACTION
        const val TX_SURFACE = IBinder.FIRST_CALL_TRANSACTION + 1
        const val TX_TOUCH = IBinder.FIRST_CALL_TRANSACTION + 2
        const val TX_KEY = IBinder.FIRST_CALL_TRANSACTION + 3
        const val TX_STOP = IBinder.FIRST_CALL_TRANSACTION + 4
        /** Sent to the app's size listener. */
        const val TX_RESIZE = IBinder.FIRST_CALL_TRANSACTION

        private val displayLock = Any()
        @Volatile private var loaded = false
        private var surface: Surface? = null
        private var sizeListener: IBinder? = null
        private var width = 0
        private var height = 0

        /** Draw into [s] (null stops); returns the current framebuffer size. */
        private fun setSurface(s: Surface?, listener: IBinder?): Pair<Int, Int> = synchronized(displayLock) {
            val old = surface
            surface = s
            sizeListener = listener
            // Once this returns QEMU no longer touches the old window.
            if (loaded) QemuNative.setSurface(s)
            old?.release()
            width to height
        }

        fun onResize(w: Int, h: Int) {
            val listener = synchronized(displayLock) {
                width = w
                height = h
                sizeListener
            } ?: return
            val data = Parcel.obtain()
            try {
                data.writeInt(w)
                data.writeInt(h)
                listener.transact(TX_RESIZE, data, null, IBinder.FLAG_ONEWAY)
            } catch (_: Exception) {
            } finally {
                data.recycle()
            }
        }

        @Volatile private var started = false
        /** Write end of QEMU's stdin; kept open so stdin never reads EOF. */
        private var stdinWriter: FileDescriptor? = null
    }
}

/**
 * Main-process side: binds [QemuVmService] and turns its process into a
 * [VmBackend.Instance]. Its companion is the [SurfaceDisplay] for whichever
 * in-process VM is running, so the display can attach before or after start.
 */
class QemuInProcess(
    ctx: Context,
    private val paths: AppPaths,
    private val argv: List<String>,
    private val cwd: String,
    private val env: Map<String, String>,
) : VmBackend.Instance {
    private val app = ctx.applicationContext
    private val main = Handler(Looper.getMainLooper())
    private val connected = CountDownLatch(1)
    private val exited = CountDownLatch(1)
    private val nativeExited = CountDownLatch(1)
    private val owner = Binder()
    @Volatile private var binder: IBinder? = null
    @Volatile private var pid = 0
    @Volatile private var bound = false
    @Volatile private var startRequested = false
    private val startGate = VmStartGate()

    private val conn = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, service: IBinder) {
            // After QEMU exits the system restarts the bound service in a fresh
            // :vm process; that one is never sent START and goes away on unbind.
            if (binder == null) {
                binder = service
                try { service.linkToDeath({ nativeExited.countDown() }, 0) }
                catch (_: Exception) { nativeExited.countDown() }
            }
            connected.countDown()
        }

        override fun onServiceDisconnected(name: ComponentName?) = Unit
    }

    /** Binds the :vm service; must be called on the main thread. */
    fun bind(): Boolean {
        bound = app.bindService(
            Intent(app, QemuVmService::class.java), conn, Context.BIND_AUTO_CREATE or Context.BIND_IMPORTANT,
        )
        if (bound) current = this
        return bound
    }

    @Volatile private var started = false

    /** Receives framebuffer size changes from the :vm process. */
    private val sizeListener = object : Binder() {
        override fun onTransact(code: Int, data: Parcel, reply: Parcel?, flags: Int): Boolean {
            if (code != QemuVmService.TX_RESIZE) return super.onTransact(code, data, reply, flags)
            val w = data.readInt()
            val h = data.readInt()
            synchronized(Companion) { onSize }?.invoke(w, h)
            return true
        }
    }

    /** Sends the companion's current Surface to the :vm process (synchronously). */
    private fun sendSurface() {
        val b = binder ?: return
        if (!started) return
        val data = Parcel.obtain()
        val reply = Parcel.obtain()
        try {
            val (s, cb) = synchronized(Companion) { surface to onSize }
            if (s != null) {
                data.writeInt(1)
                s.writeToParcel(data, 0)
            } else {
                data.writeInt(0)
            }
            data.writeStrongBinder(if (s != null) sizeListener else null)
            b.transact(QemuVmService.TX_SURFACE, data, reply, 0)
            val w = reply.readInt()
            val h = reply.readInt()
            if (w > 0 && h > 0) cb?.invoke(w, h)
        } catch (_: Exception) {
            // The :vm process is gone; pump() reports that.
        } finally {
            data.recycle()
            reply.recycle()
        }
    }

    private fun send(code: Int, fill: (Parcel) -> Unit) {
        val b = binder ?: return
        if (!started) return
        val data = Parcel.obtain()
        try {
            fill(data)
            b.transact(code, data, null, IBinder.FLAG_ONEWAY)
        } catch (_: Exception) {
        } finally {
            data.recycle()
        }
    }

    override val isAlive get() = exited.count > 0

    override fun pump(onLine: (String) -> Unit): Int {
        var consoleRead: ParcelFileDescriptor? = null
        try {
            val b = binder ?: run {
                if (!connected.await(10, TimeUnit.SECONDS)) {
                    onLine("error: the :vm service did not start")
                    return -1
                }
                binder!!
            }
            val (read, write) = ParcelFileDescriptor.createPipe()
            consoleRead = read
            val data = Parcel.obtain()
            val reply = Parcel.obtain()
            try {
                data.writeString(paths.qemuLib.absolutePath)
                data.writeStringArray(argv.toTypedArray())
                data.writeString(cwd)
                data.writeStringArray(env.flatMap { listOf(it.key, it.value) }.toTypedArray())
                data.writeStrongBinder(owner)
                data.writeString(paths.monitorSocket.absolutePath)
                data.writeFileDescriptor(write.fileDescriptor)
                data.writeString(paths.installId)
                check(startGate.start {
                    startRequested = true
                    b.transact(QemuVmService.TX_START, data, reply, 0)
                    pid = reply.readInt()
                    check(pid > 0) { "The native service or a file operation still owns the guest disks" }
                }) { "VM start was cancelled" }
            } finally {
                data.recycle()
                reply.recycle()
                // Only the :vm process may hold the write end, so EOF means it exited.
                write.close()
            }
            started = true
            sendSurface()

            VmConsole(paths.logFile).drain(ParcelFileDescriptor.AutoCloseInputStream(read), onLine)
            ensureNativeExit()
            return exitStatus(onLine)
        } catch (e: Exception) {
            onLine("error: in-process QEMU: $e")
            return -1
        } finally {
            // A failed pipe/log/callback is not evidence that QEMU released its disks.
            ensureNativeExit()
            try { consoleRead?.close() } catch (_: Exception) {}
            if (current === this) current = null
            exited.countDown()
            unbind()
        }
    }

    /** QEMU's exit status, from the system's record of how the :vm process ended. */
    private fun exitStatus(onLine: (String) -> Unit): Int {
        val am = app.getSystemService(ActivityManager::class.java)
        repeat(20) {
            val info = am.getHistoricalProcessExitReasons(app.packageName, pid, 1).firstOrNull()
            if (info != null) {
                if (info.reason == ApplicationExitInfo.REASON_EXIT_SELF) return info.status
                val why = info.description?.takeIf { it.isNotBlank() } ?: when (info.reason) {
                    ApplicationExitInfo.REASON_SIGNALED -> "signal ${info.status}"
                    ApplicationExitInfo.REASON_LOW_MEMORY -> "killed for low memory"
                    ApplicationExitInfo.REASON_CRASH_NATIVE -> "native crash"
                    else -> "exit reason ${info.reason}"
                }
                onLine(":vm process ended: $why")
                // Like Process.waitFor() for a child killed by a signal.
                return if (info.reason == ApplicationExitInfo.REASON_SIGNALED) 128 + info.status else -1
            }
            Thread.sleep(100)
        }
        onLine(":vm process ended; no exit record found")
        return -1
    }

    override fun stop() {
        startGate.cancel { ensureNativeExit() }
    }

    override fun kill() {
        startGate.cancel {
            requestRemoteStop()
            if (pid != 0) Process.sendSignal(pid, OsConstants.SIGTERM)
        }
        // pump() unbinds only after binder death confirms native termination.
    }

    private fun requestRemoteStop() {
        val b = binder ?: return
        val data = Parcel.obtain()
        try { b.transact(QemuVmService.TX_STOP, data, null, IBinder.FLAG_ONEWAY) }
        catch (_: Exception) {}
        finally { data.recycle() }
    }

    private fun ensureNativeExit() {
        val b = binder ?: return
        if (!startRequested || !b.isBinderAlive) return
        requestRemoteStop()
        if (!nativeExited.await(10, TimeUnit.SECONDS) && pid != 0) Process.sendSignal(pid, OsConstants.SIGTERM)
        if (!nativeExited.await(5, TimeUnit.SECONDS) && pid != 0) Process.killProcess(pid)
        // Do not publish STOPPED if even the forced termination has not happened yet.
        while (b.isBinderAlive) Thread.sleep(50)
    }

    private fun unbind() {
        main.post {
            if (bound) {
                bound = false
                app.unbindService(conn)
            }
        }
    }

    /** The display of the running in-process VM; keeps the Surface across a VM (re)start. */
    companion object : SurfaceDisplay {
        @Volatile private var current: QemuInProcess? = null
        private var surface: Surface? = null
        private var onSize: ((Int, Int) -> Unit)? = null

        override fun setSurface(surface: Surface?, onSize: ((Int, Int) -> Unit)?) {
            synchronized(this) {
                this.surface = surface
                this.onSize = onSize
            }
            current?.sendSurface()
        }

        override fun touch(x: Int, y: Int, w: Int, h: Int, down: Boolean) {
            current?.send(QemuVmService.TX_TOUCH) {
                it.writeInt(x); it.writeInt(y); it.writeInt(w); it.writeInt(h); it.writeInt(if (down) 1 else 0)
            }
        }

        override fun key(name: String, down: Boolean) {
            current?.send(QemuVmService.TX_KEY) { it.writeString(name); it.writeInt(if (down) 1 else 0) }
        }
    }
}
