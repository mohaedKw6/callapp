#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fox Caller v10.2 - Gmail Tricks Edition
=========================================
Email provider: Gmail dots trick + Gmail plus trick + IMAP
  -> Telicall accepts @gmail.com
  -> Gmail dots: user@gmail.com = u.ser@gmail.com = u.s.e.r@gmail.com
  -> Gmail plus: user+tag1@gmail.com = user+tag2@gmail.com
  -> Telicall sees each variation as a DIFFERENT account
  -> All OTPs arrive at the SAME Gmail inbox
  -> IMAP reads OTP automatically (App Password required once)
  -> Old Telicall emails are deleted at startup to avoid OTP confusion

Mode:
  --mode server   = create account + upload to server + server makes SIP call
  --mode create   = create accounts only (no calls)

Usage:
  python3 fox_caller11.py numbers.xlsx
  python3 fox_caller11.py numbers.xlsx --mode server --threads 5
  python3 fox_caller11.py numbers.xlsx --mode create --threads 10

First run: script asks for Gmail + App Password, saves to fox_config.json
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
import imaplib
import email as email_mod
from datetime import datetime
from email.header import decode_header
from urllib.parse import unquote
from filelock import FileLock

# ═══════════════════════════════════════════════════════════════
# ─── Config ───────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
API_URL       = "https://api.telicall.com"
SERVER_URL    = "https://callapp-production-c84c.up.railway.app"
ADMIN_KEY     = "06d271200e53fb4482acd8679bfe358a"
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DAN_FILE      = os.path.join(BASE_DIR, "Dan.json")
CONFIG_FILE   = os.path.join(BASE_DIR, "fox_config.json")
PASSWORD      = "@@@GMAQ@@@"
DEFAULT_DURATION = 64
DEFAULT_THREADS   = 3
SESSION_POOL_SIZE = 5
MAX_RETRIES       = 8
OTP_TIMEOUT       = 90
OTP_POLL_INTERVAL = 3

# ═══════════════════════════════════════════════════════════════
# ─── Gmail Config (credentials) ──────────────────────────────
# ═══════════════════════════════════════════════════════════════
_gmail_addr      = ""
_gmail_app_pass  = ""

def _is_valid_app_password(pwd):
    """Check if password looks like a Google App Password (16 lowercase letters)."""
    clean = pwd.replace(' ', '')  # Remove spaces (Google shows it with spaces)
    return len(clean) == 16 and clean.isalpha() and clean.islower()

def load_or_ask_gmail():
    """Load Gmail credentials from config file, or ask once and save."""
    global _gmail_addr, _gmail_app_pass

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            _gmail_addr = cfg.get("gmail", "").strip()
            _gmail_app_pass = cfg.get("app_password", "").strip()
            if _gmail_addr and _gmail_app_pass and '@' in _gmail_addr:
                print(f"  Gmail:      {_gmail_addr} (saved)", flush=True)
                # Warn if App Password format is wrong
                if not _is_valid_app_password(_gmail_app_pass):
                    print(f"  ⚠️  App Password مش شكله صح! لازم يكون 16 حرف صغير (بدون أرقام)", flush=True)
                    print(f"     الباسورد الحالي: {'*'*len(_gmail_app_pass)} ({len(_gmail_app_pass)} حرف)", flush=True)
                    print(f"     App Password شكله: xkrm yqwa bnzp drtf (16 حرف صغير)", flush=True)
                    print(f"     اعمل App Password من: https://myaccount.google.com/apppasswords", flush=True)
                    # Ask again
                    new_pass = input("  App Password الصحيح (أو Enter عشان تمشي): ").strip()
                    if new_pass:
                        _gmail_app_pass = new_pass.replace(' ', '')
                        # Save updated config
                        try:
                            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                                json.dump({"gmail": _gmail_addr, "app_password": _gmail_app_pass}, f, indent=2)
                        except Exception:
                            pass
                return
        except Exception:
            pass

    print(f"\n  {'─'*50}", flush=True)
    print(f"  إعداد Gmail (مرة واحدة فقط)", flush=True)
    print(f"  {'─'*50}", flush=True)
    print(f"  ⚠️  App Password مش الباسورد العادي!", flush=True)
    print(f"     اعمل واحد من: https://myaccount.google.com/apppasswords", flush=True)
    print(f"     شكله: xkrm yqwa bnzp drtf (16 حرف صغير)", flush=True)
    print(f"  {'─'*50}", flush=True)
    _gmail_addr = input("  Gmail address : ").strip()
    _gmail_app_pass = input("  App Password  : ").strip()

    # Remove spaces from App Password
    _gmail_app_pass = _gmail_app_pass.replace(' ', '')

    if not _gmail_addr or not _gmail_app_pass:
        print("  ERROR: يجب إدخال Gmail و App Password!", flush=True)
        sys.exit(1)

    if '@' not in _gmail_addr:
        _gmail_addr += '@gmail.com'

    # Validate App Password format
    if not _is_valid_app_password(_gmail_app_pass):
        print(f"\n  ❌ الباسورد اللي دخلت مش App Password!", flush=True)
        print(f"     الباسورد بتاعك: {'*'*len(_gmail_app_pass)} ({len(_gmail_app_pass)} حرف)", flush=True)
        print(f"     App Password لازم يكون: 16 حرف صغير بس (بدون أرقام)", flush=True)
        print(f"     مثال: xkrmyqwabnzpdrtf", flush=True)
        print(f"     اعمل واحد من: https://myaccount.google.com/apppasswords", flush=True)
        print(f"\n     1) روح https://myaccount.google.com/security", flush=True)
        print(f"     2) فعّل 2-Step Verification", flush=True)
        print(f"     3) روح https://myaccount.google.com/apppasswords", flush=True)
        print(f"     4) اعمل App Password جديد", flush=True)
        print(f"     5) انسخ الكود الـ 16 حرف", flush=True)

        retry = input("\n  حابب تدخل App Password صحيح؟ (y/n): ").strip().lower()
        if retry == 'y':
            _gmail_app_pass = input("  App Password  : ").strip().replace(' ', '')
            if not _is_valid_app_password(_gmail_app_pass):
                print("  ⚠️  لسه مش شكل App Password، بس هنحاول...")
        else:
            print("  ⚠️  هنكمل بس هيفشل IMAP", flush=True)

    # Save to config
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({"gmail": _gmail_addr, "app_password": _gmail_app_pass}, f, indent=2)
        print(f"  ✅ تم الحفظ في {CONFIG_FILE}", flush=True)
    except Exception as e:
        print(f"  ⚠️ لم أستطع حفظ الإعدادات: {e}", flush=True)


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
# ─── Gmail Variation Generator ───────────────────────────────
# ═══════════════════════════════════════════════════════════════
class GmailVariationGenerator:
    """
    Generates unlimited unique Gmail variations using:
      1. Dots trick: user@gmail.com -> u.ser@gmail.com -> u.s.e.r@gmail.com ...
      2. Plus trick: user+tag@gmail.com -> user+tag2@gmail.com ...
      3. Dots + Plus: u.ser+tag@gmail.com -> u.s.er+tag2@gmail.com ...

    Gmail ignores dots in addresses, so all dot variations deliver
    to the same inbox. Telicall treats each variation as a different account.
    """

    def __init__(self, base_email):
        self.base_email = base_email.lower().strip()
        parts = self.base_email.split('@')
        self.domain = parts[1] if len(parts) == 2 else 'gmail.com'

        # Remove existing dots from username (Gmail ignores them)
        raw_username = parts[0]
        self.clean_username = raw_username.replace('.', '')

        self._lock = threading.Lock()
        self._dot_variations = self._generate_dot_variations()
        self._dot_index = 0
        self._plus_counter = 0
        self._dot_phase = True  # True = using dot variations, False = using plus

    def _generate_dot_variations(self):
        """Generate all possible dot placements in the username."""
        n = len(self.clean_username)
        if n <= 1:
            return [self.clean_username]

        variations = []
        # mask represents which positions have dots
        # positions are between characters: c[0] . c[1] . c[2] ...
        # there are (n-1) possible dot positions
        for mask in range(1, 2 ** (n - 1)):
            result = self.clean_username[0]
            for i in range(1, n):
                if mask & (1 << (i - 1)):
                    result += '.' + self.clean_username[i]
                else:
                    result += self.clean_username[i]
            variations.append(result)

        # Also include the original (no dots) as the last resort
        variations.append(self.clean_username)

        # Shuffle for randomness
        random.shuffle(variations)
        return variations

    def next_variation(self):
        """Get next unique email variation (thread-safe)."""
        with self._lock:
            if self._dot_index < len(self._dot_variations):
                v = self._dot_variations[self._dot_index]
                self._dot_index += 1
                return f"{v}@{self.domain}"

            # Dot variations exhausted -> use plus trick with dots
            self._plus_counter += 1
            tag = f"fx{self._plus_counter}"

            # Pick a random dot variation to combine with plus
            dot_base = random.choice(self._dot_variations)
            return f"{dot_base}+{tag}@{self.domain}"

    @property
    def total_dot_variations(self):
        return len(self._dot_variations)

    @property
    def used_count(self):
        with self._lock:
            return self._dot_index + self._plus_counter


# ═══════════════════════════════════════════════════════════════
# ─── IMAP OTP Reader ─────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
_imap_lock = threading.Lock()  # Serialize IMAP access across workers

def _decode_str(s):
    """Decode email header string."""
    if s is None:
        return ""
    decoded_parts = decode_header(s)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            try:
                result.append(part.decode(charset or 'utf-8', errors='ignore'))
            except Exception:
                result.append(part.decode('utf-8', errors='ignore'))
        else:
            result.append(str(part))
    return ''.join(result)

def _get_email_body(msg):
    """Extract text body from an email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct in ('text/plain', 'text/html'):
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or 'utf-8'
                        body += payload.decode(charset, errors='ignore')
                except Exception:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or 'utf-8'
                body = payload.decode(charset, errors='ignore')
        except Exception:
            pass
    return body

def _extract_otp_from_text(text):
    """Extract 6-digit OTP from text."""
    # Clean HTML tags
    clean = re.sub(r'<[^>]+>', ' ', text)
    m = re.search(r'\b(\d{6})\b', clean)
    if m:
        return m.group(1)
    return None

# Track OTPs we already used to avoid reading old ones
_used_otps = set()
_used_otps_lock = threading.Lock()

def imap_read_otp(target_variation, timeout=OTP_TIMEOUT, sent_time=None):
    """
    Read OTP from Gmail via IMAP — only reads emails that arrived AFTER sent_time.
    - target_variation: the email we sent to Telicall (e.g., u.ser+fx1@gmail.com)
    - sent_time: timestamp before we called send_verify (to ignore old emails)
    - Returns the 6-digit OTP code or None on timeout
    """
    if sent_time is None:
        sent_time = time.time()

    deadline = time.time() + timeout
    # Track UIDs we already checked in this call
    checked_uids = set()

    while time.time() < deadline:
        if _stop_flag.is_set():
            return None

        with _imap_lock:
            try:
                mail = imaplib.IMAP4_SSL('imap.gmail.com', 993)
                mail.login(_gmail_addr, _gmail_app_pass)
                mail.select('INBOX')

                # Search for emails from Telicall that arrived recently
                # Use SINCE to limit to today's emails only
                today = datetime.now().strftime('%d-%b-%Y')
                search_criteria = f'(FROM "telicall" SINCE {today})'
                status, data = mail.uid('search', None, search_criteria)

                # Fallback: if no results with FROM filter, try broader search
                if status != 'OK' or not data[0]:
                    search_criteria = f'(SINCE {today})'
                    status, data = mail.uid('search', None, search_criteria)

                if status == 'OK' and data[0]:
                    all_uids = data[0].split()
                    # Only check UIDs we haven't looked at yet in this call
                    new_uids = [u for u in all_uids if u not in checked_uids]

                    # Check new emails (most recent first)
                    for uid in reversed(new_uids):
                        checked_uids.add(uid)

                        # Fetch only headers first (faster)
                        status, header_data = mail.uid('fetch', uid, '(BODY[HEADER.FIELDS (DATE FROM TO DELIVERED-TO X-ORIGINAL-TO SUBJECT)])')
                        if status != 'OK' or not header_data or not header_data[0]:
                            continue

                        header_text = header_data[0][1].decode('utf-8', errors='ignore').lower()

                        # Quick check: does this email contain "teli" or "verif" or "code"?
                        if not any(kw in header_text for kw in ['teli', 'verif', 'code', 'otp']):
                            continue

                        # Check email date to ensure it arrived AFTER we sent verification
                        date_str = ''
                        for line in header_text.split('\n'):
                            if line.startswith('date:'):
                                date_str = line.replace('date:', '', 1).strip()
                                break

                        if date_str:
                            try:
                                from email.utils import parsedate_to_datetime
                                email_time = parsedate_to_datetime(date_str)
                                email_ts = email_time.timestamp()
                                # Only accept emails that arrived after we sent the verification
                                # Allow 60 second buffer for clock skew
                                if email_ts < (sent_time - 60):
                                    continue
                            except Exception:
                                pass  # If we can't parse the date, still check it

                        # Now fetch full message to get OTP
                        status, msg_data = mail.uid('fetch', uid, '(RFC822)')
                        if status != 'OK':
                            continue

                        raw = msg_data[0][1]
                        msg = email_mod.message_from_bytes(raw)

                        body = _get_email_body(msg)
                        otp = _extract_otp_from_text(body)

                        if otp:
                            # Check if we already used this OTP (avoid duplicates)
                            with _used_otps_lock:
                                if otp in _used_otps:
                                    continue
                                _used_otps.add(otp)

                            # Mark as read and delete
                            try:
                                mail.uid('store', uid, '+FLAGS', '\\Seen')
                                mail.uid('store', uid, '+FLAGS', '\\Deleted')
                            except Exception:
                                pass

                            # Expunge deleted messages
                            try:
                                mail.expunge()
                            except Exception:
                                pass

                            mail.logout()
                            return otp

                mail.logout()
            except imaplib.IMAP4.error as e:
                err_str = str(e).lower()
                if 'auth' in err_str or 'login' in err_str or 'credential' in err_str:
                    print(f"  ❌ IMAP auth error! Check App Password", flush=True)
                    return None
            except Exception:
                pass

        time.sleep(OTP_POLL_INTERVAL)

    return None

def test_imap_connection():
    """Test IMAP connection at startup. Returns True if successful."""
    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com', 993)
        mail.login(_gmail_addr, _gmail_app_pass)
        mail.select('INBOX')
        status, data = mail.search(None, 'ALL')
        count = len(data[0].split()) if data[0] else 0

        # Delete ALL old Telicall verification emails to prevent OTP confusion
        deleted = 0
        if count > 0:
            all_uids = data[0].split()
            for uid in all_uids:
                try:
                    # Fetch only subject to check if it's from Telicall
                    status, header_data = mail.fetch(uid, '(BODY[HEADER.FIELDS (FROM SUBJECT)])')
                    if status == 'OK' and header_data and header_data[0]:
                        header_text = header_data[0][1].decode('utf-8', errors='ignore').lower()
                        if 'teli' in header_text or 'verif' in header_text:
                            mail.store(uid, '+FLAGS', '\\Deleted')
                            deleted += 1
                except Exception:
                    pass
            if deleted > 0:
                try:
                    mail.expunge()
                except Exception:
                    pass

        mail.logout()
        if deleted > 0:
            print(f"  IMAP:       🗑️ Deleted {deleted} old Telicall emails", flush=True)
        return True, count
    except imaplib.IMAP4.error as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)


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
    print(f"  Pool:       جلسات={_session_pool.qsize()}", flush=True)


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
                    return None, f'BLOCKED'
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
            except:
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
    "variations_used": 0,
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
                        print(f"[{tid}] ✅ Call OK {phone} ({dur}s) <- {caller}", flush=True)
                        update_stat("calls_ok")
                    elif s in ("failed", "error"):
                        err = status_data.get("error", "")
                        if "balance" in str(err).lower():
                            print(f"[{tid}] ❌ NO_BALANCE {phone}", flush=True)
                            update_stat("calls_no_balance")
                        else:
                            print(f"[{tid}] ❌ Call failed {phone} ({err})", flush=True)
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
# ─── Worker: Create Account + Call (with retry) ─────────────
# ═══════════════════════════════════════════════════════════════
_variation_gen = None  # GmailVariationGenerator instance

def _try_one_phone(phone, duration, mode, tid):
    """
    One attempt for a phone number. Returns:
    'ok'            = account created + call triggered
    'no_balance'    = account created but no balance for call
    'domain_blocked'= domain blocked
    'email_exists'  = email already registered
    'retry'         = transient error, can retry
    'fail'          = permanent failure
    """
    # Step 1: Get next email variation
    email_addr = _variation_gen.next_variation()
    email_short = email_addr.split('@')[0][:15]
    update_stat("variations_used")

    print(f"[{tid}] 📧 {email_short}...@gmail.com -> {phone}", flush=True)

    # Step 2: Get Session
    tok, device, headers, sess_proxy = get_session_from_pool()
    active_proxy = sess_proxy or get_proxy()

    if not tok:
        print(f"[{tid}] ❌ Session failed {phone}", flush=True)
        update_stat("session_fail")
        return 'retry'

    # Step 3: Send Verification (record time BEFORE sending)
    sent_time = time.time()
    ref, err = send_verify(email_addr, headers, active_proxy)
    if not ref:
        err_str = str(err or "")
        if err_str == 'EMAIL_EXISTS':
            print(f"[{tid}] ⚠️ Email exists {email_short}... - trying another", flush=True)
            update_stat("email_exists")
            return 'email_exists'
        elif 'BLOCKED' in err_str:
            print(f"[{tid}] ❌ Gmail blocked by Telicall?! {phone}", flush=True)
            update_stat("domain_blocked")
            return 'domain_blocked'
        else:
            print(f"[{tid}] ❌ Verify send failed {phone} ({err_str[:50]})", flush=True)
            update_stat("verify_fail")
        if active_proxy:
            active_proxy = get_proxy_and_mark_dead(active_proxy)
        return 'retry'

    print(f"[{tid}] 📨 OTP sent -> {email_short}...", flush=True)

    # Step 4: Get OTP via IMAP (only emails after sent_time)
    otp = imap_read_otp(email_addr, timeout=OTP_TIMEOUT, sent_time=sent_time)
    if not otp:
        print(f"[{tid}] ❌ OTP timeout {phone} <- {email_short}", flush=True)
        update_stat("otp_fail")
        return 'retry'

    print(f"[{tid}] 🔢 OTP:{otp} {email_short}", flush=True)

    # Step 5: Verify OTP
    time.sleep(1)
    user, verify_err = verify_otp_api(ref, otp, headers, active_proxy)
    if not user:
        if verify_err == 'email_exists':
            print(f"[{tid}] ⚠️ Email exists (OTP step) {email_short}... - trying another", flush=True)
            update_stat("email_exists")
            return 'email_exists'
        elif verify_err == 'expired':
            print(f"[{tid}] ❌ OTP expired/wrong {phone}", flush=True)
            update_stat("confirm_fail")
            return 'retry'
        else:
            print(f"[{tid}] ❌ Confirm failed {phone} ({verify_err})", flush=True)
            update_stat("confirm_fail")
            return 'retry'

    # Step 6: Save Account
    total = save_account(email_addr, device, tok)
    print(f"[{tid}] ✅ Account! {email_short} (#{total})", flush=True)

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
        print(f"[{tid}] 📞 Call! {phone} (ready:{ready}, id:{str(call_id)[:10]}...)", flush=True)
        return 'ok'

    # Fallback: make-call (blocking)
    result = trigger_make_call(phone, duration)
    status = result.get("status", "unknown")
    from_num = result.get("from", result.get("from_number", "?"))
    dur = result.get("duration", result.get("actual_duration", 0))
    error = result.get("error", "")

    if status == "answered_ok":
        print(f"[{tid}] ✅ Call OK {phone} ({dur}s) <- {from_num}", flush=True)
        update_stat("calls_ok")
        return 'ok'
    elif "balance" in str(error).lower() or status == "no_balance":
        print(f"[{tid}] ⚠️ NO_BALANCE {phone}", flush=True)
        update_stat("calls_no_balance")
        update_stat("accounts_no_bal")
        return 'no_balance'
    else:
        print(f"[{tid}] ❌ Call failed {phone} ({error or status})", flush=True)
        update_stat("calls_failed")
        update_stat("accounts_ok")
        return 'no_balance'

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
                print(f"[{tid}] 🔄 Retry {attempt}/{MAX_RETRIES} for {phone}", flush=True)
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
                continue  # try with a different email variation
            elif result == 'retry':
                continue
            else:
                break

        if not success:
            add_failed_phone(phone, last_result or 'unknown')
            print(f"[{tid}] ❌ Final fail {phone} after {MAX_RETRIES} attempts ({last_result})", flush=True)

        time.sleep(0.3)


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
        var_used = _variation_gen.used_count if _variation_gen else 0
        var_total = _variation_gen.total_dot_variations if _variation_gen else 0
        print(f"\n  📊 Stats ({elapsed/60:.1f}min | {rate:.1f}/min):", flush=True)
        print(f"     Total: {s['total']} | ✅ Accounts: {s['accounts_ok']} | 📞 Calls OK: {s['calls_ok']}", flush=True)
        print(f"     ❌ Errors: email={s['email_fail']} session={s['session_fail']} "
              f"verify={s['verify_fail']} OTP={s['otp_fail']} confirm={s['confirm_fail']}", flush=True)
        print(f"     Email exists: {s['email_exists']} | NO_BALANCE: {s['calls_no_balance']} | "
              f"Retries: {s['retries']} | Variations: {var_used}/{var_total}+∞", flush=True)
        print(f"     Failed phones: {len(_failed_phones)}", flush=True)


# ═══════════════════════════════════════════════════════════════
# ─── Main ─────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def main():
    global _start_time, _phone_queue, _variation_gen

    parser = argparse.ArgumentParser(description="Fox Caller v10.0 - Gmail Tricks Edition")
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

    args = parser.parse_args()

    print("\n" + "=" * 60, flush=True)
    print("  Fox Caller v10.2 - Gmail Tricks Edition", flush=True)
    print("  Gmail dots trick + plus trick + IMAP OTP", flush=True)
    print("=" * 60, flush=True)

    # 1. Gmail credentials
    load_or_ask_gmail()

    # 2. Initialize Gmail variation generator
    _variation_gen = GmailVariationGenerator(_gmail_addr)
    print(f"  Gmail:      {_gmail_addr}", flush=True)
    print(f"  Dots:       {_variation_gen.total_dot_variations} variations + unlimited plus", flush=True)

    # 3. Test IMAP connection
    print(f"\n  🔍 Testing IMAP connection...", flush=True)
    imap_ok, imap_info = test_imap_connection()
    if imap_ok:
        print(f"  ✅ IMAP connected! Inbox: {imap_info} messages", flush=True)
    else:
        print(f"  ❌ IMAP failed: {imap_info}", flush=True)
        print(f"     تأكد من Gmail و App Password!", flush=True)
        sys.exit(1)

    # 4. Read numbers
    numbers = read_numbers(args.file)
    if not numbers:
        print("ERROR: No numbers in file!", flush=True)
        sys.exit(1)

    if args.limit > 0:
        numbers = numbers[:args.limit]

    _phone_queue = numbers
    _start_time = time.time()

    print(f"\n  Numbers:    {len(numbers)}", flush=True)
    print(f"  Mode:       {args.mode}", flush=True)
    print(f"  Threads:    {args.threads}", flush=True)
    print(f"  Duration:   {args.duration}s", flush=True)
    print(f"  Retries:    {MAX_RETRIES} per number", flush=True)

    # 5. Init proxy manager
    init_proxy_manager()

    # 6. Check server
    if args.mode == "server":
        if is_server_available():
            print(f"  Server:     ✅ Available ({SERVER_URL})", flush=True)
        else:
            print(f"  Server:     ⚠️ Unavailable! Switching to create mode", flush=True)
            args.mode = "create"

    # 7. Start pools
    start_pools()

    # 8. Quick test - create one Telicall session
    print(f"\n  🔍 Quick Test: Creating Telicall session...", flush=True)
    test_tok, test_dev, _ = init_session(get_proxy())
    if test_tok:
        print(f"  ✅ Session created! Token: {test_tok[:15]}...", flush=True)
    else:
        print(f"  ⚠️ Session creation failed! Will retry during operation...", flush=True)

    print(f"\n  🚀 Starting...", flush=True)
    print("-" * 60, flush=True)

    # 9. Start stats printer
    stats_thread = threading.Thread(target=print_stats, daemon=True)
    stats_thread.start()

    # 10. Start call monitor (server mode)
    if args.mode == "server":
        monitor_thread = threading.Thread(target=monitor_calls, daemon=True)
        monitor_thread.start()

    # 11. Start worker threads
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
    var_used = _variation_gen.used_count if _variation_gen else 0

    print("\n" + "=" * 60, flush=True)
    print("  📊 Final Report", flush=True)
    print("=" * 60, flush=True)
    print(f"  ⏱️  Time: {elapsed/60:.1f} minutes", flush=True)
    print(f"  📞 Total numbers: {s['total']}", flush=True)
    print(f"  ✅ New accounts: {s['accounts_ok']}", flush=True)
    print(f"  📞 Successful calls: {s['calls_ok']}", flush=True)
    print(f"  ⚠️  NO_BALANCE: {s['calls_no_balance']}", flush=True)
    print(f"  ❌ Final failures: {len(_failed_phones)}", flush=True)
    print(f"  🔄 Retries: {s['retries']}", flush=True)
    print(f"  📧 Gmail variations used: {var_used}", flush=True)
    print(f"\n  ❌ Error breakdown:", flush=True)
    print(f"     Email fail: {s['email_fail']}", flush=True)
    print(f"     Session fail: {s['session_fail']}", flush=True)
    print(f"     Verify send fail: {s['verify_fail']}", flush=True)
    print(f"     OTP fail: {s['otp_fail']}", flush=True)
    print(f"     Confirm fail: {s['confirm_fail']}", flush=True)
    print(f"     Domain blocked: {s['domain_blocked']}", flush=True)
    print(f"     Email exists: {s['email_exists']}", flush=True)

    if _failed_phones:
        print(f"\n  ❌ Failed numbers ({len(_failed_phones)}):", flush=True)
        for fp in _failed_phones[:20]:
            print(f"     {fp['phone']} ({fp['reason']})", flush=True)
        if len(_failed_phones) > 20:
            print(f"     ... and {len(_failed_phones) - 20} more", flush=True)

    code_errors = s['email_fail'] + s['session_fail'] + s['verify_fail'] + s['otp_fail'] + s['confirm_fail'] + s['domain_blocked']
    if code_errors == 0 and s['email_exists'] > 0:
        print(f"\n  ✅ No code errors! ({s['email_exists']} emails existed - auto-replaced)", flush=True)
    elif code_errors == 0:
        print(f"\n  🎉 Zero errors! Everything working perfectly!", flush=True)
    else:
        print(f"\n  ⚠️  {code_errors} errors need fixing", flush=True)

    print("=" * 60, flush=True)

    # Stop pools
    _stop_flag.set()


if __name__ == "__main__":
    main()
