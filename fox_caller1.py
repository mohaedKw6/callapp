#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fox Caller v7.0 - Dual Mode Call Launcher
==========================================
وضعين جوه نفس الملف:

  --mode server   = يرفع الحساب للسيرفر والسيرفر بيعمل المكالمة (64s صوت)
  --mode direct   = بيعمل المكالمة من الجهاز نفسه مباشرة عبر Telicall API

Usage:
  # وضع السيرفر (64 ثانية صوت كامل)
  python3 fox_caller1.py numbers.xlsx --mode server

  # وضع مباشر (يرن من الجهاز - بدون سيرفر)
  python3 fox_caller1.py numbers.xlsx --mode direct

  # إنشاء حسابات فقط
  python3 fox_caller1.py numbers.xlsx --mode create

  # خيارات إضافية
  python3 fox_caller1.py numbers.xlsx --mode direct --duration 64 --threads 3
  python3 fox_caller1.py numbers.xlsx --mode server --no-xrealip
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
DEFAULT_THREADS   = 3

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
        print(f"  Proxies:     None", flush=True)

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
# ─── Email Providers (5 sources) ──────────────────────────────
# ═══════════════════════════════════════════════════════════════

def create_mob2_mail(proxy_dict=None):
    try:
        r = requests.post("https://mob2.temp-mail.org/mailbox",
            headers={'Accept': 'application/json', 'User-Agent': '3.49', 'Accept-Encoding': 'gzip'},
            proxies=proxy_dict, timeout=10)
        if r.status_code == 200:
            d = r.json()
            if d.get('mailbox') and d.get('token'):
                return {'email': d['mailbox'], 'token': d['token'], 'api_type': 'mob2'}
        elif r.status_code == 429:
            time.sleep(2)
    except Exception:
        pass
    return None

def create_io_mail(proxy_dict=None):
    domain = random.choice(DOMAINS)
    name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    try:
        r = requests.post("https://api.internal.temp-mail.io/api/v3/email/new",
            json={"domain": domain, "name": name},
            headers={'Accept': 'application/json', 'Application-Name': 'web',
                     'Application-Version': '2.2.29', 'Origin': 'https://temp-mail.io',
                     'User-Agent': 'Mozilla/5.0'},
            proxies=proxy_dict, timeout=10)
        if r.status_code == 200:
            email = r.json().get('email')
            if email:
                return {'email': email, 'token': email, 'api_type': 'io'}
        elif r.status_code == 429:
            time.sleep(2)
    except Exception:
        pass
    return None

WEB2_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Origin': 'https://temp-mail.org', 'Referer': 'https://temp-mail.org/',
    'Content-Type': 'application/json'
}

def create_web2_mail(proxy_dict=None):
    try:
        r = requests.post("https://web2.temp-mail.org/mailbox",
                          headers=WEB2_HEADERS, proxies=proxy_dict, timeout=10)
        if r.status_code in [200, 201]:
            data = r.json()
            email = data.get('mailbox', '')
            token = data.get('token', '')
            if email and token:
                return {'email': email, 'token': token, 'api_type': 'web2'}
        elif r.status_code == 429:
            time.sleep(3)
    except Exception:
        pass
    return None

_mailtm_domains = None
_mailtm_domains_lock = threading.Lock()

def _get_mailtm_domains():
    global _mailtm_domains
    with _mailtm_domains_lock:
        if _mailtm_domains:
            return _mailtm_domains
    try:
        r = requests.get("https://api.mail.tm/domains", timeout=8)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict):
                domains = [d.get('domain', '') for d in data.get('hydra:member', []) if d.get('domain')]
            elif isinstance(data, list):
                domains = [d.get('domain', '') for d in data if isinstance(d, dict) and d.get('domain')]
            else:
                domains = []
            with _mailtm_domains_lock:
                _mailtm_domains = domains
            return domains
    except Exception:
        pass
    return []

def create_mailtm(proxy_dict=None):
    domains = _get_mailtm_domains()
    if not domains:
        return None
    domain = random.choice(domains)
    name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
    email = f"{name}@{domain}"
    password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    try:
        r = requests.post("https://api.mail.tm/accounts",
                          json={"address": email, "password": password},
                          proxies=proxy_dict, timeout=10)
        if r.status_code in [200, 201]:
            r2 = requests.post("https://api.mail.tm/token",
                               json={"address": email, "password": password},
                               proxies=proxy_dict, timeout=10)
            if r2.status_code == 200:
                token = r2.json().get('token', '')
                if token:
                    return {'email': email, 'token': token, 'api_type': 'mailtm'}
    except Exception:
        pass
    return None

def create_guerrilla_mail(proxy_dict=None):
    try:
        r = requests.get("https://api.guerrillamail.com/ajax.php?f=get_email_address",
                         params={"lang": "en"}, proxies=proxy_dict, timeout=10)
        if r.status_code == 200:
            data = r.json()
            email = data.get('email_addr', '')
            sid = data.get('sid_token', '')
            if email and sid:
                return {'email': email, 'token': sid, 'api_type': 'guerrilla'}
    except Exception:
        pass
    return None

def create_email(proxy_dict=None):
    """Try ALL providers sequentially then parallel"""
    providers = [
        ("temp-mail.io", lambda: create_io_mail(proxy_dict)),
        ("mob2", lambda: create_mob2_mail(proxy_dict)),
        ("mail.tm", lambda: create_mailtm(proxy_dict)),
        ("web2", lambda: create_web2_mail(proxy_dict)),
        ("guerrilla", lambda: create_guerrilla_mail(proxy_dict)),
    ]
    # Sequential
    for name, fn in providers:
        result = fn()
        if result:
            return result
        time.sleep(0.3)
    # Parallel fallback
    result_box = [None]
    done = threading.Event()
    def _try(fn):
        r = fn()
        if r and not done.is_set():
            done.set()
            result_box[0] = r
    threads = [threading.Thread(target=_try, args=(fn,)) for _, fn in providers]
    for t in threads:
        t.start()
    done.wait(timeout=12)
    return result_box[0]

# --- Inbox checking ---
def check_mob2_inbox(tkn, proxy_dict=None):
    try:
        r = requests.get("https://mob2.temp-mail.org/messages",
                         headers={'Accept': 'application/json', 'User-Agent': '3.49', 'Authorization': tkn},
                         proxies=proxy_dict, timeout=8)
        if r.status_code == 200:
            return r.json().get('messages', [])
    except Exception:
        pass
    return []

def check_io_inbox(email, proxy_dict=None):
    try:
        r = requests.get(f"https://api.internal.temp-mail.io/api/v3/email/{email}/messages",
                         proxies=proxy_dict, timeout=8)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []

def check_web2_inbox(email_token, proxy_dict=None):
    try:
        headers = WEB2_HEADERS.copy()
        headers['Authorization'] = f'Bearer {email_token}'
        r = requests.get('https://web2.temp-mail.org/messages', headers=headers, proxies=proxy_dict, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else data.get('messages', [])
    except Exception:
        pass
    return []

def check_mailtm_inbox(token, proxy_dict=None):
    try:
        r = requests.get("https://api.mail.tm/messages",
                         headers={"Authorization": f"Bearer {token}"}, proxies=proxy_dict, timeout=8)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict):
                return data.get('hydra:member', [])
            elif isinstance(data, list):
                return data
    except Exception:
        pass
    return []

def check_guerrilla_inbox(sid_token, proxy_dict=None):
    try:
        r = requests.get("https://api.guerrillamail.com/ajax.php?f=get_email_list",
                         params={"sid_token": sid_token, "offset": 0}, proxies=proxy_dict, timeout=8)
        if r.status_code == 200:
            data = r.json()
            return data.get('list', [])
    except Exception:
        pass
    return []

def get_otp(api_type, token_or_email, proxy_dict=None, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if api_type == 'mob2':
                messages = check_mob2_inbox(token_or_email, proxy_dict)
            elif api_type == 'io':
                messages = check_io_inbox(token_or_email, proxy_dict)
            elif api_type == 'web2':
                messages = check_web2_inbox(token_or_email, proxy_dict)
            elif api_type == 'mailtm':
                messages = check_mailtm_inbox(token_or_email, proxy_dict)
            elif api_type == 'guerrilla':
                messages = check_guerrilla_inbox(token_or_email, proxy_dict)
            else:
                messages = []
            for msg in messages:
                content = str(msg.get('text', '') or msg.get('body', '') or
                             msg.get('bodyPreview', '') or msg.get('content', '') or
                             msg.get('excerpt', '') or msg.get('mail_body', '') or msg)
                subject = str(msg.get('subject', '')).lower()
                sender = str(msg.get('from', '')).lower()
                combined = f"{sender} {subject} {content}".lower()
                if 'teli' in combined or 'verification' in subject or 'verify' in subject:
                    m = re.search(r'\b(\d{6})\b', content)
                    if m:
                        return m.group(1)
        except Exception:
            pass
        time.sleep(3)
    return None

# ═══════════════════════════════════════════════════════════════
# ─── Telicall API ─────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def init_session(proxy_dict=None, use_xrealip=True):
    """Init Telicall session. x-real-ip ON by default - Telicall needs Egyptian IP!"""
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
            return r.json().get('result', {}).get('reference')
    except Exception:
        pass
    return None

def verify_otp_api(ref, code, headers, proxy_dict=None):
    try:
        headers["x-request-id"] = str(uuid.uuid4())
        headers["x-req-timestamp"] = str(int(time.time() * 1000))
        r = requests.post(f"{API_URL}/auth/verify-identity",
                          json={'reference': ref, 'code': str(code)},
                          headers=headers, proxies=proxy_dict, timeout=12)
        if r.status_code == 200:
            return r.json().get('result', {}).get('user')
    except Exception:
        pass
    return None

def direct_telicall_call(phone, token, device_id, proxy_dict=None):
    """اتصال مباشر عبر Telicall API من الجهاز نفسه (بدون سيرفر)
    بيعمل /call/outbound/start ← الرقم التاني هييرن!
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
    if not proxy_dict:
        h["x-currency"] = "EGP"
        h["x-real-ip"] = rand_eg_ip()
    try:
        r = requests.post(f"{API_URL}/call/outbound/start",
                          json={'to': phone, 'source': 'numpad'},
                          headers=h, proxies=proxy_dict, timeout=12)
        if r.status_code == 200:
            data = r.json()
            if data.get('result'):
                result = data['result']
                sip = result.get('sip', {})
                from_info = result.get('from', {})
                return {
                    'success': True,
                    'from': from_info.get('msisdn', ''),
                    'to': result.get('to', {}).get('msisdn', phone),
                    'sip_user': sip.get('username', ''),
                    'sip_domain': sip.get('domain', ''),
                    'limit': sip.get('callLimit', 60),
                }
        elif r.status_code == 400:
            err = r.text.lower()
            if 'balance' in err:
                return {'success': False, 'error': 'NO_BALANCE'}
            return {'success': False, 'error': f'400: {r.text[:100]}'}
        else:
            return {'success': False, 'error': f'HTTP {r.status_code}'}
    except Exception as e:
        return {'success': False, 'error': str(e)}

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
    "email_fail": 0, "verify_fail": 0, "total": 0,
}
_start_time = None

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

# ═══════════════════════════════════════════════════════════════
# ─── Active Call Tracking (server mode) ──────────────────────
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
    """Background: check async call statuses for server mode"""
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
                            print(f"[{tid}] ❌ فشل {phone} ({err})", flush=True)
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
# ─── Worker: Create Account + Call (BOTH MODES) ──────────────
# ═══════════════════════════════════════════════════════════════
def create_and_call(duration, mode="direct", use_xrealip=True):
    """
    Worker: creates account + makes call
    
    mode = "server"  → upload token to server, server makes SIP call (64s audio)
    mode = "direct"  → call Telicall API directly from this device
    mode = "create"  → just create accounts, no calls
    """
    tid = threading.current_thread().name
    current_proxy = get_proxy()

    while True:
        phone = get_next_phone()
        if not phone:
            break

        update_stat("total")

        # ═══════ Step 1: Create Email ═══════
        mail = None
        for attempt in range(5):
            mail = create_email(current_proxy)
            if mail:
                break
            if attempt < 4:
                time.sleep(1 + attempt)
        
        if not mail:
            print(f"[{tid}] 📧 لا إيميل {phone}", flush=True)
            update_stat("email_fail")
            continue

        email_addr = mail['email']
        email_short = email_addr.split('@')[0][:12]

        # ═══════ Step 2: Init Session ═══════
        tok, device, headers = init_session(current_proxy, use_xrealip=use_xrealip)
        if not tok:
            print(f"[{tid}] 🔑 فشل الجلسة {phone} <- {email_short}", flush=True)
            if current_proxy:
                current_proxy = get_proxy_and_mark_dead(current_proxy)
            update_stat("verify_fail")
            continue

        # ═══════ Step 3: Send Verification ═══════
        ref = send_verify(email_addr, headers, current_proxy)
        if not ref:
            print(f"[{tid}] 📨 فشل التحقق {phone} <- {email_short}", flush=True)
            if current_proxy:
                current_proxy = get_proxy_and_mark_dead(current_proxy)
            update_stat("verify_fail")
            continue

        # ═══════ Step 4: Get OTP ═══════
        otp = get_otp(mail['api_type'], mail['token'], current_proxy)
        if not otp:
            print(f"[{tid}] 🔢 OTP انتهى {phone} <- {email_short}", flush=True)
            update_stat("verify_fail")
            continue

        # ═══════ Step 5: Verify OTP ═══════
        user = verify_otp_api(ref, otp, headers, current_proxy)
        if not user:
            print(f"[{tid}] ❌ فشل OTP {phone} <- {email_short}", flush=True)
            update_stat("verify_fail")
            continue

        # ═══════ Step 6: Save Account ═══════
        total = save_account(email_addr, device, tok)
        print(f"[{tid}] ✅ حساب جديد {email_short} (إجمالي: {total})", flush=True)

        # ═══════ Step 7: Call based on MODE ═══════

        if mode == "create":
            # إنشاء حسابات فقط
            update_stat("accounts_ok")
            continue

        elif mode == "server":
            # ══════ وضع السيرفر ══════
            # ارفع التوكن للسيرفر
            ready = upload_to_server(email_addr, device, tok)
            
            # جرّب async call أولاً (مش بيستنى)
            call_id, verify_url = trigger_async_call(phone, duration)
            if call_id:
                add_active_call(call_id, phone, email_short, tid)
                print(f"[{tid}] 📞[سيرفر] يرن {phone} <- {email_short} (ready:{ready})", flush=True)
                continue
            
            # fallback: make-call (blocking)
            result = trigger_make_call(phone, duration)
            status = result.get("status", "unknown")
            from_num = result.get("from", result.get("from_number", "?"))
            dur = result.get("duration", result.get("actual_duration", 0))
            error = result.get("error", "")
            
            if status == "answered_ok":
                print(f"[{tid}] ✅[سيرفر] {phone} ({dur}s) <- {from_num}", flush=True)
                update_stat("calls_ok")
            elif "balance" in str(error).lower() or status == "no_balance":
                print(f"[{tid}] ❌[سيرفر] NO_BALANCE {phone}", flush=True)
                update_stat("calls_no_balance")
                update_stat("accounts_no_bal")
            else:
                print(f"[{tid}] ❌[سيرفر] فشل {phone} ({error or status})", flush=True)
                update_stat("calls_failed")
                update_stat("accounts_ok")

        elif mode == "direct":
            # ══════ وضع مباشر (من الجهاز) ══════
            result = direct_telicall_call(phone, tok, device, current_proxy)
            
            if result and result.get('success'):
                from_num = result.get('from', '')
                print(f"[{tid}] 📞[مباشر] تم الاتصال! {phone} <- {from_num}", flush=True)
                update_stat("calls_ok")
                update_stat("accounts_ok")
                # كمان ارفع التوكن للسيرفر عشان يستعمله بعدين
                upload_to_server(email_addr, device, tok)
            elif result and result.get('error') == 'NO_BALANCE':
                print(f"[{tid}] ❌[مباشر] NO_BALANCE {phone} <- {email_short}", flush=True)
                update_stat("calls_no_balance")
                update_stat("accounts_no_bal")
            elif result:
                err = result.get('error', 'unknown')
                print(f"[{tid}] ❌[مباشر] فشل {phone} ({err})", flush=True)
                update_stat("calls_failed")
                update_stat("accounts_ok")
            else:
                print(f"[{tid}] ❌[مباشر] فشل الاتصال {phone}", flush=True)
                update_stat("calls_failed")
                update_stat("accounts_ok")

# ═══════════════════════════════════════════════════════════════
# ─── Main ─────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def main():
    global _start_time, _phone_queue, PROXY_FILE

    parser = argparse.ArgumentParser(
        description="Fox Caller v7.0 - Dual Mode Call Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  server   = يرفع الحساب للسيرفر والسيرفر بيعمل المكالمة (64s صوت كامل)
  direct   = بيعمل المكالمة من الجهاز نفسه مباشرة عبر Telicall API
  create   = إنشاء حسابات فقط بدون مكالمات

Examples:
  python3 fox_caller1.py numbers.xlsx --mode server
  python3 fox_caller1.py numbers.xlsx --mode direct --threads 3
  python3 fox_caller1.py numbers.xlsx --mode create --threads 5
""")
    parser.add_argument("file", help="Phone numbers file (.xlsx or .txt)")
    parser.add_argument("--mode", choices=["server", "direct", "create"],
                        default="direct", help="Call mode (default: direct)")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION)
    parser.add_argument("--threads", type=int, default=DEFAULT_THREADS)
    parser.add_argument("--proxies", default=PROXY_FILE, help="Proxy file path")
    parser.add_argument("--no-xrealip", action="store_true",
                        help="Disable x-real-ip (only if you have Egyptian IP)")
    args = parser.parse_args()

    PROXY_FILE = args.proxies

    if not os.path.exists(args.file):
        print(f"ERROR: File not found: {args.file}", flush=True)
        sys.exit(1)

    numbers = read_numbers(args.file)
    if not numbers:
        print("ERROR: No valid phone numbers found in file", flush=True)
        sys.exit(1)

    _phone_queue = numbers

    mode_names = {
        "server": "سيرفر (السيرفر يعمل المكالمة 64s)",
        "direct": "مباشر (من الجهاز عبر Telicall API)",
        "create": "إنشاء حسابات فقط",
    }

    print("=" * 60, flush=True)
    print("  Fox Caller v7.0 - Dual Mode", flush=True)
    print("=" * 60, flush=True)
    print(f"  Numbers:     {len(numbers)} phones", flush=True)
    print(f"  Duration:    {args.duration}s", flush=True)
    print(f"  Threads:     {args.threads}", flush=True)
    print(f"  Mode:        {mode_names[args.mode]}", flush=True)
    print(f"  x-real-ip:   {'OFF' if args.no_xrealip else 'ON (Egyptian IP)'}", flush=True)

    init_proxy_manager()
    print("=" * 60, flush=True)

    # Test server
    if args.mode in ("server",):
        print("\nTesting server...", flush=True)
        server_ok = is_server_available()
        if server_ok:
            print(f"  Server: ✅ متاح", flush=True)
        else:
            print(f"  Server: ❌ مش متاح!", flush=True)
            print(f"  ⚠️  السيرفر مش متاح - ممكن الاتصالات تفشل", flush=True)

    print(f"\nStarting {args.threads} workers ({args.mode} mode)...\n", flush=True)

    _start_time = time.time()

    # Start monitor thread for server mode
    if args.mode == "server":
        monitor_thread = threading.Thread(target=monitor_calls, daemon=True)
        monitor_thread.start()

    # Start worker threads
    threads = []
    for i in range(args.threads):
        t = threading.Thread(target=create_and_call,
                             args=(args.duration, args.mode, not args.no_xrealip),
                             daemon=True, name=f"W{i}")
        t.start()
        threads.append(t)
        time.sleep(0.5)

    for t in threads:
        t.join()

    if args.mode == "server":
        print(f"\nWaiting for remaining server calls...", flush=True)
        time.sleep(15)

    # Final stats
    elapsed = time.time() - _start_time
    mins = int(elapsed) // 60
    secs = int(elapsed) % 60
    with _stats_lock:
        s = _stats
    print(f"\n{'=' * 60}", flush=True)
    print(f"  النتائج النهائية [{mins}m{secs}s] - {mode_names[args.mode]}", flush=True)
    print(f"{'=' * 60}", flush=True)
    print(f"  الأرقام:          {len(numbers)}", flush=True)
    print(f"  اتصالات ناجحة:    {s['calls_ok']}", flush=True)
    print(f"  NO BALANCE:       {s['calls_no_balance']}", flush=True)
    print(f"  اتصالات فشلت:     {s['calls_failed']}", flush=True)
    print(f"  حسابات جديدة:     {s['accounts_ok']}", flush=True)
    print(f"  حسابات بدون رصيد: {s['accounts_no_bal']}", flush=True)
    print(f"  فشل إيميل:        {s['email_fail']}", flush=True)
    print(f"  فشل تحقق:         {s['verify_fail']}", flush=True)
    print(f"{'=' * 60}", flush=True)

if __name__ == "__main__":
    main()
