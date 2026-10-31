package io.github.dylanneve1.iosonpixel

import android.content.SharedPreferences
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.lang.reflect.Proxy

class InstallProfileRegistrationTest {
    @get:Rule val temporary = TemporaryFolder()

    private val customSettings = VmSettings(ramGb = 2, smp = 2, tbSizeMb = 512,
        splitWx = false, vcpuAffinity = "0,2", inProcess = false,
        security = Security.FULL, extraArgs = "custom=1", avfDisplay = true, avfNetwork = true)

    @Test fun creatingOtherProfileWhenSelectedProfileHasNoInstallKeepsSelectionInOneCommit() {
        val files = temporary.newFolder("files")
        val shared = temporary.newFolder("shared")
        val legacy = legacy(files, shared)
        assertNull(GuestProfile.IOS14.resolve(listOf(legacy), null, files))
        val editor = RecordingEditor(mapOf("current" to "1", "selected_profile" to GuestProfile.IOS14.id,
            "next_id" to 42, "list" to InstallMigration.encode(listOf(legacy))))

        val plan = Installs.planProfileRegistration(listOf(legacy), "1", 42, GuestProfile.IOS16_5,
            null, files, shared)
        assertTrue(plan.commitTo(editor.editor))

        assertTrue(plan.created)
        assertEquals("42", plan.target.id)
        assertEquals(GuestProfile.IOS16_5.defaultSettings, plan.target.settings)
        assertEquals(File(files, "ios16-current").absolutePath, plan.target.internalDir)
        assertEquals(1, editor.commits)
        assertEquals(0, editor.applies)
        assertEquals("1", editor.values["current"])
        assertEquals(GuestProfile.IOS14.id, editor.values["selected_profile"])
        assertEquals(43, editor.values["next_id"])
        val saved = InstallMigration.decode(editor.values["list"] as String)!!
        assertEquals(legacy, saved.first { it.id == "1" })
        assertNull(GuestProfile.IOS14.resolve(saved, null, files))
        assertEquals("42", GuestProfile.IOS16_5.resolve(saved, null, files)?.id)
    }

    @Test fun firstAdoptionOfOtherProfilePreservesExistingIdSettingsLocationAndSelection() {
        val files = temporary.newFolder("files")
        val shared = temporary.newFolder("shared")
        val legacy = legacy(files, shared)
        val existing = Install("9", "User renamed guest", File(files, "ios16-current").absolutePath,
            File(shared, "original-9").absolutePath, true, customSettings)
        val editor = RecordingEditor(mapOf("current" to "1", "selected_profile" to GuestProfile.IOS14.id,
            "next_id" to 41, "list" to InstallMigration.encode(listOf(legacy, existing))))

        val plan = Installs.planProfileRegistration(listOf(legacy, existing), "1", 41,
            GuestProfile.IOS16_5, null, files, shared)
        assertTrue(plan.commitTo(editor.editor))

        assertFalse(plan.created)
        assertEquals(existing.copy(profileId = GuestProfile.IOS16_5.id), plan.target)
        assertEquals("1", editor.values["current"])
        assertEquals(GuestProfile.IOS14.id, editor.values["selected_profile"])
        assertEquals(41, editor.values["next_id"])
        assertEquals(1, editor.commits)
        val saved = InstallMigration.decode(editor.values["list"] as String)!!
        assertEquals(2, saved.size)
        assertEquals(plan.target, saved.single { it.profileId == GuestProfile.IOS16_5.id })
        assertEquals(customSettings, saved.single { it.id == "9" }.settings)
        assertNull(GuestProfile.IOS14.resolve(saved, null, files))
    }

    @Test fun repeatRegistrationPreservesMissingCurrentPreferenceAndExistingSharedInstall() {
        val files = temporary.newFolder("files")
        val shared = temporary.newFolder("shared")
        val existing = Install("7", "Keep name", File(files, "custom").absolutePath,
            File(shared, "keep-shared").absolutePath, false, customSettings, profileId = GuestProfile.IOS16_5.id)
        val editor = RecordingEditor(mapOf("next_id" to 99, "list" to InstallMigration.encode(listOf(existing))))

        val plan = Installs.planProfileRegistration(listOf(existing), null, 99, GuestProfile.IOS16_5,
            "7", files, shared)
        assertTrue(plan.commitTo(editor.editor))

        assertFalse(plan.created)
        assertEquals(existing, plan.target)
        assertFalse(editor.values.containsKey("current"))
        assertEquals(99, editor.values["next_id"])
        assertEquals(listOf(existing), InstallMigration.decode(editor.values["list"] as String))
        assertEquals(1, editor.commits)
    }

    private fun legacy(files: File, shared: File) = Install("1", "Original VM",
        File(files, "vm").absolutePath, File(shared, "vm").absolutePath,
        true, customSettings.copy(inProcess = true), legacy = true)

    /** Real registration commit logic with a transaction-recording JVM Editor interface. */
    private class RecordingEditor(initial: Map<String, Any>) {
        val values = initial.toMutableMap()
        private val pending = mutableMapOf<String, Any?>()
        var commits = 0
        var applies = 0
        val editor = Proxy.newProxyInstance(SharedPreferences.Editor::class.java.classLoader,
            arrayOf(SharedPreferences.Editor::class.java)) { proxy, method, args ->
            when (method.name) {
                "putString", "putInt" -> { pending[args!![0] as String] = args[1]; proxy }
                "remove" -> { pending[args!![0] as String] = null; proxy }
                "commit" -> {
                    commits++
                    pending.forEach { (key, value) -> if (value == null) values.remove(key) else values[key] = value }
                    pending.clear()
                    true
                }
                "apply" -> { applies++; error("Profile registration must commit synchronously") }
                "toString" -> "RecordingEditor"
                else -> error("Unexpected preference editor call: ${method.name}")
            }
        } as SharedPreferences.Editor
    }
}
