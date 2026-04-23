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
import org.linphone.core.TransportType

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

  override fun definition() = ModuleDefinition {
    Name("LinphoneCall")
    Events("onCall")

    AsyncFunction("startCall") { options: StartCallOptions, promise: Promise ->
      try {
        ensureCore()
        registerAndCall(options)
        promise.resolve(null)
      } catch (e: Throwable) {
        Log.e(TAG, "startCall failed", e)
        promise.reject("E_START", e.message ?: "start failed", e)
      }
    }

    AsyncFunction("hangup") { promise: Promise ->
      try {
        core?.currentCall?.terminate() ?: core?.calls?.firstOrNull()?.terminate()
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
        // Try to also set in linphone
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

  private fun ensureCore() {
    if (core != null) return
    val ctx = appContext.reactContext ?: throw IllegalStateException("no context")
    Factory.instance().setLogCollectionPath(ctx.filesDir.absolutePath)
    Factory.instance().enableLogCollection(org.linphone.core.LogCollectionState.Enabled)
    Factory.instance().loggingService.setLogLevel(LogLevel.Message)

    val c = Factory.instance().createCore(null, null, ctx)
    c.isNetworkReachable = true
    // Audio codecs preference: keep PCMA/PCMU/Opus enabled
    c.start()
    core = c

    val l = object : CoreListenerStub() {
      override fun onCallStateChanged(core: Core, call: Call, state: Call.State?, message: String?) {
        Log.d(TAG, "Call state: $state ($message)")
        when (state) {
          Call.State.OutgoingInit -> emit("outgoing_init", message)
          Call.State.OutgoingProgress -> emit("outgoing_progress", message)
          Call.State.OutgoingRinging -> emit("ringing", message)
          Call.State.Connected, Call.State.StreamsRunning -> emit("connected", message)
          Call.State.End, Call.State.Released -> emit("ended", message)
          Call.State.Error -> emit("failed", message ?: "call failed")
          else -> {}
        }
      }
    }
    listener = l
    c.addListener(l)
  }

  private fun emit(state: String, reason: String?) {
    main.post {
      try {
        sendEvent("onCall", mapOf("state" to state, "reason" to (reason ?: "")))
      } catch (_: Throwable) {}
    }
  }

  private fun registerAndCall(o: StartCallOptions) {
    val c = core ?: throw IllegalStateException("Core not initialized")

    // Clear previous accounts
    c.clearAccounts()
    c.clearProxyConfig()
    c.clearAllAuthInfo()

    val transport = when (o.protocol.lowercase()) {
      "tls" -> TransportType.Tls
      "tcp" -> TransportType.Tcp
      else -> TransportType.Udp
    }

    val identity = Factory.instance().createAddress("sip:${o.username}@${o.domain}")
      ?: throw IllegalStateException("invalid identity")
    val proxyAddr = Factory.instance().createAddress("sip:${o.domain}:${o.port};transport=${o.protocol.lowercase()}")
      ?: throw IllegalStateException("invalid proxy")

    val authInfo = Factory.instance().createAuthInfo(
      o.username, null, o.password, null, null, o.domain
    )
    c.addAuthInfo(authInfo)

    val params = c.createAccountParams()
    params.identityAddress = identity
    params.serverAddress = proxyAddr
    params.isRegisterEnabled = true
    if (transport == TransportType.Tls) {
      c.mediaEncryption = MediaEncryption.None
      c.isVerifyServerCertificates = false
      c.isVerifyServerCn = false
    }

    val account = c.createAccount(params)
    c.addAccount(account)
    c.defaultAccount = account

    // Place the call to the destination (E.164 or local)
    val dest = if (o.destination.startsWith("+") || o.destination.startsWith("sip:")) {
      o.destination.removePrefix("+")
    } else o.destination
    val target = "sip:$dest@${o.domain}"
    val callAddr = Factory.instance().createAddress(target)
      ?: throw IllegalStateException("invalid destination")

    val callParams = c.createCallParams(null)
    callParams?.mediaEncryption = MediaEncryption.None

    if (callParams != null) c.inviteAddressWithParams(callAddr, callParams)
    else c.inviteAddress(callAddr)

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
