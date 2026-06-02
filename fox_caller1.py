#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fox Caller v5.0 - Fixed Call Launcher
======================================
FIXES over v4.0:
  - Proxy support for account creation (accounts GET balance!)
  - Multiple email providers (temp-mail.org + temp-mail.io)
  - 45+ email domains (not just hitzcart.com)
  - Balance check before uploading to server (no more NO_BALANCE!)
  - Non-blocking: concurrent calls via threads + async server endpoint
  - Reports: [W1] ANSWERED_OK +966510122129 (64.0s) <- 447447233691

Usage:
  python3 fox_caller1.py numbers.xlsx
  python3 fox_caller1.py numbers.xlsx --duration 64 --threads 5
  python3 fox_caller1.py numbers.xlsx --proxies alive_proxies.txt
"""

import requests
import json
import uuid
import time
import random
import re
import os
import string
import hashlib
import base64
import threading
import argparse
import sys
from datetime import datetime
from filelock import FileLock

# ═══════════════════════════════════════════════════════════════
# ─── Config ───────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
API_URL       = "https://api.telicall.com"
SERVER_URL    = "https://callapp-production-c84c.up.railway.app"
ADMIN_KEY     = "06d271200e53fb4482acd8679bfe358a"
DAN_FILE      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Dan.json")
PASSWORD      = "@@@GMAQ@@@"
DEFAULT_DURATION = 64
DEFAULT_THREADS   = 5

# 45+ email domains that work with temp-mail.io
DOMAINS = [
    "daouse.com", "bltiwd.com", "rommiui.com", "mrotzis.com",
    "mkzaso.com", "illubd.com", "wnbaldwy.com", "xkxkud.com",
    "yzcalo.com", "ozsaip.com", "bwmyga.com", "ruutukf.com",
    "inovic.com", "vmani.com", "dpptd.com", "moflix.com",
    "fanclub.com", "nqmo.com", "hostaldelrio.com", "sjgpne.com",
    "lfatj.com", "kzlcl.com", "vbaif.com", "yarbfi.com",
    "rcedem.com", "mkgt.com", "fexbox.org", "bheps.com",
    "lgbtq.page", "triots.com", "kalmlom.com", "khreb.com",
    "okhfb.com", "adrianou.com", "psnator.com", "rigle.com",
    "plonker.com", "9me1.com", "maulve.com", "txcct.com",
    "chitthuri.com", "digiway.com", "freps.click", "pirol.com",
    "retre.org", "hitzcart.com", "googxs.co", "doreact.co",
    "ifcoat.co", "matkind.co", "googlemail.com",
]

# ═══════════════════════════════════════════════════════════════
# ─── Proxy Manager (from t.py - accounts get balance!) ───────
# ═══════════════════════════════════════════════════════════════
PROXY_FILE      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alive_proxies.txt")
_proxy_lock     = threading.Lock()
_dead_proxies   = set()
_proxy_list     = []

def _load_proxies_from_file():
    """Load proxies from file (supports http://, socks5://, ip:port)"""
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
    """Initialize proxy manager - call once at startup"""
    global _proxy_list
    _proxy_list = _load_proxies_from_file()
    if _proxy_list:
        types = {}
        for p in _proxy_list:
            t = p.split('://')[0]
            types[t] = types.get(t, 0) + 1
        breakdown = ' | '.join(f"{k}={v}" for k, v in sorted(types.items()))
        print(f"  Proxies:     {len(_proxy_list)} loaded ({breakdown})", flush=True)
    else:
        print(f"  Proxies:     None (using x-real-ip fallback)", flush=True)
        print(f"  WARNING:     Accounts may have NO BALANCE without proxies!", flush=True)

def get_proxy():
    """Get a random alive proxy dict, or None"""
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
    """Mark current proxy as dead and get a new one"""
    if proxy_dict:
        url = list(proxy_dict.values())[0]
        _mark_dead(url)
        with _proxy_lock:
            alive_count = len([p for p in _proxy_list if p not in _dead_proxies])
        if alive_count % 10 == 0:
            print(f"  ⚠ Alive proxies: {alive_count}", flush=True)
    return get_proxy()

# ═══════════════════════════════════════════════════════════════
# ─── Egyptian IP Generator (fallback when no proxies) ────────
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
    """Generate random Egyptian IP (for x-real-ip fallback)"""
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
# ─── Email Providers ──────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

# --- temp-mail.org (mob2 endpoint) ---
def create_mob2_mail(proxy_dict=None):
    """Create email via mob2.temp-mail.org"""
    try:
        r = requests.post(
            "https://mob2.temp-mail.org/mailbox",
            headers={'Accept': 'application/json', 'User-Agent': '3.49',
                     'Accept-Encoding': 'gzip'},
            proxies=proxy_dict, timeout=8
        )
        if r.status_code == 200:
            d = r.json()
            if d.get('mailbox') and d.get('token'):
                return {'email': d['mailbox'], 'token': d['token'], 'api_type': 'mob2'}
    except Exception:
        pass
    return None

# --- temp-mail.io (45+ domains) ---
def create_io_mail(proxy_dict=None):
    """Create email via temp-mail.io with random domain"""
    domain = random.choice(DOMAINS)
    name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    try:
        r = requests.post(
            "https://api.internal.temp-mail.io/api/v3/email/new",
            json={"domain": domain, "name": name},
            headers={
                'Accept': 'application/json',
                'Application-Name': 'web',
                'Application-Version': '2.2.29',
                'Origin': 'https://temp-mail.io',
                'User-Agent': 'Mozilla/5.0'
            },
            proxies=proxy_dict, timeout=8
        )
        if r.status_code == 200:
            email = r.json().get('email')
            if email:
                return {'email': email, 'token': email, 'api_type': 'io'}
    except Exception:
        pass
    return None

# --- web2.temp-mail.org (legacy) ---
WEB2_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Origin': 'https://temp-mail.org',
    'Referer': 'https://temp-mail.org/',
    'Content-Type': 'application/json'
}

def create_web2_mail(proxy_dict=None):
    """Create email via web2.temp-mail.org (legacy)"""
    try:
        r = requests.post("https://web2.temp-mail.org/mailbox",
                          headers=WEB2_HEADERS, proxies=proxy_dict, timeout=10)
        if r.status_code in [200, 201]:
            data = r.json()
            email = data.get('mailbox', '')
            token = data.get('token', '')
            if email and token:
                return {'email': email, 'token': token, 'api_type': 'web2'}
    except Exception:
        pass
    return None

def create_email(proxy_dict=None):
    """Create temp email - tries all providers in parallel, returns first success"""
    result = [None]
    done = threading.Event()

    def _try(fn):
        r = fn()
        if r and not done.is_set():
            done.set()
            result[0] = r

    threads = [
        threading.Thread(target=_try, args=(lambda: create_mob2_mail(proxy_dict),)),
        threading.Thread(target=_try, args=(lambda: create_io_mail(proxy_dict),)),
        threading.Thread(target=_try, args=(lambda: create_web2_mail(proxy_dict),)),
    ]
    for t in threads:
        t.start()
    done.wait(timeout=10)
    return result[0]


# --- Inbox checking ---
def check_mob2_inbox(tkn, proxy_dict=None):
    try:
        r = requests.get(
            "https://mob2.temp-mail.org/messages",
            headers={'Accept': 'application/json', 'User-Agent': '3.49',
                     'Authorization': tkn},
            proxies=proxy_dict, timeout=8
        )
        if r.status_code == 200:
            return r.json().get('messages', [])
    except Exception:
        pass
    return []

def check_io_inbox(email, proxy_dict=None):
    try:
        r = requests.get(
            f"https://api.internal.temp-mail.io/api/v3/email/{email}/messages",
            proxies=proxy_dict, timeout=8
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []

def check_web2_inbox(email_token, proxy_dict=None):
    try:
        headers = WEB2_HEADERS.copy()
        headers['Authorization'] = f'Bearer {email_token}'
        r = requests.get('https://web2.temp-mail.org/messages',
                         headers=headers, proxies=proxy_dict, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else data.get('messages', [])
    except Exception:
        pass
    return []

def get_otp(api_type, token_or_email, proxy_dict=None, timeout=90):
    """Get OTP from email inbox with timeout"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if api_type == 'mob2':
                messages = check_mob2_inbox(token_or_email, proxy_dict)
            elif api_type == 'io':
                messages = check_io_inbox(token_or_email, proxy_dict)
            elif api_type == 'web2':
                messages = check_web2_inbox(token_or_email, proxy_dict)
            else:
                messages = []

            for msg in messages:
                content = str(
                    msg.get('text', '') or msg.get('body', '') or
                    msg.get('bodyPreview', '') or msg.get('content', '') or msg
                )
                subject = str(msg.get('subject', '')).lower()
                sender = str(msg.get('from', '')).lower()
                combined = f"{sender} {subject} {content}".lower()
                if 'teli' in combined or 'verification' in subject or 'verify' in subject:
                    m = re.search(r'\b(\d{6})\b', content)
                    if m:
                        return m.group(1)
        except Exception:
            pass
        time.sleep(2)
    return None

# ═══════════════════════════════════════════════════════════════
# ─── Telicall API ─────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def init_session(proxy_dict=None, use_real_ip=False):
    """Initialize Telicall session.
    
    Args:
        proxy_dict: Proxy to use (preferred - accounts get balance!)
        use_real_ip: If True and no proxy, use x-real-ip header
    """
    device = ''.join(random.choices('0123456789abcdef', k=16))
    ip = rand_eg_ip() if use_real_ip else ""

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
    # Add x-real-ip ONLY when no proxy (fallback mode)
    if ip and not proxy_dict:
        h["x-currency"] = "EGP"
        h["x-real-ip"] = ip

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
                          proxies=proxy_dict, timeout=10)
        if r.status_code == 200:
            tok = r.json().get('result', {}).get('token')
            if tok:
                h["x-token"] = tok
                return tok, device, h
    except Exception:
        pass
    return None, None, None

def send_verify(email, headers, proxy_dict=None):
    """Send verification email"""
    try:
        headers["x-request-id"] = str(uuid.uuid4())
        headers["x-req-timestamp"] = str(int(time.time() * 1000))
        r = requests.post(f"{API_URL}/auth/send-email", json={'email': email},
                          headers=headers, proxies=proxy_dict, timeout=10)
        if r.status_code == 200:
            return r.json().get('result', {}).get('reference')
    except Exception:
        pass
    return None

def verify_otp_api(ref, code, headers, proxy_dict=None):
    """Verify OTP code"""
    try:
        headers["x-request-id"] = str(uuid.uuid4())
        headers["x-req-timestamp"] = str(int(time.time() * 1000))
        r = requests.post(f"{API_URL}/auth/verify-identity",
                          json={'reference': ref, 'code': str(code)},
                          headers=headers, proxies=proxy_dict, timeout=10)
        if r.status_code == 200:
            return r.json().get('result', {}).get('user')
    except Exception:
        pass
    return None

def check_token_balance(token, device_id, proxy_dict=None):
    """Check if a token has balance by trying to start a test call.
    
    Returns:
        True if account has balance (call API accepted)
        False if NO_BALANCE
        None if inconclusive
    """
    h = {
        "host": "api.telicall.com",
        "x-request-id": str(uuid.uuid4()),
        "user-agent": "Dalvik/2.1.0",
        "x-app-version": "1.2.1",
        "x-client-device-id": device_id,
        "x-lang": "en", "x-os": "android", "x-os-version": "11",
        "x-req-timestamp": str(int(time.time() * 1000)),
        "x-req-signature": "-1",
        "content-type": "application/json",
        "x-token": token,
    }
    # Add x-real-ip when no proxy
    if not proxy_dict:
        h["x-currency"] = "EGP"
        h["x-real-ip"] = rand_eg_ip()

    try:
        # Use a dummy number just to check if the API accepts or rejects
        r = requests.post(
            f"{API_URL}/call/outbound/start",
            json={'to': '+201000000000', 'source': 'numpad'},
            headers=h, proxies=proxy_dict, timeout=10
        )
        if r.status_code == 200 and r.json().get('result'):
            return True  # Has balance - API returned SIP credentials
        elif r.status_code == 400:
            err = r.text.lower()
            if 'balance' in err:
                return False  # NO_BALANCE
            return None  # Other 400 error (maybe invalid number)
        else:
            return None  # Inconclusive
    except Exception:
        return None

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
    """Save account to encrypted Dan.json"""
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
def upload_to_server(email, device_id, token):
    """Upload account token to server"""
    try:
        r = requests.post(f"{SERVER_URL}/api/fox-caller/upload-accounts",
                          headers={"Content-Type": "application/json",
                                   "x-admin-key": ADMIN_KEY},
                          json={"accounts": [{"email": email,
                                              "x-client-device-id": device_id,
                                              "x-token": token}]},
                          timeout=15)
        if r.status_code == 200:
            data = r.json()
            return data.get("ready_tokens", 0)
    except Exception:
        pass
    return 0

def trigger_async_call(phone, duration=64):
    """Trigger async call on server (fire and forget)"""
    try:
        r = requests.post(f"{SERVER_URL}/api/fox-caller/async-call",
                          headers={"Content-Type": "application/json",
                                   "x-admin-key": ADMIN_KEY},
                          json={"phone": phone, "duration": duration},
                          timeout=15)
        if r.status_code == 200:
            data = r.json()
            return data.get("call_id"), data.get("verification_url", "")
    except Exception:
        pass
    return None, ""

def trigger_make_call(phone, duration=64):
    """Trigger blocking call on server (waits for completion)"""
    try:
        r = requests.post(f"{SERVER_URL}/api/fox-caller/make-call",
                          headers={"Content-Type": "application/json",
                                   "x-admin-key": ADMIN_KEY},
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
    """Check async call status on server"""
    try:
        r = requests.get(f"{SERVER_URL}/api/fox-caller/call-status/{call_id}",
                         timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

def get_server_stats():
    """Get server stats (ready tokens, etc.)"""
    try:
        r = requests.get(f"{SERVER_URL}/api/admin/stats",
                         headers={"x-admin-key": ADMIN_KEY}, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}

# ═══════════════════════════════════════════════════════════════
# ─── Read Numbers from File ──────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def read_numbers(filepath):
    """Read phone numbers from .xlsx or .txt file"""
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

    # Remove duplicates
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
    "answered": 0,
    "no_answer": 0,
    "busy": 0,
    "failed": 0,
    "no_balance": 0,
    "accounts_created": 0,
    "accounts_no_balance": 0,
    "total": 0,
}
_start_time = None

# Phone queue
_phone_queue = []
_queue_lock = threading.Lock()
_queue_index = 0

def get_next_phone():
    global _queue_index
    with _queue_lock:
        if _queue_index < len(_phone_queue):
            phone = _phone_queue[_queue_index]
            _queue_index += 1
            return phone
    return None

def update_stat(key, delta=1):
    with _stats_lock:
        _stats[key] += delta

def format_stats():
    elapsed = time.time() - _start_time if _start_time else 0
    mins = int(elapsed) // 60
    secs = int(elapsed) % 60
    with _stats_lock:
        s = _stats
        return (f"Stats [{mins}m{secs}s] "
                f"{s['answered']} Ans | {s['no_answer']} NoA | "
                f"{s['busy']} Bsy | {s['no_balance']} NoBal | "
                f"{s['failed']} Fail | "
                f"Accounts: {s['accounts_created']} ok / {s['accounts_no_balance']} no-bal | "
                f"{s['total']} Total")

# ═══════════════════════════════════════════════════════════════
# ─── Active Call Tracking ─────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
_active_calls = []
_active_call_lock = threading.Lock()

def add_active_call(call_id, phone, caller_info, tid):
    with _active_call_lock:
        _active_calls.append({
            "call_id": call_id,
            "phone": phone,
            "caller": caller_info,
            "tid": tid,
            "started": time.time()
        })

def monitor_calls():
    """Background thread: poll async call statuses and report results"""
    while True:
        time.sleep(8)
        with _active_call_lock:
            remaining = []
            for c in _active_calls:
                status_data = check_call_status(c["call_id"])
                if status_data:
                    s = status_data.get("status", "")
                    dur = status_data.get("actual_duration", 0)
                    phone = c["phone"]
                    caller = status_data.get("from_number", c["caller"])
                    tid = c["tid"]

                    if s == "answered_ok":
                        verified = status_data.get("verified", False)
                        if verified:
                            print(f"[{tid}] ANSWERED_OK {phone} ({dur}s) <- {caller}", flush=True)
                            update_stat("answered")
                        else:
                            print(f"[{tid}] ANSWERED_SHORT {phone} ({dur}s) <- {caller}", flush=True)
                            update_stat("no_answer")
                        continue  # Done, don't keep in list

                    elif s == "failed":
                        print(f"[{tid}] CALL_FAILED {phone} <- {caller}", flush=True)
                        update_stat("failed")
                        continue

                    elif s == "error":
                        err = status_data.get("error", "")
                        if "balance" in err.lower() or "no_balance" in err.lower():
                            print(f"[{tid}] NO_BALANCE {phone}", flush=True)
                            update_stat("no_balance")
                        else:
                            print(f"[{tid}] ERROR {phone}: {err}", flush=True)
                            update_stat("failed")
                        continue

                    # Still in progress (ringing/calling)
                    remaining.append(c)
                else:
                    # Can't check status - timeout after 5 min
                    elapsed = time.time() - c["started"]
                    if elapsed > 300:
                        print(f"[{tid}] TIMEOUT {c['phone']}", flush=True)
                        update_stat("failed")
                    else:
                        remaining.append(c)
            _active_calls.clear()
            _active_calls.extend(remaining)

# ═══════════════════════════════════════════════════════════════
# ─── Worker: Create Account + Call ────────────────────────────
# ═══════════════════════════════════════════════════════════════
def create_and_call(duration):
    """
    Worker function:
    1. Pick next phone number from queue
    2. Create a Telicall account (with proxy if available)
    3. Verify account has balance
    4. Upload token to server
    5. Trigger server-side call (async preferred)
    6. Move to next number (don't wait for 64s!)
    """
    tid = threading.current_thread().name
    current_proxy = get_proxy()  # Get proxy at start of each iteration

    while True:
        phone = get_next_phone()
        if not phone:
            break

        update_stat("total")
        call_id = None

        # ── Step 1: Create email ──
        for email_attempt in range(3):
            mail = create_email(current_proxy)
            if mail:
                break
            time.sleep(1)
        else:
            print(f"[{tid}] NO_EMAIL {phone}", flush=True)
            update_stat("failed")
            continue

        email_addr = mail['email']
        email_short = email_addr.split('@')[0][:15]

        # ── Step 2: Init Telicall session ──
        use_fallback_ip = current_proxy is None
        for init_attempt in range(2):
            tok, device, headers = init_session(current_proxy, use_real_ip=use_fallback_ip)
            if tok:
                break
            # If init fails with proxy, try marking it dead and getting new one
            if current_proxy:
                current_proxy = get_proxy_and_mark_dead(current_proxy)
                use_fallback_ip = current_proxy is None
        else:
            print(f"[{tid}] INIT_FAIL {phone} <- {email_short}", flush=True)
            update_stat("failed")
            continue

        # ── Step 3: Send verification ──
        ref = send_verify(email_addr, headers, current_proxy)
        if not ref:
            print(f"[{tid}] VERIFY_SEND_FAIL {phone} <- {email_short}", flush=True)
            # Might be proxy issue
            if current_proxy:
                current_proxy = get_proxy_and_mark_dead(current_proxy)
                use_fallback_ip = current_proxy is None
            update_stat("failed")
            continue

        # ── Step 4: Get OTP ──
        otp = get_otp(mail['api_type'], mail['token'], current_proxy)
        if not otp:
            print(f"[{tid}] OTP_TIMEOUT {phone} <- {email_short}", flush=True)
            update_stat("failed")
            continue

        # ── Step 5: Verify OTP ──
        user = verify_otp_api(ref, otp, headers, current_proxy)
        if not user:
            print(f"[{tid}] VERIFY_FAIL {phone} <- {email_short}", flush=True)
            update_stat("failed")
            continue

        # ── Step 6: Check balance ──
        has_balance = check_token_balance(tok, device, current_proxy)
        if has_balance is False:
            print(f"[{tid}] NO_BALANCE {phone} <- {email_short} (account created but 0 balance)", flush=True)
            update_stat("accounts_no_balance")
            # Save to Dan.json anyway (for record) but DON'T upload to server
            save_account(email_addr, device, tok)
            # Try next proxy if available
            if current_proxy:
                current_proxy = get_proxy_and_mark_dead(current_proxy)
                use_fallback_ip = current_proxy is None
            update_stat("no_balance")
            continue  # Skip this number's call, move to next

        # ── Step 7: Save to Dan.json ──
        total = save_account(email_addr, device, tok)
        update_stat("accounts_created")

        # ── Step 8: Upload token to server ──
        ready = upload_to_server(email_addr, device, tok)

        # ── Step 9: Trigger server-side call ──
        # Try async-call first (non-blocking, preferred)
        call_id, verify_url = trigger_async_call(phone, duration)
        if call_id:
            caller_info = email_short
            add_active_call(call_id, phone, caller_info, tid)
            print(f"[{tid}] RING {phone} <- {email_short} (ready:{ready})", flush=True)
        else:
            # Fallback: try make-call (blocking)
            result = trigger_make_call(phone, duration)
            status = result.get("status", "unknown")
            from_num = result.get("from", result.get("from_number", "?"))
            actual_dur = result.get("duration", result.get("actual_duration", 0))
            error = result.get("error", "")

            if status == "answered_ok":
                print(f"[{tid}] ANSWERED_OK {phone} ({actual_dur}s) <- {from_num}", flush=True)
                update_stat("answered")
            elif "balance" in str(error).lower() or status == "no_balance":
                print(f"[{tid}] NO_BALANCE {phone} <- {from_num}", flush=True)
                update_stat("no_balance")
            elif status in ("no_answer", "failed"):
                print(f"[{tid}] NO_ANSWER {phone} <- {from_num}", flush=True)
                update_stat("no_answer")
            elif status == "busy":
                print(f"[{tid}] BUSY {phone} <- {from_num}", flush=True)
                update_stat("busy")
            else:
                print(f"[{tid}] FAILED {phone} ({error or status})", flush=True)
                update_stat("failed")

# ═══════════════════════════════════════════════════════════════
# ─── Main ─────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def main():
    global _start_time, _phone_queue, PROXY_FILE

    parser = argparse.ArgumentParser(description="Fox Caller v5.0 - Fixed Call Launcher")
    parser.add_argument("file", help="Phone numbers file (.xlsx or .txt)")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION,
                        help=f"Call duration in seconds (default: {DEFAULT_DURATION})")
    parser.add_argument("--threads", type=int, default=DEFAULT_THREADS,
                        help=f"Number of worker threads (default: {DEFAULT_THREADS})")
    parser.add_argument("--proxies", default=PROXY_FILE,
                        help="Proxy file path (default: alive_proxies.txt in same dir)")
    args = parser.parse_args()

    # Override proxy file if specified
    PROXY_FILE = args.proxies

    # Read numbers
    if not os.path.exists(args.file):
        print(f"ERROR: File not found: {args.file}", flush=True)
        sys.exit(1)

    numbers = read_numbers(args.file)
    if not numbers:
        print("ERROR: No valid phone numbers found in file", flush=True)
        sys.exit(1)

    _phone_queue = numbers

    print("=" * 60, flush=True)
    print("  Fox Caller v5.0 - Fixed Call Launcher", flush=True)
    print("=" * 60, flush=True)
    print(f"  Server:      {SERVER_URL}", flush=True)
    print(f"  Numbers:     {len(numbers)} phones from {args.file}", flush=True)
    print(f"  Duration:    {args.duration}s per call", flush=True)
    print(f"  Threads:     {args.threads}", flush=True)
    print(f"  Domains:     {len(DOMAINS)} email domains", flush=True)
    print(f"  Strategy:    1 account = 1 call (balance verified!)", flush=True)

    # Init proxies
    init_proxy_manager()

    print("=" * 60, flush=True)

    # Quick server test
    print("\nTesting server connection...", flush=True)
    try:
        r = requests.get(f"{SERVER_URL}/api/health", timeout=10)
        if r.status_code == 200:
            print(f"  Server OK: {r.json()}", flush=True)
        else:
            print(f"  Server returned {r.status_code}", flush=True)
    except Exception as e:
        print(f"  Server error: {e}", flush=True)
        print("  WARNING: Server may not be available!", flush=True)

    # Check server stats
    stats = get_server_stats()
    if stats:
        print(f"  Ready tokens: {stats.get('ready_tokens', '?')}", flush=True)
        print(f"  Total users:  {stats.get('total_users', '?')}", flush=True)

    print(f"\nStarting {args.threads} workers...", flush=True)
    print(f"Format: [W#] STATUS +PHONE <- EMAIL (ready:N)", flush=True)
    print(f"Status: RING | ANSWERED_OK | NO_BALANCE | FAILED\n", flush=True)

    _start_time = time.time()

    # Start monitor thread
    monitor_thread = threading.Thread(target=monitor_calls, daemon=True)
    monitor_thread.start()

    # Start worker threads
    threads = []
    for i in range(args.threads):
        t = threading.Thread(target=create_and_call, args=(args.duration,),
                             daemon=True, name=f"W{i}")
        t.start()
        threads.append(t)

    # Wait for all workers to finish
    for t in threads:
        t.join()

    # Wait for remaining async calls to complete
    print(f"\nAll numbers processed. Waiting for remaining calls...", flush=True)
    time.sleep(15)

    # Final stats
    elapsed = time.time() - _start_time
    mins = int(elapsed) // 60
    secs = int(elapsed) % 60
    with _stats_lock:
        s = _stats
    print(f"\n{'=' * 60}", flush=True)
    print(f"  FINAL RESULTS [{mins}m{secs}s]", flush=True)
    print(f"{'=' * 60}", flush=True)
    print(f"  Total numbers:    {len(numbers)}", flush=True)
    print(f"  Answered OK:      {s['answered']}", flush=True)
    print(f"  No Answer:        {s['no_answer']}", flush=True)
    print(f"  Busy/Declined:    {s['busy']}", flush=True)
    print(f"  Failed:           {s['failed']}", flush=True)
    print(f"  No Balance:       {s['no_balance']}", flush=True)
    print(f"  Accounts created: {s['accounts_created']} (with balance)", flush=True)
    print(f"  Accounts no-bal:  {s['accounts_no_balance']} (0 balance, skipped)", flush=True)
    print(f"{'=' * 60}", flush=True)

if __name__ == "__main__":
    main()
