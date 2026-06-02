#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fox Caller v2.0 - Bulk TelliCall Account Creator
=================================================
Fixed: Multi-provider email system to avoid rate limiting.

Email providers (in order):
  1. tempmail.lol (PRIMARY) — many domains, no rate limit
  2. temp-mail.org web2 (FALLBACK) — works but rate-limits
  3. temp-mail.org mob2 (LAST RESORT)

Key fixes from v1.1:
  - tempmail.lol as primary provider (unlimited requests)
  - Automatic failover: if primary fails → try next provider
  - Per-provider rate limiting + circuit breaker
  - Domain filtering: skip blocklisted domains, accept only verified ones
  - Reduced concurrency to avoid burning providers
"""

import requests
import json
import uuid
import time
import random
import re
import string
import os
import hashlib
import base64
import threading
import queue
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from filelock import FileLock

# ─── Config ─────────────────────────────────────────
API_URL  = "https://api.telicall.com"
DAN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Dan.json")
PASSWORD = "@@@GMAQ@@@"

THREADS = 10
BATCH_SIZE = 10
EMAIL_POOL_SIZE   = 15
SESSION_POOL_SIZE = 20

# ─── Egyptian IP Rotation ──────────────────────────────
_EG_RANGES = [
    (41, 32), (41, 33), (41, 34), (41, 35), (41, 36),
    (41, 37), (41, 38), (41, 39), (41, 40), (41, 41),
    (41, 42), (41, 43), (41, 44), (41, 45), (41, 46),
    (41, 47), (41, 48), (41, 49), (41, 50), (41, 51),
    (41, 52), (41, 53), (41, 54), (41, 55), (41, 56),
    (41, 57), (41, 58), (41, 59), (41, 60), (41, 61),
    (156, 192), (156, 193), (156, 194), (156, 195),
    (156, 196), (156, 197), (156, 198), (156, 199),
    (156, 200), (156, 201), (156, 202), (156, 203),
    (197, 32), (197, 33), (197, 34), (197, 35),
    (197, 36), (197, 37), (197, 38), (197, 39),
    (197, 40), (197, 41), (197, 42), (197, 43),
]

_ip_lock = threading.Lock()
_used_ips = set()

def rand_eg_ip():
    with _ip_lock:
        for _ in range(50):
            a, b = random.choice(_EG_RANGES)
            c = random.randint(1, 254)
            d = random.randint(1, 254)
            ip = f"{a}.{b}.{c}.{d}"
            if ip not in _used_ips:
                _used_ips.add(ip)
                return ip
        _used_ips.clear()
        a, b = random.choice(_EG_RANGES)
        c = random.randint(1, 254)
        d = random.randint(1, 254)
        return f"{a}.{b}.{c}.{d}"

# ═══════════════════════════════════════════════════════
# ─── Multi-Provider Email System ─────────────────────
# ═══════════════════════════════════════════════════════

# ─── Provider 1: tempmail.lol (PRIMARY) ──────────────
TEMPMAIL_LOL_URL = "https://api.tempmail.lol"

# ─── Provider 2: temp-mail.org web2 (FALLBACK) ───────
WEB2_BASE_URL = "https://web2.temp-mail.org"
WEB2_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Origin': 'https://temp-mail.org',
    'Referer': 'https://temp-mail.org/',
    'Content-Type': 'application/json'
}

# ─── Provider 3: temp-mail.org mob2 (LAST RESORT) ────
MOB2_BASE_URL = "https://mob2.temp-mail.org"
MOB2_HEADERS = {
    'Accept': 'application/json',
    'User-Agent': '3.49',
    'Accept-Encoding': 'gzip'
}

# ─── Domain Filtering ──────────────────────────────
# الدومينات اللي بتشتغل مع Telicall
WORKING_DOMAINS = {
    # tempmail.lol
    'blaizesmp.net', 'chillart.org', 'dogmrp.com',
    'for4u.net', 'basketrise.com', 'autofixmax.com',
    # temp-mail.org
    'ifcoat.com', 'doreact.com', 'googxs.com', 'hitzcart.com', 'matkind.com',
}

# الدومينات المحظورة من Telicall
BLOCKLISTED_DOMAINS = {'wshu.net', '4nly.com', 'alf5.com', 'mtupu.com',
                       'guerrillamailblock.com', 'guerrillamail.com', 'guerrillamail.de'}

# ─── Per-Provider Rate Limiter ──────────────────────
class ProviderRateLimiter:
    """بيحدد عدد الطلبات لكل مزود خدمة"""
    def __init__(self, name, min_interval=1.0, max_fails=5, cooldown=30):
        self.name = name
        self.min_interval = min_interval
        self.max_fails = max_fails
        self.cooldown = cooldown
        self.lock = threading.Lock()
        self.last_request = 0.0
        self.consecutive_fails = 0
        self.is_blocked = False
        self.blocked_at = 0.0
        self.total_requests = 0
        self.total_success = 0
        self.total_fails = 0

    def wait(self):
        with self.lock:
            now = time.time()
            elapsed = now - self.last_request
            if elapsed < self.min_interval:
                wait_time = self.min_interval - elapsed
                time.sleep(wait_time)
            self.last_request = time.time()
            self.total_requests += 1

    def record_success(self):
        with self.lock:
            self.consecutive_fails = 0
            self.is_blocked = False
            self.total_success += 1

    def record_failure(self):
        with self.lock:
            self.consecutive_fails += 1
            self.total_fails += 1
            if self.consecutive_fails >= self.max_fails:
                self.is_blocked = True
                self.blocked_at = time.time()
                print(f"  🔴 {self.name} اتحظر! ({self.consecutive_fails} فشل) — استنى {self.cooldown} ثانية", flush=True)

    def is_available(self):
        with self.lock:
            if not self.is_blocked:
                return True
            elapsed = time.time() - self.blocked_at
            if elapsed >= self.cooldown:
                self.is_blocked = False
                self.consecutive_fails = 0
                print(f"  🟢 {self.name} رجع يشتغل!", flush=True)
                return True
            return False

    def wait_if_blocked(self):
        while not self.is_available():
            remaining = self.cooldown - (time.time() - self.blocked_at)
            if remaining > 0:
                time.sleep(min(remaining, 5))
            else:
                break

# إنشاء rate limiters لكل مزود
_provider_lol = ProviderRateLimiter("tempmail.lol", min_interval=0.5, max_fails=10, cooldown=20)
_provider_web2 = ProviderRateLimiter("temp-mail.org/web2", min_interval=2.0, max_fails=5, cooldown=45)
_provider_mob2 = ProviderRateLimiter("temp-mail.org/mob2", min_interval=2.0, max_fails=5, cooldown=45)

_file_lock    = threading.Lock()
_counter_lock = threading.Lock()
_mem_lock     = threading.Lock()
_new_count    = 0
_stop_flag    = threading.Event()
_accounts_cache: list = None

def _make_key(password: str) -> bytes:
    return hashlib.sha256(password.encode()).digest()

def encrypt_text(plain: str, password: str) -> bytes:
    key  = _make_key(password)
    data = plain.encode('utf-8')
    enc  = bytes([data[i] ^ key[i % len(key)] for i in range(len(data))])
    return base64.b64encode(enc)

def decrypt_file(path: str, password: str) -> str:
    with open(path, 'rb') as f:
        raw = base64.b64decode(f.read())
    key = _make_key(password)
    return bytes([raw[i] ^ key[i % len(key)] for i in range(len(raw))]).decode('utf-8')

def load_accounts() -> list:
    global _accounts_cache
    with _mem_lock:
        if _accounts_cache is not None:
            return _accounts_cache
    if not os.path.exists(DAN_FILE):
        return []
    try:
        raw = open(DAN_FILE, 'rb').read()
        try:
            result = json.loads(decrypt_file(DAN_FILE, PASSWORD))
        except:
            result = json.loads(raw.decode('utf-8'))
        with _mem_lock:
            _accounts_cache = result
        return result
    except:
        return []

def save_account(email, device, tok):
    global _accounts_cache
    lock_path = DAN_FILE + ".lock"
    lock = FileLock(lock_path, timeout=10)
    with lock:
        current = []
        if os.path.exists(DAN_FILE):
            try:
                current = json.loads(decrypt_file(DAN_FILE, PASSWORD))
            except:
                try:
                    current = json.loads(open(DAN_FILE, 'rb').read().decode('utf-8'))
                except:
                    current = []
        current.append({
            "email": email,
            "x-client-device-id": device,
            "x-token": tok,
            "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        total = len(current)
        encrypted = encrypt_text(json.dumps(current, indent=2, ensure_ascii=False), PASSWORD)
        with open(DAN_FILE, 'wb') as f:
            f.write(encrypted)
        with _mem_lock:
            _accounts_cache = current
        return total

# ═══════════════════════════════════════════════════════
# ─── Email Creation — Multi-Provider ─────────────────
# ═══════════════════════════════════════════════════════

def create_email_tempmail_lol():
    """Provider 1: tempmail.lol — دومينات كتير ومفيش rate limit"""
    for attempt in range(3):
        _provider_lol.wait_if_blocked()
        if _stop_flag.is_set():
            return None
        _provider_lol.wait()

        try:
            r = requests.get(f"{TEMPMAIL_LOL_URL}/generate", timeout=15)
            if r.status_code == 200:
                data = r.json()
                email = data.get('address')
                token = data.get('token')
                if email and token:
                    domain = email.split('@')[1] if '@' in email else ''
                    if domain in BLOCKLISTED_DOMAINS:
                        if attempt < 2:
                            time.sleep(0.5)
                            continue
                    _provider_lol.record_success()
                    return {
                        'email': email,
                        'token': token,
                        'api_type': 'tempmail_lol',
                    }
            else:
                _provider_lol.record_failure()
                time.sleep(2)
        except Exception as e:
            _provider_lol.record_failure()
            print(f"  ⚠️ tempmail.lol error: {e}", flush=True)
            time.sleep(2)
    return None

def create_email_web2():
    """Provider 2: temp-mail.org web2 — احتياطي"""
    for attempt in range(5):
        _provider_web2.wait_if_blocked()
        if _stop_flag.is_set():
            return None
        _provider_web2.wait()

        try:
            r = requests.post(f"{WEB2_BASE_URL}/mailbox", headers=WEB2_HEADERS, timeout=15)
            if r.status_code in [200, 201]:
                data = r.json()
                email = data.get('mailbox')
                token = data.get('token')
                if email and token:
                    domain = email.split('@')[1] if '@' in email else ''
                    if domain in BLOCKLISTED_DOMAINS:
                        if attempt < 4:
                            time.sleep(1)
                            continue
                    _provider_web2.record_success()
                    return {
                        'email': email,
                        'token': token,
                        'api_type': 'web2',
                    }
            elif r.status_code == 429:
                wait = 15 * (attempt + 1)
                print(f"  ⚠️ web2 rate limited (429) — استنى {wait} ثانية", flush=True)
                _provider_web2.record_failure()
                time.sleep(wait)
            else:
                _provider_web2.record_failure()
                time.sleep(3)
        except Exception as e:
            _provider_web2.record_failure()
            print(f"  ⚠️ web2 error: {e}", flush=True)
            time.sleep(3)
    return None

def create_email_mob2():
    """Provider 3: temp-mail.org mob2 — ملاذ أخير"""
    for attempt in range(3):
        _provider_mob2.wait_if_blocked()
        if _stop_flag.is_set():
            return None
        _provider_mob2.wait()

        try:
            r = requests.post(f"{MOB2_BASE_URL}/mailbox", headers=MOB2_HEADERS, timeout=10)
            if r.status_code == 200:
                data = r.json()
                email = data.get('mailbox')
                token = data.get('token')
                if email and token:
                    domain = email.split('@')[1] if '@' in email else ''
                    if domain in BLOCKLISTED_DOMAINS:
                        if attempt < 2:
                            time.sleep(1)
                            continue
                    _provider_mob2.record_success()
                    return {
                        'email': email,
                        'token': token,
                        'api_type': 'mob2',
                    }
            elif r.status_code == 429:
                wait = 15 * (attempt + 1)
                print(f"  ⚠️ mob2 rate limited (429) — استنى {wait} ثانية", flush=True)
                _provider_mob2.record_failure()
                time.sleep(wait)
            else:
                _provider_mob2.record_failure()
                time.sleep(3)
        except Exception as e:
            _provider_mob2.record_failure()
            print(f"  ⚠️ mob2 error: {e}", flush=True)
            time.sleep(3)
    return None

def create_email():
    """
    بيعمل ايميل مؤقت — بيجرب المزودين بالترتيب:
    1. tempmail.lol (أساسي — دومينات كتير + مفيش rate limit)
    2. temp-mail.org web2 (احتياطي)
    3. temp-mail.org mob2 (ملاذ أخير)
    """
    # Provider 1: tempmail.lol
    result = create_email_tempmail_lol()
    if result:
        return result

    # Provider 2: web2
    if _provider_web2.is_available():
        print("  ⚠️ tempmail.lol فشل، جاري تجربة temp-mail.org web2...", flush=True)
        result = create_email_web2()
        if result:
            return result

    # Provider 3: mob2
    if _provider_mob2.is_available():
        print("  ⚠️ web2 فشل، جاري تجربة mob2...", flush=True)
        result = create_email_mob2()
        if result:
            return result

    return None

# ═══════════════════════════════════════════════════════
# ─── Inbox Checking — Multi-Provider ─────────────────
# ═══════════════════════════════════════════════════════

def check_inbox_tempmail_lol(email_token):
    """بيشيك inbox على tempmail.lol"""
    try:
        r = requests.get(f"{TEMPMAIL_LOL_URL}/auth/{email_token}", timeout=15)
        if r.status_code == 200:
            data = r.json()
            # tempmail.lol returns {"email": [...messages...]}
            return data.get('email', [])
    except Exception as e:
        print(f"  ⚠️ tempmail.lol inbox: {e}", flush=True)
    return []

def check_web2_inbox(email_token):
    """بيشيك inbox على temp-mail.org (web2)"""
    try:
        headers = WEB2_HEADERS.copy()
        headers['Authorization'] = f'Bearer {email_token}'
        r = requests.get(f'{WEB2_BASE_URL}/messages', headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else data.get('messages', [])
    except Exception as e:
        print(f"  ⚠️ web2 inbox: {e}", flush=True)
    return []

def check_mob2_inbox(email_token):
    """بيشيك inbox على temp-mail.org (mob2)"""
    try:
        headers = MOB2_HEADERS.copy()
        headers['Authorization'] = email_token
        r = requests.get(f'{MOB2_BASE_URL}/messages', headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data.get('messages', [])
    except Exception as e:
        print(f"  ⚠️ mob2 inbox: {e}", flush=True)
    return []

def get_otp(api_type, jwt):
    """بيستنى OTP من مزود البريد المناسب"""
    deadline = time.time() + 90
    while time.time() < deadline:
        if _stop_flag.is_set():
            return None
        try:
            if api_type == 'tempmail_lol':
                messages = check_inbox_tempmail_lol(jwt)
            elif api_type == 'web2':
                messages = check_web2_inbox(jwt)
            else:
                messages = check_mob2_inbox(jwt)
            for msg in messages:
                sender  = msg.get('from', '').lower()
                subject = msg.get('subject', '').lower()
                body    = msg.get('bodyPreview', msg.get('body', msg.get('textBody', msg.get('bodyHtml', ''))))
                content = f"{sender} {subject} {body}".lower()
                if 'teli' in content or 'verification' in subject or 'verify' in subject or 'تحقق' in subject or 'رمز' in subject:
                    m = re.search(r'\b(\d{6})\b', str(body))
                    if m:
                        return m.group(1)
        except:
            pass
        time.sleep(3)
    return None

# ─── Email & Session Pools ──────────────────────────

_email_pool   = queue.Queue(maxsize=EMAIL_POOL_SIZE)
_session_pool = queue.Queue(maxsize=SESSION_POOL_SIZE)

def _email_pool_filler():
    """بيملا الـ pool بإيميلات من كل المزودين"""
    while not _stop_flag.is_set():
        if _email_pool.qsize() < EMAIL_POOL_SIZE:
            mail = create_email()
            if mail:
                domain = mail['email'].split('@')[1] if '@' in mail['email'] else ''
                if domain in BLOCKLISTED_DOMAINS:
                    continue
                try:
                    _email_pool.put_nowait(mail)
                except queue.Full:
                    pass
            else:
                # لو كل المزودين فشلوا → استنى أكتر
                time.sleep(8)
        else:
            time.sleep(1)

def _session_pool_filler():
    while not _stop_flag.is_set():
        if _session_pool.qsize() < SESSION_POOL_SIZE:
            tok, device, headers = init_session()
            if tok:
                try:
                    _session_pool.put_nowait((tok, device, headers))
                except queue.Full:
                    pass
        else:
            time.sleep(0.5)

def get_email_from_pool() -> dict:
    try:
        mail = _email_pool.get(timeout=15)
        domain = mail['email'].split('@')[1] if '@' in mail['email'] else ''
        if domain in BLOCKLISTED_DOMAINS:
            return create_email()
        return mail
    except queue.Empty:
        return create_email()

def get_session_from_pool():
    try:
        return _session_pool.get(timeout=10)
    except queue.Empty:
        tok, device, headers = init_session()
        return (tok, device, headers) if tok else (None, None, None)

def start_pools():
    # 2 fillers للإيميلات (عشان tempmail.lol يقدر يملّي بسرعة)
    for _ in range(2):
        t = threading.Thread(target=_email_pool_filler, daemon=True)
        t.start()
    # 3 fillers للـ sessions
    for _ in range(3):
        t = threading.Thread(target=_session_pool_filler, daemon=True)
        t.start()
    print("⏳ بيجهّز الـ pool...", flush=True)
    time.sleep(3)

# ─── TelliCall API ──────────────────────────────────

def init_session():
    ip = rand_eg_ip()
    device = ''.join(random.choices('0123456789abcdef', k=16))
    h = {
        "host": "api.telicall.com",
        "x-request-id": str(uuid.uuid4()),
        "user-agent": "Dalvik/2.1.0",
        "x-app-version": "1.2.1",
        "x-client-device-id": device,
        "x-lang": "en", "x-os": "android", "x-os-version": "11",
        "x-req-timestamp": str(int(time.time() * 1000)),
        "x-req-signature": "-1",
        "content-type": "application/json",
        "x-token": "",
        "x-currency": "EGP",
        "x-real-ip": ip,
    }
    body = {
        "countryCode": "eg", "deviceName": "Infinix X698",
        "notificationToken": "", "oldToken": "",
        "peerKey": str(random.randint(100, 999)),
        "timeZone": "Africa/Cairo", "localizationKey": ""
    }
    try:
        h["x-request-id"]    = str(uuid.uuid4())
        h["x-req-timestamp"] = str(int(time.time() * 1000))
        r = requests.post(f"{API_URL}/init", json=body, headers=h, timeout=10)
        if r.status_code == 200:
            tok = r.json().get('result', {}).get('token')
            if tok:
                h["x-token"] = tok
                return tok, device, h
        else:
            print(f"  ⚠️ init [{ip}]: {r.status_code}", flush=True)
    except Exception as e:
        print(f"  ⚠️ init [{ip}]: {e}", flush=True)
    return None, None, None

def send_verify(email, headers):
    try:
        headers["x-request-id"]    = str(uuid.uuid4())
        headers["x-req-timestamp"] = str(int(time.time() * 1000))
        r = requests.post(f"{API_URL}/auth/send-email", json={'email': email},
                          headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json().get('result', {}).get('reference')
        else:
            try:
                err = r.json().get('meta', {}).get('errorMessage', r.text[:80])
            except:
                err = r.text[:80]
            print(f"  ⚠️ send_verify: {r.status_code} | {err}", flush=True)
    except Exception as e:
        print(f"  ⚠️ send_verify: {e}", flush=True)
    return None

def verify_otp_api(ref, code, headers):
    try:
        headers["x-request-id"]    = str(uuid.uuid4())
        headers["x-req-timestamp"] = str(int(time.time() * 1000))
        r = requests.post(f"{API_URL}/auth/verify-identity",
                          json={'reference': ref, 'code': str(code)},
                          headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json().get('result', {}).get('user')
        else:
            try:
                err = r.json().get('meta', {}).get('errorMessage', r.text[:80])
            except:
                err = r.text[:80]
            print(f"  ⚠️ verify_otp: {r.status_code} | {err}", flush=True)
    except Exception as e:
        print(f"  ⚠️ verify_otp: {e}", flush=True)
    return None

def create_one_account():
    tid = threading.current_thread().name

    # 1. إنشاء ايميل
    mail = get_email_from_pool()
    if not mail:
        print(f"[{tid}] ❌ فشل إنشاء البريد من كل المزودين", flush=True)
        return False, "فشل البريد"

    email_addr = mail['email']
    domain = email_addr.split('@')[1] if '@' in email_addr else ''
    provider = mail['api_type']
    print(f"[{tid}] 📧 {email_addr} ({domain}) [{provider}]", flush=True)

    if domain in BLOCKLISTED_DOMAINS:
        print(f"[{tid}] ⚠️ دومين محظور ({domain})، جاري المحاولة بدومين آخر...", flush=True)
        mail = create_email()
        if not mail:
            print(f"[{tid}] ❌ فشل إنشاء البريد البديل", flush=True)
            return False, "دومين محظور"
        email_addr = mail['email']
        domain = email_addr.split('@')[1] if '@' in email_addr else ''
        provider = mail['api_type']
        print(f"[{tid}] 📧 بديل: {email_addr} ({domain}) [{provider}]", flush=True)

    # 2. عمل session
    tok, device, headers = init_session()
    if not tok:
        print(f"[{tid}] 🚫 init_session فشل", flush=True)
        return False, "INIT_FAILED"
    print(f"[{tid}] 🔑 Session OK", flush=True)

    # 3. إرسال verification
    ref = send_verify(email_addr, headers)
    if not ref:
        print(f"[{tid}] 🚫 send_verify فشل", flush=True)
        return False, "VERIFY_FAILED"
    print(f"[{tid}] 📨 OTP أُرسل، ref={ref[:8]}...", flush=True)

    # 4. استنى OTP
    otp = get_otp(mail['api_type'], mail['token'])
    if not otp:
        print(f"[{tid}] ⏰ OTP timeout", flush=True)
        return False, "OTP timeout"
    print(f"[{tid}] 🔢 OTP: {otp}", flush=True)

    # 5. verify
    user = verify_otp_api(ref, otp, headers)
    if not user:
        print(f"[{tid}] ❌ verify فشل", flush=True)
        return False, "فشل التحقق"

    total = save_account(email_addr, device, tok)
    print(f"[{tid}] ✅ تم! الإجمالي: {total}", flush=True)
    return True, total

# ─── Burst Pool ────────────────────────────────────
_burst_pool = ThreadPoolExecutor(max_workers=10)

def _do_burst():
    global _new_count
    futures = {_burst_pool.submit(create_one_account): i for i in range(2)}
    for f in as_completed(futures):
        try:
            ok, result = f.result()
            if ok:
                with _counter_lock:
                    _new_count += 1
                    n = _new_count
                print(f"⚡ burst #{n} | الإجمالي: {result}", flush=True)
        except:
            pass

def worker():
    global _new_count
    tid = threading.current_thread().name

    while not _stop_flag.is_set():
        batch_done = 0
        while batch_done < BATCH_SIZE and not _stop_flag.is_set():
            ok, result = create_one_account()

            if ok:
                with _counter_lock:
                    _new_count += 1
                    n = _new_count
                batch_done += 1
                print(f"✅ حساب #{n} | batch {batch_done}/{BATCH_SIZE} | الإجمالي: {result}", flush=True)

                time.sleep(2)
                print(f"[{tid}] 🔥 بيطلع 2 حسابات بالتوازي...", flush=True)
                _burst_pool.submit(_do_burst)

        if batch_done == BATCH_SIZE:
            print(f"[{tid}] 🎯 Batch مكتمل", flush=True)

def main():
    global _accounts_cache

    print("🌐 السكريبت بيشتغل على الـ IP بتاعك مباشرة بدون بروكسي", flush=True)
    print("🔄 بيلفّ على IPs مصرية عشوائية في x-real-ip", flush=True)
    print("", flush=True)
    print("📧 ═══ مزودين البريد ═══", flush=True)
    print("  1️⃣  tempmail.lol (أساسي — دومينات كتير + مفيش rate limit)", flush=True)
    print("  2️⃣  temp-mail.org/web2 (احتياطي)", flush=True)
    print("  3️⃣  temp-mail.org/mob2 (ملاذ أخير)", flush=True)
    print("", flush=True)
    print(f"✅ الدومينات المسموحة: {', '.join(sorted(WORKING_DOMAINS))}", flush=True)
    print(f"🚫 الدومينات المحظورة: {', '.join(sorted(BLOCKLISTED_DOMAINS))}", flush=True)
    print("", flush=True)

    # نتأكد إن tempmail.lol شغال
    try:
        r = requests.get(f"{TEMPMAIL_LOL_URL}/generate", timeout=10)
        if r.status_code == 200:
            test_email = r.json().get('address', '')
            test_domain = test_email.split('@')[1] if '@' in test_email else ''
            blocked = "🚫 محظور" if test_domain in BLOCKLISTED_DOMAINS else "✅ شغال"
            print(f"📬 tempmail.lol متاح (عينة: {test_email} - {blocked})", flush=True)
        else:
            print(f"⚠️  tempmail.lol رجع {r.status_code}", flush=True)
    except:
        print("⚠️  tempmail.lol مش متاح حالياً", flush=True)

    # نتأكد إن temp-mail.org شغال
    try:
        r = requests.post(f"{WEB2_BASE_URL}/mailbox", headers=WEB2_HEADERS, timeout=10)
        if r.status_code in [200, 201]:
            test_email = r.json().get('mailbox', '')
            test_domain = test_email.split('@')[1] if '@' in test_email else ''
            blocked = "🚫 محظور" if test_domain in BLOCKLISTED_DOMAINS else "✅ شغال"
            print(f"📬 temp-mail.org متاح (عينة: {test_email} - {blocked})", flush=True)
    except:
        print("⚠️  temp-mail.org مش متاح حالياً", flush=True)

    existing = load_accounts()
    ex_count = len(existing)
    _accounts_cache = existing

    if ex_count > 0:
        print(f"\n📂 تم تحميل {ex_count} حساب موجود — سيتم الإضافة عليها", flush=True)

    print(f"\n🚀 تشغيل {THREADS} threads متوازية...", flush=True)

    start_pools()

    threads = []
    for _ in range(THREADS):
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        threads.append(t)

    try:
        while not _stop_flag.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        _stop_flag.set()

    for t in threads:
        t.join(timeout=5)

    # إحصائيات المزودين
    print("\n📊 ═══ إحصائيات المزودين ═══", flush=True)
    for p in [_provider_lol, _provider_web2, _provider_mob2]:
        print(f"  {p.name}: {p.total_success} نجح / {p.total_fails} فشل / {p.total_requests} طلب", flush=True)

    total = len(_accounts_cache) if _accounts_cache else 0
    if _new_count > 0:
        print(f"\n✅ تم حفظ الملف: {DAN_FILE}")
        print(f"📊 الإجمالي الكلي: {total} حساب ({_new_count} جديد)")
    else:
        print("\n⚠️ محدش اتعمل — حاول تاني")

if __name__ == "__main__":
    main()
