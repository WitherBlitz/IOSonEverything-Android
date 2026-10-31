package io.github.dylanneve1.iosonpixel

import io.github.dylanneve1.iosonpixel.install.GuestRecord
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.security.MessageDigest

class GpuGuestProfileTest {
    @get:Rule val temporary = TemporaryFolder()
    private val gpuId = "iphone11-18A5351d-gles-v1"
    private fun gpu(): GuestProfile {
        val profile = GuestProfile.entries.singleOrNull { it.id == gpuId }
        assertNotNull("A separate prepared GPU profile must exist", profile)
        return profile!!
    }

    @Test fun gpuHasSeparateIdentityAndKnownChildProcessDefaults() {
        val profile = gpu()
        assertEquals("ios14-gpu-lab", profile.directoryName)
        assertEquals("ios14_gpu_install", profile.preferenceName)
        assertFalse(profile.installationEnabled)
        assertEquals(3, profile.defaultSettings.ramGb)
        assertEquals(4, profile.defaultSettings.smp)
        assertFalse(profile.defaultSettings.inProcess)
        assertEquals(GuestProfile.entries.size, GuestProfile.entries.map { it.id }.toSet().size)
        assertEquals(GuestProfile.entries.size, GuestProfile.entries.map { it.directoryName }.toSet().size)
        assertTrue(GuestProfile.IOS14.defaultSettings.inProcess)
        assertFalse(GuestProfile.IOS16_5.defaultSettings.inProcess)
    }

    @Test fun gpuReadinessRequiresMatchingRecipeAndOptInMarker() {
        val profile = gpu(); val directory = temporary.newFolder()
        fixture(directory, GuestProfile.IOS14.id)
        File(directory, "gpu-lab-enabled").writeText("enabled")
        assertFalse(profile.ready(directory, true))
        fixture(directory, gpuId)
        assertTrue(profile.ready(directory, true))
        assertFalse(GuestProfile.IOS14.ready(directory, true))
        File(directory, "gpu-lab-enabled").delete()
        assertFalse(profile.ready(directory, true))
    }

    @Test fun gpuAdoptionRejectsSameSizeImmutableCorruption() {
        val profile = gpu(); val directory = temporary.newFolder()
        fixture(directory, gpuId); File(directory, "gpu-lab-enabled").writeText("enabled")
        assertTrue(profile.ready(directory, true))
        File(directory, "kernel").writeText("bad")
        assertFalse(profile.ready(directory, true))
    }

    @Test fun staleGpuPreferenceCannotAdoptCpuDirectoryOrViceVersa() {
        val profile = gpu(); val base = temporary.newFolder()
        val cpu = install("2", File(base, "ios-current"), null)
        val accelerated = install("4", File(base, profile.directoryName), null)
        assertNull(profile.resolve(listOf(cpu), "2", base))
        assertNull(GuestProfile.IOS14.resolve(listOf(accelerated), "4", base))
        assertEquals("4", profile.resolve(listOf(cpu, accelerated), "2", base)?.id)
    }

    @Test fun cpuRecoveryNeverPromotesGpuRecipe() {
        gpu(); val base = temporary.newFolder(); val current = File(base, "ios-current").apply { mkdirs() }
        fixture(current, gpuId); File(current, "gpu-lab-enabled").writeText("enabled")
        assertNull(GuestRecord.recover(base, current))
        assertTrue(current.isDirectory)
        assertEquals(setOf("ios-current"), base.list()!!.toSet())
    }

    @Test fun registeringGpuPreservesCpuAndIos16SelectionSettingsAndFiles() {
        val profile = gpu(); val base = temporary.newFolder(); val shared = temporary.newFolder()
        val cpu = install("2", File(base, "ios-current"), GuestProfile.IOS14.id)
        val other = install("3", File(base, "ios16-current"), GuestProfile.IOS16_5.id)
            .copy(name = "My iOS16", settings = VmSettings(ramGb = 4, smp = 2, inProcess = false))
        File(base, "sentinel").writeText("preserve")
        val plan = Installs.planProfileRegistration(listOf(cpu, other), "3", 4, profile, "2", base, shared)
        assertEquals("3", plan.currentId)
        assertEquals(cpu, plan.installs[0]); assertEquals(other, plan.installs[1])
        assertEquals("4", plan.target.id); assertEquals(gpuId, plan.target.profileId)
        assertEquals(File(base, "ios14-gpu-lab"), plan.target.dir)
        assertEquals("preserve", File(base, "sentinel").readText())
    }

    @Test fun gpuLaunchRequiresAllBundledRuntimeLibraries() {
        val directory = temporary.newFolder(); fixture(directory, gpuId)
        File(directory, "gpu-lab-enabled").writeText("enabled")
        val libraries = temporary.newFolder()
        val names = listOf("libios_gpu.so", "libios_gpu_worker.so", "libgfxstream_backend.so", "libc++.so")
        assertEquals(4, GpuProfileChecks.problems(gpuId, directory, libraries).size)
        names.forEach { File(libraries, it).writeText("runtime") }
        assertTrue(GpuProfileChecks.problems(gpuId, directory, libraries).isEmpty())
        for (name in names) {
            File(libraries, name).writeText("")
            assertEquals(listOf("Required GPU runtime is missing: $name"),
                GpuProfileChecks.problems(gpuId, directory, libraries))
            File(libraries, name).writeText("runtime")
        }
    }

    @Test fun cpuProfilesDoNotRequireGraphicsLibrariesOrMarker() {
        val directory = temporary.newFolder(); val libraries = temporary.newFolder()
        for (id in listOf(null, GuestProfile.IOS14.id, GuestProfile.IOS16_5.id))
            assertTrue(GpuProfileChecks.problems(id, directory, libraries).isEmpty())
    }

    @Test fun gpuOptInMarkerIsBoundedAndMustBeAFile() {
        val profile = gpu(); val directory = temporary.newFolder(); fixture(directory, gpuId)
        val marker = File(directory, "gpu-lab-enabled")
        marker.writeText(""); assertFalse(profile.ready(directory))
        marker.writeText("x".repeat(257)); assertFalse(profile.ready(directory))
        marker.delete(); marker.mkdir(); assertFalse(profile.ready(directory))
    }

    @Test fun genericFolderImportCannotReplaceManagedGraphicsOrIos16Profiles() {
        assertTrue(GuestProfile.IOS14.supportsFolderImport)
        assertFalse(GuestProfile.IOS16_5.supportsFolderImport)
        assertFalse(gpu().supportsFolderImport)
    }

    @Test fun cachedGpuAssessmentCannotAuthorizeSameSizeCorruptBytesAtExec() {
        val profile = gpu(); val directory = temporary.newFolder(); fixture(directory, gpuId)
        File(directory, "gpu-lab-enabled").writeText("enabled")
        assertTrue(GpuLaunchIntegrity.verify(directory) { true })
        assertTrue(profile.verifiedForUi(directory))
        val kernel = File(directory, "kernel"); val stamp = kernel.lastModified()
        kernel.writeText("bad"); assertTrue(kernel.setLastModified(stamp))
        assertTrue(profile.ready(directory))
        assertTrue(profile.verifiedForUi(directory)) // Metadata is only a UI hint.
        val base = temporary.newFolder(); var executed = false
        val result = VerifiedLaunch<String>().run({ DiskLease.acquire(base) }, { keepGoing ->
            assertTrue(DiskLease.busy(base))
            GpuLaunchIntegrity.verify(directory, keepGoing)
        }, { executed = true; "child" })
        assertNull(result); assertFalse(executed); assertFalse(DiskLease.busy(base))
        assertTrue(profile.assessedForUi(directory)); assertFalse(profile.verifiedForUi(directory))
    }

    @Test fun cancelledGpuRecheckRetainsPreviousUiAssessment() {
        val profile = gpu(); val directory = temporary.newFolder(); fixture(directory, gpuId)
        File(directory, "gpu-lab-enabled").writeText("enabled")
        assertTrue(GpuLaunchIntegrity.verify(directory) { true })
        var polls = 0
        assertFalse(GpuLaunchIntegrity.verify(directory) { ++polls < 5 })
        assertTrue(polls >= 5); assertTrue(profile.verifiedForUi(directory))
        File(directory, "gpu-lab-enabled").delete()
        assertFalse(profile.verifiedForUi(directory)); assertFalse(profile.ready(directory))
    }

    @Test fun guestDiskWritesDoNotInvalidateImmutableGpuAssessment() {
        val directory = temporary.newFolder(); fixture(directory, gpuId)
        File(directory, "gpu-lab-enabled").writeText("enabled")
        assertTrue(GpuLaunchIntegrity.verify(directory) { true })
        File(directory, "root").writeText("xyz")
        assertTrue(GpuLaunchIntegrity.verifiedForUi(directory))
        assertTrue(GpuLaunchIntegrity.verify(directory) { true })
    }

    private fun install(id: String, directory: File, profile: String?) =
        Install(id, "Guest", directory.path, "/external/$id", true, VmSettings(), profileId = profile)

    private fun fixture(directory: File, profile: String) {
        val required = listOf("root", "kernel", "dtb", "trustcache", "sep_rom", "sep_fw", "vm.properties",
            "firmware", "syscfg", "ctrl_bits", "nvram", "effaceable", "panic_log", "sep_nvram", "sep_ssc")
        val files = JSONObject(); val hashes = JSONObject()
        for (name in required) {
            val file = File(directory, name).apply { writeText("abc") }
            files.put(name, file.length())
            hashes.put(name, MessageDigest.getInstance("SHA-256").digest(file.readBytes()).joinToString("") { "%02x".format(it) })
        }
        File(directory, "installation.json").writeText(JSONObject().put("profile", profile)
            .put("restored", true).put("patched", true).put("files", files).put("static_sha256", hashes).toString())
    }
}
