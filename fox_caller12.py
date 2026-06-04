#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fox Caller v12.1 - tempmail.lol Edition
========================================
Email provider: tempmail.lol API ONLY
  - No Gmail, No IMAP, No App Password needed!
  - Creates temp emails via API, reads OTP via API
  - Supports custom domains (Telicall may block default domains)
  - Each inbox is completely separate - no race conditions!

  tempmail.lol API:
  ─────────────────
  POST /v2/inbox/create  → creates inbox (returns address + token)
  GET  /v2/inbox?token=X  → fetches emails for that inbox

  IMPORTANT: Default tempmail.lol domains may be BLOCKED by Telicall!
  ──────────────────────────────────────────────────────────────────
  If blocked, you MUST use a custom domain:
  1. Buy/own a domain that Telicall accepts
  2. Set it up on tempmail.lol dashboard: https://tempmail.lol/ar/account
  3. Run: python3 fox_caller12.py numbers.xlsx --domain yourdomain.com

  Telicall Accepted Domains (known):
  ──────────────────────────────────
  gmail.com, protonmail.com, yahoo.com, outlook.com
  + any custom domain not on their blocklist

  xlsx Reading:
  ──────────────
  - Reads phone numbers from any column in xlsx
  - Handles Egyptian numbers: 0101234567 → +200101234567
  - Handles: +20..., 0020..., 20..., 01... formats
  - Shows found numbers before starting

Mode:
  --mode server   = create account + upload to server + server makes SIP call
  --mode create   = create accounts only (no calls)

Usage:
  python3 fox_caller12.py numbers.xlsx
  python3 fox_caller12.py numbers.xlsx --mode server --threads 5
  python3 fox_caller12.py numbers.xlsx --domain mydomain.com
  python3 fox_caller12.py numbers.xlsx --api-key YOUR_KEY
  python3 fox_caller12.py file.xlsx --country eg   (auto-add +20)
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
from filelock import FileLock


# ═══════════════════════════════════════════════════════════════
# ─── Config ───────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
API_URL       = "https://api.telicall.com"
SERVER_URL    = "https://callapp-production-c84c.up.railway.app"
ADMIN_KEY     = "06d271200e53fb4482acd8679bfe358a"
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DAN_FILE      = os.path.join(BASE_DIR, "Dan.json")
PASSWORD      = "@@@GMAQ@@@"
DEFAULT_DURATION = 64
DEFAULT_THREADS   = 3
SESSION_POOL_SIZE = 5
MAX_RETRIES       = 8
OTP_TIMEOUT       = 90
OTP_POLL_INTERVAL = 3

# tempmail.lol
TEMPMAIL_API_BASE = "https://api.tempmail.lol"
TEMPMAIL_API_KEY  = "tempmail.20260604.vmu8bbm2vo5rurre32cnojhp84h7um7kuswa5uqwzq1pewhv"
TEMPMAIL_DOMAIN   = ""  # Custom domain (set via --domain or auto)


# ═══════════════════════════════════════════════════════════════
# ─── tempmail.lol API ─────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
_tempmail_lock = threading.Lock()

def tempmail_create_inbox(prefix=None, domain=None, debug=False):
    """
    Create a temp email inbox via tempmail.lol API.
    Returns (email_address, inbox_token) or (None, None) on failure.
    
    API: POST /v2/inbox/create
    Body: {"domain": "...", "prefix": "..."}  (both optional)
    Response 201: {"address": "...", "token": "..."}
    """
    body = {}
    if domain:
        body["domain"] = domain
    if prefix:
        body["prefix"] = prefix
    
    attempts = [
        ("POST+auth", "POST", {"Content-Type": "application/json", "Authorization": f"Bearer {TEMPMAIL_API_KEY}"} if TEMPMAIL_API_KEY else {"Content-Type": "application/json"}),
        ("GET", "GET", {}),
        ("POST+noauth", "POST", {"Content-Type": "application/json"}),
    ]
    
    for name, method, hdrs in attempts:
        try:
            if method == "POST":
                r = requests.post(f"{TEMPMAIL_API_BASE}/v2/inbox/create",
                                  headers=hdrs, json=body, timeout=20)
            else:
                r = requests.get(f"{TEMPMAIL_API_BASE}/v2/inbox/create",
                                 headers=hdrs, timeout=20)
            
            if debug:
                print(f"    [DEBUG] {name}: HTTP {r.status_code} | Body: {r.text[:200]}", flush=True)
            
            if r.status_code == 201:
                data = r.json()
                addr = data.get("address")
                tok = data.get("token")
                if addr and tok:
                    if debug:
                        print(f"    [DEBUG] {name}: SUCCESS! {addr}", flush=True)
                    return addr, tok
                else:
                    if debug:
                        print(f"    [DEBUG] {name}: 201 but missing fields: {list(data.keys())}", flush=True)
            else:
                if debug:
                    print(f"    [DEBUG] {name}: Expected 201, got {r.status_code}", flush=True)
        except requests.exceptions.ConnectionError as e:
            if debug:
                print(f"    [DEBUG] {name}: ConnectionError: {e}", flush=True)
        except requests.exceptions.Timeout as e:
            if debug:
                print(f"    [DEBUG] {name}: Timeout: {e}", flush=True)
        except Exception as e:
            if debug:
                print(f"    [DEBUG] {name}: {type(e).__name__}: {e}", flush=True)
    
    return None, None


def tempmail_get_emails(inbox_token):
    """
    Fetch emails for an inbox via tempmail.lol API.
    Returns list of email dicts or empty list.
    
    API: GET /v2/inbox?token=X
    Response 200: {"emails": [...], "expired": bool}
    
    Email object: {from, to, subject, body, html, date}
    """
    try:
        r = requests.get(f"{TEMPMAIL_API_BASE}/v2/inbox",
                         params={"token": inbox_token}, timeout=20)
        if r.status_code == 200:
            data = r.json()
            return data.get("emails", [])
        return []
    except Exception:
        return []


def tempmail_read_otp(inbox_token, timeout=OTP_TIMEOUT, sent_time=None):
    """
    Poll tempmail.lol inbox for OTP from Telicall.
    Returns 6-digit OTP string or None on timeout.
    
    Each inbox is COMPLETELY SEPARATE - no race conditions!
    No IMAP, no Delivered-To matching needed.
    Just poll until we find a 6-digit code.
    """
    if sent_time is None:
        sent_time = time.time()
    
    deadline = time.time() + timeout
    
    while time.time() < deadline:
        if _stop_flag.is_set():
            return None
        
        emails = tempmail_get_emails(inbox_token)
        
        for email_data in emails:
            # Check if email arrived after we sent the OTP
            email_ts = email_data.get("date", 0)
            # tempmail.lol date is Unix timestamp in milliseconds
            if isinstance(email_ts, (int, float)):
                email_ts_sec = email_ts / 1000 if email_ts > 1e12 else email_ts
                # Only consider emails that arrived after we sent the request
                if email_ts_sec < (sent_time - 30):
                    continue
            
            # Extract OTP from body and/or html
            body_text = email_data.get("body", "") or ""
            html_text = email_data.get("html", "") or ""
            combined = body_text + " " + html_text
            
            otp = _extract_otp(combined)
            if otp:
                return otp
        
        time.sleep(OTP_POLL_INTERVAL)
    
    return None


def _extract_otp(text):
    """Extract 6-digit OTP from text."""
    clean = re.sub(r'<[^>]+>', ' ', text)
    m = re.search(r'\b(\d{6})\b', clean)
    return m.group(1) if m else None


def test_tempmail_connection():
    """Test tempmail.lol API at startup. Returns (success, domain_used, read_ok)."""
    # Try multiple times with debug on first attempt
    for attempt in range(3):
        try:
            debug_mode = (attempt == 0)  # Show debug on first attempt
            addr, token = tempmail_create_inbox(domain=TEMPMAIL_DOMAIN or None, debug=debug_mode)
            if addr and token:
                domain = addr.split('@')[1] if '@' in addr else '?'
                # Also test reading emails
                emails = tempmail_get_emails(token)
                read_ok = isinstance(emails, list)
                return True, domain, read_ok
            else:
                print(f"    Attempt {attempt+1}/3: inbox creation returned None", flush=True)
        except Exception as e:
            print(f"    Attempt {attempt+1}/3: {type(e).__name__}: {e}" , flush=True)
        if attempt < 2:
            time.sleep(2)
    
    # Last resort: try raw connection test
    try:
        r = requests.get(TEMPMAIL_API_BASE, timeout=10)
        print(f"    Raw connection to {TEMPMAIL_API_BASE}: HTTP {r.status_code}", flush=True)
    except Exception as e:
        print(f"    Cannot reach {TEMPMAIL_API_BASE}: {type(e).__name__}: {e}" , flush=True)
    
    return False, None, False


def discover_domains(count=10):
    """Create multiple inboxes to discover available domains."""
    domains = {}
    for i in range(count):
        addr, _ = tempmail_create_inbox(domain=TEMPMAIL_DOMAIN or None)
        if addr and '@' in addr:
            domain = addr.split('@')[1]
            domains[domain] = domains.get(domain, 0) + 1
    return domains


def test_domain_on_telicall(domain):
    """Test if a specific domain is accepted by Telicall."""
    test_email = f"foxtest{random.randint(1000,9999)}@{domain}"
    try:
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
        r = requests.post(f"{API_URL}/init", json={
            "countryCode": "eg", "deviceName": "Infinix X698",
            "notificationToken": "", "oldToken": "",
            "peerKey": str(random.randint(100, 999)),
            "timeZone": "Africa/Cairo", "localizationKey": ""
        }, headers=h, timeout=12)
        if r.status_code == 200:
            tok = r.json().get('result', {}).get('token')
            if tok:
                h["x-token"] = tok
                h["x-request-id"] = str(uuid.uuid4())
                h["x-req-timestamp"] = str(int(time.time() * 1000))
                r2 = requests.post(f"{API_URL}/auth/send-email",
                                   json={'email': test_email}, headers=h, timeout=12)
                if r2.status_code == 200:
                    return "ACCEPTED"
                else:
                    try:
                        err = r2.json().get('meta', {}).get('errorMessage', r2.text[:80])
                        err_lower = str(err).lower()
                        if 'blocklist' in err_lower or 'blocked' in err_lower:
                            return "BLOCKED"
                        elif 'already' in err_lower:
                            return "ACCEPTED"  # domain is ok, just email taken
                        return f"REJECTED ({err[:40]})"
                    except:
                        return "REJECTED"
        return "SESSION_FAIL"
    except Exception as e:
        return f"ERROR ({str(e)[:30]})"


# ═══════════════════════════════════════════════════════════════
# ─── Proxy Manager ────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
PROXY_FILE      = os.path.join(BASE_DIR, "alive_proxies.txt")
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
    (102, 156), (102, 157), (102, 158), (102, 159),
    (102, 160), (102, 161), (102, 162), (102, 163),
    (102, 164), (102, 165),
    (154, 128), (154, 129), (154, 130), (154, 131),
    (154, 132), (154, 133), (154, 134), (154, 135),
    (154, 136), (154, 137), (154, 138), (154, 139),
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
# ─── Session Pool ────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
_session_pool = queue.Queue(maxsize=SESSION_POOL_SIZE)
_stop_flag = threading.Event()
_pool_stats = {"sessions_created": 0}
_pool_stats_lock = threading.Lock()

def _session_pool_filler():
    """Background: fills session pool."""
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

def get_session_from_pool():
    """Get a session from pool or create one."""
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

def start_pools(num_session_fillers=1):
    """Start background pool fillers."""
    for _ in range(num_session_fillers):
        t = threading.Thread(target=_session_pool_filler, daemon=True)
        t.start()
    time.sleep(2)
    print(f"  Pool:       sessions={_session_pool.qsize()}", flush=True)


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
    """Send verification email. Returns (reference, error)."""
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
                    return None, 'BLOCKED'
                return None, err
            except Exception:
                return None, f"HTTP {r.status_code}"
    except Exception as e:
        return None, str(e)

def verify_otp_api(ref, code, headers, proxy_dict=None):
    """Verify OTP. Returns (user, error_type)."""
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
def _normalize_phone(num, country='eg'):
    """
    Normalize a phone number to international format.
    Handles Egyptian numbers in all common formats:
      0101234567   → +200101234567
      100101234567  → +200101234567
      20101234567   → +20101234567
      0020101234567 → +20101234567
      +20101234567  → +20101234567
      +200101234567 → +200101234567
    """
    # Remove formatting characters
    num = num.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    num = num.replace('\u202a', '').replace('\u202c', '')  # LTR/RTL marks
    
    # Remove any non-digit except leading +
    if not num.startswith('+'):
        num = '+' + num if num.isdigit() else num
    
    # Strip to digits only for analysis
    digits = num.lstrip('+')
    
    if not digits.isdigit() or len(digits) < 8:
        return None
    
    # Egyptian number normalization
    if country == 'eg':
        # 01012345678 (local format with leading 0) → +201012345678
        if digits.startswith('0') and len(digits) == 11:
            return '+20' + digits[1:]  # Drop leading 0, add +20
        # 0101234567 (10-digit local with leading 0) → +20101234567
        elif digits.startswith('01') and len(digits) == 10:
            return '+20' + digits[1:]  # Drop leading 0
        # 1012345678 (without leading 0, local mobile prefix) → +201012345678
        elif digits.startswith('1') and len(digits) == 10:
            return '+20' + digits
        # 201012345678 (with country code 20 already) → +201012345678
        elif digits.startswith('20') and len(digits) >= 11:
            return '+' + digits
        # 0020101234567 (00 international prefix) → +20101234567
        elif digits.startswith('00'):
            return '+' + digits[2:]
    
    # Generic handling for other countries
    if digits.startswith('00'):
        return '+' + digits[2:]
    
    if len(digits) >= 10:
        return '+' + digits
    
    return None


def read_numbers(filepath, country='eg'):
    """Read phone numbers from xlsx or txt file, normalize to international format."""
    numbers = []
    raw_count = 0
    
    if filepath.endswith(('.xlsx', '.xls')):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(filepath, read_only=True)
            ws = wb.active
            for row in ws.iter_rows(values_only=True):
                for cell in row:
                    if cell is not None:
                        raw = str(cell).strip()
                        if not raw:
                            continue
                        raw_count += 1
                        normalized = _normalize_phone(raw, country)
                        if normalized:
                            numbers.append(normalized)
            wb.close()
        except ImportError:
            print("ERROR: openpyxl not installed. Run: pip3 install openpyxl", flush=True)
            sys.exit(1)
        except Exception as e:
            print(f"ERROR reading xlsx: {e}", flush=True)
            sys.exit(1)
    else:
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    raw = line.strip()
                    if not raw:
                        continue
                    raw_count += 1
                    normalized = _normalize_phone(raw, country)
                    if normalized:
                        numbers.append(normalized)
        except Exception as e:
            print(f"ERROR reading file: {e}", flush=True)
            sys.exit(1)
    
    # Deduplicate
    seen = set()
    unique = []
    for n in numbers:
        if n not in seen:
            seen.add(n)
            unique.append(n)
    
    if unique:
        print(f"\n  Numbers found: {len(unique)} unique (from {raw_count} raw entries)", flush=True)
        # Show first 5 as examples
        for i, n in enumerate(unique[:5]):
            print(f"    [{i+1}] {n}", flush=True)
        if len(unique) > 5:
            print(f"    ... and {len(unique)-5} more", flush=True)
    
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
    "inbox_fail": 0,
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
                        print(f"[{tid}] Call OK {phone} ({dur}s) <- {caller}", flush=True)
                        update_stat("calls_ok")
                    elif s in ("failed", "error"):
                        err = status_data.get("error", "")
                        if "balance" in str(err).lower():
                            print(f"[{tid}] NO_BALANCE {phone}", flush=True)
                            update_stat("calls_no_balance")
                        else:
                            print(f"[{tid}] Call failed {phone} ({err})", flush=True)
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
# ─── Worker: Create Account + Call (with retry) ─────────────
# ═══════════════════════════════════════════════════════════════
_inbox_counter = 0
_inbox_counter_lock = threading.Lock()

def _next_inbox_prefix():
    """Generate a unique prefix for each inbox (thread-safe)."""
    global _inbox_counter
    with _inbox_counter_lock:
        _inbox_counter += 1
        return f"fox{_inbox_counter}"


def _try_one_phone(phone, duration, mode, tid):
    """
    One attempt for a phone number. Returns:
    'ok'            = account created + call triggered
    'no_balance'    = account created but no balance for call
    'domain_blocked'= domain blocked by Telicall
    'email_exists'  = email already registered
    'retry'         = transient error, can retry
    'fail'          = permanent failure
    """
    # Step 1: Create temp email inbox via tempmail.lol
    prefix = _next_inbox_prefix()
    domain = TEMPMAIL_DOMAIN or None
    
    email_addr, inbox_token = tempmail_create_inbox(prefix=prefix, domain=domain, debug=False)
    
    if not email_addr or not inbox_token:
        print(f"[{tid}] Inbox creation failed {phone}", flush=True)
        update_stat("inbox_fail")
        return 'retry'
    
    email_short = email_addr.split('@')[0][:20]
    email_domain = email_addr.split('@')[1] if '@' in email_addr else '?'
    
    print(f"[{tid}] Email: {email_addr} -> {phone}", flush=True)
    
    # Step 2: Get Session
    tok, device, headers, sess_proxy = get_session_from_pool()
    active_proxy = sess_proxy or get_proxy()
    
    if not tok:
        print(f"[{tid}] Session failed {phone}", flush=True)
        update_stat("session_fail")
        return 'retry'
    
    # Step 3: Send Verification (record time BEFORE sending)
    sent_time = time.time()
    ref, err = send_verify(email_addr, headers, active_proxy)
    if not ref:
        err_str = str(err or "")
        if err_str == 'EMAIL_EXISTS':
            print(f"[{tid}] Email exists {email_short} - trying another", flush=True)
            update_stat("email_exists")
            return 'email_exists'
        elif 'BLOCKED' in err_str:
            print(f"[{tid}] Domain BLOCKED: {email_domain}", flush=True)
            update_stat("domain_blocked")
            return 'domain_blocked'
        else:
            print(f"[{tid}] Verify send failed {phone} ({err_str[:50]})", flush=True)
            update_stat("verify_fail")
        if active_proxy:
            active_proxy = get_proxy_and_mark_dead(active_proxy)
        return 'retry'
    
    print(f"[{tid}] OTP sent -> {email_short}", flush=True)
    
    # Step 4: Get OTP via tempmail.lol API
    # Each inbox is completely separate - no race conditions!
    otp = tempmail_read_otp(inbox_token, timeout=OTP_TIMEOUT, sent_time=sent_time)
    if not otp:
        print(f"[{tid}] OTP timeout {phone} <- {email_short}", flush=True)
        update_stat("otp_fail")
        return 'retry'
    
    print(f"[{tid}] OTP:{otp} {email_short}", flush=True)
    
    # Step 5: Verify OTP
    time.sleep(1)
    user, verify_err = verify_otp_api(ref, otp, headers, active_proxy)
    if not user:
        if verify_err == 'email_exists':
            print(f"[{tid}] Email exists (OTP step) {email_short} - trying another", flush=True)
            update_stat("email_exists")
            return 'email_exists'
        elif verify_err == 'expired':
            print(f"[{tid}] OTP expired/wrong {phone}", flush=True)
            update_stat("confirm_fail")
            return 'retry'
        else:
            print(f"[{tid}] Confirm failed {phone} ({verify_err})", flush=True)
            update_stat("confirm_fail")
            return 'retry'
    
    # Step 6: Save Account
    total = save_account(email_addr, device, tok)
    print(f"[{tid}] Account! {email_short} (#{total})", flush=True)
    
    # Step 7: Upload + Call via Server
    if mode == "create":
        update_stat("accounts_ok")
        return 'ok'
    
    # Upload account to server
    ready = upload_to_server(email_addr, device, tok)
    
    # Server makes the actual SIP call
    call_id, verify_url = trigger_async_call(phone, duration)
    if call_id:
        add_active_call(call_id, phone, email_short, tid)
        print(f"[{tid}] Call! {phone} (ready:{ready}, id:{str(call_id)[:10]}...)", flush=True)
        return 'ok'
    
    # Fallback: make-call (blocking)
    result = trigger_make_call(phone, duration)
    status = result.get("status", "unknown")
    from_num = result.get("from", result.get("from_number", "?"))
    dur = result.get("duration", result.get("actual_duration", 0))
    error = result.get("error", "")
    
    if status == "answered_ok":
        print(f"[{tid}] Call OK {phone} ({dur}s) <- {from_num}", flush=True)
        update_stat("calls_ok")
        return 'ok'
    elif "balance" in str(error).lower() or status == "no_balance":
        print(f"[{tid}] NO_BALANCE {phone}", flush=True)
        update_stat("calls_no_balance")
        update_stat("accounts_no_bal")
        return 'no_balance'
    else:
        print(f"[{tid}] Call failed {phone} ({error or status})", flush=True)
        update_stat("calls_failed")
        update_stat("accounts_ok")
        return 'no_balance'

_call_delay = 2.0  # Will be set from args

def create_and_call(duration, mode="server", use_xrealip=True):
    """Main worker - gets phone numbers and tries to make calls with retry."""
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
                print(f"[{tid}] Retry {attempt}/{MAX_RETRIES} for {phone}", flush=True)
                time.sleep(1)
            
            result = _try_one_phone(phone, duration, mode, tid)
            last_result = result
            
            if result == 'ok':
                success = True
                break
            elif result == 'no_balance':
                success = True  # account was created
                break
            elif result in ('domain_blocked', 'email_exists'):
                continue  # try with a different inbox
            elif result == 'retry':
                continue
            else:
                break
        
        if not success:
            add_failed_phone(phone, last_result or 'unknown')
            print(f"[{tid}] Final fail {phone} after {MAX_RETRIES} attempts ({last_result})", flush=True)
        
        # Delay between calls to avoid rate limiting
        time.sleep(_call_delay)


# ═══════════════════════════════════════════════════════════════
# ─── Stats Printer ────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def print_stats():
    while not _stop_flag.is_set():
        _stop_flag.wait(30)
        with _stats_lock:
            s = dict(_stats)
        elapsed = time.time() - _start_time if _start_time else 1
        rate = s['total'] / elapsed * 60 if elapsed > 0 else 0
        print(f"\n  Stats ({elapsed/60:.1f}min | {rate:.1f}/min):", flush=True)
        print(f"     Total: {s['total']} | Accounts: {s['accounts_ok']} | Calls OK: {s['calls_ok']}", flush=True)
        print(f"     Errors: inbox={s['inbox_fail']} session={s['session_fail']} "
              f"verify={s['verify_fail']} OTP={s['otp_fail']} confirm={s['confirm_fail']}", flush=True)
        print(f"     Email exists: {s['email_exists']} | NO_BALANCE: {s['calls_no_balance']} | "
              f"Retries: {s['retries']} | Domain blocked: {s['domain_blocked']}", flush=True)
        print(f"     Failed phones: {len(_failed_phones)}", flush=True)


# ═══════════════════════════════════════════════════════════════
# ─── Main ─────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def main():
    global _start_time, _phone_queue, TEMPMAIL_API_KEY, TEMPMAIL_DOMAIN
    
    parser = argparse.ArgumentParser(description="Fox Caller v12.1 - tempmail.lol Edition")
    parser.add_argument("file", help="Phone numbers file (.xlsx or .txt)")
    parser.add_argument("--mode", choices=["server", "create"], default="server",
                       help="server=create+call | create=accounts only")
    parser.add_argument("--threads", type=int, default=DEFAULT_THREADS,
                       help=f"Worker threads (default: {DEFAULT_THREADS})")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION,
                       help=f"Call duration in seconds (default: {DEFAULT_DURATION})")
    parser.add_argument("--limit", type=int, default=0,
                       help="Max numbers to process (0=all)")
    parser.add_argument("--no-xrealip", action="store_true",
                       help="Disable x-real-ip header")
    parser.add_argument("--api-key", type=str, default=TEMPMAIL_API_KEY,
                       help="tempmail.lol API key")
    parser.add_argument("--domain", type=str, default="",
                       help="Custom domain for tempmail.lol (e.g. mydomain.com)")
    parser.add_argument("--country", type=str, default="eg",
                       help="Country code for number normalization (default: eg)")
    parser.add_argument("--delay", type=float, default=2.0,
                       help="Delay between calls in seconds (default: 2.0)")
    
    args = parser.parse_args()
    
    # Apply overrides
    if args.api_key:
        TEMPMAIL_API_KEY = args.api_key
    if args.domain:
        TEMPMAIL_DOMAIN = args.domain
    
    print("\n" + "=" * 60, flush=True)
    print("  Fox Caller v12.1 - tempmail.lol Edition", flush=True)
    print("  Temp email via API - No Gmail, No IMAP!", flush=True)
    print("=" * 60, flush=True)
    
    # 1. Test tempmail.lol connection
    print(f"\n  Testing tempmail.lol API...", flush=True)
    tm_ok, tm_domain, tm_read = test_tempmail_connection()
    if tm_ok:
        print(f"  tempmail.lol: OK! Domain: {tm_domain} | Read: {'OK' if tm_read else 'FAIL'}", flush=True)
    else:
        print(f"  tempmail.lol: FAILED! Check API key and internet", flush=True)
        sys.exit(1)
    
    # 2. Test if domain is accepted by Telicall
    print(f"\n  Testing domain {tm_domain} on Telicall...", flush=True)
    telicall_status = test_domain_on_telicall(tm_domain)
    if telicall_status == "ACCEPTED":
        print(f"  Telicall: ACCEPTED! Domain {tm_domain} works!", flush=True)
    else:
        print(f"  Telicall: {telicall_status} for {tm_domain}", flush=True)
        if TEMPMAIL_DOMAIN:
            print(f"  Using custom domain: {TEMPMAIL_DOMAIN}", flush=True)
        else:
            print(f"\n  WARNING: Default tempmail.lol domains may be BLOCKED by Telicall!", flush=True)
            print(f"  Solution: Use a custom domain that Telicall accepts:", flush=True)
            print(f"    1. Buy/own a domain", flush=True)
            print(f"    2. Set it up on tempmail.lol: https://tempmail.lol/ar/account", flush=True)
            print(f"    3. Run: python3 fox_caller12.py numbers.xlsx --domain yourdomain.com", flush=True)
            print(f"\n  Continuing anyway... (may get BLOCKED errors)", flush=True)
    
    # 3. Show config
    print(f"\n  API Key:    {TEMPMAIL_API_KEY[:20]}...", flush=True)
    print(f"  Domain:     {TEMPMAIL_DOMAIN or 'auto (random tempmail.lol domain)'}", flush=True)
    print(f"  Method:     tempmail.lol API (no Gmail, no IMAP!)", flush=True)
    
    # 4. Read numbers
    numbers = read_numbers(args.file, country=args.country)
    if not numbers:
        print("ERROR: No numbers in file!", flush=True)
        sys.exit(1)
    
    if args.limit > 0:
        numbers = numbers[:args.limit]
    
    _phone_queue = numbers
    _start_time = time.time()
    
    print(f"\n  Numbers:    {len(numbers)}", flush=True)
    print(f"  Country:    {args.country.upper()}", flush=True)
    print(f"  Mode:       {args.mode}", flush=True)
    print(f"  Threads:    {args.threads}", flush=True)
    print(f"  Duration:   {args.duration}s", flush=True)
    print(f"  Delay:      {args.delay}s between calls", flush=True)
    print(f"  Retries:    {MAX_RETRIES} per number", flush=True)
    
    # 5. Init proxy manager
    init_proxy_manager()
    
    # 6. Check server
    if args.mode == "server":
        if is_server_available():
            print(f"  Server:     Available ({SERVER_URL})", flush=True)
        else:
            print(f"  Server:     Unavailable! Switching to create mode", flush=True)
            args.mode = "create"
    
    # 7. Start pools
    start_pools()
    
    # 8. Quick test - create one Telicall session
    print(f"\n  Quick Test: Creating Telicall session...", flush=True)
    test_tok, test_dev, _ = init_session(get_proxy())
    if test_tok:
        print(f"  Session created! Token: {test_tok[:15]}...", flush=True)
    else:
        print(f"  Session creation failed! Will retry during operation...", flush=True)
    
    print(f"\n  Starting...", flush=True)
    print("-" * 60, flush=True)
    
    # 9. Start stats printer
    stats_thread = threading.Thread(target=print_stats, daemon=True)
    stats_thread.start()
    
    # 10. Start call monitor (server mode)
    if args.mode == "server":
        monitor_thread = threading.Thread(target=monitor_calls, daemon=True)
        monitor_thread.start()
    
    # 11. Start worker threads
    # Set global call delay
    global _call_delay
    _call_delay = args.delay
    
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
    
    # Wait for all workers
    for t in workers:
        t.join()
    
    # Wait for active calls
    time.sleep(15)
    
    # Final stats
    elapsed = time.time() - _start_time if _start_time else 0
    with _stats_lock:
        s = dict(_stats)
    
    print("\n" + "=" * 60, flush=True)
    print("  Final Report", flush=True)
    print("=" * 60, flush=True)
    print(f"  Time: {elapsed/60:.1f} minutes", flush=True)
    print(f"  Total numbers: {s['total']}", flush=True)
    print(f"  New accounts: {s['accounts_ok']}", flush=True)
    print(f"  Successful calls: {s['calls_ok']}", flush=True)
    print(f"  NO_BALANCE: {s['calls_no_balance']}", flush=True)
    print(f"  Final failures: {len(_failed_phones)}", flush=True)
    print(f"  Retries: {s['retries']}", flush=True)
    print(f"\n  Error breakdown:", flush=True)
    print(f"     Inbox fail: {s['inbox_fail']}", flush=True)
    print(f"     Session fail: {s['session_fail']}", flush=True)
    print(f"     Verify send fail: {s['verify_fail']}", flush=True)
    print(f"     OTP fail: {s['otp_fail']}", flush=True)
    print(f"     Confirm fail: {s['confirm_fail']}", flush=True)
    print(f"     Domain blocked: {s['domain_blocked']}", flush=True)
    print(f"     Email exists: {s['email_exists']}", flush=True)
    
    if _failed_phones:
        print(f"\n  Failed numbers ({len(_failed_phones)}):", flush=True)
        for fp in _failed_phones[:20]:
            print(f"     {fp['phone']} ({fp['reason']})", flush=True)
        if len(_failed_phones) > 20:
            print(f"     ... and {len(_failed_phones) - 20} more", flush=True)
    
    code_errors = s['inbox_fail'] + s['session_fail'] + s['verify_fail'] + s['otp_fail'] + s['confirm_fail'] + s['domain_blocked']
    if code_errors == 0 and s['email_exists'] > 0:
        print(f"\n  No code errors! ({s['email_exists']} emails existed - auto-replaced)", flush=True)
    elif code_errors == 0:
        print(f"\n  Zero errors! Everything working perfectly!", flush=True)
    else:
        print(f"\n  {code_errors} errors need fixing", flush=True)
    
    print("=" * 60, flush=True)
    
    # Stop pools
    _stop_flag.set()


if __name__ == "__main__":
    main()
