package io.github.dylanneve1.iosonpixel

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.security.MessageDigest

class GuestProfileTest {
    @get:Rule val temporary = TemporaryFolder()
    @Test fun profileAssociationSurvivesPreferenceRoundTrip() {
        val raw = """[{"id":"2","name":"Renamed guest","internal_dir":"/private/ios-current",
            "shared_dir":"/shared/2","internal":true,"profile_id":"iphone11-18A5351d-cpu-v1","settings":{}}]"""
        val decoded = InstallMigration.decode(raw)!!
        val encoded = JSONArray(InstallMigration.encode(decoded)).getJSONObject(0)
        assertEquals("iphone11-18A5351d-cpu-v1", encoded.optString("profile_id"))
        assertEquals("2", encoded.getString("id"))
    }

    @Test fun profileResolutionKeepsExistingGeneratedIdentityAndGuestFiles() {
        val base = temporary.newFolder()
        val old = File(base, "ios-current").apply { mkdirs() }
        val newer = File(base, "ios16-current").apply { mkdirs() }
        File(old, "user-data").writeText("existing iOS14 data")
        File(newer, "user-data").writeText("separate iOS16 data")
        val one = install("2", old, null)
        val two = install("7", newer, "ios16.5-20F66-virt-cpu-v1")
        assertEquals("2", GuestProfile.IOS14.resolve(listOf(one, two), "2", base)?.id)
        assertEquals("7", GuestProfile.IOS16_5.resolve(listOf(one, two), "2", base)?.id)
        assertEquals("existing iOS14 data", File(old, "user-data").readText())
        assertEquals("separate iOS16 data", File(newer, "user-data").readText())
        assertEquals(setOf("ios-current", "ios16-current"), base.list()!!.toSet())
    }

    @Test fun stalePreferenceCannotAdoptAnotherProfilesGuest() {
        val base = temporary.newFolder()
        val other = install("2", File(base, "ios16-current"), "ios16.5-20F66-virt-cpu-v1")
        assertNull(GuestProfile.IOS14.resolve(listOf(other), "2", base))
    }

    @Test fun stalePreferenceCannotAdoptOtherProfilesUntaggedDirectory() {
        val base = temporary.newFolder()
        val other = install("2", File(base, "ios-current"), null)
        assertNull(GuestProfile.IOS16_5.resolve(listOf(other), "2", base))
    }

    @Test fun duplicateProfileAssociationsAreRejectedInsteadOfPickingArbitrarily() {
        val base = temporary.newFolder()
        val one = install("2", File(base, "ios-current"), "iphone11-18A5351d-cpu-v1")
        assertNull(GuestProfile.IOS14.resolve(listOf(one, one.copy(id = "3")), "2", base))
    }

    @Test fun installPreferenceOrPlaceholderFilesCannotMakeIos16Ready() {
        val dir = temporary.newFolder()
        for (name in listOf("Image", "payload.bin", "system.apfs")) File(dir, name).writeText("placeholder")
        assertFalse(GuestProfile.IOS16_5.ready(dir))
        receipt(dir)
        mutateReceipt(dir) { put("kernel_patches_verified", false) }
        assertFalse(GuestProfile.IOS16_5.ready(dir))
    }

    @Test fun preparedIos16IsExperimentalUntilAllQualificationChecksPass() {
        val dir = temporary.newFolder()
        receipt(dir)
        assertTrue(GuestProfile.IOS16_5.ready(dir, verifyHashes = true))
        assertFalse(GuestProfile.IOS16_5.qualified(dir))
        mutateReceipt(dir) { put("gui_boot_verified", true); put("input_verified", true) }
        assertFalse(GuestProfile.IOS16_5.qualified(dir))
        mutateReceipt(dir) { put("persistence_verified", true) }
        assertFalse(GuestProfile.IOS16_5.qualified(dir))
        dataReceipt(dir)
        assertTrue(GuestProfile.IOS16_5.qualified(dir))
    }

    @Test fun persistentReceiptRequiresItsActualMutableDisk() {
        val dir = temporary.newFolder()
        receipt(dir);dataReceipt(dir)
        assertTrue(GuestProfile.IOS16_5.hasPersistentArchive(dir))
        File(dir, "data.store").delete()
        assertFalse(GuestProfile.IOS16_5.ready(dir))
        assertFalse(GuestProfile.IOS16_5.hasPersistentArchive(dir))
    }

    @Test fun mutableArchiveWritesDoNotInvalidateInitialProvenanceHash() {
        val dir = temporary.newFolder()
        receipt(dir);dataReceipt(dir)
        File(dir, "data.store").writeText("updated guest data")
        assertTrue(GuestProfile.IOS16_5.ready(dir, verifyHashes = true))
        File(dir, "data.store").appendText("truncated identity changed")
        assertFalse(GuestProfile.IOS16_5.ready(dir))
    }

    @Test fun wrongProfileMissingAndEmptyFilesCannotMakeIos16Ready() {
        val dir = temporary.newFolder()
        receipt(dir)
        mutateReceipt(dir) { put("profile", "iphone11-18A5351d-cpu-v1") }
        assertFalse(GuestProfile.IOS16_5.ready(dir))
        receipt(dir)
        File(dir, "payload.bin").delete()
        assertFalse(GuestProfile.IOS16_5.ready(dir))
        receipt(dir)
        File(dir, "system.apfs").writeBytes(byteArrayOf())
        mutateReceipt(dir) { getJSONObject("files").getJSONObject("system.apfs").put("bytes", 0) }
        assertFalse(GuestProfile.IOS16_5.ready(dir))
    }

    @Test fun importHashVerificationRejectsSameSizeCorruption() {
        val dir = temporary.newFolder()
        receipt(dir)
        File(dir, "Image").writeText("broken kernel!")
        assertFalse(GuestProfile.IOS16_5.ready(dir, verifyHashes = true))
    }

    @Test fun switchingIsBlockedDuringEveryGuestOrDiskOperation() {
        assertTrue(GuestProfile.switchAllowed(false, false, false, false))
        assertFalse(GuestProfile.switchAllowed(true, false, false, false))
        assertFalse(GuestProfile.switchAllowed(false, true, false, false))
        assertFalse(GuestProfile.switchAllowed(false, false, true, false))
        assertFalse(GuestProfile.switchAllowed(false, false, false, true))
    }

    private fun install(id: String, dir: File, profile: String?) = Install(id, "Renamed guest", dir.path,
        "/external/$id", true, VmSettings(), profileId = profile)

    private fun receipt(dir: File) {
        val files = JSONObject()
        for (name in listOf("Image", "payload.bin", "system.apfs")) {
            val file = File(dir, name).apply { writeText("kernel fixture") }
            files.put(name, JSONObject().put("bytes", file.length()).put("sha256",
                MessageDigest.getInstance("SHA-256").digest(file.readBytes()).joinToString("") { "%02x".format(it) }))
        }
        File(dir, "installation.json").writeText(JSONObject().put("profile", "ios16.5-20F66-virt-cpu-v1")
            .put("schema_version", 1).put("prepared", true).put("kernel_patches_verified", true)
            .put("gui_boot_verified", false).put("input_verified", false).put("persistence_verified", false)
            .put("files", files).toString())
    }

    private fun mutateReceipt(dir: File, action: JSONObject.() -> Unit) {
        val path = File(dir, "installation.json")
        path.writeText(JSONObject(path.readText()).apply(action).toString())
    }

    private fun dataReceipt(dir: File) {
        val file = File(dir, "data.store").apply { writeText("initial guest data") }
        mutateReceipt(dir) { getJSONObject("files").put("data.store", JSONObject()
            .put("bytes", file.length()).put("mutable", true).put("sha256_is_initial_only", true)
            .put("sha256", "0".repeat(64))) }
    }
}
