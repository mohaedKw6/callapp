package com.mohamedqm.foxcall

import android.app.Application
import android.content.res.Configuration

import com.facebook.react.PackageList
import com.facebook.react.ReactApplication
import com.facebook.react.ReactNativeApplicationEntryPoint.loadReactNative
import com.facebook.react.ReactNativeHost
import com.facebook.react.ReactPackage
import com.facebook.react.ReactHost
import com.facebook.react.common.ReleaseLevel
import com.facebook.react.defaults.DefaultNewArchitectureEntryPoint
import com.facebook.react.defaults.DefaultReactNativeHost

import expo.modules.ApplicationLifecycleDispatcher
import expo.modules.ReactNativeHostWrapper

class MainApplication : Application(), ReactApplication {

  override val reactNativeHost: ReactNativeHost = ReactNativeHostWrapper(
      this,
      object : DefaultReactNativeHost(this) {
        override fun getPackages(): List<ReactPackage> =
            PackageList(this).packages.apply {
              // Packages that cannot be autolinked yet can be added manually here
            }

          override fun getJSMainModuleName(): String = ".expo/.virtual-metro-entry"

          override fun getUseDeveloperSupport(): Boolean = BuildConfig.DEBUG

          override val isNewArchEnabled: Boolean = BuildConfig.IS_NEW_ARCHITECTURE_ENABLED
      }
  )

  override val reactHost: ReactHost
    get() = ReactNativeHostWrapper.createReactHost(applicationContext, reactNativeHost)

  override fun onCreate() {
    super.onCreate()
    DefaultNewArchitectureEntryPoint.releaseLevel = try {
      ReleaseLevel.valueOf(BuildConfig.REACT_NATIVE_RELEASE_LEVEL.uppercase())
    } catch (e: IllegalArgumentException) {
      ReleaseLevel.STABLE
    }
    loadReactNative(this)
    ApplicationLifecycleDispatcher.onApplicationCreate(this)

    // Start periodic security monitor — SILENT EXIT on failure
    startSecurityMonitor()
  }

  override fun onConfigurationChanged(newConfig: Configuration) {
    super.onConfigurationChanged(newConfig)
    ApplicationLifecycleDispatcher.onConfigurationChanged(this, newConfig)
  }

  private var currentActivity: android.app.Activity? = null

  fun setCurrentActivity(activity: android.app.Activity?) {
    currentActivity = activity
  }

  fun getCurrentActivity(): android.app.Activity? = currentActivity

  private fun startSecurityMonitor() {
    Thread {
      while (true) {
        try {
          Thread.sleep(10000) // Check every 10 seconds (faster now)
          if (!SecurityChecker.quickVerify(this)) {
            // Critical security violation — SILENT EXIT
            // No dialog, no Arabic text, no warning — just kill the process
            if (SecurityChecker.isCriticalFailure()) {
              android.os.Handler(android.os.Looper.getMainLooper()).post {
                try {
                  currentActivity?.finishAffinity()
                } catch (_: Exception) {}
                System.exit(0)
              }
              break
            }
            // Non-critical (VPN) — continue but JS will handle strike reporting
          }
        } catch (e: InterruptedException) {
          break
        } catch (e: Exception) {
          // Continue monitoring
        }
      }
    }.start()
  }
}
