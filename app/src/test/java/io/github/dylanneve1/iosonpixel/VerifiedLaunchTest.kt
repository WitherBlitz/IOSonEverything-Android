package io.github.dylanneve1.iosonpixel

import java.io.Closeable
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class VerifiedLaunchTest {
    @get:Rule val temporary = TemporaryFolder()

    private class Resource : Closeable {
        var closes = 0
        override fun close() { closes++ }
    }

    private fun checkedThread(error: AtomicReference<Throwable?>, action: () -> Unit) = Thread {
        try { action() } catch (failure: Throwable) { error.compareAndSet(null, failure) }
    }

    @Test fun sameSizeCorruptionCannotReachExecDespiteValidMetadata() {
        val dir = fixture()
        File(dir, "Image").writeText("BROKEN fixture")
        assertTrue(GuestProfile.IOS16_5.ready(dir))
        val resource = Resource()
        var executed = false
        val result = VerifiedLaunch<String>().run({ resource },
            { keepGoing -> Ios16LaunchIntegrity.verify(dir, keepGoing) },
            { executed = true; "child" })
        assertNull(result)
        assertFalse(executed)
        assertEquals(1, resource.closes)
        assertFalse(Ios16LaunchIntegrity.verifiedForUi(dir))
    }

    @Test fun fullVerificationPrecedesExecWhileLeaseIsHeld() {
        val base = temporary.newFolder()
        val dir = fixture()
        val gate = VerifiedLaunch<String>()
        var ownership: DiskLease? = null
        val result = gate.run({ DiskLease.acquire(base) }, { keepGoing ->
            assertTrue(DiskLease.busy(base))
            Ios16LaunchIntegrity.verify(dir, keepGoing)
        }, { lease -> ownership = lease; assertTrue(DiskLease.busy(base)); "child" })
        assertEquals("child", result)
        assertTrue(Ios16LaunchIntegrity.verifiedForUi(dir))
        assertTrue(DiskLease.busy(base))
        ownership!!.close()
        assertFalse(DiskLease.busy(base))
    }

    @Test fun cancellationDuringVerificationNeverExecsAndReleasesLease() {
        val base = temporary.newFolder()
        val entered = CountDownLatch(1)
        val proceed = CountDownLatch(1)
        val gate = VerifiedLaunch<String>()
        var executed = false
        val error = AtomicReference<Throwable?>(null)
        val thread = checkedThread(error) { assertNull(gate.run({ DiskLease.acquire(base) }, { keepGoing ->
            entered.countDown(); check(proceed.await(3, TimeUnit.SECONDS)); keepGoing()
        }, { executed = true; "late child" })) }
        thread.start(); assertTrue(entered.await(3, TimeUnit.SECONDS))
        gate.cancel { fail("No child exists during hashing") }
        assertTrue(DiskLease.busy(base))
        proceed.countDown(); thread.join(3000)
        assertFalse(thread.isAlive); assertNull(error.get()); assertFalse(executed); assertFalse(DiskLease.busy(base))
    }

    @Test fun destroyDuringExecKillsPublishedChildWithoutEarlyLeaseRelease() {
        val entered = CountDownLatch(1)
        val proceed = CountDownLatch(1)
        val gate = VerifiedLaunch<String>()
        val resource = Resource()
        val killed = AtomicBoolean(false)
        val error = AtomicReference<Throwable?>(null)
        val worker = checkedThread(error) { assertEquals("child", gate.run({ resource }, { true }, {
            entered.countDown(); check(proceed.await(3, TimeUnit.SECONDS)); "child"
        })) }
        worker.start(); assertTrue(entered.await(3, TimeUnit.SECONDS))
        val destroy = checkedThread(error) { gate.cancel { assertEquals("child", it); killed.set(true) } }
        destroy.start(); proceed.countDown()
        worker.join(3000); destroy.join(3000)
        assertFalse(worker.isAlive || destroy.isAlive); assertNull(error.get()); assertTrue(killed.get())
        assertEquals(0, resource.closes) // Child pump owns it until actual process exit.
        resource.close(); assertEquals(1, resource.closes)
        assertNull(gate.run({ fail("Cancelled guard reacquired lease"); resource }, { true }, { "late" }))
    }

    @Test fun launchExceptionReleasesLeaseAndCancellationBeforeStartDoesNotAcquire() {
        val resource = Resource()
        val gate = VerifiedLaunch<String>()
        try { gate.run({ resource }, { true }, { error("exec failed") }); fail("Expected exec failure") }
        catch (expected: IllegalStateException) { assertEquals("exec failed", expected.message) }
        assertEquals(1, resource.closes)
        val cancelled = VerifiedLaunch<String>()
        cancelled.cancel { fail("No child") }
        assertNull(cancelled.run({ fail("Acquired after destroy"); resource }, { true }, { "late" }))
    }

    @Test fun cancellationWinsEvenWhenAnInFlightVerifierReturnsTrue() {
        val gate = VerifiedLaunch<String>()
        val resource = Resource()
        assertNull(gate.run({ resource }, {
            gate.cancel { fail("No child") }
            true // Deliberately stale successful verification cannot bypass cancellation.
        }, { fail("Exec after cancellation"); "late" }))
        assertEquals(1, resource.closes)
    }

    @Test fun failedReconciliationCannotAuthorizeUiAndChangedFilesInvalidateSuccess() {
        val dir = fixture()
        assertFalse(Ios16LaunchIntegrity.verifiedForUi(dir))
        assertTrue(Ios16LaunchIntegrity.verify(dir) { true })
        assertTrue(Ios16LaunchIntegrity.verifiedForUi(dir))
        File(dir, "Image").writeText("invalid fixture plus length")
        assertFalse(Ios16LaunchIntegrity.verifiedForUi(dir))
        Ios16LaunchIntegrity.record(dir, false)
        assertTrue(Ios16LaunchIntegrity.assessedForUi(dir))
        assertFalse(Ios16LaunchIntegrity.verifiedForUi(dir))
    }

    @Test fun cancellationInsideStreamingHashDoesNotMarkUiVerified() {
        val dir = fixture()
        File(dir, "system.apfs").writeBytes(ByteArray(1024 * 1024) { 7 })
        writeReceipt(dir)
        var polls = 0
        assertFalse(Ios16LaunchIntegrity.verify(dir) { ++polls < 8 })
        assertTrue(polls >= 8)
        assertFalse(Ios16LaunchIntegrity.verifiedForUi(dir))
    }

    @Test fun mutableArchiveChangesDoNotInvalidateVerifiedImmutableFilesForUi() {
        val dir = fixture()
        val archive = File(dir, "data.store").apply { writeText("initial") }
        val receipt = File(dir, "installation.json")
        val json = JSONObject(receipt.readText())
        json.getJSONObject("files").put("data.store", JSONObject().put("bytes", archive.length())
            .put("mutable", true).put("sha256_is_initial_only", true).put("sha256", "0".repeat(64)))
        receipt.writeText(json.toString())
        assertTrue(Ios16LaunchIntegrity.verify(dir) { true })
        archive.writeText("changed")
        archive.setLastModified(archive.lastModified() + 5000)
        assertTrue(Ios16LaunchIntegrity.verifiedForUi(dir))
        archive.appendText("invalid length")
        assertFalse(Ios16LaunchIntegrity.verifiedForUi(dir))
    }

    @Test fun cancelledRecheckDoesNotTurnPreviouslyVerifiedFilesIntoAUiFailure() {
        val dir = fixture()
        assertTrue(Ios16LaunchIntegrity.verify(dir) { true })
        assertFalse(Ios16LaunchIntegrity.verify(dir) { false })
        assertTrue(Ios16LaunchIntegrity.verifiedForUi(dir))
    }

    @Test fun unchangedUiFingerprintNeverReplacesFullHashAtTheNextLaunch() {
        val dir = fixture()
        assertTrue(Ios16LaunchIntegrity.verify(dir) { true })
        val image = File(dir, "Image")
        val originalTime = image.lastModified()
        image.writeText("BROKEN fixture")
        assertTrue(image.setLastModified(originalTime))
        assertTrue(Ios16LaunchIntegrity.verifiedForUi(dir)) // Same length/mtime is only a UI hint.
        val resource = Resource()
        assertNull(VerifiedLaunch<String>().run({ resource },
            { keepGoing -> Ios16LaunchIntegrity.verify(dir, keepGoing) },
            { fail("Cached metadata authorized corrupt bytes"); "child" }))
        assertEquals(1, resource.closes)
        assertFalse(Ios16LaunchIntegrity.verifiedForUi(dir))
    }

    @Test fun verifierExceptionNullChildAndBusyLeaseCannotLeakOwnershipOrExec() {
        val resource = Resource()
        try {
            VerifiedLaunch<String>().run({ resource }, { error("read failed") }, { fail("Exec after read failure"); "child" })
            fail("Expected read failure")
        } catch (expected: IllegalStateException) { assertEquals("read failed", expected.message) }
        assertEquals(1, resource.closes)
        val second = Resource()
        assertNull(VerifiedLaunch<String>().run({ second }, { true }, { null }))
        assertEquals(1, second.closes)
        assertNull(VerifiedLaunch<String>().run<Resource>({ null },
            { fail("Verification without ownership"); true }, { fail("Exec without ownership"); "child" }))
    }

    private fun fixture(): File = temporary.newFolder().also { dir ->
        listOf("Image", "payload.bin", "system.apfs").forEach { File(dir, it).writeText("kernel fixture") }
        writeReceipt(dir)
    }

    private fun writeReceipt(dir: File) {
        val files = JSONObject()
        listOf("Image", "payload.bin", "system.apfs").forEach { name ->
            val file = File(dir, name)
            files.put(name, JSONObject().put("bytes", file.length()).put("sha256",
                MessageDigest.getInstance("SHA-256").digest(file.readBytes()).joinToString("") { "%02x".format(it) }))
        }
        File(dir, "installation.json").writeText(JSONObject().put("schema_version", 1)
            .put("profile", GuestProfile.IOS16_5.id).put("prepared", true)
            .put("kernel_patches_verified", true).put("files", files).toString())
    }
}
