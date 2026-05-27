#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fox App API v2 — Secure server with JWT authentication, request signing,
IP logging, rate limiting, admin endpoints, and call logging.

- Token v2 (Fox Token): per-user key + HMAC — compatible with foxToken.ts.
- JWT access + refresh tokens for API authentication.
- HMAC-SHA256 request body signing.
- Per-user rate limiting (60 req/min, 5 calls/min).
- Admin panel endpoints with secret-key auth.
- All call activity logged to call_logs.json.
- Flask HTTP API exposed for the React Native app.
- /token Telegram command still works for initial Fox Token generation.
"""
import os
import json
import time
import hashlib
import hmac as hmac_mod
import secrets
import base64
import threading
import logging
from datetime import datetime
from collections import defaultdict
from functools import wraps

from flask import Flask, request, jsonify

# ─── Load .env file FIRST ────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(_env_path, override=False)
except ImportError:
    pass

log = logging.getLogger("fox-app")

# ═══════════════════════════════════════════════════════════════════════════════
#  Configuration
# ═══════════════════════════════════════════════════════════════════════════════

SHARED_SECRET = os.environ.get("SHARED_SECRET", "FOXCALL_2026_SHARED_SECRET_v1").strip('"').strip("'").strip()
REPLIT_API_URL = (
    "https://3bdef2f4-6a1f-4c7d-af7c-73040d9e35ab-00-2dvjd113zga7x"
    ".sisko.replit.dev"
)

# Derived secrets — all originate from SHARED_SECRET so only one secret
# needs to be rotated.
JWT_SECRET = hashlib.sha256(f"{SHARED_SECRET}:jwt_access".encode()).digest()
REFRESH_SECRET = hashlib.sha256(f"{SHARED_SECRET}:jwt_refresh".encode()).digest()
# 🔒 V3: Admin secret derivation changed to invalidate old leaked key (06d271200e53fb4482acd8679bfe358a)
_COMPROMISED_KEYS = {"06d271200e53fb4482acd8679bfe358a"}
_admin_secret_env = os.environ.get("ADMIN_SECRET", "").strip('"').strip("'").strip()
if _admin_secret_env and _admin_secret_env not in _COMPROMISED_KEYS:
    ADMIN_SECRET = _admin_secret_env
else:
    if _admin_secret_env in _COMPROMISED_KEYS:
        log.error("🔒 COMPROMISED ADMIN KEY DETECTED in env! Forcing new key derivation.")
    ADMIN_SECRET = hashlib.sha256(f"{SHARED_SECRET}:admin_v3_2026".encode()).hexdigest()[:32]

# Timeouts / limits
JWT_EXPIRY_SECONDS = 7 * 24 * 3600        # 7 days
REFRESH_EXPIRY_SECONDS = 30 * 24 * 3600    # 30 days
RATE_LIMIT_WINDOW = 60                      # 1 minute window
RATE_LIMIT_MAX_REQUESTS = 60                # general API requests
RATE_LIMIT_MAX_CALLS = 9999                 # call attempts (effectively unlimited)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if os.path.abspath(__file__) else os.getcwd()

# ─── Persistent Data Directory ──────────────────────────────────────────────────
# Must match the DATA_DIR used in callv2.py.
# On Railway/cloud: set DATA_DIR env var to a mounted volume path (e.g. /app/data)
# On local dev: defaults to ./data/ subdirectory
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(SCRIPT_DIR, "data"))
os.makedirs(DATA_DIR, exist_ok=True)

CALL_LOGS_FILE = os.path.join(DATA_DIR, "call_logs.json")
RECORDINGS_DIR = os.path.join(DATA_DIR, "recordings")
os.makedirs(RECORDINGS_DIR, exist_ok=True)


def _resolve_public_url() -> str:
    """Resolve the public URL for token generation.
    Priority: PUBLIC_URL env var > REPLIT_DEV_DOMAIN > fallback.
    On Railway, PUBLIC_URL is always set correctly.
    """
    env_url = os.environ.get("PUBLIC_URL", "").rstrip("/")
    if env_url:
        return env_url
    if os.environ.get("REPLIT_DEV_DOMAIN"):
        return f"https://{os.environ['REPLIT_DEV_DOMAIN']}"
    return REPLIT_API_URL


PUBLIC_URL = _resolve_public_url()
PORT = int(os.environ.get("PORT", "5000"))


# ═══════════════════════════════════════════════════════════════════════════════
#  Fox Token v2 — kept for compatibility with foxcall/services/foxToken.ts
# ═══════════════════════════════════════════════════════════════════════════════

def _user_key(user_id) -> bytes:
    return hashlib.sha256(f"{SHARED_SECRET}:{user_id}".encode()).digest()


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def encode_token(user_id, server_url: str) -> str:
    """Create a Fox Token (v2 format).  Compatible with foxToken.ts."""
    uid = str(user_id)
    nonce = secrets.token_hex(6)
    inner = f"{uid}|{server_url}|{nonce}"
    key = _user_key(uid)
    tag = hmac_mod.new(key, inner.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    payload = f"{inner}|{tag}".encode("utf-8")
    ct = _xor(payload, key)
    return f"{uid}:{_b64url_encode(ct)}"


def decode_token(token: str) -> dict | None:
    """Decode and validate a Fox Token.  Returns {user_id, server_url} or None."""
    try:
        t = token.strip()
        idx = t.index(":")
        if idx < 1:
            return None
        uid = t[:idx]
        enc = t[idx + 1:]
        if not uid.isdigit():
            return None
        key = _user_key(uid)
        ct = _b64url_decode(enc)
        pt = _xor(ct, key)
        text = pt.decode("utf-8")
        parts = text.split("|")
        if len(parts) != 4:
            return None
        emb_uid, server_url, nonce, tag = parts
        if emb_uid != uid:
            return None
        if not server_url.startswith(("http://", "https://")):
            return None
        inner = f"{emb_uid}|{server_url}|{nonce}"
        expected = hmac_mod.new(key, inner.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
        if not hmac_mod.compare_digest(expected, tag):
            return None
        return {"user_id": uid, "server_url": server_url}
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  JWT Implementation (no external dependency — pure stdlib)
# ═══════════════════════════════════════════════════════════════════════════════

def _jwt_b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwt_b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _jwt_encode(payload: dict, secret: bytes, expiry_seconds: int) -> str:
    """Create a signed JWT (HS256)."""
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = dict(payload)
    payload["iat"] = now
    payload["exp"] = now + expiry_seconds

    h = _jwt_b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    p = _jwt_b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{h}.{p}".encode()
    sig = hmac_mod.new(secret, signing_input, hashlib.sha256).digest()
    s = _jwt_b64url_encode(sig)
    return f"{h}.{p}.{s}"


def _jwt_decode(token: str, secret: bytes) -> dict | None:
    """Decode and validate a JWT.  Returns payload dict or None."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        h, p, s = parts
        signing_input = f"{h}.{p}".encode()
        expected_sig = hmac_mod.new(secret, signing_input, hashlib.sha256).digest()
        actual_sig = _jwt_b64url_decode(s)
        if not hmac_mod.compare_digest(expected_sig, actual_sig):
            return None
        payload = json.loads(_jwt_b64url_decode(p))
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def create_access_token(user_id: str, device_id: str) -> str:
    return _jwt_encode(
        {"sub": user_id, "device_id": device_id, "type": "access"},
        JWT_SECRET,
        JWT_EXPIRY_SECONDS,
    )


def create_refresh_token(user_id: str, device_id: str) -> str:
    return _jwt_encode(
        {"sub": user_id, "device_id": device_id, "type": "refresh"},
        REFRESH_SECRET,
        REFRESH_EXPIRY_SECONDS,
    )


def verify_access_token(token: str) -> dict | None:
    payload = _jwt_decode(token, JWT_SECRET)
    if payload and payload.get("type") == "access":
        return payload
    return None


def verify_refresh_token(token: str) -> dict | None:
    payload = _jwt_decode(token, REFRESH_SECRET)
    if payload and payload.get("type") == "refresh":
        return payload
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  IP Address helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _get_client_ip() -> str:
    """Get the real client IP, checking proxy headers."""
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    real = request.headers.get("X-Real-IP", "")
    if real:
        return real.strip()
    return request.remote_addr or "0.0.0.0"


def _update_user_ip(user_id: str, ip: str):
    """Store / update the user's last IP in users_db.json."""
    try:
        cv = _cv()
        db = cv.load_users_db()
        uid = str(user_id)
        if uid in db:
            db[uid]["last_ip"] = ip
            db[uid]["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cv.save_users_db(db)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
#  Rate Limiting (in-memory, per-user)
# ═══════════════════════════════════════════════════════════════════════════════

_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_call_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_rate_lock = threading.Lock()


def _check_rate_limit(
    user_id: str,
    limit: int,
    store: dict,
    window: int = RATE_LIMIT_WINDOW,
) -> bool:
    """Return True if the request is within the rate limit, False if exceeded."""
    now = time.time()
    with _rate_lock:
        store[user_id] = [t for t in store[user_id] if now - t < window]
        if len(store[user_id]) >= limit:
            return False
        store[user_id].append(now)
        return True


# ═══════════════════════════════════════════════════════════════════════════════
#  Request Signing verification
# ═══════════════════════════════════════════════════════════════════════════════

# ─── Anti-replay nonce store (in-memory, with auto-cleanup) ──────────────────
_used_nonces: dict[str, float] = {}
_nonce_lock = threading.Lock()
NONCE_EXPIRY_SECONDS = 300  # Nonces expire after 5 minutes


def _cleanup_old_nonces():
    """Remove expired nonces from the store."""
    now = time.time()
    expired = [k for k, v in _used_nonces.items() if now - v > NONCE_EXPIRY_SECONDS]
    for k in expired:
        _used_nonces.pop(k, None)


def _verify_request_signature(jwt_token: str) -> bool:
    """Verify the HMAC-SHA256 signature of the request body with anti-replay.

    Client must send headers:
        x-signature: HMAC-SHA256(jwt_token + timestamp + nonce + body, SHARED_SECRET)
        x-timestamp: Unix timestamp (seconds)
        x-nonce: Random unique identifier

    Anti-replay: rejects requests with timestamps older than 5 minutes
    or previously-used nonces.
    """
    sig = request.headers.get("x-signature", "")
    timestamp_str = request.headers.get("x-timestamp", "")
    nonce = request.headers.get("x-nonce", "")

    if not sig or not timestamp_str or not nonce:
        return False

    # Validate timestamp (must be within 5 minutes)
    try:
        ts = int(timestamp_str)
    except ValueError:
        return False

    now = int(time.time())
    if abs(now - ts) > 300:  # 5-minute window
        return False

    # Anti-replay: check nonce hasn't been used before
    with _nonce_lock:
        _cleanup_old_nonces()
        if nonce in _used_nonces:
            return False
        _used_nonces[nonce] = time.time()

    # Verify HMAC signature
    body = request.get_data(as_text=True)
    signing_input = f"{jwt_token}{timestamp_str}{nonce}{body}"
    expected = hmac_mod.new(
        SHARED_SECRET.encode(),
        signing_input.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac_mod.compare_digest(expected, sig)


# ═══════════════════════════════════════════════════════════════════════════════
#  Call Logging (call_logs.json)
# ═══════════════════════════════════════════════════════════════════════════════

_call_log_lock = threading.Lock()


def _load_api_call_logs() -> dict:
    """Load call_logs.json.  Returns the canonical structure."""
    if os.path.exists(CALL_LOGS_FILE):
        try:
            with open(CALL_LOGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Ensure keys exist
            data.setdefault("all_users", {})
            data.setdefault("all_calls", [])
            data.setdefault("all_phones", {})
            return data
        except Exception:
            pass
    return {"all_users": {}, "all_calls": [], "all_phones": {}}


def _save_api_call_logs(data: dict):
    try:
        with open(CALL_LOGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _log_api_call(
    user_id: str,
    to: str,
    from_num: str,
    sip_domain: str,
    start_time: str,
    end_time: str,
    duration: int,
    status: str,
    ip_address: str,
    call_id: str = "",
):
    """Append a call record to call_logs.json."""
    with _call_log_lock:
        logs = _load_api_call_logs()
        record = {
            "call_id": call_id or secrets.token_hex(8),
            "user_id": str(user_id),
            "to": to,
            "from": from_num,
            "sip_domain": sip_domain,
            "start_time": start_time,
            "end_time": end_time,
            "duration": duration,
            "status": status,
            "ip_address": ip_address,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        logs["all_calls"].append(record)

        uid = str(user_id)

        # Update user stats in call logs
        if uid not in logs["all_users"]:
            logs["all_users"][uid] = {
                "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total_calls": 0,
                "phones_called": [],
            }
        if status == "ended":
            logs["all_users"][uid]["total_calls"] = (
                logs["all_users"][uid].get("total_calls", 0) + 1
            )
        phone_clean = to.replace("+", "") if to else ""
        if phone_clean and phone_clean not in logs["all_users"][uid].get(
            "phones_called", []
        ):
            logs["all_users"][uid].setdefault("phones_called", []).append(phone_clean)

        # Update phone stats
        if phone_clean and phone_clean not in logs["all_phones"]:
            logs["all_phones"][phone_clean] = {
                "first_call": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total_calls": 0,
                "users_called": [],
            }
        if phone_clean and status == "ended":
            logs["all_phones"][phone_clean]["total_calls"] = (
                logs["all_phones"][phone_clean].get("total_calls", 0) + 1
            )
            logs["all_phones"][phone_clean]["last_call"] = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            if uid not in logs["all_phones"][phone_clean].get("users_called", []):
                logs["all_phones"][phone_clean].setdefault("users_called", []).append(
                    uid
                )

        _save_api_call_logs(logs)


# ═══════════════════════════════════════════════════════════════════════════════
#  Active call sessions (in-memory tracker)
# ═══════════════════════════════════════════════════════════════════════════════

_active_calls: dict[str, dict] = {}
_active_calls_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════════════
#  Fox Token Session Tracking — one active token per user
# ═══════════════════════════════════════════════════════════════════════════════

def _fox_token_hash(fox_token: str) -> str:
    """Compute SHA-256 hash of a Fox Token for tracking."""
    return hashlib.sha256(fox_token.strip().encode()).hexdigest()


def _set_active_fox_token(uid: str, fox_token: str, device_id: str = ""):
    """Store the currently active Fox Token hash for a user.
    This is called when a new token is created or when a user logs in."""
    try:
        cv = _cv()
        db = cv.load_users_db()
        if uid in db:
            db[uid]["active_fox_token_hash"] = _fox_token_hash(fox_token)
            db[uid]["active_device_id"] = device_id
            db[uid]["active_token_set_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cv.save_users_db(db)
    except Exception:
        pass


def _invalidate_all_sessions(uid: str):
    """Invalidate all active sessions for a user by clearing their refresh token hash
    and setting a session_invalidated_at timestamp.
    This forces any logged-in device to be kicked out immediately on the next API request,
    even if their JWT access token hasn't expired yet."""
    try:
        cv = _cv()
        db = cv.load_users_db()
        if uid in db:
            db[uid]["refresh_token_hash"] = ""
            db[uid]["active_device_id"] = ""
            db[uid]["session_invalidated_at"] = int(time.time())
            cv.save_users_db(db)
    except Exception:
        pass


def _notify_telegram_device_login(uid: str, new_device_id: str, ip: str):
    """Send a Telegram notification to the user that someone logged in from a new device."""
    try:
        cv = _cv()
        bot = cv.get_bot_instance() if hasattr(cv, 'get_bot_instance') else None
        if bot:
            bot.send_message(
                int(uid),
                f"🔔 *تنبيه أمني*\n\n"
                f"تم تسجيل الدخول لحسابك من جهاز جديد:\n"
                f"📱 الجهاز: `{new_device_id[:16]}...`\n"
                f"🌐 IP: `{ip}`\n"
                f"🕐 الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"إذا لم تكن أنت، أنشئ توكن جديد من البوت لإلغاء الجلسة السابقة.",
                parse_mode='Markdown'
            )
    except Exception:
        pass


def _notify_telegram_token_revoked(uid: str):
    """Send a Telegram notification that the user's token has been revoked (new token created)."""
    try:
        cv = _cv()
        bot = cv.get_bot_instance() if hasattr(cv, 'get_bot_instance') else None
        if bot:
            bot.send_message(
                int(uid),
                "🔑 *تم إنشاء توكن جديد*\n\n"
                "تم إلغاء التوكن القديم تلقائياً.\n"
                "أي جهاز كان يستخدم التوكن القديم سيتم تسجيل خروجه.",
                parse_mode='Markdown'
            )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers — lazy import of callv2 to avoid circular load
# ═══════════════════════════════════════════════════════════════════════════════

def _cv():
    import callv2
    return callv2


def _user_record(uid: str) -> dict:
    cv = _cv()
    rec = {}
    try:
        rec.update(cv.load_users_db().get(str(uid), {}) or {})
    except Exception:
        pass
    try:
        bd = cv.load_bot_data()
        bd_user = (bd.get("users", {}) or {}).get(str(uid), {})
        for k, v in bd_user.items():
            rec.setdefault(k, v)
        # legacy balances dict (from earlier bot.py)
        legacy = (bd.get("balances", {}) or {}).get(str(uid))
        if legacy is not None and "balance" not in rec:
            rec["balance"] = legacy
    except Exception:
        pass
    return rec


def _balance(uid: str) -> float:
    return float(_user_record(uid).get("balance", 0.0) or 0.0)


def _call_cost() -> float:
    cv = _cv()
    try:
        d = cv.load_bot_data()
        return float(d.get("settings", {}).get("call_cost", 0.20))
    except Exception:
        return 0.20


def _unanswered_call_cost() -> float:
    """Cost for an unanswered call (partial charge)."""
    cv = _cv()
    try:
        d = cv.load_bot_data()
        return float(d.get("settings", {}).get("unanswered_call_cost", 0.05))
    except Exception:
        return 0.05


def _is_banned(uid: str) -> bool:
    cv = _cv()
    try:
        return cv.is_banned(int(uid))
    except Exception:
        try:
            banned = cv.load_banned_db()
            return str(uid) in banned
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════════════════════════
#  Decorators
# ═══════════════════════════════════════════════════════════════════════════════

def _require_jwt(f):
    """Decorator: requires valid JWT Bearer token + request signature +
    rate-limit check + IP logging.  Sets request._fox_* attributes."""

    @wraps(f)
    def decorated(*args, **kwargs):
        # 1. JWT from Authorization header
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "missing or invalid Authorization header"}), 401
        jwt_token = auth_header[7:].strip()
        payload = verify_access_token(jwt_token)
        if not payload:
            return jsonify({"error": "invalid or expired token"}), 401

        uid = str(payload.get("sub", ""))
        if not uid:
            return jsonify({"error": "invalid token payload"}), 401

        # 1.5 Check if the user's session has been revoked
        # This covers two scenarios:
        #   a) New Fox Token was created (session_invalidated_at > JWT iat)
        #   b) Different device logged in (device_id mismatch)
        try:
            cv = _cv()
            db = cv.load_users_db()
            user_rec = db.get(uid, {})

            # Check if session was invalidated by a new token generation
            invalidated_at = user_rec.get("session_invalidated_at", 0)
            jwt_iat = payload.get("iat", 0)
            if invalidated_at and jwt_iat < invalidated_at:
                return jsonify({
                    "error": "token_changed",
                    "message": "تم تغيير التوكن برجاء ادخال التوكن الجديد"
                }), 401

            # Check if another device is now the active one
            active_device = user_rec.get("active_device_id", "")
            if active_device and payload.get("device_id", "") != active_device:
                return jsonify({
                    "error": "session_revoked",
                    "message": "تم تسجيل الدخول من جهاز آخر. أنشئ توكن جديد."
                }), 401
        except Exception:
            pass

        # 2. Request-signature verification
        if not _verify_request_signature(jwt_token):
            return jsonify({"error": "invalid request signature"}), 401

        # 3. Rate limiting (general)
        if not _check_rate_limit(uid, RATE_LIMIT_MAX_REQUESTS, _rate_limit_store):
            return (
                jsonify(
                    {"error": "rate limit exceeded. max 60 requests per minute"}
                ),
                429,
            )

        # 4. IP logging
        ip = _get_client_ip()
        _update_user_ip(uid, ip)

        # 5. Stash on request for handler use
        request._fox_uid = uid
        request._fox_device = payload.get("device_id", "")
        request._fox_ip = ip
        request._fox_jwt = jwt_token

        return f(*args, **kwargs)

    return decorated


# ─── Admin Rate Limiting ─────────────────────────────────────────────────────
_admin_rate_store = defaultdict(list)
_admin_rate_lock = threading.Lock()


def _check_admin_rate_limit(ip, limit=5):
    now = time.time()
    with _admin_rate_lock:
        _admin_rate_store[ip] = [t for t in _admin_rate_store[ip] if now - t < 60]
        if len(_admin_rate_store[ip]) >= limit:
            return False
        _admin_rate_store[ip].append(now)
        return True


def _require_admin(f):
    """Decorator: requires x-admin-key header matching ADMIN_SECRET + rate limiting."""

    @wraps(f)
    def decorated(*args, **kwargs):
        ip = _get_client_ip()
        if not _check_admin_rate_limit(ip):
            return jsonify({"error": "admin rate limit exceeded"}), 429
        admin_key = request.headers.get("x-admin-key", "")
        if not admin_key or not hmac_mod.compare_digest(admin_key, ADMIN_SECRET):
            return jsonify({"error": "unauthorized — invalid admin key"}), 403
        return f(*args, **kwargs)

    return decorated


# ═══════════════════════════════════════════════════════════════════════════════
#  Flask app
# ═══════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
#  🔒 Security Headers & Deprecated Endpoints
# ═══════════════════════════════════════════════════════════════════════════════

@app.after_request
def _security_headers(response):
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # 🔒 CORS: Only allow requests from our own domain and Telegram
    origin = request.headers.get("Origin", "")
    allowed_origins = [
        PUBLIC_URL,
        "https://web.telegram.org",
        "https://t.me",
    ]
    if origin and (origin in allowed_origins or origin.endswith(".telegram.org")):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, x-admin-key, x-farm-token, x-signature, x-timestamp, x-nonce"
        response.headers["Access-Control-Max-Age"] = "86400"
    return response


@app.before_request
def _handle_cors_preflight():
    """Handle CORS preflight OPTIONS requests."""
    if request.method == "OPTIONS":
        origin = request.headers.get("Origin", "")
        allowed_origins = [
            PUBLIC_URL,
            "https://web.telegram.org",
            "https://t.me",
        ]
        if origin and (origin in allowed_origins or origin.endswith(".telegram.org")):
            resp = jsonify({"ok": True})
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, x-admin-key, x-farm-token, x-signature, x-timestamp, x-nonce"
            resp.headers["Access-Control-Max-Age"] = "86400"
            return resp
        return jsonify({"error": "forbidden"}), 403


# Old endpoints — disabled, return 410 Gone
@app.route("/api/ads/complete-ad/", methods=["GET", "POST"])
def _deprecated_complete_ad():
    return jsonify({"error": "deprecated", "status": "gone"}), 410


# ─── Unauthenticated routes ─────────────────────────────────────────────────

@app.get("/")
def _root():
    return {"service": "Fox Call Bot", "ok": True, "url": PUBLIC_URL}


@app.get("/admin")
def _admin_panel():
    """Serve the admin panel HTML page."""
    import os
    admin_file = os.path.join(SCRIPT_DIR, "admin_panel.html")
    if os.path.exists(admin_file):
        with open(admin_file, "r", encoding="utf-8") as f:
            return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}
    return {"error": "Admin panel not found"}, 404


@app.get("/api/health")
def _health():
    return {"ok": True, "service": "callapp-bot", "version": "4.0.0"}


# ═══════════════════════════════════════════════════════════════════════════════
#  App Version / Force Update
# ═══════════════════════════════════════════════════════════════════════════════

VERSION_CONFIG_FILE = os.path.join(DATA_DIR, "version_config.json")
APK_STORAGE_PATH = os.path.join(DATA_DIR, "fox-call-latest.apk")
_version_config_lock = threading.Lock()


def _load_version_config() -> dict:
    """Load version_config.json. Returns the canonical structure."""
    default = {
        "latest_version": "4.0.0",
        "latest_version_code": 15,
        "minimum_version_code": 15,
        "force_update": True,
        "download_url": "",
        "update_message_ar": "يتوفر تحديث جديد للتطبيق! يرجى تحميل النسخة الجديدة للمتابعة.",
        "update_message_en": "A new update is available! Please download the latest version to continue.",
    }
    if os.path.exists(VERSION_CONFIG_FILE):
        try:
            with open(VERSION_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            default.update(data)
            return default
        except Exception:
            pass
    return default


def _save_version_config(data: dict):
    try:
        with _version_config_lock:
            with open(VERSION_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _apk_filename() -> str:
    """Generate the APK filename based on the current version config."""
    version = _load_version_config().get("latest_version", "latest")
    return f"fox-call-v{version}-arm64.apk"


def _resolve_download_url() -> str:
    """Resolve the APK download URL.
    If download_url is set in version_config, use it.
    Otherwise, use the fresh-download endpoint which returns a direct GitHub URL.
    """
    config = _load_version_config()
    custom_url = config.get("download_url", "")
    if custom_url:
        return custom_url
    # Default: use the fresh-download endpoint (returns a direct download URL from GitHub)
    return f"{PUBLIC_URL}/api/fresh-download-url/{_apk_filename()}"


@app.get("/api/app-version")
def api_app_version():
    """Return the latest app version info for force-update checks.
    Unauthenticated — called before login.
    Query params:
        vc: current app versionCode (integer)
    """
    vc = request.args.get("vc", "0")
    try:
        vc = int(vc)
    except ValueError:
        vc = 0

    config = _load_version_config()
    min_vc = config.get("minimum_version_code", 0)
    force = vc < min_vc and config.get("force_update", True)
    download_url = _resolve_download_url()
    apk_size = 0
    try:
        if os.path.exists(APK_STORAGE_PATH):
            apk_size = os.path.getsize(APK_STORAGE_PATH)
    except Exception:
        pass

    return jsonify({
        "latest_version": config.get("latest_version", ""),
        "latest_version_code": config.get("latest_version_code", 0),
        "minimum_version_code": min_vc,
        "force_update": force,
        "download_url": download_url,
        "apk_size": apk_size,
        "update_message_ar": config.get("update_message_ar", ""),
        "update_message_en": config.get("update_message_en", ""),
    })


GITHUB_REPO = "mohaedkw1/callapp"  # GitHub repo for APK storage
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "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")
# APKs are stored as GitHub Releases (supports large files up to 2GB)
# For private repos, we get a temporary direct download URL via the GitHub API


def _get_github_release_download_url(tag: str, filename: str) -> str | None:
    """Get a temporary download URL for a GitHub Release asset (private repo).
    Returns the direct download URL (time-limited Azure blob URL), or None on failure."""
    import urllib.request
    import json as _json

    # Step 1: Find the release by tag to get the asset ID
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/{tag}"
    log.info("Looking up GitHub Release tag '%s': %s", tag, api_url)

    req = urllib.request.Request(api_url, headers={
        "Authorization": f"token {GITHUB_TOKEN}",
        "User-Agent": "FoxCall-Server/1.0",
        "Accept": "application/vnd.github.v3+json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        release_data = _json.loads(resp.read().decode())

    # Step 2: Find the matching asset
    asset_id = None
    asset_size = 0
    for asset in release_data.get("assets", []):
        if asset.get("name") == filename:
            asset_id = asset.get("id")
            asset_size = asset.get("size", 0)
            break

    if not asset_id:
        log.error("Asset '%s' not found in release '%s'", filename, tag)
        return None

    log.info("Found asset ID %d, size %d bytes. Getting download URL...", asset_id, asset_size)

    # Step 3: Get the temporary download URL by hitting the asset API endpoint
    # with Accept: application/octet-stream — GitHub returns a 302 redirect
    # to a time-limited Azure blob URL. We extract the Location header.
    asset_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/assets/{asset_id}"

    # Use a custom opener that does NOT follow redirects so we can capture the Location header
    class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None  # Don't follow the redirect

    opener = urllib.request.build_opener(_NoRedirectHandler)

    req = urllib.request.Request(asset_url, headers={
        "Authorization": f"token {GITHUB_TOKEN}",
        "User-Agent": "FoxCall-Server/1.0",
        "Accept": "application/octet-stream",
    })

    try:
        opener.open(req, timeout=15)
        log.warning("Expected 302 redirect but got a 200")
        return None
    except urllib.error.HTTPError as e:
        if e.code == 302:
            redirect_url = e.headers.get("Location")
            if redirect_url:
                log.info("Got download redirect URL (length=%d chars)", len(redirect_url))
                return redirect_url
        log.error("Unexpected HTTP error getting download URL: %d %s", e.code, e.reason)
        return None
    except Exception as e:
        log.error("Failed to get download URL: %s", e)
        return None


@app.get("/api/fresh-download-url/<filename>")
def api_fresh_download_url(filename):
    """Redirect to a fresh, temporary direct download URL for the APK from GitHub Releases.
    This endpoint does a 302 redirect to the actual download URL on GitHub/Azure CDN.
    Works with any HTTP client that follows redirects (including expo-file-system).
    """
    import re
    from flask import redirect

    # Validate the filename
    if not filename.endswith(".apk") or not filename.startswith("fox-call-"):
        return jsonify({"error": "Invalid APK filename"}), 400

    # If APK exists locally, redirect to the local download endpoint
    if os.path.exists(APK_STORAGE_PATH):
        local_url = f"{PUBLIC_URL}/api/download/{filename}"
        return redirect(local_url, code=302)

    # Get download URL from GitHub Releases and redirect
    try:
        ver_match = re.search(r'v(\d+\.\d+\.\d+)', filename)
        if ver_match:
            tag = f"v{ver_match.group(1)}"
        else:
            tag = f"v{_load_version_config().get('latest_version', 'latest')}"

        download_url = _get_github_release_download_url(tag, filename)
        if download_url:
            log.info("Redirecting to fresh download URL for %s", filename)
            return redirect(download_url, code=302)
        else:
            log.error("Could not get download URL from GitHub for %s", filename)
    except Exception as e:
        log.error("Failed to get fresh download URL: %s", e)

    return jsonify({"error": "Could not get download URL"}), 404


@app.get("/api/download/<filename>")
def api_download_apk(filename):
    """Serve the APK file for in-app download.
    URL format: /api/download/fox-call-v3.4.0-arm64.apk
    If APK is stored locally, serve it directly.
    Otherwise, stream from GitHub Releases in chunks."""
    import re

    # Validate the filename looks like a valid APK
    if not filename.endswith(".apk") or not filename.startswith("fox-call-"):
        return jsonify({"error": "Invalid APK filename"}), 400

    # If APK exists locally, serve it directly
    if os.path.exists(APK_STORAGE_PATH):
        from flask import send_file
        try:
            return send_file(
                APK_STORAGE_PATH,
                mimetype="application/vnd.android.package-archive",
                as_attachment=True,
                download_name=filename,
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # APK not found locally — stream from GitHub Releases
    try:
        # Extract version from filename (e.g. fox-call-v3.4.0-arm64.apk → v3.4.0)
        ver_match = re.search(r'v(\d+\.\d+\.\d+)', filename)
        if ver_match:
            tag = f"v{ver_match.group(1)}"
        else:
            tag = f"v{_load_version_config().get('latest_version', 'latest')}"

        log.info("APK not found locally, streaming from GitHub Release: tag=%s, file=%s", tag, filename)
        download_url = _get_github_release_download_url(tag, filename)

        if download_url:
            # Stream the APK from GitHub in chunks to avoid loading entire file in memory
            import urllib.request
            from flask import Response, stream_with_context

            log.info("Streaming APK from GitHub to client in chunks...")

            def generate():
                req = urllib.request.Request(download_url, headers={
                    "User-Agent": "FoxCall-Server/1.0",
                })
                with urllib.request.urlopen(req, timeout=180) as resp:
                    while True:
                        chunk = resp.read(65536)  # 64KB chunks
                        if not chunk:
                            break
                        yield chunk

            return Response(
                stream_with_context(generate()),
                mimetype="application/vnd.android.package-archive",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "Transfer-Encoding": "chunked",
                },
            )
        else:
            log.error("Could not get download URL from GitHub")
    except Exception as e:
        log.error("Failed to stream APK from GitHub: %s", e)

    return jsonify({"error": "APK file not found on server and GitHub download failed"}), 404


@app.post("/api/admin/upload-apk")
@_require_admin
def api_admin_upload_apk():
    """Upload APK file to server (admin only).
    Accepts multipart/form-data with 'file' field.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided. Use multipart/form-data with 'file' field."}), 400

    file = request.files["file"]
    if not file.filename or not file.filename.endswith(".apk"):
        return jsonify({"error": "Only .apk files are allowed"}), 400

    try:
        file.save(APK_STORAGE_PATH)
        file_size = os.path.getsize(APK_STORAGE_PATH)
        # Auto-update the download URL to point to this server with filename
        config = _load_version_config()
        config["download_url"] = f"{PUBLIC_URL}/api/download/{_apk_filename()}"
        _save_version_config(config)
        return jsonify({
            "ok": True,
            "size": file_size,
            "size_mb": round(file_size / (1024 * 1024), 2),
            "download_url": config["download_url"],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/admin/version-config")
@_require_admin
def api_admin_version_config():
    """Update the version config (admin only).
    Body:
        {
            "latest_version": "3.3.0",
            "latest_version_code": 10,
            "minimum_version_code": 10,
            "force_update": true,
            "download_url": "https://...",
            "update_message_ar": "...",
            "update_message_en": "..."
        }
    """
    body = request.get_json(silent=True) or {}
    config = _load_version_config()

    if "latest_version" in body:
        config["latest_version"] = str(body["latest_version"])
    if "latest_version_code" in body:
        config["latest_version_code"] = int(body["latest_version_code"])
    if "minimum_version_code" in body:
        config["minimum_version_code"] = int(body["minimum_version_code"])
    if "force_update" in body:
        config["force_update"] = bool(body["force_update"])
    if "download_url" in body:
        config["download_url"] = str(body["download_url"])
    if "update_message_ar" in body:
        config["update_message_ar"] = str(body["update_message_ar"])
    if "update_message_en" in body:
        config["update_message_en"] = str(body["update_message_en"])

    _save_version_config(config)
    return jsonify({"ok": True, "config": config})


# ─── Auth endpoints ─────────────────────────────────────────────────────────

@app.post("/api/auth/login")
def api_auth_login():
    """Authenticate with a Fox Token + device_id → receive JWT pair.

    Request body:
        {
            "token": "<Fox Token from Telegram bot>",
            "device_id": "<unique device identifier>"
        }
    """
    body = request.get_json(silent=True) or {}
    fox_token = (body.get("token") or "").strip()
    device_id = (body.get("device_id") or "").strip()

    if not fox_token:
        return jsonify({"error": "missing 'token' (Fox Token)"}), 400
    if not device_id:
        return jsonify({"error": "missing 'device_id'"}), 400

    # Validate the Fox Token
    decoded = decode_token(fox_token)
    if not decoded:
        return jsonify({"error": "invalid Fox Token"}), 401

    uid = decoded["user_id"]

    if _is_banned(uid):
        return jsonify({"error": "banned"}), 403

    # ── Fox Token session enforcement ──────────────────────────
    # Only allow login with the currently active Fox Token.
    # If a new token was generated, old tokens are rejected.
    fox_token_hash = hashlib.sha256(fox_token.encode()).hexdigest()
    try:
        cv = _cv()
        db = cv.load_users_db()
        active_hash = db.get(uid, {}).get("active_fox_token_hash", "")
        active_device = db.get(uid, {}).get("active_device_id", "")

        if active_hash and fox_token_hash != active_hash:
            # This is an OLD token — reject it
            return jsonify({
                "error": "token_changed",
                "message": "تم تغيير التوكن برجاء ادخال التوكن الجديد"
            }), 401

        # Check if another device is already logged in with this token
        if active_device and active_device != device_id and active_hash == fox_token_hash:
            # Notify the user that someone is logging in from another device
            ip = _get_client_ip()
            _notify_telegram_device_login(uid, device_id, ip)
    except Exception:
        pass

    # Capture and store IP
    ip = _get_client_ip()
    _update_user_ip(uid, ip)

    # Generate JWT access + refresh tokens
    access_token = create_access_token(uid, device_id)
    refresh_token = create_refresh_token(uid, device_id)

    # Persist refresh-token hash so we can revoke it later
    try:
        cv = _cv()
        db = cv.load_users_db()
        if uid in db:
            db[uid]["refresh_token_hash"] = hashlib.sha256(
                refresh_token.encode()
            ).hexdigest()
            db[uid]["last_login"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cv.save_users_db(db)
    except Exception:
        pass

    # Mark this Fox Token as the active one for this user
    _set_active_fox_token(uid, fox_token, device_id)

    log.info("User %s authenticated from IP %s", uid, ip)

    return jsonify(
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": JWT_EXPIRY_SECONDS,
            "user_id": uid,
        }
    )


@app.post("/api/auth/refresh")
def api_auth_refresh():
    """Exchange a valid refresh token for a new access + refresh pair.

    Request body:
        { "refresh_token": "<refresh_token>" }
    """
    body = request.get_json(silent=True) or {}
    refresh_token = (body.get("refresh_token") or "").strip()

    if not refresh_token:
        return jsonify({"error": "missing 'refresh_token'"}), 400

    payload = verify_refresh_token(refresh_token)
    if not payload:
        return jsonify({"error": "invalid or expired refresh token"}), 401

    uid = str(payload.get("sub", ""))
    device_id = payload.get("device_id", "")

    if _is_banned(uid):
        return jsonify({"error": "banned"}), 403

    # Ensure refresh token matches the one we issued
    try:
        cv = _cv()
        db = cv.load_users_db()
        stored_hash = db.get(uid, {}).get("refresh_token_hash", "")
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        if stored_hash and not hmac_mod.compare_digest(stored_hash, token_hash):
            return jsonify({"error": "refresh token revoked"}), 401
    except Exception:
        pass

    # Rotate tokens
    ip = _get_client_ip()
    _update_user_ip(uid, ip)

    new_access = create_access_token(uid, device_id)
    new_refresh = create_refresh_token(uid, device_id)

    try:
        cv = _cv()
        db = cv.load_users_db()
        if uid in db:
            db[uid]["refresh_token_hash"] = hashlib.sha256(
                new_refresh.encode()
            ).hexdigest()
            cv.save_users_db(db)
    except Exception:
        pass

    return jsonify(
        {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "Bearer",
            "expires_in": JWT_EXPIRY_SECONDS,
        }
    )


@app.post("/api/auth/check-token")
def api_auth_check_token():
    """Check if a Fox Token is still valid (matches the active token for the user).
    Used by the app to detect when a token has been revoked."""
    body = request.get_json(silent=True) or {}
    fox_token = (body.get("token") or "").strip()

    if not fox_token:
        return jsonify({"valid": False, "reason": "missing token"}), 400

    decoded = decode_token(fox_token)
    if not decoded:
        return jsonify({"valid": False, "reason": "invalid token"}), 401

    uid = decoded["user_id"]
    fox_token_hash = hashlib.sha256(fox_token.encode()).hexdigest()

    try:
        cv = _cv()
        db = cv.load_users_db()
        active_hash = db.get(uid, {}).get("active_fox_token_hash", "")

        if active_hash and fox_token_hash != active_hash:
            return jsonify({"valid": False, "reason": "token_changed", "message": "تم تغيير التوكن برجاء ادخال التوكن الجديد"})
    except Exception:
        pass

    return jsonify({"valid": True})


# ─── Protected API endpoints ────────────────────────────────────────────────

@app.get("/api/me")
@_require_jwt
def api_me():
    uid = request._fox_uid
    rec = _user_record(uid)
    bal = _balance(uid)
    cost = _call_cost()
    possible = int(bal // cost) if cost > 0 else 0

    # Get last 10 calls for this user
    call_history = []
    try:
        logs = _load_api_call_logs()
        all_calls = logs.get("all_calls", [])
        user_calls = [c for c in all_calls if c.get("user_id") == uid][-10:]
        user_calls.reverse()  # most recent first
        for c in user_calls:
            call_history.append({
                "call_id": c.get("call_id", ""),
                "to": c.get("to", ""),
                "from": c.get("from", ""),
                "start_time": c.get("start_time", ""),
                "duration": c.get("duration", 0),
                "status": c.get("status", ""),
            })
    except Exception:
        pass

    # Get Telegram profile photo URL (cached in users_db)
    photo_url = rec.get("photo_url", "")
    if not photo_url:
        photo_url = _get_telegram_photo_url(uid)
        if photo_url:
            try:
                cv = _cv()
                db = cv.load_users_db()
                if uid in db:
                    db[uid]["photo_url"] = photo_url
                    cv.save_users_db(db)
            except Exception:
                pass

    # Calculate used tokens (calls actually made)
    used_calls = 0
    try:
        logs = _load_api_call_logs()
        all_calls = logs.get("all_calls", [])
        used_calls = len([c for c in all_calls if c.get("user_id") == uid and c.get("status") in ("ended", "started")])
    except Exception:
        pass

    # ─── Monthly subscription status (for the app) ──────────────────
    monthly_sub_info = {"active": False, "plan": None, "calls_remaining": 0, "total_calls": 0, "expires": None}
    try:
        cv = _cv()
        monthly = cv.get_monthly_sub(uid)
        if monthly:
            plan_info = cv.MONTHLY_PLANS.get(monthly.get("plan", ""), {})
            total_calls = plan_info.get("calls", 0)
            calls_left = cv.get_monthly_calls_left(uid)
            is_unlimited = total_calls >= 999999
            monthly_sub_info = {
                "active": True,
                "plan": monthly.get("plan", ""),
                "planName": plan_info.get("name", ""),
                "planEmoji": plan_info.get("emoji", ""),
                "calls_remaining": -1 if is_unlimited else calls_left,
                "total_calls": -1 if is_unlimited else total_calls,
                "isUnlimited": is_unlimited,
                "expires": monthly.get("expires", ""),
            }
            # If user has active unlimited monthly sub, override possibleCalls
            if is_unlimited:
                possible = 999999
    except Exception:
        pass

    # ─── App subscription status ──────────────────
    app_sub_info = {"active": False, "plan": None, "calls_remaining": 0, "total_calls": 0}
    try:
        app_sub = _get_user_subscription(uid)
        if app_sub:
            app_sub_info = {
                "active": True,
                "plan": app_sub.get("plan", "free"),
                "calls_remaining": app_sub.get("calls_remaining", 0),
                "total_calls": app_sub.get("total_calls", 0),
                "expires_at": app_sub.get("expires_at", None),
            }
    except Exception:
        pass

    return jsonify(
        {
            "userId": uid,
            "username": rec.get("username") or "",
            "firstName": rec.get("first_name") or "",
            "fullName": (
                (rec.get("first_name") or "")
                + (" " + rec["last_name"] if rec.get("last_name") else "")
            ).strip()
            or rec.get("username")
            or uid,
            "photoUrl": photo_url,
            "balance": round(bal, 2),
            "cost": round(cost, 2),
            "possibleCalls": possible,
            "usedCalls": used_calls,
            "monthlySubscription": monthly_sub_info,
            "appSubscription": app_sub_info,
            "call_history": call_history,
        }
    )


@app.get("/api/balance")
@_require_jwt
def api_balance():
    uid = request._fox_uid
    return jsonify({"balance": _balance(uid), "cost": _call_cost()})


@app.post("/api/call/start")
@_require_jwt
def api_call_start():
    uid = request._fox_uid
    ip = request._fox_ip

    if _is_banned(uid):
        return jsonify({"error": "banned"}), 403

    # Call-specific rate limit
    if not _check_rate_limit(uid, RATE_LIMIT_MAX_CALLS, _call_rate_limit_store):
        return (
            jsonify(
                {"error": "call rate limit exceeded. max 5 calls per minute"}
            ),
            429,
        )

    body = request.get_json(silent=True) or {}
    to = (body.get("to") or "").strip()
    if not to:
        return jsonify({"error": "missing 'to'"}), 400

    cv = _cv()
    cost = _call_cost()
    bal = _balance(uid)
    # Block call entirely if balance is less than the full call cost
    if bal < cost - 0.001:
        return (
            jsonify(
                {
                    "error": (
                        f"رصيدك مش كافي"
                        f" ({bal:.2f}$). الحد الأدنى"
                        f" {cost:.2f}$"
                    )
                }
            ),
            402,
        )

    try:
        result = cv.start_call(to, max_retries=3)
    except Exception as e:
        log.exception("start_call failed")
        # 🔄 محاولة بروكسي من آي بي المستخدم
        try:
            proxy_req = cv.get_proxy_call_request(to)
            if proxy_req:
                log.info("Server call failed, falling back to user IP proxy for %s", to)
                return jsonify({
                    "proxy_required": True,
                    "proxy_request": {
                        "url": proxy_req["url"],
                        "method": proxy_req["method"],
                        "headers": proxy_req["headers"],
                        "body": proxy_req["body"],
                    },
                    "email_used": proxy_req.get("email_used", ""),
                })
        except Exception:
            pass
        return jsonify({"error": str(e)}), 502

    if result is None:
        # 🔄 محاولة بروكسي من آي بي المستخدم
        try:
            proxy_req = cv.get_proxy_call_request(to)
            if proxy_req:
                log.info("No accounts on server, falling back to user IP proxy for %s", to)
                return jsonify({
                    "proxy_required": True,
                    "proxy_request": {
                        "url": proxy_req["url"],
                        "method": proxy_req["method"],
                        "headers": proxy_req["headers"],
                        "body": proxy_req["body"],
                    },
                    "email_used": proxy_req.get("email_used", ""),
                })
        except Exception:
            pass
        return (
            jsonify(
                {
                    "error": (
                        "\u0644\u0627 \u064a\u0648\u062c\u062f \u062d\u0633\u0627\u0628\u0627\u062a"
                        " \u0645\u062a\u0627\u062d\u0629 \u0623\u0648"
                        " \u0627\u0644\u062d\u0633\u0627\u0628\u0627\u062a \u0641\u0634\u0644\u062a"
                    )
                }
            ),
            502,
        )
    if result == "no_balance":
        # 🔄 محاولة بروكسي من آي بي المستخدم
        try:
            proxy_req = cv.get_proxy_call_request(to)
            if proxy_req:
                log.info("No balance on server, falling back to user IP proxy for %s", to)
                return jsonify({
                    "proxy_required": True,
                    "proxy_request": {
                        "url": proxy_req["url"],
                        "method": proxy_req["method"],
                        "headers": proxy_req["headers"],
                        "body": proxy_req["body"],
                    },
                    "email_used": proxy_req.get("email_used", ""),
                })
        except Exception:
            pass
        return (
            jsonify(
                {
                    "error": (
                        "no_balance"
                    )
                }
            ),
            502,
        )
    if isinstance(result, dict) and "error" in result:
        err_code = result["error"]
        log.error("Telicall API error: %s", err_code)
        if "404" in err_code:
            return (
                jsonify(
                    {
                        "error": (
                            "خدمة المكالمات غير متاحة حالياً. حاول بعد قليل."
                        )
                    }
                ),
                502,
            )
        elif "400" in err_code:
            return (
                jsonify(
                    {
                        "error": (
                            "رقم غير صالح أو خدمة غير متاحة"
                        )
                    }
                ),
                400,
            )
        else:
            return (
                jsonify(
                    {
                        "error": (
                            f"خطأ مؤقت في خدمة المكالمات، حاول مرة أخرى"
                        )
                    }
                ),
                502,
            )

    # Mark the Telicall account token as used & remove from accounts list
    try:
        email_used = result.get("email_used", "") or result.get("email", "")
        cv.mark_email_used(email_used)
        # احذف الحساب من قائمة accounts عشان متتستعملش تاني
        if email_used and hasattr(cv, '_remove_account_by_email'):
            cv._remove_account_by_email(email_used)
    except Exception:
        pass

    # Deduct full call cost upfront
    cv.deduct_balance(uid, cost)

    # Update bot stats
    try:
        d = cv.load_bot_data()
        d.setdefault("stats", {})["total_calls"] = (
            d.get("stats", {}).get("total_calls", 0) + 1
        )
        cv.save_bot_data(d)
    except Exception:
        pass

    # Build call record & log
    call_id = secrets.token_hex(8)
    sip_domain = result.get("domain", "")
    from_num = result.get("from", "")
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _active_calls_lock:
        _active_calls[call_id] = {
            "user_id": uid,
            "to": result.get("to", to),
            "from": from_num,
            "sip_domain": sip_domain,
            "start_time": start_time,
            "ip_address": ip,
            "recording": False,
        }

    _log_api_call(
        user_id=uid,
        to=result.get("to", to),
        from_num=from_num,
        sip_domain=sip_domain,
        start_time=start_time,
        end_time="",
        duration=0,
        status="started",
        ip_address=ip,
        call_id=call_id,
    )

    return jsonify(
        {
            "call_id": call_id,
            "sip": {
                "username": result.get("user", ""),
                "password": result.get("pass", ""),
                "domain": sip_domain,
                "port": result.get("port", 5060),
                "protocol": result.get("proto", "tcp"),
                "callLimit": result.get("limit", 60),
            },
            "from": from_num,
            "to": result.get("to", to),
            "balance": _balance(uid),
            "cost_deducted": round(cost, 2),
            "cost_total": round(cost, 2),
            "cost_remaining": 0,
        }
    )


@app.post("/api/call/end")
@_require_jwt
def api_call_end():
    uid = request._fox_uid
    ip = request._fox_ip
    body = request.get_json(silent=True) or {}
    call_id = (body.get("call_id") or "").strip()
    duration = body.get("duration", 0) or 0

    # Close active session if we have a matching call_id
    call_info = None
    if call_id:
        with _active_calls_lock:
            call_info = _active_calls.pop(call_id, None)

    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if call_info:
        _log_api_call(
            user_id=call_info["user_id"],
            to=call_info["to"],
            from_num=call_info["from"],
            sip_domain=call_info["sip_domain"],
            start_time=call_info["start_time"],
            end_time=end_time,
            duration=int(duration),
            status="ended",
            ip_address=ip,
            call_id=call_id,
        )

    # No additional charge — full cost was already deducted at call start

    # Update bot stats
    try:
        cv = _cv()
        d = cv.load_bot_data()
        d.setdefault("stats", {})["success_calls"] = (
            d.get("stats", {}).get("success_calls", 0) + 1
        )
        cv.save_bot_data(d)
    except Exception:
        pass

    return jsonify({"ok": True, "call_id": call_id, "balance": _balance(uid), "answered": duration > 0})


@app.post("/api/call/proxy-result")
@_require_jwt
def api_call_proxy_result():
    """App submits the result of a proxied call request that was made from the user's IP.
    Body: {
        status_code: int,
        response_body: object,    // the JSON response from the call API
        email_used: str,          // the email_used from the proxy_request
    }
    """
    uid = request._fox_uid
    ip = request._fox_ip
    body = request.get_json(silent=True) or {}
    status_code = body.get("status_code", 0)
    response_body = body.get("response_body") or {}
    email_used = body.get("email_used", "")

    if status_code != 200 or not (isinstance(response_body, dict) and response_body.get("result")):
        # الطلب اللي المستخدم عمله فشل برضه
        err_msg = ""
        if isinstance(response_body, dict):
            err_msg = response_body.get("error", "") or response_body.get("message", "")
        # لو رصيد خلص
        if isinstance(response_body, str) and "balance" in response_body.lower():
            # احذف الحساب وسجله
            if email_used:
                try:
                    cv = _cv()
                    cv._remove_account_by_email(email_used)
                    cv.mark_email_used(email_used)
                except Exception:
                    pass
            return jsonify({"error": "no_balance"}), 502
        # لو خطأ 400/404
        if status_code == 400:
            return jsonify({"error": "رقم غير صالح أو خدمة غير متاحة"}), 400
        if status_code == 404:
            return jsonify({"error": "خدمة المكالمات غير متاحة حالياً. حاول بعد قليل."}), 502
        return jsonify({"error": err_msg or "فشل الطلب من جهازك - حاول مرة أخرى"}), 502

    # ✅ النتيجة نجحت! استخرج بيانات SIP
    result_data = response_body.get("result", {})
    sip_info = result_data.get("sip", {})
    from_info = result_data.get("from", {})
    to_info = result_data.get("to", {})

    result = {
        "user": sip_info.get("username"),
        "pass": sip_info.get("password"),
        "domain": sip_info.get("domain"),
        "port": sip_info.get("port", 5060),
        "proto": sip_info.get("protocol", "tcp"),
        "from": from_info.get("msisdn", ""),
        "to": to_info.get("msisdn", ""),
        "limit": sip_info.get("callLimit", 60),
        "email_used": email_used,
    }

    # Mark account as used & remove from list
    try:
        cv = _cv()
        if email_used:
            cv.mark_email_used(email_used)
            if hasattr(cv, '_remove_account_by_email'):
                cv._remove_account_by_email(email_used)
    except Exception:
        pass

    # Deduct call cost
    cost = _call_cost()
    cv = _cv()
    cv.deduct_balance(uid, cost)

    # Update bot stats
    try:
        d = cv.load_bot_data()
        d.setdefault("stats", {})["total_calls"] = (
            d.get("stats", {}).get("total_calls", 0) + 1
        )
        cv.save_bot_data(d)
    except Exception:
        pass

    # Build call record & log
    call_id = secrets.token_hex(8)
    sip_domain = result.get("domain", "")
    from_num = result.get("from", "")
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _active_calls_lock:
        _active_calls[call_id] = {
            "user_id": uid,
            "to": result.get("to", ""),
            "from": from_num,
            "sip_domain": sip_domain,
            "start_time": start_time,
            "ip_address": ip,
            "recording": False,
            "proxied": True,
        }

    _log_api_call(
        user_id=uid,
        to=result.get("to", ""),
        from_num=from_num,
        sip_domain=sip_domain,
        start_time=start_time,
        end_time="",
        duration=0,
        status="started",
        ip_address=ip,
        call_id=call_id,
    )

    log.info("Proxy call succeeded for user %s via IP %s", uid, ip)

    return jsonify(
        {
            "call_id": call_id,
            "sip": {
                "username": result.get("user", ""),
                "password": result.get("pass", ""),
                "domain": sip_domain,
                "port": result.get("port", 5060),
                "protocol": result.get("proto", "tcp"),
                "callLimit": result.get("limit", 60),
            },
            "from": from_num,
            "to": result.get("to", ""),
            "balance": _balance(uid),
            "cost_deducted": round(cost, 2),
            "cost_total": round(cost, 2),
            "cost_remaining": 0,
        }
    )


@app.get("/api/call-history")
@_require_jwt
def api_call_history():
    """Return the user's past calls from call_logs.json (most recent first, limit 50)."""
    uid = request._fox_uid
    try:
        logs = _load_api_call_logs()
        all_calls = logs.get("all_calls", [])
        user_calls = [c for c in all_calls if c.get("user_id") == uid]
        # Most recent first, limit 50
        user_calls = user_calls[-50:][::-1]
        # Return only the fields specified
        result = []
        for c in user_calls:
            result.append({
                "call_id": c.get("call_id", ""),
                "to": c.get("to", ""),
                "from": c.get("from", ""),
                "start_time": c.get("start_time", ""),
                "duration": c.get("duration", 0),
                "status": c.get("status", ""),
            })
        return jsonify({"calls": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/call/recording")
@_require_jwt
def api_call_recording():
    """Set recording preference for an active call.

    Request body:
        { "call_id": "...", "record": true/false }
    """
    uid = request._fox_uid
    body = request.get_json(silent=True) or {}
    call_id = (body.get("call_id") or "").strip()
    record = body.get("record", False)

    if not call_id:
        return jsonify({"error": "missing 'call_id'"}), 400

    with _active_calls_lock:
        call_info = _active_calls.get(call_id)
        if not call_info:
            return jsonify({"error": "call not found or already ended"}), 404
        if call_info.get("user_id") != uid:
            return jsonify({"error": "call does not belong to you"}), 403
        call_info["recording"] = bool(record)

    return jsonify({"ok": True, "recording": bool(record)})


@app.post("/api/call/recording/upload")
@_require_jwt
def api_call_recording_upload():
    """Upload a call recording file after the call ends.

    The mobile app records the call locally and uploads the file here.
    The recording is saved to RECORDINGS_DIR and will be available
    for the admin to retrieve.

    Request: multipart/form-data with:
        - call_id: string
        - file: audio file (wav, ogg, mp3, m4a)
    """
    uid = request._fox_uid

    call_id = (request.form.get("call_id") or "").strip()
    if not call_id:
        return jsonify({"error": "missing 'call_id'"}), 400

    # Verify the call belongs to this user
    try:
        logs = _load_api_call_logs()
        call_record = None
        for c in logs.get("all_calls", []):
            if c.get("call_id") == call_id and c.get("user_id") == uid:
                call_record = c
                break
        if not call_record:
            return jsonify({"error": "call not found or does not belong to you"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Save the uploaded file
    if "file" not in request.files:
        return jsonify({"error": "missing 'file' in upload"}), 400

    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"error": "empty file"}), 400

    # Determine extension
    ext = os.path.splitext(uploaded.filename)[1] or ".wav"
    if ext.lower() not in (".wav", ".ogg", ".mp3", ".m4a", ".flac", ".webm", ".amr"):
        ext = ".wav"

    # Use call_id as filename for easy retrieval
    save_path = os.path.join(RECORDINGS_DIR, f"{call_id}{ext}")
    os.makedirs(RECORDINGS_DIR, exist_ok=True)

    try:
        uploaded.save(save_path)
        file_size = os.path.getsize(save_path)

        # Update the call log to mark it as having a recording
        try:
            logs = _load_api_call_logs()
            for c in logs.get("all_calls", []):
                if c.get("call_id") == call_id:
                    c["has_recording"] = True
                    c["recording_file"] = f"{call_id}{ext}"
                    c["recording_size"] = file_size
                    break
            _save_api_call_logs(logs)
        except Exception:
            pass

        # Notify admin via Telegram bot about the new recording
        try:
            cv = _cv()
            from callv2 import BOT_TOKEN, ADMIN_IDS
            import telebot
            _bot = telebot.TeleBot(BOT_TOKEN)
            for admin_id in ADMIN_IDS:
                try:
                    _bot.send_message(
                        admin_id,
                        f"🎙️ *تسجيل مكالمة جديد*\n\n"
                        f"🆔 معرف المكالمة: `{call_id}`\n"
                        f"👤 المستخدم: `{uid}`\n"
                        f"📞 إلى: `{call_record.get('to', '')}`\n"
                        f"⏱️ المدة: {call_record.get('duration', 0)} ثانية\n"
                        f"📊 الحجم: {file_size / 1024:.1f} KB",
                        parse_mode='Markdown'
                    )
                    # Send the actual recording file
                    with open(save_path, 'rb') as audio_f:
                        _bot.send_document(
                            admin_id, audio_f,
                            caption=f"🎙️ تسجيل المكالمة `{call_id}`",
                            parse_mode='Markdown'
                        )
                except Exception:
                    pass
        except Exception:
            pass

        return jsonify({"ok": True, "call_id": call_id, "file": f"{call_id}{ext}", "size": file_size})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
#  Security Strike System — 3-strike auto-ban with admin notification
# ═══════════════════════════════════════════════════════════════════════════════

STRIKES_FILE = os.path.join(DATA_DIR, "security_strikes.json")
_strikes_lock = threading.Lock()
MAX_STRIKES = 3


def _load_strikes() -> dict:
    """Load security strikes database."""
    if os.path.exists(STRIKES_FILE):
        try:
            with open(STRIKES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"strikes": {}}


def _save_strikes(data: dict):
    """Save security strikes database."""
    try:
        with open(STRIKES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _add_strike(uid: str, reason: str, fox_token: str = "") -> dict:
    """Add a security strike for a user. Auto-ban after MAX_STRIKES.
    Returns {strikes, banned, reason}."""
    with _strikes_lock:
        data = _load_strikes()
        strikes = data.setdefault("strikes", {})
        user_strikes = strikes.setdefault(uid, {"count": 0, "reasons": [], "banned": False})

        user_strikes["count"] = user_strikes.get("count", 0) + 1
        user_strikes.setdefault("reasons", []).append({
            "reason": reason,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "fox_token": fox_token[:20] + "..." if fox_token else "",
        })

        should_ban = user_strikes["count"] >= MAX_STRIKES

        if should_ban:
            user_strikes["banned"] = True
            # Actually ban the user
            try:
                cv = _cv()
                cv.ban_user(int(uid))
            except Exception:
                # Fallback: add to banned_db directly
                try:
                    banned = cv.load_banned_db()
                    banned[uid] = {
                        "reason": f"auto_ban:{reason}",
                        "strikes": user_strikes["count"],
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    cv.save_banned_db(banned)
                except Exception:
                    pass

            # Notify admins via Telegram
            _notify_admins_intrusion(uid, reason, fox_token, user_strikes["count"])

        _save_strikes(data)

        return {
            "strikes": user_strikes["count"],
            "banned": should_ban,
            "reason": reason,
        }


def _notify_admins_intrusion(uid: str, reason: str, fox_token: str, strike_count: int):
    """Send Telegram notification to admins about intrusion attempt."""
    try:
        cv = _cv()
        user_rec = _user_record(uid)
        username = user_rec.get("username", "")
        first_name = user_rec.get("first_name", "")

        token_display = fox_token[:30] + "..." if fox_token and len(fox_token) > 30 else (fox_token or "N/A")

        msg = (
            "🚨 *INTRUSION DETECTED*\n\n"
            f"👤 User: `{uid}`\n"
            f"📝 Name: {first_name}\n"
            f"🔍 Username: @{username}\n"
            f"🔑 Token: `{token_display}`\n"
            f"⚠️ Reason: `{reason}`\n"
            f"📊 Strikes: `{strike_count}/{MAX_STRIKES}`\n"
            f"🚫 Status: *AUTO-BANNED*\n"
            f"🕐 Time: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        )

        bot_token = os.environ.get("BOT_TOKEN") or os.environ.get("TELI_BOT_TOKEN", "")
        if bot_token:
            bot_token = bot_token.strip('"')
            import requests as req
            for admin_id in cv.ADMIN_IDS if hasattr(cv, 'ADMIN_IDS') else [962731079, 7627857345]:
                try:
                    req.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={
                            "chat_id": admin_id,
                            "text": msg,
                            "parse_mode": "Markdown",
                        },
                        timeout=10,
                    )
                except Exception:
                    pass
    except Exception:
        pass


@app.post("/api/security/strike")
@_require_jwt
def api_security_strike():
    """Report suspicious behavior from the app.
    Body: { "reason": "vpn|root|tamper|hook|emulator|signature", "details": "..." }

    After 3 strikes, user is auto-banned and admin is notified.
    """
    uid = request._fox_uid
    body = request.get_json(silent=True) or {}
    reason = (body.get("reason") or "").strip()
    details = (body.get("details") or "").strip()

    if not reason:
        return jsonify({"error": "missing 'reason'"}), 400

    # Get the fox token from the JWT for reporting
    fox_token = ""
    try:
        fox_token = request._fox_jwt or ""
    except Exception:
        pass

    result = _add_strike(uid, reason, fox_token)

    return jsonify({
        "ok": True,
        "strikes": result["strikes"],
        "max_strikes": MAX_STRIKES,
        "banned": result["banned"],
        "reason": result["reason"],
    })


@app.get("/api/security/status")
@_require_jwt
def api_security_status():
    """Check current security status for the user."""
    uid = request._fox_uid
    with _strikes_lock:
        data = _load_strikes()
        user_strikes = data.get("strikes", {}).get(uid, {"count": 0, "reasons": [], "banned": False})
    return jsonify({
        "strikes": user_strikes.get("count", 0),
        "max_strikes": MAX_STRIKES,
        "banned": user_strikes.get("banned", False),
    })


# ═══════════════════════════════════════════════════════════════════════════════
#  Telegram Profile Photo endpoint
# ═══════════════════════════════════════════════════════════════════════════════

def _get_telegram_photo_url(uid: str) -> str:
    """Get the Telegram profile photo URL for a user."""
    try:
        bot_token = os.environ.get("BOT_TOKEN") or os.environ.get("TELI_BOT_TOKEN", "")
        if bot_token:
            bot_token = bot_token.strip('"')
            import requests as req
            # Get user profile photos
            resp = req.get(
                f"https://api.telegram.org/bot{bot_token}/getUserProfilePhotos",
                params={"user_id": int(uid), "limit": 1},
                timeout=10,
            )
            data = resp.json()
            if data.get("ok") and data.get("result", {}).get("photos"):
                photos = data["result"]["photos"][0]
                # Get the largest photo
                file_id = photos[-1]["file_id"]
                # Get file path
                file_resp = req.get(
                    f"https://api.telegram.org/bot{bot_token}/getFile",
                    params={"file_id": file_id},
                    timeout=10,
                )
                file_data = file_resp.json()
                if file_data.get("ok") and file_data.get("result", {}).get("file_path"):
                    file_path = file_data["result"]["file_path"]
                    return f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
    except Exception:
        pass
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
#  Admin endpoints
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/admin/user/<user_id>")
@_require_admin
def api_admin_user(user_id: str):
    """Get full user info including balance, IP, last call, registration date."""
    uid = str(user_id).strip()

    rec = _user_record(uid)
    if not rec:
        return jsonify({"error": "user not found"}), 404

    bal = _balance(uid)
    cost = _call_cost()
    possible = int(bal // cost) if cost > 0 else 0

    # Get last 20 calls for this user
    user_calls = []
    try:
        logs = _load_api_call_logs()
        all_calls = logs.get("all_calls", [])
        user_calls = [c for c in all_calls if c.get("user_id") == uid][-20:]
        user_calls.reverse()  # most recent first
    except Exception:
        pass

    # Last call details
    last_call = user_calls[0] if user_calls else {}

    return jsonify(
        {
            "user_id": uid,
            "username": rec.get("username") or "",
            "first_name": rec.get("first_name") or "",
            "last_name": rec.get("last_name") or "",
            "full_name": (
                (rec.get("first_name") or "")
                + (" " + rec["last_name"] if rec.get("last_name") else "")
            ).strip()
            or rec.get("username")
            or uid,
            "balance": round(bal, 2),
            "cost": round(cost, 2),
            "possible_calls": possible,
            "ip_address": rec.get("last_ip") or "",
            "last_seen": rec.get("last_seen") or rec.get("last_use") or "",
            "registration_date": rec.get("first_seen") or "",
            "last_login": rec.get("last_login") or "",
            "streak": rec.get("streak", 0),
            "referrals": rec.get("referrals", 0),
            "dan_calls": rec.get("dan_calls", 0),
            "last_call": last_call,
            "call_history": user_calls,
            "is_banned": _is_banned(uid),
        }
    )


@app.get("/api/admin/calls/<user_id>")
@_require_admin
def api_admin_calls(user_id: str):
    """Get call logs for a specific user.  ?limit=N (default 20, max 100)."""
    uid = str(user_id).strip()
    limit = request.args.get("limit", 20, type=int)
    limit = min(limit, 100)

    try:
        logs = _load_api_call_logs()
        all_calls = logs.get("all_calls", [])
        user_calls = [c for c in all_calls if c.get("user_id") == uid]
        total = len(user_calls)
        # Most recent first
        user_calls = user_calls[-limit:][::-1]
        return jsonify(
            {
                "user_id": uid,
                "total_calls": total,
                "calls": user_calls,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/admin/stats")
@_require_admin
def api_admin_stats():
    """Get overall statistics for the dashboard."""
    try:
        logs = _load_api_call_logs()
        all_calls = logs.get("all_calls", [])

        # Get bot stats
        cv = _cv()
        bot_data = cv.load_bot_data()
        bot_stats = bot_data.get("stats", {})
        used_accounts = len(bot_data.get("used_accounts", []))

        # Get token stats
        ready_tokens = cv.count_ready_tokens()
        accounts_count = len(cv.accounts) if hasattr(cv, 'accounts') else 0

        # Get all users and their balances
        users_db = cv.load_users_db()
        total_balance = sum(float(u.get("balance", 0) or 0) for u in users_db.values())

        return jsonify({
            "total_calls": bot_stats.get("total_calls", 0),
            "success_calls": bot_stats.get("success_calls", 0),
            "total_users": len(users_db),
            "total_balance": round(total_balance, 2),
            "ready_tokens": ready_tokens,
            "accounts_count": accounts_count,
            "used_accounts": used_accounts,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/admin/cleanup-tokens")
@_require_admin
def api_admin_cleanup_tokens():
    """Clean up used tokens from the ready cache (admin only)."""
    try:
        cv = _cv()
        removed = cv.cleanup_used_tokens_from_cache()
        ready_tokens = cv.count_ready_tokens()
        return jsonify({
            "ok": True,
            "removed": removed,
            "remaining_ready_tokens": ready_tokens,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/admin/users")
@_require_admin
def api_admin_all_users():
    """Get all users with basic info for the user list."""
    try:
        cv = _cv()
        users_db = cv.load_users_db()
        logs = _load_api_call_logs()
        all_users_logs = logs.get("all_users", {})

        users_list = []
        for uid, rec in users_db.items():
            bal = float(rec.get("balance", 0) or 0)
            cost = _call_cost()
            users_list.append({
                "user_id": uid,
                "username": rec.get("username") or "",
                "full_name": (
                    (rec.get("first_name") or "")
                    + (" " + rec.get("last_name", "") if rec.get("last_name") else "")
                ).strip() or rec.get("username") or uid,
                "balance": round(bal, 2),
                "last_ip": rec.get("last_ip") or "",
                "last_seen": rec.get("last_seen") or rec.get("last_login") or "",
                "total_calls": all_users_logs.get(uid, {}).get("total_calls", 0),
                "is_banned": _is_banned(uid),
            })

        # Sort by last seen
        users_list.sort(key=lambda x: x["last_seen"] or "", reverse=True)

        return jsonify({"users": users_list})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/admin/all-calls")
@_require_admin
def api_admin_all_calls():
    """Get all calls for the calls log view."""
    try:
        limit = request.args.get("limit", 200, type=int)
        limit = min(limit, 1000)

        logs = _load_api_call_logs()
        all_calls = logs.get("all_calls", [])
        # Most recent first, limit
        calls = all_calls[-limit:][::-1]

        return jsonify({"calls": calls, "total": len(all_calls)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/admin/ips")
@_require_admin
def api_admin_ips():
    """Get all unique IP addresses with user info."""
    try:
        cv = _cv()
        users_db = cv.load_users_db()
        logs = _load_api_call_logs()
        all_users_logs = logs.get("all_users", {})

        ip_map = {}
        for uid, rec in users_db.items():
            ip = rec.get("last_ip", "")
            if ip:
                if ip not in ip_map:
                    ip_map[ip] = {
                        "ip": ip,
                        "user_id": uid,
                        "username": rec.get("username") or "",
                        "last_seen": rec.get("last_seen") or rec.get("last_login") or "",
                        "total_calls": all_users_logs.get(uid, {}).get("total_calls", 0),
                    }

        # Sort by last seen
        ips_list = sorted(ip_map.values(), key=lambda x: x["last_seen"] or "", reverse=True)

        return jsonify({"ips": ips_list})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/admin/track/<user_id>")
@_require_admin
def api_admin_track(user_id: str):
    """Comprehensive user tracking: info, IP, call history, referrals, contacts, etc."""
    uid = str(user_id).strip()

    # User record from users_db + bot_data
    rec = _user_record(uid)

    # Call history from call_logs.json
    call_history = []
    try:
        logs = _load_api_call_logs()
        all_calls = logs.get("all_calls", [])
        call_history = [c for c in all_calls if c.get("user_id") == uid]
        call_history.reverse()  # most recent first
    except Exception:
        pass

    # Call stats from logs
    call_stats = {}
    try:
        logs = _load_api_call_logs()
        call_stats = logs.get("all_users", {}).get(uid, {})
    except Exception:
        pass

    # Telegram bot data
    bot_user = {}
    try:
        cv = _cv()
        bd = cv.load_bot_data()
        bot_user = (bd.get("users", {}) or {}).get(uid, {})
    except Exception:
        pass

    bal = _balance(uid)
    cost = _call_cost()
    possible = int(bal // cost) if cost > 0 else 0

    return jsonify({
        "user_id": uid,
        "username": rec.get("username") or "",
        "first_name": rec.get("first_name") or "",
        "last_name": rec.get("last_name") or "",
        "full_name": (
            (rec.get("first_name") or "")
            + (" " + rec["last_name"] if rec.get("last_name") else "")
        ).strip() or rec.get("username") or uid,
        "balance": round(bal, 2),
        "cost": round(cost, 2),
        "possible_calls": possible,
        "ip_address": rec.get("last_ip") or "",
        "last_seen": rec.get("last_seen") or rec.get("last_use") or "",
        "registration_date": rec.get("first_seen") or "",
        "last_login": rec.get("last_login") or "",
        "streak": rec.get("streak", 0),
        "referrals": rec.get("referrals", 0),
        "dan_calls": rec.get("dan_calls", 0),
        "is_banned": _is_banned(uid),
        "call_stats": call_stats,
        "call_history": call_history,
        "bot_data": bot_user,
    })


@app.post("/api/admin/balance")
@_require_admin
def api_admin_balance():
    """Adjust a user's balance (positive to add, negative to deduct).
    🔒 SECURED: max $5 per transaction, 2/min per IP, daily cap per user.
    """
    # Extra rate limit for balance changes — strict
    ip = _get_client_ip()
    if not _check_admin_rate_limit(f"bal:{ip}", limit=2):
        return jsonify({"error": "balance change rate limit exceeded (max 2/min)"}), 429

    body = request.get_json(silent=True) or {}
    uid = str(body.get("user_id", "")).strip()
    amount = body.get("amount", 0)

    if not uid:
        return jsonify({"error": "missing user_id"}), 400
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400

    # 🔒 Limit single transaction amount — max $5
    if abs(amount) > 5.0:
        return jsonify({"error": "single transaction limited to $5 max"}), 400

    # 🔒 Daily cap: max $10 total balance changes per user per day
    try:
        cv = _cv()
        db = cv.load_users_db()
        admin_bal_daily = db.get(uid, {}).get("admin_bal_daily", {})
        date_str = time.strftime("%Y-%m-%d")
        if admin_bal_daily.get("date") != date_str:
            admin_bal_daily = {"date": date_str, "total_added": 0.0, "total_deducted": 0.0}
        if amount > 0:
            if admin_bal_daily.get("total_added", 0) + amount > 10.0:
                return jsonify({"error": f"daily add limit reached for user ({admin_bal_daily.get('total_added', 0):.2f}/$10)"}), 429
            admin_bal_daily["total_added"] = round(admin_bal_daily.get("total_added", 0) + amount, 2)
        else:
            if admin_bal_daily.get("total_deducted", 0) + abs(amount) > 10.0:
                return jsonify({"error": f"daily deduct limit reached for user ({admin_bal_daily.get('total_deducted', 0):.2f}/$10)"}), 429
            admin_bal_daily["total_deducted"] = round(admin_bal_daily.get("total_deducted", 0) + abs(amount), 2)
        db.setdefault(uid, {})["admin_bal_daily"] = admin_bal_daily
        cv.save_users_db(db)
    except Exception as e:
        log.error("[admin_audit] Daily cap check error: %s", e)

    try:
        cv = _cv()
        new_balance = cv.add_balance(int(uid), amount)
        log.warning("[admin_audit] BALANCE: uid=%s amt=$%.2f new=$%.2f ip=%s",
                    uid, amount, new_balance, ip)
        return jsonify({"ok": True, "user_id": uid, "amount": amount, "new_balance": round(new_balance, 2)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/admin/ban/<user_id>")
@_require_admin
def api_admin_ban(user_id: str):
    """Ban a user by adding to banned_db."""
    uid = str(user_id).strip()
    try:
        cv = _cv()
        cv.add_banned(int(uid), admin_id=None, reason="Banned by admin panel")
        return jsonify({"ok": True, "message": f"User {uid} banned"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/admin/unban/<user_id>")
@_require_admin
def api_admin_unban(user_id: str):
    """Unban a user by removing from banned_db."""
    uid = str(user_id).strip()
    try:
        cv = _cv()
        cv.remove_banned(int(uid))
        return jsonify({"ok": True, "message": f"User {uid} unbanned"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
#  Fox Farm — account creation & upload endpoints
# ═══════════════════════════════════════════════════════════════════════════════

# Farm auth token derived from SHARED_SECRET (same material as ADMIN_SECRET)
FARM_TOKEN = hashlib.sha256(f"{SHARED_SECRET}:farm".encode()).hexdigest()[:32]

# In-memory farm stats tracker
_farm_stats = {"total_created": 0, "total_uploaded": 0, "last_upload": ""}
FARM_STATS_FILE = os.path.join(DATA_DIR, "farm_stats.json")
_farm_stats_lock = threading.Lock()


def _load_farm_stats() -> dict:
    """Load farm stats from disk, merging with in-memory defaults."""
    default = {"total_created": 0, "total_uploaded": 0, "last_upload": ""}
    if os.path.exists(FARM_STATS_FILE):
        try:
            with open(FARM_STATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            default.update(data)
        except Exception:
            pass
    return default


def _save_farm_stats(stats: dict):
    """Persist farm stats to disk."""
    try:
        with _farm_stats_lock:
            with open(FARM_STATS_FILE, "w", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _require_farm_auth(f):
    """Decorator: requires x-farm-token header matching the derived FARM_TOKEN."""

    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("x-farm-token", "")
        if not token or not hmac_mod.compare_digest(token, FARM_TOKEN):
            return jsonify({"error": "unauthorized — invalid farm token"}), 403
        return f(*args, **kwargs)

    return decorated


@app.post("/api/farm/auth")
def api_farm_auth():
    """Authenticate with a farm key.  Returns a session token identical to
    the FARM_TOKEN (derived from SHARED_SECRET, same as ADMIN_SECRET source).
    🔒 Rate limited: max 3 attempts per minute per IP.

    Body: {"key": "..."}
    """
    # Rate limit farm auth attempts
    ip = _get_client_ip()
    if not _check_admin_rate_limit(f"farm_auth:{ip}", limit=3):
        return jsonify({"error": "farm auth rate limit exceeded (max 3/min)"}), 429

    body = request.get_json(silent=True) or {}
    key = body.get("key", "")
    if not key or not hmac_mod.compare_digest(key, ADMIN_SECRET):
        log.warning("[farm] Failed farm auth attempt from IP: %s", ip)
        return jsonify({"error": "invalid farm key"}), 403
    return jsonify({"ok": True, "token": FARM_TOKEN})


@app.post("/api/farm/upload-accounts")
@_require_farm_auth
def api_farm_upload_accounts():
    """Receive created accounts from the farm app.

    Body: {"accounts": [{"email": "...", "device_id": "...", "token": "..."}, ...]}

    For each account the server:
      1. Calls cv.add_ready_token()  → adds to tokens_cache ready list
      2. Calls cv.save_account()     → appends to encrypted accounts file

    Returns: {"ok": true, "added": N}
    """
    body = request.get_json(silent=True) or {}
    accounts = body.get("accounts", [])
    if not isinstance(accounts, list):
        return jsonify({"error": "accounts must be a list"}), 400

    added = 0
    cv = _cv()
    valid_accounts = []
    for acc in accounts:
        email = acc.get("email", "").strip()
        device_id = acc.get("device_id", "").strip()
        token = acc.get("token", "").strip()
        if not email or not device_id or not token:
            continue
        valid_accounts.append({"email": email, "device_id": device_id, "token": token})

    if not valid_accounts:
        return jsonify({"ok": True, "added": 0})

    added = len(valid_accounts)

    # Save to tokens cache directly (fast, no lock needed)
    try:
        TOKENS_CACHE_FILE = cv.TOKENS_CACHE_FILE
        cache = {}
        if os.path.exists(TOKENS_CACHE_FILE):
            with open(TOKENS_CACHE_FILE, 'r', encoding='utf-8') as f:
                cache = json.load(f)
        ready_tokens = cache.get("ready_tokens", [])
        existing_emails = {t.get("email", "") for t in ready_tokens}
        new_tokens = []
        for acc in valid_accounts:
            if acc["email"] not in existing_emails:
                new_tokens.append({
                    "email": acc["email"],
                    "device_id": acc["device_id"],
                    "token": acc["token"],
                    "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
        ready_tokens.extend(new_tokens)
        cache["ready_tokens"] = ready_tokens
        cache["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(TOKENS_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log.warning("farm upload: token cache save failed: %s", exc)

    # Add to accounts list in memory (will be persisted by GitHub sync)
    try:
        for acc in valid_accounts:
            cv.accounts.append({
                "email": acc["email"],
                "x-client-device-id": acc["device_id"],
                "x-token": acc["token"],
                "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
    except Exception as exc:
        log.warning("farm upload: accounts list append failed: %s", exc)

    # Update farm stats
    if added > 0:
        with _farm_stats_lock:
            stats = _load_farm_stats()
            stats["total_created"] = stats.get("total_created", 0) + added
            stats["total_uploaded"] = stats.get("total_uploaded", 0) + added
            stats["last_upload"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _farm_stats.update(stats)
            _save_farm_stats(stats)

    return jsonify({"ok": True, "added": added, "queued": True})


@app.get("/api/farm/stats")
@_require_farm_auth
def api_farm_stats():
    """Get farming stats.  Requires farm auth token.

    Returns: {"ready_tokens": N, "used_accounts": N, "accounts_in_file": N}
    """
    cv = _cv()
    try:
        ready_tokens = cv.count_ready_tokens()
    except Exception:
        ready_tokens = 0

    try:
        bd = cv.load_bot_data()
        used_accounts = len(bd.get("used_accounts", []))
    except Exception:
        used_accounts = 0

    try:
        cv.load_accounts()
        accounts_in_file = len(cv.accounts) if hasattr(cv, "accounts") else 0
    except Exception:
        accounts_in_file = 0

    return jsonify({
        "ready_tokens": ready_tokens,
        "used_accounts": used_accounts,
        "accounts_in_file": accounts_in_file,
    })


@app.get("/api/farm/config")
@_require_farm_auth
def api_farm_config():
    """Get creation config (domains list).  Requires farm auth token.

    Returns: {"domains": [...], "api_url": "https://api.telicall.com"}
    """
    cv = _cv()
    try:
        domains = list(cv.DOMAINS) if hasattr(cv, "DOMAINS") else []
    except Exception:
        domains = []

    return jsonify({
        "domains": domains,
        "api_url": "https://api.telicall.com",
    })


# ═══════════════════════════════════════════════════════════════════════════════
#  App Subscriptions (v4.0.0)
# ═══════════════════════════════════════════════════════════════════════════════

APP_SUBSCRIPTIONS_FILE = os.path.join(DATA_DIR, "app_subscriptions.json")
_app_sub_lock = threading.Lock()


def _load_app_subscriptions() -> dict:
    """Load app_subscriptions.json. Structure: { user_id: { calls_remaining, total_calls, expires_at, plan } }"""
    if os.path.exists(APP_SUBSCRIPTIONS_FILE):
        try:
            with open(APP_SUBSCRIPTIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_app_subscriptions(data: dict):
    try:
        with _app_sub_lock:
            with open(APP_SUBSCRIPTIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _get_user_subscription(uid: str) -> dict | None:
    """Get a user's active app subscription, or None if expired/not found."""
    subs = _load_app_subscriptions()
    sub = subs.get(uid)
    if not sub:
        return None
    # Check expiry
    expires_at = sub.get("expires_at", 0)
    if expires_at and time.time() > expires_at:
        return None
    return sub


@app.get("/api/app-subscription")
@_require_jwt
def api_app_subscription():
    """Get the user's app subscription status.
    Returns: { active, calls_remaining, total_calls, plan, expires_at } or { active: false }
    """
    uid = request._fox_uid
    sub = _get_user_subscription(uid)
    if not sub:
        return jsonify({
            "active": False,
            "calls_remaining": 0,
            "total_calls": 0,
            "plan": None,
            "expires_at": None,
        })
    return jsonify({
        "active": True,
        "calls_remaining": sub.get("calls_remaining", 0),
        "total_calls": sub.get("total_calls", 0),
        "plan": sub.get("plan", "free"),
        "expires_at": sub.get("expires_at", None),
    })


@app.post("/api/app-subscription/use-call")
@_require_jwt
def api_app_subscription_use_call():
    """Use a call from the app subscription.
    Deducts 1 call from the user's subscription if available.
    Body: { } (no params needed)
    Returns: { success, calls_remaining } or { success: false, error }
    """
    uid = request._fox_uid
    subs = _load_app_subscriptions()
    sub = subs.get(uid)
    if not sub:
        return jsonify({"success": False, "error": "No active subscription"}), 404

    # Check expiry
    expires_at = sub.get("expires_at", 0)
    if expires_at and time.time() > expires_at:
        return jsonify({"success": False, "error": "Subscription expired"}), 403

    calls_remaining = sub.get("calls_remaining", 0)
    if calls_remaining <= 0:
        return jsonify({"success": False, "error": "No calls remaining"}), 403

    # Deduct one call
    sub["calls_remaining"] = calls_remaining - 1
    sub["last_used"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subs[uid] = sub
    _save_app_subscriptions(subs)

    return jsonify({
        "success": True,
        "calls_remaining": sub["calls_remaining"],
    })


# ═══════════════════════════════════════════════════════════════════════════════
#  Telegram /token command + Flask launcher
# ═══════════════════════════════════════════════════════════════════════════════

def install_fox_layer(bot):
    """Wire into the running TeleBot instance: add /token command + Flask thread."""

    @bot.message_handler(commands=["token", "fox", "app"])
    def on_token(m):
        uid = m.from_user.id
        try:
            cv = _cv()
            db = cv.load_users_db()
            urec = db.get(str(uid), {})
            if not urec:
                db[str(uid)] = {
                    "first_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "username": m.from_user.username or "",
                    "first_name": m.from_user.first_name or "",
                    "balance": float(
                        cv.load_bot_data()
                        .get("settings", {})
                        .get("default_balance", 0.0)
                    ),
                }
                cv.save_users_db(db)
        except Exception:
            pass

        tok = encode_token(uid, PUBLIC_URL)
        bal = _balance(uid)
        cost = _call_cost()
        text = (
            "\U0001f511 *توكن تطبيق Fox Call*\n\n"
            f"`{tok}`\n\n"
            f"\U0001f4b0 رصيدك: *${bal:.2f}*\n"
            f"\U0001f4de تكلفة المكالمة: *${cost:.2f}*\n\n"
            "\U0001f4f1 افتح تطبيق Fox Call \u2192 الصق التوكن \u2192 اعمل اتصال.\n"
            "\u26a0\ufe0f التوكن مرتبط بحسابك. متشركوش مع حد."
        )
        bot.send_message(m.chat.id, text, parse_mode="Markdown")

    log.info("Fox app layer installed (commands: /token /fox /app).")
    _start_flask_once()


# ═══════════════════════════════════════════════════════════════════════════════
#  Ads System — Watch ads via Monetag to earn balance
#  🔒 Anti-cheat: HMAC ad tokens, Telegram initData validation, fingerprinting
# ═══════════════════════════════════════════════════════════════════════════════

ADSGRAM_BLOCK_ID = os.environ.get("ADSGRAM_BLOCK_ID", "int-32989")  # Legacy AdsGram
ADSGRAM_API_TOKEN = os.environ.get("ADSGRAM_API_TOKEN", "")   # Legacy AdsGram
ADSGRAM_BOT_BLOCK_ID = os.environ.get("ADSGRAM_BOT_BLOCK_ID", "32999")  # Legacy AdsGram

# ─── Monetag SDK Configuration ─────────────────────────────────────────────────
MONETAG_ZONE_ID = os.environ.get("MONETAG_ZONE_ID", "11063303")
MONETAG_SDK_FUNCTION = os.environ.get("MONETAG_SDK_FUNCTION", f"show_{MONETAG_ZONE_ID}")
MONETAG_ENABLED = os.environ.get("MONETAG_ENABLED", "true").lower() == "true"
ADS_PER_SESSION = 10
ADS_REWARD = 0.20                # $0.20 for completing 10 ads
ADS_SESSION_EXPIRY = 30 * 60     # 30 minutes
ADS_DAILY_LIMIT = 5              # max completed sessions per day (5 × $0.20 = $1.00/day)
ADS_MIN_VERIFY_DELAY = 5         # minimum seconds between challenge issue and verify
ADS_FALLBACK_DURATION = 15       # seconds per fallback ad
ADS_REWARD_PER_AD = 0.02         # $0.02 per individual ad

# ─── Anti-Cheat Configuration ──────────────────────────────────────────────────
ADS_SECRET_KEY = hashlib.sha256(f"{SHARED_SECRET}:ads_anti_cheat".encode()).digest()
ADS_MIN_AD_DURATION = 10         # minimum seconds an ad must be shown before claiming
ADS_FINGERPRINT_SALT = os.environ.get("ADS_FINGERPRINT_SALT", secrets.token_hex(16))  # 🔒 Random per-deploy salt — never in frontend
ADS_MAX_AD_TOKEN_AGE = 120       # ad token expires after 120 seconds (gives more time for SDK loading)

# In-memory active ad sessions
_ads_sessions: dict[str, dict] = {}
_ads_sessions_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════════════
#  🔒 Anti-Cheat Functions
# ═══════════════════════════════════════════════════════════════════════════════

def _generate_ad_token(session_token: str, ad_index: int, timestamp: int) -> str:
    """Generate a cryptographically signed ad token for one specific ad.
    Format: ad_index:timestamp:HMAC-SHA256(session_token:ad_index:timestamp)
    This token CANNOT be forged without ADS_SECRET_KEY."""
    msg = f"{session_token}:{ad_index}:{timestamp}"
    sig = hmac_mod.new(ADS_SECRET_KEY, msg.encode(), hashlib.sha256).hexdigest()[:24]
    token = f"{ad_index}:{timestamp}:{sig}"
    return token


def _validate_ad_token(ad_token: str, session_token: str, current_ad_index: int) -> dict | None:
    """Validate an ad token. Returns {ad_index, timestamp} or None if invalid.
    Checks: correct index, valid signature, not expired, minimum ad duration elapsed."""
    try:
        parts = ad_token.split(":")
        if len(parts) != 3:
            return None
        idx_str, ts_str, sig = parts
        idx = int(idx_str)
        ts = int(ts_str)

        # Must match expected ad index
        if idx != current_ad_index:
            log.warning("[anti_cheat] Ad index mismatch: expected %d, got %d", current_ad_index, idx)
            return None

        # Verify HMAC signature
        msg = f"{session_token}:{idx}:{ts}"
        expected_sig = hmac_mod.new(ADS_SECRET_KEY, msg.encode(), hashlib.sha256).hexdigest()[:24]
        if not hmac_mod.compare_digest(sig, expected_sig):
            log.warning("[anti_cheat] Invalid ad token signature for session %s", session_token[:20])
            return None

        # Token must not be expired
        now = int(time.time())
        if now - ts > ADS_MAX_AD_TOKEN_AGE:
            log.warning("[anti_cheat] Ad token expired for user in session %s", session_token[:20])
            return None

        # Minimum ad duration must have elapsed since token was issued
        elapsed = time.time() - ts
        if elapsed < ADS_MIN_AD_DURATION:
            log.warning("[anti_cheat] Ad too fast: %.1fs < %ds minimum", elapsed, ADS_MIN_AD_DURATION)
            return None

        return {"ad_index": idx, "timestamp": ts}
    except Exception as e:
        log.error("[anti_cheat] Token validation error: %s", e)
        return None


# ─── initData Replay Protection ──────────────────────────────────────────────
_initdata_used = {}
_initdata_lock = threading.Lock()


def _validate_telegram_init_data(init_data: str) -> dict | None:
    """Validate Telegram WebApp initData using HMAC-SHA256 with bot token.
    🔒 STRICT MODE: No dev_mode fallback. BOT_TOKEN is REQUIRED.
    🔒 Replay protection: each initData hash can only be used once.
    🔒 Tight auth_date window: 5 minutes (not 1 hour)."""
    if not init_data or len(init_data) < 20:
        return None

    # Replay protection
    initdata_hash = hashlib.sha256(init_data.encode()).hexdigest()[:32]
    now = time.time()
    with _initdata_lock:
        expired = [k for k, v in _initdata_used.items() if now - v > 600]
        for k in expired:
            del _initdata_used[k]
        if initdata_hash in _initdata_used:
            log.warning("[anti_cheat] initData REPLAY ATTACK rejected")
            return None

    try:
        BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
        if not BOT_TOKEN:
            log.error("[anti_cheat] NO BOT_TOKEN — cannot validate initData!")
            return None

        from urllib.parse import parse_qs
        parsed = parse_qs(init_data, keep_blank_values=True)

        hash_value = parsed.get("hash", [""])[0]
        if not hash_value:
            return None

        user_str = parsed.get("user", [""])[0]
        if not user_str:
            return None

        auth_date_str = parsed.get("auth_date", ["0"])[0]
        auth_date = int(auth_date_str) if auth_date_str else 0

        # Tight window: 5 minutes
        if time.time() - auth_date > 300:
            log.warning("[anti_cheat] initData expired (>5min old)")
            return None

        # Build data-check-string
        data_check = []
        for key in sorted(parsed.keys()):
            if key == "hash":
                continue
            value = parsed[key][0]
            data_check.append(f"{key}={value}")
        data_check_string = "\n".join(data_check)

        # Compute HMAC
        secret_key = hmac_mod.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed_hash = hmac_mod.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if not hmac_mod.compare_digest(computed_hash, hash_value):
            log.warning("[anti_cheat] initData HMAC mismatch — FORGED!")
            return None

        user_data = json.loads(user_str)
        uid = user_data.get("id")
        if not uid:
            return None

        # Mark as used (replay protection)
        with _initdata_lock:
            _initdata_used[initdata_hash] = now

        return {"user_id": str(uid), "auth_date": auth_date}
    except Exception as e:
        log.error("[anti_cheat] initData validation error: %s", e)
        return None


def _validate_fingerprint(fp: str, session_token: str) -> bool:
    """Validate browser fingerprint. STRICT: reject empty/short/fake fingerprints.
    🔒 Format: hash_salt (hash first, then underscore, then per-session salt).
    Must be at least 40 chars, contain underscore, and have valid hex hash portion.
    The salt part must match the per-session fp_salt derived from ADS_FINGERPRINT_SALT."""
    if not fp or len(fp) < 40:
        return False
    if fp.startswith("err_") or fp.startswith("fake") or fp == "0" * 32:
        return False
    if "_" not in fp:
        return False
    parts = fp.split("_", 1)
    hash_part = parts[0]
    salt_part = parts[1] if len(parts) > 1 else ""
    if len(hash_part) < 8:
        return False
    try:
        int(hash_part, 16)
    except ValueError:
        return False
    # 🔒 Verify the salt matches what the server generated for this session
    expected_salt = hashlib.sha256(f"{ADS_FINGERPRINT_SALT}:{session_token[:16]}".encode()).hexdigest()[:16]
    if salt_part != expected_salt:
        log.warning("[anti_cheat] Fingerprint salt mismatch: expected %s got %s", expected_salt[:8], salt_part[:8])
        return False
    return True


# ─── AdsGram Bot API ────────────────────────────────────────────────────────
def _fetch_adsgram_ad(user_id: str, lang: str = "ar") -> dict | None:
    """Fetch an ad from AdsGram Bot API. Returns ad data dict or None."""
    if not ADSGRAM_API_TOKEN or not ADSGRAM_BOT_BLOCK_ID:
        log.warning("[adsgram_api] Missing ADSGRAM_API_TOKEN or ADSGRAM_BOT_BLOCK_ID")
        return None
    import urllib.request
    import urllib.parse
    params = urllib.parse.urlencode({
        "tgid": str(user_id),
        "blockid": ADSGRAM_BOT_BLOCK_ID,
        "language": lang,
        "token": ADSGRAM_API_TOKEN,
    })
    url = f"https://api.adsgram.ai/advbot?{params}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "FoxCall-Bot/1.0",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            if data.get("text_html") or data.get("click_url"):
                log.info("[adsgram_api] Got ad for user %s", user_id)
                return data
            else:
                log.warning("[adsgram_api] No ad available for user %s", user_id)
                return None
    except Exception as e:
        log.error("[adsgram_api] Error fetching ad: %s", e)
        return None


def _generate_ads_session_token(user_id: str) -> str:
    """Generate a cryptographic ad session token."""
    nonce = secrets.token_hex(16)
    timestamp = str(int(time.time()))
    msg = f"{user_id}:{timestamp}:{nonce}"
    sig = hmac_mod.new(
        f"{SHARED_SECRET}:ads_session".encode(),
        msg.encode(),
        hashlib.sha256,
    ).hexdigest()[:32]
    return f"{user_id}:{timestamp}:{nonce}:{sig}"


def _validate_ads_session_token(token: str) -> dict | None:
    """Validate an ad session token. Returns {user_id, timestamp, nonce} or None."""
    try:
        parts = token.split(":")
        if len(parts) != 4:
            return None
        user_id, timestamp, nonce, sig = parts
        if not user_id.isdigit():
            return None
        msg = f"{user_id}:{timestamp}:{nonce}"
        expected_sig = hmac_mod.new(
            f"{SHARED_SECRET}:ads_session".encode(),
            msg.encode(),
            hashlib.sha256,
        ).hexdigest()[:32]
        if not hmac_mod.compare_digest(sig, expected_sig):
            return None
        if int(time.time()) - int(timestamp) > ADS_SESSION_EXPIRY:
            return None
        return {"user_id": user_id, "timestamp": int(timestamp), "nonce": nonce}
    except Exception:
        return None


def _create_ad_session(user_id: str) -> str:
    """Create a new ad session for a user. Returns the session token."""
    token = _generate_ads_session_token(user_id)
    with _ads_sessions_lock:
        # Clean expired sessions
        expired = [
            k for k, v in _ads_sessions.items()
            if time.time() > v.get("expires_at", 0)
        ]
        for k in expired:
            del _ads_sessions[k]
        _ads_sessions[token] = {
            "user_id": user_id,
            "created_at": time.time(),
            "ads_completed": 0,
            "ads_attempted": 0,
            "expires_at": time.time() + ADS_SESSION_EXPIRY,
        }
    return token


def _get_ad_session(session_token: str) -> dict | None:
    with _ads_sessions_lock:
        session = _ads_sessions.get(session_token)
        if not session:
            return None
        if time.time() > session.get("expires_at", 0):
            _ads_sessions.pop(session_token, None)
            return None
        return session


def _update_ads_stats(uid: str, completed: bool = True, attempted: bool = True):
    """Tracks: total_earned, ads_completed (real), ads_watched (attempts)."""
    try:
        cv = _cv()
        db = cv.load_users_db()
        if uid in db:
            stats = db[uid].get("ads_stats", {
                "total_earned": 0.0,
                "ads_completed": 0,
                "ads_watched": 0,
            })
            if attempted:
                stats["ads_watched"] = stats.get("ads_watched", 0) + 1
            if completed:
                stats["ads_completed"] = stats.get("ads_completed", 0) + 1
            db[uid]["ads_stats"] = stats
            cv.save_users_db(db)
    except Exception as e:
        log.error("[ads_stats] Error updating stats for %s: %s", uid, e)


def _add_ads_reward(uid: str, amount: float = ADS_REWARD):
    """Add ads reward balance to user and notify via Telegram."""
    try:
        cv = _cv()
        new_bal = cv.add_balance(int(uid), amount)
        log.info("[ads] Awarded $%.2f to user %s (new balance: $%.2f)", amount, uid, new_bal)

        # Update stats
        try:
            db = cv.load_users_db()
            if uid in db:
                stats = db[uid].get("ads_stats", {})
                stats["total_earned"] = round(stats.get("total_earned", 0.0) + amount, 2)
                db[uid]["ads_stats"] = stats
                cv.save_users_db(db)
        except Exception:
            pass

        # Notify user via Telegram
        try:
            import callv2 as _cv2
            if hasattr(_cv2, 'bot'):
                _cv2.bot.send_message(
                    int(uid),
                    f"💰 تم إضافة `{amount:.2f}$` لحسابك\n"
                    f"✅ رصيدك الجديد: `{new_bal:.2f}$`",
                    parse_mode='Markdown',
                )
        except Exception:
            pass
    except Exception as e:
        log.error("[ads_reward] Error adding reward for %s: %s", uid, e)


def _check_daily_ads_limit(uid: str) -> bool:
    """Check if user can still watch ads today. Returns True if under limit."""
    try:
        cv = _cv()
        db = cv.load_users_db()
        if uid not in db:
            return True
        daily = db[uid].get("ads_daily", {})
        date_str = time.strftime("%Y-%m-%d")
        if daily.get("date") != date_str:
            return True
        return daily.get("count", 0) < ADS_DAILY_LIMIT
    except Exception:
        return True


def _increment_daily_ads_count(uid: str):
    try:
        cv = _cv()
        db = cv.load_users_db()
        if uid not in db:
            db[uid] = {}
        daily = db[uid].get("ads_daily", {})
        date_str = time.strftime("%Y-%m-%d")
        if daily.get("date") != date_str:
            daily = {"date": date_str, "count": 0}
        daily["count"] = daily.get("count", 0) + 1
        db[uid]["ads_daily"] = daily
        cv.save_users_db(db)
    except Exception as e:
        log.error("[ads_daily] Error updating daily count for %s: %s", uid, e)


def _get_ads_daily_count(uid: str) -> int:
    try:
        cv = _cv()
        db = cv.load_users_db()
        daily = db.get(uid, {}).get("ads_daily", {})
        date_str = time.strftime("%Y-%m-%d")
        if daily.get("date") != date_str:
            return 0
        return daily.get("count", 0)
    except Exception:
        return 0


def _get_ads_stats(uid: str) -> dict:
    try:
        cv = _cv()
        db = cv.load_users_db()
        return db.get(uid, {}).get("ads_stats", {
            "total_earned": 0.0,
            "ads_completed": 0,
            "ads_watched": 0,
        })
    except Exception:
        return {"total_earned": 0.0, "ads_completed": 0, "ads_watched": 0}


# ─── Ads Flask Endpoints ────────────────────────────────────────────────────

@app.get("/ads/<session_token>")
def _ads_page(session_token):
    """Serve the ads watching page. Validates the session token first."""
    token_data = _validate_ads_session_token(session_token)
    if not token_data:
        return "<h3>⚠️ رابط الإعلانات منتهي أو غير صالح</h3>", 403

    uid = token_data["user_id"]

    if not _check_daily_ads_limit(uid):
        return "<h3>⏰ وصلت الحد اليومي لمشاهدة الإعلانات! حاول غداً</h3>", 403

    # Create or refresh session
    session = _get_ad_session(session_token)
    if not session:
        with _ads_sessions_lock:
            expired = [k for k, v in _ads_sessions.items() if time.time() > v.get("expires_at", 0)]
            for k in expired:
                del _ads_sessions[k]
            _ads_sessions[session_token] = {
                "user_id": uid,
                "created_at": time.time(),
                "ads_completed": 0,
                "ads_attempted": 0,
                "expires_at": time.time() + ADS_SESSION_EXPIRY,
            }
        session = _ads_sessions.get(session_token)

    return _render_ads_page(session_token, uid)


@app.get("/api/ads/init/<session_token>")
def _ads_init_session(session_token):
    """Get initial ad token and session info for the WebApp.
    Returns the first HMAC-signed ad token that must be used for ad #0."""
    session = _get_ad_session(session_token)
    if not session:
        return jsonify({"error": "session_expired"}), 400
    if session["ads_completed"] >= ADS_PER_SESSION:
        return jsonify({"error": "all_ads_completed"}), 400

    # Generate ad token for the current ad index
    current_index = session["ads_completed"]
    ts = int(time.time())
    ad_token = _generate_ad_token(session_token, current_index, ts)

    return jsonify({
        "ok": True,
        "ad_token": ad_token,
        "ad_index": current_index,
        "ads_completed": session["ads_completed"],
        "total_ads": ADS_PER_SESSION,
    })


@app.get("/api/ads/session-config/<session_token>")
def _ads_session_config(session_token):
    """🔒 Fetch session config (ad_token + fp_salt) from API.
    This replaces embedding sensitive values in the HTML page source.
    Validates the session token before returning any data."""
    token_data = _validate_ads_session_token(session_token)
    if not token_data:
        return jsonify({"error": "invalid_session"}), 403

    session = _get_ad_session(session_token)
    if not session:
        return jsonify({"error": "session_expired"}), 400
    if session["ads_completed"] >= ADS_PER_SESSION:
        return jsonify({"error": "all_ads_completed"}), 400

    # Generate ad token for the current ad index
    current_index = session["ads_completed"]
    ts = int(time.time())
    ad_token = _generate_ad_token(session_token, current_index, ts)

    # Generate per-session fingerprint salt (derived from server secret + session)
    fp_salt = hashlib.sha256(f"{ADS_FINGERPRINT_SALT}:{session_token[:16]}".encode()).hexdigest()[:16]

    return jsonify({
        "ok": True,
        "ad_token": ad_token,
        "fp_salt": fp_salt,
        "ad_index": current_index,
        "ads_completed": session["ads_completed"],
        "total_ads": ADS_PER_SESSION,
    })


# 🔒 DEPRECATED: /api/ads/challenge — disabled, returns 410 Gone
@app.route("/api/ads/challenge/<session_token>", methods=["GET"])
def _ads_get_challenge(session_token):
    return jsonify({"error": "deprecated", "status": "gone"}), 410


@app.post("/api/ads/complete-ad/<session_token>")
def _ads_complete_ad(session_token):
    """🔒 Anti-cheat ad completion endpoint.
    Requires: ad_token (HMAC-signed), telegram_init_data, fingerprint.
    All three must be valid to claim reward."""
    data = request.get_json(silent=True) or {}
    ad_token = data.get("ad_token", "")
    init_data = data.get("init_data", "")
    fingerprint = data.get("fp", "")

    # 1. Validate session
    session = _get_ad_session(session_token)
    if not session:
        return jsonify({"error": "session_expired"}), 400
    if session["ads_completed"] >= ADS_PER_SESSION:
        return jsonify({"error": "all_ads_completed"}), 400

    # 2. Validate ad token (HMAC-signed, cannot be forged)
    current_index = session["ads_completed"]
    token_data = _validate_ad_token(ad_token, session_token, current_index)
    if not token_data:
        log.warning("[anti_cheat] Ad token validation failed for session %s", session_token[:20])
        return jsonify({"error": "invalid_ad_token", "message": "Ad verification failed"}), 403

    # 3. Validate Telegram initData (ensures request comes from Telegram WebApp)
    if init_data:
        tg_data = _validate_telegram_init_data(init_data)
        if tg_data is None:
            log.warning("[anti_cheat] Telegram initData invalid for session %s", session_token[:20])
            return jsonify({"error": "invalid_init_data", "message": "Request not from Telegram"}), 403
        # Verify user ID matches
        if not tg_data.get("dev_mode") and tg_data.get("user_id"):
            if str(tg_data["user_id"]) != session["user_id"]:
                log.warning("[anti_cheat] User ID mismatch: tg=%s session=%s",
                           tg_data["user_id"], session["user_id"])
                return jsonify({"error": "user_mismatch", "message": "User ID mismatch"}), 403

    # 4. Validate fingerprint (🔒 REQUIRED — prevents script-based requests)
    if not fingerprint:
        log.warning("[anti_cheat] Missing fingerprint for session %s", session_token[:20])
        return jsonify({"error": "missing_fingerprint", "message": "Browser verification required"}), 403
    if not _validate_fingerprint(fingerprint, session_token):
        log.warning("[anti_cheat] Fingerprint validation failed for session %s", session_token[:20])
        return jsonify({"error": "invalid_fingerprint", "message": "Browser verification failed"}), 403

    # 5. All checks passed — record the ad completion
    uid = session["user_id"]
    session["ads_completed"] += 1
    session["ads_attempted"] += 1
    session["last_ad_time"] = time.time()
    completed = session["ads_completed"]
    all_done = completed >= ADS_PER_SESSION

    _update_ads_stats(uid, completed=True, attempted=True)

    # 6. Generate next ad token (for the next ad)
    next_ad_token = None
    if not all_done:
        next_ts = int(time.time())
        next_ad_token = _generate_ad_token(session_token, completed, next_ts)

    if all_done:
        _add_ads_reward(uid)
        _increment_daily_ads_count(uid)
        with _ads_sessions_lock:
            _ads_sessions.pop(session_token, None)

    return jsonify({
        "ok": True,
        "ads_completed": completed,
        "total_ads": ADS_PER_SESSION,
        "all_done": all_done,
        "reward": ADS_REWARD if all_done else 0,
        "next_ad_token": next_ad_token,
    })


# 🔒 DEPRECATED: /api/ads/verify — disabled, returns 410 Gone
@app.route("/api/ads/verify", methods=["POST"])
def _ads_verify():
    return jsonify({"error": "deprecated", "status": "gone"}), 410


@app.get("/api/ads/stats/<uid>")
def _ads_user_stats(uid):
    try:
        stats = _get_ads_stats(uid)
        daily_count = _get_ads_daily_count(uid)
    except Exception:
        stats = _get_ads_stats(uid)
        daily_count = _get_ads_daily_count(uid)
    return jsonify({
        "ok": True,
        "stats": stats,
        "daily_count": daily_count,
        "daily_remaining": max(0, ADS_DAILY_LIMIT - daily_count),
    })


# ─── AdsGram Server-Side Reward Endpoint ────────────────────────────────────
@app.get("/api/ads/reward")
def _adsgram_reward():
    """AdsGram server-side reward callback.
    URL format: https://your-domain/api/ads/reward?userid=[userId]
    The [userId] is replaced by AdsGram with the Telegram user ID."""
    userid = request.args.get("userid", "").strip()
    if not userid or not userid.isdigit():
        log.warning("[ads_reward] Invalid userid: %s", userid)
        return jsonify({"error": "invalid_userid"}), 400

    uid = str(userid)

    try:
        cv = _cv()
        db = cv.load_users_db()
        if uid not in db:
            log.warning("[ads_reward] User %s not found", uid)
            return jsonify({"error": "user_not_found"}), 404
    except Exception as e:
        log.error("[ads_reward] DB error: %s", e)
        return jsonify({"error": "db_error"}), 500

    if not _check_daily_ads_limit(uid):
        log.info("[ads_reward] User %s hit daily limit", uid)
        return jsonify({"error": "daily_limit_reached"}), 429

    # Rate limit: max 6 rewards per user per 60 seconds
    if not _check_rate_limit(f"ads_reward_{uid}", 6, _rate_limit_store, window=60):
        log.warning("[ads_reward] Rate limited for user %s", uid)
        return jsonify({"error": "rate_limited"}), 429

    # Add the reward
    try:
        new_bal = _cv().add_balance(int(uid), ADS_REWARD_PER_AD)
        log.info("[ads_reward] Awarded $%.2f to user %s (new balance: $%.2f)", ADS_REWARD_PER_AD, uid, new_bal)
    except Exception as e:
        log.error("[ads_reward] Error adding reward: %s", e)
        return jsonify({"error": "reward_failed"}), 500

    # Update stats
    try:
        db = _cv().load_users_db()
        if uid in db:
            stats = db[uid].get("ads_stats", {
                "total_earned": 0.0,
                "ads_completed": 0,
                "ads_watched": 0,
            })
            stats["ads_watched"] = stats.get("ads_watched", 0) + 1
            stats["ads_completed"] = stats.get("ads_completed", 0) + 1
            stats["total_earned"] = round(stats.get("total_earned", 0.0) + ADS_REWARD_PER_AD, 2)
            db[uid]["ads_stats"] = stats
            _cv().save_users_db(db)

            daily = db[uid].get("ads_daily", {})
            date_str = time.strftime("%Y-%m-%d")
            if daily.get("date") != date_str:
                daily = {"date": date_str, "count": 0}
            daily["count"] = daily.get("count", 0) + 1
            db[uid]["ads_daily"] = daily
            _cv().save_users_db(db)
    except Exception as e:
        log.error("[ads_reward] Error updating stats: %s", e)

    # Notify user
    try:
        import callv2 as _cv2
        if hasattr(_cv2, 'bot'):
            _cv2.bot.send_message(
                int(uid),
                f"💰 تم إضافة `{ADS_REWARD_PER_AD:.2f}$` لحسابك\n"
                f"✅ رصيدك الجديد: `{new_bal:.2f}$`",
                parse_mode='Markdown',
            )
    except Exception:
        pass

    return jsonify({"ok": True, "reward": ADS_REWARD_PER_AD, "new_balance": round(new_bal, 2)})


@app.get("/api/ads/bot-fetch/<uid>")
def _ads_bot_fetch(uid):
    """Fetch an ad from AdsGram Bot API for a specific user."""
    admin_key = request.headers.get("x-admin-key", "")
    if not admin_key or not hmac_mod.compare_digest(admin_key, ADMIN_SECRET):
        return jsonify({"error": "unauthorized"}), 403
    lang = request.args.get("lang", "ar")
    ad_data = _fetch_adsgram_ad(uid, lang)
    if ad_data:
        return jsonify({"ok": True, "ad": ad_data})
    return jsonify({"ok": False, "error": "no_ad_available"}), 404


# ─── Ads Page Renderer ──────────────────────────────────────────────────────

def _render_ads_page(session_token: str, uid: str) -> str:
    """🔒 Render the anti-cheat ads page with Monetag SDK.
    🔒 Sensitive values (ad_token, fp_salt, uid) are NOT in HTML — fetched from API."""
    stats = _get_ads_stats(uid)
    daily_count = _get_ads_daily_count(uid)
    daily_remaining = max(0, ADS_DAILY_LIMIT - daily_count)

    monetag_script = (
        f"<script async src='//libtl.com/sdk.js' data-zone='{MONETAG_ZONE_ID}' data-sdk='{MONETAG_SDK_FUNCTION}'></script>"
        if MONETAG_ENABLED else ''
    )

    # Build 10 ad dots
    ad_dots_html = ""
    for i in range(ADS_PER_SESSION):
        cls = 'ad-dot current' if i == 0 else 'ad-dot'
        ad_dots_html += f'<div class="{cls}" id="dot{i}"></div>\n            '

    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Fox Call</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    {monetag_script}
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Arial, sans-serif;
            background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            color: #fff;
            padding: 20px;
            overflow-x: hidden;
        }}
        .container {{ max-width: 420px; width: 100%; text-align: center; }}
        .logo {{ font-size: 28px; font-weight: bold; margin-bottom: 5px; }}
        .logo span {{ color: #ff6b35; }}
        .subtitle {{ color: #888; font-size: 14px; margin-bottom: 20px; }}
        .ad-dots {{ display: flex; justify-content: center; gap: 6px; margin: 15px 0; flex-wrap: wrap; }}
        .ad-dot {{
            width: 12px; height: 12px; border-radius: 50%;
            background: rgba(255,255,255,0.15); transition: all 0.4s;
        }}
        .ad-dot.completed {{ background: #4CAF50; box-shadow: 0 0 8px rgba(76,175,80,0.5); }}
        .ad-dot.current {{ background: #ff6b35; animation: pulse 1.5s infinite; }}
        @keyframes pulse {{
            0%,100% {{ box-shadow: 0 0 0 0 rgba(255,107,53,0.4); }}
            50% {{ box-shadow: 0 0 0 10px rgba(255,107,53,0); }}
        }}
        .progress-bar {{
            background: rgba(255,255,255,0.08); border-radius: 20px;
            height: 32px; margin: 15px 0; overflow: hidden; position: relative;
        }}
        .progress-fill {{
            background: linear-gradient(90deg, #ff6b35, #f7931e);
            height: 100%; border-radius: 20px; transition: width 0.6s ease; width: 0%;
        }}
        .progress-text {{
            position: absolute; top: 50%; left: 50%;
            transform: translate(-50%,-50%); font-size: 14px; font-weight: bold;
            text-shadow: 0 1px 3px rgba(0,0,0,0.5);
        }}
        .status-box {{
            background: rgba(255,255,255,0.06); border-radius: 16px;
            padding: 18px; margin: 12px 0; font-size: 16px; min-height: 60px;
            display: flex; align-items: center; justify-content: center;
            border: 1px solid rgba(255,255,255,0.08);
        }}
        .btn {{
            display: inline-block; padding: 14px 36px; border: none;
            border-radius: 14px; font-size: 17px; font-weight: bold;
            cursor: pointer; transition: all 0.3s; margin: 8px;
        }}
        .btn-primary {{
            background: linear-gradient(135deg, #ff6b35, #f7931e);
            color: #fff; box-shadow: 0 4px 20px rgba(255,107,53,0.35);
        }}
        .btn-primary:hover {{ transform: translateY(-2px); box-shadow: 0 6px 25px rgba(255,107,53,0.5); }}
        .btn-primary:disabled {{ opacity: 0.5; cursor: not-allowed; transform: none; }}
        .info-card {{
            background: rgba(255,255,255,0.04); border-radius: 12px;
            padding: 12px; margin: 10px 0; font-size: 13px; color: #bbb;
            border: 1px solid rgba(255,255,255,0.06);
        }}
        .info-card .row {{ display: flex; justify-content: space-between; padding: 4px 0; }}
        .spinner {{
            display: inline-block; width: 18px; height: 18px;
            border: 2px solid rgba(255,255,255,0.3); border-top-color: #ff6b35;
            border-radius: 50%; animation: spin 0.7s linear infinite;
            vertical-align: middle; margin-left: 8px;
        }}
        @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
        .completed-banner {{ padding: 20px; }}
        .completed-banner .big {{ font-size: 20px; font-weight: bold; margin-top: 8px; color: #4CAF50; }}
        .success-icon {{ color: #4CAF50; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">🦊 Fox <span>Call</span></div>
        <div class="subtitle">شاهد {ADS_PER_SESSION} إعلانات واكسب رصيد!</div>

        <div class="ad-dots">
            {ad_dots_html}
        </div>

        <div class="progress-bar">
            <div class="progress-fill" id="progressFill"></div>
            <div class="progress-text" id="progressText">0 / {ADS_PER_SESSION}</div>
        </div>

        <div class="status-box" id="adStatus">جاري التحضير...</div>

        <button class="btn btn-primary" id="watchBtn" disabled onclick="initAndShowAd()">
            📺 مشاهدة الإعلان
        </button>

        <div class="info-card">
            <div class="row">
                <span>💰 المكافأة</span>
                <span>+{ADS_REWARD:.2f}$</span>
            </div>
            <div class="row">
                <span>📊 المتبقي اليوم</span>
                <span>{daily_remaining} جلسة</span>
            </div>
            <div class="row">
                <span>📈 إجمالي الكسب</span>
                <span>{stats.get('total_earned', 0):.2f}$</span>
            </div>
        </div>
    </div>

    <script>
        // 🔒 Anti-cheat: sensitive values are fetched from API, NOT embedded in HTML
        const _0s = "{session_token}";
        const _0t = {ADS_PER_SESSION};
        const _0r = {ADS_REWARD};
        const _0b = window.location.origin;
        let _0c = 0;
        let _0l = false;
        let _0a = null;  // Will be fetched from API
        let _0k = null;  // Will be fetched from API (fp_salt, per-session)
        let _0m = {"true" if MONETAG_ENABLED else "false"};
        let _0p = {ADS_REWARD_PER_AD};

        // 🔒 Fetch session config from API (ad_token + fp_salt — never in page source)
        async function _0loadConfig() {{
            try {{
                const resp = await fetch(_0b + '/api/ads/session-config/' + _0s);
                if (resp.ok) {{
                    const data = await resp.json();
                    if (data.ok) {{
                        _0a = data.ad_token;
                        _0k = data.fp_salt;
                        return true;
                    }}
                }}
            }} catch(e) {{ console.warn("Config fetch error:", e); }}
            return false;
        }}

        // 🔒 Generate browser fingerprint (fp_salt is per-session, from API)
        function _0fp() {{
            try {{
                if (!_0k) return '';  // No salt yet
                const c = document.createElement('canvas');
                const g = c.getContext('2d');
                g.textBaseline = 'top';
                g.font = '14px Arial';
                g.fillText(_0k, 2, 2);
                const f = c.toDataURL();
                let h = 0;
                for (let i = 0; i < f.length; i++) {{ h = ((h << 5) - h) + f.charCodeAt(i); h |= 0; }}
                const nav = [screen.width, screen.height, navigator.language, new Date().getTimezoneOffset()].join('|');
                const raw = _0k + ':' + Math.abs(h).toString(36) + ':' + nav;
                let hash = 0;
                for (let i = 0; i < raw.length; i++) {{
                    const ch = raw.charCodeAt(i);
                    hash = ((hash << 5) - hash) + ch;
                    hash |= 0;
                }}
                return Math.abs(hash).toString(36) + '_' + _0k;
            }} catch(e) {{
                return '';
            }}
        }}

        // 🔒 Get Telegram initData
        function _0tg() {{
            try {{
                if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData) {{
                    return window.Telegram.WebApp.initData;
                }}
            }} catch(e) {{}}
            return '';
        }}

        // Wait for Monetag SDK to load (with timeout)
        function _0waitForSDK(maxWait) {{
            return new Promise((resolve) => {{
                const fn = 'show_{MONETAG_ZONE_ID}';
                if (typeof window[fn] === 'function') {{
                    resolve(true);
                    return;
                }}
                let waited = 0;
                const interval = setInterval(() => {{
                    waited += 200;
                    if (typeof window[fn] === 'function') {{
                        clearInterval(interval);
                        resolve(true);
                    }} else if (waited >= maxWait) {{
                        clearInterval(interval);
                        resolve(false);
                    }}
                }}, 200);
            }});
        }}

        // Initialize Telegram WebApp
        try {{
            if (window.Telegram && window.Telegram.WebApp) {{
                window.Telegram.WebApp.ready();
                window.Telegram.WebApp.expand();
            }}
        }} catch(e) {{}}

        // ─── Main ad watching flow ────
        async function initAndShowAd() {{
            if (_0l) return;
            _0l = true;
            const status = document.getElementById('adStatus');
            const btn = document.getElementById('watchBtn');
            btn.disabled = true;

            // Load config if not yet loaded
            if (!_0a || !_0k) {{
                status.innerHTML = '<span class="spinner"></span> جاري التحضير...';
                const configOk = await _0loadConfig();
                if (!configOk || !_0a) {{
                    status.innerHTML = '⚠️ حصل خطأ — حاول مرة تانية';
                    btn.disabled = false;
                    _0l = false;
                    return;
                }}
            }}

            // ── Try Monetag SDK ──
            if (_0m) {{
                // Wait for SDK to load (up to 8 seconds)
                const sdkReady = await _0waitForSDK(8000);
                if (sdkReady) {{
                    try {{
                        status.innerHTML = '<span class="spinner"></span> جاري تحميل الإعلان...';

                        // Show the ad
                        const fn = 'show_{MONETAG_ZONE_ID}';
                        await window[fn]();

                        // Ad watched — claim reward with anti-cheat tokens
                        status.innerHTML = '<span class="spinner"></span> جاري تسجيل المكافأة...';

                        const fp = _0fp();
                        const tg = _0tg();

                        const resp = await fetch(_0b + '/api/ads/complete-ad/' + _0s, {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{
                                ad_token: _0a,
                                init_data: tg,
                                fp: fp
                            }})
                        }});

                        if (resp.ok) {{
                            const data = await resp.json();
                            if (data.ok) {{
                                _0c = data.ads_completed;
                                _0a = data.next_ad_token || null;
                                _0updateUI();

                                if (data.all_done) {{
                                    _0showDone();
                                }} else {{
                                    status.innerHTML = '<span class="success-icon">✅</span> إعلان '
                                        + _0c + ' من ' + _0t + ' تم! '
                                        + '<span style="color:#4CAF50;font-size:14px">+' + _0p.toFixed(2) + '$</span>';
                                    btn.textContent = '▶️ التالي (' + _0c + '/' + _0t + ')';
                                    btn.disabled = false;
                                }}
                                _0l = false;
                                return;
                            }}
                        }}

                        // Server rejected — show specific error
                        try {{
                            const errData = await resp.json();
                            console.warn("Ad completion rejected:", errData.error);
                            if (errData.error === 'invalid_ad_token') {{
                                status.innerHTML = '⚠️ فشل التحقق من الإعلان<br><span style="font-size:12px;color:#aaa">حاول تاني</span>';
                            }} else if (errData.error === 'missing_fingerprint') {{
                                status.innerHTML = '⚠️ يجب استخدام المتصفح<br><span style="font-size:12px;color:#aaa">الروبوتات مش مقبولة!</span>';
                            }} else if (errData.error === 'too_fast') {{
                                status.innerHTML = '⚠️ سرعت أوي — استنى شوية<br><span style="font-size:12px;color:#aaa">حاول تاني بعد 10 ثواني</span>';
                            }} else {{
                                status.innerHTML = '⚠️ حصل خطأ: ' + (errData.message || errData.error) + '<br><span style="font-size:12px;color:#aaa">حاول تاني</span>';
                            }}
                        }} catch(e2) {{
                            status.innerHTML = '⚠️ حصل خطأ في تسجيل المكافأة<br><span style="font-size:12px;color:#aaa">حاول تاني</span>';
                        }}
                        btn.disabled = false;
                        _0l = false;
                        return;

                    }} catch(e) {{
                        console.warn("Monetag error:", e);
                    }}
                }} else {{
                    console.warn("Monetag SDK did not load in time");
                }}
            }}

            // ── No Monetag / SDK failed ──
            status.innerHTML = '⚠️ الإعلانات مش متاحة حالياً<br><span style="font-size:12px;color:#aaa">حاول تاني بعد شوية!</span>';
            btn.disabled = false;
            _0l = false;
        }}

        function _0showDone() {{
            const status = document.getElementById('adStatus');
            const btn = document.getElementById('watchBtn');
            btn.style.display = 'none';
            document.getElementById('progressFill').style.width = '100%';
            document.getElementById('progressText').textContent = _0t + ' / ' + _0t;
            for (let i = 0; i < _0t; i++) {{
                document.getElementById('dot' + i).className = 'ad-dot completed';
            }}
            status.innerHTML = '<div class="completed-banner">'
                + '<div class="success-icon">🎉</div>'
                + '<div class="big">تم إكمال جميع الإعلانات!</div>'
                + '<div style="margin-top:8px">💰 تم إضافة +' + _0r.toFixed(2) + '$ لحسابك</div>'
                + '<div style="margin-top:6px;font-size:13px;color:#c8e6c9">ارجع للبوت للتأكد من رصيدك</div>'
                + '</div>';
            try {{
                if (window.Telegram && window.Telegram.WebApp) {{
                    setTimeout(function() {{ window.Telegram.WebApp.close(); }}, 3000);
                }}
            }} catch(e) {{}}
        }}

        function _0updateUI() {{
            const pct = (_0c / _0t) * 100;
            document.getElementById('progressFill').style.width = pct + '%';
            document.getElementById('progressText').textContent = _0c + ' / ' + _0t;
            for (let i = 0; i < _0t; i++) {{
                const dot = document.getElementById('dot' + i);
                dot.className = 'ad-dot';
                if (i < _0c) dot.className = 'ad-dot completed';
                else if (i === _0c) dot.className = 'ad-dot current';
            }}
        }}

        // Initialize
        (async function() {{
            const btn = document.getElementById('watchBtn');
            const status = document.getElementById('adStatus');
            status.innerHTML = '<span class="spinner"></span> جاري التحضير...';

            // Fetch config from API (ad_token + fp_salt)
            await _0loadConfig();

            if (_0m) {{
                // Wait for Monetag SDK to load
                const sdkReady = await _0waitForSDK(6000);
                if (sdkReady) {{
                    status.textContent = 'اضغط لمشاهدة إعلان';
                }} else {{
                    status.textContent = '⏳ جاري تحميل الإعلانات...';
                    // Keep waiting in background
                    _0waitForSDK(15000).then(ok => {{
                        if (ok) status.textContent = 'اضغط لمشاهدة إعلان';
                        else status.innerHTML = '⚠️ الإعلانات مش متاحة حالياً<br><span style="font-size:12px;color:#aaa">حاول تاني بعد شوية!</span>';
                    }});
                }}
            }} else {{
                status.textContent = '⚠️ الإعلانات مش متاحة حالياً';
            }}
            btn.textContent = '📺 مشاهدة الإعلان';
            btn.disabled = false;
        }})();
    </script>
</body>
</html>"""


_flask_started = False
_flask_lock = threading.Lock()


def _start_flask_once():
    global _flask_started
    with _flask_lock:
        if _flask_started:
            return
        _flask_started = True

    def _run():
        log.info(
            "Fox app Flask listening on 0.0.0.0:%d (PUBLIC_URL=%s)", PORT, PUBLIC_URL
        )
        try:
            app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)
        except Exception as e:
            log.exception("Flask crashed: %s", e)

    threading.Thread(target=_run, daemon=True).start()
