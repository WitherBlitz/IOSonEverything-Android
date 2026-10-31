package io.github.dylanneve1.iosonpixel

import android.app.Instrumentation
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.media.ImageReader
import android.os.Handler
import android.os.HandlerThread
import android.os.SystemClock
import java.io.File
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.atomic.AtomicBoolean
import org.json.JSONArray
import org.json.JSONObject

/** Real Android buffer-queue qualification; explicitly not physical-screen evidence. */
object SurfaceDeliveryChecks {
    fun run(instrumentation: Instrumentation): String {
        val ctx = instrumentation.targetContext
        check(VmState.status == VmState.Status.STOPPED)
        val install = checkNotNull(Installs.forProfile(ctx, GuestProfile.IOS14_METAL))
        check(install.settings.inProcess)
        checkNotNull(DiskLease.acquire(ctx.filesDir)).close()
        val width = 1440; val height = 3120
        val reader = ImageReader.newInstance(width, height, PixelFormat.RGBX_8888, 3)
        val thread = HandlerThread("surface-qualification-consumer").apply { start() }
        val frames = AtomicInteger()
        val contentReady = AtomicBoolean()
        val modalVisible = AtomicBoolean()
        val failure = AtomicReference<Throwable?>()
        val capture = AtomicReference<String?>()
        val delivered = mutableListOf<Long>()
        val changed = mutableListOf<Long>()
        var previous: IntArray? = null
        reader.setOnImageAvailableListener({ source ->
            try {
                source.acquireLatestImage()?.use { image ->
                    check(image.width == width && image.height == height)
                    val plane = image.planes[0]; val buffer = plane.buffer
                    // Blue Close label in the known expired-beta alert; wallpaper here is red.
                    val modalAt = 1676 * plane.rowStride + 680 * plane.pixelStride
                    val modalR = buffer.get(modalAt).toInt() and 255
                    val modalG = buffer.get(modalAt + 1).toInt() and 255
                    val modalB = buffer.get(modalAt + 2).toInt() and 255
                    modalVisible.set(modalR < 140 && modalG in 80..200 && modalB > 180)
                    val samples = IntArray(36 * 60)
                    var index = 0
                    for (y in 360 until 2760 step 40) for (x in 0 until width step 40) {
                        val at = y * plane.rowStride + x * plane.pixelStride
                        samples[index++] = ((buffer.get(at).toInt() and 255) * 77 +
                            (buffer.get(at + 1).toInt() and 255) * 150 +
                            (buffer.get(at + 2).toInt() and 255) * 29) shr 8
                    }
                    val now = SystemClock.elapsedRealtime()
                    if (samples.count { it >= 10 } > samples.size * 3 / 5) contentReady.set(true)
                    synchronized(delivered) {
                        delivered.add(now)
                        previous?.let { before ->
                            if (samples.indices.count { kotlin.math.abs(samples[it] - before[it]) >= 18 } >= samples.size / 100)
                                changed.add(now)
                        }
                    }
                    previous = samples
                    frames.incrementAndGet()
                    capture.getAndSet(null)?.let { name ->
                        val pixels = IntArray(360 * 780)
                        for (y in 0 until 780) for (x in 0 until 360) {
                            val at = y * 4 * plane.rowStride + x * 4 * plane.pixelStride
                            pixels[y * 360 + x] = (255 shl 24) or ((buffer.get(at).toInt() and 255) shl 16) or
                                ((buffer.get(at + 1).toInt() and 255) shl 8) or (buffer.get(at + 2).toInt() and 255)
                        }
                        val bitmap = Bitmap.createBitmap(pixels, 360, 780, Bitmap.Config.ARGB_8888)
                        File(ctx.cacheDir, name).outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
                        bitmap.recycle()
                    }
                }
            } catch (error: Throwable) { failure.compareAndSet(null, error) }
        }, Handler(thread.looper))
        fun swipe(x1: Int, y1: Int, x2: Int, y2: Int) {
            QemuInProcess.touch(x1, y1, width, height, true)
            for (step in 1..24) {
                Thread.sleep(42)
                QemuInProcess.touch(x1 + (x2 - x1) * step / 24, y1 + (y2 - y1) * step / 24, width, height, true)
            }
            QemuInProcess.touch(x2, y2, width, height, false)
        }
        fun tap(x: Int, y: Int) {
            QemuInProcess.touch(x, y, width, height, true); Thread.sleep(80)
            QemuInProcess.touch(x, y, width, height, false)
        }
        fun saveFrame(name: String) {
            capture.set(name)
            QemuInProcess.setSurface(reader.surface) { w, h -> check(w == width && h == height) }
            val deadline = SystemClock.elapsedRealtime() + 5000
            while (capture.get() != null && SystemClock.elapsedRealtime() < deadline && failure.get() == null) Thread.sleep(20)
            check(capture.get() == null) { "Surface snapshot was not delivered" }
        }
        var gestureStart = 0L; var gestureEnd = 0L
        try {
            Installs.select(ctx, install.id)
            QemuInProcess.setSurface(reader.surface) { w, h -> check(w == width && h == height) }
            VmService.start(ctx, install)
            val deadline = SystemClock.elapsedRealtime() + 90000
            while (!contentReady.get() && SystemClock.elapsedRealtime() < deadline && failure.get() == null) Thread.sleep(100)
            failure.get()?.let { throw it }
            check(contentReady.get()) { "Guest wallpaper did not reach the native Surface: ${VmState.log()}" }
            Thread.sleep(3000)
            saveFrame("surface-delivery-locked.png")
            swipe(720, 3050, 720, 1600)
            val modalDeadline = SystemClock.elapsedRealtime() + 20000
            while (!modalVisible.get() && SystemClock.elapsedRealtime() < modalDeadline) Thread.sleep(100)
            check(modalVisible.get()) { "Expected beta alert did not arrive; motion workload context is unqualified" }
            // The first rendered Close glyph can precede UIKit enabling interaction.
            Thread.sleep(1200)
            saveFrame("surface-delivery-before-tap.png")
            tap(720, 1675)
            val tapDeadline = SystemClock.elapsedRealtime() + 5000
            while (modalVisible.get() && SystemClock.elapsedRealtime() < tapDeadline) Thread.sleep(50)
            saveFrame("surface-delivery-after-tap.png")
            check(!modalVisible.get()) { "Short tap did not dismiss the actual iOS beta alert" }
            Thread.sleep(1000)
            saveFrame("surface-delivery-home.png")
            swipe(1240, 1550, 180, 1550)
            Thread.sleep(3000)
            gestureStart = SystemClock.elapsedRealtime()
            repeat(4) { index ->
                if (index % 2 == 0) swipe(1240, 1550, 180, 1550) else swipe(180, 1550, 1240, 1550)
                Thread.sleep(1000)
            }
            gestureEnd = SystemClock.elapsedRealtime()
            saveFrame("surface-delivery-final.png")
            Thread.sleep(1000)
            failure.get()?.let { throw it }
        } finally {
            QemuInProcess.setSurface(null, null)
            VmService.stop(ctx)
            val deadline = SystemClock.elapsedRealtime() + 30000
            while (VmState.status != VmState.Status.STOPPED && SystemClock.elapsedRealtime() < deadline) Thread.sleep(100)
            reader.close(); thread.quitSafely(); thread.join(5000)
        }
        check(VmState.status == VmState.Status.STOPPED && VmState.lastExit == 0) { "Surface normal stop failed" }
        checkNotNull(DiskLease.acquire(ctx.filesDir)).close()
        val seconds = ((gestureEnd - gestureStart + 999) / 1000).toInt()
        val counts = synchronized(delivered) { (0 until seconds).map { second ->
            changed.count { it >= gestureStart + second * 1000 && it < minOf(gestureEnd, gestureStart + (second + 1) * 1000) }
        } }
        return JSONObject().put("actual_buffer_size", JSONArray(listOf(width, height)))
            .put("delivery", "Android ImageReader Surface; physical screen remains unqualified")
            .put("frames", frames.get()).put("motion_interval_ms", gestureEnd - gestureStart)
            .put("visible_change_samples_per_second", JSONArray(counts)).put("exit", VmState.lastExit)
            .put("fresh_gles_metrics", JSONArray(VmState.log().lines().filter {
                it.startsWith("FRESH_GLES gfx:") || it.startsWith("FRESH_GLES redwood-gl: frame")
            }))
            .put("native_copy_metrics", JSONArray(VmState.log().lines().filter {
                it.startsWith("IOSGPU_COPY_PERF ")
            }))
            .put("native_display_metrics", JSONArray(VmState.log().lines().filter {
                it.startsWith("ANDROID_DISPLAY_PERF ")
            }))
            .put("disk_ownership_released", true).toString()
    }
}
