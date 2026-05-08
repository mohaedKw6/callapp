/**
 * Fox Farm — Account Creator
 * Creates Telicall accounts from the user's IP address
 * Flow: Create temp email → Init session → Send verify → Get OTP → Verify → Upload
 */

const DOMAINS = [
  'daouse.com', 'bltiwd.com', 'rommiui.com', 'mrotzis.com',
  'mkzaso.com', 'illubd.com', 'wnbaldwy.com', 'xkxkud.com',
  'yzcalo.com', 'ozsaip.com', 'bwmyga.com', 'ruutukf.com', 'inovic.com',
];

const API_URL = 'https://api.telicall.com';

// ─── Helpers ──────────────────────────────────────────────────────────

function randomHex(len) {
  const chars = '0123456789abcdef';
  let result = '';
  for (let i = 0; i < len; i++) result += chars[Math.floor(Math.random() * 16)];
  return result;
}

function randomAlphaNum(len) {
  const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  let result = '';
  for (let i = 0; i < len; i++) result += chars[Math.floor(Math.random() * chars.length)];
  return result;
}

function uuid() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

function getHeaders(token = '', deviceId = '') {
  if (!deviceId) deviceId = randomHex(16);
  return {
    'host': 'api.telicall.com',
    'x-request-id': uuid(),
    'user-agent': 'Dalvik/2.1.0',
    'x-app-version': '1.2.1',
    'x-client-device-id': deviceId,
    'x-lang': 'en',
    'x-os': 'android',
    'x-os-version': '11',
    'x-req-timestamp': Date.now().toString(),
    'x-req-signature': '-1',
    'content-type': 'application/json',
    'x-token': token,
  };
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ─── Temp Email Creation ──────────────────────────────────────────────

async function createMob2Mail() {
  try {
    const res = await fetch('https://mob2.temp-mail.org/mailbox', {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
        'User-Agent': '3.49',
        'Accept-Encoding': 'gzip',
      },
    });
    if (res.ok) {
      const data = await res.json();
      if (data.mailbox && data.token) {
        return { email: data.mailbox, token: data.token, apiType: 'mob2' };
      }
    }
  } catch (e) { /* ignore */ }
  return null;
}

async function createIoMail(domain) {
  if (!domain) domain = DOMAINS[Math.floor(Math.random() * DOMAINS.length)];
  const name = randomAlphaNum(10);
  try {
    const res = await fetch('https://api.internal.temp-mail.io/api/v3/email/new', {
      method: 'POST',
      headers: {
        'Accept': 'application/json, text/plain, */*',
        'Application-Name': 'web',
        'Application-Version': '2.2.29',
        'Origin': 'https://temp-mail.io',
        'User-Agent': 'Mozilla/5.0',
        'content-type': 'application/json',
      },
      body: JSON.stringify({ domain, name }),
    });
    if (res.ok) {
      const data = await res.json();
      if (data.email) {
        return { email: data.email, token: data.email, apiType: 'io' };
      }
    }
  } catch (e) { /* ignore */ }
  return null;
}

async function createEmail() {
  // Try mob2 first, then io
  const mob2 = await createMob2Mail();
  if (mob2) return mob2;

  const io = await createIoMail();
  if (io) return io;

  return null;
}

// ─── Inbox Checking ───────────────────────────────────────────────────

async function checkMob2Inbox(token) {
  try {
    const res = await fetch('https://mob2.temp-mail.org/messages', {
      headers: {
        'Accept': 'application/json',
        'User-Agent': '3.49',
        'Authorization': token,
      },
    });
    if (res.ok) {
      const data = await res.json();
      return data.messages || [];
    }
  } catch (e) { /* ignore */ }
  return [];
}

async function checkIoInbox(email) {
  try {
    const res = await fetch(
      `https://api.internal.temp-mail.io/api/v3/email/${email}/messages`
    );
    if (res.ok) {
      return await res.json();
    }
  } catch (e) { /* ignore */ }
  return [];
}

async function getOtp(mailInfo) {
  for (let i = 0; i < 24; i++) {
    await sleep(5000);
    try {
      let messages = [];
      if (mailInfo.apiType === 'mob2') {
        messages = await checkMob2Inbox(mailInfo.token);
      } else if (mailInfo.apiType === 'io') {
        messages = await checkIoInbox(mailInfo.email);
      }

      for (const msg of messages) {
        const content =
          msg.text || msg.body || msg.content || JSON.stringify(msg);
        if (content.toLowerCase().includes('teli')) {
          const match = content.match(/\b(\d{6})\b/);
          if (match) return match[1];
        }
      }
    } catch (e) { /* ignore */ }
  }
  return null;
}

// ─── Telicall API ─────────────────────────────────────────────────────

async function initSession(deviceId) {
  const headers = getHeaders('', deviceId);
  headers['x-token'] = '';
  const body = {
    countryCode: 'eg',
    deviceName: 'Infinix X698',
    notificationToken: '',
    oldToken: '',
    peerKey: String(Math.floor(Math.random() * 900) + 100),
    timeZone: 'Africa/Cairo',
    localizationKey: '',
  };

  const res = await fetch(`${API_URL}/init`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });

  if (res.status === 429) throw new Error('IP_BLOCKED');
  if (res.status === 403) throw new Error('IP_BLOCKED');

  if (res.ok) {
    const data = await res.json();
    if (data.result?.token) {
      return data.result.token;
    }
  }
  throw new Error('INIT_FAILED');
}

async function sendVerify(email, token, deviceId) {
  const headers = getHeaders(token, deviceId);
  const res = await fetch(`${API_URL}/auth/send-email`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ email }),
  });

  if (res.status === 429) throw new Error('IP_BLOCKED');
  if (res.status === 403) throw new Error('IP_BLOCKED');

  if (res.ok) {
    const data = await res.json();
    if (data.result?.reference) {
      return data.result.reference;
    }
  }
  throw new Error('SEND_EMAIL_FAILED');
}

async function verifyOtp(reference, code, token, deviceId) {
  const headers = getHeaders(token, deviceId);
  const res = await fetch(`${API_URL}/auth/verify-identity`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ reference, code: String(code) }),
  });

  if (res.status === 429) throw new Error('IP_BLOCKED');
  if (res.status === 403) throw new Error('IP_BLOCKED');

  if (res.ok) {
    const data = await res.json();
    if (data.result?.user) {
      return data.result.user;
    }
  }
  throw new Error('VERIFY_FAILED');
}

// ─── Main: Create One Account ─────────────────────────────────────────

/**
 * Creates one Telicall account from the user's IP.
 * Returns { success, account, error } where account is { email, device_id, token }
 * Throws Error with message 'IP_BLOCKED' if the IP is blocked.
 */
export async function createOneAccount(onProgress) {
  const deviceId = randomHex(16);
  let sessionToken = '';
  let mailInfo = null;
  let reference = '';

  try {
    // Step 1: Create temp email
    onProgress?.('📧 إنشاء بريد مؤقت...');
    mailInfo = await createEmail();
    if (!mailInfo) {
      return { success: false, error: 'فشل إنشاء البريد المؤقت' };
    }

    // Step 2: Init session (this is where IP block is most likely detected)
    onProgress?.('🔄 تهيئة الجلسة...');
    sessionToken = await initSession(deviceId);

    // Step 3: Send verification email
    onProgress?.('📨 إرسال كود التحقق...');
    reference = await sendVerify(mailInfo.email, sessionToken, deviceId);

    // Step 4: Get OTP from email
    onProgress?.('⏳ انتظار كود التحقق...');
    const otp = await getOtp(mailInfo);
    if (!otp) {
      return { success: false, error: 'لم يتم استلام كود التحقق' };
    }

    // Step 5: Verify OTP
    onProgress?.('✅ التحقق من الكود...');
    const user = await verifyOtp(reference, otp, sessionToken, deviceId);
    if (!user) {
      return { success: false, error: 'فشل التحقق من الكود' };
    }

    // Success!
    onProgress?.('🎉 تم إنشاء الحساب بنجاح!');
    return {
      success: true,
      account: {
        email: mailInfo.email,
        device_id: deviceId,
        token: sessionToken,
      },
    };
  } catch (e) {
    if (e.message === 'IP_BLOCKED') {
      return { success: false, error: 'IP_BLOCKED' };
    }
    return { success: false, error: e.message || 'خطأ غير معروف' };
  }
}

/**
 * Create multiple accounts in sequence.
 * Calls onProgress(status) and onAccountCreated(account) for each.
 * Stops on IP_BLOCKED.
 * Returns { created: [...], failed: N, ipBlocked: bool }
 */
export async function createMultipleAccounts(count, onProgress, onAccountCreated, onIpBlocked) {
  const created = [];
  let failed = 0;
  let ipBlocked = false;

  for (let i = 0; i < count; i++) {
    if (ipBlocked) break;

    onProgress?.(`🔄 حساب ${i + 1} من ${count}...`);

    const result = await createOneAccount((msg) => {
      onProgress?.(`[${i + 1}/${count}] ${msg}`);
    });

    if (result.success) {
      created.push(result.account);
      onAccountCreated?.(result.account, i + 1);
    } else if (result.error === 'IP_BLOCKED') {
      ipBlocked = true;
      onIpBlocked?.();
    } else {
      failed++;
    }

    // Small delay between accounts
    if (i < count - 1 && !ipBlocked) {
      await sleep(Math.floor(Math.random() * 3000) + 2000);
    }
  }

  return { created, failed, ipBlocked };
}

export { DOMAINS };
