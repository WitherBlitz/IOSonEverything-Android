package io.github.dylanneve1.iosonpixel

import io.github.dylanneve1.iosonpixel.rfb.RfbClient
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.File
import org.json.JSONObject

/** Feed actual client decoding without a socket; verify complete-frame callbacks. */
object RfbProtocolChecks {
    fun run(): String {
        var framePixels = IntArray(0)
        val events = mutableListOf<String>()
        val images = mutableListOf<List<Int>>()
        val listener = object : VmDisplay.Listener {
            override fun onResize(width: Int, height: Int, pixels: IntArray) {
                framePixels = pixels
                events += "resize:${width}x$height"
            }
            override fun onUpdate(x: Int, y: Int, w: Int, h: Int) {
                events += "update:$x,$y,$w,$h"
                images += framePixels.toList()
            }
            override fun onFrameComplete() { events += "complete" }
            override fun onDisconnected(error: Throwable?) {}
        }
        data class Rect(val x: Int, val y: Int, val w: Int, val h: Int, val encoding: Int = 0,
                        val colors: List<Int> = emptyList())
        fun packet(vararg rectangles: Rect): DataInputStream {
            val bytes = ByteArrayOutputStream()
            DataOutputStream(bytes).use { output ->
                output.writeByte(0); output.writeByte(0); output.writeShort(rectangles.size)
                for (r in rectangles) {
                    output.writeShort(r.x); output.writeShort(r.y); output.writeShort(r.w); output.writeShort(r.h)
                    output.writeInt(r.encoding)
                    for (p in r.colors) { output.writeByte(p); output.writeByte(p ushr 8); output.writeByte(p ushr 16); output.writeByte(0) }
                }
            }
            return DataInputStream(ByteArrayInputStream(bytes.toByteArray()))
        }
        val reply = ByteArrayOutputStream(); val output = DataOutputStream(reply)
        val client = RfbClient(File("unused-protocol-test.sock"), listener)
        val red = 0xffff0000.toInt(); val blue = 0xff0000ff.toInt()
        val green = 0xff00ff00.toInt(); val white = 0xffffffff.toInt(); val black = 0xff000000.toInt()
        try {
            client.readMessage(packet(Rect(0, 0, 4, 3, -223),
                Rect(0, 0, 1, 1, colors = listOf(red)), Rect(3, 2, 1, 1, colors = listOf(blue))), output)
            check(events == listOf("resize:4x3", "update:0,0,4,3", "complete")) { "Fragmented callbacks: $events" }
            check(images.single() == List(12) { when (it) { 0 -> red; 11 -> blue; else -> black } })

            events.clear(); images.clear()
            client.readMessage(packet(), output)
            check(events == listOf("complete") && images.isEmpty()) { "Empty update republished old damage" }

            events.clear()
            client.readMessage(packet(Rect(1, 1, 2, 1, colors = listOf(green, white))), output)
            check(events == listOf("update:1,1,2,1", "complete"))
            check(images.single() == List(12) { when (it) { 0 -> red; 11 -> blue; 5 -> green; 6 -> white; else -> black } })

            events.clear(); images.clear()
            client.readMessage(packet(Rect(0, 0, 1, 1, colors = listOf(green)), Rect(0, 0, 2, 2, -223),
                Rect(1, 1, 1, 1, colors = listOf(white))), output)
            check(events == listOf("resize:2x2", "update:1,1,1,1", "complete")) { "Resize callbacks: $events" }
            check(images.single() == listOf(black, black, black, white)) { "Obsolete framebuffer pixels survived resize" }
            check(reply.toByteArray().takeLast(10) == listOf<Byte>(3, 1, 0, 0, 0, 0, 0, 2, 0, 2))

            events.clear(); images.clear()
            var refused = false
            try { client.readMessage(packet(Rect(2, 0, 1, 1, colors = listOf(red))), output) }
            catch (_: IllegalArgumentException) { refused = true }
            check(refused && events.isEmpty() && framePixels.toList() == listOf(black, black, black, white))
            client.readMessage(packet(), output)
            check(events == listOf("complete") && images.isEmpty())
        } finally { client.close() }
        return JSONObject().put("passed", true).put("scope", "actual RfbClient decoder; no socket or physical window")
            .put("fragmented_callbacks", "one update after all pixels, then complete")
            .put("consecutive_empty_resize_bounds_requests", true).toString()
    }
}
