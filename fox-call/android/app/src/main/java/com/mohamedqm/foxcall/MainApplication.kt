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
              // Packages that cannot be autolinked yet can be added manually here, for example:
              // add(MyReactNativePackage())
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

    // Start periodic security check
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

  private fun startSecurityMonitor() {
    Thread {
      while (true) {
        try {
          Thread.sleep(30000) // Check every 30 seconds
          if (!SecurityChecker.verifyApp(this)) {
            // Security violation detected - kill the app
            android.os.Handler(android.os.Looper.getMainLooper()).post {
              try {
                val activity = currentActivity
                if (activity != null) {
                  android.app.AlertDialog.Builder(activity)
                    .setTitle("\u26A0\uFE0F \u062E\u0637\u0623 \u0641\u064A \u0627\u0644\u0623\u0645\u0627\u0646")
                    .setMessage("\u062A\u0645 \u0627\u0643\u062A\u0634\u0627\u0641 \u062A\u0639\u062F\u064A\u0644 \u063A\u064A\u0631 \u0645\u0635\u0631\u062D \u0628\u0647.\n\u0627\u0644\u062A\u0637\u0628\u064A\u0642 \u0633\u064A\u063A\u0644\u0642 \u0627\u0644\u0622\u0646.")
                    .setCancelable(false)
                    .setPositiveButton("\u062E\u0631\u0648\u062C") { _, _ ->
                      activity.finishAffinity()
                      System.exit(0)
                    }
                    .show()
                } else {
                  System.exit(0)
                }
              } catch (e: Exception) {
                System.exit(0)
              }
            }
            break
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
