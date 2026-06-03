#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fox Caller v15.0 - TempMail.org Edition
=========================================
مزود إيميل: mob2.temp-mail.org API (بدون متصفح/Chrome/DrissionPage)

الجديد في v15.0:
  - temp-mail.org API بدل tempail.top (شغال 100% بدون Cloudflare)
  - لا DrissionPage - لا Chrome - لا Playwright - لا متصفح خالص
  - لا SandVPN - لا emailnator
  - requests عادي بس (لا curl_cffi - لا cloudscraper)
  - الدومينات: @snocv.com @tixpad.com (مقبولة من Telicall!)

API Flow:
  1. POST /mailbox  → إنشاء إيميل جديد + JWT token
  2. GET  /messages  → قراءة الرسائل/OTP
  3. POST /mailbox  → تغيير الإيميل (JWT بيتغير)

Usage:
  python3 fox_caller1.py numbers.xlsx --mode server
  python3 fox_caller1.py numbers.xlsx --mode server --threads 5
  python3 fox_caller1.py numbers.xlsx --mode create --threads 10
"""

import requests
import json
import uuid
import time
import random
import re
import os
import hashlib
import base64
import threading
import argparse
import sys
import queue
from datetime import datetime
from filelock import FileLock

# ═══════════════════════════════════════════════════════════════
# ─── Config ───────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
API_URL           = "https://api.telicall.com"
SERVER_URL        = "https://callapp-production-c84c.up.railway.app"
ADMIN_KEY         = "06d271200e53fb4482acd8679bfe358a"
DAN_FILE          = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Dan.json")
PASSWORD          = "@@@GMAQ@@@"
DEFAULT_DURATION  = 64
DEFAULT_THREADS   = 3
EMAIL_POOL_SIZE   = 15
SESSION_POOL_SIZE = 5
MAX_RETRIES       = 8

# temp-mail.org config
TEMPMAIL_API      = "https://mob2.temp-mail.org"
TEMPMAIL_UA       = "4.02"

# ═══════════════════════════════════════════════════════════════
# ─── Proxy Manager ────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
PROXY_FILE      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alive_proxies.txt")
_proxy_lock     = threading.Lock()
_dead_proxies   = set()
_proxy_list     = []

def _load_proxies_from_file():
    proxies = []
    if not os.path.exists(PROXY_FILE):
        return proxies
    try:
        with open(PROXY_FILE, encoding='utf-8', errors='ignore') as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        for line in lines:
            if '://' in line:
                proxies.append(line)
            elif ':' in line and '.' in line:
                proxies.append(f"http://{line}")
    except Exception:
        pass
    random.shuffle(proxies)
    return proxies

def init_proxy_manager():
    global _proxy_list
    _proxy_list = _load_proxies_from_file()
    if _proxy_list:
        types = {}
        for p in _proxy_list:
            t = p.split('://')[0]
            types[t] = types.get(t, 0) + 1
        breakdown = ' | '.join(f"{k}={v}" for k, v in sorted(types.items()))
        print(f"  Proxies:     {len(_proxy_list)} ({breakdown})", flush=True)
    else:
        print(f"  Proxies:     None (direct connection)", flush=True)

def get_proxy():
    with _proxy_lock:
        alive = [p for p in _proxy_list if p not in _dead_proxies]
    if alive:
        p = random.choice(alive)
        return {"http": p, "https": p}
    return None

def _mark_dead(proxy_url):
    with _proxy_lock:
        _dead_proxies.add(proxy_url)

def get_proxy_and_mark_dead(proxy_dict):
    if proxy_dict:
        url = list(proxy_dict.values())[0]
        _mark_dead(url)
    return get_proxy()

# ═══════════════════════════════════════════════════════════════
# ─── Egyptian IP Generator ───────────────────────────────────
# ═══════════════════════════════════════════════════════════════
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

_ip_lock  = threading.Lock()
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

# ═══════════════════════════════════════════════════════════════
# ─── Email Provider: mob2.temp-mail.org API ──────────────────
# ═══════════════════════════════════════════════════════════════
_tempmail_stats = {"ok": 0, "fail": 0, "otp_ok": 0, "otp_fail": 0}
_tempmail_stats_lock = threading.Lock()
_tempmail_lock = threading.Lock()
_tempmail_fail_count = 0
TEMPMAIL_MAX_FAILS = 20


class TempMailOrgProvider:
    """بتتعامل مع mob2.temp-mail.org API
    
    API Flow:
      1. POST /mailbox  → إنشاء إيميل جديد + JWT token
      2. GET  /messages?after={ts} → قراءة الرسائل
      3. POST /mailbox  → تغيير الإيميل (عشان نعمل واحد جديد)
    
    Headers:
      authorization: <JWT> (بدون "Bearer")
      user-agent: 4.02
      accept: application/json
    
    Rate Limit:
      POST /mailbox: 15 طلب لكل فترة
    """

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            'user-agent': TEMPMAIL_UA,
            'accept': 'application/json',
            'accept-encoding': 'gzip',
        })
        self._jwt = None
        self._current_email = None
        self._current_ts = 0  # timestamp للـ after parameter
        self._rate_limit_remaining = 15

    def create_email(self, max_retries=3):
        """بيعمل إيميل مؤقت جديد من temp-mail.org
        
        لو عندنا JWT فعلًا، بنعمل POST /mailbox عشان نغير الإيميل
        لو أول مرة، بنعمل POST /mailbox بدون JWT
        """
        global _tempail_fail_count

        for attempt in range(max_retries):
            try:
                headers = {}
                if self._jwt:
                    headers['authorization'] = self._jwt

                resp = self._session.post(
                    f'{TEMPMAIL_API}/mailbox',
                    headers=headers,
                    timeout=20,
                )

                # تحديث rate limit
                rl = resp.headers.get('x-ratelimit-remaining')
                if rl:
                    self._rate_limit_remaining = int(rl)

                if resp.status_code == 200:
                    data = resp.json()
                    new_token = data.get('token', '')
                    new_mailbox = data.get('mailbox', '')

                    if new_token and new_mailbox and '@' in new_mailbox:
                        self._jwt = new_token
                        self._current_email = new_mailbox
                        self._current_ts = int(time.time())

                        with _tempmail_stats_lock:
                            _tempail_stats["ok"] += 1
                        _tempail_fail_count = 0

                        return {
                            'email': new_mailbox,
                            'jwt': new_token,
                            'provider': 'tempmail_org',
                            'api_type': 'tempmail_org',
                            'created_ts': self._current_ts,
                        }

                elif resp.status_code == 429:
                    # Rate limited — نستنى شوية
                    retry_after = int(resp.headers.get('retry-after', 60))
                    print(f"  ⏳ temp-mail.org rate limit — نستنى {retry_after}s", flush=True)
                    time.sleep(min(retry_after, 60))
                    continue

                elif resp.status_code in (403, 503):
                    # Cloudflare أو حاجة
                    if attempt < max_retries - 1:
                        time.sleep(3)
                        continue

            except requests.exceptions.ConnectionError:
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue

        with _tempail_stats_lock:
            _tempail_stats["fail"] += 1
        _tempail_fail_count += 1
        return None

    def check_otp(self, mail_info, timeout=90):
        """بتدور على OTP في صندوق temp-mail.org
        
        بنعمل polling كل 5 ثواني على GET /messages?after={ts}
        """
        jwt = mail_info.get('jwt')
        created_ts = mail_info.get('created_ts', 0)

        if not jwt:
            with _tempail_stats_lock:
                _tempail_stats["otp_fail"] += 1
            return None

        deadline = time.time() + timeout
        after_ts = created_ts

        while time.time() < deadline:
            try:
                headers = {'authorization': jwt}
                resp = self._session.get(
                    f'{TEMPMAIL_API}/messages',
                    params={'after': after_ts},
                    headers=headers,
                    timeout=15,
                )

                if resp.status_code == 200:
                    data = resp.json()
                    messages = data.get('messages', [])

                    for msg in messages:
                        # نحدث after_ts عشان ما نشوفش نفس الرسالة تاني
                        received = msg.get('receivedAt', 0)
                        if received > after_ts:
                            after_ts = received

                        # بنستخرج OTP من الـ subject
                        subject = str(msg.get('subject', ''))
                        otp = self._extract_otp(subject)
                        if otp:
                            with _tempail_stats_lock:
                                _tempail_stats["otp_ok"] += 1
                            return otp

                        # بنستخرج OTP من الـ bodyPreview
                        body_preview = str(msg.get('bodyPreview', ''))
                        otp = self._extract_otp(body_preview)
                        if otp:
                            with _tempail_stats_lock:
                                _tempail_stats["otp_ok"] += 1
                            return otp

                        # لو لسه مش لاقين OTP، نجيب الرسالة كاملة
                        msg_id = msg.get('_id')
                        if msg_id:
                            from_email = str(msg.get('from', '')).lower()
                            if 'teli' in from_email or 'verif' in subject.lower():
                                full_otp = self._get_message_otp(msg_id, jwt)
                                if full_otp:
                                    with _tempail_stats_lock:
                                        _tempail_stats["otp_ok"] += 1
                                    return full_otp

                elif resp.status_code == 401:
                    # JWT منتهي
                    break

            except Exception:
                pass

            time.sleep(5)

        with _tempmail_stats_lock:
            _tempail_stats["otp_fail"] += 1
        return None

    def _get_message_otp(self, msg_id, jwt):
        """بتجيب الرسالة كاملة وبتستخرج OTP من bodyHtml"""
        try:
            headers = {'authorization': jwt}
            resp = self._session.get(
                f'{TEMPMAIL_API}/messages/{msg_id}/',
                headers=headers,
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                body_html = str(data.get('bodyHtml', ''))
                subject = str(data.get('subject', ''))

                # بنستخرج OTP من body
                otp = self._extract_otp(body_html)
                if otp:
                    return otp

                # بنستخرج من subject كمان
                otp = self._extract_otp(subject)
                if otp:
                    return otp

        except Exception:
            pass
        return None

    def _extract_otp(self, text):
        """بتستخرج OTP (6 أرقام) من نص"""
        if not text:
            return None
        # بندور على 6 أرقام متتالية
        m = re.search(r'\b(\d{6})\b', text)
        if m:
            return m.group(1)
        return None

    def delete_email(self, mail_info):
        """بتغيّر الإيميل الحالي عشان نقدر نعمل واحد جديد
        
        مفيش delete endpoint — بنعمل POST /mailbox عشان نعمل إيميل جديد
        والقديم بيتمسح تلقائي
        """
        # بنعمل create_email جديد لو محتاجين
        # الـ JWT بيتحدث تلقائي في create_email
        pass

    def change_mailbox(self):
        """بتغيّر الإيميل الحالي — بتعمل POST /mailbox بالـ JWT الحالي"""
        return self.create_email()


# ─── Global provider instance ───
_tempmail_provider = None  # يتم تعيينه في main()

# ═══════════════════════════════════════════════════════════════
# ─── Email Pool ──────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
_email_pool = queue.Queue(maxsize=EMAIL_POOL_SIZE)
_session_pool = queue.Queue(maxsize=SESSION_POOL_SIZE)
_stop_flag = threading.Event()
_pool_stats = {"emails_created": 0, "sessions_created": 0}
_pool_stats_lock = threading.Lock()

def _email_pool_filler():
    """خلفية: بيملا بول الإيميلات من temp-mail.org"""
    global _tempail_fail_count

    while not _stop_flag.is_set():
        if _email_pool.qsize() < EMAIL_POOL_SIZE:
            if _tempail_fail_count >= TEMPMAIL_MAX_FAILS:
                time.sleep(10)
                continue

            mail = None
            if _tempmail_provider:
                mail = _tempmail_provider.create_email()

            if mail:
                try:
                    _email_pool.put_nowait(mail)
                    with _pool_stats_lock:
                        _pool_stats["emails_created"] += 1
                except queue.Full:
                    pass
            else:
                time.sleep(3)
        else:
            time.sleep(0.5)

def _session_pool_filler():
    while not _stop_flag.is_set():
        if _session_pool.qsize() < SESSION_POOL_SIZE:
            proxy = get_proxy()
            tok, device, headers = init_session(proxy)
            if tok:
                try:
                    _session_pool.put_nowait((tok, device, headers, proxy))
                    with _pool_stats_lock:
                        _pool_stats["sessions_created"] += 1
                except queue.Full:
                    pass
            else:
                time.sleep(1)
        else:
            time.sleep(0.5)

def get_email_from_pool():
    try:
        return _email_pool.get(timeout=15)
    except queue.Empty:
        if _tempmail_provider:
            for attempt in range(5):
                mail = _tempmail_provider.create_email()
                if mail:
                    return mail
                time.sleep(3)
        return None

def get_session_from_pool():
    try:
        return _session_pool.get(timeout=8)
    except queue.Empty:
        for attempt in range(3):
            proxy = get_proxy()
            tok, device, headers = init_session(proxy)
            if tok:
                return (tok, device, headers, proxy)
            time.sleep(1)
        proxy = get_proxy()
        return (None, None, None, proxy)

def start_pools():
    for _ in range(2):
        t = threading.Thread(target=_email_pool_filler, daemon=True)
        t.start()
    t = threading.Thread(target=_session_pool_filler, daemon=True)
    t.start()
    print("  Pool:       جاري التعبئة...", flush=True)
    time.sleep(3)
    print(f"  Pool:       إيميلات={_email_pool.qsize()} | جلسات={_session_pool.qsize()}", flush=True)

# ═══════════════════════════════════════════════════════════════
# ─── Unified OTP getter ──────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def get_otp_from_mail(mail_info, timeout=90):
    if _tempmail_provider:
        return _tempmail_provider.check_otp(mail_info, timeout=timeout)
    return None

# ═══════════════════════════════════════════════════════════════
# ─── Telicall API ─────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def init_session(proxy_dict=None, use_xrealip=True):
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
    }
    if use_xrealip and not proxy_dict:
        h["x-currency"] = "EGP"
        h["x-real-ip"] = rand_eg_ip()
    body = {
        "countryCode": "eg", "deviceName": "Infinix X698",
        "notificationToken": "", "oldToken": "",
        "peerKey": str(random.randint(100, 999)),
        "timeZone": "Africa/Cairo", "localizationKey": ""
    }
    try:
        h["x-request-id"] = str(uuid.uuid4())
        h["x-req-timestamp"] = str(int(time.time() * 1000))
        r = requests.post(f"{API_URL}/init", json=body, headers=h,
                          proxies=proxy_dict, timeout=12)
        if r.status_code == 200:
            tok = r.json().get('result', {}).get('token')
            if tok:
                h["x-token"] = tok
                return tok, device, h
    except Exception:
        pass
    return None, None, None

def send_verify(email, headers, proxy_dict=None):
    try:
        headers["x-request-id"] = str(uuid.uuid4())
        headers["x-req-timestamp"] = str(int(time.time() * 1000))
        r = requests.post(f"{API_URL}/auth/send-email", json={'email': email},
                          headers=headers, proxies=proxy_dict, timeout=12)
        if r.status_code == 200:
            return r.json().get('result', {}).get('reference'), None
        else:
            try:
                err_data = r.json()
                err = err_data.get('meta', {}).get('errorMessage', r.text[:80])
                err_lower = str(err).lower()
                if 'already exist' in err_lower or 'already registered' in err_lower:
                    return None, 'EMAIL_EXISTS'
                if 'blocklist' in err_lower or 'blocked' in err_lower or 'محظور' in err:
                    return None, f'BLOCKED:{email.split("@")[1] if "@" in email else ""}'
                return None, err
            except Exception:
                return None, f"HTTP {r.status_code}"
    except Exception as e:
        return None, str(e)

def verify_otp_api(ref, code, headers, proxy_dict=None):
    try:
        headers["x-request-id"] = str(uuid.uuid4())
        headers["x-req-timestamp"] = str(int(time.time() * 1000))
        r = requests.post(f"{API_URL}/auth/verify-identity",
                          json={'reference': ref, 'code': str(code)},
                          headers=headers, proxies=proxy_dict, timeout=12)
        if r.status_code == 200:
            user = r.json().get('result', {}).get('user')
            if user:
                return user, None
            return None, 'other'
        elif r.status_code == 400:
            try:
                err_msg = r.json().get('meta', {}).get('errorMessage', r.text[:100])
                err_lower = str(err_msg).lower()
                if 'already exist' in err_lower or 'already registered' in err_lower:
                    return None, 'email_exists'
                if 'expired' in err_lower or 'invalid' in err_lower:
                    return None, 'expired'
                return None, f'other:{err_msg[:50]}'
            except Exception:
                return None, 'other:HTTP400'
        else:
            return None, f'other:HTTP{r.status_code}'
    except Exception as e:
        return None, f'other:{str(e)[:50]}'

# ═══════════════════════════════════════════════════════════════
# ─── Dan.json Encryption ──────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def _make_key(password: str) -> bytes:
    return hashlib.sha256(password.encode()).digest()

def encrypt_text(plain: str, password: str) -> bytes:
    key = _make_key(password)
    data = plain.encode('utf-8')
    enc = bytes([data[i] ^ key[i % len(key)] for i in range(len(data))])
    return base64.b64encode(enc)

def decrypt_file(path: str, password: str) -> str:
    with open(path, 'rb') as f:
        raw = base64.b64decode(f.read())
    key = _make_key(password)
    return bytes([raw[i] ^ key[i % len(key)] for i in range(len(raw))]).decode('utf-8')

def save_account(email, device, tok):
    lock_path = DAN_FILE + ".lock"
    lock = FileLock(lock_path, timeout=10)
    with lock:
        current = []
        if os.path.exists(DAN_FILE):
            try:
                current = json.loads(decrypt_file(DAN_FILE, PASSWORD))
            except Exception:
                try:
                    current = json.loads(open(DAN_FILE, 'rb').read().decode('utf-8'))
                except Exception:
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
        return total

# ═══════════════════════════════════════════════════════════════
# ─── Server API ───────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def is_server_available():
    try:
        r = requests.get(f"{SERVER_URL}/api/health", timeout=8)
        return r.status_code == 200
    except Exception:
        return False

def upload_to_server(email, device_id, token):
    try:
        r = requests.post(f"{SERVER_URL}/api/fox-caller/upload-accounts",
                          headers={"Content-Type": "application/json", "x-admin-key": ADMIN_KEY},
                          json={"accounts": [{"email": email, "x-client-device-id": device_id, "x-token": token}]},
                          timeout=15)
        if r.status_code == 200:
            return r.json().get("ready_tokens", 0)
    except Exception:
        pass
    return -1

def trigger_async_call(phone, duration=64):
    try:
        r = requests.post(f"{SERVER_URL}/api/fox-caller/async-call",
                          headers={"Content-Type": "application/json", "x-admin-key": ADMIN_KEY},
                          json={"phone": phone, "duration": duration}, timeout=15)
        if r.status_code == 200:
            data = r.json()
            return data.get("call_id"), data.get("verification_url", "")
    except Exception:
        pass
    return None, ""

def trigger_make_call(phone, duration=64):
    try:
        r = requests.post(f"{SERVER_URL}/api/fox-caller/make-call",
                          headers={"Content-Type": "application/json", "x-admin-key": ADMIN_KEY},
                          json={"phone": phone, "duration": duration},
                          timeout=duration + 120)
        if r.status_code == 200:
            return r.json()
        else:
            try:
                return r.json()
            except Exception:
                return {"status": "error", "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def check_call_status(call_id):
    try:
        r = requests.get(f"{SERVER_URL}/api/fox-caller/call-status/{call_id}", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

# ═══════════════════════════════════════════════════════════════
# ─── Read Numbers from File ──────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def read_numbers(filepath):
    numbers = []
    if filepath.endswith('.xlsx'):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(filepath, read_only=True)
            ws = wb.active
            for row in ws.iter_rows(values_only=True):
                for cell in row:
                    if cell is not None:
                        num = str(cell).strip()
                        num = num.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
                        if num.startswith('00'):
                            num = '+' + num[2:]
                        if num.startswith('+') and len(num) >= 10:
                            numbers.append(num)
                        elif len(num) >= 10 and num.isdigit():
                            numbers.append('+' + num)
            wb.close()
        except ImportError:
            print("ERROR: openpyxl not installed. Run: pip3 install openpyxl", flush=True)
            sys.exit(1)
    else:
        try:
            with open(filepath, 'r') as f:
                for line in f:
                    num = line.strip().replace(' ', '').replace('-', '')
                    if num.startswith('00'):
                        num = '+' + num[2:]
                    if num.startswith('+') and len(num) >= 10:
                        numbers.append(num)
                    elif len(num) >= 10 and num.isdigit():
                        numbers.append('+' + num)
        except Exception as e:
            print(f"ERROR reading file: {e}", flush=True)
            sys.exit(1)
    seen = set()
    unique = []
    for n in numbers:
        if n not in seen:
            seen.add(n)
            unique.append(n)
    return unique

# ═══════════════════════════════════════════════════════════════
# ─── Stats ────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
_stats_lock = threading.Lock()
_stats = {
    "calls_ok": 0, "calls_no_balance": 0, "calls_failed": 0,
    "accounts_ok": 0, "accounts_no_bal": 0,
    "email_fail": 0, "verify_fail": 0, "otp_fail": 0,
    "confirm_fail": 0, "session_fail": 0,
    "domain_blocked": 0, "email_exists": 0,
    "total": 0, "retries": 0,
}
_start_time = None

_phone_queue = []
_queue_lock = threading.Lock()
_queue_index = 0

_failed_phones = []
_failed_lock = threading.Lock()

def get_next_phone():
    global _queue_index
    with _queue_lock:
        if _queue_index < len(_phone_queue):
            phone = _phone_queue[_queue_index]
            _queue_index += 1
            return phone
    return None

def add_failed_phone(phone, reason):
    with _failed_lock:
        _failed_phones.append({"phone": phone, "reason": reason})

def update_stat(key, delta=1):
    with _stats_lock:
        _stats[key] += delta

# ═══════════════════════════════════════════════════════════════
# ─── Active Call Tracking ────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
_active_calls = []
_active_call_lock = threading.Lock()

def add_active_call(call_id, phone, from_num, tid):
    with _active_call_lock:
        _active_calls.append({
            "call_id": call_id, "phone": phone,
            "from": from_num, "tid": tid, "started": time.time()
        })

def monitor_calls():
    while True:
        time.sleep(10)
        with _active_call_lock:
            remaining = []
            for c in _active_calls:
                status_data = check_call_status(c["call_id"])
                if status_data:
                    s = status_data.get("status", "")
                    dur = status_data.get("actual_duration", 0)
                    phone = c["phone"]
                    caller = status_data.get("from_number", c["from"])
                    tid = c["tid"]
                    if s == "answered_ok":
                        print(f"[{tid}] ✅ تم الاتصال {phone} ({dur}s) <- {caller}", flush=True)
                        update_stat("calls_ok")
                    elif s in ("failed", "error"):
                        err = status_data.get("error", "")
                        if "balance" in str(err).lower():
                            print(f"[{tid}] ❌ NO_BALANCE {phone}", flush=True)
                            update_stat("calls_no_balance")
                        else:
                            print(f"[{tid}] ❌ فشل المكالمة {phone} ({err})", flush=True)
                            update_stat("calls_failed")
                        continue
                    else:
                        remaining.append(c)
                else:
                    elapsed = time.time() - c["started"]
                    if elapsed > 300:
                        print(f"[{tid}] ⏰ TIMEOUT {c['phone']}", flush=True)
                        update_stat("calls_failed")
                    else:
                        remaining.append(c)
            _active_calls.clear()
            _active_calls.extend(remaining)

# ═══════════════════════════════════════════════════════════════
# ─── Worker ──────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def _try_one_phone(phone, duration, mode, tid):
    mail = get_email_from_pool()
    if not mail:
        print(f"[{tid}] ❌ لا إيميل متاح {phone}", flush=True)
        update_stat("email_fail")
        return 'retry'

    email_addr = mail['email']
    email_short = email_addr.split('@')[0][:12]
    email_domain = email_addr.split('@')[1] if '@' in email_addr else '?'

    print(f"[{tid}] 📧 {email_short}...@{email_domain} -> {phone}", flush=True)

    tok, device, headers, sess_proxy = get_session_from_pool()
    active_proxy = sess_proxy or get_proxy()

    if not tok:
        print(f"[{tid}] ❌ فشل الجلسة {phone}", flush=True)
        update_stat("session_fail")
        return 'retry'

    ref, err = send_verify(email_addr, headers, active_proxy)
    if not ref:
        err_str = str(err or "")
        if err_str == 'EMAIL_EXISTS':
            print(f"[{tid}] ⚠️ إيميل مسجل {email_short}...@{email_domain}", flush=True)
            update_stat("email_exists")
            return 'email_exists'
        elif err_str.startswith('BLOCKED:'):
            blocked_domain = err_str.split(':', 1)[1]
            print(f"[{tid}] ❌ دومين محظور: {blocked_domain} {phone}", flush=True)
            update_stat("domain_blocked")
            return 'domain_blocked'
        else:
            print(f"[{tid}] ❌ فشل التحقق {phone} ({err_str[:50]})", flush=True)
            update_stat("verify_fail")
        if active_proxy:
            active_proxy = get_proxy_and_mark_dead(active_proxy)
        return 'retry'

    # ─── انتظار OTP ───
    otp = get_otp_from_mail(mail, timeout=90)
    if not otp:
        print(f"[{tid}] ❌ OTP انتهى {phone} <- {email_short}", flush=True)
        update_stat("otp_fail")
        # نغيّر الإيميل عشان نعمل واحد جديد
        if _tempmail_provider:
            _tempmail_provider.change_mailbox()
        return 'retry'

    print(f"[{tid}] 🔢 OTP:{otp} {email_short}", flush=True)

    time.sleep(1)
    user, verify_err = verify_otp_api(ref, otp, headers, active_proxy)
    if not user:
        if verify_err == 'email_exists':
            print(f"[{tid}] ⚠️ إيميل مسجل (OTP) {email_short}...@{email_domain}", flush=True)
            update_stat("email_exists")
            return 'email_exists'
        elif verify_err == 'expired':
            print(f"[{tid}] ❌ OTP انتهى/غلط {phone}", flush=True)
            update_stat("confirm_fail")
            return 'retry'
        else:
            print(f"[{tid}] ❌ فشل التأكيد {phone} ({verify_err})", flush=True)
            update_stat("confirm_fail")
            return 'retry'

    total = save_account(email_addr, device, tok)
    print(f"[{tid}] ✅ حساب! {email_short} (#{total})", flush=True)

    # نغيّر الإيميل عشان نعمل واحد جديد للمرة الجاية
    if _tempmail_provider:
        _tempmail_provider.change_mailbox()

    if mode == "create":
        update_stat("accounts_ok")
        return 'ok'

    ready = upload_to_server(email_addr, device, tok)
    call_id, verify_url = trigger_async_call(phone, duration)
    if call_id:
        add_active_call(call_id, phone, email_short, tid)
        print(f"[{tid}] 📞 مكالمة! {phone} (ready:{ready}, id:{str(call_id)[:10]}...)", flush=True)
        return 'ok'

    result = trigger_make_call(phone, duration)
    status = result.get("status", "unknown")
    from_num = result.get("from", result.get("from_number", "?"))
    dur = result.get("duration", result.get("actual_duration", 0))
    error = result.get("error", "")

    if status == "answered_ok":
        print(f"[{tid}] ✅ تم الاتصال {phone} ({dur}s) <- {from_num}", flush=True)
        update_stat("calls_ok")
        return 'ok'
    elif "balance" in str(error).lower() or status == "no_balance":
        print(f"[{tid}] ⚠️ NO_BALANCE {phone}", flush=True)
        update_stat("calls_no_balance")
        update_stat("accounts_no_bal")
        return 'no_balance'
    else:
        print(f"[{tid}] ❌ فشل المكالمة {phone} ({error or status})", flush=True)
        update_stat("calls_failed")
        update_stat("accounts_ok")
        return 'no_balance'

def create_and_call(duration, mode="server", use_xrealip=True):
    tid = threading.current_thread().name

    while True:
        phone = get_next_phone()
        if not phone:
            break

        update_stat("total")

        success = False
        last_result = None
        for attempt in range(1, MAX_RETRIES + 1):
            if attempt > 1:
                update_stat("retries")
                print(f"[{tid}] 🔄 إعادة محاولة {attempt}/{MAX_RETRIES} لـ {phone}", flush=True)
                time.sleep(1)

            result = _try_one_phone(phone, duration, mode, tid)
            last_result = result

            if result in ('ok', 'no_balance'):
                success = True
                break
            elif result in ('domain_blocked', 'email_exists'):
                continue
            elif result == 'retry':
                continue
            else:
                break

        if not success:
            add_failed_phone(phone, last_result or 'unknown')
            print(f"[{tid}] ❌ فشل نهائي {phone} بعد {MAX_RETRIES} محاولات ({last_result})", flush=True)

        time.sleep(0.3)

# ═══════════════════════════════════════════════════════════════
# ─── Stats Printer ────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def print_stats():
    while True:
        time.sleep(30)
        with _stats_lock:
            s = dict(_stats)
        with _tempmail_stats_lock:
            ts = dict(_tempail_stats)
        elapsed = time.time() - _start_time if _start_time else 1
        rate = s['total'] / elapsed * 60 if elapsed > 0 else 0
        rl = _tempmail_provider._rate_limit_remaining if _tempmail_provider else '?'
        print(f"\n  📊 Stats ({elapsed/60:.1f}min | {rate:.1f}/min):", flush=True)
        print(f"     إجمالي: {s['total']} | ✅ حسابات: {s['accounts_ok']} | 📞 مكالمات: {s['calls_ok']}", flush=True)
        print(f"     ❌ إيميل={s['email_fail']} جلسة={s['session_fail']} تحقق={s['verify_fail']} OTP={s['otp_fail']} تأكيد={s['confirm_fail']}", flush=True)
        print(f"     إيميل مسجل: {s['email_exists']} | دومين محظور: {s['domain_blocked']} | NO_BALANCE: {s['calls_no_balance']}", flush=True)
        print(f"     temp-mail.org: ok={ts['ok']} fail={ts['fail']} OTP✅={ts['otp_ok']} OTP❌={ts['otp_fail']} (rate_limit:{rl})", flush=True)

# ═══════════════════════════════════════════════════════════════
# ─── Main ─────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def main():
    global _start_time, _phone_queue, _tempmail_provider

    parser = argparse.ArgumentParser(description="Fox Caller v15.0 - TempMail.org Edition")
    parser.add_argument("file", help="ملف الأرقام (.xlsx أو .txt)")
    parser.add_argument("--mode", choices=["server", "create"], default="server",
                       help="server=اتصال عبر السيرفر | create=إنشاء حسابات بس")
    parser.add_argument("--threads", type=int, default=DEFAULT_THREADS,
                       help=f"عدد الخيوط (افتراضي: {DEFAULT_THREADS})")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION,
                       help=f"مدة المكالمة بالثواني (افتراضي: {DEFAULT_DURATION})")
    parser.add_argument("--limit", type=int, default=0,
                       help="عدد الأرقام الأقصى")
    parser.add_argument("--no-xrealip", action="store_true",
                       help="إلغاء x-real-ip header")

    args = parser.parse_args()

    # ─── Initialize temp-mail.org provider ───
    _tempmail_provider = TempMailOrgProvider()

    print("\n" + "=" * 60, flush=True)
    print(f"  Fox Caller v15.0 - TempMail.org Edition", flush=True)
    print(f"  Email: mob2.temp-mail.org (@snocv.com / @tixpad.com)", flush=True)
    print(f"  ✅ requests عادي | لا Cloudflare | لا متصفح", flush=True)
    print("=" * 60, flush=True)

    numbers = read_numbers(args.file)
    if not numbers:
        print("ERROR: لا توجد أرقام في الملف!", flush=True)
        sys.exit(1)

    if args.limit > 0:
        numbers = numbers[:args.limit]

    _phone_queue = numbers
    _start_time = time.time()

    print(f"\n  Numbers:    {len(numbers)}", flush=True)
    print(f"  Mode:       {args.mode}", flush=True)
    print(f"  Threads:    {args.threads}", flush=True)
    print(f"  Duration:   {args.duration}s", flush=True)
    print(f"  Retries:    {MAX_RETRIES} per number", flush=True)
    print(f"  Email API:  mob2.temp-mail.org (Temp Mail app)", flush=True)

    init_proxy_manager()

    # ─── Quick Test ───
    print("\n  🔍 Quick Test: جرب temp-mail.org API...", flush=True)
    test_mail = _tempmail_provider.create_email()
    if test_mail:
        test_email = test_mail['email']
        test_domain = test_email.split('@')[1] if '@' in test_email else '?'
        print(f"  ✅ temp-mail.org: {test_email} ({test_domain})", flush=True)
        try:
            _email_pool.put_nowait(test_mail)
        except queue.Full:
            pass
    else:
        print(f"  ❌ temp-mail.org مش رد! السكريبت مش هيشتغل!", flush=True)
        sys.exit(1)

    # Check server
    if args.mode == "server":
        if is_server_available():
            print(f"  Server:     ✅ متاح ({SERVER_URL})", flush=True)
        else:
            print(f"  Server:     ⚠️ غير متاح! هنعمل create بس", flush=True)
            args.mode = "create"

    # Start pools
    start_pools()

    print(f"\n  🚀 بدء التشغيل...", flush=True)
    print("-" * 60, flush=True)

    stats_thread = threading.Thread(target=print_stats, daemon=True)
    stats_thread.start()

    if args.mode == "server":
        monitor_thread = threading.Thread(target=monitor_calls, daemon=True)
        monitor_thread.start()

    workers = []
    for i in range(args.threads):
        t = threading.Thread(
            target=create_and_call,
            args=(args.duration, args.mode, not args.no_xrealip),
            name=f"W{i+1}",
            daemon=True
        )
        t.start()
        workers.append(t)

    for t in workers:
        t.join()

    time.sleep(15)

    elapsed = time.time() - _start_time if _start_time else 0
    with _stats_lock:
        s = dict(_stats)
    with _tempmail_stats_lock:
        ts = dict(_tempail_stats)

    print("\n" + "=" * 60, flush=True)
    print("  📊 التقرير النهائي", flush=True)
    print("=" * 60, flush=True)
    print(f"  ⏱️  الوقت: {elapsed/60:.1f} دقيقة", flush=True)
    print(f"  📞 إجمالي: {s['total']} | ✅ حسابات: {s['accounts_ok']} | 📞 مكالمات: {s['calls_ok']}", flush=True)
    print(f"  ⚠️  NO_BALANCE: {s['calls_no_balance']} | ❌ فشل: {len(_failed_phones)}", flush=True)
    print(f"  📧 temp-mail.org: ok={ts['ok']} fail={ts['fail']} OTP✅={ts['otp_ok']} OTP❌={ts['otp_fail']}", flush=True)

    if _failed_phones:
        print(f"\n  ❌ أرقام فشلت:", flush=True)
        for fp in _failed_phones[:20]:
            print(f"     {fp['phone']} ({fp['reason']})", flush=True)
        if len(_failed_phones) > 20:
            print(f"     ... و {len(_failed_phones) - 20} كمان", flush=True)

    print("=" * 60, flush=True)
    _stop_flag.set()


if __name__ == "__main__":
    main()
