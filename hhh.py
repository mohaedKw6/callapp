#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fox Caller v3.0 - TelliCall Account Creator (hhh variant)
=========================================================
- ONLY hitzcart.com domain (fixed)
- web2.temp-mail.org as the only email provider
- Egyptian IP rotation on every request (x-real-ip)
- Continuous account creation without stopping
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
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from filelock import FileLock

# ─── Config ─────────────────────────────────────────
API_URL  = "https://api.telicall.com"
DAN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Dan.json")
PASSWORD = "@@@GMAQ@@@"

THREADS    = 10
FIXED_DOMAIN = "hitzcart.com"

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
    """Random Egyptian IP - every call gives a different one"""
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

# ─── web2.temp-mail.org ──────────────────────────────
WEB2_BASE_URL = "https://web2.temp-mail.org"
WEB2_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Origin': 'https://temp-mail.org',
    'Referer': 'https://temp-mail.org/',
    'Content-Type': 'application/json'
}

# ─── Stats ───────────────────────────────────────────
_counter_lock = threading.Lock()
_mem_lock     = threading.Lock()
_new_count    = 0
_stop_flag    = threading.Event()
_accounts_cache = None

# ═══════════════════════════════════════════════════════
# ─── Dan.json Encryption ─────────────────────────────
# ═══════════════════════════════════════════════════════

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
# ─── Email: web2 ONLY + hitzcart.com ONLY ────────────
# ═══════════════════════════════════════════════════════

def create_hitzcart_email():
    """
    Create email with ONLY hitzcart.com domain.
    Keeps trying until it gets hitzcart.com, discards other domains.
    On 429 rate limit, waits 2 seconds and retries immediately.
    """
    while not _stop_flag.is_set():
        try:
            r = requests.post(f"{WEB2_BASE_URL}/mailbox", headers=WEB2_HEADERS, timeout=15)
            if r.status_code in [200, 201]:
                data = r.json()
                email = data.get('mailbox', '')
                token = data.get('token', '')
                if email and token:
                    domain = email.split('@')[1] if '@' in email else ''
                    if domain == FIXED_DOMAIN:
                        return {
                            'email': email,
                            'token': token,
                            'api_type': 'web2',
                        }
                    # Not hitzcart.com - discard and retry immediately
            elif r.status_code == 429:
                # Rate limited - short wait then retry
                time.sleep(2)
            else:
                time.sleep(1)
        except Exception as e:
            print(f"  web2 error: {e}", flush=True)
            time.sleep(2)
    return None

def check_web2_inbox(email_token):
    """Check inbox on web2"""
    try:
        headers = WEB2_HEADERS.copy()
        headers['Authorization'] = f'Bearer {email_token}'
        r = requests.get(f'{WEB2_BASE_URL}/messages', headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else data.get('messages', [])
    except:
        pass
    return []

def get_otp(email_token):
    """Wait for OTP from web2 inbox"""
    deadline = time.time() + 90
    while time.time() < deadline:
        if _stop_flag.is_set():
            return None
        try:
            messages = check_web2_inbox(email_token)
            for msg in messages:
                sender  = msg.get('from', '').lower()
                subject = msg.get('subject', '').lower()
                body    = msg.get('bodyPreview', msg.get('body', msg.get('textBody', msg.get('bodyHtml', ''))))
                content = f"{sender} {subject} {body}".lower()
                if 'teli' in content or 'verification' in subject or 'verify' in subject:
                    m = re.search(r'\b(\d{6})\b', str(body))
                    if m:
                        return m.group(1)
        except:
            pass
        time.sleep(3)
    return None

# ═══════════════════════════════════════════════════════
# ─── TelliCall API ──────────────────────────────────
# ═══════════════════════════════════════════════════════

def init_session():
    """Initialize TelliCall session with rotating Egyptian IP"""
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
            print(f"  init [{ip}]: {r.status_code}", flush=True)
    except Exception as e:
        print(f"  init [{ip}]: {e}", flush=True)
    return None, None, None

def send_verify(email, headers):
    """Send verification email"""
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
            print(f"  send_verify: {r.status_code} | {err}", flush=True)
    except Exception as e:
        print(f"  send_verify: {e}", flush=True)
    return None

def verify_otp_api(ref, code, headers):
    """Verify OTP code"""
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
            print(f"  verify_otp: {r.status_code} | {err}", flush=True)
    except Exception as e:
        print(f"  verify_otp: {e}", flush=True)
    return None

# ═══════════════════════════════════════════════════════
# ─── Account Creation ───────────────────────────────
# ═══════════════════════════════════════════════════════

def create_one_account():
    """Create one complete TelliCall account with hitzcart.com email"""
    tid = threading.current_thread().name

    # 1. Create hitzcart.com email (keeps trying until it gets one)
    mail = create_hitzcart_email()
    if not mail:
        print(f"[{tid}] Stopped", flush=True)
        return False, "stopped"

    email_addr = mail['email']
    print(f"[{tid}] {email_addr}", flush=True)

    # 2. Init TelliCall session with new IP
    tok, device, headers = init_session()
    if not tok:
        print(f"[{tid}] init failed", flush=True)
        return False, "INIT_FAILED"

    # 3. Send verification
    ref = send_verify(email_addr, headers)
    if not ref:
        print(f"[{tid}] send_verify failed", flush=True)
        return False, "VERIFY_FAILED"

    # 4. Wait for OTP
    otp = get_otp(mail['token'])
    if not otp:
        print(f"[{tid}] OTP timeout", flush=True)
        return False, "OTP_TIMEOUT"

    # 5. Verify OTP
    user = verify_otp_api(ref, otp, headers)
    if not user:
        print(f"[{tid}] verify failed", flush=True)
        return False, "VERIFY_FAILED"

    # 6. Save account
    total = save_account(email_addr, device, tok)
    print(f"[{tid}] DONE! Total: {total}", flush=True)
    return True, total

def worker():
    """Worker thread - continuously creates accounts"""
    global _new_count
    tid = threading.current_thread().name

    while not _stop_flag.is_set():
        ok, result = create_one_account()

        if ok:
            with _counter_lock:
                _new_count += 1
                n = _new_count
            print(f"[{tid}] Account #{n} | Total: {result}", flush=True)
        else:
            # On failure, short pause then retry
            if not _stop_flag.is_set():
                time.sleep(1)

# ═══════════════════════════════════════════════════════
# ─── Main ───────────────────────────────────────────
# ═══════════════════════════════════════════════════════

def main():
    global _accounts_cache, _new_count

    print("=" * 50, flush=True)
    print("Fox Caller v3.0 (hhh) - hitzcart.com ONLY", flush=True)
    print("=" * 50, flush=True)
    print(f"Domain: @{FIXED_DOMAIN}", flush=True)
    print(f"Provider: web2.temp-mail.org ONLY", flush=True)
    print(f"IPs: Egyptian rotation on every request", flush=True)
    print(f"Threads: {THREADS}", flush=True)
    print(f"Mode: CONTINUOUS (Ctrl+C to stop)", flush=True)
    print("=" * 50, flush=True)

    # Quick test
    print("\nTesting web2 API...", flush=True)
    try:
        r = requests.post(f"{WEB2_BASE_URL}/mailbox", headers=WEB2_HEADERS, timeout=10)
        if r.status_code in [200, 201]:
            test_email = r.json().get('mailbox', '')
            test_domain = test_email.split('@')[1] if '@' in test_email else ''
            status = "= hitzcart.com!" if test_domain == FIXED_DOMAIN else f"!= {FIXED_DOMAIN}, will keep trying"
            print(f"  web2 OK: {test_email} {status}", flush=True)
        elif r.status_code == 429:
            print(f"  web2 rate limited (429) - will retry with short delays", flush=True)
        else:
            print(f"  web2 returned {r.status_code}", flush=True)
    except Exception as e:
        print(f"  web2 error: {e}", flush=True)

    existing = load_accounts()
    _accounts_cache = existing
    ex_count = len(existing)
    _new_count = 0

    if ex_count > 0:
        print(f"\nLoaded {ex_count} existing accounts", flush=True)

    print(f"\nStarting {THREADS} threads - CONTINUOUS mode...\n", flush=True)

    threads = []
    for i in range(THREADS):
        t = threading.Thread(target=worker, daemon=True, name=f"W{i}")
        t.start()
        threads.append(t)

    try:
        while not _stop_flag.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nStopping...", flush=True)
        _stop_flag.set()

    for t in threads:
        t.join(timeout=5)

    total = len(_accounts_cache) if _accounts_cache else 0
    print(f"\nAccounts created this session: {_new_count}", flush=True)
    print(f"Total accounts in Dan.json: {total}", flush=True)
    print(f"File: {DAN_FILE}", flush=True)

if __name__ == "__main__":
    main()
