package com.mohamedqm.foxcall

import android.os.Build
import android.os.Bundle

import com.facebook.react.ReactActivity
import com.facebook.react.ReactActivityDelegate
import com.facebook.react.defaults.DefaultNewArchitectureEntryPoint.fabricEnabled
import com.facebook.react.defaults.DefaultReactActivityDelegate

import expo.modules.ReactActivityDelegateWrapper

class MainActivity : ReactActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    setTheme(R.style.AppTheme);
    super.onCreate(null)

    // ═══════════════════════════════════════════════════════════════════
    //  Multi-layer Anti-Tamper Security Check
    //  If ANY critical check fails → SILENT EXIT. No dialog, no warning.
    //  Non-critical issues (VPN) → report strike to server.
    // ═══════════════════════════════════════════════════════════════════
    val securityOk = SecurityChecker.verifyApp(this)
    
    if (!securityOk && SecurityChecker.isCriticalFailure()) {
      // Critical failure — silent exit immediately
      // No dialog, no Arabic text, no warning — just crash
      finishAffinity()
      System.exit(0)
      return
    }
    
    if (!securityOk && !SecurityChecker.isCriticalFailure()) {
      // Non-critical (e.g., VPN detected) — report strike but allow app to continue
      // The JS side will handle reporting to server
    }

    (application as? MainApplication)?.setCurrentActivity(this)
  }

  override fun onDestroy() {
    (application as? MainApplication)?.setCurrentActivity(null)
    super.onDestroy()
  }

  override fun getMainComponentName(): String = "main"

  override fun createReactActivityDelegate(): ReactActivityDelegate {
    return ReactActivityDelegateWrapper(
          this,
          BuildConfig.IS_NEW_ARCHITECTURE_ENABLED,
          object : DefaultReactActivityDelegate(
              this,
              mainComponentName,
              fabricEnabled
          ){})
  }

  override fun invokeDefaultOnBackPressed() {
      if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.R) {
          if (!moveTaskToBack(false)) {
              super.invokeDefaultOnBackPressed()
          }
          return
      }

      super.invokeDefaultOnBackPressed()
  }
}
