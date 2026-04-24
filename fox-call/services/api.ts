import { decodeFoxToken, FoxTokenInfo } from './foxToken';

export interface UserInfo {
  userId: string;
  username: string;
  fullName: string;
  balance: number;
  cost: number;
  possibleCalls: number;
}

export interface SipCreds {
  username: string;
  password: string;
  domain: string;
  port: number;
  protocol: 'tls' | 'tcp' | 'udp';
  callLimit: number;
}

export interface CallStartResult {
  sip: SipCreds;
  from: string;
  to: string;
  balance: number;
}

export class FoxApi {
  private serverUrl: string;
  private userId: string;
  private deviceId: string;

  constructor(token: FoxTokenInfo, deviceId: string) {
    this.serverUrl = token.serverUrl.replace(/\/+$/, '');
    this.userId = token.userId;
    this.deviceId = deviceId;
  }

  static fromToken(rawToken: string, deviceId: string): FoxApi | null {
    const info = decodeFoxToken(rawToken);
    if (!info) return null;
    return new FoxApi(info, deviceId);
  }

  private headers(): Record<string, string> {
    return {
      'x-user-id': this.userId,
      'x-device-id': this.deviceId,
      'content-type': 'application/json',
    };
  }

  private async fetchOne(baseUrl: string, method: string, path: string, body?: unknown): Promise<Response> {
    const url = `${baseUrl}${path}`;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 10000);
    try {
      return await fetch(url, {
        method,
        headers: this.headers(),
        body: body ? JSON.stringify(body) : undefined,
        signal: ctrl.signal,
      });
    } finally {
      clearTimeout(timer);
    }
  }

  private async req<T>(method: string, path: string, body?: unknown): Promise<T> {
    const baseUrl = this.serverUrl;
    let lastErr: Error = new Error('تعذّر الاتصال بالسيرفر');

    try {
      const res = await this.fetchOne(baseUrl, method, path, body);
      const text = await res.text();
      let data: any = {};
      try { data = text ? JSON.parse(text) : {}; } catch { /* not json */ }
      if (!res.ok) {
        const msg = data?.error || `خطأ ${res.status}`;
        throw new Error(msg);
      }
      return data as T;
    } catch (e: any) {
      if (e.name === 'AbortError') {
        lastErr = new Error('انقطع الاتصال بالسيرفر');
      } else {
        lastErr = e;
      }
    }
    throw lastErr;
  }

  getMe() {
    return this.req<UserInfo>('GET', '/api/me');
  }

  getBalance() {
    return this.req<{ balance: number; cost: number }>('GET', '/api/balance');
  }

  startCall(to: string) {
    return this.req<CallStartResult>('POST', '/api/call/start', { to });
  }

  endCall(callId?: string, duration?: number) {
    return this.req<{ ok: boolean }>('POST', '/api/call/end', { callId, duration });
  }
}
