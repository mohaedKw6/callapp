#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import json
import uuid
import time
import random
import re
import string
import os
import sys
import hashlib
import base64
import threading
import csv
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

# ─── Proxy Manager ────────────────────────────────────
PROXY_FILE      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alive_proxies.txt")
DEAD_PROXY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dead_proxies.txt")

_proxy_lock    = threading.Lock()
_dead_proxies  = set()
_dead_file_lock = threading.Lock()
_proxy_list    = []
_reload_warning_shown = False   # للتحكم في رسالة "كل البروكسيات ماتت"

def _save_dead_proxy(url: str):
    try:
        with _dead_file_lock:
            with open(DEAD_PROXY_FILE, "a", encoding="utf-8") as f:
                f.write(url + "\n")
    except Exception:
        pass

def _extract_host_port(proxy_url: str) -> str:
    """يرجع host:port من رابط كامل زي http://1.2.3.4:8080"""
    if '://' in proxy_url:
        return proxy_url.split('://', 1)[1]
    return proxy_url

def _remove_proxy_from_file(proxy_url: str):
    """يمسح البروكسي الميت من ملف alive_proxies.txt بالكامل"""
    if not os.path.exists(PROXY_FILE):
        return
    target = _extract_host_port(proxy_url)
    lock = FileLock(PROXY_FILE + ".lock", timeout=10)
    try:
        with lock:
            with open(PROXY_FILE, encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            # كمان مرة results عشان نقدر نمسح البروكسي بأي صيغة
            new_lines = []
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                # لو السطر هو نفسه البروكسي كامل (بأي بروتوكول) أو يحتوي على host:port
                if stripped == proxy_url or _extract_host_port(stripped) == target:
                    continue   # نحذف السطر
                # كمان لو السطر ip:port بدون بروتوكول
                if '://' not in stripped and stripped == target:
                    continue
                new_lines.append(line)
            with open(PROXY_FILE, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
    except Exception:
        pass

def _load_proxies_from_file() -> list:
    proxies = []
    if not os.path.exists(PROXY_FILE):
        print(f"⚠️  ملف البروكسيات مش موجود: {PROXY_FILE}", flush=True)
        return proxies
    try:
        with open(PROXY_FILE, encoding='utf-8', errors='ignore') as f:
            lines = [l.strip() for l in f.readlines()]

        non_empty = [l for l in lines if l]
        if not non_empty:
            return proxies

        PROTOCOLS = {'http', 'https', 'socks4', 'socks5'}
        first = non_empty[0]
        has_full_url   = any('://' in l for l in non_empty)
        has_proto_only = any(l.lower() in PROTOCOLS and '://' not in l for l in non_empty)
        is_csv         = ',' in first and '://' not in first and ':' not in first.split(',')[0]

        if is_csv:
            import io
            reader = csv.DictReader(io.StringIO('\n'.join(lines)))
            for row in reader:
                url = row.get('proxy', '').strip()
                if url and '://' in url:
                    proxies.append(url)

        elif has_proto_only:
            current_proto = 'http'
            for line in non_empty:
                l = line.lower()
                if l in PROTOCOLS:
                    current_proto = l
                elif ':' in line and '.' in line and '://' not in line:
                    proxies.append(f"{current_proto}://{line}")
                elif '://' in line:
                    proxies.append(line)

        elif has_full_url:
            for line in non_empty:
                if '://' in line:
                    proxies.append(line)

        else:
            for line in non_empty:
                if ':' in line and '.' in line:
                    proxies.append(f"http://{line}")

    except Exception as e:
        print(f"⚠️  خطأ في قراية ملف البروكسيات: {e}", flush=True)

    random.shuffle(proxies)
    return proxies

def init_proxy_manager():
    global _proxy_list, _reload_warning_shown
    _proxy_list = _load_proxies_from_file()
    _reload_warning_shown = False
    if _proxy_list:
        types = {}
        for p in _proxy_list:
            t = p.split('://')[0]
            types[t] = types.get(t, 0) + 1
        breakdown = ' | '.join(f"{k}={v}" for k,v in sorted(types.items()))
        print(f"🌐 تم تحميل {len(_proxy_list)} بروكسي ({breakdown})", flush=True)
    else:
        print("⚠️  مفيش بروكسيات — الاسكريبت هيشتغل بدون proxy", flush=True)

def _mark_dead(proxy_url: str):
    with _proxy_lock:
        if proxy_url in _dead_proxies:
            return
        _dead_proxies.add(proxy_url)
    _save_dead_proxy(proxy_url)
    _remove_proxy_from_file(proxy_url)   # 🔥 يمسحه من الملف الأصلي

def get_proxy() -> dict | None:
    if not _proxy_list:
        return None
    with _proxy_lock:
        alive = [p for p in _proxy_list if p not in _dead_proxies]
    if alive:
        return {"http": p, "https": p} if (p := random.choice(alive)) else None
    _reload_proxies()
    with _proxy_lock:
        alive = [p for p in _proxy_list if p not in _dead_proxies]
    if not alive:
        return None
    p = random.choice(alive)
    return {"http": p, "https": p}

def _reload_proxies():
    global _proxy_list, _dead_proxies, _reload_warning_shown
    fresh = _load_proxies_from_file()
    if not fresh:
        if not _reload_warning_shown:
            print("\n⛔ كل البروكسيات اللي في الملف ماتوا — أضف بروكسيات جديدة أو أعد تشغيل السكريبت", flush=True)
            _reload_warning_shown = True
        return
    with _proxy_lock:
        new_ones = [p for p in fresh if p not in _dead_proxies]
        added = len(new_ones)
        _proxy_list = list(set(_proxy_list) | set(fresh))
    if added:
        print(f"\n♻️  تم إعادة تحميل {added} proxy جديد من الملف", flush=True)
        _reload_warning_shown = False  # رجعنا لعادي
    else:
        if not _reload_warning_shown:
            print("\n⛔ كل البروكسيات اللي في الملف ماتوا — أضف بروكسيات جديدة أو أعد تشغيل السكريبت", flush=True)
            _reload_warning_shown = True

def get_proxy_and_mark_dead_on_fail(last_proxy_url: str | None) -> dict | None:
    if last_proxy_url:
        _mark_dead(last_proxy_url)
        with _proxy_lock:
            alive_count = len([p for p in _proxy_list if p not in _dead_proxies])
        if alive_count % 50 == 0:
            print(f"⚠️  بروكسيات حية متبقية: {alive_count}", flush=True)
    return get_proxy()

# ─── 45 دومين مؤقت — كلهم مجربين وشغالين مع temp-mail.io ─────────
DOMAINS = [
    # ── المجموعة الأصلية (13) ──
    "daouse.com", "bltiwd.com", "rommiui.com", "mrotzis.com",
    "mkzaso.com", "illubd.com", "wnbaldwy.com", "xkxkud.com",
    "yzcalo.com", "ozsaip.com", "bwmyga.com", "ruutukf.com", "inovic.com",
    # ── المجموعة الجديدة (32) ──
    "vmani.com", "dpptd.com", "moflix.com", "fanclub.com",
    "nqmo.com", "hostaldelrio.com", "sjgpne.com", "lfatj.com",
    "kzlcl.com", "vbaif.com", "yarbfi.com", "rcedem.com",
    "mkgt.com", "fexbox.org", "bheps.com", "lgbtq.page",
    "triots.com", "kalmlom.com", "khreb.com", "okhfb.com",
    "adrianou.com", "psnator.com", "rigle.com", "plonker.com",
    "9me1.com", "maulve.com", "txcct.com", "chitthuri.com",
    "digiway.com", "freps.click", "pirol.com", "retre.org",
]

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

# ─── البريد المؤقت ───────────────────────────────────
def create_mob2_mail():
    try:
        r = requests.post(
            "https://mob2.temp-mail.org/mailbox",
            headers={'Accept': 'application/json', 'User-Agent': '3.49', 'Accept-Encoding': 'gzip'},
            proxies=get_proxy(), timeout=6
        )
        if r.status_code == 200:
            d = r.json()
            if d.get('mailbox') and d.get('token'):
                return {'email': d['mailbox'], 'token': d['token'], 'api_type': 'mob2'}
    except: pass
    return None

def create_io_mail():
    domain = random.choice(DOMAINS)
    name   = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    try:
        r = requests.post(
            "https://api.internal.temp-mail.io/api/v3/email/new",
            json={"domain": domain, "name": name},
            headers={
                'Accept': 'application/json',
                'Application-Name': 'web',
                'Application-Version': '2.2.29',
                'Origin': 'https://temp-mail.io',
                'User-Agent': 'Mozilla/5.0'
            },
            proxies=get_proxy(), timeout=6
        )
        if r.status_code == 200:
            email = r.json().get('email')
            if email:
                return {'email': email, 'token': email, 'api_type': 'io'}
    except: pass
    return None

def create_email():
    result = [None]
    done   = threading.Event()

    def _try(fn):
        r = fn()
        if r and not done.is_set():
            done.set()
            result[0] = r

    threads = [threading.Thread(target=_try, args=(fn,)) for fn in [create_mob2_mail, create_io_mail]]
    for t in threads: t.start()
    done.wait(timeout=7)
    return result[0]

_email_pool   = queue.Queue(maxsize=EMAIL_POOL_SIZE)
_session_pool = queue.Queue(maxsize=SESSION_POOL_SIZE)

def _email_pool_filler():
    while not _stop_flag.is_set():
        if _email_pool.qsize() < EMAIL_POOL_SIZE:
            mail = create_email()
            if mail:
                try:
                    _email_pool.put_nowait(mail)
                except queue.Full:
                    pass
        else:
            time.sleep(0.2)

def _session_pool_filler():
    while not _stop_flag.is_set():
        if _session_pool.qsize() < SESSION_POOL_SIZE:
            proxy = get_proxy()
            tok, device, headers = init_session(proxy)
            if tok:
                try:
                    _session_pool.put_nowait((tok, device, headers, proxy))
                except queue.Full:
                    pass
        else:
            time.sleep(0.2)

def get_email_from_pool() -> dict:
    try:
        return _email_pool.get(timeout=8)
    except queue.Empty:
        return create_email()

def get_session_from_pool():
    try:
        return _session_pool.get(timeout=10)
    except queue.Empty:
        proxy = get_proxy()
        tok, device, headers = init_session(proxy)
        return (tok, device, headers, proxy) if tok else (None, None, None, proxy)

def start_pools():
    for _ in range(3):
        t = threading.Thread(target=_email_pool_filler, daemon=True)
        t.start()
    for _ in range(3):
        t = threading.Thread(target=_session_pool_filler, daemon=True)
        t.start()
    print("⏳ بيجهّز الـ pool...", flush=True)
    time.sleep(3)

def check_mob2_inbox(tkn):
    try:
        r = requests.get(
            "https://mob2.temp-mail.org/messages",
            headers={'Accept': 'application/json', 'User-Agent': '3.49', 'Authorization': tkn},
            proxies=get_proxy(), timeout=6
        )
        if r.status_code == 200:
            return r.json().get('messages', [])
    except: pass
    return []

def check_io_inbox(email):
    try:
        r = requests.get(
            f"https://api.internal.temp-mail.io/api/v3/email/{email}/messages",
            proxies=get_proxy(), timeout=6
        )
        if r.status_code == 200:
            return r.json()
    except: pass
    return []

def get_otp(api_type, token_or_email):
    deadline = time.time() + 60
    while time.time() < deadline:
        if _stop_flag.is_set():
            return None
        try:
            messages = check_mob2_inbox(token_or_email) if api_type == 'mob2' else check_io_inbox(token_or_email)
            for msg in messages:
                content = str(msg.get('text','') or msg.get('body','') or msg.get('content','') or msg)
                if 'teli' in content.lower():
                    m = re.search(r'\b(\d{6})\b', content)
                    if m:
                        return m.group(1)
        except: pass
        time.sleep(0.5)
    return None

def init_session(proxy_dict):
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
        "x-token": ""
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
                          proxies=proxy_dict, timeout=10)
        if r.status_code == 200:
            tok = r.json().get('result', {}).get('token')
            if tok:
                h["x-token"] = tok
                return tok, device, h
    except Exception:
        pass
    return None, None, None

def send_verify(email, headers, proxy_dict):
    try:
        headers["x-request-id"]    = str(uuid.uuid4())
        headers["x-req-timestamp"] = str(int(time.time() * 1000))
        r = requests.post(f"{API_URL}/auth/send-email", json={'email': email},
                          headers=headers, proxies=proxy_dict, timeout=10)
        if r.status_code == 200:
            return r.json().get('result', {}).get('reference')
    except Exception:
        pass
    return None

def verify_otp_api(ref, code, headers, proxy_dict):
    try:
        headers["x-request-id"]    = str(uuid.uuid4())
        headers["x-req-timestamp"] = str(int(time.time() * 1000))
        r = requests.post(f"{API_URL}/auth/verify-identity",
                          json={'reference': ref, 'code': str(code)},
                          headers=headers, proxies=proxy_dict, timeout=10)
        if r.status_code == 200:
            return r.json().get('result', {}).get('user')
    except: pass
    return None

def create_one_account(proxy_dict):
    tid = threading.current_thread().name

    mail_res    = [None]
    session_res = [None, None, None, None]

    def _get_mail():
        mail_res[0] = get_email_from_pool()

    def _get_session():
        tok, device, headers, prx = get_session_from_pool()
        session_res[0] = tok
        session_res[1] = device
        session_res[2] = headers
        session_res[3] = prx

    t1 = threading.Thread(target=_get_mail)
    t2 = threading.Thread(target=_get_session)
    t1.start(); t2.start()
    t1.join();  t2.join()

    mail = mail_res[0]
    tok, device, headers, sess_proxy = session_res

    active_proxy = sess_proxy or proxy_dict

    if not mail:
        print(f"[{tid}] ❌ فشل إنشاء البريد", flush=True)
        return False, "فشل البريد"
    print(f"[{tid}] 📧 {mail['email']}", flush=True)

    if not tok:
        print(f"[{tid}] 🚫 init_session فشل — الـ proxy اتحظر، بيغيّر...", flush=True)
        return False, "PROXY_DEAD"
    print(f"[{tid}] 🔑 Session OK", flush=True)

    ref = send_verify(mail['email'], headers, active_proxy)
    if not ref:
        print(f"[{tid}] 🚫 send_verify فشل — الـ proxy اتحظر، بيغيّر...", flush=True)
        if active_proxy:
            _mark_dead(list(active_proxy.values())[0])
        return False, "PROXY_DEAD"
    print(f"[{tid}] 📨 OTP أُرسل، ref={ref[:8]}...", flush=True)

    otp = get_otp(mail['api_type'], mail['token'])
    if not otp:
        print(f"[{tid}] ⏰ OTP timeout", flush=True)
        return False, "OTP timeout"
    print(f"[{tid}] 🔢 OTP: {otp}", flush=True)

    user = verify_otp_api(ref, otp, headers, active_proxy)
    if not user:
        print(f"[{tid}] ❌ verify فشل", flush=True)
        return False, "فشل التحقق"

    total = save_account(mail['email'], device, tok)
    return True, total

_burst_pool = ThreadPoolExecutor(max_workers=50)

def _do_burst(proxy_dict):
    global _new_count
    futures = {_burst_pool.submit(create_one_account, proxy_dict): i for i in range(5)}
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

    def _pick_proxy():
        p = get_proxy()
        if p:
            print(f"[{tid}] 🔄 Proxy جديد: {list(p.values())[0]}", flush=True)
        return p

    def _kill_proxy(proxy_dict):
        if not proxy_dict:
            return
        url = list(proxy_dict.values())[0]
        _mark_dead(url)
        with _proxy_lock:
            alive = len([p for p in _proxy_list if p not in _dead_proxies])
        print(f"[{tid}] 🪦 Proxy مات → اتمسح من الملف | متبقي: {alive}", flush=True)

    while not _stop_flag.is_set():
        current_proxy = _pick_proxy()
        if current_proxy is None:
            print(f"[{tid}] ⏳ مفيش proxy — بيستنى 5 ثواني...", flush=True)
            time.sleep(5)
            continue

        batch_done = 0
        while batch_done < BATCH_SIZE and not _stop_flag.is_set():
            ok, result = create_one_account(current_proxy)

            if ok:
                with _counter_lock:
                    _new_count += 1
                    n = _new_count
                batch_done += 1
                print(f"✅ حساب #{n} | batch {batch_done}/{BATCH_SIZE} | الإجمالي: {result}", flush=True)

                print(f"[{tid}] 🔥 بيطلق 5 حسابات بالتوازي...", flush=True)
                _burst_pool.submit(_do_burst, current_proxy)

            elif result == "PROXY_DEAD":
                _kill_proxy(current_proxy)
                current_proxy = None
                break

        if batch_done == BATCH_SIZE:
            print(f"[{tid}] 🎯 Batch مكتمل — بيغيّر الـ proxy...", flush=True)

def main():
    global _accounts_cache

    init_proxy_manager()

    existing = load_accounts()
    ex_count = len(existing)
    _accounts_cache = existing

    if ex_count > 0:
        print(f"📂 تم تحميل {ex_count} حساب موجود — سيتم الإضافة عليها", flush=True)

    print(f"🌐 {len(DOMAINS)} دومين مؤقت متاح")
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
        print("\n⚠️ برجاء تغيير الـ IP — افتح VPN")

if __name__ == "__main__":
    main()
