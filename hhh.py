#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TelliCall Bot v4 - Multi-Provider Email + Inbox Watcher + Date Feature
======================================================================
Changes from v3:
  - tempmail.lol as PRIMARY email provider (no rate limits!)
  - temp-mail.org as fallback providers (web2 + mob2)
  - Automatic failover between providers
  - Updated domain lists with new tempmail.lol domains
  - Fixed rate limiting issues from v3
"""

import telebot
from telebot import types
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

# ==================== إعدادات البوت ====================
BOT_TOKEN = "7622961655:AAEMyav7MYmZMRNADkzj8KCIv2yEx2vpxd4"
OWNER_ID = 962731079  # ضع Telegram ID الخاص بك

bot = telebot.TeleBot(BOT_TOKEN)

# ==================== إعدادات TelliCall ====================
TELICALL_BASE_URL = "https://api.telicall.com"
APP_VERSION = "1.2.1"
OS_VERSION = "11"
USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 11; Infinix X698 Build/RP1A.200720.011)"

# ==================== إعدادات Dan.json ====================
DAN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Dan.json")
PASSWORD = "@@@GMAQ@@@"

# ═══════════════════════════════════════════════════════
# ─── Multi-Provider Email Config ─────────────────────
# ═══════════════════════════════════════════════════════

# Provider 1: tempmail.lol (PRIMARY — no rate limit)
TEMPMAIL_LOL_URL = "https://api.tempmail.lol"

# Provider 2: temp-mail.org web2 (FALLBACK)
WEB2_BASE_URL = "https://web2.temp-mail.org"
WEB2_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Origin': 'https://temp-mail.org',
    'Referer': 'https://temp-mail.org/',
    'Content-Type': 'application/json'
}

# Provider 3: temp-mail.org mob2 (LAST RESORT)
MOB2_BASE_URL = "https://mob2.temp-mail.org"
MOB2_HEADERS = {
    'Accept': 'application/json',
    'User-Agent': '3.49',
    'Accept-Encoding': 'gzip'
}

# ==================== Domain Filtering ====================
WORKING_DOMAINS = {
    # tempmail.lol
    'blaizesmp.net', 'chillart.org', 'dogmrp.com',
    'for4u.net', 'basketrise.com', 'autofixmax.com',
    # temp-mail.org
    'ifcoat.com', 'doreact.com', 'googxs.com', 'hitzcart.com', 'matkind.com',
}

BLOCKLISTED_DOMAINS = {'wshu.net', '4nly.com', 'alf5.com', 'mtupu.com',
                       'guerrillamailblock.com', 'guerrillamail.com', 'guerrillamail.de'}

# ==================== حالات ومراقبو البريد ====================
active_tasks = {}     # مهام الإنشاء الجارية  {chat_id: True/False}
inbox_watchers = {}   # مراقبو البريد النشطين  {email: {'thread':..., 'stop':Event, ...}}
inbox_watchers_lock = threading.Lock()

# ==================== Dan.json Encryption ====================

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

def load_dan_accounts():
    """تحميل الحسابات من Dan.json"""
    if not os.path.exists(DAN_FILE):
        return []
    try:
        raw = open(DAN_FILE, 'rb').read()
        try:
            result = json.loads(decrypt_file(DAN_FILE, PASSWORD))
        except:
            result = json.loads(raw.decode('utf-8'))
        return result
    except:
        return []

# ═══════════════════════════════════════════════════════
# ─── InboxWatcher - نظام مراقبة البريد ──────────────
# ═══════════════════════════════════════════════════════

def get_all_messages_tempmail_lol(email_token):
    """جلب كل الرسائل من tempmail.lol"""
    try:
        response = requests.get(f"{TEMPMAIL_LOL_URL}/auth/{email_token}", timeout=15)
        if response.status_code == 200:
            data = response.json()
            return data.get('email', [])
    except Exception as e:
        print(f"[tempmail.lol fetch] {e}")
    return []

def get_all_messages_web2(email_token):
    """جلب كل الرسائل من web2"""
    try:
        headers = WEB2_HEADERS.copy()
        headers['Authorization'] = f"Bearer {email_token}"
        response = requests.get(f"{WEB2_BASE_URL}/messages", headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            return data if isinstance(data, list) else data.get('messages', [])
    except Exception as e:
        print(f"[web2 fetch] {e}")
    return []

def get_all_messages_mob2(email_token):
    """جلب كل الرسائل من mob2"""
    try:
        headers = MOB2_HEADERS.copy()
        headers['Authorization'] = email_token
        response = requests.get(f"{MOB2_BASE_URL}/messages", headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data.get('messages', [])
    except Exception as e:
        print(f"[mob2 fetch] {e}")
    return []

def get_messages_by_api(api_type, email_token):
    """جلب الرسائل حسب نوع المزود"""
    if api_type == 'tempmail_lol':
        return get_all_messages_tempmail_lol(email_token)
    elif api_type == 'web2':
        return get_all_messages_web2(email_token)
    else:
        return get_all_messages_mob2(email_token)

def get_message_id(msg):
    """استخراج ID فريد للرسالة لتجنب تكرار الإشعارات"""
    return msg.get('id') or msg.get('_id') or msg.get('uid') or str(msg.get('date', '')) + msg.get('from', '')

def format_message_notification(account_email, msg, account_number=None):
    """تنسيق رسالة الإشعار لإرسالها للمستخدم"""
    sender  = msg.get('from', 'غير معروف')
    subject = msg.get('subject', 'بدون موضوع')
    body    = msg.get('bodyPreview') or msg.get('textBody') or msg.get('body', '')
    
    if len(str(body)) > 400:
        body = str(body)[:400] + "..."
    
    account_label = f"#{account_number}" if account_number else ""
    
    text = (
        f"📬 *رسالة جديدة {account_label}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📧 *الحساب:* `{account_email}`\n"
        f"👤 *المرسل:* `{sender}`\n"
        f"📌 *الموضوع:* `{subject}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 *المحتوى:*\n{body}"
    )
    return text

def inbox_watcher_loop(chat_id, account_email, email_token, api_type, account_number, stop_event):
    """الحلقة الرئيسية لمراقبة صندوق الوارد لحساب واحد."""
    print(f"[Watcher START] {account_email} | api={api_type} | chat={chat_id}")
    
    seen_ids = set()
    initial_msgs = get_messages_by_api(api_type, email_token)
    for m in initial_msgs:
        seen_ids.add(get_message_id(m))
    
    print(f"[Watcher] {account_email} | رسائل أولية: {len(seen_ids)}")
    
    CHECK_INTERVAL = 30
    
    while not stop_event.is_set():
        for _ in range(CHECK_INTERVAL):
            if stop_event.is_set():
                break
            time.sleep(1)
        
        if stop_event.is_set():
            break
        
        try:
            current_msgs = get_messages_by_api(api_type, email_token)
            
            new_messages = []
            for msg in current_msgs:
                msg_id = get_message_id(msg)
                if msg_id not in seen_ids:
                    new_messages.append(msg)
                    seen_ids.add(msg_id)
            
            for msg in new_messages:
                print(f"[Watcher] رسالة جديدة في {account_email}: {msg.get('subject', '?')}")
                notification = format_message_notification(account_email, msg, account_number)
                
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton(
                    f"🔕 إيقاف مراقبة هذا الحساب",
                    callback_data=f"stop_watch_{account_email}"
                ))
                
                try:
                    bot.send_message(
                        chat_id,
                        notification,
                        parse_mode='Markdown',
                        reply_markup=markup
                    )
                except Exception as e:
                    print(f"[Watcher] خطأ في إرسال الإشعار: {e}")
        
        except Exception as e:
            print(f"[Watcher ERROR] {account_email}: {e}")
    
    print(f"[Watcher STOP] {account_email}")

def start_inbox_watcher(chat_id, account):
    """تشغيل مراقب صندوق الوارد لحساب معين في thread منفصل"""
    email       = account['email']
    email_token = account['email_token']
    api_type    = account['api_used']
    acct_num    = account.get('number', '?')
    
    stop_event = threading.Event()
    
    thread = threading.Thread(
        target=inbox_watcher_loop,
        args=(chat_id, email, email_token, api_type, acct_num, stop_event),
        daemon=True,
        name=f"watcher_{email}"
    )
    thread.start()
    
    with inbox_watchers_lock:
        inbox_watchers[email] = {
            'thread': thread,
            'stop': stop_event,
            'chat_id': chat_id,
            'account_number': acct_num,
            'started_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    
    print(f"[Watcher] بدء مراقبة: {email}")
    return True

def stop_inbox_watcher(email):
    """إيقاف مراقب صندوق الوارد لحساب معين"""
    with inbox_watchers_lock:
        if email in inbox_watchers:
            inbox_watchers[email]['stop'].set()
            del inbox_watchers[email]
            print(f"[Watcher] إيقاف مراقبة: {email}")
            return True
    return False

def stop_all_watchers_for_chat(chat_id):
    """إيقاف جميع مراقبي البريد لمستخدم معين"""
    to_stop = []
    with inbox_watchers_lock:
        for email, data in inbox_watchers.items():
            if data['chat_id'] == chat_id:
                to_stop.append(email)
    
    for email in to_stop:
        stop_inbox_watcher(email)
    
    return len(to_stop)

# ═══════════════════════════════════════════════════════
# ─── دوال إنشاء الإيميل — Multi-Provider ────────────
# ═══════════════════════════════════════════════════════

def create_email_tempmail_lol():
    """Provider 1: tempmail.lol — أساسي (مفيش rate limit)"""
    for attempt in range(3):
        try:
            r = requests.get(f"{TEMPMAIL_LOL_URL}/generate", timeout=15)
            if r.status_code == 200:
                data = r.json()
                email = data.get('address')
                token = data.get('token')
                if email and token:
                    domain = email.split('@')[1] if '@' in email else ''
                    if domain in BLOCKLISTED_DOMAINS:
                        if attempt < 2:
                            time.sleep(0.5)
                            continue
                    return {'email': email, 'token': token, 'api': 'tempmail_lol'}
            else:
                time.sleep(2)
        except Exception as e:
            print(f"tempmail.lol error: {e}")
            time.sleep(2)
    return None

def create_email_web2():
    """Provider 2: temp-mail.org web2 — احتياطي"""
    for attempt in range(5):
        try:
            response = requests.post(f"{WEB2_BASE_URL}/mailbox", headers=WEB2_HEADERS, timeout=15)
            if response.status_code in [200, 201]:
                data = response.json()
                email = data.get('mailbox')
                token = data.get('token')
                if email and token:
                    domain = email.split('@')[1] if '@' in email else ''
                    if domain in BLOCKLISTED_DOMAINS:
                        if attempt < 4:
                            time.sleep(1)
                            continue
                    return {'email': email, 'token': token, 'api': 'web2'}
            elif response.status_code == 429:
                time.sleep(10 * (attempt + 1))
            else:
                time.sleep(3)
        except Exception as e:
            print(f"web2 create error: {e}")
            time.sleep(3)
    return None

def create_email_mob2():
    """Provider 3: temp-mail.org mob2 — ملاذ أخير"""
    for attempt in range(3):
        try:
            response = requests.post(f"{MOB2_BASE_URL}/mailbox", headers=MOB2_HEADERS, timeout=10)
            if response.status_code == 200:
                data = response.json()
                email = data.get('mailbox')
                token = data.get('token')
                if email and token:
                    domain = email.split('@')[1] if '@' in email else ''
                    if domain in BLOCKLISTED_DOMAINS:
                        if attempt < 2:
                            time.sleep(1)
                            continue
                    return {'email': email, 'token': token, 'api': 'mob2'}
        except Exception as e:
            print(f"mob2 create error: {e}")
            time.sleep(3)
    return None

def create_email_smart():
    """
    بيعمل ايميل مؤقت — بيجرب المزودين بالترتيب:
    1. tempmail.lol (أساسي)
    2. temp-mail.org web2 (احتياطي)
    3. temp-mail.org mob2 (ملاذ أخير)
    """
    # Provider 1: tempmail.lol
    result = create_email_tempmail_lol()
    if result:
        domain = result['email'].split('@')[1] if '@' in result['email'] else ''
        if domain not in BLOCKLISTED_DOMAINS:
            return result
        print(f"⚠️ tempmail.lol أعطى دومين محظور ({domain})، جاري تجربة web2...")
    else:
        print("⚠️ tempmail.lol فشل، جاري تجربة web2...")
    
    # Provider 2: web2
    result = create_email_web2()
    if result:
        domain = result['email'].split('@')[1] if '@' in result['email'] else ''
        if domain not in BLOCKLISTED_DOMAINS:
            return result
        print(f"⚠️ web2 أعطى دومين محظور ({domain})، جاري تجربة mob2...")
    else:
        print("⚠️ web2 فشل، جاري تجربة mob2...")
    
    # Provider 3: mob2
    return create_email_mob2()

# ═══════════════════════════════════════════════════════
# ─── دوال فحص الـ Inbox — Multi-Provider ────────────
# ═══════════════════════════════════════════════════════

def check_inbox_for_code_tempmail_lol(email_token, max_attempts=20, wait_seconds=5):
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(f"{TEMPMAIL_LOL_URL}/auth/{email_token}", timeout=15)
            if response.status_code == 200:
                data = response.json()
                msgs = data.get('email', [])
                code = extract_verification_code(msgs)
                if code:
                    return code
        except Exception as e:
            print(f"tempmail.lol inbox: {e}")
        if attempt < max_attempts:
            time.sleep(wait_seconds)
    return None

def check_inbox_for_code_web2(email_token, max_attempts=20, wait_seconds=5):
    headers = WEB2_HEADERS.copy()
    headers['Authorization'] = f"Bearer {email_token}"
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(f"{WEB2_BASE_URL}/messages", headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                msgs = data if isinstance(data, list) else data.get('messages', [])
                code = extract_verification_code(msgs)
                if code:
                    return code
        except Exception as e:
            print(f"web2 inbox: {e}")
        if attempt < max_attempts:
            time.sleep(wait_seconds)
    return None

def check_inbox_for_code_mob2(email_token, max_attempts=20, wait_seconds=5):
    headers = MOB2_HEADERS.copy()
    headers['Authorization'] = email_token
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(f"{MOB2_BASE_URL}/messages", headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                msgs = data.get('messages', [])
                code = extract_verification_code(msgs)
                if code:
                    return code
        except Exception as e:
            print(f"mob2 inbox: {e}")
        if attempt < max_attempts:
            time.sleep(wait_seconds)
    return None

def check_inbox_for_code_smart(email_token, api_type, max_attempts=20, wait_seconds=5):
    if api_type == 'tempmail_lol':
        return check_inbox_for_code_tempmail_lol(email_token, max_attempts, wait_seconds)
    elif api_type == 'web2':
        return check_inbox_for_code_web2(email_token, max_attempts, wait_seconds)
    return check_inbox_for_code_mob2(email_token, max_attempts, wait_seconds)

def extract_verification_code(messages):
    for msg in messages:
        sender  = msg.get('from', '').lower()
        subject = msg.get('subject', '').lower()
        body    = msg.get('bodyPreview', msg.get('body', msg.get('textBody', msg.get('bodyHtml', ''))))
        if 'teli' in sender or 'teli' in subject or 'verification' in subject or 'verify' in subject or 'تحقق' in subject or 'رمز' in subject:
            match = re.search(r'\b(\d{6})\b', str(body))
            if match:
                return match.group(1)
    return None

# ==================== دوال TelliCall ====================

def generate_device_id():
    return ''.join(random.choices('0123456789abcdef', k=16))

def generate_peer_key():
    return str(random.randint(100, 999))

def get_base_headers(token=""):
    return {
        "host": "api.telicall.com",
        "x-request-id": str(uuid.uuid4()),
        "x-retry-count": "0",
        "user-agent": USER_AGENT,
        "x-app-version": APP_VERSION,
        "x-client-device-id": generate_device_id(),
        "x-lang": "ar",
        "x-os": "android",
        "x-os-version": OS_VERSION,
        "x-req-timestamp": str(int(time.time() * 1000)),
        "content-type": "application/json; charset=utf-8",
        "accept-encoding": "gzip",
        "x-token": token,
        "x-req-signature": "-1"
    }

def init_telicall_session():
    try:
        body = {
            "countryCode": "eg",
            "deviceName": "Infinix X698",
            "notificationToken": "",
            "oldToken": "",
            "peerKey": generate_peer_key(),
            "timeZone": "Africa/Cairo",
            "localizationKey": ""
        }
        response = requests.post(f"{TELICALL_BASE_URL}/init", json=body, headers=get_base_headers(), timeout=15)
        if response.status_code == 200:
            data = response.json()
            if 'result' in data and 'token' in data['result']:
                return data['result']['token']
    except Exception as e:
        print(f"init error: {e}")
    return None

def send_verification_email(tc_token, email):
    try:
        response = requests.post(
            f"{TELICALL_BASE_URL}/auth/send-email",
            json={"email": email},
            headers=get_base_headers(tc_token),
            timeout=15
        )
        if response.status_code == 200:
            data = response.json()
            if 'result' in data and 'reference' in data['result']:
                return data['result']['reference']
        else:
            try:
                err = data.get('meta', {}).get('errorMessage', '') if response.status_code != 200 else ''
            except:
                err = ''
            print(f"send email error: {response.status_code} - {err}")
    except Exception as e:
        print(f"send email error: {e}")
    return None

def verify_and_create_account(tc_token, reference, code):
    try:
        response = requests.post(
            f"{TELICALL_BASE_URL}/auth/verify-identity",
            json={"reference": reference, "code": str(code)},
            headers=get_base_headers(tc_token),
            timeout=15
        )
        if response.status_code == 200:
            data = response.json()
            if 'result' in data and 'user' in data['result']:
                return data['result']['user'], tc_token
    except Exception as e:
        print(f"verify error: {e}")
    return None, None

def get_account_balance(tc_token):
    try:
        response = requests.post(
            f"{TELICALL_BASE_URL}/get-landings",
            headers=get_base_headers(tc_token),
            timeout=15
        )
        if response.status_code == 200:
            data = response.json()
            if 'result' in data and 'coupon' in data['result']:
                return data['result']['coupon'].get('price', '0')
    except Exception as e:
        print(f"balance error: {e}")
    return None

# ==================== إنشاء حساب واحد ====================

def create_single_account(progress_callback=None):
    """إنشاء حساب TelliCall كامل مع multi-provider email."""
    def log(msg):
        if progress_callback:
            progress_callback(msg)
        print(msg)

    # الخطوة 1: إيميل مؤقت
    log("📧 جاري إنشاء إيميل مؤقت (tempmail.lol → web2 → mob2)...")
    email_data = create_email_smart()
    if not email_data:
        log("❌ فشل إنشاء الإيميل من جميع المصادر")
        return None

    email       = email_data['email']
    email_token = email_data['token']
    api_used    = email_data['api']
    domain      = email.split('@')[1] if '@' in email else ''
    
    if domain in BLOCKLISTED_DOMAINS:
        log(f"⚠️ الدومين {domain} محظور! جاري تجربة أخرى...")
        email_data = create_email_smart()
        if not email_data:
            log("❌ فشل إنشاء إيميل بدومين غير محظور")
            return None
        email       = email_data['email']
        email_token = email_data['token']
        api_used    = email_data['api']
        domain      = email.split('@')[1] if '@' in email else ''
    
    log(f"✅ إيميل: `{email}` (عبر {api_used}) [{domain}]")

    # الخطوة 2: جلسة TelliCall
    log("🔐 جاري تهيئة جلسة TelliCall...")
    tc_token = init_telicall_session()
    if not tc_token:
        log("❌ فشل تهيئة الجلسة")
        return None
    log("✅ تم الحصول على Token")

    # الخطوة 3: إرسال كود التحقق
    log("📤 إرسال كود التحقق إلى الإيميل...")
    reference = send_verification_email(tc_token, email)
    if not reference:
        log("❌ فشل إرسال الكود")
        return None
    log("✅ تم إرسال الكود")

    # الخطوة 4: انتظار الكود
    log("⏳ انتظار وصول الكود (حتى 100 ثانية)...")
    code = check_inbox_for_code_smart(email_token, api_used, max_attempts=20, wait_seconds=5)
    if not code:
        log("❌ لم يصل الكود في الوقت المحدد")
        return None
    log(f"✅ تم استلام الكود: `{code}`")

    # الخطوة 5: إنشاء الحساب
    log("🔑 جاري إنشاء الحساب...")
    user_data, final_token = verify_and_create_account(tc_token, reference, code)
    if not user_data:
        log("❌ فشل التحقق من الكود")
        return None
    log("🎉 تم إنشاء الحساب!")

    # الخطوة 6: الرصيد
    log("💰 جاري جلب الرصيد...")
    time.sleep(2)
    balance = get_account_balance(final_token)

    # الخطوة 7: حفظ في Dan.json
    device_id = generate_device_id()
    try:
        from filelock import FileLock
        lock_path = DAN_FILE + ".lock"
        lock = FileLock(lock_path, timeout=10)
        with lock:
            current = load_dan_accounts()
            current.append({
                "email": email,
                "x-client-device-id": device_id,
                "x-token": final_token,
                "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            encrypted = encrypt_text(json.dumps(current, indent=2, ensure_ascii=False), PASSWORD)
            with open(DAN_FILE, 'wb') as f:
                f.write(encrypted)
        log("✅ تم حفظ الحساب في Dan.json")
    except Exception as e:
        log(f"⚠️ فشل حفظ في Dan.json: {e}")

    return {
        'email':          email,
        'email_token':    email_token,
        'tc_token':       final_token,
        'user_id':        user_data.get('opaqueId'),
        'reference_code': user_data.get('referenceCode'),
        'balance':        balance or '0',
        'api_used':       api_used,
        'created_at':     datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

# ==================== هاندلرز البوت ====================

@bot.message_handler(commands=['start'])
def handle_start(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🚀 إنشاء حسابات", callback_data="create_accounts"),
        types.InlineKeyboardButton("📅 تاريخ الحسابات", callback_data="date_info"),
        types.InlineKeyboardButton("📬 الحسابات المراقبة", callback_data="list_watchers"),
        types.InlineKeyboardButton("🔕 إيقاف كل المراقبة", callback_data="stop_all_watchers"),
        types.InlineKeyboardButton("📋 كل الحسابات", callback_data="all_accounts"),
        types.InlineKeyboardButton("ℹ️ عن البوت", callback_data="about")
    )
    bot.send_message(
        message.chat.id,
        "👋 *أهلاً بك في بوت TelliCall v4!*\n\n"
        "🤖 أنا بنشئلك حسابات TelliCall أوتوماتيك\n"
        "💰 كل حساب برصيد *$0.25*\n"
        "📬 وبراقبلك صندوق كل حساب وأبعتلك الرسائل فور وصولها\n"
        "📅 ممكن تشوف تاريخ كل الحسابات وتفاصيلها\n\n"
        "🆕 v4: tempmail.lol كمزود أساسي — مفيش rate limit!\n\n"
        "اضغط على الزر اللي يناسبك:",
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['date'])
def handle_date_cmd(message):
    """عرض تاريخ الحسابات - أمر سريع"""
    _show_date_info(message.chat.id)

@bot.message_handler(commands=['accounts'])
def handle_accounts_cmd(message):
    """عرض كل الحسابات - أمر سريع"""
    _show_all_accounts(message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "date_info")
def handle_date_info(call):
    bot.answer_callback_query(call.id)
    _show_date_info(call.message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "all_accounts")
def handle_all_accounts(call):
    bot.answer_callback_query(call.id)
    _show_all_accounts(call.message.chat.id)

def _show_date_info(chat_id):
    """عرض معلومات التاريخ والإحصائيات للحسابات"""
    accounts = load_dan_accounts()
    
    if not accounts:
        bot.send_message(chat_id, "📭 *لا توجد حسابات في Dan.json*", parse_mode='Markdown')
        return
    
    total = len(accounts)
    
    today = datetime.now().strftime("%Y-%m-%d")
    today_count = 0
    yesterday = None
    try:
        from datetime import timedelta
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    except:
        pass
    yesterday_count = 0
    
    domain_stats = {}
    oldest = None
    newest = None
    
    for acc in accounts:
        created = acc.get('created', '')
        email = acc.get('email', '')
        domain = email.split('@')[1] if '@' in email else 'غير معروف'
        
        domain_stats[domain] = domain_stats.get(domain, 0) + 1
        
        if today in created:
            today_count += 1
        if yesterday and yesterday in created:
            yesterday_count += 1
        
        if created:
            if oldest is None or created < oldest:
                oldest = created
            if newest is None or created > newest:
                newest = created
    
    date_groups = {}
    for acc in accounts:
        created = acc.get('created', 'غير معروف')
        date_key = created[:10] if len(created) >= 10 else created
        if date_key not in date_groups:
            date_groups[date_key] = 0
        date_groups[date_key] += 1
    
    text = f"📅 *تاريخ الحسابات*\n"
    text += f"━━━━━━━━━━━━━━━━━━━━\n\n"
    text += f"📊 *إجمالي الحسابات:* `{total}`\n"
    text += f"📆 *حسابات اليوم:* `{today_count}`\n"
    if yesterday:
        text += f"📆 *حسابات أمس:* `{yesterday_count}`\n"
    text += f"🕐 *أقدم حساب:* `{oldest or 'غير معروف'}`\n"
    text += f"🕐 *أحدث حساب:* `{newest or 'غير معروف'}`\n"
    text += f"\n🌐 *الدومينات:*\n"
    for dom, cnt in sorted(domain_stats.items(), key=lambda x: -x[1]):
        status = "✅" if dom in WORKING_DOMAINS else ("🚫" if dom in BLOCKLISTED_DOMAINS else "❓")
        text += f"  {status} `{dom}`: {cnt}\n"
    text += f"\n📈 *حسابات حسب اليوم:*\n"
    for date_key in sorted(date_groups.keys(), reverse=True):
        count = date_groups[date_key]
        bar = "█" * min(count, 20)
        text += f"  `{date_key}`: {count} {bar}\n"
    
    bot.send_message(chat_id, text, parse_mode='Markdown')

def _show_all_accounts(chat_id):
    """عرض كل الحسابات مع التفاصيل"""
    accounts = load_dan_accounts()
    
    if not accounts:
        bot.send_message(chat_id, "📭 *لا توجد حسابات في Dan.json*", parse_mode='Markdown')
        return
    
    total = len(accounts)
    display_accounts = accounts[-20:] if len(accounts) > 20 else accounts
    start_idx = max(0, len(accounts) - 20)
    
    text = f"📋 *كل الحسابات ({total})*\n"
    if total > 20:
        text += f"_آخر 20 حساب من {total}_\n"
    text += f"━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for i, acc in enumerate(display_accounts):
        idx = start_idx + i + 1
        email = acc.get('email', 'غير معروف')
        domain = email.split('@')[1] if '@' in email else ''
        created = acc.get('created', 'غير معروف')
        token = acc.get('x-token', '')
        has_token = "✅" if token else "❌"
        
        text += f"*#{idx}* {has_token} `{email}`\n"
        text += f"  📅 `{created}`\n"
    
    with_token = sum(1 for a in accounts if a.get('x-token'))
    without_token = total - with_token
    
    text += f"\n━━━━━━━━━━━━━━━━━━━━\n"
    text += f"✅ بحساب Token: *{with_token}*\n"
    text += f"❌ بدون Token: *{without_token}*\n"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📅 التاريخ", callback_data="date_info"),
        types.InlineKeyboardButton("🚀 إنشاء حسابات", callback_data="create_accounts")
    )
    
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "about")
def handle_about(call):
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "ℹ️ *عن البوت v4*\n\n"
        "🔧 *مصادر الإيميل (3 مزودين):*\n"
        "• tempmail.lol (أساسي — مفيش rate limit!)\n"
        "• web2.temp-mail.org (احتياطي)\n"
        "• mob2.temp-mail.org (ملاذ أخير)\n\n"
        "✅ *الدومينات المسموحة:*\n"
        "• blaizesmp.net, chillart.org\n"
        "• dogmrp.com, for4u.net\n"
        "• basketrise.com, autofixmax.com\n"
        "• ifcoat.com, doreact.com\n"
        "• googxs.com, hitzcart.com\n"
        "• matkind.com\n\n"
        "🚫 *الدومينات المحظورة:*\n"
        "• wshu.net, 4nly.com\n"
        "• alf5.com, mtupu.com\n"
        "• guerrillamail* (كل الدومينات)\n\n"
        "📬 *المراقبة التلقائية:*\n"
        "بعد إنشاء كل حساب، البوت يراقب صندوق إيميله كل 30 ثانية\n"
        "أي رسالة جديدة تجيك فوراً في الدردشة\n\n"
        "📅 *خاصية التاريخ:*\n"
        "شوف كل حساباتك وتواريخها وإحصائياتها\n\n"
        "💡 من 1 لـ 10 حسابات في كل طلب",
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda c: c.data == "list_watchers")
def handle_list_watchers(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    
    active = []
    with inbox_watchers_lock:
        for email, data in inbox_watchers.items():
            if data['chat_id'] == chat_id:
                active.append((email, data['account_number'], data['started_at']))
    
    if not active:
        bot.send_message(chat_id, "📭 *لا توجد حسابات تحت المراقبة حالياً*", parse_mode='Markdown')
        return
    
    text = f"📬 *الحسابات المراقبة ({len(active)})*\n━━━━━━━━━━━━━━━━━━━━\n"
    markup = types.InlineKeyboardMarkup()
    
    for email, num, started in active:
        text += f"#{num} `{email}`\n  📅 بدأ: {started}\n"
        markup.add(types.InlineKeyboardButton(
            f"🔕 إيقاف #{num}",
            callback_data=f"stop_watch_{email}"
        ))
    
    markup.add(types.InlineKeyboardButton("🔕 إيقاف الكل", callback_data="stop_all_watchers"))
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("stop_watch_"))
def handle_stop_single_watcher(call):
    bot.answer_callback_query(call.id)
    email = call.data.replace("stop_watch_", "")
    
    if stop_inbox_watcher(email):
        bot.send_message(call.message.chat.id, f"🔕 *تم إيقاف مراقبة:*\n`{email}`", parse_mode='Markdown')
    else:
        bot.send_message(call.message.chat.id, f"⚠️ المراقبة مش شغالة أصلاً لـ `{email}`", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data == "stop_all_watchers")
def handle_stop_all_watchers(call):
    bot.answer_callback_query(call.id)
    stopped = stop_all_watchers_for_chat(call.message.chat.id)
    if stopped > 0:
        bot.send_message(call.message.chat.id, f"🔕 *تم إيقاف {stopped} مراقب*", parse_mode='Markdown')
    else:
        bot.send_message(call.message.chat.id, "📭 لا يوجد مراقبون نشطون")

@bot.callback_query_handler(func=lambda c: c.data == "create_accounts")
def handle_create_accounts(call):
    bot.answer_callback_query(call.id)
    
    markup = types.InlineKeyboardMarkup(row_width=5)
    buttons = [types.InlineKeyboardButton(f"{i} 🔑", callback_data=f"count_{i}") for i in range(1, 11)]
    markup.add(*buttons)
    markup.add(types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel"))
    
    bot.send_message(
        call.message.chat.id,
        "📊 *كم حساب تريد إنشاءه؟*\n\n"
        "⏱ كل حساب ~2 دقيقة\n"
        "📬 المراقبة تبدأ تلقائياً بعد إنشاء كل حساب\n"
        "📅 كل حساب بيتسجل في Dan.json\n"
        "🆕 v4: tempmail.lol كمزود أساسي — مفيش rate limit!",
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda c: c.data == "cancel")
def handle_cancel(call):
    bot.answer_callback_query(call.id)
    if call.message.chat.id in active_tasks:
        active_tasks[call.message.chat.id] = False
    bot.send_message(call.message.chat.id, "❌ تم الإلغاء")

@bot.callback_query_handler(func=lambda c: c.data.startswith("count_"))
def handle_count_selection(call):
    bot.answer_callback_query(call.id)
    count   = int(call.data.split("_")[1])
    chat_id = call.message.chat.id
    
    if active_tasks.get(chat_id) is True:
        bot.send_message(chat_id, "⚠️ عندك عملية جارية، خليها تخلص الأول!")
        return
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ ابدأ", callback_data=f"confirm_{count}"),
        types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel")
    )
    bot.send_message(
        chat_id,
        f"✅ *تأكيد الطلب*\n\n"
        f"📊 عدد الحسابات: *{count}*\n"
        f"⏱ الوقت التقريبي: *{count * 2} دقيقة*\n"
        f"📬 المراقبة تبدأ تلقائياً لكل حساب\n"
        f"📅 كل حساب بيتسجل في Dan.json\n\n"
        f"هل أنت متأكد؟",
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("confirm_"))
def handle_confirm(call):
    bot.answer_callback_query(call.id)
    count   = int(call.data.split("_")[1])
    chat_id = call.message.chat.id
    
    active_tasks[chat_id] = True
    threading.Thread(
        target=run_account_creation,
        args=(chat_id, count),
        daemon=True
    ).start()

# ==================== حلقة إنشاء الحسابات ====================

def run_account_creation(chat_id, count):
    """تشغيل إنشاء عدة حسابات بالتسلسل مع مراقبة تلقائية."""
    successful = []
    failed = 0
    
    bot.send_message(
        chat_id,
        f"🚀 *بدء إنشاء {count} حساب...*\n"
        f"📧 مزود البريد: tempmail.lol (أساسي) + temp-mail.org (احتياطي)\n"
        f"📬 المراقبة ستبدأ تلقائياً بعد كل حساب\n"
        f"✅ الدومينات: blaizesmp.net, chillart.org, dogmrp.com, for4u.net وغيرها",
        parse_mode='Markdown'
    )
    
    for i in range(1, count + 1):
        if not active_tasks.get(chat_id, True):
            bot.send_message(chat_id, "⛔ تم إيقاف العملية")
            break
        
        progress_msg = bot.send_message(
            chat_id,
            f"⚙️ *الحساب {i}/{count}*\n━━━━━━━━━━━━━━━━━━━━",
            parse_mode='Markdown'
        )
        progress_lines = [f"⚙️ *الحساب {i}/{count}*\n━━━━━━━━━━━━━━━━━━━━"]
        
        def update_progress(msg_text, _pm=progress_msg, _pl=progress_lines):
            _pl.append(msg_text)
            try:
                bot.edit_message_text(
                    "\n".join(_pl),
                    chat_id=chat_id,
                    message_id=_pm.message_id,
                    parse_mode='Markdown'
                )
            except Exception:
                pass
        
        account = create_single_account(progress_callback=update_progress)
        
        if account:
            account['number'] = i
            successful.append(account)
            
            bot.send_message(
                chat_id,
                f"✅ *حساب ناجح! ({i}/{count})*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📧 **الإيميل:** `{account['email']}`\n"
                f"🔑 **Token:** `{account['tc_token'][:50]}...`\n"
                f"🆔 **User ID:** `{account['user_id']}`\n"
                f"🎫 **كود الإحالة:** `{account['reference_code']}`\n"
                f"💰 **الرصيد:** `{account['balance']}` USD\n"
                f"📅 **تاريخ الإنشاء:** `{account['created_at']}`\n"
                f"🌐 **API:** `{account['api_used']}`\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📬 *تم تشغيل مراقبة صندوق البريد تلقائياً*",
                parse_mode='Markdown'
            )
            
            start_inbox_watcher(chat_id, account)
        
        else:
            failed += 1
            bot.send_message(
                chat_id,
                f"❌ *فشل الحساب {i}/{count}*",
                parse_mode='Markdown'
            )
        
        if i < count:
            wait = random.randint(10, 20)
            bot.send_message(chat_id, f"⏳ انتظار {wait} ثانية...")
            time.sleep(wait)
    
    total = len(successful)
    total_balance = sum(float(a.get('balance', 0) or 0) for a in successful)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🔄 إنشاء المزيد", callback_data="create_accounts"),
        types.InlineKeyboardButton("📅 تاريخ الحسابات", callback_data="date_info"),
        types.InlineKeyboardButton("📬 الحسابات المراقبة", callback_data="list_watchers")
    )
    
    bot.send_message(
        chat_id,
        f"📊 *النتائج النهائية*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ الناجحة: *{total}*\n"
        f"❌ الفاشلة: *{failed}*\n"
        f"📈 نسبة النجاح: *{(total/max(count,1))*100:.0f}%*\n"
        f"💰 إجمالي الرصيد: *${total_balance:.2f}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📬 *{total} مراقب بريد نشط في الخلفية*\n"
        f"📅 كل الحسابات محفوظة في Dan.json",
        parse_mode='Markdown',
        reply_markup=markup
    )
    
    active_tasks.pop(chat_id, None)

# ==================== أمر الإدمن ====================

@bot.message_handler(commands=['admin'])
def handle_admin(message):
    if message.chat.id != OWNER_ID:
        bot.send_message(message.chat.id, "⛔ غير مصرح")
        return
    
    dan_accounts = load_dan_accounts()
    dan_count = len(dan_accounts)
    with_token = sum(1 for a in dan_accounts if a.get('x-token'))
    
    with inbox_watchers_lock:
        total_watchers = len(inbox_watchers)
    
    bot.send_message(
        message.chat.id,
        f"👑 *لوحة الإدمن*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📂 *Dan.json:*\n"
        f"  • إجمالي: *{dan_count}* حساب\n"
        f"  • بـ Token: *{with_token}*\n"
        f"  • بدون: *{dan_count - with_token}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📬 *المراقبة:*\n"
        f"  • نشط: *{total_watchers}* مراقب\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📧 *مزودين البريد:*\n"
        f"  1. tempmail.lol (أساسي)\n"
        f"  2. temp-mail.org/web2\n"
        f"  3. temp-mail.org/mob2",
        parse_mode='Markdown'
    )

# ==================== تشغيل البوت ====================

if __name__ == "__main__":
    print("=" * 50)
    print("🤖 TelliCall Bot v4 — Multi-Provider Email")
    print("=" * 50)
    print(f"📧 Provider 1: tempmail.lol (PRIMARY)")
    print(f"📧 Provider 2: temp-mail.org/web2 (FALLBACK)")
    print(f"📧 Provider 3: temp-mail.org/mob2 (LAST RESORT)")
    print(f"✅ Working domains: {len(WORKING_DOMAINS)}")
    print(f"🚫 Blocklisted domains: {len(BLOCKLISTED_DOMAINS)}")
    print("=" * 50)
    
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Bot error: {e}")
            time.sleep(5)
