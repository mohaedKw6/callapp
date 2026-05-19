import { decodeFoxToken } from './foxToken';

// ============================================================================
// Pure JavaScript HMAC-SHA256 implementation for React Native
// (React Native doesn't have Node's crypto module)
// ============================================================================

const SHA256_K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
  0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
  0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
  0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
  0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
  0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

const SHA256_H0 = new Uint32Array([
  0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
  0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
]);

function rr(v, n) {
  return (v >>> n) | (v << (32 - n));
}

function sha256(data) {
  const msgLen = data.length;
  const bitLen = msgLen * 8;
  const padLen = 64 - ((msgLen + 1 + 8) % 64 || 64);
  const totalLen = msgLen + 1 + padLen + 8;

  const buf = new Uint8Array(totalLen);
  buf.set(data);
  buf[msgLen] = 0x80;

  const dv = new DataView(buf.buffer);
  dv.setUint32(totalLen - 4, bitLen, false);

  const h = new Uint32Array(SHA256_H0);

  for (let off = 0; off < totalLen; off += 64) {
    const w = new Uint32Array(64);
    for (let i = 0; i < 16; i++) {
      w[i] = dv.getUint32(off + i * 4, false);
    }
    for (let i = 16; i < 64; i++) {
      const s0 = rr(w[i - 15], 7) ^ rr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rr(w[i - 2], 17) ^ rr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
    }

    let a = h[0], b = h[1], c = h[2], d = h[3];
    let e = h[4], f = h[5], g = h[6], hh = h[7];

    for (let i = 0; i < 64; i++) {
      const S1 = rr(e, 6) ^ rr(e, 11) ^ rr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const t1 = (hh + S1 + ch + SHA256_K[i] + w[i]) | 0;
      const S0 = rr(a, 2) ^ rr(a, 13) ^ rr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) | 0;

      hh = g; g = f; f = e; e = (d + t1) | 0;
      d = c; c = b; b = a; a = (t1 + t2) | 0;
    }

    h[0] = (h[0] + a) | 0;
    h[1] = (h[1] + b) | 0;
    h[2] = (h[2] + c) | 0;
    h[3] = (h[3] + d) | 0;
    h[4] = (h[4] + e) | 0;
    h[5] = (h[5] + f) | 0;
    h[6] = (h[6] + g) | 0;
    h[7] = (h[7] + hh) | 0;
  }

  const out = new Uint8Array(32);
  const ov = new DataView(out.buffer);
  for (let i = 0; i < 8; i++) {
    ov.setUint32(i * 4, h[i], false);
  }
  return out;
}

function toHex(bytes) {
  let hex = '';
  for (let i = 0; i < bytes.length; i++) {
    hex += ('0' + bytes[i].toString(16)).slice(-2);
  }
  return hex;
}

function hmacSha256(key, message) {
  const enc = new TextEncoder();
  let keyBytes = enc.encode(key);

  if (keyBytes.length > 64) {
    keyBytes = sha256(keyBytes);
  }

  const padded = new Uint8Array(64);
  padded.set(keyBytes);

  const ipad = new Uint8Array(64);
  const opad = new Uint8Array(64);
  for (let i = 0; i < 64; i++) {
    ipad[i] = padded[i] ^ 0x36;
    opad[i] = padded[i] ^ 0x5c;
  }

  const msgBytes = enc.encode(message);

  const innerData = new Uint8Array(64 + msgBytes.length);
  innerData.set(ipad);
  innerData.set(msgBytes, 64);
  const innerHash = sha256(innerData);

  const outerData = new Uint8Array(64 + 32);
  outerData.set(opad);
  outerData.set(innerHash, 64);

  return toHex(sha256(outerData));
}

// ============================================================================
// FoxApi — JWT-authenticated API client
// ============================================================================

const SHARED_SECRET = 'FOXCALL_2026_SHARED_SECRET_v1';

export class FoxApi {
  constructor(token, deviceId, rawToken) {
    this._serverUrl = token.serverUrl.replace(/\/+$/, '');
    this._rawToken = rawToken;
    this._deviceId = deviceId;
    this._accessToken = null;
    this._refreshToken = null;
    this._tokenExpiresAt = 0;
    this._currentCallId = null;
  }

  static fromToken(rawToken, deviceId) {
    const info = decodeFoxToken(rawToken);
    if (!info) return null;
    return new FoxApi(info, deviceId, rawToken);
  }

  /** Decode a Fox Token without creating an API instance (for version check). */
  static decodeTokenOnly(rawToken) {
    return decodeFoxToken(rawToken);
  }

  /** Get the server URL this API instance is connected to. */
  getServerUrl() {
    return this._serverUrl;
  }

  // ------------------------------------------------------------------ Auth

  async login() {
    const res = await this._unauthenticatedReq(
      'POST',
      '/api/auth/login',
      { token: this._rawToken, device_id: this._deviceId },
    );
    this._accessToken = res.access_token;
    this._refreshToken = res.refresh_token;
    this._tokenExpiresAt = Date.now() + (res.expires_in - 30) * 1000;
  }

  async _refreshAccessToken() {
    const res = await this._unauthenticatedReq(
      'POST',
      '/api/auth/refresh',
      { refresh_token: this._refreshToken },
    );
    this._accessToken = res.access_token;
    this._refreshToken = res.refresh_token;
    this._tokenExpiresAt = Date.now() + (res.expires_in - 30) * 1000;
  }

  async _ensureToken() {
    if (this._accessToken && Date.now() < this._tokenExpiresAt) return;
    if (this._refreshToken) {
      try {
        await this._refreshAccessToken();
        return;
      } catch (e) {
        // If token was changed, don't try to login with old token — propagate the error
        if (e?.isTokenChanged) throw e;
        // Refresh failed — fall through to full login
      }
    }
    await this.login();
  }

  // ------------------------------------------------------------------ Headers

  _computeSignature(requestBody) {
    const timestamp = Math.floor(Date.now() / 1000).toString();
    const nonce = this._generateNonce();
    // Include timestamp + nonce in signature to prevent replay attacks
    const message = (this._accessToken ?? '') + timestamp + nonce + requestBody;
    const sig = hmacSha256(SHARED_SECRET, message);
    return { sig, timestamp, nonce };
  }

  _generateNonce() {
    const chars = '0123456789abcdef';
    let nonce = '';
    for (let i = 0; i < 16; i++) nonce += chars[Math.floor(Math.random() * 16)];
    return nonce;
  }

  _authHeaders(body) {
    const h = {
      'Authorization': 'Bearer ' + this._accessToken,
      'content-type': 'application/json',
    };
    // Compute signature with timestamp and nonce for anti-replay protection
    const { sig, timestamp, nonce } = this._computeSignature(body ?? '');
    h['x-signature'] = sig;
    h['x-timestamp'] = timestamp;
    h['x-nonce'] = nonce;
    return h;
  }

  // ------------------------------------------------------------------ Fetch helpers

  async _unauthenticatedReq(method, path, body) {
    const url = this._serverUrl + path;
    const bodyStr = body ? JSON.stringify(body) : undefined;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 10000);
    try {
      const res = await fetch(url, {
        method,
        headers: { 'content-type': 'application/json' },
        body: bodyStr,
        signal: ctrl.signal,
      });
      const text = await res.text();
      let data = {};
      try { data = text ? JSON.parse(text) : {}; } catch { /* not json */ }
      if (!res.ok) {
        // Check for token_changed error from server
        if (data?.error === 'token_changed') {
          const err = new Error(data?.message || 'تم تغيير التوكن برجاء ادخال التوكن الجديد');
          err.isTokenChanged = true;
          throw err;
        }
        throw new Error(data?.message || data?.error || 'خطأ ' + res.status);
      }
      return data;
    } catch (e) {
      if (e.name === 'AbortError') {
        throw new Error('انقطع الاتصال بالسيرفر');
      }
      throw e;
    } finally {
      clearTimeout(timer);
    }
  }

  async _doFetch(method, path, headers, body, timeoutMs = 10000) {
    const url = this._serverUrl + path;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      return await fetch(url, { method, headers, body, signal: ctrl.signal });
    } finally {
      clearTimeout(timer);
    }
  }

  async _req(method, path, body, timeoutMs) {
    await this._ensureToken();

    const bodyStr = body ? JSON.stringify(body) : undefined;
    let lastErr = new Error('تعذّر الاتصال بالسيرفر');

    let res = null;
    try {
      res = await this._doFetch(method, path, this._authHeaders(bodyStr), bodyStr, timeoutMs);
    } catch (e) {
      if (e.name === 'AbortError') {
        throw new Error('انقطع الاتصال بالسيرفر');
      }
      lastErr = e;
    }

    if (res && res.status === 401) {
      // First, check if it's a token_changed error (cannot be fixed by refresh)
      const preText = await res.clone().text();
      let preData = {};
      try { preData = preText ? JSON.parse(preText) : {}; } catch {}
      if (preData?.error === 'token_changed') {
        // Token was revoked by a new token generation — must re-enter new token
        const err = new Error(preData?.message || 'تم تغيير التوكن برجاء ادخال التوكن الجديد');
        err.isTokenChanged = true;
        throw err;
      }

      // Try refresh token for other 401 errors
      if (this._refreshToken) {
        try {
          await this._refreshAccessToken();
          res = await this._doFetch(method, path, this._authHeaders(bodyStr), bodyStr, timeoutMs);
        } catch (e) {
          if (e.name === 'AbortError') {
            throw new Error('انقطع الاتصال بالسيرفر');
          }
          // If refresh also fails with token_changed, propagate it
          if (e?.isTokenChanged) throw e;
          lastErr = e;
          res = null;
        }
      }
    }

    if (!res) throw lastErr;

    const text = await res.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch { /* not json */ }

    if (!res.ok) {
      // Check for token_changed in the final response too
      if (data?.error === 'token_changed') {
        const err = new Error(data?.message || 'تم تغيير التوكن برجاء ادخال التوكن الجديد');
        err.isTokenChanged = true;
        throw err;
      }
      throw new Error(data?.error || data?.message || 'خطأ ' + res.status);
    }

    return data;
  }

  // ------------------------------------------------------------------ Token management (for SecureStore persistence)

  getTokens() {
    return { accessToken: this._accessToken, refreshToken: this._refreshToken };
  }

  setTokens(access, refresh) {
    this._accessToken = access;
    this._refreshToken = refresh;
    this._tokenExpiresAt = Date.now() + 7 * 24 * 3600 * 1000; // 7 days default
  }

  // ------------------------------------------------------------------ Public API

  getMe() {
    return this._req('GET', '/api/me');
  }

  getBalance() {
    return this._req('GET', '/api/balance');
  }

  async startCall(to) {
    // ⏱️ زيادة timeout لمسار المكالمة لأن السيرفر ممكن يحاول أكتر من توكن
    const raw = await this._req('POST', '/api/call/start', { to }, 45000);

    // لو السيرفر طلب بروكسي (الطلب يتعمل من آي بي المستخدم)
    if (raw.proxy_required && raw.proxy_request) {
      return await this._handleProxyCall(raw);
    }

    const res = {
      sip: raw.sip,
      from: raw.from,
      to: raw.to,
      balance: raw.balance,
      callId: raw.call_id ?? raw.callId,
    };
    this._currentCallId = res.callId;
    return res;
  }

  async _handleProxyCall(proxyData) {
    // عمل طلب المكالمة من آي بي المستخدم بدل السيرفر
    const { url, method, headers, body } = proxyData.proxy_request;
    const emailUsed = proxyData.email_used || '';

    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 30000);
      const response = await fetch(url, {
        method: method || 'POST',
        headers: headers,
        body: JSON.stringify(body),
        signal: ctrl.signal,
      });
      clearTimeout(timer);

      const text = await response.text();
      let responseBody;
      try {
        responseBody = text ? JSON.parse(text) : {};
      } catch {
        responseBody = text;
      }

      // إرسال النتيجة للسيرفر
      const result = await this._req('POST', '/api/call/proxy-result', {
        status_code: response.status,
        response_body: responseBody,
        email_used: emailUsed,
      });

      const res = {
        sip: result.sip,
        from: result.from,
        to: result.to,
        balance: result.balance,
        callId: result.call_id ?? result.callId,
      };
      this._currentCallId = res.callId;
      return res;
    } catch (e) {
      if (e.name === 'AbortError') {
        throw new Error('انقطع الاتصال بخادم المكالمات');
      }
      throw new Error('فشل الاتصال من جهازك - حاول مرة أخرى');
    }
  }

  endCall(callId, duration) {
    const id = callId ?? this._currentCallId;
    this._currentCallId = null;
    return this._req('POST', '/api/call/end', {
      call_id: id,
      duration,
    });
  }

  markCallFailed(callId) {
    const id = callId ?? this._currentCallId;
    this._currentCallId = null;
    return this._req('POST', '/api/call/end', {
      call_id: id,
      duration: 0,
      failed: true,
    }).catch(() => {});
  }

  getCallId() {
    return this._currentCallId;
  }

  // ------------------------------------------------------------------ Call History

  getCallHistory() {
    return this._req('GET', '/api/call-history');
  }

  // ------------------------------------------------------------------ Call Recording

  setRecording(callId, record) {
    const id = callId ?? this._currentCallId;
    return this._req('POST', '/api/call/recording', {
      call_id: id,
      record,
    });
  }

  // ------------------------------------------------------------------ Security Strike Reporting

  reportStrike(reason, details = '') {
    return this._req('POST', '/api/security/strike', { reason, details });
  }

  getSecurityStatus() {
    return this._req('GET', '/api/security/status');
  }

}
