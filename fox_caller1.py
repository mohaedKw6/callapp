#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fox Caller v8.2 - Call Launcher + Email Pool
============================================
مزودين إيميل متعددين + Email Pool + مكالمات عبر السيرفر

مهم: Telicall /call/outbound/start بيرجع SIP credentials بس
      الرقم مش هييرن لحد ما SIP client يتصل ويعمل INVITE!
      عشان كده كل المكالمات بتتعمل عبر السيرفر (عنده SIP client)

وضعين:
  --mode server   = إنشاء حساب + رفعه للسيرفر + السيرفر يعمل المكالمة (SIP)
  --mode create   = إنشاء حسابات فقط بدون مكالمات

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
import string
import hashlib
import base64
import threading
import argparse
import sys
import queue
from datetime import datetime
from urllib.parse import unquote
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
EMAIL_POOL_SIZE   = 15    # عدد الإيميلات الجاهزة في البول
SESSION_POOL_SIZE = 10    # عدد الجلسات الجاهزة في البول

# Old DOMAINS (blocklisted by Telicall - kept as last resort fallback)
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
    "ifcoat.co", "matkind.co",
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
# ─── Email Provider 1: Emailnator (@gmail.com) ──────────────
# ═══════════════════════════════════════════════════════════════
_emailnator_stats = {"ok": 0, "fail": 0}
_emailnator_stats_lock = threading.Lock()

def _new_emailnator_session():
    """بيفتح session جديد مع emailnator"""
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    })
    r = s.get("https://www.emailnator.com/", timeout=15)
    if r.status_code != 200:
        return None, None

    xsrf_decoded = unquote(s.cookies.get('XSRF-TOKEN', ''))
    if not xsrf_decoded:
        return None, None

    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json',
        'Origin': 'https://www.emailnator.com',
        'Referer': 'https://www.emailnator.com/',
        'X-Requested-With': 'XMLHttpRequest',
        'X-XSRF-TOKEN': xsrf_decoded,
    }
    return s, headers

def create_emailnator_mail(email_type=None):
    """
    emailnator.com - بيدي @gmail.com / @googlemail.com
    أنواع: dotGmail (نقاط), plusGmail (+), googleMail (@googlemail.com)
    Telicall بيقبل كلهم ✅
    """
    types = [email_type] if email_type else ["dotGmail", "plusGmail", "googleMail"]
    random.shuffle(types)  # عشان نوزع الحمل

    s, headers = _new_emailnator_session()
    if not s:
        return None

    for etype in types:
        try:
            r = s.post("https://www.emailnator.com/generate-email", headers=headers,
                       json={"email": [etype]}, timeout=15)
            if r.status_code == 200:
                data = r.json()
                email_list = data.get('email', [])
                if email_list:
                    with _emailnator_stats_lock:
                        _emailnator_stats["ok"] += 1
                    return {
                        'email': email_list[0],
                        'api_type': 'emailnator',
                        'session': s,
                        'xsrf_headers': headers,
                        'provider': f'emailnator-{etype}',
                    }
        except Exception:
            continue
        time.sleep(0.3)

    with _emailnator_stats_lock:
        _emailnator_stats["fail"] += 1
    return None

def check_emailnator_inbox(mail_info, timeout=90):
    """بيبص في inbox الـ emailnator عشان يلاقي الـ OTP"""
    s = mail_info['session']
    headers = mail_info['xsrf_headers']
    email_addr = mail_info['email']

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = s.post("https://www.emailnator.com/message-list", headers=headers,
                       json={"email": email_addr}, timeout=15)
            if r.status_code == 200:
                data = r.json()
                msg_data = data.get('messageData', [])
                for msg in msg_data:
                    content = str(msg)
                    if 'teli' in content.lower() or 'verif' in content.lower():
                        m = re.search(r'\b(\d{6})\b', content)
                        if m:
                            return m.group(1)
                        if isinstance(msg, dict):
                            msg_id = msg.get('messageID', '')
                            if msg_id:
                                r2 = s.post("https://www.emailnator.com/message-detail", headers=headers,
                                           json={"email": email_addr, "messageID": msg_id}, timeout=15)
                                if r2.status_code == 200:
                                    m2 = re.search(r'\b(\d{6})\b', r2.text)
                                    if m2:
                                        return m2.group(1)
        except Exception:
            pass
        time.sleep(3)
    return None

# ═══════════════════════════════════════════════════════════════
# ─── Email Provider 2: temp-mail.io (fallback - محظور غالباً) ─
# ═══════════════════════════════════════════════════════════════
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
                return {'email': email, 'token': email, 'api_type': 'io', 'provider': 'temp-mail.io'}
    except Exception:
        pass
    return None

def create_mob2_mail(proxy_dict=None):
    try:
        r = requests.post("https://mob2.temp-mail.org/mailbox",
            headers={'Accept': 'application/json', 'User-Agent': '3.49', 'Accept-Encoding': 'gzip'},
            proxies=proxy_dict, timeout=10)
        if r.status_code == 200:
            d = r.json()
            if d.get('mailbox') and d.get('token'):
                return {'email': d['mailbox'], 'token': d['token'], 'api_type': 'mob2', 'provider': 'mob2'}
    except Exception:
        pass
    return None

def check_io_inbox(email, proxy_dict=None):
    try:
        r = requests.get(f"https://api.internal.temp-mail.io/api/v3/email/{email}/messages",
                         proxies=proxy_dict, timeout=8)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []

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

def get_otp_fallback(api_type, token_or_email, proxy_dict=None, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if api_type == 'mob2':
                messages = check_mob2_inbox(token_or_email, proxy_dict)
            elif api_type == 'io':
                messages = check_io_inbox(token_or_email, proxy_dict)
            else:
                messages = []
            for msg in messages:
                content = str(msg.get('text', '') or msg.get('body', '') or
                             msg.get('bodyPreview', '') or msg.get('content', '') or
                             msg.get('excerpt', '') or msg.get('mail_body', '') or msg)
                subject = str(msg.get('subject', '')).lower()
                combined = f"{subject} {content}".lower()
                if 'teli' in combined or 'verification' in subject or 'verify' in subject:
                    m = re.search(r'\b(\d{6})\b', content)
                    if m:
                        return m.group(1)
        except Exception:
            pass
        time.sleep(3)
    return None

# ═══════════════════════════════════════════════════════════════
# ─── Email Pool (بيجهز إيميلات مسبقاً) ─────────────────────
# ═══════════════════════════════════════════════════════════════
_email_pool = queue.Queue(maxsize=EMAIL_POOL_SIZE)
_session_pool = queue.Queue(maxsize=SESSION_POOL_SIZE)
_stop_flag = threading.Event()
_pool_stats = {"emails_created": 0, "sessions_created": 0}
_pool_stats_lock = threading.Lock()

def _email_pool_filler():
    """خلفية: بيملا بول الإيميلات باستخدام مزودين مختلفين"""
    while not _stop_flag.is_set():
        if _email_pool.qsize() < EMAIL_POOL_SIZE:
            # جرّب مزودين مختلفين بالتوازي
            results = [None]
            done = threading.Event()

            def _try_emailnator():
                mail = create_emailnator_mail()
                if mail and not done.is_set():
                    done.set()
                    results[0] = mail

            def _try_io():
                mail = create_io_mail()
                if mail and not done.is_set():
                    done.set()
                    results[0] = mail

            def _try_mob2():
                mail = create_mob2_mail()
                if mail and not done.is_set():
                    done.set()
                    results[0] = mail

            threads = [
                threading.Thread(target=_try_emailnator),
                threading.Thread(target=_try_io),
                threading.Thread(target=_try_mob2),
            ]
            for t in threads:
                t.start()
            done.wait(timeout=15)
            for t in threads:
                t.join(timeout=1)

            mail = results[0]
            if mail:
                try:
                    _email_pool.put_nowait(mail)
                    with _pool_stats_lock:
                        _pool_stats["emails_created"] += 1
                except queue.Full:
                    pass
        else:
            time.sleep(0.5)

def _session_pool_filler():
    """خلفية: بيملا بول الجلسات"""
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
            time.sleep(0.5)

def get_email_from_pool():
    """بيجيب إيميل من البول (جاهز) أو بيعمل واحد لو فاضي"""
    try:
        return _email_pool.get(timeout=8)
    except queue.Empty:
        # البول فاضي - اعمل إيميل مباشرة
        mail = create_emailnator_mail()
        if mail:
            return mail
        mail = create_io_mail()
        if mail:
            return mail
        mail = create_mob2_mail()
        if mail:
            return mail
        return None

def get_session_from_pool():
    """بيجيب جلسة من البول (جاهزة) أو بيعمل واحدة لو فاضي"""
    try:
        return _session_pool.get(timeout=8)
    except queue.Empty:
        proxy = get_proxy()
        tok, device, headers = init_session(proxy)
        return (tok, device, headers, proxy) if tok else (None, None, None, proxy)

def start_pools(num_email_fillers=3, num_session_fillers=2):
    """بيشغل خلفيات البول"""
    for _ in range(num_email_fillers):
        t = threading.Thread(target=_email_pool_filler, daemon=True)
        t.start()
    for _ in range(num_session_fillers):
        t = threading.Thread(target=_session_pool_filler, daemon=True)
        t.start()
    print("  Pool:       جاري التعبئة...", flush=True)
    time.sleep(3)
    print(f"  Pool:       إيميلات={_email_pool.qsize()} | جلسات={_session_pool.qsize()}", flush=True)

# ═══════════════════════════════════════════════════════════════
# ─── Unified OTP getter ──────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def get_otp_from_mail(mail_info, proxy_dict=None, timeout=90):
    api_type = mail_info.get('api_type', '')
    if api_type == 'emailnator':
        return check_emailnator_inbox(mail_info, timeout=timeout)
    elif api_type in ('io', 'mob2'):
        return get_otp_fallback(api_type, mail_info.get('token', ''), proxy_dict, timeout=timeout)
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
                err = r.json().get('meta', {}).get('errorMessage', r.text[:80])
                return None, err
            except:
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
            return r.json().get('result', {}).get('user')
    except Exception:
        pass
    return None

def direct_telicall_call(phone, token, device_id, proxy_dict=None, use_xrealip=True):
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
    if use_xrealip and not proxy_dict:
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
    tid = threading.current_thread().name

    while True:
        phone = get_next_phone()
        if not phone:
            break

        update_stat("total")

        # ═══════ Step 1: Get Email (from pool or create) ═══════
        mail = get_email_from_pool()
        if not mail:
            print(f"[{tid}] ❌ لا إيميل {phone}", flush=True)
            update_stat("email_fail")
            continue

        email_addr = mail['email']
        email_short = email_addr.split('@')[0][:12]
        email_domain = email_addr.split('@')[1] if '@' in email_addr else '?'
        provider = mail.get('provider', mail.get('api_type', '?'))
        is_safe = email_domain in ('gmail.com', 'googlemail.com', 'outlook.com')
        tag = "✅" if is_safe else "⚠️"
        print(f"[{tid}] 📧 {tag} {email_short}...@{email_domain} [{provider}] -> {phone}", flush=True)

        # ═══════ Step 2: Get Session (from pool or create) ═══════
        tok, device, headers, sess_proxy = get_session_from_pool()
        active_proxy = sess_proxy or get_proxy()

        if not tok:
            print(f"[{tid}] ❌ فشل الجلسة {phone}", flush=True)
            update_stat("verify_fail")
            continue

        # ═══════ Step 3: Send Verification ═══════
        ref, err = send_verify(email_addr, headers, active_proxy)
        if not ref:
            err_str = str(err or "")
            if 'blocklist' in err_str.lower():
                print(f"[{tid}] ❌ دومين محظور {email_domain} {phone}", flush=True)
            else:
                print(f"[{tid}] ❌ فشل التحقق {phone} ({err_str[:50]})", flush=True)
            if active_proxy:
                active_proxy = get_proxy_and_mark_dead(active_proxy)
            update_stat("verify_fail")
            continue

        # ═══════ Step 4: Get OTP ═══════
        otp = get_otp_from_mail(mail, active_proxy, timeout=90)
        if not otp:
            print(f"[{tid}] ❌ OTP انتهى {phone} <- {email_short}", flush=True)
            update_stat("verify_fail")
            continue
        print(f"[{tid}] 🔢 OTP:{otp} {email_short}", flush=True)

        # ═══════ Step 5: Verify ═══════
        user = verify_otp_api(ref, otp, headers, active_proxy)
        if not user:
            print(f"[{tid}] ❌ فشل التأكيد {phone}", flush=True)
            update_stat("verify_fail")
            continue

        # ═══════ Step 6: Save ═══════
        total = save_account(email_addr, device, tok)
        print(f"[{tid}] ✅ حساب! {email_short} (#{total})", flush=True)

        # ═══════ Step 7: Upload + Call via Server ═══════
        if mode == "create":
            update_stat("accounts_ok")
            continue

        # Upload account to server
        print(f"[{tid}] 📤 رفع الحساب للسيرفر...", flush=True)
        ready = upload_to_server(email_addr, device, tok)
        print(f"[{tid}] 📤 تم الرفع (ready:{ready})", flush=True)

        # Server makes the actual SIP call
        print(f"[{tid}] 📞 جاري تشغيل المكالمة عبر السيرفر (SIP)...", flush=True)
        call_id, verify_url = trigger_async_call(phone, duration)
        if call_id:
            add_active_call(call_id, phone, email_short, tid)
            print(f"[{tid}] 📞 المكالمة اتعملت! {phone} (id:{call_id[:10]}...)", flush=True)
            continue

        # Fallback: make-call (blocking, waits for result)
        print(f"[{tid}] 📞 تجربة make-call...", flush=True)
        result = trigger_make_call(phone, duration)
        status = result.get("status", "unknown")
        from_num = result.get("from", result.get("from_number", "?"))
        dur = result.get("duration", result.get("actual_duration", 0))
        error = result.get("error", "")

        if status == "answered_ok":
            print(f"[{tid}] ✅ تم الاتصال {phone} ({dur}s) <- {from_num}", flush=True)
            update_stat("calls_ok")
        elif "balance" in str(error).lower() or status == "no_balance":
            print(f"[{tid}] ❌ NO_BALANCE {phone}", flush=True)
            update_stat("calls_no_balance")
            update_stat("accounts_no_bal")
        else:
            print(f"[{tid}] ❌ فشل {phone} ({error or status})", flush=True)
            update_stat("calls_failed")
            update_stat("accounts_ok")

        time.sleep(0.5)

# ═══════════════════════════════════════════════════════════════
# ─── Stats Printer ────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def print_stats():
    while True:
        time.sleep(30)
        with _stats_lock:
            s = dict(_stats)
        with _emailnator_stats_lock:
            es = dict(_emailnator_stats)
        with _pool_stats_lock:
            ps = dict(_pool_stats)
        elapsed = time.time() - _start_time if _start_time else 1
        rate = s['total'] / elapsed * 60 if elapsed > 0 else 0
        pool_e = _email_pool.qsize()
        pool_s = _session_pool.qsize()
        print(f"\n{'='*55}", flush=True)
        print(f"  ⏱ {int(elapsed//60)}د {int(elapsed%60)}ث | معدل: {rate:.1f}/د", flush=True)
        print(f"  ✅ مكالمات: {s['calls_ok']} | ❌ فشل: {s['calls_failed']} | 💰 NO_BAL: {s['calls_no_balance']}", flush=True)
        print(f"  📧 إيميلات: فشل={s['email_fail']} | تحقق فشل={s['verify_fail']}", flush=True)
        print(f"  🔋 Pool: إيميلات={pool_e} | جلسات={pool_s}", flush=True)
        print(f"  📊 emailnator: ✅{es['ok']} ❌{es['fail']} | بول إجمالي: {ps['emails_created']}إ {ps['sessions_created']}ج", flush=True)
        print(f"{'='*55}\n", flush=True)

# ═══════════════════════════════════════════════════════════════
# ─── Main ─────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def main():
    global _start_time, _phone_queue, PROXY_FILE

    parser = argparse.ArgumentParser(
        description="Fox Caller v8.1 - Dual Mode + Email Pool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  server   = يرفح الحساب للسيرفر والسيرفر بيعمل المكالمة
  direct   = بيعمل المكالمة من الجهاز نفسه مباشرة
  create   = إنشاء حسابات فقط بدون مكالمات

Examples:
  python3 fox_caller1.py numbers.xlsx --mode direct
  python3 fox_caller1.py numbers.xlsx --mode server --threads 5
  python3 fox_caller1.py numbers.xlsx --mode create --threads 10
""")
    parser.add_argument("file", help="Phone numbers file (.xlsx or .txt)")
    parser.add_argument("--mode", choices=["server", "create"],
                        default="server", help="Call mode (default: server)")
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
        "server": "سيرفر (SIP + صوت 64ث)",
        "create": "إنشاء حسابات فقط",
    }

    print("=" * 60, flush=True)
    print("  Fox Caller v8.2 - Email Pool + SIP Calls", flush=True)
    print("  كل المكالمات عبر السيرفر (SIP client)", flush=True)
    print("=" * 60, flush=True)
    print(f"  Numbers:     {len(numbers)} phones", flush=True)
    print(f"  Duration:    {args.duration}s", flush=True)
    print(f"  Threads:     {args.threads}", flush=True)
    print(f"  Mode:        {mode_names[args.mode]}", flush=True)
    print(f"  x-real-ip:   {'OFF' if args.no_xrealip else 'ON (Egyptian IP)'}", flush=True)
    print(f"  Email Pool:  {EMAIL_POOL_SIZE} | Session Pool: {SESSION_POOL_SIZE}", flush=True)

    init_proxy_manager()
    print("=" * 60, flush=True)

    # Test server
    print("\nTesting server...", flush=True)
    if is_server_available():
        print("  Server: ✅ متاح", flush=True)
    else:
        print("  Server: ❌ غير متاح!", flush=True)
        sys.exit(1)

    # Quick test emailnator
    print("\nQuick test: emailnator...", flush=True)
    test_mail = create_emailnator_mail()
    if test_mail:
        print(f"  ✅ شغال: {test_mail['email']} [{test_mail.get('provider','?')}]", flush=True)
    else:
        print(f"  ⚠️ مش شغال - هيستخدم fallback", flush=True)

    # Start pools BEFORE workers
    print("\nStarting Email Pool + Session Pool...", flush=True)
    start_pools(num_email_fillers=3, num_session_fillers=2)

    _start_time = time.time()

    # Start workers
    print(f"\nStarting {args.threads} workers ({args.mode} mode)...\n", flush=True)
    workers = []
    for i in range(args.threads):
        t = threading.Thread(
            target=create_and_call,
            args=(args.duration, args.mode, not args.no_xrealip),
            name=f"W{i}",
            daemon=True
        )
        t.start()
        workers.append(t)

    if args.mode == "server":
        t = threading.Thread(target=monitor_calls, daemon=True)
        t.start()

    t_stats = threading.Thread(target=print_stats, daemon=True)
    t_stats.start()

    try:
        while True:
            alive = [t for t in workers if t.is_alive()]
            if not alive:
                break
            time.sleep(1)
    except KeyboardInterrupt:
        _stop_flag.set()
        print("\n\n⏹️ تم الإيقاف!", flush=True)

    # Final stats
    elapsed = time.time() - _start_time if _start_time else 0
    with _stats_lock:
        s = dict(_stats)

    print("\n" + "=" * 60, flush=True)
    print("  النتيجة النهائية", flush=True)
    print("=" * 60, flush=True)
    print(f"  الوقت: {int(elapsed//60)}د {int(elapsed%60)}ث", flush=True)
    print(f"  ✅ مكالمات ناجحة: {s['calls_ok']}", flush=True)
    print(f"  ❌ مكالمات فشلت: {s['calls_failed']}", flush=True)
    print(f"  💰 NO_BALANCE: {s['calls_no_balance']}", flush=True)
    print(f"  ✅ حسابات جديدة: {s['accounts_ok']}", flush=True)
    print(f"  📧 فشل إيميل: {s['email_fail']}", flush=True)
    print(f"  📨 فشل تحقق: {s['verify_fail']}", flush=True)
    print("=" * 60, flush=True)

if __name__ == "__main__":
    main()
