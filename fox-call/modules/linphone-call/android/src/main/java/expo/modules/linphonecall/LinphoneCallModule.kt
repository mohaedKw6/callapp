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
import org.linphone.core.AuthInfo
import org.linphone.core.Call
import org.linphone.core.Core
import org.linphone.core.CoreListenerStub
import org.linphone.core.Factory
import org.linphone.core.LogLevel
import org.linphone.core.MediaEncryption
import org.linphone.core.ProxyConfig
import org.linphone.core.RegistrationState
import org.linphone.core.TransportType

class StartCallOptions : Record {
  @Field var username: String = ""
  @Field var password: String = ""
  @Field var domain: String = ""
  @Field var port: Int = 5060
  @Field var protocol: String = "tcp"
  @Field var destination: String = ""
  @Field var callLimitSec: Int = 0
}

class LinphoneCallModule : Module() {
  private val TAG = "LinphoneCall"
  private var core: Core? = null
  private var listener: CoreListenerStub? = null
  private val main = Handler(Looper.getMainLooper())

  // Track call state for cleanup
  private var callActive = false
  private var currentCall: Call? = null

  override fun definition() = ModuleDefinition {
    Name("LinphoneCall")
    Events("onCall")

    AsyncFunction("startCall") { options: StartCallOptions, promise: Promise ->
      try {
        ensureCore()
        directCall(options, promise)
      } catch (e: Throwable) {
        Log.e(TAG, "startCall failed", e)
        emit("failed", e.message ?: "فشل بدء المكالمة")
        callActive = false
        promise.reject("E_START", e.message ?: "start failed", e)
      }
    }

    AsyncFunction("hangup") { promise: Promise ->
      try {
        callActive = false
        val c = core
        val call = c?.currentCall ?: c?.calls?.firstOrNull()
        if (call != null) {
          call.terminate()
        }
        currentCall = null
        releaseAudioFocus()
        promise.resolve(null)
      } catch (e: Throwable) {
        promise.reject("E_HANGUP", e.message ?: "hangup failed", e)
      }
    }

    AsyncFunction("setMute") { muted: Boolean, promise: Promise ->
      try {
        core?.isMicEnabled = !muted
        Log.d(TAG, "Mic ${if (muted) "muted" else "unmuted"}")
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

        // Use Linphone API to route audio
        val c = core
        if (c != null) {
          val targetType = if (on) AudioDevice.Type.Speaker else AudioDevice.Type.Earpiece
          val cap = AudioDevice.Capabilities.CapabilityPlay
          val device = c.audioDevices.firstOrNull {
            it.type == targetType && it.hasCapability(cap)
          }
          if (device != null) {
            c.outputAudioDevice = device
            Log.d(TAG, "Audio output set to: ${device.deviceName} (${device.type})")
          } else {
            Log.w(TAG, "No ${if (on) "speaker" else "earpiece"} device found, falling back to speakerphoneOn")
          }
        }
        promise.resolve(null)
      } catch (e: Throwable) {
        promise.reject("E_SPK", e.message ?: "speaker failed", e)
      }
    }

    AsyncFunction("sendDtmf") { digit: String, promise: Promise ->
      try {
        val c = core ?: throw IllegalStateException("Core not initialized")
        val call = c.currentCall ?: c.calls.firstOrNull()
        if (call != null && digit.isNotEmpty()) {
          try { c.playDtmf(digit[0], 100) } catch (_: Throwable) {}
          call.sendDtmf(digit[0])
        }
        promise.resolve(null)
      } catch (e: Throwable) {
        promise.reject("E_DTMF", e.message ?: "dtmf failed", e)
      }
    }

    OnDestroy { teardown() }
  }

  /**
   * Initialize the Linphone Core with proper TLS and audio configuration.
   */
  private fun ensureCore() {
    if (core != null) return
    val ctx = appContext.reactContext ?: throw IllegalStateException("no context")

    // Configure Linphone factory for TLS compatibility
    try {
      Factory.instance().setLogCollectionPath(ctx.filesDir.absolutePath)
      Factory.instance().enableLogCollection(org.linphone.core.LogCollectionState.Enabled)
      Factory.instance().loggingService.setLogLevel(LogLevel.Message)
      // CRITICAL: Clear root CA to disable certificate verification for self-signed certs
      // This matches the raw SIP class behavior: ssl.CERT_NONE
      Factory.instance().setRootCa("")

      // Set debug mode for better logging
      Factory.instance().isDebugMode = true
    } catch (e: Throwable) {
      Log.w(TAG, "Factory config warning: ${e.message}")
    }

    val c = Factory.instance().createCore(null, null, ctx)
    c.isNetworkReachable = true

    // Configure audio settings - critical for call audio
    c.echoCancellationEnabled = true
    c.echoLimiterEnabled = true

    // Disable adaptive rate control for more stable audio
    try { c.isAdaptiveRateControlEnabled = false } catch (_: Throwable) {}
    try { c.preferredVideoDefinition = null } catch (_: Throwable) {} // No video

    // Audio codec preferences: PCMU and PCMA are the standard SIP codecs
    // Enable all audio codecs for maximum compatibility
    try {
      for (codec in c.audioPayloadTypes) {
        val name = codec.mimeType.lowercase()
        if (name == "pcmu" || name == "pcma" || name == "opus" ||
            name == "gsm" || name == "g722" || name == "ilbc" || name == "speex") {
          codec.enable(true)
          Log.d(TAG, "Audio codec enabled: ${codec.mimeType}/${codec.clockRate}")
        }
      }
    } catch (e: Throwable) {
      Log.w(TAG, "Audio codec configuration warning: ${e.message}")
    }

    // CRITICAL: Disable TLS certificate verification for self-signed certs
    // This matches callv2.py: context.check_hostname = False, context.verify_mode = ssl.CERT_NONE
    try {
      c.verifyServerCertificates(false)
      c.verifyServerCn(false)
      Log.d(TAG, "Server certificate verification disabled")
    } catch (e: Throwable) {
      Log.w(TAG, "verifyServerCertificates/Cn not available: ${e.message}")
    }

    // Set media encryption to None - SIP signaling over TLS but RTP audio unencrypted
    // This matches the Telicall server behavior
    c.mediaEncryption = MediaEncryption.None

    c.start()
    core = c
    Log.d(TAG, "Linphone Core created and started successfully")

    val l = object : CoreListenerStub() {
      override fun onCallStateChanged(core: Core, call: Call, state: Call.State, message: String) {
        Log.d(TAG, "Call state: $state ($message)")
        when (state) {
          Call.State.OutgoingInit -> {
            emit("outgoing_init", "جاري الاتصال...")
          }
          Call.State.OutgoingProgress -> {
            emit("outgoing_progress", "جاري الاتصال...")
          }
          Call.State.OutgoingRinging -> {
            emit("ringing", "يرن...")
          }
          Call.State.OutgoingEarlyMedia -> {
            emit("ringing", "يرن...")
          }
          Call.State.Connected -> {
            callActive = true
            currentCall = call
            // Configure audio devices after connection
            configureAudioForCall()
            emit("connected", "تم الاتصال")
          }
          Call.State.StreamsRunning -> {
            if (!callActive) {
              callActive = true
              currentCall = call
              configureAudioForCall()
            }
            emit("connected", "تم الاتصال")
          }
          Call.State.Paused -> {
            // Call paused - keep audio focus
          }
          Call.State.PausedByRemote -> {
            // Remote paused the call
          }
          Call.State.Resuming -> {
            // Call resuming
            configureAudioForCall()
          }
          Call.State.End -> {
            callActive = false
            currentCall = null
            releaseAudioFocus()
            emit("ended", "انتهت المكالمة")
          }
          Call.State.Released -> {
            callActive = false
            currentCall = null
            releaseAudioFocus()
            emit("ended", "انتهت المكالمة")
          }
          Call.State.Error -> {
            callActive = false
            currentCall = null
            releaseAudioFocus()
            val reason = parseCallError(message)
            Log.e(TAG, "Call error: $reason (raw: $message)")
            emit("failed", reason)
          }
          else -> {}
        }
      }

      override fun onRegistrationStateChanged(core: Core, cfg: ProxyConfig, state: RegistrationState, message: String) {
        // We don't use registration - log only for debugging
        Log.d(TAG, "Registration state (ignored): $state ($message)")
      }

      override fun onAudioDeviceChanged(core: Core, audioDevice: AudioDevice) {
        Log.d(TAG, "Audio device changed: ${audioDevice.deviceName} (${audioDevice.type})")
      }

      override fun onAudioDevicesListUpdated(core: Core) {
        Log.d(TAG, "Audio devices list updated")
      }

      override fun onDtmfReceived(core: Core, call: Call, dtmf: Int) {
        Log.d(TAG, "DTMF received: $dtmf")
      }
    }
    listener = l
    c.addListener(l)
  }

  /**
   * Configure audio routing when a call is active.
   * Sets up the audio manager, requests audio focus, and selects proper input/output devices.
   */
  private fun configureAudioForCall() {
    val ctx = appContext.reactContext ?: return
    val c = core ?: return

    main.post {
      try {
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager

        // Request audio focus for voice call
        @Suppress("DEPRECATION")
        val focusResult = am.requestAudioFocus(
          null,
          AudioManager.STREAM_VOICE_CALL,
          AudioManager.AUDIOFOCUS_GAIN_TRANSIENT
        )
        Log.d(TAG, "Audio focus request result: $focusResult")

        // Set audio mode for voice communication
        am.mode = AudioManager.MODE_IN_COMMUNICATION
        am.isSpeakerphoneOn = false
        am.isBluetoothScoOn = false

        // Stop any playing audio
        try { am.abandonAudioFocus(null) } catch (_: Throwable) {}
        @Suppress("DEPRECATION")
        am.requestAudioFocus(null, AudioManager.STREAM_VOICE_CALL, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)

        // Set Linphone input audio device to microphone
        val micDevice = c.audioDevices.firstOrNull {
          it.type == AudioDevice.Type.Microphone && it.hasCapability(AudioDevice.Capabilities.CapabilityRecord)
        }
        if (micDevice != null) {
          c.inputAudioDevice = micDevice
          Log.d(TAG, "Input audio device set to: ${micDevice.deviceName}")
        } else {
          Log.w(TAG, "No microphone device found!")
        }

        // Set Linphone output audio device to earpiece (default for phone calls)
        val earpieceDevice = c.audioDevices.firstOrNull {
          it.type == AudioDevice.Type.Earpiece && it.hasCapability(AudioDevice.Capabilities.CapabilityPlay)
        }
        if (earpieceDevice != null) {
          c.outputAudioDevice = earpieceDevice
          Log.d(TAG, "Output audio device set to: ${earpieceDevice.deviceName}")
        } else {
          Log.w(TAG, "No earpiece device found, trying speaker")
          val speakerDevice = c.audioDevices.firstOrNull {
            it.type == AudioDevice.Type.Speaker && it.hasCapability(AudioDevice.Capabilities.CapabilityPlay)
          }
          if (speakerDevice != null) {
            c.outputAudioDevice = speakerDevice
          }
        }

        Log.d(TAG, "Audio configured: mic=${c.inputAudioDevice?.deviceName}, speaker=${c.outputAudioDevice?.deviceName}")
      } catch (e: Throwable) {
        Log.e(TAG, "Failed to configure audio", e)
      }
    }
  }

  /**
   * Release audio focus when call ends.
   */
  private fun releaseAudioFocus() {
    val ctx = appContext.reactContext ?: return
    main.post {
      try {
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        am.mode = AudioManager.MODE_NORMAL
        am.isSpeakerphoneOn = false
        @Suppress("DEPRECATION")
        am.abandonAudioFocus(null)
      } catch (_: Throwable) {}
    }
  }

  /**
   * Request audio focus BEFORE placing the call.
   * This is critical - audio must be set up before the SIP INVITE is sent.
   */
  private fun requestAudioFocusBeforeCall() {
    val ctx = appContext.reactContext ?: return
    try {
      val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
      am.mode = AudioManager.MODE_IN_COMMUNICATION
      am.isSpeakerphoneOn = false
      am.isBluetoothScoOn = false
      @Suppress("DEPRECATION")
      am.requestAudioFocus(null, AudioManager.STREAM_VOICE_CALL, AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
      Log.d(TAG, "Audio focus requested before call")
    } catch (e: Throwable) {
      Log.w(TAG, "Failed to request audio focus: ${e.message}")
    }
  }

  private fun parseCallError(message: String): String {
    val lower = message.lowercase()
    return when {
      lower.contains("not found") || lower.contains("404") -> "الرقم غير موجود أو الخدمة غير متاحة"
      lower.contains("401") || lower.contains("unauthorized") -> "فشل المصادقة - بيانات SIP غير صالحة"
      lower.contains("403") || lower.contains("forbidden") -> "ممنوع الاتصال - تحقق من الرصيد"
      lower.contains("408") || lower.contains("timeout") || lower.contains("timed out") -> "انتهت مهلة الاتصال - تحقق من الإنترنت"
      lower.contains("480") || lower.contains("temporarily") -> "الرقم مش متاح حالياً"
      lower.contains("486") || lower.contains("busy") -> "الرقم مشغول"
      lower.contains("487") || lower.contains("cancelled") -> "تم إلغاء المكالمة"
      lower.contains("503") || lower.contains("service unavailable") -> "الخدمة غير متاحة حالياً"
      lower.contains("network") || lower.contains("unreachable") -> "لا يمكن الوصول للخادم - تحقق من الإنترنت"
      lower.contains("tls") || lower.contains("ssl") || lower.contains("certificate") -> "مشكلة في الاتصال الآمن - جرب بروتوكول TCP"
      lower.contains("declined") || lower.contains("603") -> "تم رفض المكالمة"
      lower.contains("does not exist") -> "الرقم غير صحيح"
      else -> message.ifEmpty { "فشل الاتصال - حاول مرة أخرى" }
    }
  }

  private fun emit(state: String, reason: String?) {
    main.post {
      try {
        sendEvent("onCall", mapOf("state" to state, "reason" to (reason ?: "")))
      } catch (_: Throwable) {}
    }
  }

  /**
   * KEY FIX: Direct call without SIP registration.
   * Telicall SIP servers do NOT support/require SIP registration.
   * The raw SIP class in callv2.py also connects directly without registration.
   * We create a Linphone account with registration disabled and place the call immediately.
   *
   * TLS FIX: For TLS connections, we properly configure the Linphone core to:
   * 1. Disable certificate verification (matching callv2.py's ssl.CERT_NONE)
   * 2. Use the correct transport type
   * 3. Set the server hostname for TLS SNI
   *
   * AUDIO FIX: We request audio focus BEFORE placing the call and
   * configure audio devices AFTER the call connects.
   */
  private fun directCall(o: StartCallOptions, promise: Promise) {
    val c = core ?: throw IllegalStateException("Core not initialized")

    // Terminate any existing calls
    c.calls.forEach { try { it.terminate() } catch (_: Throwable) {} }
    currentCall = null

    // Clean up previous accounts
    try {
      val existingAccounts = c.accounts.toList()
      for (account in existingAccounts) {
        try { c.removeAccount(account) } catch (_: Throwable) {}
      }
    } catch (e: Throwable) {
      Log.w(TAG, "Warning clearing accounts: ${e.message}")
    }

    // Also clear auth info
    try {
      val existingAuth = c.authInfoList.toList()
      for (auth in existingAuth) {
        try { c.removeAuthInfo(auth) } catch (_: Throwable) {}
      }
    } catch (e: Throwable) {
      Log.w(TAG, "Warning clearing auth info: ${e.message}")
    }

    val transport = when (o.protocol.lowercase()) {
      "tls" -> TransportType.Tls
      "tcp" -> TransportType.Tcp
      else -> TransportType.Udp
    }

    Log.d(TAG, "Setting up SIP call: ${o.username}@${o.domain}:${o.port} transport=${o.protocol} to=${o.destination}")

    // Create SIP identity address: sip:username@domain
    val identityStr = "sip:${o.username}@${o.domain}"
    Log.d(TAG, "Creating identity: $identityStr")
    val identity = Factory.instance().createAddress(identityStr)
    if (identity == null) {
      throw IllegalStateException("فشل إنشاء عنوان SIP - تحقق من بيانات الاتصال")
    }

    // Create proxy/server address: sip:domain:port;transport=proto
    val proxyStr = "sip:${o.domain}:${o.port};transport=${o.protocol.lowercase()}"
    Log.d(TAG, "Creating proxy: $proxyStr")
    val proxyAddr = Factory.instance().createAddress(proxyStr)
    if (proxyAddr == null) {
      throw IllegalStateException("فشل الاتصال بخادم SIP - تأكد من صحة البيانات")
    }

    // For TLS: set the server hostname for SNI (Server Name Indication)
    // This is critical for TLS connections to work with virtual hosting
    if (transport == TransportType.Tls) {
      try {
        proxyAddr.host = o.domain
        Log.d(TAG, "TLS SNI hostname set to: ${o.domain}")
      } catch (e: Throwable) {
        Log.w(TAG, "Failed to set TLS SNI hostname: ${e.message}")
      }
    }

    // Create authentication info for 401/407 challenge responses
    val authInfo = Factory.instance().createAuthInfo(
      o.username,  // username
      null,        // userid (null = same as username)
      o.password,  // password
      null,        // ha1
      null,        // realm
      o.domain     // domain
    )
    c.addAuthInfo(authInfo)
    Log.d(TAG, "Auth info added for user: ${o.username}@${o.domain}")

    // Configure account params with REGISTRATION DISABLED
    val params = c.createAccountParams()
    params.identityAddress = identity
    params.serverAddress = proxyAddr

    // KEY FIX: Disable SIP registration - Telicall servers don't support it
    params.isRegisterEnabled = false

    // Configure transport explicitly
    params.transport = transport

    // Set outbound proxy to ensure all requests go through the SIP server
    try { params.isOutboundProxyEnabled = true } catch (_: Throwable) {}

    // For better compatibility, set reasonable timeouts
    try { params.registerTimeout = 0 } catch (_: Throwable) {}

    val account = c.createAccount(params)
    c.addAccount(account)
    c.defaultAccount = account

    Log.d(TAG, "Account created and set as default (registration disabled, transport=${o.protocol})")

    // CRITICAL: Request audio focus BEFORE placing the call
    // This ensures the audio pipeline is ready when the SIP INVITE goes out
    requestAudioFocusBeforeCall()

    // Place the call immediately - no need to wait for registration
    emit("outgoing_init", "جاري الاتصال...")

    try {
      placeCall(o)
      Log.d(TAG, "Call placed successfully")
      promise.resolve(null)
    } catch (e: Throwable) {
      Log.e(TAG, "placeCall failed", e)
      releaseAudioFocus()
      emit("failed", e.message ?: "فشل بدء المكالمة")
      promise.reject("E_CALL", e.message ?: "فشل بدء المكالمة", e)
    }
  }

  private fun placeCall(o: StartCallOptions) {
    val c = core ?: throw IllegalStateException("Core not initialized")

    // Normalize destination - remove + prefix
    val dest = o.destination.trim().removePrefix("+")

    // Create call target: sip:number@domain
    val targetStr = "sip:$dest@${o.domain}"
    Log.d(TAG, "Placing call to: $targetStr")

    val callAddr = Factory.instance().createAddress(targetStr)
    if (callAddr == null) {
      throw IllegalStateException("رقم غير صالح: $dest")
    }

    // Set transport on call address to match account
    callAddr.transport = when (o.protocol.lowercase()) {
      "tls" -> TransportType.Tls
      "tcp" -> TransportType.Tcp
      else -> TransportType.Udp
    }

    // Create call params
    val callParams = c.createCallParams(null)
    if (callParams != null) {
      // Disable media encryption - RTP audio without SRTP
      // SIP signaling is secured by TLS, but media uses plain RTP
      callParams.mediaEncryption = MediaEncryption.None

      // Enable early media (ringing tone)
      callParams.enableEarlyMediaSending = true

      // Audio only - no video
      try { callParams.isVideoEnabled = false } catch (_: Throwable) {}
      try { callParams.enableVideo(false) } catch (_: Throwable) {}

      // Set audio codec preferences
      try {
        // Disable video codecs
        for (codec in c.videoPayloadTypes) {
          codec.enable(false)
        }
      } catch (_: Throwable) {}

      // Place the call with params
      c.inviteAddressWithParams(callAddr, callParams)
    } else {
      // Fallback without params
      c.inviteAddress(callAddr)
    }

    Log.d(TAG, "SIP INVITE sent successfully")
  }

  private fun teardown() {
    callActive = false
    currentCall = null
    releaseAudioFocus()
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
