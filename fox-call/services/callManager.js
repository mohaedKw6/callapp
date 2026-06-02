import LinphoneCall from '../modules/linphone-call';

const REUSE_LIMIT = 3; // Max reuse attempts for same number on no-answer

export class CallManager {
  constructor(api) {
    this._api = api;
    this._listener = {};
    this._state = 'idle';
    this._startedAt = 0;
    this._wasAnswered = false; // Track if call was actually answered
    this._timer = null;
    this._currentCall = null;
    this._muted = false;
    this._speaker = false;
    this._nativeUnsub = null;
    this._reuseCount = 0; // How many times we've retried the same number
    this._lastNumber = ''; // Last called number for reuse tracking
  }

  on(l) { this._listener = l; }

  isMuted() { return this._muted; }
  isSpeaker() { return this._speaker; }
  getState() { return this._state; }
  getCallInfo() { return this._currentCall; }
  getReuseCount() { return this._reuseCount; }
  getLastNumber() { return this._lastNumber; }

  _setState(s) {
    this._state = s;
    this._listener.onState?.(s);
  }

  async startCall(to, retries = 2) {
    // Track number reuse
    if (to === this._lastNumber) {
      this._reuseCount++;
    } else {
      this._reuseCount = 0;
      this._lastNumber = to;
    }

    // If we've reused this number too many times, reset and let the app fetch a new number
    if (this._reuseCount > REUSE_LIMIT) {
      this._reuseCount = 0;
      this._listener.onMaxReuse?.();
    }

    this._setState('connecting');
    this._wasAnswered = false; // Reset for new call
    let lastError = '';

    for (let attempt = 0; attempt <= retries; attempt++) {
      let res;
      try {
        res = await this._api.startCall(to);
        this._currentCall = res;

        // Check if Linphone native module is available
        if (!LinphoneCall.isAvailable()) {
          this._setState('failed');
          this._listener.onError?.('الوحدة الصوتية غير متاحة - يجب تثبيت نسخة محدثة من التطبيق');
          throw new Error('Linphone module not available');
        }

        // Subscribe to native call events
        this._nativeUnsub = LinphoneCall.addCallListener((evt) => {
          console.log('[CallManager] Native event:', evt.state, evt.reason);
          if (evt.state === 'ringing' || evt.state === 'outgoing_progress') {
            this._setState('ringing');
          } else if (evt.state === 'outgoing_init') {
            // Still connecting, keep state
          } else if (evt.state === 'connected') {
            this._wasAnswered = true; // Mark as answered BEFORE any reset
            this._setState('connected');
            this._startedAt = Date.now();
            this._startTimer();
          } else if (evt.state === 'ended') {
            this._cleanup('ended');
          } else if (evt.state === 'failed') {
            const reason = evt.reason || 'فشل الاتصال';
            console.error('[CallManager] Call failed:', reason);
            this._listener.onError?.(reason);
            this._cleanup('failed');
          }
        });

        try {
          await LinphoneCall.startCall({
            username: res.sip.username,
            password: res.sip.password,
            domain: res.sip.domain,
            port: res.sip.port,
            protocol: res.sip.protocol,
            destination: to.replace(/^\+/, ''),
            callLimitSec: res.sip.callLimit,
          });
          this._setState('ringing');
          return res;
        } catch (e) {
          const errMsg = e?.message || 'فشل تشغيل الصوت';
          const friendly = this._translateError(errMsg);
          console.error('[CallManager] Linphone startCall error:', errMsg);

          // If this is the last attempt, show error
          if (attempt >= retries) {
            this._listener.onError?.(friendly);
            this._cleanup('failed');
            throw e;
          }

          lastError = friendly;
          console.log('[CallManager] Retry ' + (attempt + 1) + '/' + retries + ' after error: ' + errMsg);
          await new Promise(r => setTimeout(r, 1500));
        }
      } catch (e) {
        const errMsg = e?.message || 'فشل بدء المكالمة';
        lastError = this._translateError(errMsg);

        // If this is the last attempt or non-retryable error
        if (attempt >= retries) {
          this._setState('failed');
          this._listener.onError?.(lastError);
          throw e;
        }

        console.log('[CallManager] API retry ' + (attempt + 1) + '/' + retries + ': ' + errMsg);
        await new Promise(r => setTimeout(r, 1500));
      }

    } // end for loop

    // All retries exhausted
    this._setState('failed');
    this._listener.onError?.(lastError || 'فشل الاتصال بعد عدة محاولات');
    throw new Error(lastError || 'فشل الاتصال بعد عدة محاولات');
  }

  _translateError(msg) {
    const lower = msg.toLowerCase();

    // Check for specific error patterns first (before generic checks)
    if (lower.includes('used') || lower.includes('already') || lower.includes('استعمل')) {
      return 'هذا الحساب مستعمل قبل كده - جاري تجربة حساب آخر';
    }
    if (lower.includes('رصيدك مش كافي') || (lower.includes('رصيدك') && lower.includes('كافي'))) {
      return 'رصيدك مش كافي لإجراء مكالمة';
    }
    if (lower.includes('no_balance') || lower.includes('الحساب المستخدم لا يحتوي على رصيد')) {
      return 'حساب المكالمات خلص رصيده - حاول بعد شوية';
    }
    if (lower.includes('فشل الاتصال من جهازك') || lower.includes('فشل الطلب من جهازك')) {
      return 'فشل الاتصال من جهازك - حاول مرة أخرى';
    }
    if (lower.includes('انقطع الاتصال بخادم المكالمات')) {
      return 'انقطع الاتصال بخادم المكالمات - حاول مرة أخرى';
    }
    if (lower.includes('no accounts') || lower.includes('لا يوجد') || lower.includes('لا توجد') || lower.includes('حسابات')) {
      return 'مفيش حسابات متاحة حالياً - حاول لاحقاً';
    }
    if (lower.includes('network') || lower.includes('unreachable') || lower.includes('timeout') || lower.includes('connection')) {
      return 'تعذر الاتصال بالخادم - تحقق من اتصال الإنترنت';
    }
    if (lower.includes('registration') || lower.includes('reg')) {
      return 'فشل التسجيل بخادم SIP - حاول مرة أخرى';
    }
    if (lower.includes('tls') || lower.includes('ssl') || lower.includes('certificate')) {
      return 'مشكلة في الاتصال الآمن - حاول مرة أخرى';
    }
    if (lower.includes('not found') || lower.includes('404') || lower.includes('غير متاحة')) {
      return 'الخدمة غير متاحة حالياً - حاول بعد قليل';
    }
    if (lower.includes('unavailable') || lower.includes('غير متاح') || lower.includes('غير موجودة')) {
      return 'الخدمة غير متاحة حالياً - حاول بعد قليل';
    }
    if (lower.includes('module') || lower.includes('native')) {
      return 'التطبيق يحتاج تحديث - حمّل النسخة الأحدث';
    }
    if (lower.includes('call_')) {
      return 'خطأ في خدمة المكالمات - حاول مرة أخرى';
    }
    if (lower.includes('500') || lower.includes('server error') || lower.includes('خطأ في')) {
      return 'خطأ في السيرفر - جربي بعد شوية';
    }
    if (msg && msg.length > 0 && msg.length < 200) {
      return msg;
    }
    return 'حدث خطأ غير متوقع - حاول مرة أخرى';
  }

  _startTimer() {
    if (this._timer) clearInterval(this._timer);
    this._timer = setInterval(() => {
      const sec = Math.floor((Date.now() - this._startedAt) / 1000);
      this._listener.onDuration?.(sec);
      const limit = this._currentCall?.sip.callLimit ?? 0;
      if (limit > 0 && sec >= limit) this.hangup();
    }, 1000);
  }

  async hangup() {
    try { await LinphoneCall.hangup(); } catch {}
    this._cleanup('ended');
  }

  async toggleMute() {
    this._muted = !this._muted;
    try { await LinphoneCall.setMute(this._muted); } catch {}
    return this._muted;
  }

  async toggleSpeaker() {
    this._speaker = !this._speaker;
    try { await LinphoneCall.setSpeaker(this._speaker); } catch {}
    return this._speaker;
  }

  async setAudioOutput(outputType) {
    try {
      await LinphoneCall.setAudioOutput(outputType);
      this._speaker = outputType === 'speaker';
    } catch {}
    return outputType;
  }

  async getAudioDevices() {
    try {
      return await LinphoneCall.getAudioDevices();
    } catch {
      return [];
    }
  }

  async sendDtmf(d) {
    try { await LinphoneCall.sendDtmf(d); } catch {}
  }

  _cleanup(finalState) {
    // Capture wasAnswered BEFORE resetting _startedAt
    const wasAnswered = this._wasAnswered;

    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
    if (this._nativeUnsub) {
      this._nativeUnsub();
      this._nativeUnsub = null;
    }
    const dur = this._startedAt ? Math.floor((Date.now() - this._startedAt) / 1000) : 0;
    const callId = this._currentCall?.callId;

    // If call ended but was never answered (duration = 0), report as failed
    if (finalState === 'ended' && !wasAnswered && dur === 0) {
      console.log('[CallManager] Call ended without being answered - marking as failed');
      this._api.markCallFailed?.(callId).catch(() => {});
    } else {
      this._api.endCall(callId, dur).catch(() => {});
    }

    // Reset state
    this._startedAt = 0;
    this._wasAnswered = false;
    this._muted = false;
    this._speaker = false;
    this._setState(finalState);
    this._listener.onEnd?.({
      wasAnswered,
      duration: dur,
      reuseCount: this._reuseCount,
    });
  }

  destroy() {
    this._cleanup('idle');
    this._currentCall = null;
  }
}
