package io.github.dylanneve1.iosonpixel

import android.app.Instrumentation
import android.graphics.Bitmap
import android.os.SystemClock
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference
import org.json.JSONArray
import org.json.JSONObject

/** Actual normal VNC client and Bitmap copies; no physical-window claim. */
object RfbDeliveryChecks {
    fun run(instrumentation: Instrumentation): String {
        val ctx = instrumentation.targetContext
        check(VmState.status == VmState.Status.STOPPED)
        val install = checkNotNull(Installs.forProfile(ctx, GuestProfile.IOS14_METAL))
        check(!install.settings.inProcess)
        checkNotNull(DiskLease.acquire(ctx.filesDir)).close()
        Installs.select(ctx, install.id)
        val backend = VmBackend.create(ctx, install)
        val width = 1440; val height = 3120
        val frames = AtomicInteger(); val rectangles = AtomicInteger()
        val bitmapNs = AtomicLong()
        val contentReady = AtomicBoolean(); val modalVisible = AtomicBoolean()
        val failure = AtomicReference<Throwable?>()
        val changed = mutableListOf<Long>()
        val bitmapLock = Any()
        var decodedPixels = IntArray(0); var bitmap: Bitmap? = null; var previous: IntArray? = null
        val listener = object : VmDisplay.Listener {
            override fun onResize(width: Int, height: Int, pixels: IntArray) {
                check(width == 1440 && height == 3120) { "Expected native 1440 x 3120, got $width x $height" }
                synchronized(bitmapLock) {
                    bitmap?.recycle(); bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
                    decodedPixels = pixels
                }
            }
            override fun onUpdate(x: Int, y: Int, w: Int, h: Int) {
                val start = SystemClock.elapsedRealtimeNanos()
                synchronized(bitmapLock) { checkNotNull(bitmap).setPixels(decodedPixels, y * width + x, width, x, y, w, h) }
                bitmapNs.addAndGet(SystemClock.elapsedRealtimeNanos() - start)
                rectangles.incrementAndGet()
            }
            override fun onFrameComplete() {
                try {
                    val modal = decodedPixels[1676 * width + 680]
                    val red = (modal ushr 16) and 255; val green = (modal ushr 8) and 255; val blue = modal and 255
                    modalVisible.set(red < 140 && green in 80..200 && blue > 180)
                    val samples = IntArray(36 * 60); var index = 0
                    for (y in 360 until 2760 step 40) for (x in 0 until width step 40) {
                        val p = decodedPixels[y * width + x]
                        samples[index++] = (((p ushr 16) and 255) * 77 +
                            ((p ushr 8) and 255) * 150 + (p and 255) * 29) shr 8
                    }
                    if (samples.count { it >= 10 } > samples.size * 3 / 5) contentReady.set(true)
                    val now = SystemClock.elapsedRealtime()
                    synchronized(changed) {
                        previous?.let { before ->
                            if (samples.indices.count { kotlin.math.abs(samples[it] - before[it]) >= 18 } >= samples.size / 100)
                                changed.add(now)
                        }
                    }
                    previous = samples; frames.incrementAndGet()
                } catch (error: Throwable) { failure.compareAndSet(null, error) }
            }
            override fun onDisconnected(error: Throwable?) { if (error != null) failure.compareAndSet(null, error) }
        }
        val client = backend.openDisplay(listener)
        val touch = checkNotNull(backend.openTouch())
        fun event(type: VmTouch.Type, x: Int, y: Int) {
            check(touch.available) { "QMP multitouch is unavailable" }
            touch.send(listOf(VmTouch.Event(type, 0, 1, x * VmTouch.MAX / width, y * VmTouch.MAX / height)))
        }
        fun swipe(x1: Int, y1: Int, x2: Int, y2: Int) {
            event(VmTouch.Type.BEGIN, x1, y1)
            for (step in 1..24) {
                Thread.sleep(42)
                event(VmTouch.Type.UPDATE, x1 + (x2 - x1) * step / 24, y1 + (y2 - y1) * step / 24)
            }
            event(VmTouch.Type.END, x2, y2)
        }
        fun saveFrame(name: String) {
            failure.get()?.let { throw it }
            // Incremental RFB has no obligation to deliver an unchanged idle
            // screen. Save the latest delivered Bitmap without waiting for dirt.
            val small = synchronized(bitmapLock) { Bitmap.createScaledBitmap(checkNotNull(bitmap), 360, 780, false) }
            File(ctx.cacheDir, name).outputStream().use { small.compress(Bitmap.CompressFormat.PNG, 100, it) }
            small.recycle()
        }
        var gestureStart = 0L; var gestureEnd = 0L; var motionFrames = 0; var motionRects = 0; var motionBitmapNs = 0L
        try {
            VmService.start(ctx, install)
            client.start(); touch.start()
            val deadline = SystemClock.elapsedRealtime() + 90000
            while ((!contentReady.get() || !touch.available) && SystemClock.elapsedRealtime() < deadline && failure.get() == null) Thread.sleep(100)
            failure.get()?.let { throw it }
            check(contentReady.get() && touch.available) { "Guest did not reach RFB: ${VmState.log()}" }
            Thread.sleep(3000)
            saveFrame("rfb-delivery-locked.png")
            swipe(720, 3050, 720, 1600)
            val modalDeadline = SystemClock.elapsedRealtime() + 20000
            while (!modalVisible.get() && SystemClock.elapsedRealtime() < modalDeadline) Thread.sleep(100)
            check(modalVisible.get()) { "Expected beta alert did not arrive; motion context is unqualified" }
            Thread.sleep(1200)
            event(VmTouch.Type.BEGIN, 720, 1675); Thread.sleep(80); event(VmTouch.Type.END, 720, 1675)
            val tapDeadline = SystemClock.elapsedRealtime() + 5000
            while (modalVisible.get() && SystemClock.elapsedRealtime() < tapDeadline) Thread.sleep(50)
            check(!modalVisible.get()) { "QMP short tap did not dismiss the beta alert" }
            Thread.sleep(1000); saveFrame("rfb-delivery-home.png")
            swipe(1240, 1550, 180, 1550); Thread.sleep(3000)
            val beforeFrames = frames.get(); val beforeRects = rectangles.get(); val beforeNs = bitmapNs.get()
            gestureStart = SystemClock.elapsedRealtime()
            repeat(4) { index ->
                if (index % 2 == 0) swipe(1240, 1550, 180, 1550) else swipe(180, 1550, 1240, 1550)
                Thread.sleep(1000)
            }
            gestureEnd = SystemClock.elapsedRealtime()
            motionFrames = frames.get() - beforeFrames; motionRects = rectangles.get() - beforeRects; motionBitmapNs = bitmapNs.get() - beforeNs
            saveFrame("rfb-delivery-final.png")
            failure.get()?.let { throw it }
        } finally {
            touch.close(); client.close()
            VmService.stop(ctx)
            val deadline = SystemClock.elapsedRealtime() + 30000
            while (VmState.status != VmState.Status.STOPPED && SystemClock.elapsedRealtime() < deadline) Thread.sleep(100)
            File(ctx.cacheDir, "rfb-delivery-console.log").writeText(VmState.log())
        }
        check(VmState.status == VmState.Status.STOPPED && VmState.lastExit == 0) { "RFB normal stop failed" }
        checkNotNull(DiskLease.acquire(ctx.filesDir)).close()
        val seconds = ((gestureEnd - gestureStart + 999) / 1000).toInt()
        val counts = synchronized(changed) { (0 until seconds).map { second ->
            changed.count { it >= gestureStart + second * 1000 && it < minOf(gestureEnd, gestureStart + (second + 1) * 1000) }
        } }
        return JSONObject().put("actual_buffer_size", JSONArray(listOf(width, height)))
            .put("delivery", "Normal Android RFB decode and Bitmap copies; no physical window")
            .put("frames", frames.get()).put("rectangles", rectangles.get()).put("motion_interval_ms", gestureEnd - gestureStart)
            .put("motion_frames", motionFrames).put("motion_rectangles", motionRects).put("motion_bitmap_ms", motionBitmapNs / 1e6)
            .put("visible_change_samples_per_second", JSONArray(counts)).put("exit", VmState.lastExit)
            .put("disk_ownership_released", true).toString()
    }
}
