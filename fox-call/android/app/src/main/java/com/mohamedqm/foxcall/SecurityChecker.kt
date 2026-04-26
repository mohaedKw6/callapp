package com.mohamedqm.foxcall

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import java.io.File
import java.net.NetworkInterface
import java.net.Socket
import java.security.MessageDigest
import java.util.Scanner

/**
 * Fox Call Security Checker v3 — Multi-layer anti-tamper protection.
 *
 * Layers:
 *  1. Root / Magisk / Superuser detection
 *  2. Frida / Xposed / hooking framework detection
 *  3. Emulator detection
 *  4. Debugger detection
 *  5. APK signature verification (Integrity Check)
 *  6. Repackaging / installer verification
 *  7. VPN detection
 *  8. Runtime integrity monitoring
 *
 * SECURITY NOTE: No Arabic strings in this file.
 * All security messages are encoded to prevent reverse engineering via text search.
 * On failure, the app SILENTLY exits — no dialog, no warning.
 */
object SecurityChecker {

    // ═══════════════════════════════════════════════════════════════════
    //  Production signing certificate SHA-256 hash (colon-separated hex)
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

    // Encoded failure reasons (not readable by simple text search)
    // Each reason is XOR'd with a key to prevent easy discovery
    private const val R_KEY: Byte = 0x5A
    private val ENCODED_REASONS = mapOf(
        1 to byteArrayOf(0x3A, 0x29, 0x76, 0x6B, 0x3A, 0x69, 0x22, 0x29, 0x73, 0x76, 0x6D, 0x29, 0x64), // frida
        2 to byteArrayOf(0x2F, 0x29, 0x29, 0x6B, 0x29, 0x22, 0x3A, 0x69, 0x22, 0x29, 0x73, 0x76, 0x6D, 0x29, 0x64), // hooking
        3 to byteArrayOf(0x3A, 0x29, 0x39, 0x76, 0x28, 0x24, 0x3A, 0x69, 0x22, 0x29, 0x73, 0x76, 0x6D, 0x29, 0x64), // root
        4 to byteArrayOf(0x28, 0x22, 0x3E, 0x29, 0x2C, 0x69, 0x22, 0x29, 0x73, 0x76, 0x6D, 0x29, 0x64), // emulator
        5 to byteArrayOf(0x64, 0x28, 0x24, 0x22, 0x3B, 0x22, 0x28, 0x69, 0x22, 0x29, 0x73, 0x76, 0x6D, 0x29, 0x64), // debugger
        6 to byteArrayOf(0x22, 0x3B, 0x24, 0x69, 0x22, 0x29, 0x73, 0x76, 0x6D, 0x29, 0x64), // signature
        7 to byteArrayOf(0x76, 0x24, 0x22, 0x23, 0x28, 0x3A, 0x69, 0x22, 0x29, 0x73, 0x76, 0x6D, 0x29, 0x64), // tamper
        8 to byteArrayOf(0x3F, 0x23, 0x2E, 0x69, 0x22, 0x29, 0x73, 0x76, 0x6D, 0x29, 0x64), // vpn
    )

    private var lastCheckResult = false
    private var checkFailedCode = 0
    private var checkTimestamp = 0L
    private val CHECK_INTERVAL = 10_000L // Re-check every 10 seconds

    // Strike tracking for suspicious behavior
    private var strikeCount = 0
    private var lastStrikeReason = ""
    private val MAX_STRIKES = 3

    /**
     * Run all security checks. Returns true if the app is safe to run.
     * In debug builds, only critical checks (Frida/Xposed) are enforced.
     * In release builds, ALL checks are enforced.
     * On failure: NO DIALOG, NO WARNING — silent exit only.
     */
    fun verifyApp(context: Context): Boolean {
        lastCheckResult = false
        checkFailedCode = 0

        val isDebug = isDebuggable(context)

        // ── Always enforce critical checks (even in debug) ──

        // 1. Frida detection
        if (isFridaDetected()) {
            checkFailedCode = 1
            return false
        }

        // 2. Hooking framework detection
        if (isHookingFrameworkDetected()) {
            checkFailedCode = 2
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
            checkFailedCode = 3
            return false
        }

        // 4. Emulator detection
        if (isEmulator()) {
            checkFailedCode = 4
            return false
        }

        // 5. Debugger detection
        if (isDebuggerConnected()) {
            checkFailedCode = 5
            return false
        }

        // 6. Signature verification (Integrity Check)
        if (!verifySignature(context)) {
            checkFailedCode = 6
            return false
        }

        // 7. Repackaging / tampering checks
        if (isTampered(context)) {
            checkFailedCode = 7
            return false
        }

        // 8. VPN detection (suspicious but not auto-exit — just a strike)
        if (isVPNActive()) {
            checkFailedCode = 8
            // VPN is suspicious but doesn't cause immediate exit
            // Instead, add a strike
            addStrike("vpn_active")
            // Don't return false — VPN alone shouldn't crash the app
            // But we record it
        }

        lastCheckResult = true
        checkTimestamp = System.currentTimeMillis()
        return true
    }

    /**
     * Lightweight periodic check — runs only time-based and critical checks.
     */
    fun quickVerify(context: Context): Boolean {
        if (System.currentTimeMillis() - checkTimestamp < CHECK_INTERVAL && lastCheckResult) {
            return true
        }
        return verifyApp(context)
    }

    fun getFailureReason(): String = decodeReason(checkFailedCode)

    fun getFailureCode(): Int = checkFailedCode

    /**
     * Returns true if the security failure is critical (should crash immediately).
     * VPN detection (code 8) is NOT critical — it's a strike.
     */
    fun isCriticalFailure(): Boolean {
        return checkFailedCode in 1..7
    }

    /**
     * Add a strike for suspicious behavior.
     * Returns the current strike count.
     */
    fun addStrike(reason: String): Int {
        strikeCount++
        lastStrikeReason = reason
        return strikeCount
    }

    fun getStrikeCount(): Int = strikeCount

    fun getLastStrikeReason(): String = lastStrikeReason

    fun shouldBan(): Boolean = strikeCount >= MAX_STRIKES

    fun resetStrikes() {
        strikeCount = 0
        lastStrikeReason = ""
    }

    private fun decodeReason(code: Int): String {
        val encoded = ENCODED_REASONS[code] ?: return "unknown"
        return String(encoded.map { (it.toInt() xor R_KEY.toInt()).toByte() }.toByteArray())
    }

    // ═══════════════════════════════════════════════════════════════════
    //  Layer 1: Root / Magisk Detection
    // ═══════════════════════════════════════════════════════════════════

    private fun isDeviceRooted(context: Context): Boolean {
        if (checkSuBinary()) return true
        if (checkMagisk()) return true
        if (checkRootApps(context)) return true
        if (trySuCommand()) return true
        if (checkSystemProperties()) return true
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

        try {
            val socket = Socket()
            socket.connect(java.net.InetSocketAddress("127.0.0.1", 27042), 200)
            socket.close()
            return true
        } catch (_: Exception) {}

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

        try {
            val socket = Socket()
            socket.connect(java.net.InetSocketAddress("127.0.0.1", 27043), 200)
            socket.close()
            return true
        } catch (_: Exception) {}

        return false
    }

    private fun isHookingFrameworkDetected(): Boolean {
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
        val hardware = Build.HARDWARE.lowercase()
        if (hardware.contains("goldfish") || hardware.contains("ranchu") ||
            hardware.contains("vbox") || hardware.contains("generic") ||
            hardware.contains("nox") || hardware.contains("bluestacks") ||
            hardware.contains("ttvm")) {
            return true
        }

        val product = Build.PRODUCT.lowercase()
        if (product.contains("sdk") || product.contains("generic") ||
            product.contains("simulator") || product.contains("nox") ||
            product.contains("bluestacks")) {
            return true
        }

        val model = Build.MODEL.lowercase()
        if (model.contains("sdk") || model.contains("emulator") ||
            model.contains("android sdk") || model.contains("nox") ||
            model.contains("bluestacks") || model.contains("tencent")) {
            return true
        }

        val manufacturer = Build.MANUFACTURER.lowercase()
        if (manufacturer.contains("genymotion") || manufacturer.contains("nox") ||
            manufacturer.contains("bluestacks") || manufacturer.contains("tencent")) {
            return true
        }

        val fingerprint = Build.FINGERPRINT.lowercase()
        if (fingerprint.contains("generic") || fingerprint.contains("emulator") ||
            fingerprint.contains("sdk")) {
            return true
        }

        val board = Build.BOARD.lowercase()
        if (board.contains("unknown") || board.contains("generic")) {
            return true
        }

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

        try {
            val cpuinfo = File("/proc/cpuinfo")
            if (cpuinfo.exists()) {
                val content = cpuinfo.readText()
                if (content.contains("Intel", ignoreCase = true) &&
                    !content.contains("atom", ignoreCase = true)) {
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
        if (android.os.Debug.isDebuggerConnected()) return true

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

                if (ALLOWED_SIGNATURES.contains(hash)) {
                    return true
                }
            }

            return false
        } catch (e: Exception) {
            return false
        }
    }

    // ═══════════════════════════════════════════════════════════════════
    //  Layer 6: Repackaging / Tampering Detection
    // ═══════════════════════════════════════════════════════════════════

    private fun isTampered(context: Context): Boolean {
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

        try {
            val appInfo = context.applicationInfo
            val sourceDir = appInfo.sourceDir
            if (sourceDir != null) {
                val apkFile = File(sourceDir)
                if (!apkFile.exists()) return true
            }
        } catch (_: Exception) {}

        try {
            val maps = File("/proc/self/maps")
            if (maps.exists()) {
                val content = maps.readText()
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
    //  Layer 7: VPN Detection
    // ═══════════════════════════════════════════════════════════════════

    fun isVPNActive(): Boolean {
        try {
            val interfaces = NetworkInterface.getNetworkInterfaces() ?: return false
            while (interfaces.hasMoreElements()) {
                val intf = interfaces.nextElement()
                val name = intf.name.lowercase()
                // Common VPN interface names
                if (name.startsWith("tun") || name.startsWith("ppp") ||
                    name.startsWith("pptp") || name.startsWith("tap") ||
                    name.startsWith("wg") || name.startsWith("ipsec") ||
                    name.startsWith("ovpn") || name.startsWith("vpn") ||
                    name.startsWith("nordvpn") || name.startsWith("expressvpn")) {
                    if (intf.isUp && !intf.isLoopback) {
                        return true
                    }
                }
            }
        } catch (_: Exception) {}
        return false
    }

    // ═══════════════════════════════════════════════════════════════════
    //  SSL Pinning Verification (runtime check from native layer)
    // ═══════════════════════════════════════════════════════════════════

    fun verifySSLPin(pin: String): Boolean {
        return ALLOWED_SERVER_PINS.contains(pin)
    }

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
