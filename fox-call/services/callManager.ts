import { FoxApi, SipCreds, CallStartResult } from './api';
import LinphoneCall, { CallEvent } from '../modules/linphone-call';

export type CallState = 'idle' | 'connecting' | 'ringing' | 'connected' | 'ended' | 'failed';

interface Listener {
  onState?: (s: CallState) => void;
  onDuration?: (sec: number) => void;
  onError?: (msg: string) => void;
  onEnd?: () => void;
}

export class CallManager {
  private api: FoxApi;
  private listener: Listener = {};
  private state: CallState = 'idle';
  private startedAt = 0;
  private timer: ReturnType<typeof setInterval> | null = null;
  private currentCall: CallStartResult | null = null;
  private muted = false;
  private speaker = false;
  private nativeUnsub: (() => void) | null = null;

  constructor(api: FoxApi) {
    this.api = api;
  }

  on(l: Listener) { this.listener = l; }

  isMuted() { return this.muted; }
  isSpeaker() { return this.speaker; }
  getState() { return this.state; }
  getCallInfo() { return this.currentCall; }

  private setState(s: CallState) {
    this.state = s;
    this.listener.onState?.(s);
  }

  async startCall(to: string, retries = 2): Promise<CallStartResult> {
    this.setState('connecting');
    let lastError: string = '';

    for (let attempt = 0; attempt <= retries; attempt++) {
      let res: CallStartResult;
      try {
        res = await this.api.startCall(to);
        this.currentCall = res;

        // Check if Linphone native module is available
        if (!LinphoneCall.isAvailable()) {
          this.setState('failed');
          this.listener.onError?.('الوحدة الصوتية غير متاحة - يجب تثبيت نسخة محدثة من التطبيق');
          throw new Error('Linphone module not available');
        }

        // Subscribe to native call events
        this.nativeUnsub = LinphoneCall.addCallListener((evt: CallEvent) => {
          console.log('[CallManager] Native event:', evt.state, evt.reason);
          if (evt.state === 'ringing' || evt.state === 'outgoing_progress') {
            this.setState('ringing');
          } else if (evt.state === 'outgoing_init') {
            // Still connecting, keep state
          } else if (evt.state === 'connected') {
            this.setState('connected');
            this.startedAt = Date.now();
            this.startTimer();
          } else if (evt.state === 'ended') {
            this.cleanup('ended');
          } else if (evt.state === 'failed') {
            const reason = evt.reason || 'فشل الاتصال';
            console.error('[CallManager] Call failed:', reason);
            this.listener.onError?.(reason);
            this.cleanup('failed');
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
          this.setState('ringing');
          return res;
        } catch (e: any) {
          const errMsg = e?.message || 'فشل تشغيل الصوت';
          const friendly = this.translateError(errMsg);
          console.error('[CallManager] Linphone startCall error:', errMsg);

          // If this is the last attempt, show error
          if (attempt >= retries) {
            this.listener.onError?.(friendly);
            this.cleanup('failed');
            throw e;
          }

          lastError = friendly;
          console.log(`[CallManager] Retry ${attempt + 1}/${retries} after error: ${errMsg}`);
          await new Promise(r => setTimeout(r, 1500));
        }
      } catch (e: any) {
        const errMsg = e?.message || 'فشل بدء المكالمة';
        lastError = this.translateError(errMsg);

        // If this is the last attempt or non-retryable error
        if (attempt >= retries) {
          this.setState('failed');
          this.listener.onError?.(lastError);
          throw e;
        }

        console.log(`[CallManager] API retry ${attempt + 1}/${retries}: ${errMsg}`);
        await new Promise(r => setTimeout(r, 1500));
      }

    // All retries exhausted
    this.setState('failed');
    this.listener.onError?.(lastError || 'فشل الاتصال بعد عدة محاولات');
    throw new Error(lastError || 'فشل الاتصال بعد عدة محاولات');
  }

  private translateError(msg: string): string {
    const lower = msg.toLowerCase();

    // Check for specific error patterns first (before generic checks)
    // Account used before errors
    if (lower.includes('used') || lower.includes('already') || lower.includes('استعمل')) {
      return 'هذا الحساب مستعمل قبل كده - جاري تجربة حساب آخر';
    }
    // No balance errors
    if (lower.includes('no_balance') || lower.includes('رصيدك مش كافي') || lower.includes('balance') || lower.includes('رصيد')) {
      if (lower.includes('telicall')) {
        return 'حساب Telicall خلص رصيده - جاري تجربة حساب آخر';
      }
      return 'رصيدك مش كافي لإجراء مكالمة';
    }
    // No accounts available
    if (lower.includes('no accounts') || lower.includes('لا يوجد') || lower.includes('لا توجد') || lower.includes('حسابات')) {
      return 'مفيش حسابات متاحة حالياً - حاول لاحقاً';
    }
    // Network errors
    if (lower.includes('network') || lower.includes('unreachable') || lower.includes('timeout') || lower.includes('connection')) {
      return 'تعذر الاتصال بالخادم - تحقق من اتصال الإنترنت';
    }
    // SIP registration errors
    if (lower.includes('registration') || lower.includes('reg')) {
      return 'فشل التسجيل بخادم SIP - حاول مرة أخرى';
    }
    // TLS/SSL errors
    if (lower.includes('tls') || lower.includes('ssl') || lower.includes('certificate')) {
      return 'مشكلة في الاتصال الآمن - حاول مرة أخرى';
    }
    // Not found / 404
    if (lower.includes('not found') || lower.includes('404') || lower.includes('غير متاحة')) {
      return 'الخدمة غير متاحة حالياً - حاول بعد قليل';
    }
    // Service unavailable
    if (lower.includes('unavailable') || lower.includes('غير متاح') || lower.includes('غير موجودة')) {
      return 'الخدمة غير متاحة حالياً - حاول بعد قليل';
    }
    // Module errors
    if (lower.includes('module') || lower.includes('native')) {
      return 'التطبيق يحتاج تحديث - حمّل النسخة الأحدث';
    }
    // Telicall specific errors
    if (lower.includes('telicall')) {
      return 'خطأ في خدمة Telicall - حاول مرة أخرى';
    }
    // Internal server error
    if (lower.includes('500') || lower.includes('server error') || lower.includes('خطأ في')) {
      return 'خطأ في السيرفر - جربي بعد شوية';
    }
    // Default - return original with friendly message
    if (msg && msg.length > 0 && msg.length < 200) {
      return msg;
    }
    return 'حدث خطأ غير متوقع - حاول مرة أخرى';
  }

  private startTimer() {
    if (this.timer) clearInterval(this.timer);
    this.timer = setInterval(() => {
      const sec = Math.floor((Date.now() - this.startedAt) / 1000);
      this.listener.onDuration?.(sec);
      const limit = this.currentCall?.sip.callLimit ?? 0;
      if (limit > 0 && sec >= limit) this.hangup();
    }, 1000);
  }

  async hangup() {
    try { await LinphoneCall.hangup(); } catch {}
    this.cleanup('ended');
  }

  async toggleMute() {
    this.muted = !this.muted;
    try { await LinphoneCall.setMute(this.muted); } catch {}
    return this.muted;
  }

  async toggleSpeaker() {
    this.speaker = !this.speaker;
    try { await LinphoneCall.setSpeaker(this.speaker); } catch {}
    return this.speaker;
  }

  async sendDtmf(d: string) {
    try { await LinphoneCall.sendDtmf(d); } catch {}
  }

  private cleanup(finalState: CallState) {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    if (this.nativeUnsub) {
      this.nativeUnsub();
      this.nativeUnsub = null;
    }
    const dur = this.startedAt ? Math.floor((Date.now() - this.startedAt) / 1000) : 0;
    const callId = this.currentCall?.callId;
    this.api.endCall(callId, dur).catch(() => {});
    this.startedAt = 0;
    this.muted = false;
    this.speaker = false;
    this.setState(finalState);
    this.listener.onEnd?.();
  }

  destroy() {
    this.cleanup('idle');
    this.currentCall = null;
  }
}
