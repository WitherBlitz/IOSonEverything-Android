package io.github.dylanneve1.iosonpixel.install

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.ServiceInfo
import android.os.IBinder
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import io.github.dylanneve1.iosonpixel.*
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

/** Owns the download, restore subprocess and wake lock across activity recreation. */
class InstallService : Service() {
    private var profile = GuestProfile.IOS14
    private val cancelled = AtomicBoolean(false)
    private var wake: PowerManager.WakeLock? = null
    private var lastUpdate = 0L
    private var latestStartId = 0
    private var preparationId = ""
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        latestStartId = startId
        if (intent?.action == CANCEL) {
            cancelled.set(true)
            if (!running) stopSelf()
            return START_NOT_STICKY
        }
        if (running) return START_NOT_STICKY
        val requested = intent?.getStringExtra("guest_profile")
        profile = GuestProfile.fromId(requested) ?: GuestProfile.IOS14
        val internal16Qualification = profile == GuestProfile.IOS16_5 &&
            (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0 &&
            intent?.getBooleanExtra(INTERNAL_IOS16_QUALIFICATION, false) == true
        if ((requested != null && GuestProfile.fromId(requested) == null) ||
            (!profile.installationEnabled && !internal16Qualification)) {
            update("Installation is not integrated for the requested guest profile.", -1.0)
            stopSelf()
            return START_NOT_STICKY
        }
        if (VmState.status != VmState.Status.STOPPED || ImportState.running) {
            update("Stop the guest or file operation before installing iOS.", -1.0)
            stopSelf()
            return START_NOT_STICKY
        }
        val lease = DiskLease.acquire(filesDir) ?: run {
            update("Wait for the previous guest or file operation to finish before installing iOS.", -1.0)
            stopSelf()
            return START_NOT_STICKY
        }
        val target = try {
            if (profile == GuestProfile.IOS16_5) Installs.ensureProfile(this, profile) else targetInstall(this)
        } catch (error: Exception) {
            lease.close(); update("Cannot save installation identity: ${error.message}", -1.0)
            stopSelf(); return START_NOT_STICKY
        }
        running = true
        cancelled.set(false)
        if (profile == GuestProfile.IOS16_5) {
            preparationId = intent?.getStringExtra(INTERNAL_PREPARATION_ID)
                ?.takeIf { it.matches(Regex("[0-9a-f-]{36}")) } ?: java.util.UUID.randomUUID().toString()
            getSharedPreferences(profile.preferenceName, MODE_PRIVATE).edit()
                .putString("preparation_attempt", preparationId).putBoolean("preparation_success", false)
                .putBoolean("preparation_complete", false).commit()
        }
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "iOS installation", NotificationManager.IMPORTANCE_LOW))
        startForeground(21, notification("Preparing installation"), ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        update("Checking downloaded firmware and preparing installation", -1.0)
        wake = getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "$packageName:install").apply { acquire(6 * 60 * 60 * 1000L) }
        Thread({
            try {
                check(VmState.status == VmState.Status.STOPPED) { "Stop the current guest before installing" }
                if (!Python.isStarted()) Python.start(AndroidPlatform(this))
                if (profile == GuestProfile.IOS16_5) {
                    val resources = File(filesDir, "ios16-installer-resources")
                    copyAssets("ios16-installer-resources", resources)
                    val prepared = Python.getInstance().getModule("iosvm.installer16").callAttr("install",
                        filesDir.absolutePath, applicationInfo.nativeLibraryDir, resources.absolutePath, this).toString()
                    val directory = File(filesDir, profile.directoryName)
                    check(File(prepared).canonicalFile == directory.canonicalFile) { "iOS16 promotion returned an unexpected directory" }
                    Installs.update(this, target.copy(internalDir = directory.absolutePath, internal = true,
                        settings = profile.defaultSettings, profileId = profile.id))
                    if (Installs.selectedProfile(this) == profile) Installs.select(this, target.id)
                    // The Python transaction streamed every immutable hash while this lease was held.
                    // This records UI assessment only; VM launch still hashes independently.
                    Ios16LaunchIntegrity.record(directory, true)
                    check(getSharedPreferences(profile.preferenceName, MODE_PRIVATE).edit()
                        .putBoolean("installed", true).putBoolean("preparation_success", true).commit())
                    update("Experimental iOS16 installation prepared. Device qualification is pending.", 1.0)
                } else {
                val resources = File(filesDir, "installer-resources")
                copyAssets("guest-tools", resources)
                copyAssets("qemu-data", File(resources, "qemu-data"))
                val module = Python.getInstance().getModule("iosvm.installer")
                module.callAttr("install", filesDir.absolutePath, applicationInfo.nativeLibraryDir,
                    resources.absolutePath, this)
                Installs.update(this, target.copy(
                    internalDir = File(filesDir, "ios-current").absolutePath,
                    internal = true,
                    settings = VmSettings(ramGb = 3, smp = 4, tbSizeMb = 256, vcpuAffinity = "", inProcess = true),
                ))
                Installs.select(this, target.id)
                getSharedPreferences("ios_install", MODE_PRIVATE).edit().putBoolean("installed", true).commit()
                update("Installation prepared. Open iOS to boot the guest.", 1.0)
                }
            } catch (error: Exception) {
                update(if (cancelled.get()) "Installation cancelled. Download progress is retained for retry."
                    else "Installation stopped: ${error.message}", -1.0)
            } finally {
                if (profile == GuestProfile.IOS16_5) getSharedPreferences(profile.preferenceName, MODE_PRIVATE)
                    .edit().putBoolean("preparation_complete", true).commit()
                Handler(Looper.getMainLooper()).post {
                    lease.close()
                    if (wake?.isHeld == true) wake?.release()
                    wake = null
                    stopForeground(STOP_FOREGROUND_REMOVE)
                    stopSelfResult(latestStartId)
                    running = false
                }
            }
        }, "ios-installer").start()
        return START_NOT_STICKY
    }

    /** Called from Python worker threads; updates are throttled to four per second. */
    @Synchronized fun update(message: String, fraction: Double) {
        val now = android.os.SystemClock.elapsedRealtime()
        if (now - lastUpdate < 250 && fraction in 0.0..<1.0) return
        lastUpdate = now
        getSharedPreferences(profile.preferenceName, MODE_PRIVATE).edit()
            .putString("message", message).putFloat("fraction", fraction.toFloat()).apply()
        val logs = File(filesDir, if (profile == GuestProfile.IOS16_5) "ios16-install-logs" else "ios-install-logs").apply { mkdirs() }
        File(logs, "status.txt").writeText(message)
        VmState.addLine("Installer: $message")
        getSystemService(NotificationManager::class.java).notify(21, notification(message))
    }

    fun isCancelled(): Boolean = cancelled.get()

    private fun copyAssets(source: String, destination: File) {
        val children = assets.list(source).orEmpty()
        if (children.isEmpty()) {
            destination.parentFile?.mkdirs()
            assets.open(source).use { input -> destination.outputStream().use { input.copyTo(it) } }
        } else {
            destination.mkdirs()
            children.forEach { copyAssets("$source/$it", File(destination, it)) }
        }
    }

    private fun notification(message: String): Notification = Notification.Builder(this, CHANNEL)
        .setSmallIcon(android.R.drawable.stat_sys_download)
        .setContentTitle("Installing iOS")
        .setContentText(message)
        .setOngoing(true)
        .setContentIntent(PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE))
        .addAction(Notification.Action.Builder(null, "Cancel", PendingIntent.getService(this, 1,
            Intent(this, InstallService::class.java).setAction(CANCEL), PendingIntent.FLAG_IMMUTABLE)).build())
        .build()

    override fun onDestroy() { cancelled.set(true); super.onDestroy() }

    companion object {
        const val CANCEL = "cancel-ios-install"
        const val INTERNAL_IOS16_QUALIFICATION = "internal_ios16_qualification"
        const val INTERNAL_PREPARATION_ID = "internal_ios16_preparation_id"
        private const val CHANNEL = "ios-install"
        @Volatile var running = false
            private set

        /** Stable identity survives process death, selection changes and adoption. */
        fun targetInstall(ctx: android.content.Context): Install {
            return Installs.ensureProfile(ctx, GuestProfile.IOS14)
        }

        fun reconcile(ctx: android.content.Context): Boolean {
            if (running || ImportState.running || VmState.status != VmState.Status.STOPPED) return false
            val lease = DiskLease.acquire(ctx.filesDir) ?: return false
            lease.use {
            // Normal startup never initializes Python. Only an interrupted16 transaction needs it.
            if (File(ctx.filesDir, "ios16-promotion.json").exists()) {
                if (!Python.isStarted()) Python.start(AndroidPlatform(ctx.applicationContext))
                Python.getInstance().getModule("iosvm.installer16").callAttr("recover", ctx.filesDir.absolutePath)
            }
            val selected = Installs.selectedProfile(ctx)
            val saved = ctx.getSharedPreferences("ios_install", MODE_PRIVATE).getString("target_install", null)
                ?.let { Installs.get(ctx, it) }
            val directory = GuestRecord.recover(ctx.filesDir, saved?.dir)
            if (directory == null) {
                val prefs = ctx.getSharedPreferences("ios_install", MODE_PRIVATE)
                if (prefs.getBoolean("installed", false)) prefs.edit().putBoolean("installed", false)
                    .putString("message", "Installed boot files failed verification. Retry installation to prepare them again.").commit()
            } else {
            val target = Installs.ensureProfile(ctx, GuestProfile.IOS14)
            if (target.dir.canonicalFile != directory.canonicalFile) {
                Installs.update(ctx, target.copy(internalDir = directory.absolutePath, internal = true,
                    settings = VmSettings(ramGb = 3, smp = 4, tbSizeMb = 256, vcpuAffinity = "", inProcess = true)))
            }
            check(ctx.getSharedPreferences("ios_install", MODE_PRIVATE).edit().putBoolean("installed", true).commit())
            }
            val next = GuestProfile.IOS16_5
            val nextDirectory = File(ctx.filesDir, next.directoryName)
            if (Ios16LaunchIntegrity.verify(nextDirectory) { true }) {
                val target = Installs.ensureProfile(ctx, next)
                if (target.dir.canonicalFile != nextDirectory.canonicalFile || target.settings.inProcess) {
                    Installs.update(ctx, target.copy(internalDir = nextDirectory.absolutePath, internal = true,
                        settings = next.defaultSettings, profileId = next.id))
                }
                check(ctx.getSharedPreferences(next.preferenceName, MODE_PRIVATE).edit().putBoolean("installed", true).commit())
            } else if (ctx.getSharedPreferences(next.preferenceName, MODE_PRIVATE).getBoolean("installed", false)) {
                ctx.getSharedPreferences(next.preferenceName, MODE_PRIVATE).edit().putBoolean("installed", false)
                    .putString("message", "iOS 16.5 boot files failed verification.").commit()
            }
            // Adopt only a separately prepared GPU recipe, in place. CPU recovery
            // and the CPU installer must never rename or promote this directory.
            for (graphics in listOf(GuestProfile.IOS14_GPU, GuestProfile.IOS14_METAL)) {
            val graphicsDirectory = File(ctx.filesDir, graphics.directoryName)
            val integrity = if (graphics == GuestProfile.IOS14_METAL) MetalLaunchIntegrity else GpuLaunchIntegrity
            if (integrity.verify(graphicsDirectory) { true }) {
                val target = Installs.ensureProfile(ctx, graphics)
                // Metal uses direct Surface output, including older saved
                // installations which selected the former VNC delivery path.
                val useSurface = graphics == GuestProfile.IOS14_METAL
                if (target.dir.canonicalFile != graphicsDirectory.canonicalFile || !target.internal || target.settings.inProcess != useSurface) {
                    Installs.update(ctx, target.copy(internalDir = graphicsDirectory.absolutePath, internal = true,
                        settings = target.settings.copy(inProcess = useSurface), profileId = graphics.id))
                }
                check(ctx.getSharedPreferences(graphics.preferenceName, MODE_PRIVATE).edit().putBoolean("installed", true).commit())
            } else {
                ctx.getSharedPreferences(graphics.preferenceName, MODE_PRIVATE).edit().putBoolean("installed", false).commit()
            }
            }
            // Adoption never switches away from the version chosen by the user.
            Installs.forProfile(ctx, selected)?.let { Installs.select(ctx, it.id) }
            }
            return true
        }
    }
}
