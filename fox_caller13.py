#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fox Caller v13.0 - Instant Mail Edition
========================================
Email provider: Instant Mail API (mail-server-2.1timetech.com)
  - Creates @gmail.com and @googlemail.com temp emails via API
  - Reads OTP from inbox via API (no IMAP needed!)
  - Gmail domains are ACCEPTED by Telicall (not blocked!)
  - Decodes encrypted API responses using reverse-engineered cipher

Services supported:
  @gmail.com        - Gmail dots trick (accepted by Telicall)
  @+gmail.com       - Gmail plus addressing
  @googlemail.com   - Googlemail dots trick (accepted by Telicall)
  @+googlemail.com  - Googlemail plus addressing

How it works:
  1. Instant Mail API creates a Gmail-based temp email
  2. The email uses Gmail dots trick (all dots ignored by Gmail)
  3. Telicall sends OTP to that email
  4. Instant Mail server receives the email (via shared Gmail IMAP)
  5. We poll the API to read the OTP

Usage:
  python3 fox_caller13.py numbers.xlsx
  python3 fox_caller13.py numbers.xlsx --service gmail
  python3 fox_caller13.py numbers.xlsx --service googlemail
  python3 fox_caller13.py numbers.xlsx --mode server --threads 5
  python3 fox_caller13.py file.xlsx --country eg
"""

import requests
import json
import uuid
import time
import random
import re
import os
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

# Instant Mail API
INSTANTMAIL_API_BASE = "https://mail-server-2.1timetech.com"
INSTANTMAIL_APP_KEY  = "b9db03078622"

# Service types
SERVICE_GMAIL       = "gmail"
SERVICE_GOOGLEMAIL  = "googlemail"
DEFAULT_SERVICE     = SERVICE_GMAIL


# ═══════════════════════════════════════════════════════════════
# ─── Instant Mail API - Encryption/Decryption ─────────────────
# ═══════════════════════════════════════════════════════════════
BASE64_ALPHA = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'

# Reverse-engineered substitution swaps (base64 character pairs)
# Format: (standard_index, standard_index) meaning those positions are swapped
_CIPHER_SWAPS = [
    (1, 51),   # B ↔ z
    (27, 57),  # b ↔ 5
    (26, 40),  # a ↔ o
    (62, 49),  # + ↔ x
    (42, 44),  # q ↔ s
    (56, 63),  # 4 ↔ /
]

def _build_custom_alphabet():
    """Build the custom base64 alphabet with cipher swaps applied."""
    alpha = list(BASE64_ALPHA)
    for i, j in _CIPHER_SWAPS:
        alpha[i], alpha[j] = alpha[j], alpha[i]
    return ''.join(alpha)

_CUSTOM_ALPHA = _build_custom_alphabet()
_DECODE_TRANS = str.maketrans(_CUSTOM_ALPHA, BASE64_ALPHA)


def instantmail_decode(encrypted_data):
    """
    Decode encrypted data from Instant Mail API.
    
    The encryption is: JSON → base64 → character substitution → reverse
    Decryption: reverse → character un-substitution → base64 decode → JSON
    
    Returns parsed JSON dict or None on failure.
    """
    try:
        # Step 1: Reverse the string
        reversed_str = encrypted_data[::-1]
        
        # Step 2: Pre-process special characters
        # '=' in encrypted string represents '+' in standard base64
        # '*' in encrypted string represents '/' in standard base64
        # 'x' at the end represents '=' padding
        processed = reversed_str.replace('*', '/').replace('=', '+')
        
        # Handle trailing 'x' as base64 padding '='
        if processed.endswith('x'):
            processed = processed[:-1] + '='
        if processed.endswith('xx'):
            processed = processed[:-2] + '=='
        
        # Step 3: Apply character substitution (custom → standard alphabet)
        standard = processed.translate(_DECODE_TRANS)
        
        # Step 4: Add base64 padding if needed
        pad_needed = 4 - len(standard) % 4
        if pad_needed < 4:
            standard += '=' * pad_needed
        
        # Step 5: Base64 decode
        decoded_bytes = base64.b64decode(standard)
        text = decoded_bytes.decode('utf-8', errors='replace')
        
        # Step 6: Parse JSON
        return json.loads(text)
    except Exception:
        return None


def instantmail_encode(data_dict):
    """
    Encode data for Instant Mail API (encrypt).
    
    Reverse of decode: JSON → base64 → character substitution → reverse
    """
    try:
        # Step 1: JSON encode
        json_str = json.dumps(data_dict, separators=(',', ':'))
        
        # Step 2: Base64 encode (without padding)
        b64 = base64.b64encode(json_str.encode()).decode().rstrip('=')
        
        # Step 3: Apply character substitution (standard → custom alphabet)
        encode_trans = str.maketrans(BASE64_ALPHA, _CUSTOM_ALPHA)
        substituted = b64.translate(encode_trans)
        
        # Step 4: Post-process special characters
        # '+' → '=' (in encrypted string)
        # '/' → '*' (in encrypted string)
        # '=' padding → 'x' at the end
        result = substituted.replace('+', '=').replace('/', '*')
        # Replace trailing '=' with 'x' for padding
        # Actually, we stripped padding, so no trailing = to handle
        
        # Step 5: Reverse
        return result[::-1]
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
# ─── Instant Mail API ─────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
_im_lock = threading.Lock()

def instantmail_create_inbox(service=DEFAULT_SERVICE, debug=False):
    """
    Create a temp email inbox via Instant Mail API.
    Returns (email_address, inbox_id) or (None, None) on failure.
    
    service: 'gmail' for @gmail.com, 'googlemail' for @googlemail.com
    """
    headers = {
        'accept': 'application/json',
        'x-app-key': INSTANTMAIL_APP_KEY,
        'Content-Type': 'application/json',
        'User-Agent': 'okhttp/4.9.2'
    }
    
    # The API accepts empty body and creates a random Gmail address
    # We can also specify the service type
    body = {}
    
    try:
        r = requests.post(
            f"{INSTANTMAIL_API_BASE}/api/g-mail?params=x03e",
            headers=headers, json=body, timeout=20
        )
        
        if debug:
            print(f"    [DEBUG] InstantMail: HTTP {r.status_code} | Body: {r.text[:200]}", flush=True)
        
        if r.status_code == 200:
            resp = r.json()
            encrypted_data = resp.get('data', '')
            
            if not encrypted_data:
                if debug:
                    print(f"    [DEBUG] InstantMail: No data in response", flush=True)
                return None, None
            
            # Decode the encrypted response
            decoded = instantmail_decode(encrypted_data)
            
            if not decoded:
                if debug:
                    print(f"    [DEBUG] InstantMail: Decode failed for: {encrypted_data[:50]}...", flush=True)
                return None, None
            
            if not decoded.get('success'):
                if debug:
                    print(f"    [DEBUG] InstantMail: API returned success=false", flush=True)
                return None, None
            
            email = decoded.get('email', '')
            inbox_id = decoded.get('id', '')
            
            if not email or not inbox_id:
                if debug:
                    print(f"    [DEBUG] InstantMail: Missing email or id: {decoded}", flush=True)
                return None, None
            
            # Verify the email domain
            domain = email.split('@')[1] if '@' in email else ''
            if service == SERVICE_GOOGLEMAIL and 'googlemail' not in domain:
                if debug:
                    print(f"    [DEBUG] InstantMail: Got {domain} instead of googlemail.com, retrying...", flush=True)
                # Try again - the API might return gmail.com sometimes
                return None, None  # Will retry
            
            if debug:
                print(f"    [DEBUG] InstantMail: SUCCESS! {email} (id: {inbox_id})", flush=True)
            
            return email, inbox_id
        
        if debug:
            print(f"    [DEBUG] InstantMail: HTTP {r.status_code}", flush=True)
    
    except requests.exceptions.ConnectionError as e:
        if debug:
            print(f"    [DEBUG] InstantMail: ConnectionError: {e}", flush=True)
    except requests.exceptions.Timeout as e:
        if debug:
            print(f"    [DEBUG] InstantMail: Timeout: {e}", flush=True)
    except Exception as e:
        if debug:
            print(f"    [DEBUG] InstantMail: {type(e).__name__}: {e}", flush=True)
    
    return None, None


def instantmail_get_messages(inbox_id, debug=False):
    """
    Get messages for an inbox via Instant Mail API.
    Returns list of message dicts or empty list.
    """
    headers = {
        'accept': 'application/json',
        'x-app-key': INSTANTMAIL_APP_KEY,
        'User-Agent': 'okhttp/4.9.2'
    }
    
    try:
        r = requests.get(
            f"{INSTANTMAIL_API_BASE}/api/email/{inbox_id}/messages",
            headers=headers, timeout=20
        )
        
        if r.status_code == 200:
            resp = r.json()
            encrypted_data = resp.get('data', '')
            
            if not encrypted_data:
                return []
            
            # Decode the response
            decoded = instantmail_decode(encrypted_data)
            
            if decoded is None:
                return []
            
            # The response might be a list of messages or empty array
            if isinstance(decoded, list):
                return decoded
            elif isinstance(decoded, dict):
                # Might be wrapped in an object
                return decoded.get('messages', decoded.get('data', []))
            
            return []
    
    except Exception:
        return []


def instantmail_read_otp(inbox_id, timeout=OTP_TIMEOUT, sent_time=None, debug=False):
    """
    Poll Instant Mail inbox for OTP from Telicall.
    Returns 6-digit OTP string or None on timeout.
    """
    if sent_time is None:
        sent_time = time.time()
    
    deadline = time.time() + timeout
    
    while time.time() < deadline:
        if _stop_flag.is_set():
            return None
        
        messages = instantmail_get_messages(inbox_id, debug=debug)
        
        for msg in messages:
            # Extract OTP from message content
            # Message format varies - try multiple fields
            text_parts = []
            
            if isinstance(msg, dict):
                # Try common field names
                for field in ['body', 'text', 'content', 'html', 'message', 'subject']:
                    val = msg.get(field, '')
                    if val:
                        text_parts.append(str(val))
                
                # If no specific fields, try all string values
                if not text_parts:
                    for key, val in msg.items():
                        if isinstance(val, str) and len(val) > 10:
                            text_parts.append(val)
            elif isinstance(msg, str):
                text_parts.append(msg)
            
            combined = ' '.join(text_parts)
            otp = _extract_otp(combined)
            if otp:
                return otp
        
        time.sleep(OTP_POLL_INTERVAL)
    
    return None


def _extract_otp(text):
    """Extract 6-digit OTP from text."""
    # Clean HTML tags
    clean = re.sub(r'<[^>]+>', ' ', text)
    # Look for 6-digit code
    m = re.search(r'\b(\d{6})\b', clean)
    return m.group(1) if m else None


def test_instantmail_connection():
    """Test Instant Mail API at startup. Returns (success, email, read_ok)."""
    for attempt in range(3):
        try:
            debug_mode = (attempt == 0)
            email, inbox_id = instantmail_create_inbox(debug=debug_mode)
            if email and inbox_id:
                domain = email.split('@')[1] if '@' in email else '?'
                # Test reading messages
                msgs = instantmail_get_messages(inbox_id)
                read_ok = isinstance(msgs, list)
                return True, email, read_ok
            else:
                print(f"    Attempt {attempt+1}/3: inbox creation returned None", flush=True)
        except Exception as e:
            print(f"    Attempt {attempt+1}/3: {type(e).__name__}: {e}", flush=True)
        if attempt < 2:
            time.sleep(2)
    
    return False, None, False


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
    for _ in range(num_session_fillers):
        t = threading.Thread(target=_session_pool_filler, daemon=True)
        t.start()
    time.sleep(2)
    print(f"  Pool:       sessions={_session_pool.qsize()}", flush=True)


# ═══════════════════════════════════════════════════════════════
# ─── Telicall API ─────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def init_session(proxy_dict=None, use_xrealip=True):
    import hashlib
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
                    return None, 'BLOCKED'
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
    import hashlib
    return hashlib.sha256(password.encode()).digest()

def encrypt_text(plain: str, password: str) -> bytes:
    import hashlib
    key = _make_key(password)
    data = plain.encode('utf-8')
    enc = bytes([data[i] ^ key[i % len(key)] for i in range(len(data))])
    return base64.b64encode(enc)

def decrypt_file(path: str, password: str) -> str:
    import hashlib
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


# ═══════════════════════════════════════════════════════════════
# ─── Read Numbers from File ──────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def _normalize_phone(num, country='eg'):
    num = num.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    num = num.replace('\u202a', '').replace('\u202c', '')
    if not num.startswith('+'):
        num = '+' + num if num.isdigit() else num
    digits = num.lstrip('+')
    if not digits.isdigit() or len(digits) < 8:
        return None
    if country == 'eg':
        if digits.startswith('0') and len(digits) == 11:
            return '+20' + digits[1:]
        elif digits.startswith('01') and len(digits) == 10:
            return '+20' + digits[1:]
        elif digits.startswith('1') and len(digits) == 10:
            return '+20' + digits
        elif digits.startswith('20') and len(digits) >= 11:
            return '+' + digits
        elif digits.startswith('00'):
            return '+' + digits[2:]
    if digits.startswith('00'):
        return '+' + digits[2:]
    if len(digits) >= 10:
        return '+' + digits
    return None

def read_numbers(filepath, country='eg'):
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
    seen = set()
    unique = []
    for n in numbers:
        if n not in seen:
            seen.add(n)
            unique.append(n)
    if unique:
        print(f"\n  Numbers found: {len(unique)} unique (from {raw_count} raw entries)", flush=True)
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
# ─── Worker: Create Account + Call ───────────────────────────
# ═══════════════════════════════════════════════════════════════
def _try_one_phone(phone, duration, mode, service, tid):
    """
    One attempt for a phone number. Returns status string.
    """
    # Step 1: Create temp email inbox via Instant Mail
    email_addr, inbox_id = instantmail_create_inbox(service=service, debug=False)
    
    if not email_addr or not inbox_id:
        print(f"[{tid}] ✗ Inbox failed {phone}", flush=True)
        update_stat("inbox_fail")
        return 'retry'
    
    email_short = email_addr.split('@')[0][:20]
    email_domain = email_addr.split('@')[1] if '@' in email_addr else '?'
    
    print(f"[{tid}] 📧 {email_addr} → {phone}", flush=True)
    
    # Step 2: Get Session
    tok, device, headers, sess_proxy = get_session_from_pool()
    active_proxy = sess_proxy or get_proxy()
    
    if not tok:
        print(f"[{tid}] ✗ Session failed {phone}", flush=True)
        update_stat("session_fail")
        return 'retry'
    
    # Step 3: Send Verification Email
    sent_time = time.time()
    ref, err = send_verify(email_addr, headers, active_proxy)
    if not ref:
        err_str = str(err or "")
        if err_str == 'EMAIL_EXISTS':
            print(f"[{tid}] ✗ Email exists {email_short}", flush=True)
            update_stat("email_exists")
            return 'email_exists'
        elif 'BLOCKED' in err_str:
            print(f"[{tid}] ✗ Domain BLOCKED: {email_domain}", flush=True)
            update_stat("domain_blocked")
            return 'domain_blocked'
        else:
            print(f"[{tid}] ✗ Verify failed {phone} ({err_str[:50]})", flush=True)
            update_stat("verify_fail")
        if active_proxy:
            active_proxy = get_proxy_and_mark_dead(active_proxy)
        return 'retry'
    
    print(f"[{tid}] ⏳ OTP sent → {email_short}@{email_domain}", flush=True)
    
    # Step 4: Read OTP from Instant Mail
    otp = instantmail_read_otp(inbox_id, timeout=OTP_TIMEOUT, sent_time=sent_time)
    
    if not otp:
        print(f"[{tid}] ✗ OTP timeout {phone}", flush=True)
        update_stat("otp_fail")
        return 'retry'
    
    print(f"[{tid}] 🔑 OTP: {otp}", flush=True)
    
    # Step 5: Verify OTP
    user, verify_err = verify_otp_api(ref, otp, headers, active_proxy)
    if not user:
        err_type = str(verify_err or "")
        if 'email_exists' in err_type:
            print(f"[{tid}] ✗ Email already registered {email_short}", flush=True)
            update_stat("email_exists")
            return 'email_exists'
        elif 'expired' in err_type:
            print(f"[{tid}] ✗ OTP expired {phone}", flush=True)
            update_stat("otp_fail")
            return 'retry'
        else:
            print(f"[{tid}] ✗ Verify failed: {err_type[:40]}", flush=True)
            update_stat("confirm_fail")
            return 'retry'
    
    # Account created!
    user_email = user.get('email', email_addr)
    print(f"[{tid}] ✓ Account: {user_email}", flush=True)
    update_stat("accounts_ok")
    
    # Step 6: Save account
    total = save_account(user_email, device, tok)
    print(f"[{tid}] 💾 Saved (total: {total})", flush=True)
    
    # Step 7: Make call or upload to server
    if mode == 'server':
        # Upload to server
        ready = upload_to_server(user_email, device, tok)
        if ready >= 0:
            print(f"[{tid}] 📤 Uploaded to server (ready: {ready})", flush=True)
        
        # Trigger call via server
        result = trigger_make_call(phone, duration)
        status = result.get('status', 'unknown')
        if status == 'answered_ok':
            dur = result.get('actual_duration', 0)
            caller = result.get('from_number', '')
            print(f"[{tid}] 📞 Call OK {phone} ({dur}s) ← {caller}", flush=True)
            update_stat("calls_ok")
            return 'ok'
        elif 'balance' in str(result.get('error', '')).lower():
            print(f"[{tid}] 💸 No balance {phone}", flush=True)
            update_stat("accounts_no_bal")
            return 'no_balance'
        else:
            err = result.get('error', 'unknown')
            print(f"[{tid}] ✗ Call failed {phone} ({err})", flush=True)
            update_stat("calls_failed")
            return 'fail'
    
    elif mode == 'call':
        # Direct call
        call_result = direct_telicall_call(phone, tok, device, active_proxy)
        if call_result.get('success'):
            from_num = call_result.get('from', '')
            sip_limit = call_result.get('limit', 60)
            print(f"[{tid}] 📞 Calling {phone} ← {from_num} (limit: {sip_limit}s)", flush=True)
            update_stat("calls_ok")
            return 'ok'
        else:
            err = call_result.get('error', '')
            if 'NO_BALANCE' in str(err):
                print(f"[{tid}] 💸 No balance {phone}", flush=True)
                update_stat("accounts_no_bal")
                return 'no_balance'
            print(f"[{tid}] ✗ Call failed {phone} ({err})", flush=True)
            update_stat("calls_failed")
            return 'fail'
    
    else:  # mode == 'create'
        print(f"[{tid}] ✓ Account created (no call)", flush=True)
        return 'ok'


def worker(thread_id, duration, mode, service, delay=0):
    """Worker thread that processes phone numbers."""
    while not _stop_flag.is_set():
        phone = get_next_phone()
        if phone is None:
            break
        
        update_stat("total")
        tid = f"T{thread_id}"
        
        for attempt in range(MAX_RETRIES):
            if _stop_flag.is_set():
                break
            
            result = _try_one_phone(phone, duration, mode, service, tid)
            
            if result == 'ok':
                break
            elif result == 'no_balance':
                add_failed_phone(phone, 'no_balance')
                break
            elif result == 'domain_blocked':
                add_failed_phone(phone, 'domain_blocked')
                break
            elif result == 'email_exists':
                # Retry with different email
                update_stat("retries")
                time.sleep(1)
                continue
            elif result == 'retry':
                update_stat("retries")
                time.sleep(2)
                continue
            else:
                add_failed_phone(phone, result)
                break
        
        if delay > 0:
            time.sleep(delay)


# ═══════════════════════════════════════════════════════════════
# ─── Main ─────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def main():
    global _start_time, _phone_queue, _queue_index
    
    parser = argparse.ArgumentParser(
        description='Fox Caller v13.0 - Instant Mail Edition (@gmail.com/@googlemail.com)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Services:
  gmail       - @gmail.com addresses (default)
  googlemail  - @googlemail.com addresses

Modes:
  create  - Create accounts only (no calls)
  call    - Create accounts + make direct SIP calls
  server  - Create accounts + upload to server + server makes calls

Examples:
  python3 fox_caller13.py numbers.xlsx
  python3 fox_caller13.py numbers.xlsx --service googlemail
  python3 fox_caller13.py numbers.xlsx --mode server --threads 5
  python3 fox_caller13.py numbers.txt --country eg --delay 3
""")
    parser.add_argument('file', help='Phone numbers file (xlsx/txt)')
    parser.add_argument('--mode', default='server', choices=['create', 'call', 'server'],
                       help='Operation mode (default: server)')
    parser.add_argument('--threads', type=int, default=DEFAULT_THREADS,
                       help=f'Number of worker threads (default: {DEFAULT_THREADS})')
    parser.add_argument('--duration', type=int, default=DEFAULT_DURATION,
                       help=f'Call duration in seconds (default: {DEFAULT_DURATION})')
    parser.add_argument('--service', default=DEFAULT_SERVICE,
                       choices=[SERVICE_GMAIL, SERVICE_GOOGLEMAIL],
                       help=f'Email service (default: {DEFAULT_SERVICE})')
    parser.add_argument('--country', default='eg',
                       help='Country code for phone normalization (default: eg)')
    parser.add_argument('--delay', type=float, default=0,
                       help='Delay between numbers in seconds (default: 0)')
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug output for API calls')
    
    args = parser.parse_args()
    
    print("╔══════════════════════════════════════════════════╗", flush=True)
    print("║     🦊 Fox Caller v13.0 - Instant Mail Edition   ║", flush=True)
    print("║     @gmail.com / @googlemail.com                 ║", flush=True)
    print("╚══════════════════════════════════════════════════╝", flush=True)
    print(flush=True)
    
    # Read phone numbers
    numbers = read_numbers(args.file, args.country)
    if not numbers:
        print("No valid phone numbers found!", flush=True)
        sys.exit(1)
    
    # Init proxy manager
    init_proxy_manager()
    
    # Test Instant Mail API
    print(f"\n  Testing Instant Mail API ({args.service})...", flush=True)
    ok, test_email, read_ok = test_instantmail_connection()
    if ok:
        domain = test_email.split('@')[1] if '@' in test_email else '?'
        print(f"  ✅ Instant Mail: OK! ({domain}, read: {read_ok})", flush=True)
    else:
        print(f"  ❌ Instant Mail: FAILED! Check internet connection.", flush=True)
        print(f"     The script requires access to mail-server-2.1timetech.com", flush=True)
        sys.exit(1)
    
    # Test Telicall session
    print(f"\n  Testing Telicall API...", flush=True)
    tok, _, _ = init_session()
    if tok:
        print(f"  ✅ Telicall: Session OK", flush=True)
    else:
        print(f"  ⚠️  Telicall: Session failed (will retry)", flush=True)
    
    # Config summary
    print(f"\n  Config:", flush=True)
    print(f"    Service:    {args.service} (@{args.service}.com)", flush=True)
    print(f"    Mode:       {args.mode}", flush=True)
    print(f"    Threads:    {args.threads}", flush=True)
    print(f"    Duration:   {args.duration}s", flush=True)
    print(f"    Numbers:    {len(numbers)}", flush=True)
    if args.delay:
        print(f"    Delay:      {args.delay}s between numbers", flush=True)
    
    # Confirm
    print(f"\n  Ready to process {len(numbers)} numbers?", flush=True)
    try:
        confirm = input("  Press Enter to start (Ctrl+C to cancel): ")
    except (KeyboardInterrupt, EOFError):
        print("\n  Cancelled.", flush=True)
        sys.exit(0)
    
    # Start
    _start_time = time.time()
    _phone_queue = numbers
    _queue_index = 0
    
    # Start session pool
    start_pools()
    
    # Start workers
    threads = []
    for i in range(args.threads):
        t = threading.Thread(target=worker, args=(i+1, args.duration, args.mode, args.service, args.delay),
                           daemon=True)
        t.start()
        threads.append(t)
    
    # Progress monitor
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(5)
            elapsed = time.time() - _start_time
            with _stats_lock:
                s = dict(_stats)
            done = s['total']
            total = len(numbers)
            pct = done * 100 // max(total, 1)
            ok_calls = s['calls_ok'] + s['accounts_ok']
            print(f"  [{pct:3d}%] Done:{done}/{total} | "
                  f"✓Acct:{s['accounts_ok']} ✓Call:{s['calls_ok']} | "
                  f"✗OTP:{s['otp_fail']} ✗Sess:{s['session_fail']} | "
                  f"⏳{elapsed:.0f}s", flush=True)
    except KeyboardInterrupt:
        print(f"\n  ⏹ Stopping...", flush=True)
        _stop_flag.set()
    
    # Wait for threads
    for t in threads:
        t.join(timeout=30)
    
    # Final stats
    elapsed = time.time() - _start_time if _start_time else 0
    with _stats_lock:
        s = dict(_stats)
    
    print(f"\n{'='*50}", flush=True)
    print(f"  Fox Caller v13.0 - Final Report", flush=True)
    print(f"{'='*50}", flush=True)
    print(f"  Time:       {elapsed:.1f}s", flush=True)
    print(f"  Processed:  {s['total']}", flush=True)
    print(f"  Accounts:   {s['accounts_ok']} created", flush=True)
    print(f"  Calls OK:   {s['calls_ok']}", flush=True)
    print(f"  No Balance: {s['accounts_no_bal']}", flush=True)
    print(f"  OTP Fail:   {s['otp_fail']}", flush=True)
    print(f"  Blocked:    {s['domain_blocked']}", flush=True)
    print(f"  Retries:    {s['retries']}", flush=True)
    print(f"{'='*50}", flush=True)
    
    if _failed_phones:
        print(f"\n  Failed phones ({len(_failed_phones)}):", flush=True)
        for fp in _failed_phones[:20]:
            print(f"    {fp['phone']}: {fp['reason']}", flush=True)
        if len(_failed_phones) > 20:
            print(f"    ... and {len(_failed_phones)-20} more", flush=True)


if __name__ == '__main__':
    main()
