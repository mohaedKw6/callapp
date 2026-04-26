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
    // Set the theme to AppTheme BEFORE onCreate to support
    // coloring the background, status bar, and navigation bar.
    // This is required for expo-splash-screen.
    setTheme(R.style.AppTheme);
    super.onCreate(null)

    // Anti-tamper security check
    if (!SecurityChecker.verifyApp(this)) {
      // App is tampered - show error and exit
      val reason = SecurityChecker.getFailureReason()
      android.app.AlertDialog.Builder(this)
        .setTitle("\u26A0\uFE0F \u062E\u0637\u0623 \u0641\u064A \u0627\u0644\u0623\u0645\u0627\u0646")
        .setMessage("\u062A\u0645 \u0627\u0643\u062A\u0634\u0627\u0641 \u062A\u0639\u062F\u064A\u0644 \u063A\u064A\u0631 \u0645\u0635\u0631\u062D \u0628\u0647 \u0641\u064A \u0627\u0644\u062A\u0637\u0628\u064A\u0642.\n\u0627\u0644\u0633\u0628\u0628: $reason\n\n\u0627\u0644\u062A\u0637\u0628\u064A\u0642 \u0644\u0646 \u064A\u0639\u0645\u0644.")
        .setCancelable(false)
        .setPositiveButton("\u062E\u0631\u0648\u062C") { _, _ ->
          finishAffinity()
          System.exit(0)
        }
        .show()
      return
    }

    // Register current activity with MainApplication for security monitor
    (application as? MainApplication)?.setCurrentActivity(this)
  }

  override fun onDestroy() {
    (application as? MainApplication)?.setCurrentActivity(null)
    super.onDestroy()
  }

  /**
   * Returns the name of the main component registered from JavaScript. This is used to schedule
   * rendering of the component.
   */
  override fun getMainComponentName(): String = "main"

  /**
   * Returns the instance of the [ReactActivityDelegate]. We use [DefaultReactActivityDelegate]
   * which allows you to enable New Architecture with a single boolean flags [fabricEnabled]
   */
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

  /**
    * Align the back button behavior with Android S
    * where moving root activities to background instead of finishing activities.
    * @see <a href="https://developer.android.com/reference/android/app/Activity#onBackPressed()">onBackPressed</a>
    */
  override fun invokeDefaultOnBackPressed() {
      if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.R) {
          if (!moveTaskToBack(false)) {
              // For non-root activities, use the default implementation to finish them.
              super.invokeDefaultOnBackPressed()
          }
          return
      }

      // Use the default back button implementation on Android S
      // because it's doing more than [Activity.moveTaskToBack] in fact.
      super.invokeDefaultOnBackPressed()
  }
}
