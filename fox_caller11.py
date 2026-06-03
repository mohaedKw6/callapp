#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fox Caller v19.0 - Gmail+Alias Auto Edition
=============================================
Email: Gmail+alias (تلقائي - بيتحفظ أول مرة بس)

الجديد في v19.0:
  - شيلنا temp-mail.org (كل الدومينات محظورة من Telicall)
  - شيلنا Gmail App Password Setup الطويل
  - أول مرة: بتدخل Gmail + App Password وبيتحفظوا
  - بعد كده: السكربت بيشتغل تلقائي من غير أي إعدادات
  - --gmail: عشان تدخل بيانات جديدة أو تغير الحساب

Usage:
  # وضع تلقائي (بيستخدم بيانات محفوظة أو بيسأل أول مرة):
  python3 fox_caller11.py numbers.xlsx
  python3 fox_caller11.py numbers.xlsx --mode server

  # وضع Gmail (إدخال بيانات جديدة):
  python3 fox_caller11.py numbers.xlsx --gmail
  python3 fox_caller11.py numbers.xlsx --gmail --email user@gmail.com --app-pass xxxx

  # إنشاء حسابات بس (بدون اتصال):
  python3 fox_caller11.py numbers.xlsx --mode create
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
import imaplib
import email as email_mod
from email.header import decode_header
from datetime import datetime
from filelock import FileLock

# ═══════════════════════════════════════════════════════════════
# ─── Config ───────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
API_URL           = "https://api.telicall.com"
SERVER_URL        = "https://callapp-production-c84c.up.railway.app"
ADMIN_KEY         = "06d271200e53fb4482acd8679bfe358a"
DAN_FILE          = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Dan.json")
CONFIG_FILE       = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".fox_caller_config.json")
PASSWORD          = "@@@GMAQ@@@"
DEFAULT_DURATION  = 64
DEFAULT_THREADS   = 3
EMAIL_POOL_SIZE   = 15
SESSION_POOL_SIZE = 5
MAX_RETRIES       = 8

# Gmail config
GMAIL_USER        = ""
GMAIL_APP_PASS    = ""
_used_aliases     = set()

# ═══════════════════════════════════════════════════════════════
# ─── Config File (Save/Load) ──────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def _obfuscate(data: str) -> str:
    """تشويش بسيط للبيانات في الكونفج"""
    key = "FoxCaller2024"
    raw = data.encode('utf-8')
    k = hashlib.sha256(key.encode()).digest()
    enc = bytes([raw[i] ^ k[i % len(k)] for i in range(len(raw))])
    return base64.b64encode(enc).decode('ascii')

def _deobfuscate(data: str) -> str:
    """فك التشويش"""
    key = "FoxCaller2024"
    raw = base64.b64decode(data)
    k = hashlib.sha256(key.encode()).digest()
    return bytes([raw[i] ^ k[i % len(k)] for i in range(len(raw))]).decode('utf-8')

def save_config(gmail_user, app_password):
    """بحفظ بيانات Gmail في ملف كونفج مشفر"""
    config = {
        'gmail': _obfuscate(gmail_user),
        'pass': _obfuscate(app_password),
        'saved': datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f)
        os.chmod(CONFIG_FILE, 0o600)
        return True
    except Exception:
        return False

def load_config():
    """بقرأ بيانات Gmail المحفوظة"""
    if not os.path.exists(CONFIG_FILE):
        return None, None
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        gmail = _deobfuscate(config.get('gmail', ''))
        app_pass = _deobfuscate(config.get('pass', ''))
        if gmail and app_pass:
            return gmail, app_pass
    except Exception:
        pass
    return None, None

def delete_config():
    """بيمسح الكونفج"""
    try:
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)
    except Exception:
        pass

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
# ─── Gmail Alias Generator ───────────────────────────────────
# ═══════════════════════════════════════════════════════════════
_gmail_stats = {"ok": 0, "fail": 0, "otp_ok": 0, "otp_fail": 0}
_gmail_stats_lock = threading.Lock()


class GmailAliasProvider:
    """بتعمل إيميلات Gmail + alias وبتقرأ OTP عن طريق IMAP
    
    Gmail + Trick:
      user+abc123@gmail.com -> يوصل لـ user@gmail.com
      u.s.e.r+abc123@gmail.com -> يوصل لـ user@gmail.com
      Telicall بيشوف كل واحد كحساب مختلف!
    
    IMAP:
      بنقرأ الرسائل من Gmail عن طريق IMAP مع App Password
      بنفلتر على رسائل Telicall وبنستخرج OTP
    """

    def __init__(self, gmail_user, app_password):
        self._gmail_user = gmail_user
        self._app_password = app_password
        if '@' in gmail_user:
            self._username, self._domain = gmail_user.split('@', 1)
        else:
            self._username = gmail_user
            self._domain = 'gmail.com'
        self._counter = 0
        self._counter_lock = threading.Lock()
        self._local = threading.local()
        self._dot_variations = self._generate_dot_variations(self._username)
        self._dot_index = 0

    def _generate_dot_variations(self, username):
        if len(username) <= 2:
            return [username]
        variations = []
        for i in range(1, len(username)):
            v = username[:i] + '.' + username[i:]
            variations.append(v)
        random.shuffle(variations)
        return variations[:20]

    def create_email(self):
        global _used_aliases
        with self._counter_lock:
            self._counter += 1
            count = self._counter
            dot_idx = (count - 1) % len(self._dot_variations)
            dot_user = self._dot_variations[dot_idx]
            tag = f"fx{count:05d}{random.randint(10,99)}"
            alias_email = f"{dot_user}+{tag}@{self._domain}"
            while alias_email in _used_aliases:
                tag = f"fx{count:05d}{random.randint(100,999)}"
                alias_email = f"{dot_user}+{tag}@{self._domain}"
            _used_aliases.add(alias_email)

        with _gmail_stats_lock:
            _gmail_stats["ok"] += 1

        return {
            'email': alias_email,
            'provider': 'gmail_alias',
            'api_type': 'gmail_imap',
            'created_ts': int(time.time()),
            'gmail_user': self._gmail_user,
        }

    def _get_imap(self):
        if not hasattr(self._local, 'imap') or self._local.imap is None:
            try:
                imap = imaplib.IMAP4_SSL('imap.gmail.com', 993)
                imap.login(self._gmail_user, self._app_password)
                self._local.imap = imap
            except Exception as e:
                print(f"  IMAP login فشل: {e}", flush=True)
                return None
        return self._local.imap

    def _reconnect_imap(self):
        if hasattr(self._local, 'imap') and self._local.imap:
            try:
                self._local.imap.logout()
            except Exception:
                pass
        self._local.imap = None
        return self._get_imap()

    def check_otp(self, mail_info, timeout=90):
        created_ts = mail_info.get('created_ts', 0)
        target_email = mail_info.get('email', '')
        deadline = time.time() + timeout
        seen_ids = set()

        while time.time() < deadline:
            try:
                imap = self._get_imap()
                if imap is None:
                    imap = self._reconnect_imap()
                    if imap is None:
                        time.sleep(5)
                        continue
                imap.select('INBOX')
                status, messages = imap.search(None, '(UNSEEN FROM "telicall")')
                if status != 'OK':
                    status, messages = imap.search(None, '(UNSEEN SUBJECT "verification")')
                if status != 'OK':
                    status, messages = imap.search(None, '(UNSEEN SUBJECT "Telicall")')
                if status != 'OK':
                    status, messages = imap.search(None, '(UNSEEN)')
                if status == 'OK' and messages[0]:
                    msg_ids = messages[0].split()
                    for msg_id in msg_ids[-15:]:
                        if msg_id in seen_ids:
                            continue
                        seen_ids.add(msg_id)
                        status, msg_data = imap.fetch(msg_id, '(RFC822)')
                        if status == 'OK':
                            raw = msg_data[0][1]
                            msg = email_mod.message_from_bytes(raw)
                            subject = str(msg.get('Subject', ''))
                            decoded_subj = self._decode_header(subject)
                            otp = self._extract_otp(decoded_subj)
                            if otp:
                                with _gmail_stats_lock:
                                    _gmail_stats["otp_ok"] += 1
                                return otp
                            body = self._get_body(msg)
                            if body:
                                otp = self._extract_otp(body)
                                if otp:
                                    with _gmail_stats_lock:
                                        _gmail_stats["otp_ok"] += 1
                                    return otp
            except imaplib.IMAP4.error:
                self._reconnect_imap()
            except Exception:
                pass
            time.sleep(5)

        with _gmail_stats_lock:
            _gmail_stats["otp_fail"] += 1
        return None

    def _decode_header(self, header_value):
        if not header_value:
            return ''
        try:
            parts = decode_header(header_value)
            decoded = []
            for part, enc in parts:
                if isinstance(part, bytes):
                    decoded.append(part.decode(enc or 'utf-8', errors='ignore'))
                else:
                    decoded.append(part)
            return ''.join(decoded)
        except Exception:
            return str(header_value)

    def _get_body(self, msg):
        body = ''
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == 'text/plain':
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or 'utf-8'
                        body = payload.decode(charset, errors='ignore')
                    except Exception:
                        pass
                    break
                elif content_type == 'text/html' and not body:
                    try:
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or 'utf-8'
                        body = payload.decode(charset, errors='ignore')
                    except Exception:
                        pass
        else:
            try:
                payload = msg.get_payload(decode=True)
                charset = msg.get_content_charset() or 'utf-8'
                body = payload.decode(charset, errors='ignore')
            except Exception:
                pass
        return body

    def _extract_otp(self, text):
        if not text:
            return None
        m = re.search(r'\b(\d{6})\b', text)
        if m:
            return m.group(1)
        return None

    def change_mailbox(self):
        pass

    def test_connection(self):
        try:
            imap = imaplib.IMAP4_SSL('imap.gmail.com', 993)
            imap.login(self._gmail_user, self._app_password)
            imap.select('INBOX')
            status, messages = imap.search(None, 'ALL')
            count = len(messages[0].split()) if messages[0] else 0
            imap.logout()
            return True, count
        except imaplib.IMAP4.authentication_errors:
            return False, "App Password غلط!"
        except Exception as e:
            return False, str(e)


# ─── Global provider instance ───
_email_provider = None  # يتم تعيينه في main()

# ═══════════════════════════════════════════════════════════════
# ─── Email Pool ──────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
_email_pool = queue.Queue(maxsize=EMAIL_POOL_SIZE)
_session_pool = queue.Queue(maxsize=SESSION_POOL_SIZE)
_stop_flag = threading.Event()
_pool_stats = {"emails_created": 0, "sessions_created": 0}
_pool_stats_lock = threading.Lock()

def _email_pool_filler():
    """خلفية: بيملا بول الإيميلات"""
    while not _stop_flag.is_set():
        if _email_pool.qsize() < EMAIL_POOL_SIZE:
            mail = None
            if _email_provider:
                mail = _email_provider.create_email()

            if mail:
                try:
                    _email_pool.put_nowait(mail)
                    with _pool_stats_lock:
                        _pool_stats["emails_created"] += 1
                except queue.Full:
                    pass
            else:
                time.sleep(1)
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
        if _email_provider:
            mail = _email_provider.create_email()
            if mail:
                return mail
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
    if _email_provider:
        return _email_provider.check_otp(mail_info, timeout=timeout)
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
                if 'blocklist' in err_lower or 'blocked' in err_lower:
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
                        print(f"[{tid}] + تم الاتصال {phone} ({dur}s) <- {caller}", flush=True)
                        update_stat("calls_ok")
                    elif s in ("failed", "error"):
                        err = status_data.get("error", "")
                        if "balance" in str(err).lower():
                            print(f"[{tid}] - NO_BALANCE {phone}", flush=True)
                            update_stat("calls_no_balance")
                        else:
                            print(f"[{tid}] - فشل المكالمة {phone} ({err})", flush=True)
                            update_stat("calls_failed")
                        continue
                    else:
                        remaining.append(c)
                else:
                    elapsed = time.time() - c["started"]
                    if elapsed > 300:
                        print(f"[{tid}] TIMEOUT {c['phone']}", flush=True)
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
        print(f"[{tid}] - لا إيميل متاح {phone}", flush=True)
        update_stat("email_fail")
        return 'retry'

    email_addr = mail['email']
    email_short = email_addr.split('@')[0][:12]
    email_domain = email_addr.split('@')[1] if '@' in email_addr else '?'

    print(f"[{tid}] @ {email_short}...@{email_domain} -> {phone}", flush=True)

    tok, device, headers, sess_proxy = get_session_from_pool()
    active_proxy = sess_proxy or get_proxy()

    if not tok:
        print(f"[{tid}] - فشل الجلسة {phone}", flush=True)
        update_stat("session_fail")
        return 'retry'

    ref, err = send_verify(email_addr, headers, active_proxy)
    if not ref:
        err_str = str(err or "")
        if err_str == 'EMAIL_EXISTS':
            print(f"[{tid}] ~ إيميل مسجل {email_short}...@{email_domain}", flush=True)
            update_stat("email_exists")
            return 'email_exists'
        elif err_str.startswith('BLOCKED:'):
            blocked_domain = err_str.split(':', 1)[1]
            print(f"[{tid}] - دومين محظور: {blocked_domain} {phone}", flush=True)
            update_stat("domain_blocked")
            return 'domain_blocked'
        else:
            print(f"[{tid}] - فشل التحقق {phone} ({err_str[:50]})", flush=True)
            update_stat("verify_fail")
        if active_proxy:
            active_proxy = get_proxy_and_mark_dead(active_proxy)
        return 'retry'

    # ─── انتظار OTP ───
    otp = get_otp_from_mail(mail, timeout=90)
    if not otp:
        print(f"[{tid}] - OTP انتهى {phone} <- {email_short}", flush=True)
        update_stat("otp_fail")
        return 'retry'

    print(f"[{tid}] # OTP:{otp} {email_short}", flush=True)

    time.sleep(1)
    user, verify_err = verify_otp_api(ref, otp, headers, active_proxy)
    if not user:
        if verify_err == 'email_exists':
            print(f"[{tid}] ~ إيميل مسجل (OTP) {email_short}...@{email_domain}", flush=True)
            update_stat("email_exists")
            return 'email_exists'
        elif verify_err == 'expired':
            print(f"[{tid}] - OTP انتهى/غلط {phone}", flush=True)
            update_stat("confirm_fail")
            return 'retry'
        else:
            print(f"[{tid}] - فشل التأكيد {phone} ({verify_err})", flush=True)
            update_stat("confirm_fail")
            return 'retry'

    total = save_account(email_addr, device, tok)
    print(f"[{tid}] + حساب! {email_short} (#{total})", flush=True)

    if mode == "create":
        update_stat("accounts_ok")
        return 'ok'

    ready = upload_to_server(email_addr, device, tok)
    call_id, verify_url = trigger_async_call(phone, duration)
    if call_id:
        add_active_call(call_id, phone, email_short, tid)
        print(f"[{tid}] >> مكالمة! {phone} (ready:{ready}, id:{str(call_id)[:10]}...)", flush=True)
        return 'ok'

    result = trigger_make_call(phone, duration)
    status = result.get("status", "unknown")
    from_num = result.get("from", result.get("from_number", "?"))
    dur = result.get("duration", result.get("actual_duration", 0))
    error = result.get("error", "")

    if status == "answered_ok":
        print(f"[{tid}] + تم الاتصال {phone} ({dur}s) <- {from_num}", flush=True)
        update_stat("calls_ok")
        return 'ok'
    elif "balance" in str(error).lower() or status == "no_balance":
        print(f"[{tid}] ~ NO_BALANCE {phone}", flush=True)
        update_stat("calls_no_balance")
        update_stat("accounts_no_bal")
        return 'no_balance'
    else:
        print(f"[{tid}] - فشل المكالمة {phone} ({error or status})", flush=True)
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
                print(f"[{tid}] ~ إعادة محاولة {attempt}/{MAX_RETRIES} لـ {phone}", flush=True)
                time.sleep(1)

            result = _try_one_phone(phone, duration, mode, tid)
            last_result = result

            if result == 'ok':
                success = True
                break
            elif result == 'no_balance':
                break
            elif result == 'email_exists':
                continue
            elif result == 'domain_blocked':
                break
            else:  # retry
                continue

        if not success:
            add_failed_phone(phone, last_result or "unknown")


# ═══════════════════════════════════════════════════════════════
# ─── Main ────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def main():
    global _email_provider, _start_time, GMAIL_USER, GMAIL_APP_PASS
    global MAX_RETRIES, _phone_queue

    parser = argparse.ArgumentParser(description='Fox Caller v19.0 - Gmail+Alias Auto Edition')
    parser.add_argument('file', help='ملف الأرقام (xlsx أو txt)')
    parser.add_argument('--gmail', action='store_true', default=False,
                        help='أعد إدخال بيانات Gmail (غيّر الحساب)')
    parser.add_argument('--email', default=None,
                        help='إيميل Gmail (مثال: user@gmail.com)')
    parser.add_argument('--app-pass', default=None,
                        help='Gmail App Password (16 حرف بدون مسافات)')
    parser.add_argument('--mode', choices=['server', 'create'], default='server',
                        help='server = اتصال تلقائي, create = إنشاء حسابات بس')
    parser.add_argument('--threads', type=int, default=DEFAULT_THREADS,
                        help=f'عدد الخيوط (افتراضي: {DEFAULT_THREADS})')
    parser.add_argument('--duration', type=int, default=DEFAULT_DURATION,
                        help=f'مدة المكالمة بالثواني (افتراضي: {DEFAULT_DURATION})')
    parser.add_argument('--retries', type=int, default=MAX_RETRIES,
                        help=f'عدد المحاولات لكل رقم (افتراضي: {MAX_RETRIES})')
    args = parser.parse_args()

    # ─── تحديد بيانات Gmail ───
    gmail_addr = args.email
    app_pass = args.app_pass

    # لو --gmail: إدخال جديد (حتى لو في كونفج محفوظ)
    # لو بدون --gmail: نستخدم الكونفج المحفوظ أو نسأل
    use_saved = not args.gmail

    if use_saved and not gmail_addr:
        # نحاول نقرأ من الكونفج المحفوظ
        saved_gmail, saved_pass = load_config()
        if saved_gmail and saved_pass:
            gmail_addr = saved_gmail
            app_pass = saved_pass
            print(f"  بيانات Gmail محفوظة: {gmail_addr}", flush=True)

    if not gmail_addr:
        gmail_addr = input("  Gmail: ").strip()
    if not app_pass:
        app_pass = input("  App Password: ").strip()

    if not gmail_addr or not app_pass:
        print(" لازم تكتب الإيميل و الـ App Password!", flush=True)
        sys.exit(1)

    GMAIL_USER = gmail_addr
    GMAIL_APP_PASS = app_pass.replace(' ', '')

    # حفظ الكونفج
    save_config(GMAIL_USER, GMAIL_APP_PASS)
    print(f"  تم حفظ البيانات! المرة الجاية هيشتغل تلقائي.", flush=True)

    # ─── Banner ───
    print("=" * 60, flush=True)
    print("  Fox Caller v19.0 - Gmail+Alias Auto Edition", flush=True)
    print(f"  Email:      {GMAIL_USER} (Gmail+alias)", flush=True)
    print("  +alias:     user+tag@gmail.com / u.s.e.r+tag@gmail.com", flush=True)
    print("=" * 60)
    print(flush=True)

    # ─── Test Gmail IMAP ───
    print("  Quick Test: جرب Gmail IMAP...", flush=True)
    _email_provider = GmailAliasProvider(GMAIL_USER, GMAIL_APP_PASS)
    ok, info = _email_provider.test_connection()
    if not ok:
        print(f"  Gmail IMAP مش شغال! {info}", flush=True)
        print(f"  تأكد إنك:", flush=True)
        print(f"    1. فعّلت IMAP في Gmail Settings", flush=True)
        print(f"    2. فعّلت 2-Step Verification", flush=True)
        print(f"    3. عملت App Password", flush=True)
        # مسح الكونفج الغلط
        delete_config()
        sys.exit(1)
    print(f"  Gmail IMAP شغال! ({info} رسائل في الـ inbox)", flush=True)

    # ─── Read Numbers ───
    numbers = read_numbers(args.file)
    if not numbers:
        print("مفيش أرقام في الملف!", flush=True)
        sys.exit(1)

    MAX_RETRIES = args.retries
    _phone_queue = numbers

    # ─── Print Config ───
    print(flush=True)
    print(f"  Numbers:    {len(numbers)}", flush=True)
    print(f"  Mode:       {args.mode}", flush=True)
    print(f"  Threads:    {args.threads}", flush=True)
    print(f"  Duration:   {args.duration}s", flush=True)
    print(f"  Retries:    {MAX_RETRIES} per number", flush=True)
    print(f"  Provider:   Gmail ({GMAIL_USER})", flush=True)

    init_proxy_manager()

    # ─── Test Telicall ───
    test_tok, _, _ = init_session()
    if not test_tok:
        print("  Telicall init فشل — ممكن يكون في مشكلة شبكة", flush=True)
    else:
        test_mail = _email_provider.create_email()
        test_ref, test_err = send_verify(test_mail['email'], {
            "host": "api.telicall.com",
            "x-request-id": str(uuid.uuid4()),
            "user-agent": "Dalvik/2.1.0",
            "x-app-version": "1.2.1",
            "x-client-device-id": "test123",
            "x-lang": "en", "x-os": "android", "x-os-version": "11",
            "x-req-timestamp": str(int(time.time() * 1000)),
            "x-req-signature": "-1",
            "content-type": "application/json",
            "x-token": test_tok,
            "x-currency": "EGP",
            "x-real-ip": rand_eg_ip(),
        })
        if test_ref:
            print(f"  Telicall بيقبل الإيميل! ({test_mail['email'][:30]}...)", flush=True)
        else:
            print(f"  Telicall رفض الإيميل: {test_err}", flush=True)

    print(flush=True)

    # ─── Start ───
    _start_time = time.time()
    start_pools()

    # Start call monitor thread
    t = threading.Thread(target=monitor_calls, daemon=True)
    t.start()

    # Start worker threads
    threads = []
    for i in range(args.threads):
        t = threading.Thread(target=create_and_call,
                             args=(args.duration, args.mode),
                             name=f"W{i+1}", daemon=False)
        t.start()
        threads.append(t)

    # Wait for all threads
    for t in threads:
        t.join()

    # ─── Final Stats ───
    elapsed = time.time() - _start_time
    print(flush=True)
    print("=" * 60, flush=True)
    print("  النتائج النهائية", flush=True)
    print("=" * 60, flush=True)
    print(f"  الوقت:          {elapsed:.0f}s ({elapsed/60:.1f} min)", flush=True)
    print(f"  إجمالي الأرقام:  {_stats['total']}", flush=True)
    print(f"  مكالمات ناجحة:   {_stats['calls_ok']}", flush=True)
    print(f"  حسابات جديدة:    {_stats['accounts_ok']}", flush=True)
    print(f"  لا رصيد:         {_stats['calls_no_balance']}", flush=True)
    print(f"  إيميل مسجل:      {_stats['email_exists']}", flush=True)
    print(f"  دومين محظور:     {_stats['domain_blocked']}", flush=True)
    print(f"  فشل التحقق:      {_stats['verify_fail']}", flush=True)
    print(f"  فشل OTP:         {_stats['otp_fail']}", flush=True)
    print(f"  فشل التأكيد:     {_stats['confirm_fail']}", flush=True)
    print(f"  فشل الجلسة:      {_stats['session_fail']}", flush=True)
    print(f"  فشل مكالمة:      {_stats['calls_failed']}", flush=True)
    print(f"  إعادة محاولات:   {_stats['retries']}", flush=True)
    print(f"  Gmail إيميلات:   {_gmail_stats['ok']}", flush=True)
    print(f"  Gmail OTP ناجح:  {_gmail_stats['otp_ok']}", flush=True)
    print(f"  Gmail OTP فشل:   {_gmail_stats['otp_fail']}", flush=True)

    if _failed_phones:
        print(flush=True)
        print(f"  الأرقام الفاشلة ({len(_failed_phones)}):", flush=True)
        for fp in _failed_phones[:20]:
            print(f"    {fp['phone']} - {fp['reason']}", flush=True)

    print("=" * 60, flush=True)


if __name__ == '__main__':
    main()
