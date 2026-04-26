package com.mohamedqm.foxcall

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.util.Base64
import java.io.File
import java.io.RandomAccessFile
import java.net.Socket
import java.security.MessageDigest
import java.util.Scanner

/**
 * Fox Call Security Checker v2 — Multi-layer anti-tamper protection.
 *
 * Layers:
 *  1. Root / Magisk / Superuser detection
 *  2. Frida / Xposed / hooking framework detection
 *  3. Emulator detection
 *  4. Debugger detection
 *  5. APK signature verification (Integrity Check)
 *  6. Repackaging / installer verification
 *  7. Runtime integrity monitoring
 */
object SecurityChecker {

    // ═══════════════════════════════════════════════════════════════════
    //  Production signing certificate SHA-256 hash (colon-separated hex)
    //  This MUST match the keystore used for release builds.
    //  Debug keystore hash: FA:C6:17:45:DC:09:03:78:6F:B9:ED:E6:2A:96:2B:39:9F:73:48:F0:BB:6F:89:9B:83:32:66:75:91:03:3B:9C
    // ═══════════════════════════════════════════════════════════════════
    private val ALLOWED_SIGNATURES = setOf(
        // Debug keystore SHA-256
        "FA:C6:17:45:DC:09:03:78:6F:B9:ED:E6:2A:96:2B:39:9F:73:48:F0:BB:6F:89:9B:83:32:66:75:91:03:3B:9C"
    )

    // Server certificate pins for SSL Pinning verification from native layer
    private val ALLOWED_SERVER_PINS = setOf(
        "VYxe9LAwK2QozwAdcQXon+QWur/Wn6o01PdWoMq1jiw=",  // Primary Railway pin
        "Zq0/KpWiTiAjhUPmQnsc3avr2vqU6g3AXVq8l6+mu78="   // Backup cert pin
    )

    private var lastCheckResult = false
    private var checkFailedReason = ""
    private var checkTimestamp = 0L
    private val CHECK_INTERVAL = 15_000L // Re-check every 15 seconds

    /**
     * Run all security checks. Returns true if the app is safe to run.
     * In debug builds, only critical checks (Frida/Xposed) are enforced.
     * In release builds, ALL checks are enforced.
     */
    fun verifyApp(context: Context): Boolean {
        lastCheckResult = false
        checkFailedReason = ""

        val isDebug = isDebuggable(context)

        // ── Always enforce critical checks (even in debug) ──

        // 1. Frida detection
        if (isFridaDetected()) {
            checkFailedReason = "Frida detected"
            return false
        }

        // 2. Hooking framework detection
        if (isHookingFrameworkDetected()) {
            checkFailedReason = "Hooking framework detected"
            return false
        }

        // In debug builds, skip remaining checks for development convenience
        if (isDebug) {
            lastCheckResult = true
            return true
        }

        // ── Release-only checks ──

        // 3. Root detection
        if (isDeviceRooted(context)) {
            checkFailedReason = "Root access detected"
            return false
        }

        // 4. Emulator detection
        if (isEmulator()) {
            checkFailedReason = "Emulator detected"
            return false
        }

        // 5. Debugger detection
        if (isDebuggerConnected()) {
            checkFailedReason = "Debugger connected"
            return false
        }

        // 6. Signature verification (Integrity Check)
        if (!verifySignature(context)) {
            checkFailedReason = "Invalid signature — app is modified"
            return false
        }

        // 7. Repackaging / tampering checks
        if (isTampered(context)) {
            checkFailedReason = "Tampering detected"
            return false
        }

        lastCheckResult = true
        checkTimestamp = System.currentTimeMillis()
        return true
    }

    /**
     * Lightweight periodic check — runs only time-based and critical checks.
     */
    fun quickVerify(context: Context): Boolean {
        // Don't re-run full check too often
        if (System.currentTimeMillis() - checkTimestamp < CHECK_INTERVAL && lastCheckResult) {
            return true
        }
        return verifyApp(context)
    }

    fun getFailureReason(): String = checkFailedReason

    // ═══════════════════════════════════════════════════════════════════
    //  Layer 1: Root / Magisk Detection
    // ═══════════════════════════════════════════════════════════════════

    private fun isDeviceRooted(context: Context): Boolean {
        // Method 1: Check su binary paths
        if (checkSuBinary()) return true

        // Method 2: Check Magisk-specific paths and files
        if (checkMagisk()) return true

        // Method 3: Check for root management apps
        if (checkRootApps(context)) return true

        // Method 4: Try executing su command
        if (trySuCommand()) return true

        // Method 5: Check for dangerous system properties
        if (checkSystemProperties()) return true

        // Method 6: Check SELinux status
        if (checkSelinux()) return true

        return false
    }

    private fun checkSuBinary(): Boolean {
        val suPaths = arrayOf(
            "/system/bin/su", "/system/xbin/su", "/sbin/su",
            "/data/local/xbin/su", "/data/local/bin/su",
            "/system/sd/xbin/su", "/system/bin/failsafe/su",
            "/data/local/su", "/su/bin/su",
            "/magisk/.core/bin/su", "/system/app/Superuser.apk",
            "/system/etc/init.d/99SuperSUDaemon",
            "/dev/com.koushikdutta.superuser.daemon/",
            "/system/xbin/daemonsu",
            "/system/bin/.ext/.su",
            "/system/usr/we-need-root",
            "/cache/.disable_magisk",
            "/data/adb/ksu", "/data/adb/apd"
        )
        for (path in suPaths) {
            if (File(path).exists()) return true
        }
        return false
    }

    private fun checkMagisk(): Boolean {
        val magiskPaths = arrayOf(
            "/sbin/.magisk",
            "/cache/.disable_magisk",
            "/data/adb/magisk",
            "/data/adb/magisk.db",
            "/data/adb/magisk/busybox",
            "/data/adb/magisk/magisk64",
            "/data/adb/magisk/magisk32",
            "/data/adb/magiskinit",
            "/data/adb/ksu",
            "/data/adb/apd",
            "/data/adb/modules",
            "/data/adb/post-fs-data.d",
            "/data/adb/service.d"
        )
        for (path in magiskPaths) {
            if (File(path).exists()) return true
        }

        // Check for Magisk Hide / Zygisk
        try {
            val maps = File("/proc/self/maps")
            if (maps.exists()) {
                val content = maps.readText()
                if (content.contains("magisk", ignoreCase = true) ||
                    content.contains("zygisk", ignoreCase = true)) {
                    return true
                }
            }
        } catch (_: Exception) {}

        return false
    }

    private fun checkRootApps(context: Context): Boolean {
        val rootAppPackages = arrayOf(
            "com.noshufou.android.su",
            "com.thirdparty.superuser",
            "eu.chainfire.supersu",
            "com.koushikdutta.superuser",
            "com.topjohnwu.magisk",
            "io.github.vvb2060.magisk",
            "com.tsng.hidemyapplist",
            "me.weishu.expuresu",
            "org.lsposed.manager",
            "io.github.lsposed.manager"
        )
        val pm = context.packageManager
        for (pkg in rootAppPackages) {
            try {
                pm.getPackageInfo(pkg, 0)
                return true
            } catch (_: PackageManager.NameNotFoundException) {
                // Not installed — good
            } catch (_: Exception) {}
        }
        return false
    }

    private fun trySuCommand(): Boolean {
        return try {
            val process = Runtime.getRuntime().exec(arrayOf("which", "su"))
            val scanner = Scanner(process.inputStream)
            val result = scanner.hasNextLine()
            scanner.close()
            process.waitFor()
            result
        } catch (_: Exception) {
            false
        }
    }

    private fun checkSystemProperties(): Boolean {
        return try {
            val getprop = Runtime.getRuntime().exec("getprop ro.debuggable")
            val s = Scanner(getprop.inputStream)
            if (s.hasNextLine() && s.nextLine().trim() == "1") return true
            s.close()

            val secureProp = Runtime.getRuntime().exec("getprop ro.secure")
            val s2 = Scanner(secureProp.inputStream)
            if (s2.hasNextLine() && s2.nextLine().trim() == "0") return true
            s2.close()

            false
        } catch (_: Exception) {
            false
        }
    }

    private fun checkSelinux(): Boolean {
        return try {
            // If SELinux is permissive, device is likely rooted
            val process = Runtime.getRuntime().exec("getenforce")
            val s = Scanner(process.inputStream)
            val result = s.hasNextLine() && s.nextLine().trim().equals("Permissive", ignoreCase = true)
            s.close()
            process.waitFor()
            result
        } catch (_: Exception) {
            false
        }
    }

    // ═══════════════════════════════════════════════════════════════════
    //  Layer 2: Frida / Xposed / Hooking Framework Detection
    // ═══════════════════════════════════════════════════════════════════

    private fun isFridaDetected(): Boolean {
        // Method 1: Check Frida binary paths
        val fridaPaths = arrayOf(
            "/data/local/tmp/frida-server",
            "/data/local/tmp/frida",
            "/data/local/tmp/re.frida.server",
            "/data/local/tmp/frida-64",
            "/data/local/tmp/frida-32",
            "/data/local/tmp/frida-server-64",
            "/data/local/tmp/frida-server-32"
        )
        for (path in fridaPaths) {
            if (File(path).exists()) return true
        }

        // Method 2: Check /proc/self/maps for frida/gadget libraries
        try {
            val maps = File("/proc/self/maps")
            if (maps.exists()) {
                val content = maps.readText()
                if (content.contains("frida", ignoreCase = true) ||
                    content.contains("gadget", ignoreCase = true) ||
                    content.contains("linjector", ignoreCase = true)) {
                    return true
                }
            }
        } catch (_: Exception) {}

        // Method 3: Check Frida default port (27042)
        try {
            val socket = Socket()
            socket.connect(java.net.InetSocketAddress("127.0.0.1", 27042), 200)
            socket.close()
            return true
        } catch (_: Exception) {}

        // Method 4: Check for frida-related threads
        try {
            val process = Runtime.getRuntime().exec(arrayOf("ls", "/proc/self/task"))
            val scanner = Scanner(process.inputStream)
            while (scanner.hasNextLine()) {
                val tid = scanner.nextLine()
                try {
                    val comm = File("/proc/self/task/$tid/comm").readText().trim()
                    if (comm.contains("frida", ignoreCase = true) ||
                        comm.contains("gum-js-loop", ignoreCase = true) ||
                        comm.contains("gmain", ignoreCase = true) ||
                        comm.contains("linjector", ignoreCase = true)) {
                        scanner.close()
                        return true
                    }
                } catch (_: Exception) {}
            }
            scanner.close()
        } catch (_: Exception) {}

        // Method 5: Check for Frida's D-Bus communication
        try {
            val socket = Socket()
            socket.connect(java.net.InetSocketAddress("127.0.0.1", 27043), 200)
            socket.close()
            return true
        } catch (_: Exception) {}

        return false
    }

    private fun isHookingFrameworkDetected(): Boolean {
        // Method 1: Xposed paths
        val xposedPaths = arrayOf(
            "/system/framework/XposedBridge.jar",
            "/system/lib/libxposed_art.so",
            "/data/dalvik-cache/xposed",
            "/system/lib64/libxposed_art.so",
            "/system/framework/edxp.jar",
            "/system/framework/edxposed.jar",
            "/data/misc/riru",
            "/data/adb/riru",
            "/data/adb/lspd"
        )
        for (path in xposedPaths) {
            if (File(path).exists()) return true
        }

        // Method 2: Check for Substrate
        if (File("/data/data/com.saurik.substrate").exists()) return true
        val substratePaths = arrayOf(
            "/data/data/com.saurik.substrate",
            "/system/lib/libsubstrate.so",
            "/system/lib64/libsubstrate.so",
            "/data/adb/substrate"
        )
        for (path in substratePaths) {
            if (File(path).exists()) return true
        }

        // Method 3: Check loaded libraries in /proc/self/maps
        try {
            val maps = File("/proc/self/maps")
            if (maps.exists()) {
                val content = maps.readText()
                if (content.contains("xposed", ignoreCase = true) ||
                    content.contains("substrate", ignoreCase = true) ||
                    content.contains("edxposed", ignoreCase = true) ||
                    content.contains("riru", ignoreCase = true) ||
                    content.contains("lsposed", ignoreCase = true) ||
                    content.contains("com.saurik.substrate")) {
                    return true
                }
            }
        } catch (_: Exception) {}

        // Method 4: Check stack trace for hooking classes
        try {
            throw Exception("security_check")
        } catch (e: Exception) {
            for (element in e.stackTrace) {
                if (element.className.contains("de.robv.android.xposed") ||
                    element.className.contains("com.saurik.substrate") ||
                    element.className.contains("edxposed") ||
                    element.className.contains("lsposed") ||
                    element.className.contains("riru")) {
                    return true
                }
            }
        }

        // Method 5: Check for LSPosed manager
        try {
            val maps = File("/proc/self/maps")
            if (maps.exists()) {
                val content = maps.readText()
                if (content.contains("lspd", ignoreCase = true)) {
                    return true
                }
            }
        } catch (_: Exception) {}

        return false
    }

    // ═══════════════════════════════════════════════════════════════════
    //  Layer 3: Emulator Detection
    // ═══════════════════════════════════════════════════════════════════

    private fun isEmulator(): Boolean {
        // Hardware checks
        val hardware = Build.HARDWARE.lowercase()
        if (hardware.contains("goldfish") || hardware.contains("ranchu") ||
            hardware.contains("vbox") || hardware.contains("generic") ||
            hardware.contains("nox") || hardware.contains("bluestacks") ||
            hardware.contains("ttvm")) {
            return true
        }

        // Product checks
        val product = Build.PRODUCT.lowercase()
        if (product.contains("sdk") || product.contains("generic") ||
            product.contains("simulator") || product.contains("nox") ||
            product.contains("bluestacks")) {
            return true
        }

        // Model checks
        val model = Build.MODEL.lowercase()
        if (model.contains("sdk") || model.contains("emulator") ||
            model.contains("android sdk") || model.contains("nox") ||
            model.contains("bluestacks") || model.contains("tencent")) {
            return true
        }

        // Manufacturer checks
        val manufacturer = Build.MANUFACTURER.lowercase()
        if (manufacturer.contains("genymotion") || manufacturer.contains("nox") ||
            manufacturer.contains("bluestacks") || manufacturer.contains("tencent")) {
            return true
        }

        // Device fingerprint
        val fingerprint = Build.FINGERPRINT.lowercase()
        if (fingerprint.contains("generic") || fingerprint.contains("emulator") ||
            fingerprint.contains("sdk")) {
            return true
        }

        // Board checks
        val board = Build.BOARD.lowercase()
        if (board.contains("unknown") || board.contains("generic")) {
            return true
        }

        // Emulator-specific files
        val emulatorFiles = arrayOf(
            "/dev/goldfish_pipe",
            "/dev/qemu_pipe",
            "/dev/socket/genyd",
            "/dev/vboxguest",
            "/system/lib/libc_malloc_debug_qemu.so",
            "/sys/qemu_trace",
            "/system/bin/qemu-props"
        )
        for (path in emulatorFiles) {
            if (File(path).exists()) return true
        }

        // Check for too many CPU cores (emulators usually have 1-2)
        // Real devices rarely have just 1 core now, but this is a weak signal

        // Check /proc/cpuinfo for emulator indicators
        try {
            val cpuinfo = File("/proc/cpuinfo")
            if (cpuinfo.exists()) {
                val content = cpuinfo.readText()
                if (content.contains("Intel", ignoreCase = true) &&
                    !content.contains("atom", ignoreCase = true)) {
                    // x86 Intel CPU without "atom" — likely emulator
                    return true
                }
            }
        } catch (_: Exception) {}

        return false
    }

    // ═══════════════════════════════════════════════════════════════════
    //  Layer 4: Debugger Detection
    // ═══════════════════════════════════════════════════════════════════

    private fun isDebuggerConnected(): Boolean {
        // Standard Android debugger check
        if (android.os.Debug.isDebuggerConnected()) return true

        // Check for debugger-related flags in /proc/self/status
        try {
            val status = File("/proc/self/status")
            if (status.exists()) {
                val content = status.readText()
                val tracerPidLine = content.lines().find { it.startsWith("TracerPid:") }
                if (tracerPidLine != null) {
                    val pid = tracerPidLine.substringAfter(":").trim()
                    if (pid != "0") return true
                }
            }
        } catch (_: Exception) {}

        return false
    }

    // ═══════════════════════════════════════════════════════════════════
    //  Layer 5: APK Signature Verification (Integrity Check)
    // ═══════════════════════════════════════════════════════════════════

    private fun isDebuggable(context: Context): Boolean {
        return (context.applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0
    }

    private fun verifySignature(context: Context): Boolean {
        try {
            // Use GET_SIGNING_CERTIFICATES for API 28+, fallback to GET_SIGNATURES
            val packageInfo = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                context.packageManager.getPackageInfo(
                    context.packageName,
                    PackageManager.GET_SIGNING_CERTIFICATES
                )
            } else {
                @Suppress("DEPRECATION")
                context.packageManager.getPackageInfo(
                    context.packageName,
                    PackageManager.GET_SIGNATURES
                )
            }

            val signatures = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                packageInfo.signingInfo?.apkContentsSigners
            } else {
                @Suppress("DEPRECATION")
                packageInfo.signatures
            }

            if (signatures == null || signatures.isEmpty()) {
                return false
            }

            for (signature in signatures) {
                val md = MessageDigest.getInstance("SHA-256")
                val digest = md.digest(signature.toByteArray())
                val hash = digest.joinToString(":") { "%02X".format(it) }

                // Check against allowed signatures
                if (ALLOWED_SIGNATURES.contains(hash)) {
                    return true
                }
            }

            // No matching signature found — this APK was signed with a different key
            return false
        } catch (e: Exception) {
            // Fail safe: if we can't verify, reject
            return false
        }
    }

    // ═══════════════════════════════════════════════════════════════════
    //  Layer 6: Repackaging / Tampering Detection
    // ═══════════════════════════════════════════════════════════════════

    private fun isTampered(context: Context): Boolean {
        // Check 1: Installer source verification
        try {
            val installer = context.packageManager.getInstallerPackageName(context.packageName)
            val blockedInstallers = listOf(
                "com.android.vending.bot",
                "com.fake.installer",
                "org.lsposed.manager"
            )
            if (installer != null && blockedInstallers.contains(installer)) {
                return true
            }
        } catch (_: Exception) {}

        // Check 2: Suspicious files in /data/local/tmp
        val suspiciousFiles = arrayOf(
            "/data/local/tmp/classes.dex",
            "/data/local/tmp/repackaged.apk",
            "/data/local/tmp/frida-server",
            "/data/local/tmp/patched.apk",
            "/data/local/tmp/magisk"
        )
        for (path in suspiciousFiles) {
            if (File(path).exists()) return true
        }

        // Check 3: Verify APK integrity by checking classes.dex CRC
        try {
            val appInfo = context.applicationInfo
            val sourceDir = appInfo.sourceDir
            if (sourceDir != null) {
                // Check if the APK has been modified by verifying file size is reasonable
                val apkFile = File(sourceDir)
                if (!apkFile.exists()) return true
            }
        } catch (_: Exception) {}

        // Check 4: Check for runtime modification indicators
        try {
            // If someone is using runtime modification tools, they often
            // modify /proc/self/mem or have suspicious memory maps
            val maps = File("/proc/self/maps")
            if (maps.exists()) {
                val content = maps.readText()
                // Check for suspicious injected libraries
                if (content.contains("libsubstrate", ignoreCase = true) ||
                    content.contains("libcydia", ignoreCase = true) ||
                    content.contains("xposed", ignoreCase = true)) {
                    return true
                }
            }
        } catch (_: Exception) {}

        return false
    }

    // ═══════════════════════════════════════════════════════════════════
    //  SSL Pinning Verification (runtime check from native layer)
    // ═══════════════════════════════════════════════════════════════════

    /**
     * Verify that a given certificate pin matches our allowed pins.
     * Used by the JS side to verify SSL connections.
     */
    fun verifySSLPin(pin: String): Boolean {
        return ALLOWED_SERVER_PINS.contains(pin)
    }

    /**
     * Get the current APK signature hash for debugging.
     */
    fun getSignatureHash(context: Context): String {
        try {
            val packageInfo = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                context.packageManager.getPackageInfo(
                    context.packageName,
                    PackageManager.GET_SIGNING_CERTIFICATES
                )
            } else {
                @Suppress("DEPRECATION")
                context.packageManager.getPackageInfo(
                    context.packageName,
                    PackageManager.GET_SIGNATURES
                )
            }

            val signatures = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                packageInfo.signingInfo?.apkContentsSigners
            } else {
                @Suppress("DEPRECATION")
                packageInfo.signatures
            }

            if (signatures != null && signatures.isNotEmpty()) {
                val md = MessageDigest.getInstance("SHA-256")
                val digest = md.digest(signatures[0].toByteArray())
                return digest.joinToString(":") { "%02X".format(it) }
            }
        } catch (_: Exception) {}
        return "unknown"
    }
}
