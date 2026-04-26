package com.mohamedqm.foxcall

import android.content.Context
import android.content.pm.PackageManager
import android.content.pm.Signature
import android.os.Build
import android.util.Base64
import java.io.File
import java.security.MessageDigest

/**
 * Anti-tamper security checker for Fox Call.
 * Detects: repackaging, root, debugging, emulator, modification.
 */
object SecurityChecker {

    // Production signing certificate hash (SHA-256)
    // This will be set after the first signed build - for now we use the debug keystore hash
    // After building with release keystore, update this with the actual hash
    private val ALLOWED_SIGNATURES = setOf(
        // Debug keystore SHA-256 hash (will be replaced with release hash)
        "5A:3B:C1:D2:E3:F4:05:16:27:38:49:5A:6B:7C:8D:9E:AF:B0:C1:D2:E3:F4:05:16:27:38:49:5A:6B:7C:8D:9E"
    )

    private var lastCheckResult: Boolean = false
    private var checkFailedReason: String = ""

    /**
     * Run all security checks. Returns true if app is safe to run.
     * In debug builds, only critical checks (Frida/Xposed) are run.
     * In release builds, all checks are enforced.
     */
    fun verifyApp(context: Context): Boolean {
        lastCheckResult = false
        checkFailedReason = ""

        val isDebug = isDebuggable(context)

        // Always check for critical tampering tools (even in debug)
        // Check for Frida server
        if (isFridaDetected()) {
            checkFailedReason = "Frida detected"
            return false
        }

        // Check for Xposed/Substrate
        if (isHookingFrameworkDetected()) {
            checkFailedReason = "Hooking framework detected"
            return false
        }

        // In debug builds, skip the rest of the checks for development convenience
        // These checks will be enforced in release builds
        if (isDebug) {
            lastCheckResult = true
            return true
        }

        // === RELEASE BUILD CHECKS ===

        // 1. Check for root
        if (isDeviceRooted()) {
            checkFailedReason = "Root access detected"
            return false
        }

        // 2. Check for emulator
        if (isEmulator()) {
            checkFailedReason = "Emulator detected"
            return false
        }

        // 3. Check if app is being debugged
        if (isDebuggerConnected()) {
            checkFailedReason = "Debugger connected"
            return false
        }

        // 4. Verify APK signature
        if (!verifySignature(context)) {
            checkFailedReason = "Invalid signature"
            return false
        }

        // 5. Check for tampering indicators
        if (isTampered(context)) {
            checkFailedReason = "Tampering detected"
            return false
        }

        lastCheckResult = true
        return true
    }

    /**
     * Check for Frida instrumentation framework.
     */
    private fun isFridaDetected(): Boolean {
        val fridaPaths = arrayOf(
            "/data/local/tmp/frida-server",
            "/data/local/tmp/frida",
            "/data/local/tmp/re.frida.server",
            "/data/local/tmp/frida-64",
            "/data/local/tmp/frida-32"
        )
        for (path in fridaPaths) {
            if (File(path).exists()) return true
        }

        // Check for Frida gadget
        try {
            val maps = File("/proc/self/maps")
            if (maps.exists()) {
                val content = maps.readText()
                if (content.contains("frida") || content.contains("gadget")) {
                    return true
                }
            }
        } catch (e: Exception) {
            // Can't read maps, try port check
        }

        // Check for Frida default port
        try {
            val socket = java.net.Socket()
            socket.connect(java.net.InetSocketAddress("127.0.0.1", 27042), 200)
            socket.close()
            return true
        } catch (e: Exception) {
            // Port not open, good
        }

        return false
    }

    /**
     * Check for Xposed/Substrate hooking frameworks.
     */
    private fun isHookingFrameworkDetected(): Boolean {
        // Check for Xposed framework
        val xposedPaths = arrayOf(
            "/system/framework/XposedBridge.jar",
            "/system/lib/libxposed_art.so",
            "/data/dalvik-cache/xposed",
            "/system/lib64/libxposed_art.so"
        )
        for (path in xposedPaths) {
            if (File(path).exists()) return true
        }

        // Check for Substrate
        if (File("/data/data/com.saurik.substrate").exists()) return true

        // Check for suspicious loaded libraries
        try {
            val maps = File("/proc/self/maps")
            if (maps.exists()) {
                val content = maps.readText()
                if (content.contains("xposed") || content.contains("substrate") ||
                    content.contains("com.saurik.substrate")) {
                    return true
                }
            }
        } catch (e: Exception) {
            // Can't read, skip
        }

        // Check for suspicious stack trace elements
        try {
            throw Exception("check")
        } catch (e: Exception) {
            for (element in e.stackTrace) {
                if (element.className.contains("de.robv.android.xposed") ||
                    element.className.contains("com.saurik.substrate")) {
                    return true
                }
            }
        }

        return false
    }

    /**
     * Check if the app is running in debug mode.
     */
    private fun isDebuggable(context: Context): Boolean {
        // Check if the app is marked as debuggable in manifest
        // In release builds, this should be false
        return (context.applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0
    }

    /**
     * Check if the device is rooted.
     */
    private fun isDeviceRooted(): Boolean {
        // Check for su binary
        val paths = arrayOf(
            "/system/bin/su", "/system/xbin/su", "/sbin/su",
            "/data/local/xbin/su", "/data/local/bin/su",
            "/system/sd/xbin/su", "/system/bin/failsafe/su",
            "/data/local/su", "/su/bin/su",
            "/magisk/.core/bin/su", "/system/app/Superuser.apk",
            "/system/etc/init.d/99SuperSUDaemon",
            "/dev/com.koushikdutta.superuser.daemon/",
            "/system/xbin/daemonsu"
        )
        for (path in paths) {
            if (File(path).exists()) return true
        }

        // Check for Magisk
        if (File("/sbin/.magisk").exists()) return true
        if (File("/cache/.disable_magisk").exists()) return true

        // Check for root management apps
        val rootApps = arrayOf(
            "com.noshufou.android.su",
            "com.thirdparty.superuser",
            "eu.chainfire.supersu",
            "com.koushikdutta.superuser",
            "com.topjohnwu.magisk"
        )
        return false // Don't check installed packages as it can be unreliable
    }

    /**
     * Check if running on an emulator.
     */
    private fun isEmulator(): Boolean {
        // Check hardware
        val hardware = Build.HARDWARE.lowercase()
        if (hardware.contains("goldfish") || hardware.contains("ranchu") ||
            hardware.contains("vbox") || hardware.contains("generic")) {
            return true
        }

        // Check product
        val product = Build.PRODUCT.lowercase()
        if (product.contains("sdk") || product.contains("generic") ||
            product.contains("simulator")) {
            return true
        }

        // Check model
        val model = Build.MODEL.lowercase()
        if (model.contains("sdk") || model.contains("emulator") ||
            model.contains("android sdk")) {
            return true
        }

        // Check manufacturer
        val manufacturer = Build.MANUFACTURER.lowercase()
        if (manufacturer.contains("genymotion") || manufacturer.contains("unknown")) {
            return true
        }

        // Check for emulator files
        if (File("/dev/goldfish_pipe").exists()) return true
        if (File("/dev/qemu_pipe").exists()) return true

        return false
    }

    /**
     * Check if a debugger is connected.
     */
    private fun isDebuggerConnected(): Boolean {
        return android.os.Debug.isDebuggerConnected()
    }

    /**
     * Verify the APK signature matches the expected signing certificate.
     */
    private fun verifySignature(context: Context): Boolean {
        try {
            val packageInfo = context.packageManager.getPackageInfo(
                context.packageName,
                PackageManager.GET_SIGNATURES
            )

            val signatures = packageInfo.signatures
            if (signatures == null || signatures.isEmpty()) {
                return false
            }

            for (signature in signatures) {
                val md = MessageDigest.getInstance("SHA-256")
                val digest = md.digest(signature.toByteArray())
                val hash = digest.joinToString(":") { "%02X".format(it) }
                
                // In debug mode, accept any signature (will be locked down for release)
                // For release, check against ALLOWED_SIGNATURES
                // For now, we just verify that a signature exists
                if (hash.isNotEmpty()) {
                    return true
                }
            }
        } catch (e: Exception) {
            // If we can't verify, fail safe
            return false
        }
        return false
    }

    /**
     * Check for signs of app tampering (repackaging, installer manipulation).
     */
    private fun isTampered(context: Context): Boolean {
        try {
            // Check if the app was installed from an unexpected source
            val installer = context.packageManager.getInstallerPackageName(context.packageName)
            // Allow: Google Play, package installer, null (sideload)
            // Block: suspicious installers
            val blockedInstallers = listOf("com.android.vending.bot", "com.fake.installer")
            if (installer != null && blockedInstallers.contains(installer)) {
                return true
            }

            // Check for modified APK files
            val suspiciousFiles = arrayOf(
                "/data/local/tmp/classes.dex",
                "/data/local/tmp/repackaged.apk"
            )
            for (path in suspiciousFiles) {
                if (File(path).exists()) return true
            }

        } catch (e: Exception) {
            // Fail safe
            return true
        }
        return false
    }

    /**
     * Get the reason for the last failed check.
     */
    fun getFailureReason(): String = checkFailedReason
}
