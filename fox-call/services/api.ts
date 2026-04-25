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
  callId: string;
}

// ============================================================================
// Pure JavaScript HMAC-SHA256 implementation for React Native
// (React Native doesn't have Node's crypto module)
// ============================================================================

// SHA-256 round constants: first 32 bits of the fractional parts of the
// cube roots of the first 64 primes
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

// SHA-256 initial hash values: first 32 bits of the fractional parts of the
// square roots of the first 8 primes
const SHA256_H0 = new Uint32Array([
  0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
  0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
]);

/** Unsigned right-rotate of a 32-bit value */
function rr(v: number, n: number): number {
  return (v >>> n) | (v << (32 - n));
}

/** Compute SHA-256 hash of a Uint8Array, returning 32 bytes */
function sha256(data: Uint8Array): Uint8Array {
  const msgLen = data.length;
  const bitLen = msgLen * 8;

  // Pad message: append 0x80, then zeros, then 64-bit big-endian length
  const padLen = 64 - ((msgLen + 1 + 8) % 64 || 64);
  const totalLen = msgLen + 1 + padLen + 8;

  const buf = new Uint8Array(totalLen);
  buf.set(data);
  buf[msgLen] = 0x80;

  const dv = new DataView(buf.buffer);
  dv.setUint32(totalLen - 4, bitLen, false); // big-endian low 32 bits

  // Initialize hash state
  const h = new Uint32Array(SHA256_H0);

  // Process each 512-bit (64-byte) block
  for (let off = 0; off < totalLen; off += 64) {
    const w = new Uint32Array(64);

    // First 16 words from the block (big-endian)
    for (let i = 0; i < 16; i++) {
      w[i] = dv.getUint32(off + i * 4, false);
    }

    // Extend to 64 words
    for (let i = 16; i < 64; i++) {
      const s0 = rr(w[i - 15], 7) ^ rr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rr(w[i - 2], 17) ^ rr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
    }

    // Initialize working variables
    let a = h[0], b = h[1], c = h[2], d = h[3];
    let e = h[4], f = h[5], g = h[6], hh = h[7];

    // 64-round compression
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

    // Add compressed chunk to hash state
    h[0] = (h[0] + a) | 0;
    h[1] = (h[1] + b) | 0;
    h[2] = (h[2] + c) | 0;
    h[3] = (h[3] + d) | 0;
    h[4] = (h[4] + e) | 0;
    h[5] = (h[5] + f) | 0;
    h[6] = (h[6] + g) | 0;
    h[7] = (h[7] + hh) | 0;
  }

  // Produce 32-byte digest (big-endian)
  const out = new Uint8Array(32);
  const ov = new DataView(out.buffer);
  for (let i = 0; i < 8; i++) {
    ov.setUint32(i * 4, h[i], false);
  }
  return out;
}

/** Convert a Uint8Array to lowercase hex string */
function toHex(bytes: Uint8Array): string {
  let hex = '';
  for (let i = 0; i < bytes.length; i++) {
    hex += ('0' + bytes[i].toString(16)).slice(-2);
  }
  return hex;
}

/**
 * Compute HMAC-SHA256(key, message) and return the result as a hex string.
 * Both key and message are UTF-8 encoded strings.
 */
function hmacSha256(key: string, message: string): string {
  const enc = new TextEncoder();
  let keyBytes = enc.encode(key);

  // If key exceeds block size (64 bytes), hash it first
  if (keyBytes.length > 64) {
    keyBytes = sha256(keyBytes);
  }

  // Pad key to 64 bytes with trailing zeros
  const padded = new Uint8Array(64);
  padded.set(keyBytes);

  // XOR key with ipad (0x36) and opad (0x5c)
  const ipad = new Uint8Array(64);
  const opad = new Uint8Array(64);
  for (let i = 0; i < 64; i++) {
    ipad[i] = padded[i] ^ 0x36;
    opad[i] = padded[i] ^ 0x5c;
  }

  const msgBytes = enc.encode(message);

  // Inner hash: SHA-256(ipad || message)
  const innerData = new Uint8Array(64 + msgBytes.length);
  innerData.set(ipad);
  innerData.set(msgBytes, 64);
  const innerHash = sha256(innerData);

  // Outer hash: SHA-256(opad || innerHash)
  const outerData = new Uint8Array(64 + 32);
  outerData.set(opad);
  outerData.set(innerHash, 64);

  return toHex(sha256(outerData));
}

// ============================================================================
// FoxApi — JWT-authenticated API client
// ============================================================================

const SHARED_SECRET = 'FOXCALL_2026_SHARED_SECRET_v1';

interface AuthResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user_id: string;
}

interface RefreshResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

export class FoxApi {
  private serverUrl: string;
  private rawToken: string;
  private deviceId: string;

  // JWT tokens (stored in memory only — never persisted)
  private accessToken: string | null = null;
  private refreshToken: string | null = null;
  private tokenExpiresAt = 0;

  // Call tracking
  private currentCallId: string | null = null;

  constructor(token: FoxTokenInfo, deviceId: string, rawToken: string) {
    this.serverUrl = token.serverUrl.replace(/\/+$/, '');
    this.rawToken = rawToken;
    this.deviceId = deviceId;
  }

  static fromToken(rawToken: string, deviceId: string): FoxApi | null {
    const info = decodeFoxToken(rawToken);
    if (!info) return null;
    return new FoxApi(info, deviceId, rawToken);
  }

  // ------------------------------------------------------------------ Auth

  /** Authenticate with the server and obtain JWT tokens */
  async login(): Promise<void> {
    const res = await this.unauthenticatedReq<AuthResponse>(
      'POST',
      '/api/auth/login',
      { token: this.rawToken, device_id: this.deviceId },
    );
    this.accessToken = res.access_token;
    this.refreshToken = res.refresh_token;
    // Refresh 30 seconds before actual expiry to avoid edge cases
    this.tokenExpiresAt = Date.now() + (res.expires_in - 30) * 1000;
  }

  /** Refresh the access token using the stored refresh token */
  private async refreshAccessToken(): Promise<void> {
    const res = await this.unauthenticatedReq<RefreshResponse>(
      'POST',
      '/api/auth/refresh',
      { refresh_token: this.refreshToken },
    );
    this.accessToken = res.access_token;
    this.refreshToken = res.refresh_token;
    this.tokenExpiresAt = Date.now() + (res.expires_in - 30) * 1000;
  }

  /** Make sure we have a valid (non-expired) access token */
  private async ensureToken(): Promise<void> {
    if (this.accessToken && Date.now() < this.tokenExpiresAt) return;
    // Try refresh first (cheaper than full login)
    if (this.refreshToken) {
      try {
        await this.refreshAccessToken();
        return;
      } catch {
        // Refresh failed — fall through to full login
      }
    }
    await this.login();
  }

  // ------------------------------------------------------------------ Headers

  /** Compute x-signature as HMAC-SHA256(access_token + requestBody, SHARED_SECRET) */
  private computeSignature(requestBody: string): string {
    const message = (this.accessToken ?? '') + requestBody;
    return hmacSha256(SHARED_SECRET, message);
  }

  /** Build authenticated request headers (Bearer token + signature) */
  private authHeaders(body?: string): Record<string, string> {
    const h: Record<string, string> = {
      'Authorization': `Bearer ${this.accessToken}`,
      'content-type': 'application/json',
    };
    if (body !== undefined) {
      h['x-signature'] = this.computeSignature(body);
    }
    return h;
  }

  // ------------------------------------------------------------------ Fetch helpers

  /** Request that does NOT require authentication (login / refresh) */
  private async unauthenticatedReq<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<T> {
    const url = `${this.serverUrl}${path}`;
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
      let data: any = {};
      try { data = text ? JSON.parse(text) : {}; } catch { /* not json */ }
      if (!res.ok) {
        throw new Error(data?.error || `خطأ ${res.status}`);
      }
      return data as T;
    } catch (e: any) {
      if (e.name === 'AbortError') {
        throw new Error('انقطع الاتصال بالسيرفر');
      }
      throw e;
    } finally {
      clearTimeout(timer);
    }
  }

  /** Low-level fetch with given headers */
  private async doFetch(
    method: string,
    path: string,
    headers: Record<string, string>,
    body?: string,
  ): Promise<Response> {
    const url = `${this.serverUrl}${path}`;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 10000);
    try {
      return await fetch(url, { method, headers, body, signal: ctrl.signal });
    } finally {
      clearTimeout(timer);
    }
  }

  /** Authenticated request with automatic 401 → token refresh → retry */
  private async req<T>(method: string, path: string, body?: unknown): Promise<T> {
    await this.ensureToken();

    const bodyStr = body ? JSON.stringify(body) : undefined;
    let lastErr: Error = new Error('تعذّر الاتصال بالسيرفر');

    // --- First attempt ---
    let res: Response | null = null;
    try {
      res = await this.doFetch(method, path, this.authHeaders(bodyStr), bodyStr);
    } catch (e: any) {
      if (e.name === 'AbortError') {
        throw new Error('انقطع الاتصال بالسيرفر');
      }
      lastErr = e;
    }

    // --- Auto-refresh on 401 ---
    if (res && res.status === 401 && this.refreshToken) {
      try {
        await this.refreshAccessToken();
        res = await this.doFetch(method, path, this.authHeaders(bodyStr), bodyStr);
      } catch (e: any) {
        if (e.name === 'AbortError') {
          throw new Error('انقطع الاتصال بالسيرفر');
        }
        lastErr = e;
        res = null;
      }
    }

    if (!res) throw lastErr;

    const text = await res.text();
    let data: any = {};
    try { data = text ? JSON.parse(text) : {}; } catch { /* not json */ }

    if (!res.ok) {
      throw new Error(data?.error || `خطأ ${res.status}`);
    }

    return data as T;
  }

  // ------------------------------------------------------------------ Public API

  getMe() {
    return this.req<UserInfo>('GET', '/api/me');
  }

  getBalance() {
    return this.req<{ balance: number; cost: number }>('GET', '/api/balance');
  }

  async startCall(to: string): Promise<CallStartResult> {
    // Server returns snake_case; map to our camelCase interface
    const raw: any = await this.req('POST', '/api/call/start', { to });
    const res: CallStartResult = {
      sip: raw.sip,
      from: raw.from,
      to: raw.to,
      balance: raw.balance,
      callId: raw.call_id ?? raw.callId,
    };
    this.currentCallId = res.callId;
    return res;
  }

  endCall(callId?: string, duration?: number) {
    const id = callId ?? this.currentCallId;
    this.currentCallId = null;
    return this.req<{ ok: boolean }>('POST', '/api/call/end', {
      call_id: id,
      duration,
    });
  }

  /** Get the current call_id (if a call is active) */
  getCallId(): string | null {
    return this.currentCallId;
  }
}
