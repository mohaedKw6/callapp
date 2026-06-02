#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TelliCall Bot v5 - hitzcart.com ONLY + IP Rotation
===================================================
- ONLY hitzcart.com domain (fixed)
- web2.temp-mail.org as the only email provider
- Egyptian IP rotation on every Telicall request
- Continuous account creation
- Inbox watcher for new messages
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

# ==================== Bot Settings ====================
BOT_TOKEN = "7622961655:AAEMyav7MYmZMRNADkzj8KCIv2yEx2vpxd4"
OWNER_ID = 962731079

bot = telebot.TeleBot(BOT_TOKEN)

# ==================== TelliCall Settings ====================
TELICALL_BASE_URL = "https://api.telicall.com"
APP_VERSION = "1.2.1"
OS_VERSION = "11"
USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 11; Infinix X698 Build/RP1A.200720.011)"
FIXED_DOMAIN = "hitzcart.com"

# ==================== Dan.json ====================
DAN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Dan.json")
PASSWORD = "@@@GMAQ@@@"

# ==================== web2.temp-mail.org ====================
WEB2_BASE_URL = "https://web2.temp-mail.org"
WEB2_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Origin': 'https://temp-mail.org',
    'Referer': 'https://temp-mail.org/',
    'Content-Type': 'application/json'
}

# ==================== Egyptian IP Rotation ====================
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

# ==================== State ====================
active_tasks = {}
inbox_watchers = {}
inbox_watchers_lock = threading.Lock()
_stop_events = {}  # {chat_id: Event}

# ==================== Encryption ====================

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
    if not os.path.exists(DAN_FILE):
        return []
    try:
        raw = open(DAN_FILE, 'rb').read()
        try:
            return json.loads(decrypt_file(DAN_FILE, PASSWORD))
        except:
            return json.loads(raw.decode('utf-8'))
    except:
        return []

def save_dan_account(email, device_id, token):
    try:
        from filelock import FileLock
        lock_path = DAN_FILE + ".lock"
        lock = FileLock(lock_path, timeout=10)
        with lock:
            current = load_dan_accounts()
            current.append({
                "email": email,
                "x-client-device-id": device_id,
                "x-token": token,
                "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            encrypted = encrypt_text(json.dumps(current, indent=2, ensure_ascii=False), PASSWORD)
            with open(DAN_FILE, 'wb') as f:
                f.write(encrypted)
    except Exception as e:
        print(f"Save error: {e}")

# ═══════════════════════════════════════════════════════
# ─── Email: web2 + hitzcart.com ONLY ─────────────────
# ═══════════════════════════════════════════════════════

def create_hitzcart_email(stop_event=None):
    """Create email with ONLY hitzcart.com domain - keeps trying until it gets one"""
    attempts = 0
    discarded = 0
    while True:
        if stop_event and stop_event.is_set():
            return None
        try:
            r = requests.post(f"{WEB2_BASE_URL}/mailbox", headers=WEB2_HEADERS, timeout=15)
            attempts += 1
            if r.status_code in [200, 201]:
                data = r.json()
                email = data.get('mailbox', '')
                token = data.get('token', '')
                if email and token:
                    domain = email.split('@')[1] if '@' in email else ''
                    if domain == FIXED_DOMAIN:
                        return {'email': email, 'token': token, 'api': 'web2', 'attempts': attempts, 'discarded': discarded}
                    else:
                        discarded += 1
                        # Not hitzcart.com - discard and retry immediately
            elif r.status_code == 429:
                time.sleep(2)
            else:
                time.sleep(1)
        except Exception as e:
            print(f"web2 create error: {e}")
            time.sleep(2)

def check_web2_inbox(email_token):
    try:
        headers = WEB2_HEADERS.copy()
        headers['Authorization'] = f"Bearer {email_token}"
        r = requests.get(f"{WEB2_BASE_URL}/messages", headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else data.get('messages', [])
    except:
        pass
    return []

def get_all_messages_web2(email_token):
    return check_web2_inbox(email_token)

def wait_for_otp(email_token, stop_event=None, max_wait=90):
    """Wait for OTP code from web2 inbox"""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if stop_event and stop_event.is_set():
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

def extract_verification_code(messages):
    for msg in messages:
        sender  = msg.get('from', '').lower()
        subject = msg.get('subject', '').lower()
        body    = msg.get('bodyPreview', msg.get('body', msg.get('textBody', msg.get('bodyHtml', ''))))
        if 'teli' in sender or 'teli' in subject or 'verification' in subject or 'verify' in subject:
            match = re.search(r'\b(\d{6})\b', str(body))
            if match:
                return match.group(1)
    return None

# ═══════════════════════════════════════════════════════
# ─── TelliCall API ──────────────────────────────────
# ═══════════════════════════════════════════════════════

def generate_device_id():
    return ''.join(random.choices('0123456789abcdef', k=16))

def get_base_headers(token="", ip=None):
    if ip is None:
        ip = rand_eg_ip()
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
        "x-req-signature": "-1",
        "x-real-ip": ip,
        "x-currency": "EGP",
    }

def init_telicall_session():
    ip = rand_eg_ip()
    try:
        body = {
            "countryCode": "eg",
            "deviceName": "Infinix X698",
            "notificationToken": "",
            "oldToken": "",
            "peerKey": str(random.randint(100, 999)),
            "timeZone": "Africa/Cairo",
            "localizationKey": ""
        }
        response = requests.post(f"{TELICALL_BASE_URL}/init", json=body, headers=get_base_headers(ip=ip), timeout=15)
        if response.status_code == 200:
            data = response.json()
            if 'result' in data and 'token' in data['result']:
                return data['result']['token']
    except Exception as e:
        print(f"init error: {e}")
    return None

def send_verification_email(tc_token, email):
    ip = rand_eg_ip()
    try:
        response = requests.post(
            f"{TELICALL_BASE_URL}/auth/send-email",
            json={"email": email},
            headers=get_base_headers(tc_token, ip=ip),
            timeout=15
        )
        if response.status_code == 200:
            data = response.json()
            if 'result' in data and 'reference' in data['result']:
                return data['result']['reference']
        else:
            try:
                err = response.json().get('meta', {}).get('errorMessage', '') if response.status_code != 200 else ''
            except:
                err = ''
            print(f"send email error: {response.status_code} - {err}")
    except Exception as e:
        print(f"send email error: {e}")
    return None

def verify_and_create_account(tc_token, reference, code):
    ip = rand_eg_ip()
    try:
        response = requests.post(
            f"{TELICALL_BASE_URL}/auth/verify-identity",
            json={"reference": reference, "code": str(code)},
            headers=get_base_headers(tc_token, ip=ip),
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
    ip = rand_eg_ip()
    try:
        response = requests.post(
            f"{TELICALL_BASE_URL}/get-landings",
            headers=get_base_headers(tc_token, ip=ip),
            timeout=15
        )
        if response.status_code == 200:
            data = response.json()
            if 'result' in data and 'coupon' in data['result']:
                return data['result']['coupon'].get('price', '0')
    except:
        pass
    return None

# ═══════════════════════════════════════════════════════
# ─── Inbox Watcher ──────────────────────────────────
# ═══════════════════════════════════════════════════════

def get_message_id(msg):
    return msg.get('id') or msg.get('_id') or msg.get('uid') or str(msg.get('date', '')) + msg.get('from', '')

def format_message_notification(account_email, msg, account_number=None):
    sender  = msg.get('from', '')
    subject = msg.get('subject', '')
    body    = msg.get('bodyPreview') or msg.get('textBody') or msg.get('body', '')
    if len(str(body)) > 400:
        body = str(body)[:400] + "..."
    label = f"#{account_number}" if account_number else ""
    return (
        f"*رسالة جديدة {label}*\n"
        f"الحساب: `{account_email}`\n"
        f"المرسل: `{sender}`\n"
        f"الموضوع: `{subject}`\n"
        f"المحتوى:\n{body}"
    )

def inbox_watcher_loop(chat_id, account_email, email_token, account_number, stop_event):
    print(f"[Watcher] START {account_email}")
    seen_ids = set()
    for m in get_all_messages_web2(email_token):
        seen_ids.add(get_message_id(m))

    while not stop_event.is_set():
        for _ in range(30):
            if stop_event.is_set():
                break
            time.sleep(1)
        if stop_event.is_set():
            break
        try:
            msgs = get_all_messages_web2(email_token)
            for msg in msgs:
                mid = get_message_id(msg)
                if mid not in seen_ids:
                    seen_ids.add(mid)
                    notification = format_message_notification(account_email, msg, account_number)
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("إيقاف مراقبة", callback_data=f"stop_watch_{account_email}"))
                    try:
                        bot.send_message(chat_id, notification, parse_mode='Markdown', reply_markup=markup)
                    except:
                        pass
        except:
            pass
    print(f"[Watcher] STOP {account_email}")

def start_inbox_watcher(chat_id, account):
    email       = account['email']
    email_token = account['email_token']
    acct_num    = account.get('number', '?')
    stop_event = threading.Event()
    thread = threading.Thread(
        target=inbox_watcher_loop,
        args=(chat_id, email, email_token, acct_num, stop_event),
        daemon=True
    )
    thread.start()
    with inbox_watchers_lock:
        inbox_watchers[email] = {
            'thread': thread, 'stop': stop_event,
            'chat_id': chat_id, 'account_number': acct_num
        }
    return True

def stop_inbox_watcher(email):
    with inbox_watchers_lock:
        if email in inbox_watchers:
            inbox_watchers[email]['stop'].set()
            del inbox_watchers[email]
            return True
    return False

def stop_all_watchers_for_chat(chat_id):
    to_stop = []
    with inbox_watchers_lock:
        for email, data in inbox_watchers.items():
            if data['chat_id'] == chat_id:
                to_stop.append(email)
    for email in to_stop:
        stop_inbox_watcher(email)
    return len(to_stop)

# ═══════════════════════════════════════════════════════
# ─── Account Creation ───────────────────────────────
# ═══════════════════════════════════════════════════════

def create_single_account(chat_id, account_num, stop_event=None, progress_callback=None):
    """Create one complete TelliCall account with hitzcart.com email"""
    def log(msg):
        if progress_callback:
            progress_callback(msg)
        print(msg)

    # Step 1: Create hitzcart.com email
    log(f"جاري إنشاء إيميل @{FIXED_DOMAIN}...")
    email_data = create_hitzcart_email(stop_event)
    if not email_data:
        log("تم الإلغاء")
        return None

    email       = email_data['email']
    email_token = email_data['token']
    attempts    = email_data['attempts']
    discarded   = email_data['discarded']
    log(f"إيميل: `{email}` (محاولات: {attempts}, رفض: {discarded})")

    # Step 2: TelliCall session
    log("تهيئة جلسة TelliCall (IP جديد)...")
    tc_token = init_telicall_session()
    if not tc_token:
        log("فشل تهيئة الجلسة")
        return None
    log("تم الحصول على Token")

    # Step 3: Send verification
    log("إرسال كود التحقق...")
    reference = send_verification_email(tc_token, email)
    if not reference:
        log("فشل إرسال الكود")
        return None
    log("تم إرسال الكود")

    # Step 4: Wait for OTP
    log("انتظار الكود...")
    code = wait_for_otp(email_token, stop_event, max_wait=90)
    if not code:
        log("لم يصل الكود")
        return None
    log(f"الكود: `{code}`")

    # Step 5: Verify
    log("إنشاء الحساب...")
    user_data, final_token = verify_and_create_account(tc_token, reference, code)
    if not user_data:
        log("فشل التحقق")
        return None
    log("تم إنشاء الحساب!")

    # Step 6: Balance
    time.sleep(2)
    balance = get_account_balance(final_token)

    # Step 7: Save
    device_id = generate_device_id()
    save_dan_account(email, device_id, final_token)
    log("تم الحفظ في Dan.json")

    return {
        'email':          email,
        'email_token':    email_token,
        'tc_token':       final_token,
        'user_id':        user_data.get('opaqueId'),
        'reference_code': user_data.get('referenceCode'),
        'balance':        balance or '0',
        'created_at':     datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

# ═══════════════════════════════════════════════════════
# ─── Bot Handlers ───────────────────────────────────
# ═══════════════════════════════════════════════════════

@bot.message_handler(commands=['start'])
def handle_start(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("إنشاء حسابات", callback_data="create_accounts"),
        types.InlineKeyboardButton("تاريخ الحسابات", callback_data="date_info"),
        types.InlineKeyboardButton("الحسابات المراقبة", callback_data="list_watchers"),
        types.InlineKeyboardButton("إيقاف كل المراقبة", callback_data="stop_all_watchers"),
        types.InlineKeyboardButton("كل الحسابات", callback_data="all_accounts"),
        types.InlineKeyboardButton("عن البوت", callback_data="about")
    )
    bot.send_message(
        message.chat.id,
        "*أهلاً بك في بوت TelliCall v5!*\n\n"
        "إنشاء حسابات TelliCall أوتوماتيك\n"
        f"الدومين: *@{FIXED_DOMAIN}* فقط\n"
        "كل طلب بـ IP مصري مختلف\n"
        "كل حساب برصيد *$0.25*\n"
        "مراقبة صندوق البريد تلقائية\n\n"
        "اضغط على الزر المناسب:",
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['date'])
def handle_date_cmd(message):
    _show_date_info(message.chat.id)

@bot.message_handler(commands=['accounts'])
def handle_accounts_cmd(message):
    _show_all_accounts(message.chat.id)

@bot.message_handler(commands=['stop'])
def handle_stop_cmd(message):
    chat_id = message.chat.id
    if chat_id in _stop_events:
        _stop_events[chat_id].set()
        bot.send_message(chat_id, "تم إيقاف العملية")
    else:
        bot.send_message(chat_id, "مفيش عملية جارية")

@bot.callback_query_handler(func=lambda c: c.data == "date_info")
def handle_date_info(call):
    bot.answer_callback_query(call.id)
    _show_date_info(call.message.chat.id)

@bot.callback_query_handler(func=lambda c: c.data == "all_accounts")
def handle_all_accounts(call):
    bot.answer_callback_query(call.id)
    _show_all_accounts(call.message.chat.id)

def _show_date_info(chat_id):
    accounts = load_dan_accounts()
    if not accounts:
        bot.send_message(chat_id, "لا توجد حسابات", parse_mode='Markdown')
        return

    total = len(accounts)
    today = datetime.now().strftime("%Y-%m-%d")
    today_count = sum(1 for a in accounts if today in a.get('created', ''))

    domain_stats = {}
    for acc in accounts:
        email = acc.get('email', '')
        domain = email.split('@')[1] if '@' in email else '?'
        domain_stats[domain] = domain_stats.get(domain, 0) + 1

    text = f"*تاريخ الحسابات*\n\n"
    text += f"الإجمالي: `{total}`\n"
    text += f"اليوم: `{today_count}`\n\n"
    text += f"الدومينات:\n"
    for dom, cnt in sorted(domain_stats.items(), key=lambda x: -x[1]):
        text += f"  `{dom}`: {cnt}\n"

    bot.send_message(chat_id, text, parse_mode='Markdown')

def _show_all_accounts(chat_id):
    accounts = load_dan_accounts()
    if not accounts:
        bot.send_message(chat_id, "لا توجد حسابات", parse_mode='Markdown')
        return

    total = len(accounts)
    display = accounts[-20:] if len(accounts) > 20 else accounts

    text = f"*كل الحسابات ({total})*\n\n"
    for i, acc in enumerate(display):
        email = acc.get('email', '?')
        created = acc.get('created', '?')
        text += f"#{total - len(display) + i + 1} `{email}`\n  {created}\n"

    bot.send_message(chat_id, text, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data == "about")
def handle_about(call):
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        f"*عن البوت v5*\n\n"
        f"الدومين: *@{FIXED_DOMAIN}* فقط\n"
        f"المزود: web2.temp-mail.org فقط\n"
        f"كل طلب بـ IP مصري مختلف\n"
        f"إنشاء مستمر بدون توقف",
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
                active.append(email)
    if not active:
        bot.send_message(chat_id, "لا توجد حسابات تحت المراقبة")
        return
    text = f"*الحسابات المراقبة ({len(active)})*\n"
    for email in active:
        text += f"  `{email}`\n"
    bot.send_message(chat_id, text, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data.startswith("stop_watch_"))
def handle_stop_single_watcher(call):
    bot.answer_callback_query(call.id)
    email = call.data.replace("stop_watch_", "")
    if stop_inbox_watcher(email):
        bot.send_message(call.message.chat.id, f"تم إيقاف مراقبة: `{email}`", parse_mode='Markdown')

@bot.callback_query_handler(func=lambda c: c.data == "stop_all_watchers")
def handle_stop_all_watchers(call):
    bot.answer_callback_query(call.id)
    stopped = stop_all_watchers_for_chat(call.message.chat.id)
    bot.send_message(call.message.chat.id, f"تم إيقاف {stopped} مراقب")

@bot.callback_query_handler(func=lambda c: c.data == "create_accounts")
def handle_create_accounts(call):
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup(row_width=5)
    buttons = [types.InlineKeyboardButton(f"{i}", callback_data=f"count_{i}") for i in range(1, 11)]
    markup.add(*buttons)
    markup.add(types.InlineKeyboardButton("إلغاء", callback_data="cancel"))
    bot.send_message(
        call.message.chat.id,
        f"*كم حساب تريد إنشاءه؟*\n\n"
        f"الدومين: *@{FIXED_DOMAIN}* فقط\n"
        f"كل طلب بـ IP مصري مختلف\n"
        f"الإنشاء مستمر بدون توقف",
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda c: c.data == "cancel")
def handle_cancel(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    if chat_id in _stop_events:
        _stop_events[chat_id].set()
    bot.send_message(chat_id, "تم الإلغاء")

@bot.callback_query_handler(func=lambda c: c.data.startswith("count_"))
def handle_count_selection(call):
    bot.answer_callback_query(call.id)
    count   = int(call.data.split("_")[1])
    chat_id = call.message.chat.id

    if active_tasks.get(chat_id) is True:
        bot.send_message(chat_id, "عندك عملية جارية، استنى تخلص أو اكتب /stop")
        return

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("ابدأ", callback_data=f"confirm_{count}"),
        types.InlineKeyboardButton("إلغاء", callback_data="cancel")
    )
    bot.send_message(
        chat_id,
        f"*تأكيد*\n\nعدد الحسابات: *{count}*\nالدومين: *@{FIXED_DOMAIN}*\nIP مختلف لكل طلب",
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("confirm_"))
def handle_confirm(call):
    bot.answer_callback_query(call.id)
    count   = int(call.data.split("_")[1])
    chat_id = call.message.chat.id

    stop_event = threading.Event()
    _stop_events[chat_id] = stop_event
    active_tasks[chat_id] = True

    threading.Thread(
        target=run_account_creation,
        args=(chat_id, count, stop_event),
        daemon=True
    ).start()

# ═══════════════════════════════════════════════════════
# ─── Account Creation Loop ──────────────────────────
# ═══════════════════════════════════════════════════════

def run_account_creation(chat_id, count, stop_event):
    """Create accounts continuously"""
    successful = []
    failed = 0

    bot.send_message(
        chat_id,
        f"*بدء إنشاء {count} حساب...*\n"
        f"الدومين: *@{FIXED_DOMAIN}*\n"
        f"IP مختلف لكل طلب",
        parse_mode='Markdown'
    )

    for i in range(1, count + 1):
        if stop_event.is_set():
            bot.send_message(chat_id, "تم الإيقاف")
            break

        progress_msg = bot.send_message(chat_id, f"الحساب {i}/{count}...")

        progress_lines = [f"الحساب {i}/{count}"]

        def update_progress(msg_text, _pm=progress_msg, _pl=progress_lines):
            _pl.append(msg_text)
            try:
                bot.edit_message_text("\n".join(_pl), chat_id=chat_id, message_id=_pm.message_id, parse_mode='Markdown')
            except:
                pass

        account = create_single_account(chat_id, i, stop_event, progress_callback=update_progress)

        if account:
            account['number'] = i
            successful.append(account)

            bot.send_message(
                chat_id,
                f"*حساب ناجح! ({i}/{count})*\n"
                f"الإيميل: `{account['email']}`\n"
                f"الرصيد: `{account['balance']}` USD\n"
                f"التاريخ: `{account['created_at']}`",
                parse_mode='Markdown'
            )

            start_inbox_watcher(chat_id, account)
        else:
            failed += 1
            bot.send_message(chat_id, f"فشل الحساب {i}/{count}")

        # Short pause between accounts
        if i < count and not stop_event.is_set():
            time.sleep(random.randint(3, 8))

    total = len(successful)
    total_balance = sum(float(a.get('balance', 0) or 0) for a in successful)

    bot.send_message(
        chat_id,
        f"*النتائج*\n\n"
        f"الناجحة: *{total}*\n"
        f"الفاشلة: *{failed}*\n"
        f"الرصيد: *${total_balance:.2f}*",
        parse_mode='Markdown'
    )

    active_tasks.pop(chat_id, None)
    _stop_events.pop(chat_id, None)

# ==================== Admin ====================

@bot.message_handler(commands=['admin'])
def handle_admin(message):
    if message.chat.id != OWNER_ID:
        bot.send_message(message.chat.id, "غير مصرح")
        return

    dan_accounts = load_dan_accounts()
    dan_count = len(dan_accounts)

    with inbox_watchers_lock:
        total_watchers = len(inbox_watchers)

    bot.send_message(
        message.chat.id,
        f"*لوحة الإدمن*\n\n"
        f"Dan.json: *{dan_count}* حساب\n"
        f"المراقبة: *{total_watchers}* نشط\n"
        f"الدومين: *@{FIXED_DOMAIN}*",
        parse_mode='Markdown'
    )

# ==================== Run Bot ====================

if __name__ == "__main__":
    print("=" * 50)
    print("TelliCall Bot v5 - hitzcart.com ONLY")
    print(f"Domain: @{FIXED_DOMAIN}")
    print(f"Provider: web2.temp-mail.org ONLY")
    print(f"IPs: Egyptian rotation")
    print("=" * 50)

    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Bot error: {e}")
            time.sleep(5)
