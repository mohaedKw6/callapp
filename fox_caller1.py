#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fox Caller v13.0 - Openlo + SandVPN Edition
=============================================
مزودين إيميل بس:
  1. SandVPN (@flyymail.com/@nobinbox.com/@tempyx.com) — REST API بسيط، إيميلات فريدة
  2. tempail.top (@openlo.link) — بيدي إيميلات فريدة، DrissionPage بيتخطى Cloudflare+reCAPTCHA

مميزات v13.0:
  - SandVPN أساسي — إيميلات فريدة مش مسجلة! REST API بدون browser
  - tempail.top (@openlo.link) احتياطي — إيميلات فريدة كمان
  - emailnator اتلغى خالص — كان بيدي إيميلات مسجلة قبل كده
  - اختبار تلقائي لدومينات SandVPN مع Telicall
  - DrissionPage بيتنزل تلقائي + Chrome بيتنزل تلقائي
  - curl_cffi بيخترق Cloudflare بتاعة SandVPN API
  - إعادة محاولة تلقائية لكل رقم (8 محاولات)
  - كشف دومينات محظورة تلقائي + استبدال فوري
  - Email Pool + Session Pool
  - مكالمات عبر السيرفر (SIP)

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
import subprocess
import glob
from datetime import datetime
from urllib.parse import unquote
from filelock import FileLock

# ═══════════════════════════════════════════════════════════════
# ─── curl_cffi import (Cloudflare bypass for SandVPN) ────────
# ═══════════════════════════════════════════════════════════════
try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    cffi_requests = None

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
EMAIL_POOL_SIZE   = 10
SESSION_POOL_SIZE = 5
MAX_RETRIES       = 8

# ─── SandVPN Config (hardcoded) ──────────────────────────────
SANDVPN_API_KEY = 'sk_live_abc123def456ghi789jkl012mno345pqr678stu901vwx234yz567'
SANDVPN_BASE_URL = 'https://api.sandvpn.com/v1/tempmail/api'
SANDVPN_DOMAINS = ['flyymail.com', 'nobinbox.com', 'tempyx.com']
SANDVPN_CF_IMPERSONATE = 'safari15_5'

# الدومينات الآمنة اللي Telicall بيقبلها (مؤكد)
SAFE_DOMAINS = frozenset(['gmail.com', 'googlemail.com', 'openlo.link'])

# دومينات SandVPN اللي Telicall بيقبلها (بيتحدد تلقائياً وقت التشغيل)
_sandvpn_accepted_domains = []
_sandvpn_accepted_lock = threading.Lock()

# قائمة الدومينات المحظورة اللي اكتشفناها وقت التشغيل
_blocklisted_domains = set()
_blocklist_lock = threading.Lock()

# ═══════════════════════════════════════════════════════════════
# ─── Chrome/Chromium Auto-Detection + Auto-Install ───────────
# ═══════════════════════════════════════════════════════════════
_chrome_path = None
_chrome_lock = threading.Lock()

def _find_chrome_binary():
    """Search common paths for Chrome/Chromium binary"""
    global _chrome_path
    with _chrome_lock:
        if _chrome_path and os.path.isfile(_chrome_path):
            return _chrome_path

        candidates = [
            # Playwright installs
            *sorted(glob.glob(os.path.expanduser('~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome')), reverse=True),
            # Puppeteer installs
            *sorted(glob.glob(os.path.expanduser('~/.cache/puppeteer/chrome/linux-*/chrome-linux64/chrome')), reverse=True),
            # System installs
            '/usr/bin/chromium-browser', '/usr/bin/chromium', '/usr/bin/google-chrome',
            '/usr/bin/google-chrome-stable',
            # Snap
            '/snap/bin/chromium',
        ]

        for path in candidates:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                _chrome_path = path
                return path

        return None

def _install_chrome():
    """بيحاول ينزل Chromium تلقائياً لو مش موجود"""
    if _find_chrome_binary():
        return True

    print("  🔧 Chrome مش موجود - بجرب أنزله تلقائياً...", flush=True)

    # Method 1: Playwright install (الأضمن)
    try:
        print("  ⏳ جاري تنزيل Chromium عبر Playwright...", flush=True)
        result = subprocess.run(
            [sys.executable, '-m', 'playwright', 'install', 'chromium'],
            capture_output=True, timeout=180, text=True
        )
        if _find_chrome_binary():
            print(f"  ✅ Chromium اتنزل! ({_chrome_path})", flush=True)
            return True
        else:
            print(f"  ⚠️ Playwright install مش اشتغل: {result.stderr[:80]}", flush=True)
    except Exception as e:
        print(f"  ⚠️ Playwright install فشل: {str(e)[:60]}", flush=True)

    # Method 2: npx playwright install
    try:
        print("  ⏳ جاري تنزيل Chromium عبر npx...", flush=True)
        result = subprocess.run(
            ['npx', 'playwright', 'install', 'chromium', '--with-deps'],
            capture_output=True, timeout=300, text=True
        )
        if _find_chrome_binary():
            print(f"  ✅ Chromium اتنزل عبر npx! ({_chrome_path})", flush=True)
            return True
    except Exception as e:
        print(f"  ⚠️ npx install فشل: {str(e)[:60]}", flush=True)

    # Method 3: apt install (لو Linux)
    try:
        print("  ⏳ جاري تنزيل Chromium عبر apt...", flush=True)
        result = subprocess.run(
            ['apt-get', 'install', '-y', 'chromium-browser'],
            capture_output=True, timeout=120, text=True
        )
        if _find_chrome_binary():
            print(f"  ✅ Chromium اتنزل عبر apt! ({_chrome_path})", flush=True)
            return True
    except Exception as e:
        print(f"  ⚠️ apt install فشل: {str(e)[:60]}", flush=True)

    print("  ❌ فشل تنزيل Chromium! شغل يدوي:", flush=True)
    print("     pip3 install playwright && python3 -m playwright install chromium", flush=True)
    return False

def _install_drissionpage():
    """بيحاول ينزل DrissionPage لو مش موجود"""
    try:
        from DrissionPage import ChromiumPage
        return True
    except ImportError:
        pass

    print("  🔧 DrissionPage مش موجود - بجرب أنزله...", flush=True)
    try:
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'DrissionPage>=4.1.0'],
                      capture_output=True, timeout=120)
        from DrissionPage import ChromiumPage
        print("  ✅ DrissionPage اتنزل!", flush=True)
        return True
    except Exception as e:
        print(f"  ❌ فشل تنزيل DrissionPage: {str(e)[:60]}", flush=True)
        print("     شغل يدوي: pip3 install DrissionPage", flush=True)
        return False

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
# ─── Email Provider 1: SandVPN (أساسي — REST API) ────────────
# ═══════════════════════════════════════════════════════════════
_sandvpn_stats = {"ok": 0, "fail": 0, "blocked": 0}
_sandvpn_stats_lock = threading.Lock()
_sandvpn_lock = threading.Lock()
_sandvpn_available = True

def _sandvpn_api_request(method, endpoint, json_data=None, timeout=20):
    """بيعمل API request لـ SandVPN باستخدام curl_cffi"""
    if not HAS_CURL_CFFI:
        return 0, 'curl_cffi not installed'

    url = f"{SANDVPN_BASE_URL}/{endpoint}"
    headers = {
        'X-API-Key': SANDVPN_API_KEY,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Origin': 'https://sandvpn.com',
        'Referer': 'https://sandvpn.com/',
    }

    try:
        if method == 'POST':
            resp = cffi_requests.post(url, json=json_data, headers=headers,
                                      impersonate=SANDVPN_CF_IMPERSONATE, timeout=timeout)
        else:
            resp = cffi_requests.get(url, headers=headers,
                                     impersonate=SANDVPN_CF_IMPERSONATE, timeout=timeout)

        status = resp.status_code
        if status == 403 and 'Just a moment' in resp.text[:200]:
            return 403, 'CLOUDFLARE_BLOCKED'

        try:
            data = resp.json()
            return status, data
        except Exception:
            return status, resp.text[:500]
    except Exception as e:
        return 0, str(e)[:100]


def _generate_random_local():
    """بيولد اسم إيميل عشوائي فريد"""
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=12))


def test_sandvpn_domain(domain):
    """بيختبر دومين SandVPN مع Telicall"""
    if not HAS_CURL_CFFI:
        print(f"    {domain}: ❌ curl_cffi مش متاح", flush=True)
        return False

    test_local = f"test{random.randint(1000,9999)}"
    status, data = _sandvpn_api_request('POST', 'create',
                                         json_data={'custom_local': test_local, 'custom_domain': domain})

    if status == 401:
        print(f"    {domain}: ⚠️ API key مش صحيح (بنفترض شغال)", flush=True)
        return True  # نفترض شغال لأن المشكلة في المفتاح مش الدومين
    if status != 200:
        err = data if isinstance(data, str) else json.dumps(data)[:100]
        print(f"    {domain}: ❌ SandVPN API فشل ({status}: {err[:60]})", flush=True)
        return False

    email_addr = None
    if isinstance(data, dict):
        email_addr = data.get('email') or data.get('address')
        if not email_addr and data.get('data'):
            email_addr = data['data'].get('email') or data['data'].get('address')

    if not email_addr:
        print(f"    {domain}: ⚠️ بيانات غريبة: {json.dumps(data)[:100]}", flush=True)
        return False

    tok, device, headers = init_session()
    if not tok:
        print(f"    {domain}: ⚠️ Telicall session فشل", flush=True)
        return True

    ref, err = send_verify(email_addr, headers)
    if ref:
        print(f"    {domain}: ✅ مقبول من Telicall!", flush=True)
        return True
    elif err and 'BLOCKED' in str(err):
        print(f"    {domain}: ❌ محظور من Telicall", flush=True)
        return False
    elif err == 'EMAIL_EXISTS':
        print(f"    {domain}: ✅ مقبول (الإيميل كان مسجل)", flush=True)
        return True
    else:
        print(f"    {domain}: ⚠️ مش واضح ({str(err)[:40]}) - بنفترض شغال", flush=True)
        return True


def auto_test_sandvpn_domains():
    """بيختبر كل دومينات SandVPN مع Telicall"""
    global _sandvpn_available, _sandvpn_accepted_domains

    if not HAS_CURL_CFFI:
        print("  ❌ curl_cffi مش متاح - SandVPN مش هيشتغل!", flush=True)
        print("  💡 pip3 install curl_cffi", flush=True)
        _sandvpn_available = False
        return []

    print("\n  🔍 اختبار دومينات SandVPN مع Telicall:", flush=True)

    accepted = []
    for domain in SANDVPN_DOMAINS:
        if test_sandvpn_domain(domain):
            accepted.append(domain)
            with _sandvpn_accepted_lock:
                if domain not in _sandvpn_accepted_domains:
                    _sandvpn_accepted_domains.append(domain)

    if not accepted:
        print("  ⚠️ ولا دومين من SandVPN اتعمل مع Telicall!", flush=True)
        _sandvpn_available = False
    else:
        print(f"  ✅ دومينات شغالة: {', '.join(accepted)}", flush=True)
        _sandvpn_available = True

    return accepted


def create_sandvpn_mail(max_retries=3):
    """SandVPN - بيعمل إيميل مؤقت — إيميلات فريدة 100%"""
    if not _sandvpn_available or not HAS_CURL_CFFI:
        with _sandvpn_stats_lock:
            _sandvpn_stats["fail"] += 1
        return None

    with _sandvpn_lock:
        with _sandvpn_accepted_lock:
            domains = list(_sandvpn_accepted_domains)
        if not domains:
            domains = list(SANDVPN_DOMAINS)

        random.shuffle(domains)

        for attempt in range(max_retries):
            for domain in domains:
                local = _generate_random_local()
                status, data = _sandvpn_api_request('POST', 'create',
                    json_data={'custom_local': local, 'custom_domain': domain})

                if status == 200:
                    actual_email = f"{local}@{domain}"
                    if isinstance(data, dict):
                        returned_email = data.get('email') or data.get('address')
                        if returned_email and '@' in str(returned_email):
                            actual_email = str(returned_email)

                    with _sandvpn_stats_lock:
                        _sandvpn_stats["ok"] += 1

                    return {
                        'email': actual_email,
                        'api_type': 'sandvpn',
                        'session': None,
                        'xsrf_headers': None,
                        'provider': f'sandvpn-{domain}',
                        'initial_msg_ids': set(),
                    }

                elif status == 401:
                    print(f"  ❌ SandVPN: API key مش صحيح!", flush=True)
                    with _sandvpn_stats_lock:
                        _sandvpn_stats["fail"] += 1
                    _sandvpn_available = False
                    return None

                elif status == 403 and isinstance(data, str) and 'CLOUDFLARE' in data:
                    time.sleep(2)
                    continue

                else:
                    continue

            if attempt < max_retries - 1:
                time.sleep(1)

    with _sandvpn_stats_lock:
        _sandvpn_stats["fail"] += 1
    return None


def check_sandvpn_inbox(mail_info, timeout=90):
    """بيدور على OTP في SandVPN inbox"""
    email_addr = mail_info['email']
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status, data = _sandvpn_api_request('GET', f'emails/{email_addr}')

            if status == 200 and isinstance(data, dict):
                emails = data.get('emails', [])
                for email_msg in emails:
                    subject = str(email_msg.get('subject', ''))
                    html_content = str(email_msg.get('html', ''))

                    m = re.search(r'\b(\d{6})\b', subject)
                    if m:
                        return m.group(1)

                    m2 = re.search(r'\b(\d{6})\b', html_content)
                    if m2:
                        return m2.group(1)

                    all_content = subject + ' ' + html_content
                    if 'teli' in all_content.lower() or 'verif' in all_content.lower():
                        m3 = re.search(r'\b(\d{6})\b', all_content)
                        if m3:
                            return m3.group(1)

        except Exception:
            pass
        time.sleep(5)
    return None

# ═══════════════════════════════════════════════════════════════
# ─── Email Provider 2: tempail.top (@openlo.link) ────────────
# ═══════════════════════════════════════════════════════════════
_tempail_stats = {"ok": 0, "fail": 0}
_tempail_stats_lock = threading.Lock()
_tempail_lock = threading.Lock()
_tempail_page = None
_tempail_init_lock = threading.Lock()
_tempail_available = True
_tempail_fail_count = 0
TEMPAIL_MAX_FAILS = 10

def _get_tempail_page():
    """بيفتح أو بيرجع الـ browser page المشترك لـ tempail.top
    بيتخطى Cloudflare + reCAPTCHA تلقائياً"""
    global _tempail_page
    with _tempail_init_lock:
        if _tempail_page is not None:
            try:
                _tempail_page.title
                return _tempail_page
            except:
                _tempail_page = None

        # Install DrissionPage لو مش موجود
        if not _install_drissionpage():
            return None

        # Install Chrome لو مش موجود
        if not _install_chrome():
            return None

        chrome_path = _find_chrome_binary()
        if not chrome_path:
            return None

        try:
            from DrissionPage import ChromiumPage, ChromiumOptions
            co = ChromiumOptions()
            co.headless()
            co.set_browser_path(chrome_path)
            co.set_argument('--no-sandbox')
            co.set_argument('--disable-gpu')
            co.set_argument('--disable-dev-shm-usage')
            co.set_argument('--disable-blink-features=AutomationControlled')
            co.set_user_agent('Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36')
            co.auto_port()
            _tempail_page = ChromiumPage(co)
            return _tempail_page
        except Exception as e:
            print(f"  ❌ tempail: browser init فشل: {str(e)[:80]}", flush=True)
            return None


def _record_tempail_fail():
    global _tempail_available, _tempail_fail_count
    _tempail_fail_count += 1
    if _tempail_fail_count >= TEMPAIL_MAX_FAILS:
        _tempail_available = False
        print(f"  ⚠️ tempail: اتعطل بعد {_tempail_fail_count} فشل", flush=True)


def _record_tempail_success():
    global _tempail_fail_count, _tempail_available
    _tempail_fail_count = 0
    if not _tempail_available:
        _tempail_available = True
        print(f"  ✅ tempail: رجع يشتغل!", flush=True)


def create_tempail_mail(max_retries=2):
    """tempail.top - بيدي @openlo.link — إيميلات فريدة مش مسجلة!"""
    with _tempail_lock:
        page = _get_tempail_page()
        if not page:
            with _tempail_stats_lock:
                _tempail_stats["fail"] += 1
            _record_tempail_fail()
            return None

        for attempt in range(max_retries):
            try:
                if attempt == 0:
                    page.get('https://tempail.top')
                else:
                    try:
                        page.get('https://tempail.top/delete')
                        time.sleep(2)
                    except:
                        pass
                    page.get('https://tempail.top')

                # استنى الإيميل يظهر (Cloudflare + reCAPTCHA + page load)
                email = None
                for i in range(45):  # 45 ثانية — كفاية للـ reCAPTCHA
                    time.sleep(1)
                    try:
                        email_elem = page.ele('#trsh_mail')
                        if email_elem:
                            val = email_elem.value
                            if val and '@' in val:
                                email = val
                                break
                    except:
                        pass
                    # كمان نجرب selector تاني
                    try:
                        email_elem = page.ele('.mail-address')
                        if email_elem:
                            val = email_elem.text or email_elem.value
                            if val and '@' in val:
                                email = val
                                break
                    except:
                        pass

                if not email:
                    _record_tempail_fail()
                    continue

                domain = email.split('@')[1] if '@' in email else ''
                if domain.lower() not in SAFE_DOMAINS and domain.lower() != 'openlo.link':
                    _record_tempail_fail()
                    continue

                with _tempail_stats_lock:
                    _tempail_stats["ok"] += 1

                _record_tempail_success()

                return {
                    'email': email,
                    'api_type': 'tempail',
                    'session': None,
                    'xsrf_headers': None,
                    'provider': 'tempail-openlo',
                    'initial_msg_ids': set(),
                    'page': page,
                }
            except:
                _record_tempail_fail()
                continue

        with _tempail_stats_lock:
            _tempail_stats["fail"] += 1
        _record_tempail_fail()
        return None


def check_tempail_inbox(mail_info, timeout=90):
    """بيدور على OTP في tempail.top عبر AJAX"""
    page = mail_info.get('page')
    if not page:
        return None

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            result = page.run_js('''
                return new Promise((resolve, reject) => {
                    var csrf = document.querySelector('meta[name=csrf-token]');
                    if (!csrf) { reject('no csrf'); return; }
                    fetch('/messages?' + Date.now(), {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                            'X-Requested-With': 'XMLHttpRequest',
                        },
                        body: '_token=' + csrf.content,
                    })
                    .then(r => r.json())
                    .then(data => resolve(JSON.stringify(data)))
                    .catch(err => reject(err.toString()));
                });
            ''')

            if result:
                try:
                    data = json.loads(result)
                    messages = data.get('messages', [])
                    for msg in messages:
                        subject = msg.get('subject', '')
                        m = re.search(r'\b(\d{6})\b', subject)
                        if m:
                            return m.group(1)

                        from_email = msg.get('from_email', '')
                        msg_id = msg.get('id', '')
                        if msg_id:
                            current_url = page.url
                            page.get(f'https://tempail.top/view/{msg_id}')
                            time.sleep(2)
                            body_text = page.run_js('return document.body.innerText')
                            if body_text:
                                m2 = re.search(r'\b(\d{6})\b', body_text)
                                if m2:
                                    return m2.group(1)
                            page.get('https://tempail.top')
                            time.sleep(1)
                except:
                    pass
        except:
            pass
        time.sleep(5)
    return None

# ═══════════════════════════════════════════════════════════════
# ─── Email Pool ──────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
_email_pool = queue.Queue(maxsize=EMAIL_POOL_SIZE)
_session_pool = queue.Queue(maxsize=SESSION_POOL_SIZE)
_stop_flag = threading.Event()
_pool_stats = {"emails_created": 0, "sessions_created": 0, "emails_rejected": 0}
_pool_stats_lock = threading.Lock()

def _is_safe_email(email_addr: str) -> bool:
    domain = email_addr.split('@')[1] if '@' in email_addr else ''
    domain_lower = domain.lower()

    if domain_lower in SAFE_DOMAINS:
        return True
    if domain_lower == 'openlo.link':
        return True

    with _sandvpn_accepted_lock:
        if domain_lower in _sandvpn_accepted_domains:
            return True

    with _blocklist_lock:
        if domain_lower in _blocklisted_domains:
            return False

    return True

def _email_pool_filler():
    """خلفية: بيملا بول الإيميلات
    SandVPN أساسي (90%) | tempail.top احتياطي"""
    while not _stop_flag.is_set():
        if _email_pool.qsize() < EMAIL_POOL_SIZE:
            mail = None
            # SandVPN أساسي (90%)
            if _sandvpn_available and HAS_CURL_CFFI and random.random() < 0.9:
                mail = create_sandvpn_mail()

            # tempail.top احتياطي
            if not mail and _tempail_available:
                mail = create_tempail_mail()

            # لو tempail فشل، جرب SandVPN
            if not mail and _sandvpn_available and HAS_CURL_CFFI:
                mail = create_sandvpn_mail()

            if mail:
                if _is_safe_email(mail['email']):
                    try:
                        _email_pool.put_nowait(mail)
                        with _pool_stats_lock:
                            _pool_stats["emails_created"] += 1
                    except queue.Full:
                        pass
                else:
                    with _pool_stats_lock:
                        _pool_stats["emails_rejected"] += 1
            else:
                time.sleep(3)
        else:
            time.sleep(0.5)

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

def get_email_from_pool(prefer_tempail=False):
    try:
        return _email_pool.get(timeout=10)
    except queue.Empty:
        for attempt in range(5):
            if prefer_tempail and _tempail_available:
                mail = create_tempail_mail()
                if mail and _is_safe_email(mail['email']):
                    return mail
            if _sandvpn_available and HAS_CURL_CFFI:
                mail = create_sandvpn_mail()
                if mail and _is_safe_email(mail['email']):
                    return mail
            if _tempail_available:
                mail = create_tempail_mail()
                if mail and _is_safe_email(mail['email']):
                    return mail
            time.sleep(2)
        return None

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

def start_pools(num_email_fillers=2, num_session_fillers=1):
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
    if api_type == 'sandvpn':
        return check_sandvpn_inbox(mail_info, timeout=timeout)
    elif api_type == 'tempail':
        return check_tempail_inbox(mail_info, timeout=timeout)
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
                err_data = r.json()
                err = err_data.get('meta', {}).get('errorMessage', r.text[:80])
                err_lower = str(err).lower()
                if 'already exist' in err_lower or 'already registered' in err_lower:
                    return None, 'EMAIL_EXISTS'
                if 'blocklist' in err_lower or 'blocked' in err_lower or 'محظور' in err:
                    domain = email.split('@')[1] if '@' in email else ''
                    with _blocklist_lock:
                        _blocklisted_domains.add(domain)
                    with _sandvpn_accepted_lock:
                        if domain in _sandvpn_accepted_domains:
                            _sandvpn_accepted_domains.remove(domain)
                    return None, f'BLOCKED:{domain}'
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
            except:
                return None, f'other:HTTP400'
        else:
            return None, f'other:HTTP{r.status_code}'
    except Exception as e:
        return None, f'other:{str(e)[:50]}'

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
# ─── Active Call Tracking ────────────────────────────────────
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
                            print(f"[{tid}] ❌ فشل المكالمة {phone} ({err})", flush=True)
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
# ─── Worker ──────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def _try_one_phone(phone, duration, mode, tid, prefer_tempail=False):
    mail = get_email_from_pool(prefer_tempail=prefer_tempail)
    if not mail:
        print(f"[{tid}] ❌ لا إيميل من أي مزود {phone}", flush=True)
        update_stat("email_fail")
        return 'retry'

    email_addr = mail['email']
    email_short = email_addr.split('@')[0][:12]
    email_domain = email_addr.split('@')[1] if '@' in email_addr else '?'
    provider = mail.get('provider', '?')
    api_type = mail.get('api_type', '?')

    if not _is_safe_email(email_addr):
        print(f"[{tid}] ❌ دومين محظور {email_domain} [{provider}]", flush=True)
        update_stat("domain_blocked")
        return 'domain_blocked'

    icon = '[sv]' if api_type == 'sandvpn' else '[tp]'
    print(f"[{tid}] {icon} 📧 {email_short}...@{email_domain} [{provider}] -> {phone}", flush=True)

    tok, device, headers, sess_proxy = get_session_from_pool()
    active_proxy = sess_proxy or get_proxy()

    if not tok:
        print(f"[{tid}] ❌ فشل الجلسة {phone}", flush=True)
        update_stat("session_fail")
        return 'retry'

    ref, err = send_verify(email_addr, headers, active_proxy)
    if not ref:
        err_str = str(err or "")
        if err_str == 'EMAIL_EXISTS':
            print(f"[{tid}] ⚠️ إيميل مسجل قبل كده {email_short}...@{email_domain} [{provider}]", flush=True)
            update_stat("email_exists")
            return 'email_exists'
        elif err_str.startswith('BLOCKED:'):
            blocked_domain = err_str.split(':', 1)[1]
            print(f"[{tid}] ❌ دومين محظور: {blocked_domain} {phone}", flush=True)
            update_stat("domain_blocked")
            return 'domain_blocked'
        else:
            print(f"[{tid}] ❌ فشل إرسال التحقق {phone} ({err_str[:50]})", flush=True)
            update_stat("verify_fail")
        if active_proxy:
            active_proxy = get_proxy_and_mark_dead(active_proxy)
        return 'retry'

    otp = get_otp_from_mail(mail, active_proxy, timeout=90)
    if not otp:
        print(f"[{tid}] ❌ OTP انتهى {phone} <- {email_short}", flush=True)
        update_stat("otp_fail")
        return 'retry'

    print(f"[{tid}] 🔢 OTP:{otp} {email_short}", flush=True)

    time.sleep(1)
    user, verify_err = verify_otp_api(ref, otp, headers, active_proxy)
    if not user:
        if verify_err == 'email_exists':
            print(f"[{tid}] ⚠️ إيميل مسجل قبل كده (OTP step) {email_short}... [{provider}]", flush=True)
            update_stat("email_exists")
            return 'email_exists'
        elif verify_err == 'expired':
            print(f"[{tid}] ❌ OTP انتهى/غلط {phone}", flush=True)
            update_stat("confirm_fail")
            return 'retry'
        else:
            print(f"[{tid}] ❌ فشل التأكيد {phone} ({verify_err})", flush=True)
            update_stat("confirm_fail")
            return 'retry'

    total = save_account(email_addr, device, tok)
    print(f"[{tid}] ✅ حساب! {email_short} (#{total})", flush=True)

    if mode == "create":
        update_stat("accounts_ok")
        return 'ok'

    ready = upload_to_server(email_addr, device, tok)
    call_id, verify_url = trigger_async_call(phone, duration)
    if call_id:
        add_active_call(call_id, phone, email_short, tid)
        print(f"[{tid}] 📞 مكالمة! {phone} (ready:{ready}, id:{str(call_id)[:10]}...)", flush=True)
        return 'ok'

    result = trigger_make_call(phone, duration)
    status = result.get("status", "unknown")
    from_num = result.get("from", result.get("from_number", "?"))
    dur = result.get("duration", result.get("actual_duration", 0))
    error = result.get("error", "")

    if status == "answered_ok":
        print(f"[{tid}] ✅ تم الاتصال {phone} ({dur}s) <- {from_num}", flush=True)
        update_stat("calls_ok")
        return 'ok'
    elif "balance" in str(error).lower() or status == "no_balance":
        print(f"[{tid}] ⚠️ NO_BALANCE {phone}", flush=True)
        update_stat("calls_no_balance")
        update_stat("accounts_no_bal")
        return 'no_balance'
    else:
        print(f"[{tid}] ❌ فشل المكالمة {phone} ({error or status})", flush=True)
        update_stat("calls_failed")
        update_stat("accounts_ok")
        return 'no_balance'

def create_and_call(duration, mode="server", use_xrealip=True):
    tid = threading.current_thread().name

    while True:
        phone = get_next_phone()
        if not phone:
            break

        update_stat("total")

        success = False
        last_result = None
        prefer_tempail = False
        for attempt in range(1, MAX_RETRIES + 1):
            if attempt > 1:
                update_stat("retries")
                print(f"[{tid}] 🔄 إعادة محاولة {attempt}/{MAX_RETRIES} لـ {phone}", flush=True)
                time.sleep(1)

            result = _try_one_phone(phone, duration, mode, tid, prefer_tempail=prefer_tempail)
            last_result = result

            if result in ('ok', 'no_balance'):
                success = True
                break
            elif result in ('domain_blocked', 'email_exists'):
                if result == 'email_exists':
                    prefer_tempail = True
                continue
            elif result == 'retry':
                continue
            else:
                break

        if not success:
            add_failed_phone(phone, last_result or 'unknown')
            print(f"[{tid}] ❌ فشل نهائي {phone} بعد {MAX_RETRIES} محاولات ({last_result})", flush=True)

        time.sleep(0.3)

# ═══════════════════════════════════════════════════════════════
# ─── Stats Printer ────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def print_stats():
    while True:
        time.sleep(30)
        with _stats_lock:
            s = dict(_stats)
        with _sandvpn_stats_lock:
            ss = dict(_sandvpn_stats)
        with _tempail_stats_lock:
            ts = dict(_tempail_stats)
        with _blocklist_lock:
            bl = len(_blocklisted_domains)
        with _sandvpn_accepted_lock:
            sv_domains = list(_sandvpn_accepted_domains)
        elapsed = time.time() - _start_time if _start_time else 1
        rate = s['total'] / elapsed * 60 if elapsed > 0 else 0
        sv_status = "✅" if _sandvpn_available else "❌"
        tp_status = "✅" if _tempail_available else "❌"
        print(f"\n  📊 Stats ({elapsed/60:.1f}min | {rate:.1f}/min):", flush=True)
        print(f"     إجمالي: {s['total']} | ✅ ناجح: {s['accounts_ok']} | 📞 مكالمات: {s['calls_ok']}", flush=True)
        print(f"     ❌ إيميل={s['email_fail']} جلسة={s['session_fail']} تحقق={s['verify_fail']} OTP={s['otp_fail']} تأكيد={s['confirm_fail']}", flush=True)
        print(f"     إيميل مسجل: {s['email_exists']} | دومين محظور: {s['domain_blocked']} | NO_BALANCE: {s['calls_no_balance']}", flush=True)
        print(f"     SandVPN {sv_status}: ok={ss['ok']} fail={ss['fail']} | Tempail {tp_status}: ok={ts['ok']} fail={ts['fail']} (fails:{_tempail_fail_count}/{TEMPAIL_MAX_FAILS}) | محظورين: {bl}", flush=True)
        if sv_domains:
            print(f"     SandVPN مقبول: {', '.join(sv_domains)}", flush=True)

# ═══════════════════════════════════════════════════════════════
# ─── Main ─────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════
def main():
    global _start_time, _phone_queue, SANDVPN_API_KEY

    parser = argparse.ArgumentParser(description="Fox Caller v13.0 - Openlo + SandVPN")
    parser.add_argument("file", help="ملف الأرقام (.xlsx أو .txt)")
    parser.add_argument("--mode", choices=["server", "create"], default="server")
    parser.add_argument("--threads", type=int, default=DEFAULT_THREADS)
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-xrealip", action="store_true")
    parser.add_argument("--sandvpn-key", type=str, default=None,
                       help="SandVPN API key")

    args = parser.parse_args()

    if args.sandvpn_key:
        SANDVPN_API_KEY = args.sandvpn_key

    print("\n" + "=" * 60, flush=True)
    print("  Fox Caller v13.0 - Openlo + SandVPN", flush=True)
    print("  SandVPN (@flyymail/@nobinbox/@tempyx) | tempail.top (@openlo.link)", flush=True)
    print("  ❌ emailnator اتلغى — كان بيدي إيميلات مسجلة", flush=True)
    print("=" * 60, flush=True)

    numbers = read_numbers(args.file)
    if not numbers:
        print("ERROR: لا توجد أرقام في الملف!", flush=True)
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
    print(f"  Email:      SandVPN ← أساسي | tempail.top ← احتياطي", flush=True)

    init_proxy_manager()

    # ─── Diagnostic ───
    print("\n  🔍 Diagnostic:", flush=True)

    # curl_cffi
    if HAS_CURL_CFFI:
        print(f"  ✅ curl_cffi: متاح", flush=True)
    else:
        print(f"  ❌ curl_cffi: مش متاح! SandVPN مش هيشتغل!", flush=True)
        print(f"  💡 pip3 install curl_cffi", flush=True)

    # Chrome
    chrome = _find_chrome_binary()
    if chrome:
        print(f"  ✅ Chrome: {chrome}", flush=True)
    else:
        print(f"  ⚠️ Chrome: مش موجود - هحاول أنزله تلقائياً", flush=True)

    # DrissionPage
    try:
        from DrissionPage import ChromiumPage
        print(f"  ✅ DrissionPage: متاح", flush=True)
    except ImportError:
        print(f"  ⚠️ DrissionPage: مش متاح - هحاول أنزله تلقائياً", flush=True)

    # SandVPN API key
    key_preview = SANDVPN_API_KEY[:15] + '...'
    print(f"  🔑 SandVPN API Key: {key_preview}", flush=True)
    if 'abc123' in SANDVPN_API_KEY:
        print(f"  ⚠️ المفتاح ده placeholder! جيب حقيقي من sandvpn.com", flush=True)
        print(f"  💡 أو شغل: --sandvpn-key YOUR_REAL_KEY", flush=True)

    # Auto-test SandVPN domains
    auto_test_sandvpn_domains()

    # Check server
    if args.mode == "server":
        if is_server_available():
            print(f"  Server:     ✅ متاح ({SERVER_URL})", flush=True)
        else:
            print(f"  Server:     ⚠️ غير متاح! هنعمل create بس", flush=True)
            args.mode = "create"

    # Start pools
    start_pools()

    # Quick test
    print("\n  🔍 Quick Test: جرب المزودين...", flush=True)

    if _sandvpn_available and HAS_CURL_CFFI:
        test_mail1 = create_sandvpn_mail()
        if test_mail1:
            print(f"  ✅ SandVPN: {test_mail1['email'][:25]}... [{test_mail1['provider']}]", flush=True)
            try:
                _email_pool.put_nowait(test_mail1)
            except queue.Full:
                pass
        else:
            print(f"  ⚠️ SandVPN مش شغال", flush=True)

    if _tempail_available:
        test_mail2 = create_tempail_mail()
        if test_mail2:
            print(f"  ✅ tempail: {test_mail2['email'][:25]}... [{test_mail2['provider']}]", flush=True)
            try:
                _email_pool.put_nowait(test_mail2)
            except queue.Full:
                pass
        else:
            print(f"  ⚠️ tempail.top مش شغال دلوقتي", flush=True)

    if not _sandvpn_available and not _tempail_available:
        print(f"\n  ❌ ولا مزود شغال! لازم:", flush=True)
        print(f"     1. SandVPN: جيب API key حقيقي من sandvpn.com", flush=True)
        print(f"     2. tempail: ثبت Chrome + DrissionPage", flush=True)

    print(f"\n  🚀 بدء التشغيل...", flush=True)
    print("-" * 60, flush=True)

    stats_thread = threading.Thread(target=print_stats, daemon=True)
    stats_thread.start()

    if args.mode == "server":
        monitor_thread = threading.Thread(target=monitor_calls, daemon=True)
        monitor_thread.start()

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

    for t in workers:
        t.join()

    time.sleep(15)

    elapsed = time.time() - _start_time if _start_time else 0
    with _stats_lock:
        s = dict(_stats)
    with _sandvpn_stats_lock:
        ss = dict(_sandvpn_stats)
    with _tempail_stats_lock:
        ts = dict(_tempail_stats)
    with _sandvpn_accepted_lock:
        sv_domains = list(_sandvpn_accepted_domains)

    print("\n" + "=" * 60, flush=True)
    print("  📊 التقرير النهائي", flush=True)
    print("=" * 60, flush=True)
    print(f"  ⏱️  الوقت: {elapsed/60:.1f} دقيقة", flush=True)
    print(f"  📞 إجمالي: {s['total']} | ✅ حسابات: {s['accounts_ok']} | 📞 مكالمات: {s['calls_ok']}", flush=True)
    print(f"  ⚠️  NO_BALANCE: {s['calls_no_balance']} | ❌ فشل: {len(_failed_phones)}", flush=True)
    print(f"  📧 SandVPN: ok={ss['ok']} fail={ss['fail']} | Tempail: ok={ts['ok']} fail={ts['fail']}", flush=True)
    if sv_domains:
        print(f"  📧 SandVPN مقبول: {', '.join(sv_domains)}", flush=True)

    print("=" * 60, flush=True)
    _stop_flag.set()


if __name__ == "__main__":
    main()
