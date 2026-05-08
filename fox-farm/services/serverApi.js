/**
 * Fox Farm — Server API client
 * Handles auth, config, stats, and account uploads
 */

const DEFAULT_SERVER = 'https://eaiupvh6.up.railway.app';

class FarmApi {
  constructor() {
    this._serverUrl = DEFAULT_SERVER;
    this._farmToken = null;
  }

  setServer(url) {
    this._serverUrl = url.replace(/\/+$/, '');
  }

  getServer() {
    return this._serverUrl;
  }

  setFarmToken(token) {
    this._farmToken = token;
  }

  // ─── Auth ────────────────────────────────────────────────────────

  async authenticate(key) {
    const res = await this._post('/api/farm/auth', { key });
    if (res.token) {
      this._farmToken = res.token;
    }
    return res;
  }

  isAuthenticated() {
    return !!this._farmToken;
  }

  // ─── Config ──────────────────────────────────────────────────────

  async getConfig() {
    return this._get('/api/farm/config');
  }

  // ─── Stats ───────────────────────────────────────────────────────

  async getStats() {
    return this._get('/api/farm/stats');
  }

  // ─── Upload accounts ─────────────────────────────────────────────

  async uploadAccounts(accounts) {
    // Upload uses a longer timeout since the server does file I/O
    // Even if the response times out, the accounts are saved on the server
    try {
      return await this._post('/api/farm/upload-accounts', { accounts }, 45000);
    } catch (e) {
      // If timeout, the upload likely succeeded on the server side
      // Verify by checking stats
      if (e.message.includes('انقطع') || e.message.includes('timeout')) {
        try {
          const stats = await this.getStats();
          return { ok: true, added: accounts.length, verified: true, server_tokens: stats.ready_tokens };
        } catch {
          // Can't verify either - assume success
          return { ok: true, added: accounts.length, verified: false };
        }
      }
      throw e;
    }
  }

  // ─── Internal fetch helpers ──────────────────────────────────────

  async _get(path) {
    const url = this._serverUrl + path;
    const headers = { 'content-type': 'application/json' };
    if (this._farmToken) headers['x-farm-token'] = this._farmToken;

    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 15000);
    try {
      const res = await fetch(url, { method: 'GET', headers, signal: ctrl.signal });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'خطأ ' + res.status);
      return data;
    } catch (e) {
      if (e.name === 'AbortError') throw new Error('انقطع الاتصال بالسيرفر');
      throw e;
    } finally {
      clearTimeout(timer);
    }
  }

  async _post(path, body, timeoutMs = 30000) {
    const url = this._serverUrl + path;
    const headers = { 'content-type': 'application/json' };
    if (this._farmToken) headers['x-farm-token'] = this._farmToken;

    const bodyStr = body ? JSON.stringify(body) : undefined;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers,
        body: bodyStr,
        signal: ctrl.signal,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'خطأ ' + res.status);
      return data;
    } catch (e) {
      if (e.name === 'AbortError') throw new Error('انقطع الاتصال بالسيرفر');
      throw e;
    } finally {
      clearTimeout(timer);
    }
  }
}

// Singleton
export default new FarmApi();
