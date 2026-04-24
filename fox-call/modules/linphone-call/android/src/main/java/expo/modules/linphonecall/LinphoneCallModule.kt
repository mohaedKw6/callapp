package expo.modules.linphonecall

import android.content.Context
import android.media.AudioManager
import android.os.Handler
import android.os.Looper
import android.util.Log
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import expo.modules.kotlin.Promise
import expo.modules.kotlin.records.Field
import expo.modules.kotlin.records.Record
import org.linphone.core.AudioDevice
import org.linphone.core.Call
import org.linphone.core.Core
import org.linphone.core.CoreListenerStub
import org.linphone.core.Factory
import org.linphone.core.LogLevel
import org.linphone.core.MediaEncryption
import org.linphone.core.ProxyConfig
import org.linphone.core.RegistrationState
import org.linphone.core.TransportType
import org.linphone.core.AuthInfo

class StartCallOptions : Record {
  @Field var username: String = ""
  @Field var password: String = ""
  @Field var domain: String = ""
  @Field var port: Int = 5060
  @Field var protocol: String = "tls"
  @Field var destination: String = ""
  @Field var callLimitSec: Int = 0
}

class LinphoneCallModule : Module() {
  private val TAG = "LinphoneCall"
  private var core: Core? = null
  private var listener: CoreListenerStub? = null
  private val main = Handler(Looper.getMainLooper())

  // Pending call state - wait for registration before dialing
  private var pendingPromise: Promise? = null
  private var pendingOpts: StartCallOptions? = null
  private var regTimeoutRunnable: Runnable? = null
  private val REG_TIMEOUT_MS = 20_000L // 20 seconds max for SIP registration
  private var callPlaced = false

  override fun definition() = ModuleDefinition {
    Name("LinphoneCall")
    Events("onCall")

    AsyncFunction("startCall") { options: StartCallOptions, promise: Promise ->
      try {
        ensureCore()
        registerAndCall(options, promise)
        // Promise is NOT resolved here — it resolves after SIP registration + call placed
      } catch (e: Throwable) {
        Log.e(TAG, "startCall failed", e)
        emit("failed", e.message ?: "start failed")
        clearPending()
        promise.reject("E_START", e.message ?: "start failed", e)
      }
    }

    AsyncFunction("hangup") { promise: Promise ->
      try {
        clearPending()
        val currentCall = core?.currentCall
        if (currentCall != null) {
          currentCall.terminate()
        } else {
          core?.calls?.firstOrNull()?.terminate()
        }
        promise.resolve(null)
      } catch (e: Throwable) {
        promise.reject("E_HANGUP", e.message ?: "hangup failed", e)
      }
    }

    AsyncFunction("setMute") { muted: Boolean, promise: Promise ->
      try {
        core?.isMicEnabled = !muted
        promise.resolve(null)
      } catch (e: Throwable) {
        promise.reject("E_MUTE", e.message ?: "mute failed", e)
      }
    }

    AsyncFunction("setSpeaker") { on: Boolean, promise: Promise ->
      try {
        val ctx = appContext.reactContext ?: throw IllegalStateException("no context")
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        am.mode = AudioManager.MODE_IN_COMMUNICATION
        am.isSpeakerphoneOn = on
        val targetType = if (on) AudioDevice.Type.Speaker else AudioDevice.Type.Earpiece
        core?.audioDevices?.firstOrNull { it.type == targetType && it.hasCapability(AudioDevice.Capabilities.CapabilityPlay) }
          ?.let { core?.outputAudioDevice = it }
        promise.resolve(null)
      } catch (e: Throwable) {
        promise.reject("E_SPK", e.message ?: "speaker failed", e)
      }
    }

    AsyncFunction("sendDtmf") { digit: String, promise: Promise ->
      try {
        val c = core?.currentCall ?: core?.calls?.firstOrNull()
        if (c != null && digit.isNotEmpty()) c.sendDtmf(digit[0])
        promise.resolve(null)
      } catch (e: Throwable) {
        promise.reject("E_DTMF", e.message ?: "dtmf failed", e)
      }
    }

    OnDestroy { teardown() }
  }

  private fun clearPending() {
    regTimeoutRunnable?.let { main.removeCallbacks(it) }
    regTimeoutRunnable = null
    pendingPromise = null
    pendingOpts = null
    callPlaced = false
  }

  private fun ensureCore() {
    if (core != null) return
    val ctx = appContext.reactContext ?: throw IllegalStateException("no context")
    Factory.instance().setLogCollectionPath(ctx.filesDir.absolutePath)
    Factory.instance().enableLogCollection(org.linphone.core.LogCollectionState.Enabled)
    Factory.instance().loggingService.setLogLevel(LogLevel.Message)

    val c = Factory.instance().createCore(null, null, ctx)
    c.isNetworkReachable = true

    // Configure audio settings
    c.echoCancellationEnabled = true
    c.echoLimiterEnabled = true

    c.start()
    core = c

    val l = object : CoreListenerStub() {
      override fun onCallStateChanged(core: Core, call: Call, state: Call.State, message: String) {
        Log.d(TAG, "Call state: $state ($message)")
        when (state) {
          Call.State.OutgoingInit -> emit("outgoing_init", message)
          Call.State.OutgoingProgress -> emit("outgoing_progress", message)
          Call.State.OutgoingRinging -> emit("ringing", message)
          Call.State.Connected, Call.State.StreamsRunning -> {
            emit("connected", message)
            // Stop registration timeout since call connected
            regTimeoutRunnable?.let { main.removeCallbacks(it) }
            regTimeoutRunnable = null
          }
          Call.State.End, Call.State.Released -> emit("ended", message)
          Call.State.Error -> {
            val reason = message.ifEmpty { "فشل الاتصال - حاول مرة أخرى" }
            Log.e(TAG, "Call error: $reason (raw: $message)")
            emit("failed", reason)
          }
          else -> {}
        }
      }

      override fun onRegistrationStateChanged(core: Core, cfg: ProxyConfig, state: RegistrationState, message: String) {
        Log.d(TAG, "Registration state: $state ($message)")
        when (state) {
          RegistrationState.Ok -> {
            Log.i(TAG, "SIP registration successful!")
            // Registration successful — now place the call
            main.post {
              regTimeoutRunnable?.let { main.removeCallbacks(it) }
              regTimeoutRunnable = null
              try {
                placeCall()
                callPlaced = true
                pendingPromise?.resolve(null)
                pendingPromise = null
              } catch (e: Throwable) {
                Log.e(TAG, "placeCall after reg failed", e)
                pendingPromise?.reject("E_CALL", e.message ?: "فشل بدء المكالمة", e)
                emit("failed", e.message ?: "فشل بدء المكالمة")
                pendingPromise = null
                pendingOpts = null
              }
            }
          }
          RegistrationState.Failed -> {
            Log.e(TAG, "SIP registration failed: $message")
            main.post {
              regTimeoutRunnable?.let { main.removeCallbacks(it) }
              regTimeoutRunnable = null
              val errorMsg = parseRegError(message)
              pendingPromise?.reject("E_REG", "فشل التسجيل: $errorMsg")
              emit("failed", "فشل التسجيل: $errorMsg")
              pendingPromise = null
              pendingOpts = null
            }
          }
          RegistrationState.Cleared -> {
            // Account removed, ignore
          }
          else -> {
            // Progress, None, etc. — wait
            Log.d(TAG, "SIP registration in progress: $state")
          }
        }
      }
    }
    listener = l
    c.addListener(l)
  }

  private fun parseRegError(message: String): String {
    val lower = message.lowercase()
    return when {
      lower.contains("not found") || lower.contains("404") -> "خادم SIP غير متاح - حاول بعد قليل"
      lower.contains("401") || lower.contains("unauthorized") || lower.contains("forbidden") -> "بيانات SIP غير صالحة"
      lower.contains("timeout") || lower.contains("timed out") -> "انتهت مهلة الاتصال - تحقق من الإنترنت"
      lower.contains("network") || lower.contains("unreachable") -> "لا يمكن الوصول لخادم SIP - تحقق من الإنترنت"
      lower.contains("tls") || lower.contains("ssl") || lower.contains("certificate") -> "مشكلة في الاتصال الآمن TLS"
      else -> message.ifEmpty { "خطأ غير معروف في التسجيل" }
    }
  }

  private fun emit(state: String, reason: String?) {
    main.post {
      try {
        sendEvent("onCall", mapOf("state" to state, "reason" to (reason ?: "")))
      } catch (_: Throwable) {}
    }
  }

  private fun registerAndCall(o: StartCallOptions, promise: Promise) {
    val c = core ?: throw IllegalStateException("Core not initialized")

    // Cancel any previous pending operation
    clearPending()
    pendingPromise = promise
    pendingOpts = o

    // Terminate any existing calls
    c.calls.forEach { try { it.terminate() } catch (_: Throwable) {} }

    // Clear previous accounts
    try {
      c.clearAccounts()
      c.clearProxyConfig()
    } catch (e: Throwable) {
      Log.w(TAG, "Warning clearing accounts: ${e.message}")
    }

    val transport = when (o.protocol.lowercase()) {
      "tls" -> TransportType.Tls
      "tcp" -> TransportType.Tcp
      else -> TransportType.Udp
    }

    // Create SIP identity address
    val identityStr = "sip:${o.username}@${o.domain}"
    Log.d(TAG, "Creating identity: $identityStr")
    val identity = Factory.instance().createAddress(identityStr)
    if (identity == null) {
      // Try with just username as sip URI
      Log.w(TAG, "createAddress failed for identity, trying alternative")
      throw IllegalStateException("فشل إنشاء عنوان SIP - تحقق من بيانات الاتصال")
    }

    // Create proxy address
    val proxyStr = "sip:${o.domain}:${o.port};transport=${o.protocol.lowercase()}"
    Log.d(TAG, "Creating proxy: $proxyStr")
    val proxyAddr = Factory.instance().createAddress(proxyStr)
    if (proxyAddr == null) {
      throw IllegalStateException("فشل الاتصال بخادم SIP - تأكد من صحة الرقم وحاول مرة أخرى")
    }

    // Create authentication info - use Account params instead for Linphone 5.4
    try {
      val authInfo = Factory.instance().createAuthInfo(o.username, null, o.password, null, null, o.domain)
      c.addAuthInfo(authInfo)
    } catch (e: Throwable) {
      Log.w(TAG, "createAuthInfo failed: ${e.message}, using params identity instead")
    }

    // Configure account params
    val params = c.createAccountParams()
    params.identityAddress = identity
    params.serverAddress = proxyAddr
    params.isRegisterEnabled = true

    // Configure transport
    params.transport = transport

    if (transport == TransportType.Tls) {
      c.mediaEncryption = MediaEncryption.None
      c.verifyServerCertificates(false)
      c.verifyServerCn(false)
    }

    // Set outbound proxy
    params.routingListEnabled = false

    val account = c.createAccount(params)
    c.addAccount(account)
    c.defaultAccount = account

    // Set registration timeout
    regTimeoutRunnable = Runnable {
      Log.e(TAG, "SIP registration timed out after ${REG_TIMEOUT_MS}ms")
      if (!callPlaced) {
        pendingPromise?.reject("E_REG_TIMEOUT", "انتهت مهلة التسجيل SIP - تحقق من اتصال الإنترنت وحاول مرة أخرى")
        emit("failed", "انتهت مهلة الاتصال - حاول مرة أخرى")
        pendingPromise = null
        pendingOpts = null
      }
    }
    main.postDelayed(regTimeoutRunnable!!, REG_TIMEOUT_MS)

    // Registration happens asynchronously
    emit("outgoing_init", "جاري التسجيل بخادم SIP...")
  }

  private fun placeCall() {
    val o = pendingOpts ?: throw IllegalStateException("no pending call options")
    val c = core ?: throw IllegalStateException("Core not initialized")

    // Normalize destination
    val dest = o.destination.trim().removePrefix("+")

    // Format: sip:number@domain
    val target = "sip:$dest@${o.domain}"
    Log.d(TAG, "Placing call to: $target")

    val callAddr = Factory.instance().createAddress(target)
    if (callAddr == null) {
      throw IllegalStateException("رقم غير صالح: $target")
    }

    // Create call params
    val callParams = c.createCallParams(null)
    callParams?.mediaEncryption = MediaEncryption.None

    // Enable early media
    callParams?.enableEarlyMediaSending = true

    if (callParams != null) {
      c.inviteAddressWithParams(callAddr, callParams)
    } else {
      c.inviteAddress(callAddr)
    }

    // Auto-route audio to earpiece by default
    main.post {
      try {
        val ctx = appContext.reactContext
        if (ctx != null) {
          val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
          am.mode = AudioManager.MODE_IN_COMMUNICATION
          am.isSpeakerphoneOn = false
        }
      } catch (_: Throwable) {}
    }
  }

  private fun teardown() {
    clearPending()
    try {
      core?.let { c ->
        listener?.let { c.removeListener(it) }
        c.calls.forEach { try { it.terminate() } catch (_: Throwable) {} }
        c.stop()
      }
    } catch (_: Throwable) {}
    core = null
    listener = null
  }
}
