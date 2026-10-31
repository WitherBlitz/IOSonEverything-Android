package io.github.dylanneve1.iosonpixel

import java.io.Closeable
import java.io.File
import java.io.RandomAccessFile
import java.nio.channels.FileLock
import java.nio.channels.OverlappingFileLockException

/** Kernel-held ownership survives a main-process restart while the native VM still lives. */
class DiskLease private constructor(private val file: RandomAccessFile, private val lock: FileLock,
    private val key: String) : Closeable {
    private var closed = false
    override fun close() = synchronized(monitor) {
        if (!closed) {
            closed = true
            try { lock.release() } finally { try { file.close() } finally { owned.remove(key) } }
        }
    }
    companion object {
        private val monitor = Any()
        private val owned = mutableSetOf<String>()
        fun acquire(base: File): DiskLease? = synchronized(monitor) {
            val path = File(base, "native-vm-owner.lock")
            val key = path.canonicalPath
            // Closing a second descriptor can release this process's POSIX locks.
            // Keep one owning channel per file; do not even reopen it while locally held.
            if (key in owned) return null
            val file = RandomAccessFile(path, "rw")
            try {
                val lock = try { file.channel.tryLock() } catch (_: OverlappingFileLockException) { null }
                if (lock != null) {
                    val writerBusy = RandomAccessFile(File(base, "native-writer.lock"), "rw").use { writer ->
                        val probe = try { writer.channel.tryLock() } catch (_: OverlappingFileLockException) { null }
                        if (probe == null) true else { probe.release(); false }
                    }
                    if (!writerBusy) { owned.add(key); return DiskLease(file, lock, key) }
                    lock.release()
                }
            } catch (error: Exception) { file.close(); throw error }
            file.close()
            return null
        }
        fun busy(base: File): Boolean = acquire(base)?.let { it.close(); false } ?: true
    }
}

class VmStartGate {
    @Volatile private var cancelled = false
    @Synchronized fun start(action: () -> Unit): Boolean {
        if (cancelled) return false
        action()
        return true
    }
    @Synchronized fun cancel(action: () -> Unit) { cancelled = true; action() }
}
