package io.github.dylanneve1.iosonpixel

import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.io.File
import java.io.RandomAccessFile
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class DiskLeaseTest {
    @get:Rule val temporary = TemporaryFolder()

    @Test fun nativeLeaseBlocksMutationsUntilActualRelease() {
        val base = temporary.newFolder()
        val native = DiskLease.acquire(base)!!
        try {
            assertNull(DiskLease.acquire(base))
            assertTrue(DiskLease.busy(base))
        } finally { native.close() }
        DiskLease.acquire(base).use { assertNotNull(it) }
        assertFalse(DiskLease.busy(base))
    }

    @Test fun survivingExecutableWriterBlocksNewMainProcessOwnership() {
        val base = temporary.newFolder()
        RandomAccessFile(File(base, "native-writer.lock"), "rw").use { writer ->
            writer.channel.lock().use {
                assertNull(DiskLease.acquire(base))
                assertTrue(DiskLease.busy(base))
            }
        }
        DiskLease.acquire(base).use { assertNotNull(it) }
    }

    @Test fun stopDuringStartCannotBeLostBeforeNativePublication() {
        val gate = VmStartGate()
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        var nativeStarted = false
        var nativeStopped = false
        val start = Thread { gate.start {
            entered.countDown()
            check(release.await(3, TimeUnit.SECONDS))
            nativeStarted = true
        } }
        start.start()
        assertTrue(entered.await(3, TimeUnit.SECONDS))
        val stop = Thread { gate.cancel { nativeStopped = nativeStarted } }
        stop.start()
        // cancel must serialize with the in-flight start, never observe a half-published VM.
        stop.join(100)
        release.countDown()
        start.join(3000); stop.join(3000)
        assertFalse(start.isAlive || stop.isAlive)
        assertTrue(nativeStopped)
        assertFalse(gate.start { fail("Cancelled gate restarted a guest") })
    }
}
