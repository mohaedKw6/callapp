#!/usr/bin/env python3
"""
Fox Caller 1 - Direct SIP Caller with Server Tracking
======================================================
Reads phone numbers from .xlsx files, creates Telicall accounts,
and makes SIP calls DIRECTLY from your device (fixes SIP 403 issue).

Also reports call results to the Fox Call Server for tracking & bot access.

Architecture:
  Client (this script) -----> Telicall API (get SIP creds)
       |                          |
       +----> SIP Server (make call directly from local IP)
       |
       +----> Fox Call Server (report results for tracking/bot)

Usage:
    python3 fox_caller1.py <file.xlsx> [--server URL] [--workers N] [--duration N]
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
import socket
import struct
import threading
import audioop
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
MAX_CONSECUTIVE_403 = 30                          # Stop after this many SIP 403s
HISTORY_FILE = "fox_call_history.json"
REPORT_TO_SERVER = True                           # Report results to server for tracking/bot

# SIP Configuration
SIP_CONNECT_TIMEOUT = 10
RECV_TIMEOUT = 5
RINGING_TIMEOUT = 80          # SIP loop iterations (80 * 0.5s = 40s ringing max)
MAX_CALL_DURATION = 600       # 10 min max call duration
INSTANT_BYE_CHECKS = 3
CALL_DURATION = 3             # Seconds to stay in call after answer (0 = hang up immediately)

# Telicall API
API_URL = "https://api.telicall.com"

# ============================================================================
#                             ANSI COLORS
# ============================================================================

class C:
    RST = '\033[0m'; BOLD = '\033[1m'; DIM = '\033[2m'
    RED = '\033[91m'; GREEN = '\033[92m'; YELLOW = '\033[93m'
    BLUE = '\033[94m'; MAGENTA = '\033[95m'; CYAN = '\033[96m'; WHITE = '\033[97m'
    BRED = '\033[1;91m'; BGREEN = '\033[1;92m'; BYELLOW = '\033[1;93m'
    BBLUE = '\033[1;94m'; BCMAGENTA = '\033[1;95m'; BCYAN = '\033[1;96m'; BWHITE = '\033[1;97m'

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
        result = {}
        for key, val in data.items():
            if isinstance(val, dict):
                result[key] = val
            elif isinstance(val, (int, float)):
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


def is_number_available(phone, history, server_url=None):
    """Check if a number is available to call."""
    key = phone.lstrip('+')
    info = history.get(key)

    if info is None:
        return True

    call_time = info.get('time', 0)
    call_result = info.get('result')

    # Time-based cooldown
    if call_time and (time.time() - call_time) < CALL_COOLDOWN:
        return False

    return True


def update_history_with_call(directory, phone, call_id=None):
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
#                     TELICALL API (Account Creation + Call Start)
# ============================================================================

# Egyptian IP ranges for x-real-ip header
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
    """Generate a random Egyptian IP for x-real-ip header."""
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


def get_telicall_headers(token=None, device_id=None):
    """Get Telicall API headers with Egyptian IP spoofing."""
    if not device_id:
        device_id = ''.join(random.choices('0123456789abcdef', k=16))
    eg_ip = rand_eg_ip()
    return {
        "host": "api.telicall.com",
        "x-request-id": str(uuid.uuid4()),
        "user-agent": "Dalvik/2.1.0",
        "x-app-version": "1.2.1",
        "x-client-device-id": device_id,
        "x-lang": "en",
        "x-os": "android",
        "x-os-version": "11",
        "x-req-timestamp": str(int(time.time() * 1000)),
        "x-req-signature": "-1",
        "content-type": "application/json",
        "x-token": token or "",
        "x-currency": "EGP",
        "x-real-ip": eg_ip,
    }


def telicall_start_call(phone, call_token, call_device_id):
    """Start a call via Telicall API and return SIP credentials."""
    if not phone.startswith('+'):
        phone = '+' + phone
    headers = get_telicall_headers(token=call_token, device_id=call_device_id)
    try:
        r = requests.post(
            f"{API_URL}/call/outbound/start",
            json={'to': phone, 'source': 'numpad'},
            headers=headers,
            timeout=10
        )
        if r.status_code == 200 and r.json().get('result'):
            sip = r.json()['result'].get('sip', {})
            from_num = r.json()['result'].get('from', {}).get('msisdn', '')
            return {
                'user': sip.get('username'),
                'pass': sip.get('password'),
                'domain': sip.get('domain'),
                'port': sip.get('port', 5060),
                'proto': sip.get('protocol', 'tcp'),
                'from': from_num,
                'to': r.json()['result'].get('to', {}).get('msisdn'),
                'limit': sip.get('callLimit', 60),
                'balance': sip.get('balanceLimit', 60),
            }
        elif r.status_code == 400:
            err_text = r.text.lower()
            if 'balance' in err_text:
                return 'no_balance'
            return {'error': 'call_400'}
        elif r.status_code == 404:
            return {'error': 'call_404'}
        elif r.status_code == 403:
            return {'error': 'call_403'}
        else:
            return {'error': f'call_{r.status_code}'}
    except Exception as e:
        return None


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
    h = get_telicall_headers(device_id=device)
    h["x-token"] = ""
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
        h = get_telicall_headers(token=headers_or_token, device_id=device_id)
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
        h = get_telicall_headers(token=headers_or_token, device_id=device_id)
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
            with account_lock:
                accounts.extend(new_accounts)
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
#                              SIP CLASS
# ============================================================================

class SIP:
    """SIP client for making VoIP calls via Telicall."""

    def __init__(self, u, p, d, pt, pr='tcp'):
        self.u, self.p, self.d, self.pt, self.pr = u, p, d, pt, pr
        self.lp = random.randint(50000, 60000)
        self.rtp_port = self.lp + 2
        self.tag = uuid.uuid4().hex[:8]
        self.seq = 1
        self.sk = None
        self.rs = self.rn = self.ro = self.rq = None
        self.br = self.cid = None
        self.rtp_sk = None
        self.rtp_run = False
        self.audio = []
        self.rtp_ip = None
        self.rtp_pt = None
        self.ssrc = random.randint(1000000, 9999999)
        self.rtp_seq = 0
        self.rtp_ts = 0
        self.remote_tag = None
        self._from_num = ''

    def conn(self):
        try:
            self.sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sk.settimeout(SIP_CONNECT_TIMEOUT)
            if self.pr == 'tls':
                import ssl
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                self.sk = context.wrap_socket(self.sk, server_hostname=self.d)
            self.sk.connect((self.d, self.pt))
            return True
        except Exception as e:
            return False

    def _pauth(self, h):
        for k, p in [('rs', r'realm="([^"]+)"'), ('rn', r'nonce="([^"]+)"'),
                     ('ro', r'opaque="([^"]+)"'), ('rq', r'qop="([^"]+)"')]:
            m = re.search(p, h)
            if m:
                setattr(self, k, m.group(1))

    def _auth(self, method, uri):
        if not self.rs or not self.rn:
            return None
        h1 = hashlib.md5(f"{self.u}:{self.rs}:{self.p}".encode()).hexdigest()
        h2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
        if self.rq:
            nc, cn = "00000001", uuid.uuid4().hex[:8]
            rp = hashlib.md5(f"{h1}:{self.rn}:{nc}:{cn}:{self.rq}:{h2}".encode()).hexdigest()
            return (f'Digest username="{self.u}",realm="{self.rs}",nonce="{self.rn}",'
                    f'uri="{uri}",response="{rp}",opaque="{self.ro}",'
                    f'qop={self.rq},nc={nc},cnonce="{cn}",algorithm=MD5')
        rp = hashlib.md5(f"{h1}:{self.rn}:{h2}".encode()).hexdigest()
        return (f'Digest username="{self.u}",realm="{self.rs}",nonce="{self.rn}",'
                f'uri="{uri}",response="{rp}",opaque="{self.ro}",algorithm=MD5')

    def send(self, msg):
        try:
            if isinstance(msg, str):
                msg = msg.encode()
            self.sk.send(msg)
            return True
        except:
            return False

    def recv(self, timeout=RECV_TIMEOUT):
        try:
            self.sk.settimeout(timeout)
            data = b''
            while True:
                chunk = self.sk.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b'\r\n\r\n' in data:
                    try:
                        header = data.split(b'\r\n\r\n')[0].decode('utf-8', errors='ignore')
                        cl = re.search(r'Content-Length:\s*(\d+)', header, re.IGNORECASE)
                        if cl:
                            body_start = data.find(b'\r\n\r\n') + 4
                            if len(data) >= body_start + int(cl.group(1)):
                                break
                        else:
                            break
                    except:
                        break
            return data.decode('utf-8', errors='ignore')
        except:
            return None

    def parse(self, resp):
        if not resp:
            return None
        lines = resp.split('\r\n')
        parts = lines[0].split(' ', 2)
        code = int(parts[1]) if len(parts) > 1 else 0
        headers = {}
        for line in lines[1:]:
            if ':' in line:
                k, v = line.split(':', 1)
                headers[k.strip().lower()] = v.strip()
        to_tag = None
        m = re.search(r';tag=([^;>\s]+)', headers.get('to', ''))
        if m:
            to_tag = m.group(1)
        sdp_ip, sdp_port = None, None
        if '\r\n\r\n' in resp:
            sdp = resp.split('\r\n\r\n', 1)[1]
            m = re.search(r'c=IN IP4 ([\d.]+)', sdp)
            if m:
                sdp_ip = m.group(1)
            m = re.search(r'm=audio (\d+)', sdp)
            if m:
                sdp_port = int(m.group(1))
        return {'code': code, 'headers': headers, 'to_tag': to_tag,
                'sdp_ip': sdp_ip, 'sdp_port': sdp_port}

    def register(self, auth=False):
        uri = f"sip:{self.d}"
        branch = f"z9hG4bK-{uuid.uuid4().hex[:16]}"
        call_id = f"{uuid.uuid4().hex[:16]}@{self.d}"
        msg = f"REGISTER {uri} SIP/2.0\r\n"
        msg += f"Via: SIP/2.0/{self.pr.upper()} {self.d}:{self.pt};branch={branch};rport\r\n"
        msg += f"From: <sip:{self.u}@{self.d}>;tag={self.tag}\r\n"
        msg += f"To: <sip:{self.u}@{self.d}>\r\n"
        msg += f"Call-ID: {call_id}\r\n"
        msg += f"CSeq: {self.seq} REGISTER\r\n"
        msg += f"Contact: <sip:{self.u}@{self.d}:{self.lp}>\r\n"
        msg += "Max-Forwards: 70\r\n"
        msg += "User-Agent: TelliCall/1.2.1\r\n"
        msg += "Allow: INVITE, ACK, CANCEL, BYE, OPTIONS\r\n"
        if auth and self.rn:
            a = self._auth("REGISTER", uri)
            if a:
                msg += f"Authorization: {a}\r\n"
        msg += "Content-Length: 0\r\n\r\n"
        self.seq += 1
        return self.send(msg)

    def _get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((self.d, 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return '0.0.0.0'

    def invite(self, number, auth=False):
        uri = f"sip:+{number}@{self.d}"
        self.br = f"z9hG4bK-{uuid.uuid4().hex[:16]}"
        self.cid = f"{uuid.uuid4().hex[:16]}@{self.d}"
        local_ip = self._get_local_ip()
        sdp = f"v=0\r\n"
        sdp += f"o=- {int(time.time())} {int(time.time())} IN IP4 {local_ip}\r\n"
        sdp += "s=TelliCall\r\n"
        sdp += f"c=IN IP4 {local_ip}\r\n"
        sdp += "t=0 0\r\n"
        sdp += f"m=audio {self.rtp_port} RTP/AVP 0 8 101\r\n"
        sdp += "a=rtpmap:0 PCMU/8000\r\n"
        sdp += "a=rtpmap:8 PCMA/8000\r\n"
        sdp += "a=rtpmap:101 telephone-event/8000\r\n"
        sdp += "a=sendrecv\r\n"
        sdp += "a=ptime:20\r\n"
        sdp_b = sdp.encode()
        msg = f"INVITE {uri} SIP/2.0\r\n"
        msg += f"Via: SIP/2.0/{self.pr.upper()} {self.d}:{self.pt};branch={self.br};rport\r\n"
        msg += f"From: <sip:{self.u}@{self.d}>;tag={self.tag}\r\n"
        msg += f"To: <sip:+{number}@{self.d}>\r\n"
        msg += f"Call-ID: {self.cid}\r\n"
        msg += f"CSeq: {self.seq} INVITE\r\n"
        msg += f"Contact: <sip:{self.u}@{self.d}:{self.lp}>\r\n"
        msg += "Max-Forwards: 70\r\n"
        msg += "User-Agent: TelliCall/1.2.1\r\n"
        msg += "Allow: INVITE, ACK, CANCEL, BYE, OPTIONS\r\n"
        msg += "Content-Type: application/sdp\r\n"
        if auth and self.rn:
            a = self._auth("INVITE", uri)
            if a:
                msg += f"Authorization: {a}\r\n"
        msg += f"Content-Length: {len(sdp_b)}\r\n\r\n"
        msg += sdp
        self.seq += 1
        return self.send(msg)

    def ack(self, number):
        msg = f"ACK sip:+{number}@{self.d} SIP/2.0\r\n"
        msg += f"Via: SIP/2.0/{self.pr.upper()} {self.d}:{self.pt};branch={self.br};rport\r\n"
        msg += f"From: <sip:{self.u}@{self.d}>;tag={self.tag}\r\n"
        msg += f"To: <sip:+{number}@{self.d}>;tag={self.remote_tag}\r\n"
        msg += f"Call-ID: {self.cid}\r\n"
        msg += f"CSeq: {self.seq} ACK\r\n"
        msg += "Max-Forwards: 70\r\n"
        msg += "Content-Length: 0\r\n\r\n"
        return self.send(msg)

    def bye(self, number):
        self.seq += 1
        branch = f"z9hG4bK-{uuid.uuid4().hex[:16]}"
        msg = f"BYE sip:+{number}@{self.d} SIP/2.0\r\n"
        msg += f"Via: SIP/2.0/{self.pr.upper()} {self.d}:{self.pt};branch={branch};rport\r\n"
        msg += f"From: <sip:{self.u}@{self.d}>;tag={self.tag}\r\n"
        msg += f"To: <sip:+{number}@{self.d}>;tag={self.remote_tag}\r\n"
        msg += f"Call-ID: {self.cid}\r\n"
        msg += f"CSeq: {self.seq} BYE\r\n"
        msg += "Max-Forwards: 70\r\n"
        msg += "Content-Length: 0\r\n\r\n"
        return self.send(msg)

    def ok(self, req):
        lines = req.split('\r\n')
        headers = {}
        for line in lines[1:]:
            if ':' in line:
                k, v = line.split(':', 1)
                headers[k.strip().lower()] = v.strip()
        msg = "SIP/2.0 200 OK\r\n"
        msg += f"Via: {headers.get('via', '')}\r\n"
        msg += f"From: {headers.get('from', '')}\r\n"
        msg += f"To: {headers.get('to', '')}\r\n"
        msg += f"Call-ID: {headers.get('call-id', '')}\r\n"
        msg += f"CSeq: {headers.get('cseq', '')}\r\n"
        msg += "Content-Length: 0\r\n\r\n"
        return self.send(msg)

    def start_rtp(self):
        try:
            self.rtp_sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.rtp_sk.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self.rtp_sk.bind(('0.0.0.0', self.rtp_port))
            except OSError:
                self.rtp_sk.bind(('0.0.0.0', 0))
                self.rtp_port = self.rtp_sk.getsockname()[1]
            self.rtp_sk.settimeout(0.05)
            self.rtp_run = True
            return True
        except:
            return False

    def build_rtp(self, payload):
        pt = 0  # PCMU silence
        first = (2 << 6) | 0
        header = struct.pack('!BBHII', first, pt, self.rtp_seq, self.rtp_ts, self.ssrc)
        self.rtp_seq = (self.rtp_seq + 1) & 0xFFFF
        self.rtp_ts += 160
        return header + payload

    def send_rtp(self):
        if not self.rtp_ip or not self.rtp_pt or not self.rtp_sk:
            return False
        payload = bytes([0xFF] * 160)  # silence
        pkt = self.build_rtp(payload)
        try:
            self.rtp_sk.sendto(pkt, (self.rtp_ip, self.rtp_pt))
            return True
        except:
            return False

    def rtp_loop(self, stop_evt, dur):
        start = time.perf_counter()

        def _recv_worker():
            sock = self.rtp_sk
            try:
                sock.settimeout(1.0)
            except:
                pass
            while self.rtp_run and not stop_evt.is_set():
                try:
                    data, addr = sock.recvfrom(4096)
                    if len(data) < 12:
                        continue
                    pt = data[1] & 0x7F
                    raw = data[12:]
                    if pt == 8:
                        pcm = audioop.alaw2lin(raw, 2)
                    else:
                        pcm = audioop.ulaw2lin(raw, 2)
                    self.audio.append(pcm)
                except socket.timeout:
                    continue
                except OSError:
                    break
                except:
                    pass

        recv_thread = threading.Thread(target=_recv_worker, daemon=True)
        recv_thread.start()

        sent = 0
        next_send = start
        PTIME = 0.020

        while self.rtp_run and not stop_evt.is_set():
            now = time.perf_counter()
            if now - start >= dur:
                break
            if now >= next_send:
                self.send_rtp()
                sent += 1
                next_send = start + sent * PTIME
            remaining = next_send - time.perf_counter()
            if remaining > 0.003:
                time.sleep(remaining - 0.002)
            while time.perf_counter() < next_send:
                pass

        stop_evt.set()
        recv_thread.join(timeout=2.0)

    def stop_rtp(self):
        self.rtp_run = False
        if self.rtp_sk:
            try:
                self.rtp_sk.close()
            except:
                pass

    def close(self):
        self.stop_rtp()
        if self.sk:
            try:
                self.sk.close()
            except:
                pass


# ============================================================================
#                     SIP CALL EXECUTION
# ============================================================================

def execute_sip_call(phone, sip_info, call_duration=CALL_DURATION):
    """
    Execute a SIP call directly from local IP.
    Returns: (result_str, duration_seconds, from_number, sip_debug)
    """
    call_start = time.time()
    sip_domain = sip_info.get('domain', '?')
    sip_port = sip_info.get('port', 5060)
    sip_user = sip_info.get('user', '?')[:10]

    sip = SIP(sip_info['user'], sip_info['pass'], sip_info['domain'],
              sip_info['port'], sip_info['proto'])
    sip._from_num = str(sip_info.get('from', '')).replace('+', '')

    # Connect
    if not sip.conn():
        return ('sip_conn_fail', 0, '', f'Cannot connect to {sip_domain}:{sip_port}')

    # REGISTER (without auth first)
    sip.register(auth=False)
    r = sip.recv(RECV_TIMEOUT)
    reg_ok = False
    if r:
        p = sip.parse(r)
        reg_code = p['code'] if p else 0
        if p and reg_code == 401:
            sip._pauth(p['headers'].get('www-authenticate', ''))
            sip.register(auth=True)
            r2 = sip.recv(RECV_TIMEOUT)
            if r2:
                p2 = sip.parse(r2)
                reg2_code = p2['code'] if p2 else 0
                if reg2_code == 200:
                    reg_ok = True
        elif reg_code == 200:
            reg_ok = True

    if not reg_ok:
        sip.close()
        return ('sip_reg_fail', time.time() - call_start, sip._from_num or '',
                'SIP registration failed')

    # INVITE (without auth first)
    num = phone.replace('+', '')
    sip.invite(num, auth=False)
    r = sip.recv(RECV_TIMEOUT)

    if not r:
        sip.close()
        return ('failed', time.time() - call_start, sip._from_num or '', 'INVITE no response')

    p = sip.parse(r)
    inv_code = p['code'] if p else 0

    if not p or inv_code != 401:
        if inv_code == 200:
            sip.remote_tag = p['to_tag']
            sdp_ip = p['sdp_ip']
            sdp_port = p['sdp_port']
            if sdp_ip and sdp_port:
                sip.ack(num)
                sip.close()
                return ('answered_ok', time.time() - call_start, sip._from_num or '', 'direct 200 OK')
        sip.close()
        return ('failed', time.time() - call_start, sip._from_num or '',
                f'INVITE unexpected {inv_code}')

    # INVITE with auth
    sip._pauth(p['headers'].get('www-authenticate', ''))
    sip.seq -= 1
    sip.invite(num, auth=True)

    # Wait for ringing / answer
    ringing_started = False
    call_answered = False
    sdp_ip = sdp_port = None
    last_sip_code = 0

    for i in range(RINGING_TIMEOUT):
        r = sip.recv(0.5)
        if r:
            p = sip.parse(r)
            code = p['code'] if p else 0
            last_sip_code = code

            if code == 100:
                pass  # Trying
            elif code == 180 or code == 183:
                ringing_started = True
            elif code == 200:
                call_answered = True
                sip.remote_tag = p['to_tag']
                sdp_ip = p['sdp_ip']
                sdp_port = p['sdp_port']

                if not sdp_ip or not sdp_port:
                    sip.close()
                    return ('failed', time.time() - call_start, sip._from_num or '', 'No SDP in 200 OK')

                sip.ack(num)

                # Check for instant BYE
                sip.sk.settimeout(0.2)
                instant_bye = False
                for _check in range(INSTANT_BYE_CHECKS):
                    try:
                        chk = sip.sk.recv(4096)
                        if chk:
                            chk_str = chk.decode('utf-8', errors='ignore')
                            if 'BYE ' in chk_str:
                                instant_bye = True
                                sip.ok(chk_str)
                                break
                    except:
                        pass

                if instant_bye:
                    sip.close()
                    return ('declined', time.time() - call_start, sip._from_num or '', 'Instant BYE')

                break

            elif code in (486, 487, 603):
                sip.close()
                return ('declined', time.time() - call_start, sip._from_num or '', f'SIP {code}')
            elif code == 404:
                sip.close()
                return ('not_found', time.time() - call_start, sip._from_num or '', 'SIP 404')
            elif code in (408, 480):
                sip.close()
                return ('no_answer', time.time() - call_start, sip._from_num or '', f'SIP {code}')
            elif code >= 400:
                sip.close()
                return (f'sip_{code}', time.time() - call_start, sip._from_num or '',
                        f'SIP error {code}')

    if not call_answered:
        sip.close()
        if ringing_started:
            return ('no_answer', time.time() - call_start, sip._from_num or '',
                    f'Ring timeout, last code={last_sip_code}')
        else:
            return ('failed', time.time() - call_start, sip._from_num or '',
                    f'No ringing, last code={last_sip_code}')

    # ===== Call was answered - Stay in call then hang up =====
    sip.rtp_ip = sdp_ip if sdp_ip else sip.d
    sip.rtp_pt = sdp_port if sdp_port else 5004

    # Determine how long to stay in call
    stay_duration = call_duration if call_duration > 0 else MAX_CALL_DURATION

    stop_evt = threading.Event()
    if sip.start_rtp():
        rt = threading.Thread(target=sip.rtp_loop, args=(stop_evt, stay_duration), daemon=True)
        rt.start()

    time.sleep(0.3)
    start_time = time.time()
    deadline = start_time + stay_duration
    call_ended = False

    sip.sk.settimeout(0.5)
    while time.time() < deadline:
        try:
            chk = sip.sk.recv(4096)
            if chk:
                chk_str = chk.decode('utf-8', errors='ignore')
                if 'BYE ' in chk_str:
                    first = chk_str.strip().split('\r\n')[0] if '\r\n' in chk_str else chk_str.strip().split('\n')[0]
                    if first.startswith('BYE ') or '\r\nBYE ' in chk_str or '\nBYE ' in chk_str:
                        sip.ok(chk_str)
                        call_ended = True
                        break
        except:
            pass

    actual_duration = time.time() - start_time
    stop_evt.set()
    sip.stop_rtp()

    if not call_ended:
        sip.bye(num)

    sip.close()

    result = 'answered_ok' if actual_duration >= 1 else 'answered_short'
    return (result, actual_duration, sip._from_num or '', f'duration={actual_duration:.1f}s')


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
#                       SERVER COMMUNICATION
# ============================================================================

def server_report_call(server_url, call_id, phone, email, result, duration, from_number, sip_debug=''):
    """Report a call result to the server for tracking."""
    if not REPORT_TO_SERVER or not server_url:
        return
    try:
        r = requests.post(f"{server_url}/call/report", json={
            'call_id': call_id,
            'phone': phone,
            'email': email,
            'result': result,
            'duration': round(duration, 1),
            'from_number': from_number,
            'sip_debug': sip_debug,
        }, timeout=5)
    except:
        pass  # Server reporting is optional


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
    print(clr(C.BWHITE, "     Fox Caller 1 - Direct SIP Caller"))
    print(clr(C.BCYAN, "  " + "=" * 55))
    print(clr(C.DIM, "     Direct SIP calls + Server tracking"))
    print(clr(C.BCYAN, "  " + "=" * 55))
    print()


def run(phones, server_url, num_workers, directory, call_duration):
    """Main loop: create accounts, pick numbers, make SIP calls directly."""
    global account_index, accounts

    total = len(phones)
    start_time = time.time()

    print()
    print(f"  {clr(C.BBLUE, 'Server:')} {server_url}")
    print(f"  {clr(C.BBLUE, 'Numbers:')} {total} | {clr(C.BBLUE, 'Workers:')} {num_workers}")
    print(f"  {clr(C.BBLUE, 'Cooldown:')} {CALL_COOLDOWN}s | {clr(C.BBLUE, 'Call Duration:')} {call_duration}s")
    print(f"  {clr(C.BBLUE, 'History:')} {HISTORY_FILE}")
    print()

    # Check server health
    health = server_health(server_url)
    if health:
        print(f"  {clr(C.BGREEN, 'Server OK!')} Active calls: {health.get('active_calls', '?')}")
    else:
        print(f"  {clr(C.YELLOW, 'Server unreachable - calls will still work locally')}")
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
                if is_number_available(phone, history):
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
        """Worker thread: picks number, gets account, makes SIP call directly."""
        while not stop_flag[0]:
            # Get next phone
            phone = get_next_phone()
            if phone is None:
                history = load_call_history(directory)
                all_unavailable = all(
                    not is_number_available(p, history)
                    for p in phones
                )
                if all_unavailable:
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

            print(f"  {clr(C.CYAN, f'[W{worker_id}] RING')} {phone} <- {email_short}")

            # Step 1: Get SIP credentials from Telicall API
            sip_info = telicall_start_call(phone, token, device_id)

            call_id = f"call_{uuid.uuid4().hex[:12]}"

            if sip_info is None:
                # API timeout
                with stats_lock:
                    stats["api_fail"] += 1
                    stats["total_calls"] += 1
                update_history_with_result(directory, phone, 'api_timeout', 0)
                print(f"  {clr(C.RED, f'[W{worker_id}] API_TIMEOUT')} {phone} <- {email_short}")
                _print_stats(start_time)
                continue

            if sip_info == 'no_balance':
                with stats_lock:
                    stats["no_balance"] += 1
                    stats["total_calls"] += 1
                used_emails.add(email)
                update_history_with_result(directory, phone, 'no_balance', 0)
                server_report_call(server_url, call_id, phone, email, 'no_balance', 0, '')
                print(f"  {clr(C.RED, f'[W{worker_id}] NO_BALANCE')} {phone} <- {email_short}")
                _print_stats(start_time)
                continue

            if isinstance(sip_info, dict) and 'error' in sip_info:
                err = sip_info['error']
                with stats_lock:
                    stats["failed"] += 1
                    stats["total_calls"] += 1
                update_history_with_result(directory, phone, err, 0)
                server_report_call(server_url, call_id, phone, email, err, 0, '')
                if err == 'call_403':
                    with c403_lock:
                        consecutive_403[0] += 1
                        if consecutive_403[0] >= MAX_CONSECUTIVE_403:
                            print(f"  {clr(C.BRED, f'{MAX_CONSECUTIVE_403}x API 403 - region blocked!')}")
                            stop_flag[0] = True
                            return
                print(f"  {clr(C.RED, f'[W{worker_id}] API_{err.upper()}')} {phone} <- {email_short}")
                _print_stats(start_time)
                continue

            # Step 2: Make SIP call directly from local IP
            update_history_with_call(directory, phone, call_id)
            with stats_lock:
                stats["active_calls"] += 1
                stats["total_calls"] += 1

            # Report to server that call is starting
            server_report_call(server_url, call_id, phone, email, 'calling', 0,
                             sip_info.get('from', ''))

            result, duration, from_num, sip_debug = execute_sip_call(phone, sip_info, call_duration)

            # Update history with result
            update_history_with_result(directory, phone, result, duration)

            # Report to server
            server_report_call(server_url, call_id, phone, email, result, duration, from_num, sip_debug)

            # Update stats
            with stats_lock:
                stats["active_calls"] -= 1
                if result in ('answered_ok', 'answered_short'):
                    stats["answered"] += 1
                    used_emails.add(email)
                elif result == 'no_answer':
                    stats["no_answer"] += 1
                elif result == 'declined':
                    stats["busy"] += 1
                elif result == 'not_found':
                    stats["not_found"] += 1
                elif result == 'no_balance':
                    stats["no_balance"] += 1
                    used_emails.add(email)
                elif result.startswith('sip_'):
                    stats["failed"] += 1
                else:
                    stats["failed"] += 1

            # Reset 403 counter on success
            if result in ('answered_ok', 'answered_short', 'no_answer', 'declined'):
                with c403_lock:
                    consecutive_403[0] = 0

            # Print result
            result_colors = {
                'answered_ok': C.BGREEN, 'answered_short': C.GREEN,
                'no_answer': C.YELLOW, 'declined': C.BYELLOW,
                'not_found': C.MAGENTA, 'no_balance': C.RED,
                'failed': C.RED, 'sip_conn_fail': C.BRED,
                'sip_reg_fail': C.BRED, 'api_timeout': C.RED,
            }
            c = result_colors.get(result, C.RED if result.startswith('sip_') else C.RED)
            dur_str = f"{duration:.1f}s" if duration else "?"
            from_str = f" <- {from_num}" if from_num else f" <- {email_short}"
            print(f"  {clr(c, f'[W{worker_id}] {result.upper()}')} {phone} ({dur_str}){from_str}")
            _print_stats(start_time)

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
    call_duration = CALL_DURATION

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
        elif arg == '--duration':
            if i + 1 < len(argv) and argv[i + 1].isdigit():
                call_duration = int(argv[i + 1])
                call_duration = max(0, min(call_duration, 600))
                i += 1
        elif arg == '--no-server':
            global REPORT_TO_SERVER
            REPORT_TO_SERVER = False
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
            print(f"  Usage: python3 fox_caller1.py <file.xlsx> [--server URL] [--workers N] [--duration N]")
            sys.exit(1)
    else:
        if not os.path.exists(selected_file):
            print(f"  {clr(C.BRED, 'File not found:')} {selected_file}")
            sys.exit(1)
        directory = os.path.dirname(selected_file)

    print(f"  {clr(C.BLUE, 'Server:')} {server_url}")
    print(f"  {clr(C.BLUE, 'Workers:')} {num_workers}")
    print(f"  {clr(C.BLUE, 'Duration:')} {call_duration}s")
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
    run(phones, server_url, num_workers, directory, call_duration)


if __name__ == "__main__":
    main()
