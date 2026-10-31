package io.github.dylanneve1.iosonpixel

import java.io.File
import java.security.MessageDigest
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import io.github.dylanneve1.iosonpixel.install.GuestRecord

class GuestRecordTest {
    @get:Rule val temporary = TemporaryFolder()

    private fun completed(directory: File) {
        directory.mkdirs()
        val files = JSONObject()
        for (name in listOf("root", "kernel", "dtb", "trustcache", "sep_rom", "sep_fw", "vm.properties",
            "firmware", "syscfg", "ctrl_bits", "nvram", "effaceable", "panic_log", "sep_nvram", "sep_ssc")) {
            File(directory, name).writeText("test fixture")
            files.put(name, 12)
        }
        File(directory, "installation.json").writeText(JSONObject()
            .put("profile", "iphone11-18A5351d-cpu-v1").put("restored", true).put("patched", true)
            .put("files", files).put("static_sha256", JSONObject().apply {
                for (name in listOf("kernel", "dtb", "trustcache", "sep_rom", "sep_fw"))
                    put(name, MessageDigest.getInstance("SHA-256").digest(File(directory, name).readBytes())
                        .joinToString("") { "%02x".format(it) })
            }).toString())
    }

    @Test fun crashBeforePreferenceAdoptionFindsCompleteCurrentGuest() {
        val base = temporary.newFolder()
        completed(File(base, "ios-current"))
        assertEquals(File(base, "ios-current"), GuestRecord.recover(base))
    }

    @Test fun crashBetweenPromotionRenamesRestoresRetainedPreviousGuest() {
        val base = temporary.newFolder()
        completed(File(base, "ios-current.previous"))
        assertEquals(File(base, "ios-current"), GuestRecord.recover(base))
        assertTrue(File(base, "ios-current/root").isFile)
    }

    @Test fun receiptCannotHideMissingGuestFile() {
        val base = temporary.newFolder()
        completed(base)
        File(base, "sep_fw").delete()
        assertFalse(GuestRecord.ready(base))
    }

    @Test fun sameSizeDamagedCurrentCannotDisplaceValidPrevious() {
        val base = temporary.newFolder()
        completed(File(base, "ios-current"))
        completed(File(base, "ios-current.previous"))
        File(base, "ios-current/kernel").writeText("bad! fixture")
        assertEquals(File(base, "ios-current"), GuestRecord.recover(base))
        assertEquals("test fixture", File(base, "ios-current/kernel").readText())
        assertTrue(base.listFiles()!!.any { it.name.startsWith("ios-damaged-") })
    }

    @Test fun missingDigestCannotBeAdopted() {
        val base = temporary.newFolder()
        completed(File(base, "ios-staging-123"))
        val receipt = File(base, "ios-staging-123/installation.json")
        receipt.writeText(JSONObject(receipt.readText()).apply { remove("static_sha256") }.toString())
        assertNull(GuestRecord.recover(base))
    }

    @Test fun movedGuestRemainsTheActiveInstallation() {
        val base = temporary.newFolder("private")
        val shared = temporary.newFolder("shared")
        completed(shared)
        assertEquals(shared, GuestRecord.recover(base, shared))
        assertFalse(File(base, "ios-current").exists())
    }
}
