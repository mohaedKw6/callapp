#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PostgreSQL Data Persistence for Fox Call Bot.

Replaces JSON file storage and GitHub sync with a proper PostgreSQL database.
All data (users, premium, banned, tokens, accounts, logs, etc.) is stored
in a single `bot_data` table using a key-value JSONB pattern, plus dedicated
tables for accounts and ready_tokens for better indexing and performance.

Environment variables:
  DATABASE_URL  — Full PostgreSQL connection URL (required)
  DB_HOST       — Database host (fallback)
  DB_PORT       — Database port (fallback)
  DB_NAME       — Database name (fallback)
  DB_USER       — Database user (fallback)
  DB_PASSWORD   — Database password (fallback)
"""

import os
import json
import time
import threading
import logging
from datetime import datetime

log = logging.getLogger("db")

# ─── Configuration ─────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip('"').strip("'").strip()

if not DATABASE_URL:
    DB_HOST = os.environ.get("DB_HOST", "").strip('"').strip("'").strip()
    DB_PORT = os.environ.get("DB_PORT", "5432").strip('"').strip("'").strip()
    DB_NAME = os.environ.get("DB_NAME", "railway").strip('"').strip("'").strip()
    DB_USER = os.environ.get("DB_USER", "postgres").strip('"').strip("'").strip()
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "").strip('"').strip("'").strip()
    if DB_HOST and DB_PASSWORD:
        DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

if DATABASE_URL:
    log.info("[db] DATABASE_URL loaded (%s...)", DATABASE_URL[:30])
else:
    log.warning("[db] No DATABASE_URL configured — will use JSON file fallback")

# ─── Connection Pool ────────────────────────────────────────────────────────────

_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    """Get or create the connection pool."""
    global _pool
    if _pool is not None:
        return _pool

    if not DATABASE_URL:
        return None

    with _pool_lock:
        if _pool is not None:
            return _pool
        try:
            import psycopg2
            from psycopg2 import pool
            _pool = pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=DATABASE_URL,
                connect_timeout=10
            )
            log.info("[db] Connection pool created successfully")
            return _pool
        except Exception as e:
            log.error("[db] Failed to create connection pool: %s", e)
            return None


def _get_conn():
    """Get a connection from the pool."""
    p = _get_pool()
    if p is None:
        return None
    try:
        conn = p.getconn()
        return conn
    except Exception as e:
        log.error("[db] Failed to get connection: %s", e)
        return None


def _return_conn(conn):
    """Return a connection to the pool."""
    p = _get_pool()
    if p and conn:
        try:
            p.putconn(conn)
        except Exception:
            pass


# ─── Schema Initialization ─────────────────────────────────────────────────────

_SCHEMA_INITIALIZED = False
_SCHEMA_LOCK = threading.Lock()


def _ensure_schema():
    """Create tables if they don't exist. Called once on startup."""
    global _SCHEMA_INITIALIZED
    if _SCHEMA_INITIALIZED:
        return True

    with _SCHEMA_LOCK:
        if _SCHEMA_INITIALIZED:
            return True

        conn = _get_conn()
        if not conn:
            log.error("[db] Cannot initialize schema — no database connection")
            return False

        try:
            with conn.cursor() as cur:
                # Key-value table for JSON data (replaces all JSON files)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS bot_data (
                        key VARCHAR(255) PRIMARY KEY,
                        data JSONB NOT NULL DEFAULT '{}'::jsonb,
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                """)

                # Dedicated accounts table (for fast lookup)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS telicall_accounts (
                        id SERIAL PRIMARY KEY,
                        email VARCHAR(255) UNIQUE NOT NULL,
                        device_id VARCHAR(255) DEFAULT '',
                        token TEXT DEFAULT '',
                        extra JSONB DEFAULT '{}'::jsonb,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """)

                # Ready tokens table (for fast pop/push)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ready_tokens (
                        id SERIAL PRIMARY KEY,
                        email VARCHAR(255) NOT NULL,
                        device_id VARCHAR(255) NOT NULL,
                        token TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """)

                # Indexes
                cur.execute("CREATE INDEX IF NOT EXISTS idx_ready_tokens_email ON ready_tokens(email)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_accounts_email ON telicall_accounts(email)")

            conn.commit()
            _SCHEMA_INITIALIZED = True
            log.info("[db] Schema initialized successfully")
            return True
        except Exception as e:
            conn.rollback()
            log.error("[db] Schema initialization failed: %s", e)
            return False
        finally:
            _return_conn(conn)


def init_db():
    """Initialize database connection and schema. Call this on startup."""
    if not DATABASE_URL:
        log.warning("[db] No DATABASE_URL — database features disabled")
        return False

    pool = _get_pool()
    if not pool:
        log.error("[db] Failed to create connection pool")
        return False

    if not _ensure_schema():
        log.error("[db] Failed to initialize schema")
        return False

    log.info("[db] Database initialized and ready")
    return True


# ─── Generic Key-Value Operations ───────────────────────────────────────────────

def load_kv(key: str, default=None):
    """Load a JSON value from the bot_data table by key."""
    conn = _get_conn()
    if not conn:
        return default

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT data FROM bot_data WHERE key = %s", (key,))
            row = cur.fetchone()
            if row:
                return row[0]
            return default
    except Exception as e:
        log.error("[db] load_kv(%s) error: %s", key, e)
        return default
    finally:
        _return_conn(conn)


def save_kv(key: str, data):
    """Save a JSON value to the bot_data table by key (upsert)."""
    conn = _get_conn()
    if not conn:
        return False

    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bot_data (key, data, updated_at)
                VALUES (%s, %s::jsonb, NOW())
                ON CONFLICT (key)
                DO UPDATE SET data = %s::jsonb, updated_at = NOW()
            """, (key, json.dumps(data), json.dumps(data)))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        log.error("[db] save_kv(%s) error: %s", key, e)
        return False
    finally:
        _return_conn(conn)


# ─── Specific Data Access Functions (same interface as JSON files) ──────────────

def load_bot_data() -> dict:
    """Load bot_data (replaces bot_data.json)."""
    default = {
        "users": {},
        "premium": {},
        "banned": {},
        "dtmf": {},
        "stats": {"total_calls": 0, "success_calls": 0},
        "voice_labels": {},
        "settings": {
            "required_referrals": 3,
            "call_cost": 0.20,
            "unanswered_call_cost": 0.05,
            "daily_bonus": 0.10,
            "referral_bonus": 0.10
        },
        "double_call_map": {},
        "promo_codes": {},
        "registered_accounts": [],
        "used_accounts": []
    }
    data = load_kv("bot_data", default)
    if data is None:
        data = default
    # Ensure all keys exist
    for k, v in default.items():
        if k not in data:
            data[k] = v
    return data


def save_bot_data(data: dict):
    """Save bot_data (replaces bot_data.json)."""
    return save_kv("bot_data", data)


def load_users_db() -> dict:
    """Load users database (replaces users_db.json)."""
    return load_kv("users_db", {}) or {}


def save_users_db(users_db: dict):
    """Save users database (replaces users_db.json)."""
    return save_kv("users_db", users_db)


def load_premium_db() -> dict:
    """Load premium database (replaces premium_db.json)."""
    return load_kv("premium_db", {}) or {}


def save_premium_db(premium_db: dict):
    """Save premium database (replaces premium_db.json)."""
    return save_kv("premium_db", premium_db)


def load_banned_db() -> dict:
    """Load banned database (replaces banned_db.json)."""
    return load_kv("banned_db", {}) or {}


def save_banned_db(banned_db: dict):
    """Save banned database (replaces banned_db.json)."""
    return save_kv("banned_db", banned_db)


def load_tokens_cache() -> dict:
    """Load tokens cache (replaces tokens_cache.json)."""
    return load_kv("tokens_cache", {"ready_tokens": [], "last_updated": ""}) or {"ready_tokens": [], "last_updated": ""}


def save_tokens_cache(data: dict):
    """Save tokens cache (replaces tokens_cache.json)."""
    data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return save_kv("tokens_cache", data)


def load_call_logs() -> dict:
    """Load call logs (replaces call_logs.json)."""
    default = {"all_users": {}, "all_calls": [], "all_phones": {}}
    return load_kv("call_logs", default) or default


def save_call_logs(data: dict):
    """Save call logs (replaces call_logs.json)."""
    return save_kv("call_logs", data)


def load_authorized_groups() -> dict:
    """Load authorized groups (replaces authorized_groups.json)."""
    return load_kv("authorized_groups", {}) or {}


def save_authorized_groups(data: dict):
    """Save authorized groups (replaces authorized_groups.json)."""
    return save_kv("authorized_groups", data)


def load_security_strikes() -> dict:
    """Load security strikes (replaces security_strikes.json)."""
    return load_kv("security_strikes", {"strikes": {}}) or {"strikes": {}}


def save_security_strikes(data: dict):
    """Save security strikes."""
    return save_kv("security_strikes", data)


def load_monthly_subs() -> dict:
    """Load monthly subscriptions (replaces monthly_subs.json)."""
    return load_kv("monthly_subs", {}) or {}


def save_monthly_subs(data: dict):
    """Save monthly subscriptions."""
    return save_kv("monthly_subs", data)


def load_dtmf_settings() -> dict:
    """Load DTMF settings (replaces dtmf_settings.json)."""
    return load_kv("dtmf_settings", {}) or {}


def save_dtmf_settings(data: dict):
    """Save DTMF settings."""
    return save_kv("dtmf_settings", data)


def load_sub_bots() -> list:
    """Load sub-bots (replaces sub_bots.json)."""
    return load_kv("sub_bots", []) or []


def save_sub_bots(data: list):
    """Save sub-bots."""
    return save_kv("sub_bots", data)


def load_failed_accounts() -> list:
    """Load failed accounts (replaces failed_accounts.json)."""
    return load_kv("failed_accounts", []) or []


def save_failed_accounts(data: list):
    """Save failed accounts."""
    return save_kv("failed_accounts", data)


def load_contacts_db() -> dict:
    """Load contacts database (replaces contacts_db.json)."""
    return load_kv("contacts_db", {}) or {}


def save_contacts_db(data: dict):
    """Save contacts database."""
    return save_kv("contacts_db", data)


def load_double_call_map() -> dict:
    """Load double call map (replaces double_call_map.json)."""
    return load_kv("double_call_map", {}) or {}


def save_double_call_map(data: dict):
    """Save double call map."""
    return save_kv("double_call_map", data)


def load_version_config() -> dict:
    """Load version config (replaces version_config.json)."""
    default = {
        "latest_version": "4.0.0",
        "latest_version_code": 15,
        "minimum_version_code": 15,
        "force_update": True,
        "download_url": "",
    }
    return load_kv("version_config", default) or default


def save_version_config(data: dict):
    """Save version config."""
    return save_kv("version_config", data)


# ─── Accounts Table Operations ──────────────────────────────────────────────────

def load_accounts_from_db() -> list:
    """Load all telicall accounts from the dedicated table."""
    conn = _get_conn()
    if not conn:
        return []

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT email, device_id, token, extra FROM telicall_accounts ORDER BY id")
            rows = cur.fetchall()
            accounts = []
            for row in rows:
                acc = {
                    "email": row[0],
                    "x-client-device-id": row[1],
                    "x-token": row[2],
                }
                if row[3] and isinstance(row[3], dict):
                    acc.update(row[3])
                accounts.append(acc)
            return accounts
    except Exception as e:
        log.error("[db] load_accounts error: %s", e)
        return []
    finally:
        _return_conn(conn)


def save_accounts_to_db(accounts: list):
    """Save all telicall accounts to the dedicated table (replaces file)."""
    conn = _get_conn()
    if not conn:
        return False

    try:
        with conn.cursor() as cur:
            # Clear existing and re-insert
            cur.execute("DELETE FROM telicall_accounts")
            for acc in accounts:
                email = acc.get("email", "")
                device_id = acc.get("x-client-device-id", acc.get("device_id", ""))
                token = acc.get("x-token", acc.get("token", ""))
                extra = {k: v for k, v in acc.items()
                         if k not in ("email", "x-client-device-id", "device_id", "x-token", "token")}
                cur.execute("""
                    INSERT INTO telicall_accounts (email, device_id, token, extra)
                    VALUES (%s, %s, %s, %s::jsonb)
                    ON CONFLICT (email) DO UPDATE SET
                        device_id = %s, token = %s, extra = %s::jsonb
                """, (email, device_id, token, json.dumps(extra),
                      device_id, token, json.dumps(extra)))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        log.error("[db] save_accounts error: %s", e)
        return False
    finally:
        _return_conn(conn)


def add_account_to_db(email: str, device_id: str, token: str, extra: dict = None):
    """Add a single account to the database."""
    conn = _get_conn()
    if not conn:
        return False

    try:
        with conn.cursor() as cur:
            extra_json = json.dumps(extra or {})
            cur.execute("""
                INSERT INTO telicall_accounts (email, device_id, token, extra)
                VALUES (%s, %s, %s, %s::jsonb)
                ON CONFLICT (email) DO UPDATE SET
                    device_id = %s, token = %s, extra = %s::jsonb
            """, (email, device_id, token, extra_json,
                  device_id, token, extra_json))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        log.error("[db] add_account error: %s", e)
        return False
    finally:
        _return_conn(conn)


def remove_account_from_db(email: str):
    """Remove an account from the database by email."""
    conn = _get_conn()
    if not conn:
        return False

    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM telicall_accounts WHERE email = %s", (email,))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        log.error("[db] remove_account error: %s", e)
        return False
    finally:
        _return_conn(conn)


# ─── Ready Tokens Table Operations ──────────────────────────────────────────────

_db_token_lock = threading.Lock()


def add_ready_token_db(email: str, device_id: str, token: str):
    """Add a ready token to the database."""
    conn = _get_conn()
    if not conn:
        return False

    try:
        with conn.cursor() as cur:
            # Remove old entry for same email first
            cur.execute("DELETE FROM ready_tokens WHERE email = %s", (email,))
            cur.execute("""
                INSERT INTO ready_tokens (email, device_id, token)
                VALUES (%s, %s, %s)
            """, (email, device_id, token))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        log.error("[db] add_ready_token error: %s", e)
        return False
    finally:
        _return_conn(conn)


def pop_ready_token_db() -> dict:
    """Pop the last ready token from the database (LIFO). Thread-safe."""
    with _db_token_lock:
        conn = _get_conn()
        if not conn:
            return None

        try:
            with conn.cursor() as cur:
                # Get the last inserted token
                cur.execute("""
                    SELECT id, email, device_id, token FROM ready_tokens
                    ORDER BY id DESC LIMIT 1
                """)
                row = cur.fetchone()
                if not row:
                    return None

                token_id, email, device_id, token = row
                # Delete it
                cur.execute("DELETE FROM ready_tokens WHERE id = %s", (token_id,))
            conn.commit()

            return {
                "email": email,
                "device_id": device_id,
                "token": token,
                "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        except Exception as e:
            conn.rollback()
            log.error("[db] pop_ready_token error: %s", e)
            return None
        finally:
            _return_conn(conn)


def count_ready_tokens_db() -> int:
    """Count ready tokens in the database."""
    conn = _get_conn()
    if not conn:
        return 0

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM ready_tokens")
            return cur.fetchone()[0]
    except Exception as e:
        log.error("[db] count_ready_tokens error: %s", e)
        return 0
    finally:
        _return_conn(conn)


def get_ready_token_db() -> dict:
    """Get the last ready token without removing it."""
    conn = _get_conn()
    if not conn:
        return None

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT email, device_id, token FROM ready_tokens
                ORDER BY id DESC LIMIT 1
            """)
            row = cur.fetchone()
            if not row:
                return None
            return {
                "email": row[0],
                "device_id": row[1],
                "token": row[2],
                "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
    except Exception as e:
        log.error("[db] get_ready_token error: %s", e)
        return None
    finally:
        _return_conn(conn)


def cleanup_used_tokens_db(used_emails: set):
    """Remove ready tokens for emails that are in the used list."""
    if not used_emails:
        return 0

    conn = _get_conn()
    if not conn:
        return 0

    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ready_tokens WHERE email = ANY(%s)", (list(used_emails),))
            removed = cur.rowcount
        conn.commit()
        if removed > 0:
            log.info("[db] Cleaned up %d used tokens from database", removed)
        return removed
    except Exception as e:
        conn.rollback()
        log.error("[db] cleanup_used_tokens error: %s", e)
        return 0
    finally:
        _return_conn(conn)


# ─── Database Health Check ──────────────────────────────────────────────────────

def db_health() -> dict:
    """Check database connection health."""
    conn = _get_conn()
    if not conn:
        return {"ok": False, "error": "No connection"}

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            return {"ok": True, "connected": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        _return_conn(conn)


# ─── Clear All Data (for fresh start) ──────────────────────────────────────────

def clear_all_data():
    """Delete all data from all tables — use for fresh start."""
    conn = _get_conn()
    if not conn:
        return False

    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ready_tokens")
            cur.execute("DELETE FROM telicall_accounts")
            cur.execute("DELETE FROM bot_data")
        conn.commit()
        log.info("[db] All data cleared — fresh start")
        return True
    except Exception as e:
        conn.rollback()
        log.error("[db] clear_all_data error: %s", e)
        return False
    finally:
        _return_conn(conn)
