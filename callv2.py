#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║                      📞 BOT CALL                             ║
║              🔧 نظام متكامل مع لوحة أدمن                     ║
║              🤖 Telegram Bot Interface                        ║
╚══════════════════════════════════════════════════════════════╝
"""

import requests
import json
import uuid
import time
import random
import socket
import hashlib
import base64
import os
import re
import wave
import threading
import string
import ssl
import struct
import sys
import io
import queue
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# ─── Load .env file FIRST ────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(_env_path, override=False)  # لا يطغى على env vars الموجودة
except ImportError:
    pass  # python-dotenv مش مثبت، هنستخدم env vars عادية

# ─── قفل للأمان المتزامن (Thread-Safety) ─────────────────────────────────────
_token_lock   = threading.Lock()          # قفل سحب التوكنات
_file_lock    = threading.Lock()          # قفل الكتابة في الملفات
_call_sem     = threading.Semaphore(500)  # حد أقصى 500 مكالمة في وقت واحد
_call_executor = ThreadPoolExecutor(max_workers=500, thread_name_prefix="call_worker")

# ─── خطط الاشتراك الشهري ─────────────────────────────────────────────────────
MONTHLY_PLANS = {
    "basic":     {"name": "أساسي",    "emoji": "🥉", "calls": 30,     "price": 3.00},
    "pro":       {"name": "محترف",    "emoji": "🥇", "calls": 100,    "price": 6.00},
    "unlimited": {"name": "غير محدود","emoji": "💎", "calls": 999999, "price": 20.00},
}

APP_SUBSCRIPTION_PLANS = {
    "app_basic":     {"name": "أساسي",    "emoji": "🥉", "calls": 30,     "price": 3.00},
    "app_pro":       {"name": "محترف",    "emoji": "🥇", "calls": 100,    "price": 6.00},
    "app_unlimited": {"name": "غير محدود","emoji": "💎", "calls": 999999, "price": 20.00},
}

BOT_VERSION = "5.2.0"

SUBSCRIPTION_SELLERS = [
    {"username": "@G_M_A_Q", "name": "⛥-𝔾_𝕄_𝔸_ℚ-⛥"},
    {"username": "@llllllIlIlIlIlIlIlIl", "name": "الوكيل"},
]

def _md(text: str) -> str:
    """Escape special Markdown characters so text displays correctly in Telegram Markdown."""
    return text.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`")

LANGUAGES = {
    "ar": {"name": "العربية", "emoji": "🇸🇦", "dir": "rtl"},
    "en": {"name": "English", "emoji": "🇬🇧", "dir": "ltr"},
    "ru": {"name": "Русский", "emoji": "🇷🇺", "dir": "ltr"},
    "es": {"name": "Español", "emoji": "🇪🇸", "dir": "ltr"},
    "pt": {"name": "Português", "emoji": "🇧🇷", "dir": "ltr"},
    "id": {"name": "Bahasa Indonesia", "emoji": "🇮🇩", "dir": "ltr"},
    "uk": {"name": "Українська", "emoji": "🇺🇦", "dir": "ltr"},
    "uz": {"name": "O'zbek", "emoji": "🇺🇿", "dir": "ltr"},
    "fa": {"name": "فارسی", "emoji": "🇮🇷", "dir": "rtl"},
    "hi": {"name": "हिन्दी", "emoji": "🇮🇳", "dir": "ltr"},
}

def get_user_lang(user_id) -> str:
    users_db = load_users_db()
    return users_db.get(str(user_id), {}).get("language", "ar")

def set_user_lang(user_id, lang_code: str):
    users_db = load_users_db()
    uid = str(user_id)
    if uid not in users_db:
        users_db[uid] = {"usage": 0, "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    users_db[uid]["language"] = lang_code
    save_users_db(users_db)

# ═══════════════════════════════════════════════════════════════════════════════
#  i18n — نظام الترجمة الشامل
# ═══════════════════════════════════════════════════════════════════════════════
_TR = {
    # ─── الرئيسية ───
    "welcome_title": {"ar": "🌟 *مرحباً بك في بوت المكالمات* 🌟", "en": "🌟 *Welcome to Call Bot* 🌟"},
    "choose_menu": {"ar": "*اختر من القائمة أدناه:*", "en": "*Choose from the menu below:*"},
    "main_menu": {"ar": "🌟 القائمة الرئيسية", "en": "🌟 Main Menu"},
    "banned": {"ar": "🚫 أنت محظور", "en": "🚫 You are banned"},
    "banned_full": {"ar": "🚫 *تم حظرك من استخدام البوت*\n\nللتواصل مع الدعم: ", "en": "🚫 *You have been banned from using this bot*\n\nContact support: "},
    "must_sub": {"ar": "📢 يجب الاشتراك في القنوات أولاً", "en": "📢 You must subscribe to the channels first"},
    "admin_badge": {"ar": "👑 *أنت أدمن*", "en": "👑 *You are an admin*"},
    "premium_badge": {"ar": "⭐ *أنت مستخدم مميز — مكالمات غير محدودة*", "en": "⭐ *You are a premium user — unlimited calls*"},
    "balance_label": {"ar": "💰 *رصيدك:*", "en": "💰 *Your balance:*"},
    "can_call": {"ar": "✅ يمكنك إجراء مكالمة", "en": "✅ You can make a call"},
    "referrals_label": {"ar": "👥 *إحالاتك:*", "en": "👥 *Your referrals:*"},
    "send_refer": {"ar": "أرسل /refer للحصول على رابط الإحالة", "en": "Send /refer to get your referral link"},
    "daily_bonus_added": {"ar": "🎁 *تم إضافة مكافأة يومية*", "en": "🎁 *Daily bonus added*"},

    # ─── الاتصال ───
    "send_phone": {"ar": "📞 أرسل رقم الهاتف:\nمثال: `+966512345678`", "en": "📞 Send the phone number:\nExample: `+966512345678`"},
    "multi_call": {"ar": "🔄 مكالمات متعددة (5 محاولات)\n\n📞 أرسل الرقم:\nمثال: `+966512345678`", "en": "🔄 Multi call (5 attempts)\n\n📞 Send the number:\nExample: `+966512345678`"},
    "invalid_number": {"ar": "❌ رقم غير صحيح.\nمثال: +966512345678", "en": "❌ Invalid number.\nExample: +966512345678"},
    "calling": {"ar": "⏳ جاري الاتصال...", "en": "⏳ Calling..."},
    "call_single": {"ar": "📞 مكالمة واحدة", "en": "📞 Single call"},
    "call_attempts": {"ar": "🔄 {n} محاولة", "en": "🔄 {n} attempts"},
    "call_success": {"ar": "✅ انتهت المكالمة بنجاح!", "en": "✅ Call ended successfully!"},
    "call_failed": {"ar": "❌ فشلت المكالمة", "en": "❌ Call failed"},
    "no_access": {"ar": "❌", "en": "❌"},
    "contact_premium": {"ar": "\n\nللاشتراك المميز تواصل: ", "en": "\n\nFor premium subscription contact: "},

    # ─── الصوت ───
    "voice_exists": {"ar": "🎤 يوجد صوت محمّل ({sec} ثانية)\n\nأرسل صوت جديد لتغييره", "en": "🎤 Voice already loaded ({sec} seconds)\n\nSend a new voice to replace it"},
    "voice_send": {"ar": "🎤 أرسل صوت (حد أقصى 60 ثانية)\nسيتم تشغيله عند الرد على المكالمة", "en": "🎤 Send a voice note (max 60 seconds)\nIt will play when the call is answered"},
    "voice_too_long": {"ar": "⚠️ الصوت طويل جداً ({dur}s)\nالحد الأقصى 60 ثانية", "en": "⚠️ Voice too long ({dur}s)\nMaximum is 60 seconds"},
    "voice_loading": {"ar": "⏳ جاري تحميل الصوت...", "en": "⏳ Loading voice..."},
    "voice_loaded": {"ar": "✅ تم تحميل الصوت!\n⏱️ المدة: {dur} ثانية\n\n📞 أرسل رقم الهاتف:", "en": "✅ Voice loaded!\n⏱️ Duration: {dur} seconds\n\n📞 Send the phone number:"},
    "voice_fail": {"ar": "❌ فشل تحميل الصوت", "en": "❌ Failed to load voice"},
    "voice_empty": {"ar": "❌ ملف الصوت فاضي", "en": "❌ Voice file is empty"},
    "voice_convert_fail": {"ar": "❌ فشل تحويل الصوت", "en": "❌ Failed to convert voice"},
    "voice_not_text": {"ar": "🎤 أرسل رسالة صوتية مش نص\nاضغط على ميكروفون التيليجرام وسجّل", "en": "🎤 Send a voice note, not text\nPress the microphone in Telegram and record"},

    # ─── الرصيد ───
    "your_balance": {"ar": "💰 *رصيدك:*", "en": "💰 *Your balance:*"},
    "call_cost": {"ar": "📞 *سعر المكالمة:*", "en": "📞 *Call cost:*"},
    "ref_link": {"ar": "🔗 رابط الإحالة الخاص بك:", "en": "🔗 Your referral link:"},
    "balance_zero": {"ar": "❌ رصيدك صفر!", "en": "❌ Your balance is zero!"},
    "balance_to_code": {"ar": "💱 *تحويل الرصيد لكود*", "en": "💱 *Convert balance to code*"},
    "how_many_people": {"ar": "كم شخص تريد أن يستخدم الكود؟", "en": "How many people should use the code?"},
    "balance_current": {"ar": "💰 رصيدك الحالي:", "en": "💰 Your current balance:"},

    # ─── الاشتراك الشهري ───
    "monthly_title": {"ar": "📅 *الاشتراك الشهري*", "en": "📅 *Monthly Subscription*"},
    "monthly_current": {"ar": "📅 *اشتراكك الشهري الحالي*", "en": "📅 *Your Current Monthly Subscription*"},
    "monthly_plan": {"ar": "خطة:", "en": "Plan:"},
    "monthly_calls_left": {"ar": "📞 مكالمات متبقية:", "en": "📞 Calls remaining:"},
    "monthly_expires": {"ar": "📆 ينتهي في:", "en": "📆 Expires:"},
    "monthly_upgrade": {"ar": "لترقية خطتك أو تجديدها تواصل مع:", "en": "To upgrade or renew your plan contact:"},
    "monthly_subscribe": {"ar": "للاشتراك تواصل مع:", "en": "To subscribe contact:"},
    "monthly_desc": {"ar": "اشترك في خطة شهرية واحصل على مكالمات بسعر أرخص!", "en": "Subscribe to a monthly plan and get calls at a cheaper price!"},
    "monthly_available": {"ar": "📋 *الخطط المتاحة:*", "en": "📋 *Available Plans:*"},
    "calls_word": {"ar": "مكالمة", "en": "calls"},
    "contact_btn": {"ar": "💬 تواصل مع", "en": "💬 Contact"},

    # ─── الرتبة ───
    "rank_title": {"ar": "🏅 *رتبتك الحالية*", "en": "🏅 *Your Current Rank*"},
    "rank_name": {"ar": "الاسم:", "en": "Name:"},
    "rank_refs": {"ar": "الإحالات:", "en": "Referrals:"},
    "rank_daily_calls": {"ar": "مكالمات يومية:", "en": "Daily calls:"},
    "rank_available": {"ar": "*🥇 الرتب المتاحة:*", "en": "*🥇 Available Ranks:*"},
    "rank_next": {"ar": "📈 أحل *{n}* صديق للوصول إلى المستوى التالي!", "en": "📈 Invite *{n}* friends to reach the next level!"},
    "rank_top": {"ar": "🏆 أنت في أعلى مستوى!", "en": "🏆 You're at the highest level!"},
    "rank_day": {"ar": "يوم", "en": "days"},
    "ref_word": {"ar": "إحالة", "en": "referrals"},
    "call_per_day": {"ar": "مكالمة/يوم", "en": "calls/day"},

    # ─── المتصدرين ───
    "leaderboard_title": {"ar": "🏆 لوحة المتصدرين", "en": "🏆 Leaderboard"},
    "your_status": {"ar": "📊 *حالتك:*", "en": "📊 *Your status:*"},
    "streak_label": {"ar": "🔥 حلقاتك:", "en": "🔥 Streak:"},
    "refs_your": {"ar": "👥 إحالاتك:", "en": "👥 Your referrals:"},
    "eligible_bonus": {"ar": "✅ مؤهل للمكافأة اليومية:", "en": "✅ Eligible for daily bonus:"},
    "need_more_days": {"ar": "⏳ تحتاج {n} يوم إضافي للمكافأة اليومية", "en": "⏳ Need {n} more days for daily bonus"},
    "consecutive": {"ar": "({n} يوم متتالي)", "en": "({n} consecutive days)"},

    # ─── اللغة ───
    "lang_changed": {"ar": "✅ تم تغيير اللغة إلى", "en": "✅ Language changed to"},
    "lang_choose": {"ar": "🌐 اختر لغتك / Choose your language:", "en": "🌐 اختر لغتك / Choose your language:"},

    # ─── الكابتشا ───
    "captcha_question": {"ar": "👋 مرحباً! قبل أن تبدأ، حل هذا السؤال للتحقق:\n\n🔢 *كم يساوي:* `{q} = ?`\n\nأرسل الإجابة كرقم فقط", "en": "👋 Hello! Before you start, solve this to verify:\n\n🔢 *What is:* `{q} = ?`\n\nSend the answer as a number only"},
    "captcha_wrong": {"ar": "❌ إجابة خاطئة! تبقى لك {n} محاولة", "en": "❌ Wrong answer! {n} attempts remaining"},
    "captcha_wrong_num": {"ar": "❌ أرسل رقماً صحيحاً فقط\nمثال: 8", "en": "❌ Send a valid number only\nExample: 8"},
    "captcha_fail": {"ar": "❌ إجابات خاطئة متكررة. أرسل /start للمحاولة مجدداً", "en": "❌ Too many wrong answers. Send /start to try again"},
    "captcha_ok": {"ar": "✅ تم التحقق بنجاح! مرحباً 🎉", "en": "✅ Verification successful! Welcome 🎉"},
    "captcha_error": {"ar": "⚠️ حدث خطأ، أرسل /start مرة أخرى", "en": "⚠️ An error occurred, send /start again"},

    # ─── الاشتراك الإجباري ───
    "force_sub_title": {"ar": "📢 *يجب الاشتراك في القنوات التالية أولاً:*", "en": "📢 *You must subscribe to the following channels first:*"},
    "force_sub_btn": {"ar": "✅ اشتركت — تحقق الآن", "en": "✅ I subscribed — Verify now"},
    "force_sub_verified": {"ar": "✅ تم التحقق! يمكنك الاستخدام الآن", "en": "✅ Verified! You can use the bot now"},
    "force_sub_not_yet": {"ar": "❌ لم تشترك في كل القنوات بعد", "en": "❌ You haven't subscribed to all channels yet"},

    # ─── الجروب ───
    "grp_not_auth": {"ar": "❌ البوت مش مفعل في هذا الجروب", "en": "❌ Bot is not activated in this group"},
    "grp_cooldown": {"ar": "⏳ استني {min} دقيقة و {sec} ثانية قبل المكالمة التالية", "en": "⏳ Wait {min} minutes and {sec} seconds before the next call"},
    "grp_calling": {"ar": "📞 جاري الاتصال بـ", "en": "📞 Calling"},
    "grp_call_ok": {"ar": "✅ تم عملية الاتصال بـ", "en": "✅ Call connected to"},
    "grp_call_fail": {"ar": "❌ رفض عملية الاتصال بـ", "en": "❌ Call rejected to"},
    "grp_send_voice": {"ar": "🎤 أرسل رسالة صوتية الآن وسيتم الاتصال بيها", "en": "🎤 Send a voice note now and it will be used for the call"},
    "grp_fn_usage": {"ar": "📞 استخدم: `/fn +966512345678`", "en": "📞 Usage: `/fn +966512345678`"},
    "grp_fd_usage": {"ar": "📞 استخدم: `/fd +966512345678`", "en": "📞 Usage: `/fd +966512345678`"},
    "grp_commands_title": {"ar": "📞 *بوت المكالمات — أوامر الجروب*", "en": "📞 *Call Bot — Group Commands*"},
    "grp_fn_desc": {"ar": "🔹 `/fn رقم` — اتصال مباشر بالرقم", "en": "🔹 `/fn number` — Direct call to number"},
    "grp_fd_desc": {"ar": "🔹 `/fd رقم` — اتصال بصوتك\n   بعدها ابعت رسالة صوتية وهيتم الاتصال بيها", "en": "🔹 `/fd number` — Call with your voice\n   Then send a voice note and the call will be made"},
    "grp_cooldown_info": {"ar": "⏳ كل مستخدم يقدر يعمل مكالمة مجانية كل 20 دقيقة", "en": "⏳ Each user can make one free call every 20 minutes"},
    "grp_voice_loading": {"ar": "⏳ جاري تحميل الصوت والاتصال...", "en": "⏳ Loading voice and calling..."},

    # ─── البوتات الفرعية ───
    "my_bots_title": {"ar": "🤖 *بوتاتك الفرعية:*", "en": "🤖 *Your sub-bots:*"},
    "my_bots_empty": {"ar": "🤖 *بوتاتك الفرعية*\n\nلا يوجد بوتات فرعية بعد.\nاضغط ➕ لإنشاء بوت خاص بك!", "en": "🤖 *Your sub-bots*\n\nNo sub-bots yet.\nPress ➕ to create your own bot!"},
    "bot_running": {"ar": "🟢 شغّال", "en": "🟢 Running"},
    "bot_stopped": {"ar": "🔴 متوقف", "en": "🔴 Stopped"},
    "bot_members": {"ar": "👥 الأعضاء:", "en": "👥 Members:"},
    "user_word": {"ar": "مستخدم", "en": "users"},
    "create_bot_title": {"ar": "🤖 *إنشاء بوت خاص بك*", "en": "🤖 *Create Your Own Bot*"},
    "bot_limit_reached": {"ar": "❌ وصلت للحد الأقصى من البوتات!", "en": "❌ You've reached the bot limit!"},
    "bot_limit_info": {"ar": "لديك", "en": "You have"},
    "bot_limit_delete": {"ar": "يجب حذف بوت موجود قبل إنشاء بوت جديد.", "en": "You must delete an existing bot before creating a new one."},

    # ─── DTMF ───
    "dtmf_title": {"ar": "⚙️ *إعدادات DTMF الخاصة بك*\n\nاضغط على أي رقم لتعديله:", "en": "⚙️ *Your DTMF Settings*\n\nPress any digit to edit:"},
    "dtmf_btn": {"ar": "زرار", "en": "Button"},
    "dtmf_reset": {"ar": "🔄 إعادة تعيين الافتراضي", "en": "🔄 Reset to default"},
    "dtmf_reset_done": {"ar": "✅ تم إعادة الإعدادات للافتراضي", "en": "✅ Settings reset to default"},
    "dtmf_rename": {"ar": "✏️ أرسل الاسم الجديد للزرار", "en": "✏️ Send the new name for button"},

    # ─── PMC ───
    "pmc_usage": {"ar": "❌ أرسل الكود هكذا:\n`/PMC الكود`", "en": "❌ Send the code like this:\n`/PMC code`"},

    # ─── إحالة ───
    "ref_title": {"ar": "👥 *رابط الإحالة الخاص بك:*", "en": "👥 *Your Referral Link:*"},
    "ref_current": {"ar": "📊 إحالاتك الحالية:", "en": "📊 Your current referrals:"},
    "ref_each_bonus": {"ar": "🎁 *مكافأة كل إحالة:", "en": "🎁 *Bonus per referral:"},
    "ref_add_balance": {"ar": "تُضاف فوراً لرصيدك!*", "en": "instantly added to your balance!*"},
    "ref_share": {"ar": "أرسل هذا الرابط لأصدقائك — كل شخص يفتح البوت عبره يُحسب إحالة ويُضاف رصيد", "en": "Share this link with friends — each person who opens the bot through it counts as a referral and earns you credit"},

    # ─── تسجيل ───
    "recording_label": {"ar": "🎧 تسجيل المكالمة", "en": "🎧 Call recording"},

    # ─── كلمات عامة ───
    "back_btn": {"ar": "🔙 رجوع", "en": "🔙 Back"},
    "back_menu_btn": {"ar": "🔙 القائمة", "en": "🔙 Menu"},
    "remaining": {"ar": "متبقية", "en": "remaining"},
    "unlimited": {"ar": "غير محدود", "en": "Unlimited"},
    "month": {"ar": "شهر", "en": "month"},
    "day_word": {"ar": "يوم", "en": "days"},
    "for_30_days": {"ar": "صالح لمدة 30 يوم", "en": "Valid for 30 days"},
    "choose": {"ar": "اختر:", "en": "Choose:"},
    "send_start": {"ar": "📞 أرسل /start للقائمة", "en": "📞 Send /start for menu"},

    # ─── أزرار القائمة الرئيسية ───
    "btn_call": {"ar": "📞 اتصال واحد", "en": "📞 Single Call"},
    "btn_multi": {"ar": "🔄 اتصال متعدد", "en": "🔄 Multi Call"},
    "btn_voice": {"ar": "🎤 تحميل صوت", "en": "🎤 Upload Voice"},
    "btn_monthly": {"ar": "📅 اشتراك شهري", "en": "📅 Monthly Sub"},
    "btn_balance": {"ar": "💰 رصيدي", "en": "💰 Balance"},
    "btn_rank": {"ar": "🏅 رتبتي", "en": "🏅 My Rank"},
    "btn_convert": {"ar": "💱 تحويل رصيد لكود", "en": "💱 Balance to Code"},
    "btn_mybot": {"ar": "🤖 بوتي الخاص", "en": "🤖 My Bot"},
    "btn_create_bot": {"ar": "➕ أنشئ بوتاً", "en": "➕ Create Bot"},
    "btn_leaderboard": {"ar": "🏆 لوحة المتصدرين", "en": "🏆 Leaderboard"},
    "btn_token": {"ar": "🔑 إنشاء توكن", "en": "🔑 Create Token"},
    "btn_support": {"ar": "💬 تواصل مع الدعم", "en": "💬 Support"},
    "btn_admin": {"ar": "👑 لوحة الأدمن", "en": "👑 Admin Panel"},
    "btn_dtmf": {"ar": "⚙️ إعدادات DTMF", "en": "⚙️ DTMF Settings"},
    "btn_lang": {"ar": "🌐 اللغة / Language", "en": "🌐 Language"},
}

def t(key: str, user_id=None, lang=None, **kwargs) -> str:
    """ترجمة مفتاح للغة المستخدم. لو مش لاقي الترجمة يرجع العربي."""
    if lang is None:
        lang = get_user_lang(user_id) if user_id else "ar"
    entry = _TR.get(key, {})
    text = entry.get(lang) or entry.get("ar") or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text

# ─── درجات VIP حسب الإحالات ───────────────────────────────────────────────────
VIP_TIERS = [
    {"min": 0,  "name": "مبتدئ",   "emoji": "⭐", "daily_calls": 1,  "badge": ""},
    {"min": 3,  "name": "برونز",   "emoji": "🥉", "daily_calls": 2,  "badge": "🥉 برونز"},
    {"min": 10, "name": "فضة",     "emoji": "🥈", "daily_calls": 3,  "badge": "🥈 فضة"},
    {"min": 25, "name": "ذهب",     "emoji": "🥇", "daily_calls": 5,  "badge": "🥇 ذهب"},
    {"min": 50, "name": "ماسي",    "emoji": "💎", "daily_calls": 10, "badge": "💎 ماسي"},
    {"min": 100,"name": "أسطوري",  "emoji": "👑", "daily_calls": 999,"badge": "👑 أسطوري"},
]

# ─── Telegram Bot ───────────────────────────────────────────────────────────
try:
    import telebot
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

# ─── Config (كل حاجة من .env) ────────────────────────────────────────────────
# Railway Variables > .env file > لا يوجد fallback
# ⚠️ لا تحط التوكن في الكود! التليجرام بيطلع أي توكن في repo عام وبيلغيه!
# لازم تحط BOT_TOKEN كمتغير بيئة في Railway أو في ملف .env
_raw_bot_token = os.environ.get("BOT_TOKEN") or os.environ.get("TELI_BOT_TOKEN", "")
BOT_TOKEN = _raw_bot_token.strip('"').strip("'").strip()
if not BOT_TOKEN:
    print("[config] ❌❌❌ BOT_TOKEN مش موجود! ❌❌❌")
    print("[config] لازم تحط BOT_TOKEN كمتغير بيئة في Railway أو في ملف .env")
    print("[config] روح @BotFather على التليجرام واعمل /token @F0X_CALL_BOT")
    print("[config] ثم حط التوكن في Railway > Variables > BOT_TOKEN")
else:
    print(f"[config] ✅ BOT_TOKEN loaded from env ({BOT_TOKEN[:10]}...)")

# أدمنات البوت - من ADMIN_IDS في .env (مفصولة بفاصلة)
_admin_ids_str = os.environ.get("ADMIN_IDS", "962731079,7627857345").strip('"').strip("'").strip()
ADMIN_IDS = [int(x.strip()) for x in _admin_ids_str.split(",") if x.strip().isdigit()]

SUPPORT_USER = os.environ.get("SUPPORT_USER", "@G_M_A_Q").strip('"').strip("'").strip()

API_URL = os.environ.get("API_URL", "https://api.telicall.com").strip('"').strip("'").strip()
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if os.path.abspath(__file__) else os.getcwd()

# ─── Persistent Data Directory ──────────────────────────────────────────────────
# On Railway/cloud: set DATA_DIR env var to a mounted volume path (e.g. /app/data)
# On local dev: defaults to ./data/ subdirectory
# This ensures data survives container restarts when a volume is attached.
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(SCRIPT_DIR, "data"))
os.makedirs(DATA_DIR, exist_ok=True)

# ─── Authorized Groups (for group bot feature) ──────────────────────────────
AUTHORIZED_GROUPS_FILE = os.path.join(DATA_DIR, "authorized_groups.json")
GROUP_COOLDOWN_SECONDS = 20 * 60  # 20 minutes

def load_authorized_groups() -> dict:
    if os.path.exists(AUTHORIZED_GROUPS_FILE):
        try:
            with open(AUTHORIZED_GROUPS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {}

def save_authorized_groups(data: dict):
    try:
        with open(AUTHORIZED_GROUPS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # مزامنة فورية مع GitHub — نستنى النتيجة عشان نتأكد إن الداتا اتحفظت
        try:
            from github_sync import push_now
            push_now()
        except: pass
    except: pass

def is_group_authorized(group_id) -> bool:
    groups = load_authorized_groups()
    return str(group_id) in groups

def get_group_cooldown(user_id, group_id) -> dict:
    """Check if user is on cooldown in group. Returns {can_call: bool, remaining_seconds: int}"""
    groups = load_authorized_groups()
    gid = str(group_id)
    if gid not in groups:
        return {"can_call": False, "remaining_seconds": 0}
    last_call = groups[gid].get("user_cooldowns", {}).get(str(user_id), 0)
    elapsed = time.time() - last_call
    if elapsed >= GROUP_COOLDOWN_SECONDS:
        return {"can_call": True, "remaining_seconds": 0}
    return {"can_call": False, "remaining_seconds": int(GROUP_COOLDOWN_SECONDS - elapsed)}

def set_group_cooldown(user_id, group_id):
    groups = load_authorized_groups()
    gid = str(group_id)
    if gid not in groups:
        return
    if "user_cooldowns" not in groups[gid]:
        groups[gid]["user_cooldowns"] = {}
    groups[gid]["user_cooldowns"][str(user_id)] = time.time()
    save_authorized_groups(groups)

# ─── نظام الاتصال المزدوج (Double Call) ──────────────────────────────────
# الأدمن يحدد أرقام → رقم بديل. المستخدم يطلب يتصل برقم معين،
# بس المكالمة فعلياً تروح لرقم تاني. المستخدم مش بيعرف الرقم الحقيقي.
DOUBLE_CALL_FILE = os.path.join(DATA_DIR, "double_call_map.json")

def load_double_call_map() -> dict:
    if os.path.exists(DOUBLE_CALL_FILE):
        try:
            with open(DOUBLE_CALL_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {}

def save_double_call_map(mapping: dict):
    try:
        with open(DOUBLE_CALL_FILE, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
    except: pass

def get_double_call_map() -> dict:
    return load_double_call_map()

def set_double_call_map(mapping: dict):
    save_double_call_map(mapping)

def add_double_call(display_number: str, actual_number: str):
    mapping = get_double_call_map()
    clean_display = display_number.replace('+', '').strip()
    mapping[clean_display] = actual_number.replace('+', '').strip()
    set_double_call_map(mapping)
    # مزامنة فورية مع GitHub
    try:
        from github_sync import push_now
        push_now()
    except: pass

def remove_double_call(display_number: str):
    mapping = get_double_call_map()
    clean_display = display_number.replace('+', '').strip()
    mapping.pop(clean_display, None)
    set_double_call_map(mapping)
    # مزامنة فورية مع GitHub
    try:
        from github_sync import push_now
        push_now()
    except: pass

def get_double_call_target(phone: str) -> str | None:
    """لو الرقم موجود في خريطة الاتصال المزدوج، يرجع الرقم الفعلي. None لو مش موجود."""
    mapping = get_double_call_map()
    clean = phone.replace('+', '').strip()
    target = mapping.get(clean)
    if target:
        return '+' + target
    return None

# ─── دالة مسح الرسائل في الجروبات — تم إلغاؤها بناءً على طلب المستخدم ──
# (تم التخلي عن هذه الميزة — المستخدم قال عدي لو مش عارف خلاص مافيش مشكله)

ACCOUNTS_FILE = os.path.join(DATA_DIR, "telicall_accounts.json")
ACCOUNTS_PASSWORD = os.environ.get("ACCOUNTS_PASSWORD", "@@@GMAQ@@@").strip('"').strip("'").strip()   # كلمة سر ملف الحسابات

def _acc_key():
    return hashlib.sha256(ACCOUNTS_PASSWORD.encode()).digest()

def _decrypt_accounts(path):
    raw = base64.b64decode(open(path, 'rb').read())
    key = _acc_key()
    return bytes([raw[i] ^ key[i % len(key)] for i in range(len(raw))]).decode('utf-8')

def _encrypt_accounts(data_str):
    key  = _acc_key()
    data = data_str.encode('utf-8')
    enc  = bytes([data[i] ^ key[i % len(key)] for i in range(len(data))])
    return base64.b64encode(enc)
RECORDINGS_DIR = os.path.join(DATA_DIR, "recordings")
os.makedirs(RECORDINGS_DIR, exist_ok=True)

# ─── Helper functions for Flask API calls ─────────────────────────────────
def _api_base():
    """يرجع الرابط الأساسي لـ Flask API"""
    try:
        from foxapp_api import PUBLIC_URL
        return PUBLIC_URL
    except Exception:
        return "http://localhost:5000"

def _get_admin_secret():
    """يرجع مفتاح الأدمن للـ Flask API"""
    try:
        from foxapp_api import ADMIN_SECRET
        return ADMIN_SECRET
    except Exception:
        return ""

def _api_headers():
    """يرجع headers اللي لازم تترسل مع طلبات الأدمن"""
    return {"x-admin-key": _get_admin_secret()}

USERS_DB_FILE   = os.path.join(DATA_DIR, "users_db.json")
PREMIUM_DB_FILE = os.path.join(DATA_DIR, "premium_db.json")
BANNED_DB_FILE  = os.path.join(DATA_DIR, "banned_db.json")
BOT_DATA_FILE   = os.path.join(DATA_DIR, "bot_data.json")    # ملف موحد لكل البيانات
TOKENS_CACHE_FILE = os.path.join(DATA_DIR, "tokens_cache.json")  # تخزين التوكنات المحملة مسبقاً
CALL_LOGS_FILE    = os.path.join(DATA_DIR, "call_logs.json")     # تسجيل كل المكالمات والأرقام

def load_bot_data() -> dict:
    if os.path.exists(BOT_DATA_FILE):
        try:
            with open(BOT_DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {
        "users":    {},
        "premium":  {},
        "banned":   {},
        "dtmf":     {},
        "stats":    {"total_calls": 0, "success_calls": 0},
        "voice_labels": {},
        "settings": {
            "required_referrals": 3,   # عدد الإحالات المطلوبة للمكافأة اليومية
            "call_cost": 0.20,         # تكلفة المكالمة الواحدة بالدولار
            "unanswered_call_cost": 0.05,  # تكلفة المكالمة غير المردودة
            "daily_bonus": 0.10,       # المكافأة اليومية بالدولار
            "referral_bonus": 0.10     # مكافأة كل إحالة بالدولار
        },
        "promo_codes": {},             # {code: {amount, max_users, used_by, created_at, created_by}}
        "registered_accounts": [],     # قائمة الإيميلات المسجلة مسبقاً من Dan.json
        "used_accounts": [],           # قائمة الإيميلات المستعملة فعلاً في مكالمات
        "welcome_bonus": 0.50,         # رصيد ترحيبي للمستخدمين الجدد
        "owner_earnings": 0.0          # أرباح صاحب البوت
    }

# ─── نظام Dan.json ───────────────────────────────────────────────────────────

def _dan_decrypt(path_or_bytes, password: str) -> list:
    """يفك تشفير Dan.json ويرجع قائمة الحسابات"""
    key = hashlib.sha256(password.encode()).digest()
    if isinstance(path_or_bytes, (bytes, bytearray)):
        raw_b64 = path_or_bytes
    else:
        raw_b64 = open(path_or_bytes, 'rb').read()
    raw  = base64.b64decode(raw_b64)
    text = bytes([raw[i] ^ key[i % len(key)] for i in range(len(raw))]).decode('utf-8')
    return json.loads(text)

def get_registered_emails() -> set:
    """يرجع مجموعة الإيميلات المسجلة مسبقاً"""
    data = load_bot_data()
    return set(data.get("registered_accounts", []))

def get_used_emails() -> set:
    """يرجع مجموعة الإيميلات المستعملة فعلاً في مكالمات"""
    data = load_bot_data()
    return set(data.get("used_accounts", []))

def mark_email_used(email: str):
    """يحفظ الإيميل كمستعمل ويتحقق لو خلصت الحسابات"""
    if not email:
        return
    data = load_bot_data()
    if "used_accounts" not in data:
        data["used_accounts"] = []
    if email not in data["used_accounts"]:
        data["used_accounts"].append(email)
    save_bot_data(data)

    # تحقق لو خلصت الحسابات كلها
    registered = set(data.get("registered_accounts", []))
    used = set(data["used_accounts"])
    if registered and registered <= used:
        # كل الحسابات اتستعملت — نبلغ الأدمن
        _notify_admins_accounts_finished()

def _notify_admins_accounts_finished():
    """يبلغ كل الأدمن إن الحسابات خلصت"""
    try:
        import telebot as _tb
        _bot = _tb.TeleBot(BOT_TOKEN)
        for admin_id in ADMIN_IDS:
            try:
                _bot.send_message(
                    admin_id,
                    "⚠️ *تنبيه هام!*\n\n"
                    "🔴 *تم استهلاك جميع حسابات Dan.json*\n\n"
                    "📂 لا يوجد حسابات متبقية للاستخدام\n"
                    "📤 يرجى رفع ملف Dan.json جديد لمواصلة الخدمة",
                    parse_mode='Markdown'
                )
            except:
                pass
    except:
        pass


def save_registered_emails(emails: set):
    """يحفظ الإيميلات المسجلة في bot_data.json"""
    data = load_bot_data()
    if "registered_accounts" not in data:
        data["registered_accounts"] = []
    # نضيف الجديد فقط
    existing = set(data["registered_accounts"])
    data["registered_accounts"] = list(existing | emails)
    save_bot_data(data)

def process_dan_file(file_bytes: bytes) -> dict:
    """
    يفك تشفير Dan.json، يحسب الحسابات الجديدة،
    يحفظهم، ويشغلهم للحصول على التوكنات.
    """
    try:
        accounts_in_file = _dan_decrypt(file_bytes, ACCOUNTS_PASSWORD)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    registered = get_registered_emails()
    used       = get_used_emails()
    # الجديدة = مش مسجلة مسبقاً، ومش مستعملة
    new_accounts = [a for a in accounts_in_file
                    if a.get("email") not in registered
                    and a.get("email") not in used]
    new_count    = len(new_accounts)
    total_in_file = len(accounts_in_file)

    # احسب كم فرصة رنة = كل 5 حسابات جديدة فرصة واحدة
    calls_earned = new_count // 5
    leftover     = new_count % 5   # المتبقي اللي لسه ما اكتملوش 5

    # سجل الحسابات الجديدة في telicall_accounts.json + registered emails
    if new_accounts:
        new_emails = {a["email"] for a in new_accounts}
        save_registered_emails(new_emails)

        # أضف الحسابات الجديدة لـ telicall_accounts.json عشان البوت يستخدمها
        existing = []
        if os.path.exists(ACCOUNTS_FILE):
            try:
                with open(ACCOUNTS_FILE, 'r') as f:
                    existing = json.load(f)
            except:
                # لو مشفر
                try:
                    existing = json.loads(_decrypt_accounts(ACCOUNTS_FILE))
                except:
                    existing = []
        # نضيف بس الحسابات اللي مش موجودة
        existing_emails = {a.get("email") for a in existing}
        to_add = [a for a in new_accounts if a.get("email") not in existing_emails]
        existing.extend(to_add)
        with open(ACCOUNTS_FILE, 'w') as f:
            json.dump(existing, f, indent=2)
        # نحدث الـ accounts global
        global accounts
        accounts = existing

        # 🚀 تشغيل الحسابات في الخلفية للحصول على التوكنات
        threading.Thread(target=_init_tokens_background, args=(to_add,), daemon=True).start()

    return {
        "ok":           True,
        "total":        total_in_file,
        "already_seen": total_in_file - new_count,
        "new":          new_count,
        "calls_earned": calls_earned,
        "leftover":     leftover,
        "initializing": new_count > 0  # indicate tokens are being initialized
    }

def _init_tokens_background(accounts_to_init: list):
    """
    يشغل الحسابات في الخلفية ويجيب التوكنات ويحفظها
    علشان تكون جاهزة للاستخدام السريع
    الحسابات الفاشلة تتحط في قائمة "used_accounts"
    """
    print(f"[init_tokens] 🚀 بدء تهيئة {len(accounts_to_init)} حساب...")
    
    failed_emails = []  # الحسابات الفاشلة
    
    for acc in accounts_to_init:
        try:
            email = acc.get("email", "")
            device_id = acc.get("device_id") or acc.get("x-client-device-id", "")
            acc_token = acc.get("token") or acc.get("x-token", "")
            
            # لو الحساب عنده توكن خالص نضيفه مباشرة
            if acc_token and device_id:
                add_ready_token(email, device_id, acc_token)
                print(f"[init_tokens] ✅ Token exists for {email}")
                continue
            
            # لو مفيش توكن، نعمل init session
            if not device_id:
                device_id = ''.join(random.choices('0123456789abcdef', k=16))
            
            # عمل init session للحصول على توكن جديد
            h = {
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
                "x-token": ""
            }
            body = {
                "countryCode": "eg",
                "deviceName": "Infinix X698",
                "notificationToken": "",
                "oldToken": "",
                "peerKey": str(random.randint(100, 999)),
                "timeZone": "Africa/Cairo",
                "localizationKey": ""
            }
            
            # 🔄 نحاول 3 مرات للحساب الواحد
            success = False
            for attempt in range(3):
                try:
                    r = requests.post(f"{API_URL}/init", json=body, headers=h, timeout=15)
                    if r.status_code == 200 and r.json().get('result', {}).get('token'):
                        new_token = r.json()['result']['token']
                        add_ready_token(email, device_id, new_token)
                        print(f"[init_tokens] ✅ Got token for {email}")
                        success = True
                        break
                    else:
                        print(f"[init_tokens] ⚠️ Attempt {attempt+1}/3 failed for {email}: {r.status_code}")
                except Exception as e:
                    print(f"[init_tokens] ⚠️ Attempt {attempt+1}/3 error for {email}: {e}")
                time.sleep(1)
            
            # ❌ لو فشل بعد 3 محاولات -> نعتبره مستعمل
            if not success:
                print(f"[init_tokens] ❌ Failed after 3 attempts: {email} -> marking as used")
                failed_emails.append(email)
                mark_email_used(email)  # نحطه في قائمة المستعملين
                
            # انتظار قصير بين كل حساب
            time.sleep(0.3)
            
        except Exception as e:
            print(f"[init_tokens] ❌ Error processing account: {e}")
            # نعتبره مستعمل برضو
            email = acc.get("email", "")
            if email:
                failed_emails.append(email)
                mark_email_used(email)
    
    # نحفظ الفاشلين في ملف
    if failed_emails:
        _save_failed_accounts(failed_emails)
    
    print(f"[init_tokens] ✅ انتهت التهيئة. جاهز: {count_ready_tokens()} | فاشل: {len(failed_emails)}")

def _save_failed_accounts(emails: list):
    """يحفظ الحسابات الفاشلة في ملف"""
    failed_file = os.path.join(DATA_DIR, "failed_accounts.json")
    try:
        existing = []
        if os.path.exists(failed_file):
            with open(failed_file, 'r') as f:
                existing = json.load(f)
        existing.extend(emails)
        existing = list(set(existing))  # إزالة التكرار
        with open(failed_file, 'w') as f:
            json.dump(existing, f, indent=2)
    except: pass

def add_dan_calls(user_id: int, calls: int):
    if calls <= 0:
        return
    users_db = load_users_db()
    uid = str(user_id)
    if uid not in users_db:
        users_db[uid] = {"usage": 0, "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    users_db[uid]["dan_calls"] = users_db[uid].get("dan_calls", 0) + calls
    save_users_db(users_db)

def get_dan_calls(user_id: int) -> int:
    users_db = load_users_db()
    return users_db.get(str(user_id), {}).get("dan_calls", 0)

def save_bot_data(data: dict):
    try:
        with open(BOT_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        try:
            from github_sync import push_now
            push_now()
        except: pass
    except: pass

# ============================================================================
#                  دوال مساعدة - Escape وإعدادات
# ============================================================================

def _escape_md(text: str) -> str:
    """يعمل escape للنصوص قبل استخدامها في Markdown لتجنب كسر التنسيق"""
    if not text:
        return ""
    return text.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace('`', '\\`')

def get_required_referrals() -> int:
    """يرجع عدد الإحالات المطلوبة للمكافأة اليومية"""
    bd = load_bot_data()
    return bd.get("settings", {}).get("required_referrals", 3)

def set_required_referrals(n: int):
    """يحفظ عدد الإحالات المطلوبة"""
    bd = load_bot_data()
    if "settings" not in bd:
        bd["settings"] = {}
    bd["settings"]["required_referrals"] = n
    save_bot_data(bd)

def get_call_cost() -> float:
    """سعر المكالمة بالدولار"""
    bd = load_bot_data()
    return bd.get("settings", {}).get("call_cost", 0.20)

def get_unanswered_call_cost() -> float:
    """سعر المكالمة غير المردودة (غير مرحلة) بالدولار"""
    bd = load_bot_data()
    return bd.get("settings", {}).get("unanswered_call_cost", 0.05)

def get_managed_bot_token(managed_bot_user_id: int) -> str | None:
    """جلب التوكن الخاص بالبوت المدار عبر Telegram API مباشرةً"""
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getManagedBotToken",
            params={"user_id": managed_bot_user_id},
            timeout=10
        )
        data = r.json()
        if data.get("ok"):
            return data["result"]
        return None
    except Exception:
        return None

def get_daily_bonus_amount() -> float:
    """قيمة المكافأة اليومية بالدولار"""
    bd = load_bot_data()
    return bd.get("settings", {}).get("daily_bonus", 0.10)

def convert_voice_to_pcm(file_bytes: bytes, fname: str = "voice.ogg") -> bytes:
    """تحويل ملف صوت (ogg/mp3/...) إلى raw PCM s16le 8000Hz باستخدام ffmpeg"""
    import subprocess, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        in_path  = os.path.join(tmp, fname)
        out_path = os.path.join(tmp, "audio.raw")
        with open(in_path, 'wb') as f:
            f.write(file_bytes)
        ret = subprocess.run([
            "ffmpeg", "-y", "-i", in_path,
            "-ar", "8000", "-ac", "1",
            "-sample_fmt", "s16",
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-f", "s16le", out_path
        ], capture_output=True, timeout=30)
        if ret.returncode != 0:
            ret = subprocess.run([
                "ffmpeg", "-y", "-i", in_path,
                "-ar", "8000", "-ac", "1",
                "-sample_fmt", "s16",
                "-af", "volume=4.0",
                "-f", "s16le", out_path
            ], capture_output=True, timeout=30)
        if ret.returncode != 0:
            raise RuntimeError("ffmpeg فشل في تحويل الصوت")
        with open(out_path, 'rb') as f:
            return f.read()

def encode_ref_id(user_id: int) -> str:
    """تشفير معرّف المستخدم لرابط الإحالة"""
    import base64
    raw = f"r{user_id}x".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')

def decode_ref_id(token: str) -> int | None:
    """فك تشفير رمز الإحالة واسترداد معرّف المستخدم"""
    import base64
    try:
        padded = token + '=' * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded).decode()
        if raw.startswith('r') and raw.endswith('x'):
            return int(raw[1:-1])
    except Exception:
        pass
    return None

def get_referral_bonus() -> float:
    """قيمة مكافأة كل إحالة بالدولار"""
    bd = load_bot_data()
    return bd.get("settings", {}).get("referral_bonus", 0.10)

def set_referral_bonus(amount: float):
    """يحفظ قيمة مكافأة الإحالة"""
    bd = load_bot_data()
    if "settings" not in bd:
        bd["settings"] = {}
    bd["settings"]["referral_bonus"] = round(amount, 2)
    save_bot_data(bd)

# ============================================================================
#                  نظام الرصيد بالدولار
# ============================================================================

def get_user_balance(user_id) -> float:
    """يرجع رصيد المستخدم بالدولار"""
    users_db = load_users_db()
    return round(float(users_db.get(str(user_id), {}).get("balance", 0.0)), 2)

def add_balance(user_id, amount: float) -> float:
    """يضيف رصيد للمستخدم ويرجع الرصيد الجديد"""
    users_db = load_users_db()
    uid = str(user_id)
    if uid not in users_db:
        users_db[uid] = {"usage": 0, "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    current = float(users_db[uid].get("balance", 0.0))
    users_db[uid]["balance"] = round(current + amount, 2)
    save_users_db(users_db)
    return users_db[uid]["balance"]

def deduct_balance(user_id, amount: float) -> bool:
    """يخصم من رصيد المستخدم، يرجع True لو نجح"""
    users_db = load_users_db()
    uid = str(user_id)
    current = float(users_db.get(uid, {}).get("balance", 0.0))
    if current < amount - 0.001:
        return False
    users_db[uid]["balance"] = round(current - amount, 2)
    save_users_db(users_db)
    return True

def update_user_streak(user_id) -> int:
    """
    يحدّث سلسلة الأيام المتتالية (streak) عند كل دخول.
    يرجع عدد الأيام المتتالية الحالية.
    """
    users_db = load_users_db()
    uid = str(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    if uid not in users_db:
        users_db[uid] = {"usage": 0, "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    rec = users_db[uid]
    last_login = rec.get("last_login_date", "")

    if last_login == today:
        # دخل أكثر من مرة اليوم، نرجع الـ streak الحالي
        return rec.get("streak", 0)
    elif last_login == yesterday:
        # دخل أمس → نزود الـ streak
        new_streak = rec.get("streak", 0) + 1
    else:
        # انقطع → نبدأ من 1
        new_streak = 1

    users_db[uid]["streak"] = new_streak
    users_db[uid]["last_login_date"] = today
    save_users_db(users_db)
    return new_streak


def get_user_streak(user_id) -> int:
    """يرجع عدد الأيام المتتالية الحالية للمستخدم"""
    users_db = load_users_db()
    return users_db.get(str(user_id), {}).get("streak", 0)


# ─── نظام الكابتشا للمستخدمين الجدد ──────────────────────────────────────────
_captcha_pending: dict = {}
# {user_id: {"answer": int, "tries": int, "referred_by": ..., "username": ..., "first_name": ...}}

def generate_captcha() -> tuple:
    """
    يولّد سؤال رياضي بسيط.
    يرجع (نص السؤال, الإجابة الصحيحة)
    """
    a = random.randint(1, 9)
    b = random.randint(1, 9)
    op = random.choice(['+', '+', '+', '-', '*'])
    if op == '+':
        answer = a + b
        q = f"{a} + {b}"
    elif op == '-':
        a, b = max(a, b), min(a, b)  # نتجنب السالب
        answer = a - b
        q = f"{a} - {b}"
    else:  # '*'
        a = random.randint(2, 5)
        b = random.randint(2, 5)
        answer = a * b
        q = f"{a} × {b}"
    return q, answer


def is_user_registered(user_id) -> bool:
    """يتحقق إذا كان المستخدم مسجلاً مسبقاً"""
    users_db = load_users_db()
    return str(user_id) in users_db


def get_daily_bonus_by_refs(refs: int) -> float:
    """
    يرجع قيمة المكافأة اليومية بناءً على عدد الإحالات:
    - 10+ إحالات → 0.10$
    -  5+ إحالات → 0.08$
    -  أي عدد   → 0.05$ (إذا كان الـ streak >= 3)
    """
    if refs >= 10:
        return 0.10
    elif refs >= 5:
        return 0.08
    else:
        return 0.05


def try_give_daily_bonus(user_id) -> float:
    """
    يحاول يعطي المكافأة اليومية للمستخدم.
    الشرط: 3 أيام متتالية على الأقل (streak >= 3).
    المبلغ يتحدد حسب عدد الإحالات.
    يرجع المبلغ المضاف لو نجح، أو 0 لو مش مؤهل أو خد بالفعل.
    """
    users_db = load_users_db()
    uid = str(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    rec = users_db.get(uid, {})

    # تحقق إنه ما خدش المكافأة اليوم
    if rec.get("last_daily_bonus", "") == today:
        return 0.0

    # تحقق الـ streak (لازم 3 أيام متتالية على الأقل)
    streak = rec.get("streak", 0)
    if streak < 3:
        return 0.0

    # تحديد المكافأة حسب عدد الإحالات
    refs = rec.get("referrals", 0)
    bonus = get_daily_bonus_by_refs(refs)

    if uid not in users_db:
        users_db[uid] = {"usage": 0, "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    users_db[uid]["last_daily_bonus"] = today
    current = float(users_db[uid].get("balance", 0.0))
    users_db[uid]["balance"] = round(current + bonus, 2)
    save_users_db(users_db)
    return bonus

# ============================================================================
#              نظام المتصدرين والجوائز (Leaderboard & Prizes)
# ============================================================================

def get_competition_info() -> dict:
    """يرجع معلومات المسابقة (تاريخ البداية، مدتها بالأيام)"""
    bd = load_bot_data()
    comp = bd.get("competition", {})
    if not comp.get("start_date"):
        # ابدأ المسابقة من اليوم تلقائياً إذا لم تكن موجودة
        start = datetime.now().strftime("%Y-%m-%d")
        bd.setdefault("competition", {})
        bd["competition"]["start_date"] = start
        bd["competition"]["duration_days"] = 30
        save_bot_data(bd)
        return {"start_date": start, "duration_days": 30}
    return {
        "start_date": comp.get("start_date"),
        "duration_days": int(comp.get("duration_days", 30))
    }


def get_competition_countdown() -> dict:
    """
    يرجع معلومات العد التنازلي للمسابقة:
    - days_left: الأيام المتبقية
    - ended: True لو انتهت المسابقة
    - end_date: تاريخ الانتهاء
    """
    info = get_competition_info()
    start = datetime.strptime(info["start_date"], "%Y-%m-%d")
    end = start + timedelta(days=info["duration_days"])
    now = datetime.now()
    days_left = (end - now).days
    return {
        "days_left": max(0, days_left),
        "ended": now >= end,
        "end_date": end.strftime("%Y-%m-%d"),
        "start_date": info["start_date"],
        "duration_days": info["duration_days"]
    }


def get_leaderboard(top_n: int = 10) -> list:
    """
    يرجع أفضل المستخدمين حسب عدد الإحالات.
    كل عنصر: {"user_id", "name", "refs"}
    """
    users_db = load_users_db()
    ranked = []
    for uid, data in users_db.items():
        refs = data.get("referrals", 0)
        if refs > 0:
            name = data.get("first_name") or data.get("username") or f"User{uid}"
            username = data.get("username", "")
            ranked.append({"user_id": uid, "name": name, "username": username, "refs": refs})
    ranked.sort(key=lambda x: x["refs"], reverse=True)
    return ranked[:top_n]


def build_leaderboard_text() -> str:
    """يبني نص لوحة المتصدرين مع العد التنازلي للجوائز"""
    board = get_leaderboard(10)
    countdown = get_competition_countdown()

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    lines = ["🏆 *لوحة أفضل المحيلين*\n"]

    if not board:
        lines.append("لا يوجد إحالات بعد. كن الأول! 🚀")
    else:
        for i, entry in enumerate(board):
            medal = medals[i] if i < len(medals) else f"{i+1}."
            uname = f" (@{entry['username']})" if entry.get("username") else ""
            name_safe = _escape_md(entry["name"])
            lines.append(f"{medal} {name_safe}{_escape_md(uname)} — *{entry['refs']}* إحالة")

    lines.append("")

    if countdown["ended"]:
        lines.append("🎉 *انتهت المسابقة!*")
        lines.append("تم توزيع الجوائز على المتصدرين.")
    else:
        lines.append(f"⏳ *الوقت المتبقي للجوائز:* `{countdown['days_left']}` يوم")
        lines.append(f"📅 تنتهي المسابقة: `{countdown['end_date']}`")
        lines.append("")
        lines.append("🎁 *الجوائز:*")
        lines.append("🥇 المركز الأول — رصيد إضافي خاص")
        lines.append("🥈 المركز الثاني — رصيد مكافأة")
        lines.append("🥉 المركز الثالث — رصيد مكافأة")

    lines.append("")
    lines.append("💡 كل إحالة = رصيد فوري + مكانة في اللوحة!")

    return "\n".join(lines)


def reset_competition(admin_id=None):
    """يعيد تعيين المسابقة من الصفر (للأدمن فقط)"""
    bd = load_bot_data()
    bd["competition"] = {
        "start_date": datetime.now().strftime("%Y-%m-%d"),
        "duration_days": 30
    }
    save_bot_data(bd)


# ============================================================================
#                  نظام الأكواد الترويجية (Promo Codes)
# ============================================================================

def create_promo_code(amount: float, max_users: int, created_by) -> str:
    """ينشئ كود ترويجي جديد ويرجع الكود"""
    bd = load_bot_data()
    if "promo_codes" not in bd:
        bd["promo_codes"] = {}
    
    # إنشاء كود عشوائي فريد
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        if code not in bd["promo_codes"]:
            break
    
    bd["promo_codes"][code] = {
        "amount": amount,
        "max_users": max_users,
        "used_by": [],
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "created_by": str(created_by)
    }
    save_bot_data(bd)
    return code

def redeem_promo_code(user_id, code: str) -> dict:
    """
    يستخدم المستخدم كود ترويجي.
    يرجع dict بـ: ok, message, amount
    """
    bd = load_bot_data()
    codes = bd.get("promo_codes", {})
    code = code.strip().upper()
    
    if code not in codes:
        return {"ok": False, "message": "❌ الكود غير موجود أو منتهي الصلاحية"}
    
    info = codes[code]
    uid = str(user_id)
    
    # تحقق إنه ما استخدمش الكود قبل كده
    if uid in info.get("used_by", []):
        return {"ok": False, "message": "❌ استخدمت هذا الكود من قبل"}
    
    # تحقق من عدد المستخدمين
    used_count = len(info.get("used_by", []))
    if used_count >= info["max_users"]:
        return {"ok": False, "message": "❌ انتهى عدد المستخدمين المسموح لهذا الكود"}
    
    # استخدم الكود
    info["used_by"].append(uid)
    save_bot_data(bd)
    
    # أضف الرصيد
    amount = float(info["amount"])
    new_balance = add_balance(user_id, amount)
    
    return {
        "ok": True,
        "message": f"✅ تم شحن `{amount:.2f}$` بنجاح!\n💰 رصيدك الآن: `{new_balance:.2f}$`",
        "amount": amount,
        "new_balance": new_balance
    }

def list_promo_codes() -> list:
    """يرجع قائمة كل الأكواد مع تفاصيلها"""
    bd = load_bot_data()
    codes = bd.get("promo_codes", {})
    result = []
    for code, info in codes.items():
        used = len(info.get("used_by", []))
        result.append({
            "code": code,
            "amount": info["amount"],
            "max_users": info["max_users"],
            "used": used,
            "remaining": info["max_users"] - used,
            "created_at": info.get("created_at", "")
        })
    return result

def convert_balance_to_code(user_id, num_people: int) -> dict:
    """يحول كامل رصيد المستخدم لكود مقسم على عدد الأشخاص"""
    balance = get_user_balance(user_id)
    if balance <= 0:
        return {"ok": False, "message": "❌ رصيدك صفر، لا يمكن التحويل"}
    if num_people <= 0:
        return {"ok": False, "message": "❌ عدد الأشخاص يجب أن يكون أكبر من صفر"}
    per_person = round(balance / num_people, 2)
    if per_person < 0.01:
        return {"ok": False, "message": "❌ القيمة لكل شخص أقل من الحد الأدنى (0.01$)"}
    if not deduct_balance(user_id, balance):
        return {"ok": False, "message": "❌ فشل خصم الرصيد"}
    code = create_promo_code(per_person, num_people, user_id)
    return {
        "ok": True, "code": code,
        "per_person": per_person, "num_people": num_people, "total": balance,
        "message": (
            f"✅ تم تحويل رصيدك بنجاح\\!\n\n"
            f"💰 الإجمالي: `{balance:.2f}$`\n"
            f"👥 عدد الأشخاص: `{num_people}`\n"
            f"💵 قيمة كل استخدام: `{per_person:.2f}$`\n\n"
            f"🎟️ الكود:\n`{code}`\n\n"
            f"أرسله لأصدقائك، يستخدمونه بـ `/PMC {code}`"
        )
    }

# ============================================================================
#                  نظام التخزين المسبق للتوكنات (للسرعة)
# ============================================================================

def load_tokens_cache() -> dict:
    """تحميل التوكنات المحملة مسبقاً"""
    if os.path.exists(TOKENS_CACHE_FILE):
        try:
            with open(TOKENS_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {"ready_tokens": [], "last_updated": ""}

def save_tokens_cache(data: dict):
    """حفظ التوكنات المحملة"""
    try:
        data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(TOKENS_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except: pass

def add_ready_token(email: str, device_id: str, token: str):
    """إضافة توكن جاهز للاستخدام — مع التحقق إنه مش مستعمل"""
    # ⚡ تحقق إن الحساب مش في قائمة المستعملين
    bd = load_bot_data()
    used_set = set(bd.get("used_accounts", []))
    if email in used_set:
        print(f"[tokens_cache] ⚠️ Skipping used account: {email}")
        return
    cache = load_tokens_cache()
    # نتأكد إنه مش موجود قبل كده
    ready_tokens = cache.get("ready_tokens", [])
    # نشيل القديم لو نفس الإيميل
    ready_tokens = [t for t in ready_tokens if t.get("email") != email]
    # نضيف الجديد
    ready_tokens.append({
        "email": email,
        "device_id": device_id,
        "token": token,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    cache["ready_tokens"] = ready_tokens
    save_tokens_cache(cache)
    print(f"[tokens_cache] ✅ Added ready token for {email}")

def get_ready_token() -> dict:
    """الحصول على توكن جاهز للاستخدام"""
    cache = load_tokens_cache()
    ready_tokens = cache.get("ready_tokens", [])
    if ready_tokens:
        return ready_tokens[-1]  # آخر واحد (LIFO)
    return None

def pop_ready_token() -> dict:
    """أخذ توكن جاهز وحذفه من القائمة — آمن للخيوط المتزامنة"""
    with _token_lock:
        cache = load_tokens_cache()
        ready_tokens = cache.get("ready_tokens", [])
        if ready_tokens:
            token_data = ready_tokens.pop()
            cache["ready_tokens"] = ready_tokens
            save_tokens_cache(cache)
            return token_data
    return None

def count_ready_tokens() -> int:
    """عدد التوكنات الجاهزة"""
    cache = load_tokens_cache()
    return len(cache.get("ready_tokens", []))

def cleanup_used_tokens_from_cache():
    """يزيل التوكنات المستعملة من الكاش — ينفذ مرة عند البداية"""
    bd = load_bot_data()
    used_set = set(bd.get("used_accounts", []))
    if not used_set:
        return 0
    cache = load_tokens_cache()
    ready_tokens = cache.get("ready_tokens", [])
    before = len(ready_tokens)
    ready_tokens = [t for t in ready_tokens if t.get("email", "") not in used_set]
    removed = before - len(ready_tokens)
    if removed > 0:
        cache["ready_tokens"] = ready_tokens
        save_tokens_cache(cache)
        print(f"[tokens_cache] 🧹 Cleaned up {removed} used tokens from cache ({before} → {len(ready_tokens)})")
    return removed

# ============================================================================
#                  نظام تسجيل المكالمات والمستخدمين
# ============================================================================

def load_call_logs() -> dict:
    """تحميل سجل المكالمات"""
    if os.path.exists(CALL_LOGS_FILE):
        try:
            with open(CALL_LOGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {
        "all_users": {},        # كل المستخدمين اللي دخلو
        "all_calls": [],        # كل المكالمات
        "all_phones": {}        # كل الأرقام اللي اشتغل عليها
    }

def save_call_logs(data: dict):
    """حفظ سجل المكالمات"""
    try:
        with open(CALL_LOGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except: pass

def log_user(user_id: int, username: str = "", first_name: str = ""):
    """تسجيل مستخدم جديد"""
    logs = load_call_logs()
    uid = str(user_id)
    if uid not in logs["all_users"]:
        logs["all_users"][uid] = {
            "username": username,
            "first_name": first_name,
            "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_calls": 0,
            "phones_called": []
        }
    else:
        # تحديث البيانات
        logs["all_users"][uid]["username"] = username or logs["all_users"][uid].get("username", "")
        logs["all_users"][uid]["first_name"] = first_name or logs["all_users"][uid].get("first_name", "")
    save_call_logs(logs)

def log_call(user_id: int, phone: str, from_num: str = "", success: bool = False, duration: int = 0):
    """تسجيل مكالمة"""
    logs = load_call_logs()
    uid = str(user_id)
    phone_clean = phone.replace("+", "")
    
    # تسجيل المكالمة
    call_record = {
        "user_id": uid,
        "phone": phone,
        "from_number": from_num,
        "success": success,
        "duration": duration,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    logs["all_calls"].append(call_record)
    
    # تحديث إحصائيات المستخدم
    if uid in logs["all_users"]:
        logs["all_users"][uid]["total_calls"] = logs["all_users"][uid].get("total_calls", 0) + 1
        if phone_clean not in logs["all_users"][uid].get("phones_called", []):
            logs["all_users"][uid].setdefault("phones_called", []).append(phone_clean)
    
    # تحديث قائمة الأرقام
    if phone_clean not in logs["all_phones"]:
        logs["all_phones"][phone_clean] = {
            "first_call": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_calls": 0,
            "users_called": []
        }
    logs["all_phones"][phone_clean]["total_calls"] = logs["all_phones"][phone_clean].get("total_calls", 0) + 1
    logs["all_phones"][phone_clean]["last_call"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if uid not in logs["all_phones"][phone_clean].get("users_called", []):
        logs["all_phones"][phone_clean].setdefault("users_called", []).append(uid)
    
    save_call_logs(logs)

DTMF_SETTINGS_FILE = os.path.join(DATA_DIR, "dtmf_settings.json")

_DEFAULT_DTMF_ACTIONS = {
    "0": {"action": "replay",   "label": "🔁 إعادة الصوت",     "enabled": True},
    "1": {"action": "confirm",  "label": "✅ موافق",             "enabled": True},
    "2": {"action": "reject",   "label": "❌ رافض",              "enabled": True},
    "9": {"action": "hangup",   "label": "📴 قطع المكالمة",     "enabled": True},
    "*": {"action": "notify",   "label": "⭐ نجمة",              "enabled": True},
    "#": {"action": "notify",   "label": "# هاش",               "enabled": True},
}

def load_dtmf_settings() -> dict:
    """إعدادات DTMF العامة (للأدمن / legacy)"""
    data = load_bot_data()
    stored = data.get("dtmf", {})
    if stored:
        return stored
    if os.path.exists(DTMF_SETTINGS_FILE):
        try:
            with open(DTMF_SETTINGS_FILE) as f:
                return json.load(f)
        except: pass
    return dict(_DEFAULT_DTMF_ACTIONS)

def save_dtmf_settings(settings: dict):
    data = load_bot_data()
    data["dtmf"] = settings
    save_bot_data(data)
    try:
        with open(DTMF_SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except: pass

def load_user_dtmf(user_id) -> dict:
    """يحمّل إعدادات DTMF الخاصة بالمستخدم — لو مفيش يرجع الافتراضي"""
    users_db = load_users_db()
    uid = str(user_id)
    stored = users_db.get(uid, {}).get("dtmf", {})
    if stored:
        return stored
    return dict(_DEFAULT_DTMF_ACTIONS)

def save_user_dtmf(user_id, settings: dict):
    """يحفظ إعدادات DTMF الخاصة بالمستخدم في users_db"""
    users_db = load_users_db()
    uid = str(user_id)
    if uid not in users_db:
        users_db[uid] = {"usage": 0, "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    users_db[uid]["dtmf"] = settings
    save_users_db(users_db)

def _sync_to_main():
    """يزامن users/premium/banned من الملفات القديمة للملف الموحد"""
    data = load_bot_data()
    for src, key in [(USERS_DB_FILE,'users'),(PREMIUM_DB_FILE,'premium'),(BANNED_DB_FILE,'banned')]:
        if os.path.exists(src):
            try:
                with open(src) as f:
                    data[key] = json.load(f)
            except: pass
    save_bot_data(data)

token = None
device_id = None
accounts = []
temp_email = None
temp_token = None
temp_api_type = None
ref = None

# إخفاء الألوان في الإخراج للمستخدم
G, R, Y, B, P, C, W, E = '', '', '', '', '', '', '', ''

DOMAINS = [
    "daouse.com", "bltiwd.com", "rommiui.com", "mrotzis.com", 
    "mkzaso.com", "illubd.com", "wnbaldwy.com", "xkxkud.com", 
    "yzcalo.com", "ozsaip.com", "bwmyga.com", "ruutukf.com", "inovic.com"
]

# ============================================================================
#                         نظام إدارة المستخدمين (JSON)
# ============================================================================

def load_users_db():
    """تحميل قاعدة بيانات المستخدمين"""
    if os.path.exists(USERS_DB_FILE):
        try:
            with open(USERS_DB_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_users_db(users_db):
    """حفظ قاعدة بيانات المستخدمين مع مزامنة GitHub"""
    with open(USERS_DB_FILE, 'w') as f:
        json.dump(users_db, f, indent=2)
    # مزامنة فورية مع GitHub عشان البيانات ماتروحش
    try:
        from github_sync import push_now
        push_now()
    except: pass

def load_premium_db():
    """تحميل قاعدة بيانات المميزين"""
    if os.path.exists(PREMIUM_DB_FILE):
        try:
            with open(PREMIUM_DB_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_premium_db(premium_db):
    """حفظ قاعدة بيانات المميزين مع مزامنة GitHub"""
    with open(PREMIUM_DB_FILE, 'w') as f:
        json.dump(premium_db, f, indent=2)
    try:
        from github_sync import push_now
        push_now()
    except: pass

def load_banned_db():
    """تحميل قاعدة بيانات المحظورين"""
    if os.path.exists(BANNED_DB_FILE):
        try:
            with open(BANNED_DB_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_banned_db(banned_db):
    """حفظ قاعدة بيانات المحظورين مع مزامنة GitHub"""
    with open(BANNED_DB_FILE, 'w') as f:
        json.dump(banned_db, f, indent=2)
    try:
        from github_sync import push_now
        push_now()
    except: pass

def get_user_usage(user_id):
    """الحصول على عدد استخدامات المستخدم"""
    users_db = load_users_db()
    user_id_str = str(user_id)
    if user_id_str not in users_db:
        users_db[user_id_str] = {"usage": 0, "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        save_users_db(users_db)
    return users_db[user_id_str]["usage"]

def increment_user_usage(user_id):
    """زيادة عدد استخدامات المستخدم"""
    users_db = load_users_db()
    user_id_str = str(user_id)
    if user_id_str not in users_db:
        users_db[user_id_str] = {"usage": 0, "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    users_db[user_id_str]["usage"] += 1
    users_db[user_id_str]["last_use"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_users_db(users_db)
    return users_db[user_id_str]["usage"]

def is_premium(user_id):
    """التحقق من أن المستخدم مميز"""
    premium_db = load_premium_db()
    return str(user_id) in premium_db

def is_premium_unlimited(user_id):
    """التحقق من أن المستخدم مميز غير محدود"""
    premium_db = load_premium_db()
    user_data = premium_db.get(str(user_id), {})
    return user_data.get("type", "limited") == "unlimited"

def get_premium_calls_left(user_id):
    """الحصول على عدد المكالمات المتبقية للمميز المحدود"""
    premium_db = load_premium_db()
    user_data = premium_db.get(str(user_id), {})
    if user_data.get("type", "limited") == "unlimited":
        return 999999  # غير محدود
    used = user_data.get("calls_used", 0)
    limit = user_data.get("calls_limit", 10)
    return max(0, limit - used)

def use_premium_call(user_id):
    """استخدام مكالمة من رصيد المميز"""
    premium_db = load_premium_db()
    uid = str(user_id)
    if uid in premium_db:
        if premium_db[uid].get("type", "limited") == "limited":
            premium_db[uid]["calls_used"] = premium_db[uid].get("calls_used", 0) + 1
            premium_db[uid]["last_use"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_premium_db(premium_db)
            return True
    return False

def is_banned(user_id):
    """التحقق من أن المستخدم محظور"""
    banned_db = load_banned_db()
    return str(user_id) in banned_db

def ban_user(user_id, reason=""):
    """حظر مستخدم وإضافته لقاعدة المحظورين"""
    banned_db = load_banned_db()
    uid = str(user_id)
    banned_db[uid] = {
        "reason": reason or "banned by admin",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_banned_db(banned_db)

def add_premium(user_id, admin_id=None, premium_type="limited", calls_limit=10):
    """إضافة مستخدم إلى المميزين
    
    premium_type: "limited" (10 مكالمات) أو "unlimited" (عدد لا نهائي)
    """
    premium_db = load_premium_db()
    user_id_str = str(user_id)
    premium_db[user_id_str] = {
        "added_by": admin_id,
        "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": premium_type,  # "limited" or "unlimited"
        "calls_limit": calls_limit if premium_type == "limited" else 999999,
        "calls_used": 0
    }
    save_premium_db(premium_db)
    return True

def remove_premium(user_id):
    """إزالة مستخدم من المميزين"""
    premium_db = load_premium_db()
    user_id_str = str(user_id)
    if user_id_str in premium_db:
        del premium_db[user_id_str]
        save_premium_db(premium_db)
        return True
    return False

def add_banned(user_id, admin_id=None, reason=""):
    """حظر مستخدم"""
    banned_db = load_banned_db()
    user_id_str = str(user_id)
    banned_db[user_id_str] = {
        "banned_by": admin_id,
        "banned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reason": reason
    }
    save_banned_db(banned_db)
    return True

def remove_banned(user_id):
    """فك حظر مستخدم"""
    banned_db = load_banned_db()
    user_id_str = str(user_id)
    if user_id_str in banned_db:
        del banned_db[user_id_str]
        save_banned_db(banned_db)
        return True
    return False

def get_referral_count(user_id):
    users_db = load_users_db()
    return users_db.get(str(user_id), {}).get("referrals", 0)

def get_user_level(user_id) -> dict:
    """مستوى المستخدم الجديد حسب VIP_TIERS"""
    refs = get_referral_count(user_id)
    tier = VIP_TIERS[0]
    for t in VIP_TIERS:
        if refs >= t["min"]:
            tier = t
    next_tier = None
    for t in VIP_TIERS:
        if t["min"] > refs:
            next_tier = t
            break
    needed = (next_tier["min"] - refs) if next_tier else 0
    return {
        "name":        tier["name"],
        "emoji":       tier["emoji"],
        "badge":       tier["badge"],
        "refs":        refs,
        "next":        next_tier["min"] if next_tier else None,
        "needed":      needed,
        "daily_calls": tier["daily_calls"],
        "perks":       f"{tier['daily_calls']} مكالمة/يوم + شارة {tier['badge'] or '⭐'}",
    }

# ─── نظام الاشتراك الشهري ─────────────────────────────────────────────────────

def _monthly_db_path():
    return os.path.join(DATA_DIR, "monthly_subs.json")

def load_monthly_subs() -> dict:
    path = _monthly_db_path()
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {}

def save_monthly_subs(data: dict):
    try:
        with open(_monthly_db_path(), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        try:
            from github_sync import push_now
            push_now()
        except: pass
    except: pass

def get_monthly_sub(user_id) -> dict | None:
    """يرجع بيانات الاشتراك الشهري للمستخدم أو None"""
    subs = load_monthly_subs()
    rec  = subs.get(str(user_id))
    if not rec:
        return None
    expires = datetime.strptime(rec["expires"], "%Y-%m-%d")
    if datetime.now() > expires:
        subs.pop(str(user_id), None)
        save_monthly_subs(subs)
        return None
    return rec

def is_monthly_subscriber(user_id) -> bool:
    return get_monthly_sub(user_id) is not None

def get_monthly_calls_left(user_id) -> int:
    rec = get_monthly_sub(user_id)
    if not rec:
        return 0
    plan = MONTHLY_PLANS.get(rec["plan"], {})
    total = plan.get("calls", 0)
    used  = rec.get("calls_used", 0)
    return max(0, total - used)

def use_monthly_call(user_id) -> bool:
    """يخصم مكالمة من الاشتراك الشهري"""
    subs = load_monthly_subs()
    uid  = str(user_id)
    rec  = subs.get(uid)
    if not rec:
        return False
    expires = datetime.strptime(rec["expires"], "%Y-%m-%d")
    if datetime.now() > expires:
        subs.pop(uid, None)
        save_monthly_subs(subs)
        return False
    plan  = MONTHLY_PLANS.get(rec["plan"], {})
    total = plan.get("calls", 0)
    used  = rec.get("calls_used", 0)
    if total == 999999 or used < total:
        subs[uid]["calls_used"] = used + 1
        save_monthly_subs(subs)
        return True
    return False

def add_monthly_sub(user_id, plan_key: str, granted_by=None) -> bool:
    """إضافة أو تجديد اشتراك شهري"""
    if plan_key not in MONTHLY_PLANS:
        return False
    subs = load_monthly_subs()
    uid  = str(user_id)
    expires = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    subs[uid] = {
        "plan":       plan_key,
        "granted_by": granted_by,
        "started":    datetime.now().strftime("%Y-%m-%d"),
        "expires":    expires,
        "calls_used": 0,
    }
    save_monthly_subs(subs)
    return True

def buy_monthly_sub_with_balance(user_id, plan_key: str) -> dict:
    """يوجه المستخدم للأشخاص المحددين للاشتراك بدلاً من خصم الرصيد"""
    plan = MONTHLY_PLANS.get(plan_key)
    if not plan:
        return {"ok": False, "msg": "خطة غير موجودة"}
    price = plan["price"]
    # Build seller info
    sellers_text = "\n".join([f"• {s['username']}" for s in SUBSCRIPTION_SELLERS])
    return {"ok": False, "msg": f"❌ يجب الاشتراك بهذه الميزة عند الأشخاص التاليين:\n\n{sellers_text}\n\n💰 سعر الخطة {plan['emoji']} {plan['name']}: `{price:.2f}$`"}

# ─── نظام اشتراك التطبيق ─────────────────────────────────────────────────────
APP_SUBS_FILE = os.path.join(DATA_DIR, "app_subs.json")

def load_app_subs() -> dict:
    if os.path.exists(APP_SUBS_FILE):
        try:
            with open(APP_SUBS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {}

def save_app_subs(data: dict):
    try:
        with open(APP_SUBS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except: pass

def get_app_sub(user_id) -> dict | None:
    subs = load_app_subs()
    rec = subs.get(str(user_id))
    if not rec:
        return None
    expires = datetime.strptime(rec["expires"], "%Y-%m-%d")
    if datetime.now() > expires:
        subs.pop(str(user_id), None)
        save_app_subs(subs)
        return None
    return rec

def is_app_subscriber(user_id) -> bool:
    return get_app_sub(user_id) is not None

def get_app_calls_left(user_id) -> int:
    rec = get_app_sub(user_id)
    if not rec:
        return 0
    plan = APP_SUBSCRIPTION_PLANS.get(rec["plan"], {})
    total = plan.get("calls", 0)
    used = rec.get("calls_used", 0)
    return max(0, total - used)

def use_app_call(user_id) -> bool:
    subs = load_app_subs()
    uid = str(user_id)
    rec = subs.get(uid)
    if not rec:
        return False
    expires = datetime.strptime(rec["expires"], "%Y-%m-%d")
    if datetime.now() > expires:
        subs.pop(uid, None)
        save_app_subs(subs)
        return False
    plan = APP_SUBSCRIPTION_PLANS.get(rec["plan"], {})
    total = plan.get("calls", 0)
    used = rec.get("calls_used", 0)
    if total == 999999 or used < total:
        subs[uid]["calls_used"] = used + 1
        save_app_subs(subs)
        return True
    return False

def add_app_sub(user_id, plan_key: str, granted_by=None) -> bool:
    if plan_key not in APP_SUBSCRIPTION_PLANS:
        return False
    subs = load_app_subs()
    uid = str(user_id)
    expires = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    subs[uid] = {
        "plan": plan_key,
        "granted_by": granted_by,
        "started": datetime.now().strftime("%Y-%m-%d"),
        "expires": expires,
        "calls_used": 0,
    }
    save_app_subs(subs)
    return True

def remove_app_sub(user_id) -> bool:
    subs = load_app_subs()
    uid = str(user_id)
    if uid in subs:
        del subs[uid]
        save_app_subs(subs)
        return True
    return False

def increment_user_calls(user_id) -> int:
    """يزيد عداد المكالمات الناجحة ويرجع العدد الجديد"""
    udb = load_users_db()
    uid = str(user_id)
    if uid not in udb:
        udb[uid] = {}
    udb[uid]["successful_calls"] = udb[uid].get("successful_calls", 0) + 1
    save_users_db(udb)
    return udb[uid]["successful_calls"]

def get_daily_calls_left(user_id):
    users_db = load_users_db()
    rec = users_db.get(str(user_id), {})
    today = datetime.now().strftime("%Y-%m-%d")
    if rec.get("daily_date", "") != today:
        return 1
    return max(0, 1 - rec.get("daily_used", 0))

def use_daily_call(user_id):
    """استخدام مكالمة من رصيد المستخدم (يخصم التكلفة من الرصيد)"""
    # الاشتراك الشهري له الأولوية
    if is_monthly_subscriber(user_id):
        use_monthly_call(user_id)
        return
    # لو مميز محدود، استخدم من رصيده المميز
    if is_premium(user_id) and not is_premium_unlimited(user_id):
        use_premium_call(user_id)
        return
    
    # خصم تكلفة المكالمة من الرصيد
    cost = get_call_cost()
    deduct_balance(user_id, cost)
    
    # تحديث آخر استخدام
    users_db = load_users_db()
    uid = str(user_id)
    if uid not in users_db:
        users_db[uid] = {"usage": 0, "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    users_db[uid]["last_use"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_users_db(users_db)

def check_user_access(user_id):
    """التحقق من صلاحية المستخدم للاستخدام"""
    if is_banned(user_id):
        return False, "محظور"
    if user_id in ADMIN_IDS:
        return True, "أدمن"

    # ── الاشتراك الشهري ──
    monthly = get_monthly_sub(user_id)
    if monthly:
        plan_info = MONTHLY_PLANS.get(monthly["plan"], {})
        left = get_monthly_calls_left(user_id)
        if plan_info.get("calls", 0) == 999999 or left > 0:
            left_str = "∞" if plan_info.get("calls",0) == 999999 else str(left)
            return True, f"{plan_info.get('emoji','📅')} اشتراك {plan_info.get('name','')} ({left_str} مكالمة متبقية)"
        else:
            expires = monthly.get("expires","")
            return False, f"📅 انتهت مكالمات اشتراكك الشهري\nيتجدد في: {expires}\nاشترِ خطة جديدة من *📅 اشتراك شهري*"

    # ── المميزون (premium) ──
    if is_premium(user_id):
        if is_premium_unlimited(user_id):
            return True, "⭐ مميز غير محدود (∞ مكالمات)"
        else:
            left = get_premium_calls_left(user_id)
            if left > 0:
                return True, f"⭐ مميز ({left} مكالمات متبقية)"
            else:
                return False, "⭐ انتهت مكالماتك المميزة"

    # ── الرصيد العادي ──
    cost = get_call_cost()
    balance = get_user_balance(user_id)
    if balance >= cost:
        return True, f"💰 رصيدك: `{balance:.2f}$`"

    # رصيد غير كافٍ
    refs = get_referral_count(user_id)
    required = get_required_referrals()
    bonus = get_daily_bonus_amount()
    if refs < required:
        return False, (
            f"💰 رصيدك: `{balance:.2f}$`\n"
            f"سعر المكالمة: `{cost:.2f}$`\n\n"
            f"للحصول على مكافأة `{bonus:.2f}$` يومياً تحتاج {required - refs} إحالة أخرى\n"
            f"أو اشترِ اشتراكاً شهرياً من *📅 اشتراك شهري*\n"
            f"أو استخدم كود شحن بـ /PMC"
        )
    else:
        return False, (
            f"💰 رصيدك: `{balance:.2f}$` (تحتاج `{cost:.2f}$`)\n\n"
            f"ستحصل على `{bonus:.2f}$` يومياً تلقائياً\n"
            f"أو اشترِ اشتراكاً شهرياً من *📅 اشتراك شهري*\n"
            f"أو استخدم كود شحن بـ /PMC"
        )

def get_welcome_bonus() -> float:
    """يرجع قيمة الرصيد الترحيبي للمستخدمين الجدد"""
    bd = load_bot_data()
    return float(bd.get("settings", {}).get("welcome_bonus", 0.50))

def log_user_entry(user_id, username, first_name, referred_by=None):
    """تسجيل دخول المستخدم وإشعار الأدمن"""
    users_db = load_users_db()
    user_id_str = str(user_id)

    is_new = user_id_str not in users_db

    # سجل في call_logs أيضاً
    log_user(user_id, username, first_name)

    if is_new:
        users_db[user_id_str] = {
            "usage": 0,
            "referrals": 0,
            "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "username": username or "",
            "first_name": first_name or ""
        }
        # 🎁 رصيد ترحيبي للمستخدم الجديد
        welcome_amount = get_welcome_bonus()
        if welcome_amount > 0:
            users_db[user_id_str]["balance"] = welcome_amount
        # لو جاء عن طريق إحالة نسجلها ونكافئ المحيل
        referral_rewarded = False
        if referred_by and str(referred_by) != user_id_str:
            ref_str = str(referred_by)
            if ref_str in users_db:
                users_db[ref_str]["referrals"] = users_db[ref_str].get("referrals", 0) + 1
                referral_rewarded = True
        save_users_db(users_db)

        # إضافة مكافأة الإحالة للمحيل بعد الحفظ
        if referral_rewarded:
            bonus_amount = get_referral_bonus()
            new_bal = add_balance(referred_by, bonus_amount)
            # إشعار المحيل
            try:
                _bot2 = telebot.TeleBot(BOT_TOKEN)
                _bot2.send_message(
                    referred_by,
                    f"🎉 *إحالة جديدة!*\n\n"
                    f"انضم شخص جديد عبر رابطك\n"
                    f"💰 مكافأة الإحالة: `{bonus_amount:.2f}$`\n"
                    f"💳 رصيدك الآن: `{new_bal:.2f}$`",
                    parse_mode='Markdown'
                )
            except:
                pass

        # بناء اليوزرنيم بالشكل الصح مع escape للرموز الخاصة
        uname_raw = f"@{username}" if username else "لا يوجد"
        uname_display = _escape_md(uname_raw)
        fname_display = _escape_md(first_name or "لا يوجد")

        for admin_id in ADMIN_IDS:
            try:
                _bot = telebot.TeleBot(BOT_TOKEN)
                bonus_info = f"\n🎁 رصيد ترحيبي: `{welcome_amount:.2f}$`" if welcome_amount > 0 else ""
                _bot.send_message(
                    admin_id,
                    f"🆕 مستخدم جديد!\n\n"
                    f"👤 المعرف: `{user_id}`\n"
                    f"📝 اليوزر: {uname_display}\n"
                    f"🏷️ الاسم: {fname_display}\n"
                    f"📅 التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{bonus_info}",
                    parse_mode='Markdown'
                )
            except:
                pass

    # تحديث الـ streak لكل المستخدمين (جديد أو قديم)
    update_user_streak(user_id)

    # تحديث اسم المستخدم للمستخدمين الموجودين
    if not is_new:
        _udb_upd = load_users_db()
        uid_str = str(user_id)
        if uid_str in _udb_upd:
            _udb_upd[uid_str]["username"] = username or _udb_upd[uid_str].get("username", "")
            _udb_upd[uid_str]["first_name"] = first_name or _udb_upd[uid_str].get("first_name", "")
            save_users_db(_udb_upd)

    return is_new

# ============================================================================
#                         دوال البوت الأساسية
# ============================================================================

def clear(): 
    pass  # نعطل المسح لأننا في تليجرام

def load_accounts():
    global accounts
    if os.path.exists(ACCOUNTS_FILE):
        try:
            # حاول فك التشفير أولاً
            decrypted = _decrypt_accounts(ACCOUNTS_FILE)
            accounts  = json.loads(decrypted)
            return len(accounts)
        except:
            try:
                # لو ملف قديم غير مشفر
                with open(ACCOUNTS_FILE, 'r') as f:
                    accounts = json.load(f)
                # احفظه مشفر فوراً
                _save_accounts_encrypted()
                return len(accounts)
            except:
                pass
    accounts = []
    return 0

def _save_accounts_encrypted():
    plain     = json.dumps(accounts, indent=2, ensure_ascii=False)
    encrypted = _encrypt_accounts(plain)
    with open(ACCOUNTS_FILE, 'wb') as f:
        f.write(encrypted)

def save_account(email, device, tok):
    accounts.append({"email": email, "x-client-device-id": device, "x-token": tok, "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    _save_accounts_encrypted()

# دوال إنشاء البريد المؤقت (مخفية تماماً)
def create_mob2_mail():
    url = "https://mob2.temp-mail.org/mailbox"
    headers = {'Accept': 'application/json', 'User-Agent': '3.49', 'Accept-Encoding': 'gzip'}
    try:
        response = requests.post(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            email = data.get('mailbox')
            tkn = data.get('token')
            if email and tkn:
                return {'email': email, 'token': tkn, 'api_type': 'mob2', 'success': True}
    except Exception as e:
        pass
    return None

def create_io_mail(domain=None, name=None):
    if not domain:
        domain = random.choice(DOMAINS)
    if not name:
        name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    url = "https://api.internal.temp-mail.io/api/v3/email/new"
    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Application-Name': 'web',
        'Application-Version': '2.2.29',
        'Origin': 'https://temp-mail.io',
        'User-Agent': 'Mozilla/5.0'
    }
    payload = {"domain": domain, "name": name}
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            email = data.get('email')
            if email:
                return {'email': email, 'token': email, 'api_type': 'io', 'success': True}
    except Exception as e:
        pass
    return None

def create_email_with_retry(max_retries=3):
    global temp_email, temp_token, temp_api_type
    for attempt in range(1, max_retries + 1):
        apis = [
            ('mob2', create_mob2_mail),
            ('io', lambda: create_io_mail(random.choice(DOMAINS))),
        ]
        for api_name, api_func in apis:
            result = api_func()
            if result and result.get('success'):
                temp_email = result['email']
                temp_token = result['token']
                temp_api_type = result['api_type']
                return True
        if attempt < max_retries:
            time.sleep(random.randint(2, 5))
    return False

def check_mob2_inbox(tkn):
    url = "https://mob2.temp-mail.org/messages"
    headers = {'Accept': 'application/json', 'User-Agent': '3.49', 'Authorization': tkn}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json().get('messages', [])
    except: pass
    return []

def check_io_inbox(email):
    url = f"https://api.internal.temp-mail.io/api/v3/email/{email}/messages"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
    except: pass
    return []

def get_otp():
    for i in range(24):
        time.sleep(5)
        try:
            messages = []
            if temp_api_type == 'mob2':
                messages = check_mob2_inbox(temp_token)
            elif temp_api_type == 'io':
                messages = check_io_inbox(temp_email)
            
            for msg in messages:
                content = str(msg.get('text', '') or msg.get('body', '') or msg.get('content', '') or msg)
                if 'teli' in content.lower():
                    m = re.search(r'\b(\d{6})\b', content)
                    if m:
                        return m.group(1)
        except: pass
    return None

# دوال TelliCall API
def get_headers(_token=None, _device_id=None):
    global token, device_id
    _t = _token if _token is not None else token
    _d = _device_id if _device_id is not None else device_id
    if not _d: _d = ''.join(random.choices('0123456789abcdef', k=16))
    return {"host": "api.telicall.com", "x-request-id": str(uuid.uuid4()), "user-agent": "Dalvik/2.1.0", "x-app-version": "1.2.1",
            "x-client-device-id": _d, "x-lang": "en", "x-os": "android", "x-os-version": "11",
            "x-req-timestamp": str(int(time.time() * 1000)), "x-req-signature": "-1", "content-type": "application/json", "x-token": _t or ""}

def init_session():
    global token
    h = get_headers(); h["x-token"] = ""
    body = {"countryCode": "eg", "deviceName": "Infinix X698", "notificationToken": "", "oldToken": "", "peerKey": str(random.randint(100, 999)), "timeZone": "Africa/Cairo", "localizationKey": ""}
    try:
        r = requests.post(f"{API_URL}/init", json=body, headers=h, timeout=15)
        if r.status_code == 200 and r.json().get('result', {}).get('token'):
            token = r.json()['result']['token']
            return True
    except: pass
    return False

def send_verify(email):
    global ref
    try:
        r = requests.post(f"{API_URL}/auth/send-email", json={'email': email}, headers=get_headers(), timeout=15)
        if r.status_code == 200 and r.json().get('result', {}).get('reference'):
            ref = r.json()['result']['reference']
            return True
    except: pass
    return False

def verify_otp(code):
    try:
        r = requests.post(f"{API_URL}/auth/verify-identity", json={'reference': ref, 'code': str(code)}, headers=get_headers(), timeout=15)
        if r.status_code == 200 and r.json().get('result', {}).get('user'):
            return r.json()['result']['user']
    except: pass
    return None

def create_account():
    global token, device_id, temp_email, temp_token, temp_api_type, ref
    token = device_id = temp_email = temp_token = temp_api_type = ref = None
    
    if not create_email_with_retry(max_retries=3):
        return False
    if not init_session():
        return False
    if not send_verify(temp_email):
        return False
    otp = get_otp()
    if not otp:
        return False
    user = verify_otp(otp)
    if user:
        save_account(temp_email, device_id, token)
        return True
    return False

def get_proxy_call_request(phone):
    """
    يرجع تفاصيل طلب المكالمة عشان التطبيق يعمله من آي بي المستخدم
    بدل ما السيرفر يعمل الطلب من آي بي السيرفر
    Returns: dict with {url, method, headers, body} or None if no accounts
    """
    with _token_lock:
        ready_token = pop_ready_token()
        call_token = None
        call_device_id = None
        email_used = ""

        if ready_token:
            call_token = ready_token.get("token")
            call_device_id = ready_token.get("device_id")
            email_used = ready_token.get("email", "")
        elif accounts:
            acc = accounts[-1]
            call_token = acc.get('x-token')
            call_device_id = acc.get('x-client-device-id')
            email_used = acc.get('email', '')
        else:
            return None

    if not call_token:
        # احذف الحساب الفاضي
        if email_used:
            _remove_account_by_email(email_used)
            mark_email_used(email_used)
        return None

    if not phone.startswith('+'):
        phone = '+' + phone

    headers = get_headers(_token=call_token, _device_id=call_device_id)

    return {
        "url": f"{API_URL}/call/outbound/start",
        "method": "POST",
        "headers": headers,
        "body": {"to": phone, "source": "numpad"},
        "email_used": email_used,
    }


def get_proxy_account_creation_requests():
    """
    يرجع خطوات إنشاء حساب جديدة عشان التطبيق ينفذها من آي بي المستخدم
    الخطوات: إنشاء إيميل → init session → send verify
    Returns: dict with step details or None
    """
    import random, string

    # إنشاء إيميل مؤقت
    domain = random.choice(DOMAINS) if DOMAINS else "daouse.com"
    name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    temp_email_addr = f"{name}@{domain}"
    device_id_str = ''.join(random.choices('0123456789abcdef', k=16))

    # بناء طلب init
    init_headers = get_headers(_token="", _device_id=device_id_str)
    init_headers["x-token"] = ""
    init_body = {
        "countryCode": "eg",
        "deviceName": "Infinix X698",
        "notificationToken": "",
        "oldToken": "",
        "peerKey": str(random.randint(100, 999)),
        "timeZone": "Africa/Cairo",
        "localizationKey": ""
    }

    # بناء طلب send-email
    send_email_headers = get_headers(_token="INIT_TOKEN_PLACEHOLDER", _device_id=device_id_str)

    # بناء طلب verify
    verify_headers = get_headers(_token="INIT_TOKEN_PLACEHOLDER", _device_id=device_id_str)

    return {
        "steps": [
            {
                "step": "init",
                "url": f"{API_URL}/init",
                "method": "POST",
                "headers": init_headers,
                "body": init_body,
                "extract": "result.token",  # المستخدم لازم يستخرج التوكن من الرد
            },
            {
                "step": "send_email",
                "url": f"{API_URL}/auth/send-email",
                "method": "POST",
                "headers": send_email_headers,
                "body": {"email": temp_email_addr},
                "extract": "result.reference",
            },
            {
                "step": "verify",
                "url": f"{API_URL}/auth/verify-identity",
                "method": "POST",
                "headers": verify_headers,
                "body": {"reference": "REFERENCE_PLACEHOLDER", "code": "OTP_PLACEHOLDER"},
                "extract": "result.user",
            }
        ],
        "temp_email": temp_email_addr,
        "device_id": device_id_str,
    }


def _try_telicall_call(phone, call_token, call_device_id, email_used=""):
    """محاولة مكالمة واحدة باستخدام توكن محدد"""
    if not phone.startswith('+'): phone = '+' + phone
    headers = get_headers(_token=call_token, _device_id=call_device_id)
    
    try:
        r = requests.post(f"{API_URL}/call/outbound/start", json={'to': phone, 'source': 'numpad'}, headers=headers, timeout=8)
        print(f"[start_call] 📡 Telicall API response: {r.status_code} (account: {email_used})")
        if r.status_code == 200 and r.json().get('result'):
            sip = r.json()['result'].get('sip', {})
            return {
                'user': sip.get('username'), 
                'pass': sip.get('password'), 
                'domain': sip.get('domain'),
                'port': sip.get('port', 5060), 
                'proto': sip.get('protocol', 'tcp'),
                'from': r.json()['result'].get('from', {}).get('msisdn'), 
                'to': r.json()['result'].get('to', {}).get('msisdn'),
                'limit': sip.get('callLimit', 60), 
                'balance': sip.get('balanceLimit', 60),
                'email_used': email_used
            }
        elif r.status_code == 400:
            err_text = r.text.lower()
            if 'balance' in err_text:
                print(f"[start_call] ❌ No balance on account {email_used}")
                return 'no_balance'
            else:
                print(f"[start_call] ❌ Telicall 400: {r.text[:200]}")
                return {'error': f"call_400"}
        elif r.status_code == 404:
            print(f"[start_call] ❌ API 404 for {email_used}")
            return {'error': 'call_404'}
        else:
            print(f"[start_call] ❌ API {r.status_code}: {r.text[:200]}")
            return {'error': f"call_{r.status_code}"}
    except Exception as e:
        print(f"[start_call] ❌ Exception for {email_used}: {e}")
        return None

def _remove_account_by_email(email: str):
    """يحذف حساب من قائمة accounts ويحفظ الملف مشفر — آمن للخيوط"""
    if not email:
        return
    with _token_lock:
        global accounts
        before = len(accounts)
        accounts = [a for a in accounts if a.get('email', '') != email]
        removed = before - len(accounts)
        if removed > 0:
            try:
                _save_accounts_encrypted()
            except Exception:
                pass
            print(f"[start_call] 🗑️ Removed {removed} account(s) for {email} from list")


def start_call(phone, max_retries=3):
    """
    يبدأ مكالمة - يفضل استخدام التوكنات المحملة مسبقاً للسرعة
    ⚠️ هذه الدالة آمنة للخيوط (thread-safe) — لا تستخدم globals للتوكن
    🔄 تكرر مع حسابات مختلفة لو الحساب الحالي فشل
    🗑️ يحذف الحساب الفاشل ويحطه في قائمة المستعملين ويمسك حساب تاني بسرعة
    ⏱️ تم تقليل timeout و max_retries عشان التطبيق يرد أسرع
    """
    no_balance_count = 0
    last_failed_email = ""

    for attempt in range(max_retries):
        # 🚀 نحاول نستخدم توكن جاهز من الكاش
        ready_token = pop_ready_token()
        call_token = None
        call_device_id = None
        email_used = ""

        if ready_token:
            call_token = ready_token.get("token")
            call_device_id = ready_token.get("device_id")
            email_used = ready_token.get("email", "")
            print(f"[start_call] ⚡ Attempt {attempt+1}/{max_retries}: cached token for {email_used}")
        elif accounts:
            with _token_lock:
                acc = accounts[-1]
                call_token = acc.get('x-token')
                call_device_id = acc.get('x-client-device-id')
                email_used = acc.get('email', '')
            print(f"[start_call] 📂 Attempt {attempt+1}/{max_retries}: account file {email_used}")
        else:
            print(f"[start_call] ❌ No accounts available")
            return None

        if not call_token:
            print(f"[start_call] ❌ No token available")
            # احذف الحساب الفاضي من القائمة
            if email_used:
                _remove_account_by_email(email_used)
                mark_email_used(email_used)
            continue

        result = _try_telicall_call(phone, call_token, call_device_id, email_used)

        if result is None or isinstance(result, dict) and "error" in result:
            # 🗑️ حذف الحساب الفاشل ووضعه في قائمة المستعملين
            err = result.get("error", "") if isinstance(result, dict) else ""
            print(f"[start_call] ❌ Account {email_used} failed with error: {err or 'None'}")

            # احذف الحساب من accounts وسجله كمستعمل
            if email_used and email_used != last_failed_email:
                _remove_account_by_email(email_used)
                mark_email_used(email_used)
                last_failed_email = email_used

            if "404" in err or "400" in err or "call_" in err:
                # جرب حساب تاني فوراً بدون انتظار
                print(f"[start_call] 🔄 Switching to next account immediately (error: {err})...")
                continue
            if result == 'no_balance':
                no_balance_count += 1
                if no_balance_count >= 2:
                    return 'no_balance'
                # جرب حساب تاني فوراً بدون انتظار
                print(f"[start_call] 🔄 No balance, switching to next account immediately...")
                continue
            # خطأ تاني - ارجع النتيجة
            return result

        # نجاح!
        return result

    return None

# ============================================================================
#                         دوال SIP والمكالمات
# ============================================================================

class SIP:
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
        self.remote_tag  = None
        self.voice_pcmu  = []
        self.voice_idx   = 0
        self.dtmf_callback = None
        self._voice_base_pkt  = 0      # للـ replay: نبدأ منين
        self._replay_requested = False  # طلب replay
        self._force_hangup    = False   # طلب قطع فوري
    
    def conn(self):
        try:
            self.sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sk.settimeout(30)
            if self.pr == 'tls':
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                self.sk = context.wrap_socket(self.sk, server_hostname=self.d)
            self.sk.connect((self.d, self.pt))
            return True
        except Exception as e:
            return False
    
    def _pauth(self, h):
        for k, p in [('rs', r'realm="([^"]+)"'), ('rn', r'nonce="([^"]+)"'), ('ro', r'opaque="([^"]+)"'), ('rq', r'qop="([^"]+)"')]:
            m = re.search(p, h)
            if m: setattr(self, k, m.group(1))
    
    def _auth(self, method, uri):
        if not self.rs or not self.rn: return None
        h1 = hashlib.md5(f"{self.u}:{self.rs}:{self.p}".encode()).hexdigest()
        h2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
        if self.rq:
            nc, cn = "00000001", uuid.uuid4().hex[:8]
            rp = hashlib.md5(f"{h1}:{self.rn}:{nc}:{cn}:{self.rq}:{h2}".encode()).hexdigest()
            return f'Digest username="{self.u}",realm="{self.rs}",nonce="{self.rn}",uri="{uri}",response="{rp}",opaque="{self.ro}",qop={self.rq},nc={nc},cnonce="{cn}",algorithm=MD5'
        rp = hashlib.md5(f"{h1}:{self.rn}:{h2}".encode()).hexdigest()
        return f'Digest username="{self.u}",realm="{self.rs}",nonce="{self.rn}",uri="{uri}",response="{rp}",opaque="{self.ro}",algorithm=MD5'
    
    def send(self, msg):
        try:
            if isinstance(msg, str): msg = msg.encode()
            self.sk.send(msg)
            return True
        except: return False
    
    def recv(self, timeout=10):
        try:
            self.sk.settimeout(timeout)
            data = b''
            while True:
                chunk = self.sk.recv(4096)
                if not chunk: break
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
                    except: break
            return data.decode('utf-8', errors='ignore')
        except: return None
    
    def parse(self, resp):
        if not resp: return None
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
        if m: to_tag = m.group(1)
        
        sdp_ip, sdp_port = None, None
        if '\r\n\r\n' in resp:
            sdp = resp.split('\r\n\r\n', 1)[1]
            m = re.search(r'c=IN IP4 ([\d.]+)', sdp)
            if m: sdp_ip = m.group(1)
            m = re.search(r'm=audio (\d+)', sdp)
            if m: sdp_port = int(m.group(1))
        
        return {'code': code, 'headers': headers, 'to_tag': to_tag, 'sdp_ip': sdp_ip, 'sdp_port': sdp_port}
    
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
            if a: msg += f"Authorization: {a}\r\n"
        
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
            if a: msg += f"Authorization: {a}\r\n"

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
        except Exception as e:
            return False
    
    _ULAW_TABLE = None

    @staticmethod
    def _build_ulaw_table():
        table = []
        for u in range(256):
            u = ~u & 0xFF
            sign = u & 0x80
            exp  = (u >> 4) & 0x07
            mant = u & 0x0F
            val  = ((mant << 1) | 1) << (exp + 2)
            val -= 33
            if sign:
                val = -val
            table.append(max(-32768, min(32767, val)))
        return table

    def _ulaw_to_linear(self, data):
        if SIP._ULAW_TABLE is None:
            SIP._ULAW_TABLE = SIP._build_ulaw_table()
        out = bytearray()
        for b in data:
            v = SIP._ULAW_TABLE[b]
            out += struct.pack('<h', v)
        return bytes(out)

    def _alaw_to_linear(self, data):
        out = bytearray()
        for b in data:
            b ^= 0x55
            sign = b & 0x80
            exp  = (b >> 4) & 0x07
            mant = b & 0x0F
            if exp:
                val = ((mant | 0x10) << 1 | 1) << (exp - 1)
            else:
                val = (mant << 1) | 1
            val <<= 3
            if sign:
                val = -val
            out += struct.pack('<h', max(-32768, min(32767, val)))
        return bytes(out)

    def build_rtp(self, payload, is_voice_pkt=False):
        # pt=8 (PCMA) للصوت المحمّل، pt=0 (PCMU) للصمت
        pt = 8 if (is_voice_pkt and getattr(self, '_voice_is_pcma', False)) else 0
        first = (2 << 6) | 0
        header = struct.pack('!BBHII', first, pt, self.rtp_seq, self.rtp_ts, self.ssrc)
        self.rtp_seq = (self.rtp_seq + 1) & 0xFFFF
        self.rtp_ts += 160
        return header + payload

    VOICE_DELAY_PKTS = 15  # 15 packet = 300ms صمت قبل بداية الفويس

    def send_rtp(self, pkt_index=None):
        if not self.rtp_ip or not self.rtp_pt or not self.rtp_sk:
            return False
        is_voice = False
        if self.voice_pcmu and pkt_index is not None:
            # لو في طلب replay نعيد ضبط الـ base
            if self._replay_requested:
                self._replay_requested = False
                self._voice_base_pkt = pkt_index
            voice_idx = pkt_index - self._voice_base_pkt - self.VOICE_DELAY_PKTS
            if 0 <= voice_idx < len(self.voice_pcmu):
                payload  = self.voice_pcmu[voice_idx]
                is_voice = True
            else:
                payload = bytes([0xFF] * 160)
        else:
            payload = bytes([0xFF] * 160)
        pkt = self.build_rtp(payload, is_voice_pkt=is_voice)
        try:
            self.rtp_sk.sendto(pkt, (self.rtp_ip, self.rtp_pt))
            return True
        except: return False

    def rtp_loop(self, stop_evt, dur):
        import time as _time
        import audioop

        PTIME = 0.020
        start = _time.perf_counter()

        recv_buf: dict = {}
        expected_seq   = [None]
        recv_count     = [0]
        rtp_sources    = set()
        recv_lock      = threading.Lock()

        def _recv_worker():
            sock = self.rtp_sk
            try: sock.settimeout(1.0)
            except: pass
            while self.rtp_run and not stop_evt.is_set():
                try:
                    data, addr = sock.recvfrom(4096)
                    if len(data) < 12:
                        continue
                    rtp_sources.add(addr[0])
                    seq = struct.unpack("!H", data[2:4])[0]
                    pt  = data[1] & 0x7F
                    raw = data[12:]

                    if pt == 101 and len(raw) >= 4:
                        event    = raw[0]
                        end_bit  = bool(raw[1] & 0x80)
                        DTMF_MAP = {
                            0:'0',1:'1',2:'2',3:'3',4:'4',5:'5',
                            6:'6',7:'7',8:'8',9:'9',10:'*',11:'#',
                            12:'A',13:'B',14:'C',15:'D'
                        }
                        if event in DTMF_MAP:
                            digit = DTMF_MAP[event]
                            if not hasattr(self, '_active_dtmf'):
                                self._active_dtmf = set()
                            if end_bit:
                                if event in self._active_dtmf:
                                    self._active_dtmf.discard(event)
                                    if self.dtmf_callback:
                                        try: self.dtmf_callback(digit)
                                        except: pass
                            else:
                                self._active_dtmf.add(event)
                        continue

                    if pt == 8:
                        pcm = audioop.alaw2lin(raw, 2)
                    else:
                        pcm = audioop.ulaw2lin(raw, 2)

                    with recv_lock:
                        if expected_seq[0] is None:
                            expected_seq[0] = seq
                        recv_buf[seq] = pcm
                        recv_count[0] += 1

                        while expected_seq[0] in recv_buf:
                            self.audio.append(recv_buf.pop(expected_seq[0]))
                            expected_seq[0] = (expected_seq[0] + 1) & 0xFFFF

                except socket.timeout:
                    continue
                except OSError:
                    break
                except Exception:
                    pass

        recv_thread = threading.Thread(target=_recv_worker, daemon=True)
        recv_thread.start()

        sent      = 0
        next_send = start

        while self.rtp_run and not stop_evt.is_set():
            now = _time.perf_counter()
            if now - start >= dur:
                break

            if now >= next_send:
                # نمرر رقم الـ packet المحدد → voice_idx مرتبط بعدد الـ packets المرسلة
                self.send_rtp(pkt_index=sent)
                sent     += 1
                next_send = start + sent * PTIME

            # busy-wait دقيق للـ 2ms الأخيرة، sleep للباقي
            remaining = next_send - _time.perf_counter()
            if remaining > 0.003:
                _time.sleep(remaining - 0.002)
            # busy-wait للدقة على Android
            while _time.perf_counter() < next_send:
                pass

        stop_evt.set()
        recv_thread.join(timeout=2.0)

        with recv_lock:
            for seq in sorted(recv_buf.keys()):
                self.audio.append(recv_buf.pop(seq))

    def stop_rtp(self):
        self.rtp_run = False
        if self.rtp_sk:
            try: self.rtp_sk.close()
            except: pass

    def get_audio_bytes(self) -> bytes:
        """يرجع WAV bytes في الذاكرة بدون حفظ على الجهاز"""
        if not self.audio:
            return b''
        try:
            import io as _io
            raw = b''.join(self.audio)
            # حاول normalize بـ numpy إذا كان موجود
            try:
                import numpy as _np
                s = _np.frombuffer(raw, dtype='<i2').astype(_np.float32)
                rms = float(_np.sqrt(_np.mean(s**2)))
                if rms > 0:
                    gain = min(8000.0 / rms, 6.0)
                    s = _np.clip(s * gain, -32768, 32767)
                raw = s.astype(_np.int16).tobytes()
            except Exception:
                pass  # استمر بدون normalize لو numpy مش متاح
            buf = _io.BytesIO()
            with wave.open(buf, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(8000)
                wf.writeframes(raw)
            result_bytes = buf.getvalue()
            print(f"[get_audio_bytes] WAV size: {len(result_bytes)} bytes")
            return result_bytes
        except Exception as e:
            print(f"[get_audio_bytes] error: {e}")
            return b''

    def save_audio(self, fn):
        data = self.get_audio_bytes()
        if not data: return False
        try:
            with open(fn, 'wb') as f: f.write(data)
            return True
        except: return False
    
    def load_voice(self, pcm_bytes: bytes):
        import audioop
        self.voice_pcmu = []
        self.voice_idx  = 0

        # تأكد إن الـ pcm_bytes عبارة عن raw s16le 8000Hz
        # حجم صحيح: عدد زوجي من البايتات
        if len(pcm_bytes) % 2 != 0:
            pcm_bytes = pcm_bytes[:-1]

        # normalize بناءً على RMS عشان الصوت يوصل بقوة كافية
        import struct as _struct, math as _math
        samples = [_struct.unpack_from('<h', pcm_bytes, i)[0]
                   for i in range(0, len(pcm_bytes)-1, 2)]
        if samples:
            rms = _math.sqrt(sum(s*s for s in samples) / len(samples)) or 1
            # نرفع لـ RMS = 8000 (مستوى جيد للـ VoIP)
            target_rms = 8000
            gain = min(target_rms / rms, 8.0)
            if gain > 1.1:
                pcm_bytes = audioop.mul(pcm_bytes, 2, gain)

        # تحويل PCM 16-bit → PCMA (G.711 alaw) — أوضح من ulaw
        pcma_all = audioop.lin2alaw(pcm_bytes, 2)

        CHUNK = 160
        for i in range(0, len(pcma_all), CHUNK):
            chunk = pcma_all[i:i+CHUNK]
            if len(chunk) < CHUNK:
                chunk = chunk + bytes([0xD5] * (CHUNK - len(chunk)))  # صمت PCMA
            self.voice_pcmu.append(chunk)  # نستخدم نفس الـ list

        dur_calc = len(self.voice_pcmu) * 20 / 1000
        print(f"[voice] {len(self.voice_pcmu)} chunks = {dur_calc:.1f}s | PCMA")
        self._voice_is_pcma = True

    def close(self):
        self.stop_rtp()
        if self.sk:
            try: self.sk.close()
            except: pass

# دوال المكالمات (مخفية)
def make_call(phone, dur=60, auto_create=True, max_retries=5, min_answered_duration=5, voice_pcm=None, dtmf_cb=None, status_cb=None, user_id=None, display_phone=None):
    os.makedirs(RECORDINGS_DIR, exist_ok=True)

    declined_count = 0  # عداد الرفض — نوقف بعد مرتين
    email_used_for_call = ""  # لتتبع الحساب المستخدم

    for retry_num in range(1, max_retries + 1):
        if retry_num > 1:
            time.sleep(random.randint(3, 7))

        # ── إذا ما في حسابات ولا توكنات جاهزة، أنشئ واحد ──────────────────────────────
        ready_count = count_ready_tokens()
        if not accounts and ready_count == 0 and auto_create:
            if status_cb:
                try: status_cb("🔄 جاري إنشاء حساب جديد...")
                except: pass
            created = False
            for _att in range(5):   # حاول 5 مرات
                if create_account():
                    created = True
                    break
                time.sleep(random.randint(3, 8))
            if not created:
                if status_cb:
                    try: status_cb("❌ تعذر إنشاء حساب — جاري الإعادة...")
                    except: pass
                time.sleep(5)
                continue  # محاولة جديدة

        # ── استخدم التوكنات الجاهزة أولاً أو الحسابات الموجودة ─────────────────────────────────────
        if ready_count == 0 and not accounts:
            continue

        info = start_call(phone)
        email_used_for_call = info.get('email_used', '') if isinstance(info, dict) else ''

        # لو الرصيد خلص → احذف الحساب وجرب الحساب التالي
        if info == 'no_balance' or info is None:
            if accounts:
                bad = accounts[-1]
                bad_email = bad.get("email", "") if isinstance(bad, dict) else ""
                accounts.pop()
                try: _save_accounts_encrypted()
                except: pass
                if bad_email:
                    mark_email_used(bad_email)
            continue  # يرجع للحلقة ويجيب حساب جديد لو الـ list فاضي

        from_num = str(info.get('from', '')).replace('+', '') if isinstance(info, dict) else ''
        res = _do_single_call(phone, dur, info, min_answered_duration,
                              voice_pcm=voice_pcm, dtmf_cb=dtmf_cb, status_cb=status_cb,
                              display_phone=display_phone)
        result, rec_data, call_from = res if isinstance(res, tuple) else (res, b'', from_num)

        if result == 'answered_ok':
            # ✅ المكالمة تمت بنجاح - سجل الحساب كمستعمل
            if email_used_for_call:
                mark_email_used(email_used_for_call)
            
            # سجل المكالمة
            if user_id:
                log_call(user_id, phone, call_from, success=True, duration=dur)
            
            # احذف من accounts لو موجود
            if accounts:
                accounts.pop()
                try: _save_accounts_encrypted()
                except: pass
            return True, call_from, rec_data

        elif result == 'answered_short':
            # رد وقطع بسرعة → احذف الحساب وسجله كمستعمل
            if email_used_for_call:
                mark_email_used(email_used_for_call)
            if accounts:
                accounts.pop()
                try: _save_accounts_encrypted()
                except: pass
            continue

        elif result in ('no_answer', 'no_ring', 'failed', 'not_found'):
            # ما ردش أو فشل → ابقى على نفس الحساب
            # سجل المحاولة الفاشلة
            if user_id:
                log_call(user_id, phone, call_from, success=False, duration=0)
            continue

        elif result == 'declined':
            # 📵 مشغول - يقفل فوراً من غير إعادة المحاولة
            if status_cb:
                try: status_cb("📵 مشغول - تم الإيقاف")
                except: pass
            return False, None, b''

    return False, None, b''

def _do_single_call(phone, dur, info, min_answered_duration=5, voice_pcm=None, dtmf_cb=None, status_cb=None, display_phone=None):
    def _notify(msg):
        if status_cb:
            try: status_cb(msg)
            except: pass

    # الرقم اللي المستخدم بيشوفه (لو مش محدد، نستخدم الرقم الفعلي)
    shown_phone = display_phone or phone

    sip = SIP(info['user'], info['pass'], info['domain'], info['port'], info['proto'])
    sip._from_num = str(info.get('from', '')).replace('+', '')
    if voice_pcm:
        sip.load_voice(voice_pcm)
    if dtmf_cb:
        sip.dtmf_callback = dtmf_cb

    _sip_registry[id(sip)] = sip
    _current_sip[0] = sip

    if not sip.conn():
        return ('failed', b'', '')

    sip.register(auth=False)
    r = sip.recv(10)
    if r:
        p = sip.parse(r)
        if p and p['code'] == 401:
            sip._pauth(p['headers'].get('www-authenticate', ''))
            sip.register(auth=True)
            sip.recv(10)

    num = phone.replace('+', '')
    sip.invite(num, auth=False)
    r = sip.recv(10)

    if not r:
        sip.close(); return ('failed', b'', '')

    p = sip.parse(r)
    if not p or p['code'] != 401:
        sip.close(); return ('failed', b'', '')

    sip._pauth(p['headers'].get('www-authenticate', ''))
    sip.seq -= 1
    sip.invite(num, auth=True)

    _notify(f"📞 جاري الاتصال بـ {shown_phone}")

    ringing_started = False
    call_answered   = False
    sdp_ip = sdp_port = None

    for i in range(120):
        r = sip.recv(0.5)
        if r:
            p = sip.parse(r)
            code = p['code'] if p else 0

            if code == 100:
                pass
            elif code == 180 or code == 183:
                if not ringing_started:
                    _notify("📳 يرن...")
                    ringing_started = True
            elif code == 200:
                call_answered = True
                sip.remote_tag = p['to_tag']
                sdp_ip   = p['sdp_ip']
                sdp_port = p['sdp_port']
                
                # 🎯 نتأكد إن فيه SDP صحيح
                if not sdp_ip or not sdp_port:
                    _notify("❌ رد غير صالح")
                    sip.close(); return ('failed', b'', sip._from_num or '')
                
                # 🎯 نرسل ACK فوراً
                sip.ack(num)
                
                # 🔍 انتظار 2 ثانية للتحقق من BYE الفوري (رد وقطع)
                sip.sk.settimeout(0.2)
                instant_bye = False
                for _check in range(10):  # 10 مرات × 0.2 ثانية = 2 ثانية
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
                    _notify("📵 رد وقطع فوراً")
                    sip.close()
                    return ('declined', b'', sip._from_num or '')
                
                _notify("✅ تم الرد!")
                break
            elif code == 486:
                _notify("📵 مشغول")
                sip.close(); return ('declined', b'', sip._from_num or '')
            elif code == 487:
                _notify("↩️ ألغيت")
                sip.close(); return ('declined', b'', sip._from_num or '')
            elif code == 603:
                _notify("🚫 رفض")
                sip.close(); return ('declined', b'', sip._from_num or '')
            elif code == 404:
                _notify("❌ الرقم غير موجود")
                sip.close(); return ('not_found', b'', sip._from_num or '')
            elif code >= 400:
                _notify(f"⚠️ كود {code}")
                sip.close(); return ('declined', b'', sip._from_num or '')

    if not call_answered:
        if ringing_started:
            _notify("📵 لم يرد أحد")
        sip.close()
        r = 'no_answer' if ringing_started else 'failed'
        return (r, b'', sip._from_num or '')

    sip.rtp_ip = sdp_ip  if sdp_ip   else sip.d
    sip.rtp_pt = sdp_port if sdp_port else 5004

    stop_evt = threading.Event()
    if sip.start_rtp():
        rt = threading.Thread(target=sip.rtp_loop, args=(stop_evt, dur))
        rt.daemon = True
        rt.start()

    time.sleep(0.5)  # نستنى RTP يستقر
    start_time = time.time()
    deadline   = start_time + dur
    call_ended = False
    end_reason = "⏱️ انتهت المدة"

    # كشف BYE فوري — timeout 0.1s
    sip.sk.settimeout(0.1)
    last_notify = time.time()
    while time.time() < deadline:
        # hangup من DTMF؟
        if sip._force_hangup:
            call_ended = False
            end_reason = "📴 قُطعت المكالمة بطلبك"
            break
        try:
            chk = sip.sk.recv(4096)
            if chk:
                chk_str = chk.decode('utf-8', errors='ignore')
                if 'BYE ' in chk_str:
                    first = chk_str.strip().split('\r\n')[0] if '\r\n' in chk_str else chk_str.strip().split('\n')[0]
                    if first.startswith('BYE ') or '\r\nBYE ' in chk_str or '\nBYE ' in chk_str:
                        sip.ok(chk_str)
                        call_ended = True
                        end_reason = "📴 أغلق الطرف الآخر المكالمة"
                        break
        except: pass
        # تم إلغاء الإشعارات المزعجة - المكالمة هتقفل فوراً لما الطرف التاني يغلق

    actual = min(int(time.time() - start_time), dur)  # مش يتجاوز الـ dur المحدد
    stop_evt.set()
    sip.stop_rtp()

    if not call_ended:
        sip.bye(num)

    # ✅ إرسال نتيجة المكالمة فوراً
    _notify(f"{end_reason}\n⏱️ المدة: {actual}s")

    # حفظ التسجيل في memory فقط — بدون حفظ على الجهاز
    from_num = sip._from_num or phone.replace('+','')
    recording_data = sip.get_audio_bytes()  # bytes مباشرة
    sip.close()

    status = 'answered_ok' if actual >= min_answered_duration else 'answered_short'
    return (status, recording_data, from_num)

def multi_call(phone, attempts=5, dur=60, voice_pcm=None, dtmf_cb=None, status_cb=None, user_id=None, display_phone=None):
    clean_phone    = phone.lstrip('+')
    declined_count = 0
    email_used_for_call = ""

    for i in range(1, attempts + 1):
        # أنشئ حساب بس لو ما في حسابات ولا توكنات جاهزة
        ready_count = count_ready_tokens()
        if not accounts and ready_count == 0:
            if status_cb:
                try: status_cb("🔄 جاري إنشاء حساب جديد...")
                except: pass
            created = False
            for _att in range(5):
                if create_account():
                    created = True
                    break
                time.sleep(random.randint(3, 8))
            if not created:
                if status_cb:
                    try: status_cb("❌ تعذر إنشاء حساب — جاري الإعادة...")
                    except: pass
                if i < attempts:
                    time.sleep(5)
                continue

        info = start_call('+' + clean_phone)
        email_used_for_call = info.get('email_used', '') if isinstance(info, dict) else ''

        if info == 'no_balance' or info is None:
            if accounts:
                bad = accounts[-1]
                bad_email = bad.get("email", "") if isinstance(bad, dict) else ""
                accounts.pop()
                try: _save_accounts_encrypted()
                except: pass
                if bad_email:
                    mark_email_used(bad_email)
            if i < attempts:
                time.sleep(random.randint(3, 7))
            continue

        res    = _do_single_call('+' + clean_phone, dur, info,
                                 min_answered_duration=5,
                                 voice_pcm=voice_pcm, dtmf_cb=dtmf_cb, status_cb=status_cb,
                                 display_phone=display_phone)
        result = res[0] if isinstance(res, tuple) else res
        call_from = res[2] if isinstance(res, tuple) and len(res) > 2 else ''

        if result == 'answered_ok':
            # ✅ المكالمة تمت بنجاح - سجل الحساب كمستعمل
            if email_used_for_call:
                mark_email_used(email_used_for_call)

            # سجل المكالمة
            if user_id:
                log_call(user_id, phone, call_from, success=True, duration=dur)

            if accounts:
                accounts.pop()
                try: _save_accounts_encrypted()
                except: pass

            rec_data = res[1] if isinstance(res, tuple) and len(res) > 1 else b''
            return (True, rec_data, call_from)

        elif result == 'answered_short':
            # رد وقطع بسرعة → سجل الحساب كمستعمل
            if email_used_for_call:
                mark_email_used(email_used_for_call)
            if accounts:
                accounts.pop()
                try: _save_accounts_encrypted()
                except: pass

        elif result == 'declined':
            # 📵 مشغول - يقفل فوراً من غير إعادة المحاولة
            if status_cb:
                try: status_cb("📵 مشغول - تم الإيقاف")
                except: pass
            return False

        if i < attempts:
            time.sleep(random.randint(5, 15))

    return False

# ============================================================================
#                  نظام البوتات الفرعية (Sub-Bots)
# ============================================================================

SUB_BOTS_FILE = os.path.join(DATA_DIR, "sub_bots.json")
_running_sub_bots: dict = {}  # token -> thread
_main_bot_instance = None    # البوت الرئيسي (يُستخدم في التحقق من الاشتراك للبوتات الفرعية)


def get_bot_instance():
    """Return the main Telegram bot instance (used by foxapp_api for notifications)."""
    return _main_bot_instance

def load_sub_bots() -> list:
    if os.path.exists(SUB_BOTS_FILE):
        try:
            with open(SUB_BOTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return []

def save_sub_bots(bots_list: list):
    try:
        with open(SUB_BOTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(bots_list, f, ensure_ascii=False, indent=2)
    except: pass

def register_sub_bot_to_file(token: str, owner_id: int, username: str) -> bool:
    bots = load_sub_bots()
    for b in bots:
        if b["token"] == token:
            return False
        if b.get("username", "").lower() == username.lower():
            return False
    bots.append({
        "token": token, "owner_id": owner_id, "username": username,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    save_sub_bots(bots)
    # مزامنة فورية مع GitHub عشان التوكن يتحفظ
    try:
        from github_sync import push_now
        push_now()
    except: pass
    return True

MAX_SUB_BOTS_PER_USER = 3   # الحد الأقصى للبوتات الفرعية لكل مستخدم

def get_user_sub_bots(owner_id: int) -> list:
    return [b for b in load_sub_bots() if b.get("owner_id") == owner_id]

def user_reached_sub_bot_limit(owner_id: int) -> bool:
    """يتحقق إذا وصل المستخدم للحد الأقصى من البوتات الفرعية"""
    return len(get_user_sub_bots(owner_id)) >= MAX_SUB_BOTS_PER_USER

def delete_sub_bot(token: str):
    bots = [b for b in load_sub_bots() if b["token"] != token]
    save_sub_bots(bots)

def launch_sub_bot(token: str, owner_id: int) -> bool:
    """تشغيل بوت فرعي في thread منفصل مع كامل الميزات"""
    if token in _running_sub_bots:
        return True
    if not TELEGRAM_AVAILABLE:
        return False
    try:
        sub = telebot.TeleBot(token, threaded=True, parse_mode=None)
        # جيب اسم البوت الفرعي مرة واحدة
        try:
            _sub_me = sub.get_me()
            _sub_username = _sub_me.username or f"bot_{owner_id}"
        except:
            _sub_username = f"bot_{owner_id}"
        sub_user_state: dict = {}
        sub_voice_store: dict = {}

        def _sub_main_kb(cid):
            kb = InlineKeyboardMarkup()
            kb.row(InlineKeyboardButton("📞 اتصال واحد", callback_data="sub_call"),
                   InlineKeyboardButton("🔄 اتصال متعدد", callback_data="sub_multi"))
            kb.row(InlineKeyboardButton("🎤 تحميل صوت", callback_data="sub_voice_upload"),
                   InlineKeyboardButton("📅 اشتراك شهري", callback_data="sub_monthly"))
            kb.row(InlineKeyboardButton("💰 رصيدي", callback_data="sub_balance"),
                   InlineKeyboardButton("🏅 رتبتي", callback_data="sub_rank"))
            kb.row(InlineKeyboardButton("💱 تحويل رصيد لكود", callback_data="sub_bal2code"))
            kb.row(InlineKeyboardButton("🤖 أنشئ بوتاً خاصاً", callback_data="sub_create_bot"))
            kb.row(InlineKeyboardButton("🏆 لوحة المتصدرين", callback_data="sub_leaderboard"))
            kb.row(InlineKeyboardButton("💬 الدعم", url=f"https://t.me/{SUPPORT_USER.replace('@','')}"))
            return kb

        def _sub_dtmf_digit_kb(cid, digit):
            settings = load_user_dtmf(cid)
            cfg = settings.get(digit, {"action": "notify", "enabled": False, "label": digit})
            enabled = cfg.get("enabled", False)
            action_now = cfg.get("action", "notify")
            label_now = cfg.get("label", digit)
            kb = InlineKeyboardMarkup()
            kb.row(InlineKeyboardButton(
                f"{'✅ مفعّل' if enabled else '❌ معطّل'} — اضغط للتبديل",
                callback_data=f"dtmf_tog_{digit}"))
            actions = [("notify","📳 إشعار"),("confirm","✅ موافق"),
                       ("reject","❌ رافض"),("hangup","📴 قطع"),("replay","🔁 إعادة")]
            for a_name, a_ar in actions:
                mark = "◉" if action_now == a_name else "○"
                kb.row(InlineKeyboardButton(f"{mark} {a_ar}", callback_data=f"dtmf_act_{digit}_{a_name}"))
            kb.row(InlineKeyboardButton("✏️ تغيير الاسم", callback_data=f"dtmf_ren_{digit}"))
            kb.row(InlineKeyboardButton("🔙 رجوع", callback_data="sub_dtmf"))
            return kb, label_now, enabled

        def _sub_do_welcome(bot_obj, cid):
            """يرسل رسالة الترحيب بعد التحقق"""
            bonus = try_give_daily_bonus(cid)
            balance = get_user_balance(cid)
            cost = get_call_cost()
            refs = get_referral_count(cid)
            streak = get_user_streak(cid)
            wb = get_welcome_bonus()
            bonus_note = f"\n🎁 مكافأة يومية {bonus:.2f}$ أضيفت!" if bonus else ""
            welcome_note = f"\n🎁 رصيد ترحيبي {wb:.2f}$ — جرب المكالمات مجاناً!" if balance > 0 and balance <= wb else ""
            streak_emoji = "🔥" * min(streak, 5)
            if streak < 3:
                streak_info = f"\n{streak_emoji}🔥 حلقاتك: {streak}/3 (تحتاج {3-streak} يوم للمكافأة اليومية)"
            else:
                daily_b = get_daily_bonus_by_refs(refs)
                streak_info = f"\n{streak_emoji} حلقاتك: {streak} يوم ✅ (مكافأة يومية {daily_b:.2f}$)"
            welcome = (
                f"🌟 مرحباً في البوت!\n\n"
                f"💰 رصيدك: {balance:.2f}$\n"
                f"👥 إحالاتك: {refs}"
                f"{streak_info}"
                f"{welcome_note}"
                f"{bonus_note}\n\n"
                f"📞 سعر المكالمة: {cost:.2f}$\n\n"
                f"اختر من القائمة:"
            )
            bot_obj.send_message(cid, welcome, reply_markup=_sub_main_kb(cid))

        @sub.message_handler(commands=['start'])
        def _sub_start(msg):
            cid = msg.chat.id
            username = msg.from_user.username or ""
            first_name = msg.from_user.first_name or ""
            last_name = msg.from_user.last_name or ""
            full_name = (first_name + " " + last_name).strip() or str(cid)
            referred_by = None
            parts = msg.text.strip().split()
            if len(parts) > 1 and parts[1].startswith("ref_"):
                referred_by = decode_ref_id(parts[1][4:])

            if is_banned(cid):
                sub.send_message(cid, f"🚫 تم حظرك\nللدعم: {_md(SUPPORT_USER)}", parse_mode='Markdown')
                return

            # ── كابتشا للمستخدمين الجدد ──
            if not is_user_registered(cid):
                q, ans = generate_captcha()
                _captcha_pending[cid] = {
                    "answer": ans,
                    "tries": 0,
                    "referred_by": referred_by,
                    "username": username,
                    "first_name": full_name,
                    "bot_source": f"sub_@{_sub_username}"
                }
                sub_user_state[cid] = {"action": "captcha"}
                sub.send_message(
                    cid,
                    f"👋 مرحباً! قبل أن تبدأ، حل هذا السؤال للتحقق:\n\n"
                    f"🔢 *كم يساوي:* `{q} = ?`\n\n"
                    f"أرسل الإجابة كرقم فقط",
                    parse_mode='Markdown'
                )
                return

            # مستخدم موجود → تابع
            log_user_entry(cid, username, full_name, referred_by=referred_by)
            _checker = _main_bot_instance or sub
            if not check_force_sub(_checker, cid):
                send_force_sub_msg(sub, cid)
                return
            _sub_do_welcome(sub, cid)

        @sub.message_handler(commands=['PMC', 'pmc'])
        def _sub_pmc(msg):
            cid = msg.chat.id
            if is_banned(cid): return
            parts = msg.text.strip().split()
            if len(parts) < 2:
                sub.reply_to(msg, "❌ استخدم: /PMC كودك")
                return
            result = redeem_promo_code(cid, parts[1])
            sub.reply_to(msg, result["message"], parse_mode='Markdown')

        @sub.message_handler(commands=['refer'])
        def _sub_refer(msg):
            cid = msg.chat.id
            if is_banned(cid): return
            try:
                bot_info = sub.get_me()
                link = f"https://t.me/{bot_info.username}?start=ref_{encode_ref_id(cid)}"
            except:
                link = "⚠️ تعذّر إنشاء الرابط"
            refs = get_referral_count(cid)
            ref_bonus = get_referral_bonus()
            req = get_required_referrals()
            balance = get_user_balance(cid)
            sub.send_message(
                cid,
                f"👥 رابط الإحالة الخاص بك:\n\n`{link}`\n\n"
                f"📊 إحالاتك: {refs}/{req}\n"
                f"💰 رصيدك: {balance:.2f}$\n"
                f"🎁 مكافأة كل إحالة: {ref_bonus:.2f}$",
                parse_mode='Markdown'
            )

        @sub.callback_query_handler(func=lambda c: True)
        def _sub_on_cb(call):
            cid = call.message.chat.id
            data = call.data
            if is_banned(cid):
                sub.answer_callback_query(call.id, "🚫 محظور")
                return

            _checker = _main_bot_instance or sub

            # check_sub زرار مخصوص — يتحقق من الاشتراك ثم يفتح القائمة
            if data == "check_sub":
                if check_force_sub(_checker, cid):
                    sub.answer_callback_query(call.id, "✅ تم التحقق! يمكنك الاستخدام الآن")
                    balance = get_user_balance(cid)
                    cost    = get_call_cost()
                    refs    = get_referral_count(cid)
                    req     = get_required_referrals()
                    sub.send_message(
                        cid,
                        f"🌟 مرحباً في البوت!\n\n"
                        f"💰 رصيدك: {balance:.2f}$\n"
                        f"👥 إحالاتك: {refs}/{req}\n\n"
                        f"📞 سعر المكالمة: {cost:.2f}$\n\n"
                        f"اختر من القائمة:",
                        reply_markup=_sub_main_kb(cid)
                    )
                else:
                    sub.answer_callback_query(call.id, "❌ لم تشترك بعد!")
                    send_force_sub_msg(sub, cid)
                return

            # تحقق الاشتراك الإجباري عبر البوت الرئيسي (الأدمن في القنوات)
            if not check_force_sub(_checker, cid):
                sub.answer_callback_query(call.id, "📢 يجب الاشتراك في القنوات أولاً")
                send_force_sub_msg(sub, cid)
                return
            sub.answer_callback_query(call.id)

            if data == "go_start" or data == "sub_go_start":
                balance = get_user_balance(cid)
                try:
                    sub.edit_message_text(
                        f"🌟 القائمة الرئيسية\n💰 رصيدك: {balance:.2f}$",
                        cid, call.message.message_id, reply_markup=_sub_main_kb(cid))
                except:
                    sub.send_message(cid, f"🌟 القائمة الرئيسية\n💰 رصيدك: {balance:.2f}$",
                                     reply_markup=_sub_main_kb(cid))

            elif data == "sub_call":
                sub_user_state[cid] = {"action": "call", "dur": 60}
                sub.send_message(cid, "📞 أرسل رقم الهاتف مع كود الدولة\nمثال: +966512345678")

            elif data == "sub_multi":
                sub_user_state[cid] = {"action": "multi", "attempts": 5, "dur": 60}
                sub.send_message(cid, "🔄 أرسل رقم الهاتف (5 محاولات)\nمثال: +966512345678")

            elif data == "sub_voice_upload":
                sub_user_state[cid] = {"action": "voice_upload"}
                sub.send_message(cid, "🎤 أرسل رسالة صوتية لاستخدامها في المكالمات")

            elif data == "sub_balance":
                balance = get_user_balance(cid)
                refs = get_referral_count(cid)
                req = get_required_referrals()
                cost = get_call_cost()
                lvl = get_user_level(cid)
                try:
                    bot_info = sub.get_me()
                    ref_link = f"https://t.me/{bot_info.username}?start=ref_{encode_ref_id(cid)}"
                except:
                    ref_link = "—"
                next_info = f"أحل {lvl['needed']} صديق للترقية ⬆️" if lvl['needed'] > 0 else "أعلى مستوى! 🏆"
                sub.send_message(
                    cid,
                    f"{lvl['emoji']} *مستواك: {lvl['name']}*\n"
                    f"┗ {next_info}\n\n"
                    f"💰 رصيدك: {balance:.2f}$\n"
                    f"👥 إحالاتك: {refs}\n"
                    f"📞 سعر المكالمة: {cost:.2f}$\n\n"
                    f"🔗 رابط الإحالة:\n`{ref_link}`",
                    parse_mode='Markdown'
                )

            elif data == "sub_bal2code":
                balance = get_user_balance(cid)
                if balance <= 0:
                    sub.send_message(cid, "❌ رصيدك صفر، لا يمكن التحويل")
                    return
                sub_user_state[cid] = {"action": "sub_balance_to_code_count"}
                sub.send_message(
                    cid,
                    f"💱 تحويل الرصيد لكود\n\n"
                    f"💰 رصيدك الحالي: {balance:.2f}$\n\n"
                    f"كم شخص تريد أن يستخدم الكود؟\nمثال: 5\n\n"
                    f"سيُنشأ كود واحد قيمته {balance:.2f}$ مقسمة على العدد"
                )

            elif data == "sub_dtmf":
                kb = _dtmf_panel_kb(cid, False)
                try:
                    sub.edit_message_text("⚙️ إعدادات DTMF — اختر زراراً:", cid,
                                          call.message.message_id, reply_markup=kb)
                except:
                    sub.send_message(cid, "⚙️ إعدادات DTMF:", reply_markup=kb)

            elif data == "sub_leaderboard":
                text = build_leaderboard_text()
                streak = get_user_streak(cid)
                refs = get_referral_count(cid)
                bonus = get_daily_bonus_by_refs(refs)
                streak_bar = "🔥" * min(streak, 7) + f" ({streak} يوم متتالي)"
                text += f"\n\n─────────────────\n"
                text += f"📊 *حالتك:*\n"
                text += f"🔥 حلقاتك: {streak_bar}\n"
                text += f"👥 إحالاتك: {refs}\n"
                if streak >= 3:
                    text += f"✅ مؤهل للمكافأة اليومية: `{bonus:.2f}$`"
                else:
                    text += f"⏳ تحتاج {3 - streak} يوم إضافي للمكافأة اليومية"
                kb_back = InlineKeyboardMarkup()
                kb_back.row(InlineKeyboardButton("🔙 رجوع", callback_data="sub_go_start"))
                sub.send_message(cid, text, parse_mode='Markdown', reply_markup=kb_back)

            # ==================== رتبتي VIP (فرعي) ====================
            elif data == "sub_rank":
                lvl   = get_user_level(cid)
                refs  = lvl["refs"]
                badge = lvl["badge"] or lvl["emoji"]
                monthly = get_monthly_sub(cid)
                monthly_line = ""
                if monthly:
                    plan_info2 = MONTHLY_PLANS.get(monthly["plan"], {})
                    left_m2 = get_monthly_calls_left(cid)
                    left_s2 = "∞" if plan_info2.get("calls",0) == 999999 else str(left_m2)
                    monthly_line = f"\n📅 *اشتراك:* {plan_info2.get('emoji','')} {plan_info2.get('name','')} ({left_s2} متبقية) — ينتهي {monthly.get('expires','')}"
                next_line2 = f"\n📈 أحل *{lvl['needed']}* صديق للترقية!" if lvl["needed"] > 0 else "\n🏆 أعلى مستوى!"
                rank_t = (
                    f"🏅 *رتبتك*\n\n{badge}\n*{lvl['name']}*\n"
                    f"إحالات: {refs} | مكالمات/يوم: {lvl['daily_calls']}"
                    f"{next_line2}{monthly_line}\n\n*الرتب:*\n"
                )
                for t in VIP_TIERS:
                    mark = "◉" if t["min"] == [tt["min"] for tt in VIP_TIERS if refs >= tt["min"]][-1] else "○"
                    rank_t += f"{mark} {t['emoji']} {t['name']} — {t['min']}+ إحالة\n"
                kb_sr = InlineKeyboardMarkup()
                kb_sr.row(InlineKeyboardButton("📅 اشتراك شهري", callback_data="sub_monthly"))
                kb_sr.row(InlineKeyboardButton("🔙 رجوع", callback_data="sub_go_start"))
                sub.send_message(cid, rank_t, parse_mode='Markdown', reply_markup=kb_sr)

            # ==================== اشتراك شهري (فرعي) ====================
            elif data == "sub_monthly":
                monthly = get_monthly_sub(cid)
                balance = get_user_balance(cid)
                plans_text2 = "\n".join([
                    f"  {pv['emoji']} {pv['name']} — {'∞' if pv['calls'] == 999999 else pv['calls']} مكالمة — {pv['price']:.2f}$"
                    for pk, pv in MONTHLY_PLANS.items()
                ])
                sellers_lines2 = "\n".join([f"👤 {_md(s['username'])} — {_md(s['name'])}" for s in SUBSCRIPTION_SELLERS])
                if monthly:
                    plan_info2 = MONTHLY_PLANS.get(monthly["plan"], {})
                    left_m2 = get_monthly_calls_left(cid)
                    left_s2 = "∞" if plan_info2.get("calls",0) == 999999 else str(left_m2)
                    st_txt = (
                        f"📅 *اشتراكك الحالي*\n\n"
                        f"{plan_info2.get('emoji','')} {plan_info2.get('name','')}\n"
                        f"📞 متبقي: *{left_s2}*\n📆 ينتهي: {monthly.get('expires','')}\n\n"
                        f"💰 رصيدك: `{balance:.2f}$`\n\n"
                        f"─────────────────\n"
                        f"🔄 *لترقية خطتك أو تجديدها تواصل مع:*\n\n"
                        f"{sellers_lines2}\n\n"
                        f"📋 *الخطط المتاحة:*\n{plans_text2}"
                    )
                else:
                    st_txt = (
                        f"📅 *الاشتراك الشهري*\n\nمكالمات أكثر بسعر أقل!\n\n"
                        f"📋 *الخطط المتاحة:*\n{plans_text2}\n\n"
                        f"💰 رصيدك: `{balance:.2f}$`\n\n"
                        f"─────────────────\n"
                        f"📥 *للاشتراك تواصل مع:*\n\n"
                        f"{sellers_lines2}"
                    )
                kb_sm = InlineKeyboardMarkup()
                for s in SUBSCRIPTION_SELLERS:
                    kb_sm.row(InlineKeyboardButton(
                        f"💬 تواصل مع {s['name']}",
                        url=f"https://t.me/{s['username'].replace('@', '')}"
                    ))
                kb_sm.row(InlineKeyboardButton("🔙 رجوع", callback_data="sub_go_start"))
                sub.send_message(cid, st_txt, parse_mode='Markdown', reply_markup=kb_sm)

            elif data.startswith("sub_buy_monthly_"):
                # تم إلغاء الشراء المباشر — توجيه للأدمن
                plan_key2 = data.replace("sub_buy_monthly_", "")
                plan2 = MONTHLY_PLANS.get(plan_key2)
                if plan2:
                    sellers_lines2 = "\n".join([f"👤 {_md(s['username'])}" for s in SUBSCRIPTION_SELLERS])
                    sub.answer_callback_query(call.id,
                        f"📥 للاشتراك في خطة {plan2['emoji']} {plan2['name']} ({plan2['price']:.2f}$)\nتواصل مع:\n{sellers_lines2}",
                        show_alert=True)
                else:
                    sub.answer_callback_query(call.id, "❌ خطة غير موجودة", show_alert=True)

            # ==================== إنشاء بوت من البوت الفرعي ====================
            elif data == "sub_create_bot":
                my_bots_c = len(get_user_sub_bots(cid))
                if user_reached_sub_bot_limit(cid):
                    kb_sl = InlineKeyboardMarkup()
                    kb_sl.row(InlineKeyboardButton("🔙 رجوع", callback_data="sub_go_start"))
                    sub.answer_callback_query(call.id,
                        f"❌ وصلت للحد الأقصى ({MAX_SUB_BOTS_PER_USER} بوتات)", show_alert=True)
                    sub.send_message(
                        cid,
                        f"❌ *وصلت للحد الأقصى!*\n\n"
                        f"لديك *{my_bots_c}/{MAX_SUB_BOTS_PER_USER}* بوتات فرعية.\n\n"
                        f"يجب حذف بوت موجود قبل إنشاء بوت جديد.",
                        parse_mode='Markdown',
                        reply_markup=kb_sl
                    )
                    return
                sub_user_state[cid] = {"action": "sub_register_bot"}
                sub.send_message(
                    cid,
                    f"🤖 *أنشئ بوتك الخاص!* ({my_bots_c}/{MAX_SUB_BOTS_PER_USER})\n\n"
                    "الخطوات:\n"
                    "1️⃣ افتح @BotFather في تيليجرام\n"
                    "2️⃣ أرسل له /newbot\n"
                    "3️⃣ اختر اسماً للبوت\n"
                    "4️⃣ احصل على التوكن\n\n"
                    "📩 أرسل لي التوكن الآن:",
                    parse_mode='Markdown'
                )

            # ── DTMF callbacks (نفس الـ data من الرئيسي) ─────────────────
            elif data.startswith("dtmf_edit_"):
                digit = data.split("_")[2]
                kb2, lbl, enabled = _sub_dtmf_digit_kb(cid, digit)
                try:
                    sub.edit_message_text(
                        f"⚙️ الزرار [{digit}]\nالاسم: {lbl}\n"
                        f"الحالة: {'مفعّل ✅' if enabled else 'معطّل ❌'}",
                        cid, call.message.message_id, reply_markup=kb2)
                except:
                    sub.send_message(cid, f"⚙️ الزرار [{digit}]", reply_markup=kb2)

            elif data.startswith("dtmf_act_"):
                parts2 = data.split("_")
                digit, act_name = parts2[2], parts2[3]
                settings = load_user_dtmf(cid)
                if digit not in settings:
                    settings[digit] = {"enabled": True, "label": digit}
                settings[digit]["action"] = act_name
                save_user_dtmf(cid, settings)
                kb2, lbl, enabled = _sub_dtmf_digit_kb(cid, digit)
                try:
                    sub.edit_message_reply_markup(cid, call.message.message_id, reply_markup=kb2)
                except: pass

            elif data.startswith("dtmf_tog_"):
                digit = data.split("_")[2]
                settings = load_user_dtmf(cid)
                if digit not in settings:
                    settings[digit] = {"action": "notify", "enabled": False, "label": digit}
                settings[digit]["enabled"] = not settings[digit].get("enabled", False)
                save_user_dtmf(cid, settings)
                kb2, lbl, enabled = _sub_dtmf_digit_kb(cid, digit)
                try:
                    sub.edit_message_reply_markup(cid, call.message.message_id, reply_markup=kb2)
                except: pass

            elif data.startswith("dtmf_ren_"):
                digit = data.split("_")[2]
                sub_user_state[cid] = {"action": "dtmf_rename", "digit": digit}
                sub.send_message(cid, f"✏️ أرسل الاسم الجديد للزرار [{digit}]:")

            elif data == "dtmf_reset":
                save_user_dtmf(cid, {})
                kb = _dtmf_panel_kb(cid, False)
                try:
                    sub.edit_message_text("✅ تم إعادة تعيين DTMF للافتراضي",
                                          cid, call.message.message_id, reply_markup=kb)
                except:
                    sub.send_message(cid, "✅ تم إعادة التعيين", reply_markup=kb)

        @sub.message_handler(content_types=['voice', 'audio'])
        def _sub_on_voice(msg):
            cid = msg.chat.id
            if is_banned(cid): return
            st = sub_user_state.get(cid, {})
            if st.get("action") != "voice_upload":
                sub.reply_to(msg, "ℹ️ اضغط '🎤 تحميل صوت' أولاً")
                return
            sub_user_state.pop(cid, None)
            try:
                if msg.voice:
                    file_id = msg.voice.file_id
                    fname   = "voice.ogg"
                    dur_s   = msg.voice.duration or 0
                else:
                    file_id = msg.audio.file_id
                    fname   = "audio.mp3"
                    dur_s   = msg.audio.duration or 0
                MAX_VOICE_SEC = 60
                if dur_s > MAX_VOICE_SEC:
                    sub.reply_to(msg, f"⚠️ الصوت طويل جداً ({dur_s}s)\nالحد الأقصى {MAX_VOICE_SEC} ثانية")
                    return
                file_info  = sub.get_file(file_id)
                file_bytes = sub.download_file(file_info.file_path)
                pcm_bytes  = convert_voice_to_pcm(file_bytes, fname)
                sub_voice_store[cid] = pcm_bytes
                dur_actual = len(pcm_bytes) // (8000 * 2)
                sub.reply_to(msg,
                    f"✅ تم تحميل الصوت!\n⏱️ المدة: {dur_actual} ثانية\n\n📞 أرسل رقم الهاتف:")
                sub_user_state[cid] = {"action": "call", "dur": 60}
            except Exception as e:
                sub.reply_to(msg, f"❌ فشل تحميل الصوت: {e}")

        @sub.message_handler(func=lambda m: True)
        def _sub_on_text(msg):
            cid = msg.chat.id
            if is_banned(cid): return
            text = (msg.text or "").strip()
            st = sub_user_state.get(cid, {})
            action = st.get("action", "")

            # ── معالجة الكابتشا ──
            if action == "captcha":
                pending = _captcha_pending.get(cid)
                if not pending:
                    sub_user_state.pop(cid, None)
                    sub.send_message(cid, "⚠️ حدث خطأ، أرسل /start مرة أخرى")
                    return
                try:
                    user_ans = int(text)
                except (ValueError, TypeError):
                    sub.reply_to(msg, "❌ أرسل رقماً صحيحاً فقط\nمثال: 8")
                    return
                if user_ans == pending["answer"]:
                    # ✅ إجابة صحيحة
                    sub_user_state.pop(cid, None)
                    _captcha_pending.pop(cid, None)
                    log_user_entry(cid, pending["username"], pending["first_name"],
                                   referred_by=pending.get("referred_by"))
                    # سجّل مصدر الانضمام
                    _udb2 = load_users_db()
                    if str(cid) in _udb2 and not _udb2[str(cid)].get("bot_source"):
                        _udb2[str(cid)]["bot_source"] = pending.get("bot_source", "")
                        save_users_db(_udb2)
                    # تحقق من أرباح صاحب البوت الفرعي
                    _bsrc = pending.get("bot_source", "")
                    if _bsrc.startswith("sub_@"):
                        _sub_uname = _bsrc.replace("sub_@", "")
                        _all_u = load_users_db()
                        _member_count = sum(1 for u in _all_u.values() if u.get("bot_source") == _bsrc)
                        check_and_add_sub_bot_earnings(_sub_uname, _member_count)
                    sub.send_message(cid, "✅ تم التحقق بنجاح! مرحباً 🎉")
                    _checker = _main_bot_instance or sub
                    if not check_force_sub(_checker, cid):
                        send_force_sub_msg(sub, cid)
                        return
                    _sub_do_welcome(sub, cid)
                else:
                    # ❌ إجابة خاطئة
                    pending["tries"] = pending.get("tries", 0) + 1
                    if pending["tries"] >= 3:
                        sub_user_state.pop(cid, None)
                        _captcha_pending.pop(cid, None)
                        sub.send_message(cid, "❌ إجابات خاطئة متكررة. أرسل /start للمحاولة مجدداً")
                    else:
                        q, ans = generate_captcha()
                        pending["answer"] = ans
                        remaining = 3 - pending["tries"]
                        sub.reply_to(
                            msg,
                            f"❌ إجابة خاطئة! تبقى لك {remaining} محاولة\n\n"
                            f"🔢 *سؤال جديد:* `{q} = ?`\n\n"
                            f"أرسل الإجابة كرقم فقط",
                            parse_mode='Markdown'
                        )
                return

            if action == "sub_balance_to_code_count":
                sub_user_state.pop(cid)
                try:
                    n = int(text)
                    if n <= 0: raise ValueError
                except:
                    sub.reply_to(msg, "❌ أرسل رقم صحيح أكبر من صفر")
                    return
                res = convert_balance_to_code(cid, n)
                sub.reply_to(msg, res["message"], parse_mode='Markdown')
                return

            if action == "dtmf_rename":
                sub_user_state.pop(cid)
                digit = st.get("digit", "")
                settings = load_user_dtmf(cid)
                if digit not in settings:
                    settings[digit] = {"action": "notify", "enabled": True}
                settings[digit]["label"] = text
                save_user_dtmf(cid, settings)
                sub.reply_to(msg, f"✅ تم تغيير اسم [{digit}] إلى: {text}")
                return

            if action == "sub_register_bot":
                sub_user_state.pop(cid, None)
                if user_reached_sub_bot_limit(cid):
                    sub.reply_to(
                        msg,
                        f"❌ *وصلت للحد الأقصى!*\n\n"
                        f"كل مستخدم يمكنه إنشاء *{MAX_SUB_BOTS_PER_USER}* بوتات فقط.\n\n"
                        f"احذف بوتاً موجوداً أولاً.",
                        parse_mode='Markdown'
                    )
                    return
                new_tok = text.strip()
                if not re.match(r'^\d+:[A-Za-z0-9_-]{30,}$', new_tok):
                    sub.reply_to(msg, "❌ التوكن غير صحيح\nمثال: `123456789:ABC-DEF...`", parse_mode='Markdown')
                    return
                ok = launch_sub_bot(new_tok, cid)
                if ok:
                    sub.reply_to(msg, "✅ *تم إطلاق بوتك الخاص بنجاح!* 🎉\nأرسل /start لبوتك الجديد.", parse_mode='Markdown')
                else:
                    sub.reply_to(msg, "❌ فشل تشغيل البوت — تأكد من أن التوكن صحيح وغير مستخدم في مكان آخر")
                return

            if action in ("call", "multi"):
                sub_user_state.pop(cid)
                dur = st.get("dur", 60)
                attempts = st.get("attempts", 5)
                call_action = action
                phone = re.sub(r'[^\d+]', '', text)
                if not re.match(r'^\+?\d{7,15}$', phone):
                    sub.send_message(cid, "❌ رقم غير صحيح\nمثال: +966512345678")
                    return
                if not phone.startswith('+'): phone = '+' + phone
                access, access_msg = check_user_access(cid)
                if not access:
                    sub.send_message(cid, f"❌ {access_msg}\n{t('contact_premium', user_id=cid)}{_md(SUPPORT_USER)}", parse_mode='Markdown')
                    return
                if cid not in ADMIN_IDS and not is_premium(cid):
                    use_daily_call(cid)
                # 🔀 تحقق من الاتصال المزدوج
                sub_display_phone = phone
                sub_actual_phone = phone
                sub_dc = get_double_call_target(phone)
                if sub_dc:
                    sub_actual_phone = sub_dc
                    print(f"[sub-bot] 🔀 تحويل: {phone} → {sub_dc}")
                label = f"🔄 {attempts} محاولة" if call_action == "multi" else "📞 مكالمة واحدة"
                sub.send_message(cid, f"📱 {sub_display_phone}\n{label}\n⏳ جاري الاتصال...")

                def _sub_status(smsg):
                    try: sub.send_message(cid, smsg)
                    except: pass

                def _sub_run():
                    voice_pcm = sub_voice_store.get(cid)

                    def _dtmf_cb(digit):
                        try:
                            sett = load_user_dtmf(cid)
                            cfg = sett.get(digit, {})
                            if not cfg.get("enabled", False): return
                            act = cfg.get("action", "notify")
                            lbl = cfg.get("label", digit)
                            sip = _current_sip[0]
                            if act == "notify": _sub_status(f"📳 ضغط [{digit}] — {lbl}")
                            elif act == "confirm": _sub_status(f"✅ وافق [{digit}]")
                            elif act == "reject": _sub_status(f"❌ رفض [{digit}]")
                            elif act == "hangup":
                                _sub_status(f"📴 قطع [{digit}]")
                                if sip: sip._force_hangup = True
                            elif act == "replay":
                                _sub_status(f"🔁 إعادة [{digit}]")
                                if sip: sip._replay_requested = True
                        except: pass

                    if call_action == "call":
                        result, sub_from_num, sub_rec_data = make_call(
                            sub_actual_phone, dur=dur, auto_create=True,
                            voice_pcm=voice_pcm, status_cb=_sub_status,
                            dtmf_cb=_dtmf_cb, user_id=cid,
                            display_phone=sub_display_phone)
                    else:
                        _sub_multi_res = multi_call(
                            sub_actual_phone, attempts=attempts, dur=dur,
                            voice_pcm=voice_pcm, status_cb=_sub_status,
                            dtmf_cb=_dtmf_cb, user_id=cid,
                            display_phone=sub_display_phone)
                        if isinstance(_sub_multi_res, tuple):
                            result, sub_rec_data, sub_from_num = _sub_multi_res
                        else:
                            result, sub_rec_data, sub_from_num = _sub_multi_res, b'', ''

                    bd = load_bot_data()
                    bd["stats"]["total_calls"] = bd["stats"].get("total_calls", 0) + 1
                    if result:
                        bd["stats"]["success_calls"] = bd["stats"].get("success_calls", 0) + 1
                    save_bot_data(bd)

                    balance = get_user_balance(cid)
                    if result:
                        lvl = get_user_level(cid)
                        sub.send_message(cid,
                            f"✅ انتهت المكالمة بنجاح!\n"
                            f"💰 رصيدك: {balance:.2f}$\n"
                            f"{lvl['emoji']} مستواك: {lvl['name']}",
                            reply_markup=_sub_main_kb(cid))
                    else:
                        sub.send_message(cid, "❌ فشلت المكالمة — حاول مرة أخرى",
                                         reply_markup=_sub_main_kb(cid))

                    # إرسال التسجيل
                    if result and sub_rec_data and len(sub_rec_data) > 200:
                        try:
                            import io as _sio
                            clean_ph = phone.replace('+','')
                            ts2 = datetime.now().strftime("%Y%m%d_%H%M%S")
                            fn2 = f"Call_{clean_ph}_{ts2}.wav"
                            buf2 = _sio.BytesIO(sub_rec_data)
                            buf2.name = fn2
                            sub.send_audio(cid, buf2, caption="🎧 تسجيل المكالمة")
                        except Exception as _e2:
                            sub.send_message(cid, f"⚠️ فشل إرسال التسجيل: {_e2}")

                    # رسالة تشجيع بعد أول مكالمة ناجحة
                    if result:
                        total_calls = increment_user_calls(cid)
                        if total_calls == 1:
                            try:
                                sub_info = sub.get_me()
                                ref_link = f"https://t.me/{sub_info.username}?start=ref_{encode_ref_id(cid)}"
                            except:
                                ref_link = "—"
                            lvl = get_user_level(cid)
                            next_note = f"\n📈 أحل *{lvl['needed']}* صديق للوصول لمستوى أعلى!" if lvl['needed'] > 0 else ""
                            sub.send_message(
                                cid,
                                f"🎉 *أول مكالمة ناجحة! مبروك!*\n\n"
                                f"شارك رابط الإحالة مع أصدقائك واكسب رصيداً مجانياً:\n"
                                f"`{ref_link}`\n\n"
                                f"👥 كل صديق = رصيد إضافي لك{next_note}",
                                parse_mode='Markdown'
                            )

                threading.Thread(target=_sub_run, daemon=True).start()
                return

            sub.send_message(cid, "اختر من القائمة:", reply_markup=_sub_main_kb(cid))

        def _poll():
            try:
                sub.infinity_polling(timeout=30, long_polling_timeout=30)
            except Exception as e:
                print(f"[SubBot:{owner_id}] polling error: {e}")

        t = threading.Thread(target=_poll, daemon=True)
        t.start()
        _running_sub_bots[token] = t
        return True
    except Exception as e:
        print(f"[SubBot] Failed to launch token for owner {owner_id}: {e}")
        return False

def start_all_sub_bots():
    """تشغيل كل البوتات الفرعية المحفوظة عند بدء التشغيل"""
    bots = load_sub_bots()
    if not bots:
        return
    print(f"[SubBot] Starting {len(bots)} saved sub-bot(s)...")
    failed_bots = []
    for b in bots:
        try:
            # تحقق من التوكن أولاً
            token_valid = _verify_sub_bot_token(b["token"])
            if not token_valid:
                print(f"[SubBot] ⚠️ Token invalid for @{b.get('username','?')} — will notify owner")
                failed_bots.append(b)
                continue
            ok = launch_sub_bot(b["token"], b["owner_id"])
            status = "✅" if ok else "❌"
            print(f"[SubBot] {status} @{b.get('username','?')} (owner:{b['owner_id']})")
            if not ok:
                failed_bots.append(b)
        except Exception as e:
            print(f"[SubBot] ❌ Error: {e}")
            failed_bots.append(b)
    
    # إبلاغ أصحاب البوتات الفاشلة
    if failed_bots:
        threading.Thread(target=_notify_failed_bot_owners, args=(failed_bots,), daemon=True).start()


def _verify_sub_bot_token(token: str) -> bool:
    """يتحقق من صلاحية توكن البوت الفرعي"""
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        if r.status_code == 200 and r.json().get("ok"):
            return True
        return False
    except:
        return False


def _notify_failed_bot_owners(failed_bots: list):
    """يبلغ أصحاب البوتات الفاشلة"""
    for b in failed_bots:
        try:
            owner_id = b.get("owner_id")
            uname = b.get("username", "؟")
            if owner_id:
                bot_tmp = telebot.TeleBot(BOT_TOKEN)
                bot_tmp.send_message(
                    owner_id,
                    f"⚠️ *البوت الفرعي الخاص بك متوقف!*\n\n"
                    f"🤖 البوت: @{uname}\n"
                    f"🔴 الحالة: التوكن غير صالح أو منتهي\n\n"
                    f"لإصلاح البوت:\n"
                    f"1️⃣ افتح @BotFather\n"
                    f"2️⃣ أعد إنشاء التوكن `/token`\n"
                    f"3️⃣ أرسل التوكن الجديد من ➕ في *بوتي الخاص*",
                    parse_mode='Markdown'
                )
        except Exception as e:
            print(f"[SubBot] Failed to notify owner {b.get('owner_id')}: {e}")


def _verify_all_sub_bots(admin_id: int):
    """فحص كل البوتات الفرعية وإبلاغ الأدمن بالنتائج"""
    bots = load_sub_bots()
    results = []
    failed = []
    for b in bots:
        uname = b.get("username", "؟")
        token_valid = _verify_sub_bot_token(b["token"])
        running = b["token"] in _running_sub_bots
        if token_valid:
            status = "🟢"
            if not running:
                # التوكن صالح لكن البوت مش شغال — أعد تشغيله
                try:
                    ok = launch_sub_bot(b["token"], b["owner_id"])
                    if ok:
                        status = "🟢 (تم إعادة التشغيل)"
                    else:
                        status = "🟡 (توكن صالح لكن فشل التشغيل)"
                except:
                    status = "🟡 (توكن صالح لكن فشل التشغيل)"
        else:
            status = "🔴 (توكن غير صالح)"
            failed.append(b)
        results.append(f"{status} @{uname} — مالك: `{b.get('owner_id','?')}`")
    
    # إبلاغ الأدمن
    msg = "🤖 *نتائج فحص البوتات الفرعية:*\n\n"
    msg += "\n".join(results)
    msg += f"\n\n📊 الإجمالي: {len(bots)} | فاشل: {len(failed)}"
    try:
        bot_tmp = telebot.TeleBot(BOT_TOKEN)
        bot_tmp.send_message(admin_id, msg, parse_mode='Markdown')
    except: pass
    
    # إبلاغ أصحاب البوتات الفاشلة
    if failed:
        _notify_failed_bot_owners(failed)


# ─── نظام أرباح أصحاب البوتات الفرعية ─────────────────────────────────────
SUB_BOT_EARNINGS_PER_USERS = 10   # كل 10 أعضاء
SUB_BOT_EARNINGS_AMOUNT = 0.05    # يكسب 0.05$

def check_and_add_sub_bot_earnings(bot_username: str, current_members: int):
    """يتحقق ويضيف أرباح لصاحب البوت الفرعي بناءً على عدد الأعضاء"""
    bots = load_sub_bots()
    for b in bots:
        if b.get("username", "").lower() == bot_username.lower():
            prev_members = b.get("last_checked_members", 0)
            prev_earnings_level = prev_members // SUB_BOT_EARNINGS_PER_USERS
            current_earnings_level = current_members // SUB_BOT_EARNINGS_PER_USERS
            
            if current_earnings_level > prev_earnings_level:
                # وصل لمرحلة أرباح جديدة
                earned = (current_earnings_level - prev_earnings_level) * SUB_BOT_EARNINGS_AMOUNT
                b["earnings"] = round(b.get("earnings", 0.0) + earned, 2)
                b["last_checked_members"] = current_members
                save_sub_bots(bots)
                
                # أضف الرصيد لصاحب البوت
                owner_id = b.get("owner_id")
                if owner_id:
                    add_balance(owner_id, earned)
                    try:
                        bot_tmp = telebot.TeleBot(BOT_TOKEN)
                        bot_tmp.send_message(
                            owner_id,
                            f"💰 *أرباح بوتك الفرعي!*\n\n"
                            f"🤖 البوت: @{bot_username}\n"
                            f"👥 الأعضاء: {current_members}\n"
                            f"💵 المكسب: ${earned:.2f}\n"
                            f"💳 تم إضافته لرصيدك!",
                            parse_mode='Markdown'
                        )
                    except: pass
            else:
                b["last_checked_members"] = current_members
                save_sub_bots(bots)
            break


# ============================================================================
#                         TELEGRAM BOT
# ============================================================================

user_state: dict = {}
voice_store: dict = {}
_sip_registry: dict = {}
_current_sip = [None]
_error_store: dict = {}

def _main_kb(is_admin=False, user_id=None):
    """أزرار شفافة للبوت — تدعم اللغة"""
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton(t("btn_call", user_id=user_id), callback_data="menu_call"),
           InlineKeyboardButton(t("btn_multi", user_id=user_id), callback_data="menu_multi"))
    kb.row(InlineKeyboardButton(t("btn_voice", user_id=user_id), callback_data="menu_voice"),
           InlineKeyboardButton(t("btn_monthly", user_id=user_id), callback_data="monthly_sub"))
    kb.row(InlineKeyboardButton(t("btn_balance", user_id=user_id), callback_data="user_balance"),
           InlineKeyboardButton(t("btn_rank", user_id=user_id), callback_data="my_rank"))
    kb.row(InlineKeyboardButton(t("btn_convert", user_id=user_id), callback_data="balance_to_code"))
    kb.row(InlineKeyboardButton(t("btn_mybot", user_id=user_id), callback_data="my_bots"),
           InlineKeyboardButton(t("btn_create_bot", user_id=user_id), callback_data="create_sub_bot"))
    kb.row(InlineKeyboardButton(t("btn_leaderboard", user_id=user_id), callback_data="show_leaderboard"))
    kb.row(InlineKeyboardButton(t("btn_token", user_id=user_id), callback_data="create_token"))
    kb.row(InlineKeyboardButton(t("btn_support", user_id=user_id), url=f"https://t.me/{SUPPORT_USER.replace('@', '')}"))

    if is_admin:
        kb.row(InlineKeyboardButton(t("btn_admin", user_id=user_id), callback_data="admin_panel"))

    kb.row(InlineKeyboardButton(t("btn_dtmf", user_id=user_id), callback_data="dtmf_settings"))
    kb.row(InlineKeyboardButton(t("btn_lang", user_id=user_id), callback_data="change_lang"))

    return kb

def _dtmf_panel_kb(user_id=None, is_admin=False):
    settings = load_user_dtmf(user_id) if user_id else load_dtmf_settings()
    kb = InlineKeyboardMarkup()
    keys = ["0","1","2","3","4","5","6","7","8","9"]
    row1 = []
    row2 = []
    for i, k in enumerate(keys):
        cfg = settings.get(k, {"label": f"زرار {k}", "action": "notify", "enabled": False})
        status = "✅" if cfg.get("enabled") else "❌"
        btn = InlineKeyboardButton(f"{status}{k}", callback_data=f"dtmf_edit_{k}")
        if i < 5:
            row1.append(btn)
        else:
            row2.append(btn)
    kb.row(*row1)
    kb.row(*row2)
    kb.row(InlineKeyboardButton("🔄 إعادة تعيين الافتراضي", callback_data="dtmf_reset"))
    back_target = "admin_panel" if is_admin else "go_start"
    kb.row(InlineKeyboardButton("🔙 رجوع", callback_data=back_target))
    return kb

def _admin_panel():
    """لوحة الأدمن الفاخرة"""
    kb = InlineKeyboardMarkup(row_width=2)
    
    # إحصائيات
    users_db = load_users_db()
    premium_db = load_premium_db()
    banned_db = load_banned_db()
    
    # حساب المميزين المحدودين وغير المحدودين
    limited_count = sum(1 for u in premium_db.values() if u.get("type", "limited") == "limited")
    unlimited_count = sum(1 for u in premium_db.values() if u.get("type", "limited") == "unlimited")
    total_users = len(users_db)
    banned_count = len(banned_db)
    
    kb.add(
        InlineKeyboardButton(f"👥 المستخدمين: {total_users}", callback_data="admin_stats"),
        InlineKeyboardButton(f"⭐ المميزين: {limited_count + unlimited_count}", callback_data="admin_premium_list")
    )
    kb.add(
        InlineKeyboardButton(f"🔘 محدودين: {limited_count}", callback_data="admin_premium_limited"),
        InlineKeyboardButton(f"♾️ غير محدودين: {unlimited_count}", callback_data="admin_premium_unlimited_list")
    )
    kb.add(
        InlineKeyboardButton(f"🔨 المحظورين: {banned_count}", callback_data="admin_banned_list"),
        InlineKeyboardButton("📊 إحصائيات", callback_data="admin_stats")
    )
    kb.add(
        InlineKeyboardButton("⭐➕ إضافة مميز (10)", callback_data="admin_add_premium_limited"),
        InlineKeyboardButton("♾️➕ مميز غير محدود", callback_data="admin_add_premium_unlimited")
    )
    kb.add(
        InlineKeyboardButton("➖ إزالة مميز", callback_data="admin_remove_premium"),
        InlineKeyboardButton("🔄 تجديد مميز", callback_data="admin_renew_premium")
    )
    kb.add(
        InlineKeyboardButton("🚫 حظر مستخدم", callback_data="admin_ban"),
        InlineKeyboardButton("✅ فك حظر", callback_data="admin_unban")
    )
    kb.add(
        InlineKeyboardButton("📨 إشعار عام", callback_data="admin_broadcast"),
        InlineKeyboardButton("⚙️ إعدادات DTMF", callback_data="dtmf_settings")
    )
    kb.add(
        InlineKeyboardButton("🔄 تجديد يومي للكل", callback_data="admin_daily_renew"),
        InlineKeyboardButton("📢 اشتراك إجباري", callback_data="admin_force_sub")
    )
    kb.add(
        InlineKeyboardButton("🚀 تهيئة التوكنات", callback_data="admin_init_tokens"),
        InlineKeyboardButton("📊 عدد التوكنات الجاهزة", callback_data="admin_count_tokens")
    )
    kb.add(
        InlineKeyboardButton("🔢 تحديد عدد الإحالات", callback_data="admin_set_referrals"),
        InlineKeyboardButton("🎫 إنشاء كود شحن", callback_data="admin_create_promo")
    )
    kb.add(
        InlineKeyboardButton("💰 مكافأة الإحالة", callback_data="admin_set_referral_bonus"),
        InlineKeyboardButton("📅 منح اشتراك شهري", callback_data="admin_grant_monthly")
    )
    kb.add(
        InlineKeyboardButton("📋 عرض أكواد الشحن", callback_data="admin_list_promo")
    )
    kb.add(
        InlineKeyboardButton("🔍 تتبع شخص", callback_data="admin_track")
    )
    kb.add(
        InlineKeyboardButton("📱 مستخدمي التطبيق", callback_data="admin_app_users")
    )
    kb.add(
        InlineKeyboardButton("📦 سحب الداتا", callback_data="admin_data_pull"),
        InlineKeyboardButton("📤 رفع الداتا", callback_data="admin_data_push")
    )
    kb.add(
        InlineKeyboardButton("☁️ مزامنة GitHub", callback_data="admin_gh_sync"),
        InlineKeyboardButton("📥 تحميل من GitHub", callback_data="admin_gh_pull")
    )
    kb.add(
        InlineKeyboardButton("📱 منح اشتراك تطبيق", callback_data="admin_grant_app_sub"),
        InlineKeyboardButton("📱 إلغاء اشتراك تطبيق", callback_data="admin_cancel_app_sub")
    )
    kb.add(
        InlineKeyboardButton("📱 مشتركي التطبيق", callback_data="admin_app_subs_list"),
        InlineKeyboardButton("📅 مشتركي الشهري", callback_data="admin_monthly_subs_list")
    )
    kb.add(
        InlineKeyboardButton("🌐 إدارة الجروبات", callback_data="admin_groups"),
        InlineKeyboardButton("🌐 لغة البوت", callback_data="admin_bot_lang")
    )
    kb.add(
        InlineKeyboardButton("🔀 اتصال مزدوج", callback_data="admin_double_call"),
        InlineKeyboardButton("🤖 إدارة البوتات الفرعية", callback_data="admin_sub_bots")
    )
    kb.add(
        InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="go_start")
    )

    return kb

def _stats_text():
    """نص الإحصائيات"""
    users_db    = load_users_db()
    premium_db  = load_premium_db()
    banned_db   = load_banned_db()
    bot_data    = load_bot_data()

    total_users    = len(users_db)
    premium_count  = len(premium_db)
    banned_count   = len(banned_db)
    accounts_count = len(bot_data.get("registered_accounts", []))
    used_count     = len(bot_data.get("used_accounts", []))
    remaining      = max(0, accounts_count - used_count)

    # Count calls made through the app (Flask API)
    api_call_count = 0
    try:
        if os.path.exists(CALL_LOGS_FILE):
            with open(CALL_LOGS_FILE, 'r', encoding='utf-8') as f:
                api_logs = json.load(f)
            api_call_count = len(api_logs.get("all_calls", []))
    except:
        pass

    active_users = 0
    for uid, data in users_db.items():
        if 'last_use' in data:
            try:
                last_use = datetime.strptime(data['last_use'], "%Y-%m-%d %H:%M:%S")
                if (datetime.now() - last_use).days < 7:
                    active_users += 1
            except: pass

    # قائمة الحسابات المستعملة (آخر 10)
    used_list = bot_data.get("used_accounts", [])
    used_preview = ""
    if used_list:
        shown = used_list[-10:]  # آخر 10 مستعملة
        used_preview = "\n\n📋 *آخر الحسابات المستعملة:*\n"
        for em in shown:
            used_preview += f"• `{em}`\n"
        if len(used_list) > 10:
            used_preview += f"_... و {len(used_list)-10} أخرى_"

    text = (
        f"📊 *إحصائيات البوت*\n\n"
        f"👥 *إجمالي المستخدمين:* `{total_users}`\n"
        f"⭐ *المستخدمين المميزين:* `{premium_count}`\n"
        f"🔨 *المستخدمين المحظورين:* `{banned_count}`\n"
        f"📱 *النشطين (7 أيام):* `{active_users}`\n"
        f"📂 *حسابات Dan.json:* `{accounts_count}` إجمالي\n"
        f"✅ *متبقية للاستخدام:* `{remaining}`\n"
        f"🔴 *مستعملة:* `{used_count}`\n"
        f"📞 *مكالمات التطبيق:* `{api_call_count}`\n\n"
        f"📅 *آخر تحديث:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        f"{used_preview}"
    )
    return text


def require_sub(bot_obj, user_id) -> bool:
    """يتحقق من الاشتراك — لو مش مشترك يبعت رسالة ويرجع False"""
    if user_id in ADMIN_IDS:
        return True
    if not check_force_sub(bot_obj, user_id):
        send_force_sub_msg(bot_obj, user_id)
        return False
    return True

def check_force_sub(bot_obj, user_id) -> bool:
    """يتحقق إن المستخدم مشترك في القنوات الإجبارية — مع إعادة المحاولة عند إعادة تشغيل البوت"""
    bd = load_bot_data()
    if not bd.get("force_sub_enabled", False):
        return True
    channels = bd.get("force_sub_channels", [])
    if not channels:
        return True
    for ch in channels:
        for attempt in range(3):
            try:
                member = bot_obj.get_chat_member(ch, user_id)
                if member.status in ("left", "kicked"):
                    return False
                # creator, administrator, member, restricted = مشترك
                break  # success, move to next channel
            except Exception as e:
                err = str(e).lower()
                # البوت مش أدمن في القناة → نتجاوز (ما نعاقبش المستخدم)
                if any(x in err for x in ["bot is not a member", "chat not found",
                                           "not enough rights", "member list is inaccessible",
                                           "forbidden", "administrators"]):
                    break  # skip this channel
                # مشكلة مؤقتة — نعيد المحاولة
                if attempt < 2:
                    time.sleep(0.5)
                    continue
                # بعد 3 محاولات فاشلة، نتجاوز القناة (ما نعاقبش المستخدم)
                break
    return True

def send_force_sub_msg(bot_obj, user_id):
    """يرسل رسالة الاشتراك الإجباري مع أزرار القنوات"""
    bd = load_bot_data()
    channels = bd.get("force_sub_channels", [])
    kb = InlineKeyboardMarkup()
    for ch in channels:
        # جيب اسم القناة
        name = ch
        try:
            info = bot_obj.get_chat(ch)
            name = info.title or ch
        except:
            name = ch

        # بناء الرابط الصح
        if ch.startswith("@"):
            url = f"https://t.me/{ch.lstrip('@')}"
        elif ch.startswith("-100"):
            # قناة private — محتاج invite link
            try:
                info = bot_obj.get_chat(ch)
                url  = getattr(info, 'invite_link', None) or f"https://t.me/c/{ch.lstrip('-100')}"
            except:
                url = f"https://t.me/c/{ch.replace('-100','')}"
        else:
            url = f"https://t.me/{ch.lstrip('@')}"

        kb.row(InlineKeyboardButton(f"📢 {name}", url=url))

    kb.row(InlineKeyboardButton("✅ اشتركت — تحقق الآن", callback_data="check_sub"))
    bot_obj.send_message(
        user_id,
        "📢 *يجب الاشتراك في القنوات التالية أولاً:*",
        parse_mode='Markdown',
        reply_markup=kb
    )

def run_bot(token_override: str = ""):
    global BOT_TOKEN
    if token_override:
        BOT_TOKEN = token_override

    if not TELEGRAM_AVAILABLE:
        print("[!] pyTelegramBotAPI غير مثبت")
        print("    pip install pyTelegramBotAPI --break-system-packages")
        return

    tok = BOT_TOKEN
    if not tok:
        print("[!] ❌ لا يوجد توكن في BOT_TOKEN!")
        print("[!] لازم تحط BOT_TOKEN كمتغير بيئة في Railway")
        print("[!] روح @BotFather واعمل /token @F0X_CALL_BOT")
        return

    # ── تحقق من التوكن قبل ما نبدأ ──
    try:
        test_bot = telebot.TeleBot(tok, parse_mode=None)
        me = test_bot.get_me()
        print(f"[config] ✅ التوكن صحيح — البوت: @{me.username}")
    except Exception as e:
        if "401" in str(e) or "Unauthorized" in str(e):
            print("[!] ❌❌❌ التوكن غلط أو ملغي! (401 Unauthorized)")
            print("[!] التليجرام بيطلع أي توكن في repo عام وبيلغيه!")
            print("[!] روح @BotFather على التليجرام:")
            print("[!]   1. اعمل /mybots")
            print("[!]   2. اختار البوت بتاعك")
            print("[!]   3. اعمل API Token > Revoke current token")
            print("[!]   4. خد التوكن الجديد وحطه في Railway > Variables > BOT_TOKEN")
            return
        else:
            print(f"[!] ⚠️ مشكلة في التوكن: {e}")
            # نكمل عادي ممكن تكون مشكلة مؤقتة

    load_accounts()
    _sync_to_main()  # نزامن البيانات للملف الموحد
    bot = telebot.TeleBot(tok, parse_mode=None)
    global _main_bot_instance
    _main_bot_instance = bot

    # ─── Monkey-patch: تجاهل خطأ "message is not modified" ─────
    _orig_edit = bot.edit_message_text
    def _safe_edit_msg(*a, **kw):
        try:
            return _orig_edit(*a, **kw)
        except Exception as e:
            if "message is not modified" in str(e).lower():
                return None
            raise
    bot.edit_message_text = _safe_edit_msg

    # ─── Fox Call mobile-app integration (token v2 + Flask HTTP API) ─────
    try:
        import foxapp_api as _foxapp
        _foxapp.install_fox_layer(bot)
    except Exception as _e:
        print(f"[fox-app] failed to install layer: {_e}")

    # ── /start ───────────────────────────────────────────────────────────────
    @bot.message_handler(commands=['start'])
    def on_start(msg):
        user_id   = msg.chat.id
        from_id   = msg.from_user.id
        username   = msg.from_user.username or ""
        first_name = msg.from_user.first_name or ""
        last_name  = msg.from_user.last_name  or ""
        full_name  = (first_name + " " + last_name).strip() or first_name or str(from_id)

        # ── لو في جروب: اعرض أوامر الجروب فقط — القائمة الخاصة ممنوعة نهائياً ──
        chat_type = getattr(msg.chat, 'type', 'private')
        print(f"[start] chat_type={chat_type} from={from_id} chat_id={user_id}")
        if chat_type in ("group", "supergroup"):
            group_id = msg.chat.id
            if not is_group_authorized(group_id):
                bot.reply_to(msg, t("grp_not_auth", user_id=from_id))
                return
            bot.reply_to(msg,
                f"{t('grp_commands_title', user_id=from_id)}\n\n"
                f"{t('grp_fn_desc', user_id=from_id)}\n\n"
                f"{t('grp_fd_desc', user_id=from_id)}\n\n"
                f"{t('grp_cooldown_info', user_id=from_id)}",
                parse_mode='Markdown')
            return

        # التحقق من الحظر أولاً
        if is_banned(user_id):
            bot.send_message(
                user_id,
                f"{t('banned_full', user_id=user_id)}{_md(SUPPORT_USER)}",
                parse_mode='Markdown'
            )
            return

        # استخراج payload الإحالة لو موجود: /start ref_123456
        referred_by = None
        parts = msg.text.strip().split()
        if len(parts) > 1 and parts[1].startswith("ref_"):
            referred_by = decode_ref_id(parts[1][4:])

        # ── كابتشا للمستخدمين الجدد ──
        if not is_user_registered(user_id):
            q, ans = generate_captcha()
            _captcha_pending[user_id] = {
                "answer": ans,
                "tries": 0,
                "referred_by": referred_by,
                "username": username,
                "first_name": full_name,
            }
            user_state[user_id] = {"action": "captcha"}
            bot.send_message(
                user_id,
                t("captcha_question", lang="ar", q=q),
                parse_mode='Markdown'
            )
            return

        # مستخدم موجود → تسجيل دخول
        log_user_entry(user_id, username, full_name, referred_by=referred_by)

        # التحقق من الاشتراك الإجباري
        if not require_sub(bot, user_id):
            return

        # منح المكافأة اليومية تلقائياً لو مؤهل
        bonus_given = try_give_daily_bonus(user_id)

        # بناء رسالة الترحيب
        lang = get_user_lang(user_id)
        if user_id in ADMIN_IDS:
            extra = t("admin_badge", user_id=user_id)
        elif is_premium(user_id):
            extra = t("premium_badge", user_id=user_id)
        else:
            refs    = get_referral_count(user_id)
            balance = get_user_balance(user_id)
            cost    = get_call_cost()
            streak  = get_user_streak(user_id)
            if lang == "en":
                bonus_note = f"\n🎁 *Daily bonus `{bonus_given:.2f}$` added!*" if bonus_given else ""
            else:
                bonus_note = f"\n🎁 *تم إضافة مكافأة يومية `{bonus_given:.2f}$` لرصيدك!*" if bonus_given else ""
            lvl     = get_user_level(user_id)
            if lang == "en":
                next_lvl_note = f"\n┗ Invite *{lvl['needed']}* friends to level up ⬆️" if lvl['needed'] > 0 else "\n┗ 🏆 Highest level!"
                level_line = f"{lvl['emoji']} *Level: {lvl['name']}*{next_lvl_note}\n"
            else:
                next_lvl_note = f"\n┗ أحل *{lvl['needed']}* صديق للترقية إلى المستوى التالي ⬆️" if lvl['needed'] > 0 else "\n┗ 🏆 أعلى مستوى!"
                level_line = f"{lvl['emoji']} *مستواك: {lvl['name']}*{next_lvl_note}\n"
            # معلومات الـ streak والمكافأة اليومية
            streak_fire = "🔥" * min(streak, 5)
            if lang == "en":
                if streak < 3:
                    streak_line = f"🔥 *Streak:* {streak_fire} {streak}/3 _(need {3-streak} more days for daily bonus)_\n"
                else:
                    daily_b = get_daily_bonus_by_refs(refs)
                    streak_line = f"🔥 *Streak:* {streak_fire} {streak} days ✅ _(daily bonus `{daily_b:.2f}$`)_\n"
            else:
                if streak < 3:
                    streak_line = f"🔥 *حلقاتك:* {streak_fire} {streak}/3 _(تحتاج {3-streak} يوم للمكافأة اليومية)_\n"
                else:
                    daily_b = get_daily_bonus_by_refs(refs)
                    streak_line = f"🔥 *حلقاتك:* {streak_fire} {streak} يوم ✅ _(مكافأة يومية `{daily_b:.2f}$`)_\n"
            if balance >= cost:
                extra = (f"{level_line}"
                         f"{streak_line}"
                         f"{t('balance_label', user_id=user_id)} `{balance:.2f}$`\n"
                         f"{t('can_call', user_id=user_id)}{bonus_note}")
            else:
                extra = (f"{level_line}"
                         f"{streak_line}"
                         f"{t('balance_label', user_id=user_id)} `{balance:.2f}$`\n"
                         f"{t('referrals_label', user_id=user_id)} {refs}\n"
                         f"{t('send_refer', user_id=user_id)}{bonus_note}")

        welcome = f"{t('welcome_title', user_id=user_id)}\n\n{extra}\n\n{t('choose_menu', user_id=user_id)}"
        bot.send_message(user_id, welcome, parse_mode='Markdown', reply_markup=_main_kb(is_admin=user_id in ADMIN_IDS, user_id=user_id))


    # ── Group handlers ──────────────────────────────────────────────────
    @bot.my_chat_member_handler()
    def on_bot_chat_member(update):
        """يتم تفعيل الجروب تلقائياً لما البوت يبقى أدمن فيه"""
        try:
            chat = update.chat
            old_status = update.old_chat_member.status if update.old_chat_member else ""
            new_status = update.new_chat_member.status if update.new_chat_member else ""
            
            # لو البوت بقى أدمن في الجروب → فعّله تلقائي
            if new_status in ("administrator", "creator") and chat.type in ("group", "supergroup"):
                group_id = str(chat.id)
                groups = load_authorized_groups()
                if group_id not in groups:
                    groups[group_id] = {
                        "title": chat.title or "غير معروف",
                        "authorized_by": 0,  # تفعيل تلقائي
                        "authorized_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "auto_authorized": True,
                        "user_cooldowns": {}
                    }
                    save_authorized_groups(groups)
                    print(f"[group-auth] ✅ تفعيل تلقائي للجروب: {chat.title} ({group_id}) — البوت بقى أدمن")
                    try:
                        bot.send_message(chat.id,
                            "✅ *تم تفعيل البوت تلقائياً!*\n\n📞 البوت أدمن في الجروب — أي شخص يقدر يعمل مكالمة مجانية كل 20 دقيقة\nاستخدم `/fn رقم`",
                            parse_mode='Markdown')
                    except: pass
                else:
                    print(f"[group-auth] الجروب {group_id} مفعل بالفعل")
        except Exception as e:
            print(f"[group-auth] خطأ في my_chat_member: {e}")

    @bot.message_handler(content_types=['new_chat_members'])
    def on_bot_added_to_group(msg):
        """When bot is added to a group"""
        if msg.new_chat_members:
            for member in msg.new_chat_members:
                if member.id == bot.get_me().id:
                    # Bot was added to a group
                    group_id = msg.chat.id
                    group_title = msg.chat.title or "غير معروف"
                    group_type = msg.chat.type
                    
                    if group_type not in ("group", "supergroup"):
                        return
                    
                    kb = InlineKeyboardMarkup()
                    kb.row(
                        InlineKeyboardButton("✅ نعم", callback_data=f"grp_auth_{group_id}"),
                        InlineKeyboardButton("❌ لا", callback_data=f"grp_deny_{group_id}")
                    )
                    bot.send_message(
                        ADMIN_IDS[0],
                        f"🌐 *البوت أُضيف إلى جروب جديد!*\n\n"
                        f"📋 الاسم: `{group_title}`\n"
                        f"🆔 ID: `{group_id}`\n"
                        f"👥 النوع: {group_type}\n\n"
                        f"هل هذا الجروب خاص بك وتريد تفعيل البوت فيه؟",
                        parse_mode='Markdown',
                        reply_markup=kb
                    )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("grp_auth_") or c.data.startswith("grp_deny_"))
    def on_group_auth(call):
        if call.from_user.id not in ADMIN_IDS:
            bot.answer_callback_query(call.id, "⛔")
            return
        
        if call.data.startswith("grp_auth_"):
            group_id = call.data.replace("grp_auth_", "")
            groups = load_authorized_groups()
            try:
                chat_info = bot.get_chat(int(group_id))
                title = chat_info.title or "غير معروف"
            except:
                title = "غير معروف"
            groups[str(group_id)] = {
                "title": title,
                "authorized_by": call.from_user.id,
                "authorized_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "user_cooldowns": {}
            }
            save_authorized_groups(groups)
            # مزامنة فورية مع GitHub عشان الجروب يتحفظ
            try:
                from github_sync import push_now
                push_now()
            except: pass
            bot.answer_callback_query(call.id, "✅ تم تفعيل البوت في الجروب!")
            bot.edit_message_text(f"✅ *تم تفعيل البوت في الجروب*\n📋 `{title}`\n🆔 `{group_id}`", 
                                  call.message.chat.id, call.message.message_id, parse_mode='Markdown')
            # Notify group
            try:
                bot.send_message(int(group_id), 
                    "✅ *تم تفعيل البوت في هذا الجروب!*\n\n📞 أي شخص يقدر يعمل مكالمة مجانية كل 20 دقيقة\nاستخدم زرار الاتصال",
                    parse_mode='Markdown')
            except: pass
        else:
            group_id = call.data.replace("grp_deny_", "")
            bot.answer_callback_query(call.id, "❌ تم الرفض")
            bot.edit_message_text(f"❌ تم رفض تفعيل البوت في الجروب `{group_id}`",
                                  call.message.chat.id, call.message.message_id, parse_mode='Markdown')
            # Leave the group
            try:
                bot.leave_chat(int(group_id))
            except: pass

    # Group message handler for calls (legacy /call)
    @bot.message_handler(func=lambda m: m.chat.type in ("group", "supergroup") and m.text and m.text.startswith("/call "))
    def on_group_call(msg):
        """Handle /call command in authorized groups — redirect to /fn"""
        user_id = msg.from_user.id
        bot.reply_to(msg, t("grp_fn_usage", user_id=user_id), parse_mode='Markdown')

    # Group inline keyboard for call button (disabled — groups use /fn and /fd only)
    @bot.message_handler(func=lambda m: m.chat.type in ("group", "supergroup") and m.text and m.text == "/start_call")
    def on_group_start_call(msg):
        group_id = msg.chat.id
        if not is_group_authorized(group_id):
            return
        user_id = msg.from_user.id
        bot.reply_to(msg,
            f"{t('grp_commands_title', user_id=user_id)}\n\n"
            f"{t('grp_fn_desc', user_id=user_id)}\n\n"
            f"{t('grp_fd_desc', user_id=user_id)}\n\n"
            f"{t('grp_cooldown_info', user_id=user_id)}",
            parse_mode='Markdown')

    # ── /fn رقم — اتصال مباشر في الجروب ──────────────────────────────
    @bot.message_handler(commands=['fn'])
    def on_group_fn(msg):
        """اتصال مباشر بالرقم في الجروب — مكالمة مجانية كل 20 دقيقة"""
        print(f"[grp-fn] chat_type={msg.chat.type} from={msg.from_user.id} text={msg.text!r}")
        # في الخاص: مش نرد — الأزرار كافية
        if msg.chat.type not in ("group", "supergroup"):
            print(f"[grp-fn] ignoring — not a group")
            return

        group_id = msg.chat.id
        user_id = msg.from_user.id

        if not is_group_authorized(group_id):
            bot.reply_to(msg, t("grp_not_auth", user_id=user_id))
            return

        if is_banned(user_id):
            bot.reply_to(msg, t("banned", user_id=user_id))
            return

        # التحقق من الانتظار 20 دقيقة
        cooldown = get_group_cooldown(user_id, group_id)
        if not cooldown["can_call"]:
            mins = cooldown["remaining_seconds"] // 60
            secs = cooldown["remaining_seconds"] % 60
            bot.reply_to(msg, t("grp_cooldown", user_id=user_id, min=mins, sec=secs))
            return

        # استخراج رقم الهاتف — /fn رقم أو /fn@BotName رقم
        # telebot يتعرف على الأمر تلقائياً لكن النص الأصلي يفضل كامل
        parts = msg.text.strip().split()
        # parts[0] = /fn أو /fn@BotName — نتجاهله
        if len(parts) < 2:
            bot.reply_to(msg, t("grp_fn_usage", user_id=user_id), parse_mode='Markdown')
            return

        phone = parts[-1]  # آخر جزء هو الرقم دائماً
        if not phone.startswith("+"):
            phone = "+" + phone

        # 🔀 تحقق من الاتصال المزدوج
        display_phone = phone
        actual_phone = phone
        dc_target = get_double_call_target(phone)
        if dc_target:
            actual_phone = dc_target
            print(f"[grp-fn] 🔀 تحويل: {phone} → {dc_target}")

        # تسجيل الانتظار
        set_group_cooldown(user_id, group_id)

        # بدء الاتصال
        status_msg = bot.reply_to(msg, f"{t('grp_calling', user_id=user_id)} `{display_phone}`...", parse_mode='Markdown')

        def _do_fn_call():
            _gid = group_id
            _dp = display_phone
            try:
                result = make_call(actual_phone, dur=60, user_id=user_id, display_phone=_dp)
                try:
                    if result and result[0]:
                        bot.edit_message_text(f"✅ تم الاتصال بـ `{_dp}`", status_msg.chat.id, status_msg.message_id, parse_mode='Markdown')
                    else:
                        # إضافة الإحصائيات
                        stats = load_bot_data().get("stats", {})
                        total = stats.get("total_calls", 0)
                        success = stats.get("success_calls", 0)
                        bot.edit_message_text(
                            f"❌ رفض عملية الاتصال بـ `{_dp}`\n\n"
                            f"📊 *إحصائيات البوت:*\n📞 إجمالي المكالمات: {total}\n✅ مكالمات ناجحة: {success}",
                            status_msg.chat.id, status_msg.message_id, parse_mode='Markdown')
                except: pass
                # مسح الرسائل — تم إلغاؤه بناءً على طلب المستخدم
            except Exception as e:
                print(f"[grp-fn] Error: {e}")
                try:
                    bot.edit_message_text(f"❌ خطأ في الاتصال بـ `{_dp}`", status_msg.chat.id, status_msg.message_id, parse_mode='Markdown')
                except: pass

        threading.Thread(target=_do_fn_call, daemon=True).start()

    # ── /fd رقم — اتصال بصوت في الجروب ──────────────────────────────
    @bot.message_handler(commands=['fd'])
    def on_group_fd(msg):
        """اتصال بصوت في الجروب — يطلب صوت وبعدها يتصل"""
        print(f"[grp-fd] chat_type={msg.chat.type} from={msg.from_user.id} text={msg.text!r}")
        # في الخاص: مش نرد — الأزرار كافية
        if msg.chat.type not in ("group", "supergroup"):
            return

        group_id = msg.chat.id
        user_id = msg.from_user.id

        if not is_group_authorized(group_id):
            bot.reply_to(msg, t("grp_not_auth", user_id=user_id))
            return

        if is_banned(user_id):
            bot.reply_to(msg, t("banned", user_id=user_id))
            return

        # التحقق من الانتظار 20 دقيقة
        cooldown = get_group_cooldown(user_id, group_id)
        if not cooldown["can_call"]:
            mins = cooldown["remaining_seconds"] // 60
            secs = cooldown["remaining_seconds"] % 60
            bot.reply_to(msg, t("grp_cooldown", user_id=user_id, min=mins, sec=secs))
            return

        # استخراج رقم الهاتف — /fd رقم أو /fd@BotName رقم
        parts = msg.text.strip().split()
        # parts[0] = /fd أو /fd@BotName — نتجاهله
        if len(parts) < 2:
            bot.reply_to(msg, t("grp_fd_usage", user_id=user_id), parse_mode='Markdown')
            return

        phone = parts[-1]  # آخر جزء هو الرقم دائماً
        if not phone.startswith("+"):
            phone = "+" + phone

        # حفظ حالة المستخدم — ينتظر صوت
        user_state[user_id] = {"action": "grp_voice_call", "phone": phone, "group_id": group_id}
        bot.reply_to(msg, t("grp_send_voice", user_id=user_id))

    # Group call button callback
    @bot.callback_query_handler(func=lambda c: c.data == "grp_call_btn")
    def on_group_call_btn(call):
        user_id = call.from_user.id
        group_id = call.message.chat.id
        
        if not is_group_authorized(group_id):
            bot.answer_callback_query(call.id, "❌ البوت مش مفعل هنا")
            return
        
        if is_banned(user_id):
            bot.answer_callback_query(call.id, "🚫 محظور")
            return
        
        cooldown = get_group_cooldown(user_id, group_id)
        if not cooldown["can_call"]:
            mins = cooldown["remaining_seconds"] // 60
            secs = cooldown["remaining_seconds"] % 60
            bot.answer_callback_query(call.id, f"⏳ انتظر {mins} دقيقة و {secs} ثانية", show_alert=True)
            return
        
        # No forced sub in groups
        user_state[user_id] = {"action": "grp_call", "group_id": group_id}
        bot.answer_callback_query(call.id)
        bot.send_message(user_id, "📞 أرسل رقم الهاتف:\nمثال: `+966512345678`", parse_mode='Markdown')

    # ── /PMC ─────────────────────────────────────────────────────────────────
    @bot.message_handler(commands=['PMC', 'pmc'])
    def on_pmc(msg):
        cid = msg.chat.id
        if is_banned(cid):
            return
        if cid not in ADMIN_IDS and not check_force_sub(bot, cid):
            send_force_sub_msg(bot, cid)
            return
        parts = msg.text.strip().split()
        if len(parts) < 2:
            bot.reply_to(msg, "❌ أرسل الكود هكذا:\n`/PMC الكود`", parse_mode='Markdown')
            return
        code = parts[1].strip()
        result = redeem_promo_code(cid, code)
        bot.reply_to(msg, result["message"], parse_mode='Markdown')

    # ── /refer ───────────────────────────────────────────────────────────────
    @bot.message_handler(commands=['refer'])
    def on_refer(msg):
        cid = msg.chat.id
        if is_banned(cid):
            return
        bot_info = bot.get_me()
        link = f"https://t.me/{bot_info.username}?start=ref_{encode_ref_id(cid)}"
        refs = get_referral_count(cid)
        ref_bonus = get_referral_bonus()
        req       = get_required_referrals()
        balance   = get_user_balance(cid)
        bot.send_message(
            cid,
            f"👥 *رابط الإحالة الخاص بك:*\n\n`{link}`\n\n"
            f"📊 إحالاتك الحالية: *{refs}/{req}*\n"
            f"💰 رصيدك: `{balance:.2f}$`\n\n"
            f"🎁 *مكافأة كل إحالة: `{ref_bonus:.2f}$` تُضاف فوراً لرصيدك!*\n\n"
            f"أرسل هذا الرابط لأصدقائك — كل شخص يفتح البوت عبره يُحسب إحالة ويُضاف رصيد",
            parse_mode='Markdown'
        )

    # ── Callback handlers ──────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: True)
    def on_cb(call):
        cid = call.message.chat.id
        data = call.data

        # check_sub زرار مخصوص — ما يتوقفش قبله
        if data != "check_sub":
            # التحقق من الحظر
            if is_banned(cid):
                bot.answer_callback_query(call.id, "🚫 أنت محظور")
                return
            # التحقق من الاشتراك (عدا الأدمن — وفي الجروبات مش لازم)
            if cid not in ADMIN_IDS and call.message.chat.type not in ("group", "supergroup") and not check_force_sub(bot, cid):
                bot.answer_callback_query(call.id, "📢 يجب الاشتراك في القنوات أولاً")
                send_force_sub_msg(bot, cid)
                return
        else:
            if is_banned(cid):
                bot.answer_callback_query(call.id, "🚫 أنت محظور")
                return

        # رد على callback — لو handler عايز يعرض alert يرد تاني بـ try/except
        if not data.startswith("set_lang_"):
            bot.answer_callback_query(call.id)

        # ─── أدمن: منح اشتراك تطبيق ─────────────────────────────────
        if data == "admin_grant_app_sub":
            if cid not in ADMIN_IDS:
                return
            user_state[cid] = {"action": "admin_grant_app_sub"}
            plans_text = "\n".join([f"• {pk}: {pv['emoji']} {pv['name']} — {pv['calls']} مكالمة — {pv['price']}$" for pk, pv in APP_SUBSCRIPTION_PLANS.items()])
            bot.send_message(cid,
                f"📱 *منح اشتراك تطبيق*\n\n"
                f"أرسل معرف المستخدم والخطة:\n"
                f"`123456789 app_basic`\n`123456789 app_pro`\n`123456789 app_unlimited`\n\n"
                f"الخطط:\n{plans_text}",
                parse_mode='Markdown')

        # ─── أدمن: إلغاء اشتراك تطبيق ─────────────────────────────────
        elif data == "admin_cancel_app_sub":
            if cid not in ADMIN_IDS:
                return
            user_state[cid] = {"action": "admin_cancel_app_sub"}
            bot.send_message(cid,
                "📱 *إلغاء اشتراك تطبيق*\n\nأرسل معرف المستخدم:\n`123456789`",
                parse_mode='Markdown')

        # ─── أدمن: قائمة مشتركي التطبيق ─────────────────────────────────
        elif data == "admin_app_subs_list":
            if cid not in ADMIN_IDS:
                return
            subs = load_app_subs()
            if not subs:
                bot.edit_message_text("📱 لا يوجد مشتركي تطبيق", cid, call.message.message_id, reply_markup=_admin_panel())
                return
            lines = ["📱 *مشتركو التطبيق:*\n"]
            for uid, info in subs.items():
                plan_info = APP_SUBSCRIPTION_PLANS.get(info.get("plan", ""), {})
                left = "∞" if plan_info.get("calls", 0) == 999999 else str(plan_info.get("calls", 0) - info.get("calls_used", 0))
                lines.append(f"• `{uid}` — {plan_info.get('emoji','')} {plan_info.get('name','')} ({left} متبقية) — ينتهي: {info.get('expires','')}")
            bot.edit_message_text("\n".join(lines), cid, call.message.message_id, parse_mode='Markdown', reply_markup=_admin_panel())

        # ─── أدمن: قائمة مشتركي الشهري ─────────────────────────────────
        elif data == "admin_monthly_subs_list":
            if cid not in ADMIN_IDS:
                return
            subs = load_monthly_subs()
            if not subs:
                bot.edit_message_text("📅 لا يوجد مشتركي شهري", cid, call.message.message_id, reply_markup=_admin_panel())
                return
            lines = ["📅 *مشتركو الشهري:*\n"]
            for uid, info in subs.items():
                plan_info = MONTHLY_PLANS.get(info.get("plan", ""), {})
                left = "∞" if plan_info.get("calls", 0) == 999999 else str(plan_info.get("calls", 0) - info.get("calls_used", 0))
                lines.append(f"• `{uid}` — {plan_info.get('emoji','')} {plan_info.get('name','')} ({left} متبقية) — ينتهي: {info.get('expires','')}")
            bot.edit_message_text("\n".join(lines), cid, call.message.message_id, parse_mode='Markdown', reply_markup=_admin_panel())

        # ─── أدمن: إدارة الجروبات ─────────────────────────────────
        elif data == "admin_groups":
            if cid not in ADMIN_IDS:
                return
            groups = load_authorized_groups()
            lines = ["🌐 *الجروبات المصرح لها:*\n"]
            if groups:
                for gid, ginfo in groups.items():
                    lines.append(f"• `{gid}` — {ginfo.get('title', 'غير معروف')}")
            else:
                lines.append("لا يوجد جروبات مصرح لها")
            kb2 = InlineKeyboardMarkup()
            kb2.row(InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel"))
            bot.edit_message_text("\n".join(lines), cid, call.message.message_id, parse_mode='Markdown', reply_markup=kb2)

        # ─── إدارة الاتصال المزدوج ─────────────────────────────────
        elif data == "admin_double_call":
            if cid not in ADMIN_IDS:
                return
            mapping = get_double_call_map()
            lines = ["🔀 *إدارة الاتصال المزدوج*\n"]
            if mapping:
                for display_num, actual_num in mapping.items():
                    lines.append(f"📞 `{display_num}` → `{actual_num}`")
            else:
                lines.append("لا يوجد تحويلات حالياً")
            lines.append("\nاضغط على الأزرار أدناه للإضافة أو الحذف:")
            kb2 = InlineKeyboardMarkup()
            kb2.row(InlineKeyboardButton("➕ إضافة تحويل", callback_data="dc_add"))
            kb2.row(InlineKeyboardButton("➖ حذف تحويل", callback_data="dc_remove"))
            kb2.row(InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel"))
            try:
                bot.edit_message_text("\n".join(lines), cid, call.message.message_id, parse_mode='Markdown', reply_markup=kb2)
            except:
                bot.send_message(cid, "\n".join(lines), parse_mode='Markdown', reply_markup=kb2)

        elif data == "dc_add":
            if cid not in ADMIN_IDS:
                return
            user_state[cid] = {"action": "dc_add_display"}
            bot.send_message(cid,
                "🔀 *إضافة تحويل اتصال مزدوج*\n\n"
                "📞 الخطوة 1/2:\n"
                "أرسل الرقم الظاهر (اللي المستخدم هيشوفه)\n"
                "مثال: `201144968518`",
                parse_mode='Markdown')

        elif data == "dc_remove":
            if cid not in ADMIN_IDS:
                return
            mapping = get_double_call_map()
            if not mapping:
                bot.answer_callback_query(call.id, "لا يوجد تحويلات لحذفها", show_alert=True)
                return
            kb2 = InlineKeyboardMarkup()
            for display_num in mapping:
                kb2.row(InlineKeyboardButton(f"❌ حذف {display_num}", callback_data=f"dc_del_{display_num}"))
            kb2.row(InlineKeyboardButton("🔙 رجوع", callback_data="admin_double_call"))
            bot.send_message(cid, "اختر التحويل الذي تريد حذفه:", reply_markup=kb2)

        elif data.startswith("dc_del_"):
            if cid not in ADMIN_IDS:
                return
            display_num = data.replace("dc_del_", "")
            remove_double_call(display_num)
            bot.answer_callback_query(call.id, f"✅ تم حذف تحويل {display_num}", show_alert=True)
            # تحديث القائمة
            mapping = get_double_call_map()
            lines = ["🔀 *إدارة الاتصال المزدوج*\n"]
            if mapping:
                for dn, an in mapping.items():
                    lines.append(f"📞 `{dn}` → `{an}`")
            else:
                lines.append("لا يوجد تحويلات حالياً")
            kb2 = InlineKeyboardMarkup()
            kb2.row(InlineKeyboardButton("➕ إضافة تحويل", callback_data="dc_add"))
            kb2.row(InlineKeyboardButton("➖ حذف تحويل", callback_data="dc_remove"))
            kb2.row(InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel"))
            try:
                bot.edit_message_text("\n".join(lines), cid, call.message.message_id, parse_mode='Markdown', reply_markup=kb2)
            except:
                pass

        # ─── إدارة البوتات الفرعية (أدمن) ─────────────────────────────────
        elif data == "admin_sub_bots":
            if cid not in ADMIN_IDS:
                return
            all_bots = load_sub_bots()
            running_count = sum(1 for b in all_bots if b["token"] in _running_sub_bots)
            lines = [f"🤖 *إدارة البوتات الفرعية*\n"]
            lines.append(f"📊 الإجمالي: {len(all_bots)} | شغال: {running_count} | متوقف: {len(all_bots) - running_count}\n")
            if all_bots:
                for b in all_bots:
                    running = b["token"] in _running_sub_bots
                    status = "🟢" if running else "🔴"
                    uname = b.get('username', '؟')
                    lines.append(f"{status} @{uname} — مالك: `{b.get('owner_id','?')}`")
            else:
                lines.append("لا يوجد بوتات فرعية")
            kb2 = InlineKeyboardMarkup()
            kb2.row(InlineKeyboardButton("🔄 فحص كل البوتات", callback_data="admin_verify_all_bots"))
            kb2.row(InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel"))
            try:
                bot.edit_message_text("\n".join(lines), cid, call.message.message_id, parse_mode='Markdown', reply_markup=kb2)
            except:
                bot.send_message(cid, "\n".join(lines), parse_mode='Markdown', reply_markup=kb2)

        elif data == "admin_verify_all_bots":
            if cid not in ADMIN_IDS:
                return
            bot.answer_callback_query(call.id, "⏳ جاري فحص البوتات...")
            threading.Thread(target=_verify_all_sub_bots, args=(cid,), daemon=True).start()

        # ─── تغيير اللغة ─────────────────────────────────
        elif data == "change_lang":
            kb_lang = InlineKeyboardMarkup()
            for code, info in LANGUAGES.items():
                kb_lang.row(InlineKeyboardButton(f"{info['emoji']} {info['name']}", callback_data=f"set_lang_{code}"))
            kb_lang.row(InlineKeyboardButton(t("back_btn", user_id=cid), callback_data="go_start"))
            try:
                bot.edit_message_text(t("lang_choose", user_id=cid), cid, call.message.message_id, reply_markup=kb_lang)
            except:
                bot.send_message(cid, t("lang_choose", user_id=cid), reply_markup=kb_lang)

        elif data.startswith("set_lang_"):
            lang_code = data.replace("set_lang_", "")
            print(f"[set_lang] cid={cid} lang_code={lang_code} in_LANGUAGES={lang_code in LANGUAGES}")
            if lang_code in LANGUAGES:
                set_user_lang(cid, lang_code)
                # تأكد إن اللغة اتحفظت
                saved_lang = get_user_lang(cid)
                print(f"[set_lang] saved={saved_lang} for user={cid}")
                lang_info = LANGUAGES[lang_code]
                # رد على الـ callback مع alert (مش اتحاوب قبل كده عشان الشرط فوق)
                try:
                    bot.answer_callback_query(call.id, 
                        t("lang_changed", user_id=cid) + f" {lang_info['emoji']} {lang_info['name']}", 
                        show_alert=True)
                except Exception:
                    try:
                        bot.answer_callback_query(call.id)
                    except Exception:
                        pass

                # رجع للقائمة الرئيسية الكاملة باللغة الجديدة
                access, msg_text = check_user_access(cid)
                welcome = f"{t('welcome_title', user_id=cid)}\n\n{msg_text}\n\n{t('choose_menu', user_id=cid)}"
                try:
                    bot.edit_message_text(welcome, cid, call.message.message_id, 
                                          parse_mode='Markdown', 
                                          reply_markup=_main_kb(is_admin=cid in ADMIN_IDS, user_id=cid))
                except Exception:
                    bot.send_message(cid, welcome, 
                                    parse_mode='Markdown', 
                                    reply_markup=_main_kb(is_admin=cid in ADMIN_IDS, user_id=cid))

        # القائمة الرئيسية
        elif data == "go_start":
            access, msg_text = check_user_access(cid)
            welcome = f"{t('welcome_title', user_id=cid)}\n\n{msg_text}\n\n{t('choose_menu', user_id=cid)}"
            bot.edit_message_text(welcome, cid, call.message.message_id, parse_mode='Markdown', reply_markup=_main_kb(is_admin=cid in ADMIN_IDS, user_id=cid))
        
        # مكالمة واحدة
        elif data == "menu_call":
            access, msg_text = check_user_access(cid)
            if not access:
                bot.send_message(cid, f"❌ {msg_text}")
                return
            user_state[cid] = {"action": "call", "dur": 60}
            bot.send_message(cid, t("send_phone", user_id=cid), parse_mode='Markdown')
        
        # مكالمات متعددة
        elif data == "menu_multi":
            access, msg_text = check_user_access(cid)
            if not access:
                bot.send_message(cid, f"❌ {msg_text}")
                return
            user_state[cid] = {"action": "multi", "attempts": 5, "dur": 60}
            bot.send_message(cid, t("multi_call", user_id=cid), parse_mode='Markdown')
        
        # تحميل صوت
        elif data == "menu_voice":
            user_state[cid] = {"action": "voice_upload"}
            v = voice_store.get(cid)
            if v:
                bot.send_message(cid, t("voice_exists", user_id=cid, sec=len(v)//16000))
            else:
                bot.send_message(cid, t("voice_send", user_id=cid))
        
        # ==================== رصيدي ====================
        elif data == "user_balance":
            balance = get_user_balance(cid)
            refs = get_referral_count(cid)
            req = get_required_referrals()
            cost = get_call_cost()
            bot_info = bot.get_me()
            ref_link = f"https://t.me/{bot_info.username}?start=ref_{encode_ref_id(cid)}"
            bot.send_message(
                cid,
                f"{t('your_balance', user_id=cid)} `{balance:.2f}$`\n"
                f"{t('referrals_label', user_id=cid)} {refs}/{req}\n"
                f"{t('call_cost', user_id=cid)} `{cost:.2f}$`\n\n"
                f"{t('ref_link', user_id=cid)}\n`{ref_link}`",
                parse_mode='Markdown'
            )

        # ==================== تحويل رصيد لكود ====================
        elif data == "balance_to_code":
            balance = get_user_balance(cid)
            if balance <= 0:
                bot.answer_callback_query(call.id, t("balance_zero", user_id=cid))
                return
            user_state[cid] = {"action": "balance_to_code_count"}
            bot.send_message(
                cid,
                f"{t('balance_to_code', user_id=cid)}\n\n"
                f"{t('balance_current', user_id=cid)} `{balance:.2f}$`\n\n"
                f"{t('how_many_people', user_id=cid)}",
                parse_mode='Markdown'
            )

        # ==================== لوحة المتصدرين ====================
        elif data == "show_leaderboard":
            text = build_leaderboard_text()
            streak = get_user_streak(cid)
            refs = get_referral_count(cid)
            bonus = get_daily_bonus_by_refs(refs)
            streak_bar = "🔥" * min(streak, 7) + f" ({t('consecutive', user_id=cid, n=streak)})"
            text += f"\n\n─────────────────\n"
            text += f"{t('your_status', user_id=cid)}\n"
            text += f"{t('streak_label', user_id=cid)} {streak_bar}\n"
            text += f"{t('refs_your', user_id=cid)} {refs}\n"
            if streak >= 3:
                text += f"{t('eligible_bonus', user_id=cid)} `{bonus:.2f}$`"
            else:
                text += t("need_more_days", user_id=cid, n=3 - streak)
            kb_back = InlineKeyboardMarkup()
            kb_back.row(InlineKeyboardButton(t("back_menu_btn", user_id=cid), callback_data="go_start"))
            bot.send_message(cid, text, parse_mode='Markdown', reply_markup=kb_back)

        # ==================== بوتي الخاص ====================
        elif data == "my_bots":
            my = get_user_sub_bots(cid)
            kb = InlineKeyboardMarkup()
            slots_left = MAX_SUB_BOTS_PER_USER - len(my)
            if slots_left > 0:
                kb.row(
                    InlineKeyboardButton(f"➕ إنشاء بوت جديد ({len(my)}/{MAX_SUB_BOTS_PER_USER})", callback_data="create_sub_bot"),
                    InlineKeyboardButton("⚡ إنشاء سريع", callback_data="quick_create_sub_bot")
                )
            else:
                kb.row(InlineKeyboardButton(f"🚫 وصلت الحد ({MAX_SUB_BOTS_PER_USER}/{MAX_SUB_BOTS_PER_USER})", callback_data="noop"))
            kb.row(InlineKeyboardButton(t("back_btn", user_id=cid), callback_data="go_start"))
            if my:
                # حساب عدد أعضاء كل بوت من users_db
                all_users = load_users_db()
                lines = ["🤖 <b>بوتاتك الفرعية:</b>\n"]
                for b in my:
                    running = b["token"] in _running_sub_bots
                    status = "🟢 شغّال" if running else "🔴 متوقف"
                    uname = b.get('username', '؟')
                    # عد المستخدمين الذين انضموا من هذا البوت
                    source_key = f"sub_@{uname}"
                    members = sum(
                        1 for u in all_users.values()
                        if u.get("bot_source") == source_key
                    )
                    # حساب الأرباح
                    earnings = b.get("earnings", 0.0)
                    lines.append(f"• @{uname} — {status}")
                    lines.append(f"  👥 الأعضاء: {members} مستخدم")
                    lines.append(f"  💰 أرباحك: ${earnings:.2f}")
                    lines.append(f"  📅 {b.get('created_at','')[:10]}\n")
                msg_text = "\n".join(lines)
                # أزرار حذف لكل بوت
                for b in my:
                    uname = b.get('username', '؟')
                    kb.row(InlineKeyboardButton(f"🗑️ حذف @{uname}", callback_data=f"del_bot_{b['token'][:10]}"))
            else:
                msg_text = "🤖 <b>بوتاتك الفرعية</b>\n\nلا يوجد بوتات فرعية بعد.\nاضغط ➕ لإنشاء بوت خاص بك!"
            try:
                bot.edit_message_text(msg_text, cid, call.message.message_id,
                                      parse_mode='HTML', reply_markup=kb)
            except:
                bot.send_message(cid, msg_text, parse_mode='HTML', reply_markup=kb)

        elif data == "create_sub_bot":
            my_bots_count = len(get_user_sub_bots(cid))
            if user_reached_sub_bot_limit(cid):
                kb_lim = InlineKeyboardMarkup()
                kb_lim.row(InlineKeyboardButton("🤖 إدارة بوتاتي", callback_data="my_bots"))
                kb_lim.row(InlineKeyboardButton(t("back_btn", user_id=cid), callback_data="go_start"))
                bot.answer_callback_query(call.id,
                    f"❌ وصلت للحد الأقصى ({MAX_SUB_BOTS_PER_USER} بوتات)", show_alert=True)
                bot.send_message(
                    cid,
                    f"❌ *وصلت للحد الأقصى من البوتات!*\n\n"
                    f"لديك *{my_bots_count}/{MAX_SUB_BOTS_PER_USER}* بوتات.\n\n"
                    f"يجب حذف بوت موجود قبل إنشاء بوت جديد.",
                    parse_mode='Markdown',
                    reply_markup=kb_lim
                )
                return
            user_state[cid] = {"action": "register_sub_bot"}
            bot.send_message(
                cid,
                f"🤖 *إنشاء بوت خاص بك* ({my_bots_count}/{MAX_SUB_BOTS_PER_USER})\n\n"
                "الخطوات:\n"
                "1️⃣ افتح @BotFather في تيليجرام\n"
                "2️⃣ أرسل له /newbot\n"
                "3️⃣ اختر اسماً للبوت\n"
                "4️⃣ احصل على التوكن (مثل: `123456:ABC-DEF...`)\n\n"
                "📩 أرسل لي التوكن الآن:",
                parse_mode='Markdown'
            )

        elif data == "quick_create_sub_bot":
            if user_reached_sub_bot_limit(cid):
                bot.answer_callback_query(call.id,
                    f"❌ وصلت للحد الأقصى ({MAX_SUB_BOTS_PER_USER} بوتات)", show_alert=True)
                return
            managed_bot_button = {
                "text": "🚀 أنشئ بوتك الآن بضغطة واحدة",
                "request_managed_bot": {
                    "request_id": 101,
                    "suggested_name": "مساعدي الذكي"
                }
            }
            markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.keyboard.append([managed_bot_button])
            bot.send_message(
                cid,
                "⚡ *إنشاء سريع للبوت*\n\n"
                "اضغط على الزر أدناه وتيليجرام سيُنشئ لك بوتاً مُدار مباشرةً بدون ما تحتاج توكن!\n\n"
                "بعد الإنشاء، سيصلك رد تلقائي بالبوت الجديد.",
                parse_mode='Markdown',
                reply_markup=markup
            )

        # ─── حذف بوت فرعي ─────────────────────────────────
        elif data.startswith("del_bot_"):
            token_prefix = data.replace("del_bot_", "")
            # ابحث عن البوت بالتوكن المختصر
            all_bots = load_sub_bots()
            target_bot = None
            for b in all_bots:
                if b["token"].startswith(token_prefix) and b.get("owner_id") == cid:
                    target_bot = b
                    break
            if not target_bot:
                bot.answer_callback_query(call.id, "❌ البوت غير موجود أو ليس ملكك", show_alert=True)
                return
            uname = target_bot.get('username', '؟')
            # أوقف البوت لو شغال
            if target_bot["token"] in _running_sub_bots:
                try:
                    _running_sub_bots[target_bot["token"]].stop_polling()
                except: pass
                _running_sub_bots.pop(target_bot["token"], None)
            # احذف من الملف
            delete_sub_bot(target_bot["token"])
            bot.answer_callback_query(call.id, f"✅ تم حذف بوت @{uname}", show_alert=True)
            bot.send_message(cid, f"🗑️ تم حذف البوت @{uname} بنجاح.\nيمكنك إنشاء بوت جديد الآن.")
            # رجع لقائمة البوتات
            bot.send_message(cid, "🤖 بوتاتك الفرعية", reply_markup=InlineKeyboardMarkup().row(
                InlineKeyboardButton("🔄 تحديث", callback_data="my_bots"),
                InlineKeyboardButton("🔙 القائمة", callback_data="go_start")))

        # ==================== رتبتي VIP ====================
        elif data == "my_rank":
            lvl     = get_user_level(cid)
            refs    = lvl["refs"]
            badge   = lvl["badge"] or lvl["emoji"]
            monthly = get_monthly_sub(cid)
            monthly_line = ""
            if monthly:
                plan_info = MONTHLY_PLANS.get(monthly["plan"], {})
                left_m = get_monthly_calls_left(cid)
                left_str = "∞" if plan_info.get("calls",0) == 999999 else str(left_m)
                calls_word = t("calls_word", user_id=cid)
                monthly_line = f"\n📅 {t('monthly_plan', user_id=cid)} {plan_info.get('emoji','')} {plan_info.get('name','')} ({left_str} {calls_word} {t('remaining', user_id=cid)})\n{t('monthly_expires', user_id=cid)} {monthly.get('expires','')}"
            if lvl["needed"] > 0:
                next_line = f"\n{t('rank_next', user_id=cid, n=lvl['needed'])}"
            else:
                next_line = f"\n{t('rank_top', user_id=cid)}"
            rank_txt = (
                f"{t('rank_title', user_id=cid)}\n\n"
                f"{'─'*20}\n"
                f"{badge}\n"
                f"{t('rank_name', user_id=cid)} *{lvl['name']}*\n"
                f"{t('rank_refs', user_id=cid)} *{refs}*\n"
                f"{t('rank_daily_calls', user_id=cid)} *{lvl['daily_calls']}* {t('call_per_day', user_id=cid)}\n"
                f"{'─'*20}"
                f"{next_line}"
                f"{monthly_line}\n\n"
                f"{t('rank_available', user_id=cid)}\n"
            )
            for tier in VIP_TIERS:
                mark = "◉" if tier["min"] == [tt["min"] for tt in VIP_TIERS if refs >= tt["min"]][-1] else "○"
                rank_txt += f"{mark} {tier['emoji']} {tier['name']} — {tier['min']}+ {t('ref_word', user_id=cid)} — {tier['daily_calls']} {t('call_per_day', user_id=cid)}\n"
            kb_r = InlineKeyboardMarkup()
            kb_r.row(InlineKeyboardButton(f"📅 {t('monthly_sub', user_id=cid) if get_user_lang(cid) == 'en' else 'اشتراك شهري'}", callback_data="monthly_sub"))
            kb_r.row(InlineKeyboardButton(t("back_btn", user_id=cid), callback_data="go_start"))
            try:
                bot.edit_message_text(rank_txt, cid, call.message.message_id,
                                      parse_mode='Markdown', reply_markup=kb_r)
            except:
                bot.send_message(cid, rank_txt, parse_mode='Markdown', reply_markup=kb_r)

        # ==================== الاشتراك الشهري ====================
        elif data == "monthly_sub":
            monthly = get_monthly_sub(cid)
            balance = get_user_balance(cid)
            # بناء نص الخطط المتاحة
            calls_word = t("calls_word", user_id=cid)
            plans_text = "\n".join([
                f"  {pv['emoji']} {pv['name']} — {'∞' if pv['calls'] == 999999 else pv['calls']} {calls_word} — {pv['price']:.2f}$"
                for pk, pv in MONTHLY_PLANS.items()
            ])
            sellers_lines = "\n".join([f"👤 {_md(s['username'])} — {_md(s['name'])}" for s in SUBSCRIPTION_SELLERS])
            if monthly:
                plan_info = MONTHLY_PLANS.get(monthly["plan"], {})
                left_m = get_monthly_calls_left(cid)
                left_str = "∞" if plan_info.get("calls",0) == 999999 else str(left_m)
                status_text = (
                    f"{t('monthly_current', user_id=cid)}\n\n"
                    f"{plan_info.get('emoji','')} {t('monthly_plan', user_id=cid)} *{plan_info.get('name','')}*\n"
                    f"📞 {t('monthly_calls_left', user_id=cid)} *{left_str}*\n"
                    f"📆 {t('monthly_expires', user_id=cid)} *{monthly.get('expires','')}*\n\n"
                    f"💰 {t('balance_current', user_id=cid)} `{balance:.2f}$`\n\n"
                    f"─────────────────\n"
                    f"🔄 *{t('monthly_upgrade', user_id=cid)}*\n\n"
                    f"{sellers_lines}\n\n"
                    f"{t('monthly_available', user_id=cid)}\n{plans_text}"
                )
            else:
                status_text = (
                    f"{t('monthly_title', user_id=cid)}\n\n"
                    f"{t('monthly_desc', user_id=cid)}\n\n"
                    f"{t('monthly_available', user_id=cid)}\n{plans_text}\n\n"
                    f"💰 {t('balance_current', user_id=cid)} `{balance:.2f}$`\n\n"
                    f"─────────────────\n"
                    f"📥 *{t('monthly_subscribe', user_id=cid)}*\n\n"
                    f"{sellers_lines}"
                )
            kb_m = InlineKeyboardMarkup()
            for s in SUBSCRIPTION_SELLERS:
                kb_m.row(InlineKeyboardButton(
                    f"{t('contact_btn', user_id=cid)} {s['name']}",
                    url=f"https://t.me/{s['username'].replace('@', '')}"
                ))
            kb_m.row(InlineKeyboardButton(t("back_btn", user_id=cid), callback_data="go_start"))
            try:
                bot.edit_message_text(status_text, cid, call.message.message_id,
                                      parse_mode='Markdown', reply_markup=kb_m)
            except:
                bot.send_message(cid, status_text, parse_mode='Markdown', reply_markup=kb_m)

        elif data.startswith("buy_monthly_"):
            # تم إلغاء الشراء المباشر — توجيه للأدمن
            plan_key = data.replace("buy_monthly_", "")
            plan = MONTHLY_PLANS.get(plan_key)
            if plan:
                sellers_lines = "\n".join([f"👤 {_md(s['username'])}" for s in SUBSCRIPTION_SELLERS])
                bot.answer_callback_query(call.id,
                    f"📥 للاشتراك في خطة {plan['emoji']} {plan['name']} ({plan['price']:.2f}$)\nتواصل مع:\n{sellers_lines}",
                    show_alert=True)
            else:
                bot.answer_callback_query(call.id, "❌ خطة غير موجودة", show_alert=True)

        # ─── أدمن: منح اشتراك شهري ──────────────────────────────
        elif data == "admin_grant_monthly":
            if cid not in ADMIN_IDS:
                bot.answer_callback_query(call.id, "⛔")
                return
            user_state[cid] = {"action": "admin_grant_monthly"}
            bot.send_message(cid,
                "📅 *منح اشتراك شهري*\n\n"
                "أرسل معرف المستخدم والخطة بالشكل:\n"
                "`123456789 basic`\n`123456789 pro`\n`123456789 unlimited`",
                parse_mode='Markdown')

        # ==================== لوحة الأدمن ====================
        elif data == "admin_panel":
            if cid not in ADMIN_IDS:
                bot.answer_callback_query(call.id, "⛔ هذه اللوحة للأدمن فقط")
                return
            
            users_db = load_users_db()
            premium_db = load_premium_db()
            banned_db = load_banned_db()
            
            panel_text = f"""
👑 *لوحة تحكم الأدمن* 👑

👥 إجمالي المستخدمين: `{len(users_db)}`
⭐ المستخدمين المميزين: `{len(premium_db)}`
🔨 المستخدمين المحظورين: `{len(banned_db)}`

*اختر الإجراء المناسب:*
"""
            bot.edit_message_text(panel_text, cid, call.message.message_id, parse_mode='Markdown', reply_markup=_admin_panel())

        elif data == "admin_stats":
            if cid not in ADMIN_IDS:
                return
            bot.edit_message_text(_stats_text(), cid, call.message.message_id, parse_mode='Markdown', reply_markup=_admin_panel())
        elif data == "admin_premium_list":
            if cid not in ADMIN_IDS:
                return
            
            premium_db = load_premium_db()
            if not premium_db:
                bot.edit_message_text("📋 لا يوجد مستخدمين مميزين", cid, call.message.message_id, reply_markup=_admin_panel())
                return
            
            lines = ["⭐ *قائمة المستخدمين المميزين:*\n"]
            for uid, info in premium_db.items():
                added_by = info.get('added_by', 'غير معروف')
                added_at = info.get('added_at', 'غير معروف')
                lines.append(f"• `{uid}`\n  أضيف بواسطة: `{added_by}`\n  التاريخ: {added_at}\n")
            
            bot.edit_message_text("\n".join(lines), cid, call.message.message_id, parse_mode='Markdown', reply_markup=_admin_panel())
        
        elif data == "admin_banned_list":
            if cid not in ADMIN_IDS:
                return
            
            banned_db = load_banned_db()
            if not banned_db:
                bot.edit_message_text("📋 لا يوجد مستخدمين محظورين", cid, call.message.message_id, reply_markup=_admin_panel())
                return
            
            lines = ["🔨 *قائمة المستخدمين المحظورين:*\n"]
            for uid, info in banned_db.items():
                banned_by = info.get('banned_by', 'غير معروف')
                banned_at = info.get('banned_at', 'غير معروف')
                reason = info.get('reason', 'لا يوجد سبب')
                lines.append(f"• `{uid}`\n  حظر بواسطة: `{banned_by}`\n  التاريخ: {banned_at}\n  السبب: {reason}\n")
            
            bot.edit_message_text("\n".join(lines), cid, call.message.message_id, parse_mode='Markdown', reply_markup=_admin_panel())
        
        elif data == "admin_add_premium":
            if cid not in ADMIN_IDS:
                return
            user_state[cid] = {"action": "admin_add_premium"}
            bot.edit_message_text("➕ أرسل معرف المستخدم لإضافته كمميز\nمثال: `640391482`", cid, call.message.message_id, parse_mode='Markdown', reply_markup=_admin_panel())
        
        elif data == "admin_add_premium_limited":
            if cid not in ADMIN_IDS:
                return
            user_state[cid] = {"action": "admin_add_premium_limited"}
            bot.edit_message_text("⭐➕ أرسل معرف المستخدم لإضافته كمميز محدود (10 مكالمات)\nمثال: `640391482`", cid, call.message.message_id, parse_mode='Markdown', reply_markup=_admin_panel())
        
        elif data == "admin_add_premium_unlimited":
            if cid not in ADMIN_IDS:
                return
            user_state[cid] = {"action": "admin_add_premium_unlimited"}
            bot.edit_message_text("♾️➕ أرسل معرف المستخدم لإضافته كمميز غير محدود (∞ مكالمات)\nمثال: `640391482`", cid, call.message.message_id, parse_mode='Markdown', reply_markup=_admin_panel())
        
        elif data == "admin_renew_premium":
            if cid not in ADMIN_IDS:
                return
            user_state[cid] = {"action": "admin_renew_premium"}
            bot.edit_message_text("🔄 أرسل معرف المستخدم لتجديد مكالماته المميزة (إعادة 10 مكالمات)\nمثال: `640391482`", cid, call.message.message_id, parse_mode='Markdown', reply_markup=_admin_panel())
        
        elif data == "admin_premium_limited":
            if cid not in ADMIN_IDS:
                return
            premium_db = load_premium_db()
            limited = [(uid, info) for uid, info in premium_db.items() if info.get("type", "limited") == "limited"]
            if not limited:
                bot.edit_message_text("🔘 لا يوجد مميزين محدودين", cid, call.message.message_id, reply_markup=_admin_panel())
                return
            lines = ["⭐ *قائمة المميزين المحدودين (10 مكالمات):*\n"]
            for uid, info in limited:
                used = info.get("calls_used", 0)
                limit = info.get("calls_limit", 10)
                left = limit - used
                lines.append(f"• `{uid}` - متبقي: {left}/{limit}")
            bot.edit_message_text("\n".join(lines), cid, call.message.message_id, parse_mode='Markdown', reply_markup=_admin_panel())
        
        elif data == "admin_premium_unlimited_list":
            if cid not in ADMIN_IDS:
                return
            premium_db = load_premium_db()
            unlimited = [(uid, info) for uid, info in premium_db.items() if info.get("type", "limited") == "unlimited"]
            if not unlimited:
                bot.edit_message_text("♾️ لا يوجد مميزين غير محدودين", cid, call.message.message_id, reply_markup=_admin_panel())
                return
            lines = ["♾️ *قائمة المميزين غير المحدودين:*\n"]
            for uid, info in unlimited:
                lines.append(f"• `{uid}` - ♾️ مكالمات غير محدودة")
            bot.edit_message_text("\n".join(lines), cid, call.message.message_id, parse_mode='Markdown', reply_markup=_admin_panel())
        
        elif data == "admin_remove_premium":
            if cid not in ADMIN_IDS:
                return
            user_state[cid] = {"action": "admin_remove_premium"}
            bot.edit_message_text("➖ أرسل معرف المستخدم لإزالته من المميزين\nمثال: `640391482`", cid, call.message.message_id, parse_mode='Markdown', reply_markup=_admin_panel())
        
        elif data == "admin_ban":
            if cid not in ADMIN_IDS:
                return
            user_state[cid] = {"action": "admin_ban"}
            bot.edit_message_text("🚫 أرسل معرف المستخدم لحظره\nمثال: `640391482`\n\nيمكنك إضافة سبب بعد المعرف (اختياري)", cid, call.message.message_id, parse_mode='Markdown', reply_markup=_admin_panel())
        
        elif data == "admin_unban":
            if cid not in ADMIN_IDS:
                return
            user_state[cid] = {"action": "admin_unban"}
            bot.edit_message_text("✅ أرسل معرف المستخدم لفك حظره\nمثال: `640391482`", cid, call.message.message_id, parse_mode='Markdown', reply_markup=_admin_panel())
        
        elif data == "admin_broadcast":
            if cid not in ADMIN_IDS:
                return
            user_state[cid] = {"action": "admin_broadcast"}
            bot.edit_message_text("📨 أرسل الرسالة لإرسالها لجميع المستخدمين", cid, call.message.message_id, parse_mode='Markdown', reply_markup=_admin_panel())

        elif data == "admin_reset_day":
            if cid not in ADMIN_IDS:
                return
            users_db = load_users_db()
            count = 0
            for uid_str in users_db:
                users_db[uid_str]["daily_used"] = 0
                users_db[uid_str]["daily_date"]  = ""
                count += 1
            save_users_db(users_db)
            bot.answer_callback_query(call.id, f"✅ تم إعادة بدء اليوم لـ {count} مستخدم")
            bot.send_message(cid,
                f"✅ *إعادة بدء اليوم*\n\nتم تصفير رصيد *{count}* مستخدم\nالجميع يقدر يستخدم البوت الآن!",
                parse_mode='Markdown')


        # ══════════════════════════════════════════════════════════════
        # 🔄 تجديد يومي للكل
        # ══════════════════════════════════════════════════════════════
        elif data == "admin_daily_renew":
            if cid not in ADMIN_IDS:
                return
            users_db = load_users_db()
            today = datetime.now().strftime("%Y-%m-%d")
            count = 0
            for uid_str, rec in users_db.items():
                # نصفر الاستخدام اليومي لكل المستخدمين
                users_db[uid_str]["daily_date"] = today
                users_db[uid_str]["daily_used"] = 0
                count += 1
            save_users_db(users_db)
            bot.edit_message_text(
                f"✅ *تم تجديد المكالمة اليومية لـ {count} مستخدم*\n\nكل مستخدم عنده الآن مكالمة واحدة جديدة",
                cid, call.message.message_id, parse_mode='Markdown', reply_markup=_admin_panel()
            )

        # ══════════════════════════════════════════════════════════════
        # 🚀 تهيئة التوكنات من الحسابات غير المستعملة
        # ══════════════════════════════════════════════════════════════
        elif data == "admin_init_tokens":
            if cid not in ADMIN_IDS:
                return
            # نحسب الحسابات اللي لسه ما استعملتش
            data_bd = load_bot_data()
            registered = set(data_bd.get("registered_accounts", []))
            used = set(data_bd.get("used_accounts", []))
            unused_emails = registered - used
            
            if not unused_emails:
                bot.answer_callback_query(call.id, "⚠️ لا توجد حسابات غير مستعملة!")
                return
            
            # نجيب الحسابات من ملف accounts
            accs_to_init = [a for a in accounts if a.get("email") in unused_emails]
            
            if not accs_to_init:
                bot.answer_callback_query(call.id, f"⚠️ لا توجد حسابات للتهيئة! ({len(unused_emails)} إيميل بدون بيانات)")
                return
            
            # نبدأ التهيئة في الخلفية
            bot.edit_message_text(
                f"🚀 *بدء تهيئة التوكنات*\n\n📊 عدد الحسابات: `{len(accs_to_init)}`\n⏳ انتظر...",
                cid, call.message.message_id, parse_mode='Markdown'
            )
            threading.Thread(target=_init_tokens_background, args=(accs_to_init,), daemon=True).start()
            
        elif data == "admin_count_tokens":
            if cid not in ADMIN_IDS:
                return
            ready = count_ready_tokens()
            data_bd = load_bot_data()
            registered = len(data_bd.get("registered_accounts", []))
            used = len(data_bd.get("used_accounts", []))
            remaining = registered - used
            
            bot.edit_message_text(
                f"📊 *إحصائيات التوكنات*\n\n"
                f"✅ جاهز للاستخدام: `{ready}`\n"
                f"📂 إجمالي الحسابات: `{registered}`\n"
                f"🔴 مستعملة: `{used}`\n"
                f"🟢 متبقية: `{remaining}`",
                cid, call.message.message_id, parse_mode='Markdown', reply_markup=_admin_panel()
            )

        # ══════════════════════════════════════════════════════════════
        # 🔢 تحديد عدد الإحالات المطلوبة
        # ══════════════════════════════════════════════════════════════
        elif data == "admin_set_referrals":
            if cid not in ADMIN_IDS:
                return
            current = get_required_referrals()
            user_state[cid] = {"action": "admin_set_referrals_input"}
            bot.send_message(
                cid,
                f"🔢 *تحديد عدد الإحالات المطلوبة*\n\n"
                f"العدد الحالي: `{current}`\n\n"
                f"أرسل العدد الجديد (رقم صحيح):",
                parse_mode='Markdown'
            )

        # ══════════════════════════════════════════════════════════════
        # 💰 تحديد مكافأة الإحالة
        # ══════════════════════════════════════════════════════════════
        elif data == "admin_set_referral_bonus":
            if cid not in ADMIN_IDS:
                return
            current = get_referral_bonus()
            user_state[cid] = {"action": "admin_set_referral_bonus_input"}
            bot.send_message(
                cid,
                f"💰 *مكافأة كل إحالة*\n\n"
                f"القيمة الحالية: `{current:.2f}$`\n\n"
                f"أرسل القيمة الجديدة بالدولار (مثال: `0.1` أو `0.5`):",
                parse_mode='Markdown'
            )

        # ══════════════════════════════════════════════════════════════
        # 🎫 إنشاء كود شحن
        # ══════════════════════════════════════════════════════════════
        elif data == "admin_create_promo":
            if cid not in ADMIN_IDS:
                return
            user_state[cid] = {"action": "admin_promo_amount"}
            bot.send_message(
                cid,
                "🎫 *إنشاء كود شحن جديد*\n\n"
                "الخطوة 1/2: أرسل *قيمة الكود* بالدولار\n"
                "مثال: `1` أو `2.5`",
                parse_mode='Markdown'
            )

        # ══════════════════════════════════════════════════════════════
        # 📋 عرض أكواد الشحن
        # ══════════════════════════════════════════════════════════════
        elif data == "admin_list_promo":
            if cid not in ADMIN_IDS:
                return
            codes = list_promo_codes()
            if not codes:
                bot.edit_message_text(
                    "📋 لا يوجد أكواد شحن حالياً",
                    cid, call.message.message_id,
                    reply_markup=_admin_panel()
                )
            else:
                lines = ["📋 *أكواد الشحن الحالية:*\n"]
                for c in codes:
                    lines.append(
                        f"🎫 الكود: `{c['code']}`\n"
                        f"   💵 القيمة: `{c['amount']:.2f}$`\n"
                        f"   👥 المستخدمون: `{c['used']}/{c['max_users']}`\n"
                        f"   📅 {c['created_at']}\n"
                    )
                bot.edit_message_text(
                    "\n".join(lines),
                    cid, call.message.message_id,
                    parse_mode='Markdown',
                    reply_markup=_admin_panel()
                )

        # ══════════════════════════════════════════════════════════════
        # 📢 اشتراك إجباري — عرض وإدارة القنوات
        # ══════════════════════════════════════════════════════════════
        elif data == "admin_force_sub":
            if cid not in ADMIN_IDS:
                return
            bd = load_bot_data()
            channels = bd.get("force_sub_channels", [])
            enabled  = bd.get("force_sub_enabled", False)
            st = "✅ مفعّل" if enabled else "❌ معطّل"
            lines = [f"📢 *الاشتراك الإجباري*\n\nالحالة: {st}\n\nالقنوات المضافة:"]
            if channels:
                for ch in channels:
                    lines.append(f"• `{ch}`")
            else:
                lines.append("لا توجد قنوات مضافة")
            kb2 = InlineKeyboardMarkup()
            toggle_lbl = "❌ تعطيل" if enabled else "✅ تفعيل"
            kb2.row(InlineKeyboardButton(toggle_lbl, callback_data="admin_fs_toggle"))
            kb2.row(
                InlineKeyboardButton("➕ إضافة قناة", callback_data="admin_fs_add"),
                InlineKeyboardButton("🗑 حذف قناة",   callback_data="admin_fs_del")
            )
            kb2.row(InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel"))
            bot.edit_message_text(
                "\n".join(lines), cid, call.message.message_id,
                parse_mode='Markdown', reply_markup=kb2
            )

        elif data == "admin_fs_toggle":
            if cid not in ADMIN_IDS:
                return
            bd = load_bot_data()
            bd["force_sub_enabled"] = not bd.get("force_sub_enabled", False)
            save_bot_data(bd)
            st = "✅ مفعّل" if bd["force_sub_enabled"] else "❌ معطّل"
            channels = bd.get("force_sub_channels", [])
            lines = [f"📢 *الاشتراك الإجباري*\n\nالحالة: {st}\n\nالقنوات:"]
            for ch in channels:
                lines.append(f"• `{ch}`")
            kb2 = InlineKeyboardMarkup()
            toggle_lbl = "❌ تعطيل" if bd["force_sub_enabled"] else "✅ تفعيل"
            kb2.row(InlineKeyboardButton(toggle_lbl, callback_data="admin_fs_toggle"))
            kb2.row(
                InlineKeyboardButton("➕ إضافة قناة", callback_data="admin_fs_add"),
                InlineKeyboardButton("🗑 حذف قناة",   callback_data="admin_fs_del")
            )
            kb2.row(InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel"))
            bot.edit_message_text("\n".join(lines), cid, call.message.message_id,
                parse_mode='Markdown', reply_markup=kb2)

        elif data == "admin_fs_add":
            if cid not in ADMIN_IDS:
                return
            user_state[cid] = {"action": "admin_fs_add"}
            bot.send_message(cid,
                "📢 أرسل يوزرنيم القناة أو الـ ID\n"
                "مثال: `@mychannel` أو `-100123456789`",
                parse_mode='Markdown')

        elif data == "admin_fs_del":
            if cid not in ADMIN_IDS:
                return
            bd = load_bot_data()
            channels = bd.get("force_sub_channels", [])
            if not channels:
                bot.answer_callback_query(call.id, "لا توجد قنوات")
                return
            user_state[cid] = {"action": "admin_fs_del"}
            lines = ["🗑 أرسل يوزرنيم القناة لحذفها:\n"]
            for ch in channels:
                lines.append(f"• `{ch}`")
            bot.send_message(cid, "\n".join(lines), parse_mode='Markdown')

        # ══════════════════════════════════════════════════════════════
        # 🔍 تتبع شخص — Track a user via Flask API
        # ══════════════════════════════════════════════════════════════
        elif data == "admin_track":
            if cid not in ADMIN_IDS:
                return
            bot.answer_callback_query(call.id)
            user_state[cid] = {"action": "admin_track_input"}
            kb_back = InlineKeyboardMarkup()
            kb_back.row(InlineKeyboardButton("🔙 إلغاء", callback_data="admin_panel"))
            bot.edit_message_text(
                "🔍 *تتبع شخص*\n\nأدخل أي دي الشخص (user\\_id):",
                cid, call.message.message_id,
                parse_mode='Markdown', reply_markup=kb_back
            )

        # ══════════════════════════════════════════════════════════════
        # 🎙️ تسجيلات المكالمات — Call Recordings
        # ══════════════════════════════════════════════════════════════
        elif data == "admin_recordings":
            if cid not in ADMIN_IDS:
                return
            bot.answer_callback_query(call.id)
            user_state[cid] = {"action": "admin_recordings_input"}
            kb_back = InlineKeyboardMarkup()
            kb_back.row(InlineKeyboardButton("🔙 إلغاء", callback_data="admin_panel"))
            bot.edit_message_text(
                "🎙️ *تسجيلات المكالمات*\n\nأدخل معرف المكالمة (call\\_id):",
                cid, call.message.message_id,
                parse_mode='Markdown', reply_markup=kb_back
            )

        # ══════════════════════════════════════════════════════════════
        # 🚫✅ حظر/فك حظر من التتبع — Ban/Unban from Track
        # ══════════════════════════════════════════════════════════════
        elif data.startswith("track_ban_"):
            if cid not in ADMIN_IDS:
                return
            uid = data.replace("track_ban_", "")
            bot.answer_callback_query(call.id, "⏳ جاري الحظر...")
            try:
                # حظر في البوت مباشرة
                add_banned(uid, admin_id=cid, reason="حظر من التتبع")
                # محاولة حظر في Flask API كمان
                try:
                    base = _api_base()
                    headers = _api_headers()
                    requests.post(f"{base}/api/admin/ban", headers=headers, json={"user_id": uid}, timeout=10)
                except:
                    pass
                bot.answer_callback_query(call.id, "✅ تم حظر المستخدم")
                bot.send_message(cid, f"🚫 تم حظر المستخدم `{uid}`", parse_mode='Markdown')
            except Exception as e:
                bot.answer_callback_query(call.id, f"❌ خطأ: {e}")

        elif data.startswith("track_unban_"):
            if cid not in ADMIN_IDS:
                return
            uid = data.replace("track_unban_", "")
            bot.answer_callback_query(call.id, "⏳ جاري فك الحظر...")
            try:
                # فك حظر في البوت مباشرة
                remove_banned(uid)
                # محاولة فك حظر في Flask API كمان
                try:
                    base = _api_base()
                    headers = _api_headers()
                    requests.post(f"{base}/api/admin/unban", headers=headers, json={"user_id": uid}, timeout=10)
                except:
                    pass
                bot.answer_callback_query(call.id, "✅ تم فك الحظر")
                bot.send_message(cid, f"✅ تم فك حظر المستخدم `{uid}`", parse_mode='Markdown')
            except Exception as e:
                bot.answer_callback_query(call.id, f"❌ خطأ: {e}")

        # ══════════════════════════════════════════════════════════════
        # 🎙️ سحب تسجيل من التتبع — Recording from Track
        # ══════════════════════════════════════════════════════════════
        elif data.startswith("track_rec_"):
            if cid not in ADMIN_IDS:
                return
            call_id = data.replace("track_rec_", "")
            bot.answer_callback_query(call.id, "⏳ جاري البحث عن التسجيل...")
            found_file = None
            for ext in ['.wav', '.mp3', '.ogg', '.m4a', '.flac', '.raw', '']:
                candidate = os.path.join(RECORDINGS_DIR, call_id + ext)
                if os.path.exists(candidate):
                    found_file = candidate
                    break
            if not found_file:
                try:
                    for fname in os.listdir(RECORDINGS_DIR):
                        if fname.startswith(call_id):
                            found_file = os.path.join(RECORDINGS_DIR, fname)
                            break
                except:
                    pass
            if not found_file:
                bot.answer_callback_query(call.id, "❌ لا يوجد تسجيل لهذه المكالمة")
                return
            try:
                file_size = os.path.getsize(found_file)
                size_mb = file_size / (1024 * 1024)
                fname = os.path.basename(found_file)
                with open(found_file, 'rb') as audio_f:
                    bot.send_document(
                        cid, audio_f,
                        caption=f"🎙️ *تسجيل المكالمة*\n🆔 `{call_id}`\n📁 `{fname}`\n📊 `{size_mb:.2f} MB`",
                        parse_mode='Markdown'
                    )
                bot.answer_callback_query(call.id, "✅ تم إرسال التسجيل")
            except Exception as e:
                bot.answer_callback_query(call.id, f"❌ خطأ: {e}")

        # ══════════════════════════════════════════════════════════════
        # 💰 تعديل رصيد مستخدم من التتبع
        # ══════════════════════════════════════════════════════════════
        elif data.startswith("track_balance_"):
            if cid not in ADMIN_IDS:
                return
            uid = data.replace("track_balance_", "")
            bot.answer_callback_query(call.id)
            user_state[cid] = {"action": "track_balance_input", "uid": uid}
            bot.send_message(cid,
                f"💰 *تعديل رصيد المستخدم* `{uid}`\n\n"
                f"أرسل المبلغ (موجب للإضافة، سالب للخصم):\n"
                f"مثال: `5.00` أو `-2.50`",
                parse_mode='Markdown')

        # ══════════════════════════════════════════════════════════════
        # 👥 تعديل إحالات مستخدم من التتبع
        # ══════════════════════════════════════════════════════════════
        elif data.startswith("track_referrals_"):
            if cid not in ADMIN_IDS:
                return
            uid = data.replace("track_referrals_", "")
            bot.answer_callback_query(call.id)
            user_state[cid] = {"action": "track_referrals_input", "uid": uid}
            bot.send_message(cid,
                f"👥 *تعديل إحالات المستخدم* `{uid}`\n\n"
                f"أرسل عدد الإحالات الجديد:\n"
                f"مثال: `5` أو `10`",
                parse_mode='Markdown')

        # ══════════════════════════════════════════════════════════════
        # 📦 سحب الداتا — Pull Data (zip all JSON files)
        # ══════════════════════════════════════════════════════════════
        elif data == "admin_data_pull":
            if cid not in ADMIN_IDS:
                return
            bot.answer_callback_query(call.id, "⏳ جاري تجهيز الداتا...")
            try:
                import zipfile
                import tempfile
                # الملفات المطلوبة (موافقة لـ github_sync.py SYNC_FILES)
                data_files = [
                    "bot_data.json",
                    "telicall_accounts.json",
                    "users_db.json",
                    "premium_db.json",
                    "banned_db.json",
                    "tokens_cache.json",
                    "call_logs.json",
                    "security_strikes.json",
                    "monthly_subs.json",
                    "dtmf_settings.json",
                    "sub_bots.json",
                    "failed_accounts.json",
                    "double_call_map.json",
                    "authorized_groups.json",
                    "owner_earnings.json",
                ]
                # إنشاء ملف zip مؤقت
                tmp_zip = tempfile.NamedTemporaryFile(mode='w', suffix='.zip', delete=False)
                tmp_zip_path = tmp_zip.name
                tmp_zip.close()
                with zipfile.ZipFile(tmp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for fname in data_files:
                        fpath = os.path.join(DATA_DIR, fname)
                        if os.path.exists(fpath):
                            zf.write(fpath, fname)
                # إرسال الملف
                file_size = os.path.getsize(tmp_zip_path)
                size_mb = file_size / (1024 * 1024)
                with open(tmp_zip_path, 'rb') as zf:
                    bot.send_document(
                        cid, zf,
                        caption=f"📦 *نسخة الداتا*\n📊 الحجم: `{size_mb:.2f} MB`\n📅 `{datetime.now().strftime('%Y-%m-%d %H:%M')}`",
                        parse_mode='Markdown'
                    )
                # تنظيف
                try: os.unlink(tmp_zip_path)
                except: pass
                bot.answer_callback_query(call.id, "✅ تم إرسال الداتا")
            except Exception as e:
                bot.answer_callback_query(call.id, f"❌ خطأ: {e}")
                try: bot.send_message(cid, f"❌ خطأ في سحب الداتا: {e}")
                except: pass

        # ══════════════════════════════════════════════════════════════
        # 📤 رفع الداتا — Push Data (expect zip upload)
        # ══════════════════════════════════════════════════════════════
        elif data == "admin_data_push":
            if cid not in ADMIN_IDS:
                return
            bot.answer_callback_query(call.id)
            user_state[cid] = {"action": "admin_data_push_input"}
            kb_back = InlineKeyboardMarkup()
            kb_back.row(InlineKeyboardButton("🔙 إلغاء", callback_data="admin_panel"))
            bot.edit_message_text(
                "📤 *رفع الداتا*\n\nأرسل ملف zip أو ملف JSON واحد\nهيتم استبدال الملفات بالجديدة ورفعها على GitHub فوراً:\n\n"
                "📦 ملف zip: استلمته من سحب الداتا\n"
                "📄 ملف JSON: ملف واحد من القائمة",
                cid, call.message.message_id,
                parse_mode='Markdown', reply_markup=kb_back
            )

        # ══════════════════════════════════════════════════════════════
        # ☁️ مزامنة GitHub — Push all data to GitHub now
        # ══════════════════════════════════════════════════════════════
        elif data == "admin_gh_sync":
            if cid not in ADMIN_IDS:
                return
            bot.answer_callback_query(call.id, "☁️ جاري المزامنة...")
            try:
                from github_sync import push_to_github
                result = push_to_github(force=True)
                pushed = result.get('pushed', 0)
                skipped = result.get('skipped', 0)
                errors = result.get('errors', 0)
                msg_text = (
                    f"☁️ *مزامنة GitHub*\n\n"
                    f"✅ مرفوع: {pushed}\n"
                    f"⏭️ تم تخطيه: {skipped}\n"
                    f"❌ أخطاء: {errors}"
                )
                bot.send_message(cid, msg_text, parse_mode='Markdown', reply_markup=_admin_panel())
            except Exception as e:
                bot.send_message(cid, f"❌ فشل المزامنة: {e}", reply_markup=_admin_panel())

        # ══════════════════════════════════════════════════════════════
        # 📥 تحميل من GitHub — Pull all data from GitHub now
        # ══════════════════════════════════════════════════════════════
        elif data == "admin_gh_pull":
            if cid not in ADMIN_IDS:
                return
            bot.answer_callback_query(call.id, "📥 جاري التحميل من GitHub...")
            try:
                from github_sync import pull_from_github
                result = pull_from_github()
                pulled = result.get('pulled', 0)
                skipped = result.get('skipped', 0)
                errors = result.get('errors', 0)
                details = result.get('details', [])
                msg_text = (
                    f"📥 *تحميل من GitHub*\n\n"
                    f"✅ تم تحميل: {pulled}\n"
                    f"⏭️ تم تخطيه: {skipped}\n"
                    f"❌ أخطاء: {errors}"
                )
                if details:
                    msg_text += "\n\n📋 التفاصيل:"
                    for d in details[:10]:
                        msg_text += f"\n  • {d}"
                bot.send_message(cid, msg_text, parse_mode='Markdown', reply_markup=_admin_panel())
                # إعادة تحميل الحسابات بعد التحميل
                if pulled > 0:
                    load_accounts()
                    bd = load_bot_data()
                    saved_accounts = bd.get("accounts", [])
                    if saved_accounts:
                        bot.send_message(cid, f"🔄 تم إعادة تحميل {len(saved_accounts)} حساب")
            except Exception as e:
                bot.send_message(cid, f"❌ فشل التحميل: {e}", reply_markup=_admin_panel())

        # ══════════════════════════════════════════════════════════════
        # 🔑 إنشاء توكن — Create Fox Token
        # ══════════════════════════════════════════════════════════════
        elif data == "create_token":
            if is_banned(cid):
                bot.answer_callback_query(call.id, "🚫 أنت محظور")
                return
            try:
                from foxapp_api import encode_token as _enc_token, PUBLIC_URL as _pub_url
                fox_token = _enc_token(str(cid), _pub_url)
                # Invalidate old token: save new token as active and clear old sessions
                try:
                    from foxapp_api import (
                        _fox_token_hash, _set_active_fox_token,
                        _invalidate_all_sessions, _notify_telegram_token_revoked,
                    )
                    # Save the new token as the active one
                    _set_active_fox_token(str(cid), fox_token)
                    # Invalidate old sessions (force logout on old devices)
                    _invalidate_all_sessions(str(cid))
                    # Notify user that old token was revoked
                    _notify_telegram_token_revoked(str(cid))
                except Exception:
                    pass
                kb_tk = InlineKeyboardMarkup()
                kb_tk.row(InlineKeyboardButton(t("back_btn", user_id=cid), callback_data="go_start"))
                bot.send_message(
                    cid,
                    f"🔑 *توكن Fox Call الخاص بك:*\n\n`{fox_token}`\n\n"
                    f"📋 انسخ التوكن وافتح تطبيق Fox Call\n"
                    f"الصق التوكن في خانة الإدخال واضغط اتصال",
                    parse_mode='Markdown',
                    reply_markup=kb_tk
                )
                bot.answer_callback_query(call.id, "✅ تم إنشاء التوكن")
            except Exception as e:
                bot.answer_callback_query(call.id, f"❌ خطأ: {e}")
                try:
                    bot.send_message(cid, f"❌ فشل إنشاء التوكن: {e}")
                except:
                    pass

        # ══════════════════════════════════════════════════════════════
        # 📱 مستخدمي التطبيق — App Users
        # ══════════════════════════════════════════════════════════════
        elif data == "admin_app_users":
            if cid not in ADMIN_IDS:
                return
            bot.answer_callback_query(call.id, "⏳ جاري التحميل...")
            try:
                users_db = load_users_db()
                # Find users who logged in via the app (have last_ip or last_login)
                app_users = {}
                for uid, data_rec in users_db.items():
                    has_ip = bool(data_rec.get("last_ip"))
                    has_login = bool(data_rec.get("last_login"))
                    has_refresh = bool(data_rec.get("refresh_token_hash"))
                    if has_ip or has_login or has_refresh:
                        app_users[uid] = {
                            "ip": data_rec.get("last_ip", ""),
                            "last_login": data_rec.get("last_login", ""),
                            "last_seen": data_rec.get("last_seen", ""),
                            "balance": data_rec.get("balance", 0),
                            "first_name": data_rec.get("first_name", ""),
                            "username": data_rec.get("username", ""),
                        }
                
                if not app_users:
                    bot.edit_message_text(
                        "📱 لا يوجد مستخدمين مسجلين عبر التطبيق حتى الآن",
                        cid, call.message.message_id,
                        reply_markup=_admin_panel()
                    )
                    return
                
                lines = [f"📱 *مستخدمي التطبيق ({len(app_users)})*\n\n"]
                for uid, info in app_users.items():
                    name = info.get("first_name") or info.get("username") or uid
                    ip = info.get("ip", "—")
                    last = info.get("last_login") or info.get("last_seen") or "—"
                    bal = info.get("balance", 0)
                    lines.append(f"👤 `{uid}` | {name}")
                    lines.append(f"   💰 `{bal:.2f}$` | 🌐 `{ip}`")
                    lines.append(f"   🕐 {last}\n")
                
                text = "\n".join(lines)
                # Split if too long
                if len(text) > 4000:
                    text = text[:3990] + "\n..."
                
                kb_au = InlineKeyboardMarkup()
                kb_au.row(InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel"))
                try:
                    bot.edit_message_text(text, cid, call.message.message_id,
                                          parse_mode='Markdown', reply_markup=kb_au)
                except:
                    bot.send_message(cid, text, parse_mode='Markdown', reply_markup=kb_au)
            except Exception as e:
                bot.answer_callback_query(call.id, f"❌ خطأ: {e}")

        # ══════════════════════════════════════════════════════════════
        # ⚙️ زرار الإعدادات — DTMF Actions
        # ══════════════════════════════════════════════════════════════
        elif data == "check_sub":
            if check_force_sub(bot, cid):
                bot.answer_callback_query(call.id, "✅ تم التحقق! يمكنك الاستخدام الآن")
                # أرسل القائمة الرئيسية
                access, msg_text = check_user_access(cid)
                refs  = get_referral_count(cid)
                left  = get_daily_calls_left(cid)
                if cid in ADMIN_IDS:
                    extra = "👑 *أنت أدمن*"
                elif is_premium(cid):
                    extra = "⭐ *أنت مستخدم مميز*"
                elif refs < 3:
                    extra = f"👥 *إحالاتك: {refs}/3*\nأرسل /refer لرابطك"
                elif left > 0:
                    extra = "✅ *متاح (1/1 مكالمة يومية)*"
                else:
                    extra = "❌ *انتهى رصيدك اليومي — يتجدد غداً*"
                bot.send_message(cid,
                    f"🌟 *مرحباً بك في بوت المكالمات* 🌟\n\n{extra}\n\n*اختر من القائمة أدناه:*",
                    parse_mode='Markdown', reply_markup=_main_kb(is_admin=cid in ADMIN_IDS, user_id=cid))
            else:
                bot.answer_callback_query(call.id, "❌ لم تشترك في كل القنوات بعد")
            return

        elif data == "dtmf_settings":
            # كل المستخدمين يقدروا يعدلوا على إعداداتهم الخاصة
            settings = load_user_dtmf(cid)
            keys = ["0","1","2","3","4","5","6","7","8","9"]
            text_lines = ["⚙️ <b>إعدادات DTMF الخاصة بك</b>\n\nاضغط على أي رقم لتعديله:"]
            for k in keys:
                cfg = settings.get(k, {"label":f"زرار {k}","action":"notify","enabled":False})
                st  = "✅" if cfg.get("enabled") else "❌"
                text_lines.append(f"{st} <b>[{k}]</b> — {cfg.get('label','؟')} → <i>{cfg.get('action','notify')}</i>")
            try:
                bot.edit_message_text(
                    "\n".join(text_lines),
                    chat_id=cid, message_id=call.message.message_id,
                    parse_mode='HTML',
                    reply_markup=_dtmf_panel_kb(user_id=cid, is_admin=cid in ADMIN_IDS))
            except:
                bot.send_message(
                    cid, "\n".join(text_lines), parse_mode='HTML',
                    reply_markup=_dtmf_panel_kb(user_id=cid, is_admin=cid in ADMIN_IDS))

        elif data == "dtmf_reset":
            # إعادة تعيين إعدادات DTMF للمستخدم للافتراضي
            save_user_dtmf(cid, dict(_DEFAULT_DTMF_ACTIONS))
            settings = _DEFAULT_DTMF_ACTIONS
            keys = ["0","1","2","3","4","5","6","7","8","9"]
            text_lines = ["✅ <b>تم إعادة الإعدادات للافتراضي</b>\n\n⚙️ <b>إعدادات DTMF الخاصة بك</b>\n\nاضغط على أي رقم لتعديله:"]
            for k in keys:
                cfg = settings.get(k, {"label":f"زرار {k}","action":"notify","enabled":False})
                st  = "✅" if cfg.get("enabled") else "❌"
                text_lines.append(f"{st} <b>[{k}]</b> — {cfg.get('label','؟')} → <i>{cfg.get('action','notify')}</i>")
            try:
                bot.edit_message_text(
                    "\n".join(text_lines), chat_id=cid, message_id=call.message.message_id,
                    parse_mode='HTML',
                    reply_markup=_dtmf_panel_kb(user_id=cid, is_admin=cid in ADMIN_IDS))
            except:
                bot.send_message(cid, "\n".join(text_lines), parse_mode='HTML',
                    reply_markup=_dtmf_panel_kb(user_id=cid, is_admin=cid in ADMIN_IDS))

        elif data.startswith("dtmf_edit_"):
            digit    = data[len("dtmf_edit_"):]
            settings = load_user_dtmf(cid)
            cfg      = settings.get(digit, {"action":"notify","label":f"زرار {digit}","enabled":True})
            status   = "✅ مفعّل" if cfg.get("enabled", True) else "❌ معطّل"
            toggle_lbl = "❌ تعطيل" if cfg.get("enabled", True) else "✅ تفعيل"
            kb2 = InlineKeyboardMarkup()
            kb2.row(
                InlineKeyboardButton("🔁 إعادة صوت",  callback_data=f"dtmf_act_{digit}_replay"),
                InlineKeyboardButton("✅ موافق",        callback_data=f"dtmf_act_{digit}_confirm")
            )
            kb2.row(
                InlineKeyboardButton("❌ رافض",         callback_data=f"dtmf_act_{digit}_reject"),
                InlineKeyboardButton("📴 قطع مكالمة",  callback_data=f"dtmf_act_{digit}_hangup")
            )
            kb2.row(
                InlineKeyboardButton("📳 إشعار فقط",   callback_data=f"dtmf_act_{digit}_notify")
            )
            kb2.row(
                InlineKeyboardButton(toggle_lbl,        callback_data=f"dtmf_tog_{digit}"),
                InlineKeyboardButton("✏️ تغيير الاسم", callback_data=f"dtmf_ren_{digit}")
            )
            kb2.row(InlineKeyboardButton("🔙 رجوع", callback_data="dtmf_settings"))
            bot.edit_message_text(
                f"⚙️ إعداد الزرار <b>[{digit}]</b>\n"
                f"الاسم الحالي: <b>{cfg.get('label', digit)}</b>\n"
                f"الإجراء: <b>{cfg.get('action', 'notify')}</b>\n"
                f"الحالة: {status}\n\n"
                "اختر الإجراء الجديد:",
                chat_id=cid, message_id=call.message.message_id,
                parse_mode='HTML', reply_markup=kb2)

        elif data.startswith("dtmf_act_"):
            parts = data[len("dtmf_act_"):].split("_", 1)
            digit, action = parts[0], parts[1]
            ACTION_LABELS = {
                "replay":  "🔁 إعادة صوت",
                "confirm": "✅ موافق",
                "reject":  "❌ رافض",
                "hangup":  "📴 قطع مكالمة",
                "notify":  "📳 إشعار فقط",
            }
            settings = load_user_dtmf(cid)
            if digit not in settings:
                settings[digit] = {"enabled": True}
            settings[digit]["action"] = action
            settings[digit]["label"]  = ACTION_LABELS.get(action, action)
            save_user_dtmf(cid, settings)
            keys = ["0","1","2","3","4","5","6","7","8","9"]
            text_lines = [f"✅ تم تعيين <b>[{digit}]</b> → {ACTION_LABELS.get(action, action)}\n\n⚙️ <b>إعدادات DTMF الخاصة بك</b>\n\nاضغط على أي رقم لتعديله:"]
            for k in keys:
                s = load_user_dtmf(cid)
                c = s.get(k, {"label":f"زرار {k}","action":"notify","enabled":False})
                st = "✅" if c.get("enabled") else "❌"
                text_lines.append(f"{st} <b>[{k}]</b> — {c.get('label','؟')} → <i>{c.get('action','notify')}</i>")
            bot.edit_message_text("\n".join(text_lines), chat_id=cid,
                message_id=call.message.message_id,
                parse_mode='HTML',
                reply_markup=_dtmf_panel_kb(user_id=cid, is_admin=cid in ADMIN_IDS))

        elif data.startswith("dtmf_tog_"):
            digit    = data[len("dtmf_tog_"):]
            settings = load_user_dtmf(cid)
            if digit not in settings:
                settings[digit] = {"action":"notify","label":f"زرار {digit}","enabled":True}
            settings[digit]["enabled"] = not settings[digit].get("enabled", True)
            save_user_dtmf(cid, settings)
            state_txt = "✅ مفعّل" if settings[digit]["enabled"] else "❌ معطّل"
            keys = ["0","1","2","3","4","5","6","7","8","9"]
            text_lines = [f"الزرار <b>[{digit}]</b> الآن: {state_txt}\n\n⚙️ <b>إعدادات DTMF الخاصة بك</b>\n\nاضغط على أي رقم لتعديله:"]
            for k in keys:
                s = load_user_dtmf(cid)
                c = s.get(k, {"label":f"زرار {k}","action":"notify","enabled":False})
                st = "✅" if c.get("enabled") else "❌"
                text_lines.append(f"{st} <b>[{k}]</b> — {c.get('label','؟')} → <i>{c.get('action','notify')}</i>")
            bot.edit_message_text("\n".join(text_lines), chat_id=cid,
                message_id=call.message.message_id,
                parse_mode='HTML',
                reply_markup=_dtmf_panel_kb(user_id=cid, is_admin=cid in ADMIN_IDS))

        elif data.startswith("dtmf_ren_"):
            digit = data[len("dtmf_ren_"):]
            user_state[cid] = {"action": "dtmf_rename", "digit": digit}
            bot.send_message(cid, f"✏️ أرسل الاسم الجديد للزرار <b>[{digit}]</b>:", parse_mode='HTML')

    # ── Voice note handler ────────────────────────────────────────────────────
    @bot.message_handler(content_types=['voice', 'audio'])
    def on_voice(msg):
        cid = msg.chat.id
        from_id = msg.from_user.id

        if is_banned(from_id):
            bot.reply_to(msg, "🚫 أنت محظور من استخدام البوت")
            return

        # ── حالة اتصال بصوت من الجروب (/fd) ──
        # في الجروب: user_state محفوظ بـ from_id (مش cid)
        st = user_state.get(from_id, {}) or user_state.get(cid, {})
        if st.get("action") == "grp_voice_call":
            group_id = st.get("group_id")
            phone = st.get("phone")
            # لا نحتاج تحقق اشتراك إجباري في الجروب
            if msg.voice:
                file_id  = msg.voice.file_id
                duration = msg.voice.duration
                fname    = "voice.ogg"
            elif msg.audio:
                file_id  = msg.audio.file_id
                duration = msg.audio.duration or 0
                fname    = "audio.mp3"
            else:
                return
            if duration > 60:
                bot.reply_to(msg, f"⚠️ الصوت طويل جداً ({duration}s)\nالحد الأقصى 60 ثانية")
                return

            m = bot.reply_to(msg, "⏳ جاري تحميل الصوت والاتصال...")

            def _grp_voice_call():
                try:
                    import subprocess, tempfile
                    file_info = bot.get_file(file_id)
                    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
                    r = requests.get(url, timeout=30)
                    if r.status_code != 200:
                        try: bot.edit_message_text("❌ فشل تحميل الصوت", cid, m.message_id)
                        except: pass
                        return
                    with tempfile.TemporaryDirectory() as tmp:
                        in_path  = os.path.join(tmp, fname)
                        out_path = os.path.join(tmp, "audio.raw")
                        with open(in_path, 'wb') as f:
                            f.write(r.content)
                        ret = subprocess.run([
                            "ffmpeg", "-y", "-i", in_path,
                            "-ar", "8000", "-ac", "1", "-sample_fmt", "s16",
                            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                            "-f", "s16le", out_path
                        ], capture_output=True, timeout=30)
                        if ret.returncode != 0:
                            ret = subprocess.run([
                                "ffmpeg", "-y", "-i", in_path,
                                "-ar", "8000", "-ac", "1", "-sample_fmt", "s16",
                                "-af", "volume=4.0", "-f", "s16le", out_path
                            ], capture_output=True, timeout=30)
                        if ret.returncode != 0:
                            try: bot.edit_message_text("❌ فشل تحويل الصوت", cid, m.message_id)
                            except: pass
                            return
                        with open(out_path, 'rb') as f:
                            pcm_bytes = f.read()
                        if len(pcm_bytes) == 0:
                            try: bot.edit_message_text("❌ ملف الصوت فاضي", cid, m.message_id)
                            except: pass
                            return

                    # حفظ الصوت وبدء الاتصال
                    voice_store[from_id] = pcm_bytes
                    user_state.pop(from_id, None)
                    # 🔀 تحقق من الاتصال المزدوج
                    v_display = phone
                    v_actual = phone
                    v_dc = get_double_call_target(phone)
                    if v_dc:
                        v_actual = v_dc
                        print(f"[grp-voice] 🔀 تحويل: {phone} → {v_dc}")
                    result = make_call(v_actual, dur=60, user_id=from_id, display_phone=v_display)
                    try:
                        if result and result[0]:
                            bot.edit_message_text(f"✅ تم عملية الاتصال بـ `{v_display}`", cid, m.message_id, parse_mode='Markdown')
                        else:
                            bot.edit_message_text(f"❌ رفض عملية الاتصال بـ `{v_display}`", cid, m.message_id, parse_mode='Markdown')
                    except: pass
                except Exception:
                    try: bot.edit_message_text(f"❌ رفض عملية الاتصال بـ `{phone}`", cid, m.message_id, parse_mode='Markdown')
                    except: pass

            threading.Thread(target=_grp_voice_call, daemon=True).start()
            return

        # تحقق من الاشتراك
        if cid not in ADMIN_IDS and not check_force_sub(bot, cid):
            send_force_sub_msg(bot, cid)
            return
        
        if msg.voice:
            file_id  = msg.voice.file_id
            duration = msg.voice.duration
            fname    = "voice.ogg"
        elif msg.audio:
            file_id  = msg.audio.file_id
            duration = msg.audio.duration or 0
            fname    = "audio.mp3"
        else:
            return
        
        MAX_VOICE_SEC = 60
        if duration > MAX_VOICE_SEC:
            bot.reply_to(msg, f"⚠️ الصوت طويل جداً ({duration}s)\nالحد الأقصى {MAX_VOICE_SEC} ثانية")
            return
        
        m = bot.reply_to(msg, "⏳ جاري تحميل الصوت...")
        
        def _convert():
            try:
                import subprocess, tempfile
                
                file_info = bot.get_file(file_id)
                url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
                r = requests.get(url, timeout=30)
                if r.status_code != 200:
                    bot.edit_message_text("❌ فشل تحميل الصوت", cid, m.message_id)
                    return
                
                with tempfile.TemporaryDirectory() as tmp:
                    in_path  = os.path.join(tmp, fname)
                    out_path = os.path.join(tmp, "audio.raw")  # raw PCM بدون header

                    with open(in_path, 'wb') as f:
                        f.write(r.content)

                    # تحويل دقيق: mono 8000Hz 16-bit signed little-endian
                    # volume=2 فقط — بدون dynaudnorm عشان ما يغيرش التوقيت
                    ret = subprocess.run([
                        "ffmpeg", "-y", "-i", in_path,
                        "-ar", "8000",
                        "-ac", "1",
                        "-sample_fmt", "s16",
                        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                        "-f", "s16le",
                        out_path
                    ], capture_output=True, timeout=30)

                    # لو loudnorm فشل جرب volume بسيط
                    if ret.returncode != 0:
                        ret = subprocess.run([
                            "ffmpeg", "-y", "-i", in_path,
                            "-ar", "8000", "-ac", "1",
                            "-sample_fmt", "s16",
                            "-af", "volume=4.0",
                            "-f", "s16le", out_path
                        ], capture_output=True, timeout=30)

                    if ret.returncode != 0:
                        bot.edit_message_text(
                            f"❌ فشل تحويل الصوت",
                            cid, m.message_id)
                        return

                    with open(out_path, 'rb') as f:
                        pcm_bytes = f.read()

                    # تحقق إن الحجم صح: 8000 sample/s * 2 byte = 16000 byte/s
                    expected = duration * 16000
                    actual   = len(pcm_bytes)
                    if actual == 0:
                        bot.edit_message_text("❌ ملف الصوت فاضي", cid, m.message_id)
                        return
                
                voice_store[cid] = pcm_bytes
                dur_actual = len(pcm_bytes) // (8000 * 2)
                bot.edit_message_text(
                    f"✅ تم تحميل الصوت!\n⏱️ المدة: {dur_actual} ثانية\n\n📞 أرسل رقم الهاتف:",
                    cid, m.message_id)
                # ← بعد تحميل الصوت مباشرة، ننتقل لمرحلة الاتصال
                user_state[cid] = {"action": "call", "dur": 60}
                
            except FileNotFoundError:
                bot.edit_message_text("❌ ffmpeg غير مثبت", cid, m.message_id)
            except Exception as e:
                bot.edit_message_text(f"❌ خطأ: {e}", cid, m.message_id)
        
        threading.Thread(target=_convert, daemon=True).start()

    # ── Document handler (Dan.json) ──────────────────────────────────────────
    @bot.message_handler(content_types=['document'])
    def on_document(msg):
        cid = msg.chat.id

        # التحقق من الحظر والاشتراك
        if is_banned(cid):
            bot.reply_to(msg, "🚫 أنت محظور")
            return
        if cid not in ADMIN_IDS and not check_force_sub(bot, cid):
            send_force_sub_msg(bot, cid)
            return

        doc = msg.document
        fname = doc.file_name or ""

        # ═══ رفع الداتا (zip أو json) — Data Push ═══
        state = user_state.get(cid, {})
        if state.get("action") == "admin_data_push_input" and cid in ADMIN_IDS:
            user_state.pop(cid, None)
            # قائمة الملفات المسموحة (موافقة لـ github_sync.py SYNC_FILES)
            allowed_data_files = [
                "bot_data.json",
                "telicall_accounts.json",
                "users_db.json",
                "premium_db.json",
                "banned_db.json",
                "tokens_cache.json",
                "call_logs.json",
                "security_strikes.json",
                "monthly_subs.json",
                "dtmf_settings.json",
                "sub_bots.json",
                "failed_accounts.json",
                "double_call_map.json",
                "authorized_groups.json",
                "owner_earnings.json",
            ]
            # ─── رفع ملف JSON واحد ───
            if fname.lower().endswith('.json'):
                m = bot.reply_to(msg, "⏳ جاري رفع ملف JSON...")
                try:
                    file_info = bot.get_file(doc.file_id)
                    file_bytes = bot.download_file(file_info.file_path)
                    # التحقق من إنه JSON صالح
                    try:
                        json.loads(file_bytes.decode('utf-8'))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        bot.edit_message_text("❌ الملف مش JSON صالح", cid, m.message_id)
                        return
                    # التحقق من الاسم
                    base_name = os.path.basename(fname)
                    if base_name not in allowed_data_files:
                        bot.edit_message_text(
                            f"❌ الملف `{base_name}` مش في القائمة المسموحة\n"
                            f"الملفات المسموحة: {', '.join(allowed_data_files)}",
                            cid, m.message_id, parse_mode='Markdown')
                        return
                    # حفظ الملف
                    dest = os.path.join(DATA_DIR, base_name)
                    with open(dest, 'wb') as f:
                        f.write(file_bytes)
                    # رفع على GitHub فوراً
                    gh_msg = ""
                    try:
                        from github_sync import push_to_github
                        gh_result = push_to_github(force=True)
                        gh_pushed = gh_result.get('pushed', 0)
                        gh_msg = f"\n☁️ GitHub: {gh_pushed} ملف تم رفعه"
                    except Exception as _ghe:
                        gh_msg = f"\n⚠️ GitHub sync فشل: {_ghe}"
                    bot.edit_message_text(
                        f"✅ تم رفع الملف بنجاح\n📄 {base_name}{gh_msg}",
                        cid, m.message_id)
                except Exception as e:
                    try: bot.edit_message_text(f"❌ خطأ في رفع الملف: {e}", cid, m.message_id)
                    except: bot.reply_to(msg, f"❌ خطأ في رفع الملف: {e}")
                return
            # ─── رفع ملف ZIP ───
            if not fname.lower().endswith('.zip'):
                bot.reply_to(msg, "❌ لازم تبعت ملف zip أو ملف json فقط", reply_markup=_admin_panel())
                return
            m = bot.reply_to(msg, "⏳ جاري رفع الداتا...")
            try:
                import zipfile
                import tempfile
                # تحميل الملف من Telegram
                file_info = bot.get_file(doc.file_id)
                file_bytes = bot.download_file(file_info.file_path)

                # التحقق من حجم الملف
                if len(file_bytes) < 4:
                    bot.edit_message_text("❌ الملف فارغ أو تالف (حجمه أقل من 4 بايت)", cid, m.message_id)
                    return

                # حفظ الملف مؤقتاً
                tmp_zip = tempfile.NamedTemporaryFile(mode='wb', suffix='.zip', delete=False)
                tmp_zip.write(file_bytes)
                tmp_zip.flush()
                tmp_zip.close()

                # التحقق من إنه zip صالح
                if not zipfile.is_zipfile(tmp_zip.name):
                    # محاولة فك تشفير base64 أو بيانات ثنائية تالفة
                    file_size_kb = len(file_bytes) / 1024
                    first_bytes = file_bytes[:20].hex() if file_bytes else 'empty'
                    bot.edit_message_text(
                        f"❌ الملف مش zip صالح\n"
                        f"📊 الحجم: {file_size_kb:.1f} KB\n"
                        f"🔢 أول 20 بايت: {first_bytes}\n"
                        f"💡 جرب تحويل الملف لـ zip ببرنامج ضغط عادي (مش RAR أو 7z)",
                        cid, m.message_id)
                    try: os.unlink(tmp_zip.name)
                    except: pass
                    return

                # فك الضغط واستبدال الملفات
                replaced = []
                errors = []
                with zipfile.ZipFile(tmp_zip.name, 'r') as zf:
                    for fname_in_zip in zf.namelist():
                        # تجاهل المجلدات والملفات المخفية
                        if fname_in_zip.endswith('/') or fname_in_zip.startswith('.'):
                            continue
                        # استخراج اسم الملف فقط (بدون مسار)
                        base_name = os.path.basename(fname_in_zip)
                        if not base_name:
                            continue
                        if base_name in allowed_data_files:
                            try:
                                content = zf.read(fname_in_zip)
                                # التحقق من إنه JSON صالح
                                try:
                                    json.loads(content.decode('utf-8'))
                                except (json.JSONDecodeError, UnicodeDecodeError):
                                    errors.append(f"{base_name}: مش JSON صالح")
                                    continue
                                dest = os.path.join(DATA_DIR, base_name)
                                with open(dest, 'wb') as f:
                                    f.write(content)
                                replaced.append(base_name)
                            except Exception as e:
                                errors.append(f"{base_name}: {e}")
                # تنظيف
                try: os.unlink(tmp_zip.name)
                except: pass
                # رفع على GitHub فوراً
                gh_msg = ""
                if replaced:
                    try:
                        from github_sync import push_to_github
                        gh_result = push_to_github(force=True)
                        gh_pushed = gh_result.get('pushed', 0)
                        gh_msg = f"\n☁️ GitHub: {gh_pushed} ملف تم رفعه"
                    except Exception as _ghe:
                        gh_msg = f"\n⚠️ GitHub sync فشل: {_ghe}"
                # نتيجة
                if replaced:
                    result_lines = [f"✅ تم رفع الداتا بنجاح", f"", f"📁 الملفات المستبدلة ({len(replaced)}):"]
                    for fn in replaced:
                        result_lines.append(f"  ✅ {fn}")
                    if errors:
                        result_lines.append(f"\n❌ أخطاء ({len(errors)}):")
                        for err in errors:
                            result_lines.append(f"  ❌ {err}")
                    result_lines.append(gh_msg)
                    try:
                        bot.edit_message_text("\n".join(result_lines), cid, m.message_id)
                    except Exception:
                        # fallback لو في أحرف خاصة
                        bot.send_message(cid, "✅ تم رفع الداتا بنجاح", reply_markup=_admin_panel())
                else:
                    msg_text = "❌ لم يتم العثور على ملفات صالحة في الـ zip"
                    if errors:
                        msg_text += "\n" + "\n".join([f"❌ {e}" for e in errors])
                    bot.edit_message_text(msg_text, cid, m.message_id)
            except Exception as e:
                try: bot.edit_message_text(f"❌ خطأ في رفع الداتا: {e}", cid, m.message_id)
                except: bot.reply_to(msg, "❌ خطأ في رفع الداتا")
            return

        # نتحقق إن الملف اسمه Dan.json
        if fname.lower() != "dan.json":
            bot.reply_to(msg, f"⚠️ الملف المتوقع اسمه `Dan.json`\nاللي بعته: `{fname}`", parse_mode='Markdown')
            return

        m = bot.reply_to(msg, "⏳ جاري معالجة الملف...")

        try:
            file_info  = bot.get_file(doc.file_id)
            url        = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
            r          = requests.get(url, timeout=30)
            if r.status_code != 200:
                bot.edit_message_text("❌ فشل تحميل الملف", cid, m.message_id)
                return

            result = process_dan_file(r.content)

            if not result["ok"]:
                bot.edit_message_text(
                    f"❌ فشل فك تشفير الملف\nالخطأ: `{result['error']}`",
                    cid, m.message_id, parse_mode='Markdown')
                return

            total       = result["total"]
            already     = result["already_seen"]
            new_acc     = result["new"]
            earned      = result["calls_earned"]
            leftover    = result["leftover"]

            if earned > 0:
                add_dan_calls(cid, earned)

            if cid in ADMIN_IDS:
                # الأدمن يشوف كل التفاصيل
                if new_acc == 0:
                    reply = (
                        f"📂 *تم فحص الملف*\n\n"
                        f"📊 الإجمالي: `{total}` | مسجّلة: `{already}` | جديدة: `0`\n"
                        f"⚠️ لا يوجد حسابات جديدة"
                    )
                else:
                    reply = (
                        f"✅ *تم معالجة الملف*\n\n"
                        f"📊 الإجمالي: `{total}` | جديدة: `{new_acc}`\n"
                        f"📞 فرص مكتسبة: `{earned}`"
                    )
                    if leftover > 0:
                        reply += f" | متبقي: `{leftover}` لاكتمال الفرصة"
                    if earned > 0:
                        reply += f"\n🎉 أُضيفت {earned} فرصة للمستخدم"
            else:
                # المستخدم العادي — سطر واحد فقط
                if new_acc == 0:
                    reply = "⚠️ لا يوجد حسابات جديدة في هذا الملف"
                elif earned > 0:
                    reply = f"🎉 يمكنك الآن إجراء `{earned}` مكالمة إضافية!"
                else:
                    reply = f"✅ تم — متبقي `{leftover}` حساب لاكتمال الفرصة القادمة"

            bot.edit_message_text(reply, cid, m.message_id, parse_mode='Markdown')

        except Exception as e:
            bot.edit_message_text(f"❌ خطأ غير متوقع: {e}", cid, m.message_id)

    # ── Managed Bot Created (إنشاء سريع) ─────────────────────────────────────
    @bot.message_handler(content_types=['managed_bot_created'])
    def on_managed_bot_created(msg):
        _handle_managed_bot_created(msg)

    @bot.message_handler(func=lambda m: hasattr(m, 'managed_bot_created') and m.managed_bot_created is not None,
                         content_types=['text', 'unknown'])
    def on_managed_bot_created_fallback(msg):
        _handle_managed_bot_created(msg)

    def _handle_managed_bot_created(msg):
        cid = msg.chat.id
        try:
            managed_info = msg.managed_bot_created
            # البنية: managed_bot_created.bot (User object)
            managed_bot  = managed_info.bot
            managed_id   = managed_bot.id
            managed_user = getattr(managed_bot, 'username', None) or f"bot_{managed_id}"
        except Exception as e:
            bot.send_message(cid, f"❌ فشل قراءة بيانات البوت الجديد: {e}")
            return

        bot.send_message(cid, f"⏳ جاري تجهيز بوتك @{managed_user}...")

        # جلب التوكن برمجياً
        managed_token = get_managed_bot_token(managed_id)
        if not managed_token:
            bot.send_message(
                cid,
                "❌ *فشل الحصول على التوكن تلقائياً*\n\n"
                "يمكنك ربط البوت يدوياً:\n"
                "1️⃣ افتح @BotFather\n"
                "2️⃣ ابحث عن بوتك الجديد\n"
                "3️⃣ احصل على التوكن وأرسله هنا عبر زر ➕",
                parse_mode='Markdown'
            )
            return

        # تحقق إذا مسجّل مسبقاً
        existing = load_sub_bots()
        if any(b["token"] == managed_token or b.get("username","").lower() == managed_user.lower() for b in existing):
            bot.send_message(cid, f"⚠️ البوت @{managed_user} مسجّل مسبقاً!")
            return

        # تحقق من الحد الأقصى (3 بوتات)
        if user_reached_sub_bot_limit(cid):
            bot.send_message(
                cid,
                f"❌ *وصلت للحد الأقصى!*\n\n"
                f"كل مستخدم يمكنه إنشاء {MAX_SUB_BOTS_PER_USER} بوتات فرعية فقط.\n\n"
                f"احذف بوتاً موجوداً من *🤖 بوتي الخاص* لإنشاء بوت جديد.",
                parse_mode='Markdown'
            )
            return

        # تسجيل وتشغيل
        register_sub_bot_to_file(managed_token, cid, managed_user)
        ok = launch_sub_bot(managed_token, cid)

        if ok:
            import html as _html_mgd
            bot.send_message(
                cid,
                f"✅ <b>تم تشغيل بوتك بنجاح!</b>\n\n"
                f"🤖 البوت: @{_html_mgd.escape(managed_user)}\n"
                f"🔗 https://t.me/{_html_mgd.escape(managed_user)}\n\n"
                f"يمكن لمستخدميه استخدام نفس ميزات هذا البوت!",
                parse_mode='HTML'
            )
            for admin_id in ADMIN_IDS:
                try:
                    owner_display = f"@{msg.from_user.username}" if msg.from_user.username else str(cid)
                    bot.send_message(
                        admin_id,
                        f"🆕 <b>بوت سريع جديد تم إنشاؤه</b>\n\n"
                        f"👤 المالك: {_html_mgd.escape(owner_display)} (<code>{cid}</code>)\n"
                        f"🤖 البوت: @{_html_mgd.escape(managed_user)}\n"
                        f"🔗 https://t.me/{_html_mgd.escape(managed_user)}",
                        parse_mode='HTML'
                    )
                except: pass
        else:
            bot.send_message(cid, "❌ فشل تشغيل البوت — تأكد من أن التوكن صحيح وغير مستخدم في مكان آخر")
            delete_sub_bot(managed_token)

    # ── Text messages ────────────────────────────────────────────────────────
    @bot.message_handler(func=lambda m: True, content_types=['text'])
    def on_text(msg):
        cid  = msg.chat.id
        text = msg.text.strip()

        # ── لو في جروب: مفيش أي رد على رسايل عادية نهائياً ──
        if getattr(msg.chat, 'type', 'private') in ("group", "supergroup"):
            return

        # تحقق من الحظر
        if is_banned(cid):
            bot.reply_to(msg, "🚫 أنت محظور من استخدام البوت")
            return

        # ── معالجة الكابتشا للمستخدمين الجدد ──
        if user_state.get(cid, {}).get("action") == "captcha":
            pending = _captcha_pending.get(cid)
            if not pending:
                user_state.pop(cid, None)
                bot.send_message(cid, "⚠️ حدث خطأ، أرسل /start مرة أخرى")
                return
            try:
                user_ans = int(text)
            except (ValueError, TypeError):
                bot.reply_to(msg, "❌ أرسل رقماً صحيحاً فقط\nمثال: 8")
                return
            if user_ans == pending["answer"]:
                # ✅ إجابة صحيحة
                user_state.pop(cid, None)
                _captcha_pending.pop(cid, None)
                log_user_entry(cid, pending["username"], pending["first_name"],
                               referred_by=pending.get("referred_by"))
                bot.send_message(cid, "✅ تم التحقق بنجاح! مرحباً 🎉")
                if not require_sub(bot, cid):
                    return
                bonus_given = try_give_daily_bonus(cid)
                # بناء رسالة الترحيب
                if cid in ADMIN_IDS:
                    extra2 = "👑 *أنت أدمن*"
                elif is_premium(cid):
                    extra2 = "⭐ *أنت مستخدم مميز*"
                else:
                    refs2   = get_referral_count(cid)
                    bal2    = get_user_balance(cid)
                    streak2 = get_user_streak(cid)
                    bn2     = f"\n🎁 *مكافأة يومية `{bonus_given:.2f}$`!*" if bonus_given else ""
                    sf2     = "🔥" * min(streak2, 5)
                    if streak2 < 3:
                        sl2 = f"🔥 *حلقاتك:* {sf2} {streak2}/3 _(تحتاج {3-streak2} يوم)_\n"
                    else:
                        db2 = get_daily_bonus_by_refs(refs2)
                        sl2 = f"🔥 *حلقاتك:* {sf2} {streak2} يوم ✅ _(مكافأة {db2:.2f}$)_\n"
                    extra2 = f"{sl2}💰 *رصيدك: `{bal2:.2f}$`*\n👥 *إحالاتك: {refs2}*{bn2}"
                welcome2 = f"🌟 *مرحباً بك في بوت المكالمات* 🌟\n\n{extra2}\n\n*اختر من القائمة أدناه:*"
                bot.send_message(cid, welcome2, parse_mode='Markdown',
                                 reply_markup=_main_kb(is_admin=cid in ADMIN_IDS, user_id=cid))
            else:
                # ❌ إجابة خاطئة
                pending["tries"] = pending.get("tries", 0) + 1
                if pending["tries"] >= 3:
                    user_state.pop(cid, None)
                    _captcha_pending.pop(cid, None)
                    bot.send_message(cid, "❌ إجابات خاطئة متكررة. أرسل /start للمحاولة مجدداً")
                else:
                    q, ans = generate_captcha()
                    pending["answer"] = ans
                    remaining = 3 - pending["tries"]
                    bot.reply_to(
                        msg,
                        f"❌ إجابة خاطئة! تبقى لك {remaining} محاولة\n\n"
                        f"🔢 *سؤال جديد:* `{q} = ?`\n\n"
                        f"أرسل الإجابة كرقم فقط",
                        parse_mode='Markdown'
                    )
            return

        # تحقق من الاشتراك قبل أي حاجة (عدا الأدمن)
        if cid not in ADMIN_IDS and not check_force_sub(bot, cid):
            send_force_sub_msg(bot, cid)
            return

        # مستخدم ليس في user_state
        if cid not in user_state:
            bot.send_message(cid, "📞 أرسل /start للقائمة")
            return

        state  = user_state[cid]  # لا نعمل pop بعد هنا إلا لما نتأكد
        action = state.get("action", "")

        # ── أوامر الأدمن ──────────────────────────────────────────
        if action == "admin_add_premium":
            user_state.pop(cid)
            try:
                add_premium(int(text), cid, premium_type="limited", calls_limit=10)
                bot.reply_to(msg, f"✅ تمت إضافة `{text}` كمميز محدود (10 مكالمات)", parse_mode='Markdown')
            except: bot.reply_to(msg, "❌ معرف غير صحيح")
            return

        if action == "admin_add_premium_limited":
            user_state.pop(cid)
            try:
                add_premium(int(text), cid, premium_type="limited", calls_limit=10)
                bot.reply_to(msg, f"⭐✅ تمت إضافة `{text}` كمميز محدود (10 مكالمات)", parse_mode='Markdown')
            except: bot.reply_to(msg, "❌ معرف غير صحيح")
            return

        if action == "admin_add_premium_unlimited":
            user_state.pop(cid)
            try:
                add_premium(int(text), cid, premium_type="unlimited")
                bot.reply_to(msg, f"♾️✅ تمت إضافة `{text}` كمميز غير محدود (∞ مكالمات)", parse_mode='Markdown')
            except: bot.reply_to(msg, "❌ معرف غير صحيح")
            return

        if action == "admin_renew_premium":
            user_state.pop(cid)
            try:
                uid = int(text)
                premium_db = load_premium_db()
                uid_str = str(uid)
                if uid_str in premium_db:
                    premium_db[uid_str]["calls_used"] = 0
                    premium_db[uid_str]["calls_limit"] = 10
                    save_premium_db(premium_db)
                    bot.reply_to(msg, f"🔄✅ تم تجديد مكالمات `{uid}` (10 مكالمات جديدة)", parse_mode='Markdown')
                else:
                    bot.reply_to(msg, f"❌ `{uid}` ليس مميزاً", parse_mode='Markdown')
            except: bot.reply_to(msg, "❌ معرف غير صحيح")
            return

        if action == "admin_remove_premium":
            user_state.pop(cid)
            try:
                uid = int(text)
                if remove_premium(uid): bot.reply_to(msg, f"✅ تمت إزالة `{uid}`", parse_mode='Markdown')
                else: bot.reply_to(msg, f"❌ `{uid}` ليس مميزاً", parse_mode='Markdown')
            except: bot.reply_to(msg, "❌ معرف غير صحيح")
            return

        if action == "admin_ban":
            user_state.pop(cid)
            parts = text.split(maxsplit=1)
            try:
                uid    = int(parts[0])
                reason = parts[1] if len(parts) > 1 else ""
                add_banned(uid, cid, reason)
                bot.reply_to(msg, f"✅ تم حظر `{uid}`\nالسبب: {reason or 'لا يوجد'}", parse_mode='Markdown')
            except: bot.reply_to(msg, "❌ معرف غير صحيح")
            return

        if action == "admin_unban":
            user_state.pop(cid)
            try:
                uid = int(text)
                if remove_banned(uid): bot.reply_to(msg, f"✅ تم فك حظر `{uid}`", parse_mode='Markdown')
                else: bot.reply_to(msg, f"❌ `{uid}` ليس محظوراً", parse_mode='Markdown')
            except: bot.reply_to(msg, "❌ معرف غير صحيح")
            return

        # ── أدمن: منح اشتراك تطبيق ──────────────────────────────────
        if action == "admin_grant_app_sub":
            user_state.pop(cid, None)
            parts_app = text.strip().split()
            if len(parts_app) != 2:
                bot.reply_to(msg, "❌ الصيغة: `معرف_المستخدم اسم_الخطة`\nمثال: `123456789 app_pro`", parse_mode='Markdown')
                return
            try:
                target_id = int(parts_app[0])
                plan_key_app = parts_app[1].lower()
            except:
                bot.reply_to(msg, "❌ معرف غير صحيح")
                return
            if plan_key_app not in APP_SUBSCRIPTION_PLANS:
                plans_list = ", ".join(APP_SUBSCRIPTION_PLANS.keys())
                bot.reply_to(msg, f"❌ خطة غير موجودة\nالخطط المتاحة: `{plans_list}`", parse_mode='Markdown')
                return
            add_app_sub(target_id, plan_key_app, granted_by=cid)
            plan_app = APP_SUBSCRIPTION_PLANS[plan_key_app]
            calls_app = "∞" if plan_app["calls"] == 999999 else str(plan_app["calls"])
            bot.reply_to(msg,
                f"✅ *تم منح اشتراك تطبيق*\n\n"
                f"المستخدم: `{target_id}`\n"
                f"الخطة: {plan_app['emoji']} *{plan_app['name']}* ({calls_app} مكالمة)\n"
                f"ينتهي بعد 30 يوم",
                parse_mode='Markdown')
            try:
                bot.send_message(target_id,
                    f"🎁 *تم تفعيل اشتراك التطبيق!*\n\n"
                    f"{plan_app['emoji']} *{plan_app['name']}* — {calls_app} مكالمة\n"
                    f"📆 صالح لمدة 30 يوم\n\n"
                    f"استمتع بمكالماتك! 🎉",
                    parse_mode='Markdown')
            except: pass
            return

        # ── أدمن: إلغاء اشتراك تطبيق ──────────────────────────────────
        if action == "admin_cancel_app_sub":
            user_state.pop(cid, None)
            try:
                target_id = int(text.strip())
                if remove_app_sub(target_id):
                    bot.reply_to(msg, f"✅ تم إلغاء اشتراك التطبيق لـ `{target_id}`", parse_mode='Markdown')
                else:
                    bot.reply_to(msg, f"❌ `{target_id}` ليس مشتركاً في التطبيق", parse_mode='Markdown')
            except:
                bot.reply_to(msg, "❌ معرف غير صحيح")
            return

        # ── تتبع شخص — استقبال user_id من الأدمن ────────────────────────
        if action == "admin_track_input":
            user_state.pop(cid)
            uid = text.strip()
            if not uid:
                bot.reply_to(msg, "❌ أرسل معرف صحيح", reply_markup=_admin_panel())
                return
            bot.reply_to(msg, "⏳ جاري التتبع...")
            try:
                base = _api_base()
                headers = _api_headers()
                r = requests.get(f"{base}/api/admin/track/{uid}", headers=headers, timeout=30)
                if r.status_code != 200:
                    err_msg = ""
                    try:
                        err_msg = r.json().get("error", "")
                    except:
                        err_msg = f"HTTP {r.status_code}"
                    bot.reply_to(msg, f"❌ فشل التتبع: {err_msg}", reply_markup=_admin_panel())
                    return
                d = r.json()
                # بناء رسالة التتبع
                lines = [
                    f"🔍 *تتبع المستخدم* `{d.get('user_id', uid)}`\n",
                    f"👤 الاسم: {_escape_md(d.get('full_name') or d.get('first_name') or 'غير معروف')}",
                    f"🆔 اليوزر: @{_escape_md(d.get('username') or 'لا يوجد')}",
                    f"🌐 IP: `{_escape_md(d.get('ip_address') or 'غير متوفر')}`",
                    f"📅 تاريخ التسجيل: `{_escape_md(d.get('registration_date') or 'غير معروف')}`",
                    f"👀 آخر ظهور: `{_escape_md(d.get('last_seen') or 'غير معروف')}`",
                    f"🔑 آخر دخول: `{_escape_md(d.get('last_login') or 'غير معروف')}`",
                    f"💰 الرصيد: `{d.get('balance', 0):.2f}$`",
                    f"📞 مكالمات التطبيق: `{d.get('call_stats', {}).get('total_calls', 0)}`",
                    f"📱 مكالمات Dan: `{d.get('dan_calls', 0)}`",
                    f"👥 الإحالات: `{d.get('referrals', 0)}`",
                    f"🔥 Streak: `{d.get('streak', 0)}`",
                    f"🚫 محظور: {'نعم ❌' if d.get('is_banned') else 'لا ✅'}",
                ]
                # آخر مكالمة
                last_call = d.get("last_call") or (d.get("call_history") or [{}])[0] if d.get("call_history") else {}
                if last_call:
                    lines.append(f"\n📞 *آخر مكالمة:*")
                    lines.append(f"   إلى: `{_escape_md(last_call.get('to', ''))}`")
                    lines.append(f"   من: `{_escape_md(last_call.get('from', ''))}`")
                    lines.append(f"   المدة: `{last_call.get('duration', 0)}s`")
                    lines.append(f"   الحالة: `{_escape_md(last_call.get('status', ''))}`")
                    lines.append(f"   الوقت: `{_escape_md(last_call.get('start_time') or last_call.get('timestamp', ''))}`")

                kb_detail = InlineKeyboardMarkup()
                # صف 1: حظر/فك حظر
                if d.get('is_banned'):
                    kb_detail.row(
                        InlineKeyboardButton("✅ فك الحظر", callback_data=f"track_unban_{uid}")
                    )
                else:
                    kb_detail.row(
                        InlineKeyboardButton("🚫 حظر الشخص", callback_data=f"track_ban_{uid}")
                    )
                # صف 2: تعديل رصيد + تعديل إحالات
                kb_detail.row(
                    InlineKeyboardButton("💰 تعديل الرصيد", callback_data=f"track_balance_{uid}"),
                    InlineKeyboardButton("👥 تعديل الإحالات", callback_data=f"track_referrals_{uid}")
                )
                kb_detail.row(InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel"))
                bot.reply_to(msg, "\n".join(lines), parse_mode='Markdown', reply_markup=kb_detail)
            except Exception as e:
                bot.reply_to(msg, f"❌ خطأ في التتبع: {e}", reply_markup=_admin_panel())
            return

        # ── تعديل رصيد من التتبع — استقبال المبلغ ──────────────
        if action == "track_balance_input":
            state_info = user_state.pop(cid)
            uid = state_info.get("uid", "")
            try:
                amount = float(text.strip())
            except:
                bot.reply_to(msg, "❌ أرسل مبلغ صحيح، مثال: `5.00` أو `-2.50`", parse_mode='Markdown')
                return
            # تعديل الرصيد مباشرة في قاعدة البيانات (أسهل وأضمن من API)
            try:
                new_balance = add_balance(int(uid), amount)
                bot.reply_to(msg, f"✅ تم تعديل رصيد `{uid}`\n💰 الرصيد الجديد: `{new_balance:.2f}$`", parse_mode='Markdown')
            except Exception as e:
                bot.reply_to(msg, f"❌ خطأ: {e}")
            return

        # ── تعديل إحالات من التتبع — استقبال العدد ──────────────
        if action == "track_referrals_input":
            state_info = user_state.pop(cid)
            uid = state_info.get("uid", "")
            try:
                count = int(text.strip())
                if count < 0: raise ValueError
            except:
                bot.reply_to(msg, "❌ أرسل رقم صحيح، مثال: `5` أو `10`", parse_mode='Markdown')
                return
            # تعديل الإحالات مباشرة في users_db
            try:
                users_db = load_users_db()
                uid_str = str(uid)
                if uid_str not in users_db:
                    users_db[uid_str] = {}
                users_db[uid_str]["referrals"] = count
                save_users_db(users_db)
                bot.reply_to(msg, f"✅ تم تعديل إحالات `{uid}` إلى `{count}`", parse_mode='Markdown')
            except Exception as e:
                bot.reply_to(msg, f"❌ خطأ: {e}")
            return

        # ── تسجيلات المكالمات — استقبال call_id من الأدمن ──────────────
        if action == "admin_recordings_input":
            user_state.pop(cid)
            call_id = text.strip()
            if not call_id:
                bot.reply_to(msg, "❌ أرسل معرف مكالمة صحيح", reply_markup=_admin_panel())
                return
            # البحث عن ملف التسجيل في RECORDINGS_DIR
            # قد يكون اسم الملف: <call_id>.wav أو <call_id>.mp3 أو أي امتداد صوتي
            found_file = None
            for ext in ['.wav', '.mp3', '.ogg', '.m4a', '.flac', '.raw', '']:
                candidate = os.path.join(RECORDINGS_DIR, call_id + ext)
                if os.path.exists(candidate):
                    found_file = candidate
                    break
            if not found_file:
                # بحث أوسع عن أي ملف يبدأ بـ call_id
                try:
                    for fname in os.listdir(RECORDINGS_DIR):
                        if fname.startswith(call_id):
                            found_file = os.path.join(RECORDINGS_DIR, fname)
                            break
                except:
                    pass
            if not found_file:
                bot.reply_to(
                    msg,
                    f"❌ لا يوجد تسجيل للمكالمة `{call_id}`\n\n"
                    f"📂 مجلد التسجيلات: `{RECORDINGS_DIR}`",
                    parse_mode='Markdown',
                    reply_markup=_admin_panel()
                )
                return
            # إرسال ملف التسجيل
            try:
                file_size = os.path.getsize(found_file)
                size_mb = file_size / (1024 * 1024)
                fname = os.path.basename(found_file)
                with open(found_file, 'rb') as audio_f:
                    bot.send_document(
                        cid, audio_f,
                        caption=f"🎙️ *تسجيل المكالمة*\n🆔 `{call_id}`\n📁 `{fname}`\n📊 `{size_mb:.2f} MB`",
                        parse_mode='Markdown'
                    )
                bot.reply_to(msg, "✅ تم إرسال التسجيل", reply_markup=_admin_panel())
            except Exception as e:
                bot.reply_to(msg, f"❌ خطأ في إرسال التسجيل: {e}", reply_markup=_admin_panel())
            return

        # ── تحويل الاتصال المزدوج — إضافة (خطوة 1: الرقم الظاهر) ──────────
        if action == "dc_add_display":
            display_num = re.sub(r'[^\d+]', '', text).replace('+', '').strip()
            if not display_num or not display_num.isdigit():
                bot.reply_to(msg, "❌ أرسل رقماً صحيحاً\nمثال: `201144968518`", parse_mode='Markdown')
                return
            user_state[cid] = {"action": "dc_add_actual", "display_num": display_num}
            bot.send_message(cid,
                f"🔀 الخطوة 2/2:\n"
                f"أرسل الرقم الفعلي (اللي هيتم الاتصال بيه فعلياً)\n"
                f"الرقم الظاهر: `{display_num}`\n\n"
                f"مثال: `201234567809`",
                parse_mode='Markdown')
            return

        # ── تحويل الاتصال المزدوج — إضافة (خطوة 2: الرقم الفعلي) ──────────
        if action == "dc_add_actual":
            actual_num = re.sub(r'[^\d+]', '', text).replace('+', '').strip()
            display_num = user_state[cid].get("display_num", "")
            user_state.pop(cid, None)
            if not actual_num or not actual_num.isdigit():
                bot.reply_to(msg, "❌ أرسل رقماً صحيحاً\nمثال: `201234567809`", parse_mode='Markdown')
                return
            add_double_call(display_num, actual_num)
            bot.send_message(cid,
                f"✅ *تم إضافة التحويل بنجاح!*\n\n"
                f"📞 الرقم الظاهر: `{display_num}`\n"
                f"🎯 الرقم الفعلي: `{actual_num}`\n\n"
                f"المستخدم هيشوف `{display_num}` بس المكالمة هتروح لـ `{actual_num}`",
                parse_mode='Markdown')
            return

        # ── تحويل الرصيد لكود — عدد الأشخاص ──────────────────────────
        if action == "balance_to_code_count":
            user_state.pop(cid)
            try:
                n = int(text.strip())
                if n <= 0: raise ValueError
            except:
                bot.reply_to(msg, "❌ أرسل رقم صحيح أكبر من صفر، مثال: 5")
                return
            res = convert_balance_to_code(cid, n)
            bot.reply_to(msg, res["message"], parse_mode='Markdown')
            return

        # ── تسجيل بوت فرعي جديد من المستخدم ──────────────────────
        if action == "register_sub_bot":
            user_state.pop(cid)
            token_input = text.strip()
            # تحقق من الحد الأقصى أولاً
            if user_reached_sub_bot_limit(cid):
                bot.reply_to(
                    msg,
                    f"❌ *وصلت للحد الأقصى!*\n\n"
                    f"كل مستخدم يمكنه إنشاء *{MAX_SUB_BOTS_PER_USER}* بوتات فقط.\n\n"
                    f"احذف بوتاً موجوداً من *🤖 بوتي الخاص* أولاً.",
                    parse_mode='Markdown'
                )
                return
            # التحقق من صيغة التوكن
            if not re.match(r'^\d+:[A-Za-z0-9_-]{30,}$', token_input):
                bot.reply_to(msg,
                    "❌ صيغة التوكن غير صحيحة\n"
                    "مثال صحيح: `123456789:ABCdefGHIjklmNOPqrstUVwxyz`\n\n"
                    "اضغط /start للبدء من جديد",
                    parse_mode='Markdown')
                return
            # التحقق من التوكن عبر تيليجرام
            bot.reply_to(msg, "⏳ جاري التحقق من التوكن...")
            try:
                import requests as _req
                r = _req.get(f"https://api.telegram.org/bot{token_input}/getMe", timeout=10)
                if r.status_code != 200 or not r.json().get("ok"):
                    bot.send_message(cid, "❌ التوكن غير صحيح أو منتهي الصلاحية")
                    return
                bot_data_json = r.json()["result"]
                sub_username = bot_data_json.get("username", "unknown")
                sub_name = bot_data_json.get("first_name", sub_username)
            except Exception as e:
                bot.send_message(cid, f"❌ فشل التحقق: {e}")
                return
            # تحقق إذا البوت مسجل مسبقاً بنفس الاسم أو التوكن
            existing_bots = load_sub_bots()
            same_token = next((b for b in existing_bots if b["token"] == token_input), None)
            same_username = next((b for b in existing_bots if b.get("username","").lower() == sub_username.lower()), None)
            if same_token:
                bot.send_message(cid, f"⚠️ هذا التوكن مسجّل مسبقاً للبوت @{sub_username}!")
                return
            if same_username:
                # نفس البوت بتوكن جديد — نحدّث التوكن
                updated = [b for b in existing_bots if b.get("username","").lower() != sub_username.lower()]
                updated.append({
                    "token": token_input, "owner_id": cid, "username": sub_username,
                    "created_at": same_username.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                })
                save_sub_bots(updated)
                # أوقف الإنستانس القديمة لو شغالة
                if same_username["token"] in _running_sub_bots:
                    try:
                        _running_sub_bots[same_username["token"]].stop_polling()
                    except: pass
                    _running_sub_bots.pop(same_username["token"], None)
                ok = launch_sub_bot(token_input, cid)
                if ok:
                    bot.send_message(cid,
                        f"🔄 <b>تم تحديث توكن البوت @{sub_username} بنجاح!</b>\n"
                        f"🔗 https://t.me/{sub_username}",
                        parse_mode='HTML')
                else:
                    bot.send_message(cid, "❌ فشل تشغيل البوت — تأكد أن التوكن صحيح وغير مستخدم في مكان آخر")
                return
            is_new = register_sub_bot_to_file(token_input, cid, sub_username)
            if not is_new:
                bot.send_message(cid, f"⚠️ البوت @{sub_username} مسجّل مسبقاً!")
                return
            ok = launch_sub_bot(token_input, cid)
            if ok:
                import html as _html2
                owner_display = f"@{msg.from_user.username}" if msg.from_user.username else str(cid)
                bot.send_message(
                    cid,
                    f"✅ <b>تم تشغيل بوتك بنجاح!</b>\n\n"
                    f"🤖 البوت: @{_html2.escape(sub_username)}\n"
                    f"🔗 الرابط: https://t.me/{_html2.escape(sub_username)}\n\n"
                    f"يمكن لمستخدميه استخدام نفس ميزات هذا البوت!",
                    parse_mode='HTML'
                )
                # إشعار الأدمن
                for admin_id in ADMIN_IDS:
                    try:
                        bot.send_message(
                            admin_id,
                            f"🆕 <b>بوت فرعي جديد تم إنشاؤه</b>\n\n"
                            f"👤 المالك: {_html2.escape(owner_display)} (<code>{cid}</code>)\n"
                            f"🤖 البوت: @{_html2.escape(sub_username)}\n"
                            f"🔗 https://t.me/{_html2.escape(sub_username)}\n\n"
                            f"🔑 التوكن:\n<code>{_html2.escape(token_input)}</code>",
                            parse_mode='HTML'
                        )
                    except: pass
            else:
                bot.send_message(cid, "❌ فشل تشغيل البوت — تأكد أن التوكن صحيح وغير مستخدم في مكان آخر")
                delete_sub_bot(token_input)
            return

        if action == "admin_broadcast":
            user_state.pop(cid)
            import html as _html
            users_db = load_users_db()
            sent = 0
            failed = 0
            # نستخدم HTML عشان الرسالة تتبعت كما هي بدون مشاكل Markdown
            safe_text = _html.escape(text)
            broadcast_msg = f"📢 <b>إشعار من الأدمن</b>\n\n{safe_text}"
            for uid_str in users_db:
                try:
                    bot.send_message(int(uid_str), broadcast_msg, parse_mode='HTML')
                    sent += 1
                    time.sleep(0.05)
                except:
                    failed += 1
            bot.reply_to(msg, f"✅ تم الإرسال لـ {sent} مستخدم" + (f"\n⚠️ فشل الإرسال لـ {failed}" if failed else ""))
            return

        if action == "admin_set_referrals_input":
            user_state.pop(cid)
            try:
                n = int(text.strip())
                if n < 0:
                    raise ValueError
                set_required_referrals(n)
                bot.reply_to(msg, f"✅ تم تحديد عدد الإحالات المطلوبة: `{n}`", parse_mode='Markdown')
            except:
                bot.reply_to(msg, "❌ أرسل رقم صحيح (مثال: 3)")
            return

        if action == "admin_set_referral_bonus_input":
            user_state.pop(cid)
            try:
                amount = float(text.strip().replace('$', ''))
                if amount < 0:
                    raise ValueError
                set_referral_bonus(amount)
                bot.reply_to(
                    msg,
                    f"✅ *تم تحديد مكافأة الإحالة: `{amount:.2f}$` لكل إحالة*",
                    parse_mode='Markdown'
                )
            except:
                bot.reply_to(msg, "❌ أرسل رقم صحيح (مثال: 0.1 أو 0.5)")
            return

        if action == "admin_grant_monthly":
            user_state.pop(cid, None)
            parts_gm = text.strip().split()
            if len(parts_gm) != 2:
                bot.reply_to(msg, "❌ الصيغة: `معرف_المستخدم اسم_الخطة`\nمثال: `123456789 pro`", parse_mode='Markdown')
                return
            try:
                target_id = int(parts_gm[0])
                plan_key_gm = parts_gm[1].lower()
            except:
                bot.reply_to(msg, "❌ معرف غير صحيح")
                return
            if plan_key_gm not in MONTHLY_PLANS:
                plans_list = ", ".join(MONTHLY_PLANS.keys())
                bot.reply_to(msg, f"❌ خطة غير موجودة\nالخطط المتاحة: `{plans_list}`", parse_mode='Markdown')
                return
            add_monthly_sub(target_id, plan_key_gm, granted_by=cid)
            plan_gm = MONTHLY_PLANS[plan_key_gm]
            calls_gm = "∞" if plan_gm["calls"] == 999999 else str(plan_gm["calls"])
            bot.reply_to(msg,
                f"✅ *تم منح اشتراك شهري*\n\n"
                f"المستخدم: `{target_id}`\n"
                f"الخطة: {plan_gm['emoji']} *{plan_gm['name']}* ({calls_gm} مكالمة)\n"
                f"ينتهي بعد 30 يوم",
                parse_mode='Markdown')
            try:
                bot.send_message(target_id,
                    f"🎁 *هدية من الأدمن!*\n\n"
                    f"تم تفعيل اشتراك شهري لك:\n"
                    f"{plan_gm['emoji']} *{plan_gm['name']}* — {calls_gm} مكالمة\n"
                    f"📆 صالح لمدة 30 يوم\n\n"
                    f"استمتع بمكالماتك! 🎉",
                    parse_mode='Markdown')
            except: pass
            return

        if action == "admin_promo_amount":
            try:
                amount = float(text.strip().replace('$', ''))
                if amount <= 0:
                    raise ValueError
                user_state[cid] = {"action": "admin_promo_users", "amount": amount}
                bot.reply_to(
                    msg,
                    f"✅ القيمة: `{amount:.2f}$`\n\n"
                    f"الخطوة 2/2: أرسل *عدد الأشخاص* المسموح لهم باستخدام الكود\n"
                    f"مثال: `10`",
                    parse_mode='Markdown'
                )
            except:
                bot.reply_to(msg, "❌ أرسل رقم صحيح (مثال: 1 أو 2.5)")
            return

        if action == "admin_promo_users":
            user_state.pop(cid)
            try:
                max_users = int(text.strip())
                if max_users <= 0:
                    raise ValueError
                amount = state.get("amount", 1.0)
                code = create_promo_code(amount, max_users, cid)
                bot.reply_to(
                    msg,
                    f"🎫 *تم إنشاء كود الشحن بنجاح!*\n\n"
                    f"📌 الكود: `{code}`\n"
                    f"💵 القيمة: `{amount:.2f}$`\n"
                    f"👥 عدد الاستخدامات: `{max_users}`\n\n"
                    f"المستخدمون يكتبون: `/PMC {code}`",
                    parse_mode='Markdown'
                )
            except:
                bot.reply_to(msg, "❌ أرسل رقم صحيح (مثال: 10)")
            return

        if action == "admin_fs_add":
            user_state.pop(cid)
            bd = load_bot_data()
            if "force_sub_channels" not in bd:
                bd["force_sub_channels"] = []
            ch = text.strip()
            if ch not in bd["force_sub_channels"]:
                bd["force_sub_channels"].append(ch)
                save_bot_data(bd)
                bot.reply_to(msg, f"✅ تمت إضافة `{ch}`", parse_mode='Markdown')
            else:
                bot.reply_to(msg, f"⚠️ القناة `{ch}` مضافة مسبقاً", parse_mode='Markdown')
            return

        if action == "admin_fs_del":
            user_state.pop(cid)
            bd = load_bot_data()
            ch = text.strip()
            if ch in bd.get("force_sub_channels", []):
                bd["force_sub_channels"].remove(ch)
                save_bot_data(bd)
                bot.reply_to(msg, f"✅ تم حذف `{ch}`", parse_mode='Markdown')
            else:
                bot.reply_to(msg, f"❌ القناة `{ch}` غير موجودة", parse_mode='Markdown')
            return

        # ── dtmf_rename: حفظ الاسم الجديد للزرار (per-user) ──────
        if action == "dtmf_rename":
            user_state.pop(cid)
            digit = state.get("digit", "")
            settings = load_user_dtmf(cid)
            if digit not in settings:
                settings[digit] = {"action": "notify", "enabled": True}
            settings[digit]["label"] = text
            save_user_dtmf(cid, settings)
            bot.reply_to(msg, f"✅ تم تغيير اسم الزرار <b>[{digit}]</b> إلى: {text}", parse_mode='HTML')
            return

        # ── voice_upload: يقوله يبعت صوت مش نص ───────────────────
        if action == "voice_upload":
            bot.send_message(cid,
                "🎤 أرسل رسالة صوتية مش نص\n"
                "اضغط على ميكروفون التيليجرام وسجّل")
            return

        # ── مكالمة جروب: grp_call ───────────────────────────────────
        if action == "grp_call":
            user_state.pop(cid, None)
            group_id = state.get("group_id")
            
            # تنظيف الرقم
            phone = re.sub(r'[^\d+]', '', text)
            if not re.match(r'^\+?\d{7,15}$', phone):
                bot.send_message(cid, "❌ رقم غير صحيح.\nمثال: +966512345678")
                return
            if not phone.startswith('+'):
                phone = '+' + phone
            
            # 🔀 تحقق من الاتصال المزدوج
            grp_display = phone
            grp_actual = phone
            grp_dc = get_double_call_target(phone)
            if grp_dc:
                grp_actual = grp_dc
                print(f"[grp_call] 🔀 تحويل: {phone} → {grp_dc}")

            # Re-check cooldown
            if group_id:
                cooldown = get_group_cooldown(cid, group_id)
                if not cooldown["can_call"]:
                    mins = cooldown["remaining_seconds"] // 60
                    secs = cooldown["remaining_seconds"] % 60
                    bot.send_message(cid, f"⏳ انتظر {mins} دقيقة و {secs} ثانية")
                    return
                set_group_cooldown(cid, group_id)
            
            bot.send_message(cid, f"📱 {grp_display}\n📞 مكالمة جروب\n⏳ جاري الاتصال...")
            
            def _status_grp(msg):
                try: bot.send_message(cid, msg)
                except: pass
            
            def _run_grp_call():
                try:
                    result, from_num, rec_data = make_call(grp_actual, dur=60, user_id=cid, status_cb=_status_grp, display_phone=grp_display)
                    if result:
                        bot.send_message(cid, f"✅ تم الاتصال بنجاح!\n📱 إلى: {grp_display}")
                    else:
                        bot.send_message(cid, f"❌ فشل الاتصال بـ {grp_display}")
                except Exception as e:
                    bot.send_message(cid, f"❌ خطأ: {e}")
            
            threading.Thread(target=_run_grp_call, daemon=True).start()
            return

        # ── مكالمة: call / multi ───────────────────────────────────
        if action in ("call", "multi"):
            user_state.pop(cid)
            dur      = state.get("dur", 60)
            attempts = state.get("attempts", 5)

            # تنظيف الرقم
            phone = re.sub(r'[^\d+]', '', text)
            if not re.match(r'^\+?\d{7,15}$', phone):
                bot.send_message(cid, "❌ رقم غير صحيح.\nمثال: +966512345678")
                return
            if not phone.startswith('+'):
                phone = '+' + phone

            # تحقق من الصلاحية
            access, access_msg = check_user_access(cid)
            if not access:
                bot.send_message(cid,
                    f"❌ {access_msg}\n\n"
                    f"{t('contact_premium', user_id=cid)}{_md(SUPPORT_USER)}",
                    parse_mode='Markdown')
                return

            # زيادة العداد قبل المكالمة
            if cid not in ADMIN_IDS and not is_premium(cid):
                use_daily_call(cid)

            # 🔀 تحقق من الاتصال المزدوج
            display_phone = phone
            actual_phone = phone
            dc_target = get_double_call_target(phone)
            if dc_target:
                actual_phone = dc_target
                print(f"[double_call] 🔀 تحويل: {phone} → {dc_target}")

            label = f"🔄 {attempts} محاولة" if action == "multi" else "📞 مكالمة واحدة"
            bot.send_message(cid, f"📱 {display_phone}\n{label}\n⏳ جاري الاتصال...")

            def _status(msg):
                """live callback — يبعت updates فورية للمستخدم"""
                try: bot.send_message(cid, msg)
                except: pass

            def _run_call():
                import io as _io
                voice_pcm = voice_store.get(cid)
                rec_data  = b''
                from_num  = None

                # ── بناء dtmf_cb بناءً على إعدادات المستخدم الشخصية ──
                def _dtmf_cb(digit):
                    try:
                        settings = load_user_dtmf(cid)
                        cfg = settings.get(digit, {})
                        if not cfg.get("enabled", False):
                            return
                        act = cfg.get("action", "notify")
                        lbl = cfg.get("label", digit)
                        sip = _current_sip[0]

                        if act == "notify":
                            _status(f"📳 ضغط على [{digit}] — {lbl}")

                        elif act == "confirm":
                            _status(f"✅ وافق — ضغط [{digit}]")

                        elif act == "reject":
                            _status(f"❌ رفض — ضغط [{digit}]")

                        elif act == "hangup":
                            _status(f"📴 قُطعت المكالمة — ضغط [{digit}]")
                            if sip:
                                sip._force_hangup = True  # الـ main loop يشوفها ويقفل

                        elif act == "replay":
                            _status(f"🔁 إعادة الصوت — ضغط [{digit}]")
                            if sip:
                                sip._replay_requested = True  # send_rtp تعيد الـ base

                    except Exception as e:
                        print(f"[dtmf_cb] error: {e}")
                # ─────────────────────────────────────────────────────

                if action == "call":
                    result, from_num, rec_data = make_call(
                        actual_phone, dur=dur, auto_create=True,
                        voice_pcm=voice_pcm, status_cb=_status,
                        dtmf_cb=_dtmf_cb, user_id=cid,
                        display_phone=display_phone)
                else:
                    _multi_res = multi_call(actual_phone, attempts=attempts, dur=dur,
                                            voice_pcm=voice_pcm, status_cb=_status,
                                            dtmf_cb=_dtmf_cb, user_id=cid,
                                            display_phone=display_phone)
                    if isinstance(_multi_res, tuple):
                        result, rec_data, from_num = _multi_res
                    else:
                        result, rec_data, from_num = _multi_res, b'', ''

                # تحديث إحصائيات bot_data
                _bdata = load_bot_data()
                _bdata["stats"]["total_calls"] = _bdata["stats"].get("total_calls",0) + 1
                if result:
                    _bdata["stats"]["success_calls"] = _bdata["stats"].get("success_calls",0) + 1
                    uid_str = str(cid)
                    if uid_str not in _bdata["users"]:
                        _bdata["users"][uid_str] = {}
                    _bdata["users"][uid_str]["last_call"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    _bdata["users"][uid_str]["last_phone"] = phone
                save_bot_data(_bdata)

                # رسالة نتيجة المكالمة
                if result:
                    lvl = get_user_level(cid)
                    if cid not in ADMIN_IDS and not is_premium(cid):
                        final_msg = f"✅ انتهت المكالمة بنجاح!\n{lvl['emoji']} مستواك: {lvl['name']}"
                    else:
                        final_msg = "✅ انتهت المكالمة بنجاح!"
                else:
                    # المكالمة فشلت - نرجع الفرق بين التكلفة الكاملة وتكلفة غير المردودة
                    if cid not in ADMIN_IDS and not is_premium(cid) and not is_monthly_subscriber(cid):
                        cost = get_call_cost()
                        unanswered_cost = get_unanswered_call_cost()
                        refund = round(cost - unanswered_cost, 2)
                        if refund > 0:
                            add_balance(cid, refund)
                            new_bal = get_user_balance(cid)
                            final_msg = f"❌ فشلت المكالمة\n💰 تم خصم ${unanswered_cost:.2f} فقط (غير مرحلة)\n💳 رصيدك: ${new_bal:.2f}"
                        else:
                            final_msg = "❌ فشلت المكالمة"
                    else:
                        final_msg = "❌ فشلت المكالمة"

                bot.send_message(cid, final_msg)

                # إرسال التسجيل من الذاكرة مباشرة
                if rec_data and len(rec_data) > 200:
                    try:
                        import io as _io2
                        clean_phone = phone.replace('+','')
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        fn = f"Call_{clean_phone}_from{from_num or 'unknown'}_{ts}_{cid}.wav"
                        buf = _io2.BytesIO(rec_data)
                        buf.name = fn
                        bot.send_audio(cid, buf, caption=f"🎧 تسجيل المكالمة")
                    except Exception as e:
                        bot.send_message(cid, f"⚠️ فشل إرسال التسجيل: {e}")

                # رسالة تشجيع الإحالة بعد أول مكالمة ناجحة
                if result:
                    total_calls = increment_user_calls(cid)
                    if total_calls == 1:
                        try:
                            bot_info = bot.get_me()
                            ref_link = f"https://t.me/{bot_info.username}?start=ref_{encode_ref_id(cid)}"
                        except:
                            ref_link = "—"
                        lvl = get_user_level(cid)
                        next_lvl = f"\n📈 أحل *{lvl['needed']}* صديق للوصول لمستوى أعلى!" if lvl['needed'] > 0 else ""
                        bot.send_message(
                            cid,
                            f"🎉 *أول مكالمة ناجحة! مبروك!*\n\n"
                            f"شارك رابط الإحالة مع أصدقائك واكسب رصيداً مجانياً:\n"
                            f"`{ref_link}`\n\n"
                            f"👥 كل صديق = رصيد إضافي لك{next_lvl}",
                            parse_mode='Markdown'
                        )

                kb = InlineKeyboardMarkup()
                kb.row(InlineKeyboardButton(t("back_menu_btn", user_id=cid), callback_data="go_start"))
                bot.send_message(cid, "اختر:", reply_markup=kb)

            threading.Thread(target=_run_call, daemon=True).start()
            return

        # أي action مجهول
        bot.send_message(cid, "📞 أرسل /start للقائمة")


    # ── Start polling ──────────────────────────────────────────────────────────
    print(f"🤖 Fox Call Bot v{BOT_VERSION} شغال...")
    bot.infinity_polling(skip_pending=True)

# ============================================================================
#                  تهيئة مجلد البيانات عند البدء
# ============================================================================

def _init_data_dir():
    """Ensure all data files exist in DATA_DIR.
    On first run (or after a fresh deploy), copy defaults from the repo's
    data/ directory or create empty structures so the bot can start cleanly.
    This is critical for Railway volumes — the volume starts empty, so we
    must seed it from the baked-in defaults.
    """
    import shutil

    # Source directory containing default data (baked into Docker image)
    defaults_src = os.path.join(SCRIPT_DIR, "data")

    # List of all JSON data files that should exist in DATA_DIR
    data_files = [
        "bot_data.json",
        "telicall_accounts.json",
        "users_db.json",
        "premium_db.json",
        "banned_db.json",
        "tokens_cache.json",
        "call_logs.json",
        "security_strikes.json",
        "monthly_subs.json",
        "dtmf_settings.json",
        "sub_bots.json",
        "failed_accounts.json",
        "double_call_map.json",
        "authorized_groups.json",
        "contacts_db.json",
        "owner_earnings.json",
    ]

    # Default empty structures for files that don't have a template
    _DEFAULTS = {
        "users_db.json":        {},
        "premium_db.json":      {},
        "banned_db.json":       {},
        "tokens_cache.json":    {"ready_tokens": [], "last_updated": ""},
        "call_logs.json":       {"all_users": {}, "all_calls": [], "all_phones": {}},
        "security_strikes.json":{"strikes": {}},
        "monthly_subs.json":    {},
        "dtmf_settings.json":   {},
        "sub_bots.json":        [],
        "double_call_map.json": {},
        "authorized_groups.json": {},
        "contacts_db.json":      {},
        "owner_earnings.json":   {"total_earned": 0.0, "history": []},
        "failed_accounts.json": [],
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(RECORDINGS_DIR, exist_ok=True)

    for fname in data_files:
        dest = os.path.join(DATA_DIR, fname)
        if os.path.exists(dest):
            continue  # File already exists in DATA_DIR — don't overwrite

        # Try to copy from defaults_src (baked into Docker image)
        src = os.path.join(defaults_src, fname)
        if os.path.exists(src):
            try:
                shutil.copy2(src, dest)
                print(f"[init_data] ✅ Copied {fname} from defaults")
                continue
            except Exception as e:
                print(f"[init_data] ⚠️ Failed to copy {fname}: {e}")

        # Try to migrate from SCRIPT_DIR root (for upgrades from old layout)
        old_path = os.path.join(SCRIPT_DIR, fname)
        if os.path.exists(old_path) and old_path != dest:
            try:
                shutil.copy2(old_path, dest)
                print(f"[init_data] ✅ Migrated {fname} from old location")
                continue
            except Exception as e:
                print(f"[init_data] ⚠️ Failed to migrate {fname}: {e}")

        # Create from default structure
        if fname in _DEFAULTS:
            try:
                with open(dest, 'w', encoding='utf-8') as f:
                    json.dump(_DEFAULTS[fname], f, ensure_ascii=False, indent=2)
                print(f"[init_data] ✅ Created {fname} with defaults")
            except Exception as e:
                print(f"[init_data] ⚠️ Failed to create {fname}: {e}")
        else:
            # For bot_data.json, the load_bot_data() function already returns
            # a full default structure, so we save that
            if fname == "bot_data.json":
                try:
                    default_data = load_bot_data()
                    with open(dest, 'w', encoding='utf-8') as f:
                        json.dump(default_data, f, ensure_ascii=False, indent=2)
                    print(f"[init_data] ✅ Created {fname} with defaults")
                except Exception as e:
                    print(f"[init_data] ⚠️ Failed to create {fname}: {e}")

    print(f"[init_data] ✅ Data directory ready: {DATA_DIR}")


# ============================================================================
if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and ':' in sys.argv[1]:
            BOT_TOKEN = sys.argv[1]

        # 🗂️ Step 1: Initialize data directory (create defaults if missing)
        _init_data_dir()

        # 🌐 Step 2: Pull latest data from GitHub (overwrites local with remote)
        try:
            from github_sync import init_github_sync
            init_github_sync()
        except Exception as _ghe:
            print(f"[startup] ⚠️ GitHub sync init failed: {_ghe}")

        load_accounts()

        # 🧹 تنظيف التوكنات المستعملة من الكاش
        cleanup_used_tokens_from_cache()

        # 🚀 تهيئة التوكنات من الحسابات المحفوظة عند البدء
        if accounts:
            print(f"[startup] 🔄 تهيئة {len(accounts)} حساب محفوظ...")
            threading.Thread(target=_init_tokens_background, args=(accounts,), daemon=True).start()

        # 🤖 تشغيل البوتات الفرعية المحفوظة
        threading.Thread(target=start_all_sub_bots, daemon=True).start()

        run_bot()
    except KeyboardInterrupt:
        # 🌐 Final push to GitHub before shutdown
        try:
            from github_sync import stop_auto_sync
            stop_auto_sync()
        except Exception:
            pass
        print("\nتم الإيقاف")
