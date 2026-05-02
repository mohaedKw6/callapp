package expo.modules.linphonecall

import android.content.Context
import android.media.AudioManager
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
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
  private var callActive = false
  private var audioInitialized = false

  override fun definition() = ModuleDefinition {
    Name("LinphoneCall")
    Events("onCall")

    AsyncFunction("startCall") { options: StartCallOptions, promise: Promise ->
      try {
        ensureCore()
        initializeAudioPipeline()
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
        val currentCall = core?.currentCall
        if (currentCall != null) {
          currentCall.terminate()
        } else {
          core?.calls?.firstOrNull()?.terminate()
        }
        releaseAudioFocus()
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

    AsyncFunction("setAudioOutput") { outputType: String, promise: Promise ->
      try {
        val ctx = appContext.reactContext ?: throw IllegalStateException("no context")
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        am.mode = AudioManager.MODE_IN_COMMUNICATION
        val c = core ?: throw IllegalStateException("core not initialized")
        val targetType = when (outputType) {
          "earpiece" -> AudioDevice.Type.Earpiece
          "speaker" -> {
            am.isSpeakerphoneOn = true
            AudioDevice.Type.Speaker
          }
          "bluetooth" -> AudioDevice.Type.Bluetooth
          else -> AudioDevice.Type.Earpiece
        }
        if (outputType != "speaker") am.isSpeakerphoneOn = false
        val device = c.audioDevices.firstOrNull {
          it.type == targetType && it.hasCapability(AudioDevice.Capabilities.CapabilityPlay)
        }
        if (device != null) {
          c.outputAudioDevice = device
          Log.d(TAG, "Audio output set to: ${device.deviceName} (type: $outputType)")
        } else {
          Log.w(TAG, "No audio device found for type: $outputType")
        }
        promise.resolve(null)
      } catch (e: Throwable) {
        promise.reject("E_AUDIO_OUT", e.message ?: "setAudioOutput failed", e)
      }
    }

    AsyncFunction("getAudioDevices") { promise: Promise ->
      try {
        val c = core ?: throw IllegalStateException("core not initialized")
        val devices = c.audioDevices
          .filter { it.hasCapability(AudioDevice.Capabilities.CapabilityPlay) }
          .map { mapOf("id" to it.id, "name" to it.deviceName, "type" to it.type.name, "isOutput" to true) }
        promise.resolve(devices)
      } catch (e: Throwable) {
        promise.reject("E_AUDIO_LIST", e.message ?: "getAudioDevices failed", e)
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

  private fun ensureCore() {
    if (core != null) return
    val ctx = appContext.reactContext ?: throw IllegalStateException("no context")
    
    // Enable logging for debugging
    Factory.instance().setLogCollectionPath(ctx.filesDir.absolutePath)
    Factory.instance().enableLogCollection(org.linphone.core.LogCollectionState.Enabled)
    Factory.instance().loggingService.setLogLevel(LogLevel.Debug)

    // CRITICAL FIX: Disable TLS certificate verification
    // This matches callv2.py: context.check_hostname = False, context.verify_mode = ssl.CERT_NONE
    // Note: Factory.setRootCa() removed in Linphone SDK 5.x - we handle this on Core instead

    val c = Factory.instance().createCore(null, null, ctx)
    c.isNetworkReachable = true

    // Configure audio settings - echo cancellation for better call quality
    c.setEchoCancellationEnabled(true)
    c.setEchoLimiterEnabled(true)

    // CRITICAL FIX: Disable TLS certificate verification for self-signed certs
    // In Linphone SDK 5.4.x, verifyServerCertificates/verifyServerCn are method calls
    try {
      c.verifyServerCertificates(false)
      Log.d(TAG, "Server certificate verification disabled")
    } catch (e: Throwable) {
      Log.w(TAG, "verifyServerCertificates not available: ${e.message}")
    }
    try {
      c.verifyServerCn(false)
      Log.d(TAG, "Server CN verification disabled")
    } catch (e: Throwable) {
      Log.w(TAG, "verifyServerCn not available: ${e.message}")
    }
    try {
      c.rootCa = ""
      Log.d(TAG, "Root CA cleared for TLS")
    } catch (e: Throwable) {
      Log.w(TAG, "rootCa not available: ${e.message}")
    }

    // Set media encryption to None
    c.mediaEncryption = MediaEncryption.None

    c.start()
    core = c

    val l = object : CoreListenerStub() {
      override fun onCallStateChanged(core: Core, call: Call, state: Call.State, message: String) {
        Log.d(TAG, "Call state: $state ($message)")
        when (state) {
          Call.State.OutgoingInit -> emit("outgoing_init", "جاري الاتصال...")
          Call.State.OutgoingProgress -> emit("outgoing_progress", "جاري الاتصال...")
          Call.State.OutgoingRinging -> emit("ringing", "يرن...")
          Call.State.OutgoingEarlyMedia -> emit("ringing", "يرن...")
          Call.State.Connected -> {
            callActive = true
            configureAudioForCall()
            emit("connected", "تم الاتصال")
          }
          Call.State.StreamsRunning -> {
            if (!callActive) {
              callActive = true
              configureAudioForCall()
            }
            emit("connected", "تم الاتصال")
          }
          Call.State.End, Call.State.Released -> {
            callActive = false
            releaseAudioFocus()
            emit("ended", "انتهت المكالمة")
          }
          Call.State.Error -> {
            callActive = false
            releaseAudioFocus()
            val reason = parseCallError(message)
            Log.e(TAG, "Call error: $reason (raw: $message)")
            emit("failed", reason)
          }
          Call.State.IncomingReceived -> {
            emit("ringing", "مكالمة واردة...")
          }
          Call.State.PushIncomingReceived -> {
            emit("ringing", "مكالمة واردة...")
          }
          else -> {}
        }
      }

      override fun onRegistrationStateChanged(core: Core, cfg: ProxyConfig, state: RegistrationState, message: String) {
        Log.d(TAG, "Registration state: $state ($message)")
        when (state) {
          RegistrationState.Ok -> Log.d(TAG, "SIP registered successfully")
          RegistrationState.Failed -> Log.w(TAG, "SIP registration failed: $message")
          RegistrationState.Cleared -> Log.d(TAG, "SIP registration cleared")
          RegistrationState.Progress -> Log.d(TAG, "SIP registration in progress...")
          else -> Log.d(TAG, "SIP registration state: $state")
        }
      }
      
      override fun onAudioDevicesListUpdated(core: Core) {
        Log.d(TAG, "Audio devices list updated")
        // Refresh audio devices when list changes
        if (audioInitialized) {
          configureAudioForCall()
        }
      }
    }
    listener = l
    c.addListener(l)
  }

  /**
   * Initialize audio pipeline with proper timing.
   * This is CRITICAL for call success - audio must be ready BEFORE SIP INVITE.
   */
  private fun initializeAudioPipeline() {
    val ctx = appContext.reactContext ?: return
    val c = core ?: return
    
    main.post {
      try {
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        am.mode = AudioManager.MODE_IN_COMMUNICATION
        
        // Request audio focus
        @Suppress("DEPRECATION")
        val result = am.requestAudioFocus(
          null, 
          AudioManager.STREAM_VOICE_CALL, 
          AudioManager.AUDIOFOCUS_GAIN_TRANSIENT
        )
        Log.d(TAG, "Audio focus request result: $result")
        
        // CRITICAL: Wait for audio pipeline to initialize
        // Linphone needs ~300-500ms after audio focus before sending SIP INVITE
        SystemClock.sleep(400)
        
        // Pre-select audio devices
        val micDevice = c.audioDevices.firstOrNull {
          it.type == AudioDevice.Type.Microphone && it.hasCapability(AudioDevice.Capabilities.CapabilityRecord)
        }
        if (micDevice != null) {
          c.inputAudioDevice = micDevice
          Log.d(TAG, "Pre-selected mic: ${micDevice.deviceName}")
        }
        
        val outputDevice = c.audioDevices.firstOrNull {
          (it.type == AudioDevice.Type.Earpiece || it.type == AudioDevice.Type.Speaker) 
          && it.hasCapability(AudioDevice.Capabilities.CapabilityPlay)
        }
        if (outputDevice != null) {
          c.outputAudioDevice = outputDevice
          Log.d(TAG, "Pre-selected output: ${outputDevice.deviceName}")
        }
        
        audioInitialized = true
        Log.d(TAG, "Audio pipeline initialized successfully")
        
      } catch (e: Throwable) {
        Log.e(TAG, "Failed to initialize audio pipeline", e)
        audioInitialized = false
      }
    }
  }

  /**
   * Configure audio routing when a call connects.
   * Prioritizes Bluetooth if connected, then earpiece.
   */
  private fun configureAudioForCall() {
    val ctx = appContext.reactContext ?: return
    val c = core ?: return
    main.post {
      try {
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        am.mode = AudioManager.MODE_IN_COMMUNICATION
        am.isSpeakerphoneOn = false

        // Set Linphone input audio device to microphone
        val micDevice = c.audioDevices.firstOrNull {
          it.type == AudioDevice.Type.Microphone && it.hasCapability(AudioDevice.Capabilities.CapabilityRecord)
        }
        if (micDevice != null) {
          c.inputAudioDevice = micDevice
          Log.d(TAG, "Input audio set to: ${micDevice.deviceName}")
        }

        // Priority: Bluetooth > Earpiece (if Bluetooth headset is connected)
        val btDevice = c.audioDevices.firstOrNull {
          it.type == AudioDevice.Type.Bluetooth && it.hasCapability(AudioDevice.Capabilities.CapabilityPlay)
        }
        if (btDevice != null) {
          c.outputAudioDevice = btDevice
          am.startBluetoothSco()
          am.isBluetoothScoOn = true
          Log.d(TAG, "Output audio set to Bluetooth: ${btDevice.deviceName}")
        } else {
          // Set Linphone output audio device to earpiece
          val earpieceDevice = c.audioDevices.firstOrNull {
            it.type == AudioDevice.Type.Earpiece && it.hasCapability(AudioDevice.Capabilities.CapabilityPlay)
          }
          if (earpieceDevice != null) {
            c.outputAudioDevice = earpieceDevice
            Log.d(TAG, "Output audio set to: ${earpieceDevice.deviceName}")
          }
        }

        Log.d(TAG, "Audio configured for call")
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
        // Stop Bluetooth SCO if it was started
        try {
          am.stopBluetoothSco()
          am.isBluetoothScoOn = false
        } catch (_: Throwable) {}
        @Suppress("DEPRECATION")
        am.abandonAudioFocus(null)
        audioInitialized = false
        Log.d(TAG, "Audio focus released")
      } catch (_: Throwable) {}
    }
  }

  private fun parseCallError(message: String): String {
    val lower = message.lowercase()
    return when {
      lower.contains("not found") || lower.contains("404") || lower.contains("user not found") -> "الرقم غير موجود أو الخدمة غير متاحة"
      lower.contains("401") || lower.contains("unauthorized") || lower.contains("auth") -> "فشل المصادقة - بيانات SIP غير صالحة"
      lower.contains("403") || lower.contains("forbidden") || lower.contains("not allowed") -> "ممنوع الاتصال - تحقق من الرصيد أو الحساب"
      lower.contains("408") || lower.contains("timeout") || lower.contains("timed out") || lower.contains("request timeout") -> "انتهت مهلة الاتصال - تحقق من الإنترنت"
      lower.contains("480") || lower.contains("temporarily") || lower.contains("not available") -> "الرقم مش متاح حالياً"
      lower.contains("486") || lower.contains("busy") -> "الرقم مشغول"
      lower.contains("487") || lower.contains("cancelled") || lower.contains("cancel") -> "تم إلغاء المكالمة"
      lower.contains("503") || lower.contains("service unavailable") || lower.contains("unavailable") -> "الخدمة غير متاحة حالياً - الحساب قد يكون معطلاً"
      lower.contains("rejected") -> "تم رفض الاتصال"
      lower.contains("declined") -> "تم رفض المكالمة"
      lower.contains("network") || lower.contains("unreachable") || lower.contains("no route") -> "لا يمكن الوصول للخادم - تحقق من الإنترنت"
      lower.contains("tls") || lower.contains("ssl") || lower.contains("certificate") || lower.contains("cert") -> "مشكلة في الاتصال الآمن - تأكد من إعدادات TLS"
      lower.contains("socket") || lower.contains("connection") || lower.contains("connect") -> "خطأ في الاتصال - تحقق من الشبكة"
      lower.contains("destruction") || lower.contains("terminated") -> "انتهت المكالمة"
      lower.contains("no match") || lower.contains("no candidate") || lower.contains("ice") -> "فشل في إنشاء الاتصال الصوتي"
      lower.contains("declined") -> "تم رفض المكالمة"
      else -> message.ifEmpty { "فشل الاتصال - حاول مرة أخرى" }.let { "خطأ: $it" }
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
   * Place a call via SIP with registration enabled.
   * The server requires REGISTER (with auth) before accepting INVITE.
   */
  private fun directCall(o: StartCallOptions, promise: Promise) {
    val c = core ?: throw IllegalStateException("Core not initialized")

    // Terminate any existing calls
    c.calls.forEach { try { it.terminate() } catch (_: Throwable) {} }

    // Clean up previous accounts
    try {
      val existingAccounts = c.accountList
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

    // CRITICAL FIX: Try TLS first, fallback to TCP if TLS fails
    // Many networks block port 5061 (TLS), so TCP is more reliable
    var lastError: String? = null
    val protocols = listOf(o.protocol.lowercase(), "tcp") // Try original first, then TCP fallback

    for (proto in protocols) {
      try {
        val transport = when (proto) {
          "tls" -> TransportType.Tls
          "tcp" -> TransportType.Tcp
          else -> TransportType.Udp
        }

        Log.d(TAG, "Trying protocol: $proto for domain ${o.domain}")

        // Create SIP identity address: sip:username@domain
        val identityStr = "sip:${o.username}@${o.domain}"
        Log.d(TAG, "Creating identity: $identityStr")
        val identity = Factory.instance().createAddress(identityStr)
        if (identity == null) {
          throw IllegalStateException("فشل إنشاء عنوان SIP - تحقق من بيانات الاتصال")
        }

        // Create proxy/server address: sip:domain:port;transport=proto
        val proxyStr = "sip:${o.domain}:${o.port};transport=$proto"
        Log.d(TAG, "Creating proxy: $proxyStr")
        val proxyAddr = Factory.instance().createAddress(proxyStr)
        if (proxyAddr == null) {
          throw IllegalStateException("فشل الاتصال بخادم SIP - تأكد من صحة البيانات")
        }

        // Create authentication info
        val authInfo = Factory.instance().createAuthInfo(
          o.username,
          null,
          o.password,
          null,
          null,
          o.domain
        )
        c.addAuthInfo(authInfo)
        Log.d(TAG, "Auth info added for user: ${o.username}@${o.domain}")

        // Configure account params
        val params = c.createAccountParams()
        params.identityAddress = identity
        params.serverAddress = proxyAddr

        // Enable SIP registration — server requires REGISTER before INVITE.
        // The server challenges with 401; Linphone auto-responds using AuthInfo.
        params.isRegisterEnabled = true

        // Configure transport
        params.transport = transport

        // Note: registerTimeout/regExpires not available in Linphone SDK 5.4.x AccountParams API
        // Registration expiry uses the SDK default (600 seconds)

        val account = c.createAccount(params)
        c.addAccount(account)
        c.defaultAccount = account

        Log.d(TAG, "Account created with protocol $proto (registration enabled)")

        // Wait for audio pipeline to be ready
        if (!audioInitialized) {
          Log.d(TAG, "Waiting for audio pipeline initialization...")
          SystemClock.sleep(300)
        }

        // Emit connecting state
        emit("outgoing_init", "جاري الاتصال...")

        // Wait for registration with timeout
        val regTimeout = 10000 // 10 seconds for registration
        val regStart = System.currentTimeMillis()
        var registered = false

        while (System.currentTimeMillis() - regStart < regTimeout) {
          val state = account?.state
          Log.d(TAG, "Registration state: $state")
          if (state == RegistrationState.Ok) {
            registered = true
            break
          } else if (state == RegistrationState.Failed) {
            break
          }
          SystemClock.sleep(200)
        }

        if (!registered) {
          Log.w(TAG, "Registration not completed in time, attempting call anyway...")
        }

        try {
          placeCall(o)
          Log.d(TAG, "Call placed successfully with protocol $proto")
          promise.resolve(null)
          return
        } catch (e: Throwable) {
          lastError = e.message
          Log.e(TAG, "Call failed with protocol $proto: ${e.message}")
          // Clear account and try next protocol
          try { c.removeAccount(account) } catch (_: Throwable) {}
        }
      } catch (e: Throwable) {
        lastError = e.message
        Log.e(TAG, "Setup failed with protocol $proto: ${e.message}")
      }
    }

    // All protocols failed
    releaseAudioFocus()
    val errorMsg = lastError ?: "فشل الاتصال بجميع البروتوكولات"
    emit("failed", errorMsg)
    promise.reject("E_CALL", errorMsg, Exception(errorMsg))
  }

  private fun placeCall(o: StartCallOptions) {
    val c = core ?: throw IllegalStateException("Core not initialized")

    // CRITICAL FIX: Telicall SIP server requires + prefix in destination
    // The bot (callv2.py) always sends: sip:+{number}@{domain}
    // So we must ensure the + prefix is present
    val rawDest = o.destination.trim().removePrefix("+")
    val targetStr = "sip:+$rawDest@${o.domain}"
    Log.d(TAG, "Placing call to: $targetStr")

    val callAddr = Factory.instance().createAddress(targetStr)
    if (callAddr == null) {
      throw IllegalStateException("رقم غير صالح: $rawDest")
    }

    // Create call params
    val callParams = c.createCallParams(null)
    callParams?.mediaEncryption = MediaEncryption.None
    callParams?.setEarlyMediaSendingEnabled(true)

    // Place the call
    if (callParams != null) {
      c.inviteAddressWithParams(callAddr, callParams)
    } else {
      c.inviteAddress(callAddr)
    }

    Log.d(TAG, "SIP INVITE sent to $targetStr")
  }

  private fun teardown() {
    callActive = false
    audioInitialized = false
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