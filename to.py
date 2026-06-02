#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TelliCall Bulk Account Creator (to.py)
=======================================
Creates TelliCall accounts in parallel using temp-mail.org emails.
Supports IP rotation, account pooling, and encrypted Dan.json storage.

Fixed: Replaced mail.tm (wshu.net - BLOCKLISTED) with temp-mail.org
Working domains: ifcoat.com, doreact.com, googxs.com, hitzcart.com, matkind.com

Usage:
    python3 to.py
"""

import requests
import json
import uuid
import time
import random
import re
import string
import os
import hashlib
import base64
import threading
import queue
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from filelock import FileLock

# ─── Config ─────────────────────────────────────────
API_URL  = "https://api.telicall.com"
DAN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Dan.json")
PASSWORD = "@@@GMAQ@@@"

THREADS = 10
BATCH_SIZE = 10
EMAIL_POOL_SIZE   = 30
SESSION_POOL_SIZE = 20

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
    """بيولّد IP مصري عشوائي مختلف كل مرة"""
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

# ─── Temp-Mail.org Config ──────────────────────────────
WEB2_BASE_URL = "https://web2.temp-mail.org"
WEB2_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Origin': 'https://temp-mail.org',
    'Referer': 'https://temp-mail.org/',
    'Content-Type': 'application/json'
}

MOB2_BASE_URL = "https://mob2.temp-mail.org"
MOB2_HEADERS = {
    'Accept': 'application/json',
    'User-Agent': '3.49',
    'Accept-Encoding': 'gzip'
}

# ─── Domain Filtering ──────────────────────────────
WORKING_DOMAINS = {'ifcoat.com', 'doreact.com', 'googxs.com', 'hitzcart.com', 'matkind.com'}
BLOCKLISTED_DOMAINS = {'wshu.net', '4nly.com', 'alf5.com', 'mtupu.com'}

_mail_lock = threading.Lock()

_file_lock    = threading.Lock()
_counter_lock = threading.Lock()
_mem_lock     = threading.Lock()
_new_count    = 0
_stop_flag    = threading.Event()

_accounts_cache: list = None

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

# ─── البريد المؤقت — temp-mail.org ──────────────────────

def create_email_web2():
    """بيعمل ايميل على temp-mail.org (web2 API) مع فلترة الدومينات"""
    for attempt in range(5):
        try:
            with _mail_lock:
                r = requests.post(f"{WEB2_BASE_URL}/mailbox", headers=WEB2_HEADERS, timeout=15)

            if r.status_code in [200, 201]:
                data = r.json()
                email = data.get('mailbox')
                token = data.get('token')
                if email and token:
                    domain = email.split('@')[1] if '@' in email else ''
                    if domain in BLOCKLISTED_DOMAINS:
                        if attempt < 4:
                            time.sleep(1)
                            continue
                    return {
                        'email': email,
                        'token': token,
                        'api_type': 'web2',
                    }
            elif r.status_code == 429:
                wait = 10 * (attempt + 1)
                time.sleep(wait)
            else:
                time.sleep(2)
        except Exception as e:
            print(f"  ⚠️ web2 create error: {e}", flush=True)
            time.sleep(2)
    return None

def create_email_mob2():
    """بيعمل ايميل على temp-mail.org (mob2 API) كاحتياطي"""
    for attempt in range(3):
        try:
            r = requests.post(f"{MOB2_BASE_URL}/mailbox", headers=MOB2_HEADERS, timeout=10)
            if r.status_code == 200:
                data = r.json()
                email = data.get('mailbox')
                token = data.get('token')
                if email and token:
                    domain = email.split('@')[1] if '@' in email else ''
                    if domain in BLOCKLISTED_DOMAINS:
                        if attempt < 2:
                            time.sleep(1)
                            continue
                    return {
                        'email': email,
                        'token': token,
                        'api_type': 'mob2',
                    }
        except Exception as e:
            print(f"  ⚠️ mob2 create error: {e}", flush=True)
            time.sleep(2)
    return None

def create_email():
    """بيعمل ايميل مؤقت — بيجرب web2 الأول وبعدين mob2"""
    result = create_email_web2()
    if result:
        return result
    print("  ⚠️ web2 فشل، جاري تجربة mob2...", flush=True)
    return create_email_mob2()

def check_web2_inbox(email_token):
    """بيشيك inbox على temp-mail.org (web2) ويرجع الرسائل"""
    try:
        headers = WEB2_HEADERS.copy()
        headers['Authorization'] = f'Bearer {email_token}'
        r = requests.get(f'{WEB2_BASE_URL}/messages', headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            msgs = data if isinstance(data, list) else data.get('messages', [])
            return msgs
    except Exception as e:
        print(f"  ⚠️ web2 inbox: {e}", flush=True)
    return []

def check_mob2_inbox(email_token):
    """بيشيك inbox على temp-mail.org (mob2) ويرجع الرسائل"""
    try:
        headers = MOB2_HEADERS.copy()
        headers['Authorization'] = email_token
        r = requests.get(f'{MOB2_BASE_URL}/messages', headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data.get('messages', [])
    except Exception as e:
        print(f"  ⚠️ mob2 inbox: {e}", flush=True)
    return []

def get_otp(api_type, jwt):
    """بيستنى OTP من temp-mail.org"""
    deadline = time.time() + 90
    while time.time() < deadline:
        if _stop_flag.is_set():
            return None
        try:
            if api_type == 'web2':
                messages = check_web2_inbox(jwt)
            else:
                messages = check_mob2_inbox(jwt)

            for msg in messages:
                sender  = msg.get('from', '').lower()
                subject = msg.get('subject', '').lower()
                body    = msg.get('bodyPreview', msg.get('body', msg.get('textBody', '')))
                content = f"{sender} {subject} {body}".lower()
                if 'teli' in content or 'verification' in subject or 'verify' in subject or 'تحقق' in subject or 'رمز' in subject:
                    m = re.search(r'\b(\d{6})\b', str(body))
                    if m:
                        return m.group(1)
        except:
            pass
        time.sleep(3)
    return None

# ─── Email & Session Pools ──────────────────────────

_email_pool   = queue.Queue(maxsize=EMAIL_POOL_SIZE)
_session_pool = queue.Queue(maxsize=SESSION_POOL_SIZE)

def _email_pool_filler():
    while not _stop_flag.is_set():
        if _email_pool.qsize() < EMAIL_POOL_SIZE:
            mail = create_email()
            if mail:
                domain = mail['email'].split('@')[1] if '@' in mail['email'] else ''
                if domain in BLOCKLISTED_DOMAINS:
                    continue
                try:
                    _email_pool.put_nowait(mail)
                except queue.Full:
                    pass
        else:
            time.sleep(0.2)

def _session_pool_filler():
    while not _stop_flag.is_set():
        if _session_pool.qsize() < SESSION_POOL_SIZE:
            tok, device, headers = init_session()
            if tok:
                try:
                    _session_pool.put_nowait((tok, device, headers))
                except queue.Full:
                    pass
        else:
            time.sleep(0.2)

def get_email_from_pool() -> dict:
    try:
        mail = _email_pool.get(timeout=8)
        domain = mail['email'].split('@')[1] if '@' in mail['email'] else ''
        if domain in BLOCKLISTED_DOMAINS:
            return create_email()
        return mail
    except queue.Empty:
        return create_email()

def get_session_from_pool():
    try:
        return _session_pool.get(timeout=10)
    except queue.Empty:
        tok, device, headers = init_session()
        return (tok, device, headers) if tok else (None, None, None)

def start_pools():
    for _ in range(3):
        t = threading.Thread(target=_email_pool_filler, daemon=True)
        t.start()
    for _ in range(3):
        t = threading.Thread(target=_session_pool_filler, daemon=True)
        t.start()
    print("⏳ بيجهّز الـ pool...", flush=True)
    time.sleep(3)

# ─── TelliCall API ──────────────────────────────────

def init_session():
    """بيعمل session جديد مع IP مصري عشوائي"""
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
        r = requests.post(f"{API_URL}/init", json=body, headers=h,
                          timeout=10)
        if r.status_code == 200:
            tok = r.json().get('result', {}).get('token')
            if tok:
                h["x-token"] = tok
                return tok, device, h
        else:
            print(f"  ⚠️ init [{ip}]: {r.status_code}", flush=True)
    except Exception as e:
        print(f"  ⚠️ init [{ip}]: {e}", flush=True)
    return None, None, None

def send_verify(email, headers):
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
            print(f"  ⚠️ send_verify: {r.status_code} | {err}", flush=True)
    except Exception as e:
        print(f"  ⚠️ send_verify: {e}", flush=True)
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
        else:
            try:
                err = r.json().get('meta', {}).get('errorMessage', r.text[:80])
            except:
                err = r.text[:80]
            print(f"  ⚠️ verify_otp: {r.status_code} | {err}", flush=True)
    except Exception as e:
        print(f"  ⚠️ verify_otp: {e}", flush=True)
    return None

def create_one_account():
    tid = threading.current_thread().name

    # 1. إنشاء ايميل على temp-mail.org
    mail = get_email_from_pool()
    if not mail:
        print(f"[{tid}] ❌ فشل إنشاء البريد", flush=True)
        return False, "فشل البريد"

    email_addr = mail['email']
    domain = email_addr.split('@')[1] if '@' in email_addr else ''
    print(f"[{tid}] 📧 {email_addr} ({domain})", flush=True)

    # تحقق إن الدومين مش محظور
    if domain in BLOCKLISTED_DOMAINS:
        print(f"[{tid}] ⚠️ دومين محظور ({domain})، جاري المحاولة بدومين آخر...", flush=True)
        mail = create_email()
        if not mail:
            print(f"[{tid}] ❌ فشل إنشاء البريد البديل", flush=True)
            return False, "دومين محظور"
        email_addr = mail['email']
        domain = email_addr.split('@')[1] if '@' in email_addr else ''
        print(f"[{tid}] 📧 بديل: {email_addr} ({domain})", flush=True)

    # 2. عمل session جديد (IP مصري عشوائي)
    tok, device, headers = init_session()
    if not tok:
        print(f"[{tid}] 🚫 init_session فشل", flush=True)
        return False, "INIT_FAILED"
    print(f"[{tid}] 🔑 Session OK", flush=True)

    # 3. إرسال verification
    ref = send_verify(email_addr, headers)
    if not ref:
        print(f"[{tid}] 🚫 send_verify فشل", flush=True)
        return False, "VERIFY_FAILED"
    print(f"[{tid}] 📨 OTP أُرسل، ref={ref[:8]}...", flush=True)

    # 4. استنى OTP من temp-mail.org
    otp = get_otp(mail['api_type'], mail['token'])
    if not otp:
        print(f"[{tid}] ⏰ OTP timeout", flush=True)
        return False, "OTP timeout"
    print(f"[{tid}] 🔢 OTP: {otp}", flush=True)

    # 5. verify
    user = verify_otp_api(ref, otp, headers)
    if not user:
        print(f"[{tid}] ❌ verify فشل", flush=True)
        return False, "فشل التحقق"

    total = save_account(email_addr, device, tok)
    print(f"[{tid}] ✅ تم! الإجمالي: {total}", flush=True)
    return True, total

_burst_pool = ThreadPoolExecutor(max_workers=50)

def _do_burst():
    global _new_count
    futures = {_burst_pool.submit(create_one_account): i for i in range(5)}
    for f in as_completed(futures):
        ok, result = f.result()
        if ok:
            with _counter_lock:
                _new_count += 1
                n = _new_count
            print(f"⚡ burst #{n} | الإجمالي: {result}", flush=True)

def worker():
    global _new_count
    tid = threading.current_thread().name

    while not _stop_flag.is_set():
        batch_done = 0
        while batch_done < BATCH_SIZE and not _stop_flag.is_set():
            ok, result = create_one_account()

            if ok:
                with _counter_lock:
                    _new_count += 1
                    n = _new_count
                batch_done += 1
                print(f"✅ حساب #{n} | batch {batch_done}/{BATCH_SIZE} | الإجمالي: {result}", flush=True)

                print(f"[{tid}] 🔥 بيطلق 5 حسابات بالتوازي...", flush=True)
                _burst_pool.submit(_do_burst)

        if batch_done == BATCH_SIZE:
            print(f"[{tid}] 🎯 Batch مكتمل", flush=True)

def main():
    global _accounts_cache

    print("🌐 السكريبت بيشتغل على الـ IP بتاعك مباشرة بدون بروكسي", flush=True)
    print("🔄 بيلفّ على IPs مصرية عشوائية في x-real-ip", flush=True)
    print("📧 خدمة البريد: temp-mail.org (web2 + mob2)", flush=True)
    print(f"✅ الدومينات المسموحة: {', '.join(sorted(WORKING_DOMAINS))}", flush=True)
    print(f"🚫 الدومينات المحظورة: {', '.join(sorted(BLOCKLISTED_DOMAINS))}", flush=True)

    # نتأكد إن temp-mail.org شغال
    try:
        r = requests.post(f"{WEB2_BASE_URL}/mailbox", headers=WEB2_HEADERS, timeout=10)
        if r.status_code in [200, 201]:
            test_email = r.json().get('mailbox', '')
            test_domain = test_email.split('@')[1] if '@' in test_email else ''
            blocked = "🚫 محظور" if test_domain in BLOCKLISTED_DOMAINS else "✅ شغال"
            print(f"📬 temp-mail.org متاح (عينة: {test_email} - {blocked})", flush=True)
        else:
            print(f"⚠️  temp-mail.org مش متاح حالياً ({r.status_code})", flush=True)
    except:
        print("⚠️  temp-mail.org مش متاح حالياً", flush=True)

    existing = load_accounts()
    ex_count = len(existing)
    _accounts_cache = existing

    if ex_count > 0:
        print(f"📂 تم تحميل {ex_count} حساب موجود — سيتم الإضافة عليها", flush=True)

    print(f"🚀 تشغيل {THREADS} threads متوازية...", flush=True)

    start_pools()

    threads = []
    for _ in range(THREADS):
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        threads.append(t)

    try:
        while not _stop_flag.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        _stop_flag.set()

    for t in threads:
        t.join(timeout=5)

    total = len(_accounts_cache) if _accounts_cache else 0
    if _new_count > 0:
        print(f"\n✅ تم حفظ الملف: {DAN_FILE}")
        print(f"📊 الإجمالي الكلي: {total} حساب ({_new_count} جديد)")
    else:
        print("\n⚠️ محدش اتعمل — حاول تاني")

if __name__ == "__main__":
    main()
