package io.github.dylanneve1.iosonpixel

import java.io.File
import java.security.MessageDigest
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/** The experimental Metal guest must never borrow a CPU/GLES installation. */
class MetalGuestProfileTest {
    @get:Rule val temporary = TemporaryFolder()
    private fun metal(): GuestProfile {
        val profile = GuestProfile.fromId("iphone11-18A5351d-metal-v1")
        assertNotNull("Metal needs its own managed profile identity", profile)
        return profile!!
    }

    @Test fun metalHasAnIndependentDirectSurfaceRecipe() {
        val profile = metal()
        assertEquals("ios14-metal-lab", profile.directoryName)
        assertEquals("ios14_metal_install", profile.preferenceName)
        assertEquals(3, profile.defaultSettings.ramGb)
        assertEquals(4, profile.defaultSettings.smp)
        assertEquals(256, profile.defaultSettings.tbSizeMb)
        assertTrue(profile.defaultSettings.inProcess)
        assertEquals("", profile.defaultSettings.vcpuAffinity)
        assertEquals(GuestProfile.entries.size, GuestProfile.entries.map { it.id }.toSet().size)
        assertEquals(GuestProfile.entries.size, GuestProfile.entries.map { it.directoryName }.toSet().size)
        assertEquals(GuestProfile.entries.size, GuestProfile.entries.map { it.preferenceName }.toSet().size)
    }

    @Test fun genericInstallerAndFolderImportCannotTargetMetal() {
        val profile = metal()
        assertFalse(profile.installationEnabled)
        assertFalse(profile.supportsFolderImport)
        assertTrue(profile.requiresVerifiedLaunch)
    }

    @Test fun staleSelectionCannotAdoptCpuOrGlesDisks() {
        val profile = metal(); val base = temporary.newFolder()
        fun install(id: String, directory: String) = Install(id, directory,
            File(base, directory).path, File(base, "shared").path, true, VmSettings())
        val cpu = install("2", "ios-current")
        val gles = install("4", "ios14-gpu-lab")
        val candidate = install("5", "ios14-metal-lab")
        assertNull(profile.resolve(listOf(cpu, gles), "2", base))
        assertNull(GuestProfile.IOS14.resolve(listOf(candidate), "5", base))
        assertNull(GuestProfile.IOS14_GPU.resolve(listOf(candidate), "5", base))
        assertEquals("5", profile.resolve(listOf(cpu, gles, candidate), "2", base)?.id)
    }

    @Test fun qualifiedMetalRecipeHasIndependentReceiptAndMarker() {
        val directory = temporary.newFolder(); fixture(directory)
        assertTrue(metal().ready(directory, true))
        assertTrue(MetalLaunchIntegrity.verify(directory) { true })
        assertFalse(GuestProfile.IOS14.ready(directory))
        assertFalse(GuestProfile.IOS14_GPU.ready(directory))
        File(directory, "metal-lab-enabled").delete()
        File(directory, "gpu-lab-enabled").writeText("enabled")
        assertFalse(metal().ready(directory))
    }

    @Test fun incompleteOrWrongScopeQualificationCannotEnableOpen() {
        val directory = temporary.newFolder(); fixture(directory)
        assertTrue(metal().ready(directory))
        val receipt = JSONObject(File(directory, "installation.json").readText())
        for (flag in listOf("public_api_verified", "visible_verified", "touch_verified", "relaunch_verified")) {
            receipt.getJSONObject("metal_qualification").put(flag, false)
            File(directory, "installation.json").writeText(receipt.toString())
            assertFalse(flag, metal().ready(directory))
            receipt.getJSONObject("metal_qualification").put(flag, true)
        }
        receipt.getJSONObject("metal_qualification").put("scope", "general-metal")
        File(directory, "installation.json").writeText(receipt.toString())
        assertFalse(metal().ready(directory))
    }

    @Test fun recipeCannotRedirectOrAddRecoveryOrHiddenOptionsEvenWithNewHash() {
        val directory = temporary.newFolder(); fixture(directory)
        assertTrue(metal().ready(directory, true))
        val original = File(directory, "vm.properties").readText()
        for (recipe in listOf(original.replace("root=root", "root=../ios-current/root"),
                original + "ramdisk=ramdisk\n", original + "unknown=value\n",
                original.replace("root_format=raw", "root_format=qcow2"),
                original + "root=other\n", original.replace("kernel=kernel", "kernel=./kernel"))) {
            File(directory, "vm.properties").writeText(recipe); receipt(directory)
            assertFalse(recipe, metal().ready(directory, true))
        }
    }

    @Test fun fullLaunchVerificationRejectsRecipeAndBootCorruptionButAllowsRootWrites() {
        val directory = temporary.newFolder(); fixture(directory)
        assertTrue(MetalLaunchIntegrity.verify(directory) { true })
        File(directory, "root").writeText("xyz")
        assertTrue(MetalLaunchIntegrity.verify(directory) { true })
        val recipe = File(directory, "vm.properties")
        val stamp = recipe.lastModified()
        recipe.writeText(recipe.readText().replace("root=root", "root=evil"))
        recipe.setLastModified(stamp)
        assertFalse(MetalLaunchIntegrity.verify(directory) { true })
        fixture(directory)
        File(directory, "kernel").writeText("bad")
        assertFalse(MetalLaunchIntegrity.verify(directory) { true })
    }

    @Test fun metalRequiresItsRuntimeWithoutChangingGlesRequirements() {
        val directory = temporary.newFolder(); fixture(directory)
        val libraries = temporary.newFolder()
        listOf("libios_gpu.so", "libios_gpu_worker.so", "libgfxstream_backend.so", "libc++.so")
            .forEach { File(libraries, it).writeText("runtime") }
        assertEquals(listOf("Required GPU runtime is missing: libiosgpu_metal.so"),
            GpuProfileChecks.problems(metal().id, directory, libraries))
        File(libraries, "libiosgpu_metal.so").writeText("runtime")
        assertTrue(GpuProfileChecks.problems(metal().id, directory, libraries).isEmpty())
        val gles = temporary.newFolder(); fixture(gles)
        val data = JSONObject(File(gles, "installation.json").readText()).put("profile", GuestProfile.IOS14_GPU.id)
        File(gles, "installation.json").writeText(data.toString())
        File(gles, "gpu-lab-enabled").writeText("enabled")
        File(libraries, "libiosgpu_metal.so").delete()
        assertTrue(GpuProfileChecks.problems(GuestProfile.IOS14_GPU.id, gles, libraries).isEmpty())
    }

    @Test fun cancelDuringMetalVerificationReleasesLeaseAndNeverExecutes() {
        val directory = temporary.newFolder(); fixture(directory)
        assertTrue(MetalLaunchIntegrity.verify(directory) { true })
        val launch = VerifiedLaunch<String>(); val base = temporary.newFolder()
        var polls = 0; var executed = false
        val result = launch.run({ DiskLease.acquire(base) }, { keepGoing ->
            MetalLaunchIntegrity.verify(directory) {
                if (++polls == 5) launch.cancel { error("No process should exist yet") }
                keepGoing()
            }
        }, { executed = true; "child" })
        assertNull(result); assertFalse(executed); assertTrue(launch.cancelled)
        assertFalse(DiskLease.busy(base))
    }

    @Test fun capturedLaunchRecipeCannotRereadDifferentArgumentsAfterVerification() {
        val directory = temporary.newFolder(); fixture(directory)
        assertTrue(MetalLaunchIntegrity.verify(directory) { true })
        val captured = MetalGuestRecipe.verifiedLayout(directory)
        assertNotNull(captured)
        File(directory, "vm.properties").writeText("root=../ios-current/root\nramdisk=ramdisk\n")
        assertEquals(File(directory, "root"), captured!!.file("root"))
        assertEquals(File(directory, "kernel"), captured.file("kernel"))
        assertEquals("exit_recovery", captured.bootMode)
        assertEquals("raw", captured.rootFormat); assertNull(captured.ramdisk)
        assertNull(MetalGuestRecipe.verifiedLayout(directory))
    }

    @Test fun registrationPreservesEveryExistingInstallAndSelection() {
        val base = temporary.newFolder(); val shared = temporary.newFolder()
        val old = listOf(GuestProfile.IOS14, GuestProfile.IOS14_GPU, GuestProfile.IOS16_5).mapIndexed { i, p ->
            Install((i + 2).toString(), "Custom " + p.id, File(base, p.directoryName).path,
                File(shared, (i + 2).toString()).path, true,
                p.defaultSettings.copy(smp = 2, tbSizeMb = 512), profileId = p.id)
        }
        val plan = Installs.planProfileRegistration(old, "4", 5, metal(), "2", base, shared)
        assertEquals(old, plan.installs.take(3)); assertEquals("4", plan.currentId)
        assertEquals("5", plan.target.id); assertEquals(metal().defaultSettings, plan.target.settings)
        assertEquals(File(base, "ios14-metal-lab"), plan.target.dir)
    }

    private fun fixture(directory: File) {
        listOf("root", "kernel", "dtb", "trustcache", "sep_rom", "sep_fw", "firmware", "syscfg",
            "ctrl_bits", "nvram", "effaceable", "panic_log", "sep_nvram", "sep_ssc").forEach {
            File(directory, it).writeText("abc")
        }
        File(directory, "vm.properties").writeText(
            "kernel=kernel\ndtb=dtb\ntrustcache=trustcache\nsep_fw=sep_fw\nsep_rom=sep_rom\n" +
            "root=root\nroot_format=raw\nboot_mode=exit_recovery\n")
        File(directory, "metal-lab-enabled").writeText("enabled")
        receipt(directory)
    }

    private fun receipt(directory: File) {
        val files = JSONObject(); val hashes = JSONObject()
        val required = listOf("root", "kernel", "dtb", "trustcache", "sep_rom", "sep_fw", "vm.properties",
            "firmware", "syscfg", "ctrl_bits", "nvram", "effaceable", "panic_log", "sep_nvram", "sep_ssc")
        required.forEach { name ->
            val file = File(directory, name)
            files.put(name, file.length())
            hashes.put(name, MessageDigest.getInstance("SHA-256").digest(file.readBytes())
                .joinToString("") { "%02x".format(it) })
        }
        val qualification = JSONObject().put("schema_version", 1).put("scope", "linked-authored-app")
            .put("public_api_verified", true).put("visible_verified", true)
            .put("touch_verified", true).put("relaunch_verified", true)
            .put("driver_sha256", "a".repeat(64)).put("app_sha256", "b".repeat(64))
            .put("runtime_sha256", "c".repeat(64)).put("metallib_sha256", "d".repeat(64))
            .put("upstream_pin", "a2c440b8bcdcf20d34aa1694b61ae22c2a7ea68b")
        File(directory, "installation.json").writeText(JSONObject().put("profile", metal().id)
            .put("restored", true).put("patched", true).put("files", files)
            .put("static_sha256", hashes).put("metal_qualification", qualification).toString())
    }
}
