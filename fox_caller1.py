#!/usr/bin/env python3
"""
Fox Caller 1 - Client for Fox Call Server
==========================================
Reads phone numbers from .xlsx files, creates Telicall accounts,
and sends call requests to the Fox Call Server.

The server handles the actual SIP calls. This client just:
1. Creates accounts
2. Picks numbers (checking history/cooldown)
3. Sends account + number to the server
4. Gets call_id back and saves to fox_call_history.json
5. Monitors active calls and picks new numbers when calls end

Usage:
    python3 fox_caller1.py <file.xlsx> [--server URL] [--workers N]
"""

import os
import sys
import re
import json
import time
import uuid
import base64
import random
import string
import hashlib
import threading
import requests
import openpyxl
from datetime import datetime
from collections import deque

# ============================================================================
#                            CONFIGURATION
# ============================================================================

SERVER_URL = "https://eaiupvh6.up.railway.app"  # Fox Call Server URL
ACCOUNTS_PASSWORD = "@@@GMAQ@@@"                  # For Dan.json encryption
CALL_COOLDOWN = 60                                # Seconds before re-calling same number
AUTO_CREATE_ACCOUNTS = True
ACCOUNT_CREATE_BATCH = 5                          # How many accounts to create at once
NUM_WORKERS = 3                                   # Concurrent workers
MAX_CONSECUTIVE_403 = 30                          # Stop after this many 403s
HISTORY_FILE = "fox_call_history.json"
SERVER_CHECK_INTERVAL = 10                        # How often to check if call ended (seconds)

# ============================================================================
#                             ANSI COLORS
# ============================================================================

class C:
    RST = '\033[0m'; BOLD = '\033[1m'; DIM = '\033[2m'
    RED = '\033[91m'; GREEN = '\033[92m'; YELLOW = '\033[93m'
    BLUE = '\033[94m'; MAGENTA = '\033[95m'; CYAN = '\033[96m'; WHITE = '\033[97m'
    BRED = '\033[1;91m'; BGREEN = '\033[1;92m'; BYELLOW = '\033[1;93m'
    BBLUE = '\033[1;94m'; BCMAGENTA = '\033[1;95m'; BCYAN = '\033[1;96m'

COLOR = sys.stdout.isatty() if hasattr(sys.stdout, 'isatty') else False

def clr(color_code, text):
    if COLOR:
        return f"{color_code}{text}{C.RST}"
    return text


# ============================================================================
#                         GLOBAL STATE
# ============================================================================

accounts = []           # List of account dicts WITH tokens
account_index = 0       # Current position in accounts list
account_lock = threading.Lock()
used_emails = set()

# Stats
stats = {
    "answered": 0, "no_answer": 0, "busy": 0, "failed": 0,
    "not_found": 0, "no_balance": 0, "api_fail": 0,
    "active_calls": 0, "total_calls": 0, "auto_created": 0,
}
stats_lock = threading.Lock()


# ============================================================================
#                    CALL HISTORY (fox_call_history.json)
# ============================================================================

def load_call_history(directory):
    """Load call history. Returns dict {phone_no_plus: {id, time, result}}"""
    path = os.path.join(directory, HISTORY_FILE)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Handle both old format (phone: timestamp) and new format (phone: {id, time})
        result = {}
        for key, val in data.items():
            if isinstance(val, dict):
                result[key] = val
            elif isinstance(val, (int, float)):
                # Old format - convert
                result[key] = {'id': None, 'time': val, 'result': None}
        return result
    except:
        return {}


def save_call_history(directory, history):
    """Save call history atomically."""
    path = os.path.join(directory, HISTORY_FILE)
    temp_path = path + '.tmp'
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, path)
    except Exception as e:
        try:
            os.unlink(temp_path)
        except:
            pass


def is_number_available(phone, history, server_url):
    """
    Check if a number is available to call.
    Returns True if:
    - Number has no history, OR
    - Last call ended (check server if has call_id), OR
    - More than CALL_COOLDOWN seconds have passed
    """
    key = phone.lstrip('+')
    info = history.get(key)

    if info is None:
        return True  # Never called before

    call_id = info.get('id')
    call_time = info.get('time', 0)
    call_result = info.get('result')

    # If call has an ID, check with server if it's still active
    if call_id:
        try:
            r = requests.get(f"{server_url}/call/{call_id}", timeout=5)
            if r.status_code == 200:
                data = r.json()
                if data.get('active', False) or data.get('status') in ('queued', 'starting', 'calling'):
                    # Call is still active - don't call this number
                    return False
                else:
                    # Call ended - update history with result
                    result = data.get('result', 'unknown')
                    duration = data.get('duration', 0)
                    info['result'] = result
                    info['duration'] = duration
                    # Number is now available
                    return True
            elif r.status_code == 404:
                # Call not found on server - it's done
                return True
        except:
            pass  # Server unreachable - check time-based cooldown

    # Time-based cooldown
    if call_time and (time.time() - call_time) < CALL_COOLDOWN:
        return False

    return True


def update_history_with_call(directory, phone, call_id, server_url):
    """Update history entry after starting a call."""
    history = load_call_history(directory)
    key = phone.lstrip('+')
    history[key] = {
        'id': call_id,
        'time': time.time(),
        'result': None,
        'duration': 0,
    }
    save_call_history(directory, history)


def update_history_with_result(directory, phone, result, duration=0):
    """Update history entry with final result."""
    history = load_call_history(directory)
    key = phone.lstrip('+')
    if key in history:
        history[key]['result'] = result
        history[key]['duration'] = duration
    else:
        history[key] = {
            'id': None,
            'time': time.time(),
            'result': result,
            'duration': duration,
        }
    save_call_history(directory, history)


# ============================================================================
#                     TELICALL API (Account Creation Only)
# ============================================================================

API_URL = "https://api.telicall.com"

# Egyptian IP ranges
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

MAIL_TM_HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'Origin': 'https://mail.tm',
    'Referer': 'https://mail.tm/en/',
    'User-Agent': 'Mozilla/5.0 (Linux; Android 11; Infinix X698) AppleWebKit/537.36',
}
MAIL_TM_DOMAIN = "wshu.net"
_mail_tm_lock = threading.Lock()


def create_mail_tm():
    for attempt in range(5):
        with _mail_tm_lock:
            name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
            email_addr = f"{name}@{MAIL_TM_DOMAIN}"
            password = 'TmpP@ss' + ''.join(random.choices(string.digits, k=4))
            try:
                r = requests.post('https://api.mail.tm/accounts',
                    json={'address': email_addr, 'password': password},
                    headers=MAIL_TM_HEADERS, timeout=15)
                if r.status_code in [200, 201]:
                    r2 = requests.post('https://api.mail.tm/token',
                        json={'address': email_addr, 'password': password},
                        headers=MAIL_TM_HEADERS, timeout=10)
                    if r2.status_code == 200:
                        jwt = r2.json()['token']
                        return {'email': email_addr, 'token': jwt, 'password': password}
                elif r.status_code == 429:
                    time.sleep(10 * (attempt + 1))
                else:
                    time.sleep(2)
            except:
                time.sleep(2)
    return None


def get_otp_from_mail(jwt):
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            r = requests.get('https://api.mail.tm/messages',
                headers={'Authorization': f'Bearer {jwt}', **MAIL_TM_HEADERS},
                timeout=8)
            if r.status_code == 200:
                data = r.json()
                messages = data.get('hydra:member', []) if isinstance(data, dict) else data
                for msg in messages:
                    msg_id = msg.get('id', '')
                    if msg_id:
                        r2 = requests.get(f'https://api.mail.tm/messages/{msg_id}',
                            headers={'Authorization': f'Bearer {jwt}', **MAIL_TM_HEADERS},
                            timeout=8)
                        if r2.status_code == 200:
                            full_msg = r2.json()
                            content = full_msg.get('text', '') or str(full_msg)
                            if 'teli' in content.lower():
                                m = re.search(r'\b(\d{6})\b', content)
                                if m:
                                    return m.group(1)
        except:
            pass
        time.sleep(2)
    return None


def init_session_with_ip():
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
        h["x-request-id"] = str(uuid.uuid4())
        h["x-req-timestamp"] = str(int(time.time() * 1000))
        r = requests.post(f"{API_URL}/init", json=body, headers=h, timeout=10)
        if r.status_code == 200:
            tok = r.json().get('result', {}).get('token')
            if tok:
                h["x-token"] = tok
                return tok, device, h
            else:
                print(f"    {clr(C.RED, 'init [' + ip + ']: no token')}", flush=True)
        else:
            print(f"    {clr(C.RED, 'init [' + ip + ']: HTTP ' + str(r.status_code))}", flush=True)
    except Exception as e:
        print(f"    {clr(C.RED, 'init [' + ip + ']: ' + str(e)[:50])}", flush=True)
    return None, None, None


def send_verify_email(email, headers_or_token, device_id=None):
    if isinstance(headers_or_token, dict):
        h = headers_or_token.copy()
        h["x-request-id"] = str(uuid.uuid4())
        h["x-req-timestamp"] = str(int(time.time() * 1000))
    else:
        device_id = device_id or ''.join(random.choices('0123456789abcdef', k=16))
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
            "x-token": headers_or_token,
        }
    try:
        r = requests.post(f"{API_URL}/auth/send-email", json={'email': email}, headers=h, timeout=10)
        if r.status_code == 200:
            return r.json().get('result', {}).get('reference')
        else:
            print(f"    {clr(C.RED, 'send_verify: HTTP ' + str(r.status_code))}", flush=True)
    except Exception as e:
        print(f"    {clr(C.RED, 'send_verify: ' + str(e)[:50])}", flush=True)
    return None


def verify_otp_code(ref, code, headers_or_token, device_id=None):
    if isinstance(headers_or_token, dict):
        h = headers_or_token.copy()
        h["x-request-id"] = str(uuid.uuid4())
        h["x-req-timestamp"] = str(int(time.time() * 1000))
    else:
        device_id = device_id or ''.join(random.choices('0123456789abcdef', k=16))
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
            "x-token": headers_or_token,
        }
    try:
        r = requests.post(f"{API_URL}/auth/verify-identity",
                          json={'reference': ref, 'code': str(code)},
                          headers=h, timeout=10)
        if r.status_code == 200:
            return r.json().get('result', {}).get('user')
        else:
            print(f"    {clr(C.RED, 'verify_otp: HTTP ' + str(r.status_code))}", flush=True)
    except Exception as e:
        print(f"    {clr(C.RED, 'verify_otp: ' + str(e)[:50])}", flush=True)
    return None


def create_one_account_fast():
    """Create a single new Telicall account."""
    mail = create_mail_tm()
    if not mail:
        return None

    tok, device, headers = init_session_with_ip()
    if not tok:
        return None

    ref = send_verify_email(mail['email'], headers)
    if not ref:
        return None

    otp = get_otp_from_mail(mail['token'])
    if not otp:
        return None

    user = verify_otp_code(ref, otp, headers)
    if not user:
        return None

    return {
        'email': mail['email'],
        'x-token': tok,
        'x-client-device-id': device,
        'password': mail.get('password', ''),
    }


def auto_create_accounts(directory, count=5, max_retries=3):
    """Create accounts in parallel."""
    if not AUTO_CREATE_ACCOUNTS:
        return []

    all_new = []

    for batch in range(max_retries):
        print(f"\n  {clr(C.BYELLOW, 'Creating ' + str(count) + ' accounts (batch ' + str(batch+1) + '/' + str(max_retries) + ')...')}")

        new_accounts = []
        create_lock = threading.Lock()
        progress = {'done': 0, 'ok': 0, 'fail': 0}

        def _create_one(idx):
            acc = create_one_account_fast()
            with create_lock:
                progress['done'] += 1
                if acc:
                    progress['ok'] += 1
                    new_accounts.append(acc)
                    print(f"    {clr(C.GREEN, '+' + str(progress['ok']))} {acc['email'][:30]}", flush=True)
                else:
                    progress['fail'] += 1
                    print(f"    {clr(C.RED, 'x')} failed #{progress['done']}", flush=True)

        threads = []
        for i in range(count):
            t = threading.Thread(target=_create_one, args=(i,), daemon=True)
            t.start()
            threads.append(t)

        for t in threads:
            t.join(timeout=90)

        print(f"  {clr(C.CYAN, 'Result:')} {clr(C.GREEN, str(progress['ok']) + ' OK')} / {clr(C.RED, str(progress['fail']) + ' failed')}")

        if new_accounts:
            all_new.extend(new_accounts)
            # Add to global accounts list
            with account_lock:
                accounts.extend(new_accounts)
            # Save to Dan.json
            _save_to_dan(directory, new_accounts)
            with stats_lock:
                stats["auto_created"] += len(new_accounts)
            print(f"  {clr(C.BGREEN, str(len(new_accounts)) + ' accounts created!')}")
            return new_accounts

        if batch < max_retries - 1:
            wait = min(3 * (batch + 1), 15)
            print(f"  {clr(C.YELLOW, 'Retry in ' + str(wait) + 's...')}")
            time.sleep(wait)

    print(f"  {clr(C.BRED, 'Failed to create accounts!')}")
    return []


def _save_to_dan(directory, new_accounts):
    """Save new accounts to Dan.json."""
    dan_path = os.path.join(directory, "Dan.json")
    try:
        raw_accounts = []
        if os.path.exists(dan_path) and os.path.getsize(dan_path) > 0:
            try:
                key = hashlib.sha256(ACCOUNTS_PASSWORD.encode()).digest()
                raw_b64 = open(dan_path, 'rb').read()
                raw = base64.b64decode(raw_b64)
                text = bytes([raw[i] ^ key[i % len(key)] for i in range(len(raw))]).decode('utf-8')
                raw_accounts = json.loads(text)
            except:
                raw_accounts = []

        for acc in new_accounts:
            raw_accounts.append({
                'email': acc['email'],
                'x-client-device-id': acc.get('x-client-device-id', ''),
                'x-token': acc.get('x-token', ''),
                'created': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

        key = hashlib.sha256(ACCOUNTS_PASSWORD.encode()).digest()
        json_str = json.dumps(raw_accounts, indent=2, ensure_ascii=False)
        raw = json_str.encode('utf-8')
        enc = base64.b64encode(bytes([raw[i] ^ key[i % len(key)] for i in range(len(raw))]))
        with open(dan_path, 'wb') as f:
            f.write(enc)
    except Exception as e:
        print(f"  {clr(C.YELLOW, 'Warning: Could not save Dan.json:')} {e}")


# ============================================================================
#                       ACCOUNT MANAGEMENT
# ============================================================================

def get_next_account():
    """Get the next available account."""
    global account_index
    with account_lock:
        while account_index < len(accounts):
            acc = accounts[account_index]
            account_index += 1
            email = acc.get('email', '')
            if email not in used_emails and acc.get('x-token'):
                return acc
        return None


def load_dan_json(filepath):
    """Load and decrypt Dan.json."""
    key = hashlib.sha256(ACCOUNTS_PASSWORD.encode()).digest()
    raw_b64 = open(filepath, 'rb').read()
    raw = base64.b64decode(raw_b64)
    text = bytes([raw[i] ^ key[i % len(key)] for i in range(len(raw))]).decode('utf-8')
    return json.loads(text)


# ============================================================================
#                       FILE READERS
# ============================================================================

def find_xlsx_files(directory):
    xlsx_files = []
    for f in os.listdir(directory):
        if f.endswith('.xlsx') and not f.startswith('~$'):
            xlsx_files.append(os.path.join(directory, f))
    return sorted(xlsx_files)


def read_phones_from_xlsx(filepath):
    wb = openpyxl.load_workbook(filepath, read_only=True)
    ws = wb.active
    phones = []
    number_col = None

    for row in ws.iter_rows(min_row=1, max_row=3, values_only=False):
        for cell in row:
            if cell.value and str(cell.value).strip().lower() in ('number', 'phone', 'mobile', 'numbers', 'phones'):
                number_col = cell.column
                break
        if number_col:
            break

    for row in ws.iter_rows(min_row=2, values_only=False):
        if number_col:
            cell = row[number_col - 1] if len(row) >= number_col else None
        else:
            cell = row[0] if row else None

        if cell and cell.value:
            val = str(cell.value).strip()
            cleaned = re.sub(r'[^\d+]', '', val)
            if cleaned and len(cleaned) >= 7:
                if not cleaned.startswith('+'):
                    cleaned = '+' + cleaned
                phones.append(cleaned)

    wb.close()
    return phones


# ============================================================================
#                         SERVER COMMUNICATION
# ============================================================================

def server_start_call(server_url, phone, token, device_id, email):
    """Send a call request to the server. Returns call_id or None."""
    try:
        r = requests.post(f"{server_url}/call/start", json={
            'phone': phone,
            'token': token,
            'device_id': device_id,
            'email': email,
        }, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data.get('call_id')
        else:
            print(f"  {clr(C.RED, 'Server error: HTTP ' + str(r.status_code))}")
            return None
    except Exception as e:
        print(f"  {clr(C.RED, 'Server error: ' + str(e)[:60])}")
        return None


def server_check_call(server_url, call_id):
    """Check call status on server. Returns dict or None."""
    try:
        r = requests.get(f"{server_url}/call/{call_id}", timeout=5)
        if r.status_code == 200:
            return r.json()
        return None
    except:
        return None


def server_health(server_url):
    """Check if server is alive."""
    try:
        r = requests.get(f"{server_url}/health", timeout=5)
        if r.status_code == 200:
            return r.json()
        return None
    except:
        return None


# ============================================================================
#                          MAIN LOOP
# ============================================================================

def print_banner():
    print()
    print(clr(C.BCYAN, "  " + "=" * 55))
    print(clr(C.BWHITE, "     Fox Caller 1 - Server Client"))
    print(clr(C.BCYAN, "  " + "=" * 55))
    print(clr(C.DIM, "     Calls via Fox Call Server (Railway)"))
    print(clr(C.BCYAN, "  " + "=" * 55))
    print()


def run(phones, server_url, num_workers, directory):
    """Main loop: create accounts, pick numbers, send to server, monitor."""
    global account_index, accounts

    total = len(phones)
    start_time = time.time()

    print()
    print(f"  {clr(C.BBLUE, 'Server:')} {server_url}")
    print(f"  {clr(C.BBLUE, 'Numbers:')} {total} | {clr(C.BBLUE, 'Workers:')} {num_workers}")
    print(f"  {clr(C.BBLUE, 'Cooldown:')} {CALL_COOLDOWN}s | {clr(C.BBLUE, 'History:')} {HISTORY_FILE}")
    print()

    # Check server health
    health = server_health(server_url)
    if health:
        print(f"  {clr(C.BGREEN, 'Server OK!')} Active calls: {health.get('active_calls', '?')}")
    else:
        print(f"  {clr(C.BRED, 'WARNING: Server unreachable! Will retry...')}")
    print()

    # Shared state
    phone_queue = deque(list(phones))
    random.shuffle(phone_queue)
    queue_lock = threading.Lock()
    refill_lock = threading.Lock()

    consecutive_403 = [0]
    c403_lock = threading.Lock()
    stop_flag = [False]
    round_num = [1]

    def get_next_phone():
        """Get next available phone from queue."""
        with queue_lock:
            history = load_call_history(directory)
            tried = 0
            total_in_q = len(phone_queue)
            while tried < total_in_q:
                phone = phone_queue.popleft()
                if is_number_available(phone, history, server_url):
                    return phone
                else:
                    phone_queue.append(phone)
                    tried += 1
            return None

    def refill_queue():
        with refill_lock:
            with queue_lock:
                phone_queue.clear()
                shuffled = list(phones)
                random.shuffle(shuffled)
                phone_queue.extend(shuffled)
            round_num[0] += 1
            print(f"  {clr(C.BCYAN, f'--- Round {round_num[0]} ---')}")

    def worker(worker_id):
        """Worker thread: picks number, gets account, sends to server, monitors."""
        while not stop_flag[0]:
            # Get next phone
            phone = get_next_phone()
            if phone is None:
                # All on cooldown or queue empty
                history = load_call_history(directory)
                all_unavailable = all(
                    not is_number_available(p, history, server_url)
                    for p in phones
                )
                if all_unavailable:
                    # Find minimum wait time
                    min_wait = CALL_COOLDOWN
                    for p in phones:
                        key = p.lstrip('+')
                        info = history.get(key)
                        if info and info.get('time'):
                            wait = CALL_COOLDOWN - (time.time() - info['time'])
                            if wait < min_wait:
                                min_wait = wait
                    wait_time = max(int(min_wait) + 1, 2)
                    print(f"  {clr(C.CYAN, f'[W{worker_id}] All busy - wait {wait_time}s...')}")
                    time.sleep(wait_time)
                refill_queue()
                continue

            # Get an account
            acc = get_next_account()
            if acc is None:
                if AUTO_CREATE_ACCOUNTS:
                    print(f"  {clr(C.BYELLOW, f'[W{worker_id}] Creating accounts...')}")
                    new = auto_create_accounts(directory, ACCOUNT_CREATE_BATCH, max_retries=3)
                    if new:
                        acc = get_next_account()
                    else:
                        print(f"  {clr(C.BRED, f'[W{worker_id}] Failed to create accounts!')}")
                        stop_flag[0] = True
                        return
                if acc is None:
                    print(f"  {clr(C.BRED, f'[W{worker_id}] No accounts!')}")
                    stop_flag[0] = True
                    return

            token = acc.get('x-token', '')
            device_id = acc.get('x-client-device-id', '')
            email = acc.get('email', '???')
            email_short = email[:20]

            # Send to server
            print(f"  {clr(C.CYAN, f'[W{worker_id}] RING')} {phone} <- {email_short}")

            call_id = server_start_call(server_url, phone, token, device_id, email)

            if call_id is None:
                # Server error - could be temporary
                with stats_lock:
                    stats["api_fail"] += 1
                print(f"  {clr(C.RED, f'[W{worker_id}] SERVER_ERR')} {phone}")
                time.sleep(2)  # Small delay before retry
                continue

            # Save call_id to history
            update_history_with_call(directory, phone, call_id, server_url)
            with stats_lock:
                stats["active_calls"] += 1
                stats["total_calls"] += 1

            print(f"  {clr(C.GREEN, f'[W{worker_id}] CALL_ID')} {call_id} for {phone}")

            # Now monitor this call - wait for it to end
            # The worker is "busy" with this call until it ends
            while not stop_flag[0]:
                time.sleep(SERVER_CHECK_INTERVAL)
                call_info = server_check_call(server_url, call_id)

                if call_info is None:
                    # Can't reach server - keep waiting
                    continue

                status = call_info.get('status', '')
                if status == 'ended':
                    # Call finished!
                    result = call_info.get('result', 'unknown')
                    duration = call_info.get('duration', 0)

                    # Update history with result
                    update_history_with_result(directory, phone, result, duration)

                    # Update stats
                    with stats_lock:
                        stats["active_calls"] -= 1
                        if result in ('answered_ok', 'answered_short'):
                            stats["answered"] += 1
                        elif result == 'no_answer':
                            stats["no_answer"] += 1
                        elif result == 'declined':
                            stats["busy"] += 1
                        elif result == 'not_found':
                            stats["not_found"] += 1
                        elif result == 'no_balance':
                            stats["no_balance"] += 1
                            used_emails.add(email)
                        elif result == 'call_403':
                            with c403_lock:
                                consecutive_403[0] += 1
                                if consecutive_403[0] >= MAX_CONSECUTIVE_403:
                                    print(f"  {clr(C.BRED, f'{MAX_CONSECUTIVE_403}x 403 - region blocked!')}")
                                    stop_flag[0] = True
                                    return
                            stats["failed"] += 1
                        else:
                            stats["failed"] += 1

                    # Reset 403 counter on success
                    if result in ('answered_ok', 'answered_short', 'no_answer', 'declined'):
                        with c403_lock:
                            consecutive_403[0] = 0

                    # Mark account as used after successful answer
                    if result in ('answered_ok', 'answered_short'):
                        used_emails.add(email)

                    # Print result
                    result_colors = {
                        'answered_ok': C.BGREEN, 'answered_short': C.GREEN,
                        'no_answer': C.YELLOW, 'declined': C.BYELLOW,
                        'not_found': C.MAGENTA, 'no_balance': C.RED,
                        'call_403': C.RED, 'failed': C.RED,
                    }
                    c = result_colors.get(result, C.RED)
                    dur_str = f"{duration}s" if duration else "?"
                    print(f"  {clr(c, f'[W{worker_id}] {result.upper()}')} {phone} ({dur_str}) <- {email_short}")

                    # Print running stats
                    _print_stats(start_time)
                    print()

                    # Call ended - pick next number
                    break

                elif status in ('queued', 'starting', 'calling'):
                    # Still active
                    continue
                else:
                    # Unknown status - treat as ended
                    break

    # Launch workers
    print(f"  {clr(C.BCYAN, f'Launching {num_workers} workers...')}")
    print()
    threads = []
    for i in range(num_workers):
        t = threading.Thread(target=worker, args=(i + 1,), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.5)

    # Monitor
    last_stats_time = time.time()
    while not stop_flag[0]:
        if all(not t.is_alive() for t in threads):
            break
        if time.time() - last_stats_time >= 30:
            _print_stats(start_time)
            last_stats_time = time.time()
        time.sleep(1)

    for t in threads:
        t.join(timeout=5)

    _print_stats(start_time)


def _print_stats(start_time):
    """Print running stats."""
    elapsed = time.time() - start_time
    with stats_lock:
        ans = stats["answered"]
        na = stats["no_answer"]
        bs = stats["busy"]
        fl = stats["failed"]
        nf = stats["not_found"]
        nb = stats["no_balance"]
        ac = stats["active_calls"]
        tc = stats["total_calls"]

    mins = int(elapsed // 60)
    secs = int(elapsed % 60)
    print(f"  {clr(C.DIM, f'Stats [{mins}m{secs}s]')} "
          f"{clr(C.GREEN, str(ans) + ' Ans')} | "
          f"{clr(C.YELLOW, str(na) + ' NoA')} | "
          f"{clr(C.BYELLOW, str(bs) + ' Bsy')} | "
          f"{clr(C.RED, str(fl) + ' Fail')} | "
          f"{clr(C.MAGENTA, str(nf) + ' NF')} | "
          f"{clr(C.BLUE, str(ac) + ' Active')} | "
          f"{clr(C.CYAN, str(tc) + ' Total')}")


# ============================================================================
#                          MAIN ENTRY POINT
# ============================================================================

def main():
    print_banner()

    # Parse arguments
    directory = os.getcwd()
    selected_file = None
    server_url = SERVER_URL
    num_workers = NUM_WORKERS

    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == '--server':
            if i + 1 < len(argv):
                server_url = argv[i + 1]
                i += 1
        elif arg == '--workers':
            if i + 1 < len(argv) and argv[i + 1].isdigit():
                num_workers = int(argv[i + 1])
                num_workers = max(1, min(num_workers, 20))
                i += 1
        elif arg.endswith(('.xlsx', '.txt', '.csv')):
            selected_file = os.path.abspath(arg)
        elif not arg.startswith('-'):
            directory = os.path.abspath(arg)
        i += 1

    # Find file
    if not selected_file:
        xlsx_files = find_xlsx_files(directory)
        if xlsx_files:
            selected_file = xlsx_files[0]
            print(f"  {clr(C.GREEN, 'File:')} {os.path.basename(selected_file)}")
        else:
            print(f"  {clr(C.BRED, 'No .xlsx files found!')}")
            print(f"  Usage: python3 fox_caller1.py <file.xlsx> [--server URL] [--workers N]")
            sys.exit(1)
    else:
        if not os.path.exists(selected_file):
            print(f"  {clr(C.BRED, 'File not found:')} {selected_file}")
            sys.exit(1)
        directory = os.path.dirname(selected_file)

    print(f"  {clr(C.BLUE, 'Server:')} {server_url}")
    print(f"  {clr(C.BLUE, 'Workers:')} {num_workers}")
    print(f"  {clr(C.BLUE, 'Directory:')} {directory}")
    print()

    # Read numbers
    print(f"  {clr(C.BLUE, 'Reading numbers...')}")
    if selected_file.endswith('.xlsx'):
        phones = read_phones_from_xlsx(selected_file)
    else:
        phones = []
        with open(selected_file, 'r') as f:
            for line in f:
                cleaned = re.sub(r'[^\d+]', '', line.strip())
                if cleaned and len(cleaned) >= 7:
                    if not cleaned.startswith('+'):
                        cleaned = '+' + cleaned
                    phones.append(cleaned)

    if not phones:
        print(f"  {clr(C.BRED, 'No phone numbers found!')}")
        sys.exit(1)

    print(f"  Numbers: {clr(C.BGREEN, str(len(phones)))}")
    print()

    # Load accounts from Dan.json if exists
    global accounts
    dan_path = None
    for candidate in ["Dan.json", "dan.json"]:
        for d in [directory, os.path.dirname(os.path.abspath(__file__))]:
            fp = os.path.join(d, candidate) if d else None
            if fp and os.path.exists(fp):
                dan_path = fp
                break
        if dan_path:
            break

    if dan_path:
        try:
            raw_accounts = load_dan_json(dan_path)
            # Initialize accounts (they already have tokens from Dan.json)
            for acc in raw_accounts:
                if acc.get('x-token') and acc.get('x-client-device-id'):
                    accounts.append(acc)
            print(f"  {clr(C.GREEN, 'Accounts from Dan.json:')} {len(accounts)}")
        except:
            accounts = []

    # Create initial accounts if needed
    if not accounts and AUTO_CREATE_ACCOUNTS:
        print(f"  {clr(C.BYELLOW, 'No accounts - creating initial batch...')}")
        auto_create_accounts(directory, ACCOUNT_CREATE_BATCH, max_retries=3)

    if not accounts:
        print(f"  {clr(C.BRED, 'No accounts available!')}")
        sys.exit(1)

    print(f"  {clr(C.BGREEN, 'Ready accounts:')} {len(accounts)}")
    print()

    # GO!
    run(phones, server_url, num_workers, directory)


if __name__ == "__main__":
    main()
