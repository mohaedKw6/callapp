// Token v2 format: `<userId>:<base64url(xor(payload, K_user))>`
// payload = `<userId>|<serverUrl>|<nonce>|<hmac16>`
// K_user  = SHA256("FOXCALL_2026_SHARED_SECRET_v1:" + userId) (32 bytes)
// hmac16  = first 16 hex chars of HMAC-SHA256(K_user, "<userId>|<serverUrl>|<nonce>")
// Must stay in lockstep with bot/foxapp_api.py.
//
// All crypto is inlined (no external deps) for maximum React Native compatibility.

const SHARED_SECRET = 'FOXCALL_2026_SHARED_SECRET_v1';

// ─── UTF-8 ────────────────────────────────────────────────────────────────
function utf8Encode(s: string): Uint8Array {
  const out: number[] = [];
  for (let i = 0; i < s.length; i++) {
    let c = s.charCodeAt(i);
    if (c < 0x80) {
      out.push(c);
    } else if (c < 0x800) {
      out.push(0xc0 | (c >> 6), 0x80 | (c & 0x3f));
    } else if (c < 0xd800 || c >= 0xe000) {
      out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 0x3f), 0x80 | (c & 0x3f));
    } else {
      // surrogate pair
      i++;
      const c2 = s.charCodeAt(i);
      const code = 0x10000 + (((c & 0x3ff) << 10) | (c2 & 0x3ff));
      out.push(
        0xf0 | (code >> 18),
        0x80 | ((code >> 12) & 0x3f),
        0x80 | ((code >> 6) & 0x3f),
        0x80 | (code & 0x3f)
      );
    }
  }
  return new Uint8Array(out);
}

function utf8Decode(bytes: Uint8Array): string {
  let s = '';
  let i = 0;
  while (i < bytes.length) {
    const b = bytes[i++];
    if (b < 0x80) {
      s += String.fromCharCode(b);
    } else if (b < 0xc0) {
      // invalid lead byte — treat as latin-1
      s += String.fromCharCode(b);
    } else if (b < 0xe0) {
      const b2 = bytes[i++] & 0x3f;
      s += String.fromCharCode(((b & 0x1f) << 6) | b2);
    } else if (b < 0xf0) {
      const b2 = bytes[i++] & 0x3f;
      const b3 = bytes[i++] & 0x3f;
      s += String.fromCharCode(((b & 0x0f) << 12) | (b2 << 6) | b3);
    } else {
      const b2 = bytes[i++] & 0x3f;
      const b3 = bytes[i++] & 0x3f;
      const b4 = bytes[i++] & 0x3f;
      let code = ((b & 0x07) << 18) | (b2 << 12) | (b3 << 6) | b4;
      code -= 0x10000;
      s += String.fromCharCode(0xd800 + (code >> 10), 0xdc00 + (code & 0x3ff));
    }
  }
  return s;
}

// ─── base64url ────────────────────────────────────────────────────────────
const B64_CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';

function b64urlDecode(s: string): Uint8Array {
  let str = s.replace(/-/g, '+').replace(/_/g, '/');
  while (str.length % 4) str += '=';
  // Build lookup
  const lut = new Int8Array(256).fill(-1);
  const std = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  for (let i = 0; i < std.length; i++) lut[std.charCodeAt(i)] = i;
  const out: number[] = [];
  for (let i = 0; i < str.length; i += 4) {
    const v0 = lut[str.charCodeAt(i)];
    const v1 = lut[str.charCodeAt(i + 1)];
    const v2 = str.charCodeAt(i + 2) === 61 ? -1 : lut[str.charCodeAt(i + 2)];
    const v3 = str.charCodeAt(i + 3) === 61 ? -1 : lut[str.charCodeAt(i + 3)];
    out.push((v0 << 2) | (v1 >> 4));
    if (v2 !== -1) out.push(((v1 & 0x0f) << 4) | (v2 >> 2));
    if (v3 !== -1) out.push(((v2 & 0x03) << 6) | v3);
  }
  return new Uint8Array(out);
}

function b64urlEncode(bytes: Uint8Array): string {
  let str = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i];
    const b1 = i + 1 < bytes.length ? bytes[i + 1] : 0;
    const b2 = i + 2 < bytes.length ? bytes[i + 2] : 0;
    str += B64_CHARS[b0 >> 2];
    str += B64_CHARS[((b0 & 0x03) << 4) | (b1 >> 4)];
    if (i + 1 < bytes.length) str += B64_CHARS[((b1 & 0x0f) << 2) | (b2 >> 6)];
    if (i + 2 < bytes.length) str += B64_CHARS[b2 & 0x3f];
  }
  return str;
}

// ─── SHA-256 (pure JS, FIPS 180-4) ────────────────────────────────────────
const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
  0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
  0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
  0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
  0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
  0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

function rotr(x: number, n: number): number {
  return ((x >>> n) | (x << (32 - n))) >>> 0;
}

function sha256Bytes(msg: Uint8Array): Uint8Array {
  const ml = msg.length;
  const bitLen = ml * 8;
  // Padding: append 0x80, then zeros, then 64-bit big-endian length
  const padLen = (((ml + 9 + 63) >> 6) << 6); // round up to multiple of 64
  const buf = new Uint8Array(padLen);
  buf.set(msg, 0);
  buf[ml] = 0x80;
  // big-endian 64-bit length (we only fill low 32 bits)
  buf[padLen - 4] = (bitLen >>> 24) & 0xff;
  buf[padLen - 3] = (bitLen >>> 16) & 0xff;
  buf[padLen - 2] = (bitLen >>> 8) & 0xff;
  buf[padLen - 1] = bitLen & 0xff;

  let h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a;
  let h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19;

  const w = new Uint32Array(64);
  for (let off = 0; off < padLen; off += 64) {
    for (let t = 0; t < 16; t++) {
      const i = off + t * 4;
      w[t] = ((buf[i] << 24) | (buf[i + 1] << 16) | (buf[i + 2] << 8) | buf[i + 3]) >>> 0;
    }
    for (let t = 16; t < 64; t++) {
      const s0 = rotr(w[t - 15], 7) ^ rotr(w[t - 15], 18) ^ (w[t - 15] >>> 3);
      const s1 = rotr(w[t - 2], 17) ^ rotr(w[t - 2], 19) ^ (w[t - 2] >>> 10);
      w[t] = (w[t - 16] + s0 + w[t - 7] + s1) >>> 0;
    }
    let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7;
    for (let t = 0; t < 64; t++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const temp1 = (h + S1 + ch + K[t] + w[t]) >>> 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const mj = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (S0 + mj) >>> 0;
      h = g; g = f; f = e; e = (d + temp1) >>> 0;
      d = c; c = b; b = a; a = (temp1 + temp2) >>> 0;
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0; h5 = (h5 + f) >>> 0; h6 = (h6 + g) >>> 0; h7 = (h7 + h) >>> 0;
  }
  const out = new Uint8Array(32);
  const hs = [h0, h1, h2, h3, h4, h5, h6, h7];
  for (let i = 0; i < 8; i++) {
    out[i * 4] = (hs[i] >>> 24) & 0xff;
    out[i * 4 + 1] = (hs[i] >>> 16) & 0xff;
    out[i * 4 + 2] = (hs[i] >>> 8) & 0xff;
    out[i * 4 + 3] = hs[i] & 0xff;
  }
  return out;
}

function bytesToHex(bytes: Uint8Array): string {
  const hex = '0123456789abcdef';
  let s = '';
  for (let i = 0; i < bytes.length; i++) {
    s += hex[(bytes[i] >> 4) & 0x0f] + hex[bytes[i] & 0x0f];
  }
  return s;
}

// ─── HMAC-SHA256 ──────────────────────────────────────────────────────────
function hmacSha256(key: Uint8Array, msg: Uint8Array): Uint8Array {
  const blockSize = 64;
  let k = key;
  if (k.length > blockSize) k = sha256Bytes(k);
  const padded = new Uint8Array(blockSize);
  padded.set(k);
  const oKey = new Uint8Array(blockSize);
  const iKey = new Uint8Array(blockSize);
  for (let i = 0; i < blockSize; i++) {
    oKey[i] = padded[i] ^ 0x5c;
    iKey[i] = padded[i] ^ 0x36;
  }
  const inner = new Uint8Array(iKey.length + msg.length);
  inner.set(iKey, 0);
  inner.set(msg, iKey.length);
  const innerHash = sha256Bytes(inner);
  const outer = new Uint8Array(oKey.length + innerHash.length);
  outer.set(oKey, 0);
  outer.set(innerHash, oKey.length);
  return sha256Bytes(outer);
}

function hmacSha256Hex(key: Uint8Array, msg: Uint8Array): string {
  return bytesToHex(hmacSha256(key, msg));
}

// ─── Public API ───────────────────────────────────────────────────────────
function userKey(userId: string): Uint8Array {
  return sha256Bytes(utf8Encode(`${SHARED_SECRET}:${userId}`));
}

function xor(data: Uint8Array, key: Uint8Array): Uint8Array {
  const out = new Uint8Array(data.length);
  for (let i = 0; i < data.length; i++) out[i] = data[i] ^ key[i % key.length];
  return out;
}

export interface FoxTokenInfo { userId: string; serverUrl: string; raw: string; }

export function decodeFoxToken(token: string): FoxTokenInfo | null {
  try {
    const t = token.trim();
    const idx = t.indexOf(':');
    if (idx < 1) return null;
    const userId = t.slice(0, idx);
    const enc = t.slice(idx + 1);
    if (!/^\d+$/.test(userId)) return null;

    const key = userKey(userId);
    const ct = b64urlDecode(enc);
    const pt = xor(ct, key);
    let text: string;
    try { text = utf8Decode(pt); } catch { return null; }

    const parts = text.split('|');
    if (parts.length !== 4) return null;
    const [embUid, serverUrl, nonce, tag] = parts;
    if (embUid !== userId) return null;
    if (!/^https?:\/\//.test(serverUrl)) return null;

    const inner = `${embUid}|${serverUrl}|${nonce}`;
    const expected = hmacSha256Hex(key, utf8Encode(inner)).slice(0, 16);
    if (expected !== tag) return null;

    return { userId, serverUrl, raw: t };
  } catch {
    return null;
  }
}

export function encodeFoxToken(userId: string, serverUrl: string): string {
  const nonceBytes = new Uint8Array(6);
  for (let i = 0; i < nonceBytes.length; i++) nonceBytes[i] = Math.floor(Math.random() * 256);
  const nonce = bytesToHex(nonceBytes);

  const key = userKey(userId);
  const inner = `${userId}|${serverUrl}|${nonce}`;
  const tag = hmacSha256Hex(key, utf8Encode(inner)).slice(0, 16);
  const payload = utf8Encode(`${inner}|${tag}`);
  const ct = xor(payload, key);
  return `${userId}:${b64urlEncode(ct)}`;
}
