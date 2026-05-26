#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║           🐘 PostgreSQL Database Manager for Fox Call Bot    ║
║                                                              ║
║  Primary storage: PostgreSQL (Railway)                       ║
║  Backup: GitHub (daily export from PostgreSQL)               ║
║  Restore: If DB empty → pull from GitHub → import to DB     ║
║                                                              ║
║  All JSON data is stored as rows in a key-value table.       ║
║  This ensures data survives Railway container restarts.      ║
╚══════════════════════════════════════════════════════════════╝
"""

import os
import json
import time
import logging
import threading
from datetime import datetime

log = logging.getLogger("db-manager")

# ═══════════════════════════════════════════════════════════════════════════════
#  Configuration — بيانات PostgreSQL (مضمنة في الكود)
# ═══════════════════════════════════════════════════════════════════════════════

# 🔧 بيانات الاتصال — القيم المضمنة في الكود (الأساسية)
# نستخدم PG_DATABASE_URL بدل DATABASE_URL عشان ما يتعارضش مع SQLite
# ⚠️ sslmode=require ضروري للاتصال بـ Railway PostgreSQL proxy
_PG_URL = "postgresql://postgres:TzIMZoWsqxpywTwxqFXBZTikFDaZRPWm@zephyr.proxy.rlwy.net:56940/railway?sslmode=require"
_PG_PRIVATE_URL = "postgresql://postgres:TzIMZoWsqxpywTwxqFXBZTikFDaZRPWm@postgres.railway.internal:5432/railway"

DATABASE_URL = os.environ.get(
    "PG_DATABASE_URL", _PG_URL
).strip('"').strip("'").strip()

DATABASE_PRIVATE_URL = os.environ.get(
    "PG_DATABASE_PRIVATE_URL", _PG_PRIVATE_URL
).strip('"').strip("'").strip()

# نستخدم PRIVATE_URL لو داخل Railway (أسرع)، وPUBLIC URL لو بره
# لو URL يبدأ بـ "postgresql://" نستخدمه، لو مش كده نستخدم القيمة المضمنة
if not DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = _PG_URL

# ⚠️ أضف sslmode=require لو مش موجود — ضروري لـ Railway PostgreSQL proxy
if "sslmode" not in DATABASE_URL:
    separator = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL = DATABASE_URL + separator + "sslmode=require"

_db_url = DATABASE_URL

# ═══════════════════════════════════════════════════════════════════════════════
#  Connection Pool
# ═══════════════════════════════════════════════════════════════════════════════

_pool = None
_pool_lock = threading.Lock()
_db_ready = False

def _get_connection():
    """يحصل على اتصال من Connection Pool"""
    global _pool
    if _pool is None or _pool.closed:
        try:
            import psycopg2.pool
            _pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=_db_url
            )
            log.info("[db] ✅ Connection pool created")
        except Exception as e:
            log.error("[db] ❌ Failed to create connection pool: %s", e)
            return None
    try:
        conn = _pool.getconn()
        return conn
    except Exception as e:
        log.error("[db] ❌ Failed to get connection: %s", e)
        # حاول يعمل pool جديد
        try:
            import psycopg2.pool
            _pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1, maxconn=10, dsn=_db_url
            )
            return _pool.getconn()
        except:
            return None

def _return_connection(conn):
    """يرجع الاتصال للـ Pool"""
    global _pool
    if _pool and conn:
        try:
            _pool.putconn(conn)
        except:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
#  Table Creation
# ═══════════════════════════════════════════════════════════════════════════════

def init_db():
    """إنشاء الجداول لو مش موجودة — ينفذ مرة واحدة عند البدء"""
    global _db_ready
    conn = _get_connection()
    if not conn:
        log.warning("[db] ⚠️ Cannot init DB — no connection")
        return False

    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            # ── جدول تخزين البيانات الأساسي (Key-Value) ──
            cur.execute("""
                CREATE TABLE IF NOT EXISTS data_store (
                    key VARCHAR(255) PRIMARY KEY,
                    value JSONB,
                    value_binary BYTEA,
                    updated_at TIMESTAMP DEFAULT NOW()
                );
            """)

            # ── جدول Dan.json Accounts ──
            cur.execute("""
                CREATE TABLE IF NOT EXISTS dan_accounts (
                    email VARCHAR(255) PRIMARY KEY,
                    account_data JSONB,
                    is_used BOOLEAN DEFAULT FALSE,
                    is_failed BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    used_at TIMESTAMP
                );
            """)

            # ── جدول التوكنات الجاهزة ──
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ready_tokens (
                    email VARCHAR(255) PRIMARY KEY,
                    device_id VARCHAR(255),
                    token TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)

            # ── جدول سجل المكالمات ──
            cur.execute("""
                CREATE TABLE IF NOT EXISTS call_history (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    phone VARCHAR(50),
                    status VARCHAR(50),
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)

            # ── Index عشان البحث سريع ──
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_dan_accounts_used
                ON dan_accounts (is_used);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_dan_accounts_failed
                ON dan_accounts (is_failed);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_call_history_user
                ON call_history (user_id);
            """)

        _db_ready = True
        log.info("[db] ✅ Database tables ready")
        return True

    except Exception as e:
        log.error("[db] ❌ Failed to init DB: %s", e)
        return False
    finally:
        _return_connection(conn)


# ═══════════════════════════════════════════════════════════════════════════════
#  Key-Value Operations — لكل ملفات JSON
# ═══════════════════════════════════════════════════════════════════════════════

def db_get(key: str, default=None):
    """يقرأ قيمة JSON من قاعدة البيانات"""
    conn = _get_connection()
    if not conn:
        return default
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM data_store WHERE key = %s",
                (key,)
            )
            row = cur.fetchone()
            if row and row[0] is not None:
                return row[0]  # JSONB → Python dict/list تلقائياً
            return default
    except Exception as e:
        log.error("[db] ❌ db_get(%s) error: %s", key, e)
        return default
    finally:
        _return_connection(conn)


def db_set(key: str, value):
    """يكتب قيمة JSON في قاعدة البيانات"""
    conn = _get_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            # json.dumps لأن psycopg2 مش بيحول كل أنواع Python تلقائي
            value_json = json.dumps(value, ensure_ascii=False, default=str)
            cur.execute("""
                INSERT INTO data_store (key, value, updated_at)
                VALUES (%s, %s::jsonb, NOW())
                ON CONFLICT (key)
                DO UPDATE SET value = %s::jsonb, updated_at = NOW()
            """, (key, value_json, value_json))
        conn.commit()
        return True
    except Exception as e:
        log.error("[db] ❌ db_set(%s) error: %s", key, e)
        try: conn.rollback()
        except: pass
        return False
    finally:
        _return_connection(conn)


def db_get_binary(key: str, default=None):
    """يقرأ بيانات binary من قاعدة البيانات (للملفات المشفرة)"""
    conn = _get_connection()
    if not conn:
        return default
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT value_binary FROM data_store WHERE key = %s",
                (key,)
            )
            row = cur.fetchone()
            if row and row[0] is not None:
                return bytes(row[0])  # BYTEA → bytes
            return default
    except Exception as e:
        log.error("[db] ❌ db_get_binary(%s) error: %s", key, e)
        return default
    finally:
        _return_connection(conn)


def db_set_binary(key: str, value: bytes):
    """يكتب بيانات binary في قاعدة البيانات (للملفات المشفرة)"""
    conn = _get_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO data_store (key, value_binary, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key)
                DO UPDATE SET value_binary = %s, updated_at = NOW()
            """, (key, value, value))
        conn.commit()
        return True
    except Exception as e:
        log.error("[db] ❌ db_set_binary(%s) error: %s", key, e)
        try: conn.rollback()
        except: pass
        return False
    finally:
        _return_connection(conn)


def db_has_key(key: str) -> bool:
    """يتحقق من وجود مفتاح في قاعدة البيانات"""
    conn = _get_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM data_store WHERE key = %s LIMIT 1",
                (key,)
            )
            return cur.fetchone() is not None
    except Exception as e:
        log.error("[db] ❌ db_has_key(%s) error: %s", key, e)
        return False
    finally:
        _return_connection(conn)


# ═══════════════════════════════════════════════════════════════════════════════
#  Dan.json Accounts — عمليات مباشرة على جدول dan_accounts
# ═══════════════════════════════════════════════════════════════════════════════

def dan_count_total() -> int:
    """عدد كل حسابات Dan.json"""
    conn = _get_connection()
    if not conn:
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM dan_accounts")
            return cur.fetchone()[0]
    except:
        return 0
    finally:
        _return_connection(conn)


def dan_count_remaining() -> int:
    """عدد الحسابات المتبقية (مش مستعملة ومش فاشلة)"""
    conn = _get_connection()
    if not conn:
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM dan_accounts WHERE is_used = FALSE AND is_failed = FALSE"
            )
            return cur.fetchone()[0]
    except:
        return 0
    finally:
        _return_connection(conn)


def dan_count_used() -> int:
    """عدد الحسابات المستعملة"""
    conn = _get_connection()
    if not conn:
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM dan_accounts WHERE is_used = TRUE")
            return cur.fetchone()[0]
    except:
        return 0
    finally:
        _return_connection(conn)


def dan_mark_used(email: str):
    """يحط علامة إن الحساب اتستعمل"""
    conn = _get_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE dan_accounts SET is_used = TRUE, used_at = NOW() WHERE email = %s",
                (email,)
            )
        conn.commit()
        return True
    except:
        try: conn.rollback()
        except: pass
        return False
    finally:
        _return_connection(conn)


def dan_add_accounts(accounts_list: list):
    """يضيف حسابات جديدة لجدول dan_accounts"""
    conn = _get_connection()
    if not conn:
        return 0
    added = 0
    try:
        with conn.cursor() as cur:
            for acc in accounts_list:
                email = acc.get("email", "")
                if not email:
                    continue
                acc_json = json.dumps(acc, ensure_ascii=False, default=str)
                try:
                    cur.execute("""
                        INSERT INTO dan_accounts (email, account_data, is_used, is_failed)
                        VALUES (%s, %s::jsonb, FALSE, FALSE)
                        ON CONFLICT (email) DO NOTHING
                    """, (email, acc_json))
                    if cur.rowcount > 0:
                        added += 1
                except:
                    pass
        conn.commit()
        log.info("[db] ✅ Added %d new Dan.json accounts", added)
        return added
    except Exception as e:
        log.error("[db] ❌ dan_add_accounts error: %s", e)
        try: conn.rollback()
        except: pass
        return 0
    finally:
        _return_connection(conn)


def dan_get_unused(limit: int = 1) -> list:
    """يرجع حسابات مش مستعملة"""
    conn = _get_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT email, account_data FROM dan_accounts
                WHERE is_used = FALSE AND is_failed = FALSE
                ORDER BY created_at ASC
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()
            result = []
            for row in rows:
                acc = row[1] if row[1] else {"email": row[0]}
                if not acc.get("email"):
                    acc["email"] = row[0]
                result.append(acc)
            return result
    except:
        return []
    finally:
        _return_connection(conn)


def dan_mark_failed(email: str):
    """يحط علامة إن الحساب فشل"""
    conn = _get_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE dan_accounts SET is_failed = TRUE WHERE email = %s",
                (email,)
            )
        conn.commit()
        return True
    except:
        try: conn.rollback()
        except: pass
        return False
    finally:
        _return_connection(conn)


def dan_is_used(email: str) -> bool:
    """يتحقق لو الحساب مستعمل"""
    conn = _get_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT is_used FROM dan_accounts WHERE email = %s",
                (email,)
            )
            row = cur.fetchone()
            return row[0] if row else False
    except:
        return False
    finally:
        _return_connection(conn)


# ═══════════════════════════════════════════════════════════════════════════════
#  Ready Tokens — عمليات مباشرة على جدول ready_tokens
# ═══════════════════════════════════════════════════════════════════════════════

def token_add(email: str, device_id: str, token: str):
    """يضيف أو يحدث توكن جاهز"""
    conn = _get_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ready_tokens (email, device_id, token, created_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (email)
                DO UPDATE SET device_id = %s, token = %s, created_at = NOW()
            """, (email, device_id, token, device_id, token))
        conn.commit()
        return True
    except:
        try: conn.rollback()
        except: pass
        return False
    finally:
        _return_connection(conn)


def token_get_ready(limit: int = 1) -> list:
    """يرجع توكنات جاهزة"""
    conn = _get_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT email, device_id, token FROM ready_tokens
                ORDER BY created_at ASC
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()
            return [
                {"email": r[0], "device_id": r[1], "token": r[2]}
                for r in rows
            ]
    except:
        return []
    finally:
        _return_connection(conn)


def token_count() -> int:
    """عدد التوكنات الجاهزة"""
    conn = _get_connection()
    if not conn:
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM ready_tokens")
            return cur.fetchone()[0]
    except:
        return 0
    finally:
        _return_connection(conn)


def token_remove(email: str):
    """يحذف توكن"""
    conn = _get_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ready_tokens WHERE email = %s", (email,))
        conn.commit()
        return True
    except:
        try: conn.rollback()
        except: pass
        return False
    finally:
        _return_connection(conn)


def token_remove_used(used_emails: set):
    """يحذف التوكنات المستعملة"""
    if not used_emails:
        return 0
    conn = _get_connection()
    if not conn:
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM ready_tokens WHERE email = ANY(%s)",
                (list(used_emails),)
            )
            deleted = cur.rowcount
        conn.commit()
        return deleted
    except:
        try: conn.rollback()
        except: pass
        return 0
    finally:
        _return_connection(conn)


# ═══════════════════════════════════════════════════════════════════════════════
#  Import / Export — نقل البيانات بين JSON و PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════════

# ملفات JSON اللي بتتحول لـ key-value في data_store
JSON_KEYS = [
    "bot_data",
    "users_db",
    "premium_db",
    "banned_db",
    "call_logs",
    "security_strikes",
    "monthly_subs",
    "dtmf_settings",
    "sub_bots",
    "failed_accounts",
    "double_call_map",
    "authorized_groups",
    "contacts_db",
    "owner_earnings",
    "app_subs",
]

# ملفات مشفرة (بتتحفظ كـ binary)
ENCRYPTED_KEYS = ["telicall_accounts"]


def db_is_empty() -> bool:
    """يتحقق لو قاعدة البيانات فاضية"""
    conn = _get_connection()
    if not conn:
        return True  # لو مفيش اتصال، نعتبرها فاضية
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM data_store")
            count = cur.fetchone()[0]
            # نتحقق كمان من dan_accounts
            cur.execute("SELECT COUNT(*) FROM dan_accounts")
            dan_count = cur.fetchone()[0]
            return count == 0 and dan_count == 0
    except:
        return True
    finally:
        _return_connection(conn)


def import_from_json(data_dir: str) -> dict:
    """يستورد كل ملفات JSON إلى PostgreSQL
    Returns {imported: int, errors: int, details: []}
    """
    result = {"imported": 0, "errors": 0, "details": []}

    # استيراد ملفات JSON العادية
    for key in JSON_KEYS:
        fname = f"{key}.json"
        fpath = os.path.join(data_dir, fname)
        if os.path.exists(fpath):
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if db_set(key, data):
                    result["imported"] += 1
                    result["details"].append(f"{fname}: imported OK")
                else:
                    result["errors"] += 1
                    result["details"].append(f"{fname}: db_set failed")
            except Exception as e:
                result["errors"] += 1
                result["details"].append(f"{fname}: {e}")
        else:
            result["details"].append(f"{fname}: not found locally")

    # استيراد telicall_accounts.json (مشفر)
    acc_path = os.path.join(data_dir, "telicall_accounts.json")
    if os.path.exists(acc_path):
        try:
            with open(acc_path, 'rb') as f:
                raw = f.read()
            # محاولة فك التشفير
            import base64, hashlib
            password = os.environ.get("ACCOUNTS_PASSWORD", "@@@GMAQ@@@").strip('"').strip("'").strip()
            key = hashlib.sha256(password.encode()).digest()
            try:
                decoded = base64.b64decode(raw)
                text = bytes([decoded[i] ^ key[i % len(key)] for i in range(len(decoded))]).decode('utf-8')
                accounts_list = json.loads(text)
                # حفظ في جدول dan_accounts
                if isinstance(accounts_list, list):
                    added = dan_add_accounts(accounts_list)
                    result["imported"] += 1
                    result["details"].append(f"telicall_accounts.json: {added} accounts imported to DB")
                else:
                    result["errors"] += 1
                    result["details"].append("telicall_accounts.json: not a list after decryption")
            except:
                # لو مش مشفر، نحفظه كـ binary
                if db_set_binary("telicall_accounts", raw):
                    result["imported"] += 1
                    result["details"].append("telicall_accounts.json: saved as binary")
                else:
                    result["errors"] += 1
                    result["details"].append("telicall_accounts.json: failed to save")
        except Exception as e:
            result["errors"] += 1
            result["details"].append(f"telicall_accounts.json: {e}")

    # استيراد bot_data.json → dan_accounts
    bd = db_get("bot_data", {})
    if bd:
        registered = bd.get("registered_accounts", [])
        used = bd.get("used_accounts", [])
        failed = bd.get("failed_accounts", [])

        # تحديث حالة الحسابات المستعملة
        for email in used:
            dan_mark_used(email)

        # تحديث حالة الحسابات الفاشلة
        if isinstance(failed, list):
            for email in failed:
                dan_mark_failed(email)

        result["details"].append(f"Marked {len(used)} used + {len(failed) if isinstance(failed, list) else 0} failed accounts")

    # استيراد tokens_cache.json → ready_tokens
    tc_path = os.path.join(data_dir, "tokens_cache.json")
    if os.path.exists(tc_path):
        try:
            with open(tc_path, 'r', encoding='utf-8') as f:
                tc = json.load(f)
            ready = tc.get("ready_tokens", [])
            for t in ready:
                token_add(t.get("email", ""), t.get("device_id", ""), t.get("token", ""))
            result["details"].append(f"tokens_cache.json: {len(ready)} tokens imported")
        except Exception as e:
            result["details"].append(f"tokens_cache.json: {e}")

    log.info("[db] Import complete: %d imported, %d errors", result["imported"], result["errors"])
    return result


def export_to_json(data_dir: str) -> dict:
    """يصدر كل البيانات من PostgreSQL إلى ملفات JSON
    Returns {exported: int, errors: int, details: []}
    """
    result = {"exported": 0, "errors": 0, "details": []}
    os.makedirs(data_dir, exist_ok=True)

    # تصدير ملفات JSON العادية
    for key in JSON_KEYS:
        fname = f"{key}.json"
        fpath = os.path.join(data_dir, fname)
        data = db_get(key)
        if data is not None:
            try:
                with open(fpath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                result["exported"] += 1
                result["details"].append(f"{fname}: exported OK")
            except Exception as e:
                result["errors"] += 1
                result["details"].append(f"{fname}: {e}")

    # تصدير telicall_accounts (من جدول dan_accounts)
    try:
        conn = _get_connection()
        if conn:
            import base64, hashlib
            with conn.cursor() as cur:
                cur.execute("SELECT email, account_data, is_used, is_failed FROM dan_accounts")
                rows = cur.fetchall()

            accounts_list = []
            for row in rows:
                acc = row[1] if row[1] else {"email": row[0]}
                if not acc.get("email"):
                    acc["email"] = row[0]
                accounts_list.append(acc)

            # تشفير الحسابات
            password = os.environ.get("ACCOUNTS_PASSWORD", "@@@GMAQ@@@").strip('"').strip("'").strip()
            key_hash = hashlib.sha256(password.encode()).digest()
            plain = json.dumps(accounts_list, indent=2, ensure_ascii=False)
            data_bytes = plain.encode('utf-8')
            enc = bytes([data_bytes[i] ^ key_hash[i % len(key_hash)] for i in range(len(data_bytes))])
            encrypted = base64.b64encode(enc)

            acc_path = os.path.join(data_dir, "telicall_accounts.json")
            with open(acc_path, 'wb') as f:
                f.write(encrypted)

            result["exported"] += 1
            result["details"].append(f"telicall_accounts.json: {len(accounts_list)} accounts exported (encrypted)")
            _return_connection(conn)
    except Exception as e:
        result["errors"] += 1
        result["details"].append(f"telicall_accounts.json: {e}")

    # تصدير tokens_cache
    try:
        ready = token_get_ready(limit=100000)
        tc = {
            "ready_tokens": [
                {"email": t["email"], "device_id": t["device_id"], "token": t["token"],
                 "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                for t in ready
            ],
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        tc_path = os.path.join(data_dir, "tokens_cache.json")
        with open(tc_path, 'w', encoding='utf-8') as f:
            json.dump(tc, f, ensure_ascii=False, indent=2)
        result["exported"] += 1
        result["details"].append(f"tokens_cache.json: {len(ready)} tokens exported")
    except Exception as e:
        result["errors"] += 1
        result["details"].append(f"tokens_cache.json: {e}")

    # تحديث bot_data.json بحسابات Dan.json
    bd = db_get("bot_data", {})
    if bd is not None:
        conn = _get_connection()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT email FROM dan_accounts")
                    all_emails = [r[0] for r in cur.fetchall()]
                    cur.execute("SELECT email FROM dan_accounts WHERE is_used = TRUE")
                    used_emails = [r[0] for r in cur.fetchall()]
                    cur.execute("SELECT email FROM dan_accounts WHERE is_failed = TRUE")
                    failed_emails = [r[0] for r in cur.fetchall()]

                bd["registered_accounts"] = all_emails
                bd["used_accounts"] = used_emails
                bd["failed_accounts"] = failed_emails

                bd_path = os.path.join(data_dir, "bot_data.json")
                with open(bd_path, 'w', encoding='utf-8') as f:
                    json.dump(bd, f, ensure_ascii=False, indent=2)

                _return_connection(conn)
            except:
                _return_connection(conn)

    log.info("[db] Export complete: %d exported, %d errors", result["exported"], result["errors"])
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Health Check
# ═══════════════════════════════════════════════════════════════════════════════

def db_health() -> dict:
    """يرجع حالة قاعدة البيانات"""
    conn = _get_connection()
    if not conn:
        return {"connected": False, "error": "No connection"}

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            version = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM data_store")
            kv_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM dan_accounts")
            dan_total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM dan_accounts WHERE is_used = FALSE AND is_failed = FALSE")
            dan_remaining = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM dan_accounts WHERE is_used = TRUE")
            dan_used = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM ready_tokens")
            tokens_ready = cur.fetchone()[0]

        return {
            "connected": True,
            "version": version[:50],
            "kv_store_keys": kv_count,
            "dan_total": dan_total,
            "dan_remaining": dan_remaining,
            "dan_used": dan_used,
            "tokens_ready": tokens_ready,
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}
    finally:
        _return_connection(conn)


def test_connection() -> bool:
    """يختبر الاتصال بقاعدة البيانات"""
    try:
        import psycopg2
        conn = psycopg2.connect(_db_url)
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.close()
        return True
    except Exception as e:
        log.error("[db] ❌ Connection test failed: %s", e)
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  Startup Initialization
# ═══════════════════════════════════════════════════════════════════════════════

def init_and_migrate(data_dir: str) -> dict:
    """تهيئة قاعدة البيانات وترحيل البيانات من JSON
    - لو DB فاضي → يستورد من JSON
    - لو DB فيه بيانات → مبيعملش حاجة
    Returns {action: str, details: dict}
    """
    # Step 1: Test connection
    if not test_connection():
        return {"action": "failed", "details": {"error": "Cannot connect to PostgreSQL"}}

    # Step 2: Create tables
    if not init_db():
        return {"action": "failed", "details": {"error": "Cannot create tables"}}

    # Step 3: Check if DB has data
    if not db_is_empty():
        log.info("[db] ✅ Database already has data — skipping import")
        return {"action": "skipped", "details": {"message": "DB already has data"}}

    # Step 4: Import from JSON files
    log.info("[db] 📥 Database is empty — importing from JSON files...")
    result = import_from_json(data_dir)

    if result["imported"] > 0:
        log.info("[db] ✅ Imported %d files from JSON", result["imported"])
        return {"action": "imported", "details": result}
    else:
        log.warning("[db] ⚠️ No JSON files to import — DB remains empty")
        return {"action": "empty", "details": result}
