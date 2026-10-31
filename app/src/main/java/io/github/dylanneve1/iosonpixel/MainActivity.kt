package io.github.dylanneve1.iosonpixel

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Spinner
import io.github.dylanneve1.iosonpixel.install.InstallService

/** Focused entry point. The reference engine's full controls live in Diagnostics. */
class MainActivity : Activity() {
    private val main = Handler(Looper.getMainLooper())
    private lateinit var status: TextView
    private lateinit var action: Button
    private lateinit var cancel: Button
    private lateinit var progress: ProgressBar
    private lateinit var selector: Spinner
    private lateinit var profileInfo: TextView
    private lateinit var preparationInfo: TextView
    private var selectedProfile = GuestProfile.IOS14
    private var reconciled = false
    private var reconciliationPending = false
    private val tick = object : Runnable {
        override fun run() { render(); main.postDelayed(this, 500) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        actionBar?.hide()
        selectedProfile = Installs.selectedProfile(this)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(28), dp(48), dp(28), dp(32))
            setBackgroundColor(Color.rgb(12, 16, 22))
        }
        fun text(value: String, size: Float) = TextView(this).apply {
            text = value; textSize = size; setTextColor(Color.WHITE)
            setPadding(0, dp(12), 0, dp(12))
        }
        root.addView(text(getString(R.string.app_name), 30f))
        root.addView(text(getString(R.string.release_tagline), 19f))
        selector = Spinner(this).apply {
            adapter = ArrayAdapter(this@MainActivity, android.R.layout.simple_spinner_item,
                GuestProfile.entries.map { it.displayName }).apply {
                setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
            }
            contentDescription = "iOS version"
            setSelection(GuestProfile.entries.indexOf(selectedProfile))
            onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                    val profile = GuestProfile.entries[position]
                    if (profile == selectedProfile) return
                    if (reconciled && Installs.selectProfile(this@MainActivity, profile)) selectedProfile = profile
                    else setSelection(GuestProfile.entries.indexOf(selectedProfile))
                    render()
                }
                override fun onNothingSelected(parent: AdapterView<*>?) = Unit
            }
        }
        root.addView(selector, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
        profileInfo = text("", 15f); root.addView(profileInfo)
        status = text("", 16f); root.addView(status)
        progress = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal)
        progress.max = 1000; root.addView(progress, LinearLayout.LayoutParams(MATCH_PARENT, dp(6)))
        action = Button(this).apply { setOnClickListener { primaryAction() } }
        root.addView(action, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
        cancel = Button(this).apply {
            text = "Cancel installation"
            setOnClickListener { startService(Intent(this@MainActivity, InstallService::class.java).setAction(InstallService.CANCEL)) }
        }
        root.addView(cancel, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
        root.addView(Button(this).apply {
            text = "Diagnostics"
            setOnClickListener { startActivity(Intent(this@MainActivity, DiagnosticsActivity::class.java)) }
        })
        root.addView(Button(this).apply {
            text = getString(R.string.support_button)
            setOnClickListener {
                AlertDialog.Builder(this@MainActivity)
                    .setTitle(R.string.support_title)
                    .setMessage(R.string.support_summary)
                    .setPositiveButton(android.R.string.ok, null)
                    .show()
            }
        })
        preparationInfo = text("", 13f); root.addView(preparationInfo)
        setContentView(ScrollView(this).apply { addView(root) })
        beginReconciliation()
    }

    override fun onStart() { super.onStart(); main.post(tick) }
    override fun onStop() { main.removeCallbacks(tick); super.onStop() }

    private fun render() {
        if (!reconciled) beginReconciliation()
        val profile = selectedProfile
        val prefs = getSharedPreferences(profile.preferenceName, MODE_PRIVATE)
        val busy = InstallService.running
        val target = profileInstall()
        val metadataReady = target != null && profile.ready(target.dir)
        if (profile.requiresVerifiedLaunch && metadataReady && !profile.assessedForUi(target!!.dir)) {
            reconciled = false
            beginReconciliation()
        }
        val prepared = metadataReady && profile.verifiedForUi(target!!.dir)
        val otherRunning = VmState.status != VmState.Status.STOPPED && VmState.install?.id != target?.id
        val diskBusy = VmState.status == VmState.Status.STOPPED && DiskLease.busy(filesDir)
        val waiting = (!reconciled && VmState.status == VmState.Status.STOPPED) ||
            ImportState.running || (!busy && diskBusy)
        selector.isEnabled = reconciled && GuestProfile.switchAllowed(
            VmState.status != VmState.Status.STOPPED, busy, ImportState.running, diskBusy)
        profileInfo.text = when (profile) {
            GuestProfile.IOS14 -> "iPhone 11 · iOS 14.0 beta 5\nCPU rendering · v0.0.1"
            GuestProfile.IOS16_5 -> "iOS 16.5 · QEMU virt\nCPU emulation · Experimental profile"
            GuestProfile.IOS14_GPU -> "iOS 14 · GPU — Experimental\nGLES rendering on Adreno · CPU emulation"
            GuestProfile.IOS14_METAL -> "iOS 14 · Metal — Experimental\nLinked Metal apps on Adreno · CPU emulation"
        }
        preparationInfo.text = when (profile) {
            GuestProfile.IOS14 -> "First installation downloads about 5.5 GB and creates a private guest disk. Keep at least 20 GB free. Preparation may take several hours with CPU emulation."
            GuestProfile.IOS16_5 -> "This profile uses a separate private guest disk. iOS14 data stays in its existing installation. GUI, input and persistence require device verification."
            GuestProfile.IOS14_GPU -> "This prepared GPU guest uses a separate private disk. Select iOS14 to return to the CPU installation. Automatic GPU installation is unavailable in this build."
            GuestProfile.IOS14_METAL -> "This separate guest supports the qualified linked Metal workload. General Metal app compatibility remains under development. Automatic installation is unavailable."
        }
        status.text = when {
            waiting -> "Waiting for the previous guest or file operation to finish."
            otherRunning -> "Stop the other guest in Diagnostics before switching."
            busy -> prefs.getString("message", "Preparing guest installation…")
            metadataReady && profile.requiresVerifiedLaunch && !prepared ->
                "Guest boot files have not passed immutable verification. Open is unavailable."
            prepared && profile == GuestProfile.IOS16_5 -> if (profile.qualified(target!!.dir))
                "Prepared guest. GUI, input and persistence are verified for this installation."
                else "Prepared experimental guest. GUI, input or persistence are not yet verified."
            prepared -> "Installation prepared. Open iOS to boot the guest."
            prefs.getBoolean("installed", false) -> "Guest files failed verification. Preparation is required again."
            !profile.installationEnabled -> "Automatic preparation is unavailable for this profile. A fully prepared and verified guest is required before Open is available."
            else -> prefs.getString("message", "Install the supported guest to get started.")
        }
        progress.progress = (prefs.getFloat("fraction", 0f) * 1000).toInt()
        progress.isIndeterminate = busy && prefs.getFloat("fraction", -1f) < 0
        cancel.visibility = if (busy) android.view.View.VISIBLE else android.view.View.GONE
        action.visibility = if (prepared || profile.installationEnabled || busy) View.VISIBLE else View.GONE
        action.isEnabled = !busy && !otherRunning && !waiting && (prepared || profile.installationEnabled)
        action.text = when {
            waiting -> "Waiting for iOS to stop…"
            otherRunning -> "Stop the other guest in Diagnostics"
            prepared && VmState.status != VmState.Status.STOPPED -> "Return to ${profile.displayName}"
            prepared -> "Open ${profile.displayName}"
            busy -> "Installing iOS…"
            else -> "Install supported iOS"
        }
    }

    private fun primaryAction() {
        if (InstallService.running || ImportState.running ||
            (!reconciled && VmState.status == VmState.Status.STOPPED) ||
            (VmState.status == VmState.Status.STOPPED && DiskLease.busy(filesDir))) return
        val profile = selectedProfile
        val target = profileInstall()
        if (VmState.status != VmState.Status.STOPPED && VmState.install?.id != target?.id) return
        val prepared = target != null && profile.ready(target.dir) && profile.verifiedForUi(target.dir)
        if (prepared) {
            if (VmState.status == VmState.Status.STOPPED) {
                if (!Installs.selectProfile(this, profile)) return
                VmService.start(this, target!!)
            }
            startActivity(Intent(this, DisplayActivity::class.java))
        } else if (profile.installationEnabled && Installs.selectProfile(this, profile)) {
            if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
                requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 10)
            startForegroundService(Intent(this, InstallService::class.java).putExtra("guest_profile", profile.id))
        }
    }

    private fun profileInstall(): Install? = Installs.forProfile(this, selectedProfile)

    /** Verifying immutable guest images must not block Android's UI thread. */
    private fun beginReconciliation() {
        if (reconciliationPending || reconciled || InstallService.running || ImportState.running ||
            VmState.status != VmState.Status.STOPPED) return
        reconciliationPending = true
        val context = applicationContext
        Thread({
            val result = runCatching { InstallService.reconcile(context) }.getOrDefault(false)
            main.post {
                reconciliationPending = false
                reconciled = result
                if (result && !isDestroyed) render()
            }
        }, "ios-profile-verification").start()
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
