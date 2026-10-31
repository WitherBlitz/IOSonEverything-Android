package io.github.dylanneve1.iosonpixel

import java.io.File
import java.io.InputStream
import java.io.OutputStream

/** Console draining shared by the two native QEMU execution modes. */
class VmConsole(
    private val file: File,
    private val maxBytes: Int = 1024 * 1024,
    private val maxLine: Int = 16384,
    private val open: (File) -> OutputStream = { it.outputStream() },
) {
    fun drain(input: InputStream, onLine: (String) -> Unit) {
        require(maxBytes >= 64 && maxLine > 0 && maxLine <= (maxBytes - 32) / 4)
        var log: OutputStream? = null
        var bytes = 0
        var logging = true
        fun notify(line: String) { try { onLine(line) } catch (_: Exception) { /* Keep draining the VM. */ } }
        fun disable(error: Exception) {
            logging = false
            try { log?.close() } catch (_: Exception) {}
            log = null
            notify("warning: guest disk logging disabled: ${error.javaClass.simpleName}")
        }
        try { log = open(file) } catch (error: Exception) { disable(error) }
        fun emit(text: String) {
            val raw = (text + "\n").toByteArray(Charsets.UTF_8)
            if (logging) try {
                if (bytes + raw.size > maxBytes) {
                    log?.close()
                    log = null
                    val previous = File(file.path + ".previous")
                    check(!previous.exists() || previous.delete()) { "Cannot remove previous guest log" }
                    check(file.renameTo(previous)) { "Cannot rotate guest log" }
                    log = open(file)
                    bytes = 0
                }
                log!!.write(raw)
                log!!.flush()
                bytes += raw.size
            } catch (error: Exception) { disable(error) }
            notify(text)
        }
        try {
            input.reader(Charsets.UTF_8).use { reader ->
                val chunk = CharArray(4096)
                val line = StringBuilder()
                var truncated = false
                fun finish() {
                    val text = line.toString().removeSuffix("\r") + if (truncated) " [line truncated]" else ""
                    emit(text)
                    line.setLength(0)
                    truncated = false
                }
                while (true) {
                    val count = reader.read(chunk)
                    if (count < 0) break
                    for (i in 0 until count) when {
                        chunk[i] == '\n' -> finish()
                        line.length < maxLine -> line.append(chunk[i])
                        else -> truncated = true
                    }
                }
                if (line.isNotEmpty() || truncated) finish()
            }
        } finally {
            try { log?.close() } catch (_: Exception) {}
        }
    }
}
